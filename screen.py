"""Live record screen: builds the record for one run from the log (read only) and renders it as HTML.

Words are taken verbatim from the words file (design/hft/live_record_screen_words.md).
Standard library only. No outside call. Nothing here writes to the log.
Stages (upto): 1..n = log rows shown one by one; n+1 = the risk cell. REPLAY plays these stages.
"""
import html
import json
from pathlib import Path

import log
import orchestrator
import referee
import render_design
import render_redesign
import risk_step

CASES_DIR = Path(__file__).resolve().parent / "pilot" / "cases"

SPEEDS = (1, 10, 30, 100)
DEFAULT_SPEED = 30
MIN_DELAY_MS = 800
CODE_ONLY = "found by code rule, no model finding"
AGENTS = (("reader", "READER"), ("rule_checker", "RULE CHECKER"), ("referee", "REFEREE"))

REASONS = {
    "quote found, rule id valid, regex agrees":
        "Quote, rule and code pattern agree.",
    "quote found, rule id valid": "The quote is in the screen text and the rule is on the list.",
    CODE_ONLY: "Found by code rule. No model finding.",
    "model and regex rule disagree (regex hit is not inside the quote)":
        "The code found it outside the quote the model gave.",
    "quote not found in the ocr text": "This quote is not in the screen text.",
    "rule id not in the frozen list": "The rule is not on the list.",
    "rule does not apply to this item type": "The rule does not apply to this kind of screen.",
    "look-alike names already use tall-man letters": "Look-alike names already use tall-man letters.",
}
UNABLE_WORDS = {
    "reader could not read the text": "The screen text could not be read",
    "ocr text is empty or under 20 characters": "The screen text is empty or too short",
    "reader listed no usable line": "The screen text could not be read",
}


def plain_reason(reason):
    r = (reason or "").strip()
    if r.lower().startswith("tool state is"):
        return "The screen text could not be read"
    return UNABLE_WORDS.get(r.lower(), r or "the reason is not in the log")


def n_faults(n):
    return f"{n} finding" if n == 1 else f"{n} findings"


def line_of(text, piece):
    """Line number (from 1) where piece first appears in text, or None."""
    i = text.find(piece) if text and piece else -1
    if i < 0:
        i = text.find(referee.fix_space(piece)) if text and piece else -1
    return None if i < 0 else text.count(chr(10), 0, i) + 1


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def say(reason):
    r = (reason or "").strip()
    if r.lower() in REASONS:
        return REASONS[r.lower()]
    if not r:
        return "No reason is written in the log."
    r = r[0].upper() + r[1:]
    return r if r.endswith(".") else r + "."


def parse_json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- the record (read only)
def rule_result_rows(con, run_id):
    return [dict(r) for r in con.execute(
        "SELECT rr.* FROM rule_results rr JOIN steps s ON s.step_id=rr.step_id WHERE s.run_id=? "
        "GROUP BY rr.rr_id ORDER BY rr.rowid", (run_id,))]


def decision_rows(con, run_id):
    return [dict(r) for r in con.execute(
        "SELECT d.* FROM decisions d JOIN steps s ON s.step_id=d.step_id WHERE s.run_id=? "
        "GROUP BY d.decision_id ORDER BY d.rowid", (run_id,))]


def human_severity_rows(con, run_id):
    try:
        return [dict(r) for r in con.execute(
            "SELECT h.* FROM human_severity h JOIN decisions d ON d.decision_id=h.decision_id "
            "JOIN steps s ON s.step_id=d.step_id WHERE s.run_id=? GROUP BY h.severity_id ORDER BY h.rowid",
            (run_id,))]
    except Exception:
        return []  # a log made before this table existed


def chain_state(con):
    ok, n, broken = log.verify_chain(con)
    return dict(ok=bool(ok), rows=n, broken=broken)


def list_runs(con):
    return [dict(r) for r in con.execute(
        "SELECT run_id, MIN(case_id) AS case_id FROM steps GROUP BY run_id ORDER BY MIN(rowid)")]


def build_record(con, run_id):
    steps = [dict(r) for r in con.execute("SELECT rowid AS row_id, * FROM steps WHERE run_id=? ORDER BY rowid",
                                          (run_id,))]
    if not steps:
        return None
    hashes = {r["row_id"]: (r["prev_hash"], r["row_hash"]) for r in con.execute(
        "SELECT row_id, prev_hash, row_hash FROM log_chain WHERE table_name='steps'")}
    for s in steps:
        s["prev_hash"], s["row_hash"] = hashes.get(s["row_id"], ("", ""))
        s["tool_calls"] = con.execute("SELECT COUNT(*) FROM tool_calls WHERE step_id=?", (s["step_id"],)).fetchone()[0]
    case = con.execute("SELECT * FROM cases WHERE case_id=?", (steps[0]["case_id"],)).fetchone()
    run = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    kind = case["kind"] if case else None
    return dict(run_id=run_id, kind=kind, now=rejudge(steps, kind), case_id=steps[0]["case_id"], planted=case["planted"] if case else "none",
                seed=run["seed"] if run else None, steps=steps,
                rules=rule_result_rows(con, run_id), decisions=decision_rows(con, run_id),
                human=human_severity_rows(con, run_id), chain=chain_state(con))


# ---------------------------------------------------------------- stage logic
def _last(steps, agent, phase):
    got = [s for s in steps if s["agent"] == agent and s["phase"] == phase]
    return got[-1] if got else None


def reader_text(steps):
    s = _last(steps, "reader", "after")
    if not s or not s["came_back"]:
        return None
    first, _, rest = s["came_back"].partition("\n")
    if first.strip() == "PASS":
        return rest if rest.strip() else None
    return None


