"""Trace engine (Ishaan). Deterministic, no LLM in the loop (BRIEF 4.3, 4.4).

Loop: fetch transfers for the frontier → run FIFO over everything fetched →
expand to addresses that received at least `min_amount` of tainted funds →
repeat until nothing new, a cap is hit, or `max_hops`.

Data comes through injectable functions (BRIEF 8.4) so tests run on real fixture
data and production uses Jinka's chain adapters:
    get_transfers(chain, address, after=None) -> list[Transfer]
    label(chain, address) -> dict | None
    freeze_status(chain, address) -> dict
    get_balance(chain, address) -> float
"""
import logging
import time
from datetime import datetime, timezone

from hound.contracts import validate_trace
from hound.engine.fifo import propagate
from hound.llm.classify import classify, features

log = logging.getLogger("hound.engine")

DEFAULTS = {"max_hops": 8, "max_branches_per_node": 12, "min_amount": 100.0}
EXCHANGE_KINDS = {"exchange_hot", "exchange_deposit"}
# A wallet receiving from this many distinct senders in the trace is a consolidation point.
CONSOLIDATION_SENDERS = 3


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _chain_defaults():
    try:
        from hound import chain  # Jinka's adapters; exports the BRIEF 8.4 functions
        return {k: getattr(chain, k) for k in ("get_transfers", "label", "freeze_status", "get_balance")}
    except (ImportError, AttributeError) as e:
        raise RuntimeError(
            "hound.chain adapters are not merged yet (need get_transfers, label, freeze_status, "
            "get_balance in hound/chain/__init__.py). Pass them to run_trace() explicitly."
        ) from e


class Audit:
    def __init__(self):
        self.entries = []

    def __call__(self, step, detail, address=None):
        self.entries.append({"t": _now(), "step": step, "address": address, "detail": detail})
        log.info("%s %s %s", step, address or "", detail)


def run_trace(case, get_transfers=None, label=None, freeze_status=None, get_balance=None, **method):
    started = time.monotonic()
    if get_transfers is None:
        deps = _chain_defaults()
        get_transfers = deps["get_transfers"]
        label = label or deps["label"]
        freeze_status = freeze_status or deps["freeze_status"]
        get_balance = get_balance or deps["get_balance"]
    label = label or (lambda c, a: None)
    freeze_status = freeze_status or (lambda c, a: {"is_frozen": False, "frozen_at": None, "freeze_tx": None})
    m = {**DEFAULTS, **method}
    audit = Audit()
    stats = {"api_calls": 0, "cache_hits": 0, "empty_results": 0}

    sends = case["sends"]
    chains = {s["chain"] for s in sends}
    if len(chains) != 1:
        raise ValueError(f"a case must start on one chain for now, got {sorted(chains)}")
    chain = chains.pop()
    seeds = {(s["tx_hash"], s["to"]) for s in sends}
    start_time = min(s["time"] for s in sends)
    victims = {s["from"] for s in sends}

    depth = {s["to"]: 1 for s in sends}
    for v in victims:
        depth.setdefault(v, 0)
    explored, stopped, labels, frozen, classes = set(), {}, {}, {}, {}
    transfers = {}
    frontier = sorted({s["to"] for s in sends})
    result = None

    for hop in range(1, m["max_hops"] + 1):
        new = []
        for addr in frontier:
            lab = label(chain, addr)
            labels[addr] = lab
            fz = freeze_status(chain, addr)
            frozen[addr] = fz
            audit("freeze_check", "frozen" if fz.get("is_frozen") else "not frozen", addr)
            if lab and lab.get("kind") in EXCHANGE_KINDS:
                stopped[addr] = "exchange"
                audit("stop", f"exchange: {lab.get('name')}", addr)
                continue
            rows = get_transfers(chain, addr, after=start_time)
            stats["api_calls"] += 1
            audit("fetch", f"{len(rows)} transfers since {start_time}", addr)
            if not rows:
                stats["empty_results"] += 1
                audit("empty_result", "no transfers returned; treated as a dead end, check the adapter", addr)
            if rows and addr not in victims:
                feats = features(addr, rows)
                top = feats["top_recipient"]
                c = classify(feats, label(chain, top) if top else None)
                classes[addr] = c
                audit("classify", f"{c['kind']} ({c['confidence']:.2f}): {'; '.join(c['reasons'])}", addr)
                if c["kind"] in EXCHANGE_KINDS and c["confidence"] >= 0.7:
                    labels[addr] = {"name": f"unlabelled {c['kind'].replace('_', ' ')}", "kind": c["kind"], "source": "classifier"}
                    stopped[addr] = "exchange"
                    audit("stop", f"classified as {c['kind']}; deposit addresses belong to the exchange's customers", addr)
                    continue
            for t in rows:
                transfers[(t["tx_hash"], t.get("log_index"), t["from"], t["to"], t["amount"])] = t
            explored.add(addr)
            if fz.get("is_frozen"):
                stopped[addr] = "frozen"
                audit("stop", f"Tether froze this address at {fz.get('frozen_at')}", addr)
            new.append(addr)

        result = propagate(transfers.values(), explored - set(k for k, v in stopped.items() if v == "exchange"), seeds)
        next_frontier = []
        for addr in new:
            if stopped.get(addr) == "frozen":
                continue
            outs = sorted(((dst, amt) for (src, dst), amt in result["edge_taint"].items() if src == addr),
                          key=lambda x: -x[1])
            kept = [(d, a) for d, a in outs if a >= m["min_amount"]]
            for d, a in outs:
                if a < m["min_amount"] and d not in depth:
                    audit("skip_branch", f"dust: {a:.2f} tainted to {d} below min_amount {m['min_amount']}", addr)
            if len(kept) > m["max_branches_per_node"]:
                for d, a in kept[m["max_branches_per_node"]:]:
                    audit("cap_hit", f"max_branches_per_node: skipped {d} ({a:.2f} tainted)", addr)
                kept = kept[: m["max_branches_per_node"]]
            for d, a in kept:
                audit("hop", f"{a:.2f} tainted USDT to {d}", addr)
                if d not in depth:
                    depth[d] = depth[addr] + 1
                if d not in explored and d not in stopped and d not in next_frontier:
                    next_frontier.append(d)
        if not next_frontier:
            audit("stop", f"no new tainted addresses after hop {hop}")
            break
        frontier = sorted(next_frontier)
    else:
        for addr in frontier:
            stopped.setdefault(addr, "max_hops")
            audit("cap_hit", f"max_hops {m['max_hops']} reached", addr)

    trace = _build(case, chain, m, result, explored, stopped, labels, frozen, depth, victims, get_balance, audit, classes)
    trace["stats"] = {**stats, "elapsed_ms": int((time.monotonic() - started) * 1000)}
    trace["audit_log"] = audit.entries
    return validate_trace(trace)


