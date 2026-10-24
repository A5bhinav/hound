"""End-to-end check of the whole demo flow, the way demo day runs it.

Boots the backend (readonly snapshot, no network) and the production web build, then drives every
step through the web's /api proxy exactly like the browser:
picker -> trace (POST + poll) -> hold (/check) -> packet (both audiences) -> proof -> every page.

    make e2e                 # from the repo root
    E2E_KEEP=1 make e2e      # leave both servers running afterwards for a browser click-through

Exit code 0 only if every required step passes. Known gaps are listed as WARN, never hidden.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
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


def http(method, url, timeout=30):
    req = urllib.request.Request(url, method=method, headers={"Accept": "application/json, text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


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


def main():
    logs = ROOT / ".e2e"
    logs.mkdir(exist_ok=True)
    bport, wport = free_port(), free_port()
    api = f"http://127.0.0.1:{bport}"
    web = f"http://127.0.0.1:{wport}"
    env = dict(os.environ, HOUND_CACHE_MODE="readonly")
    env.pop("ANTHROPIC_API_KEY", None) if os.environ.get("E2E_NO_CLAUDE") else None
    procs = []
    try:
        print(f"backend :{bport}  web :{wport}  logs {logs}/", flush=True)
        procs.append(subprocess.Popen([PY, "-m", "uvicorn", "hound.api:app", "--port", str(bport)], cwd=ROOT / "backend",
                                      env=env, stdout=open(logs / "backend.log", "w"), stderr=subprocess.STDOUT))
        wait_for(f"{api}/health", 60, procs[-1], "backend")
        wenv = dict(os.environ, HOUND_API_URL=api, HOUND_DATA="", PORT=str(wport))
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
        step("intake: GET /api/intake/active served", code == 200, f"{code} (CK's hound/intake/routes.py)", required=False)
    finally:
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
