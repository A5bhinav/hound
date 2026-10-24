"""ETH seeds → USDT lots through same-transaction swaps (AUDIT issue 1, N6).

A.H. paid ETH. Her pass-through d95 sent it to A-1, B-1 and C-1, and each of those swapped
ETH for USDT. On-chain, every swap is one transaction: ETH goes out of the swap address and
USDT comes back in the same tx. So, at each swap address:

1. Replay its native ETH history in chain order with FIFO lots (wei, seed_id). The victim's
   sends are seeded lots; any other ETH in is clean. Gas paid by the address is an outflow too.
2. For every ETH-out that has a USDT transfer in the same tx, the ETH lots it consumed are
   converted to USDT at the realised rate: each seed gets floor(usdt * seed_wei / eth_out),
   and the rounding remainder stays clean, so conservation holds to the base unit.
3. ETH-outs with no USDT in the same tx are reported as `swap_unresolved`, never dropped.

Output feeds `fifo.propagate` as multi-seed lots keyed by (tx_hash, usdt_recipient).
"""
from collections import defaultdict, deque

from hound.engine.fifo import _dequeue, to_base


def resolve_eth_seeds(sends, native_txs, usdt_transfers):
    """sends: case sends with token ETH, each with a seed_id.
    native_txs: native txs touching the swap addresses ({tx_hash, from, to, amount_wei, gas_wei, block, tx_index, time}).
    usdt_transfers: USDT transfers (to find the same-tx USDT leg).
    Returns {"seeds": {(tx, to): [(seed_id, base)]}, "swaps": [...], "unresolved": [...], "gas": {seed: wei}}.
    """
    by_seed_tx = {(s["tx_hash"], s["to"]): s["seed_id"] for s in sends}
    swap_addrs = sorted({s["to"] for s in sends})
    usdt_by_tx = defaultdict(list)
    for t in usdt_transfers:
        usdt_by_tx[t["tx_hash"]].append(t)

    seeds, swaps, unresolved = {}, [], []
    gas = defaultdict(int)
    for x in swap_addrs:
        rows = sorted({(r["tx_hash"], r["from"], r["to"]): r for r in native_txs if x in (r["from"], r["to"])}.values(),
                      key=lambda r: (r["block"], r.get("tx_index") or 0))
        q = deque()
        for r in rows:
            wei = int(r["amount_wei"])
            if r["to"] == x and r["from"] != x and wei > 0:
                q.append([wei, by_seed_tx.get((r["tx_hash"], x))])
                continue
            if r["from"] != x:
                continue
            fee = int(r.get("gas_wei") or 0)
            if fee:
                for sid, w in _dequeue(q, fee):
                    if sid:
                        gas[sid] += w
            if wei <= 0:
                continue
            parts = _dequeue(q, wei)
            seeded = [(sid, w) for sid, w in parts if sid]
            legs = [t for t in usdt_by_tx.get(r["tx_hash"], []) if t["from"] != x and to_base(t) > 0]
            mine = [t for t in legs if t["to"] == x] or legs  # aggregators may route the USDT elsewhere
            if not seeded:
                continue
            if not mine:
                unresolved.append({"address": x, "tx_hash": r["tx_hash"], "eth_out_wei": wei,
                                   "by_seed_wei": _sum(seeded)})
                continue
            usdt = sum(to_base(t) for t in mine)
            recipient = max(mine, key=to_base)["to"]
            by_seed_usdt = {sid: usdt * w // wei for sid, w in _sum(seeded).items()}
            key = (r["tx_hash"], recipient)
            seeds[key] = sorted(by_seed_usdt.items())
            swaps.append({"address": x, "tx_hash": r["tx_hash"], "time": r["time"], "recipient": recipient,
                          "eth_out_wei": wei, "usdt_in_base": usdt,
                          "by_seed_wei": _sum(seeded), "by_seed_usdt_base": by_seed_usdt})
    return {"seeds": seeds, "swaps": swaps, "unresolved": unresolved, "gas": dict(gas)}


def _sum(parts):
    out = defaultdict(int)
    for sid, w in parts:
        out[sid] += w
    return dict(out)
