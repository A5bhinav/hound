"""Fixture chain: the BRIEF 8.4 chain functions served from examples/ohnd_transfers.json.

414 real Ethereum USDT transfers around DOJ case 1:25-cv-00386 (BigQuery). Used by tests,
and by the API until Jinka's hound.chain adapters are merged. Freeze status comes from
examples/usdt_freeze_events.json, Tether's public AddedBlackList events (not DOJ labels).
"""
import json
from functools import lru_cache

from hound.contracts import EXAMPLES

@lru_cache(maxsize=1)
def _freezes():
    """Tether's public AddedBlackList events for this window (chain data, like the transfers)."""
    return {e["address"]: (e["time"], e["tx_hash"]) for e in json.loads((EXAMPLES / "usdt_freeze_events.json").read_text())}


@lru_cache(maxsize=1)
def _all():
    return json.loads((EXAMPLES / "ohnd_transfers.json").read_text())


def get_transfers(chain, address, token=None, as_of=None, after=None):
    """as_of: a block number (inclusive) or an ISO time."""
    if chain != "ethereum":
        raise ValueError(f"fixture chain only has ethereum data, asked for {chain}")
    out = []
    for t in _all():
        if address not in (t["from"], t["to"]) or t["amount"] <= 0 or t["from"] == t["to"]:
            continue  # zero-value transfers are address-poisoning lookalikes (AUDIT N2)
        if after is not None and t["time"] < after:
            continue
        if isinstance(as_of, int) and t["block"] > as_of:
            continue
        if isinstance(as_of, str) and t["time"] > as_of:
            continue
        out.append(t)
    return out


@lru_cache(maxsize=1)
def _native():
    return json.loads((EXAMPLES / "ohnd_eth_txs.json").read_text())


def get_native_txs(chain, address, as_of=None, after=None):
    """Native ETH txs touching `address` (value, gas, block, tx_index), same filters as get_transfers."""
    if chain != "ethereum":
        raise ValueError(f"fixture chain only has ethereum data, asked for {chain}")
    return [t for t in _native() if address in (t["from"], t["to"])
            and (after is None or t["time"] >= after)
            and not (isinstance(as_of, int) and t["block"] > as_of)
            and not (isinstance(as_of, str) and t["time"] > as_of)]


def label(chain, address):
    return None  # holdout: no DOJ labels, and the fixture has no exchange labels


def freeze_status(chain, address):
    f = _freezes().get(address)
    return {"is_frozen": bool(f), "frozen_at": f[0] if f else None, "freeze_tx": f[1] if f else None}


def get_balance(chain, address, token="USDT"):
    return 0.0  # the frozen USDT was burned and reissued to law enforcement in Nov 2024
