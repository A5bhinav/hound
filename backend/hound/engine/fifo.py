"""FIFO taint propagation over a set of transfers (BRIEF 4.3).

Every explored address keeps a FIFO queue of lots. A lot is (amount, tainted).
Inflows from a victim send are fully tainted. Inflows from another explored address
carry whatever taint that address's FIFO dequeue produced. Inflows from anywhere else
are clean. An outflow dequeues oldest lots first; if the queue runs dry (funds that
arrived before our window), the rest of the outflow is treated as clean.

This is the accounting DOJ used for its named victims in 1:25-cv-00386.
Cycles need no special case: tainted funds that flow back into an address are
just new lots on its queue.
"""
from collections import defaultdict, deque

EPS = 1e-9


def order_key(t):
    return (t.get("block") or 0, t.get("log_index") or 0, t["time"], t["tx_hash"])


def propagate(transfers, explored, seeds):
    """Run FIFO over `transfers` (deduped, any order) for the `explored` address set.

    seeds: set of (tx_hash, to) pairs that are victim sends (fully tainted).
    Returns per-address and per-edge taint totals.
    """
    queues = defaultdict(deque)
    tainted_in = defaultdict(float)     # total tainted inflow per address
    edge_taint = defaultdict(float)     # (from, to) -> tainted amount moved
    edge_total = defaultdict(float)
    edge_txs = defaultdict(list)
    edge_times = defaultdict(list)

    for t in sorted(transfers, key=order_key):
        src, dst, amt = t["from"], t["to"], float(t["amount"])
        if amt <= 0 or src == dst:
            continue
        if (t["tx_hash"], dst) in seeds:
            tainted = amt
        elif src in explored:
            tainted = _dequeue(queues[src], amt)
        else:
            tainted = 0.0
        if src in explored or (t["tx_hash"], dst) in seeds:
            key = (src, dst)
            edge_total[key] += amt
            edge_taint[key] += tainted
            edge_txs[key].append(t["tx_hash"])
            edge_times[key].append(t["time"])
        if dst in explored:
            queues[dst].append([amt, tainted])
            tainted_in[dst] += tainted

    remaining = {a: sum(l[1] for l in q) for a, q in queues.items()}
    return {
        "tainted_in": dict(tainted_in),
        "remaining_tainted": remaining,
        "edge_taint": dict(edge_taint),
        "edge_total": dict(edge_total),
        "edge_txs": dict(edge_txs),
        "edge_times": dict(edge_times),
    }


def _dequeue(queue, amount):
    """Take `amount` off the front of the queue; return how much of it was tainted."""
    tainted = 0.0
    need = amount
    while need > EPS and queue:
        lot = queue[0]
        take = min(need, lot[0])
        frac = lot[1] / lot[0] if lot[0] > EPS else 0.0
        tainted += take * frac
        lot[0] -= take
        lot[1] -= take * frac
        need -= take
        if lot[0] <= EPS:
            queue.popleft()
    return tainted
