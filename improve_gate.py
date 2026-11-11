"""Test gate for the safe self-improvement loop (hft-team-12). Pure functions.
Standard library only. No model client, no network. Deterministic.
All gate numbers are PROPOSALS for the owner. PCCP used as a design reference only. Not a medical device.
Spec: docs/specs/improve_gate.md"""
import hashlib
import json
import math
import re
from pathlib import Path

import log

IMPROVE_SCHEMA = Path(__file__).resolve().parent / "improve_schema.sql"

MAX_CHARS = 300
KINDS = ("prompt_line", "lesson", "rule_threshold_suggestion")
TARGETS = ("finder", "reader", "checker", "lesson_list", "threshold_note")
OVERLAP_WORDS = 8
REQUIRED_SETTINGS = ("alpha", "max_candidates", "correction", "need_runs", "false_alarm_per_30",
                     "time_pct", "max_lessons")
REFUSED_TEXT = (
    r"report nothing", r"say no findings", r"no findings", r"report no ", r"skip hard", r"skip difficult",
    r"skip the hard", r"do not report", r"don't report", r"never report", r"ignore unreadable",
    r"say nothing",
)


class GateRefusal(Exception):
    """The gate refuses to run. The reason is plain text."""


def sha256(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- statistics
def mcnemar_exact_one_sided(b, c):
    """One-sided exact p that new is better than old. b = found by new only, c = found by old only.
    P(X >= b) with X ~ Binomial(b + c, 0.5). With c = 0 this is 0.5 ** b."""
    n = b + c
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(b, n + 1)) / 2 ** n


def min_b_to_pass(alpha, candidates):
    """Smallest B (with C = 0) whose p is at most alpha / candidates (Bonferroni)."""
    level = alpha / max(1, candidates)
    b = 1
    while 0.5 ** b > level:
        b += 1
    return b


def passes_stat(b, c, alpha, candidates):
    return mcnemar_exact_one_sided(b, c) <= alpha / max(1, candidates)


def is_found(runs, need=2):
    """Found = found in at least `need` runs, each with a quote or a rule id."""
    ok = sum(1 for r in runs if r.get("found") and (r.get("quote") or r.get("rule_id")))
    return ok >= need


def paired_table(old_faults, new_faults, need=2):
    """Pair old and new per fault. B = new only, C = old only."""
    ids = sorted(old_faults)
    o = {i: is_found(old_faults[i], need) for i in ids}
    n = {i: is_found(new_faults[i], need) for i in ids}
    return {"B": sum(n[i] and not o[i] for i in ids), "C": sum(o[i] and not n[i] for i in ids),
            "both": sum(o[i] and n[i] for i in ids), "neither": sum(not o[i] and not n[i] for i in ids),
            "B_ids": [i for i in ids if n[i] and not o[i]], "C_ids": [i for i in ids if o[i] and not n[i]],
            "misses": sum(not o[i] for i in ids)}


# ---------------------------------------------------------------- settings from the protocol row
def parse_settings(text, claimed_sha):
    """Settings are fixed once, in a protocol row with its hash. A changed text with the old hash is refused."""
    if sha256(text) != claimed_sha:
        raise GateRefusal("protocol hash does not match its text; settings were changed after the hash was set")
    try:
        s = json.loads(text)
    except ValueError as e:
        raise GateRefusal(f"protocol text is not valid settings ({e})")
    missing = [k for k in REQUIRED_SETTINGS if k not in s]
    if missing:
        raise GateRefusal("protocol is missing settings: " + ", ".join(missing))
    return s


def load_settings(con, protocol_id):
    row = con.execute("SELECT text, sha256 FROM protocol WHERE protocol_id=?", (protocol_id,)).fetchone()
    if row is None:
        raise GateRefusal(f"protocol row {protocol_id} not found")
    return parse_settings(row[0], row[1])


# ---------------------------------------------------------------- candidate checks
def _words(text):
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def overlap_hit(text, case_texts, n=OVERLAP_WORDS):
    """True if n words in a row of `text` also appear in a row in any case text."""
    w = _words(text)
    if len(w) < n:
        return False
    grams = {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}
    for ct in case_texts or []:
        cw = _words(ct)
        for i in range(len(cw) - n + 1):
            if " ".join(cw[i:i + n]) in grams:
                return True
    return False


