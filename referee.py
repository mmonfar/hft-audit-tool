"""Referee: plain code, no model. Checks every suggested fault and gives it a state.

Rules decide, models only suggest. Standard library only. No network.
Same input gives the same answer every time.
"""
import json
import re
from pathlib import Path

FIELDS = ("fault_id", "rule_id", "quote", "location", "severity", "confidence", "audience")
MIN_TEXT = 20
LIMIT_MARK = "<<TOKEN_LIMIT>>"

# Regex rules: rule id -> function(text) -> list of quotes that hit. Tools, not models.
_ABBREV = re.compile(r"(?<![\w.])(?:QD|QOD|IU|U|MS|MSO4|MGSO4)(?![\w.])|\b\d+\.0\s*mg\b|(?<![\d])\.\d+\s*mg\b")
_BUTTON = re.compile(r"\[[^\]\n]+\]")


def regex_emr01(text):
    return [m.group(0) for m in _ABBREV.finditer(text)]


def regex_alt03(text):
    buttons = _BUTTON.findall(text)
    if len(buttons) == 1 and buttons[0].strip("[] ").upper() in ("OK", "CLOSE", "DISMISS"):
        return buttons[:1]
    return []


REGEX_RULES = {"EMR-01": regex_emr01, "ALT-03": regex_alt03}

# ---- item type and "applies to" (hft-team-08). The source for "applies to" is the framework file.
FRAMEWORK_FILE = Path(__file__).resolve().parent / "framework" / "hf_framework_v0.json"
NOT_APPLY = "rule does not apply to this item type"
CODE_ONLY = "found by code rule, no model finding"
_ERROR_START = re.compile(r"^\W*(?:error|failed|failure)\b", re.I)
_ERROR_PHRASE = re.compile(r"went wrong|could not be completed|something failed", re.I)
_SIGNAL_LINE = re.compile(r"^\W*(?:alert|warning|caution|notice|danger|stop)\b", re.I | re.M)
_TALL_MAN = re.compile(r"\b[A-Za-z]*[a-z][A-Z]{2,}[A-Za-z]*\b")
_applies_cache = {}


def applies_map():
    """rule id -> set of item types, read from the framework file (cached)."""
    if not _applies_cache:
        data = json.loads(FRAMEWORK_FILE.read_text(encoding="utf-8"))
        for c in data.get("criteria", []):
            if c.get("rule_id"):
                _applies_cache.setdefault(c["rule_id"], set()).update(c.get("applies_to") or [])
    return _applies_cache


def classify_item(text, kind=None):
    """'error_message', 'alert', 'label' or None (unknown: no filter). Plain code rules.
    An item is an error message when its first line starts with Error/Failed/Failure, or it says
    'went wrong' / 'could not be completed' / 'something failed'. Otherwise the case kind decides."""
    first = next((ln for ln in (text or "").splitlines() if ln.strip()), "")
    if kind in ("alert", "label", None) and (_ERROR_START.search(first) or _ERROR_PHRASE.search(text or ""))             and kind != "label":
        return "error_message"
    return kind if kind in ("alert", "label") else None


def rule_applies(rule_id, item_type):
    if item_type is None:
        return True
    types = applies_map().get(rule_id)
    return True if not types else item_type in types


def alert_count(text):
    return len(_SIGNAL_LINE.findall(text or ""))


def tall_man_in_use(quote):
    """True when 2 or more words in the quote are written with tall-man capitals (like BrinDACOL)."""
    return len(_TALL_MAN.findall(quote or "")) >= 2


def fix_space(s):
    """White-space fixed: runs of spaces, tabs and line breaks become one space. Case is kept."""
    return " ".join((s or "").split())


def quote_found(quote, ocr_text):
    q = fix_space(quote)
    return bool(q) and q in fix_space(ocr_text)


