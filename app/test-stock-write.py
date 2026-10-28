#!/usr/bin/env python3
"""Checks for stock_write - setting a count on the website.

No network: the PUT is an injected opener that records the request and answers
with whatever the test wants. What matters is that the request carries one
field, that a 200 which did not store the number is a failure, and that one
card failing never stops the others.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP)]

import stock_write                                    # noqa: E402

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
        body = request.data
        self.requests.append({"url": request.full_url, "method": request.method,
                              "body": json.loads(body.decode("utf-8"))
                              if body else None,
                              "headers": dict(request.headers)})
        if not self.answers:
            return 200, json.dumps({"id": 1, "stock_quantity": 0,
                                    "manage_stock": True}).encode("utf-8")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def product(pid=1, quantity=2):
    return (200, json.dumps({"id": pid, "stock_quantity": quantity,
                             "manage_stock": True}).encode("utf-8"))


def error(status, message=""):
    return (status, json.dumps({"code": "x", "message": message}).encode("utf-8"))


def test_one_count():
    print("== 1. one count, written where it belongs ==")
    opener = Recorder(product(7, 0))
    result = stock_write.set_count("https://shop.example", "ck_a", "cs_b", 7, 0,
                                   opener=opener)
    request = opener.requests[0]
    parts = urlsplit(request["url"])
    query = parse_qs(parts.query)
    check("it is a PUT to that product's own address",
          request["method"] == "PUT" and
          parts.path == "/wp-json/wc/v3/products/7", request["url"])
    check("the keys travel as the site's own parameters",
          query.get("consumer_key") == ["ck_a"] and
          query.get("consumer_secret") == ["cs_b"], str(query))
    check("only the count is sent - not price, status or images",
          request["body"] == {"stock_quantity": 0}, str(request["body"]))
    check("the answer's count is what comes back",
          result == {"id": 7, "inventory": 0}, str(result))

    check("a count is read as a number even as text",
          stock_write.set_count("https://shop.example", "k", "s", 3, "4",
                                opener=Recorder(product(3, 4)))["inventory"]
          == 4, "")
    for bad in ("x", None, 1.5, True):
        try:
            #  True is 1 in Python; a card count is never a yes/no answer, so
            #  it is refused like any other value that is not a number.
            result = stock_write.set_count("https://shop.example", "k", "s", 3,
                                           bad, opener=Recorder())
            check("a count that is not a whole number is refused (%r)" % (bad,),
                  False, str(result))
        except stock_write.StockWriteError as exc:
            check("a count that is not a whole number is refused (%r)" % (bad,),
                  "whole number" in exc.message, exc.message)
    try:
        stock_write.set_count("https://shop.example", "k", "s", 3, -1,
                              opener=Recorder())
        check("a negative count is refused", False, "")
    except stock_write.StockWriteError as exc:
        check("a negative count is refused", "negative" in exc.message,
              exc.message)


def test_refusals():
    print()
    print("== 2. what the website says when it will not ==")
    opener = Recorder(error(401, "Consumer key is invalid"))
    try:
        stock_write.set_count("https://shop.example", "k", "s", 1, 0,
                              opener=opener)
        check("a rejected key is named as a key problem", False, "")
    except stock_write.StockWriteError as exc:
        check("a rejected key is named as a key problem",
              exc.status == 401 and "Read/Write" in exc.hint, exc.hint)

    try:
        stock_write.set_count("https://shop.example", "k", "s", 1, 0,
                              opener=Recorder(error(403)))
        check("a key without product rights says how to fix it", False, "")
    except stock_write.StockWriteError as exc:
        check("a key without product rights says how to fix it",
              "Re-create" in exc.hint, exc.hint)

    try:
        stock_write.set_count("https://shop.example", "k", "s", 9, 0,
                              opener=Recorder(error(404)))
        check("a product that is gone is not retried forever", False, "")
    except stock_write.StockWriteError as exc:
        check("a product that is gone is not retried forever",
              "no longer on the website" in exc.message, exc.message)

    #  A 200 that did not store the number is the failure this panel exists for
    opener = Recorder(product(1, 5))
    try:
        stock_write.set_count("https://shop.example", "k", "s", 1, 0,
                              opener=opener)
        check("a 200 that kept the old count is a failure, not a success",
              False, "")
    except stock_write.StockWriteError as exc:
        check("a 200 that kept the old count is a failure, not a success",
              "kept its own count (5) instead of 0" in exc.message, exc.message)

    #  A product whose count is not managed by the shop has no number to keep
    payload = json.dumps({"id": 1, "manage_stock": False,
                          "stock_quantity": None}).encode("utf-8")
    result = stock_write.set_count("https://shop.example", "k", "s", 1, 0,
                                   opener=Recorder((200, payload)))
    check("an unmanaged product is not called a failed write",
          result == {"id": 1, "inventory": 0}, str(result))

    #  A 200 with no product in it is not proof either
    try:
        stock_write.set_count("https://shop.example", "k", "s", 1, 0,
                              opener=Recorder((200, b"{}")))
        check("an answer without the product is not called success", False, "")
    except stock_write.StockWriteError as exc:
        check("an answer without the product is not called success",
              "could not be confirmed" in exc.message, exc.message)

    #  A 5xx is retried, then reported
    opener = Recorder(error(503), error(503), error(503))
    try:
        stock_write.set_count("https://shop.example", "k", "s", 1, 0,
                              opener=opener)
        check("a server error is retried and then reported", False, "")
    except stock_write.StockWriteError as exc:
        check("a server error is retried and then reported",
              len(opener.requests) == 2 and "HTTP 503" in exc.message,
              "%d tries, %s" % (len(opener.requests), exc.message))

    opener = Recorder(error(502), product(1, 0))
    result = stock_write.set_count("https://shop.example", "k", "s", 1, 0,
                                   opener=opener)
    check("and a retry that works is a success",
          result["inventory"] == 0 and len(opener.requests) == 2, str(result))

    try:
        stock_write.set_count("https://shop.example", "", "", 1, 0,
                              opener=Recorder())
        check("missing keys are refused before a request is made", False, "")
    except stock_write.StockWriteError as exc:
        check("missing keys are refused before a request is made",
              "keys" in exc.message, exc.message)

    check("an address that is not a website is refused rather than guessed",
          stock_write.product_url("shop.example", 1, "k", "s") == "", "")
    check("and a product id that is not a number likewise",
          stock_write.product_url("https://shop.example", "abc", "k", "s")
          == "", "")


def test_many_counts():
    print()
    print("== 3. many cards: one failure does not stop the rest ==")
    opener = Recorder(product(1, 0), error(403), product(3, 1))
    seen = []
    result = stock_write.set_counts(
        "https://shop.example", "k", "s",
        [{"id": 1, "quantity": 0, "title": "Card one"},
         {"id": 2, "quantity": 4, "title": "Card two"},
         {"id": 3, "quantity": 1, "title": "Card three"}],
        opener=opener, on_item=seen.append)
    check("the cards that worked are reported with their new counts",
          [(row["id"], row["inventory"]) for row in result["updated"]] ==
          [(1, 0), (3, 1)], str(result["updated"]))
    check("the one that failed is named with the reason and what to do",
          len(result["failed"]) == 1 and result["failed"][0]["id"] == 2 and
          "Re-create" in result["failed"][0]["hint"], str(result["failed"]))
    check("every card is attempted, in order",
          [json.loads(r["body"].decode()) if isinstance(r["body"], bytes)
           else r["body"] for r in []] == [] and
          len(opener.requests) == 3, str(len(opener.requests)))
    check("a caller that watches each card sees both kinds",
          [entry.get("id") for entry in seen] == [1, 2, 3], str(seen))

    result = stock_write.set_counts("https://shop.example", "k", "s", [],
                                    opener=Recorder())
    check("nothing selected is not an error",
          result == {"updated": [], "failed": []}, str(result))


def test_rows_to_plan():
    print()
    print("== 4. which rows can be written to the website ==")
    rows = [
        {"kind": "fix", "woo_id": 1, "woo": 2, "other": 0, "card": "Card one"},
        {"kind": "fix", "woo_id": 2, "woo": 1, "other": 1, "card": "Agrees"},
        {"kind": "fix", "woo_id": None, "woo": 1, "other": 4,
         "card": "No website product"},
        {"kind": "only-woo", "woo_id": 3, "woo": 2, "other": None,
         "card": "Only on the website"},
        {"kind": "only-other", "woo_id": None, "woo": None, "other": 1,
         "card": "Only elsewhere"},
    ]
    plan = stock_write.plan_from_rows(rows, "CanadianShopper")
    check("only a card on both sides with two different counts is written",
          len(plan) == 1 and plan[0]["id"] == 1, str(plan))
    check("the plan carries the website's number and the other side's",
          plan[0]["from"] == 2 and plan[0]["to"] == 0, str(plan))
    check("and the card's name, so the confirmation can say which one",
          plan[0]["title"] == "Card one", str(plan))
    check("the confirmation reads card by card",
          stock_write.describe(plan) == ["  Card one\n      website 2 -> 0"],
          str(stock_write.describe(plan)))
    check("one sentence says how much would change",
          stock_write.summary(plan) ==
          "1 website count would be set to CanadianShopper's count.",
          stock_write.summary(plan))
    check("and an empty plan says nothing would change",
          stock_write.summary([]) == "Nothing to change.", "")


def main():
    test_one_count()
    test_refusals()
    test_many_counts()
    test_rows_to_plan()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL STOCK WRITE CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
