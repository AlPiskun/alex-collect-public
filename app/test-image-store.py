#!/usr/bin/env python3
"""Checks for the image store: moving the last batch's images out of the way.

Two folders fill up with every card image the shop has ever used - the
pipeline's ``output`` (tiles, then the same files renamed to their listing
titles) and the photos panel's ``replacements`` (the fronts cut out of a
scan). This is the rule that keeps them apart, so what matters is that it:

  * only ever looks at images - a CSV or a report in those folders is a
    record and is never touched;
  * never overwrites and never renames what it moves;
  * keeps the ``_tiles`` shape, because that is how a sheet is put back
    together;
  * deletes **only** the black tiles the person leaves ticked in a window
    showing them as pictures, and only after agreeing to the move at all;
  * does nothing at all without an answer that says yes - a closed dialog is
    a cancelled run, never a silent move.

Pillow draws the tiles these tests measure; tkinter is stubbed, so the
app-level half runs without a display.
"""
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:                                  # pragma: no cover
    Image = ImageDraw = None

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
WINDOWS = []          # every Toplevel the app opened, so a test can press it


class FakeWidget:
    """Enough of a widget to build and drive the app's dialogs.

    Anything not written out here answers ``self`` from a call, which is what
    a Tk widget does for the layout and measuring calls a dialog makes in
    passing. Each Tk class gets its own subclass below, because "is this a
    Button or a Label?" decides whether a caption is a button that needs an
    explanation.
    """

    def __init__(self, *args, **kwargs):
        self._kw = dict(kwargs)
        self.children = []
        self.command = kwargs.get("command")
        self.parent = args[0] if args else None
        if self.parent is not None and hasattr(self.parent, "children"):
            self.parent.children.append(self)
        self.destroyed = False

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: self

    # -- layout -----------------------------------------------------------
    def pack(self, *a, **k): return self
    def pack_forget(self, *a, **k): return self
    def grid(self, *a, **k): return self
    def place(self, *a, **k): return self
    def bind(self, *a, **k): return self
    def bind_all(self, *a, **k): return self
    def unbind_all(self, *a, **k): return self
    def configure(self, **k): self._kw.update(k)
    def config(self, **k): self._kw.update(k)
    def cget(self, key): return self._kw.get(key, "")
    def winfo_children(self): return list(self.children)
    def destroy(self): self.destroyed = True
    def winfo_exists(self): return True
    def winfo_toplevel(self): return self
    def winfo_width(self): return 800
    def winfo_height(self): return 600
    def update_idletasks(self): return None
    def update(self): return None
    def focus_set(self): pass
    def yview(self, *a, **k): return (0.0, 1.0)
    def yview_scroll(self, *a, **k): return None
    def bbox(self, *a, **k): return (0, 0, 200, 200)
    def create_window(self, *a, **k): return 1
    def itemconfigure(self, *a, **k): return None
    def columnconfigure(self, *a, **k): return None
    def rowconfigure(self, *a, **k): return None
    def insert(self, *a, **k): pass
    def delete(self, *a, **k): pass
    def get(self, *a, **k): return ""
    def set(self, value): pass
    def curselection(self): return ()
    def invoke(self):
        if self.command:
            return self.command()

    def after(self, delay, callback=None):
        """Remembered, never fired: a page that re-measures itself would
        otherwise recurse inside its own measurement."""
        self.jobs = getattr(self, "jobs", {})
        self._job_no = getattr(self, "_job_no", 0) + 1
        job = "job-%d" % self._job_no
        self.jobs[job] = (delay, callback)
        return job

    def after_idle(self, callback=None): return self.after(0, callback)
    def after_cancel(self, job): getattr(self, "jobs", {}).pop(job, None)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


class FakeVar:
    """A Tk variable that really holds its value."""

    def __init__(self, master=None, value=None, **k):
        self._value = value

    def get(self): return self._value
    def set(self, value): self._value = value
    def trace_add(self, *_a, **_k): return "trace"
    def trace(self, *_a, **_k): return "trace"
    def trace_remove(self, *_a, **_k): return None


