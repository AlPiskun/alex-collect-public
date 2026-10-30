"""Checks for photo_assign: the worksheet that lines images up with products.

    python test-photo-assign.py

No tkinter and no store: the pool is built from real sheets on disk, and the
products are the plain dictionaries a website search returns. The cards arrive
in an order - the nine the photo queue picked out of an order, or the names
pasted into the panel - and the worksheet has to keep that order, put a product
on every row it can, and keep the words of the ones it cannot.
"""

import shutil
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:                                   # pragma: no cover
    print("Pillow is required for these checks.")
    raise SystemExit(1)

import photo_assign
import photo_pool

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


def make_sheet(path, blanks=()):
    """A page-shaped 3x3 sheet, so the split finds cards instead of squares."""
    cell_w = 600
    cell_h = int(cell_w * 1.414)
    sheet = Image.new("RGB", (cell_w * 3, cell_h * 3 + 400), (0, 0, 0))
    position = 1
    for row in range(3):
        for col in range(3):
            if position not in blanks:
                sheet.paste((235, 230, 220),
                            (col * cell_w + 80, row * cell_h + 80,
                             (col + 1) * cell_w - 80, (row + 1) * cell_h - 80))
            position += 1
    sheet.save(path)
    return path


def product(pid, name, sku=""):
    return {"id": pid, "name": name, "sku": sku, "images": []}


_LOADED = {}


def loaded(root):
    """A pool holding one front sheet with seven cards and one back sheet.

    Split once and shared: reading two sheets per check would make this file
    take a minute to run, and nothing here changes the pool.
    """
    if "pool" not in _LOADED:
        front = make_sheet(Path(root) / "front-1.jpg", blanks=(2, 9))
        back = make_sheet(Path(root) / "back-1.jpg", blanks=(2, 9))
        pool = photo_pool.PhotoPool(tiles_dir=Path(root) / "tiles")
        pool.add_sheet(front, side="front")
        pool.add_sheet(back, side="back")
        _LOADED["pool"] = pool
    return _LOADED["pool"]


# ------------------------------------------------------------------ the tiles
def test_front_tiles(root):
    print()
    print("== 1. a card is named once, from the front images ==")
    pool = loaded(root)
    tiles = photo_assign.front_tiles(pool)
    check("only the front sheet's cards are lined up", len(tiles) == 7,
          str(len(tiles)))
    check("no back is offered as a card of its own",
          all(tile["side"] == "front" for tile in tiles),
          str([tile["side"] for tile in tiles]))
    check("the blank slots are not cards",
          [tile["position"] for tile in tiles] == [1, 3, 4, 5, 6, 7, 8],
          str([tile["position"] for tile in tiles]))
    check("they come in the order the sheet was read",
          [tile["position"] for tile in tiles] ==
          sorted(tile["position"] for tile in tiles),
          str([tile["position"] for tile in tiles]))


def test_front_tiles_with_unmarked_sheets(root):
    print()
    print("== 2. a sheet nobody marked still holds cards ==")
    pool = photo_pool.PhotoPool()
    #  A pool whose split returns a known set: the sheet is not read here.
    pool._tiles = [
        {"position": 3, "path": Path("c"), "sheet": "s2", "side": "",
         "used_by": ""},
        {"position": 1, "path": Path("a"), "sheet": "s1", "side": "front",
         "used_by": ""},
        {"position": 2, "path": Path("b"), "sheet": "s1", "side": "",
         "used_by": ""},
        {"position": 1, "path": Path("d"), "sheet": "s1", "side": "back",
         "used_by": ""},
    ]
    tiles = photo_assign.front_tiles(pool)
    check("a marked front comes before an unmarked image",
          [str(tile["path"]) for tile in tiles][0] == "a",
          str([str(tile["path"]) for tile in tiles]))
    check("the back is left out",
          all(str(tile["path"]) != "d" for tile in tiles),
          str([str(tile["path"]) for tile in tiles]))
    check("unmarked images follow, sheet by sheet",
          [str(tile["path"]) for tile in tiles] == ["a", "b", "c"],
          str([str(tile["path"]) for tile in tiles]))
    check("an empty pool holds no cards",
          photo_assign.front_tiles(photo_pool.PhotoPool()) == [])