def proposals_of(steps):
    s = _last(steps, "rule_checker", "after")
    data = parse_json(s["came_back"]) if s else None
    return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []


def final_of(steps):
    s = _last(steps, "referee", "after")
    data = parse_json(s["came_back"]) if s else None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- today's referee (no model call)
def code_check(rid, quote, text):
    """What the code pattern for this rule finds in the text, judged by referee.py.
    kind: 'inside' (a hit lies inside the quote), 'outside' (hits only elsewhere), 'none', 'list' (no pattern)."""
    fn = referee.REGEX_RULES.get(rid)
    if fn is None or not text:
        return dict(kind="list", hit=None)
    hits = fn(text)
    if not hits:
        return dict(kind="none", hit=None)
    q = referee.fix_space(quote or "")
    inside = [h for h in hits if referee.fix_space(h) in q]
    return dict(kind="inside", hit=inside[0]) if inside else dict(kind="outside", hit=hits[0])


def rejudge(steps, kind):
    """Re-judge the logged model output with TODAY's referee.py. No model call. Returns a final dict
    (state, findings, dropped), or the logged one when the log holds no readable text."""
    logged = final_of(steps)
    text = reader_text(steps)
    if logged is None or text is None or logged.get("state") == "UNABLE TO CHECK":
        return logged
    props, seen = [], set()
    for st in steps:  # every rule-checker reply, so a quote that was sent back stays in the record
        if st["agent"] == "rule_checker" and st["phase"] == "after":
            for q in proposals_of([st]):
                if (q.get("rule_id"), q.get("quote")) not in seen:
                    seen.add((q.get("rule_id"), q.get("quote")))
                    props.append(q)
    ids = set(orchestrator.load_rules())
    item = referee.classify_item(text, kind)
    sent = {(d.get("rule_id"), d.get("quote")) for d in logged.get("dropped") or [] if d.get("sent_back")}
    verdicts = referee.add_code_findings(referee.judge(props, text, ids, item), text, item, ids)
    kept = [dict(rule_id=v["finding"]["rule_id"], quote=v["finding"]["quote"], state=v["decision"], reason=v["reason"])
            for v in verdicts if v["decision"] != "drop"]
    dropped = [dict(rule_id=v["finding"].get("rule_id"), quote=v["finding"].get("quote"), reason=v["reason"],
                    sent_back=(v["finding"].get("rule_id"), v["finding"].get("quote")) in sent)
               for v in verdicts if v["decision"] == "drop"]
    state = ("DISPUTED" if any(k["state"] == "DISPUTED" for k in kept) else "CONFIRMED" if kept else "CHECKED")
    return dict(state=state, findings=kept, dropped=dropped)


def delay_ms(rec, upto, speed):
    steps = rec["steps"]
    if upto <= 0 or upto >= len(steps):
        return MIN_DELAY_MS
    from datetime import datetime
    try:
        gap = (datetime.fromisoformat(steps[upto]["ts"]) - datetime.fromisoformat(steps[upto - 1]["ts"])).total_seconds()
    except ValueError:
        gap = 0
    return int(max(MIN_DELAY_MS, gap / max(speed, 1) * 1000))


# ---------------------------------------------------------------- icons (inline, no namespace needed)
ICONS = {
    "CONFIRMED": '<svg class="icon tick" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l5 5 11-11" fill="none" stroke="currentColor" stroke-width="3"/></svg>',
    "DISPUTED": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"/><rect x="3" y="3" width="9" height="18" fill="currentColor"/></svg>',
    "DROPPED": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="4 3"/><path d="M5 19L19 5" stroke="currentColor" stroke-width="2"/></svg>',
    "UNABLE TO CHECK": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"/><path d="M3 11L11 3M3 18L18 3M7 21L21 7M14 21L21 14" stroke="currentColor" stroke-width="2"/></svg>',
    "CHECKED": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 12h8" stroke="currentColor" stroke-width="2"/></svg>',
    "replay": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l13 8-13 8z" fill="currentColor"/></svg>',
    "live": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" fill="currentColor"/></svg>',
    "linked": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="8" width="8" height="8" fill="currentColor"/><rect x="14" y="8" width="8" height="8" fill="currentColor"/><path d="M10 12h4" stroke="currentColor" stroke-width="2"/></svg>',
    "broken": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="8" width="7" height="8" fill="currentColor"/><rect x="15" y="8" width="7" height="8" fill="currentColor"/><path d="M10 6l-1 12M14 6l1 12" stroke="currentColor" stroke-width="2"/></svg>',
}


def badge(state):
    cls = state.lower().replace(" ", "-")
    return f'<span class="badge b-{cls}" data-state="{esc(state)}">{ICONS[state]}<b>{esc(state)}</b></span>'


# ---------------------------------------------------------------- pieces
TIP = ("Each log row holds the hash of the row before. This shows edits. "
       "It does not stop a full rewrite of the file.")
FOOTER = ("Pre-check. Not a medical device. Does not replace a human factors engineer. Not reviewed. "
          "Made-up cases, invented names. Runs on this computer only.")


def _speed_button(v, speed):
    pressed = ' aria-pressed="true"' if v == speed else ""
    return f'<button type="button" data-speed="{v}"{pressed}>x{v}</button>'


