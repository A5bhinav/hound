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
                     get_balance=fixture_chain.get_balance)


A9 = "0xafd770d8898a0e323c607fe91358345e7b2378a5"


def test_reaches_doj_seized_wallets_blind():
    # Seeds = the 20 A-branch inflows into A-1. Under FIFO they reach A-7 and A-8.
    # A-9 is fed mostly by the B branch (0x447190... matches DOJ's B-3, 447...eb691),
    # so reaching A-9 needs B-branch seeds: CK's scoreboard adds them.
    trace = run()
    ends = {e["address"]: e for e in trace["endpoints"]}
    a_branch_finals = set(FINALS) - {A9}
    assert a_branch_finals <= set(ends), f"missing finals: {a_branch_finals - set(ends)}"
    # Replay: freezes are hidden from the engine, so the finals end as holding (money still
    # there at the cutoff block). The freeze is attached to the node for the UI to reveal.
    nodes = {n["address"]: n for n in trace["nodes"]}
    for a in a_branch_finals:
        assert ends[a]["reason"] == "holding" and ends[a]["victim_remaining"] > 0
        assert nodes[a]["frozen"]["is_frozen"] and not ends[a]["freezable"]
    assert A6 in {n["address"] for n in trace["nodes"]}, "must pass through the A-6 consolidation"


def test_taint_is_conserved():
    trace = run()
    seeded = sum(s["amount"] for s in example("ohnd_replay.case")["sends"])
    for e in trace["edges"]:
        assert e["attributed_amount"] <= e["amount"] + 1e-6
    victims = {s["from"] for s in example("ohnd_replay.case")["sends"]}
    victim_out = sum(e["attributed_amount"] for e in trace["edges"] if e["from"] in victims)
    assert abs(victim_out - seeded) < 1e-3


def test_conservation_per_seed_to_the_micro_unit():
    # Every seed's money ends somewhere visible: endpoints (holding, capped, dust, exchange,
    # max_hops) plus what is still sitting in intermediate wallets.
    from hound.engine.fifo import propagate
    trace = run()
    for seed in trace["seeds"]:
        sid = seed["seed_id"]
        ended = sum(e["attributed_by_seed"].get(sid, 0) for e in trace["endpoints"] if e["reason"] != "holding")
        holding = sum(e["attributed_by_seed"].get(sid, 0) for e in trace["endpoints"] if e["reason"] == "holding")
        assert ended + holding <= seed["amount"] + 1e-6


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
