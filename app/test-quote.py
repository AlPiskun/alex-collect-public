#!/usr/bin/env python3
"""The quote: its sums, its file, its PDF, its order - and the panel itself.

A quote is the one thing in Alex Collect a customer sees, so the checks are
about what a customer would notice: a total that adds up, a discount that
cannot go below zero, a page with the shop's own logo and colour on it, the
right cards on the order, and a price that moved since the quote was written
being said out loud rather than hidden.

No network and no real Tk: the site is a fake opener, and the panel is driven
through the stubs in test-photo-panel.py, which replaces Tk before gui.py is
imported.
"""
import importlib.util
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]

_spec = importlib.util.spec_from_file_location("photo_panel",
                                              APP / "test-photo-panel.py")
photo_panel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(photo_panel)

from PIL import Image                                     # noqa: E402

import gui                                                # noqa: E402
import quote as quote_model                               # noqa: E402
import quote_pdf                                          # noqa: E402

FakeWidget = photo_panel.FakeWidget
FakeVar = photo_panel.FakeVar
BOX = photo_panel._BOX

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


def sample(today=None):
    """A quote with three cards, the shape the panel builds."""
    q = quote_model.new_quote(number="Q-2026-0001", company="Piskun Cards",
                              currency="C$",
                              today=today or date(2026, 10, 30))
    q["customer"] = {"name": "Dana Whitfield", "email": "dana@example.com",
                     "phone": "(519) 555-0142",
                     "address": "18 Maple Row\nOrangeville, ON L9W 2C3"}
    q["notes"] = "Prices in Canadian dollars. Shipping is extra."
    for index, (name, price) in enumerate((
            ("1989 O-Pee-Chee Batman #1 NM 7", "4.00"),
            ("1989 O-Pee-Chee Batman #2 EX-MT 6", "5.50"),
            ("1989 O-Pee-Chee Batman #3 EX", "")), 1):
        quote_model.add_item(q, {"id": 100 + index, "name": name,
                                 "sku": "BAT-%02d" % index, "price": price})
    return q


# ---------------------------------------------------------------- 1. sums
def test_sums():
    print()
    print("== 1. what the customer would add up ==")
    q = sample()
    sums = quote_model.totals(q)
    check("the subtotal adds every card", sums["subtotal"] == 9.5, sums)
    check("the count is cards and items",
          sums["lines"] == 3 and sums["units"] == 3, sums)
    check("a card with no price is counted apart, not as zero",
          sums["unpriced"] == 1 and sums["subtotal"] == 9.5, sums)
    check("no discount means the total is the subtotal",
          sums["discount"] == 0 and sums["total"] == 9.5, sums)

    q["discount"] = {"kind": "percent", "value": 10}
    sums = quote_model.totals(q)
    check("a percentage comes off the subtotal", sums["discount"] == 0.95,
          sums)
    check("and the label says which discount it was",
          sums["discount_label"] == "Discount 10%", sums)
    check("the total is subtotal less the discount", sums["total"] == 8.55,
          sums)

    q["discount"] = {"kind": "amount", "value": 2.5}
    sums = quote_model.totals(q)
    check("a flat amount comes off as it is", sums["discount"] == 2.5, sums)
    check("and the label is just a discount",
          sums["discount_label"] == "Discount", sums)

    q["discount"] = {"kind": "amount", "value": 500}
    sums = quote_model.totals(q)
    check("a discount bigger than the quote never goes below zero",
          sums["total"] == 0 and sums["discount"] == 9.5, sums)

    q["discount"] = {"kind": "percent", "value": 150}
    sums = quote_model.totals(q)
    check("a percentage over 100 is capped", sums["total"] == 0, sums)

    q["discount"] = {"kind": "percent", "value": "not a number"}
    check("a discount that is not a number is no discount",
          quote_model.totals(q)["discount"] == 0, q["discount"])

    q = sample()
    quote_model.set_quantity(q, 0, 3)
    sums = quote_model.totals(q)
    check("three of one card multiplies its line",
          quote_model.line_total(q["items"][0]) == 12.0, q["items"][0])
    check("and counts as three items, one card",
          sums["lines"] == 3 and sums["units"] == 5, sums)
    quote_model.set_quantity(q, 0, 0)
    check("a quantity is never zero - the line would vanish",
          quote_model.item_quantity(q["items"][0]) == 1, q["items"][0])

    check("money is written with the shop's prefix",
          quote_model.money(12.5, "C$") == "C$12.50", quote_model.money(12.5))
    check("a missing price is not written as money",
          quote_model.money(None) == "-", quote_model.money(None))
    check("a price typed with a dollar sign is read",
          quote_model.parse_money(" $1,204.50 ") == 1204.5, "")
    check("an empty box is not a price",
          quote_model.parse_money("") is None, "")
    check("a negative price is refused",
          quote_model.parse_money("-5") is None, "")