# --------------------------------------------------------------- the worksheet
def test_cards_line_up_with_images(root):
    print()
    print("== 3. the Nth card goes on the Nth image ==")
    pool = loaded(root)
    cards = [product(11, "1972-73 O-Pee-Chee Dave Burrows #133", "BUR-133"),
             product(12, "1979-80 O-Pee-Chee Wayne Gretzky #18"),
             product(13, "1985-86 O-Pee-Chee Mario Lemieux #9")]
    rows = photo_assign.rows_from_products(pool, cards)
    check("one row per image", len(rows) == 7, str(len(rows)))
    check("the first three rows hold the three cards",
          [row["status"] for row in rows[:3]] == [photo_assign.MATCHED] * 3,
          str([row["status"] for row in rows[:3]]))
    check("the row carries the product",
          [row["product"]["id"] for row in rows[:3]] == [11, 12, 13],
          str([row["product"] for row in rows[:3]]))
    check("the row says which card it is",
          rows[0]["title"] == "1972-73 O-Pee-Chee Dave Burrows #133",
          rows[0]["title"])
    check("in the order the cards were given",
          [row["title"].split()[-1] for row in rows[:3]] ==
          ["#133", "#18", "#9"], str([row["title"] for row in rows[:3]]))
    check("the images left over have no card on them",
          [row["status"] for row in rows[3:]] == [photo_assign.EMPTY] * 4,
          str([row["status"] for row in rows[3:]]))
    check("and say so in the row's own words",
          rows[3]["title"] == "" and rows[3]["product"] is None,
          str(rows[3]))
    check("every row keeps the tile it belongs to",
          [row["tile"]["position"] for row in rows] ==
          [1, 3, 4, 5, 6, 7, 8], str([row["tile"]["position"] for row in rows]))


def test_a_card_that_matched_nothing_keeps_its_words(root):
    print()
    print("== 4. a card the search could not find is still on the page ==")
    pool = loaded(root)
    cards = [product(11, "1972-73 O-Pee-Chee Dave Burrows #133"), None, None]
    names = ["", "1990 Score Mario Lemieux #2"]
    rows = photo_assign.rows_from_products(pool, cards, names)
    check("the row is kept rather than dropped", len(rows) == 7,
          str(len(rows)))
    check("it says the search found nothing",
          rows[1]["status"] == photo_assign.MISSING, rows[1]["status"])
    check("and keeps the words that were typed",
          rows[1]["title"] == "1990 Score Mario Lemieux #2", rows[1]["title"])
    check("with no product attached", rows[1]["product"] is None,
          str(rows[1]["product"]))
    check("the matched card still has its product",
          rows[0]["product"]["id"] == 11, str(rows[0]["product"]))
    check("the card with no words and no match is \"no card\"",
          rows[2]["status"] == photo_assign.EMPTY, rows[2]["status"])


def test_the_products_name_wins(root):
    print()
    print("== 5. the website's own name is the one shown ==")
    pool = loaded(root)
    cards = [product(11, "1979-80 O-Pee-Chee Wayne Gretzky #18")]
    rows = photo_assign.rows_from_products(
        pool, cards, ["gretzky 1979 opc 18"])
    check("the product's name is used",
          rows[0]["title"] == "1979-80 O-Pee-Chee Wayne Gretzky #18",
          rows[0]["title"])


def test_more_images_than_cards(root):
    print()
    print("== 6. seven images, two cards ==")
    pool = loaded(root)
    rows = photo_assign.rows_from_products(
        pool, [product(11, "Card one"), product(12, "Card two")],
        ["Card one", "Card two"])
    check("two matched and five waiting for a card",
          photo_assign.summary(rows) == {photo_assign.MATCHED: 2,
                                         photo_assign.MISSING: 0,
                                         photo_assign.EMPTY: 5},
          str(photo_assign.summary(rows)))


