#!/usr/bin/env python3
"""Offline tests for woo_orders.py.

Turning a customer's text into an order touches money and a live shop, so the
parts that can go quietly wrong are checked here: which card a sloppy line
means, when the app must refuse to guess, and what exactly is sent when the
order is written. No network, no window.
"""
import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP)]

import woo_orders  # noqa: E402

PASS = 0
FAIL = 0

SITE = "https://shop.example"
KEY = "ck_live"
SECRET = "cs_live"

CATALOG = [
    {"id": 1, "name": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
     "price": "40.00", "sku": "GR-1"},
    {"id": 2, "name": "1990 Score Mario Lemieux #2 NM", "price": "12.50",
     "sku": "ML-2"},
    {"id": 3, "name": "1979 O-Pee-Chee Wayne Gretzky #18 NM-MT 8",
     "price": "250.00", "sku": "GR-18"},
    {"id": 4, "name": "1966 Topps Bobby Orr #35 VG", "price": "400.00",
     "sku": "BO-35"},
    {"id": 5, "name": "1989 O-Pee-Chee Wayne Gretzky #2 NM", "price": "15.00",
     "sku": "GR-2"},
]


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s %s" % (name, extra))


class FakeOpener:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append({
            "method": request.get_method(),
            "url": request.full_url,
            "body": json.loads(request.data.decode("utf-8"))
            if request.data else None,
            "headers": {k.lower(): v for k, v in request.header_items()},
        })
        reply = self.replies.pop(0) if self.replies else (200, b"{}")
        if isinstance(reply, Exception):
            raise reply
        return reply


def order_reply(order_id=77, line_items=(), number="1234"):
    return (200, json.dumps({"id": order_id, "number": number,
                             "line_items": list(line_items),
                             "fee_lines": []}).encode("utf-8"))


def plan_for(*product_ids):
    return [{"product_id": pid, "quantity": 1, "line": "line",
             "product": {"id": pid, "name": "card", "price": "10.00"}}
            for pid in product_ids]


# --------------------------------------------------------------- 1. the list
def test_parsing():
    print("== 1. the pasted list ==")
    text = """1. 1989 O-Pee-Chee Gretzky #1
2) 1990 Score Mario Lemieux #2
- 1966 Topps Bobby Orr #35 - $400
\u2022 "1979 Gretzky #18"
   # this line is a note, not a card

   1979 O-Pee-Chee Wayne Gretzky #18 NM-MT 8   
"""
    names = woo_orders.parse_card_list(text)
    check("numbering, bullets and quotes are removed",
          names[:4] == ["1989 O-Pee-Chee Gretzky #1",
                        "1990 Score Mario Lemieux #2",
                        "1966 Topps Bobby Orr #35",
                        "1979 Gretzky #18"], str(names))
    check("a comment line is not a card", not any("note" in n for n in names))
    check("blank lines and extra spaces are dropped", "" not in names)
    check("a trailing price is not part of the name",
          "1966 Topps Bobby Orr #35" in names)
    check("the pasted order is kept", names[0].startswith("1989"))
    check("duplicate lines are kept for the order builder",
          woo_orders.parse_card_list("Gretzky #1\nGretzky #1") ==
          ["Gretzky #1", "Gretzky #1"])
    check("an empty paste is empty", woo_orders.parse_card_list("") == [])
    check("whitespace-only input is empty",
          woo_orders.parse_card_list("   \n\n\t\n") == [])
    check("a dash inside a name survives",
          woo_orders.clean_card_line("1989 O-Pee-Chee Gretzky") ==
          "1989 O-Pee-Chee Gretzky")


