"""Disk cache for every chain API response.

Each raw response is stored as one JSON file under `cache/<namespace>/`, keyed by a
hash of the request parameters (never API keys). TTL is decided when reading, from
the stored value, so "historical, never changes" data is kept forever and "might
still change" data expires.

Env:
  HOUND_CACHE_DIR   where to store files (default: <repo>/cache)
  HOUND_OFFLINE=1   never touch the network: use any cached copy regardless of age,
                    and raise CacheMiss if there is none (for the demo on bad wifi)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("hound.chain.cache")

REPO_ROOT = Path(__file__).resolve().parents[3]

# Empty results are suspicious (the kill test got a silent zero that a retry fixed),
# so they are never kept longer than this, whatever the caller's TTL.
EMPTY_TTL = 3600.0


class CacheMiss(RuntimeError):
    """Raised in offline mode when a response was never cached."""


def cache_dir() -> Path:
    return Path(os.environ.get("HOUND_CACHE_DIR") or REPO_ROOT / "cache")


def offline() -> bool:
    return os.environ.get("HOUND_OFFLINE", "").lower() in ("1", "true", "yes")


def _path(namespace: str, parts: dict) -> Path:
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    h = hashlib.sha256(blob.encode()).hexdigest()[:40]
    return cache_dir() / namespace / h[:2] / f"{h}.json"


def read(namespace: str, parts: dict) -> dict | None:
    """Return the stored entry {"saved_at", "value", "empty", "parts"} or None."""
    p = _path(namespace, parts)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError) as e:
        log.warning("corrupt cache file %s (%s); ignoring it", p, e)
        return None


def write(namespace: str, parts: dict, value: Any, empty: bool = False) -> None:
    p = _path(namespace, parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {"parts": parts, "saved_at": time.time(), "empty": empty, "value": value}
    # atomic write so a crash mid-write never leaves half a file
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
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
    """
    entry = read(namespace, parts)
    if entry is not None:
        value = entry["value"]
        if offline():
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
    elif offline():
        raise CacheMiss(f"HOUND_OFFLINE=1 and nothing cached for {namespace} {parts}")

    value = fetch()
    write(namespace, parts, value, empty=bool(is_empty and is_empty(value)))
    return value
