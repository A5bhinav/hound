"""Trace engine (Ishaan). Deterministic, no LLM decides anything (BRIEF 4.3, AUDIT issues 3, 7, 8).

Loop: fetch transfers for the frontier → one global FIFO replay over everything fetched →
expand to addresses that received at least `min_amount` of victim money → repeat until
nothing new, a cap, the call budget, the deadline, or `max_hops`.

Every cap is visible: money that isn't followed ends at a `capped` or `dust` endpoint,
and unexpanded frontier ends at `max_hops` / `budget` / `time_cap` with status "partial".

Replay mode (case.freeze_visibility == "hidden"): freezes are NOT used as stops, because
that would hand the engine DOJ's own action. They are attached to nodes after the run so
the UI can reveal them. `case.data_cutoff_block` bounds every fetch.

Data comes through injectable functions (BRIEF 8.4):
    get_transfers(chain, address, after=None, as_of=None) -> list[Transfer]
    label(chain, address) -> dict | None
    freeze_status(chain, address) -> dict
    get_balance(chain, address) -> float (whole tokens)
"""
import hashlib
import json
import logging
import time
from datetime import datetime, timezone

from hound.contracts import validate_trace
from hound.engine.fifo import from_base, propagate
from hound.engine.swaps import resolve_eth_seeds
from hound.llm.classify import classify, features

log = logging.getLogger("hound.engine")
ENGINE_VERSION = "0.3"
DEFAULTS = {"max_hops": 8, "max_branches_per_node": 12, "min_amount": 100.0, "max_api_calls": 400, "deadline_s": 120}
EXCHANGE_KINDS = {"exchange_hot", "exchange_deposit"}
CONSOLIDATION_SENDERS = 3
# Edge confidence = base(method) x completeness. Path confidence = product along the path.
CONFIDENCE_MODEL = {"base": {"direct": 1.0, "consolidation": 0.9, "swap": 0.9, "peel": 0.85, "bridge_match": 0.6},
                    "completeness": {"complete": 1.0, "incomplete": 0.5}}
NO_FREEZE = {"is_frozen": False, "frozen_at": None, "freeze_tx": None}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _chain_defaults():
    try:
        from hound import chain  # Jinka's adapters; exports the BRIEF 8.4 functions
        deps = {k: getattr(chain, k) for k in ("get_transfers", "label", "freeze_status", "get_balance")}
        deps["get_native_txs"] = getattr(chain, "get_native_txs", None)
        return deps
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


