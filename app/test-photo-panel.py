#!/usr/bin/env python3
"""Drive the real Photos panel against a stubbed Tk.

test-gui.py checks the panel with a real Tk, so it needs Windows (or Tk
anywhere). This file answers the other half: it replaces Tk with small fakes so
the panel's decisions - which image goes where, which arguments reach the
plugin, and what happens with an older plugin - can be checked in the same
places the other headless tests run.

It earns its keep. It caught a product lookup that discarded the gallery (so
every replacement was named after the scan instead of the card), an inverted
"keep the old photos" answer, and a pair counter that could drift apart.

No network: the site is a fake, and the uploader is replaced.
"""
import json
import shutil
import sys
import tempfile
import types
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


# --------------------------------------------------------------- Tk stand-ins
class FakeWidget:
    def __init__(self, *args, **kwargs):
        self._kw = dict(kwargs)
        self.packed = False
        self.children = []
        self.command = kwargs.get("command")
        self.value = kwargs.get("text", "")
        self.items = []
        self.selection = ()
        self.parent = args[0] if args else None
        if self.parent is not None and hasattr(self.parent, "children"):
            self.parent.children.append(self)

    def pack(self, *a, **k):
        self.packed = True
        return self

    def pack_forget(self, *a, **k):
        self.packed = False

    def grid(self, *a, **k): return self
    def place(self, *a, **k): return self
    def bind(self, *a, **k): return self
    def configure(self, **k): self._kw.update(k)
    def config(self, **k): self._kw.update(k)
    def cget(self, key):
        return self._kw.get("text", self.value) if key == "text" \
            else self._kw.get(key, "")
    def winfo_children(self): return list(self.children)
    def destroy(self):
        #  A destroyed widget leaves its parent: the panel rebuilds its grid
        #  after the pictures are decoded, and the old cells must be gone.
        parent = getattr(self, "parent", None)
        if parent is not None and hasattr(parent, "children"):
            try:
                parent.children.remove(self)
            except ValueError:
                pass

    def focus_set(self): pass
    def yview(self, *a, **k): return (0.0, 1.0)
    def xview(self, *a, **k): return (0.0, 1.0)
    def see(self, *a, **k): return None
    def protocol(self, *a, **k): return None
    def insert(self, *a, **k):
        if a and a[0] == "end":
            self.items.append(a[1])
    def delete(self, *a, **k):
        if a and a[0] == 0:
            self.items = []
    def get(self, *args, **kwargs):
        return self.value      # Text.get("1.0", "end") and Entry.get()
    def set(self, value): self.value = value
    def curselection(self):
        return self.selection or ((0,) if self.items else ())
    def selection_set(self, index): self.selection = (index,)
    def invoke(self):
        if self.command:
            self.command()
    # -- the handful of calls a scrollable canvas makes ---------------------
    def create_window(self, *a, **k): return 1
    def itemconfigure(self, *a, **k): return None
    def bbox(self, *a, **k): return (0, 0, 200, 200)
    def yview_scroll(self, *a, **k): return None
    def bind_all(self, *a, **k): return None
    def unbind_all(self, *a, **k): return None
    def winfo_containing(self, *a, **k): return None
    def winfo_toplevel(self): return self
    def add(self, child, **kwargs):
        """ttk.Notebook.add: remember the tab and its label."""
        self.tabs = getattr(self, "tabs", [])
        self.tabs.append((child, kwargs.get("text", "")))
        return child

    def select(self, *a, **k): return None

    def columnconfigure(self, *a, **k): return None
    def rowconfigure(self, *a, **k): return None
    def grid_columnconfigure(self, *a, **k): return None
    def update(self): return None
    def update_idletasks(self): return None
    def winfo_rootx(self): return 0
    def winfo_rooty(self): return 0
    def winfo_width(self): return 800
    def winfo_height(self): return 600
    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


class FakeVar:
    def __init__(self, master=None, value=None, **k): self._value = value
    def get(self): return self._value
    def set(self, value): self._value = value