# --------------------------------------------------------------- 2. cards
def test_cards():
    print()
    print("== 2. adding a batch of cards at once ==")
    products = [{"id": 1, "name": "1989 O-Pee-Chee Batman #1", "sku": "B1",
                 "price": "4.00"},
                {"id": 2, "name": "1989 O-Pee-Chee Batman #2", "sku": "B2",
                 "price": "5.00"},
                {"id": 3, "name": "1989 O-Pee-Chee Batman #3", "sku": "B3",
                 "price": ""}]
    q = quote_model.new_quote(currency="C$")
    added, already = quote_model.add_items(q, products, skip_existing=True)
    check("every match goes on in one press", added == 3 and already == 0,
          (added, already))
    check("each card is one row", len(q["items"]) == 3, q["items"])
    check("a card with no price on the site arrives with no price",
          q["items"][2]["price"] == "", q["items"][2])
    added, already = quote_model.add_items(q, products, skip_existing=True)
    check("pressing it again does not double the quote",
          added == 0 and already == 3 and len(q["items"]) == 3, (added,
                                                                 already))
    quote_model.add_item(q, products[0])
    check("adding one card by itself raises its quantity instead of a second "
          "row", len(q["items"]) == 3 and q["items"][0]["quantity"] == 2,
          q["items"][0])

    q = quote_model.new_quote()
    quote_model.add_item(q, {"name": "Typed in by hand", "price": "12"})
    check("a card typed in by hand has no product id",
          q["items"][0]["product_id"] == 0, q["items"][0])
    quote_model.add_item(q, {"name": "Another typed card", "price": ""})
    check("a typed card with no price keeps no price",
          q["items"][1]["price"] == "", q["items"][1])
    try:
        quote_model.add_item(q, {"name": "   "})
        check("a card with no name is refused", False, "no error")
    except quote_model.QuoteError:
        check("a card with no name is refused", True)

    #  The search only ever offers what can be sold, and the list can be put
    #  in the order the person asked for.
    shelf = [{"id": 1, "name": "Batman #1", "price": "4.00",
              "stock_status": "instock"},
             {"id": 2, "name": "Batman #2", "price": "5.50",
              "stock_status": "instock"},
             {"id": 3, "name": "Batman #3", "price": "7.00",
              "stock_status": "outofstock"},
             {"id": 4, "name": "Batman #4", "price": "9.00",
              "stock_status": "onbackorder"},
             {"id": 5, "name": "Batman #5", "price": ""}]
    on_shelf = quote_model.in_stock(shelf)
    check("only the cards the shop says are in stock are offered",
          [row["id"] for row in on_shelf] == [1, 2], on_shelf)
    check("a card that does not say whether it is in stock is not guessed at",
          5 not in [row["id"] for row in on_shelf], on_shelf)
    check("sorting by name orders the same cards A to Z",
          [row["name"] for row in
           quote_model.sort_products(shelf, "name")] ==
          ["Batman #1", "Batman #2", "Batman #3", "Batman #4", "Batman #5"],
          [row["name"] for row in quote_model.sort_products(shelf, "name")])
    cheapest = quote_model.sort_products(shelf, "price")
    check("cheapest first puts the prices in order and the unpriced card last",
          [row["id"] for row in cheapest] == [1, 2, 3, 4, 5],
          [(row["id"], row["price"]) for row in cheapest])
    dearest = quote_model.sort_products(shelf, "price_desc")
    check("dearest first is the same list the other way round",
          [row["id"] for row in dearest] == [4, 3, 2, 1, 5],
          [(row["id"], row["price"]) for row in dearest])
    newest = quote_model.sort_products(shelf, "newest")
    check("newest first is the last card the site made",
          [row["id"] for row in newest] == [5, 4, 3, 2, 1], newest)
    check("two cards at the same price fall back to their names",
          [row["name"] for row in quote_model.sort_products(
              [{"name": "B", "price": "5"}, {"name": "A", "price": "5"}],
              "price")] == ["A", "B"])
    check("a stored sort the chooser does not know falls back to the name",
          quote_model.sort_key_for("Cheapest, somehow") == "name"
          and quote_model.sort_label_for("nonsense") == "Name (A to Z)",
          (quote_model.sort_key_for("Cheapest, somehow"),
           quote_model.sort_label_for("nonsense")))
    check("and every sort the chooser offers has a label",
          [key for key, _text in quote_model.SORTS] ==
          ["name", "price", "price_desc", "newest"], quote_model.SORTS)

    removed = quote_model.remove_item(q, 0)
    check("a row can be taken off", removed["name"] == "Typed in by hand"
          and len(q["items"]) == 1, q)
    try:
        quote_model.remove_item(q, 9)
        check("removing a row that is gone says so", False, "no error")
    except quote_model.QuoteError:
        check("removing a row that is gone says so", True)


# ---------------------------------------------------------------- 3. file
def test_files(root):
    print()
    print("== 3. the quote is a file that can be opened next week ==")
    folder = root / "quotes"
    first = quote_model.save(sample(), folder)
    check("the file is named after the quote number",
          first.name == "Q-2026-0001.json", first.name)
    check("saving makes the folder", folder.is_dir())
    again = quote_model.save(sample(), folder)
    check("saving the same quote twice replaces its file, not a second one",
          again == first and len(list(folder.glob("*.json"))) == 1,
          [p.name for p in folder.glob("*.json")])
    other = sample(today=date(2026, 10, 31))
    other["number"] = ""
    second = quote_model.save(other, folder)
    check("the next quote gets the next number, in the same year",
          second.name == "Q-2026-0002.json", second.name)

    loaded = quote_model.load(first)
    check("what is read back is what was written",
          loaded["customer"]["name"] == "Dana Whitfield"
          and len(loaded["items"]) == 3, loaded["customer"])
    check("and the number comes back with it",
          loaded["number"] == "Q-2026-0001", loaded["number"])
    check("the quote is dated and held for a fortnight",
          loaded["issued"] == "2026-10-30" and
          loaded["valid_until"] == "2026-11-13", loaded["valid_until"])

    rows = quote_model.list_quotes(folder)
    check("the folder lists the quotes, newest first",
          [row["number"] for row in rows] == ["Q-2026-0002", "Q-2026-0001"],
          [row["number"] for row in rows])
    check("and shows the customer and the total",
          rows[1]["customer"] == "Dana Whitfield" and rows[1]["total"] == 9.5,
          rows[1])

    #  A quote file is a JSON file in the user's folder: it can be edited,
    #  truncated, or written by an older version.
    odd = folder / "Q-2026-0009.json"
    odd.write_text(json.dumps({"number": "Q-2026-0009",
                               "items": [{"name": "A card", "quantity": "2"},
                                         {"no_name": True}, "rubbish"]}),
                   encoding="utf-8")
    repaired = quote_model.load(odd)
    check("a hand-edited quote is repaired, not a traceback",
          len(repaired["items"]) == 1 and repaired["items"][0]["quantity"] == 2,
          repaired["items"])
    check("and the parts it never had are filled in",
          repaired["customer"] == {"name": "", "email": "", "phone": "",
                                   "address": ""}, repaired["customer"])
    broken = folder / "Q-2026-0010.json"
    broken.write_text("{ this is not json", encoding="utf-8")
    try:
        quote_model.load(broken)
        check("a corrupted file says so instead of crashing", False, "no error")
    except quote_model.QuoteError as error:
        check("a corrupted file says so instead of crashing",
              "not readable JSON" in error.message, error.message)
    listed = quote_model.list_quotes(folder)
    check("and it is still listed, as broken",
          any(row["broken"] and row["number"] == "Q-2026-0010"
              for row in listed), listed[:3])

    check("the next number does not reuse a deleted one",
          quote_model.next_number(folder) == "Q-2026-0011",
          quote_model.next_number(folder))
    check("and it starts at one in a fresh folder",
          quote_model.next_number(root / "empty") == "Q-%d-0001"
          % date.today().year, quote_model.next_number(root / "empty"))

    #  The search box on the Print an order panel reads this folder when no
    #  website can be asked: a quote carries the customer and every card name.
    #  Both saved quotes are the same sample, so both answer - which is the
    #  point of a search: it lists the matches, it does not pick one.
    found = quote_model.find_saved(folder, "whitfield")
    check("a saved quote is found by the customer's name",
          [row["number"] for row in found] == ["Q-2026-0002", "Q-2026-0001"],
          [row["number"] for row in found])
    check("and by a card's name, in any order the words are typed",
          [row["number"] for row in
           quote_model.find_saved(folder, "batman 1")] ==
          ["Q-2026-0002", "Q-2026-0001"],
          quote_model.find_saved(folder, "batman 1"))
    check("and by its number, with or without the Q-",
          [row["number"] for row in
           quote_model.find_saved(folder, "2026 0002")] == ["Q-2026-0002"],
          quote_model.find_saved(folder, "2026 0002"))
    check("every match says why it is there",
          found[0]["why"] == ["the customer"], found[0]["why"])
    check("a card match names the card on the quote",
          any(why.startswith("a card: 1989 O-Pee-Chee Batman")
              for why in quote_model.find_saved(folder, "batman")[0]["why"]),
          quote_model.find_saved(folder, "batman")[0]["why"])
    check("a search that matches nothing answers with nothing",
          quote_model.find_saved(folder, "zzz") == [])
    try:
        quote_model.find_saved(folder, "  ")
        blank_error = ""
    except quote_model.QuoteError as error:
        blank_error = error.message
    check("and a blank search is asked for again, not answered",
          "Type a quote number" in blank_error, blank_error or "no error")

    check("the quote as text holds every card and the total",
          all(word in quote_model.as_text(loaded)
              for word in ("Dana Whitfield", "Batman #1", "TOTAL",
                           "C$9.50")), quote_model.as_text(loaded))


