"""Helpers for replacing one card's photos.

The replacement workflow starts from a fresh 3x3 sheet scan, not from a
pipeline run: split the sheet, ignore the empty slots, name the keeper the same
as the card's current website image plus a counter, and repeat until the sheet
is used up.

Nothing here uses Tkinter or the network, so the rules are testable without a
GUI and without touching a website.

The split geometry deliberately mirrors card_pipeline: a replacement scan is
the same physical sheet as a listing scan, so it must be cropped identically.
test-photo-replace.py asserts the constants stay equal rather than trusting
this comment.
"""
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - reported by the tools that need it
    Image = None

# --- split geometry: keep in step with card_pipeline ----------------------
GRID_COLS = 3
GRID_ROWS = 3
TOTAL_CARDS = GRID_COLS * GRID_ROWS
IMG_FORMAT = "webp"
BOTTOM_CROP = 400
BORDER_CROP = 72
TARGET_WIDTH = 600
TARGET_KB = 110
MIN_QUALITY = 80
MAX_QUALITY = 100
QUALITY_TOLERANCE = 5

# --- blank slot detection -------------------------------------------------
# An unused slot on the sheet scans as a black plastic pocket. A real card is
# never that dark on average, so a tile only counts as empty when it is BOTH
# very dark on average AND almost entirely dark pixel by pixel. Two conditions
# keep a dark card (black border, heavy shadow) from being thrown away.
DARK_LEVEL = 32          # a pixel this bright or darker counts as dark
BLANK_MEAN = 24          # average brightness of a fully black tile
BLANK_COVERAGE = 0.98    # share of dark pixels a blank tile must have


class PhotoReplaceError(Exception):
    """A replacement job could not be prepared."""


def tile_is_blank(tile, dark_level=DARK_LEVEL, mean_limit=BLANK_MEAN,
                  coverage=BLANK_COVERAGE):
    """True when a tile is an empty (black) slot on the sheet."""
    if tile is None:
        return True
    grey = tile.convert("L")
    histogram = grey.histogram()
    total = sum(histogram)
    if not total:
        return True
    dark = sum(histogram[:dark_level])
    mean = sum(value * count for value, count in enumerate(histogram)) / total
    return mean <= mean_limit and (dark / total) >= coverage


def _crop_tile(image, row, col):
    """One tile of the sheet, cropped the same way card_pipeline crops it."""
    width, height = image.size
    tile_w = width // GRID_COLS
    tile_h = height // GRID_ROWS
    box = (col * tile_w, row * tile_h,
           (col + 1) * tile_w, (row + 1) * tile_h)
    tile = image.crop(box)
    tw, th = tile.size
    tile = tile.crop((BORDER_CROP, BORDER_CROP, tw - BORDER_CROP,
                      th - BORDER_CROP))
    tw, th = tile.size
    new_height = int((TARGET_WIDTH / tw) * th)
    return tile.resize((TARGET_WIDTH, new_height), Image.LANCZOS)


def _save_target_size(image, output_path):
    """Save as WebP near TARGET_KB, matching the pipeline's file size."""
    from io import BytesIO

    target_bytes = TARGET_KB * 1024
    low, high = MIN_QUALITY, MAX_QUALITY
    best = None
    while low <= high:
        mid = (low + high) // 2
        buffer = BytesIO()
        image.save(buffer, "WEBP", quality=mid, method=6, optimize=True)
        size = buffer.tell()
        if abs(size - target_bytes) <= (QUALITY_TOLERANCE * 1024):
            best = buffer.getvalue()
            break
        if size > target_bytes:
            high = mid - 1
        else:
            best = buffer.getvalue()
            low = mid + 1
    if best is None:
        buffer = BytesIO()
        image.save(buffer, "WEBP", quality=MIN_QUALITY, method=6, optimize=True)
        best = buffer.getvalue()
    Path(output_path).write_bytes(best)


