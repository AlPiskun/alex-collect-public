#!/usr/bin/env python3
"""Offline regression tests for `card_pipeline.py listing`.

The 2.36 refactor moved several locals into helper functions
(parse_listing_text, confirm_card_metadata). The image-rename stage still
needs two of them, and a missing binding there only shows up when the
pipeline actually reaches that stage - which is also the stage the GUI
skips when it passes --front-prefix/--back-prefix.

These checks run the real command both in-process (to prove the rename
confirmation is reached) and as a subprocess (to prove the shipped script
runs end to end).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parent
PIPELINE = APP / "pipeline"
sys.path[:0] = [str(APP), str(PIPELINE)]
import card_pipeline  # noqa: E402

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


def quiet():
    return redirect_stdout(StringIO())


def make_args(**overrides):
    base = dict(input="cards.txt", brand="O-Pee-Chee", category=None,
                subcategory=None, quantity=1, yes=False, image_ext="webp",
                front_prefix=None, back_prefix=None, copy=False,
                no_images=False, facebook=False, canadianshopper=False,
                canadianshopper_image_base_url=None, no_browser=True,
                feed_wait=0, feed_cookie=None, browser=None)
    base.update(overrides)
    return argparse.Namespace(**base)


def test_rename_stage_reaches_its_confirmation(root):
    """No NameError in the rename stage; the [y/N] prompt is asked."""
    asked = {"prompt": None}
    applied = {"ops": None}

    def fake_input(prompt=""):
        asked["prompt"] = prompt
        return "n"            # decline: nothing is moved, nothing is applied

    ops = [("src_a.webp", "dst_a.webp", "card 1 front")]
    with patch.object(card_pipeline, "OUTPUT_DIR", root), \
            patch.object(card_pipeline, "WOOCOMMERCE_DIR", root / "woo"), \
            patch.object(card_pipeline, "read_listing_text",
                         lambda path: "AI reply"), \
            patch.object(card_pipeline, "parse_listing_text",
                         lambda raw, args: [{"seo_title": "Card",
                                             "front_img": "dst_a.webp",
                                             "back_img": ""}]), \
            patch.object(card_pipeline, "print_parsed_cards",
                         lambda parsed: None), \
            patch.object(card_pipeline, "confirm_card_metadata",
                         lambda parsed, args: 1), \
            patch.object(card_pipeline, "build_rows",
                         lambda parsed, quantity: [{"SKU": "S1",
                                                    "Name": "Card",
                                                    "Regular price": "9",
                                                    "Categories": "Sports"}]), \
            patch.object(card_pipeline, "write_woocommerce_csv",
                         lambda rows: str(root / "woo" / "import.csv")), \
            patch.object(card_pipeline, "print_woocommerce_rows",
                         lambda rows, path: None), \
            patch.object(card_pipeline, "autodetect_prefixes",
                         lambda directory, ext: ("front", "back", {})), \
            patch.object(card_pipeline, "targets_from_rows",
                         lambda rows: ([], [])), \
            patch.object(card_pipeline, "plan_renames",
                         lambda *a, **k: (list(ops), [])), \
            patch.object(card_pipeline, "apply_renames",
                         lambda o, copy=False: applied.update(ops=o)), \
            patch.object(card_pipeline, "run_post_listing_uploads",
                         lambda args, parsed: None), \
            patch("builtins.input", fake_input), quiet():
        card_pipeline.cmd_listing(make_args())

    check("listing reaches the rename confirmation without a NameError",
          asked["prompt"] is not None and "Apply these" in asked["prompt"],
          repr(asked["prompt"]))
    check("declining the confirmation moves nothing", applied["ops"] is None)


def test_rename_applies_with_yes(root):
    """With -y the same stage applies the plan instead of prompting."""
    applied = {"ops": None}
    ops = [("src_a.webp", "dst_a.webp", "card 1 front")]

    def boom(*_a, **_k):
        raise AssertionError("no prompt should be asked when -y is set")

    with patch.object(card_pipeline, "OUTPUT_DIR", root), \
            patch.object(card_pipeline, "WOOCOMMERCE_DIR", root / "woo"), \
            patch.object(card_pipeline, "read_listing_text",
                         lambda path: "AI reply"), \
            patch.object(card_pipeline, "parse_listing_text",
                         lambda raw, args: [{"seo_title": "Card",
                                             "front_img": "dst_a.webp",
                                             "back_img": ""}]), \
            patch.object(card_pipeline, "print_parsed_cards",
                         lambda parsed: None), \
            patch.object(card_pipeline, "confirm_card_metadata",
                         lambda parsed, args: 1), \
            patch.object(card_pipeline, "build_rows",
                         lambda parsed, quantity: [{"SKU": "S1",
                                                    "Name": "Card",
                                                    "Regular price": "9",
                                                    "Categories": "Sports"}]), \
            patch.object(card_pipeline, "write_woocommerce_csv",
                         lambda rows: str(root / "woo" / "import.csv")), \
            patch.object(card_pipeline, "print_woocommerce_rows",
                         lambda rows, path: None), \
            patch.object(card_pipeline, "autodetect_prefixes",
                         lambda directory, ext: ("front", "back", {})), \
            patch.object(card_pipeline, "targets_from_rows",
                         lambda rows: ([], [])), \
            patch.object(card_pipeline, "plan_renames",
                         lambda *a, **k: (list(ops), [])), \
            patch.object(card_pipeline, "apply_renames",
                         lambda o, copy=False: applied.update(ops=o)), \
            patch.object(card_pipeline, "run_post_listing_uploads",
                         lambda args, parsed: None), \
            patch("builtins.input", boom), quiet():
        card_pipeline.cmd_listing(make_args(yes=True))

    check("-y applies the rename plan without prompting",
          applied["ops"] == ops, repr(applied["ops"]))


def test_shipped_script_runs_end_to_end(root):
    """The real script, copied the way an install looks, exits 0."""
    d = root / "install"
    (d / "pipeline").mkdir(parents=True)
    for name in ("card_pipeline.py", "output_history.py"):
        shutil.copyfile(PIPELINE / name, d / "pipeline" / name)
    for name in ("browser_utils.py", "user_settings.py", "plugin_manager.py",
                 "cs_listing.py"):
        shutil.copyfile(APP / name, d / name)
    (d / "gui-settings.json").write_text(
        json.dumps({"browser_name": "system"}), encoding="utf-8")

    # 18 tile images, the shape a split leaves behind (no prefixes given, so
    # the pipeline must auto-detect the two scan sets itself).
    out = d / "pipeline" / "output"
    out.mkdir()
    for stem in ("scan-1000000001", "scan-1000000002"):
        for n in range(1, 10):
            (out / ("%s_%d.webp" % (stem, n))).write_bytes(b"RIFF0000WEBP")

    listing_text = d / "_card_input.txt"
    listing_text.write_text("SEO Image titles:\n" + "x" * 220 + "\n",
                            encoding="utf-8")
    env = os.environ.copy()
    env["HOME"] = str(root / "home")
    env.pop("DISPLAY", None)
    result = subprocess.run(
        [sys.executable, str(d / "pipeline" / "card_pipeline.py"), "listing",
         "--input", str(listing_text), "--no-browser"],
        capture_output=True, text=True, timeout=300, input="Y\nY\n",
        env=env, cwd=str(d))

    output = result.stdout + result.stderr
    check("the shipped listing command exits 0", result.returncode == 0,
          output[-300:])
    check("no NameError or traceback", "NameError" not in output and
          "Traceback" not in output, output[-300:])
    check("the scan sets were auto-detected",
          "Auto-detected scan sets" in result.stdout or
          "No matching source files" in result.stdout, output[-300:])


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        print("== 1. the rename stage is reachable ==")
        stage = root / "stage"
        stage.mkdir()
        test_rename_stage_reaches_its_confirmation(stage)
        test_rename_applies_with_yes(stage)

        print("== 2. the shipped script runs end to end ==")
        test_shipped_script_runs_end_to_end(root)

    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL PIPELINE LISTING CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
