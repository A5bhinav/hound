"""Engine vs the real DOJ case (1:25-cv-00386), blind: no DOJ labels are given to the engine.

Transfers are real Ethereum USDT transfers (BigQuery). Freeze status uses Tether's public
AddedBlackList events, which is the same data Jinka's freezes.py will serve.
"""
from hound.contracts import example
from hound.engine.fifo import _dequeue, propagate
from hound.engine.trace import run_trace

from hound import fixture_chain

TRANSFERS = fixture_chain._all()
A6 = "0x58e99d9413bb6ce05748a84f76e5fff4bb2d0dcb"
FINALS = {
    "0xa1770ead287dc8e91631a7a323390d5b744f0021": "2024-06-21T14:53:11Z",
    "0xafd770d8898a0e323c607fe91358345e7b2378a5": "2024-06-21T14:51:11Z",
    "0x4e5cda8f0d772ac57e947545192a0657ad47abb5": "2024-06-25T17:07:23Z",
}


def run():
    return run_trace(example("ohnd_replay.case"), get_transfers=fixture_chain.get_transfers,
                     label=fixture_chain.label, freeze_status=fixture_chain.freeze_status,
                     get_balance=fixture_chain.get_balance, get_native_txs=fixture_chain.get_native_txs)


A9 = "0xafd770d8898a0e323c607fe91358345e7b2378a5"
A8 = "0x4e5cda8f0d772ac57e947545192a0657ad47abb5"
A7 = "0xa1770ead287dc8e91631a7a323390d5b744f0021"
# DOJ's intermediates, resolved from the complaint; the engine never sees this list.
INTERMEDIATES = {
    "0xcf9bbfa762ef5a84ba3d25350de941a6db485027", "0x78366b2f6c5321ac30629c078120385ae2da1a06",
    "0x9eb0c71e79066552bdd05a69fc4dcac075db5e1f", "0x07fbb418aac62abc4ca3e7ee8ccf8ce7693e9d53",
    "0xdf6fa72c71577c3a3209db202d4815021f0ed53f", A6, "0xe799442b78b502cfa156895099ae26709c2d6ad0",
    "0x212a021291a4a4007bc8892b2176c41204d9c794", "0x447190fc07d5d9d0552077f6942fd3131eb6911a",
    "0x28b877f1c8e6a4bdf0407a6a77eb83346fd17376", "0xa327e6cfdd29022a530950079877861636f4dbb8",
}


def _final_scores(trace):
    """DOJ para 74 counts money traced INTO each final. Money relayed from one final to another
    (A-6 -> A-9 -> A-7) is scored once, at the first final it reaches."""
    score = {a: 0.0 for a in FINALS}
    for e in trace["edges"]:
        if e["token"] == "USDT" and e["to"] in FINALS and e["from"] not in FINALS:
            score[e["to"]] += e["attributed_amount"]
    return score


def test_reaches_doj_seized_wallets_blind():
    # A.H.'s six real ETH sends, freezes hidden, data cut off one block before the last freeze.
    trace = run()
    nodes = {n["address"]: n for n in trace["nodes"]}
    assert INTERMEDIATES <= set(nodes), f"missed intermediates: {INTERMEDIATES - set(nodes)}"
    assert set(FINALS) <= set(nodes), f"missed finals: {set(FINALS) - set(nodes)}"
    score = _final_scores(trace)
    # Bands: green <=5%, amber 5-20%, red >20%.
    assert abs(score[A7] - 314657) / 314657 < 0.05, score[A7]
    assert abs(score[A8] - 11954) / 11954 < 0.05, score[A8]      # ~12,078: A-6's later outflows re-checked
    assert abs(score[A9] - 43071) / 43071 < 0.20, score[A9]
    seeded = sum(p["usdt_out"] for p in trace["swaps"]["per_seed"].values())
    assert sum(score.values()) <= seeded + 1e-6, "finals cannot hold more than the victim sent"
    assert nodes[A7]["frozen"]["is_frozen"], "freeze must be attached for the UI reveal"


def _run_with_result(**kw):
    """run() plus the engine's final FIFO result (spied), for exact accounting."""
    import hound.engine.trace as tr
    seen = []
    real = tr.propagate

    def spy(*a, **k):
        r = real(*a, **k)
        seen.append((r, set(a[1])))
        return r
    tr.propagate = spy
    try:
        trace = run_trace(example("ohnd_replay.case"), **{**dict(
            get_transfers=fixture_chain.get_transfers, label=fixture_chain.label,
            freeze_status=fixture_chain.freeze_status, get_balance=fixture_chain.get_balance,
            get_native_txs=fixture_chain.get_native_txs), **kw})
    finally:
        tr.propagate = real
    return trace, seen[-1][0], seen[-1][1]


def test_eth_seeds_are_conserved():
    for sid, p in run()["swaps"]["per_seed"].items():
        assert abs(p["eth_sent"] - (p["eth_swapped"] + p["eth_gas"] + p["eth_unresolved"])) < 1e-6, (sid, p)
        assert p["usdt_out"] > 0


def test_taint_is_conserved():
    trace = run()
    for e in trace["edges"]:
        assert e["attributed_amount"] <= e["amount"] + 1e-6


