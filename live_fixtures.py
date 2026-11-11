"""Synthetic runs for the live record screen: one run per end state. Invented names only."""
import json

import log

Q2 = "ALERT: Kelmorane dose 40 mg is above the range 5 to 20 mg"
Q1 = "Take 1 tablet QD"
TEXT = Q2 + "\n" + Q1 + "\nGive 4 U daily"      # QD sits inside the quote Q1; "U" is found by code only
TEXT_OK = Q2 + "\n[OK]"                          # pilot P08 type: the [OK] hit lies outside the quoted alert line
TEXT_PLAIN = Q2 + "\nGive 1 tablet daily"        # no code pattern hit at all


def _step(con, run, case, agent, phase, ts, asked=None, came=None):
    log.write_step(con, phase, f"{run}-{agent}-1-{phase[0]}", run, case, agent, 1, ts, asked=asked, came_back=came)


def _run(con, run, case, planted="none", kind="label", reader=TEXT, proposals=None, final=None, rules=(), decisions=()):
    con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",
                (run, "2026-11-09T18:00:00", "dv1", "sh1", "dev", "off", 1, "fixture"))
    log.add_case(con, case, kind, "dev", "ih", planted=planted)
    _step(con, run, case, "reader", "before", "2026-11-09T18:00:01", asked="read it")
    _step(con, run, case, "reader", "after", "2026-11-09T18:00:10", came=("PASS\n" + reader) if reader else "FAIL")
    _step(con, run, case, "rule_checker", "before", "2026-11-09T18:00:11", asked="suggest faults")
    _step(con, run, case, "rule_checker", "after", "2026-11-09T18:03:00",
          came=json.dumps(proposals) if proposals is not None else "")
    sid = f"{run}-referee-1-b"
    _step(con, run, case, "referee", "before", "2026-11-09T18:03:01", asked="{}")
    for i, (rid, quote, passed, why) in enumerate(rules):
        cur = con.execute("INSERT INTO rule_results VALUES (?,?,?,?,?,?)", (f"{sid}-r{i}", sid, rid, quote, passed, why))
        log.link_row(con, "rule_results", cur.lastrowid)
    for i, (dec, quote, rid, wrote) in enumerate(decisions):
        cur = con.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?)",
                          (f"{sid}-d{i}", sid, "referee", dec, quote, rid, None, wrote))
        log.link_row(con, "decisions", cur.lastrowid)
    con.commit()
    _step(con, run, case, "referee", "after", "2026-11-09T18:03:02", came=json.dumps(final))


def prop(fid, rid, quote, sev="medium"):
    return dict(fault_id=fid, rule_id=rid, quote=quote, location="line 1", severity=sev, confidence="high",
                audience="x")


def build(con):
    """Runs: rConf (C2 type: QD inside the quote = CONFIRMED, plus a code-only row, plus human severity),
    rDisp (P08 type: [OK] outside the quote = DISPUTED), rDrop, rUnable, rChecked."""
    _run(con, "rConf", "C2", proposals=[prop("F001", "EMR-01", Q1, "9")],
         rules=[("EMR-01", "QD", 0, "pattern found")],
         decisions=[("CONFIRMED", Q1, "EMR-01", "{}")],
         final=dict(state="CONFIRMED", dropped=[], findings=[
             dict(quote=Q1, rule_id="EMR-01", state="CONFIRMED", reason="quote found, rule id valid, regex agrees"),
             dict(quote="U", rule_id="EMR-01", state="CONFIRMED", reason="found by code rule, no model finding")]))
    _run(con, "rDisp", "C3", kind="alert", reader=TEXT_OK, proposals=[prop("F001", "ALT-03", Q2)],
         rules=[("ALT-03", "[OK]", 0, "pattern found")],
         final=dict(state="DISPUTED", dropped=[], findings=[
             dict(quote=Q2, rule_id="ALT-03", state="DISPUTED",
                  reason="model and regex rule disagree (regex hit is not inside the quote)")]))
    _run(con, "rDrop", "C4", planted="fake_quote", reader=TEXT_PLAIN,
         proposals=[prop("trap1", "EMR-01", "Give double dose now")],
         final=dict(state="CHECKED", findings=[], dropped=[
             dict(quote="Give double dose now", rule_id="EMR-01", sent_back=True,
                  reason="quote not found in the OCR text")]))
    _run(con, "rUnable", "C5", planted="unreadable", reader="", proposals=None,
         decisions=[("UNABLE TO CHECK", None, None, "tool state is ocr_failed")],
         final=dict(state="UNABLE TO CHECK", findings=[], dropped=[]))
    _run(con, "rChecked", "C6", reader=TEXT_PLAIN, proposals=[], final=dict(state="CHECKED", findings=[], dropped=[]))
    log.add_human_severity(con, "hs1", "rConf-referee-1-b-d0", "F001", "Dr Test Reader", "critical",
                           "invented reason", "2026-11-10T09:00:00")
