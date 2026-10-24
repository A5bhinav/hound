"""Hound HTTP API (BRIEF 8.5). Ishaan wires routes; logic lives in each owner's module.

Run: cd backend && uvicorn hound.api:app --reload --port 8000
"""
import hmac
import importlib
import ipaddress
import json
import logging
import os
import re
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

log = logging.getLogger("hound.api")
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
KNOWN_KEYS = ("ANTHROPIC_API_KEY", "ETHERSCAN_API_KEY", "TRONGRID_API_KEY", "BLOCKSCOUT_API_KEY",
              "CHAINABUSE_API_KEY", "HOUND_ADMIN_TOKEN", "HOUND_PUBLIC_ORIGIN")


def _load_env(path=ENV_FILE):
    """Load the repo-root .env before any hound module reads os.environ. Real env vars always win
    (override=False). Logs key NAMES only, never values. Tests set HOUND_NO_DOTENV=1."""
    if os.environ.get("HOUND_NO_DOTENV") == "1":
        log.info("HOUND_NO_DOTENV=1: repo .env not loaded")
        return
    if not path.exists():
        log.warning("no .env at %s; keys come from the process environment only", path)
    else:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
    present = [k for k in KNOWN_KEYS if os.environ.get(k)]
    log.warning("env keys present: %s", ", ".join(present) or "none")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY unset: the writer and classifier will use templates and rules, not Claude")


_load_env()

from hound.contracts import ROOT, example, validate_case
from hound.engine import trace as trace_module
from hound.engine.trace import DEFAULTS, _redact, run_trace
from hound.llm.facts import WriterInputError
from hound.llm.writer import write_case
from hound.proof.backtest import serve as backtest_serve
from hound.proof.doj_ohnd import doj_scoreboard
from hound.watch.check import check
from hound.watch.other_payers import other_payers
from hound.watch import watchlist
from hound.watch.watchlist import register_trace