def test_more_cards_than_images(root):
    print()
    print("== 7. more cards than images leaves the extra cards off ==")
    pool = loaded(root)
    cards = [product(11, "Card one"), product(12, "Card two")]
    rows = photo_assign.rows_from_products(
        pool, cards, ["Card one", "Card two"])
    check("one row per image, not per card", len(rows) == 7, str(len(rows)))
    check("the first two are the two cards",
          [row["status"] for row in rows[:2]] == [photo_assign.MATCHED] * 2,
          str([row["status"] for row in rows[:2]]))


def test_no_cards_at_all(root):
    print()
    print("== 8. a sitting with nothing named yet ==")
    pool = loaded(root)
    rows = photo_assign.rows_from_products(pool, None, None)
    check("every image is a row", len(rows) == 7, str(len(rows)))
    check("none of them has a card",
          photo_assign.summary(rows)[photo_assign.EMPTY] == 7,
          str(photo_assign.summary(rows)))
    check("and the window says so", photo_assign.headline(rows) ==
          "7 with no card", photo_assign.headline(rows))


def test_a_product_with_no_id_is_not_a_card(root):
    print()
    print("== 9. a half-read product is not applied ==")
    pool = loaded(root)
    rows = photo_assign.rows_from_products(
        pool, [{"name": "no id here"}], ["typed words"])
    check("the row is a miss, not a match",
          rows[0]["status"] == photo_assign.MISSING, rows[0]["status"])
    check("with the typed words kept", rows[0]["title"] == "typed words",
          rows[0]["title"])
    check("and nothing to apply",
          photo_assign.ready(rows) == [], str(photo_assign.ready(rows)))


# --------------------------------------------------------------- the decisions
def test_summary(root):
    print()
    print("== 10. the counts under the list ==")
    rows = [{"status": photo_assign.MATCHED}, {"status": photo_assign.MATCHED},
            {"status": photo_assign.MISSING}, {"status": photo_assign.EMPTY}]
    check("every status is counted",
          photo_assign.summary(rows) == {photo_assign.MATCHED: 2,
                                         photo_assign.MISSING: 1,
                                         photo_assign.EMPTY: 1},
          str(photo_assign.summary(rows)))
    check("an empty worksheet counts nothing",
          photo_assign.summary([]) == {photo_assign.MATCHED: 0,
                                       photo_assign.MISSING: 0,
                                       photo_assign.EMPTY: 0},
          str(photo_assign.summary([])))
    check("a row with no status counts as a miss rather than crashing",
          photo_assign.summary([{}])[photo_assign.MISSING] == 1,
          str(photo_assign.summary([{}])))


def test_ready(root):
    print()
    print("== 11. only a matched card is applied without asking ==")
    pool = loaded(root)
    cards = [product(11, "Card one"), None]
    rows = photo_assign.rows_from_products(pool, cards, ["", "Card two"])
    ready = photo_assign.ready(rows)
    check("one row is ready", len(ready) == 1, str(len(ready)))
    check("and it is the matched one", ready[0]["product"]["id"] == 11,
          str(ready[0]["product"]))
    check("a matched row with no image is not ready",
          photo_assign.ready([{"status": photo_assign.MATCHED,
                               "product": {"id": 1}, "tile": None},
                              {"status": photo_assign.MATCHED,
                               "product": {"id": 2}, "tile": {"position": 1}}])
          == [{"status": photo_assign.MATCHED, "product": {"id": 2},
               "tile": {"position": 1}}],
          str(photo_assign.ready([{"status": photo_assign.MATCHED,
                                   "product": {"id": 1}, "tile": None}])))
    check("nothing ready is an empty list", photo_assign.ready([]) == [])


def test_headline(root):
    print()
    print("== 12. the one line the window shows ==")
    rows = [{"status": photo_assign.MATCHED}, {"status": photo_assign.MATCHED},
            {"status": photo_assign.MISSING}, {"status": photo_assign.EMPTY}]
    said = photo_assign.headline(rows)
    check("it says how many are ready", "2 ready" in said, said)
    check("how many matched nothing", "1 matched nothing" in said, said)
    check("and how many have no card", "1 with no card" in said, said)
    check("in that order",
          said.index("ready") < said.index("matched nothing") <
          said.index("no card"), said)
    check("a worksheet with nothing on it says so",
          photo_assign.headline([]) == "nothing to assign",
          photo_assign.headline([]))
    check("only the counts that are there are mentioned",
          photo_assign.headline([{"status": photo_assign.MATCHED}]) ==
          "1 ready", photo_assign.headline([{"status": photo_assign.MATCHED}]))