# --------------------------------------- 7. pictures and links on the page
def test_pictures_and_links(root):
    print()
    print("== 7. the cards' pictures, and a name that opens the card ==")
    picture = root / "card.png"
    Image.new("RGB", (250, 350), (12, 200, 12)).save(picture)

    quote = quote_model.new_quote()
    quote_model.add_item(quote, {
        "id": 501, "name": "Batman #1", "price": "4.00",
        "images": [{"src": "https://shop.example/b.jpg"}],
        "permalink": "https://shop.example/product/batman-1/"})
    quote_model.add_item(quote, {"id": 502, "name": "Batman #2",
                                 "price": "5.00"})
    kept = quote_model.normalise(quote)
    check("a card on a quote keeps its picture",
          kept["items"][0]["image"] == "https://shop.example/b.jpg",
          kept["items"][0])
    check("and its page on the website, so the printed name can be a link",
          kept["items"][0]["url"] ==
          "https://shop.example/product/batman-1/", kept["items"][0])
    check("a card with no picture or page keeps neither",
          kept["items"][1]["image"] == "" and kept["items"][1]["url"] == "",
          kept["items"][1])

    folder = root / "linked-quotes"
    written = quote_model.save(quote, folder)
    back = quote_model.load(written)
    check("and both survive being saved and opened next week",
          back["items"][0]["image"] == "https://shop.example/b.jpg"
          and back["items"][0]["url"] ==
          "https://shop.example/product/batman-1/", back["items"][0])

    def fake_get(site, path, params=None, key=None, secret=None, **kwargs):
        return 200, [{"id": 7, "name": "Batman #1", "price": "4.00",
                      "stock_status": "instock",
                      "images": [{"src": "https://shop.example/b.jpg"}],
                      "permalink": "https://shop.example/?p=7"}]

    found = quote_model.search(fake_get, "s", "k", "s", "batman")
    check("a card found on the shop carries its page as well as its picture",
          found and found[0]["image"] == "https://shop.example/b.jpg"
          and found[0]["url"] == "https://shop.example/?p=7", found)

    counts = {}
    links = {}
    images = {"https://shop.example/b.jpg": picture}
    pages = quote_pdf.build_pages(quote, dpi=100, images=images,
                                  links=links, counts=counts)
    check("every card with a picture is drawn, and the rest are counted",
          counts.get("pictures") == 1 and counts.get("missing") == 1, counts)

    #  The picture column, scanned for the colour of the test card.
    margin = quote_pdf.Page(100).margin
    width, _height = quote_pdf.picture_box(quote_pdf.Page(100))
    drawn = any(
        pages[0].getpixel((x, y)) == (12, 200, 12)
        for x in range(margin, margin + width + 1, 2)
        for y in range(0, pages[0].height, 4))
    check("the picture is printed in the card's own column", drawn, "")

    info = quote_pdf.render(quote, root / "linked.pdf", dpi=100, images=images)
    printed = quote_pdf.pdf_writer.read_links(info["path"])
    check("the PDF is written with a link, not only a picture",
          info["path"].is_file() and printed ==
          ["https://shop.example/product/batman-1/"], printed)
    check("a card without a page prints without a link, not a dead one",
          len(printed) == 1 and len(links.get(0) or []) == 1, links)
    check("a picture that could not be fetched is counted, not fatal",
          info.get("missing") == 1 and info["pages"] == 1, info)

    #  The link sits over the card's name: right of the picture, left of the
    #  quantity, so clicking a price never opens a product page.
    page_size = quote_pdf.Page(100)
    x0, y0, x1, y1, url = (links.get(0) or [(0, 0, 0, 0, "")])[0]
    check("the link is over the name and nothing else",
          x0 >= quote_pdf.card_column(page_size)
          and x1 <= quote_pdf._columns(page_size)["quantity"]
          and y1 > y0, (x0, y0, x1, y1))

    #  A long quote: the links have to follow their cards onto every page.
    many = sample()
    for index in range(1, 41):
        quote_model.add_item(many, {
            "id": 900 + index, "name": "Linked Card #%d" % index,
            "price": "1.00", "permalink":
            "https://shop.example/p/%d/" % index})
    many_info = quote_pdf.render(many, root / "linked-long.pdf", dpi=100)
    many_links = quote_pdf.pdf_writer.read_links(many_info["path"])
    check("every card's name is a link, across pages",
          many_info["pages"] >= 2 and len(many_links) == 40
          and many_links[0].endswith("/p/1/")
          and many_links[-1].endswith("/p/40/"),
          (many_info["pages"], len(many_links), many_links[-1:]))


