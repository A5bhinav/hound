"""Build and warm a LIVE gold-case candidate into the local cache only (never the snapshot).

    cd backend
    # from victim tx hashes in a Chainabuse report (optionally keep only sends to the scam address)
    .venv/bin/python -m hound.chain.warm_live --name gold1 --to 0xSCAM 0xTX1 0xTX2 ...
    # or re-warm an existing case file
    .venv/bin/python -m hound.chain.warm_live data/cases_live/gold1.case.json
    # --bundle: crawl into a fresh cache (Etherscan and RPC sources both) and pack it into the
    # private data/cases_live/cache/ so the demo laptop runs the case offline. AirDrop the whole
    # data/cases_live/ folder; never commit it.

Writes data/cases_live/<name>.case.json (gitignored), runs the real trace in
HOUND_CACHE_MODE=record into cache/ (gitignored), prints the ending (holding balances, frozen
or not, exchanges reached), other payers and check() on the first hop and the endpoints, and
records every address it touched in cache/live_addresses.json so snapshot.pack() refuses to
publish them. Live addresses are truncated in everything printed for sharing.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from .cache import REPO_ROOT, cache_dir

LIVE_DIR = REPO_ROOT / "data" / "cases_live"


def short(a: str) -> str:
    return f"{a[:8]}…{a[-6:]}" if a and len(a) > 16 else a


def live_addresses_file() -> Path:
    return cache_dir() / "live_addresses.json"


def remember_live(addresses: set[str]) -> None:
    p = live_addresses_file()
    have = set(json.loads(p.read_text())) if p.exists() else set()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(have | {a.lower() for a in addresses if a})))


def build_case(name: str, tx_hashes: list[str], to: str | None) -> dict:
    from . import tx_sends
    sends = []
    for h in tx_hashes:
        try:
            sends += tx_sends("ethereum", h, to=to)
        except ValueError as e:
            print(f"  skip {h[:12]}…: {e}")
    if not sends:
        raise SystemExit("no usable sends: check the tx hashes / --to address")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {"case_id": f"live-{name}", "created_at": now, "source": "chainabuse",
            "victim": {"alias": "Chainabuse reporter", "age_band": None, "exchange_used": None},
            "story": {"scam_app": None, "platform": None, "first_contact": None,
                      "summary": f"{len(sends)} sends from a public Chainabuse report (reported, not proven)"},
            "sends": sends, "status": "intake", "as_of": now, "freeze_visibility": "visible"}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m hound.chain.warm_live")
    ap.add_argument("items", nargs="+", help="tx hashes, or one existing .case.json")
    ap.add_argument("--name", help="case name (required with tx hashes)")
    ap.add_argument("--to", help="keep only sends to this address (the reported scam address)")
    ap.add_argument("--bundle", action="store_true", help="pack a private offline bundle into data/cases_live/cache/")
    a = ap.parse_args(argv)
    os.environ.setdefault("HOUND_CACHE_MODE", "record")
    if a.bundle:
        import shutil
        warm = REPO_ROOT / "cache" / "live_warm"
        shutil.rmtree(warm, ignore_errors=True)
        os.environ["HOUND_CACHE_DIR"] = str(warm)
        os.environ["HOUND_SNAPSHOT"] = "0"  # a complete crawl: nothing served from snapshots
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    from . import get_balance, stats
    from ..contracts import validate_case
    from ..engine.trace import run_trace
    from ..watch.check import check
    from ..watch.other_payers import payments, summary
    from ..watch.watchlist import Watchlist

    if len(a.items) == 1 and a.items[0].endswith(".json"):
        path = Path(a.items[0])
        case = json.loads(path.read_text())
    else:
        if not a.name:
            ap.error("--name is required with tx hashes")
        case = build_case(a.name, a.items, a.to)
        LIVE_DIR.mkdir(parents=True, exist_ok=True)
        path = LIVE_DIR / f"{a.name}.case.json"
        path.write_text(json.dumps(case, indent=1) + "\n")
    validate_case(case)
    print(f"case {case['case_id']}: {len(case['sends'])} sends, "
          f"{sum(s['amount'] for s in case['sends'] if s['token'] == 'USDT'):,.2f} USDT + "
          f"{sum(s['amount'] for s in case['sends'] if s['token'] == 'ETH'):,.4f} ETH -> saved {path}")

    t0 = time.time()
    if a.bundle and os.environ.get("ETHERSCAN_API_KEY"):
        # warm the RPC path too, so the bundle works on a laptop with or without an Etherscan key
        os.environ["HOUND_ETH_TRANSFER_SOURCES"] = "rpc,blockscout_v2,blockscout"
        tr_rpc = run_trace(case)
        payments(tr_rpc)
        os.environ.pop("HOUND_ETH_TRANSFER_SOURCES")
    trace = run_trace(case)
    remember_live({n["address"] for n in trace["nodes"]} | {s["from"] for s in case["sends"]}
                  | {s["to"] for s in case["sends"]})
    print(f"trace {trace['status']} in {time.time() - t0:.0f}s: {len(trace['nodes'])} nodes, "
          f"{len(trace['endpoints'])} endpoints, {stats()}")
    gold = []
    for e in trace["endpoints"]:
        bal = e.get("balance_usdt")
        if bal is None and e["reason"] in ("holding",):
            bal = get_balance("ethereum", e["address"])
        tag = "GOLD (unfrozen, freezable)" if e["reason"] == "holding" and e.get("freezable") else e["reason"]
        if e["reason"] == "holding" and e.get("freezable"):
            gold.append(e)
        print(f"  endpoint {short(e['address'])}: {tag}, victim inflow {e.get('victim_inflow', 0):,.2f}, "
              f"balance {bal if bal is not None else '-'}, exchange {e.get('exchange')}")
    rows = payments(trace)
    print(f"other payers: {summary(rows)['text']}")
    remember_live({r["from"] for r in rows} | {r["entry_address"] for r in rows})
    wl = Watchlist()
    wl.add_trace(trace)
    first_hops = sorted({s["to"] for s in case["sends"]})
    for addr in first_hops + [e["address"] for e in trace["endpoints"]]:
        r = check("ethereum", addr, watch=wl)
        print(f"  check {short(addr)}: {r['decision']} ({r['evidence']['rule_fired']})")
    print("VERDICT:", "gold ending available" if gold else "no unfrozen holding endpoint: fallback ending")
    if a.bundle:
        from .cache import LIVE_SNAPSHOT_DIR
        from .snapshot import pack
        counts = pack(cache_root=cache_dir(), out_dir=LIVE_SNAPSHOT_DIR, merge=True, allow_live=True)
        print(f"bundle: {counts} -> {LIVE_SNAPSHOT_DIR} (gitignored). AirDrop data/cases_live/ to the demo laptop.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
