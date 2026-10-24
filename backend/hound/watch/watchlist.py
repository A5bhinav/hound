"""Watchlist: scam-cluster addresses built from traces (+ optional Chainabuse reports).

Rules (brief v3.1 §0 item 9, AUDIT.md issue 13, no false blocks):
  - exchange, service, infrastructure and victim addresses are never on it
  - HOLD  a trace node (entry / intermediate / consolidation / holding) with path confidence
          >= 0.8 and >= 100 USDT of victim money attributed. The case itself is the report.
  - WARN  trace nodes at 0.5-0.8; addresses known only from reports; last victim inflow older
          than 30 days (live cases only; a replay is judged at its own cutoff)
  - ALLOW trace nodes below 0.5 ("no Hound data" for anything not listed)
  - reports alone never hold; Tether-frozen addresses are held by check() itself

The process-wide list loads *.trace.json from HOUND_TRACE_DIRS plus cache/watchlist.json, and
register_trace() rewrites cache/watchlist.json after each trace, so check() is a pure lookup.

Victim money is kept per case: re-running a case replaces its figure, never adds to it, so
rehearsals and page reloads can't inflate a hold (REVIEW_TEAM_R2 ops-2 / engine-r2-01). Only USDT
counts (ETH edges are ETH, not dollars), and each victim send counts at most once per wallet.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from .. import chain
from ..chain.cache import REPO_ROOT, cache_dir
from ..chain.eth import iso, parse_time

log = logging.getLogger("hound.watch.watchlist")

HOLD_MIN_CONFIDENCE = 0.8
WARN_MIN_CONFIDENCE = 0.5
HOLD_MIN_USDT = 100.0
STALE_DAYS = 30
FILE_FORMAT = 2  # cache/watchlist.json; older files summed inflow per run and are ignored
LISTABLE_KINDS = ("entry", "intermediate", "consolidation", "holding", "unknown")
NEVER_LISTED_LABELS = ("exchange_hot", "exchange_deposit", "service", "infra")
NEVER_LISTED_ENDPOINTS = ("high_volume", "exchange", "capped")
DEFAULT_TRACE_DIRS = "examples,data/traces"
MAX_PATH_HOPS = 4


def _key(ch: str, address: str) -> tuple[str, str]:
    return ch, address.lower() if ch == "ethereum" else address


def _new_entry(ch: str, addr: str) -> dict[str, Any]:
    return {"chain": ch, "address": addr, "cases": set(), "traces": set(), "reports": set(),
            "report_latest_at": None, "direct_hit": False, "confidence": 0.0, "min_depth": None,
            "victim_inflow": 0.0, "inflow_by_case": {}, "conf_by_case": {}, "report_confidence": 0.0,
            "last_inflow": None, "replay": False, "path": [], "evidence": []}


def _refresh(e: dict[str, Any]) -> None:
    """Derived figures: victim money = sum over cases (each case counted once, latest run wins);
    confidence = best path confidence over cases and reports."""
    e["victim_inflow"] = sum(e["inflow_by_case"].values())
    e["confidence"] = max([e.get("report_confidence", 0.0), *e["conf_by_case"].values()])


def _seed_caps(trace: dict) -> dict[str, float]:
    """USDT value of each seed (victim send): its USDT amount, or the USDT its ETH swapped into."""
    cap: dict[str, float] = {}
    for s in trace.get("seeds") or []:
        if s.get("token") == "USDT" and s.get("seed_id"):
            cap[s["seed_id"]] = cap.get(s["seed_id"], 0.0) + float(s.get("amount") or 0)
    for row in (trace.get("swaps") or {}).get("resolved") or []:
        for sid, v in (row.get("victim_usdt") or {}).items():
            cap[sid] = cap.get(sid, 0.0) + float(v or 0)
    return cap


def _once(by_seed: dict, cap: dict[str, float]) -> float:
    """Victim money on an edge with each victim dollar counted once: an edge's per-seed figure adds
    up every pass of a laundering loop (A-2 -> ... -> A-6 -> A-2), so it can exceed the send itself."""
    return sum(min(float(v or 0), cap[sid]) if sid in cap else float(v or 0) for sid, v in by_seed.items())


def _victim_usdt_in(trace: dict) -> dict[str, float]:
    """USDT of victim money that reached each address in this trace.

    - USDT edges only. Victim-side ETH edges carry ETH amounts; an ETH entry wallet instead counts
      the USDT its victim ETH swapped into (trace["swaps"]["resolved"][].victim_usdt).
    - Each seed (victim send) counts at most its own USDT value at one wallet, and the total never
      exceeds what the victims sent, so laundering loops (A-6 -> A-2 -> ... -> A-6) can't count the
      same dollar twice."""
    cap = _seed_caps(trace)
    swaps = (trace.get("swaps") or {}).get("resolved") or []
    total = sum(cap.values())
    per: dict[str, dict[str, float]] = {}

    def add(addr, by_seed):
        m = per.setdefault(addr, {})
        for sid, v in by_seed.items():
            m[sid] = m.get(sid, 0.0) + float(v or 0)

    for e in trace.get("edges", []):
        if (e.get("token") or "USDT") == "USDT":
            add(e.get("to"), e.get("attributed_by_seed") or {"": e.get("attributed_amount") or 0})
    for row in swaps:
        add(row.get("recipient") or row.get("address"), row.get("victim_usdt") or {})
    out = {}
    for addr, m in per.items():
        amt = _once(m, cap)
        out[addr] = min(amt, total) if total else amt
    return out


def _deposit_sweepers(trace: dict, nodes: dict[str, dict]) -> set[str]:
    """Nodes whose every outflow goes to a labelled exchange hot wallet: an exchange deposit address
    sweeping into its exchange (AUDIT: a proven sweep into a labelled hot wallet is the exchange stop).
    Exchange-owned, so never listed. Seen live: a Coinbase deposit address that got 96,028.85 USDT
    and swept all of it to Coinbase 10 four minutes later."""
    hot = {a for a, n in nodes.items() if n.get("kind") == "exchange_hot"}
    outs: dict[str, list[dict]] = {}
    for e in trace.get("edges", []):
        outs.setdefault(e.get("from"), []).append(e)
    return {a for a, es in outs.items() if es and hot and all(e.get("to") in hot for e in es)
            and len({e.get("to") for e in es}) == 1}


def _is_contract(ch: str, addr: str) -> bool:
    try:
        return chain.is_contract(ch, addr)
    except (chain.ChainAPIError, chain.CacheMiss) as e:
        log.info("is_contract unknown for %s (%s); listing it", addr, type(e).__name__)
        return False


def _path_to(trace: dict, addr: str, victims: set[str]) -> list[dict]:
    """How victim money reached `addr`: the shortest chain of trace edges from a victim (<= 4 hops),
    preferring larger attributed amounts. Falls back to the largest inflows when no victim is
    within 4 hops."""
    by_to: dict[str, list[dict]] = {}
    for e in trace.get("edges", []):
        by_to.setdefault(e.get("to"), []).append(e)
    amt = lambda e: float(e.get("attributed_amount") or e.get("amount") or 0)
    cap = _seed_caps(trace)

    def hop_amount(e):
        by_seed = e.get("attributed_by_seed")
        if (e.get("token") or "USDT") == "USDT" and by_seed and cap:
            return round(_once(by_seed, cap), 6)  # never more victim money than the victims sent
        return e.get("attributed_amount", e.get("amount"))

    def hop(e):
        shown = e.get("attributed_amount", e.get("amount"))  # the figure the trace graph prints on this edge
        a = hop_amount(e)
        capped = a is not None and shown is not None and abs(float(a) - float(shown)) > 0.005
        return {"from": e["from"], "to": e["to"], "amount": a,
                # when they differ, `amount` counts each victim's money once (laundering loops deduped)
                "edge_amount": shown,
                "amount_basis": "victim money counted once" if capped else "edge amount",
                "token": e.get("token") or "USDT",  # victim-side hops are ETH: never print them as USDT
                "tx_hashes": (e.get("tx_hashes") or [])[:2], "confidence": e.get("confidence"),
                "method": e.get("method")}

    frontier: list[tuple[str, list[dict]]] = [(addr, [])]
    seen = {addr}
    for _ in range(MAX_PATH_HOPS):
        nxt = []
        for cur, path in frontier:
            for e in sorted(by_to.get(cur, []), key=lambda x: -amt(x)):
                if e["from"] in victims:
                    return [hop(x) for x in reversed(path + [e])]
                if e["from"] not in seen:
                    seen.add(e["from"])
                    nxt.append((e["from"], path + [e]))
        frontier = nxt
    # no victim within reach: largest inflow chain
    path, cur, seen = [], addr, {addr}
    while len(path) < MAX_PATH_HOPS:
        ins = [e for e in by_to.get(cur, []) if e.get("from") not in seen]
        if not ins:
            break
        e = max(ins, key=amt)
        path.append(e)
        cur = e["from"]
        seen.add(cur)
    return [hop(x) for x in reversed(path)]


class Watchlist:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.entries: dict[tuple[str, str], dict[str, Any]] = {}

    # ------------------------------------------------------------ building

    def add_trace(self, trace: dict) -> int:
        """Add a trace's scam-controlled nodes. Returns how many entries were added or updated."""
        nodes = {n["address"]: n for n in trace.get("nodes", [])}
        victims = {a for a, n in nodes.items() if n.get("kind") == "victim"}
        # busy endpoints are services, never scam wallets: holding them blocks every user
        busy = {e["address"] for e in trace.get("endpoints", []) if e.get("reason") in NEVER_LISTED_ENDPOINTS}
        busy |= _deposit_sweepers(trace, nodes)
        case_id = trace.get("case_id") or trace.get("trace_id") or "unknown-case"
        replay = bool(trace.get("replay"))
        usdt_in = _victim_usdt_in(trace)
        added = 0
        with self._lock:
            for addr, n in nodes.items():
                ch = n.get("chain", "ethereum")
                if n.get("kind") not in LISTABLE_KINDS or addr in victims or addr in busy:
                    continue
                lb = chain.label(ch, addr)
                if lb and lb["kind"] in NEVER_LISTED_LABELS:
                    continue
                if _is_contract(ch, addr):
                    continue  # routers, aggregators, RFQ desks: never held (REVIEW: false holds)
                inbound = [e for e in trace.get("edges", []) if e.get("to") == addr]
                conf = n.get("path_confidence")  # the engine's figure; the BRIEF HOLD rule uses it
                if conf is None:
                    conf = max([e.get("confidence", 0.5) for e in inbound], default=0.5)
                e = self.entries.setdefault(_key(ch, addr), _new_entry(ch, addr))
                e["cases"].add(case_id)
                if trace.get("trace_id"):
                    e["traces"].add(trace["trace_id"])
                e["direct_hit"] = e["direct_hit"] or any(x.get("from") in victims for x in inbound)
                e["replay"] = e["replay"] or replay
                depth = n.get("depth")
                if depth is not None:
                    e["min_depth"] = depth if e["min_depth"] is None else min(e["min_depth"], depth)
                # per case, replaced on every run: re-tracing a case never adds to its figure
                e["inflow_by_case"][case_id] = usdt_in.get(addr, 0.0)
                e["conf_by_case"][case_id] = float(conf)
                _refresh(e)
                times = [x["last_time"] for x in inbound if x.get("last_time")]
                if times:
                    e["last_inflow"] = max([t for t in [e["last_inflow"], *times] if t])
                if not e["path"]:
                    e["path"] = _path_to(trace, addr, victims)
                added += 1
        return added

    def add_reports(self, reports: list[dict]) -> int:
        """Chainabuse-style reports: [{"address","chain","report_count","reported_at","reporter","tx_hash",...}].
        Independent = distinct (reporter, source tx); without those fields each report_count unit counts.
        Exchanges, services and infrastructure are still skipped."""
        n = 0
        with self._lock:
            for r in reports:
                ch, addr = r.get("chain", "ethereum"), r["address"]
                lb = chain.label(ch, addr)
                if lb and lb["kind"] in NEVER_LISTED_LABELS:
                    continue
                e = self.entries.setdefault(_key(ch, addr), _new_entry(ch, addr))
                if r.get("reporter") or r.get("tx_hash"):
                    e["reports"].add(f"{r.get('reporter')}|{r.get('tx_hash')}")
                else:
                    base = len(e["reports"])
                    e["reports"].update(f"anon-{base + i}" for i in range(int(r.get("report_count") or 1)))
                if r.get("reported_at") and (e["report_latest_at"] is None or r["reported_at"] > e["report_latest_at"]):
                    e["report_latest_at"] = r["reported_at"]
                e["report_confidence"] = max(e.get("report_confidence", 0.0), float(r.get("confidence") or 0.5))
                _refresh(e)
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

    # ------------------------------------------------------------ persistence

    def to_json(self) -> dict:
        def enc(e):
            return {**e, "cases": sorted(e["cases"]), "traces": sorted(e["traces"]), "reports": sorted(e["reports"])}
        return {"format": FILE_FORMAT, "version": self.version(), "saved_at": iso(time.time()),
                "entries": [enc(e) for _, e in sorted(self.entries.items())]}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_json()))
        os.replace(tmp, path)

    def load(self, path: Path) -> int:
        if not path.exists():
            return 0
        data = json.loads(path.read_text())
        if data.get("format") != FILE_FORMAT:
            # older files added each run's inflow on top of the last (999K for A-7 after 3 runs)
            log.warning("ignoring %s: old format (inflated per-run inflow); it is rebuilt on the next trace", path)
            return 0
        with self._lock:
            for e in data.get("entries", []):
                cur = self.entries.setdefault(_key(e["chain"], e["address"]), _new_entry(e["chain"], e["address"]))
                for k in ("cases", "traces", "reports"):
                    cur[k] |= set(e.get(k, []))
                for k in ("direct_hit", "replay"):
                    cur[k] = cur[k] or e.get(k, False)
                # the file holds the latest run of each case it saw: it replaces that case's figure
                cur["inflow_by_case"].update(e.get("inflow_by_case") or {})
                cur["conf_by_case"].update(e.get("conf_by_case") or {})
                cur["report_confidence"] = max(cur.get("report_confidence", 0.0), e.get("report_confidence", 0.0))
                _refresh(cur)
                cur["path"] = cur["path"] or e.get("path", [])
                for k in ("last_inflow", "report_latest_at"):
                    vals = [v for v in (cur[k], e.get(k)) if v]
                    cur[k] = max(vals) if vals else None
                if e.get("min_depth") is not None:
                    cur["min_depth"] = e["min_depth"] if cur["min_depth"] is None else min(cur["min_depth"], e["min_depth"])
        return len(data.get("entries", []))

    def version(self) -> str:
        blob = json.dumps(sorted((k, sorted(v["cases"]), len(v["reports"])) for k, v in self.entries.items()))
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    # ------------------------------------------------------------ reading

    def lookup(self, ch: str, address: str) -> dict | None:
        e = self.entries.get(_key(ch, address))
        if not e:
            return None
        out = dict(e)
        out["cases"] = sorted(e["cases"])
        out["traces"] = sorted(e["traces"])
        out["reports"] = len(e["reports"])
        out["independent_reports"] = len(e["cases"]) + len(e["reports"])
        return out

    def decision(self, entry: dict, now: float | None = None) -> tuple[str, str, list[str]]:
        """-> (decision "hold" | "warn" | "allow", rule_fired, reasons) for a watchlist entry."""
        now = time.time() if now is None else now
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
        if not traced:
            reasons.append("known only from reports: reports alone never hold")
            return "warn", "reports_only", reasons
        stale = (not entry.get("replay") and entry.get("last_inflow")
                 and parse_time(entry["last_inflow"]) < now - STALE_DAYS * 86400)
        if conf >= HOLD_MIN_CONFIDENCE and inflow >= HOLD_MIN_USDT and not stale:
            reasons.append(f"path confidence {conf:.2f}, {inflow:,.2f} USDT of victim money attributed")
            return "hold", "trace_node_high_confidence", reasons
        if stale and conf >= WARN_MIN_CONFIDENCE:
            reasons.append(f"last victim inflow {entry['last_inflow']} is older than {STALE_DAYS} days: warning only")
            return "warn", "stale_inflow", reasons
        if conf >= WARN_MIN_CONFIDENCE:
            if inflow < HOLD_MIN_USDT:
                reasons.append(f"only {inflow:,.2f} USDT attributed (hold needs {HOLD_MIN_USDT:.0f}): warning only")
            else:
                reasons.append(f"path confidence {conf:.2f} is below {HOLD_MIN_CONFIDENCE}: warning only, never a hold")
            return "warn", "trace_node_mid_confidence", reasons
        reasons.append(f"path confidence {conf:.2f} is below {WARN_MIN_CONFIDENCE}: no action")
        return "allow", "low_confidence", reasons

    def __len__(self) -> int:
        return len(self.entries)


