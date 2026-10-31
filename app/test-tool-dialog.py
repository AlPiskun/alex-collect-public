"""Checks for the tool-dialog channel: what the app answers a plugin that asks.

    python test-tool-dialog.py

A tool writes a marker to stdout, the app shows a real dialog and writes the
answer back to the tool's stdin. That channel is how the CanadianShopper plugin
asks "which gallery row is the old back?" - and if the app answers the wrong
shape, a live listing gets the wrong row replaced. tkinter is stubbed, so this
runs without a display.
"""

import json
import sys
import types
from pathlib import Path

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
    """Just enough app for the dialog handlers: they only need wait_window."""

    def __init__(self):
        self.settings = {}
        self.lines = []

    def wait_window(self, window):
        window.wait_window()

    def console_line(self, text, tag=""):
        self.lines.append((tag, str(text)))


def make_app():
    """A fake app carrying the real handler methods, unbound from Tk."""
    app = FakeApp()
    for name in ("handle_tool_dialog", "_pick_cs_back"):
        setattr(app, name, types.MethodType(getattr(CLS, name), app))
    return app


def press(label):
    """Make the next dialog press the button with this label."""
    def go(window):
        for widget in window.walk():
            if widget.cget("text") == label and widget.command:
                widget.invoke()
                return
        window.destroy()
    PRESS["fn"] = go


def press_row(index):
    """Make the next dialog select row ``index`` then press the replace button."""
    def go(window):
        for widget in window.walk():
            if widget._kw.get("height") == 9:
                widget.selection_set(index)
        for widget in window.walk():
            if widget.cget("text") == "Replace the selected row":
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
    print("== 1. the plugin asks which row is the old back ==")
    app = make_app()
    press_row(1)
    answer = app.handle_tool_dialog(dict(REQUEST))
    check("the answer names the chosen row", answer == {"row": "row-b"},
          str(answer))
    check("it is the row's ID, not its position", answer.get("row") != "1",
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
    app = make_app()
    press("Cancel this card")
    answer = app.handle_tool_dialog(dict(REQUEST))
    check("the answer cancels", answer == {"cancel": True}, str(answer))
    check("it does not also name a row", "row" not in answer, str(answer))


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
    print("== 6. the card that failed: one gallery row ==")
    app = make_app()
    press_row(0)
    request = dict(REQUEST, rows=[{"id": "13820", "filename":
                                   "burrows-133.webp", "sortOrder": 1}])
    answer = app.handle_tool_dialog(request)
    check("one row can still be chosen", answer == {"row": "13820"},
          str(answer))
    check("the answer is a string ID", isinstance(answer.get("row"), str),
          str(answer))


def test_row_without_id():
    print()
    print("== 7. a row with no ID is refused, not guessed ==")
    app = make_app()
    _BOX.shown.clear()

    def press_anyway(window):
        for w in window.walk():
            if w._kw.get("height") == 9:
                w.selection_set(0)
        for w in window.walk():
            if w.cget("text") == "Replace the selected row":
                w.invoke()
                break
        for w in window.walk():
            if w.cget("text") == "Cancel this card":
                w.invoke()
                return
        window.destroy()

    PRESS["fn"] = press_anyway
    answer = app.handle_tool_dialog(dict(REQUEST, rows=[{"filename": "x.jpg"}]))
    check("the user is told the row has no ID",
          any("no ID" in str(payload) for _kind, payload in _BOX.shown),
          str(_BOX.shown))
    check("nothing is replaced", answer == {"cancel": True}, str(answer))


def test_unknown_type():
    print()
    print("== 8. an unknown request still answers safely ==")
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
    print("== 9. a long step moves a bar instead of printing gibberish ==")
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
    runner._consume_dialog_protocol(marker + "{not json" + gui._TOOL_DIALOG_END)
    check("a broken event is dropped, not fatal",
          app.progress_bar.cget("value") == 3 and
          app.progress_label.text.startswith("[4/9]"),
          str(app.progress_bar.kw))
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
    print("== 10. the bar ends with the step that owns it ==")
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


def main():
    test_pick_a_row()
    test_add_instead()
    test_cancel()
    test_untouched_window()
    test_add_disallowed()
    test_one_row()
    test_row_without_id()
    test_unknown_type()
    test_progress_markers()
    test_progress_ends_with_the_step()
    print()
    print("=" * 60)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASSED))
        return 1
    print("ALL TOOL DIALOG CHECKS PASSED (%d)" % PASSED)
    return 0


if __name__ == "__main__":
    sys.exit(main())
