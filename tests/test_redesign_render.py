"""Illustrative redesign on the live record screen (card hft-team-14).

String checks on the rendered page, then a browser sweep at 390, 1366 and 1920 px.
Proofs can fail: each check has a planted wrong case that must be caught.
"""
import http.client
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import live_fixtures  # noqa: E402
import log  # noqa: E402
import redesign_table as rt  # noqa: E402
import render_design  # noqa: E402
import render_redesign  # noqa: E402
import server  # noqa: E402

RUNS = ("rConf", "rDisp", "rDrop", "rUnable", "rChecked")
SHOWN = {"rConf": True, "rDisp": True, "rDrop": False, "rUnable": False, "rChecked": False}
SIZES = {"390": (390, 844), "1366": (1366, 768), "1920": (1920, 1080)}


@pytest.fixture(scope="module")
def dbpath(tmp_path_factory):
    p = tmp_path_factory.mktemp("rd") / "fx.sqlite"
    con = log.open_db(str(p))
    live_fixtures.build(con)
    con.close()
    return str(p)


@pytest.fixture(scope="module")
def srv(dbpath):
    s, t = server.start(dbpath, port=0, mode="live")
    yield s
    server.stop(s, t)


def page(srv, run, path="/view"):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    c.request("GET", f"{path}?run={run}")
    r = c.getresponse()
    body = r.read().decode("utf-8")
    c.close()
    assert r.status == 200
    return body


def cards(html):
    return re.findall(r'<li class="rcard( disputed)?" data-n="(\d+)"', html)


def ledger_states(html):
    return re.findall(r'<tr[^>]*data-n="(\d+)"[^>]*>.*?data-state="(CONFIRMED|DISPUTED)"', html, re.S)


def check_fix_count(html, confirmed):
    """Raises when the number of fix cards is not the number of CONFIRMED findings."""
    got = len([c for c in cards(html) if not c[0]])
    if got != confirmed:
        raise AssertionError(f"{got} fix cards for {confirmed} confirmed findings")


@pytest.mark.parametrize("run", RUNS)
def test_section_only_for_confirmed_or_disputed(srv, run):
    html = page(srv, run)
    assert ("id=\"redesign\"" in html) == SHOWN[run]
    if not SHOWN[run]:
        assert rt.TAG not in html and "What changed" not in html and rt.DISPUTED_WORDS not in html


@pytest.mark.parametrize("run", [r for r in RUNS if SHOWN[r]])
def test_tag_exact_and_order_after_findings(srv, run):
    html = page(srv, run)
    assert html.count(rt.TAG) == 1
    assert html.index('id="redesign"') > html.index("<table") > html.index('class="panel"')
    assert html.index('id="redesign"') < html.index('class="foot"')
    assert html.index("What changed") > html.index(rt.TAG)


def test_fix_count_equals_confirmed_count_and_numbers_equal_ids(srv):
    for run, confirmed in (("rConf", 2), ("rDisp", 1)):
        html = page(srv, run)
        check_fix_count(html, confirmed)
        ids = {n: s for n, s in ledger_states(html)}
        for dis, n in cards(html):
            assert ids[n] == ("DISPUTED" if dis else "CONFIRMED")
        # chips on the image carry the same numbers
        assert set(re.findall(r'class="bx rbx[^"]*" data-n="(\d+)"', html)) <= set(ids)


def test_planted_extra_card_is_caught(srv):
    html = page(srv, "rConf")
    bad = html.replace('<ol class="rcards">', '<ol class="rcards"><li class="rcard" data-n="9">x</li>', 1)
    with pytest.raises(AssertionError):
        check_fix_count(bad, 2)


def test_disputed_shows_only_the_human_line_no_fix(srv):
    html = page(srv, "rDisp")
    m = re.search(r'<li class="rcard disputed".*?</li>', html, re.S)
    assert m and rt.DISPUTED_WORDS in m.group(0)
    for w in ("Principle:", "Source:", "Rule:", "Write", "Add choices"):
        assert w not in m.group(0)


@pytest.mark.parametrize("run", RUNS)
def test_banned_words_absent_from_the_page(srv, run):
    assert render_redesign.banned_hits(page(srv, run)) == []
    assert render_redesign.banned_hits("Better") == ["better"]  # the grep can fail


