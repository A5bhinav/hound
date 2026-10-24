"""FIFO taint propagation over a set of transfers (BRIEF 4.3, AUDIT issue 7).

One global replay, in chain order (block, log_index), over every transfer that
touches an explored address. Every explored address keeps a FIFO queue of lots
`[amount_base, seed_id]`; seed_id None means clean money (opening balance or outside
inflow). A victim send creates a lot tagged with its seed. An outflow takes the oldest
lots first; if the queue runs dry (money that arrived before our window), the rest is
clean. Cycles need nothing special: money that comes back is just a new lot.

Amounts are integers in base units (USDT = 6 decimals) so lots never drift.
"""
from collections import defaultdict, deque

DECIMALS = 6


def to_base(t):
    if t.get("amount_base") is not None:
        return int(t["amount_base"])
    return int(round(float(t["amount"]) * 10 ** DECIMALS))


def from_base(x):
    return round(x / 10 ** DECIMALS, DECIMALS)


def order_key(t):
    """log_index is unique within an Ethereum block, so (block, log_index) is the chain order on its
    own. tx_index is left out: some sources omit it, and None sorting as 0 would misorder a block.
    Rows without log_index sort after the indexed rows of their block (the engine flags them)."""
    li = t.get("log_index")
    return (t.get("block") or 0, li is None, li or 0, t["time"], t["tx_hash"])


def propagate(transfers, explored, seeds):
    """seeds: {(tx_hash, to): seed_id | [(seed_id, base_units)]}. Returns per-seed totals."""
    queues = defaultdict(deque)
    tainted_in = defaultdict(lambda: defaultdict(int))      # address -> seed -> base units in
    edge_seed = defaultdict(lambda: defaultdict(int))       # (from, to) -> seed -> base units
    edge_total = defaultdict(int)
    edge_txs = defaultdict(list)
    edge_times = defaultdict(list)
    seeded = defaultdict(int)
    alloc = {}  # swap key -> {seed_id: base units not yet handed out}; consumed across split-route legs

    for t in sorted(transfers, key=order_key):
        src, dst, amt = t["from"], t["to"], to_base(t)
        if amt <= 0 or src == dst:
            continue
        seed = seeds.get((t["tx_hash"], dst))
        if isinstance(seed, str):
            parts = [(seed, amt)]
            seeded[seed] += amt
        elif seed:  # multi-seed lot from a swap: [(seed_id, base)], remainder is clean
            # A split-route swap pays the recipient in several legs of one tx, all under this key.
            # Hand the allocation out across the legs in chain order; never more than a leg carries.
            left = alloc.setdefault((t["tx_hash"], dst), {sid: a for sid, a in seed if a > 0})
            parts, rest = [], amt
            for sid in sorted(left):
                take = min(left[sid], rest)
                if take > 0:
                    parts.append((sid, take))
                    seeded[sid] += take
                    left[sid] -= take
                    rest -= take
            if rest:
                parts.append((None, rest))
        elif src in explored:
            parts = _dequeue(queues[src], amt)
        else:
            parts = [(None, amt)]
        if src in explored or seed is not None:
            key = (src, dst)
            edge_total[key] += amt
            edge_txs[key].append(t["tx_hash"])
            edge_times[key].append(t["time"])
            for s, a in parts:
                if s is not None:
                    edge_seed[key][s] += a
        if dst in explored:
            for s, a in parts:
                if a:
                    queues[dst].append([a, s])
                if s is not None:
                    tainted_in[dst][s] += a

    remaining = {a: _by_seed(q) for a, q in queues.items()}
    return {
        "tainted_in": {a: dict(v) for a, v in tainted_in.items()},
        "remaining": remaining,
        "edge_seed": {k: dict(v) for k, v in edge_seed.items()},
        "edge_total": dict(edge_total),
        "edge_txs": dict(edge_txs),
        "edge_times": dict(edge_times),
        "seeded": dict(seeded),
    }


def _by_seed(queue):
    out = defaultdict(int)
    for amt, s in queue:
        if s is not None:
            out[s] += amt
    return dict(out)


def _dequeue(queue, amount):
    """Take `amount` base units off the front; return [(seed_id, amount)] in FIFO order."""
    parts = []
    need = amount
    while need > 0 and queue:
        lot = queue[0]
        take = min(need, lot[0])
        parts.append((lot[1], take))
        lot[0] -= take
        need -= take
        if lot[0] == 0:
            queue.popleft()
    if need > 0:
        parts.append((None, need))  # funds from before the window: clean
    return parts
