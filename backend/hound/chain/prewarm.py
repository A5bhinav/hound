"""Warm cache/ by running every committed curated Case through the real pipeline, then pack the
committed snapshot (AUDIT issue 10: crawl from the Cases, never from the holdout list).

    cd backend && .venv/bin/python -m hound.chain.prewarm [--no-pack] [--merge] [case.json ...]

By default the crawl runs in an empty cache/warm/ with the snapshot ignored, and the snapshot is
replaced by exactly what it fetched; --merge keeps cache/warm/ and the snapshot and adds to them.
Either way it never crawls or packs the server's cache/ (strangers' lookups land there).

Cases: examples/*.case.json and data/cases/*.json (data/cases_live/ is never crawled: live
addresses must not land in the public snapshot). For each case: run_trace, other payers, and
check() on every node. Runs in HOUND_CACHE_MODE=record unless another mode is set.
Then `python -m hound.chain.snapshot` runs automatically (unless --no-pack).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

from .cache import REPO_ROOT

log = logging.getLogger("hound.chain.prewarm")


def curated_cases(extra: list[str]) -> list[Path]:
    files = sorted((REPO_ROOT / "examples").glob("*.case.json")) + sorted((REPO_ROOT / "data" / "cases").glob("*.json"))
    files += [Path(p) for p in extra]
    return [f for f in files if "cases_live" not in f.parts]


def main(argv: list[str]) -> int:
    os.environ.setdefault("HOUND_CACHE_MODE", "record")
    fresh = "--merge" not in argv
    warm = REPO_ROOT / "cache" / "warm"
    os.environ["HOUND_CACHE_DIR"] = str(warm)
    if fresh:
        # crawl into an empty cache with the snapshot switched off, so the new snapshot holds
        # exactly what the curated cases need
        import shutil
        shutil.rmtree(warm, ignore_errors=True)
        os.environ["HOUND_SNAPSHOT"] = "0"
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    from . import freeze_events, stats
    from ..engine.trace import run_trace
    from ..watch.check import check
    from ..watch.other_payers import payments, summary
    from ..watch.watchlist import Watchlist

    pack = "--no-pack" not in argv
    files = curated_cases([a for a in argv if not a.startswith("--")])
    t0 = time.time()
    print(f"ethereum: {len(freeze_events('ethereum'))} USDT freeze events")
    failures = 0
    for f in files:
        case = json.loads(f.read_text())
        try:
            trace = run_trace(case)
            rows = payments(trace)
            wl = Watchlist()
            wl.add_trace(trace)
            decisions = [check(n["chain"], n["address"], watch=wl)["decision"] for n in trace["nodes"]]
            print(f"{f.name}: status {trace['status']}, {len(trace['nodes'])} nodes, "
                  f"{len(trace['endpoints'])} endpoints, other payers: {summary(rows)['text']}, "
                  f"checks {dict((d, decisions.count(d)) for d in set(decisions))}")
        except Exception as e:  # report every case, then fail
            failures += 1
            print(f"{f.name}: FAILED {type(e).__name__}: {e}")
    print(f"done in {time.time() - t0:.0f}s, {failures} failures, {stats()}")
    if pack and not failures:
        from .snapshot import pack as do_pack
        print("snapshot:", do_pack(merge=not fresh))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
