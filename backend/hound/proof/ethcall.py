"""Minimal direct Ethereum reads used by proof/ until chain/ (Jinka) exists.

USDT balanceOf and isBlackListed via eth_call on public RPCs. Deterministic, no key.
"""
from __future__ import annotations

import json
import time
import urllib.request

USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
RPCS = ["https://ethereum-rpc.publicnode.com", "https://eth.blockscout.com/api/eth-rpc", "https://cloudflare-eth.com"]
SEL_BALANCE_OF = "0x70a08231"
SEL_IS_BLACKLISTED = "0xe47d6060"  # keccak("isBlackListed(address)")[:4]


def rpc(method: str, params: list, tries: int = 6) -> dict:
    last = None
    for i in range(tries):
        url = RPCS[i % len(RPCS)]
        try:
            req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": "hound"})
            with urllib.request.urlopen(req, timeout=60) as r:
                out = json.load(r)
            if "error" in out:
                last = out["error"]
                time.sleep(1)
                continue
            return out
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(1 + i)
    raise RuntimeError(f"eth rpc {method} failed: {last}")


def _pad(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def usdt_balance(address: str) -> float:
    r = rpc("eth_call", [{"to": USDT, "data": SEL_BALANCE_OF + _pad(address)}, "latest"])
    return int(r["result"], 16) / 1e6


def usdt_is_blacklisted(address: str) -> bool:
    r = rpc("eth_call", [{"to": USDT, "data": SEL_IS_BLACKLISTED + _pad(address)}, "latest"])
    return int(r["result"], 16) == 1
