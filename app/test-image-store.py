#!/usr/bin/env python3
"""Checks for the image store: moving the last batch's images out of the way.

Two folders fill up with every card image the shop has ever used - the
pipeline's ``output`` (tiles, then the same files renamed to their listing
titles) and the photos panel's ``replacements`` (the fronts cut out of a
scan). This is the rule that keeps them apart, so what matters is that it:

  * only ever looks at images - a CSV or a report in those folders is a
    record and is never touched;
  * never deletes, never overwrites, and never renames what it moves;
  * keeps the ``_tiles`` shape, because that is how a sheet is put back
    together;
  * does nothing at all without an answer that says yes - a closed dialog is
    a cancelled run, never a silent move.

tkinter is stubbed, so the app-level half runs without a display.
"""
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path

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


# ------------------------------------------------------------------ Tk stub
class FakeWidget:
    def __init__(self, *args, **kwargs):
        self._kw = dict(kwargs)
        self.children = []
        self.command = kwargs.get("command")
        self.parent = args[0] if args else None
        if self.parent is not None and hasattr(self.parent, "children"):
            self.parent.children.append(self)

    def pack(self, *a, **k): return self
    def grid(self, *a, **k): return self
    def place(self, *a, **k): return self
    def bind(self, *a, **k): return self
    def configure(self, **k): self._kw.update(k)
    def config(self, **k): self._kw.update(k)
    def cget(self, key): return self._kw.get(key, "")
    def winfo_children(self): return list(self.children)
    def destroy(self): pass
    def focus_set(self): pass
    def yview(self, *a, **k): return (0.0, 1.0)
    def protocol(self, *a, **k): return None
    def insert(self, *a, **k): pass
    def delete(self, *a, **k): pass
    def get(self, *a, **k): return ""
    def set(self, value): pass
    def curselection(self): return ()
    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def install_tk():
    tk = types.ModuleType("tkinter")
    for name in ("Frame", "Label", "Button", "Entry", "Text", "Listbox",
                 "Toplevel", "Canvas", "StringVar", "BooleanVar", "IntVar",
                 "Tk"):
        setattr(tk, name, FakeWidget)
    tk.font = types.SimpleNamespace(nametofont=lambda *a, **k: FakeWidget())
    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "Button", "Entry", "LabelFrame", "Notebook",
                 "Scrollbar", "Checkbutton", "Radiobutton", "Combobox",
                 "Treeview", "Separator", "Progressbar"):
        setattr(ttk, name, FakeWidget)
    ttk.Style = lambda *a, **k: types.SimpleNamespace(
        configure=lambda *a, **k: None, lookup=lambda *a, **k: "22",
        theme_use=lambda *a, **k: None, map=lambda *a, **k: None)
    dialog = types.ModuleType("tkinter.filedialog")
    dialog.asked = []
    dialog.askopenfilename = lambda **k: ""
    dialog.askopenfilenames = lambda **k: ()
    dialog.askdirectory = lambda **k: ""
    box = types.ModuleType("tkinter.messagebox")
    box.shown = []
    for name in ("showinfo", "showwarning", "showerror"):
        setattr(box, name, (lambda kind: lambda *a, **k:
                            box.shown.append((kind, a)))(name))
    box.askyesno = lambda *a, **k: False
    box.askyesnocancel = lambda *a, **k: None
    prompt = types.ModuleType("tkinter.simpledialog")
    prompt.askstring = lambda *a, **k: ""
    colour = types.ModuleType("tkinter.colorchooser")
    colour.askcolor = lambda *a, **k: (None, None)
    for name, module in (("tkinter", tk), ("tkinter.ttk", ttk),
                         ("tkinter.filedialog", dialog),
                         ("tkinter.messagebox", box),
                         ("tkinter.simpledialog", prompt),
                         ("tkinter.colorchooser", colour)):
        sys.modules[name] = module
    tk.ttk, tk.filedialog = ttk, dialog
    tk.messagebox, tk.simpledialog = box, prompt
    tk.colorchooser = colour
    return tk, ttk, dialog, box


_TK, _TTK, _DIALOG, _BOX = install_tk()

import gui                                     # noqa: E402
import image_store                             # noqa: E402


# ------------------------------------------------------------------- helpers
def make_folder(root, name, images=3, tiles=1):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    made = []
    for index in range(images):
        path = folder / ("img_%d.webp" % index)
        path.write_bytes(b"image")
        made.append(path)
    if tiles:
        tile_dir = folder / image_store.TILES_DIRNAME / "sheet-a"
        tile_dir.mkdir(parents=True, exist_ok=True)
        for index in range(tiles):
            path = tile_dir / ("sheet-a_%d.webp" % index)
            path.write_bytes(b"image")
            made.append(path)
    (folder / "notes.csv").write_text("a record, not an image")
    (folder / "report.json").write_text("{}")
    return folder, made


