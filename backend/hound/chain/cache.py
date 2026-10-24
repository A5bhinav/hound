"""Disk cache for every chain API response (AUDIT issues 4, 10, N5).

Each raw response is one JSON file under `cache/<namespace>/`, keyed by a hash of the request
parameters with every secret removed. TTL is decided when reading, from the stored value, so
history that can't change is kept forever and anything near the chain head expires.

A committed snapshot (data/fixtures/cache/<namespace>.json.gz) is consulted after the local
cache, so a fresh clone can run the demo with no network. Build it with
    .venv/bin/python -m hound.chain.snapshot

HOUND_CACHE_MODE:
  live          (default) TTLs respected, misses and expired entries fetched and stored
  record        same as live; use while warming the snapshot
  readonly      never touch the network: any cached copy regardless of age, CacheMiss on a miss
                (tests and the frozen demo)
  prefer_cache  any cached copy regardless of age; a miss goes live (demo "try your own")
HOUND_OFFLINE=1 is an alias for readonly. HOUND_CACHE_DIR overrides <repo>/cache.
HOUND_SNAPSHOT=0 ignores the committed snapshot (used while warming it).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("hound.chain.cache")

REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_DIR = REPO_ROOT / "data" / "fixtures" / "cache"
# Private bundle for live cases (gitignored with data/cases_live/): AirDrop the folder to the
# demo laptop. Read after the public snapshot. Built by `warm_live --bundle`.
LIVE_SNAPSHOT_DIR = REPO_ROOT / "data" / "cases_live" / "cache"
MODES = ("live", "record", "readonly", "prefer_cache")

# Empty results are suspicious (the kill test's silent zero), so never kept longer than this.
EMPTY_TTL = 600.0
# Request params that carry credentials; removed before hashing and never stored.
SECRET_PARAMS = {"apikey", "api_key", "apiKey", "key", "access_token"}


class CacheMiss(RuntimeError):
    """Raised in readonly mode when a response was never cached."""


def cache_dir() -> Path:
    return Path(os.environ.get("HOUND_CACHE_DIR") or REPO_ROOT / "cache")


def mode() -> str:
    if os.environ.get("HOUND_OFFLINE", "").lower() in ("1", "true", "yes"):
        return "readonly"
    m = os.environ.get("HOUND_CACHE_MODE", "live").strip().lower() or "live"
    if m not in MODES:
        raise ValueError(f"HOUND_CACHE_MODE={m!r}; expected one of {MODES}")
    return m


def offline() -> bool:
    return mode() == "readonly"


def _secret_values() -> set[str]:
    out = set()
    for k, v in os.environ.items():
        if v and len(v) >= 8 and any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            out.add(v)
    return out


def clean_parts(parts: dict) -> dict:
    """Drop credential params and any value equal to a secret from the environment."""
    secrets = _secret_values()
    return {k: v for k, v in parts.items() if k not in SECRET_PARAMS and not (isinstance(v, str) and v in secrets)}


def key(parts: dict) -> str:
    blob = json.dumps(clean_parts(parts), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:40]


def _path(namespace: str, parts: dict) -> Path:
    h = key(parts)
    return cache_dir() / namespace / h[:2] / f"{h}.json"


@lru_cache(maxsize=32)
def _load_gz(path: str) -> dict[str, dict]:
    p = Path(path)
    if not p.exists():
        return {}
    with gzip.open(p, "rt") as f:
        return json.load(f)


def _snapshot(namespace: str) -> dict[str, dict]:
    return _load_gz(str(SNAPSHOT_DIR / f"{namespace}.json.gz"))


def _live_snapshot(namespace: str) -> dict[str, dict]:
    return _load_gz(str(LIVE_SNAPSHOT_DIR / f"{namespace}.json.gz"))


def read(namespace: str, parts: dict) -> dict | None:
    """Return the stored entry {"saved_at", "value", "empty", "parts"} from the local cache,
    else from the committed snapshot, else None."""
    p = _path(namespace, parts)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError) as e:
            log.warning("corrupt cache file %s (%s); ignoring it", p, e)
    if os.environ.get("HOUND_SNAPSHOT", "1") == "0":
        return None  # warming: the snapshot must not hide what a fresh run fetches
    k = key(parts)
    return _snapshot(namespace).get(k) or _live_snapshot(namespace).get(k)


def write(namespace: str, parts: dict, value: Any, empty: bool = False) -> None:
    p = _path(namespace, parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {"parts": clean_parts(parts), "saved_at": time.time(), "empty": empty, "value": value}
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")  # atomic: never half a file
    with os.fdopen(fd, "w") as f:
        json.dump(entry, f)
    os.replace(tmp, p)


def cached(
    namespace: str,
    parts: dict,
    fetch: Callable[[], Any],
    ttl: float | None | Callable[[Any], float | None],
    is_empty: Callable[[Any], bool] | None = None,
    on_hit: Callable[[], None] | None = None,
) -> Any:
    """Return the cached value for `parts`, or call `fetch()` and store the result.
    ttl: seconds, None = forever, or a function of the value returning either.
    `fetch` must raise on an error response: errors are never cached."""
    m = mode()
    entry = read(namespace, parts)
    if entry is not None:
        value = entry["value"]
        if m in ("readonly", "prefer_cache"):
            if on_hit:
                on_hit()
            return value
        limit = ttl(value) if callable(ttl) else ttl
        if entry.get("empty"):
            limit = EMPTY_TTL if limit is None else min(limit, EMPTY_TTL)
        if limit is None or time.time() - entry["saved_at"] < limit:
            if on_hit:
                on_hit()
            return value
    elif m == "readonly":
        raise CacheMiss(f"HOUND_CACHE_MODE=readonly and nothing cached for {namespace} {clean_parts(parts)}")

    value = fetch()
    write(namespace, parts, value, empty=bool(is_empty and is_empty(value)))
    return value


def reload_snapshot() -> None:
    _load_gz.cache_clear()
