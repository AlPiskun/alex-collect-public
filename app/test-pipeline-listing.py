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
from contextlib import redirect_stderr, redirect_stdout
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
            patch.object(card_pipeline, "maybe_create_woocommerce_products",
                         lambda args, path: (False, "")), \
            patch.object(card_pipeline, "run_post_listing_uploads",
                         lambda args, parsed, **kw: None), \
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
            patch.object(card_pipeline, "maybe_create_woocommerce_products",
                         lambda args, path: (False, "")), \
            patch.object(card_pipeline, "run_post_listing_uploads",
                         lambda args, parsed, **kw: None), \
            patch("builtins.input", boom), quiet():
        card_pipeline.cmd_listing(make_args(yes=True))

    check("-y applies the rename plan without prompting",
          applied["ops"] == ops, repr(applied["ops"]))


def test_dark_back_variant_keeps_its_front(root):
    """A dark-back card's front is renamed like any other card's.

    A variant card is named after the variant *and* the side, so
    "16-...-Kings-dark-back-front" contains the word "-back" twice. The side
    used to be decided by "does the name contain -front/ -back anywhere",
    which matched both, printed "a front and back were joined together",
    dropped the front title - and left that card's front image unrenamed.
    Four cards in one real batch were dark backs.
    """
    folder = root / "renames"
    folder.mkdir()
    dark_front = ("16-Neil-Komadoski-1972-73-O-Pee-Chee-Los-Angeles-Kings-"
                  "dark-back-front")
    dark_back = dark_front[:-len("front")] + "back"
    plain_front = "7-Foo-1972-73-O-Pee-Chee-Minnesota-North-Stars-front"
    plain_back = plain_front[:-len("front")] + "back"

    #  parse_images() answers for ONE card, which is how the AI sheet text is
    #  read - two titles in, a front and a back out.
    parsed = card_pipeline.parse_images(
        "\n".join((dark_front, dark_back)))
    check("a dark-back card keeps both of its image titles",
          parsed[0] == dark_front + ".webp" and parsed[1] == dark_back + ".webp",
          repr(parsed))
    parsed = card_pipeline.parse_images(
        "\n".join((plain_front, plain_back)))
    check("a plain card's titles are untouched",
          parsed == (plain_front + ".webp", plain_back + ".webp"), repr(parsed))

    #  The tiles are written as WebP, so the name says WebP - a title ending
    #  in another extension is named in the pipeline's format, not the
    #  title's. A ".jpg" name on a WebP file is what made the eBay Quick
    #  List's image links lie about the pictures.
    parsed = card_pipeline.parse_images(
        plain_front + ".jpg\n" + plain_back + ".JPG")
    check("a title that says .jpg is named .webp, because it is a WebP file",
          parsed == (plain_front + ".webp", plain_back + ".webp"), repr(parsed))
    parsed = card_pipeline.parse_images(
        "\n".join((dark_front + ".png", dark_back)))
    check("and a title that says .png is named .webp too",
          parsed == (dark_front + ".webp", dark_back + ".webp"), repr(parsed))

    #  The fix must not resurrect the accident it replaced: two whole titles
    #  run together are still refused, not renamed to whichever side came
    #  last.
    joined = "16-Foo-front-16-Bar-back"
    err = StringIO()
    with redirect_stderr(err):
        parsed = card_pipeline.parse_images(joined + "\n16-Bar-back")
    check("two whole titles run together are still refused",
          parsed == ("", "16-Bar-back.webp") and
          "joined together" in err.getvalue(), repr((parsed, err.getvalue())))

    rows = [{"Images": ", ".join((dark_front + ".webp", dark_back + ".webp"))},
            {"Images": ", ".join((plain_front + ".webp", plain_back + ".webp"))}]
    fronts, backs = card_pipeline.targets_from_rows(rows)
    check("the dark-back front is the front, not both sides",
          fronts.get(1) == dark_front + ".webp" and
          backs.get(1) == dark_back + ".webp",
          "fronts=%r backs=%r" % (fronts, backs))
    check("no card plans one file as both its front and its back",
          all(backs.get(pos) != name for pos, name in fronts.items()),
          "fronts=%r backs=%r" % (fronts, backs))

    #  End to end: the four sources a real scan would leave behind, renamed
    #  through the same plan the listing stage uses.
    #  Two cards, so the second is position 2. A back sleeve is mirrored:
    #  back position 3 belongs to the card in front position 1, and the middle
    #  column (back position 2) to the card in front position 2.
    for name in ("scan-front_1.png", "scan-front_2.png",
                 "scan-back_3.png", "scan-back_2.png"):
        (folder / name).write_bytes(b"image")
    ops, missing = card_pipeline.plan_renames(
        str(folder), fronts, backs, "scan-front", "scan-back", "png")
    by_target = {Path(dst).name: Path(src).name for src, dst, _label in ops}
    check("a dark-back card's front image is renamed",
          by_target.get(dark_front + ".webp") == "scan-front_1.png",
          repr(by_target))
    check("a dark-back card's back image is renamed",
          by_target.get(dark_back + ".webp") == "scan-back_3.png",
          repr(by_target))
    check("the plain card is renamed the same way",
          by_target.get(plain_front + ".webp") == "scan-front_2.png" and
          by_target.get(plain_back + ".webp") == "scan-back_2.png",
          repr(by_target))
    check("nothing is reported missing for either card",
          not [m for m in missing if "position 1 " in m
               or "position 2 " in m], repr(missing))


