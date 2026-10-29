#!/usr/bin/env python3
"""Offline tests for `card_pipeline.py rerun`.

A re-run rebuilds ONE marketplace output from files that already exist. These
checks pin down the two promises that matter: only the chosen marketplace
runs, and images are never moved or renamed again.
"""
import argparse
import os
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
    """Silence the pipeline's console chatter during a check."""
    return redirect_stdout(StringIO())


def make_args(**overrides):
    base = dict(market="facebook", input=None, brand="O-Pee-Chee",
                category=None, subcategory=None, quantity=1, yes=True,
                image_ext="webp", facebook=False, canadianshopper=False,
                no_browser=True, feed_wait=0, feed_cookie=None, browser=None,
                canadianshopper_image_base_url=None)
    base.update(overrides)
    return argparse.Namespace(**base)


class Recorder:
    """Stand-in for a stage function that records how it was called."""

    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    def __call__(self, *args, **kwargs):
        self.calls.append(self.name)
        return None


def stage_patches(calls):
    """Patch every post-listing stage so a run only records its name."""
    return (
        patch.object(card_pipeline, "maybe_run_facebook",
                     Recorder("facebook", calls)),
        patch.object(card_pipeline, "maybe_run_canadianshopper",
                     Recorder("canadianshopper", calls)),
        patch.object(card_pipeline, "maybe_run_ebay_quicklist",
                     Recorder("ebay", calls)),
        patch.object(card_pipeline, "build_rows",
                     lambda parsed, quantity: [{"SKU": "CARD-001",
                                                "Name": "Re-run card",
                                                "Regular price": "9",
                                                "Categories": "Sports"}])
    )


def run_rerun(market, cards=True):
    """Run cmd_rerun with stages recorded; returns the stage call order."""
    calls = []
    with patch.object(card_pipeline, "find_rerun_input",
                      lambda args: Path("C:/batch/_card_input.txt")), \
            patch.object(card_pipeline, "read_listing_text",
                         lambda path: "AI reply text"), \
            patch.object(card_pipeline, "parse_listing_text",
                         lambda raw, args: [{"seo_title": "Card"}] if cards
                         else []), \
            patch.object(card_pipeline, "print_parsed_cards",
                         lambda parsed: None), \
            patch.object(card_pipeline, "confirm_card_metadata",
                         lambda parsed, args: 1), \
            patch.object(card_pipeline, "write_woocommerce_csv",
                         lambda rows: "woocommerce_import_now.csv"), \
            patch.object(card_pipeline, "print_woocommerce_rows",
                         lambda rows, path: None):
        fb, cs, ebay, rows = stage_patches(calls)
        with fb, cs, ebay, rows, quiet():
            card_pipeline.cmd_rerun(make_args(market=market))
    return calls


def test_find_rerun_input(root):
    """Explicit path wins, then _card_input.txt, then the newest sibling."""
    batch = root / "batch"
    batch.mkdir()
    with patch.object(card_pipeline, "SCRIPT_DIR", batch), \
            patch("os.getcwd", return_value=str(root)):
        check("no AI text yet reports nothing",
              card_pipeline.find_rerun_input(make_args()) is None)

        older = batch / "_card_input_20260101_120000.txt"
        older.write_text("old reply\n", encoding="utf-8")
        os.utime(older, (10, 10))
        check("a timestamped reply is found automatically",
              card_pipeline.find_rerun_input(make_args()) == older)

        newest = batch / "_card_input_20260102_120000.txt"
        newest.write_text("new reply\n", encoding="utf-8")
        os.utime(newest, (20, 20))
        check("the newest timestamped reply wins",
              card_pipeline.find_rerun_input(make_args()) == newest)

        standard = batch / "_card_input.txt"
        standard.write_text("the app's own copy\n", encoding="utf-8")
        os.utime(standard, (5, 5))
        check("_card_input.txt is preferred over timestamped copies",
              card_pipeline.find_rerun_input(make_args()) == standard)

        explicit = root / "somewhere_else.txt"
        explicit.write_text("hand-picked reply\n", encoding="utf-8")
        check("an explicit --input always wins",
              card_pipeline.find_rerun_input(
                  make_args(input=str(explicit))) == explicit)

        empty = batch / "_card_input_empty.txt"
        empty.write_text("", encoding="utf-8")
        standard.unlink()
        newest.unlink()
        older.unlink()
        check("an empty file is not offered as the AI text",
              card_pipeline.find_rerun_input(make_args()) is None)


