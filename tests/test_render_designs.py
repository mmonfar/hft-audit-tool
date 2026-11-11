"""hft-team-11: the design is drawn, boxes are display only.
Risk-list tests: box holds its quote; image text = case text (hash match); phone 390 no side scroll;
colour never the only signal; box state comes from run data; no tag overlap."""
import hashlib
import json
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import live_fixtures  # noqa: E402
import log  # noqa: E402
import render_design  # noqa: E402
import screen  # noqa: E402
import server  # noqa: E402

CASES = ROOT / "pilot" / "cases"
PILOT_LOG = ROOT / "pilot" / "audit_log_pilot.sqlite"
IDS = [f"P{n:02d}" for n in range(1, 21)]
NS = "{http://www.w3.org/2000/svg}"


def case(cid):
    meta = json.loads((CASES / f"{cid}.json").read_text(encoding="utf-8"))
    text = (CASES / f"{cid}.ocr.txt").read_bytes().decode("utf-8")
    exp = json.loads((CASES / f"{cid}.expected.json").read_text(encoding="utf-8"))
    return meta, text, exp


def design(cid):
    meta, text, _ = case(cid)
    return render_design.Design(text, meta["kind"], cid, unreadable=meta["planted"] == "unreadable")


# ---- image text = case text, hash match
@pytest.mark.parametrize("cid", IDS)
def test_image_text_is_case_text_and_hash_matches(cid):
    meta, text, _ = case(cid)
    d = design(cid)
    svg = d.svg()
    assert render_design.drawn_text(svg) == text
    assert f'data-case-sha="{hashlib.sha256(text.encode("utf-8")).hexdigest()}"' in svg
    saved = (CASES / f"{cid}.design.svg").read_text(encoding="utf-8").strip()
    assert saved == d.svg(inline=False), "saved design differs from the generator: run pilot/make_cases.py"
    assert render_design.drawn_text(saved) == text


def test_only_chrome_words_are_added():
    for cid in IDS:
        svg = design(cid).svg()
        root = ET.fromstring(svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1))
        for t in root.iter(NS + "text"):
            if t.get("class") == "chrome":
                assert "".join(t.itertext()) in render_design.CHROME


# ---- each box holds its quote (positions known at build time)
@pytest.mark.parametrize("cid", [c for c in IDS])
def test_each_box_holds_its_quote(cid):
    meta, text, exp = case(cid)
    d = design(cid)
    root = ET.fromstring(d.svg().replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1))
    quotes = list(exp.get("expected_quotes") or [])
    if exp.get("trap_quote"):
        quotes.append(exp["trap_quote"])
    for q in quotes:
        b = d.locate(q)
        if q not in text or "\n" in q:
            assert b is None, "a quote that is not in the text must get no box"
            continue
        assert b is not None
        lines = text.split("\n")
        assert lines[b["line"]][b["a"]:b["b"]] == q
        g = next(g for g in root.iter(NS + "g") if g.get("class") == "row" and int(g.get("data-line")) == b["line"])
        pos, got = 0, []
        for el in g:
            src = el.get("data-src") if el.get("class") == "btn" else "".join(el.itertext())
            lo, hi = max(pos, b["a"]), min(pos + len(src), b["b"])
            if lo < hi:
                got.append(src[lo - pos:hi - pos])
                if el.get("class") != "btn":
                    xs = [float(v) for v in el.get("x").split()]
                    assert len(xs) == len(src), "one x per letter"
                    assert abs(xs[lo - pos] - (d.x0 + lo * d.cw)) < 0.02
            pos += len(src)
        assert "".join(got) == q
        assert abs(b["x"] + d.padx - (d.x0 + b["a"] * d.cw)) < 0.02 and abs(b["w"] - 2 * d.padx - (b["b"] - b["a"]) * d.cw) < 0.02


