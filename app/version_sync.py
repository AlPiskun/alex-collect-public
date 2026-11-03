#!/usr/bin/env python3
"""One number, in every place that has to say it.

Alex Collect's version lives in ``gui.py`` (``VERSION = "3.26"``). Everything
else in the repository has to agree with it: the two installers' ``AppVersion``
and the setup files they are named after, the Windows build script, the browser
user agents the tools send, the core version a plugin is checked against, the
package's own MANIFEST and README, the installer's consistency test, and the
tests that stamp a proof file with the app version.

That agreement used to be kept by hand, and it stopped: both ``.iss`` files
were left at 3.23 while the app said 3.26 - a setup that installed itself as an
older release than the one inside it. Nothing caught it, because the only test
that reads those files lives in ``installer/`` and nothing else looked.

This module is the list of every place, the check that they all agree, and the
command that moves them together::

    python version_sync.py            # what the version is, and whether it agrees
    python version_sync.py --check    # exit 1 unless every place agrees
    python version_sync.py 3.27       # move every place to 3.27

A place that is missing from the list is a place that will drift, so the check
also scans the repository for anything that *looks* like a version declaration
and refuses a number that is not the current one: a new file cannot be
forgotten quietly, and a pattern that stops matching its file is reported
rather than passed over.

It also reads the two installers back and prints what each one calls itself and
the setup file it builds - so "is the .iss up to date?" is answered on screen -
and it names any finished setup left in ``installer/Output/`` that was built as
another version, because double-clicking that one installs the older release.
"""
import re
import sys
from pathlib import Path

#: The repository root - this file lives one folder down, in ``app/``.
ROOT = Path(__file__).resolve().parent.parent

#: Every place the version has to appear, with the pattern that finds it.
#: Each pattern has exactly one group: the number itself. The app's own
#: ``VERSION`` line is first because it is the source of truth; the rest are
#: copies that must agree with it.
PLACES = (
    ("app/gui.py", "the app's own version",
     r'(?m)^VERSION = "(\d+\.\d+)"$'),
    ("app/cs_products.py", "the user agent the catalogue reader sends",
     r'AlexCollect/(\d+\.\d+)'),
    ("app/stock_write.py", "the user agent the stock writer sends",
     r'AlexCollect/(\d+\.\d+)'),
    ("app/woo_create.py", "the user agent the product creator sends",
     r'AlexCollect/(\d+\.\d+)'),
    ("app/plugin_manager.py", "the core version a plugin is checked against",
     r'core_version="(\d+\.\d+)"'),
    ("installer/alexcollect.iss", "the installer's AppVersion",
     r'(?m)^#define MyAppVersion "(\d+\.\d+)"$'),
    ("installer/alexcollect-bundled.iss",
     "the bundled installer's AppVersion",
     r'(?m)^#define MyAppVersion "(\d+\.\d+)"$'),
    ("installer/README.md", "the setup file names the build produces",
     r'AlexCollect-Setup-(?:bundled-)?(\d+\.\d+)\.exe'),
    ("installer/build-bundled.bat", "the setup file name the script prints",
     r'AlexCollect-Setup-(?:bundled-)?(\d+\.\d+)\.exe'),
    ("MANIFEST.txt", "the package's heading", r'(?m)^Alex Collect (\d+\.\d+) —'),
    ("README.md", "the README's heading", r'(?m)^# Alex Collect (\d+\.\d+)$'),
    ("docs/TESTING.md", "the line the suite prints when it starts",
     r'Alex Collect (\d+\.\d+), from'),
    ("app/test-cs-edit.py",
     "the app version a proof written in the panel is stamped with",
     r'app_version="(\d+\.\d+)"'),
    ("app/test-cs-proof.py",
     "the app version the proof-file checks are stamped with",
     r'app_version="(\d+\.\d+)"'),
)

#: Note what is *not* in the list: ``installer/test-bundled-config.py``. It
#: used to hold a copy of the version, and it now reads the number out of
#: ``gui.py`` and asserts the installers agree with it - a check, not a copy.
#: A copy that is not there cannot drift, and a hard-coded number reappearing
#: in that file shows up below as a stray.

