#!/usr/bin/env python3
"""Drive the "Print an order" panel against a stubbed Tk and a fake shop.

The panel exists for one question: which order? It answers it three ways -
the number on the dashboard, the customer's name, or a card's name - from the
website when the keys are saved and from the quotes folder always, then prints
the sheet the shop is packed against.

No network, no real order, no Tk: the widgets are the stand-ins in
test-photo-panel.py (reached through test-order-panel.py, which already wires
them up), and the website is a list of canned replies.
"""
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]

#  The Tk stand-ins, the fake requests and the fake app all live in the order
#  panel's test; importing it runs its definitions and none of its checks,
#  because it only calls main() when it is run by itself.
_spec = importlib.util.spec_from_file_location("order_panel",
                                              APP / "test-order-panel.py")
order_panel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(order_panel)

import gui  # noqa: E402
import quote as quote_model  # noqa: E402

FakeWidget = order_panel.FakeWidget
FakeApp = order_panel.FakeApp
BOX = order_panel.BOX
FakeNet = order_panel.FakeNet
SyncThread = order_panel.SyncThread

PASS = 0
FAIL = 0

SITE = ("https://shop.example", "ck_live", "cs_live")


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s %s" % (name, extra))


def full_order(number="1234", order_id=77, customer=("Dana", "Whitfield"),
               status="processing"):
    """One order as the shop's REST API answers with it."""
    first, last = customer
    return {
        "id": order_id, "number": number, "status": status,
        "currency": "CAD", "date_created": "2026-10-30T09:00:00",
        "date_paid": "2026-10-30T09:05:00", "total": "52.50",
        "discount_total": "0.00", "shipping_total": "0.00",
        "prices_include_tax": True, "billing": {
            "first_name": first, "last_name": last,
            "address_1": "18 Maple Row", "city": "Orangeville", "state": "ON",
            "postcode": "L9W 2C3", "country": "CA"},
        "line_items": [
            {"name": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
             "product_id": 1, "quantity": 1, "price": 40.0,
             "total": "40.00",
             "image": {"src": "https://shop.example/g.jpg"}},
            {"name": "1990 Score Mario Lemieux #2 NM", "product_id": 2,
             "quantity": 1, "price": 12.5, "total": "12.50",
             "sku": "ML-2", "image": {"src": "https://shop.example/l.jpg"}}],
    }


def reply(payload, status=200):
    return (status, json.dumps(payload).encode("utf-8"))


def build(app):
    """The panel's widgets, named the way a person sees them."""
    parent = FakeWidget()
    gui.build_ordersheet(parent, app)
    widgets = list(parent.walk())
    buttons = {}
    for widget in widgets:
        text = str(widget._kw.get("text") or "")
        if text and widget._kw.get("command") is not None:
            buttons.setdefault(text, widget)
    areas = {str(w._kw.get("text") or ""): w for w in widgets
             if isinstance(w, gui.ttk.LabelFrame)}
    parts = {"parent": parent, "widgets": widgets, "buttons": buttons,
             "areas": areas}
    parts["term"] = next(w._kw["textvariable"] for w in widgets
                         if w._kw.get("textvariable") is not None)
    parts["entry"] = next(w for w in widgets
                          if w._kw.get("textvariable") is not None)
    parts["listing"] = next(w for w in widgets if w._kw.get("height") == 7)
    found = areas["2. The orders it found"]
    parts["result"] = next(w for w in found.walk()
                           if isinstance(w, gui.ttk.Label)
                           and w is not found
                           and str(w._kw.get("text") or "") == ""
                           and w._kw.get("wraplength") is not None)
    parts["note"] = next(w for w in widgets
                         if isinstance(w, gui.ttk.Label)
                         and "quote's own paper" in str(w._kw.get("text") or ""))
    return parts


def saved_quote(app, name="Dana Whitfield", cards=("Batman #1",),
                number="Q-2026-0001"):
    """A quote file in the folder the panel reads, as one would really sit."""
    quote = quote_model.new_quote()
    quote["number"] = number
    quote["customer"]["name"] = name
    for card in cards:
        quote_model.add_item(quote, {"id": 501, "name": card,
                                     "price": "4.00",
                                     "images": [{"src":
                                                 "https://shop.example/b.jpg"}],
                                     "permalink":
                                         "https://shop.example/p/batman-1/"})
    return quote_model.save(quote, Path(app.settings["quotes_dir"]))