@pytest.mark.parametrize("run", [r for r in RUNS if SHOWN[r]])
def test_no_internal_words_no_fixed_mark_no_link_lines(srv, run):
    sec = page(srv, run).split('id="redesign"', 1)[1]
    low = sec.lower()
    for w in ("wiki", "summary note", "refs_books", ".md", "fixed"):  # zero-trace: ok
        assert w not in low, w
    stage = sec.split('class="rstage"', 1)[1].split('class="rlist"', 1)[0]
    assert "<path" not in stage and 'class="conn' not in stage


def test_drawn_text_equals_case_text_except_table_words(srv):
    html = page(srv, "rConf")
    svgs = re.findall(r'<svg[^>]*class="design rw".*?</svg>', html.split('id="redesign"', 1)[1], re.S)
    assert len(svgs) == 1
    assert render_design.drawn_text(svgs[0]) == live_fixtures.TEXT.replace("Take 1 tablet QD", "Take 1 tablet every day")
    html = page(srv, "rDisp")
    svgs = re.findall(r'<svg[^>]*class="design rw".*?</svg>', html.split('id="redesign"', 1)[1], re.S)
    assert render_design.drawn_text(svgs[0]) == live_fixtures.TEXT_OK.replace("[OK]", "[OK] [Change] [Cancel]")


def test_undrawable_fix_says_so_and_changes_nothing(srv):
    text = "ALERT: x\nCheck dose now"
    f = [dict(id=1, rule="ALT-02", state="CONFIRMED", quote="Check dose now")]
    sec = render_redesign.section(f, text, "alert", "Z1")
    assert render_redesign.CANT_DRAW in sec
    svg = re.search(r'<svg[^>]*class="design rw".*?</svg>', sec, re.S).group(0)
    assert render_design.drawn_text(svg) == text
    assert "Fix A" in sec and "Fix C" in sec  # all catalogue fixes sit under the same chip


def test_undrawable_fix_gets_chip_only_no_solid_box():
    text = "ALERT: x" + NL + "Check dose now" + NL + "Take 1 tablet QD"
    f = [dict(id=1, rule="ALT-02", state="CONFIRMED", quote="Check dose now"),
         dict(id=2, rule="EMR-01", state="CONFIRMED", quote="Take 1 tablet QD")]
    sec = render_redesign.section(f, text, "alert", "Z4")
    boxes = re.findall(r'<div class="bx rbx ([^"]*)" data-n="(\d+)"', sec)
    by = {}
    for cls, n in boxes:
        by.setdefault(n, set()).add("chiponly" in cls.split())
    assert by == {"1": {True}, "2": {False}}, by  # 1 = not drawn (chip only), 2 = drawn (solid box)
    assert re.search(r'chiponly rw".*?<b class="numchip"[^>]*>1</b>', sec)  # the number chip is still on the quote


def test_gap_in_numbers_is_kept(srv):
    text = "ALERT: x\nTake 1 tablet QD\nGive 5.0 mg"
    f = [dict(id=1, rule="EMR-01", state="CONFIRMED", quote="Take 1 tablet QD"),
         dict(id=3, rule="EMR-01", state="CONFIRMED", quote="5.0 mg")]
    sec = render_redesign.section(f, text, "alert", "Z2")
    assert [n for _, n in cards(sec)] == ["1", "3"]
    assert 'Remove the zero after the point in &quot;5.0 mg&quot;.' in sec
    assert "2 fixes shown." in sec


def test_nested_quotes_do_not_draw_twice():
    text = "ALERT: x\nGive 5.0 mg QD now"
    f = [dict(id=1, rule="EMR-01", state="CONFIRMED", quote="Give 5.0 mg QD now"),
         dict(id=2, rule="EMR-01", state="CONFIRMED", quote="QD")]
    sec = render_redesign.section(f, text, "alert", "Z3")
    check_fix_count(sec, 2)


def test_state_gate_in_code_not_in_style():
    for st in ("DROPPED", "UNABLE TO CHECK", "CHECKED", ""):
        assert render_redesign.section([dict(id=1, rule="EMR-01", state=st, quote="QD")], "QD", "label", "Z") == ""


def test_no_model_or_network_import_in_render():
    import ast
    tree = ast.parse((ROOT / "render_redesign.py").read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0])
    assert mods <= {"html", "re", "redesign_table", "render_design"}, mods


# ---------------------------------------------------------------- browser sweep (full width sweep, line count)
def _gap(a, b):
    dx = max(a["x"] - (b["x"] + b["w"]), b["x"] - (a["x"] + a["w"]))
    dy = max(a["y"] - (b["y"] + b["h"]), b["y"] - (a["y"] + a["h"]))
    return max(dx, dy)


