"""Checks for the tool-dialog channel: what the app answers a plugin that asks.

    python test-tool-dialog.py

A tool writes a marker to stdout, the app shows a real dialog and writes the
answer back to the tool's stdin. That channel is how the CanadianShopper plugin
asks "which photo already on this listing is the old back?" - and if the app
answers the wrong shape, a live listing gets the wrong row replaced. The
question is put as pictures, so what is checked here is that a photo can be
clicked, that one that cannot be downloaded is still a choice, and that the
question is not asked at all when the read already proved there is no old back.
tkinter is stubbed, so this runs without a display.
"""

import json
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

FAIL = 0
PASSED = 0


def check(name, cond, extra=""):
    global FAIL, PASSED
    if cond:
        PASSED += 1
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
        self.value = kwargs.get("text", "")
        self.items = []
        self.selection = ()
        self.parent = args[0] if args else None
        if self.parent is not None and hasattr(self.parent, "children"):
            self.parent.children.append(self)

    def pack(self, *a, **k): return self
    def grid(self, *a, **k): return self
    def place(self, *a, **k): return self
    def bind(self, sequence, handler=None, *a, **k):
        if handler is not None:
            #  A photo is chosen by clicking it, so the fake records what the
            #  dialog bound and can play it back as a click.
            self._bound = getattr(self, "_bound", {})
            self._bound[sequence] = handler
        return self

    def event_generate(self, sequence, *a, **k):
        handler = getattr(self, "_bound", {}).get(sequence)
        if handler is not None:
            handler(None)
    def configure(self, **k): self._kw.update(k)
    def config(self, **k): self._kw.update(k)
    def cget(self, key):
        return self._kw.get("text", self.value) if key == "text" \
            else self._kw.get(key, "")
    def winfo_children(self): return list(self.children)
    def destroy(self): pass
    def focus_set(self): pass
    def yview(self, *a, **k): return (0.0, 1.0)
    def protocol(self, *a, **k): return None
    def insert(self, *a, **k):
        if a and a[0] == "end":
            self.items.append(a[1])
    def delete(self, *a, **k):
        if a and a[0] == 0:
            self.items = []
    def get(self, *a, **k): return self.value
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