def test_conservation_per_seed_is_exact():
    # Every seeded USDT base unit ends somewhere visible: an endpoint (holding, frozen, exchange,
    # dust, capped, max_hops...) or still sitting in a traced intermediate wallet. Nothing leaks.
    trace, result, explored = _run_with_result()
    node_set = {n["address"] for n in trace["nodes"]}
    ends = {e["address"] for e in trace["endpoints"] if e["reason"] not in ("dust", "capped")}
    for sid, p in trace["swaps"]["per_seed"].items():
        at_ends = sum(e["attributed_by_seed"].get(sid, 0) for e in trace["endpoints"])
        residual = sum(result["remaining"].get(a, {}).get(sid, 0) for a in node_set & explored if a not in ends)
        assert abs(at_ends + residual / 1e6 - p["usdt_out"]) < 1e-6, (sid, at_ends, residual / 1e6, p["usdt_out"])


def test_no_victim_money_flows_to_unfollowed_addresses():
    # Outflows to addresses outside the trace must be exactly the dust / capped leftovers.
    trace, result, explored = _run_with_result()
    node_set = {n["address"] for n in trace["nodes"]}
    leak = {}
    for (src, dst), by in result["edge_seed"].items():
        if src in explored and dst not in node_set and sum(by.values()) > 0:
            leak[src] = leak.get(src, 0) + sum(by.values())
    covered = {}
    for e in trace["endpoints"]:
        if e["reason"] in ("dust", "capped"):
            covered[e["address"]] = covered.get(e["address"], 0) + round(sum(e["attributed_by_seed"].values()) * 1e6)
    assert leak == covered, (leak, covered)


def test_leftover_audit_lines_are_not_repeated():
    t = run()
    lines = [(e["step"], e["address"], e["detail"]) for e in t["audit_log"] if e["step"] in ("hop", "skip_branch", "cap_hit")]
    assert len(lines) == len(set(lines))
    hops = [(e["address"], e["detail"].rsplit(" ", 1)[-1]) for e in t["audit_log"] if e["step"] == "hop" and e["address"]]
    assert len(hops) == len(set(hops)), "one hop line per (address, destination)"
    assert len([e for e in t["endpoints"] if e["reason"] in ("dust", "capped")]) == \
        len({(e["address"], e["reason"]) for e in t["endpoints"] if e["reason"] in ("dust", "capped")})


def test_reruns_are_identical():
    def stable(t):
        t = dict(t)
        t.pop("created_at"); t.pop("stats"); t.pop("audit_log")
        return t
    assert stable(run()) == stable(run())


def test_audit_log_records_every_step():
    steps = {e["step"] for e in run()["audit_log"]}
    assert {"fetch", "freeze_check", "hop", "stop", "classify"} <= steps


def test_poison_lookalikes_are_never_nodes():
    # Real zero-value lookalikes of A-6 (0x58e9...0dcb) sent by A-9 (AUDIT N2). Serve the zero-value
    # rows too, so the engine's own filtering is what keeps them out.
    lookalikes = {"0x58e7c560", "0x58e1a9cc"}
    raw = [t for t in TRANSFERS if t["amount"] == 0 and t["to"][:10] in lookalikes]
    assert raw, "fixture should hold the lookalike rows"

    def with_zero(chain, address, after=None, as_of=None):
        return [t for t in TRANSFERS if address in (t["from"], t["to"]) and t["block"] <= as_of]
    t = run_trace(example("ohnd_replay.case"), get_transfers=with_zero, label=fixture_chain.label,
                  freeze_status=fixture_chain.freeze_status, get_native_txs=fixture_chain.get_native_txs)
    seen = {n["address"] for n in t["nodes"]} | {e["to"] for e in t["edges"]} | {e["address"] for e in t["endpoints"]}
    assert A6 in seen
    assert not {a for a in seen if a[:10] in lookalikes}


def test_fifo_takes_oldest_first():
    from collections import deque
    q = deque([[100, None], [50, "s1"]])
    assert _dequeue(q, 100) == [(None, 100)]      # clean lot leaves first
    assert _dequeue(q, 80) == [("s1", 50), (None, 30)]  # then the seed, then pre-window money


def test_cycles_do_not_loop_forever():
    a, b = "0xa", "0xb"
    ts = [{"tx_hash": f"t{i}", "from": x, "to": y, "amount": 10.0, "time": f"2024-01-0{i+1}T00:00:00Z", "block": i}
          for i, (x, y) in enumerate([("0xv", a), (a, b), (b, a), (a, b)])]
    r = propagate(ts, {a, b}, {("t0", a): "s1"})
    assert r["remaining"][b] == {"s1": 10_000_000}


def test_high_volume_and_fetch_errors_are_visible_not_fatal():
    class TooManyTransfers(Exception):
        pass

    def flaky(chain, address, after=None, as_of=None):
        if address == A6:
            raise TooManyTransfers("over 10,000 transfers")
        if address == "0x212a021291a4a4007bc8892b2176c41204d9c794":
            raise ConnectionError("rpc down")
        return fixture_chain.get_transfers(chain, address, after=after, as_of=as_of)

    t = run_trace(example("ohnd_replay.case"), get_transfers=flaky, label=fixture_chain.label,
                  freeze_status=fixture_chain.freeze_status, get_balance=fixture_chain.get_balance,
                  get_native_txs=fixture_chain.get_native_txs)
    reasons = {e["address"]: e["reason"] for e in t["endpoints"]}
    assert reasons[A6] == "high_volume"
    assert reasons["0x212a021291a4a4007bc8892b2176c41204d9c794"] == "dead_end"
    assert t["status"] == "partial" and t["stats"]["fetch_errors"] == 1
    # integrity: the victim money that reached the unfetchable addresses is still accounted for
    ends = {(e["address"], e["reason"]): e for e in t["endpoints"]}
    assert ends[(A6, "high_volume")]["victim_inflow"] > 0
    assert ends[("0x212a021291a4a4007bc8892b2176c41204d9c794", "dead_end")]["victim_inflow"] > 0


