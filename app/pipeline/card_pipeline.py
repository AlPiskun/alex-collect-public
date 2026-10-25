#!/usr/bin/env python3
"""
Alex Collect — Unified Card Listing Pipeline

Commands
--------
  split    – Cut a 3x3 sleeve scan into 9 individual card images.
             Uses the original prefix-based naming (prefix_1..prefix_9).
             Applies bottom crop, border crop, resize, and target file size.

  listing  – Parse AI-generated listing text, auto-detect front/back
             prefixes by timestamp, rename card images with SEO names
             (mirrored backs), detect categories with confirmation,
             produce a WooCommerce-ready CSV, prompt for upload, refresh
             the Facebook feed, and optionally create a CanadianShopper CSV.

Sleeve image handling:
  - Split files live in ./output, named <prefix>_1 .. <prefix>_9.
  - The 1..9 suffix is the card's position in the sleeve.
  - Fronts map straight (file _N -> card N).
  - BACKS ARE ALWAYS MIRRORED left-to-right: within each row the outer
    columns swap (1<->3, 4<->6, 7<->9); the middle (2,5,8) stays.
  - Scan the FRONT sleeve first so its filename timestamp is older than
    the BACK's -- the script uses that to tell fronts from backs.

Category / sub-category:
  - Each card's category is auto-detected from its text against:
      Non Sports Card              (no sub-category)
      Sports Card > Baseball Card
      Sports Card > Basketball Card
      Sports Card > Football Card
      Sports Card > Hockey Card
  - After parsing, the script prints its guess for every card and asks
    you to confirm or correct before writing the CSV.
"""

import argparse
import csv
import html
import math
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit
from datetime import datetime
from io import BytesIO
from pathlib import Path

try:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
except ImportError:
    sys.exit("Pillow is required.  pip install Pillow")

# =====================================================================
#  CONFIGURATION
# =====================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
for _module_dir in (str(APP_DIR), str(SCRIPT_DIR)):
    if _module_dir not in sys.path:
        sys.path.insert(0, _module_dir)
from browser_utils import available_browsers, browser_label, open_urls as launch_urls
from output_history import (consolidate_csv_history,
                            consolidate_ebay_history, write_ebay_sidecar)
from user_settings import (load_user_settings, save_user_settings,
                           site_admin_url, site_url, feed_urls)

USER_SETTINGS = load_user_settings(APP_DIR / "gui-settings.json")
OUTPUT_DIR = SCRIPT_DIR / "output"
CANADIANSHOPPER_DIR = SCRIPT_DIR / "canadianshopper_products"
EBAY_QUICKLIST_DIR = SCRIPT_DIR / "ebay_quick_list"
WOOCOMMERCE_DIR = SCRIPT_DIR / "woocommerce_products"


def _roll_csv_history(directory, pattern, history_name, exclude_paths=(),
                      key_fields=()):
    try:
        result = consolidate_csv_history(
            directory, pattern, history_name, exclude_paths=exclude_paths,
            key_fields=key_fields)
        if result["files"]:
            print("  History updated: %s (%d record(s)); removed %d older file(s)." %
                  (result["history"], result["rows"], result["deleted"]))
        return result
    except Exception as exc:
        print("  ! Could not consolidate prior output files into %s: %s" %
              (Path(directory) / history_name, exc), file=sys.stderr)
        print("    Original files were kept; the current output can continue.")
        return None


def _roll_ebay_history(exclude_paths=()):
    try:
        result = consolidate_ebay_history(EBAY_QUICKLIST_DIR,
                                          exclude_paths=exclude_paths)
        if result["files"]:
            print("  eBay history updated: %s (%d run(s)); removed %d older file(s)." %
                  (result["history"], result["runs"], result["deleted"]))
        return result
    except Exception as exc:
        print("  ! Could not consolidate prior eBay Quick Lists: %s" % exc,
              file=sys.stderr)
        print("    Original pages were kept; the current run can continue.")
        return None


GRID_COLS = 3
GRID_ROWS = 3
TOTAL_CARDS = GRID_COLS * GRID_ROWS
IMG_FORMAT = "webp"

# --- IMAGE SPLIT SETTINGS ---
BOTTOM_CROP = 400       # pixels to trim from bottom of full scan
BORDER_CROP = 72        # pixels to trim from each edge of each card tile
TARGET_WIDTH = 600       # resize each card to this width (height scales)
TARGET_KB = 110          # target file size in KB
MIN_QUALITY = 80
MAX_QUALITY = 100
QUALITY_TOLERANCE = 5    # +/- KB acceptable range
# -----------------------------

SITE_URL = site_url(USER_SETTINGS)

# =====================================================================
#  STEP 1 — SPLIT SCANS  (original parameters)
# =====================================================================
def extract_prefix(filepath: Path) -> str:
    """Extract prefix from scan filename for split output names.

    e.g. 'Scan2026-08-04_142535.jpg' -> 'Scan2026-08-04_142535'"""
    return filepath.stem


def save_webp_target_size(img, output_path):
    """Save a PIL Image as WebP, using binary search on quality
    to hit the TARGET_KB file size within QUALITY_TOLERANCE."""
    target_bytes = TARGET_KB * 1024
    low = MIN_QUALITY
    high = MAX_QUALITY
    best_data = None

    while low <= high:
        mid = (low + high) // 2
        buffer = BytesIO()
        img.save(buffer, "WEBP", quality=mid, method=6, optimize=True)
        size = buffer.tell()

        if abs(size - target_bytes) <= (QUALITY_TOLERANCE * 1024):
            best_data = buffer.getvalue()
            break

        if size > target_bytes:
            high = mid - 1
        else:
            best_data = buffer.getvalue()
            low = mid + 1

    # Fallback if exact match not found
    if best_data is None:
        buffer = BytesIO()
        img.save(buffer, "WEBP", quality=MIN_QUALITY, method=6, optimize=True)
        best_data = buffer.getvalue()

    with open(output_path, "wb") as f:
        f.write(best_data)
    print(f"  -> {os.path.basename(output_path)} ({len(best_data) // 1024} KB)")


