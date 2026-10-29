#!/usr/bin/env python3
"""Offline regression tests for facebook_feed.py first-run bootstrap.

Run from app/: python test-facebook-feed.py
Uses a fake requests module and a tiny synthetic Google product feed; no
network requests or seller credentials are involved.
"""
import ast
import csv
import json
import os
from contextlib import redirect_stdout
from io import StringIO
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP / "pipeline"))
import card_pipeline as pipeline  # noqa: E402

FEED_SCRIPT = (APP / "pipeline" / "facebook_merchant_products"
               / "facebook_feed.py")
PASS = 0
FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("PASS", label)
    else:
        FAIL += 1
        print("FAIL", label, detail)


def make_sandbox(parent, batch_names):
    pipeline = parent / "pipeline"
    feed_dir = pipeline / "facebook_merchant_products"
    feed_dir.mkdir(parents=True)
    shutil.copyfile(FEED_SCRIPT, feed_dir / "facebook_feed.py")
    shutil.copyfile(APP / "user_settings.py", parent / "user_settings.py")
    (parent / "gui-settings.json").write_text(
        '{"woo_site_url":"https://example.test"}', encoding="utf-8")

    entries = [
        ("1001", "Older live card"),
        ("1002", "Fresh batch alpha"),
        ("1003", "Fresh batch beta"),
    ]
    namespace = "http://base.google.com/ns/1.0"
    items = []
    for pid, title in entries:
        items.append(
            "<item><g:id>%s</g:id><g:title>%s</g:title>"
            "<g:description>Test listing</g:description>"
            "<g:link>https://example.test/product/%s</g:link>"
            "<g:image_link>https://example.test/%s.jpg</g:image_link>"
            "<g:price>4.00 CAD</g:price></item>" %
            (pid, title, pid, pid))
    xml = ('<?xml version="1.0"?><rss xmlns:g="%s"><channel>%s</channel>'
           '</rss>' % (namespace, "".join(items)))
    (feed_dir / "fixture.xml").write_text(xml, encoding="utf-8")
    (feed_dir / "requests.py").write_text(
        "from pathlib import Path\n"
        "class Response:\n"
        "    status_code = 200\n"
        "    headers = {'CF-Cache-Status': 'DYNAMIC'}\n"
        "    content = Path(__file__).with_name('fixture.xml').read_bytes()\n"
        "def get(*args, **kwargs):\n"
        "    return Response()\n",
        encoding="utf-8")

    woo_dir = pipeline / "woocommerce_products"
    woo_dir.mkdir(parents=True)
    old_csv = woo_dir / "woocommerce_import_20261018_120000.csv"
    with old_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["SKU", "Name"])
        writer.writeheader()
        writer.writerow({"SKU": "OLD", "Name": "Old unrelated batch"})
    os.utime(old_csv, (1, 1))

    batch_csv = woo_dir / "woocommerce_import_20261019_120000.csv"
    with batch_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["SKU", "Name"])
        writer.writeheader()
        for number, name in enumerate(batch_names, 1):
            writer.writerow({"SKU": "NEW-%d" % number, "Name": name})

    return feed_dir


def run_script(feed_dir, answer):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"  # reproduce the Windows failure
    result = subprocess.run(
        [sys.executable, "-u", "facebook_feed.py"],
        cwd=str(feed_dir), input=answer.encode("ascii"),
        capture_output=True, env=env, timeout=60)
    output = (result.stdout + result.stderr).decode("utf-8", "replace")
    return result, output