class FakeToplevel(FakeWidget):
    """A dialog window; the harness presses one of its buttons."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._title = k.get("title", "")

    def title(self, value=None):
        if value is not None:
            self._title = value
        return self._title
    def transient(self, *a, **k): return self
    def geometry(self, *a, **k): return self
    def grab_set(self, *a, **k): return self
    def wait_window(self, *a, **k):
        PRESS["fn"](self)


PRESS = {"fn": lambda window: None}


def install_tk():
    tk = types.ModuleType("tkinter")
    for name, obj in dict(Frame=FakeWidget, Label=FakeWidget, Button=FakeWidget,
                          Entry=FakeWidget, Text=FakeWidget, Listbox=FakeWidget,
                          Toplevel=FakeToplevel, Canvas=FakeWidget,
                          StringVar=FakeWidget, BooleanVar=FakeWidget,
                          IntVar=FakeWidget, Tk=FakeWidget).items():
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
    return tk, ttk, box


_TK, _TTK, _BOX = install_tk()

import gui                                     # noqa: E402

CLS = gui.App


class FakeApp:
    """Just enough app for the dialog handlers: wait_window and pictures."""

    def __init__(self):
        #  A real folder, because the dialog saves each gallery photo before
        #  it draws it - never the app's own folder, so a test writes nothing
        #  into the checkout.
        self.settings = {"pipeline_dir": tempfile.mkdtemp()}
        self.lines = []
        self._photo_read = None

    def wait_window(self, window):
        window.wait_window()

    def after(self, _delay, callback):
        callback()

    def winfo_screenwidth(self):
        return 1920

    def console_line(self, text, tag=""):
        self.lines.append((tag, str(text)))


def make_app():
    """A fake app carrying the real handler methods, unbound from Tk."""
    app = FakeApp()
    for name in ("handle_tool_dialog", "_pick_cs_back", "_known_old_back"):
        setattr(app, name, types.MethodType(getattr(CLS, name), app))
    return app


FAILS = set()


def fake_fetch(url, **_kwargs):
    """Every photo downloads at once, unless a check says this one cannot."""
    if url in FAILS:
        raise OSError("the photo could not be read")
    return b"picture"


def run_now(_app, work, done):
    """Do the downloads on this thread: a check must not race the window."""
    try:
        result, error = work(), None
    except Exception as exc:            # noqa: BLE001 - the dialog draws it
        result, error = None, exc
    done(result, error)


def answer_for(request, press_fn=None, fetch=fake_fetch, app=None):
    """Answer one dialog, with its pictures loaded before it is drawn."""
    app = app or make_app()
    if press_fn is not None:
        PRESS["fn"] = press_fn
    with patch.object(gui, "in_background", run_now), \
            patch.object(gui.cs_products, "fetch_bytes", fetch), \
            patch.object(gui.photo_thumbs, "thumbnail",
                         lambda path, size=None: ("thumb", str(path))), \
            patch.object(gui.photo_thumbs, "as_photo",
                         lambda image: ("photo", str(image[1]))):
        return app, app.handle_tool_dialog(dict(request))


def drawn_in(window):
    """Every photo the window actually drew."""
    return [w.cget("image") for w in window.walk() if w.cget("image")]


def labels_in(window):
    return [str(w.cget("text")) for w in window.walk()]


def press(label):
    """Make the next dialog press the button with this label."""
    def go(window):
        for widget in window.walk():
            if widget.cget("text") == label and widget.command:
                widget.invoke()
                return
        window.destroy()
    PRESS["fn"] = go


def click_photo(window, name):
    """Click the cell carrying this photo's name, drawn or not.

    The name is on the picture's own label until the photo arrives and in the
    line under it afterwards, so both are looked at - and nothing else is, so
    a name in the window's prose cannot be mistaken for the photo.
    """
    for widget in window.walk():
        text = str(widget.cget("text"))
        if text == name or (text.startswith(("position", "OLD BACK")) and
                            name in text):
            widget.event_generate("<Button-1>")
            return True
    return False


def press_row(name):
    """Make the next dialog click the photo with this name, then replace it."""
    def go(window):
        click_photo(window, name)
        for widget in window.walk():
            if widget.cget("text") == "Replace the selected photo":
                widget.invoke()
                return
        window.destroy()
    PRESS["fn"] = go


REQUEST = {
    "type": "pick_back",
    "title": "1972-73 O-Pee-Chee Dave Burrows #133 Rookie Card",
    "front": "133-Dave-Burrows-front-2.webp",
    "back": "133-Dave-Burrows-back-2.webp",
    "rows": [
        {"id": "row-a", "filename": "burrows-133-old.jpg", "sortOrder": 1,
         "url": "https://store.example/u/burrows-133-old.jpg"},
        {"id": "row-b", "filename": "burrows-133-coa.jpg", "sortOrder": 2,
         "url": "https://store.example/u/burrows-133-coa.jpg"},
    ],
    "allow_add": True,
}


def test_pick_a_row():
    print()
    print("== 1. the plugin asks which photo is the old back ==")
    seen = {"drawn": [], "labels": [], "marked": []}

    def look(window):
        seen["drawn"] = drawn_in(window)
        seen["labels"] = labels_in(window)
        click_photo(window, "burrows-133-coa.jpg")
        seen["marked"] = labels_in(window)
        for widget in window.walk():
            if widget.cget("text") == "Replace the selected photo":
                widget.invoke()
                return
        window.destroy()

    app, answer = answer_for(REQUEST, look)
    check("every photo already on the listing is drawn, not listed",
          len(seen["drawn"]) == 2, str(seen["drawn"]))
    check("a photo is drawn for each row", all(
        item[0] == "photo" for item in seen["drawn"]), str(seen["drawn"]))
    check("each row's name is written under its picture",
          any("burrows-133-old.jpg" in line for line in seen["labels"]) and
          any("burrows-133-coa.jpg" in line for line in seen["labels"]),
          str(seen["labels"]))
    check("a click marks that photo as the old back",
          any(line.startswith("OLD BACK") and "burrows-133-coa.jpg" in line
              for line in seen["marked"]), str(seen["marked"]))
    check("the answer names the chosen row", answer == {"row": "row-b"},
          str(answer))
    check("it is the row's ID, not its position", answer.get("row") != "2",
          str(answer))
    check("the answer is one JSON-able shape", json.loads(
        json.dumps(answer)) == answer)


def test_add_instead():
    print()
    print("== 2. no old back - keep every row and add the new one ==")
    app = make_app()
    press("No old back - keep every row and add the new one")
    answer = app.handle_tool_dialog(dict(REQUEST))
    check("the answer is an explicit null row",
          answer == {"row": None} and "row" in answer, str(answer))
    check("it is not a cancel", "cancel" not in answer, str(answer))


def test_cancel():
    print()
    print("== 3. cancelling changes nothing ==")
    app, answer = _cancel_answer()
    check("the answer cancels", answer == {"cancel": True}, str(answer))
    check("it does not also name a row", "row" not in answer, str(answer))


def _cancel_answer():
    app = make_app()
    press("Cancel this card")
    return app, app.handle_tool_dialog(dict(REQUEST))


def test_untouched_window():
    print()
    print("== 4. a window nobody answered must not change a listing ==")
    app = make_app()
    PRESS["fn"] = lambda window: None          # closes without choosing
    answer = app.handle_tool_dialog(dict(REQUEST))
    check("an unanswered window cancels rather than adding a back",
          answer == {"cancel": True}, str(answer))


def test_add_disallowed():
    print()
    print("== 5. when the plugin does not offer adding ==")
    app = make_app()
    request = dict(REQUEST, allow_add=False)
    labels = []

    def look(window):
        labels.extend(w.cget("text") for w in window.walk())
        for w in window.walk():
            if w.cget("text") == "Cancel this card":
                w.invoke()
                return
        window.destroy()

    PRESS["fn"] = look
    answer = app.handle_tool_dialog(request)
    check("the keep-every-row button is not offered",
          "No old back - keep every row and add the new one" not in labels,
          str([x for x in labels if x]))
    check("cancelling still works", answer == {"cancel": True}, str(answer))


def test_one_row():
    print()
    print("== 6. the card that failed: one gallery row, and it is the front ==")
    request = dict(REQUEST, rows=[{"id": "13820", "filename":
                                   "burrows-133.webp", "sortOrder": 1}])
    press_row("burrows-133.webp")
    app, answer = answer_for(request)
    check("one row can still be chosen", answer == {"row": "13820"},
          str(answer))
    check("the answer is a string ID", isinstance(answer.get("row"), str),
          str(answer))


def test_one_row_is_shown():
    print()
    print("== 7. ...and that one photo is drawn, not described ==")
    request = dict(REQUEST, rows=[{"id": "13820",
                                   "filename": "burrows-133.webp",
                                   "sortOrder": 1,
                                   "url": "https://store.example/u/one.webp"}])
    seen = {}

    def look(window):
        seen["drawn"] = drawn_in(window)
        seen["labels"] = labels_in(window)
        click_photo(window, "burrows-133.webp")
        seen["marked"] = labels_in(window)
        for widget in window.walk():
            if widget.cget("text") == "Replace the selected photo":
                widget.invoke()
                return
        window.destroy()

    app, answer = answer_for(request, look)
    check("the only photo is drawn", len(seen["drawn"]) == 1, str(seen["drawn"]))
    check("its name sits under it",
          any("burrows-133.webp" in line for line in seen["labels"]),
          str(seen["labels"]))
    check("clicking it makes it the old back",
          any(line.startswith("OLD BACK") and "burrows-133.webp" in line
              for line in seen["marked"]), str(seen["marked"]))
    check("and it is the row that gets replaced", answer == {"row": "13820"},
          str(answer))


def test_photo_that_cannot_be_downloaded():
    print()
    print("== 8. a photo that cannot be downloaded is still a choice ==")
    FAILS.clear()
    FAILS.add("https://store.example/u/burrows-133-old.jpg")
    seen = {}

    def look(window):
        seen["drawn"] = drawn_in(window)
        seen["labels"] = labels_in(window)
        click_photo(window, "burrows-133-old.jpg")
        for widget in window.walk():
            if widget.cget("text") == "Replace the selected photo":
                widget.invoke()
                return
        window.destroy()

    try:
        app, answer = answer_for(REQUEST, look)
    finally:
        FAILS.clear()
    check("the row that could be read is drawn",
          len(seen["drawn"]) == 1, str(seen["drawn"]))
    check("the one that could not keeps its name, so it is not missing",
          any("burrows-133-old.jpg" in line for line in seen["labels"]),
          str(seen["labels"]))
    check("and it can still be chosen", answer == {"row": "row-a"},
          str(answer))


def test_nothing_clicked_yet():
    print()
    print("== 9. nothing is replaced before a photo is clicked ==")
    seen = {}

    def look(window):
        for widget in window.walk():
            if widget.cget("text") == "Replace the selected photo":
                widget.invoke()
        seen["labels"] = labels_in(window)
        seen["still_open"] = any(w.cget("text") == "Cancel this card"
                                 for w in window.walk())
        for widget in window.walk():
            if widget.cget("text") == "Cancel this card":
                widget.invoke()
                return
        window.destroy()

    app, answer = answer_for(REQUEST, look)
    check("the window says a photo has to be clicked first",
          any("Click the photo" in line for line in seen["labels"]),
          str(seen["labels"]))
    check("the window stays open rather than answering",
          seen["still_open"], "")
    check("and closing it changes nothing", answer == {"cancel": True},
          str(answer))


def test_no_old_back_read():
    print()
    print("== 10. the read already proved there is no old back ==")
    #  The report: a gallery holding only the listing's own front. Asking
    #  "which of these is the old back?" offers the front as a candidate and
    #  there is no right answer - so the app answers it from the read it took.
    front = "https://store.example/u/burrows-133.webp"
    seen = {"opened": False}

    def look(window):
        seen["opened"] = True
        window.destroy()

    app = make_app()
    app._photo_read = {"title": REQUEST["title"], "current": front,
                       "rows": [{"id": "row-a", "imageUrl": front,
                                 "sortOrder": 1}]}
    request = dict(REQUEST, rows=[{"id": "row-a",
                                   "filename": "burrows-133.webp",
                                   "sortOrder": 1, "url": front}])
    answer = answer_for(request, look, app=app)[1]
    check("no window opens", not seen["opened"], "")
    check("the new back is added beside the front", answer == {"row": None},
          str(answer))
    check("and the console says why the question was not asked",
          any("no old back to replace" in line for _tag, line in app.lines),
          str(app.lines))

    seen["opened"] = False
    app = make_app()
    app._photo_read = {"title": REQUEST["title"], "current": front,
                       "rows": []}
    answer = answer_for(dict(REQUEST, rows=[]), look, app=app)[1]
    check("an empty gallery is the same answer", answer == {"row": None},
          str(answer))
    check("and it is answered without a window", not seen["opened"], "")

    #  Anything the read could not prove falls back to the question.
    for label, read in (
            ("a second row that could be a back",
             {"title": REQUEST["title"], "current": front,
              "rows": [{"id": "row-a", "imageUrl": front, "sortOrder": 1},
                       {"id": "row-b", "imageUrl": "https://x/other.jpg",
                        "sortOrder": 2}]}),
            ("a different listing",
             {"title": "Some other card", "current": front,
              "rows": [{"id": "row-a", "imageUrl": front, "sortOrder": 1}]}),
            ("a gallery nobody could read",
             {"title": REQUEST["title"], "current": front, "rows": None}),
            ("a photo the app never read",
             {"title": REQUEST["title"], "current": front,
              "rows": [{"id": "row-a", "imageUrl": front, "sortOrder": 1}]})):
        asked = {"opened": False}

        def look_more(window):
            asked["opened"] = True
            window.destroy()

        app = make_app()
        app._photo_read = read
        request = dict(REQUEST, rows=[{"id": "row-z", "filename": "z.jpg",
                                       "sortOrder": 1}])
        if label == "a photo the app never read":
            request = dict(REQUEST, rows=[{"id": "row-z", "filename": "z.jpg",
                                           "sortOrder": 1}])
        else:
            request = dict(REQUEST)
        answer = answer_for(request, look_more, app=app)[1]
        check("with %s the seller is still asked" % label, asked["opened"] and
              answer == {"cancel": True}, str((asked, answer)))


def test_unknown_type():
    print()
    print("== 11. an unknown request still answers safely ==")
    app = make_app()
    answer = app.handle_tool_dialog({"type": "something_new"})
    check("an unknown type answers an empty object", answer == {}, str(answer))
    check("the tool is never left waiting on rubbish",
          isinstance(answer, dict), str(type(answer)))


class FakeBar:
    def __init__(self):
        self.kw = {"maximum": 100, "value": 0}

    def configure(self, **changes):
        self.kw.update(changes)

    def cget(self, key):
        return self.kw.get(key)


class FakeLabel:
    def __init__(self):
        self.text = ""

    def config(self, **changes):
        self.text = changes.get("text", self.text)


class FakeRow:
    def __init__(self):
        self.shown = False

    def grid(self, *a, **k):
        self.shown = True

    def grid_remove(self):
        self.shown = False


def make_progress_app(running=True):
    """An app carrying only what the progress bar needs, unbound from Tk."""
    app = types.SimpleNamespace(
        progress_bar=FakeBar(), progress_label=FakeLabel(),
        progress_row=FakeRow(), status=FakeLabel(),
        runner=types.SimpleNamespace(title="Card pipeline: listing"),
        console_line=lambda *a, **k: None,
        _input_enable=lambda *a, **k: None,
        after=lambda *a, **k: None)
    for name in ("on_progress", "progress_show", "progress_hide",
                 "on_run_start", "on_run_end"):
        setattr(app, name, types.MethodType(getattr(CLS, name), app))
    app._progress_shown = False
    app._progress_closed = True
    app._progress_finished = False
    app.progress_hide()
    if running:
        #  The same flag on_run_start sets; this fake has no console.
        app._progress_closed = False
    return app


def test_progress_markers():
    print()
    print("== 12. a long step moves a bar instead of printing gibberish ==")
    app = make_progress_app()
    runner = gui.Runner(app)
    runner.send = lambda text: None
    marker = gui._TOOL_PROGRESS_START
    event = json.dumps({"index": 3, "total": 9, "stage": "create",
                        "item": {"name": "16-Foo-dark-back-front"}})

    before = runner._consume_dialog_protocol("card 2 of 9\n" + marker[:12])
    after = runner._consume_dialog_protocol(
        marker[12:] + event + gui._TOOL_DIALOG_END + "card 3 of 9\n")
    check("the marker never reaches the console",
          before + after == "card 2 of 9\ncard 3 of 9\n",
          repr(before + after))
    check("a marker split across chunks still moves the bar",
          app.progress_bar.cget("maximum") == 9 and
          app.progress_bar.cget("value") == 2,
          str(app.progress_bar.kw))
    check("the bar says which card and which part of the work",
          app.progress_label.text ==
          "[3/9] creating the draft and reading it back - "
          "16-Foo-dark-back-front", repr(app.progress_label.text))
    check("the bar is on screen while the step runs", app.progress_row.shown)

    #  "done" for a card is what fills its slot.
    runner._consume_dialog_protocol(
        marker + json.dumps({"index": 3, "total": 9, "stage": "done",
                             "item": {"name": "Card"}}) + gui._TOOL_DIALOG_END)
    check("finishing a card fills its slot",
          app.progress_bar.cget("value") == 3, str(app.progress_bar.kw))

    #  A stage the app has no words for is shown as the tool wrote it, and a
    #  broken event changes nothing at all.
    runner._consume_dialog_protocol(
        marker + json.dumps({"index": 4, "total": 9, "stage": "resize",
                             "item": {"name": "Card"}}) + gui._TOOL_DIALOG_END)
    check("an unknown stage is shown as it arrives",
          "resize" in app.progress_label.text, app.progress_label.text)
    #  A broken event is dropped, and written to the log - never to the
    #  console, and never into the log beside the app. That log is the
    #  seller's record of what the app did; a check run that appends "tool
    #  progress protocol failed" to it leaves a line that reads like a fault
    #  the checks found in a run where everything passed.
    this_runs_log = Path(tempfile.mkdtemp()) / "gui-log.txt"
    with patch.object(gui, "LOG_FILE", this_runs_log):
        runner._consume_dialog_protocol(marker + "{not json" +
                                        gui._TOOL_DIALOG_END)
    check("a broken event is dropped, not fatal",
          app.progress_bar.cget("value") == 3 and
          app.progress_label.text.startswith("[4/9]"),
          str(app.progress_bar.kw))
    kept = (this_runs_log.read_text(encoding="utf-8")
            if this_runs_log.is_file() else "")
    check("and it is recorded in the log the run was given, not the console",
          "tool progress protocol failed" in kept, repr(kept))
    runner._consume_dialog_protocol(
        marker + json.dumps({"index": 0, "total": 0, "stage": "start"}) +
        gui._TOOL_DIALOG_END)
    check("an event with no total leaves the bar alone",
          app.progress_bar.cget("value") == 3, str(app.progress_bar.kw))

    app.progress_hide()
    check("a finished run puts the bar away",
          not app.progress_row.shown and
          app.progress_bar.cget("value") == 0 and app.progress_label.text == "")


def test_progress_ends_with_the_step():
    """The bar must go when the products are done, not when the batch is.

    A real run left the bar sitting at the last card while CanadianShopper
    published drafts, wired photos, the eBay Quick List opened and the
    Facebook question came and went - minutes of "9/9" over a run that was
    plainly still going, which reads as a bar that is stuck.
    """
    print()
    print("== 13. the bar ends with the step that owns it ==")
    app = make_progress_app()
    runner = gui.Runner(app)
    runner.send = lambda text: None
    marker = gui._TOOL_PROGRESS_START

    runner._consume_dialog_protocol(
        marker + json.dumps({"index": 9, "total": 9, "stage": "publish",
                             "item": {"name": "Last card"}}) +
        gui._TOOL_DIALOG_END)
    check("the step is on screen at its last card",
          app.progress_row.shown and app.progress_bar.cget("value") == 9,
          str(app.progress_bar.kw))
    runner._consume_dialog_protocol(
        marker + json.dumps({"stage": "finish", "index": 9, "total": 9}) +
        gui._TOOL_DIALOG_END)
    check("the step saying it is over takes the bar away",
          not app.progress_row.shown)
    check("and the status line says the batch is still running",
          "still running" in app.status.text, repr(app.status.text))

    #  Nothing that arrives after that may redraw it.
    runner._consume_dialog_protocol(
        marker + json.dumps({"index": 3, "total": 9, "stage": "photos",
                             "item": {"name": "Later"}}) + gui._TOOL_DIALOG_END)
    check("a leftover event after the step ends cannot bring the bar back",
          not app.progress_row.shown)
    #  ...but real new work can: a later step that starts its own items gets
    #  its own bar rather than silence.
    runner._consume_dialog_protocol(
        marker + json.dumps({"index": 1, "total": 5, "stage": "start",
                             "item": {"name": "Another step"}}) +
        gui._TOOL_DIALOG_END)
    check("a later step that starts its own items gets the bar back",
          app.progress_row.shown and app.progress_bar.cget("maximum") == 5,
          str(app.progress_bar.kw))

    #  And the end of the run is final even if a marker was in flight.
    app = make_progress_app()
    runner = gui.Runner(app)
    runner.send = lambda text: None
    app._progress_closed = True
    runner._consume_dialog_protocol(
        marker + json.dumps({"index": 2, "total": 9, "stage": "photos",
                             "item": {"name": "Late"}}) + gui._TOOL_DIALOG_END)
    check("a finished run never shows a bar again", not app.progress_row.shown)

    #  A tool that prints a bar and then dies without saying "finish" still
    #  loses it: the run ending is the backstop.
    app = make_progress_app()
    app.on_run_end("Card pipeline: listing", 1)
    check("a run that ends for any reason leaves no bar behind",
          not app.progress_row.shown and app._progress_closed)


def test_windows_only_suite_calls_real_methods():
    """test-gui.py can only run where there is a display; this can.

    A typo in that suite costs a whole round trip through the Windows machine,
    which is exactly what happened: it called the tool-dialog parser on the app
    instead of on the runner, and the run died half way through section 19
    after 250 passing checks. Reading the file instead of running it catches
    that class of mistake here, in a second.
    """
    print()
    print("== 14. the Windows-only suite only calls things that exist ==")
    import ast
    app_dir = Path(__file__).resolve().parent
    gui_tree = ast.parse((app_dir / "gui.py").read_text(encoding="utf-8"))
    suite_tree = ast.parse((app_dir / "test-gui.py").read_text(
        encoding="utf-8"))

    def api(cls, owners):
        """What that object has: its class's methods, plus its attributes.

        The attributes are collected across the whole file because several
        panels hang their state on ``app.`` (``app._custom_ai_editor``) from
        inside a builder function, not from the class.
        """
        methods = set()
        if cls:
            for node in gui_tree.body:
                if isinstance(node, ast.ClassDef) and node.name == cls:
                    methods |= {item.name for item in ast.walk(node)
                                if isinstance(item, (ast.FunctionDef,
                                                     ast.AsyncFunctionDef))}
        assigned = {node.attr for node in ast.walk(gui_tree)
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.ctx, ast.Store)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in owners}
        return methods | assigned

    known = {"app": api("App", {"self", "app"}),
             "runner": api("Runner", {"self"})}
    #  Only private names are checked: ``app.status`` and friends are Tk
    #  methods and widgets this file cannot enumerate without a display.
    missing = {}
    for node in ast.walk(suite_tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                and isinstance(node.value, ast.Name)
                and node.value.id in known
                and node.attr.startswith("_")
                and node.attr not in known[node.value.id]):
            missing.setdefault(
                "%s.%s (line %d)" % (node.value.id, node.attr, node.lineno),
                node.lineno)
    check("every private app/runner method the suite calls really exists",
          not missing, str(missing))

    #  And the other way round for the two names this app must not confuse:
    #  the dialog channel belongs to the runner, the bar to the app.
    check("the dialog channel belongs to the runner", hasattr(
        gui.Runner, "_consume_dialog_protocol") and
        not hasattr(gui.App, "_consume_dialog_protocol"))
    check("the bar belongs to the app", hasattr(gui.App, "on_progress") and
          hasattr(gui.App, "progress_hide"))


def main():
    test_pick_a_row()
    test_add_instead()
    test_cancel()
    test_untouched_window()
    test_add_disallowed()
    test_one_row()
    test_one_row_is_shown()
    test_photo_that_cannot_be_downloaded()
    test_nothing_clicked_yet()
    test_no_old_back_read()
    test_unknown_type()
    test_progress_markers()
    test_progress_ends_with_the_step()
    test_windows_only_suite_calls_real_methods()
    print()
    print("=" * 60)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASSED))
        return 1
    print("ALL TOOL DIALOG CHECKS PASSED (%d)" % PASSED)
    return 0


if __name__ == "__main__":
    sys.exit(main())
