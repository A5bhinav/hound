"""Shared HTTP client for chain APIs: throttling, retries with back-off on 429/5xx,
loud errors, and call counters that feed Trace.stats."""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Callable

import httpx

log = logging.getLogger("hound.chain")


class ChainAPIError(RuntimeError):
    """A chain API call failed after all retries, or returned an error we can't use."""


class RateLimited(ChainAPIError):
    """The source asked us to wait longer than we're willing to (switch source instead)."""

    def __init__(self, msg: str, wait_s: float):
        super().__init__(msg)
        self.wait_s = wait_s


class TooManyTransfers(ChainAPIError):
    """The address has more transfers than the cap (HOUND_MAX_TRANSFERS): exchange / service-like.
    A fraud trace should stop there rather than download it all."""

    def __init__(self, address: str, seen: int, cap: int):
        super().__init__(f"{address} has more than {seen} transfers (cap HOUND_MAX_TRANSFERS={cap}); "
                         f"treat it as an exchange/service endpoint")
        self.address = address
        self.seen = seen


# Never sleep longer than this for one 429; raise RateLimited so the caller can fall back.
MAX_WAIT_S = 45.0


# Counters for Trace.stats. Call reset_stats() at the start of a trace.
STATS: dict[str, int] = {"api_calls": 0, "cache_hits": 0, "empty_results": 0, "retries": 0, "errors": 0}


def reset_stats() -> None:
    for k in STATS:
        STATS[k] = 0


def stats() -> dict[str, int]:
    return dict(STATS)


def count_cache_hit() -> None:
    STATS["cache_hits"] += 1


def count_empty() -> None:
    STATS["empty_results"] += 1


# Minimum seconds between requests per host (free tiers).
MIN_INTERVAL = {
    "eth.blockscout.com": 0.2,
    "api.etherscan.io": 0.4,  # free key: ~2.5 req/s (AUDIT issue 4 token bucket)
    "api.trongrid.io": 0.12,  # keyed: ~15 req/s
}

_lock = threading.Lock()
_last_call: dict[str, float] = {}
_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=40.0, headers={"user-agent": "hound/0.1 (Cal Hacks 13.0)"})
    return _client


def _throttle(host: str) -> None:
    gap = MIN_INTERVAL.get(host, 0.1)
    with _lock:
        wait = _last_call.get(host, 0.0) + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def safe_url(url: str) -> str:
    """scheme://host only: Alchemy and Infura put the API key in the URL path."""
    try:
        u = httpx.URL(url)
        return f"{u.scheme}://{u.host}"
    except Exception:  # noqa: BLE001 - never let redaction raise
        return "<url>"


def _redact(params: dict | None) -> dict | None:
    if not params:
        return params
    return {k: ("***" if "key" in k.lower() else v) for k, v in params.items()}


def request_json(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json_body: Any = None,
    headers: dict | None = None,
    retries: int = 5,
    retry_reason: Callable[[Any], str | None] | None = None,
) -> Any:
    """GET/POST and parse JSON. Retries on network errors, HTTP 429/5xx, and bodies
    for which `retry_reason(body)` returns a reason (e.g. "Max rate limit reached").
    Raises ChainAPIError when it gives up. Never returns silently on failure."""
    host = httpx.URL(url).host
    last_err = "unknown"
    for attempt in range(retries + 1):
        _throttle(host)
        STATS["api_calls"] += 1
        retry_after: float | None = None
        try:
            r = client().request(method, url, params=params, json=json_body, headers=headers)
        except httpx.TransportError as e:
            last_err = f"{type(e).__name__}: {e}"
        else:
            if r.status_code == 429 or r.status_code >= 500:
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                ra = r.headers.get("retry-after")
                if ra and ra.replace(".", "", 1).isdigit():
                    retry_after = float(ra)
                reset_ms = r.headers.get("x-ratelimit-reset")  # Blockscout: ms until the window resets
                if r.status_code == 429 and reset_ms and reset_ms.isdigit():
                    retry_after = int(reset_ms) / 1000.0 + 0.2
                if retry_after is not None and retry_after > MAX_WAIT_S:
                    STATS["errors"] += 1
                    raise RateLimited(f"{host} rate limit: retry in {retry_after:.0f}s ({method} {safe_url(url)} "
                                      f"params={_redact(params)})", retry_after)
            elif r.status_code >= 400:
                STATS["errors"] += 1
                raise ChainAPIError(
                    f"{method} {safe_url(url)} params={_redact(params)} -> HTTP {r.status_code}: {r.text[:300]}"
                )
            else:
                try:
                    body = r.json()
                except ValueError:
                    last_err = f"non-JSON body: {r.text[:200]}"
                else:
                    reason = retry_reason(body) if retry_reason else None
                    if not reason:
                        return body
                    last_err = reason
        if attempt == retries:
            break
        delay = retry_after if retry_after is not None else min(30.0, 2.0**attempt) + random.random() * 0.5
        STATS["retries"] += 1
        log.warning("retry %d/%d in %.1fs: %s %s params=%s (%s)", attempt + 1, retries, delay, method, safe_url(url),
                    _redact(params), last_err)
        time.sleep(delay)
    STATS["errors"] += 1
    raise ChainAPIError(f"{method} {safe_url(url)} params={_redact(params)} failed after {retries + 1} tries: {last_err}")
