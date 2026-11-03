#!/usr/bin/env python3
"""Checks for version_sync - one number, in every place that has to say it.

The drift this exists for was real and silent: both Inno Setup scripts were
left at 3.23 while the app said 3.26, so the installer would have named itself
an older release than the copy inside it. Nothing failed, because the only test
that reads those two files lives in installer/ and nothing else looked at them.

So these checks are about the *net*, not the numbers: every place is found,
every place agrees, a bump would reach all of them, and a file that starts
naming a version without being listed is reported rather than ignored.

    Run:  python test-version.py
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))

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


import version_sync                                    # noqa: E402

ROOT = version_sync.ROOT


def test_the_version_is_where_it_says_it_is():
    print()
    print("== 1. one number, and it is a version ==")
    version = version_sync.read_version()
    check("the app declares a version in gui.py", bool(version), version)
    check("it is shaped like a version - x.yy, not x.y",
          bool(version_sync.SHAPE.match(version)), version)
    check("the file is the one the list names first",
          version_sync.source() == ROOT / "app" / "gui.py",
          str(version_sync.source()))
    check("the app states exactly one version",
          len(version_sync.found_in(ROOT / "app" / "gui.py",
                                    version_sync.PLACES[0][2])) == 1, "")


def test_every_place_agrees():
    print()
    print("== 2. every place that names it names the same one ==")
    state = version_sync.check()
    check("no place names a different version", not state["wrong"],
          str(state["wrong"]))
    check("and no place has lost its line entirely", not state["unfound"],
          str(state["unfound"]))
    check("nothing else in the repository names a version", not state["strays"],
          str(state["strays"][:6]))
    check("the check passes as a whole", version_sync.report()[1],
          "\n".join(version_sync.report()[0]))

    print()
    print("== 3. the two installers, which is what drifted ==")
    version = state["version"]
    for name in ("alexcollect.iss", "alexcollect-bundled.iss"):
        path = ROOT / "installer" / name
        text = path.read_text(encoding="utf-8")
        check("%s installs as %s" % (name, version),
              '#define MyAppVersion "%s"' % version in text, name)
        check("%s names the version once, in one place" % name,
              text.count('#define MyAppVersion') == 1, name)


def test_every_place_would_move():
    print()
    print("== 4. a bump would reach every one of them ==")
    version = version_sync.read_version()
    moved, missed = {}, []
    for relative, _what, pattern in version_sync.PLACES:
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        bumped, count = version_sync.render(path, pattern, "9.99")
        if not count or version not in text or "9.99" not in bumped:
            missed.append((relative, count))
            continue
        #  The old number must be gone from every position the pattern covers:
        #  a file with two versions in it would leave one behind.
        if re.search(pattern.replace("(\\d+\\.\\d+)", version), bumped):
            missed.append((relative, "left a copy behind"))
        moved[relative] = count
    check("every listed place can be moved", not missed, str(missed))
    check("and the move is a move, not an addition",
          all(count >= 1 for count in moved.values()) and
          len(moved) == len(version_sync.PLACES),
          str((len(moved), len(version_sync.PLACES))))
    #  dry_run must not touch anything: this ran over the real files.
    check("reading them changed nothing", version_sync.read_version() == version,
          version_sync.read_version())
    check("a version that is not a version is refused rather than written",
          _refused("3.9") and _refused("three") and _refused(""), "")


def _refused(value):
    try:
        version_sync.apply(value, dry_run=True)
    except ValueError:
        return True
    return False


def test_the_two_commands_agree():
    print()
    print("== 5. the command and the test say the same thing ==")
    result = subprocess.run(
        [sys.executable, str(APP / "version_sync.py"), "--check"],
        capture_output=True, text=True)
    check("python version_sync.py --check exits 0 when they agree",
          result.returncode == 0, result.stdout[-400:] + result.stderr[-200:])
    check("and it says how many places it looked at",
          str(len(version_sync.PLACES)) in result.stdout, result.stdout[-300:])
    check("the installer's own consistency test passes with them",
          _installer_test(), _installer_message())


def _installer_test():
    result = subprocess.run(
        [sys.executable, str(ROOT / "installer" / "test-bundled-config.py")],
        capture_output=True, text=True)
    globals()["_INSTALLER"] = result
    return result.returncode == 0


def _installer_message():
    result = globals().get("_INSTALLER")
    if result is None:
        return ""
    return (result.stdout or "") + (result.stderr or "")[-400:]


def test_a_copy_that_lags_is_caught():
    """The drift that happened, on a copy: caught, named, and repaired.

    Runs against a throwaway copy of the repository so the real one is only
    ever read. What is being proved is not that the numbers agree today -
    section 2 does that - but that a number left behind cannot pass.
    """
    print()
    print("== 6. a copy that lags is caught, and one command repairs it ==")
    real = version_sync.ROOT
    version = version_sync.read_version()
    untouched = {name: (real / name).read_text(encoding="utf-8")
                 for name in ("app/gui.py", "installer/alexcollect.iss",
                              "installer/alexcollect-bundled.iss")}
    scratch = Path(tempfile.mkdtemp(prefix="alex-version-"))
    try:
        repo = scratch / "repo"
        shutil.copytree(real, repo,
                        ignore=shutil.ignore_patterns(".git", "__pycache__",
                                                      "Output", "runtime"))
        version_sync.ROOT = repo

        lines, good = version_sync.report()
        check("an untouched copy agrees", good, "\n".join(lines))

        #  Put one installer back where both of them really were: 3.23.
        iss = repo / "installer" / "alexcollect.iss"
        iss.write_text(iss.read_text(encoding="utf-8").replace(
            '#define MyAppVersion "%s"' % version,
            '#define MyAppVersion "3.23"'), encoding="utf-8")
        lines, good = version_sync.report()
        said = "\n".join(lines)
        check("an installer left behind fails the check", not good, said)
        check("the failure names the file, the number it kept and the one "
              "that is current",
              "installer/alexcollect.iss" in said and "3.23" in said
              and version in said, said)
        check("and it does not blame the installer that agrees",
              "alexcollect-bundled.iss" not in said, said)
        check("the other check would have caught it too - the installer's "
              "own test now compares against gui.py",
              _installer_disagrees(scratch), "")

        #  A file that starts naming a version and is never added to the list.
        note = repo / "docs" / "new-note.md"
        note.write_text("# Alex Collect 3.20\n", encoding="utf-8")
        said = "\n".join(version_sync.report()[0])
        check("a new file naming a version is reported rather than ignored",
              "new-note.md" in said and "3.20" in said, said)
        note.unlink()

        #  One command, every copy - the installers included.
        version_sync.apply("9.99")
        lines, good = version_sync.report()
        check("one command moves every copy, installers included",
              good, "\n".join(lines))
        check("and every place really moved",
              version_sync.read_version() == "9.99"
              and not version_sync.disagreements("9.99"),
              str(version_sync.disagreements("9.99")))
        check("a version that is not a version is still refused",
              _refused("3.9") and _refused("three") and _refused(""), "")
    finally:
        version_sync.ROOT = real
        shutil.rmtree(scratch, ignore_errors=True)

    changed = [name for name, text in untouched.items()
               if (real / name).read_text(encoding="utf-8") != text]
    check("the real repository was only read", not changed, str(changed))
    check("and it still says what it said", version_sync.read_version() == version,
          version_sync.read_version())


def _installer_disagrees(scratch):
    """The installer's test, run inside the broken copy, must fail."""
    script = scratch / "repo" / "installer" / "test-bundled-config.py"
    result = subprocess.run([sys.executable, str(script)],
                            capture_output=True, text=True)
    return result.returncode != 0


def main():
    test_the_version_is_where_it_says_it_is()
    test_every_place_agrees()
    test_every_place_would_move()
    test_the_two_commands_agree()
    test_a_copy_that_lags_is_caught()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL VERSION CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
