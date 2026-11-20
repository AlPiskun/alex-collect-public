"""The replacement pictures a seller picked, and which photo each one is.

Why this exists
---------------
Replacing one listing's photos used to ask which photo first, then open a file
picker, and only afterwards show the picture - so the file had to be chosen by
name from a list nobody could see. A seller who has just scanned the fronts and
the backs of the cards being replaced is holding two sheets, not two
carefully-named files: what they want is to point at the scan, see the nine
cards on it, and click the front and then the back.

That is the whole of this file: what a chosen file is (a nine-slot sheet or a
single card photo), and which picture has been clicked for the front and which
for the back. There is no Tkinter here and nothing touches the network, so
every rule below is checked without a window - ``test-photo-pictures.py``.
"""
from pathlib import Path

import photo_replace

try:
    from PIL import Image
except ImportError:                                   # pragma: no cover
    Image = None

#: What the app can read as a picture (the same list the file pickers offer).
PICTURE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")

#: A scan at least this big on its shorter side holds nine cards; anything
#: smaller is one card photographed on its own. It is only a starting guess:
#: a single card scanned at 600 dpi is as tall as a sheet scanned at 200, so
#: the window always offers the other reading in one click and says which one
#: it used.
SHEET_MIN_SIDE = 1200

#: Nine slots in one row where the window is wide enough for them.
GRID_COLUMNS_MAX = 9

#: The two photos a card has, in the order the shop shows them.
SIDES = ("front", "back")


class PhotoPickError(Exception):
    """A chosen file cannot be read, said in words rather than a traceback."""


def is_picture(path):
    """True when ``path`` has a picture's extension."""
    return Path(str(path or "")).suffix.lower() in PICTURE_SUFFIXES


def size_of(path):
    """``(width, height)`` of a picture, read from its header."""
    path = Path(str(path or ""))
    if not path.is_file():
        raise PhotoPickError("That file is not on this computer any more: %s"
                             % path)
    if Image is None:
        raise PhotoPickError("Pillow is required to read a scan's pictures.")
    try:
        with Image.open(path) as opened:
            return tuple(opened.size)
    except Exception as exc:                    # noqa: BLE001 - any failure
        raise PhotoPickError("Could not read %s: %s"
                             % (path.name, exc)) from exc


def looks_like_sheet(size):
    """True when a picture is big enough to be a scan of nine cards."""
    try:
        short = min(int(size[0]), int(size[1]))
    except (TypeError, ValueError, IndexError):
        return False
    return short >= SHEET_MIN_SIDE


def guess_kind(path):
    """``"sheet"`` or ``"picture"``, from the file's own size."""
    return "sheet" if looks_like_sheet(size_of(path)) else "picture"


def kind_words(kind):
    """What a source turned out to be, in the words the window uses."""
    return "a sheet of nine cards" if str(kind) == "sheet" else "one picture"


def cut_sheet(path, output_dir, prefix=""):
    """The nine slots of a scan without the empty ones.

    Returns ``(tiles, empties)``: one ``{"path", "position", "label"}`` per
    card that is really on the sheet, and how many slots were left empty.
    """
    try:
        slots = photo_replace.split_sheet(path, output_dir,
                                          prefix=prefix or None)
    except photo_replace.PhotoReplaceError as exc:
        raise PhotoPickError(str(exc)) from exc
    tiles, empties = [], 0
    for slot in slots:
        if slot.get("blank") or not slot.get("path"):
            empties += 1
            continue
        tiles.append({"path": slot["path"],
                      "position": int(slot.get("position") or 0),
                      "label": "Slot %d" % int(slot.get("position") or 0)})
    return tiles, empties


def pictures_in(path, output_dir, as_sheet=None):
    """What to show for one chosen file: its nine slots, or the file itself.

    ``as_sheet`` forces the reading - ``True`` cuts it into nine, ``False``
    treats the whole file as one picture - and ``None`` guesses from the size.
    Returns ``{"source", "kind", "tiles", "empties", "words"}``.
    """
    path = Path(str(path or ""))
    if not is_picture(path):
        raise PhotoPickError("That file is not a picture the app can read: %s"
                             % path)
    if as_sheet is None:
        kind = guess_kind(path)
    else:
        kind = "sheet" if as_sheet else "picture"
    if kind == "sheet":
        tiles, empties = cut_sheet(path, output_dir, prefix=path.stem)
        if not tiles:
            raise PhotoPickError(
                "Every slot on %s is empty, so there is no picture to choose. "
                "Run the scan again - or, if the file is one card "
                "photographed on its own, use it as one picture." % path.name)
        words = "%s - %d picture%s cut from the sheet" % (
            path.name, len(tiles), "" if len(tiles) == 1 else "s")
        if empties:
            words += " (%d empty slot%s left out)" % (
                empties, "" if empties == 1 else "s")
    else:
        tiles = [{"path": path, "position": 0, "label": path.name}]
        empties = 0
        words = "%s - the whole file is the picture" % path.name
    for tile in tiles:
        tile["sheet"] = str(path) if kind == "sheet" else ""
        tile.setdefault("side", "")
    return {"source": str(path), "kind": kind, "tiles": tiles,
            "empties": empties, "words": words}


def slot_proposal(front_tiles, back_tiles):
    """A function naming the back in the same slot as a chosen front.

    The two scans are usually one sitting: the fronts, then the same nine
    slots photographed backs. So the back in the front's slot is offered
    before anything is clicked - and it is only an offer: clicking another
    back replaces it, and the window says which of the two it is.
    """
    by_slot = {}
    for tile in back_tiles or ():
        position = int(tile.get("position") or 0)
        if position and position not in by_slot:
            by_slot[position] = str(tile.get("path") or "")

    def suggest(front_key):
        for tile in front_tiles or ():
            if str(tile.get("path") or "") == str(front_key or ""):
                return by_slot.get(int(tile.get("position") or 0), "")
        return ""

    return suggest