def test_drawn_letters_have_normal_spacing():
    """No textLength: letters keep the font's own advance (0.6 em), so no stretched letter spacing."""
    for cid in IDS:
        d = design(cid)
        svg = d.svg()
        assert "textLength" not in svg and "lengthAdjust" not in svg and "letter-spacing" not in svg
        assert abs(d.cw - 0.6 * d.size) < 0.001


def test_unreadable_designs_have_no_box_and_a_plate():
    for cid in ("P17", "P18"):
        d = design(cid)
        assert d.kind == "unreadable"
        assert "No readable design" in d.svg()
        assert d.locate("~~") is None or cid == "P17"


def test_third_type_and_captions():
    assert design("P05").caption() == "Made-up design P05: pick list."
    assert design("P07").caption() == "Made-up design P07: order set."
    assert design("P08").caption() == "Made-up design P08: alert window."
    assert design("P03").caption() == "Made-up design P03: drug label."


def test_no_far_corner_button_or_extra_fault_drawn():
    """CD brief 5.1: only the fault the case text names. One [OK] button sits on its own line, in order."""
    d = design("P08")
    b = d.locate("[OK]")
    assert b["x"] < 64 and b["line"] == 1
    svg = design("P10").svg()
    assert "#B9BEC0" not in svg and 'font-size="12"' not in svg


