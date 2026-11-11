"""Live record screen: read-only routes, modes, five end states, labels, no outside request."""
import http.client
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import log  # noqa: E402
import referee  # noqa: E402
import screen  # noqa: E402
import server  # noqa: E402
import live_fixtures  # noqa: E402

PILOT_LOG = ROOT / "pilot" / "audit_log_pilot.sqlite"
BANNED = [w.strip() for w in (ROOT / "pilot" / "banned_names.txt").read_text(encoding="utf-8").splitlines()
          if w.strip() and not w.startswith("#")]
RUNS = ("rConf", "rDisp", "rDrop", "rUnable", "rChecked")


@pytest.fixture(scope="module")
def dbpath(tmp_path_factory):
    p = tmp_path_factory.mktemp("live") / "fx.sqlite"
    con = log.open_db(str(p))
    live_fixtures.build(con)
    con.close()
    return str(p)


def get(srv, target):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    c.request("GET", target)
    r = c.getresponse()
    body = r.read().decode("utf-8")
    c.close()
    return r.status, body


def view(path, run, mode="live", extra=""):
    srv, t = server.start(path, port=0, mode=mode)
    try:
        s, b = get(srv, f"/view?run={run}{extra}")
        assert s == 200
        return b
    finally:
        server.stop(srv, t)