def test_first_run_delta_and_baseline(root):
    feed_dir = make_sandbox(root / "matched", [
        "Fresh batch alpha", "Fresh batch beta"])
    result, output = run_script(feed_dir, "\n")
    # The machine date controls the actual filename, so find today's output.
    deltas = list(feed_dir.glob("facebook_delta_*.xlsx"))
    history_path = feed_dir / "facebook_history.xlsx"
    delta_ids = set()
    history_ids = set()
    delta_frame = pd.DataFrame()
    if deltas and history_path.is_file():
        delta_frame = pd.read_excel(deltas[-1], dtype={"id": str})
        delta_ids = set(delta_frame["id"])
        history_ids = set(pd.read_excel(history_path, dtype={"id": str})["id"])
    check("first run exits successfully under cp1252", result.returncode == 0,
          output[-1200:])
    check("first-run delta is exactly the current two-row Woo batch",
          len(deltas) == 1 and delta_ids == {"1002", "1003"},
          "delta ids=%r; output tail=%s" % (delta_ids, output[-800:]))
    check("Facebook workbook includes the requested condition",
          "CONDITION" in delta_frame and
          set(delta_frame["CONDITION"].dropna()) == {"Used - Good"},
          str(delta_frame.get("CONDITION", "missing").tolist()))
    check("Facebook workbook description uses the configurable template",
          "DESCRIPTION" in delta_frame and
          "Trading Card\\n\\nView and purchase here: "
          "https://example.test/product/1002" in
          str(delta_frame.iloc[0].get("DESCRIPTION", "")),
          str(delta_frame.iloc[0].get("DESCRIPTION", "") if not delta_frame.empty else "empty"))
    check("first-run history baselines all live feed products",
          history_ids == {"1001", "1002", "1003"},
          "history ids=%r" % history_ids)
    check("preview identifies the selected Woo CSV and two-product delta",
          "woocommerce_import_20261019_120000.csv" in output and
          "New products: 2" in output and "2426" not in output,
          output[-1000:])


def test_saved_feed_field_overrides_are_applied(root):
    feed_dir = make_sandbox(root / "custom-fields", ["Fresh batch alpha"])
    settings_path = feed_dir.parents[1] / "gui-settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings.update({
        "facebook_feed_title_template": "{title} - Test Edition",
        "facebook_feed_price_template": "{price:.2f}",
        "facebook_feed_condition": "Used - Good",
        "facebook_feed_description_template": (
            "Custom: {description} / {product_url}"),
        "facebook_feed_category": "Test Cards",
        "facebook_feed_id_template": "SKU-{id}",
        "facebook_feed_image_link_template": "https://images.example/{id}.jpg",
    })
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    result, output = run_script(feed_dir, "\n")
    deltas = list(feed_dir.glob("facebook_delta_*.xlsx"))
    frame = pd.read_excel(deltas[-1], dtype={"id": str}) if deltas else pd.DataFrame()
    check("custom Facebook field settings reach the generated workbook",
          result.returncode == 0 and not frame.empty and
          frame.iloc[0]["TITLE"] == "Fresh batch alpha - Test Edition" and
          float(frame.iloc[0]["PRICE"]) == 4.0 and
          frame.iloc[0]["CONDITION"] == "Used - Good" and
          frame.iloc[0]["CATEGORY"] == "Test Cards" and
          frame.iloc[0]["id"] == "SKU-1002" and
          frame.iloc[0]["image_link"] == "https://images.example/1002.jpg" and
          frame.iloc[0]["DESCRIPTION"] ==
          "Custom: Test listing / https://example.test/product/1002",
          output[-1000:])


def test_ambiguous_or_missing_batch_fails_closed(root):
    feed_dir = make_sandbox(root / "unmatched", ["Not in the live feed"])
    result, output = run_script(feed_dir, "")
    check("unmatched Woo CSV exits with a clear safe-stop",
          result.returncode == 2 and "Safe first-run bootstrap stopped" in output,
          output[-800:])
    check("failed bootstrap writes neither delta nor history",
          not list(feed_dir.glob("facebook_delta_*.xlsx")) and
          not (feed_dir / "facebook_history.xlsx").exists())


class FakePipe(list):
    """Lines the pipeline can read, and close, like a real pipe."""

    def close(self):
        pass


class FakeChild:
    """A stand-in for subprocess.Popen that answers like a helper would."""

    def __init__(self, lines=(), code=0, record=None):
        self.stdout = FakePipe(lines)
        self.returncode = code
        self.record = record if record is not None else {}

    def wait(self):
        return self.returncode


