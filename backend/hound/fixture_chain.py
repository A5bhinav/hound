"""Fixture chain: the BRIEF 8.4 chain functions served from examples/ohnd_transfers.json.

414 real Ethereum USDT transfers around DOJ case 1:25-cv-00386 (BigQuery). Used by tests,
and by the API until Jinka's hound.chain adapters are merged. Freeze status comes from
Tether's public AddedBlackList events for the 3 wallets it froze (not from DOJ labels).
"""
import json
from functools import lru_cache

from hound.contracts import EXAMPLES

FREEZES = {
    "0xa1770ead287dc8e91631a7a323390d5b744f0021": ("2024-06-21T14:53:11Z", "0x5b124d778136157b2f9e27e5fc6179780598288a9f36be7bd558301068f48b7a"),
    "0xafd770d8898a0e323c607fe91358345e7b2378a5": ("2024-06-21T14:51:11Z", "0x547c5335f4887c8b06ef4f1eec7726404ad6c23ce8a9f794cd14d3e4d21da776"),
    "0x4e5cda8f0d772ac57e947545192a0657ad47abb5": ("2024-06-25T17:07:23Z", "0xa76529e1aa4576206a8c4c5fab2b136d94f24768b957dd7809de41bf9f55f4a5"),
}


@lru_cache(maxsize=1)
def _all():
    return json.loads((EXAMPLES / "ohnd_transfers.json").read_text())


def get_transfers(chain, address, token=None, before=None, after=None):
    if chain != "ethereum":
        raise ValueError(f"fixture chain only has ethereum data, asked for {chain}")
    return [t for t in _all() if address in (t["from"], t["to"])
            and (after is None or t["time"] >= after) and (before is None or t["time"] <= before)]


def label(chain, address):
    return None  # holdout: no DOJ labels, and the fixture has no exchange labels


def freeze_status(chain, address):
    f = FREEZES.get(address)
    return {"is_frozen": bool(f), "frozen_at": f[0] if f else None, "freeze_tx": f[1] if f else None}


def get_balance(chain, address, token="USDT"):
    return 0.0  # the frozen USDT was burned and reissued to law enforcement in Nov 2024