def text_of(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# ---- routes: GET only, loopback only
def test_new_routes_serve_rows_and_writes_are_refused(dbpath):
    srv, t = server.start(dbpath, port=0)
    try:
        for target in ("/api/rule_results/rConf", "/api/decisions/rConf", "/api/human_severity/rConf"):
            s, b = get(srv, target)
            assert s == 200 and json.loads(b)["rows"], target
        s, b = get(srv, "/api/log_chain")
        d = json.loads(b)
        assert s == 200 and d["ok"] is True and d["rows"] > 0
        for verb in ("POST", "PUT", "DELETE", "PATCH"):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
            c.request(verb, "/api/decisions/rConf", body=b"x")
            assert c.getresponse().status == 405
            c.close()
    finally:
        server.stop(srv, t)


def test_only_do_get_reads_and_bind_is_loopback(dbpath):
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert re.findall(r"def (do_[A-Z]+)", src) == ["do_GET"]
    with pytest.raises(ValueError):
        server.AuditServer(dbpath, 0, "0.0.0.0")
    srv, t = server.start(dbpath, port=0)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        server.stop(srv, t)


# ---- modes
def test_replay_label_in_replay_mode_only(dbpath):
    r = view(dbpath, "rConf", "replay", "&speed=30")
    assert "REPLAY." in r and "Recorded run, shown at x30 speed. Original times shown." in r
    assert "LIVE." not in r
    live = view(dbpath, "rConf", "live", "&speed=30")
    assert "LIVE." in live and "Real speed." in live and "REPLAY" not in live and "x30" not in live


def test_bad_speed_falls_back_to_default(dbpath):
    assert "x30 speed" in view(dbpath, "rConf", "replay", "&speed=999999")


# ---- five end states
@pytest.mark.parametrize("run,word", [("rConf", "CONFIRMED"), ("rDisp", "DISPUTED"), ("rDrop", "DROPPED"),
                                      ("rUnable", "UNABLE TO CHECK"), ("rChecked", "CHECKED")])
def test_each_end_state_renders_with_word_and_shape(dbpath, run, word):
    r = view(dbpath, run)
    assert f'data-state="{word}"' in r
    assert word in text_of(r)
    assert "<svg" in r  # a shape, not colour alone


def test_confirmed_reason_and_no_bare_ok(dbpath):
    t = text_of(view(dbpath, "rConf"))
    assert "Quote, rule and code pattern agree." in t
    assert "Code kept this finding." in t and 'Pattern "QD" found inside the quote.' in t
    assert not re.search(r"\bOK\b", t)


def test_disputed_shows_both_sides_and_no_winner(dbpath):
    t = text_of(view(dbpath, "rDisp"))
    for s in ("Model quoted: line 1", "Code found: [OK], line 2", "A human must look. The record names no winner.",
              "The code found it outside the quote the model gave.", 'Pattern "[OK]" found, but outside the quote.'):
        assert s in t
    assert 'class="tick"' not in view(dbpath, "rDisp")


def test_dropped_has_reason_struck_quote_and_no_risk(dbpath):
    r = view(dbpath, "rDrop")
    t = text_of(r)
    for s in ("This quote is not in the screen text.", "Sent back to the rule checker. Code judged the reply.",
              "Dropped (1). Open to read the reasons.", "Planted test case. The model quotes text that is not there, on purpose.",
              "Not rated: dropped"):
        assert s in t
    assert 'class="struck"' in r
    assert "Severity:" not in t
    # the planted test is told once, in one separate line (ED ruling, hft-team-11 batch 1)
    assert t.count("Planted test case") == 1
    assert re.search(r'<p class="planted">Planted test case\. The model quotes text that is not there, on purpose\.</p>', r)


def test_unable_has_no_clean_words(dbpath):
    r = view(dbpath, "rUnable")
    t = text_of(r)
    low = t.lower()
    for bad in ("no findings", "no faults", "passed", "0 results", "clean"):
        assert bad not in low, bad
    assert not re.search(r"\bok\b", low)
    assert "The check stopped: The screen text could not be read." in t
    assert "No text could be read from this screen." in t and "tool state" not in t
    assert "The check did not finish." in t and "Check this text by hand." in t
    assert 'class="ledger"' not in r  # the banner replaces the ledger
    assert "Severity:" not in t


def test_checked_is_not_unable_and_has_no_tick(dbpath):
    r = view(dbpath, "rChecked")
    t = text_of(r)
    assert "The text was read. No finding passed the code check. 0 dropped." in t
    assert "This is a result for this one case only." in t and "safe" not in t.lower()
    assert 'data-state="UNABLE TO CHECK"' not in r and 'class="tick"' not in r


def test_code_only_row(dbpath):
    t = text_of(view(dbpath, "rConf"))
    for s in ("No model finding", "Found by code rule. No model finding.", "Added by code",
              'Pattern "U" found in the text. No model finding.'):
        assert s in t


# ---- risk cell
def test_risk_cell_three_apart_fields_no_model_number(dbpath):
    r = view(dbpath, "rConf")
    cells = re.findall(r'<td class="risk[^"]*"[^>]*>(.*?)</td>', r, re.S)
    assert len(cells) == 2
    for c in cells:
        t = text_of(c)
        assert "Severity:" in t and "Occurrence: example, not measured" in t and "Detection:" in t
    joined = text_of(" ".join(cells))
    assert "Proposal only. Not used to rank." in text_of(view(dbpath, "rConf"))
    assert "9" not in joined  # the model proposed "9": it must not show in the risk cell
    assert not re.search(r"\b(rpn|total)\b", joined, re.I)


def test_human_severity_shows_name_and_date(dbpath):
    t = text_of(view(dbpath, "rConf"))
    assert "Severity: critical. Set by Dr Test Reader, 2026-11-10." in t
    assert "Human entry" in t and "Table value was major. Replaced." in t


# ---- labels, words, numbers
@pytest.mark.parametrize("run", RUNS)
def test_always_on_labels(dbpath, run):
    t = text_of(view(dbpath, run))
    for s in ("PILOT. Made-up case, invented names.", "Not a medical device. Not reviewed by a human.",
              "No accuracy figure", "Models suggest.", "Code rules decide."):
        assert s in t, s


@pytest.mark.parametrize("run", RUNS)
def test_no_numbers_or_banned_words(dbpath, run):
    r = view(dbpath, run)
    t = text_of(r).replace("No accuracy figure", "")
    assert "%" not in text_of(r)
    assert not re.search(r"\b\d+ of \d+\b", t)
    for w in ("accurate", "accuracy", "validated", "proven", "tamper-proof", "ai-powered", "rules run before"):
        assert w not in t.lower(), w


def test_chain_chip_intact_and_broken(dbpath, tmp_path):
    assert "Log chain intact" in view(dbpath, "rConf")
    bad = tmp_path / "bad.sqlite"
    shutil.copy(dbpath, bad)
    con = sqlite3.connect(bad)
    con.execute("DROP TRIGGER steps_no_update")
    con.execute("UPDATE steps SET came_back='changed' WHERE step_id='rConf-reader-1-a'")
    con.commit()
    con.close()
    assert "Log chain broken. Do not trust this record." in text_of(view(str(bad), "rConf"))


def test_replay_stages_fill_in_order(dbpath):
    # rows revealed: 1 reader-b 2 reader-a 3 rc-b 4 rc-a 5 referee-b 6 referee-a, 7 = risk
    assert "Press Play to start the replay." in view(dbpath, "rConf", "replay", "&upto=0")
    s4 = view(dbpath, "rConf", "replay", "&upto=4")
    assert "Model suggested" in s4 and 'data-state="CONFIRMED"' not in s4 and "pattern" not in text_of(s4).split("Code rule result")[-1].lower()
    s5 = view(dbpath, "rConf", "replay", "&upto=5")
    assert 'Pattern "QD" found inside the quote.' in s5 and 'data-state="CONFIRMED"' not in s5
    s6 = view(dbpath, "rConf", "replay", "&upto=6")
    assert 'data-state="CONFIRMED"' in s6 and "Severity:" not in text_of(s6)
    assert "Severity:" in text_of(view(dbpath, "rConf", "replay", "&upto=7"))


def test_highlight_only_on_newest_code_cell_never_on_model(dbpath):
    r = view(dbpath, "rConf", "replay", "&upto=5")
    assert r.count("Just filled") == 1
    assert len(re.findall(r'<td class="[^"]*\bjust\b', r)) == 1
    for cell in re.findall(r'<td class="[^"]*\bmodel\b[^"]*"', r):
        assert "just" not in cell


def test_no_run_and_unreadable(tmp_path, dbpath):
    srv, t = server.start(dbpath, port=0)
    try:
        s, b = get(srv, "/view?run=")
        assert "No run selected. Pick a case before you start." in text_of(b)
    finally:
        server.stop(srv, t)
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"not a database")
    srv, t = server.start(str(junk), port=0)
    try:
        s, b = get(srv, "/view?run=x")
        assert "LOG UNREADABLE. The log file cannot be read. Stop. Do not use this record." in text_of(b)
    finally:
        server.stop(srv, t)


