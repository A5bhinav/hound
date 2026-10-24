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


def test_reaches_doj_seized_wallets_blind():
    # A.H.'s six real ETH sends, freezes hidden, data cut off one block before the last freeze.
    trace = run()
    nodes = {n["address"]: n for n in trace["nodes"]}
    assert INTERMEDIATES <= set(nodes), f"missed intermediates: {INTERMEDIATES - set(nodes)}"
    inflow = {e["to"]: 0.0 for e in trace["edges"]}
    for e in trace["edges"]:
        inflow[e["to"]] += e["attributed_amount"] if e["token"] == "USDT" else 0
    # DOJ para 74 counts money traced INTO each wallet. Bands: green <=5%, amber 5-20%, red >20%.
    assert abs(inflow[A7] - 314657) / 314657 < 0.20
    assert abs(inflow[A9] - 43071) / 43071 < 0.20
    # Known miss: A-6 only starts paying A-8 on May 30, after A.H.'s lots have passed through.
    assert inflow.get(A8, 0) == 0
    assert nodes[A7]["frozen"]["is_frozen"], "freeze must be attached for the UI reveal"


def test_eth_seeds_are_conserved():
    for sid, p in run()["swaps"]["per_seed"].items():
        assert abs(p["eth_sent"] - (p["eth_swapped"] + p["eth_gas"] + p["eth_unresolved"])) < 1e-6, (sid, p)
        assert p["usdt_out"] > 0


def test_taint_is_conserved():
    trace = run()
    for e in trace["edges"]:
        assert e["attributed_amount"] <= e["amount"] + 1e-6
    usdt_seeded = sum(p["usdt_out"] for p in trace["swaps"]["per_seed"].values())
    ended = sum(e["victim_remaining"] for e in trace["endpoints"])
    assert ended <= usdt_seeded + 1e-3


def test_conservation_per_seed_to_the_micro_unit():
    # Every seed's money ends somewhere visible: endpoints (holding, capped, dust, exchange,
    # max_hops) plus what is still sitting in intermediate wallets.
    from hound.engine.fifo import propagate
    trace = run()
    for sid, p in trace["swaps"]["per_seed"].items():
        ended = sum(e["attributed_by_seed"].get(sid, 0) for e in trace["endpoints"])
        assert ended <= p["usdt_out"] + 1e-6, (sid, ended, p["usdt_out"])


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
    # Real zero-value lookalikes of A-6 (58e…b2d0dcb) exist in the data (AUDIT N2).
    nodes = {n["address"] for n in run()["nodes"]}
    zero = {t["to"] for t in TRANSFERS if t["amount"] == 0} | {t["from"] for t in TRANSFERS if t["amount"] == 0}
    assert not (nodes & (zero - {n for n in nodes if any(t["amount"] > 0 and n in (t["from"], t["to"]) for t in TRANSFERS)}))


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
    with pytest.raises(RuntimeError, match="budget"):
        run_trace(case, get_transfers=fixture_chain.get_transfers, get_native_txs=fixture_chain.get_native_txs, max_api_calls=3)


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