app = FastAPI(title="Hound", docs_url=None, redoc_url=None, openapi_url=None)  # no route map over the tunnel
# Browsers reach the API through the Next proxy (same origin), so CORS only needs local dev origins
# plus the one public web origin the operator names.
PUBLIC_ORIGINS = [o.strip() for o in os.environ.get("HOUND_PUBLIC_ORIGIN", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=PUBLIC_ORIGINS,
                   allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
                   allow_methods=["*"], allow_headers=["*"])

# In-memory store for the hackathon. Curated cases are loaded from data/cases/ + examples/.
CASES = {}
TRACES = {}   # engine trace_id -> Trace
JOBS = {}     # job id (uuid4, returned as trace_id by POST /cases/{id}/trace) -> job state
LATEST = {}   # case_id -> latest job id (may be running or failed)
LAST_DONE = {}  # case_id -> trace_id of the latest successful trace; the packet reads this
_LOCK = threading.Lock()
_GENERATION = 0  # bumped by /demo/reset so a job started before the reset cannot write after it
CHAIN_FUNCS = ("get_transfers", "label", "freeze_status", "get_balance")
# Whole-job wall clock. The engine checks its own deadline only between adapter calls, and one call
# can retry across several hosts, so the API bounds it from outside; other_payers gets its own budget.
ENGINE_BUDGET_S = DEFAULTS["deadline_s"] + 30
OTHER_PAYERS_BUDGET_S = 20
JOB_STALE_S = ENGINE_BUDGET_S + OTHER_PAYERS_BUDGET_S + 10  # a running job older than this is hung
REPLAY_CASE = "ohnd-replay-ah"  # the DOJ replay the proof scoreboard scores
CLIENT_FORBIDDEN = ("case_id", "freeze_visibility", "data_cutoff_block")  # server-owned / replay-only fields


class MissingAdapters(RuntimeError):
    """api.py's own explicit check found hound.chain without a needed adapter."""


# The engine raises AdaptersMissing when it has no adapter to call (engine fixer, parallel branch).
# Fixture fallback happens ONLY on these types, never on a generic RuntimeError (ChainAPIError,
# CacheMiss and budget errors all subclass RuntimeError and must surface as errors).
FALLBACK_ERRORS = tuple(t for t in (MissingAdapters, getattr(trace_module, "AdaptersMissing", None)) if t)


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Only these cases may feed the watchlist (and so make /check HOLD a wallet): cases the operator put
# on disk, and cases the server's own intake verified on chain. A client-posted case can be traced
# (judges may try their own scenario) but can never mint a hold against someone else's wallet.
TRUSTED = set()
LIVE_CASES = set()  # cases from data/cases_live: real, unfrozen addresses; redacted beyond localhost
PACKETS = {}  # (trace_id, audience) -> Claude-written packet, so repeat hits never re-call Claude
FALLBACK_PACKETS = {}  # (trace_id, audience) -> (template packet, monotonic expiry) when Claude failed
FALLBACK_TTL_S = 60.0  # with a key set but Claude failing, retry Claude at most once a minute per key
_PACKET_LOCKS = {}


def mark_verified(case_id):
    """Called by server-side intake (operator approval), never by a client. If the case was already
    traced (the operator reviews the trace before approving), that trace is registered with the
    watchlist now; otherwise the next trace registers itself (_register checks TRUSTED)."""
    with _LOCK:
        TRUSTED.add(case_id)
        trace = TRACES.get(LAST_DONE.get(case_id))
    if trace is not None:
        _register(f"approve-{case_id}", trace, trace.get("source") == "fixture")


SKIPPED_CASES = []  # invalid curated files: listed in /health instead of crashing startup


def _load_curated():
    live = sorted((ROOT / "data" / "cases_live").glob("*.case.json"))  # gitignored, demo laptop only
    files = (sorted((ROOT / "data" / "cases").glob("*.case.json")) + live
             + [ROOT / "examples" / "ohnd_replay.case.json"])
    SKIPPED_CASES.clear()
    for f in files:
        if not f.exists():
            continue
        try:
            c = validate_case(json.loads(f.read_text()))
        except Exception as e:  # noqa: BLE001 - one bad file must never stop the server (demo laptop)
            SKIPPED_CASES.append({"file": f.name, "error": f"{type(e).__name__}: {str(e)[:200]}"})
            log.error("skipping invalid curated case %s: %s", f.name, e)
            continue
        CASES[c["case_id"]] = c
        TRUSTED.add(c["case_id"])
        if f in live:
            LIVE_CASES.add(c["case_id"])
    log.info("loaded %d curated cases, skipped %d invalid", len(CASES), len(SKIPPED_CASES))


_load_curated()


def _case(case_id):
    if case_id not in CASES:
        raise HTTPException(404, f"no case {case_id!r}")
    return CASES[case_id]


PROXY_HEADERS = ("cf-connecting-ip", "x-real-ip", "forwarded", "true-client-ip")


def _loopback(host):
    try:
        ip = ipaddress.ip_address((host or "").strip())
    except ValueError:
        return False
    return ip.is_loopback or bool(getattr(ip, "ipv4_mapped", None) and ip.ipv4_mapped.is_loopback)


def _is_local(request):
    """True only for a caller on this machine. A tunnel (cloudflared) also connects from loopback,
    so any proxy header naming another client, or a non-loopback X-Forwarded-For hop, is not local."""
    if not _loopback(request.client.host if request.client else None):
        return False
    # Any forwarding header means the request came through a proxy or tunnel. The values are
    # client-controlled (X-Forwarded-For: 127.0.0.1 is trivial to send), so never trust them.
    if any(h in request.headers for h in PROXY_HEADERS) or "x-forwarded-for" in request.headers:
        return False
    # The Next proxy adds X-Forwarded-Host: the host the browser asked for. A LAN viewer of
    # http://192.168.x.y:3000 reaches us from loopback too, so only a localhost name stays local.
    fwd_host = request.headers.get("x-forwarded-host")
    if fwd_host is not None and _host_name(fwd_host) not in LOCAL_HOSTNAMES:
        return False
    return True


LOCAL_HOSTNAMES = ("localhost", "127.0.0.1", "[::1]", "::1")


def _host_name(value):
    """'localhost:3000' -> 'localhost', '[::1]:3000' -> '[::1]'; first entry of a comma list."""
    h = value.split(",")[0].strip().lower()
    if h.startswith("["):
        return h.split("]")[0] + "]"
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


ANY_ADDR = re.compile(r"(?<![0-9A-Za-z])(0x[0-9a-fA-F]{64}|0x[0-9a-fA-F]{40}|[0-9a-fA-F]{64}"
                      r"|T[1-9A-HJ-NP-Za-km-z]{33})(?![0-9A-Za-z])")


def _short(v):
    return v[:6] + "..." + v[-4:]


def _redact_live(obj):
    """Copy with every address and tx hash shortened (prefix 6 + ... + suffix 4), story dropped and
    the victim alias cleared. Applied to live cases for callers beyond localhost (PITCH, BRIEF 0)."""
    if isinstance(obj, dict):
        out = {k: _redact_live(v) for k, v in obj.items() if k != "story"}
        if isinstance(out.get("victim"), dict):
            out["victim"] = {**out["victim"], "alias": None}
        return out
    if isinstance(obj, list):
        return [_redact_live(v) for v in obj]
    if isinstance(obj, str):
        return ANY_ADDR.sub(lambda m: _short(m.group()), obj)
    return obj


def _public(case_id, body, request):
    return _redact_live(body) if case_id in LIVE_CASES and not _is_local(request) else body


@app.get("/cases")
def list_cases(request: Request):
    # Full validated Case objects: the web reads sends, created_at and the replay fields off each row.
    with _LOCK:
        rows = [dict(c) for c in CASES.values()]
    return [_public(c["case_id"], c, request) for c in rows]


ETH_TX = re.compile(r"^0x[0-9a-fA-F]{64}$")
TRON_TX = re.compile(r"^[0-9a-fA-F]{64}$")


def _iso_ok(v):
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return "T" in v
    except (AttributeError, ValueError):
        return False


def _check_engine_input(case):
    """Reject with 422 what the engine would only reject later inside the trace job, so a judge
    typing their own case sees the real reason at once (token, chain mix, send count, Tron, time)."""
    sends = case.get("sends")
    if not isinstance(sends, list):
        return
    if len(sends) > trace_module.MAX_SENDS:
        raise HTTPException(422, f"case has {len(sends)} sends; the limit is {trace_module.MAX_SENDS}")
    for k in ("created_at", "as_of"):
        if isinstance(case.get(k), str) and not _iso_ok(case[k]):
            raise HTTPException(422, f"{k} {case[k]!r} is not an ISO 8601 date-time like 2026-10-24T00:00:00Z")
    chains = set()
    for i, s in enumerate(sends):
        if not isinstance(s, dict):
            continue
        if isinstance(s.get("token"), str):
            s["token"] = s["token"].strip().upper()
            if s["token"] not in ("USDT", "ETH"):
                raise HTTPException(422, f"sends[{i}].token {s['token']!r} is not supported (USDT or ETH only)")
        if isinstance(s.get("time"), str) and not _iso_ok(s["time"]):
            raise HTTPException(422, f"sends[{i}].time {s['time']!r} is not an ISO 8601 date-time like 2026-10-24T00:00:00Z")
        chains.add(s.get("chain"))
        if s.get("chain") == "tron":
            if s.get("token") == "ETH":
                raise HTTPException(422, f"sends[{i}]: ETH is not a Tron token")
            for k in ("from", "to"):
                if isinstance(s.get(k), str):
                    s[k] = s[k].strip()
                    if not TRON_ADDR.match(s[k]):
                        raise HTTPException(422, f"sends[{i}].{k} {s[k]!r} is not a Tron address (34 base58 characters starting with T)")
            if isinstance(s.get("tx_hash"), str):
                s["tx_hash"] = s["tx_hash"].strip()
                if not TRON_TX.match(s["tx_hash"]):
                    raise HTTPException(422, f"sends[{i}].tx_hash {s['tx_hash']!r} is not a Tron tx hash (64 hex)")
    if len(chains) > 1:
        raise HTTPException(422, f"a case must start on one chain, got {sorted(map(str, chains))}")


def _normalize_sends(sends):
    """Ethereum sends are lowercased like the chain adapters (eth.norm), else seeds never match and the
    trace comes back silently empty. Malformed hex is a 400."""
    for i, s in enumerate(sends if isinstance(sends, list) else []):
        if not isinstance(s, dict) or s.get("chain") != "ethereum":
            continue
        for k in ("from", "to"):
            if isinstance(s.get(k), str):
                v = s[k].strip()
                if not ETH_ADDR.match(v):
                    raise HTTPException(400, f"sends[{i}].{k} {v!r} is not an ethereum address (0x plus 40 hex)")
                s[k] = v.lower()
        if isinstance(s.get("tx_hash"), str):
            v = s["tx_hash"].strip()
            if not ETH_TX.match(v):
                raise HTTPException(400, f"sends[{i}].tx_hash {v!r} is not an ethereum tx hash (0x plus 64 hex)")
            s["tx_hash"] = v.lower()


@app.post("/cases")
def create_case(case: dict):
    # Clients cannot pick the id (overwrites curated cases) or dress a live case up as a replay.
    bad = [k for k in CLIENT_FORBIDDEN if k in case]
    if bad:
        raise HTTPException(400, f"{', '.join(bad)} cannot be set by the client")
    if case.get("source") == "doj_replay":
        raise HTTPException(400, "source 'doj_replay' is reserved for curated replay cases")
    _normalize_sends(case.get("sends"))
    _check_engine_input(case)
    case["case_id"] = f"case-{uuid.uuid4().hex[:8]}"
    case.setdefault("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    case.setdefault("status", "intake")
    try:
        validate_case(case)
    except ValueError as e:
        raise HTTPException(422, str(e))
    with _LOCK:
        CASES[case["case_id"]] = case
    return case


def _chain_deps(case):
    """Real hound.chain adapters. Raises MissingAdapters if a needed one is absent (explicit check).

    get_native_txs is required only for cases with ETH sends (the A.H. replay starts from six).
    """
    try:
        chain = importlib.import_module("hound.chain")
        missing = [k for k in CHAIN_FUNCS if not callable(getattr(chain, k, None))]
    except ImportError as e:
        raise MissingAdapters(f"hound.chain import failed: {type(e).__name__}") from e
    if not missing:
        deps = {k: getattr(chain, k) for k in CHAIN_FUNCS}
        deps["get_native_txs"] = getattr(chain, "get_native_txs", None)
        if deps["get_native_txs"] is not None or not any(s.get("token") == "ETH" for s in case["sends"]):
            return deps
        missing = ["get_native_txs (case has ETH sends)"]
    raise MissingAdapters("hound.chain is missing " + ", ".join(missing))


def _fixture_deps():
    from hound import fixture_chain as fc
    return {k: getattr(fc, k) for k in CHAIN_FUNCS + ("get_native_txs",)}


def _trace_with_fallback(job_id, case, progress):
    """Returns (trace, using_fixture). Fixture data is used ONLY when the adapters are missing AND the
    case is the curated DOJ replay; the trace is then marked source='fixture'. Every other error raises."""
    try:
        return run_trace(case, progress=progress, **_chain_deps(case)), False
    except FALLBACK_ERRORS as e:
        if case.get("source") != "doj_replay":
            raise
        log.warning("REAL CHAIN ADAPTERS MISSING (%s); job %s replays case %s on fixture data from "
                    "examples/ohnd_transfers.json, marked source=fixture", e, job_id, case["case_id"])
    del progress[:]  # drop the failed attempt's audit entries; the fixture run starts a fresh log
    trace = run_trace(case, progress=progress, **_fixture_deps())
    # Set after run_trace's schema validation, which may not list "fixture" until the engine branch merges.
    trace["source"] = "fixture"
    return trace, True


class JobTimeout(TimeoutError):
    """A trace step ran past its API wall-clock budget."""


def _within(budget_s, fn, name):
    """Run fn in a daemon thread and wait at most budget_s. On overrun raise JobTimeout; the thread
    cannot be killed, so it runs on and its result is dropped (the job is no longer 'running')."""
    box = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller
            box["error"] = e

    t = threading.Thread(target=target, daemon=True, name=name)
    t.start()
    t.join(budget_s)
    if t.is_alive():
        raise JobTimeout(f"{name} ran over {budget_s}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _audit(trace, step, detail):
    trace.setdefault("audit_log", []).append({"t": _now_iso(), "step": step, "address": None, "detail": detail})


def _other_payers_skip_reason(trace):
    """other_payers re-reads the chain for every scam wallet. When the trace already shows the chain
    was unreachable or found nothing, that only repeats the same dead retries."""
    if (trace.get("stats") or {}).get("fetch_errors"):
        return "the trace had chain fetch errors"
    if any("not found on chain" in (e.get("detail") or "") for e in trace.get("audit_log") or []):
        return "a seed send was not found on chain"
    if not trace.get("edges"):
        return "no USDT was traced"
    # Past the engine deadline the chain is slow; other_payers would only add its own budget on top.
    if (any(e.get("reason") == "time_cap" for e in trace.get("endpoints") or [])
            or any(e.get("step") == "cap_hit" and (e.get("detail") or "").startswith("time_cap")
                   for e in trace.get("audit_log") or [])):
        return "the trace hit its time cap"
    return None


def _attach_other_payers(job_id, trace, using_fixture):
    """other_payers reads the live hound.chain, so it is skipped on fixture traces (never mix data)
    and a failure in it leaves the finished trace intact with other_payers = []."""
    if using_fixture:
        log.warning("trace job %s ran on fixture data; other_payers skipped (it would read the live chain)", job_id)
        trace["other_payers"] = []
        return
    reason = _other_payers_skip_reason(trace)
    if reason:
        log.warning("trace job %s: other_payers skipped because %s", job_id, reason)
        _audit(trace, "skip_branch", f"other payers not searched: {reason}")
        trace["other_payers"] = []
        return
    try:
        trace["other_payers"] = _within(OTHER_PAYERS_BUDGET_S, lambda: other_payers(trace), f"other_payers-{job_id[:8]}")
    except JobTimeout:
        log.error("trace job %s: other_payers ran over %ss; trace kept as partial with other_payers=[]",
                  job_id, OTHER_PAYERS_BUDGET_S)
        _audit(trace, "error", f"other payers search ran over {OTHER_PAYERS_BUDGET_S}s; skipped")
        trace["other_payers"] = []
        trace["status"] = "partial"
    except Exception:
        log.error("trace job %s: other_payers failed, trace kept with other_payers=[]: %s",
                  job_id, _redact(traceback.format_exc()))
        trace["other_payers"] = []


def _finish(job_id, generation, ok, trace=None):
    """Apply a finished job under the lock. Returns False if the result was dropped."""
    job = JOBS.get(job_id)
    if generation != _GENERATION or job is None:
        log.warning("trace job %s finished after /demo/reset; result dropped", job_id)
        return False
    if job["status"] != "running":
        log.warning("trace job %s finished after it was superseded; result dropped", job_id)
        return False
    case = CASES.get(job["case_id"])
    if ok:
        TRACES[trace["trace_id"]] = trace
        # A re-trace can reuse the trace_id (it is a digest of the case): never serve the old packet.
        for cache in (PACKETS, FALLBACK_PACKETS):
            for key in [k for k in cache if k[0] == trace["trace_id"]]:
                cache.pop(key, None)
        job.update(status=trace.get("status", "done"), result_trace_id=trace["trace_id"])
        LAST_DONE[job["case_id"]] = trace["trace_id"]
        if case is not None:
            case["status"] = "traced"
    else:
        if case is not None:
            case["status"] = job["prev_status"]
    return True


def _run_job(job_id, case, generation, progress):
    try:
        trace, using_fixture = _within(ENGINE_BUDGET_S, lambda: _trace_with_fallback(job_id, case, progress),
                                       f"engine-{job_id[:8]}")
    except Exception as e:  # report every engine failure to the poller, never swallow it
        # Full detail stays in the server log (secrets redacted); the poller gets the type only,
        # because adapter errors can carry request URLs with API keys in them. Two exceptions carry
        # no URLs: our own timeout, and the engine's ValueError on bad case input.
        if isinstance(e, JobTimeout):
            log.error("trace job %s for case %s ran over %ss (chain APIs slow or unreachable); ended as error",
                      job_id, case["case_id"], ENGINE_BUDGET_S)
            msg = f"TimeoutError: trace ran over {ENGINE_BUDGET_S}s; the chain APIs are slow or unreachable"
        else:
            log.error("trace job %s for case %s failed: %s", job_id, case["case_id"], _redact(traceback.format_exc()))
            msg = f"{type(e).__name__}: trace failed; see the server log for job {job_id}"
            if type(e) is ValueError:
                msg = f"ValueError: {_redact(str(e))[:300]}"
        with _LOCK:
            job = JOBS.get(job_id)
            if _finish(job_id, generation, ok=False):
                job.update(status="error", error=msg)
        return
    _attach_other_payers(job_id, trace, using_fixture)
    with _LOCK:
        if not _finish(job_id, generation, ok=True, trace=trace):
            return
    _register(job_id, trace, using_fixture)
    log.info("trace job %s done: %s (%s)", job_id, trace["trace_id"], trace["status"])


def _register(job_id, trace, using_fixture):
    """Feed the watchlist so /check holds wallets from this trace right away (not only preloaded ones)."""
    if trace["case_id"] not in TRUSTED:
        log.warning("trace job %s: case %s is not curated or verified; not registered with the watchlist "
                    "(an unverified client case must never cause a hold)", job_id, trace["case_id"])
        return
    if using_fixture:
        log.warning("trace job %s ran on fixture data; not registered with the watchlist", job_id)
        return
    try:
        n = register_trace(trace)
        log.info("trace job %s registered with the watchlist (%s addresses)", job_id, n)
    except Exception:
        log.error("trace job %s: register_trace failed; /check will not hold its wallets: %s",
                  job_id, _redact(traceback.format_exc()))


def _job_view(job_id):
    """Caller holds _LOCK. Raises 404 if the job is gone (e.g. after /demo/reset)."""
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"no trace {job_id!r}")
    if job["status"] == "running":
        # run_trace appends audit entries to job["progress"] live; return a copy of what is there.
        return {"trace_id": job_id, "case_id": job["case_id"], "status": "running",
                "started_at": job["started_at"], "elapsed_s": round(time.monotonic() - job["started_mono"], 1),
                "audit_log_so_far": list(job["progress"])}
    if job["status"] == "error":
        return {"trace_id": job_id, "case_id": job["case_id"], "status": "error", "error": job["error"]}
    # The engine Trace has its own trace_id; job_id is the handle POST returned, so clients can key on it.
    return {**TRACES[job["result_trace_id"]], "job_id": job_id}


@app.post("/cases/{case_id}/trace")
def trace_case(case_id: str, request: Request):
    view, _ = _start_trace(case_id)
    return _public(case_id, view, request)


def _start_trace(case_id, generation=None):
    """Start (or join) the trace job for a case. Returns (job view, worker thread, or None when an
    already running job was joined). generation (background prewarm): start nothing, (None, None),
    if a /demo/reset has run since it was captured."""
    case = _case(case_id)
    job_id = uuid.uuid4().hex
    with _LOCK:
        if generation is not None and generation != _GENERATION:
            return None, None
        prev_id = LATEST.get(case_id)
        prev = JOBS.get(prev_id)
        if prev and prev["status"] == "running":
            age = time.monotonic() - prev["started_mono"]
            if age <= JOB_STALE_S:
                return _job_view(prev_id), None  # one trace per case at a time
            log.error("trace job %s for case %s hung for %.0fs; superseded by %s", prev_id, case_id, age, job_id)
            prev.update(status="error", error=f"TimeoutError: trace ran over {JOB_STALE_S}s and was superseded by job {job_id}")
            case["status"] = prev["prev_status"]
        JOBS[job_id] = {"case_id": case_id, "status": "running", "prev_status": case["status"],
                        "started_at": _now_iso(), "started_mono": time.monotonic(), "progress": []}
        LATEST[case_id] = job_id
        case["status"] = "tracing"
        generation = _GENERATION
        view = _job_view(job_id)
        progress = JOBS[job_id]["progress"]
    t = threading.Thread(target=_run_job, args=(job_id, case, generation, progress), daemon=True,
                         name=f"trace-{job_id[:8]}")
    t.start()
    return view, t


@app.get("/cases/{case_id}/trace")
def case_trace(case_id: str, request: Request):
    _case(case_id)
    with _LOCK:
        if case_id not in LATEST:
            raise HTTPException(404, f"case {case_id!r} has no trace; POST /cases/{case_id}/trace first")
        view = _job_view(LATEST[case_id])
    return _public(case_id, view, request)


@app.get("/traces/{trace_id}")
def get_trace(trace_id: str, request: Request):
    with _LOCK:
        if trace_id in JOBS:
            view = _job_view(trace_id)
        elif trace_id in TRACES:
            view = TRACES[trace_id]
        else:
            raise HTTPException(404, f"no trace {trace_id!r}")
    return _public(view.get("case_id"), view, request)


@app.get("/cases/{case_id}/packet")
def packet(case_id: str, request: Request, audience: str = "detective"):
    written, trace = _get_packet(case_id, audience)
    if case_id in LIVE_CASES and not _is_local(request):
        # The prose is written from the victim's story (scam app, platform, first contact); beyond
        # localhost a live case returns only the structured fields, never the paragraphs.
        written = {**{k: v for k, v in written.items() if k != "text"}, "text": None, "redacted": True}
    return _public(case_id, {"packet": written, "trace": trace}, request)


def _get_packet(case_id, audience, generation=None):
    """(packet, trace) for the case's latest finished trace, cached per (trace_id, audience).
    generation: set by the background prewarm; a packet finished after a reset is not cached."""
    case = _case(case_id)
    with _LOCK:
        trace = TRACES.get(LAST_DONE.get(case_id))
        if trace is not None:
            key = (trace["trace_id"], audience)
            lock = _PACKET_LOCKS.setdefault(key, threading.Lock())
    if trace is None:
        raise HTTPException(409, f"case {case_id!r} has no finished trace yet; POST /cases/{case_id}/trace and poll it first")
    with lock:  # concurrent hits for one key wait for the first Claude call instead of making their own
        written = PACKETS.get(key)
        cached = FALLBACK_PACKETS.get(key)
        if written is None and cached and time.monotonic() < cached[1]:
            written = cached[0]
        if written is None:
            try:
                written = write_case(trace, case, audience)
            except WriterInputError as e:
                log.warning("packet %s: writer refused input: %s", case_id, e)
                raise HTTPException(422, str(e))
            except AssertionError:
                log.exception("packet %s/%s: writer failed an internal check", case_id, audience)
                raise HTTPException(500, "The case packet could not be written for this trace. See the server log.")
            if generation is not None and generation != _GENERATION:
                log.warning("packet %s/%s finished after /demo/reset; not cached", case_id, audience)
                return written, trace
            if written.get("source") == "claude":
                PACKETS[key] = written
            elif os.environ.get("ANTHROPIC_API_KEY"):
                # Claude failed (rate limit, credits) and the writer fell back: hold the template briefly
                # so a caller looping /packet cannot turn every hit into another Claude call.
                log.warning("packet %s/%s: Claude fell back to the template; caching it for %.0fs",
                            case_id, audience, FALLBACK_TTL_S)
                FALLBACK_PACKETS[key] = (written, time.monotonic() + FALLBACK_TTL_S)
    return written, trace


def token_matches(sent, token):
    """Constant-time header check; bytes so a non-ASCII header value is a mismatch, not a TypeError."""
    return bool(token) and hmac.compare_digest((sent or "").encode("utf-8"), token.encode("utf-8"))


def _origin_netloc(origin):
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]+)", origin.strip().lower())
    return m.group(1) if m else None


