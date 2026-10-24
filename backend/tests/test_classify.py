from hound import fixture_chain
from hound.llm.classify import classify, features, rules

DOJ_PATH = ["0xcf9bbfa762ef5a84ba3d25350de941a6db485027", "0x78366b2f6c5321ac30629c078120385ae2da1a06",
            "0x9eb0c71e79066552bdd05a69fc4dcac075db5e1f", "0x58e99d9413bb6ce05748a84f76e5fff4bb2d0dcb"]


def test_deposit_sweep_pattern_is_an_exchange_deposit():
    dep, hot = "0xdep", "0xhot"
    ts = []
    for i in range(6):
        ts.append({"from": f"0xuser{i}", "to": dep, "amount": 100.0 + i, "time": f"2024-01-0{i+1}T00:00:00Z"})
        ts.append({"from": dep, "to": hot, "amount": 100.0 + i, "time": f"2024-01-0{i+1}T02:00:00Z"})
    f = features(dep, ts)
    assert rules(f, {"name": "Binance 14", "kind": "exchange_hot"})["kind"] == "exchange_deposit"
    # the same pattern sweeping into an unknown wallet is a possible scam collector, not an exchange
    assert rules(f, None)["kind"] == "unknown"


def test_scam_wallets_are_not_mistaken_for_exchanges():
    # An exchange stop ends the trace, so a false exchange would hide the money.
    for a in DOJ_PATH:
        f = features(a, fixture_chain.get_transfers("ethereum", a))
        assert classify(f)["kind"] not in ("exchange_deposit", "exchange_hot"), (a, f)


def test_claude_only_rewords_reasons(monkeypatch):
    # BRIEF §0: the classifier is an opinion, never a stop. Claude may not change kind or confidence.
    import hound.llm.classify as cl
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(cl, "_cache", {})
    f = {"address": "0xhv", "truncated": True, "n_in": 9000, "n_out": 9000, "distinct_senders": 0,
         "distinct_recipients": 0, "top_recipient_share": 0, "median_hold_hours": None, "top_recipient": None}
    monkeypatch.setattr(cl, "_claude", lambda f, floor: {"kind": "exchange_hot", "confidence": 0.95, "reasons": ["busy"]})
    out = classify(f)
    assert (out["kind"], out["confidence"], out["reasons"]) == ("exchange_hot", 0.6, ["busy"])
    monkeypatch.setattr(cl, "_cache", {})
    monkeypatch.setattr(cl, "_claude", lambda f, floor: {"kind": "personal", "confidence": 0.9, "reasons": ["mine"]})
    assert classify(f) == rules(f)


def test_prompt_has_no_address(monkeypatch):
    import sys
    import types
    import hound.llm.classify as cl
    sent = {}

    class Msgs:
        def create(self, **kw):
            sent.update(kw)
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text='{"kind":"unknown","confidence":0.5,"reasons":[]}')])

    class Client:
        def __init__(self, **kw):
            sent["client"] = kw
            self.messages = Msgs()
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Client))
    f = features("0xsecretaddr", [{"from": "0xa", "to": "0xsecretaddr", "amount": 1.0, "time": "2024-01-01T00:00:00Z"}])
    cl._claude(f, rules(f))
    assert "0xsecretaddr" not in sent["messages"][0]["content"]
    assert sent["client"] == {"timeout": 8, "max_retries": 0}