def test_nested_gui_python_uses_console_interpreter(root, monkeypatch):
    """Nested helpers run through the console interpreter, and are heard.

    The feed helper used to be launched with inherited handles, which on the
    user's machine produced "exited with code 3221225786" and not one line of
    explanation. Now it is started with pipes this file owns, so whatever it
    says reaches the console - and the interpreter choice is still the console
    python.exe beside pythonw.exe.
    """
    bindir = root / "python-bin"
    bindir.mkdir(parents=True, exist_ok=True)
    pythonw = bindir / "pythonw.exe"
    python = bindir / "python.exe"
    pythonw.write_bytes(b"")
    python.write_bytes(b"")

    attempts = []
    original_executable = sys.executable
    original_launcher = pipeline.stream_child
    original_popen = pipeline.subprocess.Popen

    def fake_stream(command, cwd):
        attempts.append({"command": command, "cwd": cwd})
        return 0, "--- Feed fetch diagnostics ---\nHTTP status : 200\n"

    try:
        sys.executable = str(pythonw)
        pipeline.stream_child = fake_stream
        ok = pipeline.run_facebook_feed_script()
    finally:
        pipeline.stream_child = original_launcher
        sys.executable = original_executable

    check("nested feed launcher uses sibling python.exe",
          ok and attempts and attempts[0]["command"][0] == str(python),
          repr(attempts))
    check("and runs the helper unbuffered, so nothing is lost",
          attempts and "-u" in attempts[0]["command"], repr(attempts))
    check("and runs it from the helper's own folder",
          attempts and attempts[0]["cwd"] ==
          pipeline.SCRIPT_DIR / "facebook_merchant_products", repr(attempts))
    check("a clean helper is not run twice", len(attempts) == 1, repr(attempts))

    #  A helper that says something and fails: keep its words, do not retry.
    attempts = []
    try:
        sys.executable = str(pythonw)
        pipeline.stream_child = lambda command, cwd: (
            attempts.append(command) or (1, "Traceback: ImportError: pandas\n"))
        ok = pipeline.run_facebook_feed_script()
    finally:
        pipeline.stream_child = original_launcher
        sys.executable = original_executable
    check("a helper that explains itself is not run a second time",
          not ok and len(attempts) == 1, repr(attempts))

    #  A helper that says nothing at all: that is a launcher problem, so the
    #  app's own interpreter gets one turn.
    attempts = []
    try:
        sys.executable = str(pythonw)
        pipeline.stream_child = lambda command, cwd: (
            attempts.append(command) or (3221225786, ""))
        ok = pipeline.run_facebook_feed_script()
    finally:
        pipeline.stream_child = original_launcher
        sys.executable = original_executable
    check("a silent failure is retried with the app's own interpreter",
          not ok and len(attempts) == 2 and
          attempts[0][0] == str(python) and attempts[1][0] == str(pythonw),
          repr(attempts))

    #  The child is started with pipes this file owns, and never inherits the
    #  app's stdin - a nested tool must not eat the answer meant for the app.
    popen_calls = []
    try:
        pipeline.subprocess.Popen = lambda command, **kw: (
            popen_calls.append((command, kw)) or FakeChild(
                ["one line\n", "two"], 0))
        with redirect_stdout(StringIO()) as said:
            code, text = pipeline.stream_child([str(python), "-u", "x.py"],
                                               root)
    finally:
        pipeline.subprocess.Popen = original_popen
    check("the child writes into a pipe the pipeline owns",
          popen_calls and popen_calls[0][1].get("stdout") is
          pipeline.subprocess.PIPE and
          popen_calls[0][1].get("stderr") is pipeline.subprocess.STDOUT,
          repr(popen_calls))
    check("and never reads the app's answers",
          popen_calls and popen_calls[0][1].get("stdin") is
          pipeline.subprocess.DEVNULL, repr(popen_calls))
    check("and is asked not to open a console window of its own",
          popen_calls and ("creationflags" in popen_calls[0][1] or
                           os.name != "nt"), repr(popen_calls))
    check("and is run unbuffered so a crash cannot swallow its output",
          popen_calls and popen_calls[0][1].get("env", {}).get(
              "PYTHONUNBUFFERED") == "1", repr(popen_calls))
    check("its output is kept whole, including a last line with no newline",
          code == 0 and text == "one line\ntwo", repr(text))
    check("and every line of it reached the console as it arrived",
          said.getvalue() == "one line\ntwo\n", repr(said.getvalue()))