# ------------------------------------------------------------- 4. address
def test_address():
    print()
    print("== 4. the customer's address becomes the order's fields ==")
    one = quote_model.split_address("12 Main St\nToronto, ON  M5V 2T6")
    check("the street, city, province and postal code are separated",
          one["address_1"] == "12 Main St" and one["city"] == "Toronto"
          and one["state"] == "ON" and one["postcode"] == "M5V 2T6", one)
    two = quote_model.split_address(
        "Jane's Cards\n12 Main St\nToronto, ON M5V2T6")
    check("a business name on the first line is kept, not dropped",
          two["address_1"] == "Jane's Cards" and two["address_2"] == "12 Main St",
          two)
    three = quote_model.split_address("18 Maple Row\nOrangeville, Ontario")
    check("a province written out is understood",
          three["city"] == "Orangeville" and three["state"] == "ON", three)
    four = quote_model.split_address("Just one line")
    check("a single line with no city in it is a street",
          four["address_1"] == "Just one line" and four["city"] == "", four)
    check("no address is no fields, not a crash",
          quote_model.split_address("")["address_1"] == "", "")
    check("the country is Canada unless told otherwise",
          quote_model.split_address("x")["country"] == "CA", "")

    billing = quote_model.billing_payload(sample())
    check("the order's billing block carries the customer",
          billing["first_name"] == "Dana" and billing["last_name"] == "Whitfield"
          and billing["email"] == "dana@example.com"
          and billing["city"] == "Orangeville"
          and billing["postcode"] == "L9W 2C3", billing)
    check("and an empty customer is not invented",
          quote_model.billing_payload(quote_model.new_quote()) == {},
          quote_model.billing_payload(quote_model.new_quote()))
    check("one word is a first name, not half a name",
          quote_model.split_name("Cher") == ("Cher", ""), "")


# --------------------------------------------------------------- 5. order
class FakeOrderApi:
    """The order endpoint: records what was sent, answers what was asked."""

    def __init__(self, total=None, fail=None):
        self.sent = []
        self.total = total
        self.fail = fail

    def __call__(self, site, key, secret, path, method="GET", params=None,
                 payload=None, timeout=60, **kwargs):
        import woo_orders
        if self.fail:
            raise woo_orders.OrderError(self.fail)
        self.sent.append({"site": site, "path": path, "method": method,
                          "payload": payload})
        if method == "GET":
            #  Reading an order back for its sheet: the website's own facts,
            #  which is what the sheet prints instead of the quote's guesses.
            return 200, {"id": 4321, "number": "4321", "status": "pending",
                         "currency": "CAD", "total": "29.97",
                         "date_created": "2026-10-30T12:00:00",
                         "date_paid": None, "discount_total": "3.33",
                         "shipping_total": "0.00", "prices_include_tax": True,
                         "fee_lines": [{"name": "Discount 10%",
                                        "total": "-3.33"}],
                         "billing": {"first_name": "Dana",
                                     "last_name": "Whitfield",
                                     "email": "dana@example.com",
                                     "phone": "(519) 555-0142",
                                     "address_1": "18 Maple Row",
                                     "city": "Orangeville", "state": "ON",
                                     "postcode": "L9W 2C3", "country": "CA"},
                         "line_items": [{"name": "1989 O-Pee-Chee Batman #1 "
                                                 "NM 7", "product_id": 501,
                                         "quantity": 1, "price": 4.0,
                                         "total": "4.00", "sku": "BAT-01",
                                         "image": {"src":
                                                   "https://shop.example/"
                                                   "card-501.jpg"}}]}
        line_items = payload.get("line_items") or []
        total = self.total
        if total is None:
            total = "0"
        return 200, {"id": 4321, "number": "4321", "total": total,
                     "line_items": line_items,
                     "status": payload.get("status")}


def test_order():
    print()
    print("== 5. the quote becomes an order, and the price is checked ==")
    q = sample()
    q["discount"] = {"kind": "percent", "value": 10}
    payload = quote_model.order_payload(q)
    check("the order is pending, so nothing is charged or emailed",
          payload["status"] == "pending" and payload["set_paid"] is False,
          payload)
    check("only the cards that came from the shop are ordered",
          [row["product_id"] for row in payload["line_items"]]
          == [101, 102, 103], payload["line_items"])
    check("the prices on the quote are not sent - the shop prices the line",
          all(set(row) == {"product_id", "quantity"}
              for row in payload["line_items"]), payload["line_items"])
    check("the discount is one fee line, negative",
          payload["fee_lines"] == [{"name": "Discount 10%",
                                    "total": "-0.95"}], payload.get("fee_lines"))
    check("the quote number rides along on the order",
          payload["meta_data"] == [{"key": "_alex_quote",
                                    "value": "Q-2026-0001"}],
          payload["meta_data"])
    check("and the note says which quote it came from",
          "Q-2026-0001" in payload["customer_note"]
          and "2026-11-13" in payload["customer_note"],
          payload["customer_note"])

    q_without_discount = sample()
    check("no discount means no fee line at all",
          "fee_lines" not in quote_model.order_payload(q_without_discount), "")

    hand = quote_model.new_quote()
    quote_model.add_item(hand, {"name": "Typed card", "price": "5"})
    try:
        quote_model.order_payload(hand)
        check("a quote with no shop cards cannot be ordered", False, "no error")
    except quote_model.QuoteError as error:
        check("a quote with no shop cards cannot be ordered",
              "nothing for an order" in error.message, error.message)

    api = FakeOrderApi(total="8.55")
    result = quote_model.create_order(q, "https://shop.example", "ck", "cs",
                                      api=api)
    check("it is created with the quote's cards and discount",
          len(api.sent) == 1 and api.sent[0]["payload"]["fee_lines"],
          api.sent)
    check("the order number comes back",
          result["number"] == "4321" and result["id"] == 4321, result)
    check("a total that matches the quote is not questioned",
          result["difference"] is None and result["note"] == "", result)

    api = FakeOrderApi(total="9.50")
    result = quote_model.create_order(q, "https://shop.example", "ck", "cs",
                                      api=api)
    check("a price that moved is named, not hidden",
          result["difference"] == 0.95 and "price changed" in result["note"],
          result)
    check("the note says both numbers",
          "9.50" in result["note"] and "8.55" in result["note"], result["note"])

    api = FakeOrderApi(fail="the site refused (HTTP 401).")
    try:
        quote_model.create_order(q, "https://shop.example", "ck", "cs", api=api)
        check("a refused order is reported as the site's words", False, "")
    except quote_model.QuoteError as error:
        check("a refused order is reported as the site's words",
              "refused" in error.message, error.message)

    try:
        quote_model.create_order(q, "", "", "")
        check("an order without keys says what is missing", False, "no error")
    except quote_model.QuoteError as error:
        check("an order without keys says what is missing",
              "keys" in error.message and "printed" in error.hint,
              error.message)

    marked = quote_model.mark_ordered(q, result)
    check("the quote records the order it became",
          marked["status"] == "ordered" and marked["order_number"] == "4321",
          marked)