#: What a version declaration looks like anywhere in the repository, listed
#: and unlisted files alike. This is the safety net: a file that starts naming
#: the version but is not in PLACES is reported instead of ignored.
#:
#: ``core_version=`` is deliberately *not* here. It is a real declaration, but
#: the plugin tests pass invented core versions to check that an old one is
#: refused ("2.22", "2.21"), and a scan that cannot tell a test's fixture from
#: the app's own number is a scan that cries wolf. That one place is checked
#: precisely, through PLACES.
DECLARATIONS = (
    r'AlexCollect/(\d+\.\d+)',
    r'(?m)^#define MyAppVersion "(\d+\.\d+)"',
    r'(?m)^VERSION = "(\d+\.\d+)"',
    r'APP_VERSION = "(\d+\.\d+)"',
    r'app_version="(\d+\.\d+)"',
    r'(?m)^Alex Collect (\d+\.\d+)',
    r'(?m)^# Alex Collect (\d+\.\d+)',
    r'AlexCollect-Setup-(?:bundled-)?(\d+\.\d+)\.exe',
    r'Alex Collect (\d+\.\d+), from',
)

#: The shapes a version may take: two numbers, the second padded to two digits
#: so that 3.9 sorts before 3.10. Anything else is a typo, not a version.
SHAPE = re.compile(r'^\d+\.\d{2}$')

#: Folders and suffixes the scan reads. Everything here is text a person
#: edits; a binary that carries a version is a build artefact, not a source.
SCAN_SUFFIXES = (".py", ".md", ".txt", ".iss", ".bat", ".sh", ".json",
                 ".example", ".cmd")
SKIP_FOLDERS = {".git", "__pycache__", "Output", "node_modules", ".venv",
                "runtime", ".pytest_cache"}


def source():
    """The file the version really lives in."""
    return ROOT / PLACES[0][0]


def read_version():
    """The app's own version, or ``""`` when the line cannot be found."""
    path = source()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    found = re.search(PLACES[0][2], text)
    return found.group(1) if found else ""


def found_in(path, pattern):
    """Every version a place names, in order. Empty when the pattern misses."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    return [match.group(1) for match in re.finditer(pattern, text)]


def places(paths=None):
    """``[(path, what, versions)]`` for every place, read as it is now."""
    listed = PLACES
    out = []
    for relative, what, pattern in listed:
        out.append((relative, what, found_in(ROOT / relative, pattern)))
    return out


def disagreements(version=""):
    """``[(path, what, versions)]`` for places that do not say ``version``.

    A place the pattern no longer finds at all is reported with an empty list:
    a line that moved or was reworded is exactly how the drift started.
    """
    version = version or read_version()
    return [(relative, what, found)
            for relative, what, found in places()
            if [value for value in found if value != version]]


def misconfigurations(version=""):
    """Places whose pattern finds nothing - a name that moved, not a number."""
    return [(relative, what) for relative, what, found in places()
            if not found]


def declarations(version=""):
    """``[(path, line_no, number, line)]`` for every stray declaration.

    Scans the whole repository, not the list: a file that has started naming
    the version and was never added to PLACES shows up here.
    """
    version = version or read_version()
    strays = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
            continue
        if any(part in SKIP_FOLDERS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for pattern in DECLARATIONS:
                for match in re.finditer(pattern, line):
                    if match.group(1) != version:
                        strays.append((str(path.relative_to(ROOT)), number,
                                       match.group(1), line.strip()[:90]))
    return strays


#: Setup files are artefacts, not sources: they are never bumped, they are
#: rebuilt. But an old one left in the output folder is worth saying out loud,
#: because double-clicking it installs the older release it was built for -
#: which is exactly what a stale .iss produces, and then outlives.
OUTPUT_FOLDER = "installer/Output"
SETUP_NAME = re.compile(r'AlexCollect-Setup-(?:bundled-)?(\d+\.\d+)\.exe$')


def setups(version=""):
    """``[(path, number)]`` for finished setups built as another version."""
    version = version or read_version()
    folder = ROOT / OUTPUT_FOLDER
    if not folder.is_dir():
        return []
    stale = []
    for path in sorted(folder.glob("AlexCollect-Setup-*.exe")):
        found = SETUP_NAME.search(path.name)
        if found and found.group(1) != version:
            stale.append((OUTPUT_FOLDER + "/" + path.name, found.group(1)))
    return stale


def installer_lines(version=""):
    """What each installer calls itself and the setup file it builds.

    Read out of the files rather than promised in a comment: this is the
    answer to "is the .iss up to date?" without opening either of them.
    """
    version = version or read_version()
    lines = []
    for relative, _what, _pattern in PLACES:
        if not relative.endswith(".iss"):
            continue
        try:
            text = (ROOT / relative).read_text(encoding="utf-8",
                                               errors="replace")
        except OSError:
            continue
        said = re.search(r'(?m)^#define MyAppVersion "(\d+\.\d+)"$', text)
        base = re.search(r'(?m)^OutputBaseFilename=(\S+)$', text)
        name = (base.group(1).replace("{#MyAppVersion}", version)
                if base else "(no output name)")
        lines.append("  %-34s AppVersion %s -> %s.exe"
                     % (relative, said.group(1) if said else "(none)", name))
    return lines


def render(path, pattern, version):
    """What a file would say with every version under ``pattern`` replaced."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return "", 0
    count = {"n": 0}

    def swap(match):
        count["n"] += 1
        return match.group(0).replace(match.group(1), version, 1)

    return re.sub(pattern, swap, text), count["n"]


