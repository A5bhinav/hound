import json
from pathlib import Path

from hound.proof.doj_ohnd import assert_holdout_clean, doj_scoreboard, load_holdout

ROOT = Path(__file__).resolve().parents[2]


def test_holdout_has_all_14_full_addresses():
    h = load_holdout()
    assert len(h["all_holdout_addresses"]) == 14
    for grp in ("starts", "intermediates", "finals"):
        for x in h["addresses"][grp]:
            a = x["address"]
            assert len(a) == 42 and a.startswith(x["prefix"]) and a.endswith(x["suffix"]), x["label"]


def test_scoreboard_empty_trace_scores_zero():
    s = doj_scoreboard(trace=None)
    assert s["summary"]["finals_reached"] == 0
    assert s["summary"]["intermediates_total"] == 8  # A-2..A-6, B-2..B-4
    assert len(s["targets"]) == 14


def test_scoreboard_counts_reached_from_fixture_transfers():
    # Build a fake Trace whose edges are the real USDT transfers among holdout addresses.
    h = load_holdout()
    hold = set(h["all_holdout_addresses"])
    tr = json.load(open(ROOT / "data" / "doj" / "usdt_transfers_holdout.json"))["transfers"]
    edges = [{"from": t["from"], "to": t["to"]} for t in tr if t["from"] in hold and t["to"] in hold]
    trace = {"nodes": [], "edges": edges, "endpoints": []}
    s = doj_scoreboard(trace)
    assert s["summary"]["finals_reached"] == 3
    assert s["summary"]["consolidation_reached"] is True
    assert s["summary"]["intermediates_reached"] == 8


def test_holdout_leak_detected():
    h = load_holdout()
    try:
        assert_holdout_clean({h["addresses"]["finals"][0]["address"]})
    except AssertionError as e:
        assert "Holdout leak" in str(e)
    else:
        raise AssertionError("leak not detected")
    assert_holdout_clean({"0x0000000000000000000000000000000000000000"}) is None