def band(rec, mode, speed, upto):
    if mode == "replay":
        mchip = (f'<div class="chip mode replay">{ICONS["replay"]}<span><b>REPLAY.</b> '
                 f'Recorded run, shown at x{speed} speed. Original times shown.</span></div>')
        ctrl = ('<div class="controls"><button type="button" data-action="play">Play</button>'
                '<span class="speeds" role="group" aria-label="Speed">'
                + "".join(_speed_button(v, speed) for v in SPEEDS) + '</span>'
                f'<details class="speedmenu"><summary>Speed x{speed}</summary>'
                '<span class="speeds" role="group" aria-label="Speed list">'
                + "".join(_speed_button(v, speed) for v in SPEEDS) + '</span></details></div>')
    else:
        mchip = f'<div class="chip mode live">{ICONS["live"]}<span><b>LIVE.</b> Real speed.</span></div>'
        ctrl = ""
    if rec["chain"]["ok"]:
        cchip = (f'<div class="chip chain ok" tabindex="0">{ICONS["linked"]}<span>Log chain intact</span>'
                 f'<span class="tip" role="tooltip">{esc(TIP)}</span></div>')
    else:
        cchip = (f'<div class="chip chain bad" tabindex="0">{ICONS["broken"]}<span>Log chain broken. '
                 f'Do not trust this record.</span><span class="tip" role="tooltip">{esc(TIP)}</span></div>')
    return (f'<header class="band" data-mode="{mode}"><div class="bandleft">'
            f'<p class="eyebrow">Live record <span>Case {esc(rec["case_id"])}</span></p>'
            f'<h1><span class="soft">Models suggest.</span> <span class="strong">Code rules decide.</span></h1></div>'
            f'<div class="bandright">{mchip}{cchip}{ctrl}</div>'
            f'<p class="chips"><span class="chip">PILOT. Made-up case, invented names.</span>'
            f'<span class="chip">Not a medical device. Not reviewed by a human.</span>'
            f'<span class="chip">No accuracy figure</span></p></header>')


def planted_line(rec, unable=False):
    """ONE planted line per screen (CD round 4 polish 2). Empty when the case is not planted."""
    if rec["planted"] == "none":
        return ""
    if unable:
        return "Planted test case. We made this screen unreadable on purpose."
    if rec["planted"] == "fake_quote":
        return "Planted test case. The model quotes text that is not there, on purpose."
    return "Planted test case. We put this finding in on purpose."


def case_strip(rec, text, quotes, finished, unable=False):
    planted = ""
    if text is None:
        body = '<p class="status">No text could be read from this screen.</p>' if finished else ""
    else:
        taken = []
        for q in quotes:
            i = text.find(q) if q else -1
            if i >= 0 and not any(i < b and a < i + len(q) for a, b in taken):
                taken.append((i, i + len(q)))
        out, pos = [], 0
        for a, b in sorted(taken):
            out.append(esc(text[pos:a]))
            out.append(f"<mark>{esc(text[a:b])}</mark>")
            pos = b
        out.append(esc(text[pos:]))
        body = f'<p class="casetext">{"".join(out)}</p>'
    return (f'<section class="strip"><p class="label">Text being checked <span class="legend">'
            f'Highlight = quote from a finding</span></p>{planted}{body}</section>')


def rail(rec, vis, show_risk, st, kept_n, dropped_n, text):
    done = st["ref_done"]
    unable = done and st["final"] and st["final"].get("state") == "UNABLE TO CHECK"
    out = []
    for agent, name in AGENTS:
        rows = [s for s in vis if s["agent"] == agent]
        if not rows or (unable and text is None and agent == "rule_checker"):
            status, last, rows = ("Not run", None, []) if done else ("Waiting", None, [])
        else:
            last = rows[-1]
            status = "Done" if last["phase"] == "after" else "Working"
        before = next((s for s in rows if s["phase"] == "before"), None)
        after = next((s for s in reversed(rows) if s["phase"] == "after"), None)
        ts = (last["ts"][11:19] if last else "")
        line = ""
        if agent == "reader":
            if after:
                line = "Read the screen text." if text is not None else "Could not read the screen text."
            elif before:
                line = "Reading the screen text."
            elif done:
                line = "Not run. The check stopped."
        elif agent == "rule_checker":
            if after:
                line = f"Suggested {n_faults(len(proposals_of(vis)))}."
            elif before:
                line = "Looking for findings."
            elif done:
                line = "Not run. The check stopped."
        else:
            if done:
                line = "Could not check." if unable else f"Kept {kept_n}. Dropped {dropped_n}."
            elif before:
                line = "Checking the quotes and rules."
        one = f'<p class="plain">{esc(line)}</p>' if line else ""
        out.append(f'<li class="step s-{status.lower().replace(" ", "-")}"><p class="agent">{name}</p>'
                   f'<p class="meta"><span class="status">{status}</span> <span>{esc(ts)}</span></p>{one}'
                   f'{_drawer(rec, agent, name, before, after, last)}</li>')
    if show_risk and not unable:
        rline, rstat = f"Rated {n_faults(kept_n)}.", "Done"
    elif unable:
        rline, rstat = "Not run.", "Not run"
    else:
        rline, rstat = "", "Waiting"
    out.append(f'<li class="step s-{rstat.lower().replace(" ", "-")}"><p class="agent">RISK</p>'
               f'<p class="meta"><span class="status">{rstat}</span></p>'
               + (f'<p class="plain">{esc(rline)}</p>' if rline else "") + '</li>')
    return (f'<details class="railwrap"><summary><span class="o">Steps. Open to read the steps.</span><span class="c">Steps. Steps below.</span></summary><nav class="rail" aria-label="Steps">'
            f'<ol>{"".join(out)}</ol></nav></details>')


