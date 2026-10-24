"""End-to-end check of the whole demo flow, the way demo day runs it.

Boots the backend (readonly snapshot, no network) and the production web build, then drives every
step through the web's /api proxy exactly like the browser:
picker -> trace (POST + poll) -> hold (/check) -> packet (both audiences) -> proof -> every page.
Then: a victim intake end to end (start -> typed send via the upload route -> validated on chain ->
trace -> not held until the operator approves -> held), a judge's own POST /cases (traced, never held),
the error paths (422/404/409/400/403), and /demo/reset last. One extra step (typed tx hash) needs the
receipt, which the readonly snapshot lacks: it runs on a second backend in prefer_cache mode and is a
WARN when the chain is unreachable. E2E_NO_LIVE_CHAIN=1 skips it.

    make e2e                 # from the repo root
    E2E_KEEP=1 make e2e      # leave both servers running afterwards for a browser click-through

Exit code 0 only if every required step passes. Known gaps are listed as WARN, never hidden.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = os.environ.get("PY", str(ROOT / "backend" / ".venv" / "bin" / "python"))
A1 = "0xcf9bbfa762ef5a84ba3d25350de941a6db485027"           # DOJ A-1: must HOLD after the replay
BINANCE = "0x28c6c06298d514db089934071355e5743bf21d60"      # Binance 14 hot wallet: must ALLOW
REPLAY = "ohnd-replay-ah"
results = []


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http(method, url, timeout=30, body=None, headers=None):
    """body: dict -> JSON, bytes -> sent as is (set Content-Type in headers)."""
    h = {"Accept": "application/json, text/html", **(headers or {})}
    if isinstance(body, dict):
        body, h["Content-Type"] = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def jget(code, body):
    try:
        return json.loads(body) if code and body else {}
    except json.JSONDecodeError:
        return {}


def multipart(fields):
    """multipart/form-data body for text fields (the upload page posts `typed` this way)."""
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in fields.items()]
    return ("".join(parts) + f"--{boundary}--\r\n").encode(), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def step(name, ok, detail="", required=True):
    results.append((name, "PASS" if ok else ("FAIL" if required else "WARN"), detail))
    print(f"  {'PASS' if ok else ('FAIL' if required else 'WARN'):4}  {name}  {detail}", flush=True)
    return ok


def wait_for(url, seconds, proc, what):
    end = time.time() + seconds
    while time.time() < end:
        if proc.poll() is not None:
            raise SystemExit(f"{what} exited early with code {proc.returncode}; see its log")
        code, _ = http("GET", url, timeout=3)
        if code == 200:
            return
        time.sleep(0.5)
    raise SystemExit(f"{what} did not come up at {url} within {seconds}s")


LIVE_INTAKE_CASE = ROOT / "data" / "cases_live" / "mindchain-binance.case.json"
TRACES_SEEN = {}  # case_id -> finished trace from trace_via_web
JUDGE_TX_TO = "0xcf9bbfa762ef5a84ba3d25350de941a6db485027"  # a judge's own send: 20,000 USDT into A-1 (DOJ data)


def trace_via_web(web, cid, tag):
    """POST trace + poll through the web proxy, like the case page. Returns the finished trace or None."""
    t0 = time.time()
    code, body = http("POST", f"{web}/api/cases/{cid}/trace")
    job = jget(code, body)
    if not step(f"[{tag}] POST trace returns a job", code == 200 and job.get("status") == "running", f"{code}"):
        return None
    while time.time() - t0 < 180:
        v = jget(*http("GET", f"{web}/api/traces/{job['trace_id']}"))
        if v.get("status") != "running":
            break
        time.sleep(0.5)
    ok = v.get("status") in ("done", "partial")
    if ok:
        TRACES_SEEN[cid] = v
    step(f"[{tag}] trace finishes (done or partial)", ok, f"status={v.get('status')} {time.time() - t0:.1f}s {v.get('error') or ''}")
    return v if ok else None


def packets_render(api, cid, tag):
    for aud in ("victim", "detective"):
        code, b = http("GET", f"{api}/cases/{cid}/packet?audience={aud}", timeout=90)
        p = jget(code, b).get("packet", {})
        cv = p.get("citations_verified") or {}
        step(f"[{tag}] {aud} packet", code == 200 and bool(p.get("text")) and cv.get("verified") == cv.get("total"),
             f"{code} source={p.get('source')} citations={cv}")


def held_for(api, trace, cid):
    """Addresses in `trace` whose /check evidence names case `cid` (the case feeds the watchlist)."""
    hits = []
    for n in trace.get("nodes", []):
        if n.get("chain", "ethereum") != "ethereum" or n.get("kind") == "victim":
            continue
        ev = jget(*http("GET", f"{api}/check?chain=ethereum&address={n['address']}")).get("evidence", {})
        if cid in (ev.get("case_ids") or []):
            hits.append(n["address"])
    return hits


def intake_flow(api, web):
    """(1) A victim's intake, end to end: start -> active -> typed send through the upload page's proxy
    route -> validated on chain -> trace -> NOT on the watchlist -> operator approve -> on the watchlist."""
    if not LIVE_INTAKE_CASE.exists():
        step("intake: real victim send available (data/cases_live/mindchain-binance.case.json)", False,
             "missing on this laptop; intake flow not run", required=False)
        return
    send = json.loads(LIVE_INTAKE_CASE.read_text())["sends"][0]
    code, b = http("POST", f"{api}/intake/start", body={"story": {"summary": "e2e intake"}, "victim": {"alias": "e2e caller"}})
    s = jget(code, b)
    cc = s.get("case_code") or ""
    if not step("intake: POST /intake/start (localhost)", code == 200 and len(cc) == 6 and (s.get("upload_url") or "") == f"{web}/c/{cc}", f"{code} {s.get('upload_url')}"):
        return
    a = jget(*http("GET", f"{api}/intake/active"))
    step("intake: /intake/active on localhost shows the code and link", a.get("case_code") == cc and a.get("upload_url") == s["upload_url"],
         f"status={a.get('status')}")
    a = jget(*http("GET", f"{api}/intake/active", headers={"X-Forwarded-For": "203.0.113.9"}))
    step("intake: /intake/active through a proxy hides the code and link", a.get("case_code") != cc and a.get("upload_url") is None,
         f"case_code={a.get('case_code')}")
    # The live case card polls this through the web proxy: the operator's own browser (localhost) sees the
    # code to read out; a visitor through the tunnel (cloudflared adds these headers, Next forwards them) must not.
    a = jget(*http("GET", f"{web}/api/intake/active"))
    step("intake: web /api/intake/active on the operator's laptop shows the code", a.get("case_code") == cc, f"{a.get('case_code')}")
    for h in ({"X-Forwarded-For": "203.0.113.9"}, {"CF-Connecting-IP": "203.0.113.9"}):
        a = jget(*http("GET", f"{web}/api/intake/active", headers=h))
        step(f"intake: web /api/intake/active via a tunnel ({next(iter(h))}) hides the code and link",
             a.get("status") and a.get("case_code") != cc and a.get("upload_url") is None, f"case_code={a.get('case_code')}")
    code, html = http("GET", f"{web}/c/{cc}", timeout=60)
    step(f"page /c/{{code}} (victim upload page) renders", code == 200 and cc in html, f"{code}")

    when = send["time"][:16].replace("T", " ")
    typed = f"I sent {send['amount']:,.2f} USDT to {send['to']} on {when}"
    body, hdr = multipart({"typed": typed})
    code, b = http("POST", f"{web}/api/intake/{cc}/screenshot", body=body, headers=hdr, timeout=90)
    r = jget(code, b)
    cid = r.get("case_id") or ""
    if not step("intake: typed send via web /api/intake/{code}/screenshot validated on chain (readonly cache)",
                code == 200 and r.get("status") == "validated" and cid.startswith("intake-"), f"{code} {b[:160]}"):
        return
    st = jget(*http("GET", f"{api}/intake/{cc}"))
    step("intake: session is validated and names the case", st.get("status") == "validated" and st.get("case_id") == cid, f"{st.get('status')}")
    body, hdr = multipart({"typed": typed})
    code, _ = http("POST", f"{web}/api/intake/{cc}/screenshot", body=body, headers=hdr)
    step("intake: a second upload on a validated session is refused (409)", code == 409, f"{code}")

    rows = jget(*http("GET", f"{api}/cases")) or []
    case = next((c for c in rows if c.get("case_id") == cid), {})
    sent = (case.get("sends") or [{}])[0]
    step("intake: new case in GET /cases with the on-chain send", case.get("source") == "screenshot"
         and sent.get("tx_hash") == send["tx_hash"] and sent.get("from") == send["from"], f"{sent.get('tx_hash', '')[:14]}")

    trace = trace_via_web(web, cid, "intake")
    if trace is None:
        return
    step("[intake] trace has nodes and edges", bool(trace.get("nodes")) and bool(trace.get("edges")),
         f"{len(trace.get('nodes', []))} nodes, {len(trace.get('edges', []))} edges")
    early = held_for(api, trace, cid)
    step("[intake] before approval: /check holds nothing on its account", not early, f"{early}")

    code, _ = http("POST", f"{api}/intake/{cc}/approve", body={"case_id": cid}, headers={"X-Forwarded-For": "203.0.113.9"})
    step("intake: approve through a proxy is refused (403)", code == 403, f"{code}")
    code, _ = http("POST", f"{api}/intake/{cc}/approve", body={"case_id": "intake-wrong"})
    step("intake: approve naming the wrong case is refused (409)", code == 409, f"{code}")
    code, b = http("POST", f"{api}/intake/{cc}/approve", body={"case_id": cid})
    step("intake: operator approve (localhost)", code == 200 and jget(code, b).get("status") == "approved", f"{code}")
    late = held_for(api, trace, cid)
    step("[intake] after approval: its traced wallets feed /check (no re-trace needed)", bool(late), f"{len(late)} addresses")
    packets_render(api, cid, "intake")
    code, html = http("GET", f"{web}/cases/{cid}", timeout=60)
    step(f"page /cases/{{intake case}} renders", code == 200 and cid in html, f"{code}")
    return cid


def judge_case(api, web):
    """(2) A judge's own case typed into POST /cases: traced and written up, never on the watchlist."""
    tx = json.loads((ROOT / "examples" / "ohnd_transfers.json").read_text())
    t = next(x for x in tx if x["to"] == JUDGE_TX_TO and x["token"] == "USDT" and x["amount"] == 20000.0)
    case = {"source": "phone", "victim": {"alias": "e2e judge"}, "story": {"summary": "a judge's own scenario"},
            "sends": [{k: t[k] for k in ("chain", "tx_hash", "from", "to", "token", "amount", "time")}]}
    case["sends"][0]["to"] = t["to"].upper().replace("0X", "0x")  # mixed case: the API must normalise it
    code, b = http("POST", f"{api}/cases", body=case)
    c = jget(code, b)
    cid = c.get("case_id") or ""
    if not step("judge: POST /cases creates a case", code == 200 and cid.startswith("case-")
                and c["sends"][0]["to"] == JUDGE_TX_TO, f"{code} {b[:120] if code != 200 else cid}"):
        return
    code, _ = http("GET", f"{api}/cases/{cid}/packet")
    step("judge: packet before trace is 409", code == 409, f"{code}")
    code, _ = http("GET", f"{api}/cases/{cid}/trace")
    step("judge: GET trace before any trace is 404", code == 404, f"{code}")
    trace = trace_via_web(web, cid, "judge")
    if trace is None:
        return
    step("[judge] trace has nodes and edges", bool(trace.get("nodes")) and bool(trace.get("edges")),
         f"{len(trace.get('nodes', []))} nodes, {len(trace.get('edges', []))} edges")
    packets_render(api, cid, "judge")
    hits = held_for(api, trace, cid)
    step("[judge] never feeds the watchlist (no /check evidence names it)", not hits, f"{hits}")
    code, html = http("GET", f"{web}/cases/{cid}", timeout=60)
    step("page /cases/{judge case} renders", code == 200 and cid in html, f"{code}")
    code, html = http("GET", f"{web}/cases/{cid}/packet", timeout=90)
    step("page /cases/{judge case}/packet renders", code == 200 and cid in html, f"{code}", required=False)
    return cid


