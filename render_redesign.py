"""Illustrative redesign section for the live record screen (spec: docs/specs/redesign.md).

Rules (CD brief, hft-team-14):
- Shown after the findings, never beside them. CONFIRMED findings only get a fix. DISPUTED shows
  "A human must decide." and no fix. Every other state shows nothing.
- Fix text comes from redesign_table only (fixed words, quote slot). Drawn words are case text or fixed table words.
- The number of a fix is the finding id. No recount. No link lines. No extra mark on the chip.
- No model, no network. Standard library plus the made-up design drawer.
"""
import html
import re

import redesign_table as rt
import render_design

# Words that must never reach the screen (CD brief section 4). Whole words, any case.
BANNED = ("recommended", "better", "approved")
INTRO = "Next: the same design, changed only where code confirmed a problem (illustrative)"
LEGEND = "Numbers on the image = numbers in the list = numbers in the findings above."
NOTHING = "No fix to show for this case. Findings that need a person stay above."
CANT_DRAW = "This fix cannot be drawn. Read it in the list."
PHONE_W, PHONE_SIZE = 340, 15  # phone drawing: stage is about 346 px wide at 390, so drawn text is 14 px or more
CHROME_W, CHROME_N = 21, 14.5  # title-bar words: 16 px or more at 1366 (scale 0.775) and 14 px or more at 390
OTHER = "Other option, not drawn"
SHOWN = "Shown on the image"


def esc(s):
    return html.escape(str(s), quote=True)


def _pct(v, whole):
    return f"{v / whole * 100:.3f}%"


def plan(findings, text):
    """What to draw. Returns (new_text, items). One item per finding, in finding order.

    item: n, rule, state, quote, new (drawn text or None), at (index in new_text of the spot or None).
    Drawn words come from redesign_table.draw_for only. Overlapping spots are not drawn twice.
    """
    text = text or ""
    items = []
    spans = []
    for f in findings:
        it = dict(n=f["id"], rule=f["rule"], state=f["state"], quote=f.get("quote") or "", new=None, at=None, i0=None)
        if it["quote"]:
            it["i0"] = text.find(it["quote"])
        items.append(it)
        if f["state"] == "CONFIRMED" and it["i0"] is not None and it["i0"] >= 0:
            new = rt.draw_for(f["rule"], it["quote"])
            if new is not None and new != it["quote"]:
                s, e = it["i0"], it["i0"] + len(it["quote"])
                if all(e <= a or s >= b for a, b, _ in spans):
                    spans.append((s, e, new))
                    it["new"] = new
    spans.sort()
    out, pos, delta = [], 0, 0
    starts = {}
    for s, e, new in spans:
        out.append(text[pos:s])
        starts[s] = (sum(len(x) for x in out), new)
        out.append(new)
        pos = e
    out.append(text[pos:])
    new_text = "".join(out)
    for it in items:
        i0 = it["i0"]
        if i0 is None or i0 < 0:
            continue
        if it["new"] is not None:
            it["at"] = starts[i0][0]
            continue
        shift = 0
        for s, e, new in spans:
            if e <= i0:
                shift += len(new) - (e - s)
        it["at"] = i0 + shift
    return new_text, items


BOX_AIR = 3


def designs(text, kind, case_id):
    """Wide and phone drawing. The frame height is the drawn text plus 24 units, so no large empty area."""
    d = render_design.Design(text, kind, case_id, chrome_size=CHROME_W)
    dn = render_design.Design(text, kind, case_id, narrow=True, phone_w=PHONE_W, phone_size=PHONE_SIZE, chrome_size=CHROME_N, pitch_extra=8)
    for x in (d, dn):
        if not x.listy and x.kind != "unreadable":
            x.H = int(x.text_bottom + 24)
    return d, dn


def _spot(d, it):
    """Box on the redesign drawing for one item, or None (no guess)."""
    if it["at"] is None:
        return None
    q = it["new"] if it["new"] is not None else it["quote"]
    extra = BOX_AIR  # the box line is 3 px thick: its inner edge must stay 4 px clear of the quote's own letters (CD round 3)
    if d.narrow and render_design.TOKEN.search(q):  # a drawn button has a 3-unit frame: more air so the box stays 4 px clear of it
        return d.locate(q, px=8 + extra, py=9 + extra, at=it["at"])
    return d.locate(q, px=d.padx + extra, py=d.pad + extra, at=it["at"])