def reject_cross_site(request, what):
    """CSRF guard for state-changing operator calls: a page on another site must not be able to
    drive the operator's browser into them. Refuses Sec-Fetch-Site: cross-site, and an Origin that
    is neither localhost nor the host this request was addressed to (direct or via the Next proxy)."""
    if request.headers.get("sec-fetch-site", "").strip().lower() == "cross-site":
        log.warning("%s refused: Sec-Fetch-Site cross-site", what)
        raise HTTPException(403, f"{what} refused: cross-site request")
    origin = request.headers.get("origin")
    if origin is None:
        return
    netloc = _origin_netloc(origin)
    if netloc is not None:
        if _host_name(netloc) in LOCAL_HOSTNAMES:
            return
        own = {h.split(",")[0].strip().lower() for h in (request.headers.get("host"),
                                                          request.headers.get("x-forwarded-host")) if h}
        if netloc in own:
            return
    log.warning("%s refused: Origin %r is not this host or localhost", what, origin[:100])
    raise HTTPException(403, f"{what} refused: cross-origin request")


def _require_admin(request):
    """Local caller OR a valid X-Hound-Admin token (the local Reset button keeps working with a token set)."""
    reject_cross_site(request, "POST /demo/reset")
    if _is_local(request):
        return
    token = os.environ.get("HOUND_ADMIN_TOKEN")
    if not token:
        raise HTTPException(403, "POST /demo/reset is localhost only (or set HOUND_ADMIN_TOKEN and send X-Hound-Admin)")
    if not token_matches(request.headers.get("x-hound-admin"), token):
        raise HTTPException(403, "POST /demo/reset needs header X-Hound-Admin equal to HOUND_ADMIN_TOKEN")