def test_shipped_script_runs_end_to_end(root):
    """The real script, copied the way an install looks, exits 0."""
    d = root / "install"
    (d / "pipeline").mkdir(parents=True)
    for name in ("card_pipeline.py", "output_history.py"):
        shutil.copyfile(PIPELINE / name, d / "pipeline" / name)
    #  Deliberately NOT cs_listing.py: this is the layout a batch folder has,
    #  and the shipped script has to run there. 2.66 made that a hard import
    #  and every pipeline run outside the app died with ModuleNotFoundError.
    for name in ("browser_utils.py", "user_settings.py", "plugin_manager.py"):
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


def test_runs_without_the_other_features(tmp_path):
    """The shipped script, with only what a batch folder carries."""
    print()
    print("== 3. the pipeline runs on its own, without the app's other modules ==")
    d = Path(tmp_path) / "alone"
    (d / "pipeline").mkdir(parents=True)
    shutil.copyfile(PIPELINE / "card_pipeline.py",
                    d / "pipeline" / "card_pipeline.py")
    shutil.copyfile(PIPELINE / "output_history.py",
                    d / "pipeline" / "output_history.py")
    for name in ("browser_utils.py", "user_settings.py", "plugin_manager.py"):
        shutil.copyfile(APP / name, d / name)
    (d / "gui-settings.json").write_text(json.dumps({"browser_name": "system"}),
                                         encoding="utf-8")
    cs_listing_present = (d / "cs_listing.py").is_file()
    check("the folder really has no cs_listing.py to borrow",
          not cs_listing_present, str(cs_listing_present))

    run = subprocess.run([sys.executable, str(d / "pipeline" / "card_pipeline.py"),
                          "--help"], capture_output=True, text=True, timeout=120)
    check("it starts and answers --help", run.returncode == 0,
          run.stderr[-300:])
    check("and does not die on a missing module",
          "ModuleNotFoundError" not in (run.stderr or ""), run.stderr[-300:])

    script = (
        "import sys, json\n"
        "sys.path[:0] = [%r, %r]\n"
        "import card_pipeline as cp\n"
        "print(json.dumps({'columns': cp.CANADIANSHOPPER_FIELDNAMES,\n"
        "                  'category': cp.CANADIANSHOPPER_CATEGORY,\n"
        "                  'province': cp.CANADIANSHOPPER_PROVINCE,\n"
        "                  'flat': cp.CANADIANSHOPPER_FLAT_SHIPPING,\n"
        "                  'free': cp.CANADIANSHOPPER_FREE_SHIPPING,\n"
        "                  'batch': cp.CANADIANSHOPPER_BATCH_SIZE}))\n"
        % (str(d), str(d / "pipeline")))
    run = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, timeout=120, cwd=str(d))
    decoded = {}
    if run.returncode == 0:
        decoded = json.loads(run.stdout.strip().splitlines()[-1])
    check("its import template is the canonical fourteen columns",
          decoded.get("columns") == [
              "title", "price_cad", "category", "description", "image_url",
              "inventory", "is_made_to_order", "ship_from_province",
              "shipping_flat_cad", "free_shipping", "handling_days",
              "transit_days", "sizes", "colors"], str(decoded)[:300])
    check("and its defaults are the same as the app's",
          (decoded.get("category"), decoded.get("province"),
           decoded.get("flat"), decoded.get("free"), decoded.get("batch")) ==
          ("Antiques & Collectibles", "ON", "4.00", "false", 500),
          str(decoded))


