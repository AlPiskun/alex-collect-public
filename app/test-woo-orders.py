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


#  A real paste: 26 of the 32 lines begin with a card number. Treating those
#  as comments silently dropped 26 cards once, which is why they are pinned.
PASTED = """\
1971-72 O-Pee-Chee Dave Keon #259 2nd Team All-Star Toronto Maple Leafs EX-MT 6

#217 Paul Henderson (Near Mint) 1970-71 O-Pee-Chee

#107 Mike Pelyk (Rookie Card) 1970-71 O-Pee-Chee

1970-71 O-Pee-Chee Lowell MacDonald #206 Pittsburgh Penguins (VG-EX 4)

1970-71 O-Pee-Chee Jim Morrison #90 Pittsburgh Penguins (EX-MT 6)

#59 Tim Horton (EX) 1970-71 O-Pee-Chee

#50 Yvan Cournoyer (NM) 1970-71 O-Pee-Chee

#177 Guy Lapointe (Rookie Card) EX 1970-71 O-Pee-Chee 

#109 Mike Walton EX 1970-71 O-Pee-Chee Trading Card

1970-71 O-Pee-Chee John Ferguson #264 Montreal Canadiens (EX-MT 6) 

#217 Paul Henderson (Excellent) 1970-71 O-Pee-Chee

1972-73 O-Pee-Chee Hockey 2nd Series Checklist #190 Unmarked (EX 5)

#8 Kenny Hodge 1970-71 O-Pee-Chee

#175a Mickey Redmond (Traded) 1970-71 O-Pee-Chee

#176 Henri Richard (EX) 1970-71 O-Pee-Chee

#181 Jean Ratelle (NM) 1970-71 O-Pee-Chee

#26 Garry Unger 1970-71 O-Pee-Chee

#58 Pete Mahovlich (EX) 1970-71 O-Pee-Chee

#139 Ed Westfall 1970-71 O-Pee-Chee

#230 Len Lunde (EX) 1970-71 O-Pee-Chee

#136 Derek Sanderson 1970-71 O-Pee-Chee 

#20 Stan Mikita (PR) 1970-71 O-Pee-Chee

#17 Pat Stapleton 1970-71 O-Pee-Chee

#19 Eric Nesterenko 1970-71 O-Pee-Chee

#219 Dave Keon (Near Mint) 1970-71 O-Pee-Chee

#191 Earl Ingarfield (EX) 1970-71 O-Pee-Chee

#178 Jean-Claude Tremblay (PR) 1970-71 O-Pee-Chee

#191 Earl Ingarfield (PR) 1970-71 O-Pee-Chee

#51 Serge Savard (EX) 1970-71 O-Pee-Chee 

#57 Jacques Lemaire (PR) 1970-71 O-Pee-Chee

#52 Jacques Laperriere (EX) 1970-71 O-Pee-Chee Clone

1970-71 O-Pee-Chee John Ferguson #264 Montreal Canadiens (EX 5)
"""


