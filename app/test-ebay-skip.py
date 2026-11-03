#!/usr/bin/env python3
"""Checks for ebay_skip - the cards that are never offered again.

No site, no window, no network: a skip is a small JSON file beside the app's
settings, and what matters is that the same card is recognized by the same
key on every list, that a file which cannot be read is not mistaken for "no
card was ever marked", and that a mark which could not be saved is reported
as not saved rather than as a skip.
"""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP)]

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


CARD = {"id": 12, "name": "1973-74 O-Pee-Chee Jim Pappin #112 EX 5",
        "sku": "OPC1973-74-112-Pappin-EX-5", "price": "1250.00"}


def test_what_identifies_a_card():
    import ebay_skip
    print("== 1. what identifies a card across lists ==")
    check("the SKU is the key, in one spelling whoever wrote it",
          ebay_skip.key_of(dict(CARD, sku=" opc1973-74-112-pappin-ex-5 "))
          == "OPC1973-74-112-PAPPIN-EX-5",
          ebay_skip.key_of(dict(CARD, sku=" opc1973-74-112-pappin-ex-5 ")))
    check("a product with no SKU is known by its id",
          ebay_skip.key_of({"id": 42, "name": "A card"}) == "id:42", "")
    check("and with neither, by its title in words",
          ebay_skip.key_of({"name": "  A   Card #1 "}) == "title:a card #1",
          ebay_skip.key_of({"name": "  A   Card #1 "}))
    check("a batch card's own title is read the way the batch spells it",
          ebay_skip.key_of({"seo_title": "A batch card"}) ==
          "title:a batch card", "")
    check("nothing at all is not a key, so it can never be marked",
          ebay_skip.key_of({}) == "" and ebay_skip.key_of(None) == "", "")
    check("the title travels with the key for the list a person reads",
          ebay_skip.title_of(CARD) == CARD["name"], ebay_skip.title_of(CARD))


def test_the_file():
    import ebay_skip
    print()
    print("== 2. the file beside the app's settings ==")
    check("it is called what the panel says it is",
          ebay_skip.FILE_NAME == "ebay-skips.json" and
          ebay_skip.path_for("/app") == Path("/app/ebay-skips.json"),
          str(ebay_skip.path_for("/app")))
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        path = ebay_skip.path_for(folder)
        check("a folder with no file marks nothing and is not an error",
              ebay_skip.load(path) == {} and ebay_skip.problem(path) == "",
              "")
        marked = ebay_skip.mark({}, ebay_skip.key_of(CARD), CARD,
                                now=datetime(2026, 11, 3, 18, 5, 9))
        check("a mark keeps the key, the card's title and the moment",
              list(marked) == ["OPC1973-74-112-PAPPIN-EX-5"] and
              marked["OPC1973-74-112-PAPPIN-EX-5"]["title"] == CARD["name"] and
              marked["OPC1973-74-112-PAPPIN-EX-5"]["at"] ==
              "2026-11-03 18:05:09", str(marked))
        check("and it does not touch the copy it was given",
              ebay_skip.mark({}, "X", CARD) != {} and
              ebay_skip.load(path) == {}, "")
        check("saving writes the file", ebay_skip.save(path, marked) and
              path.is_file(), "")
        check("and reading it back gives the same cards",
              ebay_skip.load(path) == marked, str(ebay_skip.load(path)))
        stored = json.loads(path.read_text(encoding="utf-8"))
        check("the file says what it is, so a person opening it knows",
              stored.get("version") == ebay_skip.VERSION and
              "_what" in stored and "cards" in stored, str(list(stored)))
        check("a file that reads is not a file with a problem",
              ebay_skip.problem(path) == "", ebay_skip.problem(path))

        path.write_text("{not json", encoding="utf-8")
        check("a file that cannot be read marks nothing",
              ebay_skip.load(path) == {}, "")
        check("but it is reported, not quietly ignored",
              "could not be read" in ebay_skip.problem(path),
              ebay_skip.problem(path))
        check("nothing is written when the marks have not changed",
              ebay_skip.save(path, marked) and
              ebay_skip.problem(path) == "", "")

        #  A file written by hand as one key per card is still a skip list.
        path.write_text(json.dumps(
            {"SOME-SKU": {"title": "A card"}}), encoding="utf-8")
        check("a hand-written file is read the same way",
              list(ebay_skip.load(path)) == ["SOME-SKU"],
              str(ebay_skip.load(path)))

        #  A path with a file where a folder has to be: the one way to make
        #  writing fail on every machine, Windows included.
        blocker = folder / "not-a-folder"
        blocker.write_text("x", encoding="utf-8")
        check("a file that cannot be written says so instead of pretending",
              ebay_skip.save(blocker / "ebay-skips.json", marked) is False,
              "")