def split_sheet(scan_path, output_dir, skip_blank=True,
                prefix=None):
    """Cut a 3x3 sheet into tiles, reporting which ones are empty.

    Returns one dict per position, in reading order:

        {"position": 1..9, "path": Path or None, "blank": bool}

    ``path`` is None for an empty slot. ``blank`` is always reported, so a
    caller can show "3 of 9 slots are empty" even when it keeps the files.
    """
    if Image is None:
        raise PhotoReplaceError("Pillow is required to read scan images.")
    scan_path = Path(scan_path)
    if not scan_path.is_file():
        raise PhotoReplaceError("Scan not found: %s" % scan_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = prefix or scan_path.stem

    image = Image.open(scan_path)
    width, height = image.size
    image = image.crop((0, 0, width, height - BOTTOM_CROP))

    results = []
    position = 1
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            tile = _crop_tile(image, row, col)
            blank = tile_is_blank(tile)
            path = None
            if not (blank and skip_blank):
                path = output_dir / ("%s_%d.%s" % (prefix, position, IMG_FORMAT))
                _save_target_size(tile, path)
            results.append({"position": position, "path": path,
                            "blank": blank})
            position += 1
    return results


def woo_image_name(product):
    """The filename of the card's current website image, or "".

    The first image is the one the product card shows, so that is the name a
    replacement has to line up with.
    """
    images = (product or {}).get("images") or []
    for image in images:
        if not isinstance(image, dict):
            continue
        source = str(image.get("src") or image.get("name") or "").strip()
        if source:
            return source.rstrip("/").rsplit("/", 1)[-1]
    return ""


def replacement_stem(image_name):
    """The base a replacement name grows from.

    A counter already on the name is dropped so replacements keep counting from
    the original: ``...-front-1.webp`` yields ``...-front``, which makes the
    next free name ``...-front-2.webp`` rather than ``...-front-1-1.webp``.
    """
    stem = Path(str(image_name or "")).stem
    if not stem:
        return ""
    parts = stem.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return stem


def next_available_path(folder, stem, suffix="." + IMG_FORMAT):
    """``stem-1.suffix``, then ``-2``, ``-3`` ... whichever is free first."""
    folder = Path(folder)
    if not stem:
        raise PhotoReplaceError("No image name to count from.")
    counter = 1
    while True:
        candidate = folder / ("%s-%d%s" % (stem, counter, suffix))
        if not candidate.exists():
            return candidate
        counter += 1


SIDES = ("front", "back")


def side_of(image_name):
    """``"front"``, ``"back"``, or "" when the name carries no side suffix.

    The site's convention is that a card's two photos differ only by that
    suffix, so it is the one thing that can be trusted when deciding which
    existing gallery rows belong to the pair being replaced.
    """
    stem = replacement_stem(image_name).lower()
    for side in SIDES:
        if stem.endswith("-" + side):
            return side
    return ""


def pair_stem(image_name):
    """The name both photos of a card share, without side or counter.

    ``dallas-smith-front.webp`` and ``dallas-smith-back-2.webp`` both yield
    ``dallas-smith``, so a replacement pair is always built from one stem.
    """
    stem = replacement_stem(image_name)
    side = side_of(stem)
    return stem[: -(len(side) + 1)] if side else stem


def pair_paths(folder, image_name, suffix="." + IMG_FORMAT,
               force_sided=False):
    """The next free front/back pair, sharing one counter.

    Both names are counted together: if ``-front-1`` is taken, the pair starts
    at ``-2`` even when ``-back-1`` is free, because a half-numbered pair is
    harder to reason about than a skipped number.

    A name with no side keeps its own shape for the front, so a legacy image
    is not renamed and only the back gains the suffix. That shape is not a
    matched pair, though, so anything sending both halves to the plugin must
    pass ``force_sided`` - the plugin verifies the two names differ only by
    ``-front``/``-back`` and rejects a pair that does not.
    """
    folder = Path(folder)
    base = pair_stem(image_name)
    if not base:
        raise PhotoReplaceError("No image name to build a pair from.")
    sided = bool(side_of(image_name)) or bool(force_sided)
    counter = 1
    while True:
        front = folder / ("%s%s-%d%s" % (base, "-front" if sided else "",
                                         counter, suffix))
        back = folder / ("%s-back-%d%s" % (base, counter, suffix))
        if not front.exists() and not back.exists():
            return {"front": front, "back": back, "counter": counter,
                    "sided": sided}
        counter += 1


def pair_ids(images):
    """The gallery rows that are a card's old front and back.

    Rows are matched by the ``-front``/``-back`` suffix. A gallery that
    predates the convention has no suffix to match, so its first row is
    treated as the front: that is the image the product card shows, and
    dropping it is the whole point of a replacement.
    """
    ids = [row.get("id") for row in images or []
           if side_of(row.get("name")) in SIDES]
    ids = [i for i in ids if i is not None]
    if images and not ids:
        ids = [images[0].get("id")]
    return [i for i in ids if i is not None]


def save_pair(folder, image_name, front_tile, back_tile=None):
    """Copy the chosen tiles in as a front/back pair sharing one counter.

    Both source files are checked before either is written, so a failure can
    not leave a front with no back. Returns the written paths.
    """
    sources = [("front", front_tile)]
    if back_tile is not None:
        sources.append(("back", back_tile))
    for label, tile in sources:
        if not Path(tile).is_file():
            raise PhotoReplaceError("The %s image is missing: %s" % (label, tile))
    #  The replacements folder is normally made before this is called; doing it
    #  here as well means save_pair() can be used on its own.
    Path(folder).mkdir(parents=True, exist_ok=True)
    suffix = Path(front_tile).suffix or "." + IMG_FORMAT
    #  Without a product there is no website image to copy the name from - the
    #  search-page fallback has none - so the scan's own name is used. Refusing
    #  to save the image the user just chose would throw away their work.
    name = image_name or Path(front_tile).stem
    targets = pair_paths(folder, name, suffix,
                         force_sided=back_tile is not None)
    written = {}
    for label, tile in sources:
        target = targets[label]
        target.write_bytes(Path(tile).read_bytes())
        written[label] = target
    return written


def plan_replacement(folder, image_name, tile_path):
    """Where a chosen tile should be written, and under what name."""
    tile_path = Path(tile_path)
    stem = replacement_stem(image_name)
    if not stem:
        stem = tile_path.stem
    target = next_available_path(Path(folder), stem,
                                 tile_path.suffix or "." + IMG_FORMAT)
    return target


def copy_as_replacement(folder, image_name, tile_path):
    """Copy a chosen tile into ``folder`` under the next replacement name."""
    tile_path = Path(tile_path)
    if not tile_path.is_file():
        raise PhotoReplaceError("Replacement image not found: %s" % tile_path)
    target = plan_replacement(folder, image_name, tile_path)
    target.write_bytes(tile_path.read_bytes())
    return target