def _drawer(rec, agent, name, before, after, last):
    if not last:
        return ""
    seq = last["seq"]
    model = ("Model: none. This step is plain code." if agent == "referee" else
             f'Model (tag): {esc(last["model_row_id"] or "not logged")}. Seed: {esc(rec["seed"])}. '
             f'Prompt version: {esc(last["prompt_id"] or "not logged")}')
    return (f'<details class="drawer" data-keep="{esc(agent)}"><summary><span class="o">Open technical detail</span>'
            f'<span class="c">Close technical detail</span></summary>'
            f'<h3>Technical detail: {esc(agent)}, step {esc(seq)}</h3><dl>'
            f'<dt>Asked</dt><dd>{esc((before or {}).get("asked"))}</dd>'
            f'<dt>Came back</dt><dd>{esc((after or {}).get("came_back"))}</dd>'
            f'<dt>Hash of this row</dt><dd>{esc(last["row_hash"][:8].upper())}</dd>'
            f'<dt>Hash of the row before</dt><dd>{esc(last["prev_hash"][:8].upper())}</dd>'
            f'<dt>Time</dt><dd>{esc(last["ts"])}</dd><dt>Tool calls</dt><dd>{esc(last["tool_calls"])}</dd>'
            f'<dt>Model</dt><dd>{model}</dd></dl>'
            f'<p class="note">Full text is shown here. The ledger shows short text.</p></details>')


# ---------------------------------------------------------------- risk cell
def risk_cell(row, human, just):
    cls = "risk just" if just else "risk"
    if row["state"] not in ("CONFIRMED", "DISPUTED"):
        return f'<td class="{cls}" data-label="Risk">Not rated: dropped</td>'
    verdict = dict(finding=dict(fault_id=row["fault_id"], rule_id=row["rule_id"], quote=row["quote"]),
                   decision=row["state"], reason=row["reason"])
    a = risk_step.assess(verdict, human_rows=human)
    sev, tag = a["severity"], ""
    if sev["source"] == risk_step.HUMAN_SOURCE:
        if sev.get("reader_id") and sev.get("date"):
            line = f'Severity: {esc(sev["value"])}. Set by {esc(sev["reader_id"])}, {esc(sev["date"])}.'
            table = risk_step.SEVERITY_TABLE.get(row["rule_id"])
            if table:
                line += f'<br><span class="grey">Table value was {esc(table[0])}. Replaced.</span>'
            tag = '<span class="tag">Human entry</span>'
        else:
            line, tag = "Human entry. Reader or date missing.", ""
    elif sev["value"]:
        line = f'Severity: {esc(sev["value"])}. Source: {esc(sev["source"])}.'
    else:
        line = "Severity: not set"
    det = "code rule" if row["code_only"] else a["detection"]["text"]
    if just:
        tag += '<span class="tag just-tag">Just filled</span>'
    return (f'<td class="{cls}" data-label="Risk"><p>{line}</p>{tag}<p>Occurrence: {esc(risk_step.EXAMPLE_TEXT)}</p>'
            f'<p>Detection: {esc(det)}</p></td>')


# ---------------------------------------------------------------- ledger
def build_rows(rec, st):
    props = proposals_of(st["vis"])
    final = st["final"] if st["ref_done"] else None
    rows = []
    if final is None:
        for p in props:
            rows.append(dict(state=None, quote=p.get("quote"), rule_id=p.get("rule_id"), reason="", prop=p,
                             code_only=False, fault_id=p.get("fault_id"), model_sev=p.get("severity") not in (None, "")))
        return rows, []
    def find(f):
        return next((p for p in props if p.get("rule_id") == f.get("rule_id") and p.get("quote") == f.get("quote")), None)
    for f in final.get("findings") or []:
        p = find(f)
        code_only = (f.get("reason") or "").strip().lower() == CODE_ONLY
        rows.append(dict(state=f.get("state"), quote=f.get("quote"), rule_id=f.get("rule_id"), reason=f.get("reason"),
                         prop=p, code_only=code_only,
                         fault_id=(p or {}).get("fault_id") or f"code-{f.get('rule_id')}",
                         model_sev=bool(p and p.get("severity") not in (None, ""))))
    dropped = []
    for d in final.get("dropped") or []:
        p = find(d)
        dropped.append(dict(state="DROPPED", quote=d.get("quote"), rule_id=d.get("rule_id"), reason=d.get("reason"),
                            prop=p, sent_back=bool(d.get("sent_back"))))
    return rows, dropped


def code_words(chk, code_only=False):
    h = esc(chk["hit"])
    if chk["kind"] == "inside":
        return (f'Pattern "{h}" found in the text. No model finding.' if code_only
                else f'Pattern "{h}" found inside the quote.')
    if chk["kind"] == "outside":
        return f'Pattern "{h}" found, but outside the quote.'
    if chk["kind"] == "none":
        return "Pattern not found."
    return "The rule is on the list. The quote is in the screen text."


def rule_cell(row, rec, st, just):
    cls = "code rule" + (" just" if just else "")
    if not st["ref_before"]:
        return f'<td class="{cls} wait" data-label="Code rule result">Waiting for code</td>'
    chk = code_check(row["rule_id"], row["quote"], st["text"])
    tag = '<span class="tag just-tag">Just filled</span>' if just else ""
    return (f'<td class="{cls}" data-label="Code rule result"><p><b>{esc(row["rule_id"])}</b></p>'
            f'<p>{code_words(chk, row["code_only"])}</p>{tag}</td>')


def model_cell(row):
    p = row["prop"]
    if p is None:
        return ('<td class="model none" data-label="Model suggested"><p>No model finding</p></td>')
    return (f'<td class="model" data-label="Model suggested"><p><b>{esc(p.get("rule_id"))}</b></p>'
            f'<p class="q">{esc(p.get("quote"))}</p></td>')


