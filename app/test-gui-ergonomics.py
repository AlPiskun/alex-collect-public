#!/usr/bin/env python3
"""Headless checks for compact task navigation and output scrollback behavior."""
from pathlib import Path
import sys
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gui  # noqa: E402


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


class YView:
    def __init__(self, last):
        self.last = last

    def yview(self):
        return (0.0, self.last)


def main():
    # New output should follow the tail only until the user scrolls up.
    check("output auto-follows at the bottom",
          gui.App._console_following_tail(
              SimpleNamespace(console=YView(1.0))))
    check("output preserves an earlier scroll position",
          not gui.App._console_following_tail(
              SimpleNamespace(console=YView(0.65))))
    task_ids = {pid for _group, ids in gui.groups_for(True) for pid in ids}
    check("settings, plugins, and logs are removed from task buttons",
          not ({"cookie", "plugins", "logs"} & task_ids))
    core_ids = {pid for _group, ids in gui.groups_for(False) for pid in ids}
    check("core task menu omits plugin-only tasks",
          not ({"stage", "wire", "zerostock"} & core_ids))
    check("task sections are Sell, After a sale, and Photos",
          [name for name, _ids in gui.groups_for(True)] ==
          ["Sell a new batch", "After a sale", "Photos"])
    check("CanadianShopper repair has a short label and plugin-aware tooltip",
          gui.MENU_LABELS["rerun"] == "Re-point photos" and
          "CanadianShopper plugin" in gui.BLURBS["rerun"])
    check("hover-tooltip helper is present", hasattr(gui, "ToolTip"))
    check("built-in AI action names are clear",
          gui.PROMPT_TITLES == {"multi": "Add grades to titles",
                                "single": "No grades in titles"})
    check("built-in AI actions explain grade inclusion or omission",
          "multiple grades" in gui.PROMPT_TOOLTIPS["multi"] and
          "one grade" in gui.PROMPT_TOOLTIPS["single"])
    source = (HERE / "gui.py").read_text(encoding="utf-8")
    check("category console has room for at least twenty rows",
          "height=20" in source)


if __name__ == "__main__":
    main()