def error_paths(api, web):
    """(3) The API says no clearly."""
    base = {"source": "phone", "victim": {"alias": "x"}, "story": {},
            "sends": [{"chain": "ethereum", "tx_hash": "0x" + "ab" * 32, "from": "0x" + "11" * 20, "to": "0x" + "22" * 20,
                       "token": "DAI", "amount": 10, "time": "2024-05-01T00:00:00Z"}]}
    code, b = http("POST", f"{api}/cases", body=base)
    step("422: POST /cases unsupported token", code == 422 and "DAI" in b, f"{code}")
    mixed = json.loads(json.dumps(base))
    mixed["sends"][0]["token"] = "USDT"
    mixed["sends"].append({"chain": "tron", "tx_hash": "cd" * 32, "from": "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE",
                           "to": "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE", "token": "USDT", "amount": 10, "time": "2024-05-01T00:00:00Z"})
    code, b = http("POST", f"{api}/cases", body=mixed)
    step("422: POST /cases mixed chains", code == 422 and "one chain" in b, f"{code}")
    code, _ = http("GET", f"{api}/cases/no-such-case/packet")
    step("404: packet for an unknown case", code == 404, f"{code}")
    code, _ = http("POST", f"{web}/api/cases/no-such-case/trace")
    step("404: web trace for an unknown case", code == 404, f"{code}")
    code, _ = http("GET", f"{web}/api/traces/no-such-trace")
    step("404: web poll for an unknown trace", code == 404, f"{code}")
    code, _ = http("GET", f"{web}/api/check?chain=tron&address=Tnope")
    step("400: /check malformed tron address", code == 400, f"{code}")
    body, hdr = multipart({"typed": "x"})
    code, _ = http("POST", f"{web}/api/intake/ZZZZZZ/screenshot", body=body, headers=hdr)
    step("404: upload to an unknown case code", code == 404, f"{code}")