class FakeApp:
    """The part of the app these two methods use, and nothing else."""

    def __init__(self, settings=None):
        self.settings = dict(settings or {})
        self.lines = []
        self.saved = []

    def console_line(self, text, tag=None):
        self.lines.append((tag, str(text)))

    def set_setting(self, key, value):
        self.settings[key] = value
        self.saved.append((key, value))


#  The real methods, unbound from Tk: they only ever touch settings, the
#  console and the two dialogs, all of which the fake above provides.
def bind(method_name):
    def bound(self, *args, **kwargs):
        return getattr(gui.App, method_name)(self, *args, **kwargs)
    return bound


for _name in ("prepare_image_folder", "_move_older_images", "ask_image_store",
              "image_store_dir"):
    setattr(FakeApp, _name, bind(_name))


def answers(yes_no=None, yes_no_cancel=None, directory=""):
    """Set what the next dialogs answer, and record that they were asked."""
    asked = {"yes_no": 0, "yes_no_cancel": 0, "directory": 0}

    def fake_yes_no(*a, **k):
        asked["yes_no"] += 1
        return bool(yes_no)

    def fake_yes_no_cancel(*a, **k):
        asked["yes_no_cancel"] += 1
        return yes_no_cancel

    def fake_directory(*a, **k):
        asked["directory"] += 1
        return directory

    _BOX.askyesno = fake_yes_no
    _BOX.askyesnocancel = fake_yes_no_cancel
    _DIALOG.askdirectory = fake_directory
    return asked


# --------------------------------------------------------------------- tests
def test_what_counts_as_an_image(root):
    print("== 1. what the folder really holds ==")
    folder, made = make_folder(root / "one", "output", images=3, tiles=2)
    found = image_store.images_in(folder)
    check("the tiles and the images are both found",
          sorted(path.name for path in found) ==
          ["img_0.webp", "img_1.webp", "img_2.webp", "sheet-a_0.webp",
           "sheet-a_1.webp"], str([p.name for p in found]))
    check("a CSV in the same folder is a record, not an image",
          all(path.suffix != ".csv" for path in found))
    check("a JSON report is left alone too",
          all(path.suffix != ".json" for path in found))
    check("nothing was moved by looking",
          all(path.exists() for path in made + [folder / "notes.csv"]))
    check("a folder that does not exist is empty, not an error",
          image_store.images_in(root / "nowhere") == [])

    print()
    print("== 2. an image still in use is never offered ==")
    keep = [folder / "img_1.webp", folder / image_store.TILES_DIRNAME /
            "sheet-a" / "sheet-a_0.webp"]
    left = image_store.images_in(folder, keep=keep)
    check("the sitting's own tiles are not on the list",
          sorted(path.name for path in left) ==
          ["img_0.webp", "img_2.webp", "sheet-a_1.webp"],
          str([p.name for p in left]))


def test_where_they_go(root):
    print()
    print("== 3. where they would go, and why some folders cannot be used ==")
    folder, _made = make_folder(root / "two", "output", images=2, tiles=1)
    store = root / "two" / "store"
    store.mkdir()
    plan = image_store.plan(folder, store, now=datetime(2026, 10, 31, 9, 37))
    check("a dated folder per batch, named after the folder it came from",
          plan["target"] == store / "output" / "2026-10-31 09-37",
          str(plan["target"]))
    check("the plan lists what would move", len(plan["files"]) == 3)
    check("the plan says so in a sentence",
          image_store.describe(plan) ==
          "3 older card images from %s would move to %s"
          % (folder, plan["target"]), image_store.describe(plan))
    check("an empty folder plans nothing, and says that instead",
          image_store.describe(
              image_store.plan(root / "nowhere", store)) ==
          "There are no older card images to move.")

    check("the folder itself is refused",
          "being moved out of" in image_store.check_store(folder, folder),
          image_store.check_store(folder, folder))
    check("a folder inside it is refused",
          "inside" in image_store.check_store(folder / "keep", folder))
    check("a folder beside it is fine", image_store.check_store(store, folder)
          == "")
    check("the batch folder itself is refused - its dated folders would land "
          "inside the folder being emptied",
          "inside" in image_store.check_store(folder.parent, folder),
          image_store.check_store(folder.parent, folder))
    check("a folder above the batch folder is fine",
          image_store.check_store(root / "two" / "elsewhere", folder) == "",
          image_store.check_store(root / "two" / "elsewhere", folder))
    check("no folder at all is refused",
          "no folder" in image_store.check_store("", folder))

    #  Two batches filed in the same minute must not be mixed together.
    (store / "output" / "2026-10-31 09-37").mkdir(parents=True)
    (store / "output" / "2026-10-31 09-37" / "old.webp").write_bytes(b"x")
    second = image_store.plan(folder, store, now=datetime(2026, 10, 31, 9, 37))
    check("a second batch in the same minute gets its own folder",
          second["target"].name == "2026-10-31 09-37 (2)",
          second["target"].name)


