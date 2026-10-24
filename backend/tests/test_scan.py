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
        assert (c.get("transfer_count") or 0) <= scan.MAX_LIFETIME_TRANSFERS, c["address"]
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
    _check_consistent(json.loads(scan.SUMMARY.read_text()))


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
