"""Loader and validator for hf_framework_v0.json.

A pre-check list for human factors review of alerts, notes and order sets.
It does not replace a human factors engineer. Not a medical device.

    python framework/framework.py <catalogue.md> [reference.md]

Exit 0 = valid, 1 = errors. Anything that could not run is printed as NOT RUN.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parent / "hf_framework_v0.json"
ARTEFACTS = ("alert", "note", "order_set")
DETECT = ("text_pattern", "measure", "human_only")
FIELDS = ("id", "artefact", "question", "failure_mode", "detect", "rule_id", "source", "fmea_fields")
FMEA_KEYS = ("severity_guess", "early_sign", "label")
SEVERITY = ("safety-critical", "major", "minor")
FMEA_LABEL = "guess, not a score"
MIN_PER_TYPE = 5
BANNED = ("certified", "validated")
NEEDS = "needs source"
ITEM_TYPES = ("alert", "error_message", "label", "note", "order_set")
RUN_WORDS = 8
RULE_RE = re.compile(r"^\| ([A-Z]{3,4}-\d{2}) \|", re.M)


def load(path=DEFAULT_FILE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def applies_map(data: dict) -> dict:
    """rule id -> set of item types it applies to (union where a rule has more than one criterion)."""
    out = {}
    for c in data.get("criteria", []):
        if c.get("rule_id"):
            out.setdefault(c["rule_id"], set()).update(c.get("applies_to") or [])
    return out


def parse_rule_ids(text: str) -> set:
    """Rule ids from the catalogue table rows (section 2)."""
    return set(RULE_RE.findall(text))


def parse_source_ids(text: str) -> set:
    """Source ids from catalogue section 5 (bullets, up to the first bracket)."""
    m = re.search(r"^## 5\. Sources used\s*$(.*)", text, re.M | re.S)
    if not m:
        return set()
    out = set()
    for line in m.group(1).splitlines():
        if not line.startswith("- ") or line.startswith("- The brief"):
            continue
        out.add(line[2:].split(" (")[0].strip())
    return out


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", text.lower())


def shared_run(candidate: str, reference: str, n: int = RUN_WORDS) -> bool:
    """True if candidate shares a run of n words with reference."""
    c, r = _words(candidate), _words(reference)
    if len(c) < n or len(r) < n:
        return False
    grams = {tuple(r[i:i + n]) for i in range(len(r) - n + 1)}
    return any(tuple(c[i:i + n]) in grams for i in range(len(c) - n + 1))


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def count_needs_source(data: dict) -> int:
    """Count every value equal to 'needs source' anywhere in the file."""
    return sum(1 for s in _strings(data) if s == NEEDS)


def validate(data: dict, rule_ids: set, source_ids: set, reference_text=None):
    """Return (errors, not_run). Empty errors and empty not_run = valid."""
    errs, not_run = [], []
    crit = data.get("criteria")
    if not isinstance(crit, list):
        return ["criteria: missing or not a list"], not_run
    seen = set()
    for c in crit:
        cid = c.get("id", "?")
        for f in FIELDS:
            if f not in c:
                errs.append(f"{cid}: missing field {f}")
        if c.get("id") in seen:
            errs.append(f"{cid}: duplicate id")
        seen.add(c.get("id"))
        if c.get("artefact") not in ARTEFACTS:
            errs.append(f"{cid}: artefact must be one of {ARTEFACTS}")
        if c.get("detect") not in DETECT:
            errs.append(f"{cid}: detect must be one of {DETECT}")
        rid = c.get("rule_id")
        if rid is not None and rid not in rule_ids:
            errs.append(f"{cid}: rule_id {rid} is not in the catalogue")
        src = c.get("source")
        if src != NEEDS and src not in source_ids:
            errs.append(f"{cid}: source {src!r} is not a catalogue section 5 id or 'needs source'")
        if rid is not None:
            at, ats = c.get("applies_to"), c.get("applies_to_source")
            if not isinstance(at, list) or not at or any(t not in ITEM_TYPES for t in at):
                errs.append(f"{cid}: applies_to must be a list of {ITEM_TYPES}")
            if not isinstance(ats, str) or len(ats.strip()) < 10 or ats.strip().lower() == NEEDS:
                errs.append(f"{cid}: applies_to_source must cite the catalogue line")
        ff = c.get("fmea_fields")
        if not isinstance(ff, dict) or any(k not in ff for k in FMEA_KEYS) \
                or ff.get("label") != FMEA_LABEL or ff.get("severity_guess") not in SEVERITY:
            errs.append(f"{cid}: fmea_fields needs severity_guess, early_sign and label '{FMEA_LABEL}'")
    for a in ARTEFACTS:
        if sum(1 for c in crit if c.get("artefact") == a) < MIN_PER_TYPE:
            errs.append(f"{a}: fewer than {MIN_PER_TYPE} criteria")
    ai = data.get("alert_inputs", {})
    for k in ("audience", "timing", "audience_source", "timing_source"):
        if not ai.get(k):
            errs.append(f"alert_inputs: missing {k}")
    low = json.dumps(data, ensure_ascii=False).lower()
    for w in BANNED:
        if w in low:
            errs.append(f"over-claim word '{w}' found")
    if reference_text is None:
        not_run.append("NOT RUN: reference copy check (no reference text given)")
    else:
        for c in crit:
            text = " ".join(_strings({k: c.get(k) for k in ("question", "failure_mode", "fmea_fields")}))
            if shared_run(text, reference_text):
                errs.append(f"{c.get('id', '?')}: {RUN_WORDS}-word run copied from the reference")
    return errs, not_run


def main(argv) -> int:
    if len(argv) < 2:
        print("usage: framework.py <catalogue.md> [reference.md]")
        return 2
    cat = Path(argv[1]).read_text(encoding="utf-8")
    ref = Path(argv[2]).read_text(encoding="utf-8") if len(argv) > 2 else None
    errs, not_run = validate(load(), parse_rule_ids(cat), parse_source_ids(cat), ref)
    for line in errs + not_run:
        print(line)
    if errs:
        return 1
    print("VALID" if not not_run else "VALID, with checks not run (see above)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