def split_scan(image_path: Path, output_dir: Path) -> list:
    """Split a 3x3 sleeve scan into 9 individual card images.

    Names them as {prefix}_1.webp through {prefix}_9.webp.

    Applies:
      1. Bottom crop (scanner bed edge)
      2. Grid split into 3x3 tiles
      3. Border crop per tile (sleeve pocket edges)
      4. Resize to TARGET_WIDTH
      5. Save as WebP at TARGET_KB file size

    Position numbering (left to right, top to bottom):
        1  2  3
        4  5  6
        7  8  9
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = extract_prefix(image_path)

    img = Image.open(image_path)
    w, h = img.size

    # Step 1: Crop bottom of full scan
    img = img.crop((0, 0, w, h - BOTTOM_CROP))
    w, h = img.size

    tile_w = w // GRID_COLS
    tile_h = h // GRID_ROWS

    created = []
    count = 1
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            # Step 2: Extract tile from grid
            box = (
                col * tile_w,
                row * tile_h,
                (col + 1) * tile_w,
                (row + 1) * tile_h
            )
            tile = img.crop(box)

            # Step 3: Remove sleeve borders from each tile
            tw, th = tile.size
            tile = tile.crop((
                BORDER_CROP,
                BORDER_CROP,
                tw - BORDER_CROP,
                th - BORDER_CROP
            ))

            # Step 4: Resize to target width (maintain aspect ratio)
            tw, th = tile.size
            new_height = int((TARGET_WIDTH / tw) * th)
            tile = tile.resize((TARGET_WIDTH, new_height), Image.LANCZOS)

            # Step 5: Save with target file size
            out_name = f"{prefix}_{count}.{IMG_FORMAT}"
            out_path = output_dir / out_name
            save_webp_target_size(tile, str(out_path))
            created.append(out_path)
            count += 1

    return created


def cmd_split(args):
    """Handle the 'split' sub-command."""
    front_path = Path(args.front)
    if not front_path.is_file():
        sys.exit(f"Front image not found: {front_path}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n-- Splitting FRONT: {front_path.name} --")
    split_scan(front_path, OUTPUT_DIR)

    if args.back:
        back_path = Path(args.back)
        if not back_path.is_file():
            sys.exit(f"Back image not found: {back_path}")
        print(f"\n-- Splitting BACK: {back_path.name} --")
        split_scan(back_path, OUTPUT_DIR)
    else:
        print("\nNo back image provided; only front images were created.")

    total = len(list(OUTPUT_DIR.glob(f"*.{IMG_FORMAT}")))
    sides = "2 sides" if args.back else "1 side"
    print(f"\n{TOTAL_CARDS} card(s) x {sides} = {total} images in output/")


# =====================================================================
#  PART 2 — TEXT PARSING (listing text -> structured card data)
# =====================================================================
DECOR_BEFORE = r"[#*>\-\s]*"
# A real section header is always followed by a literal colon (optionally
# wrapped in markdown bold asterisks / whitespace), e.g. "Grade Estimate:"
# or "**Grade Estimate:**". Requiring the colon (instead of treating it as
# merely optional) prevents an incidental prose mention of the same words
# -- e.g. "...a conservative mid-grade estimate. The card retains..." --
# from being mistaken for the actual header and truncating that field.
# A real section header is always followed by a literal colon (optionally
# wrapped in markdown bold asterisks / whitespace), e.g. "Grade Estimate:"
# or "**Grade Estimate:**". Requiring the colon (instead of treating it as
# merely optional) prevents an incidental prose mention of the same words
# -- e.g. "...a conservative mid-grade estimate. The card retains..." --
# from being mistaken for the actual header and truncating that field.
# An optional parenthetical aside is also tolerated directly before the
# colon, e.g. "SEO Image titles (must be unique):", since some templates
# add a short instructional note right after the label.
DECOR_AFTER  = r"(?:\s*\([^)]*\))?[*\s]*:[*\s]*"

MARKER_SPECS = [
    # Unified header used by most templates: "SEO Image titles:" followed
    # by both the front and back filename on their own lines. Excludes
    # "Back SEO Image Title" (handled separately below) via a negative
    # lookbehind, since that phrase also contains the literal substring
    # "SEO Image Title" and would otherwise be matched twice per card.
    # The lookbehind only excludes "Back" on the SAME line (space/tab
    # connector, not newline) -- some templates end a variant-descriptor
    # line with the word "Back" (e.g. "...Light Back") immediately
    # followed by a genuine unified "SEO Image titles:" header on the
    # *next* line, and that must still match as "images", not be mistaken
    # for a same-line "Back SEO Image Title:" header.
    ("images",              r"(?<!Back[ \t])SEO\s+Image\s+titles?"),
    # Some templates instead split the images section into two separate
    # one-filename headers: "Front SEO Image Title:" / "Back SEO Image
    # Title:". The "Front" variant is matched by the "images" pattern
    # above (it starts a new card, same as the unified header). This
    # "images_back" marker matches only the same-line "Back" variant
    # (space/tab connector, not newline -- see note above), and is
    # merged into the current card's "images" field in split_into_cards()
    # rather than starting a new card -- mirroring how "condition_report"
    # merges into "product_description".
    ("images_back",         r"Back[ \t]+SEO\s+Image\s+titles?"),
    ("seo_title",           r"SEO\s+Title"),
    ("product_description", r"Product\s+Description"),
    ("condition_report",    r"Condition\s+Report"),
    ("grade_estimate",      r"Grade\s+Estimate"),
    ("price",               r"Price\s+Recommendation"),
    ("keyword",             r"Primary\s+SEO\s+Keyword"),
    ("tags",                r"WooCommerce\s+Tag\s+Bundle"),
]

MARKER_PATTERNS = [
    (key, DECOR_BEFORE + label + DECOR_AFTER)
    for key, label in MARKER_SPECS
]

KNOWN_BRANDS = [
    ("O-Pee-Chee",  r"O-?Pee-?Chee"),
    ("O-Pee-Chee",  r"\bOPC\b"),
    ("Topps",       r"\bTopps\b"),
    ("Parkhurst",   r"\bParkhurst\b"),
    ("Upper Deck",  r"\bUpper\s+Deck\b"),
    ("Bowman",      r"\bBowman\b"),
    ("Fleer",       r"\bFleer\b"),
    ("Score",       r"\bScore\b"),
    ("Pro Set",     r"\bPro\s*Set\b"),
    ("Panini",      r"\bPanini\b"),
]

GRADE_RE = re.compile(
    r"\b("
    r"GEM[\s\-]?MT|GEM|"
    r"NM[\s\-]?MT|"
    r"EX[\s\-]?MT|"
    r"VG[\s\-]?EX|"
    r"NM|MINT|EX|VG|GOOD|FAIR|POOR|PR|FR"
    r")\b\s*(\d+(?:\.\d+)?)?",
    re.IGNORECASE,
)

CONDITION_KEYWORDS_RE = re.compile(
    r"corner|centering|edge|surface|crease|wrinkl|stain|gloss|wear",
    re.IGNORECASE,
)

NOISE_CITATION_RE = re.compile(
    r"(?:[A-Z][A-Za-z\u2019']*(?:\s+[A-Z][A-Za-z\u2019']*){0,5})\s*\+\s*\d+"
)
NOISE_EBAY_RE = re.compile(
    r"\beBay\b(?=(?:Condition Report|Grade Estimate|Product Description|"
    r"Price Recommendation|Primary SEO Keyword|WooCommerce Tag Bundle))"
)

IMAGE_EXT_RE = re.compile(
    r"\.(webp|jpe?g|png|gif|tif?f|bmp)$", re.IGNORECASE
)

# Best-effort repair for a front/back SEO Image title pair that lost its
# line break upstream (e.g. a clipboard-capture step that flattens
# newlines) and arrived as one run-on string like:
#   85-Gary Jarrett-1970-71-O-Pee-Chee-front-EX85-Gary Jarrett-...-back-EX
# Matches "-front" or "-back" plus any letter-only grade suffix (EX,
# VG-EX, EX-MT, ...) immediately followed by the start of a new filename
# (digits, a hyphen, then a capital letter), and inserts a line break
# right there.
JOIN_SPLIT_RE = re.compile(
    r"((?:-front|-back)(?:-[A-Za-z]+)*)(?=\d+-[A-Z])"
)


def split_joined_image_titles(text):
    return JOIN_SPLIT_RE.sub(lambda m: m.group(1) + "\n", text)


def has_image_extension(name):
    return bool(IMAGE_EXT_RE.search(name))


# =====================================================================
#  Category / sub-category tree + detection
# =====================================================================
CATEGORY_CHOICES = [
    ("Non Sports Card", ""),
    ("Sports Card",     "Baseball Card"),
    ("Sports Card",     "Basketball Card"),
    ("Sports Card",     "Football Card"),
    ("Sports Card",     "Hockey Card"),
]

SPORT_KEYWORDS = {
    "Hockey Card": [
        r"\bhockey\b", r"\bnhl\b", r"\bstanley cup\b", r"\bgoalie\b",
        r"\bgoaltender\b", r"\bcenterman\b", r"\bleft wing\b", r"\bright wing\b",
        r"\bdefenseman\b", r"\bmaple leafs\b", r"\bcanadiens\b", r"\bbruins\b",
        r"\bblackhawks\b", r"\bred wings\b", r"\boilers\b", r"\bflames\b",
        r"\bcanucks\b", r"\bsenators\b", r"\bpredators\b", r"\bavalanche\b",
        r"\bsharks\b", r"\bducks\b", r"\bpenguins\b", r"\bflyers\b",
        r"\bcapitals\b", r"\bislanders\b", r"\bdevils\b", r"\bsabres\b",
        r"\blightning\b", r"\bhurricanes\b", r"\bcoyotes\b", r"\bblue jackets\b",
        r"\bnordiques\b", r"\bwhalers\b", r"\bnorth stars\b", r"\bwild\b",
    ],
    "Baseball Card": [
        r"\bbaseball\b", r"\bmlb\b", r"\bpitcher\b", r"\boutfielder\b",
        r"\bshortstop\b", r"\bworld series\b", r"\byankees\b", r"\bred sox\b",
        r"\bdodgers\b", r"\bgiants\b", r"\bcubs\b", r"\bmets\b", r"\bbraves\b",
        r"\bastros\b", r"\bcardinals\b", r"\bphillies\b", r"\btigers\b",
        r"\bguardians\b", r"\bathletics\b", r"\bpirates\b", r"\bbrewers\b",
        r"\bmariners\b", r"\bpadres\b", r"\breds\b", r"\btwins\b", r"\bangels\b",
        r"\bblue jays\b", r"\brockies\b", r"\bmarlins\b", r"\bnationals\b",
        r"\brays\b", r"\bwhite sox\b", r"\broyals\b", r"\borioles\b",
    ],
    "Basketball Card": [
        r"\bbasketball\b", r"\bnba\b", r"\bpoint guard\b", r"\bshooting guard\b",
        r"\bsmall forward\b", r"\bpower forward\b", r"\bdunk\b", r"\brebound\b",
        r"\blakers\b", r"\bceltics\b", r"\bbulls\b", r"\bwarriors\b", r"\bnets\b",
        r"\bknicks\b", r"\bheat\b", r"\bspurs\b", r"\brockets\b",
        r"\bmavericks\b", r"\bsuns\b", r"\bclippers\b", r"\bnuggets\b",
        r"\btrail blazers\b", r"\bjazz\b", r"\bgrizzlies\b", r"\bpelicans\b",
        r"\btimberwolves\b", r"\bthunder\b", r"\bmagic\b", r"\bhawks\b",
        r"\bhornets\b", r"\bpistons\b", r"\bpacers\b", r"\bbucks\b",
        r"\bcavaliers\b", r"\b76ers\b", r"\bsixers\b", r"\braptors\b",
    ],
    "Football Card": [
        r"\bfootball\b", r"\bnfl\b", r"\bcfl\b", r"\bquarterback\b",
        r"\brunning back\b", r"\bwide receiver\b", r"\btouchdown\b",
        r"\btight end\b", r"\blinebacker\b", r"\bcowboys\b", r"\bpatriots\b",
        r"\bpackers\b", r"\bsteelers\b", r"\b49ers\b", r"\bniners\b",
        r"\beagles\b", r"\bbears\b", r"\bbroncos\b", r"\braiders\b",
        r"\bchargers\b", r"\bchiefs\b", r"\bbills\b", r"\bdolphins\b",
        r"\bbengals\b", r"\bbrowns\b", r"\bravens\b", r"\btitans\b",
        r"\bcolts\b", r"\bjaguars\b", r"\btexans\b", r"\bcommanders\b",
        r"\bredskins\b", r"\bvikings\b", r"\blions\b", r"\bfalcons\b",
        r"\bsaints\b", r"\bbuccaneers\b", r"\brams\b", r"\bseahawks\b",
    ],
}

NON_SPORTS_KEYWORDS = [
    r"\bnon-?sports?\b", r"\bstar wars\b", r"\bmarvel\b", r"\bdc comics\b",
    r"\bgarbage pail kids\b", r"\bpok[eé]mon\b", r"\bmagic:? the gathering\b",
    r"\byu-?gi-?oh\b", r"\bdisney\b", r"\btrading card game\b", r"\btcg\b",
    r"\bwacky packages\b", r"\bmars attacks\b", r"\bbatman\b", r"\bsuperman\b",
    r"\bspider-?man\b", r"\bx-?men\b",
]


def detect_sport_category(text):
    lower = text.lower()

    for pattern in NON_SPORTS_KEYWORDS:
        if re.search(pattern, lower, re.IGNORECASE):
            return "Non Sports Card", ""

    scores = {}
    for sub, patterns in SPORT_KEYWORDS.items():
        count = sum(1 for p in patterns if re.search(p, lower, re.IGNORECASE))
        if count:
            scores[sub] = count

    if not scores:
        return "Sports Card", "Hockey Card"

    best_sub = max(scores, key=scores.get)
    return "Sports Card", best_sub


def category_label(category, subcategory):
    return category if not subcategory else f"{category} > {subcategory}"


def print_category_menu():
    print("\n  Available categories:")
    for i, (top, sub) in enumerate(CATEGORY_CHOICES, start=1):
        print(f"    {i}. {category_label(top, sub)}")


def print_category_plan(parsed):
    """Keep one compact row per card so a nine-card plan fits the console."""
    print("\n== Detected categories (one row per card) ==\n")
    for i, c in enumerate(parsed, start=1):
        title = c["seo_title"] or f"(card {i})"
        if len(title) > 58:
            title = title[:55] + "..."
        category = category_label(c["category"], c["subcategory"])
        print(f"  {i:>2}. {title}  ->  {category}")


def prompt_one_category(parsed, idx):
    c = parsed[idx]
    title = c["seo_title"] or f"card {idx + 1}"
    print(f"\n  Card {idx + 1}: {title}  "
          f"(currently: {category_label(c['category'], c['subcategory'])})")
    print_category_menu()
    while True:
        try:
            choice = input(
                f"  Pick 1-{len(CATEGORY_CHOICES)} (blank to keep current): "
            ).strip()
        except EOFError:
            choice = ""
        if choice == "":
            return
        if choice.isdigit() and 1 <= int(choice) <= len(CATEGORY_CHOICES):
            top, sub = CATEGORY_CHOICES[int(choice) - 1]
            c["category"], c["subcategory"] = top, sub
            return
        print(f"  Please enter a number 1-{len(CATEGORY_CHOICES)}.")


def confirm_categories(parsed, auto_yes=False):
    print_category_plan(parsed)
    if auto_yes:
        print("\n(-y set: accepting detected categories without prompting.)")
        return
    while True:
        try:
            answer = input(
                "\nAre these categories correct? "
                "[Y/n, or a card number to fix one] "
            ).strip().lower()
        except EOFError:
            answer = "y"
        if answer in ("", "y", "yes"):
            return
        if answer in ("n", "no"):
            for i in range(len(parsed)):
                prompt_one_category(parsed, i)
            print_category_plan(parsed)
            continue
        if answer.isdigit() and 1 <= int(answer) <= len(parsed):
            prompt_one_category(parsed, int(answer) - 1)
            print_category_plan(parsed)
            continue
        print("  Please answer y, n, or a card number.")


# =====================================================================
#  Quantity confirmation
# =====================================================================
def print_quantity_plan(parsed):
    print("\n== Stock quantities ==\n")
    for i, c in enumerate(parsed, start=1):
        title = c["seo_title"] or f"(card {i})"
        print(f"  {i}. {title}\n"
              f"     -> Qty: {c['quantity']}")


def prompt_one_quantity(parsed, idx):
    c = parsed[idx]
    title = c["seo_title"] or f"card {idx + 1}"
    while True:
        try:
            choice = input(
                f"\n  Card {idx + 1}: {title}  "
                f"(currently: {c['quantity']})\n"
                f"  New quantity (blank to keep current): "
            ).strip()
        except EOFError:
            choice = ""
        if choice == "":
            return
        if choice.isdigit() and int(choice) >= 0:
            c["quantity"] = int(choice)
            return
        print("  Please enter a whole number 0 or greater.")


def confirm_quantities(parsed, auto_yes=False):
    print_quantity_plan(parsed)
    if auto_yes:
        print("\n(-y set: accepting default quantities without prompting.)")
        return
    while True:
        try:
            answer = input(
                "\nAre these quantities correct? "
                "[Y/n, or a card number to edit one] "
            ).strip().lower()
        except EOFError:
            answer = "y"
        if answer in ("", "y", "yes"):
            return
        if answer in ("n", "no"):
            for i in range(len(parsed)):
                prompt_one_quantity(parsed, i)
            print_quantity_plan(parsed)
            continue
        if answer.isdigit() and 1 <= int(answer) <= len(parsed):
            prompt_one_quantity(parsed, int(answer) - 1)
            print_quantity_plan(parsed)
            continue
        print("  Please answer y, n, or a card number.")


# =====================================================================
#  Text parsing helpers
# =====================================================================
def find_all_markers(text):
    matches = []
    for key, pattern in MARKER_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            matches.append((m.start(), m.end(), key))
    matches.sort(key=lambda t: t[0])

    deduped = []
    last_end = -1
    for start, end, key in matches:
        if start < last_end:
            continue
        deduped.append((start, end, key))
        last_end = end
    return deduped


def split_into_cards(raw_text):
    markers = find_all_markers(raw_text)
    if not any(key == "images" for _, _, key in markers):
        raise ValueError(
            "Couldn't find any 'SEO Image titles' sections in the input text. "
            "Make sure each card block includes that header."
        )

    cards = []
    current = None

    for i, (start, end, key) in enumerate(markers):
        next_start = markers[i + 1][0] if i + 1 < len(markers) else len(raw_text)
        content = raw_text[end:next_start].strip()

        if key == "images":
            if current is not None:
                cards.append(current)
            current = {"images": content}
            continue

        if current is None:
            continue

        if key == "images_back":
            existing = current.get("images", "")
            current["images"] = (existing + "\n" + content).strip()
        elif key == "condition_report":
            existing = current.get("product_description", "")
            current["product_description"] = (existing + "\n\n" + content).strip()
        else:
            current[key] = content

    if current is not None:
        cards.append(current)

    return cards


def strip_noise(text):
    text = NOISE_CITATION_RE.sub("", text)
    text = NOISE_EBAY_RE.sub("", text)
    return text


def strip_markdown(text):
    text = text.replace("**", "").replace("__", "")
    text = text.replace("`", "")
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "", text)
    text = re.sub(r"(?<!\*)\*(?!\*)", "", text)
    return text


def add_missing_sentence_spaces(text):
    return re.sub(r"(?<=[.!?])(?=[A-Z])", " ", text)


def clean_description_text(raw):
    text = strip_noise(raw)
    text = strip_markdown(text)
    text = add_missing_sentence_spaces(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def first_line(text):
    if not text:
        return ""
    for line in text.splitlines():
        line = strip_markdown(line).strip()
        if line:
            return line
    return ""


# Windows forbids these characters in filenames: \ / : * ? " < > |
# Also strip trailing dots/spaces (Windows disallows them at the end of a name)
_WIN_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|]')


def sanitize_filename_component(text):
    """Strip characters that are illegal in Windows filenames (e.g. the
    '?' in a title like 'Baseball or Music?'), so downstream renames
    never hit WinError 123."""
    if not text:
        return ""
    text = _WIN_ILLEGAL_RE.sub("", text)
    text = text.rstrip(" .")
    return text


def grade_slug(grade):
    """Convert a cleaned grade string (e.g. 'EX 5' or 'VG-EX') into a
    filename-safe suffix (e.g. 'EX-5' or 'VG-EX'). Returns '' when no
    grade is available."""
    if not grade:
        return ""
    grade = sanitize_filename_component(grade.strip())
    return re.sub(r"\s+", "-", grade)


def parse_images(images_text, default_ext="webp"):
    """
    Read the front and back filenames straight out of the supplied
    'SEO Image titles' section. These are the exact filenames used for
    renaming and for the CSV's Images column -- only the configured
    image extension is appended if the supplied title didn't include one.

    Expected examples:
        1-Eddie-Shack-1969-70-O-Pee-Chee-front-VG-EX-4
        1-Eddie-Shack-1969-70-O-Pee-Chee-back-VG-EX-4
        10-Wayne-Gretzky-1980-81-O-Pee-Chee-front
        10-Wayne-Gretzky-1980-81-O-Pee-Chee-back
    """
    front = ""
    back = ""
    default_ext = default_ext.lstrip(".")

    text = strip_markdown(images_text)

    # Repair front/back titles that lost their line break upstream (e.g. a
    # clipboard-capture step that flattens newlines) before splitting.
    text = split_joined_image_titles(text)

    # Keep one supplied image title per line. Also permit commas or pipes
    # as separators, but do NOT split on hyphens because grade suffixes use
    # hyphens (for example: VG-EX-4).
    lines = re.split(r"[\r\n,|]+", text)

    for line in lines:
        filename = line.strip()

        # Remove optional Markdown/list wrappers only.
        filename = filename.strip("[](){} \t")
        filename = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", filename)
        filename = filename.strip()

        if not filename:
            continue

        # A valid SEO image title must contain exactly one image side.
        # NOTE: this match is intentionally case-SENSITIVE. Variant
        # descriptors like "Dark Back" / "Light Back" are Title Case in
        # supplied filenames, while the actual side marker is always
        # lowercase "-front"/"-back". Matching case-insensitively would
        # make a filename like "...-Dark-Back-front" match BOTH is_front
        # (from "-front") and is_back (from "-Back-"), causing a false
        # "joined together" detection and dropping the title entirely.
        is_front = bool(
            re.search(r"-front(?:-|\.|$)", filename)
        )
        is_back = bool(
            re.search(r"-back(?:-|\.|$)", filename)
        )

        # Ignore lines that are not image-title filenames.
        if not is_front and not is_back:
            continue

        # A filename cannot be both a front and a back. If it is, that means
        # two titles were accidentally joined together; do not use it.
        if is_front and is_back:
            print(
                "WARNING: A front and back image title were joined together "
                f"and will be ignored:\n  {filename}",
                file=sys.stderr,
            )
            continue

        # Add only the extension when no extension was supplied.
        # Do not add, remove, or modify the grade portion.
        if not has_image_extension(filename):
            filename += "." + default_ext

        if is_front:
            front = filename
        else:
            back = filename

    return front, back


def extract_card_number(seo_title):
    m = re.search(r"#(\w+)", seo_title)
    return m.group(1) if m else ""


def extract_year(seo_title):
    m = re.search(r"(\d{4}-\d{2}|\d{4})", seo_title)
    return m.group(1) if m else ""


def extract_brand(seo_title, default_brand):
    for canonical, pattern in KNOWN_BRANDS:
        if re.search(pattern, seo_title, re.IGNORECASE):
            return canonical
    return default_brand


def extract_player_name(seo_title, brand):
    m = re.match(r"^\s*(?:\d{4}-\d{2}|\d{4})\s+(.+?)#", seo_title.strip())
    if not m:
        return ""
    middle = m.group(1).strip()
    for _, pattern in KNOWN_BRANDS:
        stripped = re.sub(
            r"^\s*" + pattern + r"\s*", "", middle, flags=re.IGNORECASE
        )
        if stripped != middle:
            middle = stripped.strip()
            break
    if brand:
        middle = re.sub(
            r"^\s*" + re.escape(brand) + r"\s*", "", middle,
            flags=re.IGNORECASE
        ).strip()
    return middle


def brand_code(brand):
    parts = re.split(r"[\s\-]+", brand.strip())
    parts = [p for p in parts if p]
    if len(parts) == 1:
        return parts[0].upper()
    letters = "".join(p[0].upper() for p in parts)
    return letters or brand.upper()


def extract_price(price_text):
    m = re.search(r"([\d]+(?:\.\d+)?)", price_text)
    return float(m.group(1)) if m else 0.0


def clean_grade(grade_text):
    if not grade_text:
        return ""
    m = GRADE_RE.search(grade_text)
    if not m:
        return first_line(grade_text)
    label = re.sub(r"\s+", "-", m.group(1).strip().upper()).replace("--", "-")
    number = m.group(2)
    return f"{label} {number}".strip() if number else label


def build_short_description(description_text, grade):
    sentences = re.split(r"(?<=[.!?])\s+", description_text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    intro = sentences[0] if sentences else ""
    condition_sentence = ""
    for s in sentences[1:]:
        if CONDITION_KEYWORDS_RE.search(s):
            condition_sentence = s
            break
    parts = [p for p in (intro, condition_sentence) if p]
    if grade:
        parts.append(f"Raw Grade Estimate: {grade}.")
    return " ".join(parts)


def parse_card(card_dict, default_brand, image_ext="webp"):
    seo_title = first_line(card_dict.get("seo_title", ""))
    grade = clean_grade(card_dict.get("grade_estimate", ""))
    keyword = first_line(card_dict.get("keyword", ""))
    price = extract_price(card_dict.get("price", ""))

    tags_raw = first_line(card_dict.get("tags", ""))
    tags = ", ".join(t.strip() for t in tags_raw.split(",") if t.strip())

    front_img, back_img = parse_images(
        card_dict.get("images", ""), default_ext=image_ext
    )

    description_text = clean_description_text(
        card_dict.get("product_description", "")
    )
    short_desc = build_short_description(description_text, grade)

    full_description = seo_title + "\n\n" + description_text
    if grade:
        full_description += f"\n\nGrade Estimate: {grade}"

    brand = extract_brand(seo_title, default_brand)
    card_num = extract_card_number(seo_title)
    year = extract_year(seo_title)
    player_name = extract_player_name(seo_title, brand)
    last = player_name.split()[-1] if player_name else ""

    category, subcategory = detect_sport_category(
        " ".join([seo_title, description_text, tags, keyword])
    )

    return {
        "player": player_name, "card_num": card_num, "year": year, "last": last,
        "brand": brand, "seo_title": seo_title, "grade": grade, "keyword": keyword,
        "price": price, "tags": tags, "front_img": front_img, "back_img": back_img,
        "short_desc": short_desc, "full_description": full_description,
        "category": category, "subcategory": subcategory,
    }


# =====================================================================
#  CSV GENERATION
# =====================================================================
FIELDNAMES = [
    "SKU", "Name", "Published", "Is featured?", "Visibility in catalog",
    "Short description", "Description", "In stock?", "Stock", "Regular price",
    "Categories", "Tags", "Images", "Attribute 1 name", "Attribute 1 value(s)",
    "Attribute 1 visible", "Attribute 1 global", "rank_math_title",
    "rank_math_description", "rank_math_focus_keyword",
]


def build_rows(cards_parsed, default_quantity=1):
    rows = []
    for c in cards_parsed:
        code = brand_code(c["brand"])
        grade_component = grade_slug(c["grade"])  # e.g. "EX-5", "VG-3"
        sku_bits = [code + c["year"], c["card_num"], c["last"], grade_component]
        sku = "-".join(b for b in sku_bits if b)

        price = math.ceil(c["price"]) if c["price"] else ""
        images = ", ".join(x for x in (c["front_img"], c["back_img"]) if x)
        quantity = c.get("quantity", default_quantity)

        rows.append({
            "SKU": sku,
            "Name": c["seo_title"],
            "Published": 1,
            "Is featured?": 0,
            "Visibility in catalog": "visible",
            "Short description": c["short_desc"],
            "Description": c["full_description"],
            "In stock?": 1,
            "Stock": quantity,
            "Regular price": price,
            "Categories": category_label(c["category"], c["subcategory"]),
            "Tags": c["tags"],
            "Images": images,
            "Attribute 1 name": "Brand",
            "Attribute 1 value(s)": c["brand"],
            "Attribute 1 visible": 1,
            "Attribute 1 global": 1,
            "rank_math_title": c["seo_title"],
            "rank_math_description": c["short_desc"],
            "rank_math_focus_keyword": c["keyword"],
        })
    return rows


def write_csv(rows, out_path):
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# =====================================================================
#  IMAGE RENAMING
#
#  Destination filenames are the exact "SEO Image titles" you supplied
#  in the input text (as parsed by parse_images() and carried through
#  the CSV's Images column) -- nothing is auto-generated from the card's
#  parsed fields. Backs remain mirrored to match the physical sleeve
#  layout.
# =====================================================================
def mirror_pos(n):
    """Return the card position for a horizontally mirrored 3x3 back scan.

    Sleeve layout:
        Front positions:       Back scan positions:
            1 2 3                  3 2 1
            4 5 6                  6 5 4
            7 8 9                  9 8 7

    Therefore, a back image scanned at position 1 belongs to card 3,
    position 4 belongs to card 6, and so on.
    """
    i = n - 1
    row, col = divmod(i, 3)
    return row * 3 + (2 - col) + 1


def targets_from_rows(rows):
    """
    Build destination filename maps from the WooCommerce CSV rows.

    The Images column was populated using parse_images(), so these names
    are the exact SEO Image titles supplied in the input text, with only
    the configured image extension added if the title did not include one.

    Returns:
        fronts: {card_position: front_destination_filename}
        backs:  {card_position: back_destination_filename}
    """
    fronts = {}
    backs = {}

    for position, row in enumerate(rows, start=1):
        image_names = [
            name.strip()
            for name in row.get("Images", "").split(",")
            if name.strip()
        ]

        # Case-sensitive for the same reason as in parse_images(): variant
        # words like "Dark Back" are Title Case, while the real side
        # marker is always lowercase "-front"/"-back".
        front = next(
            (
                name for name in image_names
                if re.search(r"-front(?:-|\.|$)", name)
            ),
            "",
        )
        back = next(
            (
                name for name in image_names
                if re.search(r"-back(?:-|\.|$)", name)
            ),
            "",
        )

        if front:
            fronts[position] = front
        if back:
            backs[position] = back

    return fronts, backs


def prefix_timestamp(prefix):
    """Convert timestamp-like digits in a scan prefix to an integer."""
    digits = re.sub(r"\D", "", prefix)
    return int(digits) if digits else None


def autodetect_prefixes(directory, ext):
    """
    Detect the two split scan sets.

    The older timestamp is treated as the front scan; the newer timestamp
    is treated as the back scan.
    """
    ext = ext.lstrip(".")
    if not os.path.isdir(directory):
        raise ValueError(f"Image directory not found: {directory}")

    pattern = re.compile(
        rf"^(.*)_(\d+)\.{re.escape(ext)}$",
        re.IGNORECASE,
    )

    groups = {}
    for name in sorted(os.listdir(directory)):
        match = pattern.match(name)
        if not match:
            continue
        prefix = match.group(1)
        position = int(match.group(2))
        groups.setdefault(prefix, set()).add(position)

    timestamped = [
        (prefix, prefix_timestamp(prefix), sorted(positions))
        for prefix, positions in groups.items()
        if prefix_timestamp(prefix) is not None
    ]

    if len(timestamped) < 2:
        raise ValueError(
            f"Could not auto-detect two timestamped scan sets in '{directory}'. "
            f"Found: {[prefix for prefix, *_ in timestamped] or 'none'}. "
            "Provide --front-prefix and --back-prefix manually."
        )

    if len(timestamped) > 2:
        raise ValueError(
            f"Found more than two scan sets in '{directory}': "
            f"{[prefix for prefix, *_ in timestamped]}. Clear out old scans, "
            "or pass --front-prefix and --back-prefix to choose explicitly."
        )

    timestamped.sort(key=lambda item: item[1])
    (front_prefix, _, front_positions), (
        back_prefix,
        _,
        back_positions,
    ) = timestamped

    return front_prefix, back_prefix, {
        front_prefix: front_positions,
        back_prefix: back_positions,
    }


def find_source(directory, prefix, pos, ext):
    """Find a split source image by scan prefix and sleeve position."""
    ext = ext.lstrip(".")
    candidate = os.path.join(directory, f"{prefix}_{pos}.{ext}")
    if os.path.exists(candidate):
        return candidate

    # Fall back to any extension if necessary.
    pattern = re.compile(
        rf"^{re.escape(prefix)}_{pos}\.\w+$",
        re.IGNORECASE,
    )
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory)):
            if pattern.match(name):
                return os.path.join(directory, name)
    return None


def plan_renames(directory, fronts, backs, front_prefix, back_prefix, ext):
    """
    Create the rename operations.

    Fronts map directly by sleeve position.
    Backs map through mirror_pos() because the back sleeve scan is
    horizontally reversed relative to the front sleeve scan.
    """
    ops = []
    missing = []

    # Front scan: source position N belongs to card N.
    for pos in range(1, TOTAL_CARDS + 1):
        target = fronts.get(pos)
        if not target:
            continue
        src = find_source(directory, front_prefix, pos, ext)
        if src is None:
            missing.append(
                f"FRONT position {pos} "
                f"({front_prefix}_{pos}.{ext.lstrip('.')})"
            )
            continue
        ops.append((
            src,
            os.path.join(directory, target),
            f"front_{pos}",
        ))

    # Back scan: source position is mirrored to the matching front card.
    for pos in range(1, TOTAL_CARDS + 1):
        card_pos = mirror_pos(pos)
        target = backs.get(card_pos)
        if not target:
            continue
        src = find_source(directory, back_prefix, pos, ext)
        if src is None:
            missing.append(
                f"BACK position {pos} "
                f"({back_prefix}_{pos}.{ext.lstrip('.')})"
            )
            continue
        ops.append((
            src,
            os.path.join(directory, target),
            f"back_{pos}->card#{card_pos}",
        ))

    return ops, missing


def print_plan(ops, missing, verb):
    """Print the proposed copy/move plan before making changes."""
    print(f"\n== Proposed image renames ({verb}) ==\n")
    for src, dst, label in ops:
        print(
            f"  [{label:16}] "
            f"{os.path.basename(src):32} -> {os.path.basename(dst)}"
        )
    if missing:
        print("\n  !! Missing source files (will be skipped):")
        for item in missing:
            print(f"     - {item}")


def apply_renames(ops, copy=False):
    """
    Apply rename operations safely in two stages.

    The temporary stage prevents filename conflicts while multiple files
    are being moved or copied.
    """
    staged = []
    for src, dst, _ in ops:
        tmp = dst + ".tmp_rename"
        if copy:
            shutil.copy2(src, tmp)
        else:
            shutil.move(src, tmp)
        staged.append((tmp, dst))

    for tmp, dst in staged:
        os.replace(tmp, dst)


# =====================================================================
#  FACEBOOK FEED
# =====================================================================
FEED_REFRESH_URL, FEED_URL = feed_urls(USER_SETTINGS)
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def http_get(url, timeout=60, cookie=None, nbytes=None):
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;"
                  "q=0.9,*/*;q=0.8",
        "Accept-Language": "en-CA,en;q=0.9",
    }
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read() if nbytes is None else resp.read(nbytes)
        return resp.status, body


def feed_is_live(feed_url, timeout=60, cookie=None):
    try:
        status, first = http_get(
            feed_url, timeout=timeout, cookie=cookie, nbytes=256
        )
        return b"<" in first
    except Exception:
        return False


def choose_browser_cli():
    """Ask once in an interactive terminal when no browser is saved."""
    choices = available_browsers()
    if not sys.stdin or not sys.stdin.isatty():
        return "system"
    print("\nChoose the browser Alex Collect should use for web pages:")
    for index, (_key, label) in enumerate(choices, 1):
        print("  %d. %s" % (index, label))
    try:
        answer = input("Browser number [1]: ").strip()
    except (EOFError, OSError):
        answer = ""
    if not answer:
        selected = choices[0]
    else:
        try:
            selected = choices[int(answer) - 1]
        except (ValueError, IndexError):
            selected = choices[0]
    USER_SETTINGS["browser_name"] = selected[0]
    save_user_settings(USER_SETTINGS, APP_DIR / "gui-settings.json")
    return selected[0]


def open_in_browser(url, browser=None):
    """Open a URL in the saved/selected browser, prompting only on first use."""
    browser = (browser or USER_SETTINGS.get("browser_name", "") or "").strip()
    if not browser:
        browser = choose_browser_cli()
    return launch_urls([url], browser or "system") or None


def open_path(path):
    """Open a local file or folder with the operating system's default app."""
    path = Path(path)
    if not path.exists():
        return False
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606 - user's chosen local file
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except Exception as exc:
        print("Could not open %s: %s" % (path, exc), file=sys.stderr)
        return False


