"""Rule-to-fix table for the illustrative redesign view (spec: docs/specs/redesign.md).

Fixed words only. A slot is filled from the finding's quoted line and nothing else.
No model, no network. Only the standard library is imported.
"""
import hashlib
import re

TAG = "Illustrative redesign. Fictional. Not a medical device."
DISPUTED_WORDS = "A human must decide."

WIKI = "wiki/Human Factors in Clinical Information Design.md"
NIELSEN = "sources/nielsen-usability-heuristics-reference/nielsen-usability-heuristics-reference.md"
ISMP = "sources/ismp-error-prone-abbreviations-reference/ismp-error-prone-abbreviations-reference.md"
TALLMAN = "sources/tall-man-lettering-lists-reference/tall-man-lettering-lists-reference.md"
WCAG = "sources/wcag-22-reference/wcag-22-reference.md"
ALERTFAT = "sources/alert-fatigue-hospitals-qualitative-2026/alert-fatigue-hospitals-qualitative-2026.md"

PENDING = "source pending"

# EMR-01 fix A: three fixed lines, picked by code from the quoted line (never a model). First match wins.
EMR01_A = (
    ("trailing_zero", re.compile(r"\d\.\d*0(?!\d)"), 'Remove the zero after the point in "{quote}".'),
    ("no_leading_zero", re.compile(r"(?<!\d)\.\d"), 'Put a zero before the point in "{quote}".'),
    ("abbreviation", re.compile(r".*", re.S), 'Write the full words in place of "{quote}".'),
)
ABBREV = re.compile(r"(?<![A-Za-z.])(QD|Q\.D\.|QOD|Q\.O\.D\.|HS|IU)(?![A-Za-z])")

# Fixed words the redesign may draw that are not case text. Inside the hash.
# Each expansion is the plain meaning of the short form listed in the ISMP note.
DRAW_EXPAND = {"QD": "every day", "Q.D.": "every day", "QOD": "every other day", "Q.O.D.": "every other day",
               "HS": "at bedtime", "IU": "international unit"}
DRAW_ALT03 = ("Change", "Cancel")  # choice buttons drawn next to a lone [OK]

# rule id -> row. Paths are relative to the knowledge store folder.
# fixes: up to 3, the first is the one shown on the main screen. principle = short name shown on screen.
TABLE = {
    "EMR-01": {
        "fixes": (
            'Write the full words in place of "{quote}".',
            'Offer a pick list instead of typing for "{quote}".',
            'Show a warning on save for "{quote}"; a person confirms.',
        ),
        "principle": "Error prevention",
        "sources": (("ISMP list of error-prone abbreviations", ISMP),
                    ("Nielsen, usability heuristic 5", NIELSEN)),
    },
    "EMR-02": {
        "fixes": (
            'Write part of "{quote}" in capitals to set it apart from look-alike names.',
            'Show the reason for the drug beside "{quote}".',
            'Show the strength beside "{quote}".',
        ),
        "principle": "Keep look-alike drug names easy to tell apart",
        "sources": (("Tall-man lettering lists", TALLMAN),
                    ("Human Factors in Clinical Information Design, principle 8", WIKI)),
    },
    "EMR-03": {
        "fixes": (
            'Make "{quote}" at least 24 by 24 pixels.',
            'Add space around "{quote}".',
            'Move the controls near "{quote}" closer together.',
        ),
        "principle": "Minimum size for a tap or click area",
        "sources": (("WCAG 2.2, criterion 2.5.8", WCAG),),
    },
    "ALT-01": {
        "fixes": (
            'Say in "{quote}" which value is the problem.',
            'State the reason in "{quote}".',
            'Offer two or three choices below "{quote}".',
        ),
        "principle": "Messages that name the problem and the next step",
        "sources": (("Nielsen, usability heuristic 9", NIELSEN),
                    ("Human Factors in Clinical Information Design, principle 9", WIKI)),
    },
    "ALT-02": {
        "fixes": (
            'Use different wording for the alert "{quote}".',
            'Use a different icon for the alert "{quote}".',
            'Combine the alert "{quote}" with alerts like it.',
        ),
        "principle": "Look-alike alerts",
        "sources": (("Human Factors in Clinical Information Design, principle 9", WIKI),),
    },
    "ALT-03": {
        "fixes": (
            'Add choices next to "{quote}".',
            'Ask for a reason when a person taps "{quote}" to dismiss the alert.',
            'Put the value on the button "{quote}".',
        ),
        "principle": "Alert fatigue",
        "sources": (("Newton et al., J Med Internet Res 2026, DOI 10.2196/78676", ALERTFAT),),
    },
    "LBL-18": {
        "fixes": (
            'Use darker text for "{quote}".',
            'Use a plain, solid background behind "{quote}".',
            'Use larger type for "{quote}".',
        ),
        "principle": "Text contrast",
        "sources": (("WCAG 2.2, criterion 1.4.3", WCAG),),
    },
}

