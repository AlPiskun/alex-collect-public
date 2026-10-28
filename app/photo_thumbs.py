"""Small pictures of a sheet's tiles, and the grid the picker lays them out in.

The panel names its tiles ``Scan01_4.webp``, which says nothing about what is
on them. These helpers turn a tile into a picture small enough to show nine at
once, so an image can be chosen by looking at it instead of by reading a name.

The Tk half is deliberately optional: ``as_photo()`` returns ``None`` wherever
tkinter or its image module is missing, and the caller falls back to a plain
list. That keeps the app (and its tests) runnable without a display.
"""

from pathlib import Path

try:
    from PIL import Image
except ImportError:                                   # pragma: no cover
    Image = None

#  Tall enough to recognise a card, small enough that nine fit on screen with
#  their captions and the buttons underneath.
THUMB_SIZE = (132, 176)
GRID_COLUMNS = 3


class ThumbnailError(Exception):
    """A tile could not be turned into a picture."""


def thumbnail(path, size=THUMB_SIZE):
    """A small copy of one tile, kept in proportion.

    Returns a PIL image. Raises :class:`ThumbnailError` when the file is
    missing or unreadable - the caller is showing a picture of a real choice,
    so silently returning a blank square would be a lie.
    """
    if Image is None:
        raise ThumbnailError("Pillow is required to show tile pictures.")
    path = Path(path)
    if not path.is_file():
        raise ThumbnailError("The tile is missing: %s" % path)
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
    except Exception as exc:
        raise ThumbnailError("Could not read %s: %s" % (path.name, exc))
    image.thumbnail(size, Image.LANCZOS)
    return image


class Thumbnails:
    """A per-run cache, so a nine-tile grid decodes each file once.

    The panel re-shows the same sheets after every card, and re-reading nine
    webp files each time is wasted work on a slow laptop.
    """

    def __init__(self, size=THUMB_SIZE):
        self.size = size
        self._cache = {}
        self.failures = []

    LIMIT = 48          # a long sitting is a handful of sheets, not a library

    def get(self, path):
        """The picture for ``path``, or None when it cannot be read."""
        key = str(path)
        if key in self._cache:
            return self._cache[key]
        if len(self._cache) >= self.LIMIT:
            #  Small pictures, but a whole afternoon of sheets would still
            #  add up; the ones being looked at are the ones worth keeping.
            self._cache.clear()
        try:
            image = thumbnail(path, self.size)
        except ThumbnailError as exc:
            self.failures.append((key, str(exc)))
            self._cache[key] = None
            return None
        self._cache[key] = image
        return image

    def clear(self):
        self._cache.clear()
        self.failures.clear()


def as_photo(image):
    """A Tk-displayable copy of ``image``, or None when Tk cannot take one.

    ``PhotoImage`` objects are garbage collected as soon as nothing references
    them, which shows up as a blank label, so the caller has to keep whatever
    this returns for as long as the widget is on screen.
    """
    if image is None:
        return None
    try:
        from PIL import ImageTk
        return ImageTk.PhotoImage(image)
    except Exception:
        #  No tkinter (a headless test run) or no image support in this build.
        return None


def rows(items, columns=GRID_COLUMNS):
    """``items`` as a list of rows, so a grid is laid out in reading order."""
    columns = max(1, int(columns))
    items = list(items)
    return [items[i:i + columns] for i in range(0, len(items), columns)]


def caption(tile, sheet="", side=True):
    """The line under a tile's picture: where it came from, in a few words.

    The sheet's file name is deliberately not part of it. Under every picture
    it costs a wrapped line - and at 800x600 that line is the difference
    between nine cards on screen and six - while saying nothing the picture
    and the picker's own question do not already say. ``sheet`` is passed in
    only when the grid really does mix sheets and the reader could not tell
    otherwise, and ``side`` when it mixes fronts and backs.
    """
    parts = []
    if sheet:
        parts.append(str(sheet))
    position = tile.get("position")
    if position:
        parts.append("Slot %d" % position)
    if side:
        name = tile.get("side") or ""
        if name:
            parts.append(name)
    return " \u00b7 ".join(parts) if parts else Path(
        str(tile.get("path") or "")).name


def describe(tile):
    """A tile in one line, used when there is no picture to show."""
    name = Path(str(tile.get("path") or "")).name
    line = caption(tile, sheet=tile.get("sheet") or "")
    return "%s   (%s)" % (line, name) if line else name