def run(app, parts, term, replies=(), keys=SITE, press=None):
    """Type a search, press Find, and hand back the fake shop's requests."""
    net = FakeNet(*replies)
    real_urlopen = urllib.request.urlopen
    urllib.request.urlopen = net
    try:
        with patch.object(gui, "read_woo_credentials",
                          lambda path=None: keys), \
                patch.object(gui.threading, "Thread", SyncThread):
            parts["term"].set(term)
            parts["buttons"]["Find the orders"].invoke()
    finally:
        urllib.request.urlopen = real_urlopen
    if press:
        press()
    return net


def lines(parts):
    return [str(item) for item in parts["listing"].items]


def test_panel_shape():
    print()
    print("== 1. the panel asks for one search and offers one button ==")
    app = FakeApp()
    parts = build(app)
    texts = [str(w._kw.get("text") or "") for w in parts["widgets"]]
    check("the panel is titled as the job it does",
          "Print an order as a PDF" in texts, texts[:4])
    check("it offers a search and the sheet",
          {"Find the orders", "Save the order as a PDF..."} <=
          set(parts["buttons"]), sorted(parts["buttons"]))
    check("the order list on the website is one click away",
          "Open the order list" in parts["buttons"], sorted(parts["buttons"]))
    check("both buttons explain themselves on hover",
          bool(gui.tip_for("Find the orders"))
          and bool(gui.tip_for("Save the order as a PDF...")),
          (gui.tip_for("Find the orders"),
           gui.tip_for("Save the order as a PDF...")))
    explain = " ".join(text for text in texts if "One box for all three" in text)
    check("it says all three things can be typed into the one box",
          all(word in explain for word in ("number", "customer", "card")),
          explain)
    check("and that looking changes nothing", "Nothing is changed" in explain,
          explain)
    check("the actions come before the explanations",
          parts["areas"]["1. Find the order"].packed
          and parts["areas"]["2. The orders it found"].packed)


def test_find_by_number():
    print()
    print("== 2. an order number is read straight from the shop ==")
    app = FakeApp()
    parts = build(app)
    order = full_order()
    net = run(app, parts, "1234", replies=[reply(order),
                                           reply([order]),
                                           reply([])])
    check("the number is read as itself, not searched for",
          any("/wc/v3/orders/1234?" in request["url"]
              for request in net.requests), [r["url"] for r in net.requests])
    check("the match is listed with the reason it is there",
          lines(parts) and "1234" in lines(parts)[0]
          and "Dana Whitfield" in lines(parts)[0]
          and "its number" in lines(parts)[0], lines(parts))
    check("a single match is already selected, so one press prints it",
          parts["listing"].selection == (0,), parts["listing"].selection)
    check("and the line says so", "already selected" in
          parts["result"]._kw.get("text", ""), parts["result"]._kw.get("text"))


def test_find_by_customer():
    print()
    print("== 3. a customer's name is the shop's own order search ==")
    app = FakeApp()
    parts = build(app)
    net = run(app, parts, "whitfield", replies=[reply([full_order()]),
                                                reply([])])
    check("the name is sent to the order search",
          any("search=whitfield" in request["url"] for request in net.requests),
          [r["url"] for r in net.requests])
    check("what it answers is listed",
          lines(parts) and "Dana Whitfield" in lines(parts)[0], lines(parts))
    check("with the shop's answer named as the reason",
          "the shop's search" in lines(parts)[0], lines(parts))


