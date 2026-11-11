"""Repeat test: the same case 3 times with the stub at a fixed seed gives the same final list.
A planted stub that changes between runs must be reported UNSTABLE."""
import json

import log
import orchestrator as orch
from casekit import GOOD_FINDING, make_case, write_stub


class Drifting(orch.StubModel):
    """Planted bad stub: the rule checker answer changes on every new object."""
    counter = 0

    def __init__(self, folder):
        super().__init__(folder)
        Drifting.counter += 1
        self.k = Drifting.counter

    def generate(self, agent, prompt, seed=0):
        if agent == "rule_checker":
            f = dict(GOOD_FINDING, rule_id="EMR-01" if self.k % 2 else "EMR-03")
            return json.dumps([f]), False
        return super().generate(agent, prompt, seed)


def test_three_runs_same_seed_give_identical_final_lists(tmp_path):
    folder = write_stub(tmp_path / "s")
    verdict, results = orch.repeat_check(make_case(), lambda: orch.StubModel(folder),
                                         lambda: log.open_db(":memory:"), 3, seed=7)
    assert verdict == "STABLE"
    assert len(results) == 3 and len({orch.final_list(r) for r in results}) == 1
    assert results[0]["state"] == "CONFIRMED"


def test_planted_unstable_stub_is_reported_unstable(tmp_path):
    folder = write_stub(tmp_path / "s")
    verdict, results = orch.repeat_check(make_case(), lambda: Drifting(folder),
                                         lambda: log.open_db(":memory:"), 3, seed=7)
    assert verdict == "UNSTABLE"
    assert len({orch.final_list(r) for r in results}) > 1


def test_cli_repeat_reports_stable_and_exit_zero(tmp_path, capsys):
    case = tmp_path / "c.json"
    case.write_text(json.dumps(make_case()), encoding="utf-8")
    write_stub(tmp_path / "c.stub")
    code = orch.main(["--case", str(case), "--db", str(tmp_path / "l.db"), "--stub", "--repeat", "3", "--seed", "7"])
    assert code == 0 and '"STABLE"' in capsys.readouterr().out


def test_cli_repeat_unstable_gives_exit_four(tmp_path, capsys, monkeypatch):
    case = tmp_path / "c.json"
    case.write_text(json.dumps(make_case()), encoding="utf-8")
    write_stub(tmp_path / "c.stub")
    monkeypatch.setattr(orch, "StubModel", Drifting)
    code = orch.main(["--case", str(case), "--db", str(tmp_path / "l.db"), "--stub", "--repeat", "3"])
    assert code == 4 and "UNSTABLE" in capsys.readouterr().out
