"""Tests for pilot/rejudge.py (hft-team-08). No model call: the replay model only reads saved outputs."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "pilot")):
    if p not in sys.path:
        sys.path.insert(0, p)

import rejudge  # noqa: E402
import run_pilot  # noqa: E402

RESULT = ROOT / "pilot" / "rejudge_result.json"


def test_result_file_exists_and_is_labelled():
    assert RESULT.is_file(), "run python pilot/rejudge.py first"
    d = json.loads(RESULT.read_text(encoding="utf-8"))
    assert d["label"] == rejudge.LABEL
    for part in ("before", "after"):
        for k, v in d[part].items():
            assert v["label"] in (rejudge.LABEL, run_pilot.PILOT_LABEL)
            assert " of " in v["value"] and "%" not in v["value"]
    assert run_pilot.forbidden_keys(d) == []
    assert "%" not in RESULT.read_text(encoding="utf-8")


def test_result_matches_a_fresh_rejudge():
    fresh = rejudge.build()
    stored = json.loads(RESULT.read_text(encoding="utf-8"))
    assert fresh["after"] == stored["after"]


def test_no_replay_gap_and_no_model_class_used():
    d = json.loads(RESULT.read_text(encoding="utf-8"))
    assert d["after"]["replay_gap"]["value"] == "0 of 20"
    src = Path(rejudge.__file__).read_text(encoding="utf-8")
    assert "LocalModel" not in src and "urllib" not in src and "http" not in src.replace("https", "")


def test_replay_model_refuses_an_unsaved_call():
    m = rejudge.ReplayModel({"reader": ["PASS\nx"]})
    assert m.generate("reader", "p")[0] == "PASS\nx"
    with pytest.raises(rejudge.ReplayGap):
        m.generate("reader", "p")


def test_note_has_the_rejudge_section_with_the_label():
    text = (ROOT / "pilot" / "PILOT_NOTE.md").read_text(encoding="utf-8")
    assert rejudge.LABEL in text and "%" not in text.split("Re-judged by code")[1]
