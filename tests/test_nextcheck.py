"""Next-check tests (hft-team-05 b). The list is fixed in code; the model can only pick from it."""
import copy
import json

import orchestrator as orch
from casekit import make_case, rows, write_stub


def run(con, tmp_path, named, kind="alert"):
    stub = write_stub(tmp_path / "stub")
    if named is not None:
        (stub / "next_check.txt").write_text(named, encoding="utf-8")
    case = dict(make_case(), kind=kind)
    return orch.run_case(case, con, orch.StubModel(stub))


def tool_row(con):
    r = rows(con, "SELECT * FROM tool_calls WHERE tool='next_check'")
    assert len(r) == 1
    return json.loads(r[0]["args"]), json.loads(r[0]["result"])


def test_lists_exist_for_both_case_types():
    assert set(orch.CHECKS) == {"label", "alert"}
    assert all(len(v) >= 2 for v in orch.CHECKS.values())


def test_no_name_uses_default(con, tmp_path):
    res = run(con, tmp_path, None)
    assert res["next_check"] == orch.CHECKS["alert"][0]
    assert tool_row(con)[1] == {"used": orch.CHECKS["alert"][0], "refused": False}


def test_name_from_the_list_is_used(con, tmp_path):
    pick = orch.CHECKS["alert"][1]
    res = run(con, tmp_path, pick)
    assert res["next_check"] == pick and tool_row(con)[1]["refused"] is False


def test_invented_check_is_refused_logged_and_default_used(con, tmp_path):
    before = copy.deepcopy(orch.CHECKS)
    res = run(con, tmp_path, "web_search")
    assert res["next_check"] == orch.CHECKS["alert"][0] != "web_search"   # a naive pick would give web_search
    args, result = tool_row(con)
    assert args["named"] == "web_search" and result == {"used": orch.CHECKS["alert"][0], "refused": True}
    assert orch.CHECKS == before                                          # the model cannot add a check


def test_name_from_the_other_case_type_is_refused(con, tmp_path):
    other = orch.CHECKS["label"][2]
    assert other not in orch.CHECKS["alert"]
    res = run(con, tmp_path, other, kind="alert")
    assert res["next_check"] == orch.CHECKS["alert"][0] and tool_row(con)[1]["refused"] is True


def test_label_case_uses_label_list(con, tmp_path):
    res = run(con, tmp_path, None, kind="label")
    assert res["next_check"] == orch.CHECKS["label"][0]


def test_unknown_kind_falls_back_and_non_text_name_is_refused():
    assert orch.choose_next_check("???", None)[0] == orch.CHECKS["label"][0]
    assert orch.choose_next_check("alert", 5) == (orch.CHECKS["alert"][0], True)