def test_find_by_card():
    print()
    print("== 4. a card's name is found by asking which orders hold it ==")
    app = FakeApp()
    parts = build(app)
    product = {"id": 501, "name": "1989 O-Pee-Chee Batman #1 NM 7"}
    net = run(app, parts, "batman", replies=[
        reply([]),            # the order search has nothing to say
        reply([product]),     # the card is a product
        reply([full_order()]),  # and this order holds it
    ])
    check("the card is looked up as a product first",
          any("/wc/v3/products?search=batman" in request["url"]
              for request in net.requests),
          [r["url"] for r in net.requests])
    check("then that product's orders are asked for",
          any("product=501" in request["url"] for request in net.requests),
          [r["url"] for r in net.requests])
    check("the order that holds it is listed",
          lines(parts) and "1234" in lines(parts)[0], lines(parts))
    check("and the card that matched is named in the row",
          "a card: 1989 O-Pee-Chee Batman #1 NM 7" in lines(parts)[0],
          lines(parts))


def test_print_from_the_shop():
    print()
    print("== 5. the match prints as the order's own sheet ==")
    app = FakeApp()
    parts = build(app)
    order = full_order()
    net = run(app, parts, "1234",
              replies=[reply(order), reply([order]), reply([])])
    seen, written, opened = {}, [], []

    real_document = gui.order_pdf.document

    def capture_document(*args, **kwargs):
        document = real_document(*args, **kwargs)
        seen.update(document)
        return document

    def fake_render(document, path, folder=None, **kwargs):
        written.append((document, path))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"%PDF-1.4\n%%EOF\n")
        return {"path": Path(path), "pages": 1, "pictures": 2, "missing": 0}

    with patch.object(gui.threading, "Thread", SyncThread), \
            patch.object(gui.order_pdf, "document", capture_document), \
            patch.object(gui.order_pdf, "render_with_pictures", fake_render), \
            patch.object(gui.order_pdf, "fetch_images",
                         lambda urls, folder, **k: {}), \
            patch.object(gui, "open_path",
                         lambda path: opened.append(str(path)) or True):
        parts["buttons"]["Save the order as a PDF..."].invoke()
    check("the sheet is the order's own, not the quote's",
          seen.get("number") == "1234", seen.get("number"))
    check("with every card and the picture the order holds",
          [item["name"] for item in seen.get("items", [])] ==
          ["1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
           "1990 Score Mario Lemieux #2 NM"]
          and seen["items"][0]["image"].endswith("g.jpg"), seen.get("items"))
    check("it says what state the order is in, in words",
          seen.get("status") == "Processing - paid"
          and seen.get("paid") == "2026-10-30",
          (seen.get("status"), seen.get("paid")))
    check("the file lands beside the quotes, named after the order",
          written and Path(written[0][1]).name == "order-1234.pdf",
          written)
    check("and is opened, so it can be checked before it goes in the box",
          opened and opened[0].endswith("order-1234.pdf"), opened)
    check("the console says where it went",
          any("Order sheet written" in text for _tag, text in app.lines),
          app.lines[-2:])
    check("printing reads the shop and never writes to it",
          all(request["method"] == "GET" for request in net.requests),
          [r["method"] for r in net.requests])


def test_print_nothing_selected():
    print()
    print("== 6. pressing print with nothing chosen asks which order ==")
    app = FakeApp()
    parts = build(app)
    BOX.shown.clear()
    parts["buttons"]["Save the order as a PDF..."].invoke()
    check("it asks, instead of printing something at random",
          BOX.shown and "Which order" in str(BOX.shown[-1]), BOX.shown[-1:])
    check("and writes no file", not (Path(app.settings["quotes_dir"]) /
                                     "orders").exists())