def decision_cell(row, rec, st, just):
    cls = "decision" + (" just" if just else "")
    state = row["state"]
    if state is None:
        return f'<td class="{cls} wait" data-label="Decision">Waiting for code</td>'
    tag = '<span class="tag just-tag">Just filled</span>' if just else ""
    if state == "CONFIRMED":
        body = f'{badge(state)}<p>{esc(say(row["reason"]))}</p><p>Code kept this finding.</p>'
    else:
        chk = code_check(row["rule_id"], row["quote"], st["text"])
        wrote = (row["prop"] or {}).get("quote") or row["quote"]
        ql = line_of(st["text"], wrote)
        hl = line_of(st["text"], chk["hit"])
        qloc = f"line {ql}" if ql else "place not found"
        hloc = f"{esc(chk['hit'])}, line {hl}" if (chk["hit"] and hl) else esc(chk["hit"] or "no match")
        body = (f'{badge("DISPUTED")}<div class="split"><div><p class="label">Model quoted: {qloc}</p></div>'
                f'<div><p class="label">Code found: {hloc}</p></div></div>'
                f'<p>{esc(say(row["reason"]))}</p><p>A human must look. The record names no winner.</p>')
    return f'<td class="{cls}" data-label="Decision">{body}{tag}</td>'


def ledger(rec, st, rows, human):
    newest = "risk" if st["risk"] else "decision" if st["ref_done"] else "rule" if st["ref_before"] else None
    trs = []
    for i, r in enumerate(rows):
        last = i == len(rows) - 1
        added = '<span class="tag">Added by code</span>' if r["code_only"] else ""
        risk = (risk_cell(r, human, newest == "risk" and last) if st["risk"] else
                '<td class="risk wait" data-label="Risk">Waiting for code</td>')
        num = f'<span class="num">{r["n"]}</span>' if r.get("n") else ""
        hint = (f'<p class="hint{" always" if r["hint"].startswith("Box not") else ""}"><span class="hw">{esc(r["hint"])}</span><span class="hn">{esc(r["hint_narrow"])}</span></p>'
                if r.get("hint") else "")
        dn = f' data-n="{r["n"]}" tabindex="0"' if r.get("n") else ""
        trs.append(f'<tr{dn}><td class="quote" data-label="Quote">{num}{esc(r["quote"])}{added}{hint}</td>{model_cell(r)}'
                   f'{rule_cell(r, rec, st, newest == "rule" and last)}'
                   f'{decision_cell(r, rec, st, newest == "decision" and last)}{risk}</tr>')
    if not trs:
        trs.append('<tr class="empty"><td colspan="5">' + esc(st["empty_text"]) + "</td></tr>")
    more = (f'<p class="more">{len(rows) - 1} more {"row" if len(rows) == 2 else "rows"} below</p>' if len(rows) > 1 else "")
    return ('<section class="ledgerwrap"><p class="caption">A finding stays only if its quote is in the case text '
            'and its rule id is on the list.</p><div class="scroll"><table class="ledger"><thead><tr>'
            '<th class="quote">Quote<small>From the case text</small></th>'
            '<th class="model">Model suggested<small>Proposal only. Not used to rank.</small></th>'
            '<th class="code">Code rule result<small>What the code checked</small></th>'
            '<th class="code">Decision<small>Made by code, not by a model</small></th>'
            '<th class="code">Risk<small>Severity, source, how found</small></th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table></div>{more}</section>')


def drop_fold(dropped):
    if not dropped:
        return ""
    items = []
    for d in dropped:
        sb = ('<p>Sent back to the rule checker. Code judged the reply.</p>' if d["sent_back"] else "")
        items.append(f'<li>{badge("DROPPED")}<p class="struck">{esc(d["quote"])}</p>'
                     f'<p>{esc(say(d["reason"]))}</p>{sb}<p>Not rated: dropped</p></li>')
    n = len(dropped)
    return (f'<details class="dropfold" open><summary><span class="o">Dropped ({n}). Open to read the reasons.</span>'
            f'<span class="c">Dropped ({n}). Reasons below.</span></summary>'
            f'<ul>{"".join(items)}</ul></details>')


def end_message(final, reason, kept, dropped):
    state = final["state"]
    if state == "UNABLE TO CHECK":
        return f"UNABLE TO CHECK: {plain_reason(reason)}. The check did not finish."
    if any(k["state"] == "DISPUTED" for k in kept):
        if len(kept) == 1:
            return f"1 finding kept. It is DISPUTED: a human must look. {len(dropped)} dropped."
        return f"{n_faults(len(kept))} kept. At least one is DISPUTED: a human must look. {len(dropped)} dropped."
    if kept:
        return f"{n_faults(len(kept))} CONFIRMED by code. {len(dropped)} dropped."
    return f"The text was read. No finding passed the code check. {len(dropped)} dropped."


def unable_banner(reason):
    hatch = ('<svg class="hatch" aria-hidden="true"><defs><pattern id="hp" width="10" height="10" '
             'patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="10" '
             'stroke="#17242B" stroke-opacity="0.22" stroke-width="2"/></pattern></defs>'
             '<rect width="4000" height="1500" fill="url(#hp)"/></svg>')
    return (f'<section class="unable" data-state="UNABLE TO CHECK">{hatch}<div class="plate">'
            f'<h2>{ICONS["UNABLE TO CHECK"]}UNABLE TO CHECK</h2>'
            f'<p>The check stopped: {esc(plain_reason(reason))}.</p><p>The check did not finish.</p>'
            f'<p>Check this text by hand.</p></div></section>')