def test_input_limits_cannot_bypass_the_call_budget():
    import pytest
    case = example("ohnd_replay.case")
    big = dict(case, sends=case["sends"] * 20)
    with pytest.raises(ValueError, match="limit"):
        run_trace(big, get_transfers=fixture_chain.get_transfers, get_native_txs=fixture_chain.get_native_txs)
    with pytest.raises(ValueError, match="unknown method"):
        run_trace(case, get_transfers=fixture_chain.get_transfers, get_native_txs=fixture_chain.get_native_txs, max_hopz=99)
    # A budget too small for the swap pass is a partial trace with visible caps, never a crash.
    t = run_trace(case, get_transfers=fixture_chain.get_transfers, get_native_txs=fixture_chain.get_native_txs,
                  max_api_calls=3)
    assert t["status"] == "partial" and t["stats"]["api_calls"] <= 3
    assert "budget" in {e["reason"] for e in t["endpoints"]}


def test_adapter_errors_never_leak_into_the_trace():
    def leaky(chain, address, after=None, as_of=None):
        if address == A6:
            raise ConnectionError("GET https://api.etherscan.io/v2/api?apikey=SECRET123&address=x failed")
        return fixture_chain.get_transfers(chain, address, after=after, as_of=as_of)
    t = run_trace(example("ohnd_replay.case"), get_transfers=leaky, label=fixture_chain.label,
                  freeze_status=fixture_chain.freeze_status, get_balance=fixture_chain.get_balance,
                  get_native_txs=fixture_chain.get_native_txs)
    import json as _json
    assert "SECRET123" not in _json.dumps(t) and "etherscan" not in _json.dumps(t)


def test_progress_list_fills_while_tracing():
    live = []
    t = run_trace(example("ohnd_replay.case"), get_transfers=fixture_chain.get_transfers, label=fixture_chain.label,
                  freeze_status=fixture_chain.freeze_status, get_balance=fixture_chain.get_balance,
                  get_native_txs=fixture_chain.get_native_txs, progress=live)
    assert live and live == t["audit_log"]


def test_swap_fetch_failure_is_partial_not_a_crash():
    class CacheMiss(Exception):
        pass
    C1 = "0xa327e6cfdd29022a530950079877861636f4dbb8"

    def native(chain, address, after=None, as_of=None):
        if address == C1:
            raise CacheMiss("readonly cache, nothing cached for ?apikey=SECRET")
        return fixture_chain.get_native_txs(chain, address, after=after, as_of=as_of)
    t = run_trace(example("ohnd_replay.case"), get_transfers=fixture_chain.get_transfers, label=fixture_chain.label,
                  freeze_status=fixture_chain.freeze_status, get_balance=fixture_chain.get_balance, get_native_txs=native)
    assert t["status"] == "partial" and t["stats"]["fetch_errors"] >= 1
    assert "SECRET" not in str(t)


# ---- synthetic cases -------------------------------------------------------------------------

V, X, Y, Z, F = "0xv", "0xx", "0xy", "0xz", "0xf"


def _t(h, a, b, amt, block, li=0, **kw):
    return {"tx_hash": h, "from": a, "to": b, "amount": float(amt), "amount_base": int(amt * 10 ** 6),
            "time": f"2024-01-01T00:{block:02d}:00Z", "block": block, "log_index": li, **kw}


def _case(sends, **kw):
    return {"case_id": "t", "source": "victim_report", "sends": [
        {"chain": "ethereum", "token": "USDT", "time": "2024-01-01T00:00:00Z", **s} for s in sends], **kw}


def _chain(rows):
    def get(chain, address, after=None, as_of=None):
        return [r for r in rows if address in (r["from"], r["to"])]
    return get


def test_split_route_swap_is_seeded_once_and_never_crashes():
    from hound.engine.swaps import resolve_eth_seeds
    eth = [{"tx_hash": "e1", "from": V, "to": X, "amount_wei": 10 ** 18, "gas_wei": 0, "block": 1, "tx_index": 0,
            "time": "2024-01-01T00:01:00Z"},
           {"tx_hash": "sw", "from": X, "to": "0xpool", "amount_wei": 10 ** 18, "gas_wei": 0, "block": 2, "tx_index": 0,
            "time": "2024-01-01T00:02:00Z"}]
    for legs in ((2000, 1000), (1000, 2000), (1500, 1500)):
        usdt = [_t("sw", "0xpool1", X, legs[0], 2, 1), _t("sw", "0xpool2", X, legs[1], 2, 2)]
        sw = resolve_eth_seeds([{"tx_hash": "e1", "to": X, "seed_id": "s1"}], eth, usdt)
        assert sw["seeds"] == {("sw", X): [("s1", 3000 * 10 ** 6)]}
        r = propagate(usdt, {X}, sw["seeds"])
        assert r["seeded"] == {"s1": 3000 * 10 ** 6}, legs
        assert r["remaining"][X] == {"s1": 3000 * 10 ** 6}


def test_old_nodes_are_rechecked_when_later_hops_change_their_taint():
    # A (hop 1) sends the victim lot to Q, Q sends it back, then A pays C. Until Q is explored,
    # Q -> A looks clean, so A -> C looks clean. Only the hop-2 replay shows A -> C is victim money,
    # and A was explored a hop earlier.
    A, Q, C = "0xa", "0xq", "0xc"
    rows = [_t("t1", V, A, 1000, 1), _t("t2", A, Q, 1000, 2), _t("t3", Q, A, 1000, 3), _t("t4", A, C, 1000, 4)]
    t = run_trace(_case([{"tx_hash": "t1", "from": V, "to": A, "amount": 1000}]), get_transfers=_chain(rows))
    ends = {e["address"]: e for e in t["endpoints"]}
    assert C in ends and ends[C]["victim_remaining"] == 1000.0, ends