# ------------------------------------------------------------ 2. the matching
def test_matching():
    print()
    print("== 2. which card a line means ==")
    check("an exact title matches at full strength",
          woo_orders.score(CATALOG[0]["name"], CATALOG[0]["name"]) == 1.0)
    picked = woo_orders.auto_pick("1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
                                  CATALOG)
    check("an exact title is used without asking", picked["id"] == 1, str(picked))
    picked = woo_orders.auto_pick("Bobby Orr 1966 #35", CATALOG)
    check("a reworded line still finds the right card", picked["id"] == 4,
          str(picked))
    picked = woo_orders.auto_pick("Mario Lemieux 1990 Score", CATALOG)
    check("word order does not matter", picked["id"] == 2, str(picked))
    picked = woo_orders.auto_pick("Gretzky 1979 #18", CATALOG)
    check("the year and card number decide between two Gretzkys",
          picked["id"] == 3, str(picked))
    picked = woo_orders.auto_pick("1989 Gretzky #1", CATALOG)
    check("#1 is not mistaken for #2", picked["id"] == 1, str(picked))
    check("a missing card number is never guessed",
          woo_orders.auto_pick("Gretzky", CATALOG) is None)
    #  "Lemieux" scores high against the only Lemieux card, and is still not
    #  enough: one word fits many cards, and the picker costs one click.
    check("one distinctive word alone is never enough",
          woo_orders.auto_pick("Lemieux", CATALOG) is None,
          str(woo_orders.auto_pick("Lemieux", CATALOG)))
    check("a number no card has does not match one",
          woo_orders.auto_pick("1989 Gretzky #99", CATALOG) is None,
          str(woo_orders.auto_pick("1989 Gretzky #99", CATALOG)))
    check("a card that is not stocked returns nothing",
          woo_orders.auto_pick("Ken Dryden 1972", CATALOG) is None)
    check("two equal candidates are never auto-picked",
          woo_orders.auto_pick("Wayne Gretzky",
                               [{"id": 9, "name": "1989 O-Pee-Chee Wayne "
                                 "Gretzky #1"},
                                {"id": 10, "name": "1989 O-Pee-Chee Wayne "
                                 "Gretzky #2"}]) is None)
    ranked = woo_orders.rank("Gretzky 1979 #18", CATALOG)
    check("candidates come back best first",
          ranked and ranked[0][1]["id"] == 3, str(ranked))
    check("weak candidates are not offered",
          all(value >= woo_orders.SHOW_MATCH for value, _ in ranked))
    check("a product with no id is ignored",
          woo_orders.rank("Gretzky", [{"name": "Gretzky #1"}]) == [])
    check("an empty catalogue is handled",
          woo_orders.rank("Gretzky", []) == [])
    check("junk in the catalogue does not crash",
          woo_orders.rank("Gretzky", [None, "x", {}]) == [])

    print()
    print("== 3. progressively broader searches ==")
    terms = woo_orders.search_terms("1989 OPC Gretzky #1")
    check("the whole line is tried first", terms[0] == "1989 OPC Gretzky #1",
          str(terms))
    check("a broader term follows when that fails", len(terms) > 1, str(terms))
    check("the distinctive word is eventually tried", "gretzky" in terms,
          str(terms))
    check("terms are not repeated",
          len({t.lower() for t in terms}) == len(terms), str(terms))
    check("a one-word line still gives one term",
          woo_orders.search_terms("Gretzky") == ["Gretzky"])


