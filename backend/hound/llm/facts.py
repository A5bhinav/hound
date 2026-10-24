"""Facts dict for the case writer (AUDIT issue 16, BRIEF §0).

`build_facts(trace, case)` returns the ONLY values a packet may cite, in five namespaces:

- `trace.*`   values copied from the Trace (engine output), type-checked.
- `case.*`    structured Case fields (times, sends), type-checked.
- `derived.*` values computed here by code (totals, counts, per-endpoint rows).
- `doj.*`     replay only, context: never scored, never a claim about a live case.
- `const.*`   fixed contacts and disclaimer strings.

Free text from outside (case_id, story, victim alias, exchange names) is sanitised and
lives only under `case.untrusted.*`. `citable(facts)` never returns anything under it,
so a crafted case id or story can not make a number or an address citable.

Paths address nested values with dots, list items by index: `derived.endpoints.0.address`.
"""
import logging
import re

log = logging.getLogger("hound.facts")

DOJ_CASE_NUMBER = "1:25-cv-00386"
CONTACTS = {
    "ic3": "https://www.ic3.gov",
    "tether": "Tether via law enforcement",
}
DISCLAIMERS = {
    "reported": "Reported, not proven.",
    "never_charges": "Hound never charges, never asks for keys or seed phrases; anyone offering paid recovery is a scam.",
}

_ETH_ADDR = re.compile(r"^0x[0-9a-f]{40}$")
_TRON_ADDR = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
_TX = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?Z)?$")
_ENUM = re.compile(r"^[a-z_]{1,32}$")
_SAFE_TEXT = re.compile(r"[^A-Za-z0-9 ,.'_-]")
_TOKEN = re.compile(r"^[A-Z0-9]{2,10}$")
_SOURCES = {"phone", "screenshot", "chainabuse", "doj_replay", "voice"}


def sanitize(text, limit=200):
    """Display-only free text: strip to safe characters, no tags, no braces, no links."""
    if text is None:
        return None
    return " ".join(_SAFE_TEXT.sub(" ", str(text)).split())[:limit]


def sanitize_label(text, limit=40):
    """Exchange labels are shown only in code-written lines: also drop hex and long digit runs."""
    text = sanitize(text, 200)
    if text is None:
        return None
    text = re.sub(r"0x[0-9A-Fa-f]*|\d{3,}", " ", text)
    return " ".join(text.split())[:limit] or None


def short_addr(addr):
    return f"{addr[:8]}…{addr[-6:]}" if len(addr) > 16 else addr


def _is_addr(v):
    return isinstance(v, str) and bool(_ETH_ADDR.match(v) or _TRON_ADDR.match(v))


