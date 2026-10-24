from hound.contracts import example
from hound.llm.writer import facts, uncited, write_case

TRACE = example("ohnd_replay.trace")
CASE = example("ohnd_replay.case")


def test_template_packets_cite_only_trace_facts():
    for audience in ("victim", "detective"):
        out = write_case(TRACE, CASE, audience)
        assert uncited(out["text"], facts(TRACE)) == []
        assert "REPLAY" in out["text"]


def test_citation_check_catches_invented_numbers():
    f = facts(TRACE)
    assert uncited("Your 999,999 USDT went to 0xdeadbeefdeadbeef.", f) == ["0xdeadbeefdeadbeef", "999,999"]


def test_detective_packet_lists_frozen_finals():
    out = write_case(TRACE, CASE, "detective")["text"]
    assert "0xa1770ead287dc8e91631a7a323390d5b744f0021" in out
    assert "frozen 2024-06-21" in out
