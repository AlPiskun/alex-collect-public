#!/usr/bin/env python3
"""Drive the real "order from a text list" panel against a stubbed Tk.

The panel decides which card each pasted line means, asks about the unclear
ones, and writes the order. This file presses those buttons the way a user
would, with the real woo_orders code talking to a fake urlopen, so the JSON
that would reach the shop is checked rather than assumed.

No network, no real order, no Tk.
"""
import importlib.util
import json
import sys
import tempfile
import urllib.request
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]

#  The Tk stand-ins live in test-photo-panel.py, which also stubs Tk before
#  importing gui. Reusing them keeps one copy of that plumbing.
_spec = importlib.util.spec_from_file_location("photo_panel",
                                              APP / "test-photo-panel.py")
photo_panel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(photo_panel)

import gui  # noqa: E402

FakeWidget = photo_panel.FakeWidget
FakeVar = photo_panel.FakeVar
BOX = photo_panel._BOX
PICKER = photo_panel.PICKER
ASKSTRING = []

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


class SyncThread:
    """Runs the panel's lookup thread inline, so a test is deterministic."""

    def __init__(self, target=None, daemon=None, **kwargs):
        self.target = target

    def start(self):
        if self.target:
            self.target()


class Reply:
    def __init__(self, status, body):
        self.status = status
        self._body = body
    def read(self): return self._body
    def __enter__(self): return self
    def __exit__(self, *exc): return False


class FakeNet:
    """Stands in for urlopen: records each order request, replays replies."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append({
            "method": request.get_method(),
            "url": request.full_url,
            "body": json.loads(request.data.decode("utf-8"))
            if request.data else None,
        })
        reply = self.replies.pop(0) if self.replies else (200, b"{}")
        if isinstance(reply, Exception):
            raise reply
        return Reply(*reply)


def order_json(order_id=77, number="1234", line_items=()):
    return (200, json.dumps({"id": order_id, "number": number,
                             "line_items": list(line_items),
                             "fee_lines": []}).encode("utf-8"))


CATALOG = [
    {"id": 1, "name": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
     "price": "40.00", "stock_status": "instock"},
    {"id": 2, "name": "1990 Score Mario Lemieux #2 NM", "price": "12.50",
     "stock_status": "instock"},
    {"id": 4, "name": "1966 Topps Bobby Orr #35 VG", "price": "400.00",
     "stock_status": "outofstock"},
]


def words_match(term, name):
    """The way WooCommerce matches: every word of the term must appear.

    A literal substring test would fail "107 pelyk" against "Mike Pelyk #107"
    and send the panel down a fallback it would not need on a real site.
    """
    wanted = [w for w in term.lower().replace("#", " ").split() if len(w) > 2]
    return bool(wanted) and all(w in name.lower() for w in wanted)


def search(site, path, params, key, secret, **kwargs):
    """A stand-in for the site's product search (the woo_get signature)."""
    term = str((params or {}).get("search") or "")
    matches = [row for row in CATALOG if words_match(term, row["name"])]
    return (200, matches) if matches else (200, [])


class FakeApp:
    def __init__(self):
        #  Quotes and order sheets are written under a temp folder: a test
        #  must never leave documents in the app's own folder.
        self.folder = Path(tempfile.mkdtemp(prefix="alex-order-panel-"))
        self.settings = {"woo_site_url": "https://shop.example",
                         "quotes_dir": str(self.folder / "quotes"),
                         "scan_dir": "/tmp", "pipeline_dir": "/tmp",
                         "browser_name": "system",
                         "canadianshopper_store_url": "",
                         "ebay_selling_url": "", "facebook_selling_url": ""}
        self.cs_addon = False
        self.opened, self.lines = [], []
        self.clipboard = None

    def open_webpages(self, urls, new_window=False):
        self.opened.extend(urls)
        return "Test browser"

    def console_line(self, text, tag=""):
        self.lines.append((tag, str(text)))

    def after(self, delay, callback):
        return callback()

    def update(self):
        pass

    def update_idletasks(self):
        pass

    def wait_window(self, window):
        window.wait_window()

    def clipboard_clear(self):
        self.clipboard = ""

    def clipboard_append(self, text):
        self.clipboard = (self.clipboard or "") + text