def _num(v, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        if v is not None:
            log.warning("facts: dropping non-numeric %s=%r", where, v)
        return None
    return v


def _iso(v, where):
    if isinstance(v, str) and _ISO.match(v):
        return v
    if v is not None:
        log.warning("facts: dropping non-ISO time %s=%r", where, v)
    return None


def _enum(v, where):
    if isinstance(v, str) and _ENUM.match(v):
        return v
    if v is not None:
        log.warning("facts: dropping non-enum %s=%r", where, v)
    return None


def _addr(v, where):
    if _is_addr(v):
        return v
    if v is not None:
        log.warning("facts: dropping malformed address %s=%r", where, v)
    return None


def _tx(v, where):
    if isinstance(v, str) and _TX.match(v):
        return v
    if v is not None:
        log.warning("facts: dropping malformed tx hash %s=%r", where, v)
    return None


def _endpoint_rows(trace):
    nodes = {n["address"]: n for n in trace.get("nodes", [])}
    rows = []
    for i, e in enumerate(trace.get("endpoints", [])):
        addr = _addr(e.get("address"), f"endpoints.{i}.address")
        if addr is None:
            raise ValueError(f"trace endpoint {i} has malformed address {e.get('address')!r}; refusing to write a packet")
        frozen = (nodes.get(addr) or {}).get("frozen") or {}
        inflow = _num(e.get("victim_inflow"), f"endpoints.{i}.victim_inflow") or 0.0
        remaining = _num(e.get("victim_remaining"), f"endpoints.{i}.victim_remaining")
        rows.append({
            "address": addr,
            "short": short_addr(addr),
            "reason": _enum(e.get("reason"), f"endpoints.{i}.reason") or "unknown",
            "victim_inflow": inflow,
            "victim_funds": remaining if remaining is not None else inflow,
            "balance_usdt": _num(e.get("balance_usdt"), f"endpoints.{i}.balance_usdt"),
            "freezable": bool(e.get("freezable")),
            "is_frozen": bool(frozen.get("is_frozen")),
            "frozen_at": _iso(frozen.get("frozen_at"), f"nodes[{addr}].frozen_at"),
            "freeze_tx": _tx(frozen.get("freeze_tx"), f"nodes[{addr}].freeze_tx"),
            "_exchange": e.get("exchange"),
        })
    rows.sort(key=lambda r: (-r["victim_funds"], r["address"]))
    return rows


def build_facts(trace, case):
    """Facts for one packet. Raises if the trace is unusable; drops (and logs) malformed fields."""
    if not isinstance(trace, dict) or "endpoints" not in trace:
        raise ValueError("build_facts needs a Trace dict with endpoints")
    case = case or {}
    replay = bool(trace.get("replay")) or case.get("source") == "doj_replay"
    method = trace.get("method") or {}
    rows = _endpoint_rows(trace)
    nodes = trace.get("nodes", [])
    edges = trace.get("edges", [])
    seeds = trace.get("seeds") or []

    t = {
        "replay": replay,
        "created_at": _iso(trace.get("created_at"), "trace.created_at"),
        "status": _enum(trace.get("status"), "trace.status"),
        "method": {
            "accounting": method.get("accounting") if method.get("accounting") in ("FIFO", "LIFO", "PIFO", "haircut") else None,
            "max_hops": _num(method.get("max_hops"), "method.max_hops"),
            "max_branches_per_node": _num(method.get("max_branches_per_node"), "method.max_branches_per_node"),
            "min_amount": _num(method.get("min_amount"), "method.min_amount"),
            "as_of_block": _num(method.get("as_of_block"), "method.as_of_block"),
        },
        "endpoints": [{k: r[k] for k in ("address", "reason", "victim_inflow", "balance_usdt", "freezable")}
                      for r in rows],
    }

    sends = []
    for i, s in enumerate(case.get("sends") or []):
        token = s.get("token") if isinstance(s.get("token"), str) and _TOKEN.match(s.get("token")) else None
        sends.append({
            "chain": _enum(s.get("chain"), f"sends.{i}.chain"),
            "tx_hash": _tx(s.get("tx_hash"), f"sends.{i}.tx_hash"),
            "from": _addr(s.get("from"), f"sends.{i}.from"),
            "to": _addr(s.get("to"), f"sends.{i}.to"),
            "token": token,
            "amount": _num(s.get("amount"), f"sends.{i}.amount"),
            "time": _iso(s.get("time"), f"sends.{i}.time"),
        })
    story = case.get("story") or {}
    victim = case.get("victim") or {}
    c = {
        "created_at": _iso(case.get("created_at"), "case.created_at"),
        "as_of": _iso(case.get("as_of"), "case.as_of"),
        "data_cutoff_block": _num(case.get("data_cutoff_block"), "case.data_cutoff_block"),
        "source": case.get("source") if case.get("source") in _SOURCES else None,
        "sends": sends,
        "untrusted": {
            "case_id": sanitize(case.get("case_id") or trace.get("case_id"), 64),
            "victim_alias": sanitize(victim.get("alias"), 120),
            "exchange_used": sanitize(victim.get("exchange_used"), 40),
            "scam_app": sanitize(story.get("scam_app"), 60),
            "platform": sanitize(story.get("platform"), 40),
            "story_summary": sanitize(story.get("summary"), 1200),
            "endpoint_exchange": [sanitize_label(r["_exchange"]) for r in rows],
        },
    }

    times = [s["time"] for s in sends if s["time"]]
    frozen = [r for r in rows if r["is_frozen"]]
    d = {
        "traced_usdt": round(sum(r["victim_funds"] for r in rows), 6),
        "seed_count": len(seeds),
        "send_count": len(sends),
        "first_send": min(times) if times else None,
        "last_send": max(times) if times else None,
        "wallet_count": len(nodes),
        "victim_wallet_count": sum(1 for n in nodes if n.get("kind") == "victim"),
        "max_depth": max((n.get("depth") or 0 for n in nodes), default=0),
        "tx_count": len({h for e in edges for h in e.get("tx_hashes", [])}),
        "endpoint_count": len(rows),
        "frozen_count": len(frozen),
        "frozen_usdt": round(sum(r["victim_funds"] for r in frozen), 6),
        "freezable_count": sum(1 for r in rows if r["freezable"]),
        "freezable_usdt": round(sum(r["victim_funds"] for r in rows if r["freezable"]), 6),
        "exchange_count": sum(1 for r in rows if r["reason"] == "exchange"),
        "endpoints": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
    }

    f = {"trace": t, "case": c, "derived": d,
         "const": {"contacts": dict(CONTACTS), "disclaimers": dict(DISCLAIMERS)}}
    if replay:
        f["doj"] = {
            "case_number": DOJ_CASE_NUMBER,
            "victims_context": "38 victims and victim accounts",
            "note": "context only, from the DOJ complaint; not scored and not a claim about this trace",
        }
    return f


def flatten(obj, prefix=""):
    """{"a": {"b": [x]}} -> {"a.b.0": x}. Only scalar leaves."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1]] = obj
    return out


def citable(facts):
    """Every path a template may cite: scalar, not None, never under case.untrusted."""
    return {p: v for p, v in flatten(facts).items()
            if v is not None and not p.startswith("case.untrusted.")}


def contact_values(facts):
    return set(facts.get("const", {}).get("contacts", {}).values())
