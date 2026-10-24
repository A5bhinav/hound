"""Label DB (AUDIT issue 12). Nothing from the DOJ case, ever.

label(chain, address) -> {"name", "kind", "source", ...extras} | None, first match wins:
  1. sanctioned   OFAC SDN (0xB10C lists): Ethereum = ETH + USDT 0x entries, Tron = TRX + USDT T...
                  check() holds; the engine keeps tracing through it
  2. infra        data/infra_allowlist.json (USDT contract, Tether Treasury, WETH, routers,
                  canonical bridges): never held, never expanded
  3. exchange_hot / exchange_deposit from the Blockscout metadata service (exchange, hot-wallet or
                  deposit-address tags; the "blocked" tag is ignored: freezes come only from
                  freeze_status). Cached for a week; skipped quietly when offline
  4. static data/labels/ethereum.json (brianleect slug allowlist, built by build_labels.py):
                  exchange_hot | exchange_deposit | service (mixer, bridge, deposit_funder, ...)
extras: "exchange" (venue name), "category" (for service / infra)

Holdout guard: the static files refuse to load if any DOJ holdout address is in them, and
holdout addresses never get a metadata label.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

from . import cache, holdout
from .cache import REPO_ROOT
from .net import ChainAPIError, count_cache_hit, request_json

log = logging.getLogger("hound.chain.labels")

LABEL_DIR = REPO_ROOT / "data" / "labels"
INFRA_FILE = REPO_ROOT / "data" / "infra_allowlist.json"
METADATA_URL = os.environ.get("BLOCKSCOUT_METADATA_URL", "https://metadata.services.blockscout.com/api/v1/metadata")
METADATA_TTL = 7 * 86400.0
EXCHANGE_KINDS = ("exchange_hot", "exchange_deposit")

# Hand-checked additions (address -> label). Keep tiny, cite a public source for each.
MANUAL: dict[str, dict[str, dict]] = {"ethereum": {}, "tron": {}}


def _key(chain: str, address: str) -> str:
    return address.lower() if chain == "ethereum" else address


@lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    db = {"static": {"ethereum": {}, "tron": {}}, "infra": {"ethereum": {}, "tron": {}},
          "sanctioned": {"ethereum": set(), "tron": set()}}
    eth_file = LABEL_DIR / "ethereum.json"
    if eth_file.exists():
        db["static"]["ethereum"].update(json.loads(eth_file.read_text())["labels"])
    else:
        log.error("missing %s: run `python -m hound.chain.build_labels`; no static exchange labels", eth_file)
    tron_file = LABEL_DIR / "tron.json"
    if tron_file.exists():
        db["static"]["tron"].update(json.loads(tron_file.read_text())["labels"])
    if INFRA_FILE.exists():
        infra = json.loads(INFRA_FILE.read_text())
        for chain in ("ethereum", "tron"):
            db["infra"][chain].update({_key(chain, a): v for a, v in infra.get(chain, {}).items()})
    else:
        log.error("missing %s: routers and the USDT contract are not protected", INFRA_FILE)
    ofac_file = LABEL_DIR / "ofac.json"
    if ofac_file.exists():
        ofac = json.loads(ofac_file.read_text())
        for chain in ("ethereum", "tron"):
            db["sanctioned"][chain] = {_key(chain, a) for a in ofac.get(chain, [])}
    else:
        log.error("missing %s: no OFAC labels loaded", ofac_file)
    for chain, extra in MANUAL.items():
        db["static"][chain].update({_key(chain, a): v for a, v in extra.items()})

    every = set(db["static"]["ethereum"]) | set(db["infra"]["ethereum"]) | db["sanctioned"]["ethereum"]
    bad = [f"{a} ({holdout.matches(a)})" for a in every if holdout.matches(a)]
    if bad:
        raise holdout.HoldoutViolation(
            f"label DB contains DOJ holdout addresses, the DOJ match would not be blind: {bad[:10]}")
    return db


def _metadata(address: str) -> dict | None:
    """Exchange label from the Blockscout metadata service, or None. Never raises."""
    if holdout.matches(address):
        return None

    def fetch():
        body = request_json("GET", METADATA_URL, params={"addresses": address, "chainId": 1}, retries=2)
        if not isinstance(body, dict) or "addresses" not in body:
            raise ChainAPIError(f"metadata service bad response: {str(body)[:200]}")
        return body

    try:
        body = cache.cached("blockscout_meta", {"address": address}, fetch=fetch, ttl=METADATA_TTL,
                            on_hit=count_cache_hit)
    except (cache.CacheMiss, ChainAPIError) as e:
        log.info("metadata label lookup skipped for %s: %s", address, e)
        return None
    entry = next((v for k, v in (body.get("addresses") or {}).items() if k.lower() == address), None)
    tags = [t for t in (entry or {}).get("tags", []) if t.get("slug") != "blocked"]
    generic = {t.get("slug") for t in tags if t.get("tagType") == "generic"}
    if not generic & {"exchange", "hot-wallet", "deposit-address"}:
        return None
    names = sorted((t for t in tags if t.get("tagType") == "name"), key=lambda t: -(t.get("ordinal") or 0))
    protocol = next((t.get("name") for t in tags if t.get("tagType") == "protocol"), None)
    exchange = protocol
    for t in names:
        try:
            exchange = exchange or json.loads(t.get("meta") or "{}").get("main_entity")
        except ValueError:
            pass
    name = names[-1]["name"] if names else (protocol or "exchange")  # most specific: lowest ordinal
    kind = "exchange_deposit" if "deposit-address" in generic else "exchange_hot"
    return {"name": name, "kind": kind, "source": "blockscout_metadata", "exchange": exchange or name}


def label(chain: str, address: str, network: bool = True) -> dict | None:
    """Label for `address`, or None. network=False skips the metadata service (pure local lookup)."""
    if not address:
        return None
    key = _key(chain, address)
    db = _load()
    if key in db["sanctioned"].get(chain, set()):
        return {"name": "OFAC SDN sanctioned address", "kind": "sanctioned", "source": "ofac_sdn"}
    if key in db["infra"].get(chain, {}):
        return dict(db["infra"][chain][key])
    if network and chain == "ethereum":
        meta = _metadata(key)
        if meta:
            return meta
    hit = db["static"].get(chain, {}).get(key)
    return dict(hit) if hit else None


def is_exchange(chain: str, address: str) -> bool:
    lb = label(chain, address)
    return bool(lb and lb["kind"] in EXCHANGE_KINDS)


def all_labels(chain: str) -> dict[str, dict]:
    """Static + infra labels (sanctioned addresses listed with kind "sanctioned")."""
    db = _load()
    out = dict(db["static"].get(chain, {}))
    out.update(db["infra"].get(chain, {}))
    out.update({a: {"name": "OFAC SDN sanctioned address", "kind": "sanctioned", "source": "ofac_sdn"}
                for a in db["sanctioned"].get(chain, set())})
    return out


def reload() -> None:
    _load.cache_clear()
    holdout.load.cache_clear()