def build(app):
    """The panel's widgets, plus the text box the user would paste into."""
    parent = FakeWidget()
    gui.build_ordertext(parent, app)
    widgets = list(parent.walk())
    #  Every stub widget is the same class, so the text box is recognised by
    #  the keyword it was built with rather than by its type.
    box = next(w for w in widgets if w._kw.get("wrap") == "word")
    build_button = next(w for w in widgets if w.cget("text") == "Build the order")
    orders_button = next(w for w in widgets
                         if w.cget("text") == "Open the order list")
    #  The panel reads its StringVar, not the Entry widget around it.
    discount = next(w._kw["textvariable"] for w in widgets
                    if w._kw.get("textvariable") is not None)
    return box, build_button, orders_button, discount




def run_panel(app, text, keys=(("https://shop.example", "ck_live", "cs_live")),
              answers=None, net=None, picker=None, order_number=None,
              search_fn=None):
    """Paste text, press the button, and report what happened."""
    box, build_button, orders_button, discount = build(app)
    box.value = text
    asked = []

    def askyesno(title, *a, **k):
        asked.append(title)
        return (answers or {}).get(title, False)

    BOX.askyesno = askyesno
    BOX.askyesnocancel = lambda title, *a, **k: asked.append(title) or \
        (answers or {}).get(title)
    ASKSTRING.clear()

    def askstring(*a, **k):
        ASKSTRING.append(a)
        return order_number

    gui.simpledialog.askstring = askstring
    PICKER["press"] = picker or (lambda window: window.destroy())
    site, key, secret = keys
    real_urlopen = urllib.request.urlopen
    if net is not None:
        urllib.request.urlopen = net
    with patch.object(gui.threading, "Thread", SyncThread), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: (site, key, secret)), \
            patch.object(gui, "woo_get", search_fn or search):
        try:
            build_button.invoke()
        finally:
            urllib.request.urlopen = real_urlopen
    return asked, orders_button, discount


def test_no_keys():
    print("== 1. without keys the order list opens and the list is copied ==")
    app = FakeApp()
    asked, orders_button, _ = run_panel(
        app, "1. 1989 O-Pee-Chee Gretzky #1\n2. 1990 Score Mario Lemieux #2",
        keys=("", "", ""))
    check("the dashboard order list is opened",
          app.opened == ["https://shop.example/wp-admin/admin.php?page=wc-orders"],
          str(app.opened))
    check("the pasted list is put on the clipboard",
          app.clipboard and "Gretzky" in app.clipboard, str(app.clipboard))
    check("nothing is written", not app.lines, str(app.lines))
    check("the user is told what happened",
          BOX.shown and "clipboard" in str(BOX.shown[-1]), str(BOX.shown[-1:]))


def test_new_order():
    print()
    print("== 2. a new order is created from the pasted list ==")
    app = FakeApp()
    BOX.shown.clear()
    net = FakeNet(order_json())
    asked, _, _ = run_panel(
        app,
        "1. 1989 O-Pee-Chee Gretzky #1\n2. 1990 Score Mario Lemieux #2\n"
        "3. 1966 Topps Bobby Orr #35",
        answers={"New order or an existing one?": True,
                 "Create the order?": True}, net=net)
    check("it asks new or existing first",
          "New order or an existing one?" in asked, str(asked))
    check("it confirms before writing", "Create the order?" in asked, str(asked))
    check("one POST is made", len(net.requests) == 1,
          str([r["method"] for r in net.requests]))
    sent = net.requests[0]
    check("the three cards are on it",
          [i["product_id"] for i in sent["body"]["line_items"]] == [1, 2, 4],
          str(sent["body"]))
    check("the order is pending, not paid",
          sent["body"]["status"] == "pending" and
          sent["body"]["set_paid"] is False, str(sent["body"]))
    check("the new order is opened in the dashboard",
          app.opened == ["https://shop.example/wp-admin/post.php?post=77"
                         "&action=edit"], str(app.opened))
    check("the console records the order number",
          any("Order #1234" in text for _, text in app.lines), str(app.lines))


