"""Tests for the self-improvement test gate (hft-team-12). Written BEFORE the code.
Synthetic data only. Stdlib + pytest. No model, no network. Every rule has one input that
passes and one that fails (lesson 8 Nov: a proof must be able to fail)."""
import hashlib
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import improve_gate as g  # noqa: E402
import log  # noqa: E402
import importlib.util  # noqa: E402

# scripts/ is not a package: load the script by path (test_schema only allows known own modules in import lines)
_spec = importlib.util.spec_from_file_location("evaluate_candidate", ROOT / "scripts" / "evaluate_candidate.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

CANARY = "CANARY-7f3a91-do-not-copy"


# ------------------------------------------------------------------ helpers
def run3(found=True):
    return [{"found": found, "quote": "q" if found else "", "rule_id": "EMR-01" if found else ""}] * 3


def result(found_ids, all_ids, clean=30, flagged=0, unable=0.2, minutes=3.3, plants=True):
    return {
        "faults": {i: run3(i in found_ids) for i in all_ids},
        "clean": {f"c{k}": [{"flagged": k < flagged}] * 3 for k in range(clean)},
        "unable_rate": unable,
        "plants": {"fake_quote": [plants] * 3, "unreadable": [plants] * 3},
        "minutes_per_case": minutes,
        "artifacts": {},
    }


IDS = [f"F{i:02d}" for i in range(20)]


class Stub:
    """Stub runner. old / new are sets of fault ids found by each version.
    kw = {"old": {...}, "new": {...}} extra args for result()."""
    def __init__(self, old_found, new_found, **kw):
        self.old, self.new, self.kw, self.calls, self.on_run = set(old_found), set(new_found), kw, [], None

    def __call__(self, version, split, candidate):
        self.calls.append((version, split))
        if self.on_run:
            self.on_run(version, split)
        found = self.old if version == "old" else self.new
        return result(found, IDS, **self.kw.get(version, {}))


def settings_text(alpha=0.05, k=3):
    return json.dumps({"alpha": alpha, "max_candidates": k, "correction": "bonferroni",
                       "need_runs": 2, "false_alarm_per_30": 1, "time_pct": 25, "max_lessons": 10}, sort_keys=True)


@pytest.fixture
def db(tmp_path):
    con = log.open_db(str(tmp_path / "gate.sqlite"))
    con.executescript(g.IMPROVE_SCHEMA.read_text(encoding="utf-8"))
    log.store_protocol(con, "P-GATE", settings_text(), "2026-11-10T00:00:00")
    yield con
    con.close()


@pytest.fixture
def rules(tmp_path):
    f = tmp_path / "referee.py"
    f.write_text("RULES = 1\n", encoding="utf-8")
    return [f]


def good_candidate(**kw):
    c = {"candidate_id": "K1", "kind": "prompt_line", "target": "finder", "text": "Check each dose unit twice."}
    c.update(kw)
    return c


def go(db, rules, runner, cand=None, **kw):
    args = dict(con=db, protocol_id="P-GATE", rule_files=rules, canaries=[CANARY], case_texts=["x y z"],
                active_lessons=0, candidates_so_far=0)
    args.update(kw)
    return ev.evaluate(cand or good_candidate(), runner, **args)


def settings():
    t = settings_text()
    return g.parse_settings(t, hashlib.sha256(t.encode()).hexdigest())


# ------------------------------------------------------------------ statistics (R3)
def test_p_equals_half_pow_b_when_c_zero():
    for b in range(1, 10):
        assert g.mcnemar_exact_one_sided(b, 0) == 0.5 ** b


def test_p_known_values_and_negative():
    assert g.mcnemar_exact_one_sided(0, 0) == 1.0
    assert abs(g.mcnemar_exact_one_sided(5, 1) - 7 / 64) < 1e-12
    assert g.mcnemar_exact_one_sided(1, 5) > 0.9  # losses dominate: p high


def test_min_b_to_pass():
    assert g.min_b_to_pass(0.05, 3) == 6
    assert g.min_b_to_pass(0.05, 1) == 5


def test_paired_table():
    old = result({"F00", "F01"}, IDS)
    new = result({"F01", "F02", "F03"}, IDS)
    t = g.paired_table(old["faults"], new["faults"])
    assert (t["B"], t["C"], t["both"]) == (2, 1, 1)
    assert t["B_ids"] == ["F02", "F03"] and t["C_ids"] == ["F00"]


def test_found_needs_two_of_three_with_quote_or_rule():
    r = {"found": True, "quote": "q", "rule_id": ""}
    assert g.is_found([r, r, {"found": False}])
    assert not g.is_found([r, {"found": False}, {"found": False}])
    assert not g.is_found([{"found": True, "quote": "", "rule_id": ""}] * 3)  # no quote, no rule id


def test_six_gains_zero_losses_eligible_five_not(db, rules):
    old = set(IDS[:5])
    r6 = go(db, rules, Stub(old, old | set(IDS[5:11])))
    assert r6["verdict"] == "eligible" and (r6["B"], r6["C"]) == (6, 0)
    assert r6["p"] == 0.5 ** 6
    r5 = go(db, rules, Stub(old, old | set(IDS[5:10])), cand=good_candidate(candidate_id="K2"))
    assert r5["verdict"] == "reject" and r5["B"] == 5


def test_printed_p_and_proposal_label(db, rules):
    old = set(IDS[:5])
    r = go(db, rules, Stub(old, old | set(IDS[5:11])))
    txt = ev.format_result(r)
    assert "proposal" in txt.lower()
    assert f"{0.5 ** 6:.4f}" in txt
    assert "ELIGIBLE" in txt and "human" in txt.lower()  # says a human must still approve


# ------------------------------------------------------------------ R7 no-op, R5, R6
def test_noop_rejected(db, rules):
    r = go(db, rules, Stub(IDS[:8], IDS[:8]))
    assert r["verdict"] == "reject" and r["B"] == 0


def test_same_version_run_twice_no_gain():
    a = result(set(IDS[:8]), IDS)
    assert g.paired_table(a["faults"], a["faults"])["B"] == 0


def test_report_nothing_text_refused_and_stub_rejected(db, rules):
    ok, why = g.check_candidate(good_candidate(text="Report nothing when unsure."))
    assert not ok and any("report nothing" in w.lower() for w in why)
    assert not g.check_candidate(good_candidate(text="Skip hard cases such as small print."))[0]
    assert g.check_candidate(good_candidate(text="Report each finding with its quote."))[0]  # paired negative
    # a version that reports nothing loses every old fault: rejected by the loss rule
    r = go(db, rules, Stub(IDS[:10], set()), cand=good_candidate(candidate_id="K9"))
    assert r["verdict"] == "reject" and r["C"] == 10


def test_lost_fault_rejects_even_with_gains(db, rules):
    old = set(IDS[:5])
    new = (old - {"F00"}) | set(IDS[5:15])  # 10 gains, 1 loss
    r = go(db, rules, Stub(old, new))
    assert r["verdict"] == "reject" and r["C"] == 1
    assert any("lost" in x.lower() for x in r["reasons"])


# ------------------------------------------------------------------ candidate checks (R4)
def test_candidate_length_and_fields():
    assert g.check_candidate(good_candidate(text="a" * 300))[0] is True
    assert g.check_candidate(good_candidate(text="a" * 301))[0] is False
    assert g.check_candidate(good_candidate(kind="rewrite_code"))[0] is False
    assert g.check_candidate(good_candidate(target="referee.py"))[0] is False
    for k in ("prompt_line", "lesson", "rule_threshold_suggestion"):
        assert g.check_candidate(good_candidate(kind=k))[0] is True


CASE = "the patient receives one tablet of the drug twice every day at noon sharp"


def test_eight_word_overlap_rejected_seven_not():
    eight = "receives one tablet of the drug twice every"
    seven = "receives one tablet of the drug twice"
    ok8, why8 = g.check_candidate(good_candidate(text=f"Look: {eight} ok"), case_texts=[CASE])
    ok7, _ = g.check_candidate(good_candidate(text=f"Look: {seven} then banana"), case_texts=[CASE])
    assert not ok8 and any("8" in w for w in why8)
    assert ok7


def test_lesson_cap_ten():
    assert g.check_candidate(good_candidate(kind="lesson"), active_lessons=9)[0] is True
    ok, why = g.check_candidate(good_candidate(kind="lesson"), active_lessons=10)
    assert not ok and any("10" in w for w in why)


def test_round_cap_three_candidates(db, rules):
    old = set(IDS[:5])
    r = go(db, rules, Stub(old, old | set(IDS[5:12])), candidates_so_far=3)
    assert r["verdict"] == "reject" and any("3 candidates" in x for x in r["reasons"])


# ------------------------------------------------------------------ must not worsen
def test_must_not_worsen_each_rule_pass_and_fail():
    S = settings()
    base = result(set(IDS), IDS, flagged=2)
    same = result(set(IDS), IDS, flagged=2)
    assert g.must_not_worsen(base, same, S, {"a": "1"}, {"a": "1"}) == []
    assert g.must_not_worsen(base, result(set(IDS), IDS, flagged=3), S, {}, {}) == []  # +1 per 30 is allowed
    assert any("false alarm" in x for x in g.must_not_worsen(base, result(set(IDS), IDS, flagged=4), S, {}, {}))
    assert any("UNABLE" in x for x in g.must_not_worsen(base, result(set(IDS), IDS, flagged=2, unable=0.1), S, {}, {}))
    assert g.must_not_worsen(base, result(set(IDS), IDS, flagged=2, unable=0.3), S, {}, {}) == []
    assert any("plant" in x for x in g.must_not_worsen(base, result(set(IDS), IDS, flagged=2, plants=False), S, {}, {}))
    assert g.must_not_worsen(base, result(set(IDS), IDS, flagged=2, minutes=4.1), S, {}, {}) == []
    assert any("time" in x for x in g.must_not_worsen(base, result(set(IDS), IDS, flagged=2, minutes=4.2), S, {}, {}))
    assert any("hash" in x for x in g.must_not_worsen(base, same, S, {"a": "1"}, {"a": "2"}))


def test_false_alarm_rule_end_to_end(db, rules):
    old = set(IDS[:5])
    s = Stub(old, old | set(IDS[5:12]), new={"flagged": 5}, old={"flagged": 0})
    r = go(db, rules, s)
    assert r["verdict"] == "reject" and any("false alarm" in x for x in r["reasons"])


# ------------------------------------------------------------------ R1 R2 canary
def test_canary_scan_finds_planted_and_clean_passes():
    assert g.canary_scan({"prompt": f"hello {CANARY} there"}, [CANARY]) == [("prompt", CANARY)]
    assert g.canary_scan({"prompt": "hello there", "log": "nothing"}, [CANARY]) == []
    assert g.canary_scan({"p": CANARY.upper()}, [CANARY]) != []  # case-blind


def test_canary_in_candidate_stops_run(db, rules):
    s = Stub(IDS[:5], IDS[:12])
    r = go(db, rules, s, cand=good_candidate(text=f"use {CANARY} here"))
    assert r["verdict"] == "reject" and r["stopped"] and s.calls == []
    assert any("canary" in x.lower() for x in r["reasons"])


def test_canary_in_runner_artifacts_stops_run(db, rules):
    class Leaky(Stub):
        def __call__(self, v, s, c):
            out = super().__call__(v, s, c)
            out["artifacts"] = {"lessons": f"x {CANARY}"}
            return out
    r = go(db, rules, Leaky(IDS[:5], IDS[:12]))
    assert r["verdict"] == "reject" and r["stopped"]


# ------------------------------------------------------------------ R8 hash of rule files
def test_stub_that_edits_rule_file_is_caught(db, rules):
    s = Stub(IDS[:5], IDS[:12])
    s.on_run = lambda v, sp: rules[0].write_text("RULES = 2\n", encoding="utf-8") if v == "new" else None
    r = go(db, rules, s)
    assert r["verdict"] == "reject" and any("hash" in x for x in r["reasons"])


def test_untouched_rule_file_passes_hash_check(db, rules):
    old = set(IDS[:5])
    assert go(db, rules, Stub(old, old | set(IDS[5:12])))["verdict"] == "eligible"


# ------------------------------------------------------------------ R9 chain
def _db_with_steps(path):
    con = log.open_db(str(path))
    log.add_case(con, "S1", "alert", "dev", log.sha256("x"))
    con.execute("INSERT INTO runs VALUES ('r1','2026-01-01T00:00:00','dv','sh','dev','off',0,'t')")
    con.commit()
    for i, ph in enumerate(("before", "after"), 1):
        log.write_step(con, ph, f"s{i}", "r1", "S1", "reader", 1, f"2026-01-01T00:00:0{i}",
                       asked="q" if ph == "before" else None, came_back="a" if ph == "after" else None)
    con.executescript(g.IMPROVE_SCHEMA.read_text(encoding="utf-8"))
    log.store_protocol(con, "P-GATE", settings_text(), "2026-11-10T00:00:00")
    return con


def test_broken_chain_refuses_to_run(tmp_path, rules):
    con = _db_with_steps(tmp_path / "ok.db")
    s = Stub(IDS[:5], IDS[:12])
    r = go(con, rules, s)
    assert r["verdict"] == "eligible" and s.calls  # chain fine: it runs
    con.execute("DROP TRIGGER steps_no_update")
    con.execute("UPDATE steps SET came_back='edited' WHERE step_id='s2'")
    con.commit()
    s2 = Stub(IDS[:5], IDS[:12])
    r2 = go(con, rules, s2, cand=good_candidate(candidate_id="K5"))
    assert r2["verdict"] == "reject" and s2.calls == []
    assert any("chain" in x.lower() for x in r2["reasons"])
    con.close()


# ------------------------------------------------------------------ R13 R14
def test_pilot_style_set_cannot_pass(db, rules):
    old = set(IDS[:17])  # 3 misses
    s = Stub(old, set(IDS))
    r = go(db, rules, s)
    assert r["verdict"] == "reject"
    assert any("cannot pass, only 3 misses; grow the set first" in x for x in r["reasons"])
    assert ("new", "dev_check") not in s.calls
    assert "6" in ev.format_result(r)  # prints the smallest B that can pass


def test_enough_misses_is_not_refused_for_size(db, rules):
    old = set(IDS[:10])  # 10 misses >= 6
    r = go(db, rules, Stub(old, old))
    assert not any("cannot pass" in x for x in r["reasons"])


def test_settings_hash_checked():
    txt = settings_text()
    h = hashlib.sha256(txt.encode()).hexdigest()
    assert g.parse_settings(txt, h)["alpha"] == 0.05
    with pytest.raises(g.GateRefusal):
        g.parse_settings(settings_text(alpha=0.2), h)  # changed alpha, old hash


def test_changed_protocol_row_refused(db, rules):
    db.execute("DROP TRIGGER protocol_no_update")
    db.execute("UPDATE protocol SET text=?", (settings_text(alpha=0.2),))
    db.commit()
    s = Stub(IDS[:5], IDS[:12])
    r = go(db, rules, s)
    assert r["verdict"] == "reject" and s.calls == []
    assert any("protocol" in x.lower() for x in r["reasons"])


# ------------------------------------------------------------------ NOT CHECKED
def test_missing_run_gives_not_checked_and_reject(db, rules):
    def boom(version, split, cand):
        raise FileNotFoundError("run file missing")
    r = go(db, rules, boom)
    assert r["verdict"] == "reject" and any("NOT CHECKED" in x for x in r["reasons"])
    assert "NOT CHECKED" in ev.format_result(r)


def test_malformed_result_not_checked(db, rules):
    r = go(db, rules, lambda v, s, c: {"faults": {}})
    assert r["verdict"] == "reject" and any("NOT CHECKED" in x for x in r["reasons"])


# ------------------------------------------------------------------ never approves; tables
def test_only_reject_or_eligible_written(db, rules):
    old = set(IDS[:5])
    go(db, rules, Stub(old, old | set(IDS[5:12])))
    go(db, rules, Stub(old, old), cand=good_candidate(candidate_id="K3"))
    assert {r[0] for r in db.execute("SELECT verdict FROM gate_results")} == {"eligible", "reject"}
    assert db.execute("SELECT COUNT(*) FROM agent_versions").fetchone()[0] == 0  # human step only
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO gate_results (candidate_id, verdict, b, c, p, reasons, protocol_id, ts)"
                   " VALUES ('x','approved',1,0,0.5,'','P-GATE','t')")