# ----------------------------------------------------------- 4. the order body
def test_payload():
    print()
    print("== 4. what is sent when the order is written ==")
    payload = woo_orders.order_payload(plan_for(1, 2))
    check("the order is created pending, not paid",
          payload["status"] == "pending" and payload["set_paid"] is False,
          str(payload))
    check("one line item per card, quantity 1",
          payload["line_items"] == [{"product_id": 1, "quantity": 1},
                                    {"product_id": 2, "quantity": 1}],
          str(payload))
    check("no fee line without a discount", "fee_lines" not in payload)

    twice = plan_for(1, 1)
    merged = woo_orders.merge_duplicates(twice)
    check("the same card twice becomes one row of quantity 2",
          len(merged) == 1 and merged[0]["quantity"] == 2, str(merged))
    check("the order body follows suit",
          woo_orders.order_payload(twice)["line_items"] ==
          [{"product_id": 1, "quantity": 2}])

    estimate = woo_orders.estimate_total(plan_for(1, 1, 2))
    check("the estimate adds up quantities", estimate["subtotal"] == 30.0,
          str(estimate))
    check("the estimate counts priced rows", estimate["priced"] == 2,
          str(estimate))
    priced = woo_orders.order_payload(plan_for(1, 1, 2), discount_percent=10)
    check("a discount becomes one negative fee line",
          priced["fee_lines"] == [{"name": "Discount 10%", "total": "-3.00"}],
          str(priced.get("fee_lines")))
    check("a discount above the subtotal is not invented",
          woo_orders.fee_lines(0, 0) == [])
    check("a zero discount adds no fee line",
          "fee_lines" not in woo_orders.order_payload(plan_for(1),
                                                      discount_percent=0))
    check("an unpriced card is counted, not guessed",
          woo_orders.estimate_total([{"product_id": 9, "quantity": 1,
                                      "product": {"id": 9}}])["unpriced"] == 1)
    check("a note is passed through",
          woo_orders.order_payload(plan_for(1), note="from a text")[
              "customer_note"] == "from a text")


# ------------------------------------------------------------- 5. the requests
def test_create():
    print()
    print("== 5. creating an order ==")
    opener = FakeOpener(order_reply())
    order = woo_orders.create_order(SITE, KEY, SECRET, plan_for(1, 2),
                                    opener=opener)
    sent = opener.requests[0]
    check("it POSTs to the orders endpoint",
          sent["method"] == "POST" and
          sent["url"].startswith("https://shop.example/wp-json/wc/v3/orders?"),
          sent["url"])
    check("the keys travel as query parameters",
          "consumer_key=ck_live" in sent["url"], sent["url"])
    check("the body is JSON",
          sent["headers"].get("content-type") == "application/json")
    check("the order comes back with its number", order["number"] == "1234")
    check("nothing is marked paid", sent["body"]["set_paid"] is False)

    opener = FakeOpener((401, b'{"message":"bad keys"}'))
    try:
        woo_orders.create_order(SITE, KEY, SECRET, plan_for(1), opener=opener)
        check("read-only keys are refused", False, "no error raised")
    except woo_orders.OrderError as exc:
        check("read-only keys are called out",
              "Read/Write" in exc.message and exc.status == 401, exc.message)
    opener = FakeOpener((200, b'{}'))
    try:
        woo_orders.create_order(SITE, KEY, SECRET, plan_for(1), opener=opener)
        check("an answer with no order id is not success", False)
    except woo_orders.OrderError as exc:
        check("an answer with no order id is not success",
              "did not return its number" in exc.message, exc.message)
    idle = FakeOpener()
    try:
        woo_orders.create_order(SITE, KEY, SECRET, [], opener=idle)
        check("an empty plan is refused", False)
    except woo_orders.OrderError:
        check("an empty plan is refused before any request", not idle.requests)
    try:
        woo_orders.create_order("", KEY, SECRET, plan_for(1), opener=idle)
        check("a missing site is refused", False)
    except woo_orders.OrderError:
        check("a missing site is refused before any request",
              not idle.requests)
    try:
        woo_orders.create_order(SITE, "", "", plan_for(1), opener=idle)
        check("missing keys are refused", False)
    except woo_orders.OrderError:
        check("missing keys are refused before any request", not idle.requests)