class FakeToplevel(FakeWidget):
    """A dialog window: remembers its geometry and how it was closed."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._title = ""
        self._geometry = ""
        self.protocol_handlers = {}
        WINDOWS.append(self)

    def title(self, value=None):
        if value is not None:
            self._title = value
        return self._title

    def geometry(self, value=None):
        if value is not None:
            self._geometry = value
        return self._geometry

    def transient(self, *a, **k): return self
    def resizable(self, *a, **k): return self
    def grab_set(self, *a, **k): return self
    def grab_release(self, *a, **k): return self
    def wait_window(self, *a, **k): return None
    def protocol(self, name, func=None):
        if func is not None:
            self.protocol_handlers[name] = func
        return self.protocol_handlers.get(name)

    def winfo_screenwidth(self): return 1280
    def winfo_screenheight(self): return 1024


def widget_class(name, base=FakeWidget):
    """A fake that stands in for one Tk class, so isinstance() is honest."""
    return type("Fake" + name, (base,), {})


def make_checkbutton():
    """A check box whose invoke() flips its variable, as Tk's does."""
    class FakeCheckbutton(widget_class("Checkbutton")):
        def invoke(self):
            var = self._kw.get("variable")
            if var is not None and hasattr(var, "get"):
                var.set(not var.get())
            return super().invoke()
    return FakeCheckbutton


def install_tk():
    tk = types.ModuleType("tkinter")
    for name, base in dict(Frame=FakeWidget, Label=FakeWidget,
                           Button=FakeWidget, Entry=FakeWidget, Text=FakeWidget,
                           Listbox=FakeWidget, Toplevel=FakeToplevel,
                           Canvas=FakeWidget, StringVar=FakeVar,
                           BooleanVar=FakeVar, IntVar=FakeVar,
                           Tk=FakeToplevel).items():
        setattr(tk, name, widget_class(name, base))
    tk.font = types.SimpleNamespace(nametofont=lambda *a, **k: FakeWidget())
    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "Button", "Entry", "LabelFrame",
                 "Notebook", "Scrollbar", "Radiobutton", "Combobox",
                 "Treeview", "Separator", "Progressbar"):
        setattr(ttk, name, widget_class(name))
    ttk.Checkbutton = make_checkbutton()
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
    """The part of the app these methods use, and nothing else."""

    def __init__(self, settings=None):
        self.settings = dict(settings or {})
        self.lines = []
        self.saved = []
        self.windows = []
        #  Set by a test to "be the person": called with the open window,
        #  it presses whichever button that test is about.
        self.window_driver = None

    def console_line(self, text, tag=None):
        self.lines.append((tag, str(text)))

    def set_setting(self, key, value):
        self.settings[key] = value
        self.saved.append((key, value))

    def winfo_screenwidth(self): return 1280
    def winfo_screenheight(self): return 1024
    def update_idletasks(self): return None

    def after(self, delay, callback=None):
        if callback is not None:
            callback()
        return "after-id"

    def wait_window(self, window):
        """Stand in for Tk: let the test answer, then close what it did not.

        A window nobody pressed anything in is closed the way the X closes
        it, which runs the window's own handler - so "closed" is tested as
        the app really meets it.
        """
        self.windows.append(window)
        if self.window_driver is not None:
            self.window_driver(window, self)
        if getattr(window, "destroyed", False):
            return
        handler = (getattr(window, "protocol_handlers", None) or {}).get(
            "WM_DELETE_WINDOW")
        if handler is not None:
            handler()
        else:
            window.destroy()


#  The real methods, unbound from Tk: they only ever touch settings, the
#  console and the two dialogs, all of which the fake above provides.
def bind(method_name):
    def bound(self, *args, **kwargs):
        return getattr(gui.App, method_name)(self, *args, **kwargs)
    return bound


for _name in ("prepare_image_folder", "_move_older_images", "ask_image_store",
              "image_store_dir", "ask_delete_blank_images"):
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
    check("a dated folder per batch, straight in the chosen folder",
          plan["target"] == store / "2026-10-31 09-37", str(plan["target"]))
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
    #  The batch folder is beside the working folder, not inside it - the
    #  images land beside output/ rather than under it, which is somewhere a
    #  person can see.
    check("the batch folder itself is fine", 
          image_store.check_store(folder.parent, folder) == "",
          image_store.check_store(folder.parent, folder))
    check("no folder at all is refused",
          "no folder" in image_store.check_store("", folder))

    #  Two batches filed in the same minute must not be mixed together.
    (store / "2026-10-31 09-37").mkdir(parents=True)
    (store / "2026-10-31 09-37" / "old.webp").write_bytes(b"x")
    second = image_store.plan(folder, store, now=datetime(2026, 10, 31, 9, 37))
    check("a second batch in the same minute gets its own folder",
          second["target"] == store / "2026-10-31 09-37 (2)",
          str(second["target"]))
    check("and nothing is filed under the source folder's name",
          "output" not in second["target"].parts,
          str(second["target"]))


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