PREWARM_AUDIENCES = ("victim", "detective")


def _prewarm(generation):
    """Re-trace the DOJ replay (about 1 s from the snapshot) and write both packets, so the next judge
    after a reset or restart never waits on a cold trace and the home/proof tiles are there. Runs in a
    background thread; every result is dropped if /demo/reset ran again meanwhile (generation moved)."""
    t0 = time.monotonic()
    try:
        if REPLAY_CASE not in CASES:
            log.warning("prewarm: %s not loaded; nothing to warm", REPLAY_CASE)
            return
        view, worker = _start_trace(REPLAY_CASE, generation=generation)
        if worker is not None:
            worker.join(JOB_STALE_S)
        elif view is not None:  # joined a trace someone else started: wait for it to finish
            end = time.monotonic() + JOB_STALE_S
            while time.monotonic() < end and generation == _GENERATION:
                with _LOCK:
                    running = (JOBS.get(view["trace_id"]) or {}).get("status") == "running"
                if not running:
                    break
                time.sleep(0.2)
        if generation != _GENERATION:
            log.warning("prewarm: reset ran during the replay trace; stopping")
            return
        with _LOCK:
            done = LAST_DONE.get(REPLAY_CASE) in TRACES
        if not done:
            log.error("prewarm: replay trace did not finish; packets not warmed (see the trace job log)")
            return
        for audience in PREWARM_AUDIENCES:
            if generation != _GENERATION:
                log.warning("prewarm: reset ran while writing packets; stopping")
                return
            packet_, _ = _get_packet(REPLAY_CASE, audience, generation=generation)
            log.info("prewarm: %s packet ready (%s)", audience, packet_.get("source"))
        log.warning("prewarm: replay trace and packets ready in %.1fs", time.monotonic() - t0)
    except Exception:  # noqa: BLE001 - a background warm-up must never take the server down
        log.error("prewarm failed: %s", _redact(traceback.format_exc()))


