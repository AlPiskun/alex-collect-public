#!/usr/bin/env python3
"""Checks for photo_pick - the two replacement pictures, chosen by looking.

The window that replaces a listing's pictures asks where they are, cuts the
scans into nine slots, and lets the front and the back be *clicked*. Which of
those clicks is the front, whether the back in the front's slot is offered, and
what the button then says are all rules, and none of them needs a window: that
is what is checked here, with real image files and no Tkinter.

test-photo-panel.py drives the window itself.
"""
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]

try:
    from PIL import Image
except ImportError:                                   # pragma: no cover
    Image = None

import photo_pick  # noqa: E402
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


def folder():
    return Path(tempfile.mkdtemp())


def card(path, size=(600, 840), colour=(240, 230, 210)):
    """One card photographed on its own - small enough to be one picture."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path)
    return path


def sheet(path, blanks=(), tile=600, colour=(245, 240, 230)):
    """A 3x3 scan: a 'card' in every slot except the ones named blank."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    width = photo_replace.GRID_COLS * tile
    height = photo_replace.GRID_ROWS * tile + photo_replace.BOTTOM_CROP
    image = Image.new("RGB", (width, height), (0, 0, 0))
    position = 0
    for row in range(photo_replace.GRID_ROWS):
        for col in range(photo_replace.GRID_COLS):
            position += 1
            if position in blanks:
                continue
            image.paste(Image.new("RGB", (tile, tile), colour),
                        (col * tile, row * tile))
    image.save(path)
    return path


def test_what_a_file_is():
    print()
    print("== 1. a scan of nine cards, or one card on its own ==")
    if Image is None:
        print("  (Pillow is missing, so the pictures cannot be made)")
        return
    work = folder()
    big = sheet(work / "fronts.jpg")
    small = card(work / "one-card.jpg")
    check("a picture's extension is recognised, whatever the case",
          photo_pick.is_picture("a.JPG") and
          photo_pick.is_picture("b.webp") and
          not photo_pick.is_picture("c.pdf") and
          not photo_pick.is_picture(""), "the suffix rule")
    check("a size is read from the file's own header",
          photo_pick.size_of(big) == (1800, 2200), photo_pick.size_of(big))
    check("a sheet is a scan big enough to hold nine cards",
          photo_pick.looks_like_sheet(photo_pick.size_of(big)), "")
    check("a card photographed on its own is not a sheet",
          not photo_pick.looks_like_sheet(photo_pick.size_of(small)), "")
    check("so the guess names each one as what it is",
          photo_pick.guess_kind(big) == "sheet" and
          photo_pick.guess_kind(small) == "picture",
          (photo_pick.guess_kind(big), photo_pick.guess_kind(small)))
    check("and the window can say which reading it used",
          photo_pick.kind_words("sheet") == "a sheet of nine cards" and
          photo_pick.kind_words("picture") == "one picture",
          photo_pick.kind_words("sheet"))
    check("a huge single card is only a guess away from being read right",
          photo_pick.looks_like_sheet((2000, 2800)), "")
    try:
        photo_pick.size_of(work / "not-there.jpg")
        check("a file that has gone is named, not guessed at", False,
              "no raise")
    except photo_pick.PhotoPickError as exc:
        check("a file that has gone is named, not guessed at",
              "not on this computer" in str(exc), exc)
    check("a file that is not a picture is refused in words",
          "not a picture" in str(_raises(photo_pick.pictures_in,
                                         work / "notes.txt", work)),
          _raises(photo_pick.pictures_in, work / "notes.txt", work))


def _raises(function, *args, **kwargs):
    """The sentence a refusal carries, for a check to look inside."""
    try:
        function(*args, **kwargs)
    except photo_pick.PhotoPickError as exc:
        return str(exc)
    return ""


