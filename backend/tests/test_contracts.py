import json
import os
import subprocess
import sys
from pathlib import Path

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
    """Everything except wall-clock values: created_at, elapsed_ms and the audit timestamps."""
    t = dict(t)
    t.pop("created_at", None)
    t["stats"] = {k: v for k, v in t.get("stats", {}).items() if k != "elapsed_ms"}
    t["audit_log"] = [{k: v for k, v in e.items() if k != "t"} for e in t.get("audit_log", [])]
    return t


BACKEND = Path(__file__).resolve().parents[1]
_REPLAY = ("import json, sys\n"
           "from hound.contracts import example\n"
           "from hound.engine.trace import run_trace\n"
           "sys.stdout.write(json.dumps(run_trace(example('ohnd_replay.case')), indent=2) + '\\n')\n")


def _engine_replay(cache_dir):
    """A fresh replay through the REAL adapters (hound.chain) from the committed snapshot only:
    HOUND_CACHE_MODE=readonly, an empty local cache, no Claude key. A subprocess, because the
    test conftest swaps hound.chain for the fixture chain."""
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "HOUND_OFFLINE", "HOUND_SNAPSHOT")}
    env.update(HOUND_CACHE_MODE="readonly", HOUND_CACHE_DIR=str(cache_dir), HOUND_NO_DOTENV="1",
               PYTHONPATH=str(BACKEND))
    p = subprocess.run([sys.executable, "-c", _REPLAY], env=env, cwd=BACKEND, capture_output=True, text=True,
                       timeout=120)
    if p.returncode:
        raise RuntimeError(f"replay subprocess failed:\n{p.stderr[-4000:]}")
    return p.stdout


def test_example_trace_is_the_engines_output(tmp_path):
    # The web fixture mode, the watchlist and the writer tests read this file. It must be exactly
    # what the engine produces today from the real adapters. Regenerate it with
    # `python -m tests.test_contracts` (from backend/) whenever the engine or the snapshot changes.
    fresh = json.loads(_engine_replay(tmp_path / "cache"))
    assert fresh["status"] == "done"
    assert _stable(example("ohnd_replay.trace")) == _stable(fresh)


if __name__ == "__main__":
    import tempfile
    from hound.contracts import EXAMPLES
    with tempfile.TemporaryDirectory() as d:
        (EXAMPLES / "ohnd_replay.trace.json").write_text(_engine_replay(Path(d)))
    print("wrote", EXAMPLES / "ohnd_replay.trace.json")