def test_replace_title(root):
    print()
    print("== 13. a row can be pointed at a card by hand ==")
    pool = loaded(root)
    rows = photo_assign.rows_from_products(pool, [None], ["Card one"])
    check("the row starts as a miss",
          rows[0]["status"] == photo_assign.MISSING, rows[0]["status"])
    picked = product(31, "1986-87 O-Pee-Chee Patrick Roy #53", "ROY-53")
    check("picking a card returns True",
          photo_assign.replace_title(rows, 0, picked) is True)
    check("the row is now matched",
          rows[0]["status"] == photo_assign.MATCHED, rows[0]["status"])
    check("and the product is the one picked",
          rows[0]["product"]["id"] == 31, str(rows[0]["product"]))
    check("so the row can be applied",
          len(photo_assign.ready(rows)) == 1,
          str(photo_assign.ready(rows)))
    check("a product with no id un-matches the row",
          photo_assign.replace_title(rows, 0, {"name": "nothing"}) is True and
          rows[0]["status"] == photo_assign.MISSING, rows[0]["status"])
    check("a row that is not there is refused",
          photo_assign.replace_title(rows, 99, picked) is False)
    check("and the rows are untouched by that", len(rows) == 7, str(len(rows)))


def test_a_second_sitting(root):
    print()
    print("== 14. the next nine images re-use the same worksheet ==")
    pool = loaded(root)
    cards = [product(11, "Card one"), product(12, "Card two")]
    first = photo_assign.rows_from_products(pool, cards, ["", ""])
    check("the sitting names two cards",
          photo_assign.summary(first)[photo_assign.MATCHED] == 2,
          str(photo_assign.summary(first)))
    second = photo_assign.rows_from_products(
        pool, [product(13, "Card three")], ["Card three"])
    check("a new worksheet starts from the same images",
          len(second) == 7, str(len(second)))
    check("and does not inherit the first one's matches",
          photo_assign.summary(second)[photo_assign.MATCHED] == 1,
          str(photo_assign.summary(second)))


def test_nothing_reads_the_sheet(root):
    print()
    print("== 15. the sheet's titles are not read here any more ==")
    gone = [name for name in ("propose", "parse_titles", "rows_from_titles",
                              "clear_winner", "CHOOSE", "CLOSE_CALL",
                              "_strip_bullet")
            if hasattr(photo_assign, name)]
    check("nothing in the module reads the sheet's titles", gone == [],
          str(gone))
    check("a row is matched by a product, or left for a person",
          photo_assign.MATCHED != photo_assign.MISSING and
          photo_assign.MISSING != photo_assign.EMPTY,
          "%s %s %s" % (photo_assign.MATCHED, photo_assign.MISSING,
                        photo_assign.EMPTY))


def main():
    root = Path(tempfile.mkdtemp(prefix="photo-assign-"))
    try:
        test_front_tiles(root)
        test_front_tiles_with_unmarked_sheets(root)
        test_cards_line_up_with_images(root)
        test_a_card_that_matched_nothing_keeps_its_words(root)
        test_the_products_name_wins(root)
        test_more_images_than_cards(root)
        test_more_cards_than_images(root)
        test_no_cards_at_all(root)
        test_a_product_with_no_id_is_not_a_card(root)
        test_summary(root)
        test_ready(root)
        test_headline(root)
        test_replace_title(root)
        test_a_second_sitting(root)
        test_nothing_reads_the_sheet(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print()
    print("=" * 60)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASSED))
        return 1
    print("ALL PHOTO ASSIGN CHECKS PASSED (%d)" % PASSED)
    return 0


if __name__ == "__main__":
    sys.exit(main())