def test_market_gating():
    """Each market runs only its own stage."""
    check("facebook re-run touches only the Facebook stage",
          run_rerun("facebook") == ["facebook"])
    check("canadianshopper re-run touches only the CanadianShopper stage",
          run_rerun("canadianshopper") == ["canadianshopper"])
    check("ebay re-run touches only the eBay stage",
          run_rerun("ebay") == ["ebay"])
    check("woocommerce re-run touches no post-listing stage",
          run_rerun("woocommerce") == [], str(run_rerun("woocommerce")))


def test_all_order():
    """`--market all` rebuilds everything in the pipeline's own order."""
    calls = run_rerun("all")
    check("all: Facebook, then CanadianShopper, then eBay",
          calls == ["facebook", "canadianshopper", "ebay"], str(calls))


def test_images_are_never_touched():
    """Re-runs must not plan or apply image renames."""
    def boom(*_args, **_kwargs):
        raise AssertionError("a re-run must not touch the images")

    ok = True
    try:
        with patch.object(card_pipeline, "find_rerun_input",
                          lambda args: Path("C:/batch/_card_input.txt")), \
                patch.object(card_pipeline, "read_listing_text",
                             lambda path: "AI reply text"), \
                patch.object(card_pipeline, "parse_listing_text",
                             lambda raw, args: [{"seo_title": "Card"}]), \
                patch.object(card_pipeline, "print_parsed_cards",
                             lambda parsed: None), \
                patch.object(card_pipeline, "confirm_card_metadata",
                             lambda parsed, args: 1), \
                patch.object(card_pipeline, "write_woocommerce_csv",
                             lambda rows: "woocommerce_import_now.csv"), \
                patch.object(card_pipeline, "print_woocommerce_rows",
                             lambda rows, path: None), \
                patch.object(card_pipeline, "plan_renames", boom), \
                patch.object(card_pipeline, "apply_renames", boom), \
                quiet():
            fb, cs, ebay, rows = stage_patches([])
            with fb, cs, ebay, rows:
                card_pipeline.cmd_rerun(make_args(market="all"))
    except AssertionError as exc:
        ok = False
        print("  (%s)" % exc)
    check("a re-run never plans or applies image renames", ok)


def test_woocommerce_csv_written(root):
    """The WooCommerce re-run writes a real CSV in the batch folder."""
    folder = root / "woocommerce_products"
    rows = [{"SKU": "CARD-001", "Name": "Card one", "Regular price": "9",
             "Categories": "Sports"}]
    with patch.object(card_pipeline, "WOOCOMMERCE_DIR", folder), quiet():
        out_path = card_pipeline.write_woocommerce_csv(rows)
    path = Path(out_path)
    check("the WooCommerce CSV is written into woocommerce_products",
          path.parent == folder and path.is_file())
    check("the CSV keeps the parsed card row",
          path.is_file() and "CARD-001" in path.read_text(encoding="utf-8-sig"))

    older = folder / "woocommerce_import_20000101_000000.csv"
    older.write_text("SKU,Name\nOLD-1,Prior card\n", encoding="utf-8")
    with patch.object(card_pipeline, "WOOCOMMERCE_DIR", folder), quiet():
        newest = Path(card_pipeline.write_woocommerce_csv(rows))
    history = folder / "woocommerce_history.csv"
    check("older WooCommerce batches roll into history",
          history.is_file() and not older.exists() and newest.is_file())


