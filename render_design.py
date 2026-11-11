"""Draws a made-up screen (drug label, alert window, pick list / order set) as SVG from the case text.

Rules (design/hft/render_designs_cd_brief.md):
- Every drawn word is case text, except a fixed chrome list (SAMPLE, close mark, frame, "No readable design").
- One case line = one drawn line, in case order. A "[X]" token is drawn as a button labelled X.
- No fault is drawn on purpose here: the text is drawn as written. The fault is in the case text.
- Text positions are known at build time: locate() gives the box (x, y, w, h) for a quote.
- The box is display only. The referee judges on text, never on a box.
Standard library only. No outside call.
"""
import hashlib
import html
import re

CHROME = ("SAMPLE", "SAMPLE LABEL", "SAMPLE ORDER LIST", "SAMPLE ALERT", "×", "No readable design")
TOKEN = re.compile(r"(\[[^\]]+\])")
TALL = re.compile(r"(?<=[a-z])[A-Z]{2,}")
CAPTIONS = {"label": "drug label", "alert": "alert window", "picklist": "pick list", "orderset": "order set",
            "unreadable": "no readable design"}
INK, WASH, RULE, CREAM = "#17242B", "#E3E5E4", "#D3D7D8", "#FDFBF7"
MONO = "Courier New,Liberation Mono,DejaVu Sans Mono,monospace"  # all 0.6 em wide: normal letter spacing
PADX = 14  # side clear space on a wide frame (still 4 px clear at 1366)
PAD = 12  # clear space (design units) between the drawn letters and the box edge
ASC, DESC = 0.88, 0.30  # letter height above / below the baseline, in em


def wrap(ln, cols):
    """Split one case line into (a, b) pieces of at most cols letters, cut after a space when possible."""
    n = len(ln)
    out, a = [], 0
    if n == 0:
        return [(0, 0)]
    while a < n:
        if n - a <= cols:
            out.append((a, n))
            break
        sp = ln.rfind(" ", a, a + cols)
        cut = sp + 1 if sp > a else a + cols
        out.append((a, cut))
        a = cut
    return out


def text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def kind_of(text, case_kind, unreadable=False):
    """label | alert | picklist | orderset | unreadable. Line 1 of the case text names the list types."""
    if unreadable:
        return "unreadable"
    first = (text or "").split("\n", 1)[0].lower()
    if first.startswith("pick list"):
        return "picklist"
    if first.startswith("order set"):
        return "orderset"
    return "alert" if case_kind == "alert" else "label"


def esc(s):
    return html.escape(s, quote=True)


