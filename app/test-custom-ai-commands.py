#!/usr/bin/env python3
"""Offline tests for editable AI command buttons and clipboard recognition."""
from pathlib import Path
import sys

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
import gui  # noqa: E402


def main():
    settings = {
        "store_name": "Example Card Shop",
        "currency_prefix": "C$",
        "currency_name": "Canadian dollars",
        "description_min_words": 300,
        "tag_count": 7,
        "listing_context": "Mention bilingual backs when visible.",
        "custom_ai_commands": [{
            "id": "grading-note",
            "name": "Condition notes",
            "tooltip": "Add a condition-specific instruction.",
            "prompt": "Write for {{STORE_NAME}}; target {{DESCRIPTION_MIN_WORDS}} words. {{LISTING_CONTEXT}}",
        }, {"name": "incomplete", "prompt": ""}],
    }
    buttons = gui.ai_prompt_buttons(settings)
    assert buttons[0][1] == "Add grades to titles"
    assert buttons[1][1] == "No grades in titles"
    assert "multiple grades" in buttons[0][2]
    assert "share one grade" in buttons[1][2]
    assert buttons[2] == ("custom_grading-note", "Condition notes",
                          "Add a condition-specific instruction.")

    prompt = gui.load_prompt("custom_grading-note", settings)
    assert prompt == (
        "Write for Example Card Shop; target 300 words. "
        "Mention bilingual backs when visible.")
    kind, _verdict = gui.classify_clipboard(prompt, settings)
    assert kind == "prompt"
    print("PASS revised default labels, tooltips, custom prompt buttons, placeholders, and clipboard detection")


if __name__ == "__main__":
    main()
