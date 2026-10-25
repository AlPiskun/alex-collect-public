#!/usr/bin/env python3
"""Offline tests for process_utils.no_window_kwargs() and its one caller.

Alex Collect runs on Windows with pythonw, so it has no console. Without
CREATE_NO_WINDOW every tool it launches is handed a fresh DOS window that sits
on the desktop until the tool exits - the "separate DOS window opens" bug.
These checks run on Linux too: they only assert which flags are requested,
never start a process or open a window.
"""
import ast
import sys
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]
import process_utils  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s %s" % (name, extra))


def test_flag_value():
    """The constant must be the documented Win32 value."""
    check("CREATE_NO_WINDOW is the documented 0x08000000",
          process_utils.CREATE_NO_WINDOW == 0x08000000,
          hex(process_utils.CREATE_NO_WINDOW))


def test_platform_switch():
    """Windows hides the console; every other platform asks for nothing."""
    with patch.object(process_utils.os, "name", "nt"):
        kwargs = process_utils.no_window_kwargs()
    check("on Windows the child console is suppressed",
          kwargs == {"creationflags": process_utils.CREATE_NO_WINDOW},
          str(kwargs))

    with patch.object(process_utils.os, "name", "posix"):
        kwargs = process_utils.no_window_kwargs()
    check("elsewhere no creation flags are passed", kwargs == {}, str(kwargs))


def test_runner_uses_it():
    """The GUI's tool runner must actually hand the flags to Popen."""
    tree = ast.parse((APP / "gui.py").read_text(encoding="utf-8"))

    imported = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "process_utils":
            imported |= any(a.name == "no_window_kwargs" for a in node.names)
    check("gui.py imports no_window_kwargs from process_utils", imported)

    def splats_helper(call):
        return any(kw.arg is None and isinstance(kw.value, ast.Call) and
                   getattr(kw.value.func, "id", "") == "no_window_kwargs"
                   for kw in call.keywords)

    popen_calls = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and
                isinstance(node.func, ast.Attribute) and
                node.func.attr == "Popen" and
                getattr(node.func.value, "id", "") == "subprocess"):
            popen_calls.append(node)

    # gui.py opens a folder on macOS/Linux with Popen; only the tool runner
    # pipes a console program, so at least one call must carry the flags.
    check("the tool runner passes the no-window flags to Popen",
          any(splats_helper(c) for c in popen_calls),
          "%d Popen call(s), none splatting no_window_kwargs()" %
          len(popen_calls))


def main():
    print("== 1. the flag itself ==")
    test_flag_value()

    print("== 2. only Windows is affected ==")
    test_platform_switch()

    print("== 3. the GUI runner uses it ==")
    test_runner_uses_it()

    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL PROCESS LAUNCH CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