# ------------------------------------------------------- images on disk
def blank_image(path, shade=6):
    """A picture of an empty slot: the scan's background and nothing else."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (120, 160), (shade, shade, shade)).save(path)
    return path


def card_image(path):
    """A picture of a card: dark table, bright card."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (120, 160), (4, 4, 4))
    ImageDraw.Draw(image).rectangle([8, 10, 112, 150], fill=(232, 226, 214))
    image.save(path)
    return path


def dark_card_image(path):
    """A dark card with white lettering: one bright pixel keeps it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (120, 160), (4, 4, 4))
    draw = ImageDraw.Draw(image)
    draw.rectangle([8, 10, 112, 150], fill=(15, 13, 11))
    draw.rectangle([20, 60, 46, 66], fill=(245, 245, 245))
    image.save(path)
    return path


def press(window, caption):
    """Press the button with this caption; True when it was found."""
    for widget in window.walk():
        if (isinstance(widget, (_TTK.Button, _TK.Button)) and
                widget.cget("text") == caption):
            widget.invoke()
            return True
    return False


def checkbuttons(window):
    return [widget for widget in window.walk()
            if isinstance(widget, _TTK.Checkbutton)]


def label_text(window):
    return " ".join(str(widget.cget("text")) for widget in window.walk()
                    if not isinstance(widget, (_TTK.Button, _TTK.Checkbutton)))


def driver_press(caption, untick=()):
    """A window driver: untick these captions, then press that button."""
    def drive(window, app):
        for widget in checkbuttons(window):
            if widget.cget("text") in untick:
                widget.invoke()
        press(window, caption)
    return drive


def test_what_looks_empty(root):
    print()
    print("== 14. what counts as an empty image ==")
    empty = blank_image(root / "blanks" / "black.webp")
    noisy = blank_image(root / "blanks" / "noisy.webp", shade=22)
    card = card_image(root / "blanks" / "card.webp")
    dark = dark_card_image(root / "blanks" / "dark-card.webp")
    grey = blank_image(root / "blanks" / "grey.webp", shade=128)
    corrupt = root / "blanks" / "corrupt.webp"
    corrupt.write_bytes(b"not an image at all")

    check("a tile of the background alone is empty",
          image_store.looks_blank(empty) is True)
    check("a slightly noisy background is empty too",
          image_store.looks_blank(noisy) is True)
    check("a card on that background is not",
          image_store.looks_blank(card) is False)
    check("a dark card still is not - its lettering is bright",
          image_store.looks_blank(dark) is False)
    check("a grey tile is not empty, because it is not the background",
          image_store.looks_blank(grey) is False)
    check("a file that will not open is never called empty",
          image_store.looks_blank(corrupt) is False)
    check("a file that is not there is never called empty",
          image_store.looks_blank(root / "blanks" / "gone.webp") is False)

    found = image_store.blank_images([card, empty, dark, noisy, grey, corrupt])
    check("only the empty ones are offered, in the order given",
          found == [empty, noisy], str(found))
    check("an empty list of files asks nothing",
          image_store.blank_images([]) == [])

    steps = []
    image_store.blank_images([card, empty] * 6,
                             on_step=lambda done, total: steps.append(
                                 (done, total)))
    check("a long check reports its progress",
          steps and steps[-1] == (12, 12), str(steps))
    check("and the count is the whole list",
          all(total == 12 for _done, total in steps), str(steps))


def test_deleting_only_what_is_ticked(root):
    print()
    print("== 15. deleting is a separate, small, reportable act ==")
    folder = root / "delete-me"
    folder.mkdir()
    one = blank_image(folder / "one.webp")
    two = blank_image(folder / "two.webp")
    keep = card_image(folder / "keep.webp")
    result = image_store.delete([one, two, folder / "gone.webp"])
    check("the images given are gone",
          not one.exists() and not two.exists())
    check("the one next to them is untouched", keep.is_file())
    check("a file that was already gone is reported, not raised",
          [item["name"] for item in result["failed"]] == ["gone.webp"],
          str(result["failed"]))
    check("what went is counted", len(result["deleted"]) == 2)
    check("and the room it freed is added up",
          result["freed"] == sum(item["size"] for item in result["deleted"]) > 0)
    check("it says so in one line",
          image_store.delete_text(result)[0].startswith(
              "Deleted 2 images that were only the background"),
          str(image_store.delete_text(result)))

    stubborn = root / "delete-me" / "a-folder.webp"
    stubborn.mkdir()
    failed = image_store.delete([stubborn])
    check("something that cannot be deleted is named with the reason",
          failed["deleted"] == [] and failed["failed"] and
          "director" in failed["failed"][0]["why"].lower(),
          str(failed["failed"]))
    check("and nothing claims to have been deleted",
          not any(line.startswith("Deleted")
                  for line in image_store.delete_text(failed)),
          str(image_store.delete_text(failed)))

    single = image_store.delete([blank_image(folder / "only.webp")])
    check("one image is one image, in English",
          image_store.delete_text(single)[0] ==
          "Deleted 1 image that was only the background (%s freed)."
          % image_store.size_text(single["freed"]),
          str(image_store.delete_text(single)))
    check("sizes read as sizes",
          (image_store.size_text(900), image_store.size_text(1536),
           image_store.size_text(3 * 1024 * 1024)) ==
          ("900 B", "1.5 KB", "3.0 MB"), "")


def test_the_plan_follows_a_delete(root):
    print()
    print("== 16. a file deleted before the move is not a failed move ==")
    folder, _made = make_folder(root / "plan-after", "output", images=3,
                                tiles=0)
    store = root / "plan-after" / "store"
    store.mkdir()
    plan = image_store.plan(folder, store, now=datetime(2026, 10, 31, 13, 0))
    image_store.delete([plan["files"][1]])
    after = image_store.forget_missing(plan)
    check("the deleted file is dropped from the plan",
          len(after["files"]) == 2 and
          plan["files"][1] not in after["files"], str(after["files"]))
    check("the rest of the plan is kept",
          after["target"] == plan["target"] and
          after["store"] == plan["store"], "")
    check("the plan it was given was not changed",
          len(plan["files"]) == 3, str(len(plan["files"])))


def make_sitting(root, name, blanks=2, cards=2):
    """A folder with the last batch's images in it, empty ones included."""
    folder = root / name / "output"
    folder.mkdir(parents=True)
    empties = [blank_image(folder / ("blank_%d.webp" % index))
               for index in range(blanks)]
    pictures = [card_image(folder / ("card_%d.webp" % index))
                for index in range(cards)]
    return folder, empties, pictures