# ----------------------------------------------------------------- 6. PDF
def test_pdf(root):
    print()
    print("== 6. the printed page ==")
    logo_path = root / "logo.png"
    logo = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
    for x in range(300):
        for y in range(120):
            logo.putpixel((x, y), (198, 40, 40, 255) if x < 280 else
                          (255, 255, 255, 0))
    logo.save(logo_path)

    q = sample()
    q["look"].update({"logo": str(logo_path), "color": "#C62828",
                      "contact": "store.piskun.ca"})
    info = quote_pdf.render(q, root / "quote.pdf", dpi=110)
    check("a PDF is written", info["path"].is_file() and
          info["path"].stat().st_size > 5000, info)
    check("the logo was used", info["logo"] is True, info)
    check("a short quote is one page", info["pages"] == 1, info)

    pages = quote_pdf.build_pages(q, dpi=110)
    top = pages[0].getpixel((40, 40))
    check("the band is printed in the colour that was chosen",
          top[0] > 150 and top[1] < 90 and top[2] < 90, top)
    #  A shop's logo is often the same colour as the band. The plate behind it
    #  is what keeps such a logo from disappearing into the page: just inside
    #  the plate's left edge the paper is white, where without a logo it is
    #  the band's colour.
    margin_px = int(round(quote_pdf.MARGIN * 110))
    band_middle = int(round(0.05 * quote_pdf.PAGE_INCHES[1] * 110))
    with_logo = pages[0].getpixel((margin_px - 2, band_middle))
    bare = sample()
    bare["look"].update({"color": "#C62828"})
    without = quote_pdf.build_pages(bare, dpi=110)[0].getpixel(
        (margin_px - 2, band_middle))
    check("the logo sits on a light plate, so a dark logo still shows",
          min(with_logo) > 230 and without == (198, 40, 40),
          (with_logo, without))

    dark = sample()
    dark["look"].update({"color": "#111111"})
    page = quote_pdf.build_pages(dark, dpi=110)[0]
    check("white text is chosen on a dark colour",
          quote_pdf.text_on((17, 17, 17)) == quote_pdf.WHITE, "")
    check("and dark text on a light one",
          quote_pdf.text_on((250, 230, 120)) == quote_pdf.INK, "")
    check("a yellow quote prints, with readable headings",
          page is not None, "")
    check("a colour typed wrongly prints in the default colour instead",
          quote_pdf.parse_colour("#nonsense") == (31, 78, 121), "")
    check("a three-digit colour is understood",
          quote_pdf.parse_colour("#c33") == (204, 51, 51), "")
    check("a colour with no hash is understood",
          quote_pdf.parse_colour("1F4E79") == (31, 78, 121), "")

    long_quote = sample()
    for index in range(4, 40):
        quote_model.add_item(long_quote, {
            "id": 100 + index, "sku": "BAT-%02d" % index,
            "name": "1989 O-Pee-Chee Batman #%d EX-MT 6" % index,
            "price": "4.00"})
    long_info = quote_pdf.render(long_quote, root / "long.pdf", dpi=110)
    check("a quote too long for one page continues onto another",
          long_info["pages"] >= 2, long_info)
    long_pages = quote_pdf.build_pages(long_quote, dpi=110)
    check("the later pages repeat the column headings",
          any(long_pages[1].getpixel((x, 200))[0] < 250
              for x in range(200, 260)), "")

    missing_logo = sample()
    missing_logo["look"]["logo"] = str(root / "not-here.png")
    info = quote_pdf.render(missing_logo, root / "nologo.pdf", dpi=110)
    check("a logo file that is not there does not stop the quote",
          info["logo"] is False and info["path"].is_file(), info)

    empty = quote_model.new_quote()
    info = quote_pdf.render(empty, root / "empty.pdf", dpi=110)
    check("a quote with no cards still prints, saying so",
          info["pages"] == 1 and info["path"].is_file(), info)

    check("a page is A4", quote_pdf.build_pages(sample(), dpi=100)[0].size
          == (827, 1169), quote_pdf.build_pages(sample(), dpi=100)[0].size)

    #  A letterhead longer than the band holds used to print its last line
    #  half on the white page under the colour.
    check("a long letterhead is cut down to the lines that fit",
          quote_pdf.contact_lines("18 Maple Row\nOrangeville, ON\n"
                                  "L9W 2C3\npiskuncards.ca", 2) ==
          ["18 Maple Row",
           "Orangeville, ON \u00b7 L9W 2C3 \u00b7 piskuncards.ca"],
          quote_pdf.contact_lines("18 Maple Row\nOrangeville, ON\n"
                                  "L9W 2C3\npiskuncards.ca", 2))
    check("and a letterhead that fits is left exactly as it was typed",
          quote_pdf.contact_lines("18 Maple Row\npiskuncards.ca", 3) ==
          ["18 Maple Row", "piskuncards.ca"])
    check("with no room at all, nothing is drawn",
          quote_pdf.contact_lines("anything", 0) == [])
    tall = sample()
    tall["look"]["contact"] = ("18 Maple Row\nOrangeville, ON L9W 2C3\n"
                               "piskuncards.ca")
    tall_page = quote_pdf.build_pages(tall, dpi=100)[0]
    edge = int(round(quote_pdf.BAND * 100))
    #  Row ``edge`` is the band's own last row; the ink that used to spill was
    #  in the white rows under it, before the parties block starts.
    below = {tall_page.getpixel((x, y)) for y in range(edge + 1, edge + 6)
             for x in range(30, 700)}
    check("no line of it is drawn on the white page under the band",
          below == {quote_pdf.WHITE}, sorted(below)[:4])


# --------------------------------------------------------------- 7. panel
class FakeApp:
    def __init__(self, folder, settings=None):
        self.body = FakeWidget()
        self._mode_frame = None
        self.settings = {"browser_name": "system", "scan_dir": str(folder),
                         "pipeline_dir": str(folder),
                         "woo_site_url": "https://shop.example",
                         "currency_prefix": "C$",
                         "quotes_dir": str(folder / "quotes"),
                         "quote_company": "", "quote_color": "#1F4E79",
                         "quote_contact": "", "quote_logo": "",
                         "canadianshopper_store_url": "", "ebay_selling_url": "",
                         "facebook_selling_url": ""}
        self.settings.update(settings or {})
        self.cs_addon = True
        self.opened, self.lines, self.clipboard = [], [], ""

    def open_webpages(self, urls, new_window=False):
        self.opened.extend(urls)
        return "Test browser"

    def console_line(self, text, tag=""):
        self.lines.append((tag, str(text)))

    def _save_user_settings_callback(self):
        """The window's own save; here it keeps the dict and writes no file."""
        return None

    def after(self, delay, callback=None):
        if callback is not None:
            callback()
        return "after-id"

    def wait_window(self, window):
        window.wait_window()

    def update(self):
        pass

    def update_idletasks(self):
        pass

    def clipboard_clear(self):
        self.clipboard = ""

    def clipboard_append(self, text):
        self.clipboard += str(text)

    def show_panel(self, panel_id):
        pass

    def clear_action_bar(self):
        bar = getattr(self, "_action_bar", None)
        if bar is not None:
            bar.destroy()
        self._action_bar = None

    def winfo_screenwidth(self):
        return 1400

    def winfo_screenheight(self):
        return 900

    def winfo_rootx(self):
        return 0

    def winfo_rooty(self):
        return 0

    def winfo_width(self):
        return 1200

    def winfo_height(self):
        return 800