def test_facebook_opening(root):
    """The Facebook step always offers the renamed images, and only once.

    card_pipeline used to open OUTPUT_DIR inside the "media URL is
    configured" branch, so a run without a WooCommerce site URL never
    showed the folder holding the images it had just renamed.
    """
    folder = root / "output"
    folder.mkdir()
    media_page = "https://shop.example/wp-admin/media-new.php"

    def run(media_url, no_browser=False):
        opened_folders, opened_urls = [], []

        def fake_open_folder(path):
            opened_folders.append(path)
            return True

        def fake_open_in_browser(url, browser=None):
            opened_urls.append(url)
            return "Test browser"

        with patch.object(card_pipeline, "site_admin_url",
                          lambda page, settings=None: media_url), \
                patch.object(card_pipeline, "OUTPUT_DIR", folder), \
                patch.object(card_pipeline, "open_folder", fake_open_folder), \
                patch.object(card_pipeline, "open_in_browser",
                             fake_open_in_browser), \
                patch("builtins.input", lambda prompt="": "n"), \
                quiet():
            card_pipeline.maybe_run_facebook(
                make_args(facebook=True, no_browser=no_browser))
        return opened_folders, opened_urls

    folders, urls = run("")
    check("a missing media URL still opens the image output folder",
          folders == [folder] and urls == [],
          "folders=%s urls=%s" % (folders, urls))

    folders, urls = run(media_page)
    check("a configured media URL opens the page and the folder exactly once",
          folders == [folder] and urls == [media_page],
          "folders=%s urls=%s" % (folders, urls))

    folders, urls = run(media_page, no_browser=True)
    check("--no-browser suppresses the media page and the folder",
          folders == [] and urls == [],
          "folders=%s urls=%s" % (folders, urls))


def test_a_failed_step_fails_the_run():
    """A run with a step missing must not end as though it finished.

    The user's own run ended with "Re-run finished: facebook." and
    "finished (OK, exit code 0)" right after the feed helper failed, so a
    missing workbook looked like a successful run.
    """
    print("== 6. a step that fails fails the run ==")
    calls = []
    recorded = []

    def failing_facebook(*args, **kwargs):
        calls.append("facebook")
        return "Facebook (the feed history helper failed)"

    real_report = card_pipeline.report_unfinished

    def fake_report(failures, still_written):
        recorded.append((list(failures), still_written))
        return real_report(failures, still_written)

    with patch.object(card_pipeline, "find_rerun_input",
                      lambda args: Path("C:/batch/_card_input.txt")), \
            patch.object(card_pipeline, "maybe_run_facebook",
                         failing_facebook), \
            patch.object(card_pipeline, "maybe_run_canadianshopper",
                         Recorder("canadianshopper", calls)), \
            patch.object(card_pipeline, "maybe_run_ebay_quicklist",
                         Recorder("ebay", calls)), \
            patch.object(card_pipeline, "report_unfinished", fake_report), \
            quiet() as said:
        code = card_pipeline.cmd_rerun(make_args(market="facebook"))
    check("the re-run returns a failing exit code",
          code == 1, repr(code))
    check("and names the step that did not finish",
          recorded and recorded[0][0] ==
          ["Facebook (the feed history helper failed)"], repr(recorded))
    check("the Facebook step still ran exactly once",
          calls.count("facebook") == 1, repr(calls))

    with redirect_stdout(StringIO()) as said:
        code = card_pipeline.report_unfinished(
            ["Facebook (the Marketplace xlsx export failed)"],
            "the WooCommerce CSV")
        text = said.getvalue()
    check("the summary says what did not finish",
          "NOT EVERY STEP FINISHED" in text and
          "Marketplace xlsx" in text, text)
    check("and what was still written", "the WooCommerce CSV" in text, text)
    check("and that the failed step changed nothing",
          "changed nothing" in text, text)
    check("nothing wrong = the exit code is 0",
          card_pipeline.report_unfinished([], "anything") == 0)


def main():
    print("== 1. the AI text a re-run reuses ==")
    with tempfile.TemporaryDirectory() as td:
        test_find_rerun_input(Path(td))

    print("== 2. one marketplace at a time ==")
    test_market_gating()
    test_all_order()

    print("== 3. images stay where they are ==")
    test_images_are_never_touched()

    print("== 4. the WooCommerce CSV is rebuilt ==")
    with tempfile.TemporaryDirectory() as td:
        test_woocommerce_csv_written(Path(td))

    print("== 5. the Facebook step opens the image folder ==")
    with tempfile.TemporaryDirectory() as td:
        test_facebook_opening(Path(td))

    test_a_failed_step_fails_the_run()

    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL MARKET RE-RUN CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
