"""Watchlist: scam-cluster addresses built from traces (+ optional Chainabuse reports).

Rules (brief v3.1 §0 item 9 / AUDIT.md issue 6, no false blocks):
  - exchange-, service- and infrastructure-labelled addresses are never on it
  - victim wallets are never on it
  - HOLD: a trace node with path confidence >= 0.8 and >= 100 USDT of victim money attributed
    (Tether-frozen addresses are held by check() itself)
  - WARN: trace nodes at confidence 0.5-0.8, and anything known only from reports
  - reports alone never hold
  - below 0.5 with no report: allow, with a note
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from .. import chain
from ..chain.cache import REPO_ROOT

log = logging.getLogger("hound.watch.watchlist")

HOLD_MIN_CONFIDENCE = 0.8
WARN_MIN_CONFIDENCE = 0.5
HOLD_MIN_USDT = 100.0
LISTABLE_KINDS = ("intermediate", "holding", "unknown")
DEFAULT_TRACE_DIRS = "examples,data/traces"


def _key(ch: str, address: str) -> tuple[str, str]:
    return ch, address.lower() if ch == "ethereum" else address


class Watchlist:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.entries: dict[tuple[str, str], dict[str, Any]] = {}

    # ------------------------------------------------------------ building

    def add_trace(self, trace: dict) -> int:
        """Add a trace's scam-controlled nodes. Returns how many entries were added or updated."""
        nodes = {n["address"]: n for n in trace.get("nodes", [])}
        victims = {a for a, n in nodes.items() if n.get("kind") == "victim"}
        case_id = trace.get("case_id") or trace.get("trace_id") or "unknown-case"
        added = 0
        with self._lock:
            for addr, n in nodes.items():
                ch = n.get("chain", "ethereum")
                if n.get("kind") not in LISTABLE_KINDS:
                    continue
                lb = chain.label(ch, addr)
                if lb and lb["kind"] != "ofac":
                    continue
                inbound = [e for e in trace.get("edges", []) if e.get("to") == addr]
                direct = [e for e in inbound if e.get("from") in victims]
                conf = max([e.get("confidence", 0.5) for e in inbound], default=0.5)
                e = self.entries.setdefault(_key(ch, addr), {
                    "chain": ch, "address": addr, "cases": set(), "traces": set(), "reports": 0,
                    "direct_hit": False, "confidence": 0.0, "min_depth": None, "victim_inflow": 0.0,
                    "evidence": [],
                })
                e["cases"].add(case_id)
                if trace.get("trace_id"):
                    e["traces"].add(trace["trace_id"])
                e["direct_hit"] = e["direct_hit"] or bool(direct)
                e["confidence"] = max(e["confidence"], conf)
                depth = n.get("depth")
                if depth is not None:
                    e["min_depth"] = depth if e["min_depth"] is None else min(e["min_depth"], depth)
                e["victim_inflow"] += sum(float(x.get("attributed_amount") or 0) for x in inbound)
                for x in inbound[:5]:
                    e["evidence"].append({
                        "case_id": case_id, "trace_id": trace.get("trace_id"), "from": x.get("from"),
                        "hop": x.get("hop"), "amount": x.get("attributed_amount", x.get("amount")),
                        "tx_hashes": (x.get("tx_hashes") or [])[:5], "method": x.get("method"),
                        "confidence": x.get("confidence"),
                    })
                added += 1
        return added

    def add_reports(self, reports: list[dict]) -> int:
        """Chainabuse-style reports: [{"address","chain","report_count","confidence",...}].
        Each report counts once toward the independent-report total; exchanges are still skipped."""
        n = 0
        with self._lock:
            for r in reports:
                ch, addr = r.get("chain", "ethereum"), r["address"]
                lb = chain.label(ch, addr)
                if lb and lb["kind"] != "ofac":
                    continue
                e = self.entries.setdefault(_key(ch, addr), {
                    "chain": ch, "address": addr, "cases": set(), "traces": set(), "reports": 0,
                    "direct_hit": False, "confidence": 0.0, "min_depth": None, "victim_inflow": 0.0,
                    "evidence": [],
                })
                e["reports"] += int(r.get("report_count") or 1)
                e["confidence"] = max(e["confidence"], float(r.get("confidence") or 0.5))
                e["evidence"].append({"source": "chainabuse", "category": r.get("category"),
                                      "reported_at": r.get("reported_at"), "report_count": r.get("report_count")})
                n += 1
        return n

    def load_dir(self, path: Path) -> int:
        n = 0
        for f in sorted(path.glob("*.trace.json")):
            try:
                self.add_trace(json.loads(f.read_text()))
                n += 1
            except (OSError, ValueError, KeyError) as e:
                log.error("bad trace file %s: %s", f, e)
        return n

    # ------------------------------------------------------------ reading

    def lookup(self, ch: str, address: str) -> dict | None:
        e = self.entries.get(_key(ch, address))
        if not e:
            return None
        out = dict(e)
        out["cases"] = sorted(e["cases"])
        out["traces"] = sorted(e["traces"])
        out["independent_reports"] = len(e["cases"]) + e["reports"]
        return out

    def decision(self, entry: dict) -> tuple[str, list[str]]:
        """-> ("hold" | "warn" | "allow", reasons) for a watchlist entry, per the rules above."""
        conf = entry["confidence"]
        traced = bool(entry["cases"])
        inflow = entry["victim_inflow"]
        reasons = []
        if traced:
            n = len(entry["cases"])
            reasons.append(f"part of a scam cluster traced from {n} victim case{'s' if n != 1 else ''}")
            if entry["direct_hit"]:
                reasons.append("a victim paid straight into this address")
        if entry["reports"]:
            reasons.append(f"{entry['reports']} public scam report(s) (reported, not proven)")
        if traced and conf >= HOLD_MIN_CONFIDENCE and inflow >= HOLD_MIN_USDT:
            reasons.append(f"path confidence {conf:.2f}, {inflow:,.2f} USDT of victim money attributed")
            return "hold", reasons
        if not traced:
            reasons.append("known only from reports: reports alone never hold")
            return "warn", reasons
        if conf >= WARN_MIN_CONFIDENCE:
            if inflow < HOLD_MIN_USDT:
                reasons.append(f"only {inflow:,.2f} USDT attributed (hold needs {HOLD_MIN_USDT:.0f}): warning only")
            else:
                reasons.append(f"path confidence {conf:.2f} is below {HOLD_MIN_CONFIDENCE}: warning only, never a hold")
            return "warn", reasons
        reasons.append(f"path confidence {conf:.2f} is below {WARN_MIN_CONFIDENCE}: no action")
        return "allow", reasons

    def __len__(self) -> int:
        return len(self.entries)


_default: Watchlist | None = None
_default_lock = threading.Lock()


def default() -> Watchlist:
    """Process-wide watchlist, loaded from *.trace.json in HOUND_TRACE_DIRS (repo-relative)."""
    global _default
    with _default_lock:
        if _default is None:
            wl = Watchlist()
            for d in os.environ.get("HOUND_TRACE_DIRS", DEFAULT_TRACE_DIRS).split(","):
                p = Path(d.strip())
                p = p if p.is_absolute() else REPO_ROOT / p
                if p.is_dir():
                    wl.load_dir(p)
            log.info("watchlist loaded: %d addresses", len(wl))
            _default = wl
        return _default


def register_trace(trace: dict) -> int:
    """Call after every trace run (api.py) so new clusters are checked immediately."""
    return default().add_trace(trace)


def reset() -> None:
    global _default
    with _default_lock:
        _default = None
