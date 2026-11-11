"""Send-back tests (hft-team-05 a). The stub model reads fixed files: no server, no network.
Call n of an agent reads <agent>.<n>.txt, so rule_checker.2.txt is the reply to the send-back."""
import json

import pytest

import log
import orchestrator as orch
from casekit import GOOD_FINDING, make_case, model_only, rows, write_stub

FAKE = dict(GOOD_FINDING, fault_id="f1", quote="Zorvatin 50 mg tablet QD")  # quote is not in the text


def go(con, tmp_path, checker, reply=None, model_cls=orch.StubModel):
    extra = {"rule_checker.2.txt": reply} if reply is not None else None
    m = model_cls(write_stub(tmp_path / "stub", checker=checker, extra=extra))
    return orch.run_case(make_case(), con, m), m


def sendback_befores(con):
    return rows(con, "SELECT * FROM steps WHERE agent='rule_checker' AND phase='before' AND seq>=3")


def test_retry_limit_is_one_and_set_in_code():
    assert orch.MAX_RETRY == 1
    src = open(orch.__file__, encoding="utf-8").read()
    assert "\nMAX_RETRY = 1" in src  # a constant in code, not a prompt


def check_exactly_one_retry(con, model):
    """The proof used twice: once on the real limit, once on a planted limit of 2 (must fail)."""
    assert model.calls["rule_checker"] == 2          # first answer + exactly 1 send-back
    assert len(sendback_befores(con)) == 1
    assert len(rows(con, "SELECT * FROM tool_calls WHERE tool='sendback'")) == 1


def test_bad_finding_gets_exactly_one_retry(con, tmp_path):
    res, m = go(con, tmp_path, json.dumps([FAKE]))      # same bad answer every time
    check_exactly_one_retry(con, m)
    assert res["state"] == "CONFIRMED" and model_only(res) == []
    assert len(res["dropped"]) == 1 and res["dropped"][0]["sent_back"] is True


def test_planted_limit_of_two_makes_the_proof_fail(con, tmp_path, monkeypatch):
    """Planted bad stub: a limit of 2 asks twice. The one-retry proof must fail on it."""
    monkeypatch.setattr(orch, "MAX_RETRY", 2)
    _, m = go(con, tmp_path, json.dumps([FAKE]))
    assert m.calls["rule_checker"] == 3
    with pytest.raises(AssertionError):
        check_exactly_one_retry(con, m)


def test_retry_with_same_fake_quote_stays_dropped_never_confirmed(con, tmp_path):
    res, _ = go(con, tmp_path, json.dumps([FAKE]), reply=json.dumps([FAKE]))
    assert model_only(res) == []
    assert res["dropped"][0]["reason"] == "quote not found in the OCR text"
    assert rows(con, "SELECT * FROM decisions WHERE decision='CONFIRMED' AND model_wrote NOT LIKE '%\"code%'") == []


def test_retry_with_real_quote_but_unknown_rule_id_stays_dropped(con, tmp_path):
    bad_rule = dict(GOOD_FINDING, fault_id="f1", rule_id="NOPE-99")
    res, _ = go(con, tmp_path, json.dumps([FAKE]), reply=json.dumps([bad_rule]))
    assert model_only(res) == [] and res["dropped"][0]["reason"] == "rule id not in the frozen list"


def test_retry_can_win_only_through_the_referee(con, tmp_path):
    fixed = dict(GOOD_FINDING, fault_id="f1")
    res, _ = go(con, tmp_path, json.dumps([FAKE]), reply=json.dumps([fixed]))
    assert res["state"] == "CONFIRMED" and res["findings"][0]["sent_back"] is True
    d = rows(con, "SELECT * FROM decisions WHERE decision='CONFIRMED' ORDER BY rowid")
    assert len(d) == 2                      # the retry judgement, then the final referee row
    assert [x["passed_to"] for x in d] == ["sendback", None]
    assert all(x["quote"] == GOOD_FINDING["quote"] and x["rule_id"] == "EMR-01" for x in d)


def test_reply_for_another_fault_id_does_not_rescue(con, tmp_path):
    other = dict(GOOD_FINDING, fault_id="zzz")
    res, _ = go(con, tmp_path, json.dumps([FAKE]), reply=json.dumps([other]))
    assert model_only(res) == [] and len(res["dropped"]) == 1


def test_prose_reply_is_unable_to_check_not_clean(con, tmp_path):
    res, _ = go(con, tmp_path, json.dumps([FAKE]), reply="Sorry, I think the quote was right.")
    assert res["state"] == "UNABLE TO CHECK"
    assert "not a clean result" in res["message"] and res["state"] != "CHECKED"


class DiesOnSendback(orch.StubModel):
    def generate(self, agent, prompt, seed=0):
        if agent == "rule_checker" and self.calls.get("rule_checker", 0) >= 1:
            self.calls["rule_checker"] += 1
            raise ConnectionError("model server gone")
        return super().generate(agent, prompt, seed)


def test_model_failure_in_retry_is_unable_to_check_and_shows_in_failed_calls(con, tmp_path):
    res, _ = go(con, tmp_path, json.dumps([FAKE]), model_cls=DiesOnSendback)
    assert res["state"] == "UNABLE TO CHECK" and "not a clean result" in res["message"]
    failed = log.failed_calls(con)
    assert len(failed) == 1 and failed[0]["agent"] == "rule_checker" and failed[0]["seq"] == 3


def test_every_retry_has_before_and_after_rows_with_new_seq_and_reason(con, tmp_path):
    go(con, tmp_path, json.dumps([FAKE]), reply=json.dumps([FAKE]))
    steps = rows(con, "SELECT seq, phase FROM steps WHERE agent='rule_checker' ORDER BY rowid")
    assert steps == [{"seq": 1, "phase": "before"}, {"seq": 1, "phase": "after"},
                     {"seq": 3, "phase": "before"}, {"seq": 3, "phase": "after"}]
    t = rows(con, "SELECT args FROM tool_calls WHERE tool='sendback'")
    args = json.loads(t[0]["args"])
    assert args["reason"] == "quote not found in the OCR text" and args["max_retry"] == 1
    assert log.failed_calls(con) == []


def test_good_finding_is_never_sent_back(con, tmp_path):
    res, m = go(con, tmp_path, json.dumps([GOOD_FINDING]))
    assert res["state"] == "CONFIRMED" and m.calls["rule_checker"] == 1
    assert sendback_befores(con) == []


def test_sample_sendback_log(con, tmp_path):
    """Prints one synthetic send-back log for the receipt (run with -s)."""
    go(con, tmp_path, json.dumps([FAKE]), reply=json.dumps([FAKE]))
    out = rows(con, "SELECT agent, seq, phase FROM steps ORDER BY rowid")
    for r in out:
        print(r)
    for r in rows(con, "SELECT tool, args FROM tool_calls WHERE tool='sendback'"):
        print(r)
    assert len(out) == 8
