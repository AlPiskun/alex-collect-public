#!/usr/bin/env python3
"""Checks for cs_picture and square_images - a picture from this computer.

No site, no network and no window: the plugin is never run here, the "download"
is a function that hands back bytes, and every picture is made in a temporary
folder with Pillow.

Every check is about one of the four things that make the feature worth having,
and each of them was a way to get it wrong:

* the padding is the one ``SquareImages.bat`` does - a portrait card centred on
  white, nothing resampled, and *the same routine*, not a second copy of it that
  can drift;
* the two files the plugin is given are a real pair - one format, one
  extension, names that differ only by ``-front``/``-back`` - because a pair it
  cannot recognise is a back *added beside* the old one, which is the defect
  this replaces;
* a back with no front to pair it with is refused before anything is written;
* and the words the windows use say what will happen: which photo, which
  position, that the old back is replaced rather than doubled, and that the
  front is re-sent unchanged.
"""
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]

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


try:
    from PIL import Image
except ImportError:                                    # pragma: no cover
    Image = None

import cs_picture                                      # noqa: E402
import photo_replace                                   # noqa: E402
import square_images                                   # noqa: E402

FRONT = "https://canadianshopper.ca/api/file/dallas-smith-front.webp"
BACK = "https://canadianshopper.ca/api/file/dallas-smith-back.webp"
TITLE = "Dallas Smith #12 - 1991 O-Pee-Chee"


def folder():
    return Path(tempfile.mkdtemp())


def picture(path, size=(600, 702), colour=(10, 120, 30)):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path)
    return path


def skipped():
    """Say plainly that the picture work cannot run, and fail the check."""
    check("Pillow is installed, so the picture work can be checked", False,
          "- python -m pip install Pillow")