def _build(case, chain, m, result, explored, stopped, labels, frozen, depth, victims, get_balance, audit, classes):
    nodes_in_trace = set(victims) | explored | set(stopped)
    senders = {}
    edges = []
    for (src, dst), taint in result["edge_taint"].items():
        if src not in nodes_in_trace or dst not in nodes_in_trace:
            continue
        senders.setdefault(dst, set()).add(src)
    for (src, dst), taint in sorted(result["edge_taint"].items(), key=lambda kv: (depth.get(kv[0][1], 99), -kv[1])):
        if src not in nodes_in_trace or dst not in nodes_in_trace:
            continue
        times = sorted(result["edge_times"][(src, dst)])
        consolidation = len(senders.get(dst, ())) >= CONSOLIDATION_SENDERS
        total = result["edge_total"][(src, dst)]
        edges.append({
            "from": src, "to": dst, "token": "USDT",
            "amount": round(total, 6), "attributed_amount": round(taint, 6),
            "tx_hashes": result["edge_txs"][(src, dst)],
            "first_time": times[0], "last_time": times[-1],
            "hop": max(1, depth.get(dst, depth.get(src, 0) + 1)),
            # Direct on-chain transfers are certain; FIFO attribution through a
            # consolidation wallet is a modelling choice, so it is marked lower.
            "confidence": 0.8 if consolidation else 0.95,
            "method": "consolidation" if consolidation else "direct",
        })

    nodes, endpoints = [], []
    for addr in sorted(nodes_in_trace, key=lambda a: (depth.get(a, 99), a)):
        lab = labels.get(addr)
        fz = frozen.get(addr) or {"is_frozen": False, "frozen_at": None, "freeze_tx": None}
        remaining = result["remaining_tainted"].get(addr, 0.0)
        if addr in victims:
            kind = "victim"
        elif lab and lab.get("kind") in EXCHANGE_KINDS:
            kind = lab["kind"]
        elif fz.get("is_frozen") or remaining >= m["min_amount"]:
            kind = "holding"
        else:
            kind = "intermediate"
        balance = None
        if get_balance and kind in ("holding",):
            balance = float(get_balance(chain, addr))
        nodes.append({
            "address": addr, "chain": chain, "kind": kind,
            "label": lab.get("name") if lab else None,
            "label_source": ("classifier" if lab.get("source") == "classifier" else
                             "exchange_list" if lab.get("kind") in EXCHANGE_KINDS else "ofac") if lab else None,
            "classifier": classes.get(addr), "balance_usdt": balance,
            "frozen": {"is_frozen": bool(fz.get("is_frozen")), "frozen_at": fz.get("frozen_at"), "freeze_tx": fz.get("freeze_tx")},
            "depth": depth.get(addr, 0),
        })
        reason = stopped.get(addr)
        if reason is None and kind == "holding":
            reason = "holding"
        if reason:
            inflow = result["tainted_in"].get(addr, 0.0)
            freezable = (not fz.get("is_frozen")) and balance is not None and remaining >= m["min_amount"] and balance >= remaining
            endpoints.append({
                "address": addr, "reason": reason, "victim_inflow": round(inflow, 6),
                "balance_usdt": balance, "freezable": bool(freezable),
                "exchange": lab.get("name") if lab and lab.get("kind") in EXCHANGE_KINDS else None,
            })

    return {
        "trace_id": f"{case['case_id']}-{int(time.time())}",
        "case_id": case["case_id"], "created_at": _now(),
        "replay": case["source"] == "doj_replay",
        "method": {"accounting": "FIFO", "max_hops": m["max_hops"],
                   "max_branches_per_node": m["max_branches_per_node"], "min_amount": m["min_amount"]},
        "nodes": nodes, "edges": edges, "endpoints": endpoints, "other_payers": [],
    }
