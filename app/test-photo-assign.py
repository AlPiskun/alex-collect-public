"""Checks for photo_assign: the worksheet that lines images up with products.

    python test-photo-assign.py

No tkinter and no store: the pool is built from real sheets on disk, and
``search`` is a stub that matches word-wise the way a real product search does.
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


STORE = [
    {"id": 1, "name": "1972-73 O-Pee-Chee Dave Burrows #133 Rookie Card"},
    {"id": 2, "name": "1979-80 O-Pee-Chee Wayne Gretzky #18"},
    {"id": 3, "name": "1985-86 O-Pee-Chee Mario Lemieux #9"},
    {"id": 4, "name": "1986-87 O-Pee-Chee Patrick Roy #53"},
    {"id": 5, "name": "1958-59 Topps Bobby Hull #8"},
    #  A second card number 18, so a title that gives only the set and the
    #  number genuinely fits two cards and must not be picked for the user.
    {"id": 6, "name": "1990-91 O-Pee-Chee Jaromir Jagr #18"},
]


def words(text):
    return set(str(text).lower().replace("-", " ").split())


def search(term):
    """A shop search that matches words, like WooCommerce does."""
    wanted = words(term)
    if not wanted:
        return []
    found = [p for p in STORE if wanted <= words(p["name"])]
    return found or [p for p in STORE if len(wanted & words(p["name"])) >= 2]


def test_titles():
    print()
    print("== 1. reading the AI's titles off a pasted answer ==")
    text = ("1. 1972-73 O-Pee-Chee Dave Burrows #133 Rookie Card\n"
            "2) 1979-80 O-Pee-Chee Wayne Gretzky #18\n"
            "\n"
            "- 1985-86 O-Pee-Chee Mario Lemieux #9\n"
            "   \n"
            "1986-87 O-Pee-Chee Patrick Roy #53\n")
    titles = photo_assign.parse_titles(text)
    check("one title per line, numbering dropped", titles[0] ==
          "1972-73 O-Pee-Chee Dave Burrows #133 Rookie Card", str(titles))
    check("a bracket number is dropped too", titles[1].startswith("1979-80"),
          str(titles))
    check("a bullet is dropped", titles[2].startswith("1985-86"), str(titles))
    check("blank lines are ignored", len(titles) == 4, str(titles))
    check("an unnumbered title is kept whole", titles[3].startswith("1986-87"),
          str(titles))
    check("a leading card number without a dot survives",
          photo_assign.parse_titles("#133 Dave Burrows")[0] == "#133 Dave Burrows",
          photo_assign.parse_titles("#133 Dave Burrows"))
    check("nothing pasted means no titles",
          photo_assign.parse_titles("") == [] and
          photo_assign.parse_titles(None) == [])


def test_worksheet(root):
    print()
    print("== 2. the images become one row each, in slot order ==")
    front = make_sheet(root / "Scan-front.jpg", blanks=(2, 9))
    back = make_sheet(root / "Scan-back.jpg", blanks=(2, 9))
    pool = photo_pool.PhotoPool(tiles_dir=root / "tiles")
    pool.add_sheet(front, index=0)
    pool.add_sheet(back, index=1)
    tiles = photo_assign.front_tiles(pool)
    check("only the front sheet's images are paired with titles",
          len(tiles) == 7 and all(t["side"] == "front" for t in tiles),
          str([(t["sheet"], t["position"]) for t in tiles]))
    check("they are in reading order",
          [t["position"] for t in tiles] == [1, 3, 4, 5, 6, 7, 8],
          str([t["position"] for t in tiles]))

    titles = ["1972-73 O-Pee-Chee Dave Burrows #133 Rookie Card",
              "1979-80 O-Pee-Chee Wayne Gretzky #18",
              "1985-86 O-Pee-Chee Mario Lemieux #9"]
    rows = photo_assign.rows_from_titles(pool, titles, search)
    check("every image gets a row, not just the titled ones", len(rows) == 7,
          str(len(rows)))
    check("the first row is the first slot", rows[0]["tile"]["position"] == 1)
    check("a clear title is matched to its card",
          rows[0]["product"]["id"] == 1, str(rows[0]["product"]))
    check("matched rows are ready to apply",
          rows[0]["status"] == photo_assign.MATCHED, rows[0]["status"])
    check("the second card is matched too",
          rows[1]["product"]["id"] == 2, str(rows[1]["product"]))
    check("an image with no title is left waiting, not guessed",
          rows[3]["status"] == photo_assign.EMPTY and
          rows[3]["product"] is None, str(rows[3]["status"]))

    line = photo_assign.headline(rows)
    check("the headline counts what is ready", "3 ready" in line, line)
    check("and what is still waiting", "4 with no title" in line, line)
    check("only matched rows are applied",
          [r["product"]["id"] for r in photo_assign.ready(rows)] == [1, 2, 3],
          str([r["product"]["id"] for r in photo_assign.ready(rows)]))


def test_uncertain(root):
    print()
    print("== 3. an unsure match is offered, never applied by itself ==")
    pool = photo_pool.PhotoPool(tiles_dir=root / "t2")
    pool.add_sheet(make_sheet(root / "Scan-02.jpg"), index=0)
    rows = photo_assign.rows_from_titles(
        pool, ["O-Pee-Chee #18"], search)
    check("a title that fits two cards is not applied",
          rows[0]["status"] == photo_assign.CHOOSE, rows[0]["status"])
    check("both cards are offered as candidates",
          len(rows[0]["candidates"]) == 2, str(rows[0]["candidates"]))
    check("an unsure row is never applied in a batch",
          photo_assign.ready(rows) == [], str(photo_assign.ready(rows)))
    check("its candidates are kept for the user to choose from",
          rows[0]["candidates"], str(rows[0]["candidates"]))

    rows = photo_assign.rows_from_titles(pool, ["Totally Unknown Card"], search)
    check("a title that matches nothing says so",
          rows[0]["status"] == photo_assign.MISSING, rows[0]["status"])
    check("and carries no product", rows[0]["product"] is None)

    check("choosing by hand makes a row ready",
          photo_assign.replace_title(rows, 0, STORE[1]) and
          rows[0]["status"] == photo_assign.MATCHED and
          rows[0]["product"]["id"] == 2)
    check("an out-of-range row is refused",
          photo_assign.replace_title(rows, 99, STORE[0]) is False)


def test_cards_first(root):
    print()
    print("== 4. cards first: a product list fills the same worksheet ==")
    pool = photo_pool.PhotoPool(tiles_dir=root / "t3")
    pool.add_sheet(make_sheet(root / "Scan-03.jpg"), index=0)
    products = [STORE[1], STORE[2], STORE[3]]
    rows = photo_assign.rows_from_products(pool, products)
    check("the Nth product goes with the Nth image",
          [r["product"]["id"] for r in rows[:3]] == [2, 3, 4],
          str([(r["product"] or {}).get("id") for r in rows[:3]]))
    check("every product row is ready",
          all(r["status"] == photo_assign.MATCHED for r in rows[:3]),
          str([r["status"] for r in rows[:3]]))
    check("the images left over wait for something to be said",
          rows[3]["status"] == photo_assign.EMPTY, rows[3]["status"])
    check("a shorter list than images is not padded",
          photo_assign.rows_from_products(pool, [])[0]["product"] is None)


def main():
    root = Path(tempfile.mkdtemp(prefix="photo-assign-"))
    try:
        test_titles()
        test_worksheet(root)
        test_uncertain(root)
        test_cards_first(root)
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