def open_folder(path):
    """Open an existing folder in the operating system's file manager."""
    path = Path(path)
    return open_path(path) if path.is_dir() else False


def refresh_facebook_feed(refresh_url, feed_url, timeout=60, wait=5,
                          cookie=None, allow_browser=True, browser=None):
    print(f"\nRefreshing Facebook feed: {refresh_url}")

    triggered = False
    try:
        status, body = http_get(refresh_url, timeout=timeout, cookie=cookie)
        print(f"  Feed rebuild triggered headlessly (HTTP {status}).")
        triggered = True
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print(f"  Headless request was blocked (HTTP {e.code}) — "
                  "this endpoint needs your logged-in session.")
        else:
            print(f"  !! Headless request failed: HTTP {e.code}.",
                  file=sys.stderr)
    except Exception as e:
        print(f"  !! Headless request failed: {e}", file=sys.stderr)

    if not triggered and allow_browser:
        used = open_in_browser(refresh_url, browser=browser)
        if used:
            print(f"\n  Opening the refresh URL in {used} instead...")
        else:
            print("\n  !! Couldn't launch a browser automatically.",
                  file=sys.stderr)
            print(f"  Please open this URL manually:\n    {refresh_url}")

        while True:
            try:
                ans = input(
                    "  Did the feed refresh load OK in the browser? [y/N] "
                ).strip().lower()
            except EOFError:
                ans = ""
            if ans in ("y", "yes"):
                triggered = True
                break
            if ans in ("n", "no", ""):
                print("  Feed refresh not confirmed.", file=sys.stderr)
                return False

    if not triggered:
        return False

    if wait:
        print(f"  Waiting {wait}s for the feed to regenerate...")
        time.sleep(wait)

    if feed_is_live(feed_url, timeout=timeout, cookie=cookie):
        print(f"  Feed is live and returning XML: {feed_url}")
        return True

    print(f"  !! Feed URL didn't return XML yet: {feed_url}",
          file=sys.stderr)
    return False


