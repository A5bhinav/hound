"""Hound HTTP API (BRIEF 8.5). Ishaan wires routes; logic lives in each owner's module.

Run: cd backend && uvicorn hound.api:app --reload --port 8000
"""
import importlib
import json
import logging
import re
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from hound.contracts import ROOT, example, validate_case
from hound.engine.trace import DEFAULTS, _redact, run_trace
from hound.llm.writer import write_case
from hound.proof.backtest import serve as backtest_serve
from hound.proof.doj_ohnd import doj_scoreboard
from hound.proof.scan import weekend_scan
from hound.watch.check import check
from hound.watch.other_payers import other_payers

log = logging.getLogger("hound.api")
app = FastAPI(title="Hound")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory store for the hackathon. Curated cases are loaded from data/cases/ + examples/.
CASES = {}
TRACES = {}   # engine trace_id -> Trace
JOBS = {}     # job id (uuid4, returned as trace_id by POST /cases/{id}/trace) -> job state
LATEST = {}   # case_id -> latest job id (may be running or failed)
LAST_DONE = {}  # case_id -> trace_id of the latest successful trace; the packet reads this
_LOCK = threading.Lock()
_GENERATION = 0  # bumped by /demo/reset so a job started before the reset cannot write after it
CHAIN_FUNCS = ("get_transfers", "label", "freeze_status", "get_balance")
JOB_STALE_S = DEFAULTS["deadline_s"] + 30  # a running job older than this is hung and may be replaced


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_curated():
    files = sorted((ROOT / "data" / "cases").glob("*.case.json")) + [ROOT / "examples" / "ohnd_replay.case.json"]
    for f in files:
        if f.exists():
            c = validate_case(json.loads(f.read_text()))
            CASES[c["case_id"]] = c
    log.info("loaded %d curated cases", len(CASES))


_load_curated()


def _case(case_id):
    if case_id not in CASES:
        raise HTTPException(404, f"no case {case_id!r}")
    return CASES[case_id]


@app.get("/cases")
def list_cases():
    return [{"case_id": c["case_id"], "source": c["source"], "status": c["status"],
             "victim": c.get("victim"), "story": c.get("story")} for c in CASES.values()]


@app.post("/cases")
def create_case(case: dict):
    case.setdefault("case_id", f"case-{uuid.uuid4().hex[:8]}")
    case.setdefault("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    case.setdefault("status", "intake")
    try:
        validate_case(case)
    except ValueError as e:
        raise HTTPException(422, str(e))
    CASES[case["case_id"]] = case
    return case


def _chain_deps(case):
    """Returns (deps, using_fixture): real hound.chain adapters if merged, else the fixture chain (loud warning).

    get_native_txs is forwarded on both paths: run_trace needs it for ETH-send cases (the A.H.
    replay starts from six ETH sends). If the real chain has no get_native_txs yet and the case
    has ETH sends, the whole fixture chain is used, so one trace never mixes real and fixture data.
    """
    try:
        chain = importlib.import_module("hound.chain")
        missing = [k for k in CHAIN_FUNCS if not callable(getattr(chain, k, None))]
    except ImportError as e:
        missing = [f"import failed: {e}"]
    if not missing:
        deps = {k: getattr(chain, k) for k in CHAIN_FUNCS}
        deps["get_native_txs"] = getattr(chain, "get_native_txs", None)
        if deps["get_native_txs"] is not None or not any(s.get("token") == "ETH" for s in case["sends"]):
            return deps, False
        missing = ["get_native_txs (case has ETH sends)"]
    log.warning("REAL CHAIN ADAPTERS MISSING (%s), tracing on fixture data from examples/ohnd_transfers.json",
                ", ".join(missing))
    from hound import fixture_chain as fc
    return {k: getattr(fc, k) for k in CHAIN_FUNCS + ("get_native_txs",)}, True


def _attach_other_payers(job_id, trace, using_fixture):
    """other_payers reads the live hound.chain, so it is skipped on fixture traces (never mix data)
    and a failure in it leaves the finished trace intact with other_payers = []."""
    if using_fixture:
        log.warning("trace job %s ran on fixture data; other_payers skipped (it would read the live chain)", job_id)
        trace["other_payers"] = []
        return
    try:
        trace["other_payers"] = other_payers(trace)
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
        deps, using_fixture = _chain_deps(case)
        trace = run_trace(case, progress=progress, **deps)
    except Exception as e:  # report every engine failure to the poller, never swallow it
        # Full detail stays in the server log (secrets redacted); the poller gets the type only,
        # because adapter errors can carry request URLs with API keys in them.
        log.error("trace job %s for case %s failed: %s", job_id, case["case_id"], _redact(traceback.format_exc()))
        with _LOCK:
            job = JOBS.get(job_id)
            if _finish(job_id, generation, ok=False):
                job.update(status="error", error=f"{type(e).__name__}: trace failed; see the server log for job {job_id}")
        return
    _attach_other_payers(job_id, trace, using_fixture)
    with _LOCK:
        if not _finish(job_id, generation, ok=True, trace=trace):
            return
    log.info("trace job %s done: %s (%s)", job_id, trace["trace_id"], trace["status"])


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
def trace_case(case_id: str):
    case = _case(case_id)
    job_id = uuid.uuid4().hex
    with _LOCK:
        prev_id = LATEST.get(case_id)
        prev = JOBS.get(prev_id)
        if prev and prev["status"] == "running":
            age = time.monotonic() - prev["started_mono"]
            if age <= JOB_STALE_S:
                return _job_view(prev_id)  # one trace per case at a time
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
    threading.Thread(target=_run_job, args=(job_id, case, generation, progress), daemon=True,
                     name=f"trace-{job_id[:8]}").start()
    return view


@app.get("/cases/{case_id}/trace")
def case_trace(case_id: str):
    _case(case_id)
    with _LOCK:
        if case_id not in LATEST:
            raise HTTPException(404, f"case {case_id!r} has no trace; POST /cases/{case_id}/trace first")
        return _job_view(LATEST[case_id])


@app.get("/traces/{trace_id}")
def get_trace(trace_id: str):
    with _LOCK:
        if trace_id in JOBS:
            return _job_view(trace_id)
        if trace_id in TRACES:
            return TRACES[trace_id]
    raise HTTPException(404, f"no trace {trace_id!r}")


@app.get("/cases/{case_id}/packet")
def packet(case_id: str, audience: str = "detective"):
    case = _case(case_id)
    with _LOCK:
        trace = TRACES.get(LAST_DONE.get(case_id))
    if trace is None:
        raise HTTPException(409, f"case {case_id!r} has no finished trace yet; POST /cases/{case_id}/trace and poll it first")
    return {"packet": write_case(trace, case, audience), "trace": trace}


@app.post("/demo/reset")
def demo_reset():
    global _GENERATION
    with _LOCK:
        _GENERATION += 1
        CASES.clear()
        TRACES.clear()
        JOBS.clear()
        LATEST.clear()
        LAST_DONE.clear()
        _load_curated()
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


@app.get("/proof/scoreboard")
def scoreboard():
    return doj_scoreboard()


@app.get("/proof/backtest")
def backtest():  # serves the batch result written by `python -m hound.proof.backtest`
    return backtest_serve()


@app.get("/scan/latest")
def scan():
    return weekend_scan()


@app.get("/health")
def health():
    return {"ok": True, "cases": len(CASES), "traces": len(TRACES), "jobs": len(JOBS), "example": bool(example("ohnd_replay.trace"))}