# ------------------------------------------------------------- 1. squaring
def test_squaring():
    print()
    print("== 1. the padding is the one SquareImages.bat does ==")
    if Image is None:
        return skipped()
    work = folder()
    source = picture(work / "card.jpg", (600, 702))
    record = square_images.square_bytes(source)
    check("a portrait card is padded to a square", record["after"] == (702, 702),
          (record["before"], record["after"]))
    check("and it is the card's own pixels moved, not stretched",
          record["padded"] and record["before"] == (600, 702),
          (record["before"], record["after"]))
    written = work / "squared.jpg"
    written.write_bytes(record["data"])
    with Image.open(written) as saved:
        saved = saved.convert("RGB")
        side = saved.size[0]
        check("what is written decodes as a real picture",
              saved.size == (702, 702), saved.size)
        #  A 600x702 card is padded on its left and right, not its top and
        #  bottom: the square is the longest side, and the card keeps every
        #  row of pixels it had.
        check("the strip added beside the card is white",
              saved.getpixel((3, side // 2)) == (255, 255, 255),
              saved.getpixel((3, side // 2)))
        check("and the card itself is still in the middle",
              saved.getpixel((side // 2, side // 2))[1] > 90,
              saved.getpixel((side // 2, side // 2)))
    already = picture(work / "square.png", (500, 500))
    same = square_images.square_bytes(already)
    check("a picture that is already square keeps its size, untouched",
          same["after"] == (500, 500) and not same["padded"], same["after"])
    landscape = picture(work / "wide.jpg", (900, 600))
    wide = square_images.square_bytes(landscape)
    check("a landscape photo is padded the same way", wide["after"] == (900, 900),
          wide["after"])
    try:
        square_images.square_bytes(work / "not-a-picture.jpg")
        check("a file that is not a picture is refused in words", False, "no raise")
    except square_images.SquareError as exc:
        check("a file that is not a picture is refused in words",
              "read as a picture" in str(exc), exc)
    #  The tool and the button must not be two different paddings.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "make_square", APP / "make-square.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    check("make-square.py uses this same routine, not a copy",
          tool.pad_to_square is square_images.pad_to_square and
          tool.encode is square_images.encode, "a second copy has appeared")
    one = tool.pad_to_square(Image.new("RGB", (300, 400), (5, 5, 5)))
    two = square_images.pad_to_square(Image.new("RGB", (300, 400), (5, 5, 5)))
    #  tobytes() rather than getdata(): the same comparison, and getdata() is
    #  deprecated in the Pillow these machines run (removed in Pillow 14).
    check("and pads a card to the very same pixels",
          one.size == two.size and one.tobytes() == two.tobytes(),
          (one.size, two.size))


# ---------------------------------------------------------------- 2. names
def test_names():
    print()
    print("== 2. the files are named the way the plugin pairs a card ==")
    check("the pair name comes from the front the listing shows now",
          cs_picture.pair_name(FRONT, TITLE) == "dallas-smith",
          cs_picture.pair_name(FRONT, TITLE))
    check("a counter on the site's own name is dropped, not stacked",
          cs_picture.pair_name(
              "https://cs.ca/api/file/dallas-smith-front-3.webp", TITLE)
          == "dallas-smith",
          cs_picture.pair_name(
              "https://cs.ca/api/file/dallas-smith-front-3.webp", TITLE))
    check("the query string is not part of the name",
          cs_picture.pair_name("https://cs.ca/api/file/dallas-smith-front.webp"
                               "?v=2", TITLE) == "dallas-smith",
          cs_picture.pair_name("https://cs.ca/api/file/x-front.webp?v=2", TITLE))
    check("with no front photo the listing's title names it",
          cs_picture.pair_name("", TITLE) == "dallas-smith-12-1991-o-pee-chee",
          cs_picture.pair_name("", TITLE))
    check("and with neither there is no name, rather than an invented one",
          cs_picture.pair_name("", "") == "", cs_picture.pair_name("", ""))
    check("a name the filesystem cannot hold falls back to the title",
          cs_picture.pair_name("https://cs.ca/api/file/a:b?c|d-front.webp",
                               TITLE) == "dallas-smith-12-1991-o-pee-chee",
          cs_picture.pair_name("https://cs.ca/api/file/a:b?c|d-front.webp", TITLE))
    #  The same address read on a machine that is not this one. A URL path is
    #  POSIX-shaped whatever the operating system, and `Path("a:b").name` is
    #  "b" on Windows - "a:" reads as a drive - so the pair name came back as
    #  one letter and the pair went to the plugin under the wrong card. Read
    #  through the split, every machine answers the same.
    colon = cs_picture.pair_name("https://cs.ca/api/file/a:b-front.webp", TITLE)
    check("a colon in the address never becomes a one-letter pair name",
          colon == "dallas-smith-12-1991-o-pee-chee" and colon != "b", colon)
    check("the address is read the same way on every operating system",
          cs_picture.pair_name("https://cs.ca/api/file/x-front.webp", TITLE)
          == "x" and
          cs_picture.pair_name("https://cs.ca/api/file/folder/x-front.webp",
                               TITLE) == "x", "")
    #  And the trap itself, stated: Windows path semantics read that address
    #  as the single letter "b", which is exactly what the suite caught on the
    #  Windows machine and what no amount of reading it here would have shown.
    #  PureWindowsPath is available on every platform, so this is the same
    #  fact everywhere.
    from pathlib import PureWindowsPath
    check("path semantics read that address as one letter - which is why the "
          "address is split by hand",
          PureWindowsPath("a:b").name == "b",
          PureWindowsPath("a:b").name)
    #  The colon check above can only catch a relapse on the machine that has
    #  the disagreeing semantics, so the rule itself is checked: a shop's
    #  filename and a photo's address are read as strings, by hand, in both
    #  places that do it. Nothing here puts them through Path.
    import ast
    import inspect
    import textwrap
    for function in (photo_replace.replacement_stem, cs_picture._filename):
        source = textwrap.dedent(inspect.getsource(function))
        #  The docstring names the trap ("PureWindowsPath(...)"), so the code
        #  is what is read - the words explaining it are not the bug.
        node = ast.parse(source).body[0]
        said = ""
        if (node.body and isinstance(node.body[0], ast.Expr) and
                isinstance(node.body[0].value, ast.Constant) and
                isinstance(node.body[0].value.value, str)):
            said = node.body[0].value.value
        code = source.replace(said, "")
        check("%s reads a name or an address as a string, not a path"
              % function.__name__, "Path(" not in code and
              "pathlib" not in code, code.strip().splitlines()[0])
    check("the two slots are position 1 and 2", (
        cs_picture.position("front"), cs_picture.position("back")) == (1, 2),
        cs_picture.position("front"))
    check("and each has words a window can use",
          "main photo" in cs_picture.slot_words("front") and
          "second photo" in cs_picture.slot_words("back"),
          cs_picture.slot_words("back"))
    check("a slot read off a filename says which it is",
          (cs_picture.slot_of("x-back.webp"), cs_picture.slot_of("back"),
           cs_picture.slot_of("x.jpg")) == ("back", "back", ""),
          cs_picture.slot_of("x-back.webp"))


# ------------------------------------------------------- 3. the two files
def test_the_pair():
    print()
    print("== 3. the plugin is given a pair it can recognise ==")
    if Image is None:
        return skipped()
    work = folder()
    new = picture(work / "photo.png", (600, 702))
    front = picture(work / "on-the-site.webp", (600, 600))
    squared = cs_picture.square_file(new, work, "dallas-smith", "back", like=FRONT)
    check("the squared file keeps the front's format, so the pair is one kind",
          squared["path"].suffix == ".webp", squared["path"].name)
    written = cs_picture.prepare(work, "dallas-smith", "back", squared["path"],
                                 front)
    check("a back is written with the front it pairs with",
          written["front"] is not None and written["back"] is not None, written)
    check("both files exist on disk",
          written["front"].is_file() and written["back"].is_file(),
          (written["front"], written["back"]))
    check("and they share one extension",
          written["front"].suffix == written["back"].suffix == ".webp",
          (written["front"].suffix, written["back"].suffix))
    check("their names differ only by -front/-back, which is what the plugin "
          "checks",
          photo_replace.pair_stem(written["front"].name) ==
          photo_replace.pair_stem(written["back"].name) and
          photo_replace.side_of(written["front"].name) == "front" and
          photo_replace.side_of(written["back"].name) == "back",
          (written["front"].name, written["back"].name))
    check("the back file is the squared picture that was confirmed",
          written["back"].read_bytes() == squared["path"].read_bytes(), "")
    #  Both photos replaced in one go: the window lets a seller click a front
    #  and a back and send them as one pair, so the two files the plugin is
    #  given must already be a pair before it ever runs.
    second = picture(work / "new-back.png", (600, 640))
    squared_front = cs_picture.square_file(new, work, "both-sides", "front",
                                           like=FRONT)
    squared_back = cs_picture.square_file(second, work, "both-sides", "back",
                                          like=FRONT)
    both = cs_picture.prepare_pair(work, "both-sides",
                                   front_picture=squared_front["path"],
                                   back_picture=squared_back["path"])
    check("both photos are written as one pair",
          both["front"] is not None and both["back"] is not None, both)
    check("the pair shares one extension and differs only by -front/-back",
          both["front"].suffix == both["back"].suffix and
          photo_replace.pair_stem(both["front"].name) ==
          photo_replace.pair_stem(both["back"].name) and
          photo_replace.side_of(both["front"].name) == "front" and
          photo_replace.side_of(both["back"].name) == "back",
          (both["front"].name, both["back"].name))
    check("the front file is the front picture that was confirmed",
          both["front"].read_bytes() == squared_front["path"].read_bytes(), "")
    check("and the back file is the back picture, not the front's copy",
          both["back"].read_bytes() == squared_back["path"].read_bytes(), "")
    back_alone = cs_picture.prepare_pair(work, "both-sides",
                                        back_picture=squared_back["path"],
                                        current_front=front)
    check("a back on its own is still paired with the front the listing shows",
          back_alone["front"] is not None and
          photo_replace.side_of(back_alone["front"].name) == "front", back_alone)
    try:
        cs_picture.prepare_pair(work, "both-sides",
                               back_picture=squared_back["path"])
        check("a back with no front at all is refused", False, "no raise")
    except cs_picture.PictureError as exc:
        check("a back with no front at all is refused",
              "nothing was written" in str(exc).lower(), exc)
    try:
        cs_picture.prepare_pair(work, "both-sides")
        check("no picture at all is refused, not written as an empty pair",
              False, "no raise")
    except cs_picture.PictureError as exc:
        check("no picture at all is refused, not written as an empty pair",
              "no picture" in str(exc).lower(), exc)
    front_only = cs_picture.prepare(work, "dallas-smith", "front",
                                    squared["path"])
    check("a front on its own is still named as the front",
          photo_replace.side_of(front_only["front"].name) == "front" and
          front_only["back"] is None,
          front_only["front"].name)
    try:
        cs_picture.prepare(work, "dallas-smith", "back", squared["path"])
        check("a back with no front to pair it with is refused", False, "no raise")
    except cs_picture.PictureError as exc:
        check("a back with no front to pair it with is refused",
              "nothing was written" in str(exc).lower(), exc)
    jpeg_front = picture(work / "other-front.jpg", (600, 600))
    try:
        cs_picture.prepare(work, "dallas-smith", "back", squared["path"],
                           jpeg_front)
        check("a pair of two different formats is refused", False, "no raise")
    except cs_picture.PictureError as exc:
        check("a pair of two different formats is refused, rather than half "
              "written", "share one format" in str(exc), exc)
    try:
        cs_picture.prepare(work, "", "front", squared["path"])
        check("no name at all is refused, not invented", False, "no raise")
    except cs_picture.PictureError as exc:
        check("no name at all is refused, not invented",
              "cannot name" in str(exc) or "cannot place" in str(exc), exc)
    missing = work / "gone.png"
    try:
        cs_picture.square_file(missing, work, "dallas-smith", "back")
        check("a picture that has been moved away is named", False, "no raise")
    except cs_picture.PictureError as exc:
        check("a picture that has been moved away is named",
              "not on this computer" in str(exc), exc)


# ------------------------------------------------------ 4. the front photo
def test_the_front_photo():
    print()
    print("== 4. the front the listing shows now is fetched, not guessed ==")
    work = folder()
    seen = []

    def fetch(url):
        seen.append(url)
        return b"front-bytes"

    saved = cs_picture.download(FRONT, work, "dallas-smith", fetch=fetch)
    check("the front is saved beside the back that is being written",
          saved.is_file() and saved.read_bytes() == b"front-bytes", saved.name)
    check("its name says it is the front of that pair",
          photo_replace.side_of(saved.name) == "front", saved.name)
    check("and it keeps the site's own extension",
          saved.suffix == ".webp", saved.suffix)
    #  Its own fetch: the one above is counted, and this address is not the
    #  one the record gave.
    odd = cs_picture.download(
        "https://cs.ca/api/file/a:b-front.webp?x=1", work, "dallas-smith",
        fetch=lambda url: b"front-bytes")
    check("an odd address still gives a name the disk can hold, with its "
          "extension kept", odd.suffix == ".webp" and ":" not in odd.name,
          odd.name)
    check("the address it asked for is the one the record gave",
          seen == [FRONT], seen)

    def boom(url):
        raise OSError("the site refused the connection")

    try:
        cs_picture.download(FRONT, work, "dallas-smith", fetch=boom)
        check("a front that cannot be fetched stops the write", False, "no raise")
    except cs_picture.PictureError as exc:
        check("a front that cannot be fetched stops the write, and says so",
              "nothing was written" in str(exc).lower(), exc)
    try:
        cs_picture.download("", work, "dallas-smith", fetch=fetch)
        check("a listing that names no front is refused", False, "no raise")
    except cs_picture.PictureError as exc:
        check("a listing that names no front is refused",
              "does not say which photo" in str(exc), exc)
    try:
        cs_picture.download(FRONT, work, "dallas-smith", fetch=lambda url: b"")
        check("an empty answer is not written as a picture", False, "no raise")
    except cs_picture.PictureError as exc:
        check("an empty answer is not written as a picture",
              "came back empty" in str(exc), exc)


# ------------------------------------------------------- 5. photos shown
def test_the_photos_that_are_already_there():
    print()
    print("== 5. a photo already on the listing is saved so it can be looked at ==")
    work = folder()
    seen = []

    def fetch(url):
        seen.append(url)
        return b"gallery-bytes"

    #  The question "which of these is the old back?" is answered by looking:
    #  the shop's own names say nothing, so every row has to become a picture.
    saved = cs_picture.row_picture(
        "https://store.example/u/IMG_2231.JPG", work, "IMG_2231.jpg",
        fetch=fetch)
    check("the row's own photo is written where the window can draw it",
          saved.is_file() and saved.read_bytes() == b"gallery-bytes", saved.name)
    check("it keeps the site's own extension", saved.suffix == ".jpg",
          saved.suffix)
    check("its name is the row's name, made safe for a disk",
          saved.name.startswith("img-2231"), saved.name)
    check("the address asked for is the row's own", seen == [
        "https://store.example/u/IMG_2231.JPG"], seen)
    check("it is not named as part of a card's pair, because it is not",
          not photo_replace.side_of(saved.name), saved.name)

    again = cs_picture.row_picture(
        "https://store.example/u/IMG_2231.JPG", work, "IMG_2231.jpg",
        fetch=fetch)
    check("two rows of one name do not overwrite each other",
          again != saved and again.is_file(), "%s / %s" % (saved, again))

    def boom(url):
        raise OSError("the shop refused the connection")

    try:
        cs_picture.row_picture("https://store.example/u/x.jpg", work,
                               "x.jpg", fetch=boom)
        check("a photo that cannot be read says so", False, "no raise")
    except cs_picture.PictureError as exc:
        check("a photo that cannot be read says so, and the name is still "
              "there to choose", "could not be read" in str(exc), exc)
    try:
        cs_picture.row_picture("", work, "x.jpg", fetch=fetch)
        check("a row with no address is refused rather than invented",
              False, "no raise")
    except cs_picture.PictureError as exc:
        check("a row with no address is refused rather than invented",
              "no address" in str(exc), exc)
    try:
        cs_picture.row_picture("https://store.example/u/x.jpg", work,
                               "x.jpg", fetch=lambda url: b"")
        check("an empty answer is not drawn as a picture", False, "no raise")
    except cs_picture.PictureError as exc:
        check("an empty answer is not drawn as a picture",
              "came back empty" in str(exc), exc)


# ---------------------------------------------------------------- 6. words
def test_the_words():
    print()
    print("== 5. what the windows and the console say ==")
    rows = [{"sortOrder": 1, "imageUrl": FRONT},
            {"sortOrder": 2, "imageUrl": BACK}]
    check("the back is found by the name the plugin gives it",
          cs_picture.back_url(rows, FRONT) == BACK, cs_picture.back_url(rows, FRONT))
    unnamed = [{"sortOrder": "1", "imageUrl": FRONT},
               {"sortOrder": "2", "imageUrl": "https://cs.ca/api/file/x.webp"}]
    check("a gallery that predates the naming uses position 2",
          cs_picture.back_url(unnamed, FRONT) == "https://cs.ca/api/file/x.webp",
          cs_picture.back_url(unnamed, FRONT))
    check("the front is never offered as the back",
          cs_picture.back_url([{"sortOrder": 1, "imageUrl": FRONT}], FRONT) == "",
          cs_picture.back_url([{"sortOrder": 1, "imageUrl": FRONT}], FRONT))
    check("a gallery nobody could read has no back to name",
          cs_picture.back_url((), FRONT) == "", "")
    lines = "\n".join(cs_picture.review_lines(TITLE, "back", rows, FRONT))
    check("the review window names the photo being replaced",
          "the back (the second photo)" in lines and TITLE in lines, lines)
    check("and where it will sit", "position 2" in lines, lines)
    check("and that the old back is replaced, not doubled",
          "replaced, not doubled" in lines, lines)
    check("and that the front goes with it unchanged",
          "unchanged" in lines and "front" in lines, lines)
    check("and that nothing else on the listing is touched",
          "not its title, price, stock or state" in lines, lines)
    front_lines = "\n".join(cs_picture.review_lines(TITLE, "front", rows, FRONT))
    check("a front swap says the back is left alone",
          "only the main photo changes" in front_lines, front_lines)
    check("with no back yet, the window says the picture is added as the "
          "second photo",
          "added as the second photo" in "\n".join(
              cs_picture.review_lines(TITLE, "back", [], "")), "")
    both_lines = "\n".join(cs_picture.review_lines(TITLE, "both", rows, FRONT))
    check("both photos: the window says both are replaced, at 1 and 2",
          "Both pictures" in both_lines and "position 1" in both_lines and
          "position 2" in both_lines, both_lines)
    check("and that it is one run of the plugin",
          "one run" in both_lines, both_lines)
    check("and that the old back is replaced, not doubled",
          "replaced, not doubled" in both_lines, both_lines)
    check("both photos are named together, for a console line",
          cs_picture.slots_words(("front", "back")) ==
          "the front and the back" and
          cs_picture.slots_words(("back",)) == "the back" and
          cs_picture.slots_words(()) == "no photo",
          cs_picture.slots_words(("front", "back")))
    check("and \"both\" is a slot the module understands",
          cs_picture.slot_of("both") == "both" and
          "front and the back" in cs_picture.slot_words("both"),
          cs_picture.slot_words("both"))
    both_done = cs_picture.done_words(0, "both", TITLE)
    check("the console reports both photos done, at their two positions",
          "both photos" in both_done and "position 1" in both_done and
          "back at 2" in both_done, both_done)
    check("the console says what the plugin reported when it worked",
          "reported the replacement done" in
          cs_picture.done_words(0, "back", TITLE), cs_picture.done_words(0, "back", TITLE))
    failed = cs_picture.done_words(2, "back", TITLE)
    check("and does not claim success when it did not finish",
          "did not finish" in failed and "exit code 2" in failed, failed)
    check("an older plugin is told what it cannot do, by version",
          "1.0.16" in cs_picture.missing_plugin("back", "1.0.15") and
          "1.0.15" in cs_picture.missing_plugin("back", "1.0.15"),
          cs_picture.missing_plugin("back", "1.0.15"))
    check("and the front's own gate names its version too",
          "1.0.15" in cs_picture.missing_plugin("front", "1.0.13"), "")
    #  A refusal already says nothing was written; a surprise from elsewhere
    #  does not, and is given the sentence rather than a second copy of it.
    once = cs_picture.words_or_nothing(
        cs_picture.PictureError("That file could not be read as a picture. "
                                "Nothing was written."))
    twice = cs_picture.words_or_nothing(OSError("There is no space left"))
    check("a refusal is not made to say nothing-was-written twice",
          once.lower().count("nothing was written") == 1, once)
    check("and a failure from elsewhere is given that promise once",
          twice.lower().count("nothing was written") == 1 and
          "no space left" in twice, twice)
    check("even when there are no words at all",
          "nothing was written" in cs_picture.words_or_nothing(None).lower(),
          cs_picture.words_or_nothing(None))


# ------------------------------------------------------------- 6. the args
def test_the_arguments():
    print()
    print("== 6. the plugin is asked exactly as it documents ==")
    argv = cs_picture.args(TITLE, "front.webp", "back.webp", "cookie.txt")
    check("the CSV-free replace mode is asked for",
          argv[:2] == ["--mode", "replace"], argv)
    check("the listing is named by its title, which is how the plugin finds it",
          "--title" in argv and argv[argv.index("--title") + 1] == TITLE, argv)
    check("both photos are given",
          argv[argv.index("--front") + 1] == "front.webp" and
          argv[argv.index("--back") + 1] == "back.webp", argv)
    check("and the cookie file the panel reads", "--cookie-file" in argv, argv)
    front_only = cs_picture.args(TITLE, "front.webp", None, "cookie.txt")
    check("a front on its own sends no --back, which would add one",
          "--back" not in front_only, front_only)


# ------------------------------------------------------- 7. the wiring
def test_the_panel():
    print()
    print("== 7. the listing panel offers it, and asks this module ==")
    #  Read as text, not imported: gui.py imports Tkinter, and this suite is
    #  one of the ones that runs on a machine with no display. It is a wiring
    #  check and says so - it proves the button is on the panel and reaches
    #  this module, not that a window opened.
    source = (APP / "gui.py").read_text(encoding="utf-8")
    caption = 'text="Replace this listing\'s pictures..."'
    check("the panel has a button for it",
          caption in source, "no button with that caption")
    check("in both places a listing's photos are edited - the panel row and "
          "the listing's own form",
          source.count(caption) == 2, source.count(caption))
    check("and the caption has its hover explanation",
          '"Replace this listing\'s pictures...":' in source,
          "no TOOLTIPS entry")
    check("the review window's button is explained too",
          '"Use this picture":' in source and
          '"Use these pictures":' in source, "")
    check("the button opens the flow",
          "command=replace_with_picture" in source and
          "def replace_with_picture(on_done=None):" in source, "")
    check("the pictures are asked for and clicked, never typed",
          "photo_pick.pictures_in(" in source and
          "photo_pick.Picks(" in source and
          '"This is one picture"' in source and
          '"This is a sheet of nine cards"' in source, "")
    for piece in ("photo_replace_available()", "photo_back_replaceable()",
                  "cs_picture.pair_name(", "cs_picture.square_file(",
                  "cs_picture.prepare_pair(", "cs_picture.args(",
                  "TOOL_ACTION(CS_PHOTO_REPLACE)"):
        check("it uses %s" % piece, piece in source, "not found in gui.py")
    flow = source.split("def replace_with_picture")[1].split(
        "    proof_row = ttk.Frame(box)")[0]
    check("and the flow itself uploads nothing - the plugin does the hosting",
          "woo_media" not in flow and "upload_media" not in flow,
          "the flow reaches for an uploader")
    #  The plugin asks which photo already on the listing is the old back. That
    #  question used to be answered from a list of filenames, which is the
    #  report that opened this: a text version of a file, with the back not
    #  available to choose at all.
    check("the question about an old back is answered with pictures",
          "cs_picture.row_picture(" in source and
          "picture_cells(" in source, "no picture drawn for a gallery row")
    check("and every row's own address is used, not just its name",
          'row.get("url") or row.get("imageUrl")' in source and
          'row.get("src")' in source, "")
    check("a read that proved there is no old back answers without a window",
          "def _known_old_back(self, request):" in source and
          "app._photo_read = {" in flow, "the read is not kept")


def main():
    print("=" * 62)
    print("  A PICTURE FROM THIS COMPUTER ON A CANADIANSHOPPER LISTING")
    print("=" * 62)
    test_squaring()
    test_names()
    test_the_pair()
    test_the_front_photo()
    test_the_photos_that_are_already_there()
    test_the_words()
    test_the_arguments()
    test_the_panel()
    print()
    print("=" * 62)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL PICTURE CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