def checked_card(dropped_n):
    return (f'<section class="checked" data-state="CHECKED">{badge("CHECKED")}'
            f'<p>The text was read. No finding passed the code check. {dropped_n} dropped.</p>'
            f'<p>This is a result for this one case only.</p></section>')


# ---------------------------------------------------------------- page
def banner(title, text):
    return f'<section class="errbanner"><h2>{esc(title)}</h2><p>{esc(text)}</p></section>'


def shell(inner, mode="live", run="", upto=0, n=0, speed=DEFAULT_SPEED, delay=MIN_DELAY_MS):
    return (f'<div id="rec" data-mode="{mode}" data-run="{esc(run)}" data-upto="{upto}" data-n="{n}" '
            f'data-speed="{speed}" data-delay="{delay}">{inner}</div>')


SEVERITY_NOTE = ("Severity levels are set from published human-factors sources. They have not been reviewed by a clinician. Use your own clinical judgement.")


def footer():
    return f'<footer class="foot"><p>{esc(FOOTER)}</p><p>{esc(SEVERITY_NOTE)}</p></footer>'


def unreadable():
    return shell(banner("LOG UNREADABLE. The log file cannot be read. Stop. Do not use this record.",
                        "Check the file, then reload.") + footer())


def no_run(runs):
    links = "".join(f'<li><a href="/?run={esc(r["run_id"])}">Case {esc(r["case_id"])}</a></li>' for r in runs)
    return shell(banner("No run selected. Pick a case before you start.", "") +
                 (f'<ul class="pick">{links}</ul>' if links else "") + footer())


# ---------------------------------------------------------------- the design itself (hft-team-11)
def design_text(rec, st):
    """The text to draw: the case file when it exists (pilot), else what the reader returned."""
    f = CASES_DIR / f"{rec['case_id']}.ocr.txt"
    if f.is_file():
        return f.read_bytes().decode("utf-8")
    return st["text"] if st["text"] is not None else ""


def _inside(a, b):
    return (a["x"] >= b["x"] and a["y"] >= b["y"] and a["x"] + a["w"] <= b["x"] + b["w"]
            and a["y"] + a["h"] <= b["y"] + b["h"] and (a["w"], a["h"]) != (b["w"], b["h"]))


def make_boxes(d, rows, st):
    """Boxes from today's run data (rows = referee result). Never typed by hand. Sets n, hint on each row."""
    boxes = []
    for i, r in enumerate(rows, 1):
        r["n"] = i
        placed = False
        if r["state"] == "CONFIRMED":
            hb = None
            if not d.narrow and not r["code_only"]:  # the code hit sits inside the quote: draw it as an inner box
                chk = code_check(r["rule_id"], r["quote"], st["text"])
                qi = d.text.find(r["quote"])
                if chk["kind"] == "inside" and chk["hit"] and chk["hit"] != r["quote"] and qi >= 0:
                    hb = d.locate(chk["hit"], px=14, py=9, at=qi)
            b = d.locate(r["quote"], px=21, py=14) if hb else d.locate(r["quote"])
            if hb and not (b and hb["line"] == b["line"] == b["line_end"] and b["a"] <= hb["a"] and hb["b"] <= b["b"]):
                hb, b = None, d.locate(r["quote"])
            if b:
                placed = True
                boxes.append(dict(n=i, kind="added" if r["code_only"] else "confirmed", box=b,
                                  word="ADDED BY CODE" if r["code_only"] else "CONFIRMED", rule=r["rule_id"],
                                  place=r["quote"]))
                if hb:
                    boxes.append(dict(n=i, kind="hit", box=hb, word=f"Code hit: {hb['quote']}", rule=r["rule_id"],
                                      place=hb["quote"]))
        elif r["state"] == "DISPUTED":
            chk = code_check(r["rule_id"], r["quote"], st["text"])
            wrote = (r["prop"] or {}).get("quote") or r["quote"]
            mb, cb = d.locate(wrote), d.locate(chk["hit"])
            if mb:
                placed = True
                boxes.append(dict(n=i, kind="dmodel", box=mb, word=f"DISPUTED. Model quoted: line {mb['line'] + 1}",
                                  rule=r["rule_id"], place=wrote))
            if cb:
                placed = True
                boxes.append(dict(n=i, kind="dcode", box=cb, rule=r["rule_id"], place=chk["hit"],
                                  word=f"DISPUTED. Code found: {chk['hit']}, line {cb['line'] + 1}"))
        r["hint"] = f"Finding {i} is marked on the image." if placed else "Box not placed."
        r["hint_narrow"] = f"Finding {i}: box above. Tap to show it." if placed else "Box not placed."
    seen = []
    for b in boxes:  # two findings on the same spot: the later box is drawn as an outer ring, so both stay visible
        b["ring"] = sum(1 for o in seen if o["n"] != b["n"] and o["box"]["x"] == b["box"]["x"] and o["box"]["y"] == b["box"]["y"]
                        and o["box"]["w"] == b["box"]["w"])
        seen.append(b)
        if b["ring"] and b["kind"] == "added":  # say in words why a second finding sits on the same spot
            b["word"] = "ADDED BY CODE. The model did not name this second finding."
    for b in boxes:
        b["nested"] = any(o is not b and o["n"] != b["n"] and _inside(b["box"], o["box"]) for o in boxes)
    boxes.sort(key=lambda b: (b["box"]["line"], b["box"]["a"], b["ring"]))  # tags follow the box order, top to bottom
    return boxes


def _pct(v, whole):
    return f"{v / whole * 100:.3f}%"