def test_frozen_address_pass_through_money_is_still_followed():
    rows = [_t("t1", V, F, 1000, 1), _t("t2", F, Z, 900, 2)]
    frz = lambda c, a, as_of=None: {"is_frozen": a == F, "frozen_at": "2024-02-01T00:00:00Z" if a == F else None,
                                     "freeze_tx": None}
    t = run_trace(_case([{"tx_hash": "t1", "from": V, "to": F, "amount": 1000}]), get_transfers=_chain(rows),
                  freeze_status=frz)
    ends = {e["address"]: e for e in t["endpoints"]}
    assert ends[F]["reason"] == "frozen" and ends[F]["victim_remaining"] == 100.0
    assert ends[Z]["victim_remaining"] == 900.0


def test_same_transfer_from_two_sources_is_counted_once():
    # X's fetch has log_index, Y's fetch of the same transfer does not (tokentx fallback).
    rows_x = [_t("t1", V, X, 1000, 1, 3), _t("t2", X, Y, 1000, 2, 7)]
    rows_y = [dict(_t("t2", X, Y, 1000, 2), log_index=None), _t("t3", Y, Z, 1000, 3, 1)]

    def get(chain, address, after=None, as_of=None):
        return {X: rows_x, Y: rows_y, Z: [rows_y[1]]}.get(address, [])
    t = run_trace(_case([{"tx_hash": "t1", "from": V, "to": X, "amount": 1000}]), get_transfers=get)
    xy = [e for e in t["edges"] if (e["from"], e["to"]) == (X, Y)]
    assert len(xy) == 1 and xy[0]["amount"] == 1000.0 and xy[0]["tx_hashes"] == ["t2"]
    assert {e["address"]: e["victim_remaining"] for e in t["endpoints"]}[Z] == 1000.0
    assert t["status"] == "partial" and any("log_index" in e["detail"] for e in t["audit_log"] if e["step"] == "error")


def test_order_ignores_missing_tx_index():
    from hound.engine.fifo import order_key
    a = _t("a", X, Y, 1, 5, li=50)           # no tx_index (blockscout): must not sort as tx 0
    b = dict(_t("b", X, Y, 1, 5, li=10), tx_index=3)
    assert sorted([a, b], key=order_key) == [b, a]


def test_missing_and_checksummed_seeds():
    rows = [_t("0xabc", V, X, 1000, 1), _t("t2", X, Y, 1000, 2)]
    good = run_trace(_case([{"tx_hash": "0xABC", "from": V.upper().replace("0X", "0x"), "to": "0xX", "amount": 1000}]),
                     get_transfers=_chain(rows))
    assert good["status"] == "done" and {e["address"] for e in good["endpoints"]} == {Y}
    bad = run_trace(_case([{"tx_hash": "0xdead", "from": V, "to": X, "amount": 1000}]), get_transfers=_chain(rows))
    assert bad["status"] == "partial"
    assert any("s1 not found" in e["detail"] for e in bad["audit_log"] if e["step"] == "error")
    import pytest
    with pytest.raises(ValueError, match="not supported"):
        run_trace(_case([{"tx_hash": "t1", "from": V, "to": X, "amount": 1, "token": "DAI"}]), get_transfers=_chain(rows))


def test_adapters_missing_is_its_own_exception(monkeypatch):
    import sys
    import pytest
    from hound.engine import trace as tr
    assert not issubclass(tr.AdaptersMissing, RuntimeError)
    case = example("ohnd_replay.case")
    with pytest.raises(tr.AdaptersMissing, match="get_native_txs"):
        run_trace(case, get_transfers=fixture_chain.get_transfers)
    import hound
    monkeypatch.setitem(sys.modules, "hound.chain", None)  # import fails
    monkeypatch.delattr(hound, "chain", raising=False)
    with pytest.raises(tr.AdaptersMissing):
        run_trace(case)


def test_post_run_lookup_failures_are_partial_not_fatal():
    rows = [_t("t1", V, X, 1000, 1)]

    def boom(*a, **k):
        raise ConnectionError("GET https://x/?apikey=SECRET down")
    t = run_trace(_case([{"tx_hash": "t1", "from": V, "to": X, "amount": 1000}], freeze_visibility="hidden"),
                  get_transfers=_chain(rows), freeze_status=boom, label=boom, get_balance=boom)
    assert t["status"] == "partial" and "SECRET" not in str(t)
    steps = [(e["step"], e["detail"]) for e in t["audit_log"] if e["step"] == "error"]
    assert any("freeze_status" in d for _, d in steps) and any("label" in d for _, d in steps)
    assert any("get_balance" in d for _, d in steps)
    assert {e["address"]: e["balance_usdt"] for e in t["endpoints"]}[X] is None


