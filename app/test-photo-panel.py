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
        self.children = []
        self.command = kwargs.get("command")
        self.value = kwargs.get("text", "")
        self.items = []
        self.selection = ()
        self.parent = args[0] if args else None
        if self.parent is not None and hasattr(self.parent, "children"):
            self.parent.children.append(self)

    def pack(self, *a, **k): return self
    def grid(self, *a, **k): return self
    def place(self, *a, **k): return self
    def bind(self, *a, **k): return self
    def configure(self, **k): self._kw.update(k)
    def config(self, **k): self._kw.update(k)
    def cget(self, key):
        return self._kw.get("text", self.value) if key == "text" \
            else self._kw.get(key, "")
    def winfo_children(self): return list(self.children)
    def destroy(self): pass
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
    def title(self, value=None):
        if value is not None: self._title = value
        return self._title
    def transient(self, *a, **k): return self
    def geometry(self, *a, **k): return self
    def grab_set(self, *a, **k): return self
    def wait_window(self, *a, **k):
        PICKER["press"](self)


PICKER = {"press": lambda window: None}


def install_tk():
    tk = types.ModuleType("tkinter")
    for name, obj in dict(Frame=FakeWidget, Label=FakeWidget, Button=FakeWidget,
                          Entry=FakeWidget, Text=FakeWidget, Listbox=FakeWidget,
                          Toplevel=FakeToplevel, Canvas=FakeWidget,
                          StringVar=FakeVar, BooleanVar=FakeVar,
                          IntVar=FakeVar, Tk=FakeWidget).items():
        setattr(tk, name, obj)
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
import photo_replace                           # noqa: E402
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


def drive(app, sheet, yes_for=(), nocancel=None, wordpress=("owner", "pw"),
          site="https://shop.example", product=None, press=None,
          scancount=1):
    """Press Find with a scripted sheet, answers and picker behaviour."""
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
    _BOX.askyesnocancel = lambda title, *a, **k: (asked.append(title), nocancel)[1]
    scans = [str(sheet)] * scancount
    _DIALOG.askopenfilename = lambda **k: scans.pop(0) if scans else str(sheet)
    keys = (site, "ck_live", "cs_live")
    wp = (site, wordpress[0], wordpress[1]) if wordpress else (site, "", "")
    with patch.object(gui, "has_woo_credentials", lambda path=None: True), \
            patch.object(gui, "read_woo_credentials", lambda path=None: keys), \
            patch.object(gui, "read_wordpress_credentials", lambda path=None: wp), \
            patch.object(gui, "woo_get", lambda *a, **k: (200, [product])):
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


def main():
    test_version_gates()
    test_pair_saved_and_sent()
    test_old_plugin_takes_front_only()
    test_old_plugin_refused()
    test_back_from_another_sheet()
    test_front_only_by_choice()
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
