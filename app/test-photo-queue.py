"""Checks for photo_queue: an order's cards, nine at a time.

    python test-photo-queue.py

No tkinter and no shop: the order and the products are plain dictionaries, the
way the website returns them. The point of these checks is the decisions - what
goes in the queue, what is named as left out and why, which nine are on the
table now, and what is remembered between two sittings.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import photo_queue

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


def product(pid, name, stock=3, manage=True, sku="", images=2):
    """A product as the WooCommerce API returns it, trimmed to what is read."""
    return {"id": pid, "name": name, "sku": sku, "manage_stock": manage,
            "stock_quantity": stock,
            "images": [{"id": 100 + pid * 10 + n} for n in range(images)]}


def line(pid, name, quantity=1, sku=""):
    return {"product_id": pid, "name": name, "quantity": quantity, "sku": sku}


def order(lines, number="1042", first="Dana", last="Lee"):
    return {"id": 7, "number": number, "line_items": lines,
            "billing": {"first_name": first, "last_name": last}}


# --------------------------------------------------------------- the sitting
def test_sheet_is_nine():
    print()
    print("== 1. a card sheet holds nine, so a sitting is nine ==")
    check("the sheet size is nine", photo_queue.SHEET == 9,
          str(photo_queue.SHEET))
    check("the memory has its own file name",
          photo_queue.STATE_NAME == "photo-queue.json",
          photo_queue.STATE_NAME)


def test_stock_of():
    print()
    print("== 2. how many can still be bought ==")
    check("a tracked count is read", photo_queue.stock_of(
        product(1, "x", stock=4)) == 4)
    check("a count written as text is read", photo_queue.stock_of(
        product(1, "x", stock="12")) == 12)
    check("zero is a number, not a missing value", photo_queue.stock_of(
        product(1, "x", stock=0)) == 0, str(photo_queue.stock_of(
            product(1, "x", stock=0))))
    check("a product that does not track stock has no count",
          photo_queue.stock_of(product(1, "x", manage=False)) is None)
    check("a missing quantity has no count", photo_queue.stock_of(
        {"manage_stock": True}) is None)
    check("nonsense is not a count", photo_queue.stock_of(
        product(1, "x", stock="plenty")) is None,
          str(photo_queue.stock_of(product(1, "x", stock="plenty"))))
    check("no product at all is not a count",
          photo_queue.stock_of(None) is None)


def test_from_order_keeps_what_can_be_sold():
    print()
    print("== 3. the order's cards that still need a photograph ==")
    lines = [line(1, "1972-73 O-Pee-Chee Dave Burrows #133"),
             line(2, "1979-80 O-Pee-Chee Wayne Gretzky #18", quantity=2),
             line(3, "1985-86 O-Pee-Chee Mario Lemieux #9")]
    products = {1: product(1, "1972-73 O-Pee-Chee Dave Burrows #133",
                           stock=1, sku="BUR-133"),
                2: product(2, "1979-80 O-Pee-Chee Wayne Gretzky #18",
                           stock=1),
                3: product(3, "1985-86 O-Pee-Chee Mario Lemieux #9",
                           stock=0)}
    built = photo_queue.from_order(order(lines), products)
    check("the order number comes back", built["number"] == "1042",
          built["number"])
    check("the customer is named", built["customer"] == "Dana Lee",
          built["customer"])
    names = [row["name"] for row in built["rows"]]
    check("a card that can still be bought is in the queue",
          "1972-73 O-Pee-Chee Dave Burrows #133" in names, str(names))
    check("a card that went to zero is left out",
          "1985-86 O-Pee-Chee Mario Lemieux #9" not in names, str(names))
    check("and it is named rather than dropped silently",
          any("Lemieux" in entry["name"] for entry in built["skipped"]),
          str(built["skipped"]))
    check("with the reason attached",
          any("sold out" in entry["why"] for entry in built["skipped"]),
          str(built["skipped"]))
    check("the quantity sold is carried per card",
          [row["sold"] for row in built["rows"] if row["id"] == 2] == [2],
          str(built["rows"]))
    check("the SKU comes from the product",
          [row["sku"] for row in built["rows"] if row["id"] == 1] == ["BUR-133"],
          str(built["rows"]))
    check("the stock is carried for the list",
          [row["stock"] for row in built["rows"] if row["id"] == 1] == [1],
          str(built["rows"]))
    check("the gallery size is carried too",
          [row["images"] for row in built["rows"] if row["id"] == 1] == [2],
          str(built["rows"]))
    check("the queue keeps the order they were sold in",
          [row["id"] for row in built["rows"]] == [1, 2],
          str([row["id"] for row in built["rows"]]))


def test_from_order_names_what_it_cannot_read():
    print()
    print("== 4. a card the website cannot explain is named, not lost ==")
    #  The last line is a fee: no product behind it, so not a card at all.
    lines = [line(1, "Card one"), line(2, "Card two"), line(3, "Card three"),
             {"name": "Shipping", "quantity": 1}]
    products = {1: product(1, "Card one", stock=2),
                2: product(2, "Card two", manage=False)}
    built = photo_queue.from_order(order(lines), products)
    check("only the readable card is queued",
          [row["id"] for row in built["rows"]] == [1],
          str([row["id"] for row in built["rows"]]))
    why = {entry["id"]: entry["why"] for entry in built["skipped"]}
    check("a product the shop did not return is named", 3 in why, str(why))
    check("and says the stock could not be read",
          "could not be read" in why.get(3, ""), str(why.get(3)))
    check("a product with no stock tracking is named", 2 in why, str(why))
    check("and says why that leaves no count",
          "does not track" in why.get(2, ""), str(why.get(2)))
    check("a line with no product is not apologised for",
          sorted(why) == [2, 3], str(sorted(why)))
    empty = {"number": "1042", "rows": []}
    check("an order with nothing left says so in words",
          photo_queue.headline(empty, [], [], 0) ==
          "No card on order 1042 still needs a photograph.",
          photo_queue.headline(empty, [], [], 0))


def test_from_order_merges_duplicates():
    print()
    print("== 5. the same card twice is still one photograph ==")
    lines = [line(1, "Card one", quantity=1), line(1, "Card one", quantity=2)]
    built = photo_queue.from_order(order(lines), {1: product(1, "Card one",
                                                             stock=4)})
    check("one row", len(built["rows"]) == 1, str(built["rows"]))
    check("with the copies added up", built["rows"][0]["sold"] == 3,
          str(built["rows"][0].get("sold")))


def test_from_order_survives_junk():
    print()
    print("== 6. an order that is missing half its parts does not crash ==")
    built = photo_queue.from_order({}, {})
    check("an empty order is an empty queue", built["rows"] == [],
          str(built["rows"]))
    check("with no number", built["number"] == "", built["number"])
    built = photo_queue.from_order({"line_items": ["nonsense", None, 3]}, {})
    check("a line that is not a line is skipped", built["rows"] == [],
          str(built["rows"]))
    built = photo_queue.from_order(None, None)
    check("no order at all still answers", built["rows"] == [],
          str(built["rows"]))


def test_next_nine():
    print()
    print("== 7. nine at a time, in order ==")
    lines = [line(pid, "Card %d" % pid) for pid in range(1, 23)]
    products = {pid: product(pid, "Card %d" % pid, stock=2)
                for pid in range(1, 23)}
    built = photo_queue.from_order(order(lines), products)
    check("every card is in the queue", len(built["rows"]) == 22,
          str(len(built["rows"])))
    first, waiting = photo_queue.next_batch(built, [])
    check("the first sitting is nine", len(first) == 9, str(len(first)))
    check("the first nine are the first nine",
          [row["id"] for row in first] == list(range(1, 10)),
          str([row["id"] for row in first]))
    check("the rest wait", len(waiting) == 13, str(len(waiting)))

    done = [row["id"] for row in first]
    second, waiting = photo_queue.next_batch(built, done)
    check("the next sitting starts at the tenth card",
          [row["id"] for row in second] == list(range(10, 19)),
          str([row["id"] for row in second]))
    check("four are left behind that", len(waiting) == 4, str(len(waiting)))

    done += [row["id"] for row in second]
    third, waiting = photo_queue.next_batch(built, done)
    check("the last sitting is the odd four",
          [row["id"] for row in third] == [19, 20, 21, 22],
          str([row["id"] for row in third]))
    check("with nothing behind them", waiting == [], str(waiting))

    done += [row["id"] for row in third]
    last, waiting = photo_queue.next_batch(built, done)
    check("a finished order has no sitting", last == [], str(last))
    check("and says every card is done",
          photo_queue.headline(built, last, waiting, len(done)) ==
          "Every card on order 1042 has been photographed.",
          photo_queue.headline(built, last, waiting, len(done)))


def test_next_batch_tolerates_bad_memory():
    print()
    print("== 8. a memory that disagrees with the order is survived ==")
    built = photo_queue.from_order(
        order([line(pid, "Card %d" % pid) for pid in (1, 2, 3)]),
        {pid: product(pid, "Card %d" % pid) for pid in (1, 2, 3)})
    check("an unknown id in the memory simply does nothing",
          len(photo_queue.next_batch(built, [99, "junk", None])[0]) == 3,
          str(photo_queue.next_batch(built, [99])[0]))
    check("ids kept as text still match",
          [row["id"] for row in photo_queue.next_batch(built, ["1"])[0]] ==
          [2, 3], str(photo_queue.next_batch(built, ["1"])[0]))
    check("a size of zero does not mean everything", 1 == len(
        photo_queue.next_batch(built, [], size=0)[0]),
          str(photo_queue.next_batch(built, [], size=0)[0]))
    check("an empty queue has no sitting",
          photo_queue.next_batch({}, [])[0] == [])


def test_still_to_do():
    print()
    print("== 9. what still needs a photograph ==")
    built = photo_queue.from_order(
        order([line(pid, "Card %d" % pid) for pid in (1, 2, 3)]),
        {pid: product(pid, "Card %d" % pid) for pid in (1, 2, 3)})
    left = photo_queue.still_to_do(built, ["2"])
    check("a photographed card drops out",
          [row["id"] for row in left] == [1, 3],
          str([row["id"] for row in left]))
    check("no memory means everything is left",
          len(photo_queue.still_to_do(built, None)) == 3)


def test_move():
    print()
    print("== 10. the nine can be reordered before the sheet is split ==")
    rows = [{"id": n} for n in (1, 2, 3, 4, 5)]
    landed = photo_queue.move(rows, 2, -1)
    check("moving up swaps with the one above",
          [row["id"] for row in rows] == [1, 3, 2, 4, 5],
          str([row["id"] for row in rows]))
    check("and says where the row landed", landed == 1, str(landed))
    landed = photo_queue.move(rows, 1, 1)
    check("moving down swaps back",
          [row["id"] for row in rows] == [1, 2, 3, 4, 5],
          str([row["id"] for row in rows]))
    check("the row followed the move", landed == 2, str(landed))
    check("the first row cannot move up",
          photo_queue.move(rows, 0, -1) == 0 and
          [row["id"] for row in rows] == [1, 2, 3, 4, 5],
          str([row["id"] for row in rows]))
    check("the last row cannot move down",
          photo_queue.move(rows, 4, 1) == 4 and
          [row["id"] for row in rows] == [1, 2, 3, 4, 5],
          str([row["id"] for row in rows]))
    check("a row that is not there does nothing",
          photo_queue.move(rows, 9, 1) == 9,
          str(photo_queue.move(rows, 9, 1)))
    check("no rows at all does nothing", photo_queue.move([], 0, 1) == 0)
    check("nonsense index does not crash",
          photo_queue.move(rows, "first", 1) == "first",
          str(photo_queue.move(rows, "first", 1)))


def test_describe_batch():
    print()
    print("== 11. the list the panel shows ==")
    rows = [{"id": 1, "name": "1972-73 O-Pee-Chee Dave Burrows #133",
             "sku": "BUR-133", "stock": 1},
            {"id": 2, "name": "1979-80 O-Pee-Chee  Wayne Gretzky   #18",
             "sku": "", "stock": 12}]
    lines = photo_queue.describe_batch(rows)
    check("one line per card", len(lines) == 2, str(lines))
    check("numbered from one", lines[0].startswith("1. "), lines[0])
    check("the SKU is shown when there is one", "BUR-133" in lines[0],
          lines[0])
    check("no empty brackets when there is not", "[" not in lines[1], lines[1])
    check("the stock is shown", "1 in stock" in lines[0], lines[0])
    check("and a bigger count reads plainly", "12 in stock" in lines[1],
          lines[1])
    check("a card with no stock number says so",
          "stock unknown" in photo_queue.describe_batch(
              [{"id": 3, "name": "x", "stock": None}])[0],
          str(photo_queue.describe_batch([{"id": 3, "name": "x",
                                           "stock": None}])))
    check("nothing to show is an empty list",
          photo_queue.describe_batch([]) == [])


def test_headline():
    print()
    print("== 12. which nine is this run ==")
    built = photo_queue.from_order(
        order([line(pid, "Card %d" % pid) for pid in range(1, 13)]),
        {pid: product(pid, "Card %d" % pid) for pid in range(1, 13)})
    batch, waiting = photo_queue.next_batch(built, [])
    said = photo_queue.headline(built, batch, waiting, 0)
    check("it names the order", "Order 1042" in said, said)
    check("it says how many are in this sitting", "9 cards in this sitting" in said,
          said)
    check("it says how many wait behind", "3 behind" in said, said)
    said = photo_queue.headline({}, [], [], 0)
    check("an empty queue asks for an order number", "No queue yet" in said,
          said)
    said = photo_queue.headline({"number": "1042", "rows": []}, [], [], 0)
    check("an order with no cards left says that instead of asking for one",
          said == "No card on order 1042 still needs a photograph.", said)
    done = [row["id"] for row in batch]
    said = photo_queue.headline(built, batch, waiting, len(done))
    check("a second sitting mentions what is already done",
          "9 already photographed" in said, said)
    said = photo_queue.headline(built, [], [], 12)
    check("a finished order is congratulated once",
          said == "Every card on order 1042 has been photographed.", said)
    said = photo_queue.headline(built, [], waiting, 9)
    check("cards waiting with nothing in the sitting are counted",
          "9 cards photographed; 3 still waiting" in said, said)
    check("one card is not \"1 cards\"",
          "1 card in this sitting" in photo_queue.headline(
              built, batch[:1], batch[1:], 0),
          photo_queue.headline(built, batch[:1], batch[1:], 0))


def test_state_round_trip(root):
    print()
    print("== 13. what has been photographed is remembered ==")
    path = Path(root) / "nested" / photo_queue.STATE_NAME
    state = {"orders": {}}
    check("nothing remembered is nothing done",
          photo_queue.done_for(state, "1042") == [],
          str(photo_queue.done_for(state, "1042")))
    photo_queue.remember(state, "1042", [1, 2, "3"])
    check("remembered ids come back as text",
          photo_queue.done_for(state, "1042") == ["1", "2", "3"],
          str(photo_queue.done_for(state, "1042")))
    photo_queue.remember(state, "1042", [3, 4])
    check("remembering the same card twice does not double it",
          photo_queue.done_for(state, "1042") == ["1", "2", "3", "4"],
          str(photo_queue.done_for(state, "1042")))
    photo_queue.remember(state, "1050", [9])
    check("another order keeps its own list",
          photo_queue.done_for(state, "1050") == ["9"],
          str(photo_queue.done_for(state, "1050")))

    saved = photo_queue.save_state(path, state)
    check("the file is written where it was asked for", saved == path,
          str(saved))
    check("the folder is made on the way", path.is_file(), str(path))
    check("the file reads back",
          photo_queue.done_for(photo_queue.load_state(path), "1042") ==
          ["1", "2", "3", "4"])
    check("the file is JSON a person can read",
          json.loads(path.read_text(encoding="utf-8"))["orders"]["1042"]
          ["done"] == ["1", "2", "3", "4"],
          path.read_text(encoding="utf-8"))

    photo_queue.forget(state, "1042")
    check("forgetting an order offers every card again",
          photo_queue.done_for(state, "1042") == [],
          str(photo_queue.done_for(state, "1042")))
    check("and leaves the other order alone",
          photo_queue.done_for(state, "1050") == ["9"])
    photo_queue.forget(state, "not there")
    check("forgetting an order that was never built is harmless",
          photo_queue.done_for(state, "1050") == ["9"])


def test_state_survives_damage(root):
    print()
    print("== 14. a memory file that is damaged costs nothing ==")
    path = Path(root) / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    check("an unreadable file remembers nothing",
          photo_queue.load_state(path) == {"orders": {}},
          str(photo_queue.load_state(path)))
    path.write_text('[1, 2, 3]', encoding="utf-8")
    check("a file holding the wrong shape remembers nothing",
          photo_queue.load_state(path) == {"orders": {}},
          str(photo_queue.load_state(path)))
    path.write_text('{"orders": {"1042": {"done": ["1"]}}}', encoding="utf-8")
    state = photo_queue.load_state(path)
    check("a good file is used", photo_queue.done_for(state, "1042") == ["1"],
          str(state))
    check("a file that is not there remembers nothing",
          photo_queue.load_state(Path(root) / "missing.json") == {"orders": {}})
    photo_queue.remember({}, "1", [2])
    check("remembering on nothing starts a fresh memory", True)
    check("an order with no number still keys cleanly",
          photo_queue.done_for({"orders": {"": {"done": ["5"]}}}, "") == ["5"],
          str(photo_queue.done_for({"orders": {"": {"done": ["5"]}}}, "")))


def test_state_is_trimmed(root):
    print()
    print("== 15. the memory keeps the orders recently worked on ==")
    state = {"orders": {}}
    for number in range(photo_queue.STATE_LIMIT + 5):
        photo_queue.remember(state, str(number), [number])
    path = photo_queue.save_state(Path(root) / "trim.json", state)
    kept = photo_queue.load_state(path)["orders"]
    check("the file does not grow past its limit",
          len(kept) == photo_queue.STATE_LIMIT, str(len(kept)))
    check("the newest order is kept",
          str(photo_queue.STATE_LIMIT + 4) in kept, str(list(kept)[-3:]))
    check("the oldest order is dropped", "0" not in kept, str(sorted(kept)[:3]))
    check("the order just worked on is the last one kept",
          list(kept)[-1] == str(photo_queue.STATE_LIMIT + 4),
          str(list(kept)[-1]))
    check("a state that cannot be written says so in words",
          _raises(photo_queue.QueueError, photo_queue.save_state,
                  Path(root) / "trim.json" / "nope" / "x.json", state))


def _raises(kind, func, *args):
    try:
        func(*args)
    except kind:
        return True
    except Exception:
        return False
    return False


def test_two_sittings(root):
    print()
    print("== 16. a second sitting carries on where the first stopped ==")
    path = Path(root) / "sitting.json"
    lines = [line(pid, "Card %d" % pid) for pid in range(1, 15)]
    products = {pid: product(pid, "Card %d" % pid, stock=5)
                for pid in range(1, 15)}
    built = photo_queue.from_order(order(lines), products)
    state = photo_queue.load_state(path)

    batch, waiting = photo_queue.next_batch(built, photo_queue.done_for(
        state, built["number"]))
    check("the first sitting is nine", len(batch) == 9, str(len(batch)))
    photo_queue.remember(state, built["number"], [row["id"] for row in batch])
    photo_queue.save_state(path, state)

    state = photo_queue.load_state(path)
    batch, waiting = photo_queue.next_batch(built, photo_queue.done_for(
        state, built["number"]))
    check("the second sitting starts at the tenth",
          [row["id"] for row in batch] == list(range(10, 15)),
          str([row["id"] for row in batch]))
    check("and it is named as five, not nine",
          "5 cards in this sitting" in photo_queue.headline(
              built, batch, waiting, 9),
          photo_queue.headline(built, batch, waiting, 9))

    photo_queue.remember(state, built["number"], [row["id"] for row in batch])
    photo_queue.save_state(path, state)
    state = photo_queue.load_state(path)
    batch, waiting = photo_queue.next_batch(built, photo_queue.done_for(
        state, built["number"]))
    check("a photographed order has nothing left", batch == [], str(batch))


def main():
    root = Path(tempfile.mkdtemp(prefix="photo-queue-"))
    try:
        test_sheet_is_nine()
        test_stock_of()
        test_from_order_keeps_what_can_be_sold()
        test_from_order_names_what_it_cannot_read()
        test_from_order_merges_duplicates()
        test_from_order_survives_junk()
        test_next_nine()
        test_next_batch_tolerates_bad_memory()
        test_still_to_do()
        test_move()
        test_describe_batch()
        test_headline()
        test_state_round_trip(root)
        test_state_survives_damage(root)
        test_state_is_trimmed(root)
        test_two_sittings(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print()
    print("=" * 60)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASSED))
        return 1
    print("ALL PHOTO QUEUE CHECKS PASSED (%d)" % PASSED)
    return 0


if __name__ == "__main__":
    sys.exit(main())
