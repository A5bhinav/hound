"""AUDIT issue 14: no holdout address may appear in engine code, prompts or the replay Case,
except the four input seeds. The engine must never import proof/ or read data/doj/."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOLD = json.load(open(ROOT / "data" / "doj" / "holdout.json"))
ENTRIES = {e["label"]: e for e in HOLD["entries"]}
ALLOWED = {ENTRIES[l]["full"].lower() for l in ("d95", "A-1", "B-1", "C-1")}
SECRET = {e["full"].lower(): e["label"] for e in HOLD["entries"] if e["full"].lower() not in ALLOWED}
# fixture that IS the chain (raw transfers served by fixture_chain) necessarily contains every wallet
CHAIN_FIXTURES = {"examples/ohnd_transfers.json"}
# fixture_chain.py serves that same chain data plus Tether's public freeze events for the finals.
# Per BRIEF §0 / AUDIT N1 those freezes must be HIDDEN from the engine during the replay
# (freeze_visibility=hidden) and revealed by the UI afterwards; owner Ishaan. Exempt here as chain data.
CHAIN_CODE = {"backend/hound/fixture_chain.py"}


def _code_files():
    for p in (ROOT / "backend" / "hound").rglob("*.py"):
        if "proof" in p.parts or str(p.relative_to(ROOT)) in CHAIN_CODE:
            continue
        yield p
    for p in (ROOT / "examples").glob("*.json"):
        if str(p.relative_to(ROOT)) not in CHAIN_FIXTURES:
            yield p


def test_no_holdout_address_in_engine_code_or_replay_fixtures():
    leaks = []
    for p in _code_files():
        txt = p.read_text(errors="ignore").lower()
        for addr, lab in SECRET.items():
            if addr in txt:
                leaks.append((str(p.relative_to(ROOT)), lab))
        for lab, e in ENTRIES.items():
            if e["full"].lower() in ALLOWED:
                continue
            pat = re.compile(re.escape(e["prefix"].lower()) + r"[0-9a-f]{%d}" % (40 - len(e["prefix"]) + 2 - len(e["suffix"])) + re.escape(e["suffix"].lower()))
            if p.suffix == ".py" and pat.search(txt):
                leaks.append((str(p.relative_to(ROOT)), lab + " (prefix…suffix)"))
    # examples/ohnd_replay.trace.json is engine output and legitimately contains reached wallets;
    # it must be marked hand_built or engine so the scoreboard can tell.
    leaks = [l for l in leaks if not l[0].endswith("ohnd_replay.trace.json")]
    assert not leaks, f"holdout leak(s): {leaks}"


def test_engine_never_imports_proof_or_reads_data_doj():
    bad = []
    for p in (ROOT / "backend" / "hound").rglob("*.py"):
        if "proof" in p.parts or p.name == "api.py":
            continue
        txt = p.read_text(errors="ignore")
        if re.search(r"from\s+hound\.proof|import\s+hound\.proof|data/doj|data\\doj", txt):
            bad.append(str(p.relative_to(ROOT)))
    assert not bad, bad


def test_replay_trace_fixture_declares_source():
    p = ROOT / "examples" / "ohnd_replay.trace.json"
    if p.exists():
        t = json.load(open(p))
        assert t.get("source") in ("hand_built", "engine", None)  # None tolerated until Ishaan's schema change lands
