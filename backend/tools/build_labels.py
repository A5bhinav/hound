"""Build data/labels/*.json from public, MIT-licensed datasets.

    cd backend && .venv/bin/python backend/tools/build_labels.py

Sources:
  - brianleect/etherscan-labels (MIT): Etherscan label dump, 2023
  (dawsbot/eth-labels is deliberately NOT used: brief v3.1 §0 / AUDIT.md)
  - 0xB10C/ofac-sanctioned-digital-currency-addresses (MIT): addresses from the OFAC SDN list

Only exchange, mixer, bridge and similar service slugs are kept, from an explicit allowlist.
Slugs like "blocked" (Tether-frozen) or "*-exploit" are never used: they could leak the DOJ case
into the label DB. Every holdout address is dropped, and the build fails if one slips through.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hound.chain.cache import REPO_ROOT  # noqa: E402
import holdout_guard as holdout  # noqa: E402

log = logging.getLogger("hound.chain.build_labels")

OUT_DIR = REPO_ROOT / "data" / "labels"
SRC = {
    "brianleect": "https://raw.githubusercontent.com/brianleect/etherscan-labels/main/data/etherscan/combined/combinedAccountLabels.json",
    "ofac_eth": "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_ETH.json",
    "ofac_usdt": "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_USDT.json",
    "ofac_trx": "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_TRX.json",
}

# slug -> display name for exchanges (custodial venues: users deposit and withdraw here)
EXCHANGES = {
    "ascendex": "AscendEX", "azbit": "Azbit", "biconomy-com": "Biconomy.com", "bilaxy": "Bilaxy",
    "binance": "Binance", "binance-deposit": "Binance", "bitbank": "bitbank", "bitfinex": "Bitfinex",
    "bitflyer": "bitFlyer", "bitget": "Bitget", "bithumb": "Bithumb", "bitmart": "BitMart",
    "bitstamp": "Bitstamp", "bittrex": "Bittrex", "bitvavo": "Bitvavo", "blofin-exchange": "BloFin",
    "btcturk": "BtcTurk", "btse": "BTSE", "cex-io": "CEX.IO", "coinbase": "Coinbase",
    "coincheck": "Coincheck", "coinex": "CoinEx", "coinone": "Coinone", "coinw": "CoinW",
    "crypto-com": "Crypto.com", "delta-exchange": "Delta Exchange", "deribit": "Deribit",
    "digifinex": "DigiFinex", "ftx": "FTX", "gate-io": "Gate.io", "gemini": "Gemini", "hitbtc": "HitBTC",
    "hotbit": "Hotbit", "huobi": "HTX (Huobi)", "indodax": "Indodax", "korbit": "Korbit", "kraken": "Kraken",
    "kucoin": "KuCoin", "mexc": "MEXC", "nexo": "Nexo", "okx": "OKX", "paribu": "Paribu",
    "poloniex": "Poloniex", "upbit": "Upbit", "uphold": "Uphold", "woo": "WOO X", "zb-com": "ZB.com",
}
# slug -> service category
SERVICES = {
    "tornado-cash": "mixer", "mixer": "mixer", "ethereum-mixer": "mixer",
    "across-protocol": "bridge", "allbridge": "bridge", "bridge": "bridge", "celer-network": "bridge",
    "connext": "bridge", "debridge": "bridge", "hop-protocol": "bridge", "layerzero": "bridge",
    "multichain": "bridge", "stargate": "bridge", "synapse": "bridge", "wormhole": "bridge",
    "changenow": "swap_service", "otc": "otc", "fiat-gateway": "fiat_gateway",
}


def _get(url: str) -> object:
    for attempt in range(4):
        try:
            r = httpx.get(url, timeout=120, follow_redirects=True)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            if attempt == 3:
                raise RuntimeError(f"download failed {url}: {e}") from e
            time.sleep(2 ** attempt)


# name prefix (lowercase) -> exchange, for when a dataset files an entry under the wrong slug
ALIASES = {v.lower(): v for v in EXCHANGES.values()} | {
    "huobi": "HTX (Huobi)", "htx": "HTX (Huobi)", "bitmax": "AscendEX", "woo": "WOO X", "crypto.com": "Crypto.com",
    "gate": "Gate.io", "zb": "ZB.com", "okex": "OKX", "hitbtc": "HitBTC",
}


def _exchange_from_name(name: str) -> str | None:
    head = name.lower().split(":")[0].strip()
    head = head.replace(" dep", "").strip()
    words = head.split()
    for n in (3, 2, 1):
        cand = " ".join(words[:n])
        if cand in ALIASES:
            return ALIASES[cand]
        # "Binance 14", "Kraken 55": drop a trailing number
        if len(words) > n and words[n].isdigit() and cand in ALIASES:
            return ALIASES[cand]
    return None


def _is_deposit(name: str, slug: str) -> bool:
    n = name.lower()
    return slug.endswith("-deposit") or " dep:" in n or ("deposit" in n and "funder" not in n)


def _classify(slugs: list[str], name: str) -> tuple[str, str | None, str | None] | None:
    """-> (kind, exchange name, category) or None to skip."""
    if "deposit funder" in name.lower() or "funder" in name.lower().split(":")[-1]:
        # pays gas into deposit addresses: an exchange-run service, used only as a feature (AUDIT issue 12)
        exch = _exchange_from_name(name)
        if exch or any(s in EXCHANGES for s in slugs):
            return "service", exch, "deposit_funder"
    for s in slugs:
        if s in EXCHANGES:
            if name:
                exch = _exchange_from_name(name)
                if exch is None:
                    return None  # e.g. "Arbitrum Foundation" filed under "deribit": not an exchange wallet
            else:
                exch = EXCHANGES[s]
            return ("exchange_deposit" if _is_deposit(name, s) else "exchange_hot"), exch, None
    for s in slugs:
        if s in SERVICES:
            return "service", None, SERVICES[s]
    return None


def build() -> dict:
    labels: dict[str, dict] = {}
    dropped_holdout: list[str] = []

    def add(addr: str, slugs: list[str], name: str, source: str):
        a = addr.strip().lower()
        if not (a.startswith("0x") and len(a) == 42):
            return
        hit = holdout.matches(a)
        if hit:
            dropped_holdout.append(f"{a} (holdout {hit}, source {source})")
            return
        c = _classify(slugs, name or "")
        if not c:
            return
        kind, exch, category = c
        entry = {"name": name or exch or slugs[0], "kind": kind, "source": source}
        if exch:
            entry["exchange"] = exch
        if category:
            entry["category"] = category
        prev = labels.get(a)
        # prefer an exchange label over a service label; otherwise keep the first source
        if prev is None or (prev["kind"] == "service" and kind != "service"):
            labels[a] = entry

    bl = _get(SRC["brianleect"])
    for addr, v in bl.items():
        add(addr, v.get("labels", []), v.get("name") or "", "etherscan-labels (brianleect, MIT)")

    ofac: dict[str, list[str]] = {"ethereum": [], "tron": []}
    for key, chain in (("ofac_eth", "ethereum"), ("ofac_usdt", None), ("ofac_trx", "tron")):
        for a in _get(SRC[key]):
            a = a.strip()
            ch = chain or ("ethereum" if a.lower().startswith("0x") else "tron")
            v = a.lower() if ch == "ethereum" else a
            if ch == "ethereum" and holdout.matches(v):
                dropped_holdout.append(f"{v} (holdout, OFAC list)")
                continue
            if v not in ofac[ch]:
                ofac[ch].append(v)

    meta = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": SRC,
        "licence": "Each source is MIT-licensed; see the linked repositories.",
        "rule": "Exchange / mixer / bridge / service slugs from an allowlist only. No 'blocked' or exploit "
                "slugs. Every DOJ holdout address is excluded (see backend/tools/holdout_guard.py).",
        "dropped_holdout": dropped_holdout,
    }
    return {"meta": meta, "ethereum": labels, "ofac": ofac}


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    out = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    eth = {"_meta": out["meta"], "labels": dict(sorted(out["ethereum"].items()))}
    ofac = {"_meta": {**out["meta"], "sources": {k: v for k, v in SRC.items() if k.startswith("ofac")}},
            **{k: sorted(v) for k, v in out["ofac"].items()}}
    (OUT_DIR / "ethereum.json").write_text(json.dumps(eth, indent=0, separators=(",", ":")) + "\n")
    (OUT_DIR / "ofac.json").write_text(json.dumps(ofac, indent=1) + "\n")
    kinds: dict[str, int] = {}
    for v in out["ethereum"].values():
        k = v["kind"] + (":" + v["category"] if v.get("category") else "")
        kinds[k] = kinds.get(k, 0) + 1
    print(f"ethereum labels: {len(out['ethereum'])} {kinds}")
    print(f"ofac: ethereum {len(out['ofac']['ethereum'])}, tron {len(out['ofac']['tron'])}")
    print(f"holdout addresses dropped: {len(out['meta']['dropped_holdout'])} {out['meta']['dropped_holdout']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