def _same(a, b):
    return all(a[k] == b[k] for k in ("x", "y", "w", "h"))


def _inside(a, b):
    return (a["x"] >= b["x"] and a["y"] >= b["y"] and a["x"] + a["w"] <= b["x"] + b["w"]
            and a["y"] + a["h"] <= b["y"] + b["h"] and (a["w"], a["h"]) != (b["w"], b["h"]))


def _boxes_html(d, items, cls):
    spots = [(it, _spot(d, it)) for it in items]
    spots = [(it, b) for it, b in spots if b]
    out = []
    seen = []  # boxes already drawn: the chip of a later box steps right of earlier chips on the same spot
    for it, b in spots:
        same = [o for o in seen if _same(o, b)]
        inner = [o for o in seen if _inside(b, o) or _inside(o, b)]
        step = len(same) + (1 if inner else 0)
        seen.append(b)
        if same:  # two findings on one spot: one box, the second chip beside the first
            out[[k for k, o in enumerate(seen[:-1]) if _same(o, b)][0]] = out[[k for k, o in enumerate(seen[:-1]) if _same(o, b)][0]].replace(
                "</div>", f'<b class="numchip" style="left:calc(-3px + {len(same)} * (var(--tag) + 4px));bottom:calc(100% + 6px)" data-n="{it["n"]}">{it["n"]}</b></div>', 1)
            out.append("")
            continue
        style = (f"left:{_pct(b['x'], d.W)};top:{_pct(b['y'], d.H)};width:{_pct(b['w'], d.W)};height:{_pct(b['h'], d.H)}")
        kind = "k-confirmed" if it["state"] == "CONFIRMED" else "k-dmodel"
        if it["state"] == "CONFIRMED" and it["new"] is None:
            kind = "k-confirmed chiponly"  # not drawn: no box, only the number chip on the quote (CD round 2, fix 1)
        word = "CONFIRMED" if it["state"] == "CONFIRMED" else "DISPUTED, not changed"
        label = f"Fix {it['n']}, {it['rule']}, {word}, at {it['quote']}." if it["state"] == "CONFIRMED" \
            else f"Box {it['n']}: DISPUTED, not changed."
        cstyle = f"left:calc(-3px + {step} * (var(--tag) + 4px));bottom:calc(100% + 6px)"
        out.append(f'<div class="bx rbx {kind} {cls}" data-n="{it["n"]}" tabindex="0" role="button" '
                   f'aria-label="{esc(label)}" style="{style}"><b class="numchip" style="{cstyle}">{it["n"]}</b></div>')
    return "".join(out)


def _alt(d, items):
    n = len({it["n"] for it in items})
    parts = [f"Illustrative redesign of made-up {render_design.CAPTIONS[d.kind]}, case {d.case_id}.", f"{n} numbered marks."]
    for it in items:
        if it["state"] == "CONFIRMED":
            parts.append(f"Mark {it['n']}: changed at \"{it['quote']}\"." if it["new"] is not None
                         else f"Mark {it['n']}: at \"{it['quote']}\", not drawn.")
        else:
            parts.append(f"Mark {it['n']}: DISPUTED, not changed.")
    return " ".join(parts)


def _card(it, badges):
    n = it["n"]
    if it["state"] != "CONFIRMED":
        label = f"Fix {n}, {it['rule']}, DISPUTED, no change."
        return (f'<li class="rcard disputed" data-n="{n}" tabindex="0" aria-label="{esc(label)}">'
                f'<p class="rchip"><b class="num">{n}</b>{badges["DISPUTED"]}</p>'
                f'<p class="fixline">{esc(rt.DISPUTED_WORDS)}</p></li>')
    fx = rt.fixes_for(dict(id=n, rule=it["rule"], state="CONFIRMED", quote=it["quote"]))
    if not fx:
        return ""
    head = fx[0]
    row = rt.TABLE[it["rule"]]
    label = f"Fix {n}, {it['rule']}, CONFIRMED, changed at {it['quote']}."
    others = "".join(
        f'<li><span class="fl">Fix {chr(65 + k)}</span> {esc(f["text"])} '
        f'<span class="fm">{SHOWN if (k == 0 and it["new"] is not None) else OTHER}</span></li>'
        for k, f in enumerate(fx))
    cant = "" if it["new"] is not None else f'<p class="cant">{esc(CANT_DRAW)}</p>'
    return (f'<li class="rcard" data-n="{n}" data-rule="{esc(it["rule"])}" tabindex="0" aria-label="{esc(label)}">'
            f'<p class="rchip"><b class="num">{n}</b>{badges["CONFIRMED"]}</p>'
            f'<p class="fixline">{esc(head["text"])}</p>{cant}'
            f'<p class="rmeta">Principle: {esc(row["principle"])}</p>'
            f'<p class="rmeta">Source: {esc("; ".join(head["sources"]))}</p>'
            f'<p class="rmeta">Rule: {esc(it["rule"])}</p>'
            f'<ol class="allfix" aria-label="All fixes for {n}">{others}</ol></li>')