class Picks:
    """Which picture has been clicked for the front, and which for the back.

    A click on a marked picture takes the mark off again, so a front-only or a
    back-only replacement is one click away from both. Nothing here writes
    anything: the window asks, and this answers what the seller has chosen.
    """

    def __init__(self, can_back=True, suggest=None):
        #: The plugin in use may be too old to replace a back without adding a
        #: second one beside it, in which case the back strip is not offered.
        self.can_back = bool(can_back)
        #: ``suggest(front_key) -> back_key``, normally :func:`slot_proposal`.
        #  A strip that changes rebuilds it from the pictures now on screen, so
        #  an earlier sheet's proposal can never select a picture that is not
        #  there any more; a caller with its own rule passes it here and keeps
        #  it across loads.
        self.suggest = suggest
        self._suggest = suggest
        self.front = ""
        self.back = ""
        self._offered = False       # True when the back is a slot proposal
        self._tiles = {side: [] for side in SIDES}
        self._source = {side: "" for side in SIDES}
        self._kind = {side: "" for side in SIDES}

    # -- the strips ---------------------------------------------------------
    def load(self, side, source, kind, tiles):
        """Show a new strip for one side, keeping any choice still on it."""
        side = str(side or "").lower()
        if side not in SIDES:
            return
        self._source[side] = str(source or "")
        self._kind[side] = str(kind or "")
        self._tiles[side] = list(tiles or ())
        here = self.keys(side)
        if side == "front":
            if self.front not in here:
                self.front = ""
            if self.back == self.front and self.back:
                self.back = ""
                self._offered = False
        elif self.back not in here:
            self.back = ""
            self._offered = False
        #  A strip that changed may hold the slot of the front that is already
        #  clicked - the back sheet is usually chosen second - so the proposal
        #  is rebuilt from the two strips as they stand now.
        self.suggest = self._suggest or slot_proposal(
            self._tiles["front"], self._tiles["back"])
        self.offer()

    def keys(self, side):
        """Every picture on one strip, as the window knows them."""
        return {str(tile.get("path") or "")
                for tile in self._tiles.get(str(side), ())}

    def tiles(self, side):
        return list(self._tiles.get(str(side), ()))

    def source(self, side):
        return self._source.get(str(side), "")

    def kind(self, side):
        return self._kind.get(str(side), "")

    def offered(self, side):
        """True when the back showing is a slot proposal, not a click."""
        return str(side) == "back" and bool(self.back) and self._offered

    # -- what is chosen -----------------------------------------------------
    def chosen(self, side):
        if str(side) == "front":
            return self.front
        if str(side) == "back":
            return self.back
        return ""

    def slots(self):
        return tuple(side for side in SIDES if self.chosen(side))

    def ready(self):
        return bool(self.slots())

    def missing(self):
        """What is still to be clicked, in one sentence; ``""`` when ready."""
        if self.ready():
            return ""
        if self.can_back:
            return ("Click the picture that is the card's new front, its new "
                    "back, or both.")
        return "Click the picture that is the card's new front."

    def button_words(self):
        slots = self.slots()
        if slots == SIDES:
            return "Replace both photos"
        if slots == ("front",):
            return "Replace the front photo"
        if slots == ("back",):
            return "Replace the back photo"
        return "Replace the photos"

    def summary(self):
        """``"Front: a.webp   Back: b.webp (offered by slot)"``."""
        parts = []
        for side in SIDES:
            path = self.chosen(side)
            if not path:
                continue
            note = " (offered by slot)" if self.offered(side) else ""
            parts.append("%s: %s%s" % (side.capitalize(),
                                       Path(path).name, note))
        return "   ".join(parts)

    # -- clicks -------------------------------------------------------------
    def pick(self, side, key):
        """Click one picture: it becomes that side, or stops being it."""
        side = str(side or "").lower()
        key = str(key or "")
        if side not in SIDES or not key:
            return ""
        if key not in self.keys(side):
            #  Only a picture the window is showing can be one of the photos.
            return ""
        if side == "back":
            #  A card's two photos cannot be the same file, and a plugin that
            #  cannot replace a back is not offered one at all.
            if not self.can_back or key == self.front:
                return self.back
            if key == self.back:
                self.back = ""
                self._offered = False
                return ""
            self.back = key
            self._offered = False
            return key
        if key == self.front:
            self.front = ""
            if self._offered:
                self.back = ""
                self._offered = False
            return ""
        self.front = key
        if self.back == key:
            self.back = ""
            self._offered = False
        self.offer()
        return key

    def offer(self):
        """Offer the back in the front's slot, unless a back was clicked.

        Called when the strips change as well as after a front is clicked: the
        back sheet is usually chosen after the front already is.
        """
        if not (self.can_back and self.front and callable(self.suggest)):
            return self.back
        if self.back and not self._offered:
            return self.back
        proposed = str(self.suggest(self.front) or "")
        if proposed and (proposed == self.front or
                         proposed not in self.keys("back")):
            #  A suggestion built from an earlier strip must never select a
            #  picture that is no longer on the screen.
            proposed = ""
        if not proposed:
            if self._offered:
                self.back = ""
                self._offered = False
            return self.back
        self.back = proposed
        self._offered = True
        return self.back

    def paths(self):
        """``{"front": path, "back": path}`` for the chosen pictures."""
        return {side: self.chosen(side) for side in self.slots()}
