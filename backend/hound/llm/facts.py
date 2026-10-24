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
import math
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

_ETH_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")  # checksummed or not; normalised to lowercase by _addr
_TRON_ADDR = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
_TX = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?Z)?$")
_ENUM = re.compile(r"^[a-z_]{1,32}$")
_SAFE_TEXT = re.compile(r"[^A-Za-z0-9 ,.'_-]")
_TOKEN = re.compile(r"^[A-Z0-9]{2,10}$")
_SOURCES = {"phone", "screenshot", "chainabuse", "doj_replay", "voice"}
# letters, spaces, dots, hyphens only: no digits (partial addresses, amounts), at most 30 chars
_LABEL = re.compile(r"[A-Za-z .-]{1,30}")
_DOTTED = re.compile(r"(?<=[A-Za-z0-9])\.(?=[A-Za-z0-9])")
# a dot between letters or digits, spaced or not ('recoverfunds . help'): sanitize turns it into a space
_DOTTED_SPACED = re.compile(r"(?<=[A-Za-z0-9])\s*\.\s*(?=[A-Za-z0-9])")
# Etherscan label names carry a sub-label and a wallet number: 'Binance: Hot Wallet 20', 'OKX 7'
_LABEL_NUMBER = re.compile(r"\s+\d+$")
ACCUSE = re.compile(r"\b(scam\w*|criminals?|fraud\w*|thief|thieves|launder\w*|crooks?|hackers?|perpetrators?"
                    r"|con\s+artists?|stolen|theft)\b", re.I)


class WriterInputError(ValueError):
    """The trace, case or audience handed to the writer is unusable. The API maps this to 422."""


def sanitize(text, limit=200):
    """Display-only free text: strip to safe characters, no tags, no braces, no links.

    A dot between two letters or digits becomes a space, spaced or not, so 'recoverfunds.help',
    'recoverfunds . help' and 'recoverfunds[.]help' in a story can not reach the model (or the
    page) as a domain. Sentence full stops in the story go too; it is background text only.
    """
    if text is None:
        return None
    return " ".join(_DOTTED_SPACED.sub(" ", _SAFE_TEXT.sub(" ", str(text))).split())[:limit]


def sanitize_label(text):
    """Exchange labels are shown only in code-written lines.

    First normalised to the exchange name: the text before ':' with a trailing wallet number
    dropped ('Binance 14' and 'Binance: Hot Wallet 20' both become 'Binance'). Then allowlisted
    or dropped, never trimmed: letters, spaces, dots and hyphens, 1 to 30 chars, no accusation
    word, no domain (so 'Crypto.com' is dropped too; the endpoint reason still says exchange)."""
    if text is None:
        return None
    label = " ".join(str(text).split(":", 1)[0].split())
    label = _LABEL_NUMBER.sub("", label)
    if not _LABEL.fullmatch(label) or ACCUSE.search(label) or _DOTTED.search(label):
        log.warning("facts: dropping exchange label %r (not in the label allowlist)", text)
        return None
    return label


def short_addr(addr):
    return f"{addr[:8]}…{addr[-6:]}" if len(addr) > 16 else addr


def _is_addr(v):
    return isinstance(v, str) and bool(_ETH_ADDR.match(v) or _TRON_ADDR.match(v))


def _norm_addr(v):
    """0x addresses compare and print lowercase; Tron base58 is case-sensitive and kept."""
    return v.lower() if isinstance(v, str) and _ETH_ADDR.match(v) else v


