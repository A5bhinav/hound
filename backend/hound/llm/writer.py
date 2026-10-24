"""Case writer (Ishaan). STUB. Real version may only cite fields from the Trace (BRIEF 4.4)."""


def write_case(trace, case, audience="victim"):
    if audience not in ("victim", "detective"):
        raise ValueError(f"audience must be victim or detective, got {audience!r}")
    ends = ", ".join(e["address"] for e in trace["endpoints"])
    return {"text": f"[stub {audience} packet] Funds traced to: {ends}", "cited": ["endpoints[].address"]}