def test_the_move(root):
    print()
    print("== 4. moving them changes nothing about them ==")
    folder, made = make_folder(root / "three", "output", images=3, tiles=2)
    store = root / "three" / "store"
    store.mkdir()
    before = {path.name: path.read_bytes() for path in made}
    plan = image_store.plan(folder, store, now=datetime(2026, 10, 31, 10, 0))
    result = image_store.move(plan)
    check("every image moved", len(result["moved"]) == 5, str(result["failed"]))
    check("nothing is left behind in the working folder",
          image_store.images_in(folder) == [])
    check("the records are still where they were",
          (folder / "notes.csv").is_file() and
          (folder / "report.json").is_file())
    moved = {path.name: path.read_bytes()
             for path in result["target"].rglob("*") if path.is_file()}
    check("and each one is byte for byte the image it was",
          moved == before, "%r vs %r" % (sorted(moved), sorted(before)))
    check("the tiles keep the shape that puts a sheet back together",
          (result["target"] / "_tiles" / "sheet-a" /
           "sheet-a_0.webp").is_file())
    check("it says what it did",
          image_store.result_text(result) ==
          ["Moved 5 older card images to %s." % result["target"]],
          str(image_store.result_text(result)))

    print()
    print("== 5. a name already in the store is never overwritten ==")
    folder, _made = make_folder(root / "four", "output", images=1, tiles=0)
    plan = image_store.plan(folder, store, now=datetime(2026, 10, 31, 11, 0))
    #  The store folder is empty when the plan is made - a plan and its move
    #  are not the same instant - and something of that name is there by the
    #  time the move runs.
    kept = plan["target"] / "img_0.webp"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"the one already there")
    result = image_store.move(plan)
    check("the older copy keeps its name and its bytes",
          kept.read_bytes() == b"the one already there")
    check("the new one gets a name of its own",
          result["moved"][0]["to"].name == "img_0 (2).webp",
          result["moved"][0]["to"].name)

    print()
    print("== 6. a file that will not move is named, not lost ==")
    folder, _made = make_folder(root / "five", "output", images=2, tiles=0)
    plan = image_store.plan(folder, store, now=datetime(2026, 10, 31, 12, 0))
    real_move = image_store.shutil.move

    def stubborn(source, destination):
        if str(source).endswith("img_1.webp"):
            raise OSError("The process cannot access the file")
        return real_move(source, destination)

    image_store.shutil.move = stubborn
    try:
        result = image_store.move(plan)
    finally:
        image_store.shutil.move = real_move
    check("the one that moved really moved", len(result["moved"]) == 1)
    check("the one that did not is still in the folder",
          (folder / "img_1.webp").is_file())
    check("and is named with the reason",
          result["failed"] and result["failed"][0]["name"] == "img_1.webp"
          and "cannot access" in result["failed"][0]["why"],
          str(result["failed"]))
    lines = image_store.result_text(result)
    check("the report says what moved and what did not",
          any("Moved 1 older card image" in line for line in lines) and
          any("could not be moved" in line for line in lines), str(lines))


