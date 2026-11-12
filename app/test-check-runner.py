#!/usr/bin/env python3
"""The one-command runner: which checkout it is about to test, and what.

    python test-check-runner.py

No Tk and no network. `check.py` at the top of the repository runs the whole
checklist; this checks the runner itself - that it finds the checkout from
wherever it is started, that it refuses by name outside one instead of
printing a list of "can't open file" answers, that its plan is the checklist
and covers every test file that exists (including one nobody added to the
list), and that it reads a script's verdict the way the script reports it.
"""
import contextlib
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import check  # noqa: E402

PASS = 0
FAIL = 0


def check_that(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s %s" % (name, extra))


def fake_checkout(root, tests=("test-version.py",)):
    """A folder that looks like a checkout, with the tests named."""
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "installer").mkdir(parents=True, exist_ok=True)
    (root / "MANIFEST.txt").write_text("Alex Collect 9.99\n", encoding="utf-8")
    (root / "app" / "version_sync.py").write_text("print('ok')\n",
                                                  encoding="utf-8")
    (root / "app" / "gui.py").write_text('VERSION = "9.99"\n', encoding="utf-8")
    (root / "installer" / "alexcollect.iss").write_text("AppVersion=9.99\n",
                                                        encoding="utf-8")
    for name in tests:
        (root / "app" / name).write_text("print('ALL CHECKS PASSED')\n",
                                         encoding="utf-8")
    return root


# ----------------------------------------------------------- 1. the folder
def test_finds_the_checkout():
    print()
    print("== 1. which folder is being tested ==")
    check_that("the real repository is found from its app folder",
               check.checkout_problems(check.find_root(HERE) or HERE) == []
               and check.find_root(HERE) == ROOT,
               check.find_root(HERE))
    check_that("and from a folder deeper inside it",
               check.find_root(HERE / "pipeline") == ROOT,
               check.find_root(HERE / "pipeline"))
    bare = Path(tempfile.mkdtemp())
    check_that("a folder that is not a checkout is not called one",
               check.find_root(bare) is None, check.find_root(bare))
    check_that("and the runner names what that folder is missing",
               set(check.checkout_problems(bare)) == set(check.REQUIRED),
               check.checkout_problems(bare))
    #  The version is read from gui.py without importing it, because
    #  importing it needs Tk - which the folder being tested may not have.
    #  The number itself is never written down here: this file would then be
    #  another place a release has to be edited, and version_sync's own test
    #  reads every place for it.
    declared = check.version_of(ROOT)
    check_that("the version comes out of gui.py without importing Tk",
               bool(re.match(r"^\d+\.\d+$", declared)), declared)


def documented_order(page):
    """The scripts a markdown page's checklist tells a person to run."""
    import re as _re
    text = Path(page).read_text(encoding="utf-8")
    blocks = _re.findall(r"```(?:cmd|sh)\n(.*?)```", text, _re.S)
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        scripts = [line for line in lines if line.startswith("python ")]
        if any(line.startswith("python version_sync.py") for line in scripts):
            return [Path(line.split()[1].replace("\\", "/")).name
                    for line in scripts]
    return []


# ------------------------------------------------------------- 2. the plan
def test_the_plan():
    print()
    print("== 2. what it will run ==")
    entries = check.plan(ROOT)
    names = [name for name, _path, _args in entries]
    check_that("the version check goes first, with --check",
               entries[0][0] == "version_sync.py"
               and entries[0][2] == ["--check"], entries[0])
    check_that("and the version test straight after it",
               names[1] == "test-version.py", names[:3])
    check_that("the installer's own check is in the list",
               "../installer/test-bundled-config.py" in check.ORDER
               and "test-bundled-config.py" in names, names[-4:])
    check_that("every script it plans really exists",
               all(path.is_file() for _name, path, _args in entries),
               [str(path) for _name, path, _args in entries
                if not path.is_file()])
    on_disk = {path.name for path in (ROOT / "app").glob("test-*.py")}
    check_that("and no test file on disk is left out of the plan",
               on_disk <= set(names), sorted(on_disk - set(names)))
    check_that("and nothing had to be added past the checklist today",
               len(entries) == len(check.ORDER), (len(entries),
                                                  len(check.ORDER)))
    #  The two pages a person follows and the runner that runs the same work
    #  are one list: a test added to one and forgotten in the other is how the
    #  page stops being true.
    #  ORDER holds the script first (``version_sync.py --check``); the pages
    #  hold the whole command (``python version_sync.py --check``).
    typed = [Path(line.split()[0].replace("\\", "/")).name
             for line in check.ORDER]
    for page in (ROOT / "docs" / "TESTING.md", ROOT / "README.md"):
        said = documented_order(page)
        check_that("the list printed in %s is the runner's list"
                   % page.name, said == typed,
                   [name for name in typed if name not in said][:4])
    #  A test file nobody added to the list still runs - last, and it is in
    #  the plan rather than silently skipped.
    extra = fake_checkout(Path(tempfile.mkdtemp()) / "clone",
                          tests=("test-version.py", "test-brand-new.py"))
    planned = [name for name, _path, _args in check.plan(extra)]
    check_that("a test file not in the checklist is still run",
               planned[-1] == "test-brand-new.py", planned)
    check_that("and the ones the checklist names keep their order",
               planned[:2] == ["version_sync.py", "test-version.py"], planned[:3])