def test_classifier_never_stops_without_a_labelled_sweep_target(monkeypatch):
    import hound.llm.classify as cl
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(cl, "_cache", {})
    monkeypatch.setattr(cl, "_claude", lambda f, floor, **k: {"kind": "exchange_deposit", "confidence": 0.99, "reasons": ["r"]})
    dep, hot = "0xdep", "0xhot"
    rows = [_t("t0", V, dep, 1000, 1)]
    for i in range(6):
        rows += [_t(f"i{i}", f"0xu{i}", dep, 100, 2 + 2 * i), _t(f"o{i}", dep, hot, 100 + (1000 if i == 5 else 0), 3 + 2 * i)]
    case = _case([{"tx_hash": "t0", "from": V, "to": dep, "amount": 1000}])
    t = run_trace(case, get_transfers=_chain(rows))
    assert "exchange" not in {e["reason"] for e in t["endpoints"]}, "Claude's opinion must not create a stop"
    node = {n["address"]: n for n in t["nodes"]}[dep]
    assert node["classifier"]["kind"] == "unknown"
    lab = lambda c, a: {"name": "Binance 14", "kind": "exchange_hot", "source": "list"} if a == hot else None
    t = run_trace(case, get_transfers=_chain(rows), label=lab)
    assert {e["address"]: e["reason"] for e in t["endpoints"]}[dep] == "exchange"
    # the inferred deposit keeps the exchange's name, not 'unlabelled exchange deposit'
    assert {e["address"]: e["exchange"] for e in t["endpoints"]}[dep] == "Binance deposit (inferred)"
    node = {n["address"]: n for n in t["nodes"]}[dep]
    assert node["label"] == "Binance deposit (inferred)" and node["label_source"] == "classifier"


def test_back_edges_hop_after_their_source_and_path_confidence():
    t = run()
    depth = {n["address"]: n["depth"] for n in t["nodes"]}
    for e in t["edges"]:
        assert e["hop"] >= depth[e["from"]] + 1 and e["hop"] >= depth[e["to"]], e
    pairs = [(e["from"], e["to"], e["token"]) for e in t["edges"]]
    assert len(pairs) == len(set(pairs)), "one edge per (from, to, token)"
    eth = [e for e in t["edges"] if e["token"] == "ETH"]
    assert len(eth) == 3 and abs(sum(e["amount"] for e in eth) - sum(s["amount"] for s in t["seeds"])) < 1e-6
    pc = {n["address"]: n["path_confidence"] for n in t["nodes"]}
    assert all(pc[n["address"]] == 1.0 for n in t["nodes"] if n["kind"] == "victim")
    assert all(0 < v <= 1 for v in pc.values())


def test_replay_balance_is_the_cutoff_balance():
    t = run()
    ends = {e["address"]: e for e in t["endpoints"]}
    assert ends[A7]["balance_usdt"] >= ends[A7]["victim_remaining"] > 0


def test_label_source_for_service_labels():
    rows = [_t("t1", V, X, 1000, 1)]
    t = run_trace(_case([{"tx_hash": "t1", "from": V, "to": X, "amount": 1000}]), get_transfers=_chain(rows),
                  label=lambda c, a: {"name": "Some Router", "kind": "service", "source": "blockscout"} if a == X else None)
    n = {n["address"]: n for n in t["nodes"]}[X]
    assert n["label_source"] == "service" and n["kind"] == "unknown"


def test_replay_is_blind():
    # Freezes are never consulted while tracing, and every fetch is bounded by the cutoff.
    case = example("ohnd_replay.case")
    cutoff = case["data_cutoff_block"]
    calls = []

    def gt(chain, address, after=None, as_of=None):
        calls.append(("transfers", as_of))
        rows = fixture_chain.get_transfers(chain, address, after=after, as_of=as_of)
        assert all(r["block"] <= cutoff for r in rows)
        return rows

    def nt(chain, address, after=None, as_of=None):
        calls.append(("native", as_of))
        return fixture_chain.get_native_txs(chain, address, after=after, as_of=as_of)

    def fz(chain, address, **kw):
        calls.append(("freeze", None))
        return fixture_chain.freeze_status(chain, address)
    t = run_trace(case, get_transfers=gt, label=fixture_chain.label, freeze_status=fz, get_native_txs=nt)
    assert all(a == cutoff for k, a in calls if k != "freeze")
    last_fetch = max(i for i, c in enumerate(calls) if c[0] != "freeze")
    assert all(i > last_fetch for i, c in enumerate(calls) if c[0] == "freeze"), "freezes read before the trace ended"
    assert "frozen" not in {e["reason"] for e in t["endpoints"]}
    assert not [e for e in t["audit_log"] if e["step"] == "stop" and "froze" in e["detail"]]


def test_swap_leg_from_two_sources_counts_once():
    from hound.engine.swaps import resolve_eth_seeds
    x = "0xswap"
    sends = [{"tx_hash": "seed", "from": "0xv", "to": x, "token": "ETH", "amount": 1.0, "seed_id": "s1"}]
    native = [{"tx_hash": "seed", "from": "0xv", "to": x, "amount_wei": str(10**18), "gas_wei": "0", "block": 1, "tx_index": 0, "time": "2024-01-01T00:00:00Z"},
              {"tx_hash": "sw", "from": x, "to": "0xrouter", "amount_wei": str(10**18), "gas_wei": "0", "block": 2, "tx_index": 0, "time": "2024-01-02T00:00:00Z"}]
    leg = {"tx_hash": "sw", "from": "0xpool", "to": x, "amount": 3000.0, "time": "2024-01-02T00:00:00Z", "block": 2}
    r = resolve_eth_seeds(sends, native, [dict(leg, log_index=7), dict(leg, log_index=None), dict(leg)])
    assert r["swaps"][0]["usdt_in_base"] == 3000 * 10**6


def test_infra_addresses_stop_and_keep_their_inflow():
    A2 = "0x78366b2f6c5321ac30629c078120385ae2da1a06"

    def lab(chain, address):
        return {"name": "Uniswap router", "kind": "infra", "source": "infra_allowlist"} if address == A2 else None
    t = run_trace(example("ohnd_replay.case"), get_transfers=fixture_chain.get_transfers, label=lab,
                  freeze_status=fixture_chain.freeze_status, get_balance=fixture_chain.get_balance,
                  get_native_txs=fixture_chain.get_native_txs)
    ends = {(e["address"], e["reason"]): e for e in t["endpoints"]}
    assert ends[(A2, "infra")]["victim_inflow"] > 0