def _box_html(d, b, placed, boxes=()):
    x = b["box"]
    cls = "dn" if d.narrow else "dw"
    style = f"left:{_pct(x['x'], d.W)};top:{_pct(x['y'], d.H)};width:{_pct(x['w'], d.W)};height:{_pct(x['h'], d.H)}"
    if b["nested"] and b["kind"] != "hit":
        style = (f"left:calc({_pct(x['x'], d.W)} + 6px);top:calc({_pct(x['y'], d.H)} + 6px);"
                 f"width:calc({_pct(x['w'], d.W)} - 12px);height:calc({_pct(x['h'], d.H)} - 12px)")
    # one tag per box. Beside the drawn line when there is clear room right of the letters (the design is seen
    # first); else above the box; below it when the box is too near the title bar.
    lead = d.line_end_x(x) + 12 - x["x"]
    free = d.W - (x["x"] + lead) - 8
    need = 110 if d.narrow else 150
    strip = d.strip_top is not None
    if strip:
        pos, tstyle = "st", ""
    elif free >= need:
        th = 30 if d.narrow else 36
        top = x["y"]
        for py in sorted(placed):  # two beside-tags on near rows: the later one steps down, never on top of the first
            if abs(top - py) < th:
                top = py + th
        placed.append(top)
        pos = "rt"
        tstyle = (f"left:{lead / d.W * 100:.3f}cqw;max-width:{free / d.W * 100:.3f}cqw;"
                  f"top:calc(50% + {(top - x['y']) / d.W * 100:.3f}cqw)")
    elif x["y"] < d.top + 30:
        pos, tstyle = "below", ""
    else:
        pos, tstyle = "", ""
    if b.get("ring"):
        g = (4 if d.narrow else 8) * b["ring"]
        style = (f"left:calc({_pct(x['x'], d.W)} - {g}px);top:calc({_pct(x['y'], d.H)} - 5px);"
                 f"width:calc({_pct(x['w'], d.W)} + {2 * g}px);height:calc({_pct(x['h'], d.H)} + 10px)")
        if not strip:
            pos, tstyle = "below", ""
    if strip:  # tags go in a strip under the drawing, never over a letter
        slot = len(placed)
        placed.append(slot)
        sy = d.strip_top + slot * d.slot
        pos = "st"
        tstyle = (f"left:{(d.sx - x['x']) / d.W * 100:.3f}cqw;top:{(sy - x['y']) / d.W * 100:.3f}cqw;"
                  f"max-width:{(d.W - d.sx - 6) / d.W * 100:.3f}cqw")
    # number chip on the box's top-left corner, above it (above the outer box for an inner hit box), never on a letter
    off = 0.0
    shift = 0.0
    if b["nested"] or b["kind"] == "hit":
        outs = [o["box"] for o in boxes if o is not b and _inside(x, o["box"])]
        if outs:
            off = x["y"] - min(o["y"] for o in outs)
            shift = max(0.0, 40 - (x["x"] - min(o["x"] for o in outs)))
    r = b.get("ring", 0)
    cstyle = (f"left:calc(-3px + {shift / d.W * 100:.3f}cqw + {r} * (var(--tag) + 2px));"
              f"bottom:calc(100% + {2 if r else 6}px + {off / d.W * 100:.3f}cqw)")
    chip = f'<b class="numchip" style="{cstyle}">{b["n"]}</b>'
    tick = "✓ " if b["kind"] == "confirmed" else ""
    label = f"Finding {b['n']}, {b['rule']}, {b['word']}, box on {b['place']}."
    return (f'<div class="bx k-{b["kind"]}{" in" if b["nested"] else ""} {cls}" data-n="{b["n"]}" data-q="{x["line"]}:{x["a"]}:{x["b"]}" tabindex="0" role="button" '
            f'aria-label="{esc(label)}" style="{style}">{chip}<span class="tg {pos}" style="{tstyle}">'
            f'<b class="nm">{b["n"]}</b><span class="w">{tick}{esc(b["word"])}</span></span></div>')


def alt_text(d, boxes):
    parts = [f"Made-up {render_design.CAPTIONS[d.kind]}, case {d.case_id}.", f"{len({b['n'] for b in boxes})} numbered boxes."]
    for b in boxes:
        parts.append(f"Box {b['n']}: {b['word']}, on \"{b['place']}\".")
    return " ".join(parts)


def conn_html(d, boxes):
    """No link lines (hft-team-11 fix 4): each box carries its own number chip, the tag below carries the same number."""
    return ""


def design_panel(rec, st, final, unable, boxes, d, boxes_n, dn):
    pl = planted_line(rec, unable)
    planted = f'<p class="planted">{esc(pl)}</p>' if pl else ""
    after = ""
    if st["ref_done"] and final and final["state"] not in ("UNABLE TO CHECK",) and not boxes and not (final.get("findings") or []):
        ran = sorted({str(x.get("rule_id")) for x in rec["rules"] if x.get("rule_id")})
        after = ('<p class="under">CHECKED: no finding passed the code check.</p>'
                 + (f'<p class="under">Rules that ran: {esc(", ".join(ran))}.</p>' if ran else ""))
    dn_svg = dn.svg().replace('class="design"', 'class="design dn"', 1)
    dw_svg = d.svg().replace('class="design"', 'class="design dw"', 1)
    pl_w, pl_n = [], []
    stage = (f'<div class="stage" style="--w:{d.W};--h:{d.H};--nw:{dn.W};--nh:{dn.H}" aria-label="{esc(alt_text(d, boxes))}">'
             f'{dw_svg}{dn_svg}{conn_html(d, boxes)}{conn_html(dn, boxes_n)}'
             f'{"".join(_box_html(d, b, pl_w, boxes) for b in boxes)}{"".join(_box_html(dn, b, pl_n, boxes_n) for b in boxes_n)}</div>')
    return (f'<div class="panel">'
            f'{"" if not boxes else ""}'
            f'<p class="legend2"{"" if boxes else " hidden"}><span class="lw">Numbered boxes = findings. Click a box or a row to link them.</span>'
            f'<span class="ln2">Numbered boxes = findings. Tap a box or a row to link them.</span></p>'
            f'{planted}<div class="frame" data-n-boxes="{len(boxes)}">{stage}</div>'
            f'<button type="button" class="enlarge" data-action="enlarge">Tap image to enlarge</button>'
            f'<p class="cap">{esc(d.caption())}</p>{after}</div>')


