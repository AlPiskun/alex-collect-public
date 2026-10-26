#!/usr/bin/env python3
"""Offline tests for photo_replace.py.

Replacing a card's photos depends on three rules that are easy to get quietly
wrong: the replacement scan must be cropped exactly like a listing scan, an
empty slot on the sheet must not be treated as a card, and a replacement name
must keep counting from the card's current website image. None of that needs a
window or a website, so all of it is checked here.
"""
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]

from PIL import Image  # noqa: E402

import photo_replace  # noqa: E402

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


def test_geometry_matches_pipeline():
    """A replacement scan is the same sheet, so the crop must not drift."""
    import card_pipeline

    for name in ("GRID_COLS", "GRID_ROWS", "IMG_FORMAT", "BOTTOM_CROP",
                 "BORDER_CROP", "TARGET_WIDTH", "TARGET_KB", "MIN_QUALITY",
                 "MAX_QUALITY", "QUALITY_TOLERANCE"):
        mine = getattr(photo_replace, name)
        theirs = getattr(card_pipeline, name)
        check("%s matches card_pipeline" % name, mine == theirs,
              "%r != %r" % (mine, theirs))


def test_blank_detection():
    black = Image.new("RGB", (400, 400), (0, 0, 0))
    white = Image.new("RGB", (400, 400), (255, 255, 255))
    near_black = Image.new("RGB", (400, 400), (8, 8, 8))

    check("a black slot is blank", photo_replace.tile_is_blank(black))
    check("a white card is not blank", not photo_replace.tile_is_blank(white))
    check("a near-black pocket is blank",
          photo_replace.tile_is_blank(near_black))

    # A dark card: mostly black but with a real picture in the middle. It must
    # survive, or a genuinely dark card would be discarded as an empty slot.
    dark_card = Image.new("RGB", (400, 400), (6, 6, 6))
    for x in range(80, 320):
        for y in range(80, 320):
            dark_card.putpixel((x, y), (120, 90, 60))
    check("a dark card with artwork is kept",
          not photo_replace.tile_is_blank(dark_card))

    # A card that fills most of the slot but has a black border all round.
    bordered = Image.new("RGB", (400, 400), (0, 0, 0))
    for x in range(40, 360):
        for y in range(40, 360):
            bordered.putpixel((x, y), (200, 190, 170))
    check("a card with a black border is kept",
          not photo_replace.tile_is_blank(bordered))


def make_sheet(path, blank_positions):
    """A 3x3 sheet: white 'cards' except at the given positions."""
    tile = 600
    width = photo_replace.GRID_COLS * tile
    height = photo_replace.GRID_ROWS * tile + photo_replace.BOTTOM_CROP
    sheet = Image.new("RGB", (width, height), (0, 0, 0))
    position = 1
    for row in range(photo_replace.GRID_ROWS):
        for col in range(photo_replace.GRID_COLS):
            if position not in blank_positions:
                box = (col * tile + 80, row * tile + 80,
                       (col + 1) * tile - 80, (row + 1) * tile - 80)
                sheet.paste((235, 230, 220), box)
            position += 1
    sheet.save(path)
    return path


def test_split_sheet(root):
    scan = make_sheet(root / "Scan2026-10-25_120000.jpg", {2, 4, 9})
    out = root / "tiles"
    results = photo_replace.split_sheet(scan, out)

    check("every position is reported", len(results) == 9, str(len(results)))
    blanks = [r["position"] for r in results if r["blank"]]
    check("the empty slots are the ones drawn empty", blanks == [2, 4, 9],
          str(blanks))
    check("empty slots write no file",
          all(r["path"] is None for r in results if r["blank"]))
    kept = [r for r in results if r["path"]]
    check("every kept slot has a real file",
          len(kept) == 6 and all(r["path"].is_file() for r in kept))
    check("kept files are named by position",
          sorted(p.name for p in out.iterdir()) ==
          ["Scan2026-10-25_120000_%d.webp" % n
           for n in (1, 3, 5, 6, 7, 8)],
          str(sorted(p.name for p in out.iterdir())))

    # A caller that wants all nine still gets the blank ones marked.
    kept_all = root / "tiles-all"
    everything = photo_replace.split_sheet(scan, kept_all, skip_blank=False)
    check("skip_blank=False keeps all nine files",
          all(r["path"] and r["path"].is_file() for r in everything) and
          [r["blank"] for r in everything] == [
              False, True, False, True, False, False, False, False, True])


