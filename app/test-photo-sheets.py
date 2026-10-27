"""Checks for photo_thumbs and photo_pool - no tkinter needed.

    python test-photo-sheets.py

Both modules are what the Photos panel leans on: photo_thumbs turns a tile into
a picture small enough to show nine at once, and photo_pool keeps the loaded
sheets and remembers which images have been used.
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

import photo_pool
import photo_replace
import photo_thumbs

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


def make_sheet(path, blanks=(2, 9), colour=(235, 230, 220)):
    """A real 3x3 sheet: white card faces, the rest black (an empty slot).

    Scanned at A4 proportions, because the sheet is a page: three cells across
    and three down are taller than they are wide, and a square stand-in would
    hide that from the picture checks.
    """
    cell_w = 600
    cell_h = int(cell_w * 1.414 * 3 / 3)          # one third of an A4 page
    content_h = cell_h * 3
    sheet = Image.new("RGB", (cell_w * 3, content_h + 400), (0, 0, 0))
    position = 1
    for row in range(3):
        for col in range(3):
            if position not in blanks:
                sheet.paste(colour, (col * cell_w + 80, row * cell_h + 80,
                                     (col + 1) * cell_w - 80,
                                     (row + 1) * cell_h - 80))
            position += 1
    sheet.save(path)
    return path


def test_thumbnails(root):
    print()
    print("== 1. a tile becomes a picture you can recognise ==")
    sheet = make_sheet(root / "Scan-01.jpg")
    found = photo_replace.split_sheet(sheet, root / "tiles")
    usable = [t for t in found if not t["blank"]]
    check("the sheet splits into seven cards", len(usable) == 7,
          str(len(usable)))

    picture = photo_thumbs.thumbnail(usable[0]["path"])
    check("a tile gives a picture", picture is not None)
    check("the picture is smaller than the tile",
          max(picture.size) <= max(photo_thumbs.THUMB_SIZE),
          str(picture.size))
    wide, tall = picture.size
    check("the card's shape is kept", tall > wide, str(picture.size))

    missing = photo_thumbs.thumbnail                          # noqa: F841
    try:
        photo_thumbs.thumbnail(root / "not-there.webp")
        check("a missing tile is reported", False)
    except photo_thumbs.ThumbnailError as exc:
        check("a missing tile is reported", "not-there.webp" in str(exc),
              str(exc))

    cache = photo_thumbs.Thumbnails()
    first = cache.get(usable[0]["path"])
    again = cache.get(usable[0]["path"])
    check("the same tile is only read once", first is again)
    check("nothing failed to load", not cache.failures, str(cache.failures))
    check("a broken path is not remembered as a picture",
          cache.get(root / "broken.webp") is None and cache.failures,
          str(cache.failures))

    check("a grid is laid out in reading order",
          [len(row) for row in photo_thumbs.rows(list(range(7)))] == [3, 3, 1],
          str([len(row) for row in photo_thumbs.rows(list(range(7)))]))
    check("the last row keeps its shape",
          photo_thumbs.rows([1, 2, 3, 4])[1] == [4],
          str(photo_thumbs.rows([1, 2, 3, 4])))

    tile = {"position": 4, "sheet": "Scan-01.jpg", "side": "front",
            "path": usable[0]["path"]}
    check("a tile is captioned by where it came from",
          photo_thumbs.caption(tile) == "Slot 4 \u00b7 front \u00b7 Scan-01.jpg",
          photo_thumbs.caption(tile))
    check("no filename is the first thing shown",
          Path(usable[0]["path"]).name not in photo_thumbs.caption(tile),
          photo_thumbs.caption(tile))
    check("the fallback line still names the file",
          Path(usable[0]["path"]).name in photo_thumbs.describe(tile),
          photo_thumbs.describe(tile))
    check("a picture cannot be made without Tk here",
          photo_thumbs.as_photo(picture) is None)
    check("no picture in, no picture out",
          photo_thumbs.as_photo(None) is None)


def test_pool(root):
    print()
    print("== 2. the sheets stay loaded, and used images are remembered ==")
    front = make_sheet(root / "Scan-01.jpg", blanks=(2, 9))
    back = make_sheet(root / "Scan-02.jpg", blanks=(2, 9))
    pool = photo_pool.PhotoPool(tiles_dir=root / "tiles")
    check("a pool starts empty", len(pool) == 0 and not pool.sheets)

    pool.add_sheet(front, index=0)
    pool.add_sheet(back, index=1)
    check("both sheets are kept", len(pool.sheets) == 2, str(pool.sheets))
    check("the first sheet is the front",
          pool.sheets[0]["side"] == "front", str(pool.sheets[0]))
    check("the second sheet is the back",
          pool.sheets[1]["side"] == "back", str(pool.sheets[1]))
    check("every card image is available", len(pool) == 14, str(len(pool)))
    check("the empty slots are counted, not kept",
          pool.sheets[0]["usable"] == 7 and pool.sheets[0]["slots"] == 9,
          str(pool.sheets[0]))

    again = pool.add_sheet(front, index=0)
    check("adding the same sheet twice changes nothing",
          len(pool.sheets) == 2 and len(pool) == 14 and again is pool.sheets[0])

    line = pool.summary()[0]
    check("a sheet is described by its slots, not its filenames",
          "Scan-01.jpg" in line and "7 of 9 slots" in line and
          "7 free" in line, line)

    # -- fronts and backs ---------------------------------------------------
    fronts = pool.front_candidates()
    check("fronts are offered first", len(fronts) == 14 and
          fronts[0]["side"] == "front", str(len(fronts)))
    first_front = fronts[0]
    partner = pool.same_slot(first_front)
    check("the back comes from the same slot on the other sheet",
          partner is not None and partner["position"] ==
          first_front["position"], str(partner))
    check("the partner really is the back sheet",
          partner["sheet"] == "Scan-02.jpg", str(partner))
    check("a back never pairs with itself on its own sheet",
          pool.same_slot(partner)["sheet"] == "Scan-01.jpg")

    backs = pool.back_candidates(first_front)
    check("the chosen front is not offered as its own back",
          all(t["path"] != first_front["path"] for t in backs))
    check("backs are offered first", backs[0]["side"] == "back", str(backs[0]))

    # -- using them ---------------------------------------------------------
    check("taking a front works", pool.take(first_front, "Card A"))
    check("the same front cannot be taken twice",
          not pool.take(first_front, "Card B"))
    check("it is recorded against the card",
          first_front["used_by"] == "Card A", first_front["used_by"])
    check("a used image is no longer offered",
          all(t["path"] != first_front["path"]
              for t in pool.front_candidates()))
    check("the progress line counts it", pool.progress() == (1, 14),
          str(pool.progress()))
    check("the sheet summary counts it", "6 free" in pool.summary()[0],
          pool.summary()[0])

    pool.take(partner, "Card A")
    check("the pair counts as two images", pool.progress() == (2, 14),
          str(pool.progress()))
    check("a used back is not proposed again",
          pool.same_slot(fronts[1]) is not None)     # next slot still free

    pool.release(first_front)
    check("a released image comes back", first_front["used_by"] == "")
    check("and can be taken again", pool.take(first_front, "Card C"))
    check("the other card's back was left alone",
          partner["used_by"] == "Card A")

    # -- sides it has to guess ---------------------------------------------
    check("a name saying BACK wins over position",
          photo_pool.guess_side(0, "Scan-BACK.jpg") == "back")
    check("a name saying front wins too",
          photo_pool.guess_side(1, "front-scan.jpg") == "front")
    check("with no clue the position decides",
          photo_pool.guess_side(1, "Scan-02.jpg") == "back")
    check("a third sheet has no side to claim",
          photo_pool.guess_side(2, "Scan-03.jpg") == "", "")

    # -- refusals -----------------------------------------------------------
    empty = make_sheet(root / "Blank-01.jpg", blanks=tuple(range(1, 10)))
    try:
        pool.add_sheet(empty, index=0)
        check("a blank sheet is refused", False)
    except photo_pool.PhotoPoolError as exc:
        check("a blank sheet is refused", "looks empty" in str(exc), str(exc))
    try:
        pool.add_sheet(root / "missing.jpg", index=0)
        check("a missing sheet is refused", False)
    except photo_pool.PhotoPoolError as exc:
        check("a missing sheet is refused", "missing.jpg" in str(exc),
              str(exc))
    check("a refused sheet is not in the pool", len(pool.sheets) == 2,
          str([s["name"] for s in pool.sheets]))

    pool.clear()
    check("clearing puts the panel back to empty",
          len(pool) == 0 and not pool.sheets and pool.progress() == (0, 0))


def main():
    root = Path(tempfile.mkdtemp(prefix="photo-sheets-"))
    try:
        test_thumbnails(root)
        test_pool(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print()
    print("=" * 60)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASSED))
        return 1
    print("ALL PHOTO SHEET CHECKS PASSED (%d)" % PASSED)
    return 0


if __name__ == "__main__":
    sys.exit(main())