def test_the_failure_record():
    print()
    print("== 2b. a failure keeps its whole output ==")
    root = Path(tempfile.mkdtemp())
    kept = check.save_failure(root, "test-broken.py", "line one\nFAIL x\n",
                              "Traceback...\nValueError: nope\n")
    said = kept.read_text(encoding="utf-8") if kept else ""
    check_that("a failing script's output is written to a file",
               kept is not None and kept.parent.name == "check-failures",
               kept)
    check_that("with what it printed and what it died of",
               "FAIL x" in said and "ValueError: nope" in said, said[:120])
    check_that("named after the script, so two runs do not collide",
               kept.name == "test-broken.txt", kept.name)
    check_that("and the reason is never summarised away",
               "--- what it printed to the error stream ---" in said, "")


def test_a_crash_is_shown():
    print()
    print("== 2c. a script that dies is not summarised away ==")
    root = fake_checkout(Path(tempfile.mkdtemp()) / "clone",
                         tests=("test-version.py",))
    (root / "app" / "test-crash.py").write_text(
        "import sys\n"
        "print('  PASS  a check that passed')\n"
        "raise ValueError('the reason it stopped')\n", encoding="utf-8")
    run = subprocess.run(
        [sys.executable, str(ROOT / "check.py"), "--root", str(root),
         "--only", "crash"],
        capture_output=True, text=True, errors="replace")
    said = run.stdout + run.stderr
    check_that("a script that stops on an error fails the run",
               run.returncode == 1, run.returncode)
    check_that("and the reason is on screen, not only the last PASS line",
               "the reason it stopped" in said, said[-500:])
    check_that("with the failing lines it printed, named",
               "FAIL" in said or "stopped with an error" in said, said[-500:])
    kept = root / "check-failures" / "test-crash.txt"
    check_that("its whole output is kept in check-failures/", kept.is_file(),
               sorted(str(p) for p in (root / "check-failures").glob("*"))
               if (root / "check-failures").is_dir() else "no folder")
    check_that("and the file holds the traceback, not a summary",
               kept.is_file() and "ValueError" in kept.read_text(encoding="utf-8"),
               "")


# ----------------------------------------------------------- 3. the reading
def test_reading_a_verdict():
    print()
    print("== 3. how a script's answer is read ==")
    check_that("a script that exits 0 passes",
               check.verdict(0) == "PASS" and check.verdict(1) == "FAIL", "")
    check_that("the last line it printed is the one shown",
               check.final_line("noise\n\nALL CHECKS PASSED (7)\n\n")
               == "ALL CHECKS PASSED (7)", "")
    check_that("a script that printed nothing says nothing rather than crash",
               check.final_line("") == "" and check.final_line(None) == "", "")


# ------------------------------------------------------- 4. the two refusals
def test_it_says_so_out_loud():
    print()
    print("== 4. the wrong folder is named, not measured ==")
    bare = Path(tempfile.mkdtemp())
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = check.main(["--root", str(bare)])
    said = output.getvalue()
    check_that("outside a checkout the runner refuses (exit 2)", code == 2, code)
    check_that("and says plainly that this is not one",
               "not an Alex Collect checkout" in said, said[:160])
    check_that("naming the folder it looked in", str(bare) in said, said[:400])
    check_that("the file it is missing by name", "app/version_sync.py" in said,
               said[:400])
    check_that("and the folder that would have worked",
               "check.py" in said and "clone being reviewed" in said,
               said[-300:])
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = check.main(["--root", str(ROOT), "--list"])
    said = output.getvalue()
    check_that("--list exits 0 and names the version and folder",
               code == 0 and check.version_of(ROOT) in said
               and str(ROOT) in said, said[:200])
    check_that("--list names every script in the plan",
               all(name in said for name, _p, _a in check.plan(ROOT)), "")


# -------------------------------------------------------- 5. one real run
def test_a_real_run():
    print()
    print("== 5. it really runs the scripts ==")
    run = subprocess.run(
        [sys.executable, str(ROOT / "check.py"), "--only", "version"],
        capture_output=True, text=True, errors="replace")
    said = run.stdout + run.stderr
    check_that("a run of the version checks exits 0", run.returncode == 0,
               (run.returncode, said[-400:]))
    check_that("and shows both scripts' own last lines",
               "ALL VERSION CHECKS PASSED" in said, said[-400:])
    check_that("with a banner naming the version and the folder",
               "== Alex Collect %s, from " % check.version_of(ROOT) in said,
               said[:200])
    check_that("and a tally at the end", "checks passed" in said, said[-200:])
    bad = fake_checkout(Path(tempfile.mkdtemp()) / "clone",
                        tests=("test-version.py", "test-broken.py"))
    (bad / "app" / "test-broken.py").write_text(
        "import sys\nprint('FAILED 1 PASSED 0')\nsys.exit(1)\n",
        encoding="utf-8")
    run = subprocess.run(
        [sys.executable, str(ROOT / "check.py"), "--root", str(bad),
         "--only", "broken"],
        capture_output=True, text=True, errors="replace")
    said = run.stdout + run.stderr
    check_that("a failing script makes the run fail", run.returncode == 1,
               run.returncode)
    check_that("and it is named in the tally, not buried above it",
               "FAILED 1 of 1: test-broken.py" in said, said[-300:])
    check_that("with the command that reads it in full",
               "python test-broken.py" in said, said[-300:])


def main():
    print("=" * 62)
    print("  THE ONE-COMMAND RUNNER")
    print("=" * 62)
    test_finds_the_checkout()
    test_the_plan()
    test_the_failure_record()
    test_a_crash_is_shown()
    test_reading_a_verdict()
    test_it_says_so_out_loud()
    test_a_real_run()
    print()
    print("=" * 62)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL CHECK RUNNER CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
