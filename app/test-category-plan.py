#!/usr/bin/env python3
"""Keep the category confirmation for a nine-card batch compact and visible."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
from unittest.mock import patch

APP = Path(__file__).resolve().parent
PIPELINE = APP / "pipeline"
sys.path[:0] = [str(APP), str(PIPELINE)]
import card_pipeline  # noqa: E402


def main():
    parsed = [{
        "seo_title": "Card %02d Player %d " % (i, i) + "X" * 120,
        "category": "Sports Trading Cards",
        "subcategory": "Hockey",
    } for i in range(1, 10)]
    output = StringIO()
    def answer(prompt):
        print(prompt, end="")
        return "y"
    with patch("builtins.input", side_effect=answer), redirect_stdout(output):
        card_pipeline.confirm_categories(parsed)
    text = output.getvalue()
    rows = [line for line in text.splitlines()
            if " -> " in line and line.strip()[:1].isdigit()]
    assert len(rows) == 9, text
    assert all("Card %02d" % i in rows[i - 1] for i in range(1, 10))
    assert all("Sports Trading Cards > Hockey" in row for row in rows)
    assert all(len(row) <= 100 and "..." in row for row in rows)
    assert "Are these categories correct?" in text
    print("PASS the category question prints all nine cards in nine compact rows")


if __name__ == "__main__":
    main()
