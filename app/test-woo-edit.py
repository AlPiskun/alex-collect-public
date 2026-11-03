#!/usr/bin/env python3
"""Checks for woo_edit - finding one product and changing its count.

No network: the PUT is an injected opener that records the request and
answers with what the test wants. What matters is that a search finds the
card that was meant and not a different one, that a count that is not a count
is refused before anything is sent, that a product the shop does not count is
refused with the fix named, and that the number reported is the number the
website answered with.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP)]

import stock_write                                    # noqa: E402
import woo_edit                                       # noqa: E402

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


class Recorder:
    """An opener that answers like the website, and keeps the request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request, timeout):
        body = getattr(request, "data", None)
        self.requests.append({"url": request.full_url,
                              "method": request.method,
                              "body": json.loads(body.decode("utf-8"))
                              if body else None})
        if not self.answers:
            return (200, json.dumps({"id": 1, "stock_quantity": 0,
                                     "manage_stock": True}).encode("utf-8"))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def product(pid=7, quantity=3, managed=True, name="Jeter, 1993 Upper Deck #279",
            sku="JET-279", **extra):
    row = {"id": pid, "name": name, "sku": sku,
           "manage_stock": managed, "stock_quantity": quantity,
           "price": "12.00"}
    row.update(extra)
    return row


def test_counts():
    print("== 1. the count a product holds ==")
    check("a counted product says how many are in stock",
          woo_edit.count_of(product(quantity=5)) == 5 and
          woo_edit.count_label(product(quantity=5)) == "5 in stock",
          woo_edit.count_label(product(quantity=5)))
    check("a counted product at zero says sold out, not 'no count'",
          woo_edit.count_of(product(quantity=0)) == 0 and
          "sold out" in woo_edit.count_label(product(quantity=0)),
          woo_edit.count_label(product(quantity=0)))
    check("a product the shop does not count has no number to edit",
          woo_edit.count_of(product(quantity=0, managed=False)) is None)
    check("and its row says so instead of showing a zero",
          woo_edit.count_label(product(managed=False)) ==
          "the website does not count it",
          woo_edit.count_label(product(managed=False)))
    check("a missing count is not zero", woo_edit.count_of({"id": 1}) is None)
    check("a count the site sends as text is still a number",
          woo_edit.count_of({"id": 1, "manage_stock": True,
                             "stock_quantity": "9"}) == 9)
    check("'true' in the site's own spelling still counts as managed",
          woo_edit.count_of({"id": 1, "manage_stock": "true",
                             "stock_quantity": "4"}) == 4)


def test_rows():
    print()
    print("== 2. one row says which card, which count, which SKU ==")
    text = woo_edit.label(product(quantity=2))
    check("the row carries the card's name",
          "Jeter, 1993 Upper Deck #279" in text, text)
    check("its count", "2 in stock" in text, text)
    check("and its SKU, so it can be found again", "[JET-279]" in text, text)
    check("a product with no SKU says so rather than showing nothing",
          "no SKU" in woo_edit.label({"id": 1, "name": "Card"}), "")
    check("a product with no title is not a blank row",
          "(no title)" in woo_edit.label({"id": 1}), "")
    numbered = woo_edit.label(product(), number=3, width=2)
    check("a numbered row stays lined up", numbered.startswith(" 3  "),
          numbered)
    full = woo_edit.describe(product(quantity=4))
    check("the picked product names its SKU, its id and its count",
          "SKU JET-279" in full and "product 7" in full and
          "4 in stock" in full, full)
    check("and its price, when the website sends one", "12.00" in full, full)


def test_parse():
    print()
    print("== 3. what a person typed ==")
    check("zero is a count", woo_edit.parse_count("0") == 0)
    check("so is a padded number", woo_edit.parse_count("  12 ") == 12)
    check("thousands typed the way money is written still read",
          woo_edit.parse_count("1,250") == 1250)
    for typed in ("", "   ", "3.5", "twelve", "-2", "1/2"):
        try:
            woo_edit.parse_count(typed)
            raised = None
        except woo_edit.WooEditError as exc:
            raised = exc
        check("%r is refused, and told what to do" % (typed,),
              raised is not None and raised.hint != "" and
              raised.message != "", str(raised and raised.message))