def test_add_to_existing():
    print()
    print("== 6. adding to an order that already exists ==")
    existing = [{"id": 501, "product_id": 2, "quantity": 1,
                 "variation_id": 0},
                {"id": 502, "product_id": 4, "quantity": 3}]
    opener = FakeOpener(order_reply(77, existing),
                        order_reply(77, existing + [{"id": 503}]))
    woo_orders.add_to_order(SITE, KEY, SECRET, "#1234", plan_for(1),
                            opener=opener)
    check("the order is read before it is changed",
          opener.requests[0]["method"] == "GET" and
          "/wp-json/wc/v3/orders/1234" in opener.requests[0]["url"],
          opener.requests[0]["url"])
    put = opener.requests[1]
    check("the change is a PUT to that order",
          put["method"] == "PUT" and "/orders/77" in put["url"], put["url"])
    check("existing rows are addressed by their own line id",
          put["body"]["line_items"][:2] ==
          [{"id": 501, "quantity": 1}, {"id": 502, "quantity": 3}],
          str(put["body"]["line_items"]))
    check("the new card is appended as a product row",
          put["body"]["line_items"][2] == {"product_id": 1, "quantity": 1},
          str(put["body"]["line_items"]))

    opener = FakeOpener(order_reply(77, existing),
                        order_reply(77, existing))
    woo_orders.add_to_order(SITE, KEY, SECRET, 77, plan_for(2), opener=opener)
    put = opener.requests[1]
    check("a card already on the order gains quantity instead of a second row",
          put["body"]["line_items"][0] == {"id": 501, "quantity": 2},
          str(put["body"]["line_items"]))
    check("the other rows are untouched",
          put["body"]["line_items"][1] == {"id": 502, "quantity": 3},
          str(put["body"]["line_items"]))

    opener = FakeOpener((404, b'{"message":"no order"}'))
    try:
        woo_orders.add_to_order(SITE, KEY, SECRET, 999, plan_for(1),
                                opener=opener)
        check("a missing order is refused", False)
    except woo_orders.OrderError as exc:
        check("a missing order says so",
              "does not exist" in exc.message, exc.message)
    check("nothing is written when the order was not found",
          len(opener.requests) == 1, str(len(opener.requests)))

    opener = FakeOpener(order_reply(77, existing), order_reply(77, existing))
    woo_orders.add_to_order(SITE, KEY, SECRET, 77, plan_for(1),
                            discount_percent=10, opener=opener)
    check("a discount on an existing order becomes a fee line",
          opener.requests[1]["body"]["fee_lines"] ==
          [{"name": "Discount 10%", "total": "-1.00"}],
          str(opener.requests[1]["body"].get("fee_lines")))


# --------------------------------------------------------------- 7. the links
def test_links():
    print()
    print("== 7. fallbacks without the API ==")
    check("the order list URL is the dashboard's",
          woo_orders.orders_admin_url("https://shop.example/") ==
          "https://shop.example/wp-admin/admin.php?page=wc-orders")
    check("a bare host gives no order list",
          woo_orders.orders_admin_url("shop.example") == "")
    check("no site gives no order list", woo_orders.orders_admin_url("") == "")
    check("the edit link points at the new order",
          woo_orders.order_edit_url("https://shop.example", 77) ==
          "https://shop.example/wp-admin/post.php?post=77&action=edit")
    check("an order with no id gives no link",
          woo_orders.order_edit_url("https://shop.example", None) == "")


def test_merge_line_items():
    print()
    print("== 8. merging never loses a row ==")
    merged = woo_orders.merge_line_items(
        [{"id": 1, "product_id": 5, "quantity": 2}],
        [{"product_id": 5, "quantity": 1}, {"product_id": 6, "quantity": 1}])
    check("an existing product is incremented, not duplicated",
          merged == [{"id": 1, "quantity": 3},
                     {"product_id": 6, "quantity": 1}], str(merged))
    check("rows without an id are ignored rather than guessed",
          woo_orders.merge_line_items([{"product_id": 5, "quantity": 2}], []) ==
          [])
    check("an empty order just gets the new rows",
          woo_orders.merge_line_items([], [{"product_id": 7, "quantity": 1}]) ==
          [{"product_id": 7, "quantity": 1}])
    check("a variation is carried through",
          woo_orders.merge_line_items(
              [{"id": 1, "product_id": 5, "quantity": 1,
                "variation_id": 44}], []) ==
          [{"id": 1, "quantity": 1, "variation_id": 44}])


def main():
    test_parsing()
    test_matching()
    test_payload()
    test_create()
    test_add_to_existing()
    test_links()
    test_merge_line_items()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL WOO ORDER CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
