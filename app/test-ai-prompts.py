#!/usr/bin/env python3
"""Offline tests for the shipped AI prompt files.

The prompts are editable, and the .txt files next to gui.py win over the
embedded copies, so a rule that only lives in one of them can drift away from
the other without anyone noticing. These checks pin the one rule that matters
for titles: the "with grade" prompt puts the raw grade at the end of the SEO
title, and the "no grades" prompt keeps it out.

No Tk, no network, no API calls - the prompt text and the fallbacks are read
straight from disk.
"""
import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]

PASS = 0
FAIL = 0

WITH_GRADE = APP / "card description command - with grade.txt"
NO_GRADE = APP / "card description command.txt"

# The title shape the with-grade prompt must ask for, ending in the raw grade.
GRADED_TITLE_TAIL = "[Team/Series] [grade])"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s %s" % (name, extra))


def prompt_constants():
    """Read PROMPT_* dicts out of gui.py without importing tkinter."""
    tree = ast.parse((APP / "gui.py").read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.startswith("PROMPT_"):
                try:
                    found[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return found


def test_prompt_files():
    """The files that actually ship to the AI."""
    check("both prompt files exist", WITH_GRADE.is_file() and NO_GRADE.is_file())
    with_grade = WITH_GRADE.read_text(encoding="utf-8")
    no_grade = NO_GRADE.read_text(encoding="utf-8")

    check("the with-grade prompt ends the SEO title in the raw grade",
          GRADED_TITLE_TAIL in with_grade,
          "looked for %r" % GRADED_TITLE_TAIL)
    check("the no-grade prompt leaves the grade out of the title",
          "[grade]" not in no_grade)
    check("the grade still names the image suffixes in the with-grade prompt",
          "-front-[grade]" in with_grade and "-back-[grade]" in with_grade)

    # A truncated or half-saved prompt file would silently replace the
    # embedded copy, so make sure the seven parsed headers are still there.
    headers = ("SEO Image titles", "SEO Title", "Product Description",
               "Grade Estimate", "Price Recommendation",
               "Primary SEO Keyword", "WooCommerce Tag Bundle")
    missing = [h for h in headers if h not in with_grade]
    check("the with-grade prompt still asks for all seven headers",
          not missing, "missing=%s" % missing)


def test_embedded_fallbacks():
    """The copies baked into gui.py, used when a .txt file is missing."""
    consts = prompt_constants()
    fallbacks = consts.get("PROMPT_FALLBACKS", {})
    files = consts.get("PROMPT_FILES", {})

    check("gui.py defines both prompt fallbacks",
          set(fallbacks) == {"multi", "single"}, str(sorted(fallbacks)))
    check("the with-grade fallback ends the SEO title in the raw grade",
          GRADED_TITLE_TAIL in fallbacks.get("multi", ""))
    check("the no-grade fallback leaves the grade out of the title",
          "[grade]" not in fallbacks.get("single", ""))

    check("the 'multi' prompt points at the with-grade file",
          files.get("multi") == WITH_GRADE.name, str(files.get("multi")))
    check("the 'single' prompt points at the no-grade file",
          files.get("single") == NO_GRADE.name, str(files.get("single")))


def main():
    print("== 1. the prompt files that ship ==")
    test_prompt_files()

    print("== 2. the embedded fallbacks agree ==")
    test_embedded_fallbacks()

    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL AI PROMPT CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