class FakeToplevel(FakeWidget):
    """A picker window; the harness presses one of its buttons."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._title = k.get("title", "")
        self._geometry = ""
        self.resizable = lambda *a, **k: self
    def title(self, value=None):
        if value is not None: self._title = value
        return self._title
    def transient(self, *a, **k): return self
    def geometry(self, value=None):
        if value is not None:
            self._geometry = value
        return self._geometry
    def grab_set(self, *a, **k): return self
    def wait_window(self, *a, **k):
        PICKER["press"](self)


PICKER = {"press": lambda window: None}


def widget_class(name, base=FakeWidget):
    """A fake that stands in for one Tk class, so isinstance() still works.

    Everything used to be the same FakeWidget, which made "is this a Button
    or a LabelFrame?" unanswerable - and the tabs view is laid out entirely in
    LabelFrame sections, so the difference is exactly what a test needs.
    """
    return type("Fake" + name, (base,), {})


def install_tk():
    tk = types.ModuleType("tkinter")
    for name, base in dict(Frame=FakeWidget, Label=FakeWidget,
                           Button=FakeWidget, Entry=FakeWidget,
                           Text=FakeWidget, Listbox=FakeWidget,
                           Toplevel=FakeToplevel, Canvas=FakeWidget,
                           StringVar=FakeVar, BooleanVar=FakeVar,
                           IntVar=FakeVar, Tk=FakeWidget).items():
        setattr(tk, name, widget_class(name, base))
    tk.font = types.SimpleNamespace(nametofont=lambda *a, **k: FakeWidget())
    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "Button", "Entry", "LabelFrame", "Notebook",
                 "Scrollbar", "Checkbutton", "Radiobutton", "Combobox",
                 "Treeview", "Separator", "Progressbar"):
        setattr(ttk, name, widget_class(name))
    ttk.Style = lambda *a, **k: types.SimpleNamespace(
        configure=lambda *a, **k: None, lookup=lambda *a, **k: "22",
        theme_use=lambda *a, **k: None, map=lambda *a, **k: None)
    dialog = types.ModuleType("tkinter.filedialog")
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
    for name, module in (("tkinter", tk), ("tkinter.ttk", ttk),
                         ("tkinter.filedialog", dialog),
                         ("tkinter.messagebox", box),
                         ("tkinter.simpledialog", prompt)):
        sys.modules[name] = module
    tk.ttk, tk.filedialog = ttk, dialog
    tk.messagebox, tk.simpledialog = box, prompt
    return tk, ttk, dialog, box


_TK, _TTK, _DIALOG, _BOX = install_tk()

import gui                                     # noqa: E402
import photo_pool                              # noqa: E402
import photo_replace                           # noqa: E402
import photo_thumbs as panel_thumbs            # noqa: E402
from PIL import Image                          # noqa: E402


# --------------------------------------------------------------- app stand-in
class FakeApp:
    def __init__(self, folder):
        self.settings = {"browser_name": "system", "scan_dir": str(folder),
                         "pipeline_dir": str(folder),
                         "woo_site_url": "https://shop.example",
                         "canadianshopper_store_url": "https://cs.example/x",
                         "ebay_selling_url": "https://www.ebay.ca/sh/lst",
                         "facebook_selling_url": "https://fb.example/selling"}
        self.cs_addon = True
        self.runs, self.opened, self.lines = [], [], []

    def run_tool(self, tool, args, title, cwd=None, on_done=None, confirm=None):
        self.runs.append({"args": [str(a) for a in args], "title": title})
        return True

    def open_webpages(self, urls, new_window=False):
        self.opened.extend(urls)
        return "Test browser"

    def console_line(self, text, tag=""):
        self.lines.append((tag, str(text)))

    def wait_window(self, window):
        window.wait_window()

    def winfo_screenwidth(self):
        return 800          # the small screen the picker has to fit on

    def winfo_screenheight(self):
        return 600

    def winfo_rootx(self): return 0
    def winfo_rooty(self): return 0
    def winfo_width(self): return 800
    def winfo_height(self): return 600


PRODUCT = {"id": 42,
           "name": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
           "sku": "SKU-1",
           "images": [{"id": 5, "src": "https://shop.example/u/gretzky-front.webp"},
                      {"id": 6, "src": "https://shop.example/u/gretzky-back.webp"},
                      {"id": 9, "src": "https://shop.example/u/certificate.webp"}]}


def install_plugin(version, folder):
    """A real installed plugin package, so the action and version are real."""
    root = folder / "plugins"
    gui.PLUGIN_MANAGER = gui.PluginManager(root=root)
    source = folder / "plugin-src"
    (source / "tools").mkdir(parents=True, exist_ok=True)
    for tool in ("sold-cards.py", "cs-image-sync.py", "cs-image-wire.py"):
        (source / "tools" / tool).write_text("# stub\n", encoding="utf-8")
    (source / "plugin.json").write_text(json.dumps({
        "id": "canadianshopper", "name": "stub", "version": version,
        "host_api": 1, "min_core_version": "2.33", "description": "test stub",
        "capabilities": ["batch.photo_stage", "batch.photo_wire",
                         "batch.photo_replace"],
        "actions": {"batch.photo_stage": "sync", "batch.photo_wire": "wire",
                    "batch.photo_replace": "sync"},
        "tools": {"sync": "tools/cs-image-sync.py",
                  "wire": "tools/cs-image-wire.py"}}), encoding="utf-8")
    gui.PLUGIN_MANAGER.install_zip(
        shutil.make_archive(str(folder / "pkg"), "zip", root_dir=source))


def make_sheet(path, blanks=(2, 9)):
    """A real 3x3 sheet: white cards, the rest black (an empty slot)."""
    tile = 600
    sheet = Image.new("RGB", (tile * 3, tile * 3 + 400), (0, 0, 0))
    position = 1
    for row in range(3):
        for col in range(3):
            if position not in blanks:
                sheet.paste((235, 230, 220),
                            (col * tile + 80, row * tile + 80,
                             (col + 1) * tile - 80, (row + 1) * tile - 80))
            position += 1
    sheet.save(path)
    return path


SHEET_CALLS = []
QUESTIONS = []


def drive(app, sheet, yes_for=(), nocancel=None, wordpress=("owner", "pw"),
          site="https://shop.example", product=None, press=None,
          scancount=1, found=True, cards=1):
    """Press Find with a scripted sheet, answers and picker behaviour.

    ``cards`` presses Find more than once on the same panel, which is how a
    whole sheet is worked through in one sitting.
    """
    SHEET_CALLS.clear()
    product = product or PRODUCT
    parent = FakeWidget()
    gui.build_newphotos(parent, app)
    widgets = list(parent.walk())
    find = next(w for w in widgets if w.cget("text") == "Find the card...")
    entry = next(w._kw["textvariable"] for w in widgets
                 if w._kw.get("textvariable") is not None)
    entry.set("gretzky")
    asked = []

    def ask(title, *a, **k):
        asked.append(title)
        return title in yes_for

    def first_button(window):
        for w in window.walk():
            if w.cget("text") == "Use this image":
                w.invoke()
                return
        window.destroy()

    PICKER["press"] = press or first_button
    _BOX.askyesno = ask
    _BOX.askyesnocancel = lambda title, *a, **k: (
        asked.append(title),
        QUESTIONS.append((title, a[0] if a else "")),
        nocancel)[2]
    #  Sheets are picked as a group now, once for the whole sitting; the
    #  single-file dialog is only used for "the back is on another scan".
    sheets = [str(sheet)] * scancount

    def pick_sheets(**_kw):
        SHEET_CALLS.append(1)
        return (sheets.pop(0),) if sheets else ()

    _DIALOG.askopenfilenames = pick_sheets
    _DIALOG.askopenfilename = lambda **k: str(sheet)
    keys = (site, "ck_live", "cs_live")
    wp = (site, wordpress[0], wordpress[1]) if wordpress else (site, "", "")
    with patch.object(gui, "has_woo_credentials", lambda path=None: True), \
            patch.object(gui, "read_woo_credentials", lambda path=None: keys), \
            patch.object(gui, "read_wordpress_credentials", lambda path=None: wp), \
            patch.object(gui, "woo_get",
                         lambda *a, **k: (200, [product] if found else [])):
        for _card in range(max(1, cards)):
            find.invoke()
    return asked


def replace_args(app):
    for run in app.runs:
        if run["args"][:2] == ["--mode", "replace"]:
            return run["args"]
    return None


def flag(args, name):
    return args[args.index(name) + 1] if args and name in args else None


UPLOADS = []


def fake_upload(site, key, secret, username, password, product, front_path,
                back_path=None, keep_ids=None, **rest):
    UPLOADS.append({"front": Path(front_path).name,
                    "back": Path(back_path).name if back_path else None,
                    "keep_ids": keep_ids,
                    "after_plugin_calls": len(UPLOADS) and None})
    return {"front": {"id": 901, "source_url": "https://shop.example/f.webp"},
            "back": ({"id": 902, "source_url": "https://shop.example/b.webp"}
                     if back_path else None),
            "product": {"id": 42}, "image_ids": [901, 902]}


def test_version_gates():
    print("== 1. the plugin version decides what is offered ==")
    folder = Path(tempfile.mkdtemp())
    for version, replace_ok, back_ok in (
            ("1.0.14", False, False), ("1.0.15", True, False),
            ("1.0.16", True, True), ("1.1", True, True),
            ("1.0.9", False, False)):
        install_plugin(version, folder / version.replace(".", "_"))
        check("%s: CSV-free replace %s" % (version,
                                           "offered" if replace_ok else "refused"),
              gui.photo_replace_available() is replace_ok,
              str(gui.photo_replace_available()))
        check("%s: --back %s" % (version,
                                 "allowed" if back_ok else "held back"),
              gui.photo_back_replaceable() is back_ok,
              str(gui.photo_back_replaceable()))


UPLOADED = []


def capture_upload(site, key, secret, username, password, product, front_path,
                   back_path=None, keep_ids=None, **rest):
    """Record what would have been sent to the website."""
    UPLOADED.append({"site": site, "keep_ids": keep_ids,
                     "front": Path(front_path).name,
                     "back": Path(back_path).name if back_path else None})
    return {"front": {"id": 901, "source_url": "https://shop.example/f.webp"},
            "back": ({"id": 902, "source_url": "https://shop.example/b.webp"}
                     if back_path else None),
            "product": {"id": 42}, "image_ids": [901, 902]}


def test_pair_saved_and_sent():
    print()
    print("== 2. both halves are picked, saved as a pair, and sent ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    sheet = make_sheet(folder / "Scan-1.jpg")
    app = FakeApp(folder)
    UPLOADS.clear()
    with patch.object(gui.woo_media, "replace_product_photos", fake_upload):
        asked = drive(app, sheet, nocancel=False,
                      yes_for={"Replace the CanadianShopper photos?"})
    files = sorted(p.name for p in (folder / "replacements").glob("*.webp"))
    check("the front and back are saved as one pair",
          files == ["gretzky-back-1.webp", "gretzky-front-1.webp"], str(files))
    args = replace_args(app)
    check("both halves reach the plugin",
          flag(args, "--front") and flag(args, "--back"), str(args))
    check("their names differ only by the side",
          Path(flag(args, "--front")).name.replace("-front", "-back") ==
          Path(flag(args, "--back")).name, str(args))
    check("the same pair is uploaded to the website",
          len(UPLOADS) == 1 and UPLOADS[0]["front"] == "gretzky-front-1.webp"
          and UPLOADS[0]["back"] == "gretzky-back-1.webp", str(UPLOADS))
    check("the panel asks about the website",
          "Put these photos on the website?" in asked, str(asked))


def test_old_plugin_takes_front_only():
    print()
    print("== 3. a 1.0.15 plugin gets the front and no back ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.15", folder / "plugin")
    sheet = make_sheet(folder / "Scan-1.jpg")
    app = FakeApp(folder)
    _BOX.shown.clear()
    UPLOADS.clear()
    with patch.object(gui.woo_media, "replace_product_photos", fake_upload):
        drive(app, sheet, nocancel=False,
              yes_for={"Replace the CanadianShopper photos?"})
    args = replace_args(app)
    check("the front is still replaced", args is not None, str(app.runs))
    check("no --back is sent to a plugin that would only append it",
          flag(args, "--back") is None, str(args))
    check("the user is told the back was held back",
          any(kind == "showwarning" and "back" in str(payload).lower()
              for kind, payload in _BOX.shown), str(_BOX.shown))
    check("the pair is still written as a matched pair for a later run",
          sorted(p.name for p in (folder / "replacements").glob("*.webp")) ==
          ["gretzky-back-1.webp", "gretzky-front-1.webp"], "")


def test_old_plugin_refused():
    print()
    print("== 4. a 1.0.14 plugin is refused outright ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.14", folder / "plugin")
    sheet = make_sheet(folder / "Scan-1.jpg")
    app = FakeApp(folder)
    _BOX.shown.clear()
    UPLOADS.clear()
    with patch.object(gui.woo_media, "replace_product_photos", fake_upload):
        drive(app, sheet, nocancel=True)
    check("nothing is sent to the plugin", not app.runs, str(app.runs))
    check("the user is told which version is needed",
          any(kind == "showwarning" and "1.0.15" in str(payload)
              for kind, payload in _BOX.shown), str(_BOX.shown))
    check("the website work still happens", len(UPLOADS) == 1, str(UPLOADS))


def test_back_from_another_sheet():
    print()
    print("== 5. the back can come from a different scan ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    front_sheet = make_sheet(folder / "Scan-front.jpg")
    back_sheet = make_sheet(folder / "Scan-back.jpg",
                            blanks=(1, 3, 4, 5, 6, 7, 8, 9))
    app = FakeApp(folder)
    picked = {"n": 0}

    def use_another(window):
        picked["n"] += 1
        if picked["n"] == 2:
            _DIALOG.askopenfilename = lambda **k: str(back_sheet)
            for w in window.walk():
                if w.cget("text") == "Another scan...":
                    w.invoke()
                    break
        for w in window.walk():
            if w.cget("text") == "Use this image":
                w.invoke()
                return

    UPLOADS.clear()
    with patch.object(gui.woo_media, "replace_product_photos", fake_upload):
        drive(app, front_sheet, nocancel=False, press=use_another,
              yes_for={"Replace the CanadianShopper photos?"})
    args = replace_args(app)
    check("both halves are still sent", flag(args, "--back") is not None,
          str(args))
    files = sorted(p.name for p in (folder / "replacements").glob("*.webp"))
    check("the pair still shares one counter", files == [
        "gretzky-back-1.webp", "gretzky-front-1.webp"], str(files))


def test_front_only_by_choice():
    print()
    print("== 6. choosing no back leaves the back alone ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    sheet = make_sheet(folder / "Scan-1.jpg")
    app = FakeApp(folder)
    UPLOADS.clear()
    with patch.object(gui.woo_media, "replace_product_photos", fake_upload):
        drive(app, sheet, nocancel=False, press=lambda w: (
            w.destroy() if any(x.cget("text") == "Cancel" and
                               "BACK" in str([y.cget("text") for y in w.walk()])
                               for x in w.walk())
            else next(x for x in w.walk()
                      if x.cget("text") == "Use this image").invoke()),
            yes_for={"No back image", "Replace the CanadianShopper photos?"})
    args = replace_args(app)
    check("only the front is sent", flag(args, "--back") is None, str(args))
    check("only the front is written",
          sorted(p.name for p in (folder / "replacements").glob("*.webp")) ==
          ["gretzky-front-1.webp"], "")
    check("only the front is uploaded",
          UPLOADS and UPLOADS[0]["back"] is None, str(UPLOADS))


def test_no_product_found():
    print()
    print("== 6b. the search fallback still saves the chosen images ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    sheet = make_sheet(folder / "Scan-1.jpg")
    app = FakeApp(folder)
    UPLOADS.clear()
    _BOX.shown.clear()
    #  No product matches, so the panel falls back to the product list. The
    #  plugin needs a title and there is none, so it must not be offered -
    #  accepting that offer used to fail on a missing name.
    with patch.object(gui.woo_media, "replace_product_photos", fake_upload):
        asked = drive(app, sheet, found=False,
                      yes_for={"Replace the CanadianShopper photos?",
                               "Put these photos on the website?"})
    files = sorted(p.name for p in (folder / "replacements").glob("*.webp"))
    check("the chosen images are still saved", len(files) == 2, str(files))
    check("they are named from the scan", all("Scan-1" in f for f in files),
          str(files))
    check("the plugin is not called without a product title", not app.runs,
          str(app.runs))
    check("nothing is uploaded without a product", not UPLOADS, str(UPLOADS))
    check("the pages still open", app.opened, str(app.opened))
    check("the plugin is not even offered without a product",
          not [t for t in asked if "CanadianShopper" in t], str(asked))


def press_first_tile(window):
    """Accept whichever image the picker has selected."""
    for w in window.walk():
        if w.cget("text") == "Use this image":
            w.invoke()
            return
    window.destroy()


def test_same_slot_back():
    print()
    print("== 10. the back is proposed from the same slot ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    front_sheet = make_sheet(folder / "Scan-front.jpg")
    back_sheet = make_sheet(folder / "Scan-back.jpg")
    app = FakeApp(folder)
    #  Both sheets are already loaded, the way they are after Add sheets.
    app.photo_pool = photo_pool.PhotoPool(tiles_dir=folder / "tiles")
    app.photo_pool.add_sheet(front_sheet, index=0)
    app.photo_pool.add_sheet(back_sheet, index=1)

    picked = {"n": 0, "front": "", "back": ""}

    def shown(window):
        """What the picker has selected, read the way the user would see it."""
        for w in window.walk():
            if w._kw.get("height") == 11 and w.items:
                index = w.curselection()[0]
                return w.items[index]
        return ""

    def press(window):
        picked["n"] += 1
        if picked["n"] == 1:
            #  Deliberately not the first image: slot 4, not slot 1, so the
            #  pairing is proven rather than stumbled into by list order.
            for w in window.walk():
                if w._kw.get("height") == 11:
                    w.selection_set(2)
            picked["front"] = shown(window)
        else:
            picked["back"] = shown(window)
        for w in window.walk():
            if w.cget("text") == "Use this image":
                w.invoke()
                return

    asked = drive(app, front_sheet, scancount=0, press=press, nocancel=False,
                  yes_for={"Replace the CanadianShopper photos?"})
    check("the loaded sheets are not asked for again", not SHEET_CALLS,
          str(SHEET_CALLS))
    args = replace_args(app)
    check("the front is the image that was chosen", "Slot 4" in picked["front"],
          picked["front"])
    check("the back offered is the same slot", "Slot 4" in picked["back"],
          picked["back"])
    check("it comes from the back sheet", "Scan-back" in picked["back"],
          picked["back"])
    check("the pairing is marked as the proposed one",
          "proposed" in picked["back"], picked["back"])
    check("both halves were sent", args is not None and "--back" in args,
          str(args))
    check("the pair is named from the card, not the scan",
          args is not None and
          Path(flag(args, "--front")).name.replace("-front", "-back") ==
          Path(flag(args, "--back")).name, str(args))
    check("the pairing did not need a second question", picked["n"] == 2,
          str(picked["n"]))
    check("the used images are remembered",
          app.photo_pool.progress() == (2, 14),
          str(app.photo_pool.progress()))
    shutil.rmtree(folder, ignore_errors=True)


def test_two_cards_one_sitting():
    print()
    print("== 11. one sheet, two cards, one sitting ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    sheet = make_sheet(folder / "Scan-01.jpg")
    app = FakeApp(folder)
    drive(app, sheet, scancount=1, cards=2, press=press_first_tile,
          nocancel=False, yes_for={"Replace the CanadianShopper photos?"})
    check("the sheet is chosen once for both cards", len(SHEET_CALLS) == 1,
          str(SHEET_CALLS))
    check("both cards were sent to the plugin", len(app.runs) == 2,
          str([r["title"] for r in app.runs]))
    fronts = [flag(run["args"], "--front") for run in app.runs
              if "--front" in run["args"]]
    check("two cards, two different front images", len(set(fronts)) == 2,
          str(fronts))
    check("the first card was not offered again for the second",
          all(fronts), str(fronts))
    check("the panel knows how much of the sheet is left",
          app.photo_pool.progress() == (4, 7),
          str(app.photo_pool.progress()))
    names = sorted(p.name for p in (folder / "replacements").glob("*.webp"))
    check("each card kept its own pair counter",
          names == ["gretzky-back-1.webp", "gretzky-back-2.webp",
                    "gretzky-front-1.webp", "gretzky-front-2.webp"],
          str(names))
    shutil.rmtree(folder, ignore_errors=True)


def test_unreadable_old_back():
    print()
    print("== 12. an old back with no readable name is asked about ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    sheet = make_sheet(folder / "Scan-01.jpg")
    app = FakeApp(folder)
    #  A gallery from before the -front/-back convention: the second photo is
    #  the old back, but nothing in its name says so.
    unreadable = {"id": 42,
                  "name": "1972-73 O-Pee-Chee Dave Burrows #133",
                  "sku": "SKU-1",
                  "images": [
                      {"id": 11, "src": "https://shop.example/u/IMG_2231.jpg"},
                      {"id": 12, "src": "https://shop.example/u/IMG_2232.jpg"},
                      {"id": 13, "src": "https://shop.example/u/"
                                        "certificate.jpg"}]}
    seen = {"rows": [], "asked": ""}

    def press(window):
        labels = [w.cget("text") for w in window.walk()]
        if "Remove this photo from the product" in labels:
            listing = next(w for w in window.walk()
                           if w._kw.get("height") == 8)
            seen["rows"] = list(listing.items)
            wanted = [i for i, text in enumerate(seen["rows"])
                      if "IMG_2232" in text]
            listing.selection_set(wanted[0] if wanted else 0)
            for w in window.walk():
                if w.cget("text") == "Remove this photo from the product":
                    w.invoke()
                    return
        for w in window.walk():
            if w.cget("text") == "Use this image":
                w.invoke()
                return
        window.destroy()

    UPLOADED.clear()
    QUESTIONS.clear()
    with patch.object(gui.woo_media, "replace_product_photos", capture_upload):
        drive(app, sheet, scancount=1, press=press, nocancel=True,
              product=unreadable)
    for title, message in QUESTIONS:
        if title == "Put these photos on the website?":
            seen["asked"] = message

    check("the old back is asked about, not guessed", seen["rows"] != [],
          str(seen["rows"]))
    check("the photo already treated as the front is not offered again",
          all("IMG_2231" not in row for row in seen["rows"]),
          str(seen["rows"]))
    check("every photo whose name says nothing is offered, so the user "
          "decides rather than the program", len(seen["rows"]) == 2,
          str(seen["rows"]))
    check("the confirmation names what comes off the product",
          "Taken off this product" in seen["asked"] and
          "IMG_2232" in seen["asked"], seen["asked"][:300])
    check("it says the image file is not deleted",
          "media library" in seen["asked"], seen["asked"][:300])
    check("the gallery keeps only the certificate",
          UPLOADED and UPLOADED[0]["keep_ids"] == [13], str(UPLOADED))
    check("the new pair is what goes on", UPLOADED and
          UPLOADED[0]["front"].endswith("-front-1.webp") and
          (UPLOADED[0]["back"] or "").endswith("-back-1.webp"),
          str(UPLOADED))
    shutil.rmtree(folder, ignore_errors=True)


def test_old_back_kept_when_asked_to():
    print()
    print("== 13. keeping every photo is still allowed ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    sheet = make_sheet(folder / "Scan-01.jpg")
    app = FakeApp(folder)
    unreadable = {"id": 42, "name": "Old gallery", "sku": "SKU-1",
                  "images": [
                      {"id": 11, "src": "https://shop.example/u/IMG_2231.jpg"},
                      {"id": 12, "src": "https://shop.example/u/IMG_2232.jpg"}]}

    def press(window):
        for w in window.walk():
            if w.cget("text") == "Keep every existing photo":
                w.invoke()
                return
        for w in window.walk():
            if w.cget("text") == "Use this image":
                w.invoke()
                return
        window.destroy()

    UPLOADED.clear()
    with patch.object(gui.woo_media, "replace_product_photos", capture_upload):
        drive(app, sheet, scancount=1, press=press, nocancel=False,
              product=unreadable)
    check("answering No keeps every existing photo",
          UPLOADED and UPLOADED[0]["keep_ids"] is None, str(UPLOADED))
    shutil.rmtree(folder, ignore_errors=True)


def test_old_back_cancelled():
    print()
    print("== 14. cancelling the question writes nothing ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    sheet = make_sheet(folder / "Scan-01.jpg")
    app = FakeApp(folder)
    unreadable = {"id": 42, "name": "Old gallery", "sku": "SKU-1",
                  "images": [
                      {"id": 11, "src": "https://shop.example/u/IMG_2231.jpg"},
                      {"id": 12, "src": "https://shop.example/u/IMG_2232.jpg"}]}

    def press(window):
        for w in window.walk():
            if w.cget("text") == "Cancel this card":
                w.invoke()
                return
        for w in window.walk():
            if w.cget("text") == "Use this image":
                w.invoke()
                return
        window.destroy()

    UPLOADED.clear()
    with patch.object(gui.woo_media, "replace_product_photos", capture_upload):
        drive(app, sheet, scancount=1, press=press, nocancel=True,
              product=unreadable)
    check("cancelling uploads nothing", not UPLOADED, str(UPLOADED))
    check("the pair is still saved locally, so nothing is lost",
          bool(list((folder / "replacements").glob("*.webp"))),
          str(sorted(p.name for p in
                     (folder / "replacements").glob("*"))))
    shutil.rmtree(folder, ignore_errors=True)


def test_replacements_folder_opens():
    print()
    print("== 15. the saved images are on screen with the pages ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    sheet = make_sheet(folder / "Scan-01.jpg")
    app = FakeApp(folder)
    opened = []

    def note(path):
        opened.append(Path(path))
        return True

    def press(window):
        for w in window.walk():
            if w.cget("text") == "Use this image":
                w.invoke()
                return
        window.destroy()

    with patch.object(gui, "open_path", note), \
            patch.object(gui.woo_media, "replace_product_photos", capture_upload):
        drive(app, sheet, scancount=1, press=press, nocancel=True)
    check("the pages still open", app.opened, str(app.opened))
    check("the replacements folder opens with them",
          opened == [folder / "replacements"], str(opened))
    names = sorted(p.name for p in (folder / "replacements").glob("*.webp"))
    check("it is the folder the pair was just written to",
          len(names) == 2 and all("-front-1" in n or "-back-1" in n
                                  for n in names), str(names))

    #  Nothing saved means nothing to show, so the folder is not opened.
    opened.clear()
    app2 = FakeApp(folder)
    with patch.object(gui, "open_path", note):
        drive(app2, sheet, scancount=0, press=press, yes_for=(),
              found=False)
    check("no replacement, no folder", not opened, str(opened))
    check("the product list still opens", app2.opened, str(app2.opened))
    shutil.rmtree(folder, ignore_errors=True)


def test_assign_window():
    print()
    print("== 16. the assignment window: titles in, replacements out ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    sheet = make_sheet(folder / "Scan-front.jpg")
    app = FakeApp(folder)
    app.photo_pool = photo_pool.PhotoPool(tiles_dir=folder / "tiles")
    app.photo_pool.add_sheet(sheet, index=0)
    parent = FakeWidget()
    gui.build_newphotos(parent, app)
    opener = next(w for w in parent.walk()
                  if w.cget("text") == "Assign photos to cards...")
    opener.invoke()
    top = app.photo_assign_window
    check("the window opens", top is not None)

    def by_text(label):
        return next((w for w in top.walk() if w.cget("text") == label), None)

    box = next(w for w in top.walk() if w._kw.get("height") == 7)
    box.get = lambda *a, **k: (
        "1. 1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6\n"
        "2. 1990 Score Mario Lemieux #2\n")
    products = [
        {"id": 42, "name": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
         "sku": "", "images": []},
        {"id": 43, "name": "1990 Score Mario Lemieux #2", "sku": "",
         "images": []},
    ]

    def fake_get(site, path, params, key, secret):
        wanted = words_set(params.get("search") or "")
        found = [p for p in products if wanted <= words_set(p["name"])]
        return 200, found

    UPLOADED.clear()
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck", "cs")), \
            patch.object(gui, "woo_get", fake_get), \
            patch.object(gui, "read_wordpress_credentials",
                         lambda path=None: ("https://shop.example", "owner", "pw")), \
            patch.object(gui.woo_media, "replace_product_photos",
                         capture_upload):
        by_text("Read these").invoke()
        listing = next(w for w in top.walk() if w._kw.get("height") == 10)
        check("each image gets a row", len(listing.items) == 7,
              str(len(listing.items)))
        shown = " ".join(str(x) for x in listing.items)
        check("a titled row names the card it matched",
              "Gretzky" in shown and "Lemieux" in shown, shown[:160])
        _BOX.askyesno = lambda *a, **k: True
        #  "Put these photos on the website?" answers yes/no/cancel.
        _BOX.askyesnocancel = lambda *a, **k: True
        by_text("Apply the ready ones").invoke()

    check("both matched cards were replaced", len(UPLOADED) == 2,
          str(len(UPLOADED)))
    check("the website was told what to keep", all(
        u["keep_ids"] is not None for u in UPLOADED), str(UPLOADED))
    names = sorted(p.name for p in (folder / "replacements").glob("*.webp"))
    check("the pair is saved as a pair", names == ["Scan-front_1-1.webp",
                                                   "Scan-front_3-1.webp"],
          str(names))
    check("one image per card is used up",
          app.photo_pool.progress() == (2, 7), str(app.photo_pool.progress()))
    check("the rows left over still say they have no title",
          any("no title" in str(x) for x in listing.items),
          str(listing.items[:3]))
    _BOX.askyesno = lambda *a, **k: False
    _BOX.askyesnocancel = lambda *a, **k: None
    shutil.rmtree(folder, ignore_errors=True)


def words_set(text):
    return set(str(text).lower().replace("-", " ").split())


def test_empty_sheet():
    print()
    print("== 7. a sheet with no cards on it does nothing ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    blank = make_sheet(folder / "blank.jpg", blanks=tuple(range(1, 10)))
    app = FakeApp(folder)
    UPLOADS.clear()
    with patch.object(gui.woo_media, "replace_product_photos", fake_upload):
        drive(app, blank, nocancel=False)
    check("no plugin call", not app.runs, str(app.runs))
    check("no upload", not UPLOADS, str(UPLOADS))


def test_website_first():
    print()
    print("== 8. the website is updated before the plugin is called ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    sheet = make_sheet(folder / "Scan-1.jpg")
    app = FakeApp(folder)
    order = []
    real_run_tool = app.run_tool

    def run_tool(tool, args, title, **kwargs):
        order.append("plugin")
        return real_run_tool(tool, args, title, **kwargs)

    def upload(*a, **k):
        order.append("website")
        return fake_upload(*a, **k)

    app.run_tool = run_tool
    with patch.object(gui.woo_media, "replace_product_photos", upload):
        drive(app, sheet, nocancel=False,
              yes_for={"Replace the CanadianShopper photos?"})
    check("the shop is updated first", order == ["website", "plugin"],
          str(order))

    print()
    print("== 9. the old photos are dropped only when asked ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    sheet = make_sheet(folder / "Scan-1.jpg")
    app = FakeApp(folder)
    UPLOADS.clear()
    with patch.object(gui.woo_media, "replace_product_photos", fake_upload):
        drive(app, sheet, nocancel=False)
    check("answering No keeps every existing photo",
          UPLOADS[0]["keep_ids"] is None, str(UPLOADS))
    UPLOADS.clear()
    app = FakeApp(folder)
    with patch.object(gui.woo_media, "replace_product_photos", fake_upload):
        drive(app, sheet, nocancel=True)
    check("answering Yes drops the old front and back but keeps the rest",
          UPLOADS[0]["keep_ids"] == [9], str(UPLOADS))


def test_actions_above_the_words():
    print()
    print("== 20. the work sits on top; the words sit underneath ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    app = FakeApp(folder)
    parent = FakeWidget()
    gui.build_newphotos(parent, app)
    widgets = list(parent.walk())
    notes = getattr(parent, "_notes_frame", None)
    find = next(w for w in widgets if w.cget("text") == "Find the card...")
    add = next(w for w in widgets if w.cget("text") == "Add sheets...")
    check("the buttons are not in the notes area",
          notes is not None and find not in list(notes.walk()) and
          add not in list(notes.walk()), str(notes))
    check("the sheet summary and the status line are",
          notes is not None and
          any("No replacement sheets loaded" in w.cget("text")
              for w in notes.walk()), "")
    help_button = getattr(app, "_doc_button", None)
    doc = getattr(app, "_doc_label", None)
    check("the panel's help is folded until it is asked for",
          help_button is not None and doc is not None and not doc.packed,
          str(help_button))
    check("the help still holds the real text, so nothing was lost",
          doc is not None and len(str(doc.cget("text"))) > 200,
          str(doc and len(str(doc.cget("text")))))
    if help_button is not None:
        help_button.invoke()
    check("one click opens it, and it opens underneath",
          doc is not None and doc.packed and
          help_button.cget("text") == "Hide this help",
          str(help_button and help_button.cget("text")))
    if help_button is not None:
        help_button.invoke()
    check("and one click folds it again",
          doc is not None and not doc.packed, str(doc and doc.packed))
    shutil.rmtree(folder, ignore_errors=True)


def test_grid_fits_a_small_screen():
    print()
    print("== 18. nine cards on an 800x600 screen: scroll, and say so ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    #  A full sheet: nine cards, no blanks - the case that overflowed.
    sheet = make_sheet(folder / "Scan-full.jpg", blanks=())
    app = FakeApp(folder)
    seen = []

    def press(window):
        """Look at the grid as the user would, then take the first picture."""
        seen.append(window)
        for widget in window.walk():
            if widget.cget("text") == "Use this image":
                widget.invoke()
                return
        window.destroy()

    #  A build that can draw pictures: without this the picker correctly
    #  falls back to the plain list, which is not what is under test.
    dummy = object()
    with patch.object(panel_thumbs, "as_photo", lambda image: dummy):
        drive(app, sheet, press=press, nocancel=False, cards=1)

    check("the picker was drawn as a grid, not a list", bool(seen), str(seen))
    grid = seen[0].walk() if seen else ()
    widgets = list(grid)
    check("the grid scrolls instead of running off the window",
          any(isinstance(w, gui.ScrollFrame) for w in widgets), "")
    scroller = next((w for w in widgets if isinstance(w, gui.ScrollFrame)),
                    None)
    captions = [w.cget("text") for w in (scroller.inner.walk() if scroller
                                         else [])
                if w.cget("text")]
    slots = [c for c in captions if c.startswith("Slot ")]
    check("every card on the sheet is offered, all nine",
          len(slots) == 9, str(slots))
    check("a caption is the slot, not a file name",
          slots and all(".jpg" not in c and ".webp" not in c for c in slots),
          str(slots))
    check("the buttons sit above the grid, so they never scroll away",
          _first_action_row(seen[0]) is not None, "")
    check("the window fits the small screen",
          _fits(seen[0]._geometry, 800, 600), seen[0]._geometry)
    check("the pictures are kept for the next card",
          getattr(app, "_tile_thumbs", None) is not None and
          len(app._tile_thumbs._cache) >= 1,
          str(getattr(app, "_tile_thumbs", None)))
    shutil.rmtree(folder, ignore_errors=True)


def _fits(geometry, width, height):
    """Whether a Tk geometry string (WxH+X+Y) fits inside a screen."""
    try:
        size = str(geometry).split("+")[0]
        w, h = [int(x) for x in size.split("x")]
    except Exception:
        return False
    return w <= width and h <= height


def _first_action_row(window):
    """The first Button in the window's walk order, if any."""
    for widget in window.walk():
        if isinstance(widget, gui.ttk.Button):
            return widget
    return None


