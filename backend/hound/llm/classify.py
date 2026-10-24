"""Address classifier (Ishaan, BRIEF 4.4a).

Exchange deposit addresses are usually unlabelled, so we spot them by behaviour:
many unrelated senders, and almost everything swept onward to one address soon after.
That pattern alone is NOT enough: a scam's collection wallet looks identical (DOJ's A-1
has 7 senders and sweeps onward within hours). The deciding signal is that a real
deposit address sweeps into a LABELLED exchange hot wallet, so `rules()` needs the
label of the sweep destination.
`features()` is plain code. `rules()` is the only thing the engine stops on (BRIEF §0:
the classifier is an opinion, never a stop). `classify()` is display only: it keeps the
rule's kind and confidence and, if ANTHROPIC_API_KEY is set, takes Claude's wording of the
reasons. Claude never changes a kind or a confidence, so reruns stay deterministic and a
third-party label name in the prompt cannot steer anything.
"""
import json
import logging
import os
from statistics import median

log = logging.getLogger("hound.classify")
MODEL = os.environ.get("HOUND_CLASSIFY_MODEL", "claude-sonnet-5-5")
KINDS = {"exchange_deposit", "exchange_hot", "personal", "service", "unknown"}
_cache = {}


def _hours(a, b):
    from datetime import datetime
    f = "%Y-%m-%dT%H:%M:%SZ"
    return (datetime.strptime(b, f) - datetime.strptime(a, f)).total_seconds() / 3600


def features(address, transfers):
    ins = [t for t in transfers if t["to"] == address]
    outs = [t for t in transfers if t["from"] == address]
    out_by = {}
    for t in outs:
        out_by[t["to"]] = out_by.get(t["to"], 0.0) + t["amount"]
    total_out = sum(out_by.values())
    top = max(out_by.values()) if out_by else 0.0
    holds = []
    for t in ins:
        nxt = next((o for o in outs if o["time"] >= t["time"]), None)
        if nxt:
            holds.append(_hours(t["time"], nxt["time"]))
    times = sorted(t["time"] for t in transfers) or [None]
    return {
        "address": address,
        "n_in": len(ins), "n_out": len(outs),
        "distinct_senders": len({t["from"] for t in ins}),
        "distinct_recipients": len(out_by),
        "total_in": round(sum(t["amount"] for t in ins), 2),
        "total_out": round(total_out, 2),
        "top_recipient_share": round(top / total_out, 3) if total_out else 0.0,
        "top_recipient": max(out_by, key=out_by.get) if out_by else None,
        "median_hold_hours": round(median(holds), 2) if holds else None,
        "first_seen": times[0], "last_seen": times[-1],
        "truncated": len(transfers) >= 10000,
    }


def rules(f, top_label=None):
    """top_label: label() of f['top_recipient'], or None."""
    if f["truncated"] or f["n_in"] + f["n_out"] >= 5000:
        return {"kind": "exchange_hot", "confidence": 0.6,
                "reasons": [f"very high volume ({f['n_in'] + f['n_out']} transfers): looks like a hot wallet or service"]}
    sweep = (f["distinct_senders"] >= 5 and f["distinct_recipients"] <= 2 and f["top_recipient_share"] >= 0.95
             and f["median_hold_hours"] is not None and f["median_hold_hours"] <= 24)
    if sweep and top_label and top_label.get("kind") == "exchange_hot":
        return {"kind": "exchange_deposit", "confidence": 0.85,
                "reasons": [f"{f['distinct_senders']} different senders",
                            f"{f['top_recipient_share']:.0%} of outflow swept to {top_label.get('name')}",
                            f"median {f['median_hold_hours']}h before sweep"]}
    if sweep:
        return {"kind": "unknown", "confidence": 0.5,
                "reasons": ["collects from many senders and sweeps to one wallet that is not a known exchange: "
                            "could be a scam collection wallet, keep tracing"]}
    return {"kind": "unknown", "confidence": 0.5, "reasons": ["no exchange-like pattern"]}


def _claude(f, floor):
    import anthropic
    prompt = (
        "Classify this blockchain address from its USDT transfer behaviour. Kinds: exchange_deposit, exchange_hot, "
        "personal, service, unknown. A deterministic rule said: " + json.dumps(floor) + ". Explain in up to 3 short "
        "reasons that cite the numbers below exactly. Reply with JSON only: {\"kind\":..,\"confidence\":0-1,\"reasons\":[..]}"
        "\n\nFEATURES:\n" + json.dumps({k: v for k, v in f.items() if k not in ("address", "top_recipient")})
    )
    msg = anthropic.Anthropic(timeout=8, max_retries=0).messages.create(model=MODEL, max_tokens=300, messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    out = json.loads(text[text.index("{"): text.rindex("}") + 1])
    if out.get("kind") not in KINDS:
        raise ValueError(f"classifier returned unknown kind {out.get('kind')!r}")
    return out


def classify(f, top_label=None, use_llm=True):
    """Display opinion. kind and confidence are always the rule's; Claude may only reword reasons."""
    floor = rules(f, top_label)
    key = (f["address"], json.dumps(floor, sort_keys=True))
    if key in _cache:
        return _cache[key]
    result = floor
    if use_llm and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            llm = _claude(f, floor)
            reasons = [str(r) for r in (llm.get("reasons") or [])][:3]
            if llm["kind"] != floor["kind"]:  # its reasons argue for another kind; keep the rule's
                log.warning("classifier: Claude said %s for %s, rules said %s; keeping the rules",
                            llm["kind"], f["address"], floor["kind"])
            elif reasons:
                result = {**floor, "reasons": reasons}
        except Exception as e:
            log.error("classifier Claude call failed for %s, using rules: %s", f["address"], e)
    _cache[key] = result
    return result