# ---- no outside request, banned names
def test_page_loads_no_remote_url(dbpath):
    names = ("index.html", "live.css", "live.js")
    blobs = [(ROOT / "web" / n).read_text(encoding="utf-8") for n in names] + [view(dbpath, r) for r in RUNS]
    for b in blobs:
        assert not re.search(r"(https?:)?//[a-z0-9]", b, re.I)
        assert "@import" not in b and "xmlns" not in b
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert re.findall(r'(?:src|href)="([^"]+)"', html) == ["/live.css", "/live.js"]


def test_banned_names_absent(dbpath):
    blobs = [(ROOT / "web" / n).read_text(encoding="utf-8").lower() for n in ("index.html", "live.css", "live.js")]
    blobs += [view(dbpath, r).lower() for r in RUNS]
    for b in blobs:
        for w in BANNED:
            assert w.lower() not in b, w


# ---- REPLAY from the logged pilot runs (no model run)
@pytest.mark.skipif(not PILOT_LOG.exists(), reason="pilot log missing")
def test_replay_of_logged_pilot_runs():
    states = {"run0008": "DISPUTED", "run0017": "UNABLE TO CHECK", "run0013": "CHECKED", "run0019": "DROPPED"}
    srv, t = server.start(str(PILOT_LOG), port=0, mode="replay")
    try:
        for run, st in states.items():
            s, b = get(srv, f"/view?run={run}&upto=9")
            assert s == 200 and "REPLAY." in b and f'data-state="{st}"' in b, run
    finally:
        server.stop(srv, t)


# ---- TRUTH: every badge agrees with today's referee (hit in the quote), and plain words
JARGON = ("regex", "ocr", "fault", "COULD NOT CHECK", "{", "tool state", "json")


def rows_of(html):
    """(quote, rule id, badge word) for each ledger row of the rendered page."""
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        quote = re.search(r'<td class="quote"[^>]*>(.*?)</td>', tr, re.S)
        rule = re.search(r'<td class="code rule[^"]*"[^>]*><p><b>([^<]+)</b>', tr)
        badge = re.search(r'data-state="([A-Z ]+)"', tr)
        if quote and rule and badge:
            q = re.sub(r"<[^>]+>", "", re.sub(r'<span class="num">.*?</span>|<p class="hint.*?</p>', "", quote.group(1))).replace("Added by code", "").strip()
            out.append((q.replace("&quot;", '"'), rule.group(1), badge.group(1)))
    return out


def badge_mismatches(html, ocr_text):
    """Rows whose badge disagrees with hit-in-quote as computed by referee.py."""
    bad = []
    for q, rid, word in rows_of(html):
        q = __import__("html").unescape(q)
        if rid in referee.REGEX_RULES:
            inside = referee._hit_in_quote(rid, q, ocr_text)
            if (word == "CONFIRMED") != inside or (word == "DISPUTED") == inside:
                bad.append((q, rid, word))
    return bad