def demo_reset(api, web, extra_ids, watched):
    """Last: /demo/reset. A proxied caller is refused; localhost clears the in-memory cases + watchlist."""
    code, _ = http("POST", f"{api}/demo/reset", headers={"X-Forwarded-For": "127.0.0.1"})
    step("403: /demo/reset with X-Forwarded-For (even 127.0.0.1) is refused", code == 403, f"{code}")
    code, _ = http("POST", f"{web}/api/demo/reset", headers={"X-Forwarded-For": "203.0.113.9"})
    step("403: web /api/demo/reset from a tunnel visitor is refused", code == 403, f"{code}")
    code, b = http("POST", f"{web}/api/demo/reset")
    step("web Reset button (/api/demo/reset through the proxy) works from localhost", code == 200, f"{code} {b[:100]}")
    code, b = http("POST", f"{api}/demo/reset")
    step("/demo/reset from localhost", code == 200 and jget(code, b).get("ok"), f"{code} {b[:80]}")
    ids = {c["case_id"] for c in jget(*http("GET", f"{api}/cases")) or []}
    step("after reset: intake and judge cases are gone, curated cases back", REPLAY in ids and not (ids & set(extra_ids)), f"{sorted(ids)}")
    code, b = http("GET", f"{web}/api/intake/active")
    step("after reset: no intake session is left on screen (204 from /api/intake/active)", code == 204, f"{code} {b[:100]}")
    for cid, trace in watched:
        left = held_for(api, trace, cid)
        step(f"after reset: watchlist no longer names {cid}", not left, f"{left}")