def strict_parse(text):
    """Whole output must be one JSON list of objects. Prose around it = invalid (None).
    Extra fields are dropped."""
    try:
        data = json.loads((text or "").strip())
    except (ValueError, TypeError):
        return None
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        return None
    return [{k: x.get(k) for k in FIELDS} for x in data]


def repeat_detected(text, hit_limit=False):
    """Same sentence 2 or more times (text outside JSON strings), or output ends at the token limit."""
    if hit_limit or (text or "").rstrip().endswith(LIMIT_MARK):
        return True
    outside = re.sub(r'"(?:[^"\\]|\\.)*"', " ", text or "")
    outside = re.sub(r"\b(?:null|true|false)\b|\d+\.\d+", " ", outside)  # JSON literals and numbers
    sentences = [fix_space(re.sub(r"[^A-Za-z\s]", " ", s)).lower() for s in re.split(r"[.!?\n]+", outside)]
    sentences = [s for s in sentences if len(s.split()) >= 4]
    return len(sentences) != len(set(sentences))


def _hit_in_quote(rid, quote, ocr_text):
    q = fix_space(quote)
    return any(fix_space(h) in q for h in REGEX_RULES[rid](ocr_text))


def judge(findings, ocr_text, rule_ids, item_type=None):
    """Return one verdict per finding: dict(finding, decision, reason).
    decision: 'drop' (quote not in text, rule id not in the frozen list, rule does not apply to the item
    type, or a code check says it is not a fault), 'DISPUTED' (code rule and model disagree), 'CONFIRMED'.
    A drop with retry=False cannot be fixed by sending it back to the model."""
    out = []
    for f in findings:
        rid, quote = f.get("rule_id"), f.get("quote")
        if not isinstance(quote, str) or not quote_found(quote, ocr_text):
            out.append(dict(finding=f, decision="drop", reason="quote not found in the OCR text"))
        elif rid not in rule_ids:
            out.append(dict(finding=f, decision="drop", reason="rule id not in the frozen list"))
        elif not rule_applies(rid, item_type):
            out.append(dict(finding=f, decision="drop", reason=NOT_APPLY, retry=False))
        elif rid == "ALT-02" and alert_count(ocr_text) < 2:
            out.append(dict(finding=f, decision="drop", retry=False,
                            reason="ALT-02 needs two or more alerts on the screen to compare; the text holds fewer"))
        elif rid == "EMR-02" and tall_man_in_use(quote):
            out.append(dict(finding=f, decision="drop", retry=False,
                            reason="look-alike names already use tall-man letters"))
        elif rid in REGEX_RULES:
            if _hit_in_quote(rid, quote, ocr_text):
                out.append(dict(finding=f, decision="CONFIRMED", reason="quote found, rule id valid, regex agrees"))
            else:
                out.append(dict(finding=f, decision="DISPUTED",
                                reason="model and regex rule disagree (regex hit is not inside the quote)"))
        else:
            out.append(dict(finding=f, decision="CONFIRMED", reason="quote found, rule id valid"))
    return out


def add_code_findings(verdicts, ocr_text, item_type, rule_ids):
    """Every regex hit that no kept model finding of the same rule covers becomes its own CONFIRMED
    finding. Only for rules that apply to the item type. Returns verdicts plus the new ones."""
    out = list(verdicts)
    n = 0
    for rid, fn in sorted(REGEX_RULES.items()):
        if rid not in rule_ids or not rule_applies(rid, item_type):
            continue
        for hit in fn(ocr_text):
            covered = any(v["decision"] != "drop" and v["finding"].get("rule_id") == rid
                          and isinstance(v["finding"].get("quote"), str)
                          and fix_space(hit) in fix_space(v["finding"]["quote"]) for v in verdicts)
            if not covered:
                n += 1
                out.append(dict(finding=dict(fault_id=f"code{n}", rule_id=rid, quote=hit, location="code rule",
                                             severity=None, confidence=None, audience=None),
                                decision="CONFIRMED", reason=CODE_ONLY))
    return out