def test_card_number_lines():
    print("== 1b. lines that begin with a card number are cards ==")
    names = woo_orders.parse_card_list(PASTED)
    check("all 32 pasted lines are read", len(names) == 32, str(len(names)))
    check("a line starting with #217 is a card, not a comment",
          names[1] == "#217 Paul Henderson (Near Mint) 1970-71 O-Pee-Chee",
          names[1] if len(names) > 1 else "")
    check("the last line is read too",
          names[-1] == "1970-71 O-Pee-Chee John Ferguson #264 Montreal "
                       "Canadiens (EX 5)", names[-1])
    check("a hash that is not a number is still a comment",
          woo_orders.parse_card_list("# a note\n#217 Tim Horton\n") ==
          ["#217 Tim Horton"])
    check("a hash alone is a comment",
          woo_orders.parse_card_list("#\n#217 Tim Horton") == ["#217 Tim Horton"])
    check("a lettered card number survives",
          "#175a Mickey Redmond (Traded) 1970-71 O-Pee-Chee" in names)
    check("the card number never becomes a comment marker mid-list",
          sum(1 for n in names if n.startswith("#")) == 26,
          str(sum(1 for n in names if n.startswith("#"))))


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
    #  Picking the two longest words alone chose the team ("toronto maple"),
    #  which is useless for finding one card. The card number anchors it.
    terms = woo_orders.search_terms(
        "1971-72 O-Pee-Chee Dave Keon #259 2nd Team All-Star Toronto Maple "
        "Leafs EX-MT 6")
    check("the card number leads the fallback searches",
          terms[1] == "259 toronto", str(terms))
    check("the year is not mistaken for the card number",
          not terms[1].startswith("1971"), str(terms))
    terms = woo_orders.search_terms("#175a Mickey Redmond (Traded) 1970-71 "
                                    "O-Pee-Chee")
    check("a lettered card number is used as written",
          terms[1].startswith("175a"), str(terms))
    #  The note in brackets is longer than the player's name, and picking it
    #  searched for "107 rookie" instead of "107 pelyk" - no product has the
    #  word "rookie", so the card was never found.
    terms = woo_orders.search_terms("#107 Mike Pelyk (Rookie Card) 1970-71 "
                                    "O-Pee-Chee")
    check("a bracketed note is not used as the search word",
          terms[1] == "107 pelyk", str(terms))
    check("the bracketed word is absent from the fallback terms",
          not any("rookie" in t.lower() for t in terms[1:]), str(terms))
    check("the card number alone is the last resort",
          terms[-1] == "107", str(terms))


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
    check("the same line twice becomes one row of quantity 2",
          len(merged) == 1 and merged[0]["quantity"] == 2, str(merged))

    #  Two grades of one card are two different things to sell, even when the
    #  catalogue only has one product for both. Merging them would turn a
    #  two-card order into "quantity 2" of a single card.
    two_grades = [
        {"product_id": 7, "quantity": 1, "line": "Henderson (Near Mint)",
         "product": {"id": 7, "price": "20.00"}},
        {"product_id": 7, "quantity": 1, "line": "Henderson (Excellent)",
         "product": {"id": 7, "price": "20.00"}},
    ]
    graded = woo_orders.merge_duplicates(two_grades)
    check("two grades of one card stay as two rows",
          len(graded) == 2 and [i["quantity"] for i in graded] == [1, 1],
          str(graded))
    check("the order body keeps both rows",
          len(woo_orders.order_payload(two_grades)["line_items"]) == 2,
          str(woo_orders.order_payload(two_grades)["line_items"]))
    check("the estimate counts both cards",
          woo_orders.estimate_total(two_grades)["subtotal"] == 40.0,
          str(woo_orders.estimate_total(two_grades)))
    check("an identical repeated line still merges",
          len(woo_orders.merge_duplicates(two_grades + [two_grades[0]])) == 2,
          str(woo_orders.merge_duplicates(two_grades + [two_grades[0]])))
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


def test_find_order():
    print()
    print("== 10. finding an order from the number a person typed ==")
    #  A shop that numbers orders by their id: one read, straight to the order.
    opener = FakeOpener(order_reply(77, [], "1234"))
    order = woo_orders.find_order(SITE, KEY, SECRET, "#1234", opener=opener)
    check("a plain number is read by its id",
          order["id"] == 77 and len(opener.requests) == 1,
          [r["url"] for r in opener.requests])
    check("and the hash people type is not part of it",
          opener.requests[0]["url"].endswith("/orders/1234?consumer_key="
                                             "ck_live&consumer_secret=cs_live"),
          opener.requests[0]["url"])

    #  A shop with its own numbering: not a number, so the list is searched.
    opener = FakeOpener((200, json.dumps([{"id": 91, "number": "WC-1042"},
                                          {"id": 92, "number": "WC-10420"},
                                          {"id": 93,
                                           "number": "WC-1042-A"}]).encode()))
    order = woo_orders.find_order(SITE, KEY, SECRET, "WC-1042", opener=opener)
    check("a shop's own number is found by searching the order list",
          order["id"] == 91, order)
    check("and only an exact number is taken, never a near one",
          order["number"] == "WC-1042", order["number"])

    opener = FakeOpener((200, json.dumps([{"id": 92,
                                          "number": "WC-10420"}]).encode()))
    try:
        woo_orders.find_order(SITE, KEY, SECRET, "WC-1042", opener=opener)
        check("an order that is not there is refused, not guessed at", False,
              "no error")
    except woo_orders.OrderError as exc:
        check("an order that is not there is refused, not guessed at",
              "WC-1042" in exc.message, exc.message)
    try:
        woo_orders.find_order(SITE, KEY, SECRET, "   ", opener=opener)
        check("an empty number is refused before any request", False, "no error")
    except woo_orders.OrderError as exc:
        check("an empty number is refused before any request",
              "number" in exc.message, exc.message)