def _num(v, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        if v is not None:
            log.warning("facts: dropping non-numeric or non-finite %s=%r", where, v)
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
        return _norm_addr(v)
    if v is not None:
        log.warning("facts: dropping malformed address %s=%r", where, v)
    return None


def _tx(v, where):
    if isinstance(v, str) and _TX.match(v):
        return v
    if v is not None:
        log.warning("facts: dropping malformed tx hash %s=%r", where, v)
    return None


# Leftover rows: the engine emits dust and capped branches as an extra endpoint row that carries
# the PARENT wallet's address (the money was sent on from there, not held there). They never take
# on the parent's freeze, balance or freezable flag.
LEFTOVER_REASONS = ("dust", "capped")
LIMIT_REASONS = ("budget", "time_cap", "max_hops")
_SEED_MISSING = re.compile(r"^seed (s\d+) not found on chain")
_SEED_SHORT = re.compile(r"^seed (s\d+): only ")


def _incomplete(trace):
    """Branches the trace could not finish, from the audit log errors and the limit stops.

    Each item is {"what": key, "address": addr or None, "seed_id": "sN" or None}; templates map
    the key to fixed wording. Returns (items, error_count, missing_seed_ids, fetch_failed_addrs)."""
    items, seen, missing, fetch_failed, errors = [], set(), set(), set(), 0

    def add(what, address=None, seed_id=None):
        if (what, address, seed_id) not in seen:
            seen.add((what, address, seed_id))
            items.append({"what": what, "address": address, "seed_id": seed_id})

    for i, a in enumerate(trace.get("audit_log") or []):
        if not isinstance(a, dict) or a.get("step") != "error":
            continue
        errors += 1
        detail = str(a.get("detail") or "")
        addr = _addr(a.get("address"), f"audit_log.{i}.address")
        if detail.startswith("fetch failed"):
            if addr:
                fetch_failed.add(addr)
            add("fetch_failed", addr)
        elif detail.startswith("could not load the swap history"):
            add("swap_fetch_failed", addr)
        elif _SEED_MISSING.match(detail):
            sid = _SEED_MISSING.match(detail).group(1)
            missing.add(sid)
            add("seed_not_found", None, sid)
        elif _SEED_SHORT.match(detail):
            add("seed_short", None, _SEED_SHORT.match(detail).group(1))
        elif "no log_index" in detail:
            add("order_guess", addr)
        elif "lookup failed" in detail:
            add("lookup_failed", addr)
        else:
            add("other_error", addr)
    for i, e in enumerate(trace.get("endpoints", [])):
        if e.get("reason") in LIMIT_REASONS:
            add(e["reason"], _addr(e.get("address"), f"endpoints.{i}.address"))
    return items, errors, missing, fetch_failed


def _endpoint_rows(trace, fetch_failed=frozenset()):
    nodes = {_norm_addr(n.get("address")): n for n in trace.get("nodes", [])}
    rows = []
    for i, e in enumerate(trace.get("endpoints", [])):
        addr = _addr(e.get("address"), f"endpoints.{i}.address")
        if addr is None:
            raise WriterInputError(f"trace endpoint {i} has malformed address {e.get('address')!r}; refusing to write a packet")
        reason = _enum(e.get("reason"), f"endpoints.{i}.reason") or "unknown"
        leftover = reason in LEFTOVER_REASONS
        if reason == "dead_end" and addr in fetch_failed:
            reason = "fetch_error"  # not a real dead end: the wallet's history could not be loaded
        # a leftover row is money that LEFT addr: the parent's freeze does not apply to it
        frozen = {} if leftover else ((nodes.get(addr) or {}).get("frozen") or {})
        # an unknown amount is never printed as 0.00: refuse the packet instead
        inflow = _num(e.get("victim_inflow"), f"endpoints.{i}.victim_inflow")
        if inflow is None:
            raise WriterInputError(f"trace endpoint {i} victim_inflow {e.get('victim_inflow')!r} is not a finite number; "
                                   "refusing to write a packet")
        remaining = _num(e.get("victim_remaining"), f"endpoints.{i}.victim_remaining")
        if remaining is None and e.get("victim_remaining") is not None:
            raise WriterInputError(f"trace endpoint {i} victim_remaining {e.get('victim_remaining')!r} is not a finite "
                                   "number; refusing to write a packet")
        # a service-sized or leftover balance is not victim money at rest: never shown, never freezable.
        # Only a holding stop (funds resting in a wallet we expanded) is freezable; a high_volume,
        # dead_end or limit stop was never expanded, so its balance proves nothing about victim funds.
        balance = None if leftover or reason == "high_volume" else _num(e.get("balance_usdt"), f"endpoints.{i}.balance_usdt")
        freezable = bool(e.get("freezable")) and reason == "holding"
        if bool(e.get("freezable")) and not freezable:
            log.warning("facts: endpoint %s reason %s marked freezable by the engine; not freezable in the packet",
                        addr, reason)
        rows.append({
            "address": addr,
            "short": short_addr(addr),
            "reason": reason,
            "leftover": leftover,
            "victim_inflow": inflow,
            "victim_funds": remaining if remaining is not None else inflow,
            "balance_usdt": balance,
            "freezable": freezable,
            "is_frozen": bool(frozen.get("is_frozen")),
            "frozen_at": _iso(frozen.get("frozen_at"), f"nodes[{addr}].frozen_at"),
            "freeze_tx": _tx(frozen.get("freeze_tx"), f"nodes[{addr}].freeze_tx"),
            "_exchange": None if leftover else e.get("exchange"),
            "_reason": _enum(e.get("reason"), f"endpoints.{i}.reason") or "unknown",
        })
    rows.sort(key=lambda r: (-r["victim_funds"], r["address"], r["reason"]))
    return rows


def _hop_rows(edges):
    """Every edge of the trace, hop order then largest first: the detective's hop table."""
    hops = []
    for i, e in enumerate(edges):
        src, dst = _addr(e.get("from"), f"edges.{i}.from"), _addr(e.get("to"), f"edges.{i}.to")
        amount = _num(e.get("attributed_amount"), f"edges.{i}.attributed_amount")
        token = e.get("token") if isinstance(e.get("token"), str) and _TOKEN.match(e.get("token")) else None
        if src is None or dst is None or amount is None or token is None:
            log.warning("facts: dropping edge %d from the hop table (malformed from/to/amount/token)", i)
            continue
        hops.append({
            "hop": _num(e.get("hop"), f"edges.{i}.hop"),
            "from": src, "to": dst, "token": token,
            "attributed_amount": round(amount, 6),
            "tx_count": len({h for h in e.get("tx_hashes") or [] if isinstance(h, str)}),
            "confidence": _num(e.get("confidence"), f"edges.{i}.confidence"),
            "method": _enum(e.get("method"), f"edges.{i}.method"),
        })
    hops.sort(key=lambda h: (h["hop"] if h["hop"] is not None else 99, -h["attributed_amount"], h["from"], h["to"]))
    return hops


def build_facts(trace, case):
    """Facts for one packet. Raises if the trace is unusable; drops (and logs) malformed fields."""
    if not isinstance(trace, dict) or "endpoints" not in trace:
        raise WriterInputError("build_facts needs a Trace dict with endpoints")
    if not trace["endpoints"]:
        raise WriterInputError("trace has no endpoints yet (nothing traced); refusing to write an empty packet")
    case = case or {}
    replay = bool(trace.get("replay")) or case.get("source") == "doj_replay"
    method = trace.get("method") or {}
    nodes = trace.get("nodes", [])
    edges = trace.get("edges", [])
    seeds = trace.get("seeds") or []
    incomplete, error_count, missing_seeds, fetch_failed = _incomplete(trace)
    if seeds and len(missing_seeds) >= len(seeds):
        raise WriterInputError(f"none of the {len(seeds)} reported sends was found on chain "
                               f"({', '.join(sorted(missing_seeds))}); check the tx hash and the recipient. "
                               "Refusing to write a packet that traces nothing")
    rows = _endpoint_rows(trace, fetch_failed)
    status = _enum(trace.get("status"), "trace.status")

    t = {
        "replay": replay,
        "created_at": _iso(trace.get("created_at"), "trace.created_at"),
        "status": status,
        "method": {
            "accounting": method.get("accounting") if method.get("accounting") in ("FIFO", "LIFO", "PIFO", "haircut") else None,
            "max_hops": _num(method.get("max_hops"), "method.max_hops"),
            "max_branches_per_node": _num(method.get("max_branches_per_node"), "method.max_branches_per_node"),
            "min_amount": _num(method.get("min_amount"), "method.min_amount"),
            "as_of_block": _num(method.get("as_of_block"), "method.as_of_block"),
        },
        "endpoints": [{"address": r["address"], "reason": r["_reason"], "victim_inflow": r["victim_inflow"],
                       "balance_usdt": r["balance_usdt"], "freezable": r["freezable"]} for r in rows],
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
        "found_seed_count": max(len(seeds) - len(missing_seeds), 0),
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
        "hops": _hop_rows(edges),
        # partial: anything but a clean 'done', or any branch the audit log says is incomplete
        "partial": status != "done" or bool(incomplete),
        "audit_error_count": error_count,
        "missing_seed_count": len(missing_seeds),
        "incomplete_count": len(incomplete),
        "incomplete": incomplete,
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
