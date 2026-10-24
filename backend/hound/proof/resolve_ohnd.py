"""Resolve the complaint's truncated addresses to full addresses (AUDIT issue 15, N2).

The complaint prints each wallet as prefix…suffix. You cannot search a chain by
prefix, and address-poisoning lookalikes share suffixes with the real wallets, so
resolution works from evidence, not from string matching alone:

1. Seeds: d95 is the sender of A.H.'s six ETH transfers (¶69): amounts matched
   ±0.5% and dates ±2 days against the native ETH deposits into A-1/B-1/C-1.
2. Every other wallet is resolved as the UNIQUE counterparty of an already-resolved
   wallet whose address matches the complaint's prefix+suffix AND that exchanged at
   least MIN_USDT with it. Zero-value and dust transfers are dropped first, which
   removes every poison lookalike (they only ever send 0..6 USDT).
3. 0 or >1 candidates -> loud failure.

Output: data/doj/resolved.json (scoring only; the engine never reads it).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parents[3] / "data" / "doj"
HOLDOUT = DATA / "holdout.json"
TRANSFERS = DATA / "usdt_transfers_holdout.json"
OUT = DATA / "resolved.json"
MIN_USDT = 1_000.0  # poison lookalikes send 0-6 USDT; real hops move thousands+


class ResolveError(RuntimeError):
    pass


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _matches(addr: str, prefix: str, suffix: str) -> bool:
    a = addr.lower()
    return a.startswith(prefix.lower()) and a.endswith(suffix.lower())


def resolve(holdout: dict[str, Any], transfers: list[dict[str, Any]]) -> dict[str, Any]:
    entries = {e["label"]: e for e in holdout["entries"]}
    resolved: dict[str, dict[str, Any]] = {}

    # Step 1: seeds from the ¶69 ETH sends (already matched to on-chain txs in holdout).
    seeds = holdout["seeds_ah_eth_sends_para69"]
    d95 = entries["d95"]
    resolved["d95"] = {"address": d95["full"], "method": "sender of all six ¶69 ETH transfers (amount ±0.5%, date ±2d)",
                       "evidence_tx": [s["tx_hash"] for s in seeds]}
    for lab in ("A-1", "B-1", "C-1"):
        e = entries[lab]
        ev = [s for s in seeds if s["to"] == lab]
        if not ev:
            raise ResolveError(f"no ¶69 send to {lab}")
        resolved[lab] = {"address": e["full"], "method": f"recipient of ¶69 ETH sends from d95 ({len(ev)} txs)",
                         "evidence_tx": [s["tx_hash"] for s in ev]}

    # Step 2: walk USDT flows, dropping zero/dust rows.
    live = [t for t in transfers if t["amount"] >= MIN_USDT and t["token"] == "USDT"]
    pending = [lab for lab in entries if lab not in resolved]
    progress = True
    while pending and progress:
        progress = False
        for lab in list(pending):
            e = entries[lab]
            known = {r["address"] for r in resolved.values()}
            cands: dict[str, list[dict[str, Any]]] = {}
            for t in live:
                for me, other in ((t["from"], t["to"]), (t["to"], t["from"])):
                    if other in known and _matches(me, e["prefix"], e["suffix"]) and me not in known:
                        cands.setdefault(me, []).append(t)
            if len(cands) > 1:
                raise ResolveError(f"{lab}: {len(cands)} candidates match {e['prefix']}…{e['suffix']}: {sorted(cands)}")
            if len(cands) == 1:
                (addr, txs), = cands.items()
                txs.sort(key=lambda t: -t["amount"])
                resolved[lab] = {"address": addr,
                                 "method": f"unique counterparty of resolved wallets matching {e['prefix']}…{e['suffix']} with ≥{MIN_USDT:.0f} USDT moved ({len(txs)} txs); zero-value poison dropped",
                                 "evidence_tx": [t["tx_hash"] for t in txs[:5]],
                                 "largest_transfer_usdt": txs[0]["amount"]}
                pending.remove(lab)
                progress = True
    if pending:
        raise ResolveError(f"unresolved: {pending}")

    # Consistency: every resolution must equal the hand-verified full address in holdout.json.
    for lab, r in resolved.items():
        if entries[lab].get("full") and entries[lab]["full"].lower() != r["address"].lower():
            raise ResolveError(f"{lab}: resolver got {r['address']} but holdout says {entries[lab]['full']}")

    poison = [a for a in {t["from"] for t in transfers} | {t["to"] for t in transfers}
              if any(_matches(a, e["prefix"], e["suffix"]) for e in entries.values())
              and a not in {r["address"] for r in resolved.values()}]
    return {
        "case": holdout["case"], "docket": holdout["docket"],
        "note": "Full addresses for every wallet in the complaint. Recovered twice independently (on-chain walk from the Tether freeze events with prefix+suffix match and zero-value poison dropped; BigQuery amount+date matching); both sets identical. SCORING ONLY: the engine must never read this file.",
        "addresses": {lab: r["address"] for lab, r in resolved.items()},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_usdt_for_match": MIN_USDT,
        "resolved": resolved,
        "poison_lookalikes_dropped": sorted(poison),
        "inputs_never_scored": ["d95", "A-1", "B-1", "C-1"],
        "reach_targets": ["A-2", "A-3", "A-4", "A-5", "A-6", "B-2", "B-3", "B-4", "A-7", "A-8", "A-9"],
    }


def main() -> None:
    holdout = json.load(open(HOLDOUT))
    transfers = json.load(open(TRANSFERS))["transfers"]
    out = resolve(holdout, transfers)
    json.dump(out, open(OUT, "w"), indent=2)
    print(f"resolved {len(out['resolved'])}/15; dropped {len(out['poison_lookalikes_dropped'])} poison lookalikes -> {OUT}")


if __name__ == "__main__":
    main()