def run_trace(case, get_transfers=None, label=None, freeze_status=None, get_balance=None, get_native_txs=None, **method):
    started = time.monotonic()
    if get_transfers is None:
        deps = _chain_defaults()
        get_transfers = deps["get_transfers"]
        label = label or deps["label"]
        freeze_status = freeze_status or deps["freeze_status"]
        get_balance = get_balance or deps["get_balance"]
        get_native_txs = get_native_txs or deps.get("get_native_txs")
    label = label or (lambda c, a: None)
    freeze_status = freeze_status or (lambda c, a: NO_FREEZE)
    m = {**DEFAULTS, **method}
    min_base = int(m["min_amount"] * 10 ** 6)
    audit = Audit()
    stats = {"api_calls": 0, "cache_hits": 0, "empty_results": 0}
    hidden = case.get("freeze_visibility") == "hidden"
    cutoff = case.get("data_cutoff_block")

    sends = case["sends"]
    chains = {s["chain"] for s in sends}
    if len(chains) != 1:
        raise ValueError(f"a case must start on one chain for now, got {sorted(chains)}")
    chain = chains.pop()
    seed_list = [{"seed_id": f"s{i + 1}", "tx_hash": s["tx_hash"], "token": s["token"], "amount": s["amount"]}
                 for i, s in enumerate(sends)]
    seeds = {(s["tx_hash"], s["to"]): seed_list[i]["seed_id"] for i, s in enumerate(sends) if s["token"] != "ETH"}
    start_time = min(s["time"] for s in sends)
    victims = {s["from"] for s in sends}
    if hidden:
        audit("freeze_check", f"replay mode: freezes hidden from the engine, cutoff block {cutoff}")
    swaps = None
    eth_sends = [dict(s, seed_id=seed_list[i]["seed_id"]) for i, s in enumerate(sends) if s["token"] == "ETH"]
    if eth_sends:
        if get_native_txs is None:
            raise RuntimeError("case has ETH sends but no get_native_txs adapter was provided (AUDIT issue 1)")
        native, usdt_legs = [], []
        for x in sorted({s["to"] for s in eth_sends}):
            native += get_native_txs(chain, x, after=None, as_of=cutoff)
            usdt_legs += get_transfers(chain, x, after=None, as_of=cutoff)
            stats["api_calls"] += 2
        swaps = resolve_eth_seeds(eth_sends, native, usdt_legs)
        seeds.update(swaps["seeds"])
        audit("hop", f"{len(swaps['swaps'])} same-tx ETH to USDT swaps resolved, {len(swaps['unresolved'])} unresolved")
        for u in swaps["unresolved"]:
            audit("stop", f"swap_unresolved: ETH out in {u['tx_hash']} has no USDT leg in the same tx", u["address"])
    depth = {s["to"]: 1 for s in sends}
    for v in victims:
        depth.setdefault(v, 0)
    explored, stopped, labels, classes = set(), {}, {}, {}
    leftovers = []   # (address, reason, {seed: base}) for capped / dust money
    transfers = {}
    frontier = sorted({s["to"] for s in sends} | ({k[1] for k in swaps["seeds"]} if swaps else set()))
    for k in (swaps["seeds"] if swaps else {}):
        depth.setdefault(k[1], 1)
    result, status = None, "done"

    for hop in range(1, m["max_hops"] + 1):
        new = []
        for addr in frontier:
            if stats["api_calls"] >= m["max_api_calls"] or time.monotonic() - started > m["deadline_s"]:
                reason = "budget" if stats["api_calls"] >= m["max_api_calls"] else "time_cap"
                stopped.setdefault(addr, reason)
                status = "partial"
                audit("cap_hit", f"{reason}: not expanded", addr)
                continue
            lab = label(chain, addr)
            labels[addr] = lab
            if lab and lab.get("kind") in EXCHANGE_KINDS:
                stopped[addr] = "exchange"
                audit("stop", f"exchange: {lab.get('name')}", addr)
                continue
            if not hidden:
                fz = freeze_status(chain, addr)
                audit("freeze_check", "frozen" if fz.get("is_frozen") else "not frozen", addr)
                if fz.get("is_frozen"):
                    stopped[addr] = "frozen"
                    audit("stop", f"Tether froze this address at {fz.get('frozen_at')}", addr)
            # FIFO needs the FULL history up to the cutoff: money that was already sitting here
            # is older than the victim's lots and must leave first (AUDIT issue 7).
            try:
                rows = get_transfers(chain, addr, after=None, as_of=cutoff)
            except Exception as e:  # noqa: BLE001 - adapters raise their own types
                stats["api_calls"] += 1
                if type(e).__name__ == "TooManyTransfers":
                    stopped[addr] = "high_volume"
                    audit("stop", f"high volume address (exchange or service sized): {e}", addr)
                else:
                    stats["fetch_errors"] = stats.get("fetch_errors", 0) + 1
                    stopped[addr] = "dead_end"
                    status = "partial"
                    audit("error", f"fetch failed after the adapter's retries: {type(e).__name__}: {e}", addr)
                continue
            stats["api_calls"] += 1
            audit("fetch", f"{len(rows)} transfers (full history" + (f" up to block {cutoff})" if cutoff else ")"), addr)
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
                    audit("stop", f"proven sweep into a labelled exchange: {c['kind']}", addr)
                    continue
            for t in rows:
                transfers[(t["tx_hash"], t.get("log_index"), t["from"], t["to"], t["amount"])] = t
            explored.add(addr)
            new.append(addr)

        result = propagate(transfers.values(), explored, seeds)
        next_frontier = []
        for addr in new:
            if stopped.get(addr) == "frozen":
                continue
            outs = sorted(((dst, sum(by.values()), by) for (src, dst), by in result["edge_seed"].items() if src == addr),
                          key=lambda x: (-x[1], x[0]))
            dust = [(d, a, by) for d, a, by in outs if a < min_base and d not in depth]
            kept = [(d, a, by) for d, a, by in outs if a >= min_base or d in depth]
            capped = kept[m["max_branches_per_node"]:]
            kept = kept[: m["max_branches_per_node"]]
            for group, reason in ((dust, "dust"), (capped, "capped")):
                if group:
                    merged = {}
                    for d, a, by in group:
                        for s, v in by.items():
                            merged[s] = merged.get(s, 0) + v
                    leftovers.append((addr, reason, merged))
                    audit("skip_branch" if reason == "dust" else "cap_hit",
                          f"{len(group)} branches, {from_base(sum(merged.values()))} USDT not followed ({reason})", addr)
            for d, a, by in kept:
                audit("hop", f"{from_base(a)} victim USDT to {d}", addr)
                if d not in depth:
                    depth[d] = depth[addr] + 1
                if d not in explored and d not in stopped and d not in next_frontier:
                    next_frontier.append(d)
        if not next_frontier:
            audit("stop", f"no new victim-funded addresses after hop {hop}")
            break
        frontier = sorted(next_frontier)
    else:
        for addr in frontier:
            stopped.setdefault(addr, "max_hops")
            audit("cap_hit", f"max_hops {m['max_hops']} reached", addr)
        status = "partial"

    frozen = {a: (freeze_status(chain, a) or NO_FREEZE) for a in sorted(set(victims) | explored | set(stopped))}
    trace = _build(case, chain, m, result, explored, stopped, labels, frozen, depth, victims, get_balance,
                   classes, seed_list, leftovers, hidden, status)
    if swaps is not None:
        trace["swaps"] = _swap_summary(swaps, eth_sends)
        for s in eth_sends:  # the ETH legs from the victim side, so the graph starts at d95
            trace["edges"].insert(0, {
                "from": s["from"], "to": s["to"], "token": "ETH", "amount": float(s["amount"]),
                "attributed_amount": float(s["amount"]), "attributed_by_seed": {s["seed_id"]: float(s["amount"])},
                "tx_hashes": [s["tx_hash"]], "first_time": s["time"], "last_time": s["time"], "hop": 1,
                "confidence": CONFIDENCE_MODEL["base"]["direct"], "method": "direct"})
    trace["stats"] = {**stats, "elapsed_ms": int((time.monotonic() - started) * 1000)}
    trace["audit_log"] = audit.entries
    return validate_trace(trace)