def test_search_orders():
    print()
    print("== 11. the one search box: a number, a customer, or a card ==")

    def order(order_id, number, first="Dana", last="Whitfield", items=()):
        return {"id": order_id, "number": number, "status": "processing",
                "billing": {"first_name": first, "last_name": last},
                "line_items": list(items)}

    #  A number that is also an id: read straight, then the shop's search and
    #  the card search are still offered - and the same order must not appear
    #  twice in the list.
    same = order(77, "1234")
    opener = FakeOpener(
        order_reply(77, [], "1234"),                  # /orders/1234
        (200, json.dumps([same]).encode()),           # /orders?search=1234
        (200, b"[]"),                                 # /products?search=1234
    )
    rows = woo_orders.search_orders(SITE, KEY, SECRET, "#1234", opener=opener)
    check("an order found twice is listed once",
          len(rows) == 1, [row["number"] for row in rows])
    check("and it says the number is what found it",
          rows[0]["found_by"] == ["its number"], rows[0]["found_by"])

    #  The same order, found by its number and again because it holds the
    #  card that was typed: one row, and both reasons are kept.
    opener = FakeOpener(
        order_reply(77, [], "1234"),
        (200, b"[]"),
        (200, json.dumps([{"id": 501, "name": "Batman #1"}]).encode()),
        (200, json.dumps([same]).encode()),
    )
    rows = woo_orders.search_orders(SITE, KEY, SECRET, "1234", opener=opener)
    check("an order found two ways keeps both reasons",
          len(rows) == 1 and rows[0]["found_by"] ==
          ["its number", "a card: Batman #1"], rows[0]["found_by"])

    #  A customer: the shop's own order search, no product lookup.
    opener = FakeOpener((200, json.dumps([order(88, "1042")]).encode()),
                        (200, b"[]"))
    rows = woo_orders.search_orders(SITE, KEY, SECRET, "whitfield",
                                    opener=opener)
    check("a customer's name is answered by the order search",
          rows and rows[0]["number"] == "1042"
          and rows[0]["customer"] == "Dana Whitfield", rows)
    check("and the row carries what the sheet will show",
          rows[0]["status"] == "processing" and rows[0]["count"] == 0
          and rows[0]["found_by"] == ["the shop's search"], rows[0])

    #  A card: products first, then the orders holding each product.
    opener = FakeOpener(
        (200, b"[]"),
        (200, json.dumps([{"id": 501, "name": "Batman #1"},
                          {"id": 502, "name": "Batman #2"}]).encode()),
        (200, json.dumps([order(99, "2001", items=[
            {"name": "Batman #1", "quantity": 2}])]).encode()),
        (200, b"[]"),
    )
    rows = woo_orders.search_orders(SITE, KEY, SECRET, "batman",
                                    opener=opener)
    check("each matching card is asked which orders hold it",
          sum(1 for r in opener.requests if "product=" in r["url"]) == 2,
          [r["url"] for r in opener.requests])
    check("and an order that holds one is listed, with the card named",
          rows and rows[0]["number"] == "2001"
          and rows[0]["found_by"] == ["a card: Batman #1"], rows)
    check("the cards on it are readable at a glance",
          rows[0]["cards"] == ["Batman #1 x2"], rows[0]["cards"])

    #  A blank search never reaches the shop.
    opener = FakeOpener()
    try:
        woo_orders.search_orders(SITE, KEY, SECRET, "  ", opener=opener)
        check("a blank search is refused before any request", False,
              "no error")
    except woo_orders.OrderError as exc:
        check("a blank search is refused before any request",
              not opener.requests and "card" in exc.message, exc.message)


def main():
    test_parsing()
    test_card_number_lines()
    test_matching()
    test_payload()
    test_create()
    test_add_to_existing()
    test_links()
    test_merge_line_items()
    test_find_order()
    test_search_orders()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL WOO ORDER CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