def check_candidate(cand, case_texts=(), active_lessons=0, settings=None):
    """Return (ok, reasons). Reasons are plain text."""
    why = []
    text = cand.get("text") or ""
    max_lessons = (settings or {}).get("max_lessons", 10)
    if cand.get("kind") not in KINDS:
        why.append("kind must be one of " + ", ".join(KINDS))
    if cand.get("target") not in TARGETS:
        why.append("target must be one of " + ", ".join(TARGETS))
    if not text.strip():
        why.append("candidate text is empty")
    if len(text) > MAX_CHARS:
        why.append(f"candidate text is {len(text)} characters; the limit is {MAX_CHARS}")
    for pat in REFUSED_TEXT:
        if re.search(pat, text, re.I):
            why.append(f"text asks the agent to hide findings or skip cases ('{pat.strip()}'); refused")
            break
    if overlap_hit(text, case_texts):
        why.append(f"{OVERLAP_WORDS} words in a row are copied from a case text; refused")
    if cand.get("kind") == "lesson" and active_lessons >= max_lessons:
        why.append(f"{active_lessons} active lessons already; the limit is {max_lessons}")
    return (not why), why


# ---------------------------------------------------------------- must-not-worsen
def false_alarms(clean, need=2):
    return sum(1 for runs in clean.values() if sum(1 for r in runs if r.get("flagged")) >= need)


def must_not_worsen(old, new, settings, old_hashes, new_hashes):
    """Return a list of plain reasons. An empty list means no check failed."""
    why = []
    n_clean = len(new["clean"])
    extra = math.ceil(n_clean / 30) * settings["false_alarm_per_30"] if n_clean else 0
    allowed = false_alarms(old["clean"]) + extra
    fa = false_alarms(new["clean"])
    if fa > allowed:
        why.append(f"false alarms rose to {fa} (at most {allowed} allowed)")
    if new["unable_rate"] < old["unable_rate"] - 1e-9:
        why.append(f"UNABLE TO CHECK rate fell from {old['unable_rate']:.2f} to {new['unable_rate']:.2f}")
    for kind, flags in new["plants"].items():
        if not all(flags):
            why.append(f"a {kind} plant is no longer caught")
    if new["minutes_per_case"] > old["minutes_per_case"] * (1 + settings["time_pct"] / 100) + 1e-9:
        why.append(f"time per case rose from {old['minutes_per_case']:.2f} to {new['minutes_per_case']:.2f} min "
                   f"(more than +{settings['time_pct']}%)")
    if old_hashes != new_hashes:
        why.append("code-rule file hash changed during the run")
    return why


def hash_files(paths):
    return {str(p): sha256(Path(p).read_text(encoding="utf-8")) if Path(p).is_file() else "MISSING"
            for p in paths}


# ---------------------------------------------------------------- canary, chain
def canary_scan(texts, canaries):
    """texts: name -> text. Return a list of (name, canary) hits. Case-blind."""
    hits = []
    for name, t in texts.items():
        low = (t or "").lower()
        for c in canaries:
            if c and c.lower() in low:
                hits.append((name, c))
    return hits


def check_chain(con):
    """Use the existing log code. Refuse to run on a broken chain."""
    ok, n, broken = log.verify_chain(con)
    if not ok:
        raise GateRefusal(f"log hash chain is broken: {broken}")
    return n


# ---------------------------------------------------------------- result shape
def validate_result(res, label):
    """Return None if the run result has every field the gate needs, else a plain reason."""
    try:
        if not isinstance(res, dict):
            return f"{label}: no result"
        for k in ("faults", "clean", "unable_rate", "plants", "minutes_per_case"):
            if k not in res:
                return f"{label}: result has no '{k}'"
        if not res["faults"]:
            return f"{label}: result has no faults"
        for runs in list(res["faults"].values()) + list(res["clean"].values()):
            if len(runs) < 3:
                return f"{label}: an item has fewer than 3 runs"
        for k in ("fake_quote", "unreadable"):
            if len(res["plants"].get(k, [])) != 3:
                return f"{label}: need 3 {k} plants"
    except (AttributeError, TypeError) as e:
        return f"{label}: result is malformed ({e})"
    return None


def decide(table, reg_table, worse, settings, candidates=None):
    """Return (verdict, reasons). Verdict is 'eligible' or 'reject'; never 'approved'."""
    k = candidates or settings["max_candidates"]
    why = []
    if table["C"] > 0:
        why.append(f"lost {table['C']} fault(s) the old version found on dev-check: " + ", ".join(table["C_ids"]))
    if reg_table["C"] > 0:
        why.append(f"lost {reg_table['C']} fault(s) on the regression set: " + ", ".join(reg_table["C_ids"]))
    if not passes_stat(table["B"], table["C"], settings["alpha"], k):
        p = mcnemar_exact_one_sided(table["B"], table["C"])
        why.append(f"not enough gain: B={table['B']}, C={table['C']}, p={p:.4f}; "
                   f"needs p <= {settings['alpha'] / k:.4f} and B >= {min_b_to_pass(settings['alpha'], k)}")
    why += worse
    return ("reject" if why else "eligible"), why
