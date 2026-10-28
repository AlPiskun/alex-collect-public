#!/usr/bin/env python3
"""Checks for sale_preview - the read-only half of "A card sold".

No network and no shop: the GET is a dict of canned replies, and the "already
added" marker is a temporary file. Then the sold panel itself is driven through
a fake Tk, to prove that Preview lists orders and writes nothing, and that
"Add these" sends only the previewed orders.
"""
import importlib.util
import json
import sys
import tempfile
import threading
import time
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
    """The fake-Tk harness from test-photo-panel, so panels can be driven."""
    spec = importlib.util.spec_from_file_location(
        "panel", str(APP / "test-photo-panel.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["panel"] = module
    spec.loader.exec_module(module)
    return module


def sync_background(app, work, done):
    """The real helper works on a thread; a test wants the answer now."""
    try:
        result, error = work(), None
    except Exception as exc:
        result, error = None, exc
    return done(result, error)


harness = load_harness()
gui = harness.gui
import sale_preview                                    # noqa: E402

ORDERS = [
    {"id": 42, "number": "1042", "status": "processing",
     "date_created": "2026-10-27T09:15:22",
     "line_items": [{"name": "1989 O-Pee-Chee Wayne Gretzky #1", "quantity": 1,
                     "sku": "GR-1"}]},
    {"id": 41, "number": "1041", "status": "completed",
     "date_created": "2026-10-26T18:02:00",
     "line_items": [{"name": "1972-73 O-Pee-Chee Dave Burrows #133",
                     "quantity": 2, "sku": ""},
                    {"name": "1990-91 Upper Deck Jaromir Jagr #356",
                     "quantity": 1, "sku": "JJ-356"}]},
    {"id": 40, "number": "1040", "status": "cancelled",
     "date_created": "2026-10-26T10:00:00",
     "line_items": [{"name": "Never sold card", "quantity": 1, "sku": ""}]},
]

PLUGIN_ORDERS = {"orders": [
    {"number": "CS-77", "status": "paid", "date": "2026-10-25 11:30:00",
     "items": [{"title": "1991-92 Pro Set Brett Hull #1", "qty": 1,
                "sku": "BH-1"}]}]}


def test_rows():
    print("== 1. orders become one row per card ==")
    rows = sale_preview.order_rows(ORDERS)
    check("a cancelled order is not a sale", len(rows) == 3, str(len(rows)))
    check("each row carries its order number",
          {r["order"] for r in rows} == {"1042", "1041"}, str(rows))
    check("the quantity comes from the line item",
          any(r["qty"] == 2 for r in rows), str([r["qty"] for r in rows]))
    check("the newest sale is first", rows[0]["order"] == "1042",
          str([(r["order"], r["date"]) for r in rows]))
    check("the order's internal id is kept for the API",
          rows[0]["id"] == "42", str(rows[0]))
    check("a card with no SKU is still a row",
          any(r["card"] == "1972-73 O-Pee-Chee Dave Burrows #133" and
              r["sku"] == "" for r in rows), str(rows))
    check("a line item with no name is dropped",
          sale_preview.order_rows([{"number": "1", "line_items": [
              {"name": "", "quantity": 1}]}]) == [], "")
    check("a junk order record does not crash the reader",
          sale_preview.order_rows([None, "x", {"number": "9"}]) == [], "")
    plugin_rows = sale_preview.order_rows(PLUGIN_ORDERS["orders"],
                                          statuses=())
    check("the plugin's items/qty/title shape is read too",
          [r["card"] for r in plugin_rows]
          == ["1991-92 Pro Set Brett Hull #1"], str(plugin_rows))
    check("its own statuses are not forced through WooCommerce's",
          len(plugin_rows) == 1 and
          sale_preview.order_rows(PLUGIN_ORDERS["orders"]) == [],
          str(plugin_rows))


def test_seen():
    print()
    print("== 2. only orders not added yet are new ==")
    rows = sale_preview.order_rows(ORDERS, source="website")
    fresh = sale_preview.unseen(rows, [])
    check("a first look sees everything", len(fresh) == 3, str(len(fresh)))
    seen = sale_preview.remember([], fresh)
    check("remembering stores source and order number, not cards",
          seen == ["website:1041", "website:1042"], str(seen))
    check("looking again finds nothing new",
          sale_preview.unseen(rows, seen) == [], "")
    newer = sale_preview.order_rows([{
        "number": "1043", "status": "processing",
        "date_created": "2026-10-28T08:00:00",
        "line_items": [{"name": "New card", "quantity": 1}]}], source="website")
    check("a later order is new again",
          len(sale_preview.unseen(newer, seen)) == 1, "")
    check("remembering again keeps both",
          sale_preview.remember(seen, newer)
          == ["website:1041", "website:1042", "website:1043"], "")
    cs = sale_preview.order_rows(PLUGIN_ORDERS["orders"], statuses=(),
                                 source="canadianshopper")
    check("the same order number on another site is a different sale",
          len(sale_preview.unseen(cs, ["website:CS-77"])) == 1, "")
    check("and it is remembered under its own source",
          sale_preview.remember([], cs) == ["canadianshopper:CS-77"], "")


def test_files():
    print()
    print("== 3. the marker file survives a restart ==")
    folder = Path(tempfile.mkdtemp())
    marker = folder / "seen.json"
    check("a missing file reads as nothing seen",
          sale_preview.load_seen(marker) == [], "")
    check("saving reports success", sale_preview.save_seen(marker, ["1042"]),
          "")
    check("the file comes back as numbers",
          sale_preview.load_seen(marker) == ["1042"],
          marker.read_text(encoding="utf-8") if marker.is_file() else "")
    marker.write_text("not json", encoding="utf-8")
    check("a corrupted file reads as nothing seen rather than crashing",
          sale_preview.load_seen(marker) == [], "")
    marker.write_text(json.dumps({"orders": ["7", "8"]}), encoding="utf-8")
    check("the stored shape is an object with an orders list",
          sale_preview.load_seen(marker) == ["7", "8"], "")
    deep = folder / "a" / "b" / "seen.json"
    check("a missing folder is created", sale_preview.save_seen(deep, ["1"]),
          "")


def test_plugin_file():
    print()
    print("== 4. the plugin answers with a file, not with console text ==")
    folder = Path(tempfile.mkdtemp())
    path = folder / "cs-orders.json"
    check("a missing file is nothing to show",
          sale_preview.read_orders_file(path) == [], "")
    path.write_text(json.dumps(PLUGIN_ORDERS), encoding="utf-8")
    check("an object holding orders is read",
          len(sale_preview.read_orders_file(path)) == 1, "")
    path.write_text(json.dumps(PLUGIN_ORDERS["orders"]), encoding="utf-8")
    check("a bare list is read as well",
          len(sale_preview.read_orders_file(path)) == 1, "")
    path.write_text("{oops", encoding="utf-8")
    check("unreadable JSON is nothing to show, not a crash",
          sale_preview.read_orders_file(path) == [], "")


def test_words():
    print()
    print("== 5. what the preview says ==")
    rows = sale_preview.order_rows(ORDERS)
    check("the headline counts cards and orders",
          sale_preview.headline(rows) == "4 cards on 2 orders, still to add.",
          sale_preview.headline(rows))
    check("one card on one order reads in the singular",
          sale_preview.headline(rows[:1]) == "1 card on 1 order, still to add.",
          sale_preview.headline(rows[:1]))
    check("nothing new says so plainly",
          sale_preview.headline([]) == "No new orders.", "")
    lines = sale_preview.describe(rows)
    check("each card gets a line with its order number",
          len(lines) == 3 and all("#10" in line for line in lines), str(lines))
    check("a quantity of two is shown, a quantity of one is not",
          any("x2" in line for line in lines) and
          sum("x1" in line for line in lines) == 0, str(lines))
    check("a long preview is cut with a count",
          sale_preview.describe(rows * 20, limit=5)[-1].startswith("  ... and "),
          sale_preview.describe(rows * 20, limit=5)[-1])
    check("a list line names the order, the date and the card",
          sale_preview.label(rows[0]).startswith("#1042  2026-10-27  "),
          sale_preview.label(rows[0]))


def test_reading():
    print()
    print("== 6. reading the website, and saying why when it cannot ==")
    calls = []

    def fetch_ok(base, path, params, key, secret):
        calls.append((path, dict(params)))
        page = params["page"]
        return 200, ORDERS if page == 1 else []

    orders = sale_preview.read_orders(fetch_ok, "https://shop.example",
                                      "ck_a", "cs_b")
    check("every order in the window comes back", len(orders) == 3,
          str(len(orders)))
    check("it reads the orders endpoint",
          calls and calls[0][0] == "/wp-json/wc/v3/orders", str(calls[:1]))
    check("it asks only for orders that are really sales",
          calls and calls[0][1]["status"] == "processing,completed",
          str(calls[:1]))
    check("it asks for the same date window the checklist tool uses",
          calls and str(calls[0][1].get("after", "")).startswith("20"),
          str(calls[:1]))
    check("it stops at the first short page", len(calls) == 1, str(len(calls)))

    calls.clear()
    sale_preview.read_orders(fetch_ok, "https://shop.example", "ck_a", "cs_b",
                             days=0)
    check("no window means no 'after' at all",
          "after" not in calls[0][1], str(calls[:1]))
    calls.clear()
    sale_preview.read_orders(fetch_ok, "https://shop.example", "ck_a", "cs_b",
                             since="2026-09-01T00:00:00")
    check("an explicit start date is used as given",
          calls[0][1].get("after") == "2026-09-01T00:00:00", str(calls[:1]))

    def fetch_full(base, path, params, key, secret):
        return 200, [{"number": str(params["page"]), "line_items": []}]

    many = sale_preview.read_orders(fetch_full, "https://shop.example",
                                    "ck_a", "cs_b", per_page=1, pages=3)
    check("a full page makes it ask for the next one, up to the limit",
          len(many) == 3, str(len(many)))

    def fetch(code, body="denied"):
        def inner(*a, **k):
            return code, body
        return inner

    for code, needle in ((401, "refused"), (403, "refused"), (500, "HTTP 500")):
        try:
            sale_preview.read_orders(fetch(code), "https://shop.example",
                                     "ck_a", "cs_b")
            check("HTTP %d is reported, not swallowed" % code, False, "")
        except sale_preview.PreviewError as exc:
            check("HTTP %d is reported, not swallowed" % code,
                  needle in exc.message, exc.message)
    try:
        sale_preview.read_orders(fetch(401), "https://shop.example",
                                 "ck_a", "cs_b")
    except sale_preview.PreviewError as exc:
        check("a refused key says where to fix it",
              "REST API" in exc.hint, exc.hint)
    try:
        sale_preview.read_orders(fetch(400), "https://shop.example",
                                 "ck_a", "cs_b")
    except sale_preview.PreviewError as exc:
        check("a rejected date window says so, and mentions the date",
              "date" in exc.message.lower() and "date" in exc.hint.lower(),
              exc.message + " / " + exc.hint)
    for missing in (("", "ck", "cs"), ("https://x", "", "")):
        try:
            sale_preview.read_orders(fetch(200), *missing)
            check("missing details are refused before any request", False, "")
        except sale_preview.PreviewError:
            check("missing details are refused before any request", True, "")


def test_channels():
    print()
    print("== 7. which channels can be previewed ==")
    check("the website is read through its API",
          sale_preview.channel_kind("website") == "api", "")
    check("CanadianShopper needs the plugin",
          sale_preview.channel_kind("canadianshopper") == "plugin", "")
    check("Facebook and eBay stay manual",
          sale_preview.channel_kind("facebook") == "manual" and
          sale_preview.channel_kind("ebay") == "manual", "")
    check("an unknown channel is manual",
          sale_preview.channel_kind("other") == "manual", "")


def build_panel():
    folder = Path(tempfile.mkdtemp())
    harness.install_plugin("1.0.16", folder / "plugin")
    app = harness.FakeApp(folder)
    parent = harness.FakeWidget()
    gui.build_sold(parent, app)
    return folder, app, parent


def find(parent, kind, text, exact=True):
    for widget in parent.walk():
        if not isinstance(widget, kind):
            continue
        got = str(widget.cget("text"))
        if (got == text) if exact else (got.startswith(text)):
            return widget
    return None


def test_panel():
    print()
    print("== 8. the sold panel previews, and writes nothing ==")
    folder, app, parent = build_panel()
    marker = folder / "seen.json"
    preview = find(parent, gui.ttk.Button, "Preview new orders")
    check("the panel has a Preview new orders button", preview is not None,
          str([w.cget("text") for w in parent.walk()
               if isinstance(w, gui.ttk.Button)]))
    order = [w.cget("text") for w in parent.walk()
             if isinstance(w, gui.ttk.Button)
             and w.cget("text") != "What this panel does"]
    check("it is the first task button on the panel",
          order and order[0] == "Preview new orders", str(order))
    summary = find(parent, gui.ttk.Label, "Nothing previewed yet.")
    check("the panel says nothing has been previewed yet",
          summary is not None, "")
    add_btn = find(parent, gui.ttk.Button, "Add these", exact=False)
    check("there is no add-these button before a preview",
          add_btn is not None and not add_btn.packed, "")

    def fetch(base, path, params, key, secret):
        return 200, ORDERS

    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a", "cs_b")), \
            patch.object(gui, "woo_get", fetch), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "SOLD_ORDERS_SEEN", marker):
        preview.invoke()
    check("no tool was started by a preview", not app.runs, str(app.runs))
    check("the console names the orders",
          any("#1042" in text for _tag, text in app.lines), str(app.lines[-4:]))
    check("it says how much sold",
          any("cards on" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and that nothing was written",
          any("nothing has been written" in text.lower()
              for _tag, text in app.lines), str(app.lines[-2:]))
    listing = next((w for w in parent.walk() if isinstance(w, gui.tk.Listbox)),
                   None)
    check("each card is shown in the panel, not only the console",
          listing is not None and len(listing.items) == 3,
          str(listing and listing.items))
    check("the summary counts what is still to add",
          summary.cget("text") == "4 cards on 2 orders, still to add.",
          summary.cget("text"))
    check("the add-these button appears, naming the count",
          add_btn.packed and add_btn.cget("text").startswith("Add these 3 cards"),
          add_btn.cget("text"))
    check("nothing was written to the checklist",
          not (folder / "sold-cards-checklist.csv").exists(), "")
    check("no marker file is written by a preview alone",
          not marker.exists(), str(marker))

    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a", "cs_b")), \
            patch.object(gui, "woo_get", fetch), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "SOLD_ORDERS_SEEN", marker):
        preview.invoke()
    check("looking again still shows them: a preview is not an add",
          len(listing.items) == 3, str(listing.items))
    check("and it still starts no tool", not app.runs, str(app.runs))

    # ---- adding the previewed orders only
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a", "cs_b")), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "SOLD_ORDERS_SEEN", marker):
        add_btn.invoke()
    check("adding runs the checklist tool", len(app.runs) == 1, str(app.runs))
    args = app.runs[0]["args"] if app.runs else []
    check("it asks for exactly the previewed orders",
          "--orders" in args and args[args.index("--orders") + 1] == "41,42",
          str(args))
    check("it writes the checklist", "--checklist" in args, str(args))
    check("the marker is not written before the tool finishes",
          not marker.exists(), str(marker))
    if app.runs:
        app.runs[0]["on_done"](1)
    check("a failed run leaves the orders to be previewed again",
          not marker.exists() and len(listing.items) == 3,
          str(marker) + " " + str(listing.items))
    if app.runs:
        with patch.object(gui, "SOLD_ORDERS_SEEN", marker):
            app.runs[0]["on_done"](0)
    check("a successful run remembers the orders",
          sale_preview.load_seen(marker) == ["website:1041", "website:1042"],
          str(sale_preview.load_seen(marker)))
    check("and clears the list, so the sale is not added twice",
          not listing.items and not add_btn.packed, str(listing.items))
    check("it says the cards were added",
          "Added" in summary.cget("text"), summary.cget("text"))


def test_preview_failure():
    print()
    print("== 9. a refused key is drawn, not swallowed ==")
    folder, app, parent = build_panel()
    marker = folder / "seen.json"
    preview = find(parent, gui.ttk.Button, "Preview new orders")
    summary = find(parent, gui.ttk.Label, "Nothing previewed yet.")
    shown = []
    real = harness._BOX.showerror
    harness._BOX.showerror = lambda *a, **k: shown.append(a)

    def refused(*a, **k):
        return 401, {"code": "woocommerce_rest_cannot_view"}

    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a", "cs_b")), \
            patch.object(gui, "woo_get", refused), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "SOLD_ORDERS_SEEN", marker):
        preview.invoke()
    harness._BOX.showerror = real
    check("the refusal is shown, not swallowed",
          shown and "refused" in str(shown[0]), str(shown))
    check("the dialog says where to fix the key",
          shown and "REST API" in str(shown[0]), str(shown))
    check("the summary says the read failed",
          "Could not read" in summary.cget("text"), summary.cget("text"))
    check("nothing is previewed after a failure",
          not any(w.packed for w in parent.walk()
                  if isinstance(w, gui.ttk.Button)
                  and str(w.cget("text")).startswith("Add these")), "")
    check("and nothing is remembered", not marker.exists(), str(marker))


def test_background_helper():
    print()
    print("== 9b. a slow read never freezes the window ==")
    class SlowApp:
        def __init__(self):
            self.calls = []
        def after(self, delay, callback=None):
            self.calls.append(delay)
            if callback is not None:
                callback()
            return "id"
    app = SlowApp()
    seen_thread, answers = {}, []

    def work():
        seen_thread["id"] = threading.get_ident()
        time.sleep(0.15)
        return ["order"]

    started = time.time()
    gui.in_background(app, work, lambda result, error: answers.append((result, error)))
    elapsed = time.time() - started
    check("the call returns before the work does", elapsed < 0.1,
          "%.3fs" % elapsed)
    deadline = time.time() + 3
    while not answers and time.time() < deadline:
        time.sleep(0.01)
    check("the answer comes back through the window's after()",
          answers and answers[0][0] == ["order"] and app.calls == [0],
          str(answers) + " " + str(app.calls))
    check("the work ran on its own thread",
          seen_thread.get("id") not in (None, threading.get_ident()),
          str(seen_thread))

    answers[:] = []

    def broken():
        raise ValueError("no shop today")

    gui.in_background(app, broken, lambda result, error: answers.append((result, error)))
    deadline = time.time() + 3
    while not answers and time.time() < deadline:
        time.sleep(0.01)
    check("a failure comes back as the error, not as a crash",
          answers and answers[0][0] is None and
          isinstance(answers[0][1], ValueError), str(answers))


def test_panel_without_keys():
    print()
    print("== 10. with no keys it offers them, and previews nothing ==")
    folder, app, parent = build_panel()
    preview = find(parent, gui.ttk.Button, "Preview new orders")
    asked, opened = [], []

    def ask(title, message="", **k):
        asked.append((title, message))
        return False

    harness._BOX.askyesno = ask
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("", "", "")), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "open_woo_keys_file",
                         lambda a, site="": opened.append(site)), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "woo_get", lambda *a, **k: (200, ORDERS)):
        preview.invoke()
    check("the app offers the one-time key setup",
          any("API keys" in title for title, _msg in asked), str(asked))
    check("it says the keys make the sale one click",
          any("one click" in msg.lower() for _title, msg in asked),
          str(asked))
    check("and says the key is read-only",
          any("READ-ONLY" in msg for _title, msg in asked), str(asked))
    check("declining opens no file", opened == [], str(opened))
    check("and nothing is previewed or run", not app.runs, str(app.runs))
    check("the console says what to do instead",
          any("type the cards" in text.lower() for _tag, text in app.lines),
          str(app.lines[-2:]))

    harness._BOX.askyesno = lambda *a, **k: True
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("", "", "")), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "open_woo_keys_file",
                         lambda a, site="": opened.append(site)):
        preview.invoke()
        harness._BOX.askyesno = ask
    check("accepting opens the keys file for the saved site",
          opened == ["https://shop.example"], str(opened))
    check("nothing was written into the program folder",
          not (folder / "woo-keys.txt").exists() and not app.runs,
          str(folder))


