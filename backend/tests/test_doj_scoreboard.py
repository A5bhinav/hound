import json
from pathlib import Path

import pytest

from hound.proof.doj_ohnd import FINALS, INPUTS, INTERMEDIATES, assert_holdout_clean, doj_scoreboard, load_holdout, load_resolved
from hound.proof.resolve_ohnd import ResolveError, resolve

ROOT = Path(__file__).resolve().parents[2]


def test_holdout_has_15_entries_with_pages_and_full_addresses():
    h = load_holdout()
    assert len(h["entries"]) == 15 and len(h["all_holdout_addresses"]) == 15
    for e in h["entries"]:
        assert e["source_page"] and e["full"].startswith(e["prefix"]) and e["full"].endswith(e["suffix"]), e["label"]
    assert len(h["seeds_ah_eth_sends_para69"]) == 6


def test_resolver_resolves_all_15_and_drops_poison():
    h = load_holdout()
    tr = json.load(open(ROOT / "data" / "doj" / "usdt_transfers_holdout.json"))["transfers"]
    out = resolve(h, tr)
    assert set(out["resolved"]) == {e["label"] for e in h["entries"]}
    assert out["resolved"]["A-6"]["address"] == "0x58e99d9413bb6ce05748a84f76e5fff4bb2d0dcb"
    assert out["poison_lookalikes_dropped"], "fixture should contain poison lookalikes"
    assert not set(out["poison_lookalikes_dropped"]) & {v["address"] for v in out["resolved"].values()}


def test_resolver_fails_loudly_on_ambiguity():
    h = load_holdout()
    tr = json.load(open(ROOT / "data" / "doj" / "usdt_transfers_holdout.json"))["transfers"]
    a6 = "0x58e99d9413bb6ce05748a84f76e5fff4bb2d0dcb"
    fake = "0x58e0000000000000000000000000000004b2d0dcb"  # same prefix+suffix, big transfer
    tr2 = tr + [{"chain": "ethereum", "tx_hash": "0xfake", "from": "0x9eb0c71e79066552bdd05a69fc4dcac075db5e1f", "to": fake,
                 "token": "USDT", "amount": 50000.0, "time": "2024-05-25T00:00:00Z", "block": 1}]
    with pytest.raises(ResolveError):
        resolve(h, tr2)
    del a6


def test_scoreboard_no_trace():
    s = doj_scoreboard(trace=None)
    assert s["summary"]["status"] == "no_trace"
    assert s["summary"]["finals_reached"] == 0 and len(s["targets"]) == 11
    assert {r["label"] for r in s["inputs"]} == set(INPUTS)


def test_scoreboard_refuses_hand_built():
    s = doj_scoreboard({"source": "hand_built", "nodes": [], "edges": [], "endpoints": []})
    assert s["summary"]["status"] == "refused" and s["summary"]["finals_reached"] == 0


def test_scoreboard_marks_incomplete_on_fetch_errors():
    s = doj_scoreboard({"nodes": [], "edges": [], "endpoints": [], "stats": {"fetch_errors": 3}})
    assert s["summary"]["status"] == "incomplete"


def test_scoreboard_full_credit_from_fixture_and_amount_bands():
    res = load_resolved()
    hold = set(res.values())
    tr = json.load(open(ROOT / "data" / "doj" / "usdt_transfers_holdout.json"))["transfers"]
    edges = [{"from": t["from"], "to": t["to"], "token": "USDT", "attributed_amount": None} for t in tr if t["from"] in hold and t["to"] in hold]
    # amount tier = money traced INTO each final (edge attributed_amount), split across two edges for A-7
    edges += [{"from": res["A-6"], "to": res["A-7"], "token": "USDT", "attributed_amount": 314657 * 1.03 / 2},
              {"from": res["A-6"], "to": res["A-7"], "token": "USDT", "attributed_amount": 314657 * 1.03 / 2},
              {"from": res["A-6"], "to": res["A-8"], "token": "USDT", "attributed_amount": 11954 * 1.15},
              {"from": res["A-6"], "to": res["A-9"], "token": "USDT", "attributed_amount": 43071 * 0.5}]
    endpoints = [{"address": res["A-7"], "victim_inflow": 1.0, "reason": "frozen"},  # remaining balance, must NOT be scored
                 {"address": res["A-8"], "victim_inflow": 1.0, "reason": "frozen"},
                 {"address": res["A-9"], "victim_inflow": 1.0, "reason": "frozen"}]
    s = doj_scoreboard({"source": "engine", "nodes": [], "edges": edges, "endpoints": endpoints})
    assert s["summary"]["intermediates_reached"] == len(INTERMEDIATES) == 8
    assert s["summary"]["finals_reached"] == len(FINALS) == 3
    assert s["summary"]["amount_bands"] == {"A-7": "green", "A-8": "amber", "A-9": "red"}
    assert all(e["doj_label"] for e in s["endpoints"])


def test_poison_lookalike_never_counts_as_reached():
    res = load_resolved()
    poison = "0x58e7c5605b96073567f441d230cba6154b2d0dcb"  # matches A-6's 58e…b2d0dcb
    s = doj_scoreboard({"source": "engine", "nodes": [{"address": poison, "chain": "ethereum"}], "edges": [], "endpoints": []})
    assert s["summary"]["consolidation_a6_reached"] is False
    assert res["A-6"] != poison


def test_holdout_leak_detected():
    h = load_holdout()
    with pytest.raises(AssertionError, match="Holdout leak"):
        assert_holdout_clean({h["entries"][0]["full"]})
    assert_holdout_clean({"0x0000000000000000000000000000000000000000"})