def console_python_executable(executable=None):
    """Use a console-enabled interpreter for nested tools on Windows.

    The GUI launches card_pipeline.py with pythonw.exe. Reusing sys.executable
    for a nested script can leave its stdout/stderr detached, hiding the real
    error and sometimes making print() fail. Prefer the sibling python.exe.
    """
    executable = str(executable or sys.executable)
    path = Path(executable)
    if path.name.lower() == "pythonw.exe":
        console = path.with_name("python.exe")
        if console.is_file():
            return str(console)
    return executable


def run_facebook_feed_script():
    """Run the standalone facebook_feed.py from facebook_merchant_products/."""
    fb_script = SCRIPT_DIR / "facebook_merchant_products" / "facebook_feed.py"
    if not fb_script.exists():
        print(f"  !! {fb_script} not found — skipping Facebook feed export.",
              file=sys.stderr)
        return False

    print(f"\nRunning Facebook feed export: {fb_script}")
    try:
        result = subprocess.run(
            [console_python_executable(), str(fb_script)],
            cwd=str(fb_script.parent),
        )
    except Exception as e:
        print(f"  !! Failed to launch Facebook feed script: {e}",
              file=sys.stderr)
        return False

    if result.returncode == 0:
        print("  Facebook feed history updated.")
        return True

    print(f"  !! Facebook feed script exited with code {result.returncode}.",
          file=sys.stderr)
    return False