def _swap_summary(sw, eth_sends):
    eth = lambda w: round(w / 10 ** 18, 9)
    rows = [{"address": r["address"], "tx_hash": r["tx_hash"], "time": r["time"], "recipient": r["recipient"],
             "eth_out": eth(r["eth_out_wei"]), "usdt_in": from_base(r["usdt_in_base"]),
             "victim_eth": {k: eth(v) for k, v in sorted(r["by_seed_wei"].items())},
             "victim_usdt": {k: from_base(v) for k, v in sorted(r["by_seed_usdt_base"].items())}} for r in sw["swaps"]]
    per_seed = {}
    for s in eth_sends:
        sid = s["seed_id"]
        per_seed[sid] = {
            "eth_sent": float(s["amount"]),
            "eth_swapped": eth(sum(r["by_seed_wei"].get(sid, 0) for r in sw["swaps"])),
            "eth_gas": eth(sw["gas"].get(sid, 0)),
            "eth_unresolved": eth(sum(u["by_seed_wei"].get(sid, 0) for u in sw["unresolved"])),
            "usdt_out": from_base(sum(r["by_seed_usdt_base"].get(sid, 0) for r in sw["swaps"])),
        }
    return {"resolved": rows, "unresolved": [{"address": u["address"], "tx_hash": u["tx_hash"],
                                              "eth_out": eth(u["eth_out_wei"])} for u in sw["unresolved"]],
            "per_seed": per_seed}


def _amounts(by_seed):
    return {s: from_base(v) for s, v in sorted(by_seed.items()) if v}