@pytest.mark.parametrize("table", ["agent_versions", "gate_results"])
def test_new_tables_append_only(db, table):
    if table == "agent_versions":
        db.execute("INSERT INTO agent_versions (version_id, parent_id, prompt_hashes, lesson_ids, thresholds,"
                   " model_name, model_digest, runtime_version, candidate_id, result, approved_by)"
                   " VALUES ('V1','','{}','[]','{}','m','d','o','K1','eligible','human')")
        assert db.execute("SELECT signed_by_owner FROM agent_versions").fetchone()[0] == ""
    else:
        db.execute("INSERT INTO gate_results (candidate_id, verdict, b, c, p, reasons, protocol_id, ts)"
                   " VALUES ('K1','reject',0,0,1.0,'','P-GATE','t')")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(f"UPDATE {table} SET candidate_id='z'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(f"DELETE FROM {table}")


def test_old_schema_file_unchanged():
    base = (ROOT / "schema.sql").read_text(encoding="utf-8")
    assert "agent_versions" not in base and "gate_results" not in base  # test_schema pins schema.sql to 14 tables


# ------------------------------------------------------------------ R3 simulation
def test_do_nothing_simulation_false_accepts_near_alpha():
    rng = random.Random(12345)
    rounds, proposed, k, alpha, n_disc = 1000, 50, 3, 0.05, 20

    def wins(n):
        b = sum(rng.random() < 0.5 for _ in range(n))
        return b, n - b

    corrected = uncorrected = 0
    for _ in range(rounds):
        # guarded: 50 proposed, only the first 3 are tried (cap), each at alpha / 3
        if any(g.passes_stat(*wins(n_disc), alpha, k) for _ in range(min(proposed, k))):
            corrected += 1
        # unguarded: all 50 tried, each at alpha
        if any(g.passes_stat(*wins(n_disc), alpha, 1) for _ in range(proposed)):
            uncorrected += 1
    assert corrected / rounds <= alpha + 0.01  # near alpha or below
    assert uncorrected / rounds > 0.3  # the simulation CAN fail: no guard gives many false accepts


# ------------------------------------------------------------------ R15 no model, no network
BAD_IMPORT = re.compile(r"^\s*(import|from)\s+(" + "olla" + "ma" + r"|requests|urllib|socket|http|httpx|openai|anthropic)\b", re.M)


def test_static_scan_no_model_client_or_network():
    for f in ("improve_gate.py", "scripts/evaluate_candidate.py"):
        src = (ROOT / f).read_text(encoding="utf-8")
        assert not BAD_IMPORT.search(src), f
        assert "__import__" not in src, f


def test_scan_can_fail():
    assert BAD_IMPORT.search("import requests\n")
    assert BAD_IMPORT.search("from urllib.request import urlopen\n")
    assert not BAD_IMPORT.search("import hashlib\n")


# ------------------------------------------------------------------ practice set
def test_practice_set_cannot_pass_with_recorded_pilot():
    rec = ROOT / "pilot" / "pilot_result.json"
    if not rec.exists():
        pytest.skip("recorded pilot result not on disk (untracked file)")
    out = ev.run_practice_set(ROOT / "pilot" / "cases", rec)
    assert out["verdict"] == "reject"
    assert any("cannot pass, only 3 misses; grow the set first" in x for x in out["reasons"])


def test_practice_set_missing_record_is_not_checked(tmp_path):
    out = ev.run_practice_set(ROOT / "pilot" / "cases", tmp_path / "nope.json")
    assert out["verdict"] == "reject" and any("NOT CHECKED" in x for x in out["reasons"])
