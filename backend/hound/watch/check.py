"""Exchange withdrawal check (Jinka). STUB: holds only the DOJ replay's frozen final wallets."""
from hound.contracts import example


def check(chain, address):
    address = address.lower() if chain == "ethereum" else address
    trace = example("ohnd_replay.trace")
    hit = [e for e in trace["endpoints"] if e["address"] == address]
    if hit:
        return {"decision": "hold", "reasons": ["stub: final wallet in DOJ replay trace"],
                "evidence": {"trace_id": trace["trace_id"], "endpoint": hit[0]}, "confidence": 0.9}
    return {"decision": "allow", "reasons": ["stub: not in any trace"], "evidence": {}, "confidence": 0.5}