def intake_typed_hash_live(logs):
    """The typed-hash path reads the tx receipt, which the readonly snapshot does not hold, so this one
    step runs on a separate backend in HOUND_CACHE_MODE=prefer_cache (live chain, private temp cache).
    Offline it is a WARN, never a fake pass."""
    port = free_port()
    api = f"http://127.0.0.1:{port}"
    env = dict(os.environ, HOUND_CACHE_MODE="prefer_cache", HOUND_CACHE_DIR=str(logs / "cache_prefer"))
    proc = subprocess.Popen([PY, "-m", "uvicorn", "hound.api:app", "--port", str(port)], cwd=ROOT / "backend",
                            env=env, stdout=open(logs / "backend-prefer-cache.log", "w"), stderr=subprocess.STDOUT)
    try:
        wait_for(f"{api}/health", 60, proc, "prefer_cache backend")
        send = next(x for x in json.loads((ROOT / "examples" / "ohnd_replay.case.json").read_text())["sends"])
        cc = jget(*http("POST", f"{api}/intake/start", body={})).get("case_code")
        body, hdr = multipart({"typed": f"tx {send['tx_hash']} amount {send['amount']} {send['token']}"})
        code, b = http("POST", f"{api}/intake/{cc}/screenshot", body=body, headers=hdr, timeout=120)
        r = jget(code, b)
        offline = r.get("status") == "needs_retake" and "reach the blockchain" in (r.get("message") or "")
        ok = r.get("status") == "validated"
        if ok:
            case = next((c for c in jget(*http("GET", f"{api}/cases")) if c["case_id"] == r["case_id"]), {})
            s0 = (case.get("sends") or [{}])[0]
            ok = s0.get("tx_hash") == send["tx_hash"] and s0.get("from") == send["from"] and s0.get("token") == send["token"]
        step("[prefer_cache: live chain] intake: typed DOJ replay tx hash validated from its receipt", ok,
             f"{code} {b[:160]}", required=not offline)
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _stat(path):
    """(mtime_ns, size) of a file, or None when it does not exist."""
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return None