PILOT_RULES = tuple(TABLE)


def emr01_kind(quote):
    """Which EMR-01 fix A line fits this quote: trailing_zero | no_leading_zero | abbreviation. Code only."""
    for name, rx, _ in EMR01_A:
        if rx.search(quote or ""):
            return name
    return "abbreviation"


def fix_lines(rule, quote):
    """The fix lines for a rule and quote. Fix A of EMR-01 is picked by the quote pattern."""
    row = TABLE.get(rule)
    if row is None:
        return []
    lines = list(row["fixes"])
    if rule == "EMR-01":
        lines[0] = next(t for n, _, t in EMR01_A if n == emr01_kind(quote))
    return [t.format(quote=quote) for t in lines]


def fixes_for(finding):
    """Fixes for one finding. Only CONFIRMED gets any; every other state gets an empty list.

    The number is the finding's own id, never counted again. Unknown rule: empty list.
    """
    if finding.get("state") != "CONFIRMED":
        return []
    row = TABLE.get(finding.get("rule"))
    if row is None:
        return []
    texts = fix_lines(finding["rule"], finding.get("quote", ""))
    return [{"number": finding["id"], "rule": finding["rule"], "text": t,
             "principle": row["principle"], "sources": [n for n, _ in row["sources"]]}
            for t in texts]


def draw_for(rule, quote):
    """The text to draw in place of the quote, or None when no fixed draw words exist (then it is not drawn).

    Only fixed words from this file or the quote itself are used. No word is made up at render time.
    """
    quote = quote or ""
    if rule == "EMR-01":
        kind = emr01_kind(quote)
        if kind == "trailing_zero":
            return re.sub(r"(\d\.\d*?)0+(?!\d)", lambda m: m.group(1).rstrip("."), quote, count=1)
        if kind == "no_leading_zero":
            return re.sub(r"(?<!\d)\.(\d)", lambda m: "0." + m.group(1), quote, count=1)
        m = ABBREV.search(quote)
        if m:
            return quote[:m.start()] + DRAW_EXPAND[m.group(1)] + quote[m.end():]
        return None
    if rule == "ALT-03" and re.fullmatch(r"\[[^\]\r\n]+\]", quote):
        return quote + " " + " ".join(f"[{w}]" for w in DRAW_ALT03)
    return None


def table_hash():
    """Hash of every fixed word the screen can show or draw, so a silent change is caught."""
    nl = chr(10)
    blob = nl.join(
        f"{r}|{'|'.join(v['fixes'])}|{v['principle']}|{'|'.join(n for n, _ in v['sources'])}"
        for r, v in sorted(TABLE.items()))
    blob += nl + "A:" + "|".join(t for _, _, t in EMR01_A)
    blob += nl + "X:" + "|".join(f"{k}={v}" for k, v in sorted(DRAW_EXPAND.items()))
    blob += nl + "B:" + "|".join(DRAW_ALT03)
    blob += nl + "T:" + TAG + "|" + DISPUTED_WORDS
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
