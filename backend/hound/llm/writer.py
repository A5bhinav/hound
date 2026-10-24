"""Case writer (Ishaan, BRIEF 4.4 / 4.7).

The packet goes to law enforcement, so a made-up number is a liability. Design:
1. `facts(trace)` turns the Trace into the only strings the packet may contain
   (formatted amounts, addresses, tx hashes, dates).
2. A deterministic template always produces a correct packet.
3. If ANTHROPIC_API_KEY is set, Claude rewrites the victim summary in plain English
   from those facts only. `uncited(text, facts)` rejects the draft if it contains any
   number, address or hash that is not in the facts, and we fall back to the template.
"""
import json
import logging
import os
import re

log = logging.getLogger("hound.writer")

MODEL = os.environ.get("HOUND_WRITER_MODEL", "claude-sonnet-5-5")
_HEX = re.compile(r"0x[0-9a-fA-F]{6,}")
_SHORT = re.compile(r"(0x[0-9a-fA-F]+)…([0-9a-fA-F]+)")
_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def money(x):
    return f"{x:,.0f}"


def short(addr):
    return f"{addr[:8]}…{addr[-6:]}"


def facts(trace, case=None):
    ends = sorted(trace["endpoints"], key=lambda e: -e["victim_inflow"])
    victims = {n["address"] for n in trace["nodes"] if n["kind"] == "victim"}
    sent = sum(e["attributed_amount"] for e in trace["edges"] if e["from"] in victims)
    f = {
        "case_id": trace["case_id"],
        "replay": bool(trace.get("replay")),
        "method": f"{trace['method']['accounting']}, max {trace['method']['max_hops']} hops",
        "victim_sent_usdt": money(sent),
        "wallets_in_trace": str(len(trace["nodes"])),
        "hops": str(max((n["depth"] for n in trace["nodes"]), default=0)),
        "endpoints": [{
            "address": e["address"], "short": short(e["address"]), "reason": e["reason"],
            "victim_inflow_usdt": money(e["victim_inflow"]),
            "frozen_at": next((n["frozen"]["frozen_at"] for n in trace["nodes"]
                               if n["address"] == e["address"] and n.get("frozen")), None),
            "freezable": e["freezable"], "exchange": e.get("exchange"),
        } for e in ends],
        "tx_hashes": sorted({h for e in trace["edges"] for h in e["tx_hashes"]}),
    }
    f["tx_count"] = str(len(f["tx_hashes"]))
    return f


def allowed_tokens(f):
    """Every number / hex string the packet is allowed to contain."""
    blob = json.dumps(f)
    toks = set(_HEX.findall(blob)) | set(_NUM.findall(blob))
    for e in f["endpoints"]:
        toks.add(e["short"].split("…")[0])
    return {t.lower() for t in toks}


def uncited(text, f):
    """Return the numbers / hex strings in `text` that are not in the facts. Empty = clean."""
    ok = allowed_tokens(f)
    bad = []
    full = [t for t in ok if t.startswith("0x")]
    for m in _SHORT.finditer(text):  # 0x4e5cda…47abb5 must be a real address from the facts
        pre, suf = m.group(1).lower(), m.group(2).lower()
        if not any(a.startswith(pre) and a.endswith(suf) for a in full):
            bad.append(m.group(0))
    text = _SHORT.sub(" ", text)
    found = set(_HEX.findall(text)) | set(_NUM.findall(text))
    for t in found:
        tl = t.lower()
        if tl in ok or any(tl in a for a in ok if len(tl) >= 6):  # shortened addresses / hashes
            continue
        if tl.isdigit() and int(tl) <= 31:  # day-of-month, "3 wallets", list numbering
            continue
        bad.append(t)
    return sorted(bad)


def template(f, audience):
    lines = []
    if f["replay"]:
        lines.append("REPLAY of a historical public case. These funds were already frozen; nothing here is sitting unfrozen today.")
    if audience == "victim":
        lines.append(f"We followed the {f['victim_sent_usdt']} USDT you sent through {f['wallets_in_trace']} wallets.")
        for e in f["endpoints"]:
            where = {"frozen": f"was frozen by Tether ({e['frozen_at']})", "exchange": f"reached the exchange {e['exchange']}",
                     "holding": "is still sitting in a wallet", "max_hops": "went further than we followed",
                     "dead_end": "went somewhere we can't follow", "dust": "was a tiny amount"}[e["reason"]]
            lines.append(f"- {e['victim_inflow_usdt']} USDT {where}: {e['short']}")
        lines.append("Hound never asks for money, keys or seed phrases. Anyone who does is a scammer.")
    else:
        lines.append(f"Case {f['case_id']}. Method: {f['method']}. Reported, not proven.")
        lines.append(f"Victim funds traced: {f['victim_sent_usdt']} USDT across {f['wallets_in_trace']} wallets, {f['hops']} hops.")
        for e in f["endpoints"]:
            extra = f", frozen {e['frozen_at']}" if e["frozen_at"] else ""
            extra += ", FREEZABLE NOW" if e["freezable"] else ""
            extra += f", exchange {e['exchange']}" if e["exchange"] else ""
            lines.append(f"- {e['address']}: {e['victim_inflow_usdt']} USDT attributed ({e['reason']}{extra})")
        lines.append(f"Underlying transactions: {f['tx_count']} (full list in the trace object).")
    return "\n".join(lines)


def _claude(f, audience):
    import anthropic
    client = anthropic.Anthropic()
    prompt = (
        f"Write a short, calm, plain-English summary for a {'scam victim, possibly elderly and scared' if audience == 'victim' else 'police detective'} "
        "of where their money went. Use ONLY the facts in this JSON. Copy numbers and addresses exactly as written. "
        "Do not add any number, date, address or claim that is not in the JSON. If replay is true, say clearly this is a historical case. "
        f"End by saying Hound never asks for money, keys or seed phrases.\n\nFACTS:\n{json.dumps(f, indent=1)}"
    )
    msg = client.messages.create(model=MODEL, max_tokens=600, messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


def write_case(trace, case, audience="victim"):
    if audience not in ("victim", "detective"):
        raise ValueError(f"audience must be victim or detective, got {audience!r}")
    f = facts(trace, case)
    text, source = template(f, audience), "template"
    if audience == "victim" and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            draft = _claude(f, audience)
            bad = uncited(draft, f)
            if bad:
                log.warning("writer draft rejected, uncited tokens %s; using template", bad[:5])
            else:
                text, source = draft, "claude"
        except Exception as e:  # network / credits / model errors must not break the packet
            log.error("writer Claude call failed, using template: %s", e)
    bad = uncited(text, f)
    if bad:
        raise AssertionError(f"packet contains uncited tokens {bad[:5]}; this is a writer bug")
    return {"text": text, "cited": ["endpoints", "edges.tx_hashes", "nodes.frozen", "method"], "source": source}