def test_names():
    check("a plain image name is the base",
          photo_replace.replacement_stem("dallas-smith-front.webp") ==
          "dallas-smith-front")
    check("an existing counter is dropped, so counting continues",
          photo_replace.replacement_stem("dallas-smith-front-1.webp") ==
          "dallas-smith-front")
    check("a number inside the name is left alone",
          photo_replace.replacement_stem("o-pee-chee-21-front.webp") ==
          "o-pee-chee-21-front")
    check("a missing image name gives no base",
          photo_replace.replacement_stem("") == "")

    product = {"images": [{"src": "https://shop.example/wp-content/uploads/"
                                  "2026/10/dallas-smith-front.webp"}]}
    check("the website image name comes from the product",
          photo_replace.woo_image_name(product) == "dallas-smith-front.webp")
    check("a product with no images gives no name",
          photo_replace.woo_image_name({"images": []}) == "")
    check("a missing product gives no name",
          photo_replace.woo_image_name(None) == "")


def test_next_available(root):
    folder = root / "replacements"
    folder.mkdir()
    first = photo_replace.next_available_path(folder, "card-front")
    check("the first replacement is -1", first.name == "card-front-1.webp",
          first.name)
    first.write_bytes(b"x")
    second = photo_replace.next_available_path(folder, "card-front")
    check("an existing -1 pushes to -2", second.name == "card-front-2.webp",
          second.name)
    second.write_bytes(b"x")
    (folder / "card-front-3.webp").write_bytes(b"x")
    third = photo_replace.next_available_path(folder, "card-front")
    check("the next free counter is used, not simply the next number",
          third.name == "card-front-4.webp", third.name)

    tile = root / "tiles" / "Scan2026-10-25_120000_5.webp"
    tile.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (600, 840), (240, 230, 210)).save(tile)
    replaced = photo_replace.copy_as_replacement(folder, "card-front.webp",
                                                 tile)
    check("a chosen tile is copied under the replacement name",
          replaced.is_file() and replaced.read_bytes() == tile.read_bytes())
    check("the copy keeps the website name as its base",
          replaced.name.startswith("card-front-"), replaced.name)
    check("the source tile is left where it was", tile.is_file())


def test_errors(root):
    try:
        photo_replace.split_sheet(root / "nope.jpg", root / "out")
        check("a missing scan raises", False)
    except photo_replace.PhotoReplaceError as exc:
        check("a missing scan raises a clear error", "Scan not found" in str(exc),
              str(exc))
    try:
        photo_replace.next_available_path(root, "")
        check("an empty base name raises", False)
    except photo_replace.PhotoReplaceError:
        check("an empty base name is refused", True)
    try:
        photo_replace.copy_as_replacement(root, "card.webp",
                                          root / "absent.webp")
        check("a missing tile raises", False)
    except photo_replace.PhotoReplaceError:
        check("a missing tile is refused", True)


def main():
    print("== 1. the crop matches the pipeline ==")
    test_geometry_matches_pipeline()

    print("== 2. empty slots are not cards ==")
    test_blank_detection()

    print("== 3. a sheet is split and counted ==")
    with tempfile.TemporaryDirectory() as td:
        test_split_sheet(Path(td))

    print("== 4. replacement names count up ==")
    test_names()
    with tempfile.TemporaryDirectory() as td:
        test_next_available(Path(td))

    print("== 5. clear errors ==")
    with tempfile.TemporaryDirectory() as td:
        test_errors(Path(td))

    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL PHOTO REPLACE CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