def _default_badges():
    return {"CONFIRMED": '<span class="badge b-confirmed" data-state="CONFIRMED"><b>CONFIRMED</b></span>',
            "DISPUTED": '<span class="badge b-disputed" data-state="DISPUTED"><b>DISPUTED</b></span>'}


def section(findings, text, kind="label", case_id="", badges=None):
    """The whole redesign section as HTML, or "" when nothing is to be shown.

    findings = [{id, rule, state, quote}] in finding order (id = the finding number).
    """
    badges = badges or _default_badges()
    shown = [f for f in findings if f.get("state") in ("CONFIRMED", "DISPUTED")]
    if not shown:
        return ""
    conf = [f for f in shown if f["state"] == "CONFIRMED" and f["rule"] in rt.TABLE]
    disp = [f for f in shown if f["state"] == "DISPUTED"]
    div = f'<div class="rdiv"><h2 id="rdh">{esc(INTRO)}</h2></div>'
    if not conf:
        cards = "".join(_card(dict(n=f["id"], rule=f["rule"], state="DISPUTED", quote=f.get("quote") or "", new=None), badges)
                        for f in disp)
        return (f'<section class="redesign none" id="redesign" aria-labelledby="rdh">{div}'
                f'<p class="rnote">{esc(NOTHING)}</p><ol class="rcards">{cards}</ol></section>')
    new_text, items = plan(shown, text)
    d, dn = designs(new_text, kind, case_id)
    dw_svg = d.svg().replace('class="design"', 'class="design rw"', 1)
    dn_svg = dn.svg().replace('class="design"', 'class="design rn"', 1)
    stage = (f'<div class="rstage" style="--w:{d.W};--h:{d.H};--nw:{dn.W};--nh:{dn.H}" aria-label="{esc(_alt(d, items))}">'
             f'{dw_svg}{dn_svg}{_boxes_html(d, items, "rw")}{_boxes_html(dn, items, "rn")}</div>')
    cards = "".join(_card(it, badges) for it in items)
    n = len(conf)
    count = f"{n} fix shown. Number = finding number." if n == 1 else f"{n} fixes shown. Number = finding number."
    cap = f"Made-up design {case_id}: {render_design.CAPTIONS[d.kind]}. Illustrative redesign."
    return (f'<section class="redesign" id="redesign" aria-labelledby="rdh">{div}'
            f'<div class="rgrid"><div class="rpanel">'
            f'<p class="rtag">{esc(rt.TAG)}</p>'
            f'<p class="legend2">{esc(LEGEND)}</p>'
            f'<div class="frame rframe">{stage}</div>'
            f'<button type="button" class="enlarge" data-action="enlarge-after">Tap image to enlarge</button>'
            f'<p class="cap" data-cap-after="{esc(cap)}" data-cap-before="{esc(d.caption().rstrip(".") + ". With the findings.")}">{esc(cap)}</p>'
            f'</div>'
            f'<div class="rlist"><h3 id="rwc">What changed</h3><p class="count">{esc(count)}</p>'
            f'<ol class="rcards">{cards}</ol></div></div></section>')


def render(findings, text=None, kind="label", case_id="X"):
    """Stand-alone render for tests: text defaults to the quoted lines, one per line."""
    if text is None:
        text = "\n".join(f.get("quote", "") for f in findings)
    return section(findings, text, kind, case_id)


def banned_hits(markup):
    """Banned words found in markup (tags removed), whole word, any case. Empty list = clean."""
    plain = re.sub(r"<[^>]+>", " ", markup)
    return sorted({w for w in BANNED if re.search(rf"(?<![A-Za-z]){w}(?![A-Za-z])", plain, re.I)})