def render(rec, mode="live", speed=DEFAULT_SPEED, upto=None, show=None):
    """show = replay only: draw just the first N decided rows (the screens show box 1 landing before box 2)."""
    if speed not in SPEEDS:
        speed = DEFAULT_SPEED
    steps = rec["steps"]
    n = len(steps)
    if upto is None:
        upto = 0 if mode == "replay" else n + 1
    upto = max(0, min(int(upto), n + 1))
    vis = steps[:min(upto, n)]
    final_row = _last(vis, "referee", "after")
    st = dict(vis=vis, final=(rec["now"] if rec.get("now") is not None else final_of(vis)) if final_row else None,
              reader_done=_last(vis, "reader", "after") is not None,
              ref_before=_last(vis, "referee", "before") is not None,
              ref_done=final_row is not None)
    st["risk"] = st["ref_done"] and upto >= n + 1
    working = vis[-1] if vis else None
    status = ""
    if not vis:
        status = ("Press Play to start the replay." if mode == "replay"
                  else "Waiting for the first step. A real model step takes minutes.")
    elif not st["reader_done"]:
        status = "Reader is working. No finding yet."
    elif not st["ref_done"] and not st["ref_before"] and _last(vis, "rule_checker", "after") is None:
        status = "Rule checker is working. Its output is a proposal."
    st["empty_text"] = "No finding yet. The code decides after the steps end."
    st["text"] = reader_text(vis) if st["reader_done"] else None
    rows, dropped = build_rows(rec, st)
    if show is not None and mode == "replay" and st["ref_done"]:
        rows, dropped = rows[:max(int(show), 0)], []
    quotes = [r["quote"] for r in rows] + [d["quote"] for d in dropped]
    text = st["text"]
    unable_reason = next((d["model_wrote"] for d in rec["decisions"] if d["decision"] == "UNABLE TO CHECK"), None) \
        or "the reason is not in the log"
    fin = st["final"]
    body = ""
    note = ""
    unable_now = bool(st["ref_done"] and fin and fin["state"] == "UNABLE TO CHECK")
    panel = ""
    if vis:
        unread = rec["planted"] == "unreadable" or (unable_now and text is None)
        d = render_design.Design(design_text(rec, st), rec.get("kind"), rec["case_id"], unreadable=unread)
        boxes = make_boxes(d, rows, st) if (st["ref_done"] and fin and not unable_now) else []
        dn = render_design.Design(design_text(rec, st), rec.get("kind"), rec["case_id"], unreadable=unread, narrow=True)
        boxes_n = make_boxes(dn, rows, st) if boxes or (st["ref_done"] and fin and not unable_now) else []
        dn.set_strip([b["word"] for b in boxes_n])
        d.set_strip([b["word"] for b in boxes])
        panel = design_panel(rec, st, fin, unable_now, boxes, d, boxes_n, dn)
    if st["ref_done"] and fin:
        kept = [r for r in rows]
        if fin["state"] == "UNABLE TO CHECK":
            body = unable_banner(unable_reason)
        elif not kept:
            body = checked_card(len(dropped)) + drop_fold(dropped)
        else:
            body = ledger(rec, st, rows, rec["human"]) + drop_fold(dropped)
        msg = "" if (not kept and fin["state"] != "UNABLE TO CHECK") else " " + esc(end_message(fin, unable_reason, kept, dropped))
        if unable_now:
            note = '<p class="finish">Run stopped.</p>'
        elif mode == "replay" and not st["risk"]:  # replay: the last step (the risk cell) is still to come
            note = '<p class="finish">Replaying a recorded run. Not live.</p>'
        else:
            note = f'<p class="finish">Run finished.{msg}</p>'
    else:
        body = ledger(rec, st, rows, rec["human"])
        if mode == "replay" and vis:
            note = '<p class="finish">Replaying a recorded run. Not live.</p>'
        elif status:
            note = ""
    if status and not st["ref_done"]:
        note = f'<p class="finish">{esc(status)}</p>' + note
    strip = case_strip(rec, text, quotes, st["reader_done"] or st["ref_done"], unable_now)
    redesign = ""
    if vis and st["ref_done"] and fin and not unable_now and rows:
        findings = [dict(id=r["n"], rule=r["rule_id"], state=r["state"], quote=r["quote"]) for r in rows]
        redesign = render_redesign.section(findings, design_text(rec, st), rec.get("kind"),
                                           rec["case_id"], badges={k: badge(k) for k in ("CONFIRMED", "DISPUTED")})
    inner = (band(rec, mode, speed, upto) +
             f'<main class="body{" nopanel" if not panel else ""}">{panel}<div class="main">{strip if panel else ""}{note}{body}</div>'
             f'{rail(rec, vis, st["risk"], st, len(rows), len(dropped), text)}</main>' + redesign + footer())
    if not panel:
        inner = inner.replace('<main class="body nopanel">', strip + '<main class="body nopanel">', 1)
    return shell(inner, mode, rec["run_id"], upto, n + 1, speed, delay_ms(rec, upto, speed))
