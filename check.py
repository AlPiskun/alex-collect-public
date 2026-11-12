#!/usr/bin/env python3
"""The whole checklist, in one command, from whichever folder you are in.

    python check.py                 run everything
    python check.py --list          just say what would run
    python check.py --only ebay     run the checks whose name contains "ebay"
    python check.py --only gui      (also matches "installer", "version", ...)

Why this exists: the checklist is forty-odd `python test-*.py` lines, and it
begins with `version_sync.py --check` - so running it from the wrong folder
answers "can't open file" for most of the list and then prints a plausible
failure from whatever older copy lives there, which reads like a broken pull
request when it is a broken folder. This file never guesses: it finds the
checkout from its own location (the folder it sits in), says which version and
which folder it is about to test, refuses by name when it is not in one, and
runs each script with the app folder as its working directory.

Nothing here knows what any test does. A script passes when it exits 0 and
fails when it does not; the last line each one prints is shown, because every
suite ends with its own tally.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

#: The order from docs/TESTING.md - the version check first, because it is the
#: one that fails while everything else is green.
ORDER = [
    "version_sync.py --check",
    "test-version.py",
    "test-gui.py",
    "test-gui-ergonomics.py",
    "test-ai-agent-flow.py",
    "test-custom-ai-commands.py",
    "test-user-settings.py",
    "test-plugin-manager.py",
    "test-core-sales.py",
    "test-facebook-feed.py",
    "test-facebook-delivery.py",
    "test-ebay-quicklist.py",
    "test-ebay-fill.py",
    "test-ebay-skip.py",
    "test-pipeline-output-organization.py",
    "test-category-plan.py",
    "test-market-rerun.py",
    "test-pipeline-listing.py",
    "test-ai-prompts.py",
    "test-process-utils.py",
    "test-photo-replace.py",
    "test-photo-queue.py",
    "test-photo-assign.py",
    "test-photo-sheets.py",
    "test-photo-panel.py",
    "test-tool-dialog.py",
    "test-linux-packaging.py",
    "test-image-store.py",
    "test-woo-orders.py",
    "test-sale-preview.py",
    "test-stock-compare.py",
    "test-cs-edit.py",
    "test-cs-proof.py",
    "test-cs-record.py",
    "test-cs-gallery.py",
    "test-cs-stage.py",
    "test-cs-listing.py",
    "test-cs-products.py",
    "test-market-stock.py",
    "test-stock-write.py",
    "test-woo-edit.py",
    "test-woo-create.py",
    "test-order-panel.py",
    "test-order-pdf.py",
    "test-order-sheet.py",
    "test-quote.py",
    "test-woo-media.py",
    "../installer/test-bundled-config.py",
    "test-check-runner.py",
]

#: What a checkout must hold for this to be the folder under review.
REQUIRED = ("app/version_sync.py", "app/gui.py", "app/test-version.py",
            "installer/alexcollect.iss", "MANIFEST.txt")


def find_root(start):
    """The checkout ``start`` belongs to, or ``None``.

    A folder is the checkout when it holds ``app/version_sync.py`` and the
    installer. Walked upwards, so ``python ../check.py`` from the app folder
    works as well as double-clicking the copy at the top.
    """
    here = Path(start).resolve()
    for candidate in [here, *here.parents]:
        if all((candidate / name).is_file() for name in REQUIRED):
            return candidate
    return None


def checkout_problems(root):
    """Every required file this folder does not have, by relative name."""
    return [name for name in REQUIRED if not (Path(root) / name).is_file()]


def version_of(root):
    """The version ``app/gui.py`` declares, read without importing Tk."""
    try:
        text = (Path(root) / "app" / "gui.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    found = re.search(r'(?m)^VERSION\s*=\s*["\']([^"\']+)["\']', text)
    return found.group(1) if found else ""


def plan(root):
    """The scripts to run, in order, as ``(name, path, args)`` triples.

    Any ``test-*.py`` that the checklist does not name is run last rather than
    forgotten: a test file nobody added to the list still gets run, and the
    runner says out loud that it was added that way.
    """
    app = Path(root) / "app"
    entries = []
    for line in ORDER:
        parts = line.split()
        script, args = parts[0], parts[1:]
        #  Resolved against the app folder, so the installer's own check -
        #  written "../installer/test-bundled-config.py" as the checklist
        #  writes it - lands on a real file rather than app/../installer.
        entries.append((Path(script).name, (app / script).resolve(), args))
    listed = {str(path.resolve()) for _name, path, _args in entries}
    for extra in sorted(app.glob("test-*.py")):
        if str(extra.resolve()) not in listed:
            entries.append((extra.name, extra, []))
    return entries


def final_line(text):
    """The last line a script printed that says something."""
    for line in reversed(str(text or "").splitlines()):
        if line.strip():
            return line.strip()
    return ""


#: Where a failing script's whole output is kept, so a paste is never the
#: only record of what happened.
FAILURE_DIR = "check-failures"


def save_failure(root, name, stdout, stderr):
    """Write one script's whole output to ``check-failures/<name>.txt``.

    A terminal shows a window of a run and a chat message shows less of it.
    The file holds everything the script said, so the next question - "what
    exactly did it print before that?" - is answered by opening one file.
    Returns the path, or ``None`` when even that cannot be written.
    """
    try:
        folder = Path(root) / FAILURE_DIR
        folder.mkdir(exist_ok=True)
        path = folder / (Path(name).stem + ".txt")
        path.write_text("$ python %s\n\n--- what it printed ---\n%s\n"
                        "--- what it printed to the error stream ---\n%s\n"
                        % (name, stdout or "", stderr or ""),
                        encoding="utf-8", errors="replace")
        return path
    except OSError:
        return None


def failed_checks(text, limit=6):
    """The lines of a failed script's output that name what failed.

    A suite prints one line per check, so the useful part of a failing run is
    the lines that *start* with FAIL - not the tally at the bottom, which says
    how many without saying which, and not a PASS line whose own name happens
    to contain the word ("PASS  the failed rows are the ones the plugin called
    errors"). Matching anywhere in the line showed six PASSes and hid the one
    failure, which is worse than showing nothing.
    """
    #  "FAIL " with a space: the tally at the bottom reads "FAILED 1   PASSED
    #  2", and that is a count, not a check.
    lines = [line.strip() for line in str(text or "").splitlines()
             if line.strip().upper().startswith("FAIL ")]
    return lines[:limit]


def error_tail(text, limit=4):
    """The last lines of a script's stderr - a traceback's own last words.

    A script that stops on an exception prints no tally at all, so its last
    line of standard output is an ordinary PASS and reads as though nothing
    went wrong. The traceback is where the reason is.
    """
    lines = [line.rstrip() for line in str(text or "").splitlines()
             if line.strip()]
    return lines[-limit:]


def verdict(returncode):
    return "PASS" if returncode == 0 else "FAIL"


def run(root, only=None, say=print):
    """Run the checklist, one script at a time; returns how many failed."""
    app = Path(root) / "app"
    entries = plan(root)
    if only:
        entries = [entry for entry in entries
                   if any(token.lower() in str(entry[1]).lower()
                          for token in only)]
    say("== Alex Collect %s, from %s ==" % (version_of(root) or "?",
                                             Path(root).resolve()))
    say("")
    failures = []
    for name, path, args in entries:
        if not path.is_file():
            say("  FAIL  %s - the file is not in this folder" % name)
            failures.append(name)
            continue
        #  ``-u`` because a script that dies mid-run otherwise loses whatever
        #  was still in its output buffer, and the last line shown would be
        #  from a minute before the crash - which is exactly the wrong clue.
        #  The two environment variables keep a Windows pipe from encoding the
        #  child's output as cp1252 and failing on a character it cannot hold.
        command = [sys.executable, "-u", str(path), *args]
        environment = dict(os.environ, PYTHONIOENCODING="utf-8",
                           PYTHONUTF8="1")
        result = subprocess.run(command, cwd=str(path.parent),
                                capture_output=True, text=True,
                                errors="replace", env=environment)
        line = final_line(result.stdout) or final_line(result.stderr)
        say("  %-4s  %-40s %s" % (verdict(result.returncode), name, line))
        if result.returncode != 0:
            failures.append(name)
            for said in failed_checks(result.stdout):
                say("          %s" % said)
            if result.stderr.strip():
                say("          the script stopped with an error:")
                for said in error_tail(result.stderr):
                    say("            %s" % said)
            kept = save_failure(root, name, result.stdout, result.stderr)
            if kept is not None:
                say("          its whole output is in %s" % kept)
    say("")
    if failures:
        say("FAILED %d of %d: %s" % (len(failures), len(entries),
                                     ", ".join(failures)))
        say("Run one on its own to read it in full, for example:")
        say("  cd %s" % app)
        say("  python %s" % failures[0])
        return len(failures)
    say("All %d checks passed." % len(entries))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run Alex Collect's whole test checklist from one command.")
    parser.add_argument("--list", action="store_true",
                        help="say what would run and stop")
    parser.add_argument("--only", action="append", metavar="TEXT",
                        help="run only the checks whose name contains TEXT "
                             "(may be given more than once)")
    parser.add_argument("--root", metavar="FOLDER",
                        help="the checkout to test (default: the folder this "
                             "file is in)")
    options = parser.parse_args(argv)

    start = Path(options.root) if options.root else Path(__file__).parent
    root = find_root(start)
    if root is None:
        missing = checkout_problems(start)
        print("This folder is not an Alex Collect checkout.")
        print("  looked in: %s" % Path(start).resolve())
        for name in missing:
            print("  missing:   %s" % name)
        print()
        print("That is why a checklist run here answers \"can't open file\" "
              "for most of it and then prints a failure from whatever older "
              "copy lives in this folder.")
        print("Run this file from the clone being reviewed instead, for "
              "example:")
        print("  python C:\\Users\\<you>\\Documents\\GitHub\\alex-collect-public"
              "\\check.py")
        return 2

    if options.list:
        print("== Alex Collect %s, from %s ==" % (version_of(root),
                                                  Path(root).resolve()))
        for name, path, args in plan(root):
            print("  %-40s %s" % (name, " ".join(args)))
        return 0
    return 1 if run(root, options.only) else 0


if __name__ == "__main__":
    sys.exit(main())