def test_picker_saves_a_line():
    print()
    print("== 3. an unclear line opens the picker and uses the choice ==")
    app = FakeApp()
    BOX.shown.clear()
    net = FakeNet(order_json())
    pressed = {"n": 0}

    def choose_mario(window):
        pressed["n"] += 1
        for widget in window.walk():
            if widget.cget("text") == "Use this card":
                widget.invoke()
                return
        window.destroy()

    #  "Lemieux" on its own fits more than one card, so it must be asked about
    #  rather than guessed at even though only one product matches today.
    run_panel(app, "Lemieux", net=net, picker=choose_mario,
              answers={"New order or an existing one?": True,
                       "Create the order?": True})
    check("the picker is opened for the unclear line", pressed["n"] == 1,
          str(pressed))
    check("the chosen card is what gets ordered",
          net.requests and
          [i["product_id"] for i in net.requests[0]["body"]["line_items"]] == [2],
          str(net.requests[0]["body"] if net.requests else ""))


def test_picker_skip():
    print()
    print("== 4. skipping a line leaves it off the order ==")
    app = FakeApp()
    net = FakeNet(order_json())

    def skip_it(window):
        for widget in window.walk():
            if widget.cget("text") == "Skip this one":
                widget.invoke()
                return

    run_panel(app,
              "1989 O-Pee-Chee Gretzky #1\nKen Dryden 1972\n"
              "1990 Score Mario Lemieux #2",
              net=net, picker=skip_it,
              answers={"New order or an existing one?": True,
                       "Create the order?": True})
    check("only the matched cards are ordered",
          [i["product_id"] for i in net.requests[0]["body"]["line_items"]] ==
          [1, 2], str(net.requests[0]["body"]))
    check("the skipped line is reported after writing",
          any("1 skipped" in text for _, text in app.lines), str(app.lines))


def test_cancel_all():
    print()
    print("== 5. cancelling in the picker writes nothing ==")
    app = FakeApp()
    net = FakeNet()

    def cancel_all(window):
        for widget in window.walk():
            if widget.cget("text") == "Cancel all":
                widget.invoke()
                return

    run_panel(app, "Ken Dryden 1972", net=net, picker=cancel_all,
              answers={"New order or an existing one?": True,
                       "Create the order?": True})
    check("no request is made", not net.requests, str(net.requests))


def test_existing_order():
    print()
    print("== 6. adding to an order that already exists ==")
    app = FakeApp()
    existing = [{"id": 501, "product_id": 2, "quantity": 1}]
    #  The order is read once to confirm the number at the prompt, and again
    #  just before the change so the merge works from fresh line items.
    net = FakeNet(order_json(77, "1234", existing),
                  order_json(77, "1234", existing),
                  order_json(77, "1234", existing + [{"id": 502}]))
    asked, _, _ = run_panel(
        app, "1989 O-Pee-Chee Gretzky #1\n1990 Score Mario Lemieux #2",
        net=net, order_number="1234",
        answers={"New order or an existing one?": False,
                 "Create the order?": True})
    check("it asks for the order number", len(ASKSTRING) == 1,
          str(ASKSTRING))
    check("the order is read before it is changed",
          net.requests[0]["method"] == "GET" and "/orders/1234" in
          net.requests[0]["url"], str(net.requests[0]["url"]))
    put = net.requests[2]
    check("the change is a PUT to that order",
          put["method"] == "PUT" and "/orders/77" in put["url"], put["url"])
    check("a card already on the order gains quantity",
          put["body"]["line_items"][0] == {"id": 501, "quantity": 2},
          str(put["body"]["line_items"]))
    check("the new card is appended",
          put["body"]["line_items"][1] == {"product_id": 1, "quantity": 1},
          str(put["body"]["line_items"]))
    check("no new order is created, only the order was changed",
          len(net.requests) == 3 and
          all(r["method"] != "POST" for r in net.requests),
          str([r["method"] for r in net.requests]))


def test_discount_and_duplicates():
    print()
    print("== 7. a discount, and the same card twice ==")
    app = FakeApp()
    net = FakeNet(order_json())
    box, build_button, orders_button, discount = build(app)
    box.value = "1989 O-Pee-Chee Gretzky #1\n1989 O-Pee-Chee Gretzky #1"
    discount.set("15")
    BOX.askyesno = lambda title, *a, **k: title == "Create the order?"
    BOX.askyesnocancel = lambda title, *a, **k: title == \
        "New order or an existing one?"
    real = urllib.request.urlopen
    urllib.request.urlopen = net
    try:
        with patch.object(gui.threading, "Thread", SyncThread), \
                patch.object(gui, "read_woo_credentials",
                             lambda path=None: ("https://shop.example",
                                                "ck_live", "cs_live")), \
                patch.object(gui, "woo_get", search):
            build_button.invoke()
    finally:
        urllib.request.urlopen = real
    body = net.requests[0]["body"]
    check("the same card twice is one row of quantity 2",
          body["line_items"] == [{"product_id": 1, "quantity": 2}],
          str(body["line_items"]))
    check("the discount is one negative fee line",
          body["fee_lines"] == [{"name": "Discount 15%", "total": "-12.00"}],
          str(body.get("fee_lines")))