def test_the_slots():
    print()
    print("== 2. a sheet becomes nine pictures, the empty slots left out ==")
    if Image is None:
        print("  (Pillow is missing, so the pictures cannot be made)")
        return
    work = folder()
    full = sheet(work / "Scan01.jpg")
    found = photo_pick.pictures_in(full, work / "cut")
    check("the file is read as a sheet", found["kind"] == "sheet",
          found["kind"])
    check("nine slots are shown, in reading order",
          [tile["position"] for tile in found["tiles"]] == list(range(1, 10)),
          [tile["position"] for tile in found["tiles"]])
    check("each one has the picture it was cut into, on disk",
          all(Path(tile["path"]).is_file() for tile in found["tiles"]), "")
    check("and a caption that says which slot it is",
          found["tiles"][0]["label"] == "Slot 1", found["tiles"][0]["label"])
    check("the sentence says how many pictures came out of it",
          "9 pictures cut from the sheet" in found["words"], found["words"])

    partly = sheet(work / "Scan02.jpg", blanks=(3, 7))
    cut = photo_pick.pictures_in(partly, work / "cut2")
    check("an empty slot is left out, not offered as a card",
          [tile["position"] for tile in cut["tiles"]] ==
          [1, 2, 4, 5, 6, 8, 9], [tile["position"] for tile in cut["tiles"]])
    check("and the sentence says how many were empty",
          "2 empty slots left out" in cut["words"], cut["words"])

    empty = sheet(work / "Scan03.jpg", blanks=tuple(range(1, 10)))
    sentence = _raises(photo_pick.pictures_in, empty, work / "cut3")
    check("a sheet with nothing on it is refused, with the way out",
          "Every slot" in sentence and "one picture" in sentence, sentence)

    one = card(work / "Scan04.jpg")
    alone = photo_pick.pictures_in(one, work / "cut4", as_sheet=False)
    check("one card is one picture, and the whole file is it",
          alone["kind"] == "picture" and len(alone["tiles"]) == 1 and
          str(alone["tiles"][0]["path"]) == str(one), alone["words"])
    #  The reading is always changeable: a 600 dpi card scan is as tall as a
    #  sheet scanned at 200, so the guess must not be the last word.
    forced = photo_pick.pictures_in(one, work / "cut5", as_sheet=True)
    check("the same file can be read as a sheet when the guess is wrong",
          forced["kind"] == "sheet" and len(forced["tiles"]) == 9,
          len(forced["tiles"]))
    forced_back = photo_pick.pictures_in(full, work / "cut6", as_sheet=False)
    check("and a sheet can be read as one picture the same way",
          forced_back["kind"] == "picture" and len(forced_back["tiles"]) == 1,
          forced_back["kind"])