def test_stale_workbook_is_named(root):
    """A failed export must never leave yesterday's workbook looking new.

    The name is dated by the day, so an old file opened from Explorer looks
    exactly like the run's own. The pipeline compares what was on disk before
    the step with what is there after it, and says so in words.
    """
    print()
    print("== a failed export does not pass off the old workbook ==")
    original = pipeline.SCRIPT_DIR
    folder = root / "feed-out"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        pipeline.SCRIPT_DIR = folder.parent
        check("no workbook at all is a known state",
              pipeline.facebook_delta_state() is None,
              str(pipeline.facebook_delta_state()))

        feed_dir = folder.parent / "facebook_merchant_products"
        feed_dir.mkdir(exist_ok=True)
        old_delta = feed_dir / "facebook_delta_2026-10-29.xlsx"
        old_delta.write_bytes(b"old")
        state = pipeline.facebook_delta_state()
        check("the workbook on disk is found with its date and size",
              state is not None and state[0] == str(old_delta) and
              state[2] == 3, str(state))
        note = pipeline.stale_facebook_note(state)
        check("an unchanged workbook is named, with when it was written",
              "facebook_delta_2026-10-29.xlsx" in note and
              "does not include this batch" in note, note)

        refreshed = feed_dir / "facebook_delta_2026-10-29.xlsx"
        refreshed.write_bytes(b"much newer content")
        check("a rewritten workbook gets no warning",
              pipeline.stale_facebook_note(state) == "",
              pipeline.stale_facebook_note(state))

        state = pipeline.facebook_delta_state()
        newer = feed_dir / "facebook_delta_2026-10-30.xlsx"
        newer.write_bytes(b"new day")
        os.utime(newer, (state[1] + 60, state[1] + 60))
        check("the newest workbook is the one compared",
              pipeline.facebook_delta_state()[0] == str(newer),
              str(pipeline.facebook_delta_state()))
        #  Taken before the newer file existed: a workbook written during the
        #  step is the run's own, so nothing is said about it.
        check("a workbook written during the step is not called old",
              pipeline.stale_facebook_note(state) == "",
              pipeline.stale_facebook_note(state))
    finally:
        pipeline.SCRIPT_DIR = original


def test_workbooks_held_open_are_named_before_any_work(root):
    """A workbook Excel is holding is named before the feed is even fetched."""
    source = FEED_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "locked_files")
    namespace = {"Path": Path}
    exec(compile(ast.Module(body=[node], type_ignores=[]),
                 str(FEED_SCRIPT), "exec"), namespace)
    locked = namespace["locked_files"]

    free = root / "free.xlsx"
    free.write_bytes(b"not really a workbook")
    check("a workbook nobody is using is not called locked",
          locked([free]) == [], locked([free]))

    def refusing(path, mode="r"):
        raise PermissionError(13, "Permission denied", str(path))

    found = locked([free], opener=refusing)
    check("a workbook held open by Excel is named",
          len(found) == 1 and str(free) in found[0][0], found)
    check("and the reason is kept, not thrown away",
          isinstance(found[0][1], OSError), found)
    check("a workbook that does not exist yet is not a lock",
          locked([root / "missing.xlsx"], opener=refusing) == [])

    answer_at = source.index("_held = locked_files(")
    fetch_at = source.index("new_df = parse_feed()")
    check("the answer comes before a single feed request is made",
          answer_at < fetch_at, (answer_at, fetch_at))
    check("and it says to close them, not just that something failed",
          "Close them and run the Facebook step again" in source)


def main():
    with tempfile.TemporaryDirectory(prefix="alexcollect-feed-test-") as tmp:
        root = Path(tmp)
        test_first_run_delta_and_baseline(root)
        test_saved_feed_field_overrides_are_applied(root)
        test_ambiguous_or_missing_batch_fails_closed(root)
        test_nested_gui_python_uses_console_interpreter(root, None)
        stale_root = root / "stale"
        stale_root.mkdir()
        test_stale_workbook_is_named(stale_root)
        locked_root = root / "locked"
        locked_root.mkdir()
        test_workbooks_held_open_are_named_before_any_work(locked_root)
    print("ALL CHECKS PASSED (%d)" % PASS if not FAIL else
          "FAILED %d   PASSED %d" % (FAIL, PASS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
