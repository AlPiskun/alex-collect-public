#!/usr/bin/env python3
"""Offline regression tests for facebook_feed.py first-run bootstrap.

Run from app/: python test-facebook-feed.py
Uses a fake requests module and a tiny synthetic Google product feed; no
network requests or seller credentials are involved.
"""
import csv
import os
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

    old_csv = pipeline / "woocommerce_import_20261018_120000.csv"
    with old_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["SKU", "Name"])
        writer.writeheader()
        writer.writerow({"SKU": "OLD", "Name": "Old unrelated batch"})
    os.utime(old_csv, (1, 1))

    batch_csv = pipeline / "woocommerce_import_20261019_120000.csv"
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
    if deltas and history_path.is_file():
        delta_ids = set(pd.read_excel(deltas[-1], dtype={"id": str})["id"])
        history_ids = set(pd.read_excel(history_path, dtype={"id": str})["id"])
    check("first run exits successfully under cp1252", result.returncode == 0,
          output[-1200:])
    check("first-run delta is exactly the current two-row Woo batch",
          len(deltas) == 1 and delta_ids == {"1002", "1003"},
          "delta ids=%r; output tail=%s" % (delta_ids, output[-800:]))
    check("first-run history baselines all live feed products",
          history_ids == {"1001", "1002", "1003"},
          "history ids=%r" % history_ids)
    check("preview identifies the selected Woo CSV and two-product delta",
          "woocommerce_import_20261019_120000.csv" in output and
          "New products: 2" in output and "2426" not in output,
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


def test_nested_gui_python_uses_console_interpreter(root):
    bindir = root / "python-bin"
    bindir.mkdir(parents=True, exist_ok=True)
    pythonw = bindir / "pythonw.exe"
    python = bindir / "python.exe"
    pythonw.write_bytes(b"")
    python.write_bytes(b"")

    calls = {}
    original_executable = sys.executable
    original_run = pipeline.subprocess.run

    class Result:
        returncode = 0

    def fake_run(command, **kwargs):
        calls["command"] = command
        return Result()

    try:
        sys.executable = str(pythonw)
        pipeline.subprocess.run = fake_run
        ok = pipeline.run_facebook_feed_script()
    finally:
        pipeline.subprocess.run = original_run
        sys.executable = original_executable

    check("nested feed launcher uses sibling python.exe",
          ok and calls.get("command", [None])[0] == str(python),
          repr(calls))


def main():
    with tempfile.TemporaryDirectory(prefix="alexcollect-feed-test-") as tmp:
        root = Path(tmp)
        test_first_run_delta_and_baseline(root)
        test_ambiguous_or_missing_batch_fails_closed(root)
        test_nested_gui_python_uses_console_interpreter(root)
    print("ALL CHECKS PASSED (%d)" % PASS if not FAIL else
          "FAILED %d   PASSED %d" % (FAIL, PASS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