CATALOG = [
    {"id": 501, "name": "1989 O-Pee-Chee Batman #1 NM 7", "sku": "BAT-01",
     "price": "4.00", "stock_status": "instock", "stock_quantity": 1,
     "images": [{"src": "https://shop.example/card-501.jpg"}]},
    {"id": 502, "name": "1989 O-Pee-Chee Batman #2 EX-MT 6", "sku": "BAT-02",
     "price": "5.50", "stock_status": "instock", "stock_quantity": 1,
     "images": [{"src": "https://shop.example/card-502.jpg"}]},
    {"id": 503, "name": "1989 O-Pee-Chee Batman #3 EX 5", "sku": "BAT-03",
     "price": "7.00", "stock_status": "outofstock", "stock_quantity": 0,
     "images": [{"src": "https://shop.example/card-503.jpg"}]},
    #  A card the "Batman" search does not return by name, so it stands for
    #  something the user only knows how to describe when they type it in.
    {"id": 504, "name": "1988 O-Pee-Chee Mario Lemieux #40 NM", "sku": "MAR-40",
     "price": "9.00", "stock_status": "instock", "stock_quantity": 1},
]
SEARCHED = CATALOG


class TextBox(FakeWidget):
    """A Text widget that keeps what is written in it, like Tk's does."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.content = ""

    def delete(self, *args, **kwargs):
        self.content = ""

    def insert(self, index, text, *args, **kwargs):
        if str(index).startswith("end") or str(index) == "insert":
            self.content += str(text)
        else:
            self.content = str(text) + self.content

    def get(self, *args, **kwargs):
        return self.content


class SyncThread:
    """The panel hands its network work to a thread; here it runs at once."""

    def __init__(self, target=None, daemon=None, **kwargs):
        self.target = target

    def start(self):
        self.target()


def build(app):
    """The panel's widgets, plus the ones a person would type into."""
    gui.tk.Text = TextBox
    parent = FakeWidget()
    gui.build_quote(parent, app)
    widgets = list(parent.walk())
    buttons = {}
    for widget in widgets:
        text = str(widget._kw.get("text") or "")
        if text and widget._kw.get("command") is not None:
            buttons.setdefault(text, widget)
    areas = {}
    for widget in widgets:
        title = str(widget._kw.get("text") or "")
        if isinstance(widget, gui.ttk.LabelFrame):
            areas[title.split(".")[0]] = widget
    parts = {"parent": parent, "widgets": widgets, "buttons": buttons,
             "areas": areas}
    parts["results"] = next(w for w in widgets if w._kw.get("height") == 6)
    parts["rows"] = next(w for w in widgets if w._kw.get("height") == 8)
    parts["search"] = next(w for w in widgets
                           if w._kw.get("width") == 34)._kw["textvariable"]
    who = areas["3"]
    parts["entries"] = [w._kw["textvariable"] for w in who.walk()
                        if w._kw.get("textvariable") is not None]
    parts["texts"] = [w for w in who.walk() if isinstance(w, TextBox)]
    parts["discount"] = next(w for w in who.walk()
                             if w._kw.get("values") == ["", "Percent",
                                                        "Amount"])
    parts["discount_value"] = next(
        w for w in parts["discount"].master.walk()
        if w is not parts["discount"] and w._kw.get("width") == 8
        and w._kw.get("textvariable") is not None)._kw["textvariable"]
    look = areas["4"]
    parts["company"] = next(w for w in look.walk()
                            if w._kw.get("width") == 24)._kw["textvariable"]
    parts["colour"] = next(w for w in look.walk()
                           if w._kw.get("width") == 10)._kw["textvariable"]
    parts["logo"] = next(w for w in look.walk()
                         if w._kw.get("width") == 44)._kw["textvariable"]
    parts["contact"] = [w for w in look.walk() if isinstance(w, TextBox)][0]
    parts["result_label"] = next(
        w for w in widgets if isinstance(w, gui.ttk.Label)
        and str(w._kw.get("text") or "").startswith("Search for a player"))
    sort_labels = [label for _key, label in quote_model.SORTS]
    parts["sort_box"] = next(w for w in widgets
                             if w._kw.get("values") == sort_labels)
    parts["sort"] = parts["sort_box"]._kw["textvariable"]
    parts["totals"] = next(w for w in widgets
                           if "TOTAL" in str(w._kw.get("text") or "")) \
        if any("TOTAL" in str(w._kw.get("text") or "") for w in widgets) else None
    return parts


def test_private_files(root):
    print()
    print("== 12. a quote's file belongs to this account, not the whole PC ==")
    #  A quote carries a name, a street address, an email and a phone number.
    #  The keys file gets the "this Windows account only" treatment; these
    #  documents are the same kind of private and used to be readable by every
    #  account on the machine.
    saved, rendered = [], []
    with patch.object(quote_model, "restrict_file_permissions",
                      lambda path: saved.append(Path(path)) or True), \
            patch.object(quote_pdf, "restrict_file_permissions",
                         lambda path: rendered.append(Path(path)) or True):
        path = quote_model.save(sample(), root / "private-quotes")
        info = quote_pdf.render(sample(), root / "private.pdf", dpi=90)
    check("saving a quote restricts the file it writes", saved == [path],
          str(saved))
    check("printing it restricts the PDF too", rendered == [info["path"]],
          str(rendered))
    check("and the restriction is applied after the file exists",
          path.is_file() and info["path"].is_file(), str(path))

    #  The same call for real, so this is not only a promise about a patch.
    real = quote_model.save(sample(), root / "private-quotes-2")
    real_pdf = quote_pdf.render(sample(), root / "private-2.pdf", dpi=90)
    if os.name == "posix":
        check("the quote file is readable by this account only",
              (real.stat().st_mode & 0o777) == 0o600, oct(real.stat().st_mode))
        check("and so is its PDF",
              (Path(real_pdf["path"]).stat().st_mode & 0o777) == 0o600,
              oct(Path(real_pdf["path"]).stat().st_mode))
    else:
        #  Windows has no mode bits; the ACL itself is checked in
        #  test-user-settings.py, and asserting 0o600 here fails on a real run.
        check("the quote file is on disk", real.is_file(), str(real))


