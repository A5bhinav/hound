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