def main():
    logs = ROOT / ".e2e"
    logs.mkdir(exist_ok=True)
    bport, wport = free_port(), free_port()
    api = f"http://127.0.0.1:{bport}"
    web = f"http://127.0.0.1:{wport}"
    # Private cache dir: the run registers an intake case and then calls /demo/reset, which deletes
    # <cache>/watchlist.json. Never let that touch the real <repo>/cache (demo traces live there).
    cache_ro = logs / "cache_readonly"
    shutil.rmtree(cache_ro, ignore_errors=True)
    real_wl = ROOT / "cache" / "watchlist.json"
    real_before = _stat(real_wl)
    env = dict(os.environ, HOUND_CACHE_MODE="readonly", HOUND_CACHE_DIR=str(cache_ro), PUBLIC_BASE_URL=web)
    env.pop("ANTHROPIC_API_KEY", None) if os.environ.get("E2E_NO_CLAUDE") else None
    procs = []
    try:
        print(f"backend :{bport}  web :{wport}  logs {logs}/", flush=True)
        procs.append(subprocess.Popen([PY, "-m", "uvicorn", "hound.api:app", "--port", str(bport)], cwd=ROOT / "backend",
                                      env=env, stdout=open(logs / "backend.log", "w"), stderr=subprocess.STDOUT))
        wait_for(f"{api}/health", 60, procs[-1], "backend")
        wenv = dict(os.environ, HOUND_API_URL=api, HOUND_DATA="", PORT=str(wport), HOUND_NEXT_DIST_DIR=".next-e2e")
        # Always rebuild: next build bakes HOUND_API_URL into the /api proxy, so a stale build points
        # the proxy at an old backend port (500 on every proxied route).
        print("building web (next build)...", flush=True)
        b = subprocess.run(["npx", "next", "build"], cwd=ROOT / "web", env=wenv,
                           stdout=open(logs / "web-build.log", "w"), stderr=subprocess.STDOUT)
        if not step("web production build", b.returncode == 0, f"see {logs}/web-build.log"):
            return
        procs.append(subprocess.Popen(["npx", "next", "start", "-p", str(wport)], cwd=ROOT / "web", env=wenv,
                                      stdout=open(logs / "web.log", "w"), stderr=subprocess.STDOUT))
        wait_for(f"{web}/", 90, procs[-1], "web")

        _, h = http("GET", f"{api}/health")
        health = json.loads(h)
        step("backend health, no skipped curated cases", health.get("ok") and not health.get("skipped_cases"),
             f"cases={health.get('cases')} skipped={health.get('skipped_cases')}")

        # The web proxy exposes ONLY the browser routes (trace, poll, check, intake) by design; cases,
        # packets and proof are fetched server-side by the pages. So those are checked on the backend
        # here, and the pages are checked for the content they render.
        code, body = http("GET", f"{api}/cases")
        cases = json.loads(body) if code == 200 else []
        ids = [c["case_id"] for c in cases]
        step("GET /cases (backend, used server-side by the picker)", code == 200 and REPLAY in ids, f"{ids}")
        code, _ = http("GET", f"{web}/api/cases")
        step("web proxy does NOT expose /api/cases (public origin stays narrow)", code != 200 or _ == "[]", f"{code}", required=False)
        step("full case objects (sends present)", all("sends" in c for c in cases))
        live = [i for i in ids if i.startswith("live-")]
        step("live case bundle present on this laptop", bool(live), f"{live or 'data/cases_live/ is empty'}", required=False)

        for cid in [REPLAY] + live:
            t0 = time.time()
            code, body = http("POST", f"{web}/api/cases/{cid}/trace")
            job = json.loads(body) if code == 200 else {}
            if not step(f"[{cid}] POST trace returns a job", code == 200 and job.get("status") == "running", f"{code}"):
                continue
            trace, polls, seen_live = None, 0, 0
            while time.time() - t0 < 180:
                _, b = http("GET", f"{web}/api/traces/{job['trace_id']}")
                v = json.loads(b)
                polls += 1
                if v.get("status") == "running":
                    seen_live = max(seen_live, len(v.get("audit_log_so_far", [])))
                    time.sleep(0.5)
                    continue
                trace = v
                break
            ok = trace is not None and trace.get("status") in ("done", "partial")
            step(f"[{cid}] trace finishes", ok, f"status={trace and trace.get('status')} {time.time() - t0:.1f}s polls={polls}")
            if not ok:
                continue
            step(f"[{cid}] trace has nodes, edges, endpoints",
                 all(trace.get(k) for k in ("nodes", "edges", "endpoints")),
                 f"{len(trace['nodes'])} nodes, {len(trace['edges'])} edges, {len(trace['endpoints'])} endpoints")
            step(f"[{cid}] status done (not partial)", trace["status"] == "done", trace["status"], required=(cid == REPLAY))
            for aud in ("victim", "detective"):
                code, b = http("GET", f"{api}/cases/{cid}/packet?audience={aud}", timeout=60)
                p = json.loads(b).get("packet", {}) if code == 200 else {}
                cv = p.get("citations_verified") or {}
                step(f"[{cid}] {aud} packet", code == 200 and p.get("text") and cv.get("verified") == cv.get("total"),
                     f"{code} source={p.get('source')} citations={cv}")

        code, b = http("GET", f"{web}/api/check?chain=ethereum&address={A1}")
        step("hold: /check A-1 after the replay", code == 200 and json.loads(b).get("decision") == "hold", b[:120])
        code, b = http("GET", f"{web}/api/check?chain=ethereum&address={BINANCE}")
        step("allow: /check Binance 14 hot wallet", code == 200 and json.loads(b).get("decision") == "allow", b[:120])
        code, _ = http("GET", f"{web}/api/check?chain=ethereum&address=0xnope")
        step("400: /check malformed address", code == 400, f"{code}")

        code, b = http("GET", f"{api}/proof/scoreboard")
        sb = json.loads(b).get("summary", {}) if code == 200 else {}
        step("proof: scoreboard 8/8, 3/3, green/green/amber, blind",
             sb.get("intermediates_reached") == 8 and sb.get("finals_reached") == 3 and sb.get("blind")
             and sb.get("amount_bands") == {"A-7": "green", "A-8": "green", "A-9": "amber"}, json.dumps(sb)[:200])
        code, b = http("GET", f"{api}/proof/backtest")
        bt = json.loads(b) if code == 200 else {}
        step("proof: backtest batch result present", bt.get("n", 0) > 0,
             f"n={bt.get('n')} median_h={bt.get('detection_lag_median_h')} escape={bt.get('escape_share_median')}")
        code, b = http("GET", f"{api}/scan/latest")
        step("proof: scan route answers (batch result or not_computed)", code == 200, b[:100], required=False)

        for path, must in [("/", REPLAY), (f"/cases/{REPLAY}", REPLAY), (f"/cases/{REPLAY}/packet", "REPLAY"),
                           ("/proof", "A-7"), ("/proof", "1:25-cv-00386"), ("/exchange", ""), ("/intake", "")]:
            code, html = http("GET", f"{web}{path}", timeout=60)
            step(f"page {path} renders", code == 200 and (must in html), f"{code}")

        code, _ = http("GET", f"{web}/api/intake/active")
        step("intake: GET /api/intake/active served (200 session or 204 none)", code in (200, 204), f"{code}")

        print("-- intake, a judge's own case, error paths --", flush=True)
        intake_id = intake_flow(api, web)
        judge_id = judge_case(api, web)
        error_paths(api, web)
        watched = []
        if intake_id:
            watched.append((intake_id, TRACES_SEEN.get(intake_id)))
        demo_reset(api, web, [i for i in (intake_id, judge_id) if i], [w for w in watched if w[1]])
        if not os.environ.get("E2E_NO_LIVE_CHAIN"):
            intake_typed_hash_live(logs)
        step("the repo's real cache/watchlist.json was not touched", _stat(real_wl) == real_before,
             f"before {real_before} after {_stat(real_wl)}")
    except SystemExit as e:
        # a server that never came up must fail the run, not vanish into the finally block
        step("servers booted", False, str(e))
    finally:
        if not results:
            step("at least one check ran", False, "nothing was checked")
        failed = [r for r in results if r[1] == "FAIL"]
        warned = [r for r in results if r[1] == "WARN"]
        print(f"\n{len(results) - len(failed) - len(warned)} pass, {len(warned)} warn, {len(failed)} fail")
        for n, s, d in failed + warned:
            print(f"  {s}: {n}  {d}")
        if os.environ.get("E2E_KEEP"):
            print(f"\nservers left running: web {web}  backend {api}")
        else:
            for p in procs:
                p.send_signal(signal.SIGINT)
            for p in procs:
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
        sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
