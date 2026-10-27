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


def test_pair_naming(root):
    """A card's two photos differ only by -front / -back, counter included."""
    check("a front name is recognised",
          photo_replace.side_of("dallas-smith-front.webp") == "front")
    check("a back name is recognised",
          photo_replace.side_of("dallas-smith-back.webp") == "back")
    check("a name with no side is recognised as neither",
          photo_replace.side_of("dallas-smith.webp") == "")
    check("a side is still found after a counter",
          photo_replace.side_of("dallas-smith-back-3.webp") == "back")
    check("both halves share one stem",
          photo_replace.pair_stem("dallas-smith-front-2.webp") ==
          photo_replace.pair_stem("dallas-smith-back.webp") == "dallas-smith")

    folder = root / "pairs"
    folder.mkdir(parents=True, exist_ok=True)
    fresh = photo_replace.pair_paths(folder, "dallas-smith-front.webp")
    check("a fresh pair starts at 1 on both sides",
          (fresh["front"].name, fresh["back"].name) ==
          ("dallas-smith-front-1.webp", "dallas-smith-back-1.webp"),
          str(fresh))

    # The important rule: one counter for the pair, not one each. A taken back
    # number must push the front too, or the two halves stop matching.
    (folder / "dallas-smith-back-1.webp").write_bytes(b"x")
    taken = photo_replace.pair_paths(folder, "dallas-smith-front.webp")
    check("a taken back number moves the front as well",
          (taken["front"].name, taken["back"].name) ==
          ("dallas-smith-front-2.webp", "dallas-smith-back-2.webp"),
          str(taken))

    (folder / "dallas-smith-front-1.webp").write_bytes(b"x")
    (folder / "dallas-smith-front-2.webp").write_bytes(b"x")
    (folder / "dallas-smith-back-2.webp").write_bytes(b"x")
    nxt = photo_replace.pair_paths(folder, "dallas-smith-front.webp")
    check("the pair skips a number either half has taken",
          nxt["counter"] == 3, str(nxt))

    from_back = photo_replace.pair_paths(folder, "dallas-smith-back.webp")
    check("building from the back image gives the same pair",
          (from_back["front"].name, from_back["back"].name) ==
          ("dallas-smith-front-3.webp", "dallas-smith-back-3.webp"),
          str(from_back))

    legacy = photo_replace.pair_paths(folder, "gretzky.webp")
    check("a name with no side keeps its own shape for the front",
          (legacy["front"].name, legacy["back"].name) ==
          ("gretzky-1.webp", "gretzky-back-1.webp"), str(legacy))

    front = root / "tile-front.webp"
    back = root / "tile-back.webp"
    front.write_bytes(b"FRONT")
    back.write_bytes(b"BACK")
    written = photo_replace.save_pair(root / "pairs", "dallas-smith-front.webp",
                                      front, back)
    check("saving a pair writes both with one counter",
          written["front"].name == "dallas-smith-front-3.webp" and
          written["back"].name == "dallas-smith-back-3.webp", str(written))
    check("each half holds its own bytes",
          written["front"].read_bytes() == b"FRONT" and
          written["back"].read_bytes() == b"BACK")

    # The plugin verifies that a front/back pair differs only by the side
    # suffix, so a name with no side must not leak through when a back is
    # supplied - gretzky-1.webp beside gretzky-back-1.webp would be rejected.
    matched = photo_replace.pair_paths(root / "pairs", "gretzky.webp",
                                       force_sided=True)
    check("a name with no side becomes a matched pair when a back is coming",
          (matched["front"].name, matched["back"].name) ==
          ("gretzky-front-1.webp", "gretzky-back-1.webp"), str(matched))
    check("a forced pair keeps one stem on both sides",
          photo_replace.pair_stem(matched["front"].name) ==
          photo_replace.pair_stem(matched["back"].name))

    only_front = photo_replace.save_pair(root / "pairs",
                                         "dallas-smith-front.webp", front)
    check("a front on its own still leaves the next number for its back",
          only_front["front"].name == "dallas-smith-front-4.webp" and
          "back" not in only_front, str(only_front))

    legacy_pair = photo_replace.save_pair(root / "pairs", "gretzky.webp",
                                          front, back)
    check("saving a pair under a legacy name still matches by name",
          legacy_pair["front"].name.replace("-front", "-back") ==
          legacy_pair["back"].name, str(legacy_pair))

    # The search-page fallback finds no product, so there is no website image
    # to copy a name from. The chosen image still has to be saved - refusing
    # here threw away the user's pick and killed the whole run.
    nameless = photo_replace.save_pair(root / "nameless", "", front, back)
    check("a card with no website image still saves a pair",
          nameless["front"].is_file() and nameless["back"].is_file(),
          str(nameless))
    check("the pair is named after the scan when nothing else is known",
          nameless["front"].name.replace("-front", "-back") ==
          nameless["back"].name, str(nameless))
    alone = photo_replace.save_pair(root / "nameless", "", front)
    check("a front alone is saved without a name too",
          alone["front"].is_file() and "back" not in alone, str(alone))

    # A gallery that predates the -front/-back naming cannot be read by
    # filename. pair_ids() then quietly treats the first row as the only one
    # to replace, which leaves an unsuffixed old back on the product beside
    # the new one - so these rows are reported for the user to decide.
    named = [{"id": 7, "name": "gretzky-front.webp"},
             {"id": 8, "name": "gretzky-back.webp"}]
    check("a named pair identifies both sides",
          photo_replace.side_rows(named)["back"]["id"] == 8,
          str(photo_replace.side_rows(named)))
    check("a named pair needs no question",
          photo_replace.unread_back_rows(named) == [],
          str(photo_replace.unread_back_rows(named)))

    loose = [{"id": 11, "name": "IMG_2231.jpg"},
             {"id": 12, "name": "IMG_2232.jpg"}]
    check("an unsuffixed pair has no identified side",
          photo_replace.side_rows(loose) == {},
          str(photo_replace.side_rows(loose)))
    check("both unsuffixed rows are offered as a possible back",
          [r["id"] for r in photo_replace.unread_back_rows(loose)] == [11, 12],
          str(photo_replace.unread_back_rows(loose)))

    mixed = [{"id": 13, "name": "burrows-front.jpg"},
             {"id": 14, "name": "back-of-card.jpg"}]
    check("a back that only says so in the middle is not identified",
          photo_replace.side_rows(mixed)["front"]["id"] == 13 and
          "back" not in photo_replace.side_rows(mixed),
          str(photo_replace.side_rows(mixed)))
    check("the un-named row beside a known front is offered",
          [r["id"] for r in photo_replace.unread_back_rows(mixed)] == [14],
          str(photo_replace.unread_back_rows(mixed)))

    paired = mixed + [{"id": 15, "name": "burrows-back.jpg"}]
    check("once a real back is named, nothing is asked",
          photo_replace.unread_back_rows(paired) == [],
          str(photo_replace.unread_back_rows(paired)))
    check("one photo alone is not a question worth asking",
          photo_replace.unread_back_rows([{"id": 99, "name": "x.jpg"}]) == [],
          str(photo_replace.unread_back_rows([{"id": 99, "name": "x.jpg"}])))

    before = sorted(p.name for p in (root / "pairs").iterdir())
    try:
        photo_replace.save_pair(root / "pairs", "dallas-smith-front.webp",
                                front, root / "missing-back.webp")
        check("a missing back is refused", False, "no error raised")
    except photo_replace.PhotoReplaceError:
        check("a missing back is refused before the front is written",
              sorted(p.name for p in (root / "pairs").iterdir()) == before,
              "the folder changed")

    check("the old pair is found by its sides",
          photo_replace.pair_ids([
              {"id": 5, "name": "a-front.webp"},
              {"id": 6, "name": "a-back.webp"},
              {"id": 9, "name": "certificate.webp"}]) == [5, 6])
    check("an unrelated photo is not part of the pair",
          9 not in photo_replace.pair_ids([
              {"id": 5, "name": "a-front.webp"},
              {"id": 9, "name": "certificate.webp"}]))
    check("a gallery with no side names falls back to its main photo",
          photo_replace.pair_ids([{"id": 5, "name": "one.webp"},
                                  {"id": 6, "name": "two.webp"}]) == [5])
    check("no images means no old pair", photo_replace.pair_ids([]) == [])


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

    print("== 5. a card's two photos are named as one pair ==")
    with tempfile.TemporaryDirectory() as td:
        test_pair_naming(Path(td))

    print("== 6. clear errors ==")
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