def _start_prewarm():
    """Background only, never blocks a request or startup. HOUND_NO_PREWARM=1 turns it off (tests)."""
    if os.environ.get("HOUND_NO_PREWARM") == "1":
        return None
    t = threading.Thread(target=_prewarm, args=(_GENERATION,), daemon=True, name="prewarm-replay")
    t.start()
    return t


@app.post("/demo/reset")
def demo_reset(request: Request):
    global _GENERATION
    _require_admin(request)
    with _LOCK:
        _GENERATION += 1
        CASES.clear()
        TRACES.clear()
        JOBS.clear()
        LATEST.clear()
        LAST_DONE.clear()
        TRUSTED.clear()
        LIVE_CASES.clear()
        PACKETS.clear()
        FALLBACK_PACKETS.clear()
        _PACKET_LOCKS.clear()
        _load_curated()
        watchlist.reset()  # drop wallets registered from the traces just cleared
    try:  # the next judge must not see the previous caller's intake session
        from hound.intake import routes as intake_routes
    except ImportError:
        intake_routes = None  # no intake module: nothing to clear (logged at startup)
    if intake_routes is not None:
        intake_routes.reset()
    _start_prewarm()  # the cleared replay trace and packets come back in the background
    log.warning("demo reset: in-memory cases, traces and jobs cleared; %d curated cases reloaded", len(CASES))
    return {"ok": True, "cases": len(CASES)}


