"""Keyword search over the framework criteria. Standard library only. No model, no vectors.

    python retrieve.py "query words"

Prints rule id, question and source id per hit. The text is context, not proof: the
referee still needs a quote found in the case text and a valid rule id.
A query with no shared word returns [] and the text "no match". Never a nearest guess.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parent / "framework" / "hf_framework_v0.json"
NEEDS = "needs source"
HEADING = "Context (not proof)"
MAX_HITS = 3
STOP = frozenset("a an the of and or to in on at is are be it its for from by with as this that "
                 "does do can each than not no any all there their they who may".split())


def _words(text) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", str(text).lower()) if w not in STOP}


def search(query, path=DEFAULT_FILE, limit=MAX_HITS) -> list:
    q = _words(query)
    if not q:
        return []
    crit = json.loads(Path(path).read_text(encoding="utf-8")).get("criteria", [])
    hits = []
    for i, c in enumerate(crit):
        text = " ".join(str(c.get(k, "")) for k in ("question", "failure_mode", "rule_id"))
        score = len(q & _words(text))
        if score:
            src = c.get("source")
            src = src if isinstance(src, str) and src.strip() else NEEDS
            hits.append(dict(id=c.get("id"), rule_id=c.get("rule_id"), question=c.get("question"),
                             failure_mode=c.get("failure_mode"), source=src,
                             sourced=src != NEEDS, score=score, _i=i))
    hits.sort(key=lambda h: (-h["score"], h["_i"]))
    for h in hits:
        del h["_i"]
    return hits[:limit]


def render(query, hits) -> str:
    if not hits:
        return f"{HEADING}\nno match"
    lines = [HEADING]
    for h in hits:
        tag = "" if h["sourced"] else " (not sourced)"
        lines.append(f"{h['rule_id'] or '(no rule id)'} | {h['question']} | source: {h['source']}{tag}")
    return "\n".join(lines)


def main(argv) -> int:
    q = " ".join(argv)
    print(render(q, search(q)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