def test_nothing_matched():
    print()
    print("== 8. a list nobody stocks creates nothing ==")
    app = FakeApp()
    net = FakeNet()
    BOX.shown.clear()
    run_panel(app, "Ken Dryden 1972", net=net,
              picker=lambda window: [w for w in window.walk()
                                     if w.cget("text") == "Skip this one"][0]
              .invoke(),
              answers={"New order or an existing one?": True,
                       "Create the order?": True})
    check("no order is written", not net.requests, str(net.requests))
    check("the user is told nothing matched",
          any("Nothing matched" in str(payload) for _, payload in BOX.shown),
          str(BOX.shown[-1:]))


def test_cancel_confirm():
    print()
    print("== 9. declining the confirmation writes nothing ==")
    app = FakeApp()
    net = FakeNet()
    run_panel(app, "1989 O-Pee-Chee Gretzky #1", net=net,
              answers={"New order or an existing one?": True,
                       "Create the order?": False})
    check("no request is made", not net.requests, str(net.requests))


def test_long_list_uses_scrollable_confirm():
    print()
    print("== 10. a long list is confirmed in a scrollable window ==")
    catalogue = [{"id": 100 + n, "name": "Test Card %d #%d NM" % (n, n),
                  "price": "10.00", "stock_status": "instock"}
                 for n in range(1, 26)]

    def big_search(site, path, params, key, secret, **kwargs):
        term = str((params or {}).get("search") or "")
        hits = [row for row in catalogue if words_match(term, row["name"])]
        return (200, hits) if hits else (200, [])

    app = FakeApp()
    net = FakeNet(order_json())
    lines = "\n".join("Test Card %d #%d" % (n, n) for n in range(1, 26))
    pressed = {"scrollable": False}

    def press(window):
        texts = [w.cget("text") for w in window.walk()]
        if "Create the order" in texts:
            pressed["scrollable"] = True
            for widget in window.walk():
                if widget.cget("text") == "Create the order":
                    widget.invoke()
                    return
        for widget in window.walk():
            if widget.cget("text") == "Use this card":
                widget.invoke()
                return

    run_panel(app, lines, net=net, picker=press, search_fn=big_search,
              answers={"New order or an existing one?": True})
    check("the long confirmation is a scrollable window",
          pressed["scrollable"], str(pressed))
    check("all 25 cards are on the order",
          net.requests and len(net.requests[0]["body"]["line_items"]) == 25,
          str(len(net.requests[0]["body"]["line_items"])
              if net.requests else 0))


def test_discount_refused():
    print()
    print("== 11. an unreadable discount writes nothing ==")
    for typed in ("abc", "150", "-5"):
        app = FakeApp()
        net = FakeNet(order_json())
        BOX.shown.clear()
        box, build_button, _, discount = build(app)
        box.value = "1989 O-Pee-Chee Gretzky #1"
        discount.set(typed)
        BOX.askyesno = lambda *a, **k: True
        BOX.askyesnocancel = lambda *a, **k: True
        real = urllib.request.urlopen
        urllib.request.urlopen = net
        try:
            with patch.object(gui.threading, "Thread", SyncThread), \
                    patch.object(gui, "read_woo_credentials",
                                 lambda path=None: ("https://shop.example",
                                                    "ck_live", "cs_live")), \
                    patch.object(gui, "woo_get", search):
                build_button.invoke()
        finally:
            urllib.request.urlopen = real
        check("%r is refused instead of charging full price" % typed,
              not net.requests and any(
                  "Discount not understood" in str(payload)
                  for _, payload in BOX.shown), str(BOX.shown[-1:]))


