"""The replacement sheets loaded for one session, and which tiles are still free.

Replacing a photo used to start with a card name and then a file dialog, so the
same sheet was split again for every card and nothing remembered which of its
images had already been used. This keeps the sheets for the whole sitting:
load them once, then take a front and a back off them card by card.

The paired back is the tile in the *same slot position* on the back sheet,
because the two sheets are scanned in the same order. That is only a proposal -
the picker can always choose something else - but it is right often enough to
remove the second pass over the scan.
"""

from pathlib import Path

import photo_replace

SIDES = ("front", "back")


class PhotoPoolError(Exception):
    """A sheet could not be added to the pool."""


def guess_side(index, name=""):
    """Which half of the pair a sheet holds, from its position and its name.

    A dropped pair arrives front first, which is what the pipeline assumes, so
    :func:`guess_side` only leans on the position when the name says nothing.
    """
    text = Path(str(name or "")).stem.lower()
    if "back" in text:
        return "back"
    if "front" in text:
        return "front"
    index = int(index) if str(index).isdigit() else -1
    return SIDES[index] if 0 <= index < len(SIDES) else ""


class PhotoPool:
    """The loaded sheets and their usable tiles."""

    def __init__(self, tiles_dir=None, split=None):
        self.tiles_dir = Path(tiles_dir) if tiles_dir else None
        self._split = split or photo_replace.split_sheet
        self.sheets = []          # one record per loaded sheet
        self._tiles = []          # every usable tile, in the order added

    # -- loading -----------------------------------------------------------
    def add_sheet(self, path, side="", index=0):
        """Split a scan and keep its card images.

        Adding the same file twice is a no-op, so a repeated drop cannot fill
        the pool with duplicates. Raises :class:`PhotoPoolError` when the file
        cannot be read or holds no cards.
        """
        path = Path(path)
        if not path.is_file():
            raise PhotoPoolError("The sheet is missing: %s" % path)
        for sheet in self.sheets:
            if sheet["path"] == path.resolve():
                return sheet
        side = side or guess_side(index, path.name)
        folder = (self.tiles_dir or path.parent) / "_tiles" / path.stem
        try:
            found = self._split(path, folder)
        except photo_replace.PhotoReplaceError as exc:
            raise PhotoPoolError(str(exc))
        except Exception as exc:            # unreadable image, bad geometry
            raise PhotoPoolError("Could not split %s: %s" % (path.name, exc))
        usable = [tile for tile in found
                  if not tile.get("blank") and tile.get("path")]
        if not usable:
            raise PhotoPoolError(
                "Every slot on %s looks empty (a black background)."
                % path.name)
        sheet = {"path": path.resolve(), "name": path.name, "side": side,
                 "slots": len(found), "usable": len(usable)}
        self.sheets.append(sheet)
        for tile in usable:
            self._tiles.append({
                "position": tile["position"], "path": Path(tile["path"]),
                "blank": False, "sheet": path.name, "side": side,
                "sheet_path": sheet["path"], "used_by": ""})
        return sheet

    def clear(self):
        self.sheets.clear()
        self._tiles.clear()

    # -- looking at what is loaded -----------------------------------------
    def __len__(self):
        return len(self._tiles)

    def tiles(self, side=None, unused_only=False):
        """Every tile, optionally one side only and only the free ones."""
        found = []
        for tile in self._tiles:
            if unused_only and tile["used_by"]:
                continue
            if side and tile["side"] and tile["side"] != side:
                continue
            found.append(tile)
        return found

    def unused(self, side=None):
        return self.tiles(side=side, unused_only=True)

    def sheet(self, name):
        for sheet in self.sheets:
            if sheet["name"] == name:
                return sheet
        return None

    # -- choosing ----------------------------------------------------------
    def front_candidates(self):
        """Free tiles a front could come from: fronts first, then unknowns."""
        tiles = self.unused()
        return sorted(tiles, key=lambda t: 0 if t["side"] == "front" else
                      (1 if not t["side"] else 2))

    def back_candidates(self, front=None):
        """Free tiles a back could come from, excluding the chosen front."""
        tiles = [t for t in self.unused() if front is None or
                 t["path"] != front["path"]]
        return sorted(tiles, key=lambda t: 0 if t["side"] == "back" else
                      (1 if not t["side"] else 2))

    def same_slot(self, tile):
        """The tile in the same slot position on the other sheet, if free.

        This is the pairing the scanner produced for free: both sheets were
        filled in the same order, so slot 4 of the back sheet is the back of
        slot 4 of the front sheet.
        """
        best = []
        for other in self.unused():
            if other["path"] == tile["path"]:
                continue
            if other["sheet_path"] == tile["sheet_path"]:
                continue
            if other["position"] != tile["position"]:
                continue
            if other["side"] and tile["side"] and \
                    other["side"] == tile["side"]:
                continue
            best.append(other)
        best.sort(key=lambda t: 0 if (t["side"] and t["side"] != tile["side"])
                  else 1)
        return best[0] if best else None

    # -- using -------------------------------------------------------------
    def take(self, tile, product=""):
        """Mark a tile as used by ``product``; False when it was already gone."""
        if tile is None:
            return False
        for candidate in self._tiles:
            if candidate["path"] == tile["path"]:
                if candidate["used_by"]:
                    return False
                candidate["used_by"] = product or "this card"
                return True
        return False

    def release(self, tile):
        """Put a tile back, so a cancelled replacement can be retried."""
        for candidate in self._tiles:
            if tile is not None and candidate["path"] == tile["path"]:
                candidate["used_by"] = ""
                return True
        return False

    # -- telling the user ---------------------------------------------------
    def summary(self):
        """One line per sheet, for the panel to show what is loaded."""
        lines = []
        for sheet in self.sheets:
            free = len([t for t in self._tiles
                        if t["sheet_path"] == sheet["path"] and
                        not t["used_by"]])
            lines.append("%s %s \u00b7 %d of %d slots \u00b7 %d free" % (
                sheet["name"], "(%s)" % sheet["side"] if sheet["side"] else "",
                sheet["usable"], sheet["slots"], free))
        return lines

    def progress(self):
        """``(used, total)`` so the panel can say how much work is left."""
        used = len([t for t in self._tiles if t["used_by"]])
        return used, len(self._tiles)
