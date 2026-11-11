"""Risk step: severity, occurrence and detection shown apart, ranked severity first.

Runs on each CONFIRMED or DISPUTED verdict from the code referee. Standard library only.
CLI: python risk_step.py --selftest | --sample | --verdicts <file.json> [--human <file.json>] [--db <sqlite>]
Rules: severity comes from a code table or a human row, never from a model. A model value is
shown as a proposal and ranks nothing. Occurrence on invented cases is "example, not measured".
There is no single combined number anywhere. Ranking is severity first, then weak detection,
then occurrence, then input order.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

DISCLAIMER = "Pre-check. Not a medical device. Does not replace a human factors engineer. NOT REVIEWED."
EXAMPLE_TEXT = "example, not measured"
PROPOSAL_LABEL = "PROPOSAL (model), not a score"
NOT_SET_LABEL = "severity: not set"
NEEDS_SOURCE = "needs source"
HUMAN_SOURCE = "human entry"

SEVERITY_LEVELS = ("minor", "major", "critical")  # weakest first
# Detection: how the check found the finding. Lower index = weaker evidence = listed first.
DETECTION_LABELS = ("model only", "quote match", "code rule")
FORBIDDEN_WORDS = ("r" "pn", "product", "score")

# Severity table keyed by rule id: (level, source id or "needs source").
# The framework sources support the rule, not the level, so every level below still needs a
# source. A human may replace a row with a log entry. A rule with no row is "not set".
SEVERITY_TABLE = {
    "ALT-01": ("major", NEEDS_SOURCE),
    "ALT-02": ("minor", NEEDS_SOURCE),
    "ALT-03": ("major", NEEDS_SOURCE),
    "NIE-02": ("minor", NEEDS_SOURCE),
    "NIE-03": ("major", NEEDS_SOURCE),
    "NIE-04": ("major", NEEDS_SOURCE),
    "EMR-01": ("major", NEEDS_SOURCE),
    "EMR-02": ("major", NEEDS_SOURCE),
    "EMR-03": ("minor", NEEDS_SOURCE),
    "LBL-18": ("major", NEEDS_SOURCE),
    "NOTE-01": ("major", NEEDS_SOURCE),
    "NOTE-02": ("major", NEEDS_SOURCE),
    "NOTE-03": ("major", NEEDS_SOURCE),
}


def _check_row(row):
    if not isinstance(row, dict) or row.get("severity") not in SEVERITY_LEVELS or not row.get("fault_id"):
        raise ValueError("human row needs fault_id and severity in " + "/".join(SEVERITY_LEVELS))


def _severity(fid, rule, proposal, table, human_rows):
    for row in human_rows:
        _check_row(row)
    human = [r for r in human_rows if r["fault_id"] == fid]
    if human:
        last = human[-1]  # the latest row wins; earlier rows stay in the log and are counted
        sev = dict(value=last["severity"], source=HUMAN_SOURCE, label=last["severity"],
                   earlier=len(human) - 1)
        if last.get("reader_id"):
            sev["reader_id"] = last["reader_id"]
            sev["date"] = str(last.get("ts") or "")[:10]
    elif rule in table:
        level, src = table[rule]
        sev = dict(value=level, source=src or NEEDS_SOURCE, label=level)
    else:
        sev = dict(value=None, source=None, label=NOT_SET_LABEL)
    prop = None
    if proposal is not None:
        prop = dict(value=proposal, label=PROPOSAL_LABEL)
    return sev, prop


def load_human_rows(db_path):
    """Read the human severity rows from the audit log, oldest first (insert order). Read only."""
    if not Path(db_path).is_file():
        raise FileNotFoundError(f"database file not found: {db_path}")
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        return [dict(fault_id=r[0], severity=r[1], reader_id=r[2], ts=r[3], reason=r[4])
                for r in con.execute("SELECT fault_id, severity, reader_id, ts, reason "
                                     "FROM human_severity ORDER BY rowid")]
    except sqlite3.OperationalError:
        return []  # a log made before this table existed: no human rows
    finally:
        con.close()


def _occurrence(rule, real_counts):
    if not real_counts or rule not in real_counts:
        return dict(text=EXAMPLE_TEXT, rate=0.0)
    c = real_counts[rule]
    k, n = c.get("k"), c.get("n")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0 or not isinstance(k, int) or not 0 <= k <= n:
        raise ValueError("real occurrence needs integer k and n with 0 <= k <= n and n > 0")
    return dict(text=f"{k} of {n} cases (n={n})", rate=k / n)


def _detection(decision, reason):
    if decision == "DISPUTED":
        label = "model only"
    elif "regex agrees" in (reason or ""):
        label = "code rule"
    else:
        label = "quote match"
    return dict(text=label, index=DETECTION_LABELS.index(label))


def assess(verdict, table=None, human_rows=(), real_counts=None):
    """One verdict -> dict with three separate fields: severity, occurrence, detection."""
    table = SEVERITY_TABLE if table is None else table
    f = verdict["finding"]
    fid, rule = f.get("fault_id"), f.get("rule_id")
    sev, prop = _severity(fid, rule, f.get("severity"), table, list(human_rows))
    return dict(fault_id=fid, rule_id=rule, decision=verdict["decision"], quote=f.get("quote"),
                severity=sev, severity_proposal=prop,
                occurrence=_occurrence(rule, real_counts),
                detection=_detection(verdict["decision"], verdict.get("reason")))


def forbidden_keys(a):
    """Names of keys that would carry one combined number. Empty list = clean."""
    return [k for k in a if any(w in k.lower() for w in FORBIDDEN_WORDS)]


def rank(items):
    """Severity first (not set = last), then weak detection first, then higher real occurrence.
    Ties keep input order."""
    def sev_index(a):
        v = a["severity"]["value"]
        return SEVERITY_LEVELS.index(v) if v in SEVERITY_LEVELS else -1

    keyed = [(-sev_index(a), a["detection"]["index"], -a["occurrence"]["rate"], i, a) for i, a in enumerate(items)]
    return [t[-1] for t in sorted(keyed, key=lambda t: t[:4])]


def product_proxy(a):
    """TEST HELPER ONLY. Mimics a product ranker so tests can show it would rank differently.
    Never used by rank()."""
    s = SEVERITY_LEVELS.index(a["severity"]["value"]) + 1 if a["severity"]["value"] in SEVERITY_LEVELS else 0
    weak = {0: 5, 1: 3, 2: 1}[a["detection"]["index"]]
    return s * weak


def run(verdicts, table=None, human_rows=(), real_counts=None):
    """Assess CONFIRMED and DISPUTED verdicts only (dropped ones are skipped), then rank."""
    kept = [v for v in verdicts if v.get("decision") in ("CONFIRMED", "DISPUTED")]
    return rank([assess(v, table, human_rows, real_counts) for v in kept])


def render(ranked):
    lines = []
    for i, a in enumerate(ranked, 1):
        s = a["severity"]
        src = f" (source: {s['source']})" if s["source"] else ""
        if s.get("reader_id"):
            src = f" (source: {s['source']}, reader {s['reader_id']}, {s['date']})"
        if s.get("earlier"):
            src += f" | earlier entries: {s['earlier']}"
        lines.append(f"{i}. {a['fault_id']} | rule {a['rule_id']} | {a['decision']}")
        lines.append(f"   {'Severity: ' if s['value'] else ''}{s['label']}{src} | Occurrence: {a['occurrence']['text']}"
                     f" | Detection: {a['detection']['text']}")
        p = a["severity_proposal"]
        if p:
            lines.append(f"   Severity {PROPOSAL_LABEL}: {p['value']} (ranks nothing until a human accepts it)")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _sample():
    ok = "quote found, rule id valid, regex agrees"
    quote = "quote found, rule id valid"
    dis = "model and regex rule disagree"

    def v(fid, rule, dec, reason, sev=None):
        f = dict(fault_id=fid, rule_id=rule, quote="synthetic quote " + fid)
        if sev is not None:
            f["severity"] = sev
        return dict(finding=f, decision=dec, reason=reason)

    return [v("s1", "EMR-03", "CONFIRMED", quote), v("s2", "EMR-01", "DISPUTED", dis, 10),
            v("s3", "ALT-02", "CONFIRMED", ok), v("s4", "XXX-99", "CONFIRMED", quote, 9),
            v("s5", "NOTE-01", "CONFIRMED", ok)]


def selftest():
    vs = _sample()
    ranked = run(vs)
    order = [a["fault_id"] for a in ranked]
    assert order == ["s2", "s5", "s1", "s3", "s4"], order
    assert all(a["occurrence"]["text"] == EXAMPLE_TEXT for a in ranked)
    assert all(not forbidden_keys(a) for a in ranked)
    assert ranked[-1]["severity"]["label"] == NOT_SET_LABEL
    assert ranked[-1]["severity_proposal"]["label"] == PROPOSAL_LABEL
    assert render(ranked).rstrip().endswith(DISCLAIMER)
    print("risk_step selftest: PASS")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--sample", action="store_true", help="print a ranked list from synthetic findings")
    ap.add_argument("--verdicts", help="JSON list of referee verdicts")
    ap.add_argument("--human", help="JSON list of human severity rows")
    ap.add_argument("--db", help="audit log (sqlite): human severity rows are read from it; they win over --human rows")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.sample:
        print(render(run(_sample())))
        return 0
    if a.verdicts:
        with open(a.verdicts, encoding="utf-8") as fh:
            vs = json.load(fh)
        hr = []
        if a.human:
            with open(a.human, encoding="utf-8") as fh:
                hr = json.load(fh)
        if a.db:
            try:
                hr = hr + load_human_rows(a.db)  # log rows come last, so the log wins
            except FileNotFoundError as e:
                print(e)
                return 1
        print(render(run(vs, human_rows=hr)))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