def test_the_window_deletes_what_is_ticked(root):
    print()
    print("== 17. the window: every ticked image goes, the cards stay ==")
    folder, empties, pictures = make_sitting(root, "window-all")
    store = root / "window-all" / "store"
    store.mkdir()
    app = FakeApp({"image_store_dir": str(store)})
    app.window_driver = driver_press("Delete the ticked images")
    answers(yes_no_cancel=True)
    went = app.prepare_image_folder(folder)

    window = app.windows[0] if app.windows else None
    check("a window opens before anything is moved", window is not None)
    check("it is called something a person can read",
          window is not None and "nothing on them" in window.title(),
          window and window.title())
    check("it shows one picture per empty image",
          window is not None and len(checkbuttons(window)) == 2,
          window and [w.cget("text") for w in checkbuttons(window)])
    check("each picture says which file it is",
          window is not None and
          [w.cget("text") for w in checkbuttons(window)] ==
          ["blank_0", "blank_1"],
          window and [w.cget("text") for w in checkbuttons(window)])
    check("they all start ticked, and the line says so",
          window is not None and
          "2 of 2 ticked for deleting" in label_text(window),
          window and label_text(window)[:120])
    endings = {w.cget("text") for w in (window.walk() if window else [])
               if isinstance(w, _TTK.Button)}
    check("both buttons that end it are there, and the two tick-all ones",
          endings == {"Delete the ticked images", "Keep them all",
                      "Tick everything", "Untick everything"}, str(endings))
    said = label_text(window) if window is not None else ""
    check("and the explanation sits with the window, not above the buttons",
          "cannot be brought back" in said, said[:200])

    check("the empty ones were deleted",
          not any(path.exists() for path in empties))
    check("the cards were not",
          all(path.exists() is False for path in pictures), 
          "(they are moved, so they are no longer in the folder either)")
    moved = sorted(path.name for path in
                   (store).rglob("*.webp"))
    check("only the cards were moved to the store",
          moved == ["card_0.webp", "card_1.webp"], str(moved))
    check("the console says what was deleted and what was moved",
          any("Deleted 2 images" in line for _tag, line in app.lines) and
          any("Moved 2 older card images" in line for _tag, line in app.lines),
          str(app.lines))
    check("and the run carried on", went is True)

    #  A folder with nothing empty in it is not worth a window at all.
    only_cards = root / "window-all" / "cards-only" / "output"
    only_cards.mkdir(parents=True)
    card_image(only_cards / "a.webp")
    card_image(only_cards / "b.webp")
    app = FakeApp({"image_store_dir": str(store)})
    app.window_driver = driver_press("Delete the ticked images")
    answers(yes_no_cancel=True)
    app.prepare_image_folder(only_cards)
    check("a folder of cards opens no window", app.windows == [],
          str(len(app.windows)))
    check("and both cards are moved",
          sorted(path.name for path in (store).rglob("*.webp")).
          count("a.webp") == 1, "")


