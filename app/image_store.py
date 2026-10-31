"""Where a batch's card images go once the next batch needs the folder back.

Every run writes its images into one working folder: the split puts the tiles
in ``pipeline/output`` and the listing stage renames them to their listing
titles, while a replacement sitting cuts the card fronts it uses out of a scan
into ``replacements``. Neither folder empties itself, so after a few batches
they hold every image the shop has ever used - and finding this week's card in
a list of four thousand is hopeless.

This is the rule that keeps them apart: a folder of images belongs to the last
batch until something new is about to be written into it, and then the older
images are **moved** to the folder chosen in User settings. It is a move, not
a delete: nothing is removed, nothing is renamed, and every image keeps the
name it was given. The move is only ever done after being asked - this module
plans it and does it, and the caller owns the question.

Only two places are looked at, deliberately: the folder itself and the
``_tiles`` working folder the replacement sheets are cut into. A folder a
person chose to keep images in is not a place to go hunting through.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

#: What counts as an image. Everything else in these folders belongs to the
#: batch as a record - a CSV, a report - and is never touched.
IMAGE_SUFFIXES = frozenset({".webp", ".jpg", ".jpeg", ".png", ".tif", ".tiff",
                            ".bmp", ".gif"})

#: The only sub-folder that is part of the work: the split sheets' tiles.
TILES_DIRNAME = "_tiles"


def plural(count, word):
    """``1 image`` / ``27 images`` - the small thing that makes a log readable."""
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


def is_image(path):
    """Whether a path is an image this app wrote (by its extension)."""
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def images_in(folder, keep=()):
    """Every image a batch left in ``folder``, in a stable order.

    ``keep`` is a set of paths that belong to something still in use - the
    current sitting's replacement tiles - and those are never offered.

    A missing folder is not an error: it means nothing has been written yet.
    """
    folder = Path(folder)
    kept = {Path(path).resolve() for path in keep or () if path}
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    found = []
    for entry in entries:
        try:
            if entry.is_file():
                if is_image(entry) and entry.resolve() not in kept:
                    found.append(entry)
            elif entry.is_dir() and entry.name == TILES_DIRNAME:
                for tile in sorted(entry.rglob("*"),
                                   key=lambda p: str(p).lower()):
                    if (tile.is_file() and is_image(tile)
                            and tile.resolve() not in kept):
                        found.append(tile)
        except OSError:
            continue          # a file that vanished or refuses to be read
    return found


def folder_label(folder):
    """A short name for a working folder, for messages and the store path."""
    name = Path(folder).name.strip()
    return name or "images"


def stamp(now=None):
    """The name one batch's moved images are filed under, safe on Windows.

    No colons: a Windows path cannot hold them, and this is a folder name.
    """
    return (now or datetime.now()).strftime("%Y-%m-%d %H-%M")


def check_store(store, folder):
    """Why ``store`` cannot be used as the place to move ``folder``'s images.

    Returns ``""`` when it can. The two cases that matter are a folder inside
    the one being emptied (which would move images back into the pile) and the
    folder itself.
    """
    #  Checked as text first: Path("") is the current folder, which would
    #  otherwise be compared as though somebody had chosen "here".
    if not str(store or "").strip():
        return "no folder has been chosen for the older card images"
    store, folder = Path(store), Path(folder)
    try:
        store_r, folder_r = store.resolve(), folder.resolve()
    except OSError:
        store_r, folder_r = store, folder
    if store_r == folder_r:
        return ("the folder chosen for the older card images is the folder "
                "they are being moved out of")
    if folder_r in store_r.parents:
        return ("the folder chosen for the older card images is inside %s, "
                "so moving them there would leave them in the pile" % folder)
    #  The dated folders are one level further in than the store
    #  (``<store>/output/<date>``), so the store can be fine while that path
    #  is not: choosing the batch folder itself would put this batch's
    #  leftovers back inside output/, one folder down, where nothing would
    #  ever look for them again.
    target_root = store_r / folder_label(folder_r)
    if target_root == folder_r or folder_r in target_root.parents:
        return ("the dated folders would be created inside %s itself, which "
                "is the folder being emptied - choose a folder outside the "
                "batch folder" % folder)
    return ""


def plan(folder, store, keep=(), now=None):
    """What moving this folder's older images would do.

    Returns a dictionary rather than doing anything, so the same answer can be
    shown to the person first: where the images would go and how many there
    are. ``files`` is empty when there is nothing to move.
    """
    folder, store = Path(folder), Path(store)
    files = images_in(folder, keep=keep)
    when = stamp(now)
    target = store / folder_label(folder) / when
    #  The same folder twice in one minute is not impossible (two sittings
    #  back to back); the second one gets its own place rather than mixing.
    counter = 2
    while _has_files(target):
        target = store / folder_label(folder) / ("%s (%d)" % (when, counter))
        counter += 1
    return {"folder": folder, "store": store, "target": target,
            "files": files, "stamp": when}


def describe(plan_result):
    """One line: how many images, where they are now, where they would go."""
    files = (plan_result or {}).get("files") or []
    if not files:
        return "There are no older card images to move."
    return ("%s from %s would move to %s"
            % (plural(len(files), "older card image"),
               (plan_result or {}).get("folder"),
               (plan_result or {}).get("target")))


def _has_files(path):
    """Whether a folder exists and holds anything - without raising."""
    try:
        return path.is_dir() and any(path.iterdir())
    except OSError:
        return False


def _free_name(path):
    """``name.webp``, or ``name (2).webp`` when that name is already taken."""
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name("%s (%d)%s"
                                   % (path.stem, counter, path.suffix))
        if not candidate.exists():
            return candidate
        counter += 1


def move(plan_result):
    """Do what :func:`plan` described; report what happened to each file.

    Nothing is ever overwritten and nothing is ever deleted. A file that
    cannot be moved (one the shop is still uploading from, a folder with no
    permission) is left exactly where it is and named in ``failed``, because
    half a move is still better than a batch that refuses to start.
    """
    folder = Path(plan_result["folder"])
    target = Path(plan_result["target"])
    moved, failed = [], []
    for source in plan_result.get("files") or []:
        try:
            relative = source.relative_to(folder)
        except ValueError:
            relative = Path(source.name)
        destination = _free_name(target / relative)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        except OSError as exc:
            failed.append({"name": source.name, "why": str(exc)})
            continue
        moved.append({"from": source, "to": destination})
    return {"moved": moved, "failed": failed, "target": target,
            "folder": folder}


def result_text(result):
    """The console lines for a finished move, in the order a person reads them."""
    result = result or {}
    moved = result.get("moved") or []
    failed = result.get("failed") or []
    lines = []
    if moved:
        lines.append("Moved %s to %s."
                     % (plural(len(moved), "older card image"),
                        result.get("target")))
    if failed:
        lines.append("%s could not be moved and %s still in %s: %s."
                     % (plural(len(failed), "older card image"),
                        "is" if len(failed) == 1 else "are",
                        result.get("folder"),
                        ", ".join(item["name"] for item in failed[:3])))
    if not lines:
        lines.append("There were no older card images to move.")
    return lines