def test_find():
    print()
    print("== 4. the search finds the card that was meant ==")
    shop = [
        product(pid=1, sku="JET-279", name="Jeter, 1993 Upper Deck #279"),
        product(pid=2, sku="JET-279-DARK", name="Jeter, 1993 Upper Deck #279 "
                "dark back"),
        product(pid=3, sku="GRIF-89", name="Griffey Jr., 1989 Upper Deck #1"),
        product(pid=2781, sku="RC-9", name="Rookie card"),
    ]
    check("a product id finds that product and nothing else",
          [row["id"] for row in woo_edit.find(shop, "2781")] == [2781],
          str([row["id"] for row in woo_edit.find(shop, "2781")]))
    check("a pasted id with a hash still finds it",
          [row["id"] for row in woo_edit.find(shop, "#2781")] == [2781])
    check("an exact SKU comes before the SKUs that only contain it",
          [row["id"] for row in woo_edit.find(shop, "JET-279")] == [1, 2],
          str([row["id"] for row in woo_edit.find(shop, "JET-279")]))
    check("a second word narrows the list instead of replacing it",
          [row["id"] for row in woo_edit.find(shop, "jeter dark")] == [2],
          str([row["id"] for row in woo_edit.find(shop, "jeter dark")]))
    check("a name find works in any case",
          [row["id"] for row in woo_edit.find(shop, "GRIFFEY")] == [3])
    check("a SKU fragment still finds its card",
          [row["id"] for row in woo_edit.find(shop, "GRIF")] == [3])
    check("something that is not there finds nothing rather than something",
          woo_edit.find(shop, "mantle") == [])
    check("an empty search lists the shop from the top",
          [row["id"] for row in woo_edit.find(shop, "", limit=2)] == [1, 2])
    check("and the limit is honest about how many rows it brings",
          len(woo_edit.find(shop, "jeter", limit=1)) == 1)


def test_note():
    print()
    print("== 5. what the website now holds ==")
    note = woo_edit.written_note(product(quantity=3), 3, 9)
    check("the sentence names the new count, the card and the old count",
          "9 in stock" in note and "Jeter" in note and "was 3" in note, note)
    check("an unchanged count is reported as unchanged, not as a change",
          "still shows 5" in woo_edit.written_note(product(), 5, 5))


def test_write():
    print()
    print("== 6. one count, written where it belongs ==")
    opener = Recorder((200, json.dumps({"id": 7, "stock_quantity": 9,
                                        "manage_stock": True}).encode("utf-8")))
    result = woo_edit.set_count("https://shop.example", "ck_a", "cs_b",
                                product(quantity=3), "9", opener=opener)
    request = opener.requests[0]
    check("it is one PUT to that product's own address",
          request["method"] == "PUT" and
          urlsplit(request["url"]).path == "/wp-json/wc/v3/products/7",
          request["url"])
    check("carrying only the count, as a number",
          request["body"] == {"stock_quantity": 9}, str(request["body"]))
    check("the answer is the website's count, not the typed one",
          result["after"] == 9 and result["before"] == 3 and
          result["id"] == 7, str(result))
    check("and the sentence it hands back says both numbers",
          "was 3" in result["note"] and "9 in stock" in result["note"],
          result["note"])

    #  A 200 that kept the old number is the failure this whole module is for.
    kept = Recorder((200, json.dumps({"id": 7, "stock_quantity": 3,
                                      "manage_stock": True}).encode("utf-8")))
    try:
        woo_edit.set_count("https://shop.example", "k", "s", product(),
                           "9", opener=kept)
        raised = None
    except stock_write.StockWriteError as exc:
        raised = exc
    check("a site that answered and kept its own count is a failure",
          raised is not None and "3" in raised.message, str(raised))


def test_refusals():
    print()
    print("== 7. what is refused before anything is sent ==")
    opener = Recorder()
    try:
        woo_edit.set_count("https://shop.example", "k", "s",
                           product(managed=False), "4", opener=opener)
        refused = None
    except woo_edit.WooEditError as exc:
        refused = exc
    check("a product the shop does not count is refused",
          refused is not None, str(refused))
    check("with the fix named, on the product's own page",
          refused is not None and "Track stock quantity" in refused.hint,
          str(refused and refused.hint))
    check("and nothing was sent", opener.requests == [], str(opener.requests))

    try:
        woo_edit.set_count("https://shop.example", "k", "s", product(), "ten",
                           opener=opener)
        typed = None
    except woo_edit.WooEditError as exc:
        typed = exc
    check("a count that is not a number is refused before sending",
          typed is not None and opener.requests == [], str(typed))

    try:
        woo_edit.set_count("https://shop.example", "k", "s", {"name": "x"}, "1",
                           opener=opener)
        picked = None
    except woo_edit.WooEditError as exc:
        picked = exc
    check("no picked product is refused, not written to product None",
          picked is not None and opener.requests == [], str(picked))


def main():
    test_counts()
    test_rows()
    test_parse()
    test_find()
    test_note()
    test_write()
    test_refusals()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL WOO EDIT CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
