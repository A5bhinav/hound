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
    freeze_status(chain, address, as_of=None) -> dict   (as_of passed only when a cutoff is set)
    get_balance(chain, address) -> float (whole tokens)  (not called in replay: the cutoff balance
                                                          is computed from the fetched history)
"""
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone

from hound.contracts import validate_trace
from hound.engine.fifo import from_base, propagate, to_base
from hound.engine.swaps import resolve_eth_seeds
from hound.llm.classify import classify, features, rules

log = logging.getLogger("hound.engine")
ENGINE_VERSION = "0.4"
MAX_SENDS = 50  # a victim report with more sends than this is not a real intake; reject it
DEFAULTS = {"max_hops": 8, "max_branches_per_node": 12, "min_amount": 100.0, "max_api_calls": 400, "deadline_s": 120}
EXCHANGE_KINDS = {"exchange_hot", "exchange_deposit"}
CONSOLIDATION_SENDERS = 3
# Edge confidence = base(method) x completeness. Path confidence = product along the path.
CONFIDENCE_MODEL = {"base": {"direct": 1.0, "consolidation": 0.9, "swap": 0.9, "peel": 0.85, "bridge_match": 0.6},
                    "completeness": {"complete": 1.0, "incomplete": 0.5}}
NO_FREEZE = {"is_frozen": False, "frozen_at": None, "freeze_tx": None}


_SECRET = re.compile(r"(?i)(api[_-]?key|apikey|token|key|secret|auth)=([^&\s]+)")


def _redact(text):
    return _SECRET.sub(r"\1=REDACTED", text)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AdaptersMissing(Exception):
    """hound.chain (or one of the adapters a case needs) is not available. Callers may fall back to
    fixture data on this exception alone; every other error is a real failure and must surface."""


def _chain_defaults():
    try:
        from hound import chain  # Jinka's adapters; exports the BRIEF 8.4 functions
        deps = {k: getattr(chain, k) for k in ("get_transfers", "label", "freeze_status", "get_balance")}
    except (ImportError, AttributeError) as e:
        raise AdaptersMissing(
            "hound.chain adapters are not available (need get_transfers, label, freeze_status, "
            "get_balance in hound/chain/__init__.py). Pass them to run_trace() explicitly."
        ) from e
    deps["get_native_txs"] = getattr(chain, "get_native_txs", None)
    return deps


class Audit:
    """Append-only step log. Pass a shared list as `progress` to watch a running trace."""

    def __init__(self, sink=None):
        self.entries = sink if sink is not None else []

    def __call__(self, step, detail, address=None):
        self.entries.append({"t": _now(), "step": step, "address": address, "detail": detail})
        log.info("%s %s %s", step, address or "", detail)


def _norm_sends(sends):
    """Ethereum addresses and hashes are lowercase everywhere downstream (adapters, seed keys).
    A checksummed (EIP-55) address from a screenshot would otherwise match nothing. Tron base58
    is case sensitive and is left alone."""
    out = []
    for s in sends:
        if s.get("token") not in ("USDT", "ETH"):
            raise ValueError(f"send {s.get('tx_hash')}: token {s.get('token')!r} is not supported (USDT or ETH only)")
        if s.get("chain") == "ethereum":
            s = dict(s, tx_hash=s["tx_hash"].lower(), **{"from": s["from"].lower(), "to": s["to"].lower()})
        out.append(s)
    return out


def _row_key(t):
    """Same transfer seen from both ends, possibly from different sources (one with log_index, one
    without): identify it by what every source has."""
    return (t["tx_hash"], t["from"], t["to"], to_base(t))


def run_trace(case, get_transfers=None, label=None, freeze_status=None, get_balance=None, get_native_txs=None,
              progress=None, **method):
    """progress: optional list; audit entries are appended to it live (AUDIT N4 polling)."""
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
    audit = Audit(progress)
    stats = {"api_calls": 0, "cache_hits": 0, "empty_results": 0}
    hidden = case.get("freeze_visibility") == "hidden"
    cutoff = case.get("data_cutoff_block")
    st = {"status": "done"}

    def out_of_time():
        return time.monotonic() - started > m["deadline_s"]

    def safe(what, fn, addr, default):
        """Label / freeze / balance lookups: a failure is an audit error and a partial trace, never a crash."""
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - adapters raise their own types
            log.warning("%s failed for %s: %s: %s", what, addr, type(e).__name__, _redact(str(e)))
            st["status"] = "partial"
            audit("error", f"{what} lookup failed ({type(e).__name__}); treated as unknown", addr)
            return default

    sends = case["sends"]
    if len(sends) > MAX_SENDS:
        raise ValueError(f"case has {len(sends)} sends; the limit is {MAX_SENDS}")
    if set(method) - set(DEFAULTS):
        raise ValueError(f"unknown method params {sorted(set(method) - set(DEFAULTS))}")
    sends = _norm_sends(sends)
    chains = {s["chain"] for s in sends}
    if len(chains) != 1:
        raise ValueError(f"a case must start on one chain for now, got {sorted(chains)}")
    chain = chains.pop()
    seed_list = [{"seed_id": f"s{i + 1}", "tx_hash": s["tx_hash"], "token": s["token"], "amount": s["amount"]}
                 for i, s in enumerate(sends)]
    seeds = {(s["tx_hash"], s["to"]): seed_list[i]["seed_id"] for i, s in enumerate(sends) if s["token"] != "ETH"}
    victims = {s["from"] for s in sends}
    if hidden:
        audit("freeze_check", f"replay mode: freezes hidden from the engine, cutoff block {cutoff}")
    swaps, native = None, []
    eth_sends = [dict(s, seed_id=seed_list[i]["seed_id"]) for i, s in enumerate(sends) if s["token"] == "ETH"]
    if eth_sends:
        if get_native_txs is None:
            raise AdaptersMissing("case has ETH sends but no get_native_txs adapter was provided (AUDIT issue 1)")
        usdt_legs, swap_errors = [], []
        for x in sorted({s["to"] for s in eth_sends}):
            if stats["api_calls"] + 2 > m["max_api_calls"] or out_of_time():
                raise RuntimeError("call budget or deadline exhausted while resolving ETH swaps")
            try:
                native += get_native_txs(chain, x, after=None, as_of=cutoff)
                usdt_legs += get_transfers(chain, x, after=None, as_of=cutoff)
            except Exception as e:  # noqa: BLE001 - adapter types vary (CacheMiss, ChainAPIError...)
                log.warning("swap fetch failed for %s: %s: %s", x, type(e).__name__, _redact(str(e)))
                stats["fetch_errors"] = stats.get("fetch_errors", 0) + 1
                swap_errors.append(x)
                st["status"] = "partial"
                audit("error", f"could not load the swap history ({type(e).__name__}); this branch is incomplete", x)
            stats["api_calls"] += 2
        swaps = resolve_eth_seeds([s for s in eth_sends if s["to"] not in swap_errors], native, usdt_legs)
        seeds.update(swaps["seeds"])
        audit("hop", f"{len(swaps['swaps'])} same-tx ETH to USDT swaps resolved, {len(swaps['unresolved'])} unresolved")
        for u in swaps["unresolved"]:
            audit("stop", f"swap_unresolved: ETH out in {u['tx_hash']} has no USDT leg in the same tx", u["address"])
        seen_native = {(r["tx_hash"], r["to"]) for r in native}
        for s in eth_sends:
            if s["to"] not in swap_errors and (s["tx_hash"], s["to"]) not in seen_native:
                st["status"] = "partial"
                audit("error", f"seed {s['seed_id']} not found on chain: no ETH transfer {s['tx_hash']} into this address",
                      s["to"])
    depth = {s["to"]: 1 for s in sends}
    for v in victims:
        depth.setdefault(v, 0)
    explored, stopped, labels, classes, feats_of = set(), {}, {}, {}, {}
    transfers = {}   # _row_key -> [rows]: the most copies of that key any single fetch returned
    frontier = sorted({s["to"] for s in sends} | ({k[1] for k in swaps["seeds"]} if swaps else set()))
    for k in (swaps["seeds"] if swaps else {}):
        depth.setdefault(k[1], 1)
    result, leftovers, hop_seen = None, [], set()

    for hop in range(1, m["max_hops"] + 1):
        for addr in frontier:
            if stats["api_calls"] >= m["max_api_calls"] or out_of_time():
                reason = "budget" if stats["api_calls"] >= m["max_api_calls"] else "time_cap"
                stopped.setdefault(addr, reason)
                st["status"] = "partial"
                audit("cap_hit", f"{reason}: not expanded", addr)
                continue
            lab = safe("label", lambda: label(chain, addr), addr, None)
            labels[addr] = lab
            if lab and lab.get("kind") in EXCHANGE_KINDS:
                stopped[addr] = "exchange"
                audit("stop", f"exchange: {lab.get('name')}", addr)
                continue
            if not hidden:
                fz = safe("freeze_status", lambda: (freeze_status(chain, addr, as_of=cutoff) if cutoff is not None
                                                    else freeze_status(chain, addr)), addr, NO_FREEZE) or NO_FREEZE
                audit("freeze_check", "frozen" if fz.get("is_frozen") else "not frozen", addr)
                if fz.get("is_frozen"):
                    # Still explored: money that left before the freeze is followed, the rest ends here.
                    stopped[addr] = "frozen"
                    audit("stop", f"Tether froze this address at {fz.get('frozen_at')}", addr)
            # FIFO needs the FULL history up to the cutoff: money that was already sitting here
            # is older than the victim's lots and must leave first (AUDIT issue 7).
            try:
                rows = get_transfers(chain, addr, after=None, as_of=cutoff)
            except Exception as e:  # noqa: BLE001 - adapters raise their own types
                stats["api_calls"] += 1
                # Never put raw exception text in the trace: adapter errors can carry request
                # URLs with API keys. Full detail goes to the server log only, redacted.
                log.warning("fetch failed for %s: %s: %s", addr, type(e).__name__, _redact(str(e)))
                if type(e).__name__ == "TooManyTransfers":
                    stopped[addr] = "high_volume"
                    audit("stop", "high volume address (exchange or service sized)", addr)
                else:
                    stats["fetch_errors"] = stats.get("fetch_errors", 0) + 1
                    stopped[addr] = "dead_end"
                    st["status"] = "partial"
                    audit("error", f"fetch failed after the adapter's retries ({type(e).__name__})", addr)
                continue
            stats["api_calls"] += 1
            audit("fetch", f"{len(rows)} transfers (full history" + (f" up to block {cutoff})" if cutoff else ")"), addr)
            if not rows:
                stats["empty_results"] += 1
                audit("empty_result", "no transfers returned; treated as a dead end, check the adapter", addr)
            no_index = sum(1 for t in rows if t.get("log_index") is None)
            if no_index:
                st["status"] = "partial"
                audit("error", f"{no_index} transfers have no log_index; their order inside a block is a guess", addr)
            if rows and addr not in victims:
                feats = features(addr, rows)
                top = feats["top_recipient"]
                top_lab = safe("label", lambda: label(chain, top), top, None) if top else None
                feats_of[addr] = (feats, top_lab)
                # The stop rests on the deterministic rules only. The one classifier stop is a proven
                # sweep into a LABELLED exchange hot wallet (rules() returns exchange_deposit 0.85).
                c = rules(feats, top_lab)
                audit("classify", f"{c['kind']} ({c['confidence']:.2f}): {'; '.join(c['reasons'])}", addr)
                if c["kind"] in EXCHANGE_KINDS and c["confidence"] >= 0.7 and top_lab \
                        and top_lab.get("kind") in EXCHANGE_KINDS:
                    labels[addr] = {"name": f"unlabelled {c['kind'].replace('_', ' ')}", "kind": c["kind"], "source": "classifier"}
                    stopped[addr] = "exchange"
                    audit("stop", f"proven sweep into a labelled exchange: {c['kind']}", addr)
                    continue
            mine = {}
            for t in rows:
                mine.setdefault(_row_key(t), []).append(t)
            for k, got in mine.items():
                have = transfers.get(k)
                if have is None or len(got) > len(have) or (
                        len(got) == len(have) and sum(t.get("log_index") is not None for t in got)
                        > sum(t.get("log_index") is not None for t in have)):
                    transfers[k] = got
            explored.add(addr)

        result = propagate([t for rows in transfers.values() for t in rows], explored, seeds)
        # Re-check EVERY explored address, not only this hop's: the replay is global, so a node
        # explored later (a cycle, a consolidation) changes the taint on older nodes' outflows.
        next_frontier, leftovers = [], []
        for addr in sorted(explored):
            outs = sorted(((dst, sum(by.values()), by) for (src, dst), by in result["edge_seed"].items()
                           if src == addr and sum(by.values()) > 0), key=lambda x: (-x[1], x[0]))
            known = [o for o in outs if o[0] in depth]
            fresh = [o for o in outs if o[0] not in depth and o[1] >= min_base]
            dust = [o for o in outs if o[0] not in depth and o[1] < min_base]
            room = max(0, m["max_branches_per_node"] - len(known))
            capped, fresh = fresh[room:], fresh[:room]
            for group, reason in ((dust, "dust"), (capped, "capped")):
                if group:
                    merged = {}
                    for d, a, by in group:
                        for sid, v in by.items():
                            merged[sid] = merged.get(sid, 0) + v
                    leftovers.append((addr, reason, len(group), merged))
            for d, a, by in sorted(known + fresh, key=lambda x: (-x[1], x[0])):
                if (addr, d) not in hop_seen:
                    hop_seen.add((addr, d))
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
        st["status"] = "partial"
    for addr, reason, n, merged in leftovers:  # final pass only, so each line appears once
        audit("skip_branch" if reason == "dust" else "cap_hit",
              f"{n} branches, {from_base(sum(merged.values()))} USDT not followed ({reason})", addr)

    seeded = result["seeded"] if result else {}
    for sl in seed_list:
        if sl["token"] != "ETH" and not seeded.get(sl["seed_id"]):
            st["status"] = "partial"
            audit("error", f"seed {sl['seed_id']} not found on chain: no USDT transfer {sl['tx_hash']} into the "
                           "recipient was returned (check the hash, the recipient and the cutoff)")
    if swaps is not None:
        for sid in sorted({s["seed_id"] for s in eth_sends}):
            want = sum(r["by_seed_usdt_base"].get(sid, 0) for r in swaps["swaps"])
            if seeded.get(sid, 0) < want:
                st["status"] = "partial"
                audit("error", f"seed {sid}: only {from_base(seeded.get(sid, 0))} of {from_base(want)} swapped USDT "
                               "was found arriving at the swap recipients")

    for addr in sorted(feats_of):  # display opinion only, after the trace; never a stop
        f, top_lab = feats_of[addr]
        classes[addr] = classify(f, top_lab, use_llm=not out_of_time())

    frozen = {a: safe("freeze_status", lambda: freeze_status(chain, a), a, NO_FREEZE) or NO_FREEZE
              for a in sorted(set(victims) | explored | set(stopped))}

    def balance_of(addr):
        if cutoff is not None:
            # Replay: today's balance would show DOJ's seizure. Use the balance at the cutoff, from
            # the full history already fetched (explored addresses only).
            if addr not in explored:
                return None
            bal = 0
            for rows in transfers.values():
                for t in rows:
                    if t["to"] == addr:
                        bal += to_base(t)
                    if t["from"] == addr:
                        bal -= to_base(t)
            if bal < 0:  # more out than in: the fetched history is incomplete, so the balance is unknown
                log.warning("cutoff balance for %s is negative (%s); history incomplete, balance unknown", addr, bal)
                return None
            return from_base(bal)
        if not get_balance:
            return None
        b = safe("get_balance", lambda: get_balance(chain, addr), addr, None)
        return None if b is None else float(b)

    trace = _build(case, chain, m, result, explored, stopped, labels, frozen, depth, victims, balance_of,
                   classes, seed_list, leftovers, hidden, st["status"])
    if swaps is not None:
        trace["swaps"] = _swap_summary(swaps, eth_sends)
        legs = {}
        for s in eth_sends:  # the ETH legs from the victim side, one edge per (from, to)
            legs.setdefault((s["from"], s["to"]), []).append(s)
        for (src, dst), group in sorted(legs.items(), reverse=True):
            times = sorted(g["time"] for g in group)
            total = round(sum(float(g["amount"]) for g in group), 9)
            by = {}
            for g in group:
                by[g["seed_id"]] = round(by.get(g["seed_id"], 0) + float(g["amount"]), 9)
            trace["edges"].insert(0, {
                "from": src, "to": dst, "token": "ETH", "amount": total, "attributed_amount": total,
                "attributed_by_seed": dict(sorted(by.items())), "tx_hashes": [g["tx_hash"] for g in group],
                "first_time": times[0], "last_time": times[-1], "hop": 1,
                "confidence": CONFIDENCE_MODEL["base"]["direct"], "method": "direct"})
    _path_confidence(trace, victims)
    trace["stats"] = {**stats, "elapsed_ms": int((time.monotonic() - started) * 1000)}
    trace["audit_log"] = list(audit.entries)
    return validate_trace(trace)


def _path_confidence(trace, victims):
    """Node path_confidence = best product of edge confidences along any path from a victim (AUDIT
    issue 8). Victims are 1.0; unreachable nodes 0.0. Max-product relaxation terminates because
    every edge confidence is <= 1."""
    pc = {n["address"]: (1.0 if n["address"] in victims else 0.0) for n in trace["nodes"]}
    for _ in range(len(pc) + 1):
        changed = False
        for e in trace["edges"]:
            v = round(pc.get(e["from"], 0.0) * e["confidence"], 6)
            if e["to"] in pc and v > pc[e["to"]]:
                pc[e["to"]] = v
                changed = True
        if not changed:
            break
    for n in trace["nodes"]:
        n["path_confidence"] = pc[n["address"]]


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


def _label_source(lab):
    if not lab:
        return None
    if lab.get("source") == "classifier":
        return "classifier"
    if lab.get("kind") in EXCHANGE_KINDS:
        return "exchange_list"
    return "ofac" if lab.get("kind") == "ofac" else "service"


def _build(case, chain, m, result, explored, stopped, labels, frozen, depth, victims, balance_of,
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
            # never before both ends are on screen: a back-edge into an early node keeps its late hop
            "hop": max(1, depth.get(src, 0) + 1, depth.get(dst, 0)),
            "confidence": CONFIDENCE_MODEL["base"][method] * CONFIDENCE_MODEL["completeness"]["complete"],
            "method": method,
        })

    # Money sent INTO a stopped address (exchange, high volume, failed fetch, budget) is not
    # replayed further, so count it from the edges; it must never silently become zero.
    edge_in = {}
    for (src, dst), by in result["edge_seed"].items():
        if src in in_trace:
            for sid, v in by.items():
                edge_in.setdefault(dst, {}).setdefault(sid, 0)
                edge_in[dst][sid] += v
    nodes, endpoints = [], []
    for addr in sorted(in_trace, key=lambda a: (depth.get(a, 99), a)):
        lab = labels.get(addr)
        fz = frozen.get(addr) or NO_FREEZE
        if addr in explored:
            remaining = result["remaining"].get(addr, {})
            inflow_by = result["tainted_in"].get(addr, {})
        else:
            remaining = inflow_by = edge_in.get(addr, {})
        rem_total = sum(remaining.values())
        if addr in victims:
            kind = "victim"
        elif lab and lab.get("kind") in EXCHANGE_KINDS:
            kind = lab["kind"]
        elif lab and lab.get("kind") == "service":
            kind = "unknown"  # a router, bridge or processor: not a holder, not sanctioned
        elif rem_total >= m["min_amount"] * 10 ** 6:
            kind = "holding"
        else:
            kind = "intermediate"
        balance = balance_of(addr) if kind == "holding" else None
        nodes.append({
            "address": addr, "chain": chain, "kind": kind,
            "label": lab.get("name") if lab else None,
            "label_source": _label_source(lab),
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
                "victim_inflow": from_base(sum(inflow_by.values())),
                "victim_remaining": from_base(rem_total), "attributed_by_seed": _amounts(remaining),
                "balance_usdt": balance, "freezable": bool(freezable),
                "exchange": lab.get("name") if lab and lab.get("kind") in EXCHANGE_KINDS else None,
            })
    for addr, reason, _n, by in leftovers:
        endpoints.append({"address": addr, "reason": reason, "victim_inflow": from_base(sum(by.values())),
                          "victim_remaining": from_base(sum(by.values())), "attributed_by_seed": _amounts(by),
                          "balance_usdt": None, "freezable": False, "exchange": None})
    endpoints.sort(key=lambda e: (-e["victim_remaining"], e["address"], e["reason"]))  # most victim money first

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