class ProgressRecorder:
    """Stands in for ProgressWindow and remembers what it was asked to say."""

    calls = []

    def __init__(self, parent, title="", text="", total=None):
        self.title, self.text, self.total = title, text, total
        self.steps, self.closed = [], False
        ProgressRecorder.calls.append(self)

    def step(self, text=None, done=None, total=None):
        self.steps.append((text, done, total))

    def close(self):
        self.closed = True

    def pump(self):
        pass


def test_loading_is_visible():
    print()
    print("== 19. reading a big scan says so instead of looking hung ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    first = make_sheet(folder / "Scan-a.jpg", blanks=(2, 4, 9))
    second = make_sheet(folder / "Scan-b.jpg", blanks=(2, 4, 9))
    app = FakeApp(folder)
    parent = FakeWidget()
    gui.build_newphotos(parent, app)
    widgets = list(parent.walk())
    add = next(w for w in widgets if w.cget("text") == "Add sheets...")
    _DIALOG.askopenfilenames = lambda **k: (str(first), str(second))
    ProgressRecorder.calls.clear()
    with patch.object(gui, "ProgressWindow", ProgressRecorder):
        add.invoke()
    made = ProgressRecorder.calls
    check("a working window is shown while the scans are split",
          len(made) == 1, str(made))
    check("it says how many scans are being read",
          made and made[0].total == 2, str(made and made[0].total))
    check("it names the sheet being split",
          made and any(step[0] and "Scan-a.jpg" in step[0]
                       for step in made[0].steps),
          str(made[0].steps if made else ""))
    check("the bar moves once per sheet",
          made and [s[1] for s in made[0].steps if s[1] is not None] ==
          [0, 1, 1, 2], str(made[0].steps if made else ""))
    check("the window is taken down again",
          made and made[0].closed, str(made and made[0].closed))
    check("both sheets were loaded", len(app.photo_pool.sheets) == 2,
          str(len(app.photo_pool.sheets)))
    shutil.rmtree(folder, ignore_errors=True)


def test_every_panel_leads_with_the_work():
    print()
    print("== 21. every panel: the work first, the words underneath ==")
    folder = Path(tempfile.mkdtemp())
    app = FakeApp(folder)
    action_types = (gui.ttk.Button, gui.ttk.Entry, gui.ttk.Combobox,
                    gui.ttk.Checkbutton, gui.ttk.Radiobutton, gui.tk.Text,
                    gui.tk.Listbox)
    wrong_place, folded, no_help = [], [], []
    for pid in gui.PANEL_ORDER:
        builder = gui.PANEL_BUILDERS.get(pid)
        if builder is None or pid == "welcome":
            continue
        parent = FakeWidget()
        try:
            builder(parent, app)
        except Exception as exc:
            wrong_place.append("%s: %s" % (pid, exc))
            continue
        notes = getattr(parent, "_notes_frame", None)
        if notes is None:
            no_help.append(pid)
            continue
        inside = set(id(w) for w in notes.walk())
        first = next((w for w in parent.walk()
                      if isinstance(w, action_types)), None)
        if first is not None and id(first) in inside:
            wrong_place.append(pid)
        if getattr(app, "_doc_label", None) is not None and app._doc_label.packed:
            folded.append(pid)
    check("every panel keeps its work above its help area",
          not wrong_place, str(wrong_place))
    check("every panel's help starts folded",
          not folded, str(folded))
    check("every panel has a help area", not no_help, str(no_help))
    shutil.rmtree(folder, ignore_errors=True)


def _labels_below(widget):
    """Every Label under a widget, not counting the widget itself."""
    found = []
    for child in widget.walk():
        if child is widget:
            continue
        if isinstance(child, gui.ttk.Label) and child.cget("text"):
            found.append(child.cget("text"))
    return found


def test_tabs_are_sections():
    print()
    print("== 22. the tabs view: one bordered section per panel ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    app = FakeApp(folder)
    parent = FakeWidget()
    gui.TabsFrame(parent, app)
    notebook = next((w for w in parent.walk()
                     if isinstance(w, gui.ttk.Notebook)), None)
    check("the tabs view builds a notebook of the groups",
          notebook is not None and
          [name for _tab, name in getattr(notebook, "tabs", [])] ==
          [group for group, _ids in gui.groups_for(app.cs_addon)],
          str([name for _tab, name in getattr(notebook, "tabs", [])]))
    sections, problems, repeated = [], [], []
    for tab, group in getattr(notebook, "tabs", []):
        ids = dict(gui.groups_for(app.cs_addon))[group]
        frames = [w for w in tab.walk() if isinstance(w, gui.ttk.LabelFrame)]
        sections.extend(frames)
        if [f.cget("text") for f in frames] != [gui.TITLES[pid] for pid in ids]:
            problems.append((group, [f.cget("text") for f in frames]))
        for pid, frame in zip(ids, frames):
            if frame.cget("style") != "PanelSection.TLabelframe":
                problems.append((pid, frame.cget("style")))
            if gui.TITLES[pid] in _labels_below(frame):
                repeated.append(pid)
    check("every panel in a group has its own section, in order",
          not problems, str(problems))
    check("a section carries the panel's title on its border",
          len(sections) == sum(len(ids) for _g, ids in
                               gui.groups_for(app.cs_addon)) and
          all(s.cget("text") for s in sections),
          str([s.cget("text") for s in sections]))
    check("the title is not printed twice inside the section",
          not repeated, str(repeated))
    photos = next((s for s in sections
                   if s.cget("text") == gui.TITLES["newphotos"]), None)
    check("the panel's buttons are inside its section",
          photos is not None and
          any(w.cget("text") == "Find the card..." for w in photos.walk()), "")
    check("so is its folded help",
          photos is not None and
          any(w.cget("text") == "What this panel does"
              for w in photos.walk()), "")

    #  The task menu shows one panel with no section around it, so there the
    #  title still has to be drawn by the panel itself.
    bare = FakeWidget()
    gui.PANEL_BUILDERS["newphotos"](bare, app)
    check("a panel outside a section still prints its own title",
          gui.TITLES["newphotos"] in _labels_below(bare), "")
    shutil.rmtree(folder, ignore_errors=True)


def test_spent_sitting():
    print()
    print("== 17. a sitting with every image used says so ==")
    folder = Path(tempfile.mkdtemp())
    install_plugin("1.0.16", folder / "plugin")
    #  Six images: three cards use them all, the fourth press has nothing to
    #  pick. It used to do nothing at all, so the panel looked broken.
    sheet = make_sheet(folder / "Scan-1.jpg", blanks=(2, 4, 9))
    app = FakeApp(folder)
    _BOX.shown.clear()
    UPLOADS.clear()
    with patch.object(gui.woo_media, "replace_product_photos", fake_upload):
        drive(app, sheet, cards=4, nocancel=False)
    check("three cards used the whole sheet",
          app.photo_pool.progress() == (6, 6), str(app.photo_pool.progress()))
    check("the fourth press explains the sheet is spent",
          any(kind == "showinfo" and "already have a card" in str(payload)
              for kind, payload in _BOX.shown), str(_BOX.shown))
    saved = sorted(p.name for p in (folder / "replacements").glob("*.webp"))
    check("the spent press saved nothing - three pairs, no fourth",
          len(saved) == 6, str(saved))
    shutil.rmtree(folder, ignore_errors=True)


def main():
    test_version_gates()
    test_pair_saved_and_sent()
    test_old_plugin_takes_front_only()
    test_old_plugin_refused()
    test_back_from_another_sheet()
    test_front_only_by_choice()
    test_no_product_found()
    test_same_slot_back()
    test_two_cards_one_sitting()
    test_unreadable_old_back()
    test_old_back_kept_when_asked_to()
    test_old_back_cancelled()
    test_replacements_folder_opens()
    test_assign_window()
    test_actions_above_the_words()
    test_every_panel_leads_with_the_work()
    test_tabs_are_sections()
    test_grid_fits_a_small_screen()
    test_loading_is_visible()
    test_spent_sitting()
    test_empty_sheet()
    test_website_first()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL PHOTO PANEL CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