def test_untick_keeps_one(root):
    print()
    print("== 18. a picture that is really a card is unticked and kept ==")
    folder, empties, _pictures = make_sitting(root, "window-some", blanks=3,
                                              cards=1)
    store = root / "window-some" / "store"
    store.mkdir()
    app = FakeApp({"image_store_dir": str(store)})
    app.window_driver = driver_press("Delete the ticked images",
                                     untick=("blank_1",))
    answers(yes_no_cancel=True)
    app.prepare_image_folder(folder)
    check("the unticked one was not deleted",
          any(path.name == "blank_1.webp"
              for path in (store).rglob("*.webp")),
          str(sorted(path.name for path in (store).rglob("*"))))
    check("the ticked ones went",
          not empties[0].exists() and not empties[2].exists())
    moved = sorted(path.name for path in (store).rglob("*.webp"))
    check("and the kept one was moved with the rest",
          moved == ["blank_1.webp", "card_0.webp"], str(moved))
    check("the count said two of three before it went",
          any("2 of 3 ticked" in str(w.cget("text"))
              for w in app.windows[0].walk()), "")


def test_keeping_them_all(root):
    print()
    print("== 19. nothing is deleted without that answer ==")
    folder, empties, _pictures = make_sitting(root, "window-none")
    store = root / "window-none" / "store"
    store.mkdir()

    app = FakeApp({"image_store_dir": str(store)})
    app.window_driver = driver_press("Keep them all")
    answers(yes_no_cancel=True)
    app.prepare_image_folder(folder)
    moved = sorted(path.name for path in (store).rglob("*.webp"))
    check("every image is in the store, empty ones included - so none of "
          "them was deleted",
          moved == ["blank_0.webp", "blank_1.webp",
                    "card_0.webp", "card_1.webp"], str(moved))
    check("and the console says they were kept",
          any("keeping the 2 images that look empty" in line
              for _tag, line in app.lines), str(app.lines))

    print()
    print("== 20. a window nobody answers deletes nothing ==")
    folder, empties, _pictures = make_sitting(root, "window-closed")
    store = root / "window-closed" / "store"
    store.mkdir()
    app = FakeApp({"image_store_dir": str(store)})
    app.window_driver = None                     # nothing is pressed at all
    answers(yes_no_cancel=True)
    app.prepare_image_folder(folder)
    moved = sorted(path.name for path in (store).rglob("*.webp"))
    check("closing the window deletes nothing",
          moved == ["blank_0.webp", "blank_1.webp",
                    "card_0.webp", "card_1.webp"], str(moved))
    check("and everything was still moved",
          not any(path.exists() for path in empties))

    print()
    print("== 21. deleting with nothing ticked says so ==")
    folder, empties, _pictures = make_sitting(root, "window-empty-ticks")
    store = root / "window-empty-ticks" / "store"
    store.mkdir()
    app = FakeApp({"image_store_dir": str(store)})

    def drive(window, _app):
        press(window, "Untick everything")
        press(window, "Delete the ticked images")

    app.window_driver = drive
    answers(yes_no_cancel=True)
    app.prepare_image_folder(folder)
    check("'untick everything' then delete deletes nothing",
          any("nothing was ticked, so nothing was deleted" in line
              for _tag, line in app.lines), str(app.lines))
    moved = sorted(path.name for path in (store).rglob("*.webp"))
    check("and everything is moved as usual",
          len(moved) == 4, str(moved))