def test_plugin_version_reading(root):
    """What the pipeline is allowed to say about the plugin it found.

    1.0.27 is the version that streams the publisher, so its question is
    visible; anything older - or unreadable - gets the safe sentence instead
    of a claim the plugin cannot back up.
    """
    print()
    print("== 4. the plugin's own version decides what may be claimed ==")
    check("1.0.27 is the streaming version",
          card_pipeline._cs_version_at_least("1.0.27",
                                             card_pipeline.CS_STREAM_VERSION))
    check("1.0.26 is not",
          not card_pipeline._cs_version_at_least(
              "1.0.26", card_pipeline.CS_STREAM_VERSION))
    check("a later minor version still counts",
          card_pipeline._cs_version_at_least(
              "1.1.0", card_pipeline.CS_STREAM_VERSION))
    check("an unreadable version is never treated as new",
          not card_pipeline._cs_version_at_least(
              "", card_pipeline.CS_STREAM_VERSION) and
          not card_pipeline._cs_version_at_least(
              "unknown", card_pipeline.CS_STREAM_VERSION))

    plugin = root / "plugins" / "canadianshopper"
    (plugin / "tools").mkdir(parents=True)
    hook = plugin / "tools" / "cs_stage_hook.py"
    hook.write_text("def run_stage(*a, **k):\n    pass\n", encoding="utf-8")
    check("no manifest = no version claimed",
          card_pipeline._cs_hook_version(hook) == "")
    (plugin / "plugin.json").write_text(
        json.dumps({"id": "canadianshopper", "version": "1.0.27"}),
        encoding="utf-8")
    check("the manifest above the tools folder is read",
          card_pipeline._cs_hook_version(hook) == "1.0.27",
          card_pipeline._cs_hook_version(hook))
    (plugin / "plugin.json").write_text("{not json", encoding="utf-8")
    check("an unreadable manifest claims nothing",
          card_pipeline._cs_hook_version(hook) == "")
    (plugin / "plugin.json").unlink()
    check("a hook with no manifest at all claims nothing",
          card_pipeline._cs_hook_version(plugin / "tools" / "nope.py") == "")
    check("and no hook at all is not an error",
          card_pipeline._cs_hook_version(None) == "")


def test_nested_helper_output_is_never_lost(root):
    """A helper that fails must be heard, not summarised by an exit code.

    The user's Facebook run ended with "exited with code 3221225786" and not
    one line of explanation, because the child's handles were inherited from
    a windowless parent. Everything a nested tool says now arrives here.
    """
    print()
    print("== 5. a failing helper's own words reach the console ==")
    talker = root / "talker.py"
    talker.write_text(
        "print('first line')\n"
        "print('a traceback line', flush=True)\n"
        "raise SystemExit(3)\n", encoding="utf-8")
    said = StringIO()
    with redirect_stdout(said), redirect_stderr(said):
        ok = card_pipeline.run_nested_tool(talker, "The talker")
    text = said.getvalue()
    check("a helper that fails is not reported as finished", ok is False,
          repr(ok))
    check("both of its lines reached the console",
          "first line" in text and "a traceback line" in text, text[-400:])
    check("and its exit code is explained in words, not left as a number",
          "exit code 3" in text and "its own error message is above" in text,
          text[-400:])
    log = root / card_pipeline.NESTED_LOG_NAME
    check("and everything it printed is saved beside it",
          log.is_file() and "a traceback line" in
          log.read_text(encoding="utf-8"), str(log))

    silent = root / "silent.py"
    silent.write_text("raise SystemExit(4)\n", encoding="utf-8")
    said = StringIO()
    with redirect_stdout(said), redirect_stderr(said):
        ok = card_pipeline.run_nested_tool(silent, "The silent one")
    text = said.getvalue()
    check("a helper that says nothing is called what it is: a launch problem",
          ok is False and "printed nothing at all" in text, text[-400:])
    check("and the log says so too, with the command that was run",
          (root / card_pipeline.NESTED_LOG_NAME).read_text(
              encoding="utf-8").count("$ ") >= 1,
          (root / card_pipeline.NESTED_LOG_NAME).read_text(
              encoding="utf-8")[:200])

    check("an OSError while starting is a failure, not a crash",
          card_pipeline.explain_exit_code(None) ==
          "it could not be started at all")
    check("a console-control exit is named in the user's own terms",
          "Ctrl+C" in card_pipeline.explain_exit_code(3221225786),
          card_pipeline.explain_exit_code(3221225786))
    check("an unknown Windows error is still shown as a code",
          card_pipeline.explain_exit_code(3221225999).startswith(
              "Windows error 0x"), card_pipeline.explain_exit_code(3221225999))


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        print("== 1. the rename stage is reachable ==")
        stage = root / "stage"
        stage.mkdir()
        test_rename_stage_reaches_its_confirmation(stage)
        test_rename_applies_with_yes(stage)

        print("== 1b. a variant card's front is renamed too ==")
        test_dark_back_variant_keeps_its_front(root)

        print("== 2. the shipped script runs end to end ==")
        test_shipped_script_runs_end_to_end(root)
        test_runs_without_the_other_features(root)

        test_plugin_version_reading(root / "version-check")

        helper_root = root / "helper"
        helper_root.mkdir()
        test_nested_helper_output_is_never_lost(helper_root)

    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL PIPELINE LISTING CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