def test_clicking():
    print()
    print("== 3. clicking a picture: the front, the back, or neither ==")
    if Image is None:
        print("  (Pillow is missing, so the pictures cannot be made)")
        return
    work = folder()
    fronts = photo_pick.pictures_in(sheet(work / "fronts.jpg"), work / "f")
    backs = photo_pick.pictures_in(sheet(work / "backs.jpg"), work / "b")
    front_keys = [str(tile["path"]) for tile in fronts["tiles"]]
    back_keys = [str(tile["path"]) for tile in backs["tiles"]]

    picks = photo_pick.Picks()
    picks.load("front", fronts["source"], fronts["kind"], fronts["tiles"])
    picks.load("back", backs["source"], backs["kind"], backs["tiles"])
    picks.suggest = photo_pick.slot_proposal(picks.tiles("front"),
                                             picks.tiles("back"))
    check("nothing clicked: nothing to send",
          picks.slots() == () and not picks.ready(), picks.slots())
    check("and the window says what is still to be clicked",
          "front" in picks.missing(), picks.missing())
    check("the button says what it would do before anything is clicked",
          picks.button_words() == "Replace the photos", picks.button_words())

    picks.pick("front", front_keys[3])
    check("a click makes that picture the front",
          picks.chosen("front") == front_keys[3], picks.chosen("front"))
    check("one click is enough to send: the slot's back comes with it",
          picks.ready() and picks.slots() == ("front", "back"),
          picks.slots())
    check("the back in the front's slot is offered, and marked as offered",
          picks.chosen("back") == back_keys[3] and picks.offered("back"),
          (picks.chosen("back"), picks.offered("back")))
    check("and nothing is missing any more", picks.missing() == "",
          picks.missing())
    check("the button says both, because both pictures are marked",
          picks.button_words() == "Replace both photos",
          picks.button_words())
    check("the summary says which one was only offered",
          "Front: " in picks.summary() and
          "Back: " in picks.summary() and
          "offered by slot" in picks.summary(), picks.summary())

    picks.pick("back", back_keys[3])
    check("clicking the offered back off leaves the front on its own",
          picks.chosen("back") == "" and picks.slots() == ("front",),
          picks.slots())
    check("and the button then says front", picks.button_words() ==
          "Replace the front photo", picks.button_words())
    picks.pick("back", back_keys[3])
    check("clicking it again puts the pair back together",
          picks.slots() == ("front", "back"), picks.slots())

    picks.pick("back", back_keys[0])
    check("clicking another back replaces the offer",
          picks.chosen("back") == back_keys[0] and not picks.offered("back"),
          picks.chosen("back"))
    check("both clicked: the button says both",
          picks.slots() == ("front", "back") and
          picks.button_words() == "Replace both photos", picks.button_words())
    check("and both files are named for the plugin",
          picks.paths() == {"front": front_keys[3], "back": back_keys[0]},
          picks.paths())

    picks.pick("front", front_keys[5])
    check("a clicked back is kept when the front changes",
          picks.chosen("back") == back_keys[0], picks.chosen("back"))
    picks.pick("back", back_keys[0])
    check("clicking the marked back again takes it off",
          picks.chosen("back") == "" and picks.slots() == ("front",),
          picks.slots())
    picks.pick("front", front_keys[5])
    check("clicking the marked front again takes it off too",
          picks.chosen("front") == "" and picks.slots() == (), picks.slots())
    check("and the back the slot offered goes with it",
          picks.chosen("back") == "", picks.chosen("back"))

    picks.pick("front", front_keys[1])
    picks.pick("back", front_keys[1])
    check("one picture cannot be both halves of the pair",
          picks.chosen("back") != front_keys[1], picks.chosen("back"))
    check("an unknown picture changes nothing",
          picks.pick("front", "nope") == "" and
          picks.chosen("front") == front_keys[1], picks.chosen("front"))
    check("an unknown side changes nothing",
          picks.pick("sideways", front_keys[0]) == "", "")


def test_the_plugin_gate():
    print()
    print("== 4. an older plugin is not offered a back it cannot replace ==")
    if Image is None:
        print("  (Pillow is missing, so the pictures cannot be made)")
        return
    work = folder()
    fronts = photo_pick.pictures_in(sheet(work / "fronts.jpg"), work / "f")
    backs = photo_pick.pictures_in(sheet(work / "backs.jpg"), work / "b")
    front_keys = [str(tile["path"]) for tile in fronts["tiles"]]
    back_keys = [str(tile["path"]) for tile in backs["tiles"]]

    picks = photo_pick.Picks(can_back=False)
    picks.load("front", fronts["source"], fronts["kind"], fronts["tiles"])
    picks.load("back", backs["source"], backs["kind"], backs["tiles"])
    picks.suggest = photo_pick.slot_proposal(picks.tiles("front"),
                                             picks.tiles("back"))
    check("with nothing clicked, the window asks for the front only",
          "front" in picks.missing() and "back" not in picks.missing(),
          picks.missing())
    picks.pick("front", front_keys[0])
    check("no back is offered when the plugin cannot replace one",
          picks.chosen("back") == "", picks.chosen("back"))
    picks.pick("back", back_keys[0])
    check("and a click on a back is ignored rather than sent",
          picks.chosen("back") == "" and picks.slots() == ("front",),
          picks.slots())
    check("so the one picture is the whole replacement",
          picks.slots() == ("front",) and
          picks.button_words() == "Replace the front photo", picks.slots())