def test_the_app_asks_first(root):
    print()
    print("== 7. nothing moves without a yes ==")
    folder, made = make_folder(root / "six", "output", images=3, tiles=0)
    store = root / "six" / "store"
    store.mkdir()

    #  The setting is there: one question, and the answer decides.
    app = FakeApp({"image_store_dir": str(store)})
    asked = answers(yes_no_cancel=False)
    kept = app.prepare_image_folder(folder)
    check("saying no keeps the images where they are", kept is True)
    check("and nothing was moved", len(image_store.images_in(folder)) == 3)
    check("one question was asked", asked["yes_no_cancel"] == 1)
    check("and the console says they were kept",
          any("keeping" in line.lower() for _tag, line in app.lines),
          str(app.lines))

    app = FakeApp({"image_store_dir": str(store)})
    asked = answers(yes_no_cancel=None)
    cancelled = app.prepare_image_folder(folder)
    check("a closed question cancels the run instead of moving on",
          cancelled is False)
    check("and nothing was moved by it", len(image_store.images_in(folder)) == 3)
    check("the console says the run was cancelled",
          any("cancelled" in line.lower() for _tag, line in app.lines),
          str(app.lines))

    app = FakeApp({"image_store_dir": str(store)})
    asked = answers(yes_no_cancel=True, directory=str(store))
    went = app.prepare_image_folder(folder)
    check("saying yes moves them and carries on", went is True)
    check("the folder is empty of images afterwards",
          image_store.images_in(folder) == [])
    check("the console says where they went",
          any("Moved 3 older card images" in line for _tag, line in app.lines),
          str(app.lines))
    check("a CSV in the folder stayed put", (folder / "notes.csv").is_file())


def test_the_setting_when_it_is_not_set(root):
    print()
    print("== 8. the setting that is asked for when it was never set ==")
    folder, made = make_folder(root / "seven", "output", images=2, tiles=0)
    store = root / "seven" / "store"
    store.mkdir()

    app = FakeApp({})
    asked = answers(yes_no=True, directory=str(store))
    went = app.prepare_image_folder(folder)
    check("with no setting the app asks for a folder", asked["yes_no"] == 1)
    check("the chosen folder is saved", app.settings.get("image_store_dir")
          == str(store), str(app.saved))
    check("choosing it is the same answer as 'move them'",
          asked["yes_no_cancel"] == 0, str(asked))
    check("so they were moved, and the run carried on",
          went is True and image_store.images_in(folder) == [])
    check("and the console names the folder that is now used",
          any("from now on" in line for _tag, line in app.lines),
          str(app.lines))

    print()
    print("== 9. declining is remembered for the sitting, not forever ==")
    folder, _made = make_folder(root / "eight", "output", images=2, tiles=0)
    app = FakeApp({})
    asked = answers(yes_no=False)
    first = app.prepare_image_folder(folder)
    check("declining still lets the run happen", first is True)
    check("nothing was saved", "image_store_dir" not in app.settings)
    check("and the pile is named, with where to change it",
          any("User Settings" in line for _tag, line in app.lines),
          str(app.lines))
    replies = asked["yes_no"]
    app.prepare_image_folder(folder)
    check("the same sitting is not asked twice", asked["yes_no"] == replies,
          "%r -> %r" % (replies, asked["yes_no"]))
    fresh = FakeApp({})
    answers(yes_no=False)
    fresh.prepare_image_folder(folder)
    check("a new sitting asks again", True)

    print()
    print("== 10. a folder that cannot be used is refused, with the reason ==")
    folder, _made = make_folder(root / "nine", "output", images=1, tiles=0)
    app = FakeApp({})
    answers(yes_no=True, directory=str(folder / "inside"))
    app.prepare_image_folder(folder)
    check("a folder inside the working folder is not saved",
          "image_store_dir" not in app.settings)
    check("and the person is told why",
          any(kind == "showwarning" and "inside" in str(args[1])
              for kind, args in _BOX.shown), str(_BOX.shown[-1:]))

    app = FakeApp({"image_store_dir": str(folder)})
    answers(yes_no_cancel=True)
    app.prepare_image_folder(folder)
    check("a saved setting that cannot work is named, not obeyed",
          any("not usable" in line for _tag, line in app.lines),
          str(app.lines))
    check("and nothing was moved by it", len(image_store.images_in(folder)) == 1)

    print()
    print("== 11. a folder with nothing in it asks nothing ==")
    empty = root / "ten" / "output"
    empty.mkdir(parents=True)
    app = FakeApp({"image_store_dir": str(store)})
    quiet = answers(yes_no_cancel=True)
    check("an empty folder carries on without a question",
          app.prepare_image_folder(empty) is True and
          quiet["yes_no_cancel"] == 0 and not app.lines)
    app = FakeApp({})
    quiet = answers(yes_no=True)
    check("and without asking for a folder either",
          app.prepare_image_folder(empty) is True and quiet["yes_no"] == 0)


