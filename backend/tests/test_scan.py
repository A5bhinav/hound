"""Weekend scan panel (AUDIT 24): the headline must equal the rows shown under it, and no
exchange-sized or labelled wallet may ever be counted."""
from __future__ import annotations

import json
import re

import pytest

from hound.proof import scan

FULL_ADDR = re.compile(r"0x[0-9a-fA-F]{40}")


def _shown(res: dict) -> list[dict]:
    """The rows the proof page lists under the headline (page.tsx ScanPanel)."""
    return [c for c in res["cases"] if c["freezable_now"] and not c["is_frozen"]]


def _check_consistent(res: dict) -> None:
    rows = _shown(res)
    assert res["addresses_unfrozen"] == len(rows)
    assert res["usdt_unfrozen"] == pytest.approx(round(sum(c["capped_usdt"] for c in rows), 2), abs=0.005)
    for c in rows:
        # fail closed: a counted row has a measured transfer count, never None
        assert c.get("transfer_count") is not None, c["address"]
        assert c["transfer_count"] <= scan.MAX_LIFETIME_TRANSFERS, c["address"]
        assert not c.get("label") and not c.get("excluded_as_exchange_or_infra"), c["address"]
        assert c["capped_usdt"] <= c["balance_usdt"] + 1e-9
        assert c["row_label"] == "reported, not proven"


def test_committed_summary_headline_equals_shown_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(scan, "OUT", tmp_path / "missing.json")  # serve the committed summary
    res = scan.serve()
    _check_consistent(res)
    shown = {c["address"] for c in _shown(res)}
    # The two exchange-sized wallets CK ruled out (>20,000 and >12,557 transfers) were on screen once.
    assert "0x9642…5d4e" not in shown and "0x4e5b…972f" not in shown
    raw = scan.SUMMARY.read_text()
    assert not FULL_ADDR.search(raw), "committed summary must keep addresses truncated"
    assert "report_ids" not in raw


def test_committed_file_is_already_consistent():
    res = json.loads(scan.SUMMARY.read_text())
    _check_consistent(res)
    assert res == scan.redact(scan.finalize(res)) | {"note": res["note"]}  # re-finalizing changes nothing
    assert all(c["transfer_count"] != scan.EXPLORER_ROW_CAP for c in _shown(res))


def test_saturated_counts_and_the_usdt_contract_are_excluded():
    res = scan.finalize({"scanned_at": "2026-10-24T00:00:00+00:00", "addresses": 5, "cases": [
        _row("0x" + "1" * 40, 5_000.0, claimed_losses_usd=5_000.0, transfer_count=1000),   # the explorer's cap
        _row("0x" + "2" * 40, 4_000.0, claimed_losses_usd=4_000.0, transfer_count=1000, transfer_count_paged=True),
        _row("0x" + "3" * 40, 3_000.0, claimed_losses_usd=3_000.0, transfer_count=1392),
        _row(scan.USDT_CONTRACT, 1e6, is_frozen=True),                                     # the token itself
        _row("0x" + "5" * 40, 9_000.0, is_frozen=True),                                    # a real frozen wallet
    ]})
    _check_consistent(res)
    assert res["usdt_unfrozen"] == 7_000.0 and res["addresses_unfrozen"] == 2
    assert res["already_frozen"] == 1
    by = {c["address"]: c for c in res["cases"]}
    assert any("saturated" in r for r in by["0x" + "1" * 40]["excluded_reasons"])
    assert "the USDT token contract itself" in by[scan.USDT_CONTRACT]["excluded_reasons"]
    redacted = scan.finalize(scan.redact({"cases": [_row(scan.USDT_CONTRACT, 1e6, is_frozen=True)]}))
    assert redacted["already_frozen"] == 0


def test_transfer_count_pages_past_the_explorer_cap(monkeypatch):
    from hound.chain import eth
    seen = []

    def fake(params, ttl=None, sources=None):
        seen.append((params["page"], params["offset"], tuple(sources)))
        return {"result": [{}] * (1000 if params["page"] < 2 else 392)}
    monkeypatch.setattr(eth, "explorer", fake)
    assert scan.transfer_count("0x" + "1" * 40) == 1392
    assert [s[:2] for s in seen] == [(1, 1000), (2, 1000)] and seen[0][2][0] == "blockscout"
    monkeypatch.setattr(eth, "explorer", lambda params, ttl=None, sources=None: {"result": [{}] * 1000})
    assert scan.transfer_count("0x" + "1" * 40) == 3000  # stops once past the limit