def case_texts():
    """(source, run id, path) for every fixture run and every logged pilot run."""
    return PILOT_LOG


@pytest.mark.parametrize("run", RUNS)
def test_fixture_badges_agree_with_referee(dbpath, run):
    con = log.open_db(dbpath)
    text = screen.reader_text(screen.build_record(con, run)["steps"]) or ""
    con.close()
    html = view(dbpath, run)
    assert badge_mismatches(html, text) == []


def test_fixture_true_examples(dbpath):
    conf = view(dbpath, "rConf")
    assert ("Take 1 tablet QD", "EMR-01", "CONFIRMED") in rows_of(conf)
    disp = rows_of(view(dbpath, "rDisp"))
    assert ("ALERT: Kelmorane dose 40 mg is above the range 5 to 20 mg", "ALT-03", "DISPUTED") in disp
    assert not any(w == "CONFIRMED" and q.startswith("ALERT") for q, _, w in disp)


@pytest.mark.skipif(not PILOT_LOG.exists(), reason="pilot log missing")
def test_pilot_replay_badges_agree_with_todays_referee():
    con = log.open_db(str(PILOT_LOG))
    runs = [r["run_id"] for r in screen.list_runs(con)]
    seen = {"CONFIRMED": 0, "DISPUTED": 0}
    srv, t = server.start(str(PILOT_LOG), port=0, mode="replay")
    try:
        for run in runs:
            text = screen.reader_text(screen.build_record(con, run)["steps"]) or ""
            s, html = get(srv, f"/view?run={run}&upto=99")
            assert badge_mismatches(html, text) == [], run
            for _, _, w in rows_of(html):
                seen[w] = seen.get(w, 0) + 1
        s, html = get(srv, "/view?run=run0008&upto=99")  # pilot P08: the [OK] hit is outside the quote
        assert 'data-state="DISPUTED"' in html
        assert ("ALT-03", "DISPUTED") in [(r, w) for _, r, w in rows_of(html)]
    finally:
        server.stop(srv, t)
        con.close()


def test_planted_wrong_badge_fails_the_check(dbpath):
    con = log.open_db(dbpath)
    disp_text = screen.reader_text(screen.build_record(con, "rDisp")["steps"])
    conf_text = screen.reader_text(screen.build_record(con, "rConf")["steps"])
    con.close()
    d = view(dbpath, "rDisp")
    assert badge_mismatches(d, disp_text) == []
    assert badge_mismatches(d.replace('data-state="DISPUTED"', 'data-state="CONFIRMED"'), disp_text)
    c = view(dbpath, "rConf")
    assert badge_mismatches(c, conf_text) == []
    assert badge_mismatches(c.replace('data-state="CONFIRMED"', 'data-state="DISPUTED"', 1), conf_text)


@pytest.mark.parametrize("run", RUNS)
def test_no_machine_words_outside_the_drawer(dbpath, run):
    html = view(dbpath, run)
    outside = re.sub(r'<details class="drawer".*?</details>', " ", html, flags=re.S)
    outside = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", outside, flags=re.S)
    t = text_of(outside).lower().replace("{", "") if False else text_of(outside).lower()
    for w in ("regex", "ocr", "fault", "COULD NOT CHECK", "tool state", "json", "came back:", "asked:"):
        assert w not in t, w


def test_unable_shows_not_run_and_dropped_wording(dbpath):
    t = text_of(view(dbpath, "rUnable"))
    assert "Not run. The check stopped." in t and "Waiting" not in t
    d = text_of(view(dbpath, "rDrop"))
    assert "Dropped (1). Reasons below." in d