ETH_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
TRON_ADDR = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")  # base58 alphabet, 34 chars


def normalize_address(chain, address):
    """Per-chain normalisation (BRIEF 8.1, AUDIT N12). Raises 400 on malformed input, never allows it."""
    address = address.strip()
    if chain == "ethereum":
        if not ETH_ADDR.match(address):
            raise HTTPException(400, f"malformed ethereum address {address!r}: expected 0x plus 40 hex characters")
        return address.lower()
    if chain == "tron":
        if not TRON_ADDR.match(address):
            raise HTTPException(400, f"malformed tron address {address!r}: expected 34 base58 characters starting with T")
        return address
    raise HTTPException(422, "chain must be ethereum or tron")


def check_address(chain: str, address: str):
    return check(chain, normalize_address(chain, address))


def _route_paths(routes):
    """Every path served by `routes`, looking inside included routers (FastAPI 0.16x wraps them)."""
    paths = set()
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            prefix = getattr(r, "include_context", None)
            prefix = getattr(prefix, "prefix", "") or ""
            paths |= {prefix + p for p in _route_paths(inner.routes)}
        elif getattr(r, "path", None):
            paths.add(r.path)
    return paths


def _include_intake_router(target=None):
    """Include hound.intake.routes.router (CK's /intake/* routes) if the module exists.

    Same contract as the watch router: missing module = no intake routes (logged); a module that
    exists but is broken or has no APIRouter named router fails loudly at startup.
    """
    target = target or app
    try:
        mod = importlib.import_module("hound.intake.routes")
    except ModuleNotFoundError as e:
        if e.name != "hound.intake.routes":
            raise
        log.warning("hound.intake.routes not found: /intake/* routes are not served (web /intake and /c/[code] will 404)")
        return
    router = getattr(mod, "router", None)
    if not isinstance(router, APIRouter):
        raise RuntimeError("hound.intake.routes exists but has no FastAPI APIRouter named 'router'")
    target.include_router(router)
    log.info("included hound.intake.routes.router (%d routes)", len(router.routes))