def test_cs_channel():
    print()
    print("== 11. CanadianShopper is read through the plugin ==")
    folder, app, parent = build_panel()
    marker = folder / "seen.json"
    out = folder / "cs-orders.json"
    cs_radio = find(parent, gui.ttk.Radiobutton, "CanadianShopper")
    preview = find(parent, gui.ttk.Button, "Preview new orders")
    listing = next(w for w in parent.walk() if isinstance(w, gui.tk.Listbox))
    cs_radio.invoke()

    shown = []
    real_showinfo = harness._BOX.showinfo
    harness._BOX.showinfo = lambda *a, **k: shown.append(a)
    with patch.object(gui, "TOOL_ACTION", lambda action: ""), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "SOLD_ORDERS_SEEN", marker):
        preview.invoke()
    check("without the action the panel says what is missing",
          any("order reader" in str(a) for a in shown), str(shown))
    check("it offers the manual route in the same breath",
          any("Type the cards" in str(a) for a in shown), str(shown))
    check("and it starts nothing", not app.runs, str(app.runs))

    shown[:] = []
    cookie = folder / "cookie.txt"
    cookie.write_text("session", encoding="utf-8")
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/sold-cards.py" if
                      action == gui.CS_ORDERS_ACTION else ""), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "SOLD_ORDERS_SEEN", marker):
        preview.invoke()
        check("with the action it runs the plugin's reader",
              len(app.runs) == 1, str(app.runs))
        args = app.runs[0]["args"] if app.runs else []
        check("the reader is told where to write its orders",
              "--orders-out" in args and
              args[args.index("--orders-out") + 1] == str(out), str(args))
        check("it passes the session cookie file",
              "--cookie-file" in args, str(args))
        check("nothing is previewed until the plugin answers",
              not listing.items, str(listing.items))
        out.write_text(json.dumps(PLUGIN_ORDERS), encoding="utf-8")
        app.runs[0]["on_done"](0)
    check("the plugin's orders appear in the list",
          listing.items and "CS-77" in listing.items[0], str(listing.items))
    check("the console names the CanadianShopper sale",
          any("CS-77" in text for _tag, text in app.lines), str(app.lines[-3:]))
    check("a failed plugin read shows nothing",
          app.runs[0]["on_done"](3) is False, "")
    check("and no marker is written by a preview",
          not marker.exists(), str(marker))
    harness._BOX.showinfo = real_showinfo

    add_btn = find(parent, gui.ttk.Button, "Add these", exact=False)
    runs_before = len(app.runs)
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "SOLD_ORDERS_SEEN", marker):
        add_btn.invoke()
    check("adding a CanadianShopper sale runs a second command",
          len(app.runs) == runs_before + 1, str(app.runs[runs_before:]))
    cs_args = app.runs[-1]["args"] if app.runs else []
    check("its order number is never sent to WooCommerce",
          "--woo-keys" not in cs_args and "--orders" not in cs_args,
          str(cs_args))
    check("the cards go in as a list, tagged CanadianShopper",
          cs_args[:1] == ["--list"] and
          cs_args[cs_args.index("--sold-on") + 1] == "canadianshopper",
          str(cs_args))
    written = Path(cs_args[1]) if cs_args[:1] == ["--list"] else None
    check("that list holds the previewed card",
          written is not None and written.is_file() and
          "Pro Set Brett Hull" in written.read_text(encoding="utf-8"),
          written.read_text(encoding="utf-8") if written and
          written.is_file() else "")


