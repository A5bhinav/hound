"""Pack the local chain cache into the committed snapshot data/fixtures/cache/<namespace>.json.gz.

    cd backend
    .venv/bin/python -m hound.chain.prewarm     # crawl the curated Cases into cache/warm, then pack
    .venv/bin/python -m hound.chain.snapshot    # re-pack cache/warm only

Only chain namespaces are packed (public chain data). The pack fails if any value from a
*KEY / *TOKEN / *SECRET env var appears in it, or any live-case address. It never packs the
server's own cache/: through the tunnel that holds lookups for any address a stranger submits
(REVIEW_TEAM_R2 security-r2-6). Freeze the snapshot Sat 10 PM (brief §0).
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

from . import cache

NAMESPACES = ("eth_rpc", "eth_v1", "eth_v2", "tron", "blockscout_meta")
WARM_DIR = cache.REPO_ROOT / "cache" / "warm"  # prewarm's crawl of the curated Cases
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


def pack(cache_root: Path | None = None, out_dir: Path | None = None, merge: bool = True,
         allow_live: bool = False) -> dict[str, int]:
    """Pack chain namespaces from `cache_root` into `out_dir`. allow_live=True only for the private
    live bundle under data/cases_live/ (gitignored); the public snapshot always refuses live addresses."""
    if allow_live and cache.LIVE_SNAPSHOT_DIR not in [out_dir, *(out_dir.parents if out_dir else [])]:
        raise ValueError("allow_live is only for data/cases_live/cache (never the public snapshot)")
    root = cache_root or cache.cache_dir()
    out = out_dir or cache.SNAPSHOT_DIR
    if not allow_live and root.resolve() == (cache.REPO_ROOT / "cache").resolve():
        raise ValueError("refusing to pack the server cache (cache/): it holds lookups for any address "
                         "submitted to the API. Pack the prewarm crawl: python -m hound.chain.prewarm")
    out.mkdir(parents=True, exist_ok=True)
    secrets = cache._secret_values()
    live = set() if allow_live else _live_addresses()
    counts = {}
    for ns in NAMESPACES:
        base = cache._snapshot(ns) if out == cache.SNAPSHOT_DIR else cache._live_snapshot(ns) if \
            out == cache.LIVE_SNAPSHOT_DIR else {}
        merged: dict[str, dict] = dict(base) if merge else {}
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
    if not WARM_DIR.is_dir():
        sys.exit("no cache/warm crawl: run python -m hound.chain.prewarm (it packs automatically)")
    print(pack(cache_root=WARM_DIR))
    sys.exit(0)