def run_facebook_export_script():
    """Run facebook_marketplace_export.py if it exists."""
    fb_export = (SCRIPT_DIR / "facebook_merchant_products"
                 / "facebook_marketplace_export.py")
    if not fb_export.exists():
        return True

    print(f"\nRunning Marketplace xlsx export: {fb_export.name}")
    try:
        result = subprocess.run(
            [console_python_executable(), str(fb_export)],
            cwd=str(fb_export.parent),
        )
    except Exception as e:
        print(f"  !! Failed to launch export: {e}", file=sys.stderr)
        return False

    if result.returncode == 0:
        print("  Facebook Marketplace xlsx export completed.")
        return True

    print(f"  !! Export exited with code {result.returncode}.",
          file=sys.stderr)
    return False


def open_facebook_delivery():
    """Open the newly generated Facebook workbook, its folder, and review page."""
    export_dir = SCRIPT_DIR / "facebook_merchant_products"
    candidates = []
    for pattern in ("facebook_delta_*.xlsx", "facebook_batch_*.xlsx"):
        candidates.extend(export_dir.glob(pattern))
    latest = max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
    if latest:
        if open_path(latest):
            print("Opened the Facebook export workbook: %s" % latest)
        else:
            print("Could not open the Facebook workbook automatically: %s" % latest)
    if open_folder(export_dir):
        print("Opened the Facebook export folder: %s" % export_dir)
    page_url = str(USER_SETTINGS.get("facebook_selling_url", "") or "").strip()
    if page_url:
        try:
            browser_used = open_in_browser(page_url)
            print("Opened the configured Facebook review/listing page in %s: %s" %
                  (browser_used or "your browser", page_url))
        except Exception as exc:
            print("Could not open the Facebook page: %s" % exc)
    else:
        print("Set a Facebook listing/review page URL in User Settings to open it.")
    try:
        input("Review the Facebook workbook/page, then press Enter to continue to the next stage...")
    except EOFError:
        pass


def maybe_run_facebook(args):
    """Prompt for WooCommerce upload, then refresh feed and run exports."""
    if not getattr(args, "facebook", False):
        return

    print("\n" + "=" * 58)
    print("  FACEBOOK MARKETPLACE EXPORT")
    print("=" * 58)
    print("\nBefore the feed can be refreshed, finish the WooCommerce upload:")
    print("  1. Import the CSV with your WooCommerce importer (this creates products).")
    print("  2. Upload the renamed media files from the output folder.")
    print("  3. Confirm the products are published/live on your store.")
    print("\nThe Facebook feed only includes products already published.")
    media_url = site_admin_url("wp-admin/media-new.php", USER_SETTINGS)
    if not media_url:
        print("Set your WooCommerce site URL in User settings to open its media page.")
    # The renamed images live in OUTPUT_DIR and have to be uploaded whatever
    # the media page is, so opening the folder must not depend on media_url
    # being configured. --no-browser still suppresses both.
    if not getattr(args, "no_browser", False):
        if media_url:
            try:
                browser_used = open_in_browser(media_url)
                print("Opened the WordPress media upload page in %s: %s" %
                      (browser_used or "your browser", media_url))
            except Exception as exc:
                print("Could not open the media upload page: %s" % exc)
        if open_folder(OUTPUT_DIR):
            print("Opened the image output folder: %s" % OUTPUT_DIR)

    while True:
        try:
            answer = input(
                "\nHave you finished the WP All Import, uploaded the media, and created/published the products? "
                "Type 'y' to refresh the feed, or 'n' to stop: "
            ).strip().lower()
        except EOFError:
            answer = ""
        if answer in ("y", "yes"):
            break
        if answer in ("n", "no", ""):
            print("Stopped before the Facebook step. Your CSV and renamed "
                  "images are ready; re-run with --facebook when done.")
            return

    if not FEED_URL or not FEED_REFRESH_URL:
        print("Set your WooCommerce site/feed URLs in User settings before "
              "running the Facebook feed step.", file=sys.stderr)
        return

    ok = refresh_facebook_feed(
        FEED_REFRESH_URL, FEED_URL,
        wait=getattr(args, "feed_wait", 5),
        cookie=getattr(args, "feed_cookie", None),
        allow_browser=not getattr(args, "no_browser", False),
        browser=getattr(args, "browser", "edge"),
    )

    if not ok:
        print("  Skipping exports because the feed could not be confirmed.",
              file=sys.stderr)
        print("  (Your CSV and renamed images are unaffected.)")
        return

    print("\n-- Running Facebook feed history tracker... --")
    if not run_facebook_feed_script():
        print("  Facebook workbook handoff skipped because feed export failed.",
              file=sys.stderr)
        return

    print("\n-- Running Marketplace xlsx export... --")
    if not run_facebook_export_script():
        print("  Facebook workbook handoff skipped because the export failed.",
              file=sys.stderr)
        return

    print("\n-- Facebook export steps complete. --")
    open_facebook_delivery()


# =====================================================================
#  CANADIANSHOPPER UPLOAD
# =====================================================================
CANADIANSHOPPER_FIELDNAMES = [
    "title", "price_cad", "category", "description", "image_url",
    "inventory", "is_made_to_order", "ship_from_province",
    "shipping_flat_cad", "free_shipping", "handling_days", "transit_days",
    "sizes", "colors",
]

CANADIANSHOPPER_CATEGORY = str(USER_SETTINGS.get(
    "canadianshopper_category", "Antiques & Collectibles"))
CANADIANSHOPPER_PROVINCE = str(USER_SETTINGS.get(
    "canadianshopper_ship_from_province", "ON"))
CANADIANSHOPPER_FLAT_SHIPPING = str(USER_SETTINGS.get(
    "canadianshopper_shipping_flat", "4.00"))
CANADIANSHOPPER_FREE_SHIPPING = (
    "true" if USER_SETTINGS.get("canadianshopper_free_shipping", False)
    else "false")
CANADIANSHOPPER_HANDLING_DAYS = str(USER_SETTINGS.get(
    "canadianshopper_handling_days", 2))
CANADIANSHOPPER_TRANSIT_DAYS = str(USER_SETTINGS.get(
    "canadianshopper_transit_days", 5))
CANADIANSHOPPER_BATCH_SIZE = 500


def default_canadianshopper_image_base_url():
    """Assume renamed images are uploaded to the configured WP uploads month."""
    if not SITE_URL:
        return ""
    return f"{SITE_URL}/wp-content/uploads/{datetime.now():%Y/%m}"


def get_canadianshopper_image_base_url(args):
    """Get the public folder URL used to build CanadianShopper image links."""
    base_url = getattr(args, "canadianshopper_image_base_url", None)
    default_url = default_canadianshopper_image_base_url()

    if not base_url:
        print("\nCanadianShopper image URLs need the public WordPress uploads folder.")
        print(
            "The default assumes WordPress stores this month's uploads at:\n"
            f"  {default_url}"
        )
        if getattr(args, "yes", False):
            base_url = default_url
            print("(-y set: using the default image folder.)")
        else:
            try:
                answer = input(
                    "Image folder URL [Enter to use the default]: "
                ).strip()
            except EOFError:
                answer = ""
            base_url = answer or default_url

    base_url = base_url.strip().rstrip("/")
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        print(
            "  !! Invalid image base URL. Use a full http:// or https:// URL. "
            "CanadianShopper CSV was not written.",
            file=sys.stderr,
        )
        return None
    return base_url


def canadianshopper_image_url(image_name, image_base_url):
    """Make a public URL for the front image (or back if there is no front)."""
    if not image_name:
        return ""
    image_name = str(image_name)
    if image_name.lower().startswith(("http://", "https://")):
        return image_name

    filename = image_name.replace("\\", "/").rsplit("/", 1)[-1]
    return f"{image_base_url}/{quote(filename, safe='-._~')}"


def build_canadianshopper_rows(cards_parsed, image_base_url):
    """Convert parsed cards to the CanadianShopper import-template columns."""
    rows = []
    for i, card in enumerate(cards_parsed, start=1):
        image_name = card.get("front_img") or card.get("back_img")
        image_url = canadianshopper_image_url(image_name, image_base_url)
        if not image_url:
            print(
                f"  !! Card {i} has no front/back image title; image_url is blank.",
                file=sys.stderr,
            )

        # Match the whole-dollar, round-up price used in the WooCommerce CSV.
        price = math.ceil(card["price"]) if card.get("price") else ""
        price_cad = f"{price:.2f}" if price != "" else ""
        description = re.sub(
            r"\s+", " ", str(card.get("full_description", ""))
        ).strip()

        rows.append({
            "title": card.get("seo_title", ""),
            "price_cad": price_cad,
            "category": CANADIANSHOPPER_CATEGORY,
            "description": description,
            "image_url": image_url,
            "inventory": str(int(card.get("quantity", 1))),
            "is_made_to_order": "false",
            "ship_from_province": CANADIANSHOPPER_PROVINCE,
            "shipping_flat_cad": CANADIANSHOPPER_FLAT_SHIPPING,
            "free_shipping": CANADIANSHOPPER_FREE_SHIPPING,
            "handling_days": CANADIANSHOPPER_HANDLING_DAYS,
            "transit_days": CANADIANSHOPPER_TRANSIT_DAYS,
            "sizes": "",
            "colors": "",
        })
    return rows


