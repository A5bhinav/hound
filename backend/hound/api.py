"""Hound HTTP API (BRIEF 8.5). Ishaan wires routes; logic lives in each owner's module.

Run: cd backend && uvicorn hound.api:app --reload --port 8000
"""
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from hound.contracts import ROOT, example, validate_case
from hound.engine.trace import run_trace
from hound.llm.writer import write_case
from hound.proof.backtest import freeze_backtest
from hound.proof.doj_ohnd import doj_scoreboard
from hound.proof.scan import weekend_scan
from hound.watch.check import check
from hound.watch.other_payers import other_payers

log = logging.getLogger("hound.api")
app = FastAPI(title="Hound")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory store for the hackathon. Curated cases are loaded from data/cases/ + examples/.
CASES = {}
TRACES = {}


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


@app.post("/cases/{case_id}/trace")
def trace_case(case_id: str):
    case = _case(case_id)
    case["status"] = "tracing"
    try:
        trace = run_trace(case)
    except RuntimeError as e:
        log.warning("REAL CHAIN ADAPTERS MISSING, tracing on fixture data: %s", e)
        from hound import fixture_chain as fc
        trace = run_trace(case, get_transfers=fc.get_transfers, label=fc.label,
                          freeze_status=fc.freeze_status, get_balance=fc.get_balance,
                          get_native_txs=fc.get_native_txs)
    trace["other_payers"] = other_payers(trace)
    TRACES[trace["trace_id"]] = trace
    case["status"] = "traced"
    return trace


@app.get("/traces/{trace_id}")
def get_trace(trace_id: str):
    if trace_id not in TRACES:
        raise HTTPException(404, f"no trace {trace_id!r}")
    return TRACES[trace_id]


@app.get("/cases/{case_id}/packet")
def packet(case_id: str, audience: str = "detective"):
    case = _case(case_id)
    trace = next((t for t in TRACES.values() if t["case_id"] == case_id), None)
    if trace is None:
        raise HTTPException(409, f"case {case_id!r} has not been traced yet; POST /cases/{case_id}/trace first")
    return {"packet": write_case(trace, case, audience), "trace": trace}


@app.get("/check")
def check_address(chain: str, address: str):
    if chain not in ("ethereum", "tron"):
        raise HTTPException(422, "chain must be ethereum or tron")
    return check(chain, address)


@app.get("/proof/scoreboard")
def scoreboard():
    return doj_scoreboard()


@app.get("/proof/backtest")
def backtest():
    return freeze_backtest()


@app.get("/scan/latest")
def scan():
    return weekend_scan()


@app.get("/health")
def health():
    return {"ok": True, "cases": len(CASES), "traces": len(TRACES), "example": bool(example("ohnd_replay.trace"))}