def _include_watch_router(target=None):
    """Include hound.watch.routes.router (Jinka's /check) if it exists; else serve the fallback GET /check.

    The router is included first, so its /check wins; the fallback is added only when no /check exists.
    """
    target = target or app
    try:
        mod = importlib.import_module("hound.watch.routes")
    except ModuleNotFoundError as e:
        if e.name != "hound.watch.routes":
            raise  # the module exists but one of its imports is broken: fail loudly
        mod = None
    router = getattr(mod, "router", None) if mod else None
    if mod is not None and not isinstance(router, APIRouter):
        raise RuntimeError("hound.watch.routes exists but has no FastAPI APIRouter named 'router'")
    if router is not None:
        target.include_router(router)
        log.info("included hound.watch.routes.router (%d routes)", len(router.routes))
    if "/check" not in _route_paths(target.routes):
        log.warning("hound.watch.routes has no /check; serving the fallback /check")
        target.add_api_route("/check", check_address, methods=["GET"])


_include_watch_router()
_include_intake_router()


@app.get("/proof/scoreboard")
def scoreboard():
    with _LOCK:
        trace = TRACES.get(LAST_DONE.get(REPLAY_CASE))
    result = doj_scoreboard(trace)
    result["trace_source"] = trace.get("source") if trace else None  # "fixture" means not live adapters
    return result


@app.get("/proof/backtest")
def backtest():  # serves the batch result written by `python -m hound.proof.backtest`
    return backtest_serve()


@app.get("/scan/latest")
def scan():
    from hound.proof.scan import serve as scan_serve
    return scan_serve()


app.router.on_startup.append(_start_prewarm)  # served app only (not CLI imports); never blocks startup


@app.get("/health")
def health():
    return {"ok": True, "cases": len(CASES), "traces": len(TRACES), "jobs": len(JOBS),
            "example": bool(example("ohnd_replay.trace")), "skipped_cases": [s["file"] for s in SKIPPED_CASES],
            # The web host victims open (upload links, the replay QR); a public URL, not a secret.
            "public_base_url": os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or None,
            # The Hound phone line shown on the report page (public, it is the number victims call).
            "phone_number": os.environ.get("HOUND_PHONE_NUMBER", "").strip() or None}