def apply(version, dry_run=False):
    """Move every place to ``version``; ``[(path, changes)]`` for the report."""
    version = str(version or "").strip()
    if not SHAPE.match(version):
        raise ValueError("%r is not a version: it should look like 3.27"
                         % version)
    report = []
    for relative, what, pattern in PLACES:
        path = ROOT / relative
        text, count = render(path, pattern, version)
        if not count:
            report.append((relative, 0))
            continue
        if not dry_run:
            path.write_text(text, encoding="utf-8")
        report.append((relative, count))
    return report


def check(version=""):
    """Everything the check can say, as ``{"version", "wrong", "unfound",
    "strays"}``."""
    version = version or read_version()
    return {"version": version,
            "wrong": disagreements(version),
            "unfound": misconfigurations(version),
            "strays": declarations(version),
            "setups": setups(version)}


def report(version=""):
    """The check as lines a person reads, and whether it passed."""
    state = check(version)
    version = state["version"]
    lines = ["Alex Collect's version is %s, from %s."
             % (version or "(not found)", PLACES[0][0])]
    if not version:
        return lines, False
    if not SHAPE.match(version):
        lines.append("  ! %r is not shaped like a version (3.27, not 3.9)"
                     % version)
        return lines, False
    for relative, what, found in state["wrong"]:
        lines.append("  ! %s (%s) says %s, not %s"
                     % (relative, what, ", ".join(found) or "nothing",
                        version))
    for relative, what in state["unfound"]:
        lines.append("  ! %s (%s) names no version at all - the line moved"
                     % (relative, what))
    #  A file already reported above is not reported twice: the same fact,
    #  said once, in the words that name what the file is for.
    reported = {relative for relative, _what, _found in state["wrong"]}
    seen = set()
    for relative, number, value, line in sorted(state["strays"]):
        key = (relative, number)
        if key in seen or relative in reported:
            continue
        seen.add(key)
        lines.append("  ! %s:%d says %s, not %s (and is not in the list of "
                     "places): %s" % (relative, number, value, version, line))
    for relative, found in state["setups"]:
        lines.append("  ! %s is a finished setup for %s - running it installs "
                     "that release, not %s. Rebuild it, or delete it."
                     % (relative, found, version))
    good = not (state["wrong"] or state["unfound"] or state["strays"]
                or state["setups"])
    if good:
        lines.append("Every one of the %d places agrees, and nothing else in "
                     "the repository names a version." % len(PLACES))
        lines.extend(installer_lines(version))
    return lines, good


def main(argv=None):
    """``--check`` to test, a version to move them all, nothing to be told."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv and argv[0] == "--check":
        lines, good = report()
        print("\n".join(lines))
        return 0 if good else 1
    if not argv:
        lines, good = report()
        print("\n".join(lines))
        if good:
            print("\nNothing to do. To move every place at once:  "
                  "python version_sync.py <version>")
        else:
            print("\nFix them all with:   python version_sync.py <version>")
        return 0 if good else 1
    wanted = argv[0]
    try:
        changes = apply(wanted)
    except ValueError as exc:
        print(exc)
        return 2
    missed = [relative for relative, count in changes if not count]
    moved = [(relative, count) for relative, count in changes if count]
    for relative, count in moved:
        print("  %-34s %d line%s" % (relative, count,
                                     "" if count == 1 else "s"))
    for relative in missed:
        print("  ! %-32s names no version - check the line moved" % relative)
    print("\n%d place%s now say %s." %
          (len(moved), "" if len(moved) == 1 else "s", wanted))
    lines, good = report()
    if not good:
        print("\n".join(lines))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
