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
    check("hover-tooltip helper is present", hasattr(gui, "ToolTip"))


if __name__ == "__main__":
    main()
