"""The 'no internet' fallback: a cold laptop with an empty cache and only the committed snapshot
(data/fixtures/cache) must trace the DOJ replay complete, other payers included (H17)."""
import json

import hound.chain as chain
from hound.chain import cache, labels

# the real adapters, captured before conftest swaps in the fixture chain for unit tests
REAL = {n: getattr(chain, n) for n in ("get_transfers", "freeze_status", "get_balance", "get_native_txs", "is_contract")}
REAL_LABEL = labels.label


def test_replay_traces_complete_offline_from_the_committed_snapshot(monkeypatch, tmp_path):
    for n, f in REAL.items():
        monkeypatch.setattr(chain, n, f)
    monkeypatch.setattr(labels, "label", REAL_LABEL)
    monkeypatch.setenv("HOUND_CACHE_DIR", str(tmp_path / "empty-cache"))
    monkeypatch.setenv("HOUND_CACHE_MODE", "readonly")  # any network call is a CacheMiss
    monkeypatch.delenv("HOUND_SNAPSHOT", raising=False)
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    monkeypatch.setattr(cache, "LIVE_SNAPSHOT_DIR", tmp_path / "no-live-bundle")  # public snapshot only
    from hound.engine.trace import run_trace
    from hound.watch.other_payers import other_payers

    case = json.loads((cache.REPO_ROOT / "examples" / "ohnd_replay.case.json").read_text())
    trace = run_trace(case)
    assert trace["status"] == "done"
    frozen = {n["address"] for n in trace["nodes"] if (n.get("frozen") or {}).get("is_frozen")}
    finals = sorted(round(e["victim_inflow"], 2) for e in trace["endpoints"]
                    if e["address"] in frozen and e["reason"] == "holding")
    assert finals == [12077.78, 47702.92, 317403.01]
    rows = other_payers(trace)
    assert len(rows) == 10
    assert trace["status"] == "done"
    assert not [a for a in trace.get("audit_log") or [] if a.get("step") == "error"]