def test_follow_up_pages():
    print()
    print("== 12. the old route still works and still opens the pages ==")
    folder, app, parent = build_panel()
    typed = folder / "sold-cards.txt"
    typed.write_text("1989 O-Pee-Chee Wayne Gretzky #1\n", encoding="utf-8")
    editor = find(parent, gui.ttk.Button, "Type the cards...")
    with patch.object(gui, "Editor") as editor_class:
        def fake_editor(**kwargs):
            kwargs["on_saved"](typed)
            return None
        editor_class.side_effect = fake_editor
        editor.invoke()
    check("typing a card remembers its file", True, "")
    add_rows = find(parent, gui.ttk.Button, "Add to the checklist", exact=False)
    with patch.object(gui, "typed_sale_title", lambda text: "Gretzky"):
        add_rows.invoke()
    check("the old add route still runs sold-everywhere.py",
          app.runs and app.runs[-1]["tool"].endswith("sold-everywhere.py"),
          str(app.runs[-1:]))
    check("and it still opens the follow-up pages",
          bool(app.opened), str(app.opened))


def main():
    test_rows()
    test_seen()
    test_files()
    test_plugin_file()
    test_words()
    test_reading()
    test_channels()
    test_panel()
    test_preview_failure()
    test_background_helper()
    test_panel_without_keys()
    test_cs_channel()
    test_follow_up_pages()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL SALE PREVIEW CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