def _row(addr, bal, **kw):
    return {"address": addr, "chain": "ethereum", "category": "PIGBUTCHERING", "report_count": 1,
            "report_ids": ["r-" + addr[-4:]], "balance_usdt": bal, "is_frozen": False, **kw}


def test_finalize_caps_and_excludes():
    a = "0x" + "1" * 40
    res = scan.finalize({"scanned_at": "2026-10-24T00:00:00+00:00", "addresses": 5, "cases": [
        _row(a, 5_000.0, claimed_losses_usd=1_200.0, transfer_count=40),             # capped to the claim
        _row("0x" + "2" * 40, 9_000_000.0, claimed_losses_usd=9e9, transfer_count=20_001),  # exchange sized
        _row("0x" + "3" * 40, 50_000.0, claimed_losses_usd=50_000.0, label={"kind": "exchange_hot"}),
        _row("0x" + "4" * 40, 700.0, claimed_losses_usd=0.0, transfer_count=3),       # nothing claimed: counts 0
        _row("0x" + "5" * 40, 800.0, claimed_losses_usd=900.0, transfer_count_error="429"),  # fail closed
    ]})
    _check_consistent(res)
    assert res["usdt_unfrozen"] == 1_200.0 and res["addresses_unfrozen"] == 1
    assert res["cases"][0]["address"] == a and res["cases"][0]["capped_usdt"] == 1_200.0
    assert all(c["as_of"] == "2026-10-24T00:00:00+00:00" for c in res["cases"])


def test_serve_live_file_is_redacted_and_rederived(monkeypatch, tmp_path):
    live = tmp_path / "scan_latest.json"
    full = "0x" + "ab" * 20
    # A stale live file whose stored headline disagrees with its rows.
    live.write_text(json.dumps({"scanned_at": "2026-10-24T00:00:00+00:00", "addresses": 2, "usdt_unfrozen": 9e6,
                                "addresses_unfrozen": 2, "cases": [
                                    _row(full, 3_000.0, claimed_losses_usd=2_500.0, transfer_count=12),
                                    _row("0x" + "cd" * 20, 9e6, claimed_losses_usd=9e6, transfer_count=12_558,
                                         freezable_now=True)]}))
    monkeypatch.setattr(scan, "OUT", live)
    res = scan.serve()
    _check_consistent(res)
    assert res["usdt_unfrozen"] == 2_500.0
    body = json.dumps(res)
    assert not FULL_ADDR.search(body) and "report_ids" not in body


def test_weekend_scan_counts_transfers_only_for_candidates(monkeypatch, tmp_path):
    big, small, frozen = "0x" + "a" * 40, "0x" + "b" * 40, "0x" + "c" * 40
    monkeypatch.setattr(scan, "OUT", tmp_path / "scan_latest.json")
    monkeypatch.setattr(scan, "chainabuse_reports", lambda **kw: [] if kw["category"] != "PIGBUTCHERING" else [
        {"report_id": f"r{i}", "address": a, "chain": "ethereum", "category": "PIGBUTCHERING",
         "reported_at": "2026-10-20", "checked": False, "trusted": False,
         "claimed_losses": [{"amount": 4_000, "asset": "USD"}]} for i, a in enumerate((big, small, frozen))])
    monkeypatch.setattr(scan, "usdt_balance", lambda a: {big: 8_956_891.82, small: 6_000.0, frozen: 10_000.0}[a])
    monkeypatch.setattr(scan, "usdt_is_blacklisted", lambda a: a == frozen)
    monkeypatch.setattr(scan, "_labelled", lambda a: None)
    monkeypatch.setattr(scan.time, "sleep", lambda s: None)
    counted = []

    def fake_count(a):
        counted.append(a)
        return 20_001 if a == big else 15

    monkeypatch.setattr(scan, "transfer_count", fake_count)
    res = scan.weekend_scan()
    _check_consistent(res)
    assert sorted(counted) == sorted([big, small])  # the frozen one never pays for a count
    assert res["usdt_unfrozen"] == 4_000.0 and res["addresses_unfrozen"] == 1
    assert json.loads((tmp_path / "scan_latest.json").read_text())["usdt_unfrozen"] == 4_000.0