def test_marking():
    import ebay_skip
    print()
    print("== 3. marking, and putting back ==")
    key = ebay_skip.key_of(CARD)
    marked = ebay_skip.mark({}, key, CARD)
    check("a marked card is marked", ebay_skip.is_marked(marked, key), "")
    check("its neighbour is not", not ebay_skip.is_marked(marked, "OTHER"), "")
    check("marking twice is one mark, not two",
          len(ebay_skip.mark(marked, key, CARD)) == 1, "")
    check("an empty key marks nothing at all",
          ebay_skip.mark({}, "", CARD) == {}, "")
    check("a key handed in as the shop spells it still matches",
          ebay_skip.is_marked(ebay_skip.mark({}, " opc1973-74-112-pappin-ex-5 ",
                                             CARD), key), "")
    check("putting a card back leaves the others alone",
          ebay_skip.unmark(ebay_skip.mark(marked, "OTHER", {"name": "Other"}),
                           key) == ebay_skip.mark({}, "OTHER",
                                                   {"name": "Other"}),
          "")
    check("putting back a card that is not there changes nothing",
          ebay_skip.unmark(marked, "NOT-THERE") == marked, "")
    check("and putting back does not edit the copy it was given",
          ebay_skip.unmark(marked, key) == {} and marked, "")


def test_splitting():
    import ebay_skip
    print()
    print("== 4. which cards a list may offer ==")
    cards = [
        dict(CARD, id=1, name="Dear #1", sku="S-1"),
        dict(CARD, id=2, name="Kept #2", sku="S-2"),
        dict(CARD, id=3, name="Dear #3", sku="S-3"),
        dict(CARD, id=4, name="Kept #4", sku="S-4"),
    ]
    skips = ebay_skip.mark(ebay_skip.mark({}, "S-2",
                                           dict(cards[1])),
                           "S-4", dict(cards[3]))
    kept, marked = ebay_skip.split(cards, skips)
    check("the cards that are not marked are the ones offered",
          [card["id"] for card in kept] == [1, 3],
          str([card["id"] for card in kept]))
    check("and the marked ones are reported, not dropped silently",
          [card["id"] for card in marked] == [2, 4],
          str([card["id"] for card in marked]))
    check("the order the caller gave is the order kept",
          [card["name"] for card in kept] == ["Dear #1", "Dear #3"], "")
    check("with nothing marked, every card is offered",
          ebay_skip.split(cards, {})[0] == cards, "")


def test_words():
    import ebay_skip
    print()
    print("== 5. what the panel and the console say ==")
    one = ebay_skip.mark({}, "S-1", {"name": "Kept card"},
                         now=datetime(2026, 11, 1, 9, 0, 0))
    two = ebay_skip.mark(one, "S-2", {"name": "Other card"},
                         now=datetime(2026, 11, 2, 9, 0, 0))
    check("nothing marked says nothing", ebay_skip.summary({}) == "", "")
    check("one card is said as one card",
          ebay_skip.summary(one) == "1 card marked to skip: Kept card.",
          ebay_skip.summary(one))
    check("newest mark first, and the count is right",
          ebay_skip.summary(two).startswith("2 cards marked to skip: "
                                            "Other card, Kept card"),
          ebay_skip.summary(two))
    rows = ebay_skip.rows(two)
    check("the list a person reads carries the key and the moment",
          rows[0]["key"] == "S-2" and rows[0]["at"] == "2026-11-02 09:00:00"
          and rows[0]["title"] == "Other card", str(rows))
    check("and nothing marked is an empty list", ebay_skip.rows({}) == [], "")

    check("what a selection left out is said with its count",
          ebay_skip.left_out({}, 0) == "" and
          "1 card marked to skip was left out" in ebay_skip.left_out({}, 1) and
          "3 cards marked to skip were left out" in ebay_skip.left_out({}, 3),
          ebay_skip.left_out({}, 3))
    check("and it says where the way back is",
          "Skipped cards button" in ebay_skip.left_out({}, 2), "")

    saved = ebay_skip.marked_sentence({"name": "Kept card"}, True, "/a/b.json")
    check("a saved mark says the card is off this list and every later one",
          "Kept card" in saved and "every later list" in saved, saved)
    refused = ebay_skip.marked_sentence({"name": "Kept card"}, False,
                                        "/a/ebay-skips.json")
    check("a mark that could not be saved says it was not marked",
          "was not marked" in refused and "ebay-skips.json" in refused,
          refused)
    back = ebay_skip.unmarked_sentence({"title": "Kept card"}, True, "/a/b")
    check("putting one back says the next selection offers it",
          "Kept card" in back and "offers it again" in back, back)
    check("and a put-back that failed says it is still marked",
          "still marked" in ebay_skip.unmarked_sentence({"title": "x"}, False),
          "")


def main():
    test_what_identifies_a_card()
    test_the_file()
    test_marking()
    test_splitting()
    test_words()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL EBAY SKIP CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