def test_a_new_strip():
    print()
    print("== 5. choosing another sheet keeps what is still on the screen ==")
    if Image is None:
        print("  (Pillow is missing, so the pictures cannot be made)")
        return
    work = folder()
    fronts = photo_pick.pictures_in(sheet(work / "fronts.jpg"), work / "f")
    backs = photo_pick.pictures_in(sheet(work / "backs.jpg"), work / "b")
    other = photo_pick.pictures_in(sheet(work / "more-backs.jpg"), work / "b2")
    front_keys = [str(tile["path"]) for tile in fronts["tiles"]]
    other_keys = [str(tile["path"]) for tile in other["tiles"]]

    picks = photo_pick.Picks()
    picks.load("front", fronts["source"], fronts["kind"], fronts["tiles"])
    picks.load("back", backs["source"], backs["kind"], backs["tiles"])
    picks.suggest = photo_pick.slot_proposal(picks.tiles("front"),
                                             picks.tiles("back"))
    picks.pick("front", front_keys[2])
    check("the back sheet chosen second offers its slot",
          picks.chosen("back") == str(backs["tiles"][2]["path"]) and
          picks.offered("back"), picks.chosen("back"))

    picks.load("back", other["source"], other["kind"], other["tiles"])
    check("another back sheet clears the offer that is no longer on it",
          picks.chosen("back") in ("", other_keys[2]), picks.chosen("back"))
    check("and the new sheet's slot is offered instead",
          picks.chosen("back") == other_keys[2] and picks.offered("back"),
          picks.chosen("back"))
    check("the front is untouched by the back sheet changing",
          picks.chosen("front") == front_keys[2], picks.chosen("front"))
    check("the source of each strip is remembered for the next card",
          picks.source("back") == other["source"] and
          picks.kind("back") == "sheet", picks.source("back"))


def test_the_proposal():
    print()
    print("== 6. the back in the front's slot, and nothing invented ==")
    fronts = [{"path": Path("/a/front-1.webp"), "position": 1},
              {"path": Path("/a/front-4.webp"), "position": 4}]
    backs = [{"path": Path("/b/back-4.webp"), "position": 4},
             {"path": Path("/b/back-9.webp"), "position": 9}]
    suggest = photo_pick.slot_proposal(fronts, backs)
    check("slot 4's front offers slot 4's back",
          suggest(str(fronts[1]["path"])) == str(backs[0]["path"]),
          suggest(str(fronts[1]["path"])))
    check("a slot with no back offers nothing",
          suggest(str(fronts[0]["path"])) == "", "")
    check("an unknown front offers nothing", suggest("/nope") == "", "")
    check("no back sheet at all offers nothing",
          photo_pick.slot_proposal(
              fronts, [])(str(fronts[1]["path"])) == "", "")


def test_the_wiring():
    print()
    print("== 7. the panel reaches this module, and the rules are here ==")
    source = (APP / "gui.py").read_text(encoding="utf-8")
    check("the panel imports it", "import photo_pick" in source, "")
    flow = source.split("def replace_with_picture")[1].split(
        "    proof_row = ttk.Frame(box)")[0]
    for piece in ("photo_pick.pictures_in(", "photo_pick.Picks(",
                  "picks.pick(", "cs_picture.prepare_pair(",
                  "cs_picture.review_lines("):
        check("the flow uses %s" % piece, piece in flow, "not found")
    check("both pictures are chosen before anything is to appear",
          flow.index("choose_pictures(") < flow.index("def review("),
          "the review comes first")
    check("the window asks where the pictures are, per side",
          "Choose the front sheet or picture..." in source and
          "Choose the back sheet or picture..." in source, "")
    check("the listing list is multi-select, so several can be moved at once",
          'selectmode="extended"' in source, "")
    check("and one confirmation names every listing before it is sent",
          "Every one of those" in source and "listed = " in source, "")


def main():
    print("=" * 62)
    print("photo_pick - the replacement pictures, chosen by looking")
    print("=" * 62)
    test_what_a_file_is()
    test_the_slots()
    test_clicking()
    test_the_plugin_gate()
    test_a_new_strip()
    test_the_proposal()
    test_the_wiring()
    print()
    print("=" * 62)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL PICTURE-CHOICE CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