def write_canadianshopper_csvs(rows):
    """Write timestamped CSVs, each containing no more than 500 products."""
    if not rows:
        return []

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_count = math.ceil(len(rows) / CANADIANSHOPPER_BATCH_SIZE)
    output_paths = []
    CANADIANSHOPPER_DIR.mkdir(parents=True, exist_ok=True)

    for batch_index in range(batch_count):
        start = batch_index * CANADIANSHOPPER_BATCH_SIZE
        batch = rows[start:start + CANADIANSHOPPER_BATCH_SIZE]
        out_path = CANADIANSHOPPER_DIR / (
            f"canadianshopper_import_{timestamp}_"
            f"{batch_index + 1:02d}_of_{batch_count:02d}.csv"
        )
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=CANADIANSHOPPER_FIELDNAMES,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(batch)
        output_paths.append(out_path)

    _roll_csv_history(
        CANADIANSHOPPER_DIR, "canadianshopper_import_*.csv",
        "canadianshopper_history.csv", exclude_paths=output_paths,
        key_fields=("title",))
    return output_paths


def _find_cs_stage_hook():
    """Find a compatible enabled plugin's pipeline-stage action.

    New plugins live in the per-user data directory. Older v2.20 CS installs
    copied the hook beside the app and remain supported as a migration path.
    """
    app_dir = SCRIPT_DIR.parent
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    try:
        from plugin_manager import PluginError, PluginManager
        manager = PluginManager(core_version=None)
        managed = [p for p in manager.list_plugins()
                   if p.get("compatible") and
                   "batch.pipeline_stage" in p.get("actions", {})]
        try:
            return manager.resolve_action("batch.pipeline_stage")
        except PluginError:
            if managed:
                # A registered but disabled/ambiguous provider must not
                # silently reactivate through a legacy copied tool.
                return None
    except Exception:
        pass
    legacy = []
    if (SCRIPT_DIR.parent / "addon-canadianshopper.txt").is_file():
        legacy.append(SCRIPT_DIR.parent / "cs_stage_hook.py")
    legacy.append(SCRIPT_DIR / "canadianshopper" / "tools" / "cs_stage_hook.py")
    return next((candidate for candidate in legacy if candidate.is_file()), None)


def canadianshopper_import_folder(output_paths, stage_hook=None):
    """Find the folder containing the final CS import CSVs."""
    if not stage_hook:
        return Path(output_paths[0]).parent if output_paths else SCRIPT_DIR
    candidates = [SCRIPT_DIR / "canadianshopper_products" / "cs-ready"]
    candidates.extend((Path(stage_hook).parent / "cs-ready",
                       SCRIPT_DIR / "cs-ready",
                       SCRIPT_DIR.parent / "cs-ready",
                       Path(USER_SETTINGS.get("pipeline_dir", "")) / "cs-ready"))
    for folder in candidates:
        try:
            if folder.is_dir() and any(folder.glob("canadianshopper_import*.csv")):
                return folder
        except OSError:
            pass
    return Path(output_paths[0]).parent if output_paths else SCRIPT_DIR


def maybe_run_canadianshopper(args, cards_parsed):
    """Build CanadianShopper CSV batches and hand them to an installed plugin."""
    # --facebook now automatically continues into this stage; --canadianshopper
    # also allows generating this CSV without running the Facebook workflow.
    if not (
        getattr(args, "canadianshopper", False)
        or getattr(args, "facebook", False)
    ):
        return

    print("\n" + "=" * 58)
    print("  CANADIANSHOPPER UPLOAD")
    print("=" * 58)
    print(
        "The CSV uses your configured category, ship-from region, and shipping "
        "defaults: %s; %s; flat %s; free shipping %s; handling %s day(s); "
        "transit %s day(s)." % (
            CANADIANSHOPPER_CATEGORY, CANADIANSHOPPER_PROVINCE,
            CANADIANSHOPPER_FLAT_SHIPPING, CANADIANSHOPPER_FREE_SHIPPING,
            CANADIANSHOPPER_HANDLING_DAYS, CANADIANSHOPPER_TRANSIT_DAYS))

    image_base_url = get_canadianshopper_image_base_url(args)
    if not image_base_url:
        return

    rows = build_canadianshopper_rows(cards_parsed, image_base_url)
    output_paths = write_canadianshopper_csvs(rows)

    print(f"\nCreated {len(rows)} CanadianShopper listing(s):")
    for batch_index, path in enumerate(output_paths):
        count = min(
            CANADIANSHOPPER_BATCH_SIZE,
            len(rows) - batch_index * CANADIANSHOPPER_BATCH_SIZE,
        )
        print(f"  - {path} ({count} product(s))")

    print(f"\nImage URL base: {image_base_url}")
    print("Next steps:")
    print("  1. Confirm the renamed images are publicly available under that folder.")
    print("  2. If the CanadianShopper plugin is installed, it stages the photos")
    print("     and offers to import the CSVs as unpublished drafts.")
    print("  3. Without the plugin, import the CSVs manually and review each draft.")
    # ---- Optional CanadianShopper photo stage: square front + back gallery
    _cs_hook = _find_cs_stage_hook()
    if _cs_hook is not None:
        import importlib.util as _ilu
        import inspect as _inspect
        _spec = _ilu.spec_from_file_location("cs_stage_hook", str(_cs_hook))
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        # Current plugins receive the core's cookie path; older v2.20
        # sibling hooks keep using their own app-root cookie file.
        params = _inspect.signature(_mod.run_stage).parameters
        kwargs = {"tools_dir": str(_cs_hook.parent)}
        if "cookie_file" in params:
            kwargs["cookie_file"] = str(SCRIPT_DIR.parent / "cookie.txt")
        if "browser_name" in params:
            kwargs["browser_name"] = USER_SETTINGS.get("browser_name", "")
        _mod.run_stage(output_paths, args, SCRIPT_DIR, OUTPUT_DIR, **kwargs)
    else:
        print("  ! CanadianShopper photo stage not installed.")
        print("    The CanadianShopper CSV above is still written - you")
        print("    can import it by hand; the photos are just not staged.")
        print("    Install the CanadianShopper add-on from the Plugins tab,")
        print("    then re-run the listing.")
        import_folder = canadianshopper_import_folder(output_paths)
        if open_folder(import_folder):
            print("Opened the CanadianShopper import folder: %s" % import_folder)

def _ebay_quicklist_sport(card):
    """Map the card's detected category/content to the attached script's sport templates."""
    text = " ".join(str(card.get(key, "")) for key in (
        "category", "subcategory", "seo_title", "keyword", "tags",
        "full_description")).casefold()
    for sport in ("hockey", "baseball", "basketball", "football"):
        if sport in text:
            return sport
    return "sports"


def _ebay_quicklist_values(card):
    """Build item-specific values using the attached Quick List heuristics and saved defaults."""
    settings = USER_SETTINGS
    tags = [tag.strip() for tag in str(card.get("tags", "")).split(",") if tag.strip()]
    brand = str(card.get("brand") or "").strip()
    if not brand:
        brand = next((tag for tag in tags
                      if re.search(r"O-Pee-Chee|Topps|Upper Deck", tag, re.I)), "")
    condition = next((tag for tag in tags
                      if re.search(r"Mint|NM|VG|Good", tag, re.I)), "")
    set_name = next((tag for tag in tags
                     if re.search(r"O-Pee-Chee|Topps", tag, re.I)), "")
    if not set_name:
        set_name = tags[0] if tags else ""
    try:
        price = math.ceil(float(card.get("price") or 0))
    except (TypeError, ValueError, OverflowError):
        price = 0
    return {
        "title": str(card.get("seo_title") or "").strip(),
        "price": ("%.2f" % price) if price else "",
        "sport": ("Sports Cards" if _ebay_quicklist_sport(card) == "sports"
                  else _ebay_quicklist_sport(card).title()),
        "year": str(card.get("year") or settings.get("ebay_default_year", "Unknown")),
        "manufacturer": brand or settings.get("ebay_default_manufacturer", "Unknown"),
        "card_number": str(card.get("card_num") or settings.get("ebay_default_card_number", "N/A")),
        "player": str(card.get("player") or settings.get("ebay_default_player", "Unknown")),
        "set": set_name or settings.get("ebay_default_set", "Vintage"),
        "condition": condition or settings.get("ebay_default_condition", "Mint"),
        "grade": str(card.get("grade") or settings.get("ebay_default_grade", "")),
        "autographed": settings.get("ebay_default_autographed", "No"),
        "description": str(card.get("full_description") or settings.get(
            "ebay_default_description", "")),
        "front_image": str(card.get("front_img") or ""),
        "back_image": str(card.get("back_img") or ""),
    }


def _ebay_image_base_url():
    """Resolve the configured public image URL base for the current uploads month."""
    now = datetime.now()
    base = str(USER_SETTINGS.get("ebay_image_base_url", "") or "").strip()
    if not base:
        base = default_canadianshopper_image_base_url()
    return (base.replace("{year}", now.strftime("%Y"))
                .replace("{month}", now.strftime("%m"))
                .rstrip("/"))


def _ebay_image_url(filename, base_url):
    if not filename:
        return ""
    if str(filename).lower().startswith(("http://", "https://")):
        return str(filename)
    return canadianshopper_image_url(filename, base_url) if base_url else ""


def _render_ebay_quicklist(cards):
    """Create a self-contained copy/drag helper from the cards in this run."""
    image_base = _ebay_image_base_url()
    cards_html = []
    template_urls = []
    for index, card in enumerate(cards, 1):
        values = _ebay_quicklist_values(card)
        sport_key = _ebay_quicklist_sport(card)
        template = str(USER_SETTINGS.get(
            "ebay_template_%s_url" % sport_key, "") or "").strip()
        if not template:
            template = str(USER_SETTINGS.get("ebay_template_default_url", "") or "").strip()
        if template:
            template_urls.append(template)
        fields = [
            ("Title", values["title"]), ("Buy It Now price (CAD)", values["price"]),
            ("Sport / Game", values["sport"]), ("Year", values["year"]),
            ("Manufacturer", values["manufacturer"]), ("Card Number", values["card_number"]),
            ("Player", values["player"]), ("Set", values["set"]),
            ("Condition", values["condition"]), ("Grade", values["grade"]),
            ("Autographed", values["autographed"]),
        ]
        snippets = []
        for label, value in fields:
            escaped_value = html.escape(str(value), quote=True)
            snippets.append(
                '<button class="snippet" draggable="true" data-value="%s" '
                'title="Drag to eBay or click to copy"><b>%s</b><br>%s</button>' %
                (escaped_value, html.escape(label), escaped_value or "(blank)"))
        description = html.escape(values["description"], quote=True)
        image_cards = []
        for label, filename in (("Front", values["front_image"]),
                                ("Back", values["back_image"])):
            url = _ebay_image_url(filename, image_base)
            if not (filename or url):
                continue
            local_path = OUTPUT_DIR / Path(filename).name if filename else None
            local_link = (local_path.resolve().as_uri()
                          if local_path and local_path.is_file() else "")
            image_source = url or local_link
            image_cards.append(
                '<div class="image">%s%s%s'
                '<button class="snippet" draggable="true" data-value="%s" '
                'title="Drag image URL to eBay or click to copy">%s image URL<br>%s</button>'
                '<small>%s</small></div>' % (
                    ('<a href="%s" target="_blank" rel="noopener">' % html.escape(image_source, quote=True)
                     if image_source else ""),
                    ('<img src="%s" alt="%s image">' %
                     (html.escape(image_source, quote=True), label)
                     if image_source else ""),
                    "</a>" if image_source else "",
                    html.escape(url or local_link, quote=True), label,
                    html.escape(url or local_link),
                    html.escape(Path(filename).name if filename else "")))
        template_link = (
            '<a class="template" href="%s" target="_blank" rel="noopener">Open %s eBay template</a>'
            % (html.escape(template, quote=True), html.escape(values["sport"]))
            if template else '<span class="template missing">Set a default eBay template URL in User Settings</span>')
        cards_html.append(
            '<article><h2>%d. %s</h2><p class="price">$%s CAD</p>%s'
            '<div class="snippets">%s</div><h3>Description (drag or click to copy)</h3>'
            '<pre class="description snippet" draggable="true" data-value="%s" '
            'title="Drag to eBay or click to copy">%s</pre><div class="images">%s</div>%s</article>' % (
                index, html.escape(values["title"]), html.escape(values["price"]),
                '<p class="sport">Sport template: %s</p>' % html.escape(values["sport"]),
                "".join(snippets), description, description,
                "".join(image_cards), template_link))
    page = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alex Collect — eBay Quick List</title>