def test_panel(root):
    print()
    print("== 7. the panel a person actually presses ==")
    folder = root / "panel"
    folder.mkdir(parents=True, exist_ok=True)
    app = FakeApp(folder)
    asks, prompts = [], []

    def search(site, path, params=None, key=None, secret=None, **kwargs):
        term = str((params or {}).get("search") or "").lower()
        words = [word for word in term.replace("#", " ").split() if word]
        rows = [row for row in SEARCHED
                if all(word in row["name"].lower() for word in words)] \
            if words else []
        return 200, [dict(row) for row in rows]

    def by_id(site, path, params=None, key=None, secret=None, **kwargs):
        wanted = str((params or {}).get("include") or "")
        ids = {int(part) for part in wanted.split(",") if part.strip()}
        return 200, [dict(row, price="9.99") for row in CATALOG
                     if row["id"] in ids]

    def lookup(site, path, params=None, key=None, secret=None, **kwargs):
        if (params or {}).get("include"):
            return by_id(site, path, params, key, secret, **kwargs)
        return search(site, path, params, key, secret, **kwargs)

    BOX.shown.clear()
    BOX.askyesno = lambda title, *a, **k: asks.append(title) or True
    #  A quote long enough to overrun a message box is confirmed in a window
    #  of its own, so the stand-in has to press the button like a person.
    confirmed = []

    def press_confirm(window):
        confirmed.append(str(getattr(window, "_title", "")))
        for child in window.walk():
            if str(child._kw.get("text") or "") == "Create the order" and \
                    child._kw.get("command"):
                child.invoke()
                return
        window.destroy()

    photo_panel.PICKER["press"] = press_confirm

    def askstring(title, prompt="", **kwargs):
        prompts.append((title, prompt))
        if "card as it should read" in prompt:
            return "1988 O-Pee-Chee Mario Lemieux #40 NM"
        if "Its price" in prompt:
            return "9.00"
        if title == "Quantity":
            return "3"
        if title == "Price":
            return "8.00"
        return ""

    gui.simpledialog.askstring = askstring
    gui.filedialog.askopenfilename = lambda **kwargs: str(root / "logo.png")
    import woo_orders

    api = FakeOrderApi(total="29.97")
    with patch_object(gui.threading, "Thread", SyncThread), \
            patch_object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck",
                                            "cs")), \
            patch_object(gui, "woo_get", lookup), \
            patch_object(woo_orders, "api_request", api):
        parts = build(app)
        buttons = parts["buttons"]
        rows, results = parts["rows"], parts["results"]

        check("the panel offers the buttons a quote needs",
              {"Search the stock", "Add all the matches", "Save the quote",
               "Print the PDF...", "Turn into an order...",
               "Type a card in by hand", "Start a new quote",
               "Open this quote", "Copy it as text",
               "Re-price from the website..."} <= set(buttons),
              sorted(buttons))
        #  The order sheet moved to its own panel: printing a packed order is
        #  an after-the-sale job, and a quote is not an order.
        check("the order sheet is not offered from a quote any more",
              "Save the order as a PDF..." not in buttons, sorted(buttons))
        bare = sorted(text for text, widget in buttons.items()
                      if not getattr(widget, "_alex_tooltip", None))
        check("every button on the panel explains itself on hover",
              not bare, bare)
        for text in ("Search the stock", "Add all the matches",
                     "Add the selected card", "Save the quote",
                     "Print the PDF...", "Turn into an order...",
                     "Copy it as text", "Re-price from the website...",
                     "Remove the selected row", "Change a price...",
                     "Pick a colour...", "Open the quotes folder"):
            check("the button %r explains itself on hover" % text,
                  bool(gui.tip_for(text)), gui.tip_for(text))

        #  -- the search, its sort, and the one-press add
        parts["search"].set("Batman")
        buttons["Search the stock"].invoke()
        check("searching lists every match that is in stock",
              len(results.items) == 2, results.items)
        check("and the out-of-stock card is named as left out, not lost",
              "out of stock" in str(parts["result_label"].cget("text")),
              parts["result_label"].cget("text"))
        check("the matches come back in name order to start with",
              [row.split("  ")[0].strip() for row in results.items] ==
              ["1989 O-Pee-Chee Batman #1 NM 7",
               "1989 O-Pee-Chee Batman #2 EX-MT 6"], results.items)
        parts["sort"].set("Price (high to low)")
        parts["sort_box"].event_generate("<<ComboboxSelected>>")
        check("choosing a sort re-orders the matches already on screen",
              [row.split("  ")[0].strip() for row in results.items] ==
              ["1989 O-Pee-Chee Batman #2 EX-MT 6",
               "1989 O-Pee-Chee Batman #1 NM 7"], results.items)
        check("and sorting does not search the shop again",
              len(results.items) == 2, results.items)
        parts["sort"].set("Name (A to Z)")
        parts["sort_box"].event_generate("<<ComboboxSelected>>")
        check("the list goes back to name order",
              "Batman #1" in str(results.items[0]), results.items)
        buttons["Add all the matches"].invoke()
        check("one press puts one of each in-stock match on the quote",
              len(rows.items) == 2, rows.items)
        buttons["Add all the matches"].invoke()
        check("a second press does not double the quote", len(rows.items) == 2,
              rows.items)
        check("the totals line adds them up",
              "TOTAL C$9.50" in (parts["totals"].cget("text")
                                 if parts["totals"] else ""),
              parts["totals"].cget("text") if parts["totals"] else "")

        #  -- a card typed in by hand
        buttons["Type a card in by hand"].invoke()
        check("a hand-typed card lands on the quote",
              any("Lemieux #40" in item for item in rows.items), rows.items)
        check("and carries the price that was typed",
              any("9.00" in item for item in rows.items), rows.items)
        check("the quote now says three cards",
              "3 cards on the quote" in (parts["totals"].cget("text") or ""),
              parts["totals"].cget("text"))

        #  -- the customer, the discount, the look
        name_var, email_var, phone_var = parts["entries"][0:3]
        name_var.set("Dana Whitfield")
        email_var.set("dana@example.com")
        phone_var.set("(519) 555-0142")
        parts["texts"][0].insert("1.0", "18 Maple Row\nOrangeville, ON "
                                       "L9W 2C3")
        parts["texts"][1].insert("1.0", "Prices in Canadian dollars.")
        parts["discount"]._kw["textvariable"].set("Percent")
        parts["discount_value"].set("10")
        parts["colour"].set("#C62828")
        parts["logo"].set(str(root / "logo.png"))
        parts["company"].set("Piskun Cards")

        #  The order the matches were shown in is kept for the next quote.
        parts["sort"].set("Newest first")
        parts["sort_box"].event_generate("<<ComboboxSelected>>")
        buttons["Save the quote"].invoke()
        quotes = folder / "quotes"
        saved = quotes / ("Q-%d-0001.json" % date.today().year)
        check("saving writes the quote file", saved.is_file(),
              sorted(str(p) for p in quotes.glob("*")))
        data = json.loads(saved.read_text(encoding="utf-8"))
        check("with the customer on it",
              data["customer"]["name"] == "Dana Whitfield", data["customer"])
        check("and the address exactly as it was typed",
              "Orangeville, ON L9W 2C3" in data["customer"]["address"],
              data["customer"]["address"])
        check("and the discount as a percentage",
              data["discount"] == {"kind": "percent", "value": 10.0},
              data["discount"])
        check("and the colour and logo that were chosen",
              data["look"]["color"] == "#C62828"
              and data["look"]["logo"].endswith("logo.png"), data["look"])
        check("the total on the screen is the discounted one",
              "TOTAL C$16.65" in (parts["totals"].cget("text") or ""),
              parts["totals"].cget("text"))
        check("the sort that was chosen is remembered for the next quote",
              app.settings.get("quote_sort") == "newest",
              app.settings.get("quote_sort"))

        opened = []
        with patch_object(gui, "open_path",
                          lambda path: opened.append(str(path)) or True):
            buttons["Print the PDF..."].invoke()
        pdf = quotes / ("%s.pdf" % data["number"])
        check("printing writes the PDF next to the quote", pdf.is_file(), pdf)
        check("and opens it, so it can be checked before it is sent",
              str(pdf) in opened, opened)

        buttons["Copy it as text"].invoke()
        check("the quote can be copied out whole",
              "Dana Whitfield" in app.clipboard and "TOTAL" in app.clipboard,
              app.clipboard[:120])

        #  -- re-pricing
        asks.clear()
        buttons["Re-price from the website..."].invoke()
        check("re-pricing asks before changing a price the customer was told",
              any("Prices have moved" in title for title in asks), asks)
        check("and takes the website's price when it is told to",
              any("9.99" in item for item in rows.items), rows.items)

        #  -- the order
        asks.clear()
        confirmed.clear()
        buttons["Turn into an order..."].invoke()
        check("the order is confirmed first, with every card shown",
              any("Turn the quote into an order" in title for title in asks)
              or any("Turn the quote into an order" in title
                     for title in confirmed), (asks, confirmed))
        check("the hand-typed card is matched to the shop before it is sent",
              all(row["product_id"] for row in
                  api.sent[0]["payload"]["line_items"]), api.sent)
        check("every card on the quote is on the order",
              [row["product_id"] for row in
               api.sent[0]["payload"]["line_items"]] == [501, 502, 504],
              api.sent[0]["payload"]["line_items"])
        check("and the out-of-stock card is not on it",
              503 not in [row["product_id"] for row in
                          api.sent[0]["payload"]["line_items"]],
              api.sent[0]["payload"]["line_items"])
        check("the order is opened so it can be checked",
              any("post.php" in url for url in app.opened), app.opened)
        after = json.loads(saved.read_text(encoding="utf-8"))
        check("and the quote now says it became an order",
              after["status"] == "ordered" and after["order_number"] == "4321",
              after["status"])
        check("the console says the order went through",
              any("is order #4321" in text for _tag, text in app.lines),
              app.lines[-3:])
        check("a total that did not match the quote is called out",
              BOX.shown and "different total" in str(BOX.shown[-1])
              or any("price changed" in text for _tag, text in app.lines),
              app.lines[-3:])

        #  A shop that refuses the search has to say so in the panel. Tk runs
        #  the posted answer later, after Python has deleted the name the
        #  except clause caught - so a callback that reads the exception it is
        #  not allowed to see anymore raises NameError, and the panel sits on
        #  "Searching..." with a traceback instead of an explanation.
        posted = []

        def hold(delay, callback=None):
            if callback is not None:
                posted.append(callback)
            return "after-id"

        def refuse(*args, **kwargs):
            raise quote_model.QuoteError("The shop did not answer the search.",
                                         "Try again in a minute.")

        parts["search"].set("Batman")
        with patch_object(app, "after", hold), \
                patch_object(gui, "woo_get", refuse):
            parts["buttons"]["Search the stock"].invoke()
        check("the answer to a failed search is posted, not run inside the try",
              len(posted) == 1, len(posted))
        for callback in posted:
            callback()
        check("a search the shop refused is explained, not left searching",
              any("did not answer" in text for _tag, text in app.lines),
              app.lines[-3:])

    #  -- without keys, the quote still saves and prints; only the shop parts
    #     say what they need.
    app = FakeApp(folder, settings={"quotes_dir": str(folder / "nokeys")})
    with patch_object(gui.threading, "Thread", SyncThread), \
            patch_object(gui, "read_woo_credentials",
                         lambda path=None: ("", "", "")), \
            patch_object(gui, "open_woo_keys_file",
                         lambda *a, **k: app.opened.append("woo-keys.txt")):
        BOX.shown.clear()
        parts = build(app)
        BOX.shown.clear()
        parts["search"].set("Batman")
        parts["buttons"]["Search the stock"].invoke()
        check("without keys, searching says where the keys go",
              BOX.shown and "woo-keys.txt" in str(BOX.shown[-1]),
              BOX.shown[-1:])
        parts["buttons"]["Type a card in by hand"].invoke()
        check("and a card can still be added by hand",
              len(parts["rows"].items) == 1, parts["rows"].items)
        parts["buttons"]["Save the quote"].invoke()
        check("the quote still saves",
              any((folder / "nokeys").glob("*.json")),
              sorted(str(p) for p in (folder / "nokeys").glob("*")))
        parts["buttons"]["Turn into an order..."].invoke()
        check("turning it into an order opens the keys file, not an error",
              "woo-keys.txt" in app.opened, app.opened)
        check("and the quote is copied so it can be pasted into an order",
              "TOTAL" in app.clipboard, app.clipboard[:80])


def patch_object(target, name, value):
    """``unittest.mock.patch.object`` for a module held by name."""
    from unittest.mock import patch
    return patch.object(target, name, value)


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def main():
    with tempfile.TemporaryDirectory(prefix="alexcollect-quote-") as tmp:
        root = Path(tmp)
        image = Image.new("RGB", (40, 20), (200, 40, 40))
        image.save(root / "logo.png")
        test_sums()
        test_cards()
        test_files(root)
        test_address()
        test_order()
        test_pdf(root)
        test_pictures_and_links(root)
        test_private_files(root)
        test_panel(root)
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL QUOTE CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