def test_wordmark_and_just_filled_tag(dbpath):
    assert "mmonfar" in (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "Just filled" in text_of(view(dbpath, "rConf"))


# ---- batch 3: one word per idea, split box places, phone first screen
def test_split_box_shows_places_not_the_quote_again(dbpath):
    r = view(dbpath, "rDisp")
    box = re.search(r'<div class="split">(.*?)</div></div>', r, re.S).group(1)
    assert "Model quoted: line" in box and "Code found:" in box and ", line" in box
    assert "Take 1" not in box and "ALERT" not in box


def test_unable_word_is_the_same_in_status_and_badge(dbpath):
    t = text_of(view(dbpath, "rUnable"))
    assert "UNABLE TO CHECK" in t and "COULD NOT CHECK" not in t


def test_no_word_fault_on_screen_in_any_state(dbpath):
    for run in RUNS:
        assert not re.search(r"faults?", text_of(view(dbpath, run)), re.I), run


def test_phone_design_is_above_844_px_and_ledger_under_it(dbpath):
    sync = pytest.importorskip("playwright.sync_api")
    srv, t = server.start(dbpath, port=0, mode="replay")
    try:
        with sync.sync_playwright() as pw:
            b = pw.chromium.launch(channel="msedge")
            for run in ("rConf", "rDisp"):
                pg = b.new_page(viewport={"width": 390, "height": 844})
                pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/?run={run}&upto=99&speed=30")
                pg.wait_for_selector("#rec .band")
                # hft-team-11: the design is the main view on the phone, the ledger sits under it
                stage = pg.evaluate("document.querySelector('.stage').getBoundingClientRect().bottom + scrollY")
                badge = pg.evaluate("document.querySelector('.badge').getBoundingClientRect().top + scrollY")
                assert stage < 844 and badge >= stage, (run, stage, badge)
                assert pg.evaluate("document.querySelectorAll('.band button[data-speed]:not(.x)').length") >= 1
                pg.close()
            b.close()
    finally:
        server.stop(srv, t)


def test_planted_line_word_per_state(dbpath):
    u = text_of(view(dbpath, "rUnable"))
    assert "We made this screen unreadable on purpose." in u and "put this finding in" not in u
    for run in RUNS:
        if run != "rUnable":
            t = text_of(view(dbpath, run))
            assert "unreadable on purpose" not in t, run


def test_split_box_line_number_never_breaks(dbpath):
    box = re.search(r'<div class="split">(.*?)</div></div>', view(dbpath, "rDisp"), re.S).group(1)
    assert re.search(r"line \d", box) and not re.search(r"line \d", box)


def test_run_finished_does_not_repeat_checked_box(dbpath):
    sync = pytest.importorskip("playwright.sync_api")
    for run in RUNS:
        h = view(dbpath, run)
        if 'data-state="CHECKED"' in h:
            fin = re.search(r'<p class="finish">(.*?)</p>', h, re.S).group(1)
            assert fin == "Run finished.", fin
            assert "No finding passed the code check" not in fin


PHONE_STATES = [("confirmed", "run0003", ("CONFIRMED", "ADDED BY CODE")), ("disputed", "run0008", ("DISPUTED",)), ("dropped", "run0019", ("CHECKED", "DROPPED")),
                ("unable", "run0017", ("UNABLE TO CHECK",)), ("checked", "run0014", ("CHECKED",))]


def test_phone_first_screen_shows_a_state_word_above_844_px():
    """ED ruling (hft-team-11 fix 6): on 390x844 a state word is visible without scrolling: the first box tag
    on the image (with its state word) or the ledger badge. The UNABLE banner counts."""
    sync = pytest.importorskip("playwright.sync_api")
    pilot = Path(__file__).resolve().parents[1] / "pilot" / "audit_log_pilot.sqlite"
    srv, t = server.start(str(pilot), port=0, mode="replay")
    try:
        with sync.sync_playwright() as p:
            try:
                b = p.chromium.launch(channel="msedge")
            except Exception:
                pytest.skip("Edge not available")
            for state, run, word in PHONE_STATES:
                pg = b.new_page(viewport={"width": 390, "height": 844})
                pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/?run={run}&upto=99&speed=30")
                pg.wait_for_selector("#rec .band")
                got = pg.evaluate("""() => { const c = [];
                  for (const e of document.querySelectorAll('.bx.dn .tg .w, .badge, .unable h2, .panel .under')) {
                    const r = e.getBoundingClientRect();
                    if (r.width && r.height) c.push([e.textContent.trim(), r.bottom + scrollY]); }
                  return c; }""")
                seen = [txt for txt, bottom in got if bottom < 844]
                assert any(w in txt.upper() for txt in seen for w in word), (state, got)
                pg.close()
            b.close()
    finally:
        server.stop(srv, t)


DISCLAIMER = ("Severity levels are set from published human-factors sources. They have not been reviewed "
              "by a clinician. Use your own clinical judgement.")


@pytest.mark.parametrize("run", RUNS)
def test_severity_disclaimer_in_rendered_report(dbpath, run):
    assert DISCLAIMER in text_of(view(dbpath, run))


def test_severity_disclaimer_in_readme():
    assert DISCLAIMER in " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