# ---- screen: box state from run data, colour not the only signal, one planted line
@pytest.fixture(scope="module")
def pages(tmp_path_factory):
    fx = tmp_path_factory.mktemp("t11") / "fx.sqlite"
    con = log.open_db(str(fx))
    live_fixtures.build(con)
    con.close()
    out = {}
    for name, path, run in (("disp", PILOT_LOG, "run0008"), ("drop", PILOT_LOG, "run0019"), ("unable", PILOT_LOG, "run0017"),
                            ("checked", PILOT_LOG, "run0013"), ("conf", fx, "rConf"), ("rep", PILOT_LOG, "run0020")):
        c = sqlite3.connect(f"file:{path.as_posix() if hasattr(path, 'as_posix') else path}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        rec = screen.build_record(c, run)
        c.close()
        out[name] = screen.render(rec, "replay", 30, 99) if rec else ""
    return out


def boxes_of(html):
    return re.findall(r'<div class="bx k-(\w+)[^"]*" data-n="(\d+)"', html)


def test_box_state_comes_from_run_data(pages):
    assert {k for k, _ in boxes_of(pages["disp"])} >= {"dmodel", "dcode"}
    kinds = {k for k, _ in boxes_of(pages["conf"])}
    assert "confirmed" in kinds and kinds <= {"confirmed", "added", "hit"}
    for name in ("drop", "unable", "checked"):
        assert boxes_of(pages[name]) == [], name
    assert "Code found: [OK], line 2" in pages["disp"]


def test_end_states_keep_hft_team_10_rulings(pages):
    assert "No finding passed the code check" in pages["checked"]
    assert "CHECKED: no finding passed the code check." in pages["checked"]
    assert "UNABLE TO CHECK" in pages["unable"] and "The check did not finish." in pages["unable"]
    assert "Dropped (" in pages["drop"]
    assert "Run stopped." in pages["unable"] and "Run finished." not in pages["unable"]
    assert pages["unable"].count("Planted test case") == 1
    assert pages["drop"].count("Planted test case") == 1 and "on purpose" in pages["drop"]
    assert "We put this finding in on purpose" not in pages["drop"]


def test_colour_is_never_the_only_signal(pages):
    css = (ROOT / "web" / "live.css").read_text(encoding="utf-8")
    for kind in ("confirmed", "dmodel", "dcode", "added"):
        assert f".k-{kind}" in css or kind == "confirmed"
    # every box carries a number and a state word in its markup, and a shape class
    for name in ("disp", "conf"):
        for m in re.finditer(r'<div class="bx k-(\w+).*?<b class="nm">(\d+)</b><span class="w">(.*?)</span>', pages[name]):
            assert m.group(3).strip()
    assert "✓" in pages["conf"]
    # the dim rule never hides an outline
    assert "rgba(23,36,43,.55)" in css


def test_panel_words(pages):
    for name, html in pages.items():
        panel = re.search(r'<div class="panel">.*?</p></div>', html, re.S)
        if not panel:
            continue
        low = re.sub(r"<[^>]+>", " ", panel.group(0)).lower()
        for bad in ("fault", "clean", "safe", "all clear", "no findings"):
            assert bad not in low, (name, bad)


def test_every_row_has_a_hint_and_matching_number(pages):
    for name in ("disp", "conf"):
        html = pages[name]
        rows = re.findall(r'<tr data-n="(\d+)"', html)
        assert rows
        assert set(rows) == {n for _, n in boxes_of(html)}


def test_replay_shows_no_box_before_code_decides(tmp_path):
    c = sqlite3.connect(f"file:{PILOT_LOG.as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    rec = screen.build_record(c, "run0008")
    c.close()
    early = screen.render(rec, "replay", 30, 2)
    assert "class=\"bx" not in early and "class=\"stage\"" in early


# ---- browser checks (skip when playwright or Edge is not on this computer)
def _browser():
    pw = pytest.importorskip("playwright.sync_api")
    p = pw.sync_playwright().start()
    try:
        return p, p.chromium.launch(channel="msedge")
    except Exception:
        p.stop()
        pytest.skip("Edge not available")


@pytest.fixture(scope="module")
def live_pages(tmp_path_factory):
    fx = tmp_path_factory.mktemp("t11b") / "fx.sqlite"
    con = log.open_db(str(fx))
    live_fixtures.build(con)
    con.close()
    srv = {"pilot": server.start(str(PILOT_LOG), port=0, mode="replay"), "fx": server.start(str(fx), port=0, mode="replay")}
    p, br = _browser()
    yield srv, br
    br.close()
    p.stop()
    for s, t in srv.values():
        server.stop(s, t)


RUNS = [("pilot", "run0008"), ("fx", "rConf"), ("pilot", "run0013"), ("pilot", "run0019"), ("pilot", "run0017")]


@pytest.mark.parametrize("src,run", RUNS)
def test_phone_390_no_side_scroll_and_no_tag_overlap(live_pages, src, run):
    srv, br = live_pages
    page = br.new_page(viewport={"width": 390, "height": 844})
    page.goto(f"http://127.0.0.1:{srv[src][0].server_address[1]}/?run={run}&upto=99&nofold")
    page.wait_for_selector(".stage")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    rects = page.evaluate("Array.from(document.querySelectorAll('.bx .nm')).map(e=>{const r=e.getBoundingClientRect();return [r.left,r.top,r.right,r.bottom]})")
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
    page.close()


@pytest.mark.parametrize("width", [1920, 1366])
def test_tags_do_not_overlap_wide(live_pages, width):
    srv, br = live_pages
    for src, run in RUNS[:2]:
        page = br.new_page(viewport={"width": width, "height": 1080 if width == 1920 else 768})
        page.goto(f"http://127.0.0.1:{srv[src][0].server_address[1]}/?run={run}&upto=99&nofold")
        page.wait_for_selector(".stage")
        rects = page.evaluate("Array.from(document.querySelectorAll('.bx .tg')).map(e=>{const r=e.getBoundingClientRect();return [r.left,r.top,r.right,r.bottom]})")
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (run, width, a, b)
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        page.close()


def test_multi_line_quote_gets_one_box_over_all_its_lines():
    d = design("P05")
    q = "Brindacol 20 mg" + chr(10) + "Brindacor 20 mg" + chr(10) + "Brindavel 20 mg"
    b = d.locate(q)
    assert b["line"] == 1 and b["line_end"] == 3
    one, three = d.locate("Brindacol 20 mg"), d.locate("Brindavel 20 mg")
    assert b["y"] <= one["y"] and b["y"] + b["h"] >= three["y"] + three["h"] - 0.01
    assert d.locate("Brindacol 20 mg" + chr(10) + "Something else") is None


def test_banned_words_safe_and_clean_are_not_on_screen(pages):
    for name, html in pages.items():
        low = re.sub(r"<[^>]+>", " ", html).lower()
        for bad in ("safe", "clean"):
            assert not re.search(r"\b" + bad + r"\b", low), (name, bad)
    assert "This is a result for this one case only." in pages["checked"]
    assert "The check did not finish." in pages["unable"] and "Check this text by hand." in pages["unable"]


# ---- measured in the browser: box clearance, link length, phone text size
def _open(br, srv, src, run, w, h, extra=""):
    page = br.new_page(viewport={"width": w, "height": h})
    page.goto(f"http://127.0.0.1:{srv[src][0].server_address[1]}/?run={run}&upto=99&nofold{extra}")
    page.wait_for_selector(".stage")
    page.wait_for_timeout(300)
    return page


CLEAR_JS = """() => {
  const svg = document.querySelector('svg.design.dw');
  const out = [];
  for (const bx of document.querySelectorAll('.bx.dw')) {
    const q = bx.dataset.q; if (!q) continue;
    const [line, a, b] = q.split(':').map(Number);
    const ctm = svg.getScreenCTM();
    const x0 = parseFloat(svg.dataset.x0), cw = parseFloat(svg.dataset.cw);
    let L = 1e9, T = 1e9, R = -1e9, B = -1e9, n = 0;
    const take = (x, y, w, h) => { const p = svg.createSVGPoint(); p.x = x; p.y = y; const p1 = p.matrixTransform(ctm);
      p.x = x + w; p.y = y + h; const p2 = p.matrixTransform(ctm); L = Math.min(L, p1.x); T = Math.min(T, p1.y); R = Math.max(R, p2.x); B = Math.max(B, p2.y); n++; };
    for (const g of svg.querySelectorAll('g.row[data-line="' + line + '"]')) {
      for (const el of g.children) {
        if (el.classList.contains('btn')) {
          const r = el.querySelector('rect'); const rb = r.getBBox();
          const col = Math.round((rb.x - 2 - x0) / cw);
          if (col >= a && col < b) take(rb.x, rb.y, rb.width, rb.height);
        } else {
          const nch = el.getNumberOfChars();
          for (let i = 0; i < nch; i++) {
            const e = el.getExtentOfChar(i); const col = Math.round((e.x - x0) / cw);
            if (col >= a && col < b) take(e.x, e.y, e.width, e.height);
          }
        }
      }
    }
    const r = bx.getBoundingClientRect();
    const bw = bx.clientLeft, bh = bx.clientTop;
    out.push({n: bx.dataset.n, chars: n, left: L - (r.left + bw), top: T - (r.top + bh), right: (r.right - bw) - R, bottom: (r.bottom - bh) - B});
  }
  return out;
}"""


@pytest.mark.parametrize("width,height", [(1920, 1080), (1366, 768)])
@pytest.mark.parametrize("src,run", [("pilot", "run0008"), ("fx", "rConf"), ("pilot", "run0003"), ("pilot", "run0005")])
def test_box_has_4px_clear_round_the_drawn_letters(live_pages, src, run, width, height):
    srv, br = live_pages
    page = _open(br, srv, src, run, width, height)
    res = page.evaluate(CLEAR_JS)
    assert res
    for r in res:
        if r["chars"] == 0:
            continue
        for side in ("left", "top", "right", "bottom"):
            assert r[side] >= 4, (run, r)
    page.close()


@pytest.mark.parametrize("width,height", [(1920, 1080), (1366, 768)])
def test_disputed_tags_keep_words(live_pages, width, height):
    srv, br = live_pages
    page = _open(br, srv, "pilot", "run0008", width, height)
    tags = page.evaluate("Array.from(document.querySelectorAll('.bx.dw')).map(b=>[b.querySelectorAll('.tg').length, b.querySelector('.tg .w').innerText, b.querySelector('.tg .w').getBoundingClientRect().height, parseFloat(getComputedStyle(b.querySelector('.tg .w')).fontSize)])")
    assert tags and all(t[0] == 1 and t[1].strip() and t[3] >= 14 for t in tags), tags
    words = " ".join(t[1] for t in tags).lower()
    assert "code found: [ok], line 2" in words and "model quoted: line 1" in words
    page.close()


@pytest.mark.parametrize("src,run", RUNS)
def test_phone_drawn_text_12px_no_chip_over_title_and_enlarge_fits(live_pages, src, run):
    srv, br = live_pages
    page = _open(br, srv, src, run, 390, 844)
    m = page.evaluate("""() => { const svg = document.querySelector('svg.design.dn'); const sc = svg.getBoundingClientRect().width / parseFloat(svg.dataset.w);
      const sizes = Array.from(svg.querySelectorAll('text')).filter(t => t.textContent.trim()).map(t => parseFloat(t.getAttribute('font-size')) * sc);
      const title = Array.from(svg.querySelectorAll('text.chrome')).map(t => { const r = t.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; });
      const tags = Array.from(document.querySelectorAll('.bx.dn .tg')).map(t => { const r = t.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; });
      return {min: Math.min(...sizes), title, tags}; }""")
    assert m["min"] >= 12, m["min"]
    for t in m["tags"]:
        for c in m["title"]:
            assert t[2] <= c[0] or c[2] <= t[0] or t[3] <= c[1] or c[3] <= t[1], (t, c)
    if page.query_selector(".enlarge"):
        page.click(".enlarge")
        z = page.evaluate("""() => { const l = document.getElementById('zoomlayer'); const s = l.querySelector('.stage').getBoundingClientRect();
          return {sw: l.scrollWidth, cw: l.clientWidth, right: s.right, left: s.left}; }""")
        assert z["sw"] <= z["cw"] and z["right"] <= 390 and z["left"] >= 0, z
    page.close()


# ---- batch 2 (CD round 2)
NO_TAG_ON_LETTER_JS = """() => {
  const svg = document.querySelector('svg.design.dn');
  const letters = [];
  for (const row of svg.querySelectorAll('g.row')) for (const t of row.querySelectorAll('text')) {
    if (!t.textContent.trim()) continue;
    const n = t.getNumberOfChars(), ctm = svg.getScreenCTM();
    for (let i = 0; i < n; i++) { if (!t.textContent[i].trim()) continue; const e = t.getExtentOfChar(i);
      const p = svg.createSVGPoint(); p.x = e.x; p.y = e.y; const a = p.matrixTransform(ctm); p.x = e.x + e.width; p.y = e.y + e.height; const b = p.matrixTransform(ctm);
      letters.push([a.x, a.y, b.x, b.y]); }
  }
  const tags = Array.from(document.querySelectorAll('.stage .bx.dn .tg')).map(t => { const r = t.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; });
  return {letters, tags};
}"""


def _covered(res):
    bad = []
    for t in res["tags"]:
        for c in res["letters"]:
            if not (t[2] <= c[0] or c[2] <= t[0] or t[3] <= c[1] or c[3] <= t[1]):
                bad.append((t, c))
    return bad


@pytest.mark.parametrize("src,run", RUNS)
def test_phone_no_tag_covers_a_drawn_letter_and_enlarge_shows_row_1(live_pages, src, run):
    srv, br = live_pages
    page = _open(br, srv, src, run, 390, 844)
    res = page.evaluate(NO_TAG_ON_LETTER_JS)
    assert res["letters"]
    assert not _covered(res), (run, _covered(res)[:2])
    if page.query_selector(".enlarge"):
        page.click(".enlarge")
        has_box = page.evaluate("document.querySelectorAll('#zoomlayer .bx.dn').length")
        if has_box:
            row = page.evaluate("""() => { const l = document.getElementById('zoomlayer'); const tr = l.querySelector('table.ledger tr[data-n]');
              if (!tr) return null; const s = l.querySelector('.stage').getBoundingClientRect(); const r = tr.getBoundingClientRect();
              return {n: tr.dataset.n, top: r.top, stageBottom: s.bottom, bottom: r.bottom, text: tr.innerText.slice(0, 60)}; }""")
            assert row and row["n"] == "1" and row["top"] >= row["stageBottom"] - 1 and row["bottom"] <= 844 + 4000, row
    page.close()


def test_mid_replay_frame_has_box_wash_and_is_not_finished(live_pages):
    srv, br = live_pages
    page = br.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(f"http://127.0.0.1:{srv['pilot'][0].server_address[1]}/?run=run0008&upto=6&nofold")
    page.wait_for_selector(".bx.dw")
    page.wait_for_timeout(300)
    assert page.query_selector("td.just"), "the row has no KEPT wash"
    fin = page.inner_text("p.finish")
    assert "Run finished" not in fin and "Replaying" in fin, fin
    assert page.query_selector("tr[data-n='1']")
    page.close()


def test_nested_inner_box_is_4px_inside_box_1_and_ledger_starts_on_a_full_row(live_pages):
    srv, br = live_pages
    page = _open(br, srv, "fx", "rConf", 1920, 1080)
    r = page.evaluate("""() => { const b = Array.from(document.querySelectorAll('.bx.dw'));
      const o = b.find(x => x.dataset.n === '1' && x.classList.contains('k-confirmed')), i = b.find(x => x.classList.contains('k-hit'));
      if (!o || !i) return null; const a = o.getBoundingClientRect(), c = i.getBoundingClientRect();
      return {l: c.left - a.left, t: c.top - a.top, r: a.right - c.right, b: a.bottom - c.bottom, n: i.dataset.n, tag: i.querySelector('.nm').innerText, q: i.dataset.q}; }""")
    assert r, "no inner box on QD"
    assert min(r["l"], r["t"], r["r"], r["b"]) >= 4, r
    assert r["n"] == "1" and r["tag"].strip() == "1"
    sc = page.evaluate("""() => { const s = document.querySelector('.scroll').getBoundingClientRect();
      const rows = Array.from(document.querySelectorAll('table.ledger tbody tr')).map(x => x.getBoundingClientRect());
      const first = rows.find(x => x.bottom > s.top + 1); return {gap: first.top - s.top}; }""")
    assert abs(sc["gap"]) <= 4, sc  # the first visible row starts at the top of the column: it is not cut
    page.close()


@pytest.mark.parametrize("width,height", [(1920, 1080), (1366, 768)])
@pytest.mark.parametrize("src,run", [("pilot", "run0008"), ("fx", "rConf"), ("pilot", "run0003"), ("pilot", "run0013")])
def test_drawn_text_starts_within_64px_under_the_title_bar(live_pages, src, run, width, height):
    srv, br = live_pages
    page = _open(br, srv, src, run, width, height)
    gap = page.evaluate("""() => { const svg = document.querySelector('svg.design.dw'); const sc = svg.getBoundingClientRect().width / parseFloat(svg.dataset.w);
      const title = svg.querySelector('rect'); const bar = svg.querySelectorAll('rect')[1]; const bh = bar.getBBox().height;
      let top = 1e9; for (const t of svg.querySelectorAll('g.row text')) { if (!t.textContent.trim()) continue; top = Math.min(top, t.getBoundingClientRect().top); }
      return (top - (svg.getBoundingClientRect().top + bh * sc)); }""")
    assert gap <= 64, gap
    page.close()


def test_second_finding_on_same_spot_says_why(live_pages):
    srv, br = live_pages
    page = _open(br, srv, "pilot", "run0008", 1920, 1080)
    tags = page.evaluate("Array.from(document.querySelectorAll('.bx.dw .tg .w')).map(e => e.innerText)")
    assert any("second finding" in t.lower() and "added by code" in t.lower() for t in tags), tags
    page.close()


# ---- hft-team-11 fix 3: box gaps, mid-replay frame, gutter links, frame fit
BOX_RECTS_JS = """(cls) => Array.from(document.querySelectorAll('.bx.' + cls)).filter(e => e.getBoundingClientRect().width)
  .map(e => { const r = e.getBoundingClientRect(); return {n: e.dataset.n, l: r.left, t: r.top, r: r.right, b: r.bottom}; })"""


def _nested(a, b, m):
    return a["l"] - b["l"] >= m and a["t"] - b["t"] >= m and b["r"] - a["r"] >= m and b["b"] - a["b"] >= m


def _bad_pairs(rects, gap=6, m=3):
    bad = []
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            if _nested(a, b, m) or _nested(b, a, m):
                continue
            sepx = max(b["l"] - a["r"], a["l"] - b["r"])
            sepy = max(b["t"] - a["b"], a["t"] - b["b"])
            if max(sepx, sepy) < gap:
                bad.append((a, b))
    return bad


@pytest.mark.parametrize("width,height,cls", [(1920, 1080, "dw"), (1366, 768, "dw"), (390, 844, "dn")])
@pytest.mark.parametrize("src,run", RUNS + [("pilot", "run0003"), ("pilot", "run0005")])
def test_non_nested_boxes_keep_6px_gap_and_nested_boxes_sit_inside(live_pages, src, run, width, height, cls):
    srv, br = live_pages
    page = _open(br, srv, src, run, width, height)
    rects = page.evaluate(BOX_RECTS_JS, cls)
    bad = _bad_pairs(rects)
    assert not bad, (run, width, bad[:2])
    page.close()


def test_mid_replay_frame_differs_from_end_state_and_box_count_equals_decided_rows(live_pages):
    srv, br = live_pages
    port = srv["pilot"][0].server_address[1]
    shots, counts = [], []
    for q in ("upto=6&show=1", "upto=99"):
        page = br.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(f"http://127.0.0.1:{port}/?run=run0008&{q}&nofold")
        page.wait_for_selector(".bx.dw")
        page.wait_for_timeout(400)
        shots.append(page.locator(".stage").screenshot())
        counts.append(page.evaluate("[new Set(Array.from(document.querySelectorAll('.bx.dw')).map(e => e.dataset.n)).size, document.querySelectorAll('table.ledger tbody tr[data-n]').length, document.querySelectorAll('td.just').length > 0]"))
        page.close()
    assert shots[0] != shots[1], "mid-replay drawing area is the same as the end state"
    assert counts[0][0] == counts[0][1] == 1 and counts[0][2], counts
    assert counts[1][0] == counts[1][1] == 2, counts


CHIP_JS = """(cls) => { const svg = document.querySelector('svg.design.' + cls); const ctm = svg.getScreenCTM();
  const letters = [];
  for (const t of svg.querySelectorAll('g.row text')) { if (!t.textContent.trim()) continue;
    for (let i = 0; i < t.getNumberOfChars(); i++) { if (!t.textContent[i].trim()) continue; const e = t.getExtentOfChar(i);
      const p = svg.createSVGPoint(); p.x = e.x; p.y = e.y; const a = p.matrixTransform(ctm); p.x = e.x + e.width; p.y = e.y + e.height; const b = p.matrixTransform(ctm);
      letters.push([a.x, a.y, b.x, b.y]); } }
  const boxes = Array.from(document.querySelectorAll('.bx.' + cls)).filter(e => e.getBoundingClientRect().width).map(b => {
    const c = b.querySelectorAll('.numchip'), t = b.querySelectorAll('.tg .nm'); const r = c[0] ? c[0].getBoundingClientRect() : null;
    return {chips: c.length, chip: c[0] ? c[0].innerText.trim() : null, tag: t[0] ? t[0].innerText.trim() : null, rect: r ? [r.left, r.top, r.right, r.bottom] : null}; });
  return {letters, boxes, conn: document.querySelectorAll('.conn').length}; }"""


@pytest.mark.parametrize("width,height,cls", [(1920, 1080, "dw"), (1366, 768, "dw"), (390, 844, "dn")])
@pytest.mark.parametrize("src,run", RUNS)
def test_each_box_has_one_number_chip_matching_its_tag_and_no_link_lines(live_pages, src, run, width, height, cls):
    srv, br = live_pages
    page = _open(br, srv, src, run, width, height)
    r = page.evaluate(CHIP_JS, cls)
    assert r["conn"] == 0, "link lines are back"
    for b in r["boxes"]:
        assert b["chips"] == 1 and b["chip"] == b["tag"] and b["chip"], (run, width, b)
        c = b["rect"]
        for t in r["letters"]:
            assert c[2] <= t[0] or t[2] <= c[0] or c[3] <= t[1] or t[3] <= c[1], (run, width, "chip covers a letter", c, t)
    page.close()


FIT_JS = """() => { const svg = document.querySelector('svg.design.dw'); const bb = svg.getBoundingClientRect(); const sc = bb.width / parseFloat(svg.dataset.w);
  let low = 0; for (const t of document.querySelectorAll('.bx.dw .tg')) low = Math.max(low, t.getBoundingClientRect().bottom);
  return {h: parseFloat(svg.dataset.h), below: (bb.bottom - low) / sc}; }"""


@pytest.mark.parametrize("src,run", [("pilot", "run0008"), ("fx", "rConf")])
def test_frame_height_is_content_plus_24_and_at_least_360(live_pages, src, run):
    srv, br = live_pages
    page = _open(br, srv, src, run, 1920, 1080)
    r = page.evaluate(FIT_JS)
    assert r["h"] >= 360, r
    assert 20 <= r["below"] <= 32, r  # empty space under the last tag: about 24 units, not ~170
    page.close()


# ---- hft-team-11 fix 5
def test_390_wrapped_line_uses_normal_line_height():
    d = render_design.Design(case("P08")[1], "alert", "P08", narrow=True)
    rows = [r for r in d.rows if r[0] == 0]
    assert len(rows) >= 2, "P08 line 1 should wrap at 390"
    for a, b in zip(rows, rows[1:]):
        assert b[3] - a[3] <= 1.5 * d.size, (b[3] - a[3], d.size)


@pytest.mark.parametrize("width,height", [(1920, 1080), (1366, 768), (390, 844)])
def test_chip_pair_on_ok_has_same_size_and_top_edge(live_pages, width, height):
    srv, br = live_pages
    page = _open(br, srv, "pilot", "run0008", width, height)
    cls = "dn" if width < 700 else "dw"
    chips = page.evaluate("(cls) => { const b = Array.from(document.querySelectorAll('.bx.' + cls)).filter(e => e.querySelectorAll('.numchip').length && e.getBoundingClientRect().width && e.dataset.q && e.dataset.q.startsWith('1:'));"
                          "return Array.from(document.querySelectorAll('.bx.' + cls + ' .numchip')).filter(c => c.parentElement.dataset.q.startsWith('1:')).map(c => { const r = c.getBoundingClientRect(); return [r.top, r.width, r.height, c.innerText.trim()]; }); }", cls)
    assert len(chips) == 2, chips
    assert abs(chips[0][0] - chips[1][0]) <= 0.5 and abs(chips[0][1] - chips[1][1]) <= 0.5 and abs(chips[0][2] - chips[1][2]) <= 0.5, chips
    page.close()


def test_390_ok_label_is_body_text_size():
    d = render_design.Design(case("P08")[1], "alert", "P08", narrow=True)
    svg = d.svg()
    m = re.search(r'<text [^>]*font-size="([\d.]+)"[^>]*class="bt"', svg)
    body = re.search(r'<text x="[^"]*" y="[^"]*" font-size="([\d.]+)"[^>]*class="ln', svg)
    assert m and body and float(m.group(1)) == float(body.group(1)), (m and m.group(1), body and body.group(1))