<style>
:root{color-scheme:light;font:15px/1.5 system-ui,sans-serif;color:#172033;background:#eef2f7}body{max-width:1100px;margin:24px auto;padding:0 16px}h1{color:#183153}article{background:white;border:1px solid #d7dfeb;border-radius:12px;padding:20px;margin:18px 0;box-shadow:0 4px 18px #1b365010}h2{margin:0;color:#183153}.price{font-size:1.35rem;color:#08652c;font-weight:700}.sport{color:#52627a}.snippets{display:flex;flex-wrap:wrap;gap:8px}.snippet{font:13px/1.4 ui-monospace,monospace;text-align:left;color:#183153;background:#f5f8fc;border:1px solid #cdd8e6;border-radius:8px;padding:9px 12px;cursor:grab;max-width:100%;overflow-wrap:anywhere}.snippet:hover{background:#e9f1fb}.description{white-space:pre-wrap;max-height:260px;overflow:auto;background:#fafbfd;border:1px solid #e1e6ee;border-radius:8px;padding:12px}.images{display:flex;flex-wrap:wrap;gap:14px;margin:14px 0}.image{display:flex;flex-direction:column;gap:6px;max-width:280px}.image img{max-width:260px;max-height:190px;object-fit:contain;background:#f5f5f5;border:1px solid #ddd;border-radius:8px}.image small{color:#65738a;overflow-wrap:anywhere}.template{display:inline-block;margin-top:14px;background:#e53238;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700}.missing{color:#9b3c00}.note{background:#fff7e8;border:1px solid #f0d29d;border-radius:8px;padding:12px}.status{color:#087044;font-weight:600}
</style>
<body><h1>⚡ Alex Collect — eBay Quick List</h1>
<p class="note">Use the buttons as draggable snippets or click to copy. Images and URLs are gathered from this card batch. Opened eBay templates do not submit listings; sign in, review each field, and submit manually.</p>
<p class="status">Click a field to copy it. Drag a field onto the matching eBay form field.</p>
__CARD_SECTIONS__
<script>
document.querySelectorAll('.snippet').forEach(function(btn){btn.addEventListener('dragstart',function(e){e.dataTransfer.setData('text/plain',btn.dataset.value||'');e.dataTransfer.effectAllowed='copy'});btn.addEventListener('click',async function(){var value=btn.dataset.value||'';try{await navigator.clipboard.writeText(value)}catch(_){var box=document.createElement('textarea');box.value=value;document.body.appendChild(box);box.select();document.execCommand('copy');box.remove()}var old=btn.innerHTML;btn.innerHTML='Copied';setTimeout(function(){btn.innerHTML=old},900)})});
</script></body></html>"""
    page = page.replace("__CARD_SECTIONS__", "".join(cards_html))
    return page, template_urls


def _parse_ebay_card_selection(answer, count):
    answer = (answer or "").strip().casefold()
    if answer in {"all", "a", "*"}:
        return list(range(count))
    if answer in {"", "n", "no", "none", "q", "quit"}:
        return []
    selected = []
    for token in re.split(r"[,;\s]+", answer):
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            if not (left.isdigit() and right.isdigit()):
                raise ValueError("Use card numbers such as 1,3 or 2-4.")
            values = range(int(left), int(right) + 1)
        elif token.isdigit():
            values = (int(token),)
        else:
            raise ValueError("Use card numbers such as 1,3 or 2-4.")
        for value in values:
            if value < 1 or value > count:
                raise ValueError("Card number %d is outside this batch." % value)
            if value - 1 not in selected:
                selected.append(value - 1)
    return selected


def maybe_run_ebay_quicklist(cards_parsed):
    """Ask which cards to prepare for manual eBay listing and open template tabs."""
    if not USER_SETTINGS.get("ebay_quicklist_enabled", True) or not cards_parsed:
        return
    EBAY_QUICKLIST_DIR.mkdir(parents=True, exist_ok=True)
    # Older pages are now durable in one history file; leave only this run's
    # current page in the active folder.
    _roll_ebay_history()
    print("\n" + "=" * 58)
    print("  eBAY QUICK LIST")
    print("=" * 58)
    try:
        answer = input("Would you like to prepare any of these cards for eBay? [y/N] ").strip().lower()
    except (EOFError, OSError):
        return
    if answer not in ("y", "yes"):
        print("  eBay Quick List skipped.")
        return
    print("\nChoose cards to prepare (comma-separated numbers, ranges, or 'all'):")
    for index, card in enumerate(cards_parsed, 1):
        values = _ebay_quicklist_values(card)
        print("  %d. %s  —  $%s CAD  —  %s" % (
            index, values["title"], values["price"], values["sport"]))
    while True:
        try:
            selection = input("Cards [e.g. 1,3 or 2-4; Enter to cancel]: ")
            selected = _parse_ebay_card_selection(selection, len(cards_parsed))
            break
        except (ValueError, EOFError, OSError) as exc:
            if isinstance(exc, (EOFError, OSError)):
                return
            print("  %s" % exc)
    if not selected:
        print("  No eBay cards selected.")
        return
    chosen = [cards_parsed[index] for index in selected]
    page, template_urls = _render_ebay_quicklist(chosen)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = EBAY_QUICKLIST_DIR / ("ebay_quick_list_%s.html" % timestamp)
    sidecar = output.with_suffix(".json")
    try:
        output.write_text(page, encoding="utf-8")
        write_ebay_sidecar(sidecar, {
            "version": 1,
            "source_file": output.name,
            "generated": timestamp,
            "cards": [_ebay_quicklist_values(card) for card in chosen],
            "template_urls": template_urls,
            "html": page,
        })
    except OSError as exc:
        print("  !! Could not create the eBay Quick List file(s): %s" % exc,
              file=sys.stderr)
        return
    browser = USER_SETTINGS.get("browser_name", "") or ""
    if not browser:
        browser = choose_browser_cli()
    try:
        launch_urls([output.resolve().as_uri()], browser or "system")
        if template_urls:
            launch_urls(template_urls, browser or "system")
        if open_folder(OUTPUT_DIR):
            print("  Opened the renamed image folder: %s" % OUTPUT_DIR)
        print("  Opened the Quick List page and %d eBay template tab(s) in %s." % (
            len(template_urls), browser_label(browser or "system")))
        print("  Details are available for copy/drag-and-drop; review and submit on eBay manually.")
        try:
            input("  Press Enter when finished with this eBay Quick List to continue...")
        except EOFError:
            pass
    except (OSError, RuntimeError) as exc:
        print("  !! Could not open the eBay Quick List in the configured browser: %s" % exc,
              file=sys.stderr)
    print("  Quick List page: %s" % output)


def run_post_listing_uploads(args, cards_parsed):
    """Run Facebook, CanadianShopper, and optional eBay Quick List stages."""
    maybe_run_facebook(args)
    maybe_run_canadianshopper(args, cards_parsed)
    maybe_run_ebay_quicklist(cards_parsed)


# =====================================================================
#  LISTING SUB-COMMAND
# =====================================================================
RERUN_MARKETS = ("woocommerce", "canadianshopper", "facebook", "ebay", "all")


def read_listing_text(input_path):
    """Read the AI reply a step should reuse (exits with a clear message)."""
    input_path = Path(input_path)
    if not input_path.is_file():
        sys.exit(f"Input file not found: {input_path}")

    raw_text = input_path.read_text(encoding="utf-8-sig")
    if not raw_text.strip():
        sys.exit("No input text found. Copy the AI listing text first.")
    return raw_text


def parse_listing_text(raw_text, args):
    """Split and parse an AI reply into card dictionaries."""
    card_dicts = split_into_cards(raw_text)
    default_brand = getattr(args, "brand", "O-Pee-Chee")
    image_ext = getattr(args, "image_ext", IMG_FORMAT)
    return [parse_card(cd, default_brand, image_ext=image_ext)
            for cd in card_dicts]


def print_parsed_cards(parsed):
    print(f"Found {len(parsed)} card(s):\n")
    for i, c in enumerate(parsed, start=1):
        print(f"  {i}. {c['seo_title']}")
        print(f"     Grade: {c['grade']}  |  Price: ${c['price']}  |  "
              f"Brand: {c['brand']}")
        print(f"     Front: {c['front_img']}")
        print(f"     Back:  {c['back_img']}")
    print()


def confirm_card_metadata(parsed, args):
    """Confirm categories and quantity; returns the quantity to use."""
    auto_yes = getattr(args, "yes", False)
    forced_category = getattr(args, "category", None)

    if forced_category:
        forced_sub = getattr(args, "subcategory", "") or ""
        for c in parsed:
            c["category"] = forced_category
            c["subcategory"] = forced_sub
        print(f"Using forced category for all cards: "
              f"{category_label(forced_category, forced_sub)}")
    else:
        confirm_categories(parsed, auto_yes=auto_yes)

    default_quantity = getattr(args, "quantity", 1)
    for c in parsed:
        c["quantity"] = default_quantity
    confirm_quantities(parsed, auto_yes=auto_yes)
    return default_quantity


def write_woocommerce_csv(rows):
    """Write this run's WooCommerce CSV and roll older ones into history."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    WOOCOMMERCE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = str(WOOCOMMERCE_DIR / f"woocommerce_import_{timestamp}.csv")
    write_csv(rows, out_path)
    _roll_csv_history(
        WOOCOMMERCE_DIR, "woocommerce_import_*.csv",
        "woocommerce_history.csv", exclude_paths=[out_path],
        key_fields=("SKU",))
    return out_path


def print_woocommerce_rows(rows, out_path):
    print(f"\nParsed {len(rows)} card(s). Wrote CSV: {out_path}")
    for r in rows:
        print(f"  - {r['SKU']}: {r['Name']}  "
              f"(${r['Regular price']})  [{r['Categories']}]")


def find_rerun_input(args):
    """The AI reply a re-run should reuse: explicit path, then the newest
    _card_input.txt the app wrote beside card_pipeline.py."""
    explicit = getattr(args, "input", None)
    if explicit:
        return Path(explicit)

    seen, candidates = set(), []
    for folder in (SCRIPT_DIR, Path.cwd()):
        for pattern in ("_card_input.txt", "*_card_input*.txt"):
            for path in sorted(folder.glob(pattern),
                               key=lambda p: _mtime(p), reverse=True):
                if path not in seen:
                    seen.add(path)
                    candidates.append(path)
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size:
                return path
        except OSError:
            continue
    return None


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _with_flags(args, **overrides):
    """A copy of the parsed args with stage flags switched on."""
    merged = vars(args).copy()
    merged.update(overrides)
    return argparse.Namespace(**merged)


def cmd_rerun(args):
    """Rebuild one marketplace output from files that already exist.

    Re-runs deliberately never rename or move images: the scans were already
    matched to the CSV, so only the chosen marketplace output is rebuilt.
    """
    market = getattr(args, "market", "all")
    if market not in RERUN_MARKETS:
        sys.exit("Unknown --market %r. Choose one of: %s"
                 % (market, ", ".join(RERUN_MARKETS)))

    print("=" * 58)
    print("  RE-RUN: %s" % market.upper())
    print("=" * 58)
    print("Only this marketplace output is rebuilt. Images are not moved "
          "or renamed, and other marketplace files are left alone.\n")

    needs_cards = market in ("woocommerce", "canadianshopper", "ebay", "all")
    parsed = None
    if needs_cards:
        input_path = find_rerun_input(args)
        if input_path is None:
            sys.exit(
                "No AI listing text found. Pass --input <file>, or run the "
                "card pipeline once so _card_input.txt is written beside "
                "card_pipeline.py.")
        print("Reusing the AI listing text: %s\n" % input_path)
        raw_text = read_listing_text(input_path)
        print("-- Parsing AI listing text... --\n")
        parsed = parse_listing_text(raw_text, args)
        if not parsed:
            sys.exit("Could not parse any card listings from the input text.")
        print_parsed_cards(parsed)
        quantity = confirm_card_metadata(parsed, args)
    else:
        quantity = getattr(args, "quantity", 1)

    if market in ("woocommerce", "all"):
        rows = build_rows(parsed, quantity)
        print_woocommerce_rows(rows, write_woocommerce_csv(rows))

    if market in ("facebook", "all"):
        maybe_run_facebook(_with_flags(args, facebook=True))

    if market in ("canadianshopper", "all"):
        maybe_run_canadianshopper(
            _with_flags(args, canadianshopper=True), parsed)

    if market in ("ebay", "all"):
        maybe_run_ebay_quicklist(parsed)

    print("\nRe-run finished: %s." % market)


def cmd_listing(args):
    """Handle the 'listing' sub-command."""
    input_path = Path(args.input)
    raw_text = read_listing_text(input_path)

    # -- Parse cards --
    print("-- Parsing AI listing text... --\n")
    parsed = parse_listing_text(raw_text, args)

    if not parsed:
        sys.exit("Could not parse any card listings from the input text.")

    print_parsed_cards(parsed)

    # -- Category detection, quantity, and the WooCommerce CSV --
    default_quantity = confirm_card_metadata(parsed, args)
    rows = build_rows(parsed, default_quantity)
    print_woocommerce_rows(rows, write_woocommerce_csv(rows))

    # -- Rename images --
    no_images = getattr(args, "no_images", False)
    if no_images:
        print("\n(--no-images set: skipping image rename step.)")
        run_post_listing_uploads(args, parsed)
        return

    directory = str(OUTPUT_DIR)
    if not os.path.isdir(directory):
        print(f"\nImage directory not found: {directory}  (nothing renamed)",
              file=sys.stderr)
        sys.exit(1)

    front_prefix = getattr(args, "front_prefix", None)
    back_prefix = getattr(args, "back_prefix", None)
    # parse_listing_text() and confirm_card_metadata() keep their own copies of
    # these two, so the rename stage below has to bind them again.
    auto_yes = getattr(args, "yes", False)
    image_ext = getattr(args, "image_ext", IMG_FORMAT)

    if not front_prefix or not back_prefix:
        try:
            front_prefix, back_prefix, detected = autodetect_prefixes(
                directory, image_ext
            )
        except ValueError as e:
            print(f"\n{e}", file=sys.stderr)
            print("(CSV was still written.)")
            sys.exit(1)

        print("\nAuto-detected scan sets by timestamp "
              "(front = older, scanned first):")
        for label, pfx in (("FRONT", front_prefix), ("BACK ", back_prefix)):
            found = detected.get(pfx, [])
            note = ("" if found == list(range(1, 10))
                    else f"  (positions found: {found})")
            print(f"   {label}: {pfx}{note}")

    fronts, backs = targets_from_rows(rows)
    copy_mode = getattr(args, "copy", False)

    ops, missing = plan_renames(
        directory, fronts, backs,
        front_prefix, back_prefix, image_ext
    )

    # Collision guard
    seen, collisions = {}, []
    for src, dst, label in ops:
        if dst in seen:
            collisions.append((dst, seen[dst], label))
        seen[dst] = label

    verb = "COPY" if copy_mode else "MOVE"
    print_plan(ops, missing, verb)

    if collisions:
        print("\n  !! Destination collisions — aborting:")
        for dst, a, b in collisions:
            print(f"     - {os.path.basename(dst)} <- {a} AND {b}")
        sys.exit(2)

    if not ops:
        print("\nNo matching source files found — nothing to rename.")
        run_post_listing_uploads(args, parsed)
        return

    if not auto_yes:
        try:
            answer = input(
                f"\nApply these {len(ops)} rename(s)? [y/N] "
            ).strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("Aborted — no files changed. (CSV was still written.)")
            return

    apply_renames(ops, copy=copy_mode)
    print(f"\nDone: {len(ops)} image(s) {verb.lower()}d to match the CSV.")

    # -- WooCommerce upload + Facebook feed --
    run_post_listing_uploads(args, parsed)


# =====================================================================
#  MAIN ENTRY POINT
# =====================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Alex Collect — Card Listing Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples
            --------
              # Split two scans:
              python card_pipeline.py split --front scan_front.jpg --back scan_back.jpg

              # Parse clipboard text and generate CSV + rename images:
              python card_pipeline.py listing --input card_input.txt

              # Force category for all cards:
              python card_pipeline.py listing --input card_input.txt \\
                  --category "Sports Card" --subcategory "Hockey Card"

              # Skip image renames (CSV only):
              python card_pipeline.py listing --input card_input.txt --no-images

              # Facebook workflow, followed automatically by CanadianShopper CSV:
              python card_pipeline.py listing --input card_input.txt --facebook

              # CanadianShopper only (without Facebook):
              python card_pipeline.py listing --input card_input.txt --canadianshopper \
                  --canadianshopper-image-base-url "https://your-store.example/wp-content/uploads/YYYY/MM"

              # Rebuild ONLY the Facebook feed files from the AI text already used:
              python card_pipeline.py rerun --market facebook

              # Rebuild ONLY the CanadianShopper CSV (images are not touched):
              python card_pipeline.py rerun --market canadianshopper --input card_input.txt
        """),
    )

    sub = parser.add_subparsers(dest="command")

    # -- split --
    p_split = sub.add_parser(
        "split", help="Split 3x3 sleeve scan(s) into 9 card images"
    )
    p_split.add_argument(
        "--front", required=True, help="Path to the FRONT scan image"
    )
    p_split.add_argument(
        "--back", default=None, help="Path to the BACK scan image"
    )

    # -- listing --
    p_list = sub.add_parser(
        "listing",
        help="Parse AI text, rename images, generate CSV"
    )
    p_list.add_argument(
        "--input", required=True,
        help="Path to the AI listing text file"
    )
    p_list.add_argument(
        "--brand", default="O-Pee-Chee",
        help="Fallback brand if none detected (default: O-Pee-Chee)"
    )
    p_list.add_argument(
        "--category", default=None,
        help="Force this top-level category for ALL cards"
    )
    p_list.add_argument(
        "--subcategory", default=None,
        help="Force this sub-category (with --category)"
    )
    p_list.add_argument(
        "--quantity", type=int, default=1,
        help="Stock quantity per item (default: 1)"
    )
    p_list.add_argument(
        "--image-ext", default="webp",
        help="Source scan extension (default: webp)"
    )
    p_list.add_argument(
        "--front-prefix",
        help="Filename prefix of FRONT scans (before _1.._9)"
    )
    p_list.add_argument(
        "--back-prefix",
        help="Filename prefix of BACK scans (before _1.._9)"
    )
    p_list.add_argument(
        "--copy", action="store_true",
        help="Copy scans instead of moving (keeps originals)"
    )
    p_list.add_argument(
        "--no-images", action="store_true",
        help="Only build CSV; skip renaming images"
    )
    p_list.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip confirmation prompts"
    )
    p_list.add_argument(
        "--facebook", action="store_true",
        help="Run Facebook workflow, then automatically create the "
             "CanadianShopper CSV"
    )
    p_list.add_argument(
        "--canadianshopper", action="store_true",
        help="Also create CanadianShopper CSV(s) when running without --facebook"
    )
    p_list.add_argument(
        "--canadianshopper-image-base-url", default=None,
        help="Public URL folder for uploaded images, e.g. "
             "https://your-store.example/wp-content/uploads/YYYY/MM"
    )
    p_list.add_argument(
        "--feed-wait", type=int, default=5,
        help="Seconds to wait after feed rebuild (default: 5)"
    )
    p_list.add_argument(
        "--feed-cookie", default=None,
        help="Cookie header for logged-in session"
    )
    p_list.add_argument(
        "--no-browser", action="store_true",
        help="Don't open refresh URL in browser"
    )
    p_list.add_argument(
        "--browser", default=None,
        help="Override the saved browser for the refresh URL"
    )

    # -- rerun --
    p_rerun = sub.add_parser(
        "rerun",
        help="Rebuild one marketplace output (Woo, CanadianShopper, "
             "Facebook, eBay) from files that already exist"
    )
    p_rerun.add_argument(
        "--market", required=True, choices=RERUN_MARKETS,
        help="Which marketplace output to rebuild ('all' runs every stage)"
    )
    p_rerun.add_argument(
        "--input", default=None,
        help="AI listing text to reuse (default: the newest _card_input.txt "
             "beside card_pipeline.py)"
    )
    p_rerun.add_argument(
        "--brand", default="O-Pee-Chee",
        help="Fallback brand if none detected (default: O-Pee-Chee)"
    )
    p_rerun.add_argument(
        "--category", default=None,
        help="Force this top-level category for ALL cards"
    )
    p_rerun.add_argument(
        "--subcategory", default=None,
        help="Force this sub-category (with --category)"
    )
    p_rerun.add_argument(
        "--quantity", type=int, default=1,
        help="Stock quantity per item (default: 1)"
    )
    p_rerun.add_argument(
        "--image-ext", default="webp",
        help="Source scan extension (default: webp)"
    )
    p_rerun.add_argument(
        "-y", "--yes", action="store_true",
        help="Accept the default categories, quantities, and image folder"
    )
    p_rerun.add_argument(
        "--canadianshopper-image-base-url", default=None,
        help="Public URL folder for uploaded images"
    )
    p_rerun.add_argument(
        "--feed-wait", type=int, default=5,
        help="Seconds to wait after feed rebuild (default: 5)"
    )
    p_rerun.add_argument(
        "--feed-cookie", default=None,
        help="Cookie header for logged-in session"
    )
    p_rerun.add_argument(
        "--no-browser", action="store_true",
        help="Don't open the refresh URL in a browser"
    )
    p_rerun.add_argument(
        "--browser", default=None,
        help="Override the saved browser for the refresh URL"
    )

    args = parser.parse_args()

    if args.command == "split":
        cmd_split(args)
    elif args.command == "listing":
        cmd_listing(args)
    elif args.command == "rerun":
        cmd_rerun(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