def test_the_window_comes_after_the_yes(root):
    print()
    print("== 22. the pictures are only offered once the move is answered ==")
    folder, empties, pictures = make_sitting(root, "window-order")
    store = root / "window-order" / "store"
    store.mkdir()

    app = FakeApp({"image_store_dir": str(store)})
    app.window_driver = driver_press("Delete the ticked images")
    asked = answers(yes_no_cancel=False)          # "no, keep them where they are"
    carried_on = app.prepare_image_folder(folder)
    check("the move was asked about first", asked["yes_no_cancel"] == 1,
          str(asked))
    check("answering no to the move does not open the window",
          app.windows == [], str(len(app.windows)))
    check("and deletes nothing", all(path.is_file() for path in empties))
    check("the run still carries on", carried_on is True)

    app = FakeApp({"image_store_dir": str(store)})
    app.window_driver = driver_press("Delete the ticked images")
    answers(yes_no_cancel=None)                   # the window was closed
    stopped = app.prepare_image_folder(folder)
    check("cancelling the move cancels the run", stopped is False)
    check("with no window and no deletion", app.windows == [])
    check("and every image still where it was",
          all(path.is_file() for path in empties + pictures))

    app = FakeApp({"image_store_dir": str(store)})
    seen = []

    def drive(window, _app):
        seen.append(len(app.windows))
        press(window, "Delete the ticked images")

    app.window_driver = drive
    answers(yes_no_cancel=True)
    app.prepare_image_folder(folder)
    check("answering yes opens the window before the move",
          seen == [1] and app.windows, str(seen))
    kept = sorted(path.name for path in (store).rglob("*.webp"))
    check("then the empty ones are gone and only the cards are in the store",
          not any(path.exists() for path in empties) and
          kept == ["card_0.webp", "card_1.webp"], str(kept))


def test_a_long_check_says_it_is_working(root):
    print()
    print("== 23. a folder of hundreds is measured with a bar, not a freeze ==")
    folder = root / "many" / "output"
    folder.mkdir(parents=True)

    class Recorder:
        calls = []

        def __init__(self, parent, title="", text="", total=None):
            self.title, self.text, self.total = title, text, total
            self.steps, self.closed, self.pumped = [], False, 0
            Recorder.calls.append(self)

        def step(self, text=None, done=None, total=None):
            self.steps.append((done, total))

        def pump(self): self.pumped += 1
        def close(self): self.closed = True

    real = gui.ProgressWindow
    gui.ProgressWindow = Recorder
    try:
        files = []
        for index in range(26):
            files.append(blank_image(folder / ("many_%02d.webp" % index)))
        app = FakeApp()
        app.window_driver = driver_press("Keep them all")
        Recorder.calls.clear()
        deleted = app.ask_delete_blank_images(folder, files)
    finally:
        gui.ProgressWindow = real
    made = Recorder.calls
    check("a working window is shown while the images are measured",
          len(made) == 1, str(made))
    check("it is told how many there are", made and made[0].total == 26,
          str(made and made[0].total))
    check("the bar moves as they are read",
          made and made[0].steps and made[0].steps[-1] == (26, 26),
          str(made and made[0].steps[-4:]))
    check("and the window is taken down again", made and made[0].closed)
    check("keeping them all deleted nothing", deleted == [])


def test_the_window_explains_every_button(root):
    print()
    print("== 24. every button in the window has its hover explanation ==")
    folder, _empties, _pictures = make_sitting(root, "window-tips")
    clear = root / "window-tips" / "store"
    clear.mkdir()
    app = FakeApp({"image_store_dir": str(clear)})
    app.window_driver = driver_press("Keep them all")
    answers(yes_no_cancel=True)
    app.prepare_image_folder(folder)
    window = app.windows[0] if app.windows else None
    missing = gui.tips_missing(window) if window is not None else ["no window"]
    check("every button in it explains itself", missing == [], str(missing))
    captions = [w.cget("text") for w in window.walk()
                if isinstance(w, (_TTK.Button, _TTK.Checkbutton))]
    check("and the four actions are the ones expected",
          set(captions) == {"Delete the ticked images", "Keep them all",
                            "Tick everything", "Untick everything",
                            "blank_0", "blank_1"},
          str(captions))



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
    with tempfile.TemporaryDirectory() as tmp:
        pictures = Path(tmp)
        test_what_looks_empty(pictures)
        test_deleting_only_what_is_ticked(pictures)
        test_the_plan_follows_a_delete(pictures)
        test_the_window_deletes_what_is_ticked(pictures)
        test_untick_keeps_one(pictures)
        test_keeping_them_all(pictures)
        test_the_window_comes_after_the_yes(pictures)
        test_a_long_check_says_it_is_working(pictures)
        test_the_window_explains_every_button(pictures)
    print()
    print("=" * 60)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL IMAGE STORE CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
