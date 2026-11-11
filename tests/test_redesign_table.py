"""Rule-to-fix table for the illustrative redesign view. The render part waits for card 14."""
import ast
import re
from pathlib import Path

import pytest

import redesign_table as rt

ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT.parent / "refs_books"  # zero-trace: ok
PILOT = ["EMR-01", "EMR-02", "EMR-03", "ALT-01", "ALT-02", "ALT-03", "LBL-18"]
EXPECTED_HASH = "99a1ebd7c581002b2b3a614d5f3c0222f973fdef65bd89f2ecf414976e9380d2"


def finding(state="CONFIRMED", rule="EMR-01", n=3, quote="QD"):
    return {"id": n, "rule": rule, "state": state, "quote": quote}


def test_every_pilot_rule_has_a_row():
    assert sorted(rt.TABLE) == sorted(PILOT)


@pytest.mark.parametrize("rule", PILOT)
def test_row_is_not_empty(rule):
    row = rt.TABLE[rule]
    assert 1 <= len(row["fixes"]) <= 3
    assert all(t.strip() and "{quote}" in t for t in row["fixes"])
    assert row["principle"].strip()
    assert row["sources"]
    for name, path in row["sources"]:
        assert name.strip() and path.strip()


@pytest.mark.parametrize("rule", PILOT)
def test_every_source_is_on_disk(rule):
    for _name, path in rt.TABLE[rule]["sources"]:
        assert (REFS / path).is_file(), path


@pytest.mark.parametrize("state", ["DISPUTED", "DROPPED", "UNABLE TO CHECK", "CHECKED", "", None])
def test_no_fix_unless_confirmed(state):
    for rule in PILOT:
        assert rt.fixes_for(finding(state=state, rule=rule)) == []


def test_unknown_rule_gives_no_fix():
    assert rt.fixes_for(finding(rule="XXX-99")) == []


@pytest.mark.parametrize("n", [1, 4, 7])
def test_number_is_the_finding_id(n):
    out = rt.fixes_for(finding(n=n))
    assert out and all(f["number"] == n for f in out)


def test_quote_fills_the_slot_and_nothing_else():
    out = rt.fixes_for(finding(quote="Q.D. 5mg"))
    assert 'Q.D. 5mg' in out[0]["text"] and "{" not in out[0]["text"]


def test_fixed_output_hash():
    assert rt.table_hash() == EXPECTED_HASH


def test_no_model_or_network_import():
    tree = ast.parse((ROOT / "redesign_table.py").read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0])
    assert mods <= {"hashlib", "re"}, mods


def test_spec_words():
    text = (ROOT / "docs" / "specs" / "redesign.md").read_text(encoding="utf-8")
    assert "Illustrative redesign. Fictional. Not a medical device." in text
    assert "A human must decide." in text
    import render_redesign
    assert render_redesign.banned_hits(re.sub(r'"[^"\n]*"', " ", text)) == []
    for w in ("Recommended", "Better", "Approved"):
        assert f'"{w}"' in text  # the ban line names all three
    assert rt.TAG in text


# --- render part (card 14) ---
def test_render_module_exists():
    import render_redesign  # noqa: F401


def test_render_shows_tag_after_findings():
    import render_redesign
    assert rt.TAG in render_redesign.render([finding()])


def test_render_hides_redesign_for_non_confirmed():
    import render_redesign
    assert "What changed" not in render_redesign.render([finding(state="DISPUTED")])


@pytest.mark.parametrize("quote,line", [
    ("QD", 'Write the full words in place of "QD".'),
    ("5.0 mg", 'Remove the zero after the point in "5.0 mg".'),
    (".5 mg", 'Put a zero before the point in ".5 mg".'),
    ("Take 1 tablet QD", 'Write the full words in place of "Take 1 tablet QD".'),
])
def test_emr01_fix_a_is_picked_by_code_pattern(quote, line):
    assert rt.fixes_for(finding(quote=quote))[0]["text"] == line


def test_banned_words_not_in_table_or_spec():
    import render_redesign
    blob = " ".join(t for r in rt.TABLE.values() for t in r["fixes"]) + " " + " ".join(r["principle"] for r in rt.TABLE.values())
    assert render_redesign.banned_hits(blob) == []
    assert render_redesign.banned_hits("not approved") == ["approved"]  # the check can fail
    spec = (ROOT / "docs" / "specs" / "redesign.md").read_text(encoding="utf-8")
    assert render_redesign.banned_hits(re.sub(r'"[^"\n]*"', " ", spec)) == []


def test_no_internal_words_in_names_or_principles():
    for row in rt.TABLE.values():
        for text in [row["principle"]] + [n for n, _ in row["sources"]]:
            low = text.lower()
            assert "wiki" not in low and "summary note" not in low and ".md" not in low, text


@pytest.mark.parametrize("rule,quote,expect", [
    ("EMR-01", "Take 1 tablet QD", "Take 1 tablet every day"),
    ("EMR-01", "5.0 mg", "5 mg"),
    ("EMR-01", ".5 mg", "0.5 mg"),
    ("EMR-01", "U", None),
    ("ALT-03", "[OK]", "[OK] [Change] [Cancel]"),
    ("ALT-02", "Check dose", None),
])
def test_draw_words_come_from_the_table(rule, quote, expect):
    assert rt.draw_for(rule, quote) == expect


def test_alt03_short_principle_and_public_source():
    row = rt.TABLE["ALT-03"]
    assert row["principle"] == "Alert fatigue"
    assert row["sources"][0][0] == "Newton et al., J Med Internet Res 2026, DOI 10.2196/78676"
    assert "Action Selection" not in row["sources"][0][0]


def test_alt02_short_principle_name():
    assert rt.TABLE["ALT-02"]["principle"] == "Look-alike alerts"
    assert len(rt.TABLE["ALT-02"]["principle"].split()) <= 3
