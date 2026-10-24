"""DOJ answer-key scoreboard for US v. 4,340,000 Tether (N.D. Ohio 1:25-cv-00386).

Compares a Trace (schemas/trace.schema.json) produced by the engine against the
addresses and per-wallet totals in the complaint. The complaint addresses live in
data/doj/holdout.json and must never be in the label DB; `assert_holdout_clean`
is the test hook for that rule.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "doj"
HOLDOUT_PATH = DATA_DIR / "holdout.json"
CASE_ID = "1:25-cv-00386"


def load_holdout(path: Path = HOLDOUT_PATH) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def _addr_set(trace: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for n in trace.get("nodes", []):
        if n.get("chain", "ethereum") == "ethereum" and n.get("address"):
            out.add(n["address"].lower())
    for e in trace.get("edges", []):
        for k in ("from", "to"):
            if e.get(k):
                out.add(e[k].lower())
    return out


def _endpoint_inflow(trace: dict[str, Any], address: str) -> float | None:
    for ep in trace.get("endpoints", []):
        if ep.get("address", "").lower() == address:
            return float(ep.get("victim_inflow") or 0.0)
    return None


def doj_scoreboard(trace: dict[str, Any] | None = None, holdout: dict[str, Any] | None = None) -> dict[str, Any]:
    """Score a Trace against the DOJ complaint.

    Returns the §8.4 shape: case, targets, reached, totals_vs_doj, holdout, plus a
    summary. Partial credit is reported honestly: intermediates reached x/11,
    consolidation (A-6) reached, finals reached x/3.
    """
    h = holdout or load_holdout()
    groups = h["addresses"]
    labelled = [(x["label"], x["address"].lower(), grp) for grp in ("starts", "intermediates", "finals") for x in groups[grp]]
    targets = [{"label": lab, "address": addr, "group": grp} for lab, addr, grp in labelled]

    if trace is None:
        reached_set: set[str] = set()
    else:
        reached_set = _addr_set(trace)

    reached = [t | {"reached": t["address"] in reached_set} for t in targets]
    inter = [t for t in reached if t["group"] == "intermediates"]
    finals = [t for t in reached if t["group"] == "finals"]
    a6 = next((t for t in reached if t["label"] == "A-6"), None)

    totals_vs_doj = []
    for fin in groups["finals"]:
        addr = fin["address"].lower()
        ours = _endpoint_inflow(trace, addr) if trace else None
        doj_total = fin["victim_usdt_traced_total"]
        totals_vs_doj.append({
            "label": fin["label"],
            "address": addr,
            "doj_victim_usdt": doj_total,
            "doj_ah_fifo_usdt": h["ah_fifo_to_finals"].get(fin["label"]),
            "ours_victim_inflow": ours,
            "frozen_at": fin["frozen_at"],
            "freeze_tx": fin["freeze_tx"],
        })

    summary = {
        "intermediates_reached": sum(t["reached"] for t in inter),
        "intermediates_total": len(inter),
        "consolidation_reached": bool(a6 and a6["reached"]),
        "finals_reached": sum(t["reached"] for t in finals),
        "finals_total": len(finals),
        "accounting_note": h["accounting"],
        "blind": True,
    }
    return {
        "case": CASE_ID,
        "docket": h["docket"],
        "source_pdf": h["source_pdf"],
        "targets": targets,
        "reached": reached,
        "totals_vs_doj": totals_vs_doj,
        "holdout": h["all_holdout_addresses"],
        "summary": summary,
    }


def assert_holdout_clean(label_addresses: set[str] | list[str], holdout: dict[str, Any] | None = None) -> None:
    """Raise if any complaint address leaked into the label DB."""
    h = holdout or load_holdout()
    leak = {a.lower() for a in label_addresses} & set(h["all_holdout_addresses"])
    if leak:
        raise AssertionError(f"Holdout leak: {sorted(leak)} present in label DB")
