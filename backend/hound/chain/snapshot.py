"""Pack the local chain cache into the committed snapshot data/fixtures/cache/<namespace>.json.gz.

    cd backend
    HOUND_CACHE_MODE=record .venv/bin/python -m hound.chain.prewarm    # warm from the Cases
    .venv/bin/python -m hound.chain.snapshot                            # pack + secret check

Only chain namespaces are packed (public chain data). The pack fails if any value from a
*KEY / *TOKEN / *SECRET env var appears in it. Freeze the snapshot Sat 10 PM (brief §0).
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

from . import cache

NAMESPACES = ("eth_rpc", "eth_v1", "eth_v2", "tron", "blockscout_meta")
MAX_FILE_MB = 50


def _live_addresses() -> set[str]:
    """Every address from data/cases_live/ and from warm_live runs: never allowed in the snapshot."""
    import re
    out: set[str] = set()
    live_dir = cache.REPO_ROOT / "data" / "cases_live"
    for f in live_dir.glob("*") if live_dir.exists() else []:
        if f.is_file():
            out |= {m.lower() for m in re.findall(r"0x[0-9a-fA-F]{40}", f.read_text(errors="ignore"))}
    for root in {cache.cache_dir(), cache.REPO_ROOT / "cache"}:
        p = root / "live_addresses.json"
        if p.exists():
            out |= set(json.loads(p.read_text()))
    return out


def pack(cache_root: Path | None = None, out_dir: Path | None = None, merge: bool = True) -> dict[str, int]:
    root = cache_root or cache.cache_dir()
    out = out_dir or cache.SNAPSHOT_DIR
    out.mkdir(parents=True, exist_ok=True)
    secrets = cache._secret_values()
    live = _live_addresses()
    counts = {}
    for ns in NAMESPACES:
        merged: dict[str, dict] = dict(cache._snapshot(ns)) if (merge and out == cache.SNAPSHOT_DIR) else {}
        for f in sorted((root / ns).glob("*/*.json")):
            try:
                entry = json.loads(f.read_text())
            except ValueError:
                continue
            merged[f.stem] = entry
        path = out / f"{ns}.json.gz"
        if not merged:
            if not merge and path.exists():
                path.unlink()  # replacing the snapshot: drop namespaces the crawl didn't use
            continue
        blob = json.dumps(merged, sort_keys=True, separators=(",", ":"))
        leaked = [s[:4] + "…" for s in secrets if s in blob]
        if leaked:
            raise RuntimeError(f"snapshot {ns} would contain secret values {leaked}; not written")
        low = blob.lower()
        live_hits = [a[:10] + "…" for a in live if a[2:] in low]
        if live_hits:
            raise RuntimeError(f"snapshot {ns} would publish {len(live_hits)} live-case addresses "
                               f"(e.g. {live_hits[:3]}); live data stays local. Not written.")
        with gzip.open(path, "wt", compresslevel=9) as fh:
            fh.write(blob)
        mb = path.stat().st_size / 1e6
        if mb > MAX_FILE_MB:
            raise RuntimeError(f"{path} is {mb:.1f} MB (> {MAX_FILE_MB} MB)")
        counts[ns] = len(merged)
    cache.reload_snapshot()
    return counts


if __name__ == "__main__":
    print(pack())
    sys.exit(0)