# ---- round 2 engine fixes ---------------------------------------------------------------

def _total_remaining(t):
    return round(sum(e["victim_remaining"] for e in t["endpoints"]), 6)


def test_dust_and_returned_money_have_endpoints():
    # engine-r2-03. A: X keeps 50 of 1000 (below min_amount) -> a dust endpoint at X.
    rows = [_t("t0", V, X, 1000, 1), _t("a", X, Y, 950, 2)]
    t = run_trace(_case([{"tx_hash": "t0", "from": V, "to": X, "amount": 1000}]), get_transfers=_chain(rows))
    ends = {(e["address"], e["reason"]): e["victim_remaining"] for e in t["endpoints"]}
    assert ends == {(Y, "holding"): 950.0, (X, "dust"): 50.0}
    assert _total_remaining(t) == 1000.0
    # B: a "profit" payout back to the victim -> returned_to_victim.
    rows = [_t("t0", V, X, 1000, 1), _t("b", X, V, 200, 2), _t("c", X, Y, 800, 3)]
    t = run_trace(_case([{"tx_hash": "t0", "from": V, "to": X, "amount": 1000}]), get_transfers=_chain(rows))
    ends = {(e["address"], e["reason"]): e["victim_remaining"] for e in t["endpoints"]}
    assert ends == {(Y, "holding"): 800.0, (V, "returned_to_victim"): 200.0}
    assert {n["address"]: n["kind"] for n in t["nodes"]}[V] == "victim"


def test_conservation_is_exact_for_random_cases():
    # engine-r2-03: every seeded victim base unit ends at exactly one endpoint, whatever the graph and caps.
    import random
    for seed in range(40):
        rng = random.Random(seed)
        addrs = [V] + [f"0x{i:02d}" for i in range(12)]
        rows, block = [], 1
        n_sends = rng.randint(1, 3)
        sends = []
        for i in range(n_sends):
            to = rng.choice(addrs[1:4])
            amt = rng.randint(200, 5000)
            rows.append(_t(f"s{i}", V, to, amt, block)); block += 1
            sends.append({"tx_hash": f"s{i}", "from": V, "to": to, "amount": amt})
        for j in range(rng.randint(5, 40)):
            a, b = rng.sample(addrs, 2)
            rows.append(_t(f"r{j}", a, b, rng.randint(1, 3000), block)); block += 1
        method = {"min_amount": rng.choice([1.0, 100.0, 500.0]), "max_branches_per_node": rng.choice([1, 2, 12]),
                  "max_hops": rng.choice([1, 2, 8]), "max_api_calls": rng.choice([3, 400])}
        t = run_trace(_case(sends), get_transfers=_chain(rows), **method)
        seeded = sum(s["amount"] for s in sends)
        assert abs(_total_remaining(t) - seeded) < 1e-6, (seed, method, _total_remaining(t), seeded, t["endpoints"])
        by_seed = {}
        for e in t["endpoints"]:
            for sid, v in e["attributed_by_seed"].items():
                by_seed[sid] = round(by_seed.get(sid, 0) + v, 6)
        assert by_seed == {f"s{i + 1}": float(s["amount"]) for i, s in enumerate(sends)}, (seed, by_seed)


def test_replay_conserves_every_seeded_usdt():
    t = run()
    seeded = sum(p["usdt_out"] for p in t["swaps"]["per_seed"].values())
    seeded += sum(s["amount"] for s in t["seeds"] if s["token"] == "USDT")
    assert abs(_total_remaining(t) - seeded) < 1e-5, (_total_remaining(t), seeded)


def test_shared_address_stops_are_never_holding_or_freezable():
    # A busy service, an exchange or a router always has the balance to "cover" the victim money,
    # which would make it look freezable. It is never a holding and never freezable.
    class TooManyTransfers(Exception):
        pass
    hv, ex, inf = "0xhv", "0xex", "0xinf"
    rows = [_t("t0", V, X, 3000, 1), _t("a", X, hv, 1000, 2), _t("b", X, ex, 1000, 3), _t("c", X, inf, 1000, 4)]
    base = _chain(rows)

    def get(chain, address, after=None, as_of=None):
        if address == hv:
            raise TooManyTransfers("too many")
        return base(chain, address)
    labels = {ex: {"name": "Binance 14", "kind": "exchange_hot"}, inf: {"name": "Router", "kind": "infra"}}
    t = run_trace(_case([{"tx_hash": "t0", "from": V, "to": X, "amount": 3000}]), get_transfers=get,
                  label=lambda c, a: labels.get(a), get_balance=lambda c, a: 10 ** 9)
    ends = {e["address"]: e for e in t["endpoints"]}
    assert {a: ends[a]["reason"] for a in (hv, ex, inf)} == {hv: "high_volume", ex: "exchange", inf: "infra"}
    assert not any(e["freezable"] for e in t["endpoints"])
    kinds = {n["address"]: n["kind"] for n in t["nodes"]}
    assert "holding" not in {kinds[hv], kinds[ex], kinds[inf]}


def test_unresolved_swaps_have_an_endpoint():
    # engine-r2-08: the 0.0755 ETH of s2 that was never swapped to USDT is visible as an endpoint.
    t = run()
    assert t["swaps"]["unresolved"], "the replay has an unresolved ETH out"
    ends = {(e["address"], e["reason"]): e for e in t["endpoints"]}
    for u in t["swaps"]["unresolved"]:
        e = ends[(u["address"], "swap_unresolved")]
        assert (e["victim_remaining"], e["freezable"], e["attributed_by_seed"]) == (0.0, False, {})