def test_stale_live_file_never_promotes_source_excluded_rows(monkeypatch, tmp_path):
    """Old-shape scan_latest.json: two big rows ruled out only by freezable_now=false (no label,
    no transfer count, no reason). finalize must keep them out of the headline."""
    live = tmp_path / "scan_latest.json"
    ok = "0x" + "12" * 20
    live.write_text(json.dumps({"scanned_at": "2026-10-24T00:00:00+00:00", "addresses": 3, "cases": [
        _row(ok, 2_000.0, transfer_count=30, freezable_now=True, excluded_as_exchange_or_infra=False),
        _row("0x" + "96" * 20, 8_956_891.82, freezable_now=False, excluded_as_exchange_or_infra=False),
        _row("0x" + "4e" * 20, 3_089_426.62, freezable_now=False, excluded_as_exchange_or_infra=False),
    ]}))
    monkeypatch.setattr(scan, "OUT", live)
    res = scan.serve()
    _check_consistent(res)
    assert res["usdt_unfrozen"] == 2_000.0 and res["addresses_unfrozen"] == 1
    big = [c for c in res["cases"] if c["balance_usdt"] > 1e6]
    assert len(big) == 2 and not any(c["freezable_now"] for c in big)
    assert all(c["excluded_reasons"] for c in big)


def test_source_exclusion_survives_even_with_a_count():
    res = scan.finalize({"cases": [_row("0x" + "77" * 20, 50_000.0, transfer_count=10, freezable_now=False)]})
    assert res["usdt_unfrozen"] == 0 and res["cases"][0]["excluded_reasons"] == ["excluded in source scan"]


def test_unknown_transfer_count_is_left_out_of_the_headline():
    res = scan.finalize({"cases": [_row("0x" + "78" * 20, 853_611.70),                      # never measured
                                   _row("0x" + "6f" * 20, 5_000.0, transfer_count=12)]})
    _check_consistent(res)
    assert res["usdt_unfrozen"] == 5_000.0
    unk = next(c for c in res["cases"] if c["balance_usdt"] > 1e5)
    assert unk["excluded_reasons"] == ["transfer count not checked"] and not unk["freezable_now"]


def test_finalize_is_idempotent_on_its_own_output():
    res = scan.finalize({"cases": [_row("0x" + "aa" * 20, 900.0, transfer_count=5),
                                   _row("0x" + "bb" * 20, 900.0)]})
    again = scan.finalize(res)
    assert again["usdt_unfrozen"] == res["usdt_unfrozen"] == 900.0
    assert [c["freezable_now"] for c in again["cases"]] == [c["freezable_now"] for c in res["cases"]]


def test_group_by_address_counts_stablecoin_losses_and_unknown_assets():
    from hound.proof.chainabuse import group_by_address

    def rep(addr, losses):
        return {"report_id": addr + str(len(losses)), "address": addr, "chain": "ethereum", "category": "PIGBUTCHERING",
                "reported_at": "2026-10-20", "checked": False, "trusted": False, "claimed_losses": losses}
    out = {r["address"]: r for r in group_by_address([
        rep("a", [{"amount": 100, "asset": "USD"}, {"amount": 50, "asset": "USDT"}, {"amount": 5, "asset": "usdc"}]),
        rep("b", [{"amount": 2, "asset": "ETH"}]),
        rep("c", [{"amount": 2, "asset": "ETH"}, {"amount": 300, "asset": "USD"}]),
        rep("d", []),
    ])}
    assert out["a"]["claimed_losses_usd"] == 155.0
    assert out["b"]["claimed_losses_usd"] is None  # unknown, falls back to balance in finalize
    assert out["c"]["claimed_losses_usd"] == 300.0
    assert out["d"]["claimed_losses_usd"] == 0.0
