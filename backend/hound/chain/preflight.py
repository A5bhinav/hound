"""Demo-day preflight for the chain side (DEMO.md, Sun 8 AM checklist).

    cd backend
    .venv/bin/python -m hound.chain.preflight          # offline: snapshot + live bundle + /check
    .venv/bin/python -m hound.chain.preflight --live   # also re-check live wallets on chain, with the time

Offline part runs in readonly mode on an empty cache, the way a cold demo laptop with no network
sees it: the DOJ replay must give the scored numbers, every data/cases_live/*.case.json must trace
from the private bundle, and check() must hold the largest frozen final and allow Binance 14. It runs twice, with and
without ETHERSCAN_API_KEY, since the demo laptop may have either.
--live then reads current USDT balance and Tether blacklist status for each live case's endpoints
and first hops ("checked h:mm"). Live addresses are truncated in the output. Exit 1 on any failure.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from .cache import REPO_ROOT

LIVE_DIR = REPO_ROOT / "data" / "cases_live"
REPLAY_CASE = REPO_ROOT / "examples" / "ohnd_replay.case.json"
# money the engine traces into the three wallets Tether froze (the scored finals), on the real
# chain. Matched by amount + freeze reveal: no holdout address appears in engine code.
REPLAY_FINALS = (317403.01, 47702.92, 12077.78)
BINANCE14 = "0x28c6c06298d514db089934071355e5743bf21d60"

failures: list[str] = []


def short(a: str) -> str:
    return f"{a[:8]}…{a[-6:]}" if a and len(a) > 16 else a


def ok(cond: bool, msg: str) -> bool:
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)
    return cond


def offline(keyed: bool) -> None:
    from ..engine.trace import run_trace
    from ..watch.check import check
    from ..watch.other_payers import payments
    from ..watch.watchlist import Watchlist

    print(f"\n[offline, {'with' if keyed else 'without'} an Etherscan key]")
    t0 = time.time()
    trace = run_trace(json.loads(REPLAY_CASE.read_text()))
    ok(trace["status"] == "done", f"DOJ replay traced from the snapshot: {trace['status']} in {time.time() - t0:.1f}s")
    frozen = {n["address"] for n in trace["nodes"] if (n.get("frozen") or {}).get("is_frozen")}
    finals = sorted((e for e in trace["endpoints"] if e["address"] in frozen and e["reason"] == "holding"),
                    key=lambda e: -e["victim_inflow"])
    got = tuple(round(e["victim_inflow"], 2) for e in finals)
    ok(got == REPLAY_FINALS, f"3 frozen finals reached with {', '.join(f'{x:,.2f}' for x in got)} USDT traced in "
                             f"(expect {', '.join(f'{x:,.2f}' for x in REPLAY_FINALS)})")
    if not finals:
        return
    wl = Watchlist()
    wl.add_trace(trace)
    top = finals[0]["address"]
    t1 = time.time()
    r = check("ethereum", top, watch=wl)
    ms = (time.time() - t1) * 1000
    ok(r["decision"] == "hold" and abs(r["evidence"]["victim_inflow_usdt"] - REPLAY_FINALS[0]) < 0.01,
       f"/check largest final: {r['decision']} ({r['evidence']['rule_fired']}), "
       f"{r['evidence']['victim_inflow_usdt']:,.2f} USDT, {ms:.0f} ms")
    r = check("ethereum", BINANCE14, watch=wl)
    ok(r["decision"] == "allow", f"/check Binance 14: {r['decision']} ({r['evidence']['rule_fired']})")

    cases = sorted(LIVE_DIR.glob("*.case.json")) if LIVE_DIR.is_dir() else []
    if not cases:
        print("  note  no data/cases_live/*.case.json on this laptop (AirDrop the folder from Jinka)")
    for f in cases:
        case = json.loads(f.read_text())
        try:
            tr = run_trace(case)
        except Exception as e:  # report every case
            ok(False, f"{case['case_id']}: {type(e).__name__}")
            continue
        top = sorted(tr["endpoints"], key=lambda e: -e.get("victim_inflow", 0))[:3]
        ends = ", ".join(f"{e.get('victim_inflow', 0):,.2f} {e.get('exchange') or e['reason']}" for e in top)
        ok(tr["status"] == "done", f"{case['case_id']} traced from the bundle: {tr['status']}; {ends}")
        try:
            rows = payments(tr)
            ok(True, f"{case['case_id']} other payers: {len(rows)} payment(s)")
        except Exception as e:
            ok(False, f"{case['case_id']} other payers: {type(e).__name__}")


def live() -> None:
    from .. import chain
    from ..engine.trace import run_trace

    print(f"\n[live, checked {time.strftime('%-I:%M %p')}]")
    for f in sorted(LIVE_DIR.glob("*.case.json")):
        case = json.loads(f.read_text())
        os.environ["HOUND_CACHE_MODE"] = "readonly"
        tr = run_trace(case)  # from the bundle: which wallets to look at
        os.environ["HOUND_CACHE_MODE"] = "live"
        addrs = sorted({s["to"] for s in case["sends"]}) + [e["address"] for e in tr["endpoints"]
                                                           if e["reason"] in ("holding", "dust", "unknown")]
        for a in addrs:
            try:
                bal = chain.get_balance("ethereum", a)
                fz = chain.freeze_status("ethereum", a)
                ok(True, f"{case['case_id']} {short(a)}: {bal:,.2f} USDT now, "
                         f"{'FROZEN' if fz['is_frozen'] else 'not frozen'} (on chain: {fz['checked_onchain']})")
            except Exception as e:
                ok(False, f"{case['case_id']} {short(a)}: {type(e).__name__}")


def main(argv: list[str]) -> int:
    meta = json.loads((REPO_ROOT / "data" / "freezes_eth.json").read_text())["_meta"]
    print(f"freeze list: built {meta['built_at']}, head block {meta['head_block']}, {meta['counts']}"
          "  (refresh: python -m hound.chain.freezes dump)")
    key = os.environ.get("ETHERSCAN_API_KEY")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ.update(HOUND_CACHE_DIR=tmp, HOUND_CACHE_MODE="readonly")
        for keyed in (False, True):
            if keyed:
                os.environ["ETHERSCAN_API_KEY"] = key or "preflight-placeholder"  # readonly: never sent
            else:
                os.environ.pop("ETHERSCAN_API_KEY", None)
            offline(keyed)
        if key:
            os.environ["ETHERSCAN_API_KEY"] = key
        else:
            os.environ.pop("ETHERSCAN_API_KEY", None)
        if "--live" in argv:
            live()
    print(f"\n{'ALL GOOD' if not failures else f'{len(failures)} FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.ERROR)
    sys.exit(main(sys.argv[1:]))