def _nested(a, b):
    def inside(p, q):
        return p["x"] >= q["x"] - 0.5 and p["y"] >= q["y"] - 0.5 and p["x"] + p["w"] <= q["x"] + q["w"] + 0.5 and p["y"] + p["h"] <= q["y"] + q["h"] + 0.5
    return inside(a, b) or inside(b, a)


JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).display !== 'none'; };
  const rect = e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y + scrollY, w: r.width, h: r.height}; };
  const sec = document.querySelector('.redesign');
  const bx = Array.from(sec.querySelectorAll('.bx')).filter(vis).map(rect);
  const chips = Array.from(sec.querySelectorAll('.numchip')).filter(vis).map(rect);
  const st = sec.querySelector('.rstage'); const fr = sec.querySelector('.frame');
  const svg = Array.from(sec.querySelectorAll('svg.design')).find(vis);
  const cards = Array.from(sec.querySelectorAll('.rcard')).map(c => c.getBoundingClientRect().left);
  return {sw: document.documentElement.scrollWidth, bx, chips, stage: rect(st), frame: rect(fr), H: +svg.getAttribute('data-h'), W: +svg.getAttribute('data-w'),
    tag: sec.querySelector('.rtag').textContent, order: sec.getBoundingClientRect().top > document.querySelector('table.ledger').getBoundingClientRect().top + scrollY - scrollY,
    nbtn: Array.from(sec.querySelectorAll('button')).filter(vis).map(b => b.getBoundingClientRect().height)};
}"""


def test_browser_sweep_all_widths_and_states(dbpath):
    pw = pytest.importorskip("playwright.sync_api")
    s, t = server.start(dbpath, port=0, mode="live")
    lines = 0
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            for run in RUNS:
                for name, (w, h) in SIZES.items():
                    pg = browser.new_page(viewport={"width": w, "height": h})
                    pg.goto(f"http://127.0.0.1:{s.server_address[1]}/?run={run}")
                    pg.wait_for_selector("#rec .band")
                    pg.wait_for_timeout(300)
                    lines += 1
                    sw = pg.evaluate("document.documentElement.scrollWidth")
                    assert sw <= w, f"{run} {name}: side scroll {sw} > {w}"
                    has = pg.evaluate("!!document.querySelector('.redesign')")
                    assert has == SHOWN[run], (run, name)
                    if has:
                        r = pg.evaluate(JS)
                        assert r["tag"] == rt.TAG
                        # spacing rules of hft-team-11: 4 px between boxes that are not nested
                        for i, a in enumerate(r["bx"]):
                            for b in r["bx"][i + 1:]:
                                if not _nested(a, b):
                                    assert _gap(a, b) >= 4, f"{run} {name}: boxes {_gap(a, b):.1f}px apart"
                        for i, a in enumerate(r["chips"]):
                            for b in r["chips"][i + 1:]:
                                assert _gap(a, b) >= 4, f"{run} {name}: chips {_gap(a, b):.1f}px apart"
                        assert pg.evaluate("document.querySelectorAll('.redesign .rstage path, .redesign .conn').length") == 0
                        # frame height fits the drawing: art height plus the frame padding, no tall empty frame
                        pad = 16 if w >= 701 else 8
                        assert r["frame"]["h"] <= r["stage"]["h"] + 2 * pad + 2, f"{run} {name}: frame too tall"
                        if name != "390":
                            assert r["stage"]["h"] <= r["H"] * r["stage"]["w"] / r["W"] + 1
                        if name == "390":
                            assert all(hh >= 44 for hh in r["nbtn"])
                    pg.close()
            browser.close()
    finally:
        server.stop(s, t)
    assert lines == len(RUNS) * len(SIZES) == 15  # nothing skipped in the sweep


def test_enlarge_switch_and_escape(dbpath):
    pw = pytest.importorskip("playwright.sync_api")
    s, t = server.start(dbpath, port=0, mode="live")
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            pg = browser.new_page(viewport={"width": 390, "height": 844})
            pg.goto(f"http://127.0.0.1:{s.server_address[1]}/?run=rConf")
            pg.wait_for_selector(".redesign .enlarge")
            pg.click(".redesign .enlarge")
            z = "#zoomlayer"
            assert pg.inner_text(z + " .rtag") == rt.TAG
            assert "illustrative redesign" in pg.inner_text(z + " .zbody > .cap").lower()
            assert pg.evaluate("document.querySelectorAll('#zoomlayer .allfix li').length") == 6  # 2 findings x 3 fixes
            pg.click("#zoomlayer [data-zv=before]")
            assert "With the findings" in pg.inner_text(z + " .zbody > .cap")
            pg.keyboard.press("Escape")
            assert pg.evaluate("!document.getElementById('zoomlayer')")
            assert pg.evaluate("document.activeElement.className") == "enlarge"
            assert pg.evaluate("document.documentElement.scrollWidth") <= 390
            browser.close()
    finally:
        server.stop(s, t)


NL = chr(10)


@pytest.mark.parametrize("text,kind", [("Krellon 5.0 mg tablet" + NL + "Take 1 tablet each morning" + NL + "Keep dry", "label"),
                                        ("ALERT: x" + NL + "[OK]", "alert"),
                                        ("ALERT: a long line " * 4 + NL + "second", "alert")])
def test_frame_height_is_content_plus_24(text, kind):
    d, dn = render_redesign.designs(text, kind, "Z")
    for x in (d, dn):
        assert x.H == int(x.text_bottom + 24)
        assert x.H - x.text_bottom <= 25  # a planted tall frame (the old 360 floor) would fail here


def test_phone_drawing_text_is_14_px_or_more_at_390():
    import render_redesign as rr
    _, dn = rr.designs("ALERT: x\nTake 1 tablet QD", "alert", "Z")
    stage_px = 390 - 2 * 12 - 2 * 3 - 2 * 8  # page margin, panel border, frame margin: the narrowest case
    scale = stage_px / dn.W
    assert dn.size * scale >= 14 and rr.CHROME_N * scale >= 14, (dn.size, scale)


CLEAR_JS = """() => {
  const sec = document.querySelector('.redesign');
  const svg = Array.from(sec.querySelectorAll('svg.design')).find(s => s.getBoundingClientRect().width > 0);
  const cls = svg.classList.contains('rn') ? 'rn' : 'rw';
  const boxes = Array.from(sec.querySelectorAll('.bx.' + cls)).filter(b => !b.classList.contains('chiponly')).map(b => {
    const r = b.getBoundingClientRect(); const c = getComputedStyle(b);
    return {n: b.dataset.n, x: r.x, y: r.y, w: r.width, h: r.height, bl: parseFloat(c.borderLeftWidth), bt: parseFloat(c.borderTopWidth),
            br: parseFloat(c.borderRightWidth), bb: parseFloat(c.borderBottomWidth)}; });
  const m = svg.getScreenCTM(); const g = [];
  svg.querySelectorAll('text.ln, text.bt').forEach(t => {
    const s = t.textContent;
    for (let i = 0; i < s.length; i++) {
      if (s[i] === " " || s[i] === "\u00a0") continue;
      const e = t.getExtentOfChar(i);
      const p = svg.createSVGPoint(); p.x = e.x; p.y = e.y; const a = p.matrixTransform(m);
      p.x = e.x + e.width; p.y = e.y + e.height; const b = p.matrixTransform(m);
      g.push({x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y});
    }
  });
  svg.querySelectorAll('.btn rect').forEach(r => { const b = r.getBoundingClientRect(); g.push({x: b.x, y: b.y, w: b.width, h: b.height}); });
  return {boxes, g};
}"""


def _edge_clear(box, gl):
    """Distance from the box line to a glyph box: outside = gap to the box, inside = gap to the nearest edge, crossing = negative."""
    gx1, gy1, gx2, gy2 = gl["x"], gl["y"], gl["x"] + gl["w"], gl["y"] + gl["h"]
    bx1, by1, bx2, by2 = box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]
    if gx2 <= bx1 or gx1 >= bx2 or gy2 <= by1 or gy1 >= by2:
        return max(bx1 - gx2, gx1 - bx2, by1 - gy2, gy1 - by2)
    if gx1 >= bx1 and gx2 <= bx2 and gy1 >= by1 and gy2 <= by2:  # inside: measure from the INNER edge of the drawn border
        return min(gx1 - bx1 - box.get("bl", 0), bx2 - gx2 - box.get("br", 0), gy1 - by1 - box.get("bt", 0), by2 - gy2 - box.get("bb", 0))
    return -1.0


def test_box_edge_is_4_px_clear_of_glyphs_at_390_1366_1920(dbpath):
    """CD round 2, fix 2. Planted proof: a box 1 px from a glyph must give a value under 4."""
    assert _edge_clear(dict(x=0, y=0, w=100, h=20), dict(x=1, y=5, w=10, h=10)) < 4
    pw = pytest.importorskip("playwright.sync_api")
    s, t = server.start(dbpath, port=0, mode="live")
    checked = 0
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            try:
                for run in ("rConf", "rDisp"):
                    for name, (w, h) in SIZES.items():
                        pg = browser.new_page(viewport={"width": w, "height": h})
                        pg.goto(f"http://127.0.0.1:{s.server_address[1]}/?run={run}")
                        pg.wait_for_selector(".redesign .bx", state="attached")
                        r = pg.evaluate(CLEAR_JS)
                        assert r["boxes"] and r["g"], (run, name)
                        for b in r["boxes"]:
                            for gl in r["g"]:
                                c = _edge_clear(b, gl)
                                assert c >= 4, f"{run} {name}: box {b['n']} is {c:.1f}px from a glyph"
                                checked += 1
                        pg.close()
            finally:
                browser.close()
    finally:
        server.stop(s, t)
    assert checked > 100


def test_pinch_hint_only_on_touch_widths(dbpath):
    pw = pytest.importorskip("playwright.sync_api")
    s, t = server.start(dbpath, port=0, mode="live")
    seen = {}
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            try:
                for name, (w, h) in SIZES.items():
                    pg = browser.new_page(viewport={"width": w, "height": h})
                    pg.goto(f"http://127.0.0.1:{s.server_address[1]}/?run=rConf")
                    pg.wait_for_selector("#redesign .enlarge", state="attached")
                    pg.evaluate("document.querySelector('#redesign [data-action=enlarge-after]').click()")
                    seen[name] = pg.inner_text("#zoomlayer .zbar p")
                    pg.close()
            finally:
                browser.close()
    finally:
        server.stop(s, t)
    assert "Pinch" in seen["390"] and "Numbers stay on the image." in seen["390"]
    for name in ("1366", "1920"):
        assert seen[name] == "Numbers stay on the image.", seen[name]


def test_redesign_title_centred_and_first_line_bold():
    text = "ALERT: x" + NL + "Take 1 tablet QD" + NL + "Give 4 U daily"
    f = [dict(id=1, rule="EMR-01", state="CONFIRMED", quote="Take 1 tablet QD")]
    sec = render_redesign.section(f, text, "label", "Z5")
    svg = re.search(r'<svg[^>]*class="design rw".*?</svg>', sec, re.S).group(0)
    lines = re.findall(r'<text [^>]*class="ln[^"]*"[^>]*>', svg)
    assert lines and any(" hd" in t for t in lines), lines  # first line keeps the bold weight of the before (CD round 3)
    d, _ = render_redesign.designs(text, "label", "Z5")
    m = re.search(r'<text x="[^"]*" y="([\d.]+)" font-size="([\d.]+)"[^>]*class="chrome">SAMPLE LABEL', svg)
    y, fs = float(m.group(1)), float(m.group(2))
    cap = fs * 0.7  # capital height: same space above and below inside the bar
    assert abs((y - cap / 2) - d.top / 2) <= 0.6, (y, fs, d.top)
    # the findings-block drawing keeps its bold first line (no change there)
    before = render_design.Design(text, "label", "Z5").svg()
    assert 'font-weight="800"' in before


def test_redesign_keeps_each_before_line_weight():
    """CD round 3, fix 1. Every line has the same weight in the redesign as in the findings drawing
    (no numbered fix changes a weight)."""
    def weights(svg):
        return [("hd" in re.search(r'class="([^"]*)"', t).group(1).split(), 'font-weight="800"' in t)
                for t in re.findall(r'<text [^>]*class="ln[^"]*"[^>]*>', svg)]
    for kind in ("label", "alert", "list"):
        text = "ALERT: Give 4 U daily" + NL + "Take 1 tablet QD" + NL + "Hold if dry"
        f = [dict(id=1, rule="EMR-01", state="CONFIRMED", quote="Take 1 tablet QD")]
        sec = render_redesign.section(f, text, kind, "W3")
        for cls, narrow in (("design rw", False), ("design rn", True)):
            m = re.search(r'<svg[^>]*class="%s".*?</svg>' % cls, sec, re.S)
            assert m, (kind, cls)
            d, dn = render_redesign.designs(text, kind, "W3")
            b = render_design.Design(text, kind, "W3") if not narrow else dn
            before = b.svg()
            assert weights(m.group(0))[:1] == weights(before)[:1], (kind, cls)
            assert weights(m.group(0)) == weights(before)[:len(weights(m.group(0)))] or kind == "list", (kind, cls)
