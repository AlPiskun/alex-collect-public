#!/usr/bin/env python3
"""Checks for reading the photo staging step's own answer.

CanadianShopper 1.0.40's ``marketplace.photo_stage`` reports every row - the
front it uploaded and its URL, the front the cache already knew, the row that
was only checked in a dry run, and the row that failed with its reason. The
older ``batch.photo_stage`` answers with an exit code alone. What is worth
testing here is the reading: that a partial batch still stages what it staged,
that a failed row is named by its card rather than counted, that a dry run is
never reported as an upload, and that the panel asks for the right command -
with the documented flags - before any of that.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]

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


def load_harness():
    spec = importlib.util.spec_from_file_location(
        "panel", str(APP / "test-photo-panel.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["panel"] = module
    spec.loader.exec_module(module)
    return module


harness = load_harness()
gui = harness.gui
import cs_stage                                        # noqa: E402

ACTION = "marketplace.photo_stage"


def fake_stage():
    """A batch of four rows: one uploaded, one cached, one failed, one new."""
    return {
        "items": [
            {"csv": "canadianshopper_import_001.csv", "row": 2,
             "sku": "PKM-006", "title": "#006/196 Wurmple",
             "status": "staged",
             "staged_url": "https://canadianshopper.ca/api/file/wurmple.jpg",
             "staged_csv": "canadianshopper_import_001.csv",
             "source_image_url": "https://shop.example/wurmple-front.jpg"},
            {"csv": "canadianshopper_import_001.csv", "row": 3,
             "sku": "PKM-007", "title": "Pikachu",
             "status": "already_staged",
             "staged_url": "https://canadianshopper.ca/api/file/pikachu.jpg"},
            {"csv": "canadianshopper_import_001.csv", "row": 4,
             "sku": "PKM-008", "title": "Charizard", "status": "error",
             "error": "no local image and the source URL answered 404"},
            {"csv": "canadianshopper_import_001.csv", "row": 5,
             "sku": "PKM-009", "title": "Blastoise", "status": "dry_run"},
        ],
        "files": [{"input": "canadianshopper_import_001.csv",
                   "output": "cs-ready/canadianshopper_import_001.csv"}],
    }


def test_the_command_the_plugin_documents():
    print()
    print("== 1. the command the plugin documents ==")
    argv = cs_stage.args("/batch", "/batch/photo-stage.json")
    check("the batch and the answer file are always asked for",
          argv == ["--batch-dir", "/batch", "--stage-out",
                   "/batch/photo-stage.json"], str(argv))
    argv = cs_stage.args("/batch", "/out.json", ready_dir="/ready",
                         cookie_file="/c.txt", images_dir="/scans",
                         dry_run=True)
    check("every optional path is passed when the caller has one",
          argv[4:] == ["--images-dir", "/scans", "--ready-dir", "/ready",
                       "--cookie-file", "/c.txt", "--dry-run"], str(argv))
    check("a dry run is asked for by its own flag",
          "--dry-run" in cs_stage.args("/b", "/o.json", dry_run=True) and
          "--dry-run" not in cs_stage.args("/b", "/o.json"), "")
    check("the action is the one 1.0.40 declares, with the old one kept",
          cs_stage.ACTION == "marketplace.photo_stage" and
          cs_stage.LEGACY_ACTION == "batch.photo_stage", "")


def test_the_answer_file_is_read_forgivingly():
    print()
    print("== 2. reading the answer, including a damaged one ==")
    folder = Path(tempfile.mkdtemp())
    good = folder / "stage.json"
    good.write_text(json.dumps(fake_stage()), encoding="utf-8")
    stage = cs_stage.read_stage(good)
    check("a written answer is read", stage is not None and
          len(cs_stage.items(stage)) == 4, str(stage and len(stage["items"])))
    check("the CSV mappings are read as input and output",
          cs_stage.files(stage) == [
              {"input": "canadianshopper_import_001.csv",
               "output": "cs-ready/canadianshopper_import_001.csv"}],
          str(cs_stage.files(stage)))
    check("a missing file is no answer, not an exception",
          cs_stage.read_stage(folder / "absent.json") is None, "")
    broken = folder / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    check("a truncated file is no answer either",
          cs_stage.read_stage(broken) is None, "")
    listed = folder / "list.json"
    listed.write_text("[1, 2, 3]", encoding="utf-8")
    check("a JSON list is not an answer this module pretends to read",
          cs_stage.read_stage(listed) is None, "")
    odd = folder / "odd.json"
    odd.write_text(json.dumps({"items": [None, 5, {"status": "staged"}],
                               "files": "nope"}), encoding="utf-8")
    stage = cs_stage.read_stage(odd)
    check("rows that are not objects are skipped, not crashed on",
          [cs_stage.status_of(row) for row in cs_stage.items(stage)] ==
          ["staged"], str(cs_stage.items(stage)))
    check("a files value that is not a list is read as none",
          cs_stage.files(stage) == [], str(cs_stage.files(stage)))


def test_counts_and_names():
    print()
    print("== 3. what the batch did, and which cards did not ==")
    stage = fake_stage()
    check("every row is counted by its status",
          cs_stage.tally(stage) == {"staged": 1, "already_staged": 1,
                                    "dry_run": 1, "error": 1},
          str(cs_stage.tally(stage)))
    check("a status this module has not met is counted, not dropped",
          cs_stage.tally({"items": [{"status": "queued"}]}).get("queued") == 1,
          str(cs_stage.tally({"items": [{"status": "queued"}]})))
    check("the fronts on the site are the staged and the cached ones",
          [item["row"] for item in cs_stage.staged(stage)] == [2, 3],
          str(cs_stage.staged(stage)))
    check("a row with no URL is not counted as staged",
          cs_stage.staged({"items": [{"status": "staged"}]}) == [], "")
    check("the failed rows are the ones the plugin called errors",
          [item["row"] for item in cs_stage.failures(stage)] == [4], "")
    line = cs_stage.failure_line(cs_stage.failures(stage)[0])
    check("a failure names the card, its row and its SKU",
          line.startswith("Charizard (row 4, SKU \"PKM-008\"") and
          "404" in line, line)
    check("a failure with no reason still says so",
          "no reason was reported" in
          cs_stage.failure_line({"title": "X", "status": "error"}), "")
    check("a row with nothing at all still reads as a row",
          "no title" in cs_stage.failure_line({}), cs_stage.failure_line({}))
    shown, more = cs_stage.failure_lines(
        {"items": [{"title": "card %d" % n, "status": "error"}
                   for n in range(25)]})
    check("only the first failures are printed, and the rest are counted",
          len(shown) == cs_stage.SHOWN_FAILURES == 20 and more == 5,
          "%s %s" % (len(shown), more))
    check("the staged CSVs are the ones the plugin says it wrote",
          cs_stage.ready_csvs(stage) ==
          ["cs-ready/canadianshopper_import_001.csv"], "")
    check("a relative answer is resolved from the batch folder it was given",
          cs_stage.output_paths(stage, "/batch") ==
          [Path("/batch/cs-ready/canadianshopper_import_001.csv")],
          str(cs_stage.output_paths(stage, "/batch")))
    check("an absolute answer is left exactly as the plugin wrote it",
          cs_stage.output_paths(
              {"files": [{"output": "/ready/a.csv"}]}, "/batch") ==
          [Path("/ready/a.csv")], "")
    check("an error answer is read for its own reason",
          cs_stage.fatal_message({"error": "no session"}) == "no session" and
          cs_stage.fatal_message({"message": "no batch"}) == "no batch" and
          cs_stage.fatal_message({"error": {"message": "bad cookie"}}) ==
          "bad cookie" and cs_stage.fatal_message({}) == "", "")


def test_the_sentence_and_the_report():
    print()
    print("== 4. the sentence the panel says ==")
    stage = fake_stage()
    text = cs_stage.summary(stage)
    check("the sentence counts what the plugin counted",
          "1 staged" in text and "1 already staged" in text and
          "1 failed" in text and "4 rows" in text, text)
    dry = cs_stage.summary(stage, dry_run=True)
    check("a dry run says nothing was uploaded",
          "nothing was uploaded" in dry.lower(), dry)
    check("and a row that was only checked is never said to be staged",
          "1 checked" in dry, dry)
    check("an empty answer says so rather than claiming success",
          "no rows" in cs_stage.summary({}), cs_stage.summary({}))

    report = cs_stage.report(stage, 1)
    tags = [tag for tag, _text in report["lines"]]
    check("a partial batch is reported with its failure, not as a crash",
          report["failed"] == 1 and "err" in tags and report["known"], str(tags))
    check("and its success is still on the console",
          any("1 staged" in text for _tag, text in report["lines"]), "")
    check("a clean batch is not warned about",
          "warn" not in [tag for tag, _t in cs_stage.report(
              {"items": [{"status": "staged", "title": "X"}]}, 0)["lines"]],
          "")

    fatal = cs_stage.report({"error": "no session"}, 2)
    check("a fatal run quotes the plugin's reason",
          "no session" in fatal["lines"][0][1] and
          fatal["summary"] == "The staging step could not run.",
          str(fatal["lines"]))
    missing = cs_stage.report(None, 0)
    check("an answer that never arrived is said to be unknown",
          missing["known"] is False and not missing["lines"], "")
    check("0 and 1 are both worth carrying on from; 2 is not",
          cs_stage.exit_is_ok(0) and cs_stage.exit_is_ok(1) and
          not cs_stage.exit_is_ok(2), "")


# ------------------------------------------------------------------ the panel
def build_panel(folder):
    gui.BASE = folder
    app = harness.FakeApp(folder)
    app.settings["pipeline_dir"] = str(folder)
    parent = harness.FakeWidget()
    gui.build_stage(parent, app)
    return app, parent


def find(parent, kind, text, exact=True):
    for widget in parent.walk():
        if not isinstance(widget, kind):
            continue
        got = str(widget.cget("text"))
        if (got == text) if exact else (got.startswith(text)):
            return widget
    return None


def batch(folder):
    """A batch folder with one import CSV and no cookie, as a fresh run has."""
    results = folder / "canadianshopper_products"
    results.mkdir(parents=True, exist_ok=True)
    (results / "canadianshopper_import_001.csv").write_text(
        "title,image_url\nWurmple,https://shop.example/wurmple-front.jpg\n",
        encoding="utf-8")
    return results


def test_the_panel_asks_the_new_action():
    print()
    print("== 5. the panel asks the plugin for the staged batch ==")
    folder = Path(tempfile.mkdtemp())
    results = batch(folder)
    app, parent = build_panel(folder)
    cookie = folder / "cookie.txt"
    cookie.write_text("session_token=secret-value\n", encoding="utf-8")
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: ("/plugins/cs/tools/cs-photo-stage.py"
                                      if action == ACTION else "")), \
            patch.object(gui, "CS_COOKIE_FILE", cookie):
        button = find(parent, gui.ttk.Button,
                      "Stage the photos (square + host + rewrite CSVs)")
        check("the staging button is on the panel", button is not None, "")
        button.invoke()
    run = app.runs[-1] if app.runs else {}
    args = run.get("args") or []
    check("the plugin's own action is what runs",
          run.get("tool") == "/plugins/cs/tools/cs-photo-stage.py",
          str(run.get("tool")))
    check("with the documented batch and answer flags",
          args[:4] == ["--batch-dir", str(results),
                       "--stage-out", str(results / "photo-stage.json")],
          str(args))
    check("and the ready folder and cookie the app already knows",
          "--ready-dir" in args and
          args[args.index("--ready-dir") + 1] == str(results / "cs-ready") and
          args[args.index("--cookie-file") + 1] == str(cookie), str(args))
    check("no per-CSV flag is invented: the plugin discovers the batch itself",
          "--csv" not in args and "--mode" not in args, str(args))

    stage_out = results / "photo-stage.json"
    stage_out.write_text(json.dumps(fake_stage()), encoding="utf-8")
    ready = results / "cs-ready"
    ready.mkdir(exist_ok=True)
    (ready / "canadianshopper_import_001.csv").write_text(
        "title,image_url\n", encoding="utf-8")
    app.lines[:] = []
    run["on_done"](1)                      # a partial batch
    said = " ".join(text for _tag, text in app.lines)
    check("a partial batch still says what it staged",
          "1 staged" in said and "1 already staged" in said, said)
    check("and names the card that failed, with the plugin's reason",
          "Charizard" in said and "404" in said, said)
    check("and says which CSV was written",
          "canadianshopper_import_001.csv" in said, said)
    check("and still moves the batch on to the import step",
          any("then come back and press Wire" in text
              for _tag, text in app.lines), str(app.lines[-2:]))


def test_a_dry_run_uploads_nothing():
    print()
    print("== 6. the preview uploads nothing and changes no CSV ==")
    folder = Path(tempfile.mkdtemp())
    results = batch(folder)
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: ("/plugins/cs/tools/cs-photo-stage.py"
                                      if action == ACTION else "")), \
            patch.object(gui, "CS_COOKIE_FILE", folder / "absent-cookie.txt"):
        app, parent = build_panel(folder)
        preview = find(parent, gui.ttk.Button, "Preview the staging (no upload)")
        check("the preview is offered when the plugin can do it",
              preview is not None, "")
        preview.invoke()
    run = app.runs[-1] if app.runs else {}
    args = run.get("args") or []
    check("the preview is the same command with --dry-run",
          "--dry-run" in args and "--batch-dir" in args, str(args))
    check("and no cookie file that does not exist is passed",
          "--cookie-file" not in args, str(args))
    stage_out = results / "photo-stage.json"
    stage_out.write_text(json.dumps(fake_stage()), encoding="utf-8")
    app.lines[:] = []
    run["on_done"](0)
    said = " ".join(text for _tag, text in app.lines)
    check("the console calls it a preview, not a staging",
          "Preview only" in said and "nothing was uploaded" in said.lower(),
          said)
    check("and says nothing will change until the real button is pressed",
          "Nothing was uploaded and no CSV was changed" in said, said)
    check("and does not claim the batch is ready to import",
          "press Wire" not in said, said)


def test_a_fatal_run_says_the_plugins_reason():
    print()
    print("== 7. a fatal run is quoted, not guessed at ==")
    folder = Path(tempfile.mkdtemp())
    results = batch(folder)
    app, parent = build_panel(folder)
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: ("/plugins/cs/tools/cs-photo-stage.py"
                                      if action == ACTION else "")):
        find(parent, gui.ttk.Button,
             "Stage the photos (square + host + rewrite CSVs)").invoke()
    run = app.runs[-1]
    (results / "photo-stage.json").write_text(
        json.dumps({"error": "the cookie is not signed in"}), encoding="utf-8")
    app.lines[:] = []
    run["on_done"](2)
    said = " ".join(text for _tag, text in app.lines)
    check("the plugin's own reason is on the console",
          "the cookie is not signed in" in said, said)
    check("and the batch is not moved on to the import step",
          "press Wire" not in said, said)

    #  An answer that never arrived is reported as unknown, not as a success.
    app.lines[:] = []
    (results / "photo-stage.json").unlink()
    run["on_done"](0)
    said = " ".join(text for _tag, text in app.lines)
    check("a run with no answer file says nothing can be said per card",
          "without writing its answer" in said, said)


def test_a_plugin_without_the_action_keeps_the_old_command():
    print()
    print("== 8. an older plugin keeps the command it documents ==")
    folder = Path(tempfile.mkdtemp())
    results = batch(folder)
    app, parent = build_panel(folder)
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: ("/plugins/cs/tools/cs-image-sync.py"
                                      if action == cs_stage.LEGACY_ACTION
                                      else "")):
        find(parent, gui.ttk.Button,
             "Stage the photos (square + host + rewrite CSVs)").invoke()
    run = app.runs[-1] if app.runs else {}
    args = run.get("args") or []
    check("without the action the old prepare command is used",
          args[:2] == ["--mode", "prepare"], str(args))
    check("and it names the batch's CSVs, as that command documents",
          "--csv" in args and args[args.index("--csv") + 1].endswith(
              "canadianshopper_import_001.csv"), str(args))
    check("and the preview is not offered, because it would not be a preview",
          find(parent, gui.ttk.Button, "Preview the staging (no upload)")
          is None, "")
    check("the old command is the plugin's own image-sync script",
          run.get("tool") == "/plugins/cs/tools/cs-image-sync.py",
          str(run.get("tool")))


def main():
    test_the_command_the_plugin_documents()
    test_the_answer_file_is_read_forgivingly()
    test_counts_and_names()
    test_the_sentence_and_the_report()
    test_the_panel_asks_the_new_action()
    test_a_dry_run_uploads_nothing()
    test_a_fatal_run_says_the_plugins_reason()
    test_a_plugin_without_the_action_keeps_the_old_command()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL CS STAGE CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
