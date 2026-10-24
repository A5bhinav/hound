"""Other payers (Jinka). STUB: returns whatever the trace already has."""


def other_payers(trace, window_days=7):
    return trace.get("other_payers", [])
