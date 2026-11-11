"""Also: hover_1366, enlarge_390, mid_replay_1920 (box appears), nested_1920 (fixture C2).
Make the screenshots of the five end states at 1920x1080, 1366x768 and 390 px, and check the 24 px floor.

Needs playwright and the Edge browser already on this computer. Starts two local servers (127.0.0.1,
port 0) and closes them at the end. REPLAY of the logged pilot runs; DISPUTED has no pilot run, so it
comes from a made-up fixture log built in a temp folder (file name says "fixture").
Run:  python docs/screens/make_screens.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import live_fixtures  # noqa: E402
import log  # noqa: E402
import server  # noqa: E402

OUT = Path(__file__).resolve().parent
PILOT = ROOT / "pilot" / "audit_log_pilot.sqlite"
SIZES = {"1920": (1920, 1080), "1366": (1366, 768), "390": (390, 844)}
# state -> (source, run id)
# Each example is a true one under today's referee.py: CONFIRMED = QD inside "Take 1 tablet QD" (fixture),
# DISPUTED = pilot P08 (the [OK] hit is outside the quoted alert line).
STATES = {"confirmed": ("pilot", "run0003"), "disputed": ("pilot", "run0008"), "dropped": ("pilot", "run0019"),
          "unable": ("pilot", "run0017"), "checked": ("pilot", "run0014")}

FLOOR_JS = """() => {
  const bad = [];
  let min = 999;
  for (const el of document.querySelectorAll('body *')) {
    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3 && n.textContent.trim()).length;
    if (!own) continue;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || cs.visibility === 'hidden' || cs.display === 'none' || cs.opacity === '0') continue;
    if (el.closest('.drawer:not([open]) dl')) continue;
    const px = parseFloat(cs.fontSize);
    min = Math.min(min, px);
    if (px < 24) bad.push(el.tagName + '.' + el.className + ' ' + px + 'px: ' + el.textContent.trim().slice(0, 30));
  }
  return {min, bad};
}"""


def shot_sec(page, path, pad=16):
    """Shoot the redesign section with 16 px of page round it, so no border is cut (the element shot clipped the card border)."""
    r = page.evaluate("(()=>{const e=document.querySelector('#redesign').getBoundingClientRect();return {x:e.x+scrollX,y:e.y+scrollY,w:e.width,h:e.height,W:document.documentElement.scrollWidth}})()")
    x = max(0, r["x"] - pad)
    page.screenshot(path=str(path), full_page=True,
                    clip={"x": x, "y": max(0, r["y"] - pad), "width": min(r["W"] - x, r["w"] + 2 * pad), "height": r["h"] + 2 * pad})


def main():
    from playwright.sync_api import sync_playwright
    tmp = Path(tempfile.mkdtemp(prefix="hft_fixture_"))
    fx = tmp / "fixture.sqlite"
    con = log.open_db(str(fx))
    live_fixtures.build(con)
    # DISPUTED-only case: one disputed finding and no code-only row, so no fix is drawn and no card says CONFIRMED
    live_fixtures._run(con, "rDispOnly", "C9", kind="alert", reader=live_fixtures.TEXT_PLAIN,
                       proposals=[live_fixtures.prop("F001", "ALT-03", live_fixtures.Q2)],
                       final=dict(state="DISPUTED", dropped=[], findings=[dict(
                           quote=live_fixtures.Q2, rule_id="ALT-03", state="DISPUTED",
                           reason="model and regex rule disagree (regex hit is not inside the quote)")]))
    con.close()
    servers = {"pilot": server.start(str(PILOT), port=0, mode="replay"),
               "fixture": server.start(str(fx), port=0, mode="replay")}
    report = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge")
            for state, (src, run) in STATES.items():
                port = servers[src][0].server_address[1]
                for name, (w, h) in SIZES.items():
                    page = browser.new_page(viewport={"width": w, "height": h})
                    page.goto(f"http://127.0.0.1:{port}/?run={run}&upto=99&speed=30")
                    page.wait_for_selector("#rec .band")
                    page.wait_for_timeout(3800)  # highlight fade ends; the dropped list folds itself after 3 s
                    shot = OUT / f"{state}_{name}.png"
                    page.screenshot(path=str(shot), full_page=(name == "390"))
                    if name == "390":
                        y = page.evaluate("(()=>{const l=Array.from(document.querySelectorAll('.bx.dn .tg .w,.badge,.unable h2,.panel .under')).filter(e=>e.getBoundingClientRect().width).map(e=>Math.round(e.getBoundingClientRect().bottom+scrollY));return l.length?Math.min(...l):null})()")
                        report.append(f"{state} 390: first state word bottom at {y} px (must be under 844)")
                    if name == "1920":
                        res = page.evaluate(FLOOR_JS)
                        band = page.evaluate("document.querySelector('.band').getBoundingClientRect().height")
                        rows = page.evaluate("Array.from(document.querySelectorAll('table.ledger tbody tr')).map(r=>Math.round(r.getBoundingClientRect().bottom))")
                        report.append(f"{state} 1920: band {band:.0f} px; row bottoms {rows}; smallest text {res['min']} px; under 24 px: {res['bad'][:5]}")
                    page.close()
            # hover state: P05 pick list at 1366, row 1 hovered (teal box, other boxes at 55%)
            port = servers["pilot"][0].server_address[1]
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.goto(f"http://127.0.0.1:{port}/?run=run0005&upto=99&speed=30&nofold")
            page.wait_for_selector(".bx")
            page.hover("tr[data-n='1']")
            page.screenshot(path=str(OUT / "hover_1366.png"))
            page.close()
            # enlarge view at 390: P08
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(f"http://127.0.0.1:{port}/?run=run0008&upto=99&speed=30&nofold")
            page.wait_for_selector(".enlarge")
            page.click(".enlarge")
            page.screenshot(path=str(OUT / "enlarge_390.png"))
            page.close()
            # mid-replay: the referee tick with box 1 landed (KEPT wash on row 1), box 2 not drawn yet. 1920
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(f"http://127.0.0.1:{port}/?run=run0008&upto=6&show=1&speed=30&nofold")
            page.wait_for_selector(".bx.dw")
            page.wait_for_timeout(400)
            page.screenshot(path=str(OUT / "mid_replay_1920.png"))
            page.close()
            # nested boxes: fixture C2 (rConf), 1920
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(f"http://127.0.0.1:{servers['fixture'][0].server_address[1]}/?run=rConf&upto=99&speed=30&nofold")
            page.wait_for_selector(".bx.dw")
            page.wait_for_timeout(600)
            page.screenshot(path=str(OUT / "nested_1920.png"))
            page.close()
            # hft-team-14: illustrative redesign, 4 states x 3 sizes (+ C2 nested, enlarge After and Before, grey copy)
            for state, (src, run) in {"confirmed": ("pilot", "run0003"), "disputed": ("pilot", "run0008"),
                                      "checked": ("pilot", "run0014"), "unable": ("pilot", "run0017")}.items():
                port = servers[src][0].server_address[1]
                for name, (w, h) in SIZES.items():
                    page = browser.new_page(viewport={"width": w, "height": h})
                    page.goto(f"http://127.0.0.1:{port}/?run={run}&upto=99&speed=30&nofold")
                    page.wait_for_selector("#rec .band")
                    page.wait_for_timeout(3800)
                    sec = page.query_selector("#redesign")
                    shot = OUT / f"redesign_{state}_{name}.png"
                    if sec:
                        shot_sec(page, shot)
                        n_cards = page.evaluate("document.querySelectorAll('.rcard').length")
                        sw = page.evaluate("document.documentElement.scrollWidth")
                        report.append(f"redesign {state} {name}: cards {n_cards}; scrollWidth {sw} (width {w})")
                        if state == "disputed" and name == "1920":  # real grey copy: the browser removes all colour
                            page.add_style_tag(content="html{filter:grayscale(1)}")
                            shot_sec(page, OUT / "redesign_disputed_1920_grey.png")
                        if state == "disputed" and name == "1366":  # selected card: its box is teal, the other chips go to 55%
                            page.click(".rcard[data-n='2']")
                            page.wait_for_timeout(300)
                            shot_sec(page, OUT / "redesign_selected_1366.png")
                    else:
                        page.screenshot(path=str(shot), full_page=(name == "390"))
                        report.append(f"redesign {state} {name}: no redesign section (as it must be)")
                    page.close()
            port = servers["fixture"][0].server_address[1]
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(f"http://127.0.0.1:{port}/?run=rConf&upto=99&speed=30&nofold")
            page.wait_for_selector("#redesign")
            shot_sec(page, OUT / "redesign_c2_1920.png")
            page.close()
            # harness shots: same fixture run, the section drawn with a changed finding list (no log path gives these two cases)
            import render_redesign
            real = render_redesign.section
            for tag, edit in (("gap_1_3", lambda f: dict(f, id=3) if f["id"] == 2 else f),
                              ("cannot_draw", lambda f: dict(f, rule="ALT-02") if f["id"] == 2 else f)):
                render_redesign.section = lambda fs, *a, _e=edit, **k: real([_e(f) for f in fs], *a, **k)
                try:
                    page = browser.new_page(viewport={"width": 1920, "height": 1080})
                    page.goto(f"http://127.0.0.1:{port}/?run=rConf&upto=99&speed=30&nofold")
                    page.wait_for_selector("#redesign")
                    shot_sec(page, OUT / f"redesign_{tag}_1920_harness.png")  # internal proof only: never on a public page or in a post
                    page.close()
                finally:
                    render_redesign.section = real
            # DISPUTED-only case (fixture rDisp): no fix drawn, only "A human must decide."
            for name in ("1920", "390"):
                w, h = SIZES[name]
                page = browser.new_page(viewport={"width": w, "height": h})
                page.goto(f"http://127.0.0.1:{port}/?run=rDispOnly&upto=99&speed=30&nofold")
                page.wait_for_selector("#redesign")
                shot_sec(page, OUT / f"redesign_disputed_only_{name}.png")
                page.close()
            for name, (w, h) in (("1920", SIZES["1920"]), ("390", SIZES["390"])):
                page = browser.new_page(viewport={"width": w, "height": h})
                page.goto(f"http://127.0.0.1:{servers['pilot'][0].server_address[1]}/?run=run0008&upto=99&speed=30&nofold")
                page.wait_for_selector("#redesign .enlarge", state="attached")
                page.evaluate("document.querySelector('#redesign .enlarge').removeAttribute('style')")
                page.evaluate("document.querySelector('#redesign [data-action=enlarge-after]').click()")
                page.screenshot(path=str(OUT / f"redesign_enlarge_after_{name}.png"))
                page.click("#zoomlayer [data-zv=before]")
                page.screenshot(path=str(OUT / f"redesign_enlarge_before_{name}.png"))
                page.close()
            # benchmark: the old placeholder page, same laptop size
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.goto((OUT / "benchmark_old_index.html").as_uri())
            page.screenshot(path=str(OUT / "benchmark_old_1366.png"))
            page.close()
            browser.close()
    finally:
        for srv, t in servers.values():
            server.stop(srv, t)
    print("\n".join(report))


if __name__ == "__main__":
    main()