def test_engine_honours_its_deadline_before_every_adapter_call(monkeypatch):
    # engine-r2 (g): no adapter call starts after the deadline, including the post-run lookups.
    import types
    import hound.engine.trace as tr
    clock = [0.0]
    monkeypatch.setattr(tr, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    calls = []

    def tick(name, fn):
        def wrapped(*a, **k):
            calls.append((name, clock[0]))
            clock[0] += 1.0
            return fn(*a, **k)
        return wrapped
    chain_rows = [_t("t0", V, "0xa0", 10000, 1)]
    for i in range(10):  # a long chain: more hops than the deadline allows
        chain_rows.append(_t(f"h{i}", f"0xa{i}", f"0xa{i + 1}", 10000 - i, 2 + i))
    t = run_trace(_case([{"tx_hash": "t0", "from": V, "to": "0xa0", "amount": 10000}]),
                  get_transfers=tick("get_transfers", _chain(chain_rows)), label=tick("label", lambda c, a: None),
                  freeze_status=tick("freeze_status", lambda c, a, **k: tr.NO_FREEZE),
                  get_balance=tick("get_balance", lambda c, a: 1.0), deadline_s=6.5)
    assert calls and max(at for _, at in calls) <= 6.5, calls
    assert t["status"] == "partial"
    assert "time_cap" in {e["reason"] for e in t["endpoints"]}
    assert abs(_total_remaining(t) - 10000) < 1e-6


def _llm_spy(monkeypatch, sleep_s=0.0):
    import hound.llm.classify as cl
    import time as _time
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(cl, "_cache", {})
    got = []

    def fake(f, floor, timeout=8.0):
        got.append(timeout)
        _time.sleep(sleep_s)
        return {**floor, "reasons": ["claude"]}
    monkeypatch.setattr(cl, "_claude", fake)
    return got


def test_replay_and_cached_runs_never_call_claude(monkeypatch):
    # engine-r2-06: a replay must be byte-identical across restarts and never wait on Claude.
    got = _llm_spy(monkeypatch)
    t = run()
    assert got == [] and all("claude" not in (n["classifier"] or {}).get("reasons", []) for n in t["nodes"])
    rows = [_t("t0", V, X, 1000, 1), _t("a", X, Y, 950, 2)]
    case = _case([{"tx_hash": "t0", "from": V, "to": X, "amount": 1000}])
    for mode in ("readonly", "prefer_cache"):
        monkeypatch.setenv("HOUND_CACHE_MODE", mode)
        run_trace(case, get_transfers=_chain(rows))
        assert got == [], mode
    monkeypatch.setenv("HOUND_CACHE_MODE", "live")
    run_trace(case, get_transfers=_chain(rows))
    assert got, "a live run may still reword the reasons"


def test_live_claude_rewording_has_a_total_budget(monkeypatch):
    import hound.engine.trace as tr
    import time as _time
    monkeypatch.setenv("HOUND_CACHE_MODE", "live")
    monkeypatch.setattr(tr, "LLM_BUDGET_S", 0.9)
    got = _llm_spy(monkeypatch, sleep_s=0.3)
    rows = [_t("t0", V, "0xa0", 10000, 1)] + [_t(f"h{i}", f"0xa{i}", f"0xa{i + 1}", 10000, 2 + i) for i in range(8)]
    t0 = _time.monotonic()
    run_trace(_case([{"tx_hash": "t0", "from": V, "to": "0xa0", "amount": 10000}]), get_transfers=_chain(rows))
    assert _time.monotonic() - t0 < 1.5
    assert 1 <= len(got) <= 2 and all(x <= 0.9 for x in got), got


class TooManyTransfers(Exception):
    pass


def _stopped_seed_case(how):
    """V pays X 777 directly, and X is stopped before its history is fetched."""
    rows = [_t("t0", V, X, 777, 1), _t("a", X, Y, 700, 2)]
    base = _chain(rows)
    kw = {}

    def get(chain, address, after=None, as_of=None):
        if address == X and how == "high_volume":
            raise TooManyTransfers("too many")
        if address == X and how == "dead_end":
            raise ConnectionError("down")
        return base(chain, address)
    if how == "exchange":
        kw["label"] = lambda c, a: {"name": "Binance 14", "kind": "exchange_hot"} if a == X else None
    if how == "infra":
        kw["label"] = lambda c, a: {"name": "Router", "kind": "infra"} if a == X else None
    if how == "time_cap":
        kw["deadline_s"] = -1
    if how == "budget":
        kw["max_api_calls"] = 1
        kw["label"] = lambda c, a: None
        rows.insert(0, _t("z", V, "0xa", 500, 0))  # 0xa (first in order) uses the one call; X never gets one
        kw["_extra"] = {"tx_hash": "z", "from": V, "to": "0xa", "amount": 500}
    sends = [{"tx_hash": "t0", "from": V, "to": X, "amount": 777}] + ([kw.pop("_extra")] if "_extra" in kw else [])
    return run_trace(_case(sends), get_transfers=get, **kw)


def test_seed_recipient_stopped_before_fetch_still_conserves():
    # R2 re-review: a victim paying straight into an exchange, a busy address, or a recipient the
    # deadline or budget never reached keeps the full seed at that recipient's endpoint.
    for how in ("exchange", "infra", "high_volume", "dead_end", "time_cap", "budget"):
        t = _stopped_seed_case(how)
        ends = [e for e in t["endpoints"] if (e["victim_remaining"] or e["victim_inflow"]) and e["address"] == X]
        assert [(e["address"], e["reason"], e["victim_inflow"], e["victim_remaining"]) for e in ends] == \
            [(X, how, 777.0, 777.0)], (how, t["endpoints"])
        assert ends[0]["attributed_by_seed"] == {"s1": 777.0}
        assert not any("not found on chain" in a["detail"] for a in t["audit_log"]), how
        assert any(e["from"] == V and e["to"] == X and e["attributed_amount"] == 777.0 for e in t["edges"]), how
        if how in ("exchange", "infra", "high_volume"):
            kinds = {n["address"]: n["kind"] for n in t["nodes"]}
            assert kinds[X] != "holding" and not ends[0]["freezable"], how


def test_conservation_fuzz_with_stops_at_any_address():
    # Seeds may land on labelled, busy, failing or unreached addresses; money may go back to a victim.
    import random
    import types
    import hound.engine.trace as tr
    W = "0xw"
    for seed in range(150):
        rng = random.Random(1000 + seed)
        addrs = [V, W] + [f"0x{i:02d}" for i in range(10)]
        roles = {a: rng.choice(["plain"] * 5 + ["exchange", "infra", "hv", "err"]) for a in addrs[2:]}
        rows, block, sends = [], 1, []
        for i in range(rng.randint(1, 3)):
            v, to = rng.choice([V, W]), rng.choice(addrs[2:6])
            amt = rng.randint(200, 5000)
            rows.append(_t(f"s{i}", v, to, amt, block)); block += 1
            sends.append({"tx_hash": f"s{i}", "from": v, "to": to, "amount": amt})
        for j in range(rng.randint(5, 40)):
            a, b = rng.sample(addrs, 2)
            rows.append(_t(f"r{j}", a, b, rng.randint(1, 3000), block)); block += 1
        base = _chain(rows)

        def get(chain, address, after=None, as_of=None, roles=roles, base=base):
            if roles.get(address) == "hv":
                raise TooManyTransfers("x")
            if roles.get(address) == "err":
                raise ConnectionError("x")
            return base(chain, address)

        def label(c, a, roles=roles):
            return {"exchange": {"name": "Ex", "kind": "exchange_hot"}, "infra": {"name": "R", "kind": "infra"}}.get(
                roles.get(a))
        clock, step = [0.0], rng.choice([0.0, 0.0, 1.0])
        real = tr.time

        def mono(clock=clock, step=step):
            clock[0] += step
            return clock[0]
        tr.time = types.SimpleNamespace(monotonic=mono)
        try:
            method = {"min_amount": rng.choice([1.0, 100.0, 500.0]), "max_branches_per_node": rng.choice([1, 2, 12]),
                      "max_hops": rng.choice([1, 2, 8]), "max_api_calls": rng.choice([1, 3, 400]),
                      "deadline_s": rng.choice([5, 40, 120])}
            t = run_trace(_case(sends), get_transfers=get, label=label, **method)
        finally:
            tr.time = real
        seeded = sum(s["amount"] for s in sends)
        assert abs(_total_remaining(t) - seeded) < 1e-6, (seed, method, roles, t["endpoints"])
        assert len({(e["address"], e["reason"]) for e in t["endpoints"]}) == len(t["endpoints"]), seed


def test_eth_swap_pass_past_the_deadline_is_partial_not_a_crash():
    calls = []

    def native(chain, address, after=None, as_of=None):
        calls.append(address)
        return []
    case = {"case_id": "t", "source": "victim_report", "sends": [
        {"chain": "ethereum", "token": "ETH", "tx_hash": "e1", "from": V, "to": X, "amount": 1.0,
         "time": "2024-01-01T00:00:00Z"}]}
    t = run_trace(case, get_transfers=lambda *a, **k: calls.append("t") or [], get_native_txs=native, deadline_s=-1)
    assert calls == [] and t["status"] == "partial"
    assert any(e["address"] == X and e["reason"] == "time_cap" for e in t["endpoints"])
    assert any(a["step"] == "cap_hit" and a["address"] == X for a in t["audit_log"])


def test_dust_branch_later_followed_is_not_counted_twice():
    V, A, B, C = "0x" + "a1" * 20, "0x" + "b2" * 20, "0x" + "c3" * 20, "0x" + "d4" * 20
    rows = [{"chain": "ethereum", "tx_hash": f"t{i}", "log_index": 0, "from": f, "to": t, "token": "USDT",
             "amount": amt, "time": f"2024-01-0{i + 1}T00:00:00Z", "block": i + 1}
            for i, (f, t, amt) in enumerate([(V, A, 1000.0), (V, B, 1000.0), (A, C, 10.0), (B, C, 900.0)])]
    case = {"case_id": "dust-twice", "created_at": "2024-01-01T00:00:00Z", "source": "phone", "status": "intake",
            "sends": [{"chain": "ethereum", "tx_hash": "t0", "from": V, "to": A, "token": "USDT", "amount": 1000.0, "time": "2024-01-01T00:00:00Z"},
                      {"chain": "ethereum", "tx_hash": "t1", "from": V, "to": B, "token": "USDT", "amount": 1000.0, "time": "2024-01-02T00:00:00Z"}]}
    get = lambda chain, address, after=None, as_of=None, **k: [r for r in rows if address in (r["from"], r["to"])]
    t = run_trace(case, get_transfers=get, label=lambda c, a: None, get_balance=lambda c, a, **k: 0.0, max_hops=1)
    assert abs(sum(e["victim_remaining"] for e in t["endpoints"]) - 2000.0) < 1e-6
