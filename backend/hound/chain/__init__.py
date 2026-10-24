"""Chain data for Hound (brief v3 §8.4). Function names here are the shared contract.

    from hound.chain import get_transfers, get_balance, freeze_status, freeze_events, label

Every call is disk-cached (cache/), retried with back-off, and fails loudly with ChainAPIError.
Empty results are retried once and logged. Counters for Trace.stats: stats() / reset_stats().
"""

from __future__ import annotations

from . import freezes as _freezes
from . import labels as _labels
from .cache import CacheMiss
from .net import ChainAPIError, RateLimited, TooManyTransfers, reset_stats, stats

CHAINS = ("ethereum", "tron")


def _adapter(chain: str):
    if chain == "ethereum":
        from . import eth
        return eth
    if chain == "tron":
        from . import tron
        return tron
    raise ValueError(f"unknown chain {chain!r}; expected one of {CHAINS}")


def get_transfers(chain: str, address: str, token: str | None = "USDT", as_of: int | str | None = None,
                  after: str | None = None, before: str | None = None, include_zero: bool = False) -> list[dict]:
    """Transfers in and out of `address`, oldest first:
    [{"chain","tx_hash","from","to","token","amount","time","block",
      "amount_base" (int), "decimals", "contract", "tx_index", "log_index", "kind"}]

    token:  "USDT" (default) | "ETH" | a token contract | None (every ERC-20 / TRC-20)
    as_of:  inclusive cutoff, a block number (int) or an ISO time (replay: case.data_cutoff_block)
    after / before: ISO time bounds (inclusive)
    Zero-value and self transfers are dropped (address-poisoning lookalikes, AUDIT N2) unless
    include_zero=True. Raises TooManyTransfers (a ChainAPIError) for exchange-sized addresses.
    """
    if isinstance(as_of, str):
        before = as_of if before is None else min(before, as_of)
    elif as_of is not None and chain == "tron":
        raise ValueError("tron transfers have no block numbers; pass as_of as an ISO time")
    rows = _adapter(chain).get_transfers(address, token=token, before=before, after=after)
    out = []
    for t in rows:
        if isinstance(as_of, int) and t.get("block") is not None and t["block"] > as_of:
            continue
        base = int(t.get("amount_raw") or 0)
        if not include_zero and (base == 0 or t["from"] == t["to"]):
            continue
        t["amount_base"] = base
        t.setdefault("tx_index", None)
        t.setdefault("kind", "native" if t.get("token") in ("ETH", "TRX") else
                     ("trc20" if chain == "tron" else "erc20"))
        out.append(t)
    return out


def get_native_txs(chain: str, address: str, as_of: int | str | None = None, after: str | None = None) -> list[dict]:
    """Native ETH txs touching `address`: {tx_hash, tx_index, from, to, amount_wei, gas_wei, block, time}
    (same shape as hound.fixture_chain). Ethereum only."""
    if chain != "ethereum":
        raise ValueError(f"native txs are only supported on ethereum, not {chain}")
    from . import eth
    return eth.get_native_txs(address, as_of=as_of, after=after)


def get_balance(chain: str, address: str, token: str = "USDT", block: int | None = None) -> float:
    """Whole-token balance; block=None is latest, a block number reads state then (archive RPC).
    Replays should pass case.data_cutoff_block: today's balances leak DOJ's seizure (AUDIT issue 3)."""
    if block is not None and chain == "tron":
        raise ValueError("historical Tron balances are not supported")
    return _adapter(chain).get_balance(address, token=token) if block is None else \
        _adapter(chain).get_balance(address, token=token, block=block)


def freeze_status(chain: str, address: str, as_of: int | str | None = None) -> dict:
    """{"is_frozen", "frozen_at", "freeze_tx", "status": frozen|unfrozen|destroyed|none} (+ destroyed_usdt etc.).
    as_of (block or ISO time) = state at that point, from the event history only."""
    _adapter(chain)
    return _freezes.freeze_status(chain, address, as_of=as_of)


def freeze_events(chain: str, after: str | None = None, before: str | None = None) -> list[dict]:
    """[{"address","frozen_at","freeze_tx","block"}], oldest first."""
    _adapter(chain)
    return _freezes.freeze_events(chain, after=after, before=before)


def label(chain: str, address: str) -> dict | None:
    """{"name","kind": exchange_hot|exchange_deposit|ofac|service,"source"} or None."""
    return _labels.label(chain, address)


def is_exchange(chain: str, address: str) -> bool:
    return _labels.is_exchange(chain, address)


__all__ = ["get_transfers", "get_native_txs", "get_balance", "freeze_status", "freeze_events", "label", "is_exchange",
           "ChainAPIError", "RateLimited", "CacheMiss", "TooManyTransfers", "stats", "reset_stats", "CHAINS"]