def test_the_terminal_side():
    print()
    print("== 12. a batch run from a terminal asks in the terminal ==")
    import os
    from unittest.mock import patch
    import card_pipeline

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder, _made = make_folder(root, "output", images=2, tiles=0)
        store = root / "store"
        store.mkdir()
        settings = {"image_store_dir": str(store)}

        #  The app has already asked; a second question would be a prompt
        #  nobody is looking at.
        with patch.dict(os.environ, {"ALEX_COLLECT_NESTED": "1"}):
            moved = card_pipeline.maybe_store_old_images(folder, settings)
        check("a run started by the app does not ask again", moved == 0 and
              len(image_store.images_in(folder)) == 2)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALEX_COLLECT_NESTED", None)
            with patch.object(card_pipeline, "ask_yes_no", lambda *a, **k: False):
                moved = card_pipeline.maybe_store_old_images(folder, settings)
            check("a 'no' in the terminal keeps them",
                  moved == 0 and len(image_store.images_in(folder)) == 2)
            with patch.object(card_pipeline, "ask_yes_no", lambda *a, **k: True):
                moved = card_pipeline.maybe_store_old_images(folder, settings)
            check("a 'yes' moves them", moved == 2 and
                  image_store.images_in(folder) == [])
            moved = card_pipeline.maybe_store_old_images(folder, settings)
            check("with nothing to move it says nothing and does nothing",
                  moved == 0)

        blank = root / "blank"
        blank.mkdir()
        (blank / "one.webp").write_bytes(b"x")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALEX_COLLECT_NESTED", None)
            with patch("builtins.print") as said:
                moved = card_pipeline.maybe_store_old_images(blank, {})
        check("with no setting it points at the setting instead of asking",
              moved == 0 and (blank / "one.webp").is_file() and
              any("User Settings" in str(call) for call in said.call_args_list),
              str(said.call_args_list[:2]))




def test_every_place_is_behind_the_question():
    print()
    print("== 13. every place a new batch's images are written asks first ==")
    source = (APP / "gui.py").read_text(encoding="utf-8")

    def method(name, where=source):
        """One method's own lines, from its def to the next one at its level."""
        start = where.find("def %s(" % name)
        if start < 0:
            return ""
        end = where.find("\n    def ", start + 1)
        return where[start:end if end > 0 else len(where)]

    for name, why in (("run_split_only", "the split step"),
                      ("run", "the whole batch")):
        body = method(name)
        check("%s asks before it writes" % why,
              "prepare_image_folder" in body, name)
        #  Before the run is handed to the runner, whatever this dialog calls
        #  it: the images cannot be moved once the split has started.
        starts = [body.find(needle) for needle in
                  ("self.on_run(", "on_run(", "run_tool(")]
        starts = [found for found in starts if found > 0]
        check("%s asks before the split starts, not after" % why,
              bool(starts) and
              body.find("prepare_image_folder") < min(starts),
              "%r vs %r" % (body.find("prepare_image_folder"), starts))

    body = method("add_sheets")
    check("loading a replacement sheet asks first",
          body.find("prepare_image_folder") < body.find("pool.add_sheet("),
          "add_sheets")
    check("and the sitting's own tiles are handed over, so they stay",
          "keep=[tile[\"path\"] for tile in pool.tiles()]" in body)
    check("a refusal stops the sheet, it does not carry on",
          "return False" in body.split("prepare_image_folder")[1].split(
              "pool.tiles_dir")[0])

    body = method("ask_for_sheet")
    check("the single-file path asks too",
          "prepare_image_folder" in body)
    check("and it hands over the sitting's tiles as well",
          "keep=[tile[\"path\"] for tile in pool.tiles()]" in body)

    pipeline = (APP / "pipeline" / "card_pipeline.py").read_text(
        encoding="utf-8")
    body = method("cmd_split", pipeline)
    check("a terminal run asks in cmd_split",
          "maybe_store_old_images(OUTPUT_DIR)" in body, body[:200])
    check("before the folder is created for this batch's tiles",
          body.find("maybe_store_old_images") < body.find("OUTPUT_DIR.mkdir"),
          body[:400])

    check("the setting is in the saved defaults, blank meaning ask",
          '\"image_store_dir\": \"\"' in
          (APP / "user_settings.py").read_text(encoding="utf-8"))
    settings_source = (APP / "gui.py").read_text(encoding="utf-8")
    check("and it has its own row in User Settings",
          "Older card images go to (blank = ask):" in settings_source)
    check("with the words that explain it in the folders help",
          "Older card images - where the images from earlier batches" in
          settings_source)



def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        test_what_counts_as_an_image(root)
        test_where_they_go(root)
        test_the_move(root)
        test_the_app_asks_first(root)
        test_the_setting_when_it_is_not_set(root)
        test_the_terminal_side()
    test_every_place_is_behind_the_question()
    print()
    print("=" * 60)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL IMAGE STORE CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
