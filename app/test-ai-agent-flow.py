#!/usr/bin/env python3
"""Headless checks for AI URL saving and clipboard-driven pipeline choices."""
from unittest.mock import patch
import json
import sys
from tempfile import TemporaryDirectory
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
import gui  # noqa: E402


class Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Label:
    def __init__(self):
        self.values = {}

    def config(self, **values):
        self.values.update(values)


class AppStub:
    def __init__(self):
        self.settings = {}
        self.clipboard = ""

    def set_setting(self, key, value):
        self.settings[key] = value

    def open_webpages(self, urls, **kwargs):
        self.opened_urls = list(urls)
        return "Test browser"

    def clipboard_get(self):
        return self.clipboard


class DialogStub:
    def __init__(self):
        self.app = AppStub()
        self.ai_url_status = Label()
        self.clip_label = Label()
        self._our_clip = "the copied prompt"
        self._last_clipboard_text = "the copied prompt"
        self._captured_answer = ""
        self._answer_choice_active = False
        self.callbacks = []
        self.choices = []
        self.alive = True

    def after_idle(self, callback):
        self.callbacks.append(callback)

    def _ask_after_ai_answer(self, answer):
        self.choices.append(answer)

    def winfo_exists(self):
        return self.alive

    def run(self, answer_override=None):
        self.ran = ("build", answer_override)

    def run_split_only(self):
        self.ran = ("split-only",)


def main():
    dialog = DialogStub()
    with patch.object(gui.simpledialog, "askstring", return_value="chatgpt.com"):
        gui.PipelineDialog.open_ai_page(dialog)
    assert dialog.app.settings["ai_agent_url"] == "https://chatgpt.com"
    assert dialog.app.opened_urls == ["https://chatgpt.com"]

    answer = "SEO Image titles:\n" + ("card details " * 40)
    dialog.app.clipboard = answer
    gui.PipelineDialog.refresh_clip(dialog)
    captured = answer.strip()
    assert dialog._captured_answer == captured
    assert len(dialog.callbacks) == 1
    dialog.callbacks.pop()()
    assert dialog.choices == [captured]

    with patch.object(gui.messagebox, "askyesnocancel", return_value=True):
        gui.PipelineDialog._ask_after_ai_answer(dialog, captured)
    assert dialog.ran == ("build", captured)
    with patch.object(gui.messagebox, "askyesnocancel", return_value=False):
        gui.PipelineDialog._ask_after_ai_answer(dialog, captured)
    assert dialog.ran == ("split-only",)
    with patch.object(gui.messagebox, "askyesnocancel", return_value=None):
        gui.PipelineDialog._ask_after_ai_answer(dialog, captured)
    assert dialog.ran == ("split-only",)

    original_settings_file = gui.SETTINGS_FILE
    try:
        with TemporaryDirectory() as tmp:
            gui.SETTINGS_FILE = Path(tmp) / "gui-settings.json"
            gui.SETTINGS_FILE.write_text(json.dumps({
                "store_name": "Example Cards",
                "currency_prefix": "€",
                "currency_name": "euros",
                "description_min_words": 250,
                "tag_count": 5,
                "listing_context": "Mention my custom item details.",
            }), encoding="utf-8")
            prompt = gui.load_prompt("multi")
            assert "for Example Cards" in prompt
            assert "nearest euros" in prompt and 'formatted as "€"' in prompt
            assert "250+ words" in prompt and "exactly 5 relevant tags" in prompt
            assert "Mention my custom item details." in prompt
            assert "{{" not in prompt
            assert "The first image (attached) is the FRONT" not in prompt
    finally:
        gui.SETTINGS_FILE = original_settings_file

    print("PASS AI URL prompt, persistence, and browser opening")
    print("PASS copied AI answer is detected and queued for a next-step choice")
    print("PASS yes/build, no/split-only, and cancel choices")
    print("PASS prompts use configured store/currency and omit removed FRONT notice")


if __name__ == "__main__":
    main()