class Design:
    """wide = 864x540 frame, one case line = one drawn line. narrow (phone) = 360 wide, drawn text 13.5 units,
    long lines wrap onto more drawn lines. Same case text, same boxes logic, two layouts."""

    def __init__(self, text, case_kind, case_id="", unreadable=False, narrow=False, phone_w=None, phone_size=None, chrome_size=None, pitch_extra=0, plain_head=False):
        self.chrome_size = chrome_size
        self.plain_head = plain_head  # redesign only: first line in the same weight as the rest (CD round 2)
        self.text = text or ""
        self.case_id = case_id
        self.narrow = narrow
        self.pad = 5 if narrow else PAD
        self.padx = 5 if narrow else PADX
        self.kind = kind_of(self.text, case_kind, unreadable)
        self.lines = self.text.split(chr(10)) if self.text else []
        self.listy = self.kind in ("picklist", "orderset")
        self.W = (phone_w or 360) if narrow else 864
        self.x0 = 54 if narrow else 64  # left gutter holds one link per tag, 9+ units apart
        if narrow:
            self.size = phone_size or 13.5
            self.cw = self.size * 0.6  # mono: every letter 0.6 em wide (13.5 -> 8.1, as before)
            cols = int((self.W - self.x0 - 10) / self.cw)
        else:
            units = max([len(ln) for ln in self.lines] or [1])
            self.cw = min(20.4, (self.W - self.x0 - 24) / max(units, 1))
            self.size, cols = self.cw / 0.6, 10 ** 6
        size = self.size
        self.sha = text_sha(self.text)
        self.chunks = []  # (line, a, b)
        for i, ln in enumerate(self.lines):
            for a, b in (wrap(ln, cols) if not (self.listy and i == 0) else [(0, len(ln))]):
                self.chunks.append((i, a, b))
        n = len(self.chunks)
        self.top = 32 if narrow else 40
        self.rows = []  # (line, a, b, baseline)
        if self.listy:
            self.top = round(size * 1.2 + 22)
            nrow = max(n - 1, 1)
            if narrow:
                self.pitch = 78
                self.H = int(self.top + nrow * self.pitch + 24)
            else:
                self.H = 540
                self.pitch = min(150, (540 - self.top - 16) / nrow)
            for k, (ln, a, b) in enumerate(self.chunks):
                if k == 0:
                    self.rows.append((ln, a, b, self.top / 2 + size * 0.35))
                else:
                    self.rows.append((ln, a, b, self.top + (k - 0.5) * self.pitch + size * 0.35))
        else:
            # two boxes on neighbour lines keep a clear gap: pitch = box height (outer box 14 clear) + room for the number chip above each box
            self.pitch = size * (ASC + DESC) + (2 * 5 + 36 if narrow else 2 * 14 + 46) + pitch_extra
            block = sum(size * 1.35 if self.chunks[k - 1][0] == self.chunks[k][0] else self.pitch for k in range(1, n))
            # the drawn text starts close under the title bar, like a real window (at most 64 px under it: room for the number chip above box 1)
            base0 = self.top + (38 if narrow else 56) + size * ASC
            if narrow:
                self.H = int(max(base0 + block + size * DESC + 44, 200))
            else:
                self.H = max(360, int(base0 + block + size * DESC + 24))
            y = base0
            for k, (ln, a, b) in enumerate(self.chunks):
                if k:  # wrapped parts of one case line: normal line height; the big gap goes between case lines only
                    y += size * 1.35 if self.chunks[k - 1][0] == ln else self.pitch
                self.rows.append((ln, a, b, y))
        if self.kind == "unreadable":
            self.H = 160 if narrow else 540
        # bottom of the drawn text (design units); the phone tag strip starts under it
        self.text_bottom = (self.rows[-1][3] + size * DESC) if self.rows and not self.listy else self.H - 24
        self.strip_top = None
        self.slot, self.sx = (46, 22) if narrow else (72, self.x0)

    def set_strip(self, words):
        """Tags go in a strip under the drawn text, one per slot, so no tag covers a letter. The frame then fits its
        content plus 24 units (phone: it grows; wide: min 360). words = the tag words, in slot order (top to bottom)."""
        n = len(words) if not isinstance(words, int) else words
        self.slot = 46 if self.narrow else 72
        self.sx = 22 if self.narrow else self.x0
        if n <= 0 or self.listy or self.kind == "unreadable":
            return
        if self.narrow:
            self.strip_top = round(self.text_bottom + self.pad + 16)
            self.H = int(self.strip_top + n * self.slot + 8)
            return
        self.strip_top = round(self.text_bottom + 13 + 5 + 18)  # clear of the link lanes under the text
        last = words[-1] if not isinstance(words, int) else ""
        lasth = 70 if len(last) * 14.3 + 60 > self.W - self.sx - 6 else 40
        self.H = max(360, int(self.strip_top + (n - 1) * self.slot + lasth + 24))

    # ------------------------------------------------------------------ geometry
    def _rect(self, r0, r1, cols_a, cols_b, px=None, py=None):
        """Box round rows r0..r1 (indexes in self.rows); letters cols_a..cols_b of the first row when r0 == r1."""
        first, last = self.rows[r0], self.rows[r1]
        px = self.padx if px is None else px
        py = self.pad if py is None else py
        top = first[3] - self.size * ASC - py
        bot = last[3] + self.size * DESC + py
        if r0 == r1:
            x = self.x0 + (cols_a - first[1]) * self.cw - px
            w = (cols_b - cols_a) * self.cw + 2 * px
        else:
            wid = max(self.rows[i][2] - self.rows[i][1] for i in range(r0, r1 + 1))
            x, w = self.x0 - px, wid * self.cw + 2 * px
        return dict(x=round(x, 2), y=round(top, 2), w=round(w, 2), h=round(bot - top, 2))

    def _span(self, line, a, last, b):
        idx = [i for i, (ln, ca, cb, _) in enumerate(self.rows)
               if (ln > line or cb > a) and (ln < last or ca < b) and line <= ln <= last]
        return idx

    def locate(self, quote, px=None, py=None, at=None):
        """Box for a quote. None when the quote is not in the text (no guess). Measured from the drawn letters.
        at = search from this text index (a hit inside a bigger quote); px, py = own clear space (units)."""
        if not quote or not self.text:
            return None
        i = self.text.find(quote, at or 0)
        if i < 0:
            fixed = re.sub(r"\s+", " ", quote).strip()
            i, quote = self.text.find(fixed, at or 0), fixed
        if i < 0:
            return None
        nl = chr(10)
        line = self.text.count(nl, 0, i)
        start = i - (self.text.rfind(nl, 0, i) + 1)
        parts = quote.split(nl)
        last = line + len(parts) - 1
        end = start + len(quote) if nl not in quote else len(parts[-1])
        idx = self._span(line, start, last, end)
        if not idx:
            return None
        box = self._rect(idx[0], idx[-1], start, end, px, py)
        box.update(line=line, line_end=last, a=start, b=end, quote=quote)
        return box

    def line_end_x(self, box):
        """Right end (design units) of the drawn letters on the last row of a box: tags go right of this."""
        idx = self._span(box["line"], box["a"], box["line_end"], box["b"])
        return max(self.x0 + (self.rows[i][2] - self.rows[i][1]) * self.cw for i in idx)

    # ------------------------------------------------------------------ drawing
    def _row(self, k):
        idx, ca, cb, base = self.rows[k]
        ln = self.lines[idx][ca:cb]
        out, pos = [], 0
        hd = idx == 0 and (self.listy or self.kind == "label") and not self.plain_head
        cls = "ln" + (" hd" if hd else "")
        dim = ' opacity="0.3"' if self.kind == "unreadable" else ""
        size = self.size
        for seg in TOKEN.split(ln):
            if not seg:
                continue
            x = self.x0 + pos * self.cw
            w = len(seg) * self.cw
            if TOKEN.fullmatch(seg):
                label = seg[1:-1]
                out.append(f'<g class="btn" data-src="{esc(seg)}"><rect x="{x + 2:.2f}" y="{base - size * ASC - 2:.2f}" '
                           f'width="{w - 4:.2f}" height="{size * (ASC + DESC) + 4:.2f}" fill="#FFFFFF" stroke="{INK}" '
                           f'stroke-width="2"/><text x="{x + w / 2:.2f}" y="{base:.2f}" text-anchor="middle" '
                           f'font-size="{size:.2f}" font-weight="700" fill="{INK}" class="bt">{esc(label)}</text></g>')
            else:
                inner = esc(seg)
                if self.listy and idx > 0:
                    inner = TALL.sub(lambda m: f'<tspan font-weight="800">{m.group(0)}</tspan>', inner)
                xs = " ".join(f"{x + j * self.cw:.2f}" for j in range(len(seg)))
                bold = ' font-weight="800"' if hd else ""
                out.append(f'<text x="{xs}" y="{base:.2f}" font-size="{size:.2f}" fill="{INK}" '
                           f'xml:space="preserve" class="{cls}"{dim}{bold}>{inner}</text>')
            pos += len(seg)
        return f'<g class="row" data-line="{idx}" data-part="{k}">{"".join(out)}</g>'

    def svg(self, inline=True):
        W, H, sha = self.W, self.H, self.sha
        pid = f"hp{sha[:8]}{'n' if self.narrow else 'w'}"
        ns = "" if inline else ' xmlns="http://www.w3.org/2000/svg"'
        font = "Plus Jakarta Sans,Segoe UI,Arial,sans-serif"
        cf = self.chrome_size or (13 if self.narrow else 14)
        ty = round(self.top / 2 + cf * 0.35, 2) if self.chrome_size else self.top / 2 + 5  # title baseline: centred in the grey bar when cf is set
        p = [f'<svg{ns} viewBox="0 0 {W} {H}" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" '
             f'role="img" aria-label="Made-up {CAPTIONS[self.kind]}, case {esc(self.case_id)}" '
             f'class="design" data-kind="{self.kind}" data-case-sha="{sha}" data-w="{W}" data-h="{H}" '
             f'data-x0="{self.x0}" data-cw="{self.cw:.4f}" data-narrow="{1 if self.narrow else 0}" '
             f'font-family="{font}">',
             f'<defs><pattern id="{pid}" width="10" height="10" patternUnits="userSpaceOnUse" '
             f'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="10" stroke="{INK}" '
             f'stroke-opacity="0.11" stroke-width="2"/></pattern></defs>',
             f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
             f'<g font-family="{MONO}" class="mono">']
        head = ""
        if self.kind == "alert":
            head = f'<rect width="{W}" height="{self.top}" fill="{WASH}"/>'                    f'<text x="{self.x0}" y="{ty}" font-size="{cf}" font-weight="700" fill="{INK}" '                    f'font-family="{font}" class="chrome">SAMPLE ALERT</text>'
            if "cannot be closed" not in self.text:
                head += f'<text x="{W - 36}" y="{self.top / 2 + 7}" font-size="22" fill="{INK}" font-family="{font}" class="chrome">×</text>'
        elif self.kind == "label":
            head = f'<rect width="{W}" height="{self.top}" fill="{WASH}"/>'                    f'<text x="{self.x0}" y="{ty}" font-size="{cf}" font-weight="700" fill="{INK}" '                    f'font-family="{font}" class="chrome">SAMPLE LABEL</text>'
        elif self.listy:
            head = f'<rect width="{W}" height="{self.top}" fill="{WASH}"/>'
            for i in range(1, max(len(self.rows) - 1, 0)):
                y = self.top + i * self.pitch
                head += f'<line x1="0" x2="{W}" y1="{y:.1f}" y2="{y:.1f}" stroke="{RULE}" stroke-width="1"/>'
            head += f'<text x="{W - 16}" y="{ty}" text-anchor="end" font-size="{cf}" font-weight="700" '                     f'fill="{INK}" font-family="{font}" class="chrome">SAMPLE</text>'
        else:
            head = f'<rect width="{W}" height="{self.top}" fill="{WASH}"/>'
        p.insert(-1, head)
        for k in range(len(self.rows)):
            p.append(self._row(k))
        p.append("</g>")
        if self.kind == "unreadable":
            p.append(f'<rect width="{W}" height="{H}" fill="url(#{pid})"/>')
            plate_w = len("No readable design") * 13.5 + 24
            p.append(f'<rect x="{(W - plate_w) / 2:.1f}" y="{H / 2 - 24:.1f}" width="{plate_w:.1f}" height="48" '
                     f'fill="{CREAM}"/><text x="{W / 2}" y="{H / 2 + 8:.1f}" text-anchor="middle" font-size="24" '
                     f'font-weight="800" fill="{INK}" font-family="{font}" class="chrome">No readable design</text>')
        p.append(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" fill="none" stroke="{INK}" stroke-width="2"/>')
        p.append("</svg>")
        return "".join(p)

    def caption(self):
        return f"Made-up design {self.case_id}: {CAPTIONS[self.kind]}."


def drawn_text(svg):
    """The case text read back from the drawing: text as written, buttons back as [label]."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(svg if "xmlns" in svg[:200] else svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1))
    ns = "{http://www.w3.org/2000/svg}"
    lines = {}
    for g in root.iter(ns + "g"):
        if g.get("class") != "row":
            continue
        parts = []
        for el in g:
            if el.get("class") == "btn":
                parts.append(el.get("data-src"))
            else:
                parts.append("".join(el.itertext()))
        lines.setdefault(int(g.get("data-line")), []).append((int(g.get("data-part")), "".join(parts)))
    lines = {k: "".join(t for _, t in sorted(v)) for k, v in lines.items()}
    return chr(10).join(lines[i] for i in sorted(lines))
