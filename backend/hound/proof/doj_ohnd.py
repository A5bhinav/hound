"""DOJ answer-key scoreboard, three tiers (BRIEF §0, AUDIT issue 2 / 14 / N2).

Case: US v. 4,340,000 Tether et al., N.D. Ohio 1:25-cv-00386.

Tier 1 REACH   : DOJ wallets the engine was NOT given. Intermediates A-2..A-6, B-2..B-4
                 (x/8) and finals A-7..A-9 (x/3). Inputs d95/A-1/B-1/C-1 never count.
Tier 2 AMOUNT  : A.H.'s ¶74 row only (A-7 314,657 / A-8 11,954 / A-9 43,071 USDT), compared
                 with what the engine attributed to each final. ≤5% green, 5-20% amber, >20% red.
Context only   : ¶¶83-85 totals (38 victims/accounts, mixed LIFO/PIFO/FIFO, subpoena data).

Matching uses FULL addresses from data/doj/resolved.json only. No prefix/suffix regex, so
poison lookalikes can never score. Traces with source "hand_built" are refused. Traces with
fetch errors are marked incomplete instead of scored as misses.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parents[3] / "data" / "doj"
HOLDOUT_PATH = DATA / "holdout.json"
RESOLVED_PATH = DATA / "resolved.json"
CASE_ID = "1:25-cv-00386"
INPUTS = ("d95", "A-1", "B-1", "C-1")
INTERMEDIATES = ("A-2", "A-3", "A-4", "A-5", "A-6", "B-2", "B-3", "B-4")
FINALS = ("A-7", "A-8", "A-9")


def load_holdout(path: Path = HOLDOUT_PATH) -> dict[str, Any]:
    return json.load(open(path))


def load_resolved(path: Path = RESOLVED_PATH) -> dict[str, str]:
    """label -> full lowercase address."""
    r = json.load(open(path))["resolved"]
    return {lab: v["address"].lower() for lab, v in r.items()}


def _trace_addresses(trace: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for n in trace.get("nodes", []):
        if n.get("chain", "ethereum") == "ethereum" and n.get("address"):
            out.add(n["address"].lower())
    for e in trace.get("edges", []):
        for k in ("from", "to"):
            if e.get(k):
                out.add(e[k].lower())
    return out


def _attributed_to(trace: dict[str, Any], address: str) -> float | None:
    """USDT the engine attributes to `address`: endpoint victim_inflow, else summed attributed edge amounts."""
    for ep in trace.get("endpoints", []):
        if ep.get("address", "").lower() == address and ep.get("victim_inflow") is not None:
            return float(ep["victim_inflow"])
    tot = 0.0
    seen = False
    for e in trace.get("edges", []):
        if e.get("to", "").lower() == address and e.get("attributed_amount") is not None:
            tot += float(e["attributed_amount"])
            seen = True
    return tot if seen else None


def _band(ours: float | None, doj: float) -> str:
    if ours is None:
        return "missing"
    err = abs(ours - doj) / doj
    return "green" if err <= 0.05 else "amber" if err <= 0.20 else "red"


def doj_scoreboard(trace: dict[str, Any] | None = None, holdout: dict[str, Any] | None = None,
                   resolved: dict[str, str] | None = None) -> dict[str, Any]:
    h = holdout or load_holdout()
    res = resolved or load_resolved()
    status = "no_trace" if trace is None else "scored"
    refused = None
    if trace is not None and trace.get("source") == "hand_built":
        refused = "trace.source is hand_built: UI fixture, not engine output"
        status = "refused"
    if trace is not None and (trace.get("stats") or {}).get("fetch_errors"):
        status = "incomplete"

    reached_set = _trace_addresses(trace) if (trace is not None and refused is None) else set()
    by_addr = {addr: lab for lab, addr in res.items()}

    def row(lab: str, group: str) -> dict[str, Any]:
        a = res[lab]
        return {"label": lab, "address": a, "group": group, "reached": a in reached_set}

    reach = [row(l, "intermediate") for l in INTERMEDIATES] + [row(l, "final") for l in FINALS]
    inputs = [{"label": l, "address": res[l], "group": "input"} for l in INPUTS]

    ah = h["amount_tier_ah_para74_usdt"]
    amount = []
    for lab in FINALS:
        a = res[lab]
        ours = _attributed_to(trace, a) if (trace is not None and refused is None) else None
        amount.append({"label": lab, "address": a, "doj_ah_para74_usdt": ah[lab], "ours_attributed_usdt": ours,
                       "pct_error": (None if ours is None else round(abs(ours - ah[lab]) / ah[lab] * 100, 1)),
                       "band": _band(ours, ah[lab])})

    # Precision next to recall: every endpoint the engine reached, with amounts, labelled if it is a DOJ wallet.
    endpoints = []
    for ep in (trace or {}).get("endpoints", []) if refused is None else []:
        a = ep.get("address", "").lower()
        endpoints.append({"address": a, "doj_label": by_addr.get(a), "reason": ep.get("reason"),
                          "victim_inflow": ep.get("victim_inflow"), "balance_usdt": ep.get("balance_usdt")})

    finals_h = {e["label"]: e for e in h["entries"] if e["label"] in FINALS}
    context = {"para83_85_totals_usdt": h["context_only_para83_85"],
               "freezes": {l: {"frozen_at": finals_h[l]["frozen_at"], "freeze_tx": finals_h[l]["freeze_tx"]} for l in FINALS},
               "accounting": h["accounting"], "note": "context only, never scored"}

    summary = {
        "status": status,
        "refused_reason": refused,
        "intermediates_reached": sum(r["reached"] for r in reach if r["group"] == "intermediate"),
        "intermediates_total": len(INTERMEDIATES),
        "consolidation_a6_reached": next(r["reached"] for r in reach if r["label"] == "A-6"),
        "finals_reached": sum(r["reached"] for r in reach if r["group"] == "final"),
        "finals_total": len(FINALS),
        "amount_bands": {r["label"]: r["band"] for r in amount},
        "blind": True,
        "start_disclosure": "DOJ printed the start in ¶69, truncated; we resolved it; the engine got nothing else.",
    }
    return {"case": CASE_ID, "docket": h["docket"], "source_pdf": h["source_pdf"],
            "inputs": inputs, "targets": reach, "reached": [r for r in reach if r["reached"]],
            "amount": amount, "totals_vs_doj": amount, "endpoints": endpoints,
            "context": context, "holdout": h["all_holdout_addresses"], "summary": summary}


def assert_holdout_clean(label_addresses: set[str] | list[str], holdout: dict[str, Any] | None = None) -> None:
    """Raise if any complaint address leaked into the label DB."""
    h = holdout or load_holdout()
    leak = {a.lower() for a in label_addresses} & set(h["all_holdout_addresses"])
    if leak:
        raise AssertionError(f"Holdout leak: {sorted(leak)} present in label DB")
