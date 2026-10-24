"""check(chain, address): should an exchange withdrawal / wallet send to this address go through?
(brief v3.1 §0 item 9, AUDIT.md issue 13). A pure local lookup: labels from local files, freezes
from data/freezes_eth.json, the in-memory watchlist. No network calls.

Order of rules (rule_fired in the evidence):
  sanctioned        OFAC SDN                                     -> hold
  exchange          exchange-labelled                            -> allow (never held: blocks all users)
  infra             USDT contract, routers, canonical bridges    -> allow
  tether_frozen     Tether froze it                              -> hold (USDT sent there is stuck)
  service / mixer   labelled service                             -> allow with a note / warn for mixers
  watchlist rules   see watchlist.py                             -> hold | warn | allow
  no_data           nothing known                                -> allow, "no Hound data"
Invalid input raises ValueError (routes.py turns it into HTTP 400), never a silent allow.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .. import chain
from ..chain.eth import iso
from . import watchlist as wl

log = logging.getLogger("hound.watch.check")

DISCLAIMER = "reported, not proven"
EVIDENCE_TTL_S = 86400  # a decision is valid for a day; the UI should re-check after expires_at


def _norm(chain_name: str, address: str) -> str:
    if chain_name not in chain.CHAINS:
        raise ValueError(f"unknown chain {chain_name!r}")
    if chain_name == "ethereum":
        from ..chain.eth import norm
    else:
        from ..chain.tron import norm
    return norm(address)


def check(chain_name: str, address: str, watch: wl.Watchlist | None = None) -> dict[str, Any]:
    """-> {"decision": "allow|warn|hold", "reasons": [str], "evidence": {...}, "confidence": float}

    evidence = {watchlist_version, rule_fired, case_ids, label, path (<= 4 hops), victim_inflow_usdt,
                frozen, chainabuse {report_count, latest_at}, expires_at, disclaimer, chain, address}
    """
    t0 = time.monotonic()
    addr = _norm(chain_name, address)
    watch = watch or wl.default()
    lb = chain.label(chain_name, addr, network=False)
    entry = watch.lookup(chain_name, addr)
    evidence: dict[str, Any] = {
        "chain": chain_name, "address": addr, "watchlist_version": watch.version(), "rule_fired": None,
        "case_ids": entry["cases"] if entry else [], "label": lb,
        "path": entry["path"] if entry else [], "victim_inflow_usdt": round(entry["victim_inflow"], 6) if entry else 0.0,
        "frozen": None,
        "chainabuse": {"report_count": entry["reports"], "latest_at": entry["report_latest_at"]} if entry else
        {"report_count": 0, "latest_at": None},
        "expires_at": iso(time.time() + EVIDENCE_TTL_S), "disclaimer": DISCLAIMER,
    }

    def result(decision: str, rule: str, reasons: list[str], confidence: float) -> dict:
        evidence["rule_fired"] = rule
        evidence["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return {"decision": decision, "reasons": reasons, "evidence": evidence, "confidence": round(confidence, 2)}

    if lb and lb["kind"] == "sanctioned":
        return result("hold", "sanctioned", ["address is on the US Treasury OFAC sanctions list"], 0.99)
    if lb and lb["kind"] in ("exchange_hot", "exchange_deposit"):
        evidence["exchange"] = lb.get("exchange") or lb["name"]
        return result("allow", "exchange", [f"exchange-owned wallet ({lb['name']}): exchange wallets are never held"],
                      0.9)
    if lb and lb["kind"] == "infra":
        return result("allow", "infra", [f"infrastructure ({lb['name']}): never held"], 0.9)

    try:
        fz = chain.freeze_status(chain_name, addr, check_onchain=False)
    except (chain.ChainAPIError, chain.CacheMiss) as e:
        log.error("freeze lookup failed for %s: %s", addr, type(e).__name__)
        fz = None
        evidence["freeze_check_error"] = "freeze status unavailable"
    evidence["frozen"] = fz

    if fz and fz["is_frozen"]:
        reasons = [f"Tether froze this address on {fz['frozen_at'] or 'an unknown date'}: USDT sent here is stuck"]
        if entry:
            reasons += watch.decision(entry)[2]
        return result("hold", "tether_frozen", reasons, 0.95)

    if lb and lb["kind"] == "service":
        if lb.get("category") == "mixer":
            return result("warn", "mixer", [f"{lb['name']} is a mixer: funds sent here are very hard to recover"], 0.7)
        return result("allow", "service", [f"labelled service ({lb['name']}): never held"], 0.6)

    if entry:
        decision, rule, reasons = watch.decision(entry)
        return result(decision, rule, reasons, entry["confidence"])

    if fz is None:
        # fail closed-ish (REVIEW_TEAM security-public-4): unknown freeze state is a warning, never allow
        return result("warn", "freeze_unknown", ["freeze status could not be checked: not checked, do not rely "
                                                 "on this as clear"], 0.3)
    return result("allow", "no_data", ["no Hound data: not in any traced scam cluster, not frozen, not sanctioned"],
                  0.5)