def _build(case, chain, m, result, explored, stopped, labels, frozen, depth, victims, get_balance,
           classes, seed_list, leftovers, hidden, status):
    in_trace = set(victims) | explored | set(stopped)
    senders = {}
    for (src, dst) in result["edge_seed"]:
        if src in in_trace and dst in in_trace:
            senders.setdefault(dst, set()).add(src)
    edges = []
    for (src, dst), by in sorted(result["edge_seed"].items(), key=lambda kv: (depth.get(kv[0][1], 99), kv[0])):
        if src not in in_trace or dst not in in_trace or not by:
            continue
        times = sorted(result["edge_times"][(src, dst)])
        method = "consolidation" if len(senders.get(dst, ())) >= CONSOLIDATION_SENDERS else "direct"
        edges.append({
            "from": src, "to": dst, "token": "USDT",
            "amount": from_base(result["edge_total"][(src, dst)]),
            "attributed_amount": from_base(sum(by.values())),
            "attributed_by_seed": _amounts(by),
            "tx_hashes": result["edge_txs"][(src, dst)],
            "first_time": times[0], "last_time": times[-1],
            "hop": max(1, depth.get(dst, depth.get(src, 0) + 1)),
            "confidence": CONFIDENCE_MODEL["base"][method] * CONFIDENCE_MODEL["completeness"]["complete"],
            "method": method,
        })

    nodes, endpoints = [], []
    for addr in sorted(in_trace, key=lambda a: (depth.get(a, 99), a)):
        lab = labels.get(addr)
        fz = frozen.get(addr) or NO_FREEZE
        remaining = result["remaining"].get(addr, {})
        rem_total = sum(remaining.values())
        if addr in victims:
            kind = "victim"
        elif lab and lab.get("kind") in EXCHANGE_KINDS:
            kind = lab["kind"]
        elif rem_total >= m["min_amount"] * 10 ** 6:
            kind = "holding"
        else:
            kind = "intermediate"
        balance = float(get_balance(chain, addr)) if get_balance and kind == "holding" else None
        nodes.append({
            "address": addr, "chain": chain, "kind": kind,
            "label": lab.get("name") if lab else None,
            "label_source": ("classifier" if lab.get("source") == "classifier" else
                             "exchange_list" if lab.get("kind") in EXCHANGE_KINDS else "ofac") if lab else None,
            "classifier": classes.get(addr), "balance_usdt": balance,
            "frozen": {"is_frozen": bool(fz.get("is_frozen")), "frozen_at": fz.get("frozen_at"), "freeze_tx": fz.get("freeze_tx")},
            "depth": depth.get(addr, 0),
        })
        reason = stopped.get(addr) or ("holding" if kind == "holding" else None)
        if reason:
            frozen_now = bool(fz.get("is_frozen"))
            freezable = (not frozen_now and balance is not None and rem_total > 0
                         and balance * 10 ** 6 >= rem_total)
            endpoints.append({
                "address": addr, "reason": reason,
                "victim_inflow": from_base(sum(result["tainted_in"].get(addr, {}).values())),
                "victim_remaining": from_base(rem_total), "attributed_by_seed": _amounts(remaining),
                "balance_usdt": balance, "freezable": bool(freezable),
                "exchange": lab.get("name") if lab and lab.get("kind") in EXCHANGE_KINDS else None,
            })
    for addr, reason, by in leftovers:
        endpoints.append({"address": addr, "reason": reason, "victim_inflow": from_base(sum(by.values())),
                          "victim_remaining": from_base(sum(by.values())), "attributed_by_seed": _amounts(by),
                          "balance_usdt": None, "freezable": False, "exchange": None})

    params = {"accounting": "FIFO", "max_hops": m["max_hops"], "max_branches_per_node": m["max_branches_per_node"],
              "min_amount": m["min_amount"], "max_api_calls": m["max_api_calls"], "engine_version": ENGINE_VERSION,
              "as_of_block": case.get("data_cutoff_block"), "freeze_visibility": "hidden" if hidden else "visible",
              "confidence_model": CONFIDENCE_MODEL}
    digest = hashlib.sha256(json.dumps([case["case_id"], params, sorted(case["sends"], key=lambda s: s["tx_hash"])],
                                       sort_keys=True).encode()).hexdigest()[:10]
    return {
        "trace_id": f"{case['case_id']}-{digest}", "case_id": case["case_id"], "created_at": _now(),
        "replay": case["source"] == "doj_replay", "status": status, "source": "engine",
        "method": params, "seeds": seed_list,
        "nodes": nodes, "edges": edges, "endpoints": endpoints, "other_payers": [],
    }
