"""Trace engine (Ishaan). STUB: returns the real DOJ replay example until the engine lands."""
from hound.contracts import example, validate_trace


def run_trace(case):
    trace = example("ohnd_replay.trace")
    trace["case_id"] = case["case_id"]
    return validate_trace(trace)