def test_percent_sign():
    print()
    print("== 12. a percent sign is accepted ==")
    app = FakeApp()
    net = FakeNet(order_json())
    box, build_button, _, discount = build(app)
    box.value = "1989 O-Pee-Chee Gretzky #1"
    discount.set("15%")
    BOX.askyesno = lambda *a, **k: True
    BOX.askyesnocancel = lambda *a, **k: True
    real = urllib.request.urlopen
    urllib.request.urlopen = net
    try:
        with patch.object(gui.threading, "Thread", SyncThread), \
                patch.object(gui, "read_woo_credentials",
                             lambda path=None: ("https://shop.example",
                                                "ck_live", "cs_live")), \
                patch.object(gui, "woo_get", search):
            build_button.invoke()
    finally:
        urllib.request.urlopen = real
    check("15% becomes one discount line",
          net.requests and net.requests[0]["body"]["fee_lines"] ==
          [{"name": "Discount 15%", "total": "-6.00"}],
          str(net.requests[0]["body"].get("fee_lines") if net.requests else ""))


def test_hash_lines_reach_the_order():
    print()
    print("== 13. lines written #217 reach the order ==")
    stocked = [
        {"id": 217, "name": "1970-71 O-Pee-Chee Paul Henderson #217 NM",
         "price": "25.00", "stock_status": "instock"},
        {"id": 107, "name": "1970-71 O-Pee-Chee Mike Pelyk #107 RC",
         "price": "8.00", "stock_status": "instock"},
    ]

    def stocked_search(site, path, params, key, secret, **kwargs):
        term = str((params or {}).get("search") or "")
        hits = [row for row in stocked if words_match(term, row["name"])]
        return (200, hits) if hits else (200, [])

    app = FakeApp()
    net = FakeNet(order_json())
    run_panel(app,
              "#217 Paul Henderson (Near Mint) 1970-71 O-Pee-Chee\n"
              "\n"
              "#107 Mike Pelyk (Rookie Card) 1970-71 O-Pee-Chee\n",
              net=net, search_fn=stocked_search,
              answers={"New order or an existing one?": True,
                       "Create the order?": True})
    check("the panel does not treat a card number as a comment",
          net.requests and len(net.requests[0]["body"]["line_items"]) == 2,
          str(net.requests[0]["body"]["line_items"] if net.requests else "none"))


def test_open_button():
    print()
    print("== 13. the open-list button ==")
    app = FakeApp()
    _, _, orders_button, _ = build(app)
    orders_button.invoke()
    check("it opens the dashboard order list",
          app.opened == ["https://shop.example/wp-admin/admin.php?page=wc-orders"],
          str(app.opened))


def test_order_sheet_moved():
    """The sheet is printed from its own panel now, not from this one.

    Printing a packed order is an after-the-sale job that finds an order by
    number, customer or card - not something the panel that writes an order
    from a pasted list should also be doing. What matters here is that this
    panel let go of it: a button left behind would print the wrong record
    without the person knowing which.
    """
    print()
    print("== 15. the order sheet belongs to its own panel ==")
    app = FakeApp()
    parent = FakeWidget()
    gui.build_ordertext(parent, app)
    texts = [str(w.cget("text") or "") for w in parent.walk()]
    check("the order-from-a-list panel no longer prints sheets",
          "Save the order as a PDF..." not in texts,
          [text for text in texts if "PDF" in text])
    check("and nothing else on it claims to", 
          not any("PDF" in text for text in texts),
          [text for text in texts if "PDF" in text])
    check("the order it writes is opened instead",
          any(text == "Open the order list" for text in texts), texts)


def test_empty_paste():
    print()
    print("== 14. an empty box asks for a list ==")
    app = FakeApp()
    net = FakeNet()
    BOX.shown.clear()
    asked, _, _ = run_panel(app, "   \n\n", net=net)
    check("nothing is written", not net.requests and not app.lines)
    check("the user is asked for a list",
          any("Paste a list first" in str(payload) for _, payload in BOX.shown),
          str(BOX.shown[-1:]))


def main():
    test_no_keys()
    test_new_order()
    test_picker_saves_a_line()
    test_picker_skip()
    test_cancel_all()
    test_existing_order()
    test_discount_and_duplicates()
    test_nothing_matched()
    test_cancel_confirm()
    test_long_list_uses_scrollable_confirm()
    test_discount_refused()
    test_percent_sign()
    test_hash_lines_reach_the_order()
    test_open_button()
    test_empty_paste()
    test_order_sheet_moved()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL ORDER PANEL CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
