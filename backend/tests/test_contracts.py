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
