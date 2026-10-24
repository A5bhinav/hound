"""Label DB: public exchange / service labels + OFAC SDN addresses. Nothing from the DOJ case.

label(chain, address) -> {"name", "kind", "source", ...extras} | None
  kind: exchange_hot | exchange_deposit | ofac | service
  extras: "exchange" (venue name, for exchange kinds), "category" (mixer | bridge | swap_service |
          otc | fiat_gateway, for service)

Data files are built by `python -m hound.chain.build_labels` into data/labels/.
Loading fails loudly (HoldoutViolation) if any DOJ holdout address is in them.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from . import holdout
from .cache import REPO_ROOT

log = logging.getLogger("hound.chain.labels")

LABEL_DIR = REPO_ROOT / "data" / "labels"

# Hand-checked additions (address -> label). Keep tiny, cite a public source for each.
MANUAL: dict[str, dict[str, dict]] = {
    "ethereum": {},
    "tron": {},
}


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, dict]]:
    db: dict[str, dict[str, dict]] = {"ethereum": {}, "tron": {}}
    eth_file = LABEL_DIR / "ethereum.json"
    if eth_file.exists():
        db["ethereum"].update(json.loads(eth_file.read_text())["labels"])
    else:
        log.error("missing %s: run `python -m hound.chain.build_labels`; no exchange labels loaded", eth_file)
    tron_file = LABEL_DIR / "tron.json"
    if tron_file.exists():
        db["tron"].update(json.loads(tron_file.read_text())["labels"])

    ofac_file = LABEL_DIR / "ofac.json"
    if ofac_file.exists():
        ofac = json.loads(ofac_file.read_text())
        for chain in ("ethereum", "tron"):
            for a in ofac.get(chain, []):
                # OFAC wins over any exchange label
                db[chain][a] = {"name": "OFAC SDN sanctioned address", "kind": "ofac", "source": "ofac_sdn"}
    else:
        log.error("missing %s: no OFAC labels loaded", ofac_file)

    for chain, extra in MANUAL.items():
        db[chain].update(extra)

    bad = [f"{a} ({holdout.matches(a)})" for a in db["ethereum"] if holdout.matches(a)]
    if bad:
        raise holdout.HoldoutViolation(
            f"label DB contains DOJ holdout addresses, the DOJ match would not be blind: {bad[:10]}")
    return db


def label(chain: str, address: str) -> dict | None:
    if not address:
        return None
    key = address.lower() if chain == "ethereum" else address
    hit = _load().get(chain, {}).get(key)
    return dict(hit) if hit else None


def is_exchange(chain: str, address: str) -> bool:
    lb = label(chain, address)
    return bool(lb and lb["kind"] in ("exchange_hot", "exchange_deposit"))


def all_labels(chain: str) -> dict[str, dict]:
    return _load().get(chain, {})


def reload() -> None:
    _load.cache_clear()
    holdout.load.cache_clear()