def test_without_keys():
    print()
    print("== 7. without keys the quotes folder still answers ==")
    app = FakeApp()
    path = saved_quote(app)
    parts = build(app)
    net = run(app, parts, "whitfield", replies=[], keys=("", "", ""))
    check("nothing is asked of the website without keys",
          not net.requests, [r["url"] for r in net.requests])
    check("the saved quote is found by the customer's name",
          lines(parts) and path.stem in lines(parts)[0], lines(parts))
    check("and the row says it is a quote",
          "quote" in lines(parts)[0], lines(parts))
    check("the panel says why the shop was not asked",
          "no WooCommerce keys" in parts["result"]._kw.get("text", ""),
          parts["result"]._kw.get("text"))

    seen, written = {}, []

    def fake_render(document, path, folder=None, **kwargs):
        written.append(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"%PDF-1.4\n%%EOF\n")
        return {"path": Path(path), "pages": 1, "pictures": 1, "missing": 0}

    real_document = gui.order_pdf.document

    def capture_document(*args, **kwargs):
        document = real_document(*args, **kwargs)
        seen.update(document)
        return document

    BOX.shown.clear()
    with patch.object(gui.threading, "Thread", SyncThread), \
            patch.object(gui.order_pdf, "document", capture_document), \
            patch.object(gui.order_pdf, "render_with_pictures", fake_render), \
            patch.object(gui, "open_path", lambda path: True):
        parts["buttons"]["Save the order as a PDF..."].invoke()
    check("the quote's own record prints when the shop cannot be asked",
          seen.get("quote_number") == "Q-2026-0001"
          and [item["name"] for item in seen.get("items", [])] ==
          ["Batman #1"], seen.get("items"))
    check("and the console says which record it came from",
          any("own record" in text for _tag, text in app.lines),
          app.lines[-3:])
    check("a quote's sheet still has every card pictured",
          seen["items"][0]["image"].endswith("b.jpg"), seen["items"][0])


def test_nothing_matched():
    print()
    print("== 8. a search that finds nothing says so ==")
    app = FakeApp()
    parts = build(app)
    run(app, parts, "zzz", replies=[reply([]), reply([])])
    check("nothing is listed", not lines(parts), lines(parts))
    check("and the panel says nothing matched, and quotes what was typed",
          "Nothing matched" in parts["result"]._kw.get("text", "")
          and "zzz" in parts["result"]._kw.get("text", ""),
          parts["result"]._kw.get("text"))
    check("the save button does not print an empty sheet",
          not (Path(app.settings["quotes_dir"]) / "orders").exists())


def test_blank_search():
    print()
    print("== 9. an empty box asks for something to look for ==")
    app = FakeApp()
    parts = build(app)
    BOX.shown.clear()
    net = FakeNet()
    real_urlopen = urllib.request.urlopen
    urllib.request.urlopen = net
    try:
        with patch.object(gui, "read_woo_credentials", lambda path=None: SITE):
            parts["term"].set("   ")
            parts["buttons"]["Find the orders"].invoke()
    finally:
        urllib.request.urlopen = real_urlopen
    check("nothing is sent to the shop", not net.requests, net.requests)
    check("the panel asks for a number, a name, or a card",
          BOX.shown and "order number" in str(BOX.shown[-1])
          and "card's name" in str(BOX.shown[-1]), BOX.shown[-1:])


def test_shop_refuses():
    print()
    print("== 10. a shop that will not answer leaves the quotes in view ==")
    app = FakeApp()
    path = saved_quote(app)
    parts = build(app)
    run(app, parts, "whitfield", replies=[OSError("no route to host"),
                                          OSError("no route to host")])
    check("the saved quote is still listed", lines(parts) and
          path.stem in lines(parts)[0], lines(parts))
    check("the panel says the website could not be searched, and why",
          "could not be searched" in parts["result"]._kw.get("text", ""),
          parts["result"]._kw.get("text"))
    check("and it is written to the console as an error",
          any(tag == "err" and "no route to host" in text
              for tag, text in app.lines), app.lines[-3:])


def test_order_list_button():
    print()
    print("== 11. the dashboard's order list is one click away ==")
    app = FakeApp()
    parts = build(app)
    with patch.object(gui, "read_woo_credentials", lambda path=None: SITE):
        parts["buttons"]["Open the order list"].invoke()
    check("it opens the order screen on the saved store",
          app.opened == ["https://shop.example/wp-admin/admin.php?"
                         "page=wc-orders"], app.opened)


def main():
    test_panel_shape()
    test_find_by_number()
    test_find_by_customer()
    test_find_by_card()
    test_print_from_the_shop()
    test_print_nothing_selected()
    test_without_keys()
    test_nothing_matched()
    test_blank_search()
    test_shop_refuses()
    test_order_list_button()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL ORDER SHEET PANEL CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