_default: Watchlist | None = None
_default_lock = threading.Lock()


def watchlist_file() -> Path:
    return cache_dir() / "watchlist.json"


def default() -> Watchlist:
    """Process-wide watchlist: *.trace.json in HOUND_TRACE_DIRS (repo-relative) + cache/watchlist.json."""
    global _default
    with _default_lock:
        if _default is None:
            wl = Watchlist()
            for d in os.environ.get("HOUND_TRACE_DIRS", DEFAULT_TRACE_DIRS).split(","):
                p = Path(d.strip())
                p = p if p.is_absolute() else REPO_ROOT / p
                if p.is_dir():
                    wl.load_dir(p)
            try:
                wl.load(watchlist_file())
            except (OSError, ValueError) as e:
                log.error("could not read %s: %s", watchlist_file(), e)
            log.info("watchlist loaded: %d addresses", len(wl))
            _default = wl
        return _default


def register_trace(trace: dict) -> int:
    """Call after every trace run (api.py): adds the trace and rewrites cache/watchlist.json."""
    wl = default()
    n = wl.add_trace(trace)
    try:
        wl.save(watchlist_file())
    except OSError as e:
        log.error("could not write %s: %s", watchlist_file(), e)
    return n


def reset() -> None:
    """/demo/reset: forget registered traces, including the copy on disk (curated *.trace.json
    files reload from HOUND_TRACE_DIRS on the next default())."""
    global _default
    with _default_lock:
        try:
            watchlist_file().unlink(missing_ok=True)
        except OSError as e:
            log.error("could not delete %s: %s", watchlist_file(), e)
        _default = None
