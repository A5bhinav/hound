import pytest

from hound.contracts import example, validate_case, validate_trace


def test_examples_match_schemas():
    validate_case(example("ohnd_replay.case"))
    validate_trace(example("ohnd_replay.trace"))


def test_bad_trace_fails_loudly():
    bad = example("ohnd_replay.trace")
    bad["edges"][0]["confidence"] = 2
    with pytest.raises(ValueError, match="confidence"):
        validate_trace(bad)


def test_fixture_has_no_doj_labels():
    # Holdout rule (BRIEF 5.1): DOJ labels must never appear in engine output.
    for n in example("ohnd_replay.trace")["nodes"]:
        assert n["label"] is None


def _stable(t):
    t = dict(t)
    for k in ("created_at", "stats", "audit_log"):
        t.pop(k, None)
    return t


def _engine_replay():
    from hound import fixture_chain as fc
    from hound.engine.trace import run_trace
    return run_trace(example("ohnd_replay.case"), get_transfers=fc.get_transfers, label=fc.label,
                     freeze_status=fc.freeze_status, get_balance=fc.get_balance, get_native_txs=fc.get_native_txs)


def test_example_trace_is_the_engines_output():
    # The web UI, the /check stub and the writer tests read this file. Regenerate it with
    # `python -m tests.test_contracts` (from backend/) whenever the engine changes.
    assert _stable(example("ohnd_replay.trace")) == _stable(_engine_replay())


if __name__ == "__main__":
    import json
    from hound.contracts import EXAMPLES
    (EXAMPLES / "ohnd_replay.trace.json").write_text(json.dumps(_engine_replay(), indent=2) + "\n")
    print("wrote", EXAMPLES / "ohnd_replay.trace.json")
