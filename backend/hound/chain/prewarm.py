"""Warm cache/ for every address on the DOJ path and in the demo cases, so the demo works offline.

    cd backend && .venv/bin/python -m hound.chain.prewarm [extra addresses...]

Then run the demo with HOUND_OFFLINE=1 to never touch the network.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time

from . import freeze_events, freeze_status, get_balance, get_transfers, stats
from .cache import REPO_ROOT
from .holdout import BRIEF_FULL
from .net import ChainAPIError, TooManyTransfers

log = logging.getLogger("hound.chain.prewarm")

ETH_ADDR = re.compile(r"0x[0-9a-fA-F]{40}\b")
TRON_ADDR = re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b")
SKIP = {"0xdac17f958d2ee523a2206206994597c13d831ec7"}  # the USDT contract itself


def _addresses_in(obj) -> set[tuple[str, str]]:
    text = json.dumps(obj)
    out = {("ethereum", a.lower()) for a in ETH_ADDR.findall(text)}
    out |= {("tron", a) for a in TRON_ADDR.findall(text)}
    return out


def targets(extra: list[str]) -> list[tuple[str, str]]:
    found: set[tuple[str, str]] = {("ethereum", a) for a in BRIEF_FULL}
    for d in ("data/cases", "examples"):
        for f in sorted((REPO_ROOT / d).glob("*.json")):
            try:
                found |= _addresses_in(json.loads(f.read_text()))
            except ValueError as e:
                log.error("bad json %s: %s", f, e)
    for a in extra:
        found.add(("tron", a) if a.startswith("T") else ("ethereum", a.lower()))
    return sorted(x for x in found if x[1] not in SKIP and not x[1].startswith("0x0000000000"))


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    t0 = time.time()
    for ch in ("ethereum",):
        print(f"{ch}: {len(freeze_events(ch))} USDT freeze events cached")
    failures = 0
    todo = targets(argv)
    for i, (ch, a) in enumerate(todo, 1):
        try:
            n = len(get_transfers(ch, a, token="USDT"))
            bal = get_balance(ch, a)
            fz = freeze_status(ch, a)["is_frozen"]
            print(f"[{i}/{len(todo)}] {ch} {a}: {n} transfers, balance {bal:,.2f}, frozen={fz}")
        except TooManyTransfers:
            print(f"[{i}/{len(todo)}] {ch} {a}: exchange-sized, skipped")
        except (ChainAPIError, ValueError) as e:
            failures += 1
            print(f"[{i}/{len(todo)}] {ch} {a}: FAILED {e}")
    print(f"done in {time.time() - t0:.0f}s, {failures} failures, {stats()}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
