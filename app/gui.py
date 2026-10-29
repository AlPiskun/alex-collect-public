#!/usr/bin/env python3
# ===========================================================================
#  Alex Collect - Control Panel (the GUI)
# ===========================================================================
#  One window for every tool in this folder. It does not contain any
#  business logic of its own: every button runs the same tested command
#  line that the .bat launchers run, so there is "one brain and two skins".
#  If a tool changes, the GUI picks the change up automatically.
#
#  Three ways in (View menu / the gear button):
#    * Wizard   - guided tour, shown on the very first launch
#    * Tasks    - "what do you want to do today?" menu (the default after)
#    * Tabs     - everything laid out in tab groups
#
#  The console pane at the bottom always shows what is running. If a tool
#  asks a question ("paste the cookie:", "Stage all of them? [Y/n]"),
#  type the answer into the box next to Send and press Send.
#
#  Everything is preview-first: nothing is written to CanadianShopper or
#  to your files without an extra confirmation step.
#
#  Run:  python gui.py            (or double-click AlexCollect.bat)
#  Test: python test-gui.py
# ===========================================================================

import json
import os
import queue
import re
import shutil
import string
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from browser_utils import available_browsers, browser_label, open_urls as launch_urls
from plugin_manager import (PluginError, PluginManager,
                            version_at_least)
from process_utils import no_window_kwargs
import photo_assign
import photo_pool
import photo_replace
import market_stock
import photo_thumbs
import sale_preview
import cs_listing
import stock_compare
import stock_write
import woo_media
import woo_orders
from sale_inputs import woo_get
from user_settings import (default_scan_dir, has_woo_credentials,
                           has_wordpress_credentials, load_user_settings,
                           marketplace_seller_urls, normalize_web_url,
                           product_edit_url, product_search_url,
                           read_woo_credentials, read_wordpress_credentials,
                           restrict_file_permissions, site_admin_url,
                           sync_site_url_to_woo_keys)

VERSION = "2.83"

DEFAULT_SCAN_DIR = default_scan_dir()
APP_NAME = "Alex Collect Control Panel"

BASE = Path(__file__).resolve().parent          # the tools folder
HERE_HAS_PIPELINE = (BASE.parent / "card_pipeline.py").exists()
WORK = BASE.parent if HERE_HAS_PIPELINE else BASE   # where card_pipeline.py + CSVs live

PLUGIN_MANAGER = PluginManager(core_version=VERSION)
CS_PLUGIN_ID = "canadianshopper"
#  The photo work is three different jobs behind one script, so they are
#  resolved by action ID rather than by filename: staging prepares images,
#  photo_wire re-wires the whole staged batch, and photo_replace re-wires the
#  one card being edited (plugin 1.0.14 and newer).
CS_PHOTO_STAGE = "batch.photo_stage"
CS_PHOTO_WIRE = "batch.photo_wire"
CS_PHOTO_REPLACE = "batch.photo_replace"
#  Reading CanadianShopper's own order list, so a sale there can be
#  previewed before it is written. Optional: a plugin without it
#  still sells cards, the panel just says what is missing.
CS_ORDERS_ACTION = "after_sale.orders"
#  Listing CanadianShopper's whole catalogue with its inventory, so the
#  two sites can be compared without opening either dashboard.
CS_STOCK_ACTION = "stock.list"
#  The write half. It is asked for exactly as the plugin names it, so an
#  older plugin that cannot set stock is detected rather than assumed.
CS_STOCK_SET_ACTION = "stock.set"
#  1.0.25 stopped filtering stock.list down to the listings that are on sale:
#  every listing comes back with its own state. Without that, a card whose
#  listing is a draft, hidden or archived simply vanishes from the comparison
#  and comes back as "only on your website" - which is why the version is
#  checked before the panel explains one of those cards away.
CS_STOCK_STATUS_VERSION = "1.0.25"
#  1.0.26 asks the site for a page it cannot serve from its cache, and re-reads
#  once when a page comes back byte-identical to the last run. Before it, a
#  listing moved in the vendor dashboard could keep coming back in its old
#  state, which reads as the app being stale when it is only repeating what it
#  was given - so the version decides what the panel is allowed to claim.
CS_STOCK_CACHE_VERSION = "1.0.26"
#  1.0.27 streams the publisher instead of capturing it, so the "type PUBLISH"
#  question reaches the console. Before it the question was invisible and a
#  run could sit there looking frozen - which is what the panel says, and why
#  the version decides which sentence a silent run gets.
CS_NESTED_STREAM_VERSION = "1.0.27"
#  Creating listings is the plugin's own importer: the core writes the CSV it
#  has always written, and this action takes that file and makes the drafts.
CS_IMPORT_ACTION = "marketplace.import_csv"
#  batch.photo_replace existed in 1.0.14 but only matched a staged CSV
#  row. The CSV-free --mode replace arrived in 1.0.15, so the action ID
#  alone cannot tell the two apart - the version has to be checked.
CS_PHOTO_REPLACE_VERSION = "1.0.15"
#  --back was additive until 1.0.16, which replaces the paired gallery row
#  instead of adding a second back beside it. Sending --back to 1.0.15 would
#  leave the old back photo on the listing, so the gate is separate.
CS_PHOTO_BACK_VERSION = "1.0.16"
CS_TOOL_ACTIONS = {
    "sold-cards.py": "after_sale.stock_update",
    # Filename resolution can only name ONE of the photo actions; call sites
    # that mean a specific one resolve it with TOOL_ACTION() instead.
    "cs-image-sync.py": CS_PHOTO_STAGE,
    "pad-and-upload.py": "batch.photo_cache_repair",
    "cs-publish-drafts.py": "marketplace.publish_drafts",
}
CS_ADDON_TOOLS = tuple(CS_TOOL_ACTIONS)


def TOOL(name):
    """Resolve core tools or plugin actions, preferring installed plugins."""
    core_path = BASE / str(name)
    action = CS_TOOL_ACTIONS.get(Path(str(name)).name)
    if action:
        try:
            return str(PLUGIN_MANAGER.resolve_action(action))
        except PluginError:
            if (PLUGIN_MANAGER.root / CS_PLUGIN_ID).exists():
                # An installed but disabled/broken plugin must not fall back to
                # stale v2.20 copies sitting beside the core tools.
                return str(PLUGIN_MANAGER.root / CS_PLUGIN_ID / "__disabled__" /
                           Path(str(name)).name)
    if ((BASE / "addon-canadianshopper.txt").is_file() and
            core_path.is_file()):
        return str(core_path)
    return str(core_path)


def TOOL_ACTION(action_id):
    """Resolve one specific plugin action, or "" when nothing provides it.

    Call sites that need a particular photo action use this instead of a
    filename, so a single script can back several actions. An empty result
    means the installed plugin predates the action; the caller decides
    whether to say so or to fall back to the filename.
    """
    try:
        return str(PLUGIN_MANAGER.resolve_action(action_id))
    except PluginError:
        return ""


def last_tool_output(app):
    """What the tool that just finished printed, or "" when nothing is known.

    A plugin's own summary is the only reliable answer to "how many drafts
    did you find" - its report file is its format, not the core's. The runner
    keeps the text of the current run for exactly that question, and a caller
    that cannot find it gets "" rather than a guess.
    """
    return str(getattr(getattr(app, "runner", None), "output", "") or "")


def plugin_version(plugin_id=CS_PLUGIN_ID):
    """The installed plugin's declared version, or "" when unreadable."""
    try:
        return str(PLUGIN_MANAGER.get_plugin(plugin_id).get("version") or "")
    except PluginError:
        return ""


def photo_replace_available():
    """Whether the plugin can replace ONE card's photos without a staged CSV.

    The action ID is not enough: 1.0.14 declares batch.photo_replace but only
    matches a staged CSV row, which a replacement run does not have. Offering
    it there would produce the "CSV(s) not found" failure the user already hit.
    """
    if not TOOL_ACTION(CS_PHOTO_REPLACE):
        return False
    return version_at_least(plugin_version(), CS_PHOTO_REPLACE_VERSION)


def photo_back_replaceable():
    """Whether --back replaces the listing's back instead of adding one."""
    if not photo_replace_available():
        return False
    return version_at_least(plugin_version(), CS_PHOTO_BACK_VERSION)


def cs_addon_present():
    """Whether the optional CanadianShopper plugin is available and enabled.

    Legacy v2.20 installs remain usable; new installs are isolated under the
    per-user plugin folder managed by plugin_manager.py.
    """
    managed_dir = PLUGIN_MANAGER.root / CS_PLUGIN_ID
    if managed_dir.exists():
        try:
            return all(PLUGIN_MANAGER.resolve_action(action).is_file()
                       for action in CS_TOOL_ACTIONS.values())
        except PluginError:
            return False
    return ((BASE / "addon-canadianshopper.txt").is_file() and
            all((BASE / n).is_file() for n in CS_ADDON_TOOLS))

SETTINGS_FILE = BASE / "gui-settings.json"
LOG_FILE = BASE / "gui-log.txt"
CHECKLIST = BASE / "sold-cards-checklist.csv"
CS_COOKIE_FILE = BASE / "cookie.txt"
#  Which orders have already been turned into checklist rows. It is a
#  cache, not a record: the checklist and the ledger stay the truth,
#  and losing this file only means a preview shows older orders again.
SOLD_ORDERS_SEEN = BASE / sale_preview.SEEN_FILE
CS_HOME = "https://canadianshopper.ca"
_TOOL_DIALOG_START = "\x1eALEX_COLLECT_DIALOG:"
_TOOL_DIALOG_END = "\x1f"


def is_sale_comment(line):
    """Keep leading card numbers like #254; ignore ordinary # comments."""
    stripped = (line or "").lstrip()
    return stripped.startswith("#") and not re.match(r"^#\s*\d", stripped)


def typed_sale_title(text):
    """Return one typed title without the quantity/channel suffix, else None."""
    lines = [line.strip() for line in text.splitlines()
             if line.strip() and not is_sale_comment(line)]
    if len(lines) != 1:
        return None
    title = re.sub(r"\s+@(website|web|site|canadianshopper|cs|ebay|facebook|fb|inperson|person)$",
                   "", lines[0], flags=re.IGNORECASE).strip()
    title = re.sub(r",\s*(?:last|\d+)\s*$", "", title,
                   flags=re.IGNORECASE).strip()
    return title or None


def sale_followup_urls(title, sold_on, settings=None):
    """Seller pages for other channels, using the user's saved URLs."""
    settings = settings or load_settings()
    urls = []
    woo_orders = site_admin_url("wp-admin/admin.php?page=wc-orders", settings)
    if sold_on != "website" and woo_orders:
        urls.append(woo_orders)
    if sold_on != "ebay" and settings.get("ebay_selling_url"):
        urls.append(settings["ebay_selling_url"])
    if sold_on != "facebook" and settings.get("facebook_selling_url"):
        urls.append(settings["facebook_selling_url"])
    if (sold_on != "canadianshopper" and
            settings.get("canadianshopper_store_url")):
        urls.append(settings["canadianshopper_store_url"])
    return urls




# ---------------------------------------------------------------- settings
def load_settings():
    s = load_user_settings(SETTINGS_FILE)
    if not s.get("pipeline_dir"):
        s["pipeline_dir"] = str(WORK)
    # A stale saved folder (e.g. the folder moved) must not hide the pipeline.
    if not (Path(s["pipeline_dir"]) / "card_pipeline.py").exists() and \
            (WORK / "card_pipeline.py").exists():
        s["pipeline_dir"] = str(WORK)
    return s


def save_settings(s):
    try:
        SETTINGS_FILE.write_text(
            json.dumps(s, indent=2, sort_keys=True), encoding="utf-8")
    except Exception as e:
        log("could not save settings: %s" % e)


def log(line):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                   line))
    except Exception:
        pass


def open_path(path):
    """Open a file or folder in the desktop's own way. Never raises."""
    p = Path(path)
    try:
        if not p.exists():
            return False
        if sys.platform == "win32":
            os.startfile(str(p))                                # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True
    except Exception as e:
        log("open_path failed for %s: %s" % (p, e))
        return False


def first_existing(*paths):
    for p in paths:
        if Path(p).exists():
            return Path(p)
    return None


# ------------------------------------------------------------------- cookie
def load_cookie_text(explicit=None):
    """Cookie string from the given text/file, or from cookie.txt."""
    raw = None
    if explicit:
        raw = explicit
    elif CS_COOKIE_FILE.exists():
        raw = CS_COOKIE_FILE.read_text(encoding="utf-8", errors="replace")
    if not raw:
        return None
    return clean_cookie_row(raw)


def clean_cookie_row(raw):
    """Accept a DevTools cookie row/header or bare value, without plugin code."""
    text = str(raw or "").strip()
    if not text:
        return ""
    # A copied DevTools table row is Name<TAB>Value<TAB>Domain<TAB>...
    if "\t" in text:
        columns = [part.strip() for part in text.split("\t")]
        if len(columns) >= 2 and re.fullmatch(r"[A-Za-z0-9_.-]+", columns[0]) and columns[1]:
            text = "%s=%s" % (columns[0], columns[1])
    if "\n" in text or "\r" in text:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cookie_line = next((line.split(":", 1)[1].strip() for line in lines
                            if line.lower().startswith("cookie:")), None)
        text = cookie_line or next((line for line in lines
                                    if "=" in line or "session_token" in line),
                                   lines[0])
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    pairs = []
    for token in re.split(r"[;\s,]+", text):
        if "=" not in token:
            continue
        name, value = token.split("=", 1)
        name, value = name.strip(), value.strip()
        if re.fullmatch(r"[A-Za-z0-9_.-]+", name) and value:
            pairs.append("%s=%s" % (name, value))
    if pairs:
        session = next((item for item in pairs if "session_token" in item), None)
        return session or "; ".join(pairs)
    # A bare session-cookie value has no key in the DevTools paste.
    value = re.sub(r"[^A-Za-z0-9._~%+/-]", "", text)
    value = value.split("/", 1)[0]
    if len(value) >= 16 and ("." in value or "%2e" in value.lower()):
        return "__Secure-better-auth.session_token=" + value
    return text


def test_connection(cookie=None):
    """Return (ok, message). Read-only; never raises."""
    cookie = cookie or load_cookie_text()
    if not cookie:
        return False, ("No cookie saved yet. Paste it in the Connection "
                       "panel (it comes from your browser, DevTools -> "
                       "Application -> Cookies -> canadianshopper.ca).")
    try:
        req = urllib_request(
            CS_HOME + "/api/auth/get-session",
            headers={
                "User-Agent": "Mozilla/5.0 (AlexCollect-GUI)",
                "Cookie": cookie,
                "Accept": "application/json",
            })
        import json as _json
        body = _json.loads(req.read().decode("utf-8", "replace"))
    except Exception as e:
        return False, "Could not reach canadianshopper.ca: %s" % e
    if not body or body in ("null", "None") or body is None:
        return False, ("The site answered, but the cookie did not log in "
                       "(no session). Paste a fresh one: log in, DevTools -> "
                       "Application -> Cookies -> canadianshopper.ca -> the "
                       "row __Secure-better-auth.session_token.")
    who = ""
    try:
        who = body.get("user", {}).get("email") or body.get("user", {}).get(
            "id") or ""
    except Exception:
        pass
    return True, "Session OK%s. The tools can talk to CanadianShopper." % (
        " (" + str(who) + ")" if who else "")


def urllib_request(url, headers=None, timeout=15):
    import urllib.request
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=headers or {}), timeout=timeout)


# ------------------------------------------------------------------ prompts
#  The two AI commands that turn a 9-card sheet scan into the seven parsed
#  headers the card pipeline eats. Editable: the .txt files next to gui.py
#  win over these embedded copies.
PROMPT_FALLBACKS = {
    "multi": 'I am listing 9 single trading cards for {{STORE_NAME}}. I need high-conversion, SEO-friendly product listings based on images of 9-card sheets. Do not use bulleted lists or — in the output.\nI\'m uploading two images of the same 3x3 sheet of trading cards in a protective sleeve:\n1. FRONT of all 9 cards\n2. BACK of all 9 cards (same 9 cards, sheet flipped horizontally like a page)\n\nGRID NUMBERING (based on the FRONT image):\n[1][2][3]\n[4][5][6]\n[7][8][9]\n\nPosition 1 = top-left, reading left-to-right then top-to-bottom, like English text.\n\nMAPPING BACK IMAGE TO FRONT POSITIONS:\nBecause the sheet is flipped horizontally (like a page turn), each row stays in the same row, but the column order reverses:\n- Left column on BACK = Right column on FRONT\n- Middle column on BACK = Middle column on FRONT\n- Right column on BACK = Left column on FRONT\n\nSo: BACK position 1 → FRONT position 3, BACK position 2 → FRONT position 2, BACK position 3 → FRONT position 1, BACK position 4 → FRONT position 6, BACK position 5 → FRONT position 5, BACK position 6 → FRONT position 4, BACK position 7 → FRONT position 9, BACK position 8 → FRONT position 8, BACK position 9 → FRONT position 7.\n\nWAIT until both images are uploaded before responding.\n\nOnce both images are provided, output results in FRONT position order (1 through 9), using this format for each:\n\nPosition [X] [card details] \nSEO Image titles (must be unique):\n[Manufactures Card #]-[Player Name]-[Year(s)]-[Brand]-front-[grade]\n[Manufactures Card #]-[Player Name]-[Year(s)]-[Brand]-back-[grade]\n\nSEO Title: (Format: \n[Year] [Brand] [Player/Character Name] #[Card #] [Key Rookie/Insert Info] [Team/Series] [grade]) Product Description: ({{DESCRIPTION_MIN_WORDS}}+ words. Write a seamless, paragraph-only narrative with a hook intro, historical context, specific pop-culture or sporting achievements, and a \'Condition Report\' section detailing the exact corner wear, edge chipping, and centering seen in the photos. {{LISTING_CONTEXT}} Include a conservative grade estimate explanation). \n\nGrade Estimate: \n(Carefully analyse for creases, wrinkles and marks. Provide a conservative raw grade estimate based on photos e.g., EX-MT 6). Price \n\nRecommendation: \n(Single price rounded up to the nearest {{CURRENCY_NAME}} based on current market value of RAW grade). \n\nPrimary SEO Keyword: \n(Best high-volume search phrase, matching the title exactly and woven naturally into the description). \n\nWooCommerce Tag Bundle: \n(A comma-separated string of exactly {{TAG_COUNT}} relevant tags).\n\nSTRICT OUTPUT FORMAT — DO NOT DEVIATE: This output gets parsed automatically by a script, so the seven headers below must appear EXACTLY as written, character-for-character, every time, with no variation across cards or across responses:\n\nSEO Image titles: SEO Title: Product Description: Grade Estimate: Price Recommendation: Primary SEO Keyword: WooCommerce Tag Bundle:\n\nFollow these rules with no exceptions:\n\nUse these exact seven header strings, spelled and worded exactly as shown above. Never rename, reword, or paraphrase a header (for example, never write "Raw Grade Estimate:" instead of "Grade Estimate:", and never split "SEO Image titles:" into separate "Front SEO Image Title:" / "Back SEO Image Title:" headers).\nEach header goes on its own line, followed immediately by a colon and nothing else on that line — no parenthetical notes, no asides, no instructions repeated back (for example, never write "SEO Image titles (must be unique):").\nDo not bold, italicize, or otherwise wrap any header in markdown (no Grade Estimate:).\n"SEO Image titles:" is always followed by exactly two lines: the front filename, then the back filename, in that order, with no blank line between them and nothing else on those lines.\nThe "Condition Report" sentence inside the Product Description must begin with the literal words "Condition Report:" (with the colon) so it can be identified within the paragraph, but it stays embedded in the Product Description narrative as instructed above — do not give it its own top-level header.\nThe content under "Grade Estimate:" should lead with the short letter/number grade itself (e.g. "EX 5" or "VG-EX 4") before any explanatory sentence, so the grade is the very first thing after the header.\nThe content under "Price Recommendation:" should be a single price only, formatted as "{{CURRENCY_PREFIX}}" followed by a whole number (e.g. "{{CURRENCY_PREFIX}}9"), with no extra words.\nDo not insert any other headers, section titles, or labels anywhere in the output beyond the seven listed above.',
    "single": 'I am listing 9 single trading cards for {{STORE_NAME}}. I need high-conversion, SEO-friendly product listings based on images of 9-card sheets. Do not use bulleted lists or — in the output.\nI\'m uploading two images of the same 3x3 sheet of trading cards in a protective sleeve:\n1. FRONT of all 9 cards\n2. BACK of all 9 cards (same 9 cards, sheet flipped horizontally like a page)\n\nGRID NUMBERING (based on the FRONT image):\n[1][2][3]\n[4][5][6]\n[7][8][9]\n\nPosition 1 = top-left, reading left-to-right then top-to-bottom, like English text.\n\nMAPPING BACK IMAGE TO FRONT POSITIONS:\nBecause the sheet is flipped horizontally (like a page turn), each row stays in the same row, but the column order reverses:\n- Left column on BACK = Right column on FRONT\n- Middle column on BACK = Middle column on FRONT\n- Right column on BACK = Left column on FRONT\n\nSo: BACK position 1 → FRONT position 3, BACK position 2 → FRONT position 2, BACK position 3 → FRONT position 1, BACK position 4 → FRONT position 6, BACK position 5 → FRONT position 5, BACK position 6 → FRONT position 4, BACK position 7 → FRONT position 9, BACK position 8 → FRONT position 8, BACK position 9 → FRONT position 7.\n\nWAIT until both images are uploaded before responding.\n\nOnce both images are provided, output results in FRONT position order (1 through 9), using this format for each:\n\nPosition [X] [card details] \nSEO Image titles: \n[Manufactures Card #]-[Player/Character Name]-[Year(s)]-[Brand]-front \n[Manufactures Card #]-[Player/Character Name]-[Year(s)]-[Brand]-back\n \nSEO Title: (Format: \n[Year] [Brand] [Player/Character Name] #[Card #] [Key Rookie/Insert Info] [Team/Series]) Product Description: ({{DESCRIPTION_MIN_WORDS}}+ words. Write a seamless, paragraph-only narrative with a hook intro, historical context, specific pop-culture or sporting achievements, and a \'Condition Report\' section detailing the exact corner wear, edge chipping, and centering seen in the photos. {{LISTING_CONTEXT}} Include a conservative grade estimate explanation). \n\nGrade Estimate: \n(Carefully analyse for creases, wrinkles and marks. Provide a conservative raw grade estimate based on photos e.g., EX-MT 6). Price \n\nRecommendation: \n(Single price rounded up to the nearest {{CURRENCY_NAME}} based on current market value of RAW grade). \n\nPrimary SEO Keyword: \n(Best high-volume search phrase, matching the title exactly and woven naturally into the description). \n\nWooCommerce Tag Bundle: \n(A comma-separated string of exactly {{TAG_COUNT}} relevant tags).\n\nSTRICT OUTPUT FORMAT — DO NOT DEVIATE: This output gets parsed automatically by a script, so the seven headers below must appear EXACTLY as written, character-for-character, every time, with no variation across cards or across responses:\n\nSEO Image titles: SEO Title: Product Description: Grade Estimate: Price Recommendation: Primary SEO Keyword: WooCommerce Tag Bundle:\n\nFollow these rules with no exceptions:\n\nUse these exact seven header strings, spelled and worded exactly as shown above. Never rename, reword, or paraphrase a header (for example, never write "Raw Grade Estimate:" instead of "Grade Estimate:", and never split "SEO Image titles:" into separate "Front SEO Image Title:" / "Back SEO Image Title:" headers).\nEach header goes on its own line, followed immediately by a colon and nothing else on that line — no parenthetical notes, no asides, no instructions repeated back (for example, never write "SEO Image titles (must be unique):").\nDo not bold, italicize, or otherwise wrap any header in markdown (no Grade Estimate:).\n"SEO Image titles:" is always followed by exactly two lines: the front filename, then the back filename, in that order, with no blank line between them and nothing else on those lines.\nThe "Condition Report" sentence inside the Product Description must begin with the literal words "Condition Report:" (with the colon) so it can be identified within the paragraph, but it stays embedded in the Product Description narrative as instructed above — do not give it its own top-level header.\nThe content under "Grade Estimate:" should lead with the short letter/number grade itself (e.g. "EX 5" or "VG-EX 4") before any explanatory sentence, so the grade is the very first thing after the header.\nThe content under "Price Recommendation:" should be a single price only, formatted as "{{CURRENCY_PREFIX}}" followed by a whole number (e.g. "{{CURRENCY_PREFIX}}9"), with no extra words.\nDo not insert any other headers, section titles, or labels anywhere in the output beyond the seven listed above.',
}
PROMPT_FILES = {
    "multi": "card description command - with grade.txt",
    "single": "card description command.txt",
}
PROMPT_TITLES = {
    "multi": "Add grades to titles",
    "single": "No grades in titles",
}
PROMPT_TOOLTIPS = {
    "multi": ("If products on this sheet have multiple grades, this command "
              "adds each card's grade to the end of its title."),
    "single": ("If this is one product or the copies share one grade, this "
               "command leaves the grade out of the product title."),
}


def custom_ai_commands(settings=None):
    """Return sanitized custom commands with stable button IDs."""
    settings = load_settings() if settings is None else settings
    raw = settings.get("custom_ai_commands", [])
    if not isinstance(raw, list):
        return []
    commands = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        prompt = str(item.get("prompt", "")).strip()
        if not name or not prompt:
            continue
        commands.append({
            "id": str(item.get("id") or ("legacy-%d" % index)),
            "name": name,
            "tooltip": str(item.get("tooltip", "")).strip() or
                       "Custom AI command. Copies this command to the clipboard.",
            "prompt": prompt,
        })
    return commands


def ai_prompt_buttons(settings=None):
    """(id, label, hover-help) for the default and user-created commands."""
    settings = load_settings() if settings is None else settings
    choices = [(kind, PROMPT_TITLES[kind], PROMPT_TOOLTIPS[kind])
               for kind in ("multi", "single")]
    choices.extend(("custom_" + item["id"], item["name"], item["tooltip"])
                   for item in custom_ai_commands(settings))
    return choices


def _render_prompt(text, settings):
    store_name = str(settings.get("store_name", "")).strip() or "my online store"
    currency_prefix = str(settings.get("currency_prefix", "C$")).strip() or "$"
    currency_name = str(settings.get("currency_name", "Canadian dollars")).strip() or "your currency"
    description_words = str(settings.get("description_min_words", 400))
    tag_count = str(settings.get("tag_count", 8))
    listing_context = str(settings.get("listing_context", "")).strip()
    return (text.replace("{{STORE_NAME}}", store_name)
             .replace("{{CURRENCY_PREFIX}}", currency_prefix)
             .replace("{{CURRENCY_NAME}}", currency_name)
             .replace("{{DESCRIPTION_MIN_WORDS}}", description_words)
             .replace("{{TAG_COUNT}}", tag_count)
             .replace("{{LISTING_CONTEXT}}", listing_context))


def load_prompt(kind, settings=None):
    settings = load_settings() if settings is None else settings
    if kind.startswith("custom_"):
        custom_id = kind[len("custom_"):]
        for item in custom_ai_commands(settings):
            if item["id"] == custom_id:
                return _render_prompt(item["prompt"], settings)
        raise KeyError("Custom AI command is no longer available: %s" % kind)
    if kind not in PROMPT_FILES:
        raise KeyError("Unknown AI command: %s" % kind)
    p = BASE / PROMPT_FILES[kind]
    try:
        text = p.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
        if not text:
            text = PROMPT_FALLBACKS[kind]
    except Exception:
        text = PROMPT_FALLBACKS[kind]
    return _render_prompt(text, settings)


def classify_clipboard(text, settings=None):
    """(kind, verdict) for whatever the clipboard holds:
    short / prompt / answer / other."""
    t = (text or "").strip()
    if not t:
        return "short", "clipboard is empty"
    settings = load_settings() if settings is None else settings
    for kind, _label, _tip in ai_prompt_buttons(settings):
        prompt = load_prompt(kind, settings)
        if prompt and t.startswith(prompt[:min(60, len(prompt))]):
            return "prompt", "still the PROMPT you copied for the AI chat"
    if len(t) < 200:
        return "short", "too short to be the full answer"
    if t.startswith("SEO Image titles") or "Grade Estimate:" in t:
        return "answer", "looks like the AI's answer"
    return "other", "some other text"


def to_clipboard(app, text):
    """Best-effort clipboard copy; returns True when it stuck."""
    try:
        app.clipboard_clear()
        app.clipboard_append(text)
        app.update_idletasks()
        app.update()
        return True
    except Exception as e:
        log("clipboard failed: %s" % e)
        return False


PIPELINE_PROMPT_HINTS = [
    ("Are the products created and published on the website?",
     "The pipeline asks whether the new cards are already PUBLISHED on "
     "your website - whether the app created them or you imported the CSV. "
     "'y' + Send continues to the Facebook files (they only include "
     "published products); 'n' or an empty Send stops here - the Woo + "
     "CanadianShopper CSVs are already written, nothing is lost. "
     "If the cards are still drafts: publish them on the website, then use "
     "the Facebook feed updater button afterwards."),
    ("product(s) on",
     "The products are about to be created on your website with the saved "
     "WooCommerce keys. 'y' + Send creates them as drafts (photos uploaded "
     "first, every product read back); 'n' or an empty Send leaves the "
     "website untouched and keeps the CSV. Nothing is ever deleted - a "
     "card whose SKU is already there is skipped."),
    ("Put the ones whose photos upload on sale",
     "'y' puts each product on sale once its front/back photos are on the "
     "site; a product whose photos did not upload stays a draft and the "
     "report says why. 'n' or an empty Send leaves them all as drafts, "
     "which you can publish any time from the website."),
    ("Create these listings as drafts",
     "The CanadianShopper plugin has staged the CSVs with the square front + "
     "back photos and is offering to send them to CanadianShopper's import "
     "service. 'y' + Send creates the listings as UNPUBLISHED DRAFTS - it "
     "never publishes anything and never changes an existing listing, and a "
     "title already on your vendor account is skipped. 'n' or an empty Send "
     "leaves the CSVs in cs-ready to import by hand. This is a different "
     "question from the one about creating products on your own website."),
    ("pick a category",
     "The pipeline detected categories - type the number(s) it shows and "
     "press Send."),
    ("Press Enter to generate Excel",
     "Press Send Enter (or Send with an empty box) to write the "
     "Marketplace delta xlsx; typing anything else cancels."),
    ("No facebook_history.xlsx found",
     "This is the first run on this computer. The updater matches the "
     "newest Woo import CSV in the pipeline folder to the live feed: "
     "only those batch cards go in the delta, while the full live feed "
     "becomes the history. Check the CSV name and match count in the "
     "preview before pressing Enter."),
    ("Facebook feed script exited with code",
     "The feed helper failed; scroll up in this console for its traceback. "
     "The app now launches nested feed tools with the console-enabled "
     "python.exe so the underlying error is visible."),
    ("Safe first-run bootstrap stopped",
     "The updater could not safely match every row in the newest Woo CSV "
     "to a live feed product. It deliberately wrote neither history nor "
     "delta, to avoid losing cards from a future delta. Confirm all batch "
     "products are published and the latest Woo CSV is in the pipeline "
     "folder; then retry."),
    ("quantities correct?",
     "The pipeline is confirming the stock quantities read from the "
     "listing text. Send Enter accepts (Y); type n and Send if you want "
     "to edit one - it asks for a card number."),
    ("Drafts: v = view",
     "Type v and Send for a read-only ready/blocked draft preview; the "
     "choices return afterwards. Type y and Send to publish ready drafts, "
     "then type PUBLISH at the publisher's confirmation. Type n (or send an "
     "empty reply) to skip draft review. Photo wiring continues without an "
     "extra Enter prompt."),
    ("photo stage not installed",
     "The CanadianShopper CSV was still written and can be imported by "
     "hand - only the automatic photo staging was skipped. Install the "
     "stage from the Add-ons panel ('Install the shipped CanadianShopper "
     "add-on'), then re-run the listing; the cookie saved in this app is "
     "picked up automatically."),
]


def _prompt_hint_for(text):
    """A human hint for a known tool question, or None."""
    for needle, hint in PIPELINE_PROMPT_HINTS:
        if needle in text:
            return hint
    return None


#  The CanadianShopper plugin runs its publisher as its own process, so the
#  publisher's "type PUBLISH" question can be swallowed and the run simply
#  stops moving. Nobody can answer a question they cannot see, so the app
#  says what to type after this long with no output at all.
PUBLISHER_WAIT_SECONDS = 20
PUBLISHER_WAIT_MARKER = "Publishing ready CanadianShopper drafts"
PUBLISHER_WAIT_NOTE = (
    "The plugin's publisher is running and has printed nothing since. This "
    "plugin is older than 1.0.27, which is the version that keeps the "
    "publisher's question visible: in this one it waits for the word PUBLISH "
    "without showing its prompt. Type PUBLISH in the answer box below and "
    "press Send, then update the plugin. If nothing happens after that, "
    "press Stop and use the card-pipeline panel's \"Publish ready drafts\" "
    "button - it is the same publisher, run so its prompt is always visible.")
PUBLISHER_WAIT_NOTE_STREAMED = (
    "The plugin's publisher has printed nothing for a while. Plugin 1.0.27 "
    "and later keep its question on screen, so this is the wait itself - "
    "reading your draft listings and checking each one - not a question "
    "nobody can see. Give it a little longer; if it never moves, press Stop "
    "and use the card-pipeline panel's \"Publish ready drafts\" button, "
    "which runs the same publisher on its own.")


def publisher_wait_note(text, version=""):
    """The note to show when a run has gone quiet at the publisher, or "".

    What the sentence may claim depends on the plugin: 1.0.27 streams the
    publisher, so silence there means work rather than a hidden question.
    """
    if PUBLISHER_WAIT_MARKER not in (text or ""):
        return ""
    if version and version_at_least(version, CS_NESTED_STREAM_VERSION):
        return PUBLISHER_WAIT_NOTE_STREAMED
    return PUBLISHER_WAIT_NOTE


MARKET_RERUNS = {
    "woocommerce": (
        "WooCommerce CSV",
        "Rebuild woocommerce_import_<time>.csv from the AI text already on "
        "disk, and create the products on the website if you ask for it. "
        "Images are not moved or renamed."),
    "canadianshopper": (
        "CanadianShopper CSV",
        "Rebuild the CanadianShopper import CSV (and let the plugin stage "
        "the photos) without repeating the AI or image steps."),
    "facebook": (
        "Facebook feed + xlsx",
        "Refresh the live feed and write the Marketplace delta xlsx. No CSV "
        "or images are rebuilt."),
    "ebay": (
        "eBay Quick List",
        "Rebuild the eBay Quick List page from the same AI text."),
}

RERUN_NEEDS_CARDS = ("woocommerce", "canadianshopper", "ebay")


def newest_ai_text(app, script=None):
    """The newest AI listing reply a re-run can reuse, or None."""
    script = script if script is not None else find_pipeline_script(
        app.settings)
    folders = []
    if script is not None:
        folders.append(script.parent)
    try:
        folders.append(Path(app.settings.get("pipeline_dir") or WORK))
    except Exception:
        pass
    seen, found = set(), []
    for folder in folders:
        try:
            candidates = [folder / "_card_input.txt"]
            candidates += sorted(folder.glob("*_card_input*.txt"),
                                 key=lambda p: _safe_mtime(p), reverse=True)
        except OSError:
            continue
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            try:
                if path.is_file() and path.stat().st_size:
                    found.append(path)
            except OSError:
                continue
    return found[0] if found else None


def _safe_mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def find_pipeline_script(settings):
    """Where card_pipeline.py lives: saved batch folder, the app's own
    pipeline folder, next to the tools folder (the Scan folder), or next
    to the tools."""
    for cand in (Path(settings.get("pipeline_dir", "")) / "card_pipeline.py",
                 BASE / "pipeline" / "card_pipeline.py",
                 WORK / "card_pipeline.py",
                 BASE.parent / "card_pipeline.py"):
        try:
            if cand.is_file():
                return cand
        except Exception:
            pass
    return None


def tool_env():
    """The environment every tool this app starts is given.

    A plugin tool that runs its own children must stream them rather than
    capture their output: this console is where the person reads the question
    they are expected to answer. Plugin 1.0.27 and later read
    ``ALEX_COLLECT_NESTED`` and add progress around each child; older ones
    ignore it, so it is safe to set for every tool.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["ALEX_COLLECT_NESTED"] = "1"
    return env


# ------------------------------------------------------------------ runner
class Runner:
    """Runs ONE tool at a time, streams its output into the console,
    and can feed it keyboard answers (the cookie prompt, [Y/n] questions)."""

    def __init__(self, app):
        self.app = app
        self.proc = None
        self.q = queue.Queue()
        self.title = ""
        self.cmd = ""
        self.on_done = None
        self._dialog_buffer = ""
        #  What the running tool printed, so a step that has to act on the
        #  tool's own words ("Drafts found: 0") can read them instead of
        #  guessing from a file whose format the core does not own.
        self.output = ""
        #  Watched so a run that stops at the plugin's hidden PUBLISH question
        #  is explained instead of looking hung.
        self._publish_watch = None
        self._publish_note_shown = False

    def busy(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, script, args, cwd, title, on_done=None, confirm=None):
        if self.busy():
            messagebox.showwarning(
                "Already running",
                "\"%s\" is still running.\nOne thing at a time: each step "
                "writes the files the next step reads." % self.title)
            return False
        if confirm and not messagebox.askyesno(title, confirm):
            log("user declined: %s" % title)
            return False
        cmd = [sys.executable, "-u", str(script)] + [str(a) for a in args]
        env = tool_env()
        self.cmd = " ".join(cmd)
        self.title = title
        self.on_done = on_done
        self._dialog_buffer = ""
        self.output = ""
        self._publish_watch = None
        self._publish_note_shown = False
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=str(cwd), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=env, **no_window_kwargs())
        except Exception as e:
            messagebox.showerror("Could not start", "%s\n\n%s" % (title, e))
            return False
        log("START %s | %s" % (title, self.cmd))
        threading.Thread(target=self._pump, daemon=True).start()
        self.app.on_run_start(title, self.cmd)
        return True

    def _pump(self):
        # byte-level reads: a tool that asks "pick a category [1/2/3]: "
        # without pressing Enter must STILL show up in the console
        import os as _os
        p = self.proc
        try:
            fd = p.stdout.fileno()
            while True:
                data = _os.read(fd, 4096)
                if not data:
                    break
                self.q.put(("out", data.decode("utf-8", "replace")))
        except Exception:
            pass
        rc = p.wait()
        self.q.put(("exit", rc))

    def send(self, text):
        if self.busy():
            try:
                self.proc.stdin.write((text + "\n").encode("utf-8"))
                self.proc.stdin.flush()
                log("sent to tool: %s" % text)
            except Exception as e:
                log("send failed: %s" % e)

    def stop(self):
        if self.busy():
            try:
                self.proc.terminate()
                log("user stopped: %s" % self.title)
            except Exception:
                pass

    def _consume_dialog_protocol(self, chunk):
        """Hide structured tool requests and answer them with real Tk dialogs."""
        text = self._dialog_buffer + chunk
        self._dialog_buffer = ""
        shown = []
        start = _TOOL_DIALOG_START
        end = _TOOL_DIALOG_END
        while text:
            pos = text.find(start)
            if pos < 0:
                # Hold only a possible partial marker; stream all other text,
                # including tools' bare prompts, immediately.
                keep = 0
                for n in range(1, min(len(start), len(text) + 1)):
                    if text.endswith(start[:n]):
                        keep = n
                if keep:
                    shown.append(text[:-keep])
                    self._dialog_buffer = text[-keep:]
                else:
                    shown.append(text)
                break
            shown.append(text[:pos])
            end_pos = text.find(end, pos + len(start))
            if end_pos < 0:
                self._dialog_buffer = text[pos:]
                break
            body = text[pos + len(start):end_pos]
            try:
                request = json.loads(body)
                answer = self.app.handle_tool_dialog(request)
                self.send(json.dumps(answer, ensure_ascii=False,
                                     separators=(",", ":")))
            except Exception as exc:
                log("tool dialog protocol failed: %s" % exc)
                self.send("{}")
            text = text[end_pos + len(end):]
        return "".join(shown)

    def _watch_publisher(self):
        """Notice a run that stops at the plugin's invisible PUBLISH prompt.

        The marker is the plugin's own line, printed just before it starts the
        publisher; if nothing at all follows it, the answer box is the only
        thing standing between the person and a window that looks frozen.
        """
        if self._publish_note_shown or not publisher_wait_note(self.output):
            return
        length = len(self.output)
        if self._publish_watch and self._publish_watch[0] == length:
            return
        self._publish_watch = (length, self.app.after(
            PUBLISHER_WAIT_SECONDS * 1000, self._publish_still_waiting))

    def _publish_still_waiting(self):
        """After the wait: say what to type, if the run really went quiet."""
        if self._publish_note_shown or not self.busy():
            return
        if not self._publish_watch \
                or len(self.output) != self._publish_watch[0]:
            return
        self._publish_note_shown = True
        try:
            self.app.console_line(
                "NOTE: " + publisher_wait_note(self.output, plugin_version()),
                "dim")
            self.app.status.config(
                text="Waiting for the word PUBLISH - type it below and press "
                     "Send (or Stop the run).")
        except Exception:
            pass          # the window went away while the timer was waiting

    def drain(self):
        """Called from the Tk loop; moves queued output into the console."""
        got = False
        while True:
            try:
                kind, payload = self.q.get_nowait()
            except queue.Empty:
                break
            got = True
            if kind == "out":
                if len(self.output) < 400000:
                    self.output += payload
                shown = self._consume_dialog_protocol(payload)
                if shown:
                    self.app.console_write(shown)
                    self._watch_publisher()
                    hint = _prompt_hint_for(shown)
                    if hint and hint not in self.app._hinted:
                        self.app._hinted.add(hint)
                        self.app.console_line("NOTE: " + hint, "dim")
                        self.app.status.config(
                            text="The tool asked a question - see the note "
                                 "above the answer box.")
                    if not shown.endswith("\n"):
                        self.app._saw_dangling_prompt = True
                        if self.busy():
                            self.app.status.config(
                                text=self.app.runner.title +
                                " is waiting for your answer - type it below "
                                "and press Send")
                            try:
                                self.app.inp.focus_set()
                            except Exception:
                                pass
            else:  # exit
                if self._dialog_buffer:
                    self.app.console_write(self._dialog_buffer)
                    self._dialog_buffer = ""
                self.app.on_run_end(self.title, payload)
                cb, self.on_done = self.on_done, None
                if cb:
                    cb(payload)
        return got


# -------------------------------------------------------------------- docs
DOCS = {}

DOCS["welcome"] = """\
You sell each card in up to FOUR places: your own website
your store, CanadianShopper, eBay and Facebook Marketplace.
Whichever one sells, the others keep offering it - so after every sale
the other listings have to be fixed, and after every new scan the
photos have to be updated everywhere.

This window is the control panel for all of it. Every button runs the
same tested tool that the .bat launchers run - nothing is reinvented.
Two safety rules, everywhere:

  * PREVIEW FIRST. Steps that change anything show you what they are
    about to do and ask before they do it.
  * ONE THING AT A TIME. The console at the bottom always shows which
    tool is running and exactly what it printed."""

DOCS["cookie"] = """\
This is the central place for your store connection, AI page, preferred browser,
marketplace pages, Facebook workbook fields/templates, listing prompt preferences,
marketplace defaults, and working folders. Save changes here; URLs and folder
paths are used across the GUI and command-line tools. If no browser is saved,
Alex Collect asks the first time it needs to open a webpage.

WooCommerce REST API credentials stay in the private, git-ignored
woo-keys.txt file. The CanadianShopper session cookie (if its plugin is
installed) is a live login; do not share it, and refresh it when the plugin
reports that authentication has expired."""

DOCS["folders"] = """\
Two folders the tools should know about:

* Batch folder - where card_pipeline.py and generated CSVs live. It is
  detected beside the tools by default; change it if your files are elsewhere.

* Scan folder - where your scanner drops files. Choose it here; the
  photo-replacement tool opens it when you replace a card's photos."""

DOCS["pipeline"] = """\
Use this for a new batch of cards. Choose the FRONT scan and, if you have
one, the BACK scan. The saved AI chat page opens in your selected browser
(or Alex Collect asks you to choose a browser the first time). Select one of
the available AI command buttons (two built-in options plus any custom
commands you added in User Settings); it is copied to the clipboard. Upload
the scans and paste the command into the AI page manually.
When you copy the complete AI reply, the app detects it and asks whether to
split and build or split only. Alex Collect matches descriptions to images
and prepares the import files and photos in your batch folder. File
preparation does not upload or publish anything. With the CanadianShopper
plugin enabled, confirm the draft import, then use the pipeline console:
v previews drafts without changes and returns to the choices, y publishes
ready drafts after you type PUBLISH, and n (or Enter) skips draft review.
Photo wiring continues without another Enter prompt. The same Preview drafts
and Publish ready drafts controls are below and in Import / publish drafts.
After products are published, the workflow can refresh your Facebook feed."""

DOCS["combine"] = """\
card_pipeline writes up to 500 cards per CSV, and the CanadianShopper
importer refuses bigger files. If several batches have piled up, this
merges them into import-sized files (500 rows / 2 MB each), skipping
titles that are already in an earlier file, so you never import the
same card twice. The originals are kept."""

DOCS["stage"] = """\
The importer can only set ONE photo per card and cannot create the
back-photo gallery row. So before importing, this step:

  1. squares every front photo (the site crops anything else),
  2. uploads fronts AND backs to CanadianShopper's own file store,
  3. rewrites the current batch into pipeline\\canadianshopper_products\\cs-ready\\ with hosted URLs,
     plus back-map.json so the backs can be attached after the import.
Older staged batches are consolidated into a history file after the next successful stage.

It needs the session cookie (Connection panel). It re-uses every image
it has already uploaded - image-cache.json - so a re-run uploads
nothing new."""

DOCS["importpanel"] = """\
Import the staged CSV on CanadianShopper, then manage draft activation here
inside Alex Collect - no bookmarklet is required for publishing:

  1. Open CanadianShopper (button below) and log in.
  2. Vendor dashboard -> Products -> upload / import the CSV.
     (A listing made from the stock panel writes the same file and can
     import it as drafts itself, when the plugin supports it.)
  3. Use the newest file from the cs-ready folder - the name starts
     with canadianshopper_import_ and ends _01_of_NN.csv.
  4. Choose Preview drafts. It lists ready and blocked drafts and writes
     a report without changing any products.
  5. Choose Publish ready drafts, accept the app's confirmation, then type
     PUBLISH in the output console to activate every ready draft. Blocked
     drafts remain drafts; use the report's edit links to fix them.

The running card pipeline offers the same actions after its draft import:
v = preview, y = publish ready drafts, n = skip. Its photo wiring continues
without a separate Enter prompt. For a manual import, press "Wire the photos"
to attach the hosted front and back."""

DOCS["wire"] = """\
After the import, this step attaches what the importer could not:
it points every new listing's main photo at the hosted square front
and adds the back photo as a gallery row behind it, using the
back-map.json from the staging step.

Always Dry-run first: the report (cs-image-report.csv) marks every
card ok / skip / unmatched / no-back, and nothing is changed. When the
dry run looks right, press Wire for real."""

DOCS["rerun"] = """\
CanadianShopper plugin repair. If a fresh CSV import has replaced photos,
this re-points listings covered by the hosted-image cache at their square
front and back gallery URLs. It uses the cached URLs directly: no WooCommerce
export is needed and no images are downloaded or uploaded. Run Dry-run first,
then review the report before applying the changes."""

DOCS["sold"] = """\
A card sold. Choose where it sold; the checklist covers the other places the
card is advertised. CanadianShopper is one of the source choices. Your cards
often exist as several copies, so enter the quantity sold—or mark the last
copy—to get the right follow-up (reduce quantity versus end the listing).

The checklist is the reminder for manual follow-ups. For one typed card, the
remaining seller pages open in your selected browser; the CanadianShopper store
search, eBay and Facebook still need the title pasted into their search fields.
The title is copied for you. Without the CanadianShopper plugin, its stock task stays manual.
When the plugin is enabled, a separate checkbox lets you preview and approve a
stock update; it is independent of the sale-source choice."""

DOCS["checklist"] = """\
The checklist (tools\\sold-cards-checklist.csv) is the memory of what
still needs doing. Every sale adds one row per channel that still
advertises the card. Tick a row off here (or put an x in the done
column in Notepad/Excel) and it stops nagging you - and every tool
run, including the .bat launchers, prints what is still outstanding
until you do."""

DOCS["zerostock"] = """\
Sweep on the CanadianShopper side: every listing already sitting at
quantity 0 gets archived (reversible - it can be reactivated later).
Useful after you sold the last copies in person. Preview shows the
list first; nothing is archived without the second click."""

DOCS["stock"] = """\
Where the numbers disagree, and where they get put right. One card can sit on
four sites; when one of them sells it, the others keep offering it until
somebody changes them. This panel reads a catalogue - your website through its
REST API keys, and CanadianShopper, eBay or Facebook through a signed-in
session - matches the cards, and lists ONLY the ones that need something done:
a count that differs, or a card that exists on one side only.

The list is the work, not a report. The website is right far more often than
not, so the first button sets every differing CanadianShopper count to the
website's count - and it always shows the exact changes and asks before writing
anything. Select rows to fix or ignore just those, and when the website is the
wrong side, select the card and open its product page: the app's keys can only
read, so the website is changed on the website's own screen. A card that is no
longer sold on the other site is ignored, which stops it being compared again
until it is restored.

A listing that exists but is not on sale - a draft, hidden, archived or out of
stock - gets its own row, because a stock count cannot fix it and stock.set
only touches listings that are on sale. When one of them is a draft, publishing
is offered; anything else is a vendor-dashboard job.

A card that exists on the website and no longer on CanadianShopper is the one
that can be put back rather than corrected: the listing buttons write the
CanadianShopper import file from the website product itself - its title, price,
photo URL and stock count - in the same fourteen columns and with the same
filename as a batch from the pipeline. Nothing appears on CanadianShopper until
that file is imported, which the panel offers to do itself when the plugin can.
It arrives as an unpublished draft, and the same run then offers to publish it:
the publisher scans every draft, activates only the ones that pass all the
readiness checks, and still asks for PUBLISH to be typed.

A pair is only made when a shared SKU or the title identifies the same card - a
wrong pair would accuse a card that is fine - and an unpaired card is never
called wrong, only "on one side"."""

DOCS["square"] = """\
Square up a photo (or a whole folder) by padding it onto a white
square - for the occasional card you upload by hand through the
dashboard instead of through a batch. The square copy is written next
to the original; the original is never touched. No cookie needed."""

DOCS["ordertext"] = """\
A customer texts you a list of cards. Paste it here and Alex Collect
creates the order on your website, with each line matched to a real
product.

One card per line, in either order - "1970-71 O-Pee-Chee Paul Henderson
#217" or "#217 Paul Henderson 1970-71 O-Pee-Chee". Numbering ("1."),
bullets, quotes, bracketed notes and a trailing price are ignored. A
line that starts with a card number is a card, not a comment; a line
that starts with a hash and a space ("# a note") is a comment.

A line repeated word for word becomes one row of quantity 2. The same
card listed at two different grades stays two rows, because those are
two different cards.

You are asked whether to start a new order or add to an existing one
(enter its order number). A line Alex Collect is not sure about opens a
search where you pick the card - nothing is guessed. Leave the discount
box empty for full price, or type a percentage to put one discount line
on the order.

The order is created as PENDING: nothing is charged and no email is
sent. Open it in the dashboard to check it and take payment.

Without website API keys the order list opens instead, and the pasted
list is copied to the clipboard so you can paste it there.
"""

DOCS["newphotos"] = """\
One card needs better photos (a rescan, a condition change, a cracked
slab). Type its name or SKU and press Find.

* With your website API keys saved, the card is looked up and its
  product edit page opens straight away. Without them you get the
  product list filtered to what you typed - and the app offers to set
  the keys up, which makes this a one-click job next time.
* Choose the folder holding the replacement images and it opens for you.
* If the replacements are a 9-card sheet, the split step cuts it into
  the nine front (and optional back) images.
* The CanadianShopper store, eBay active listings, and Facebook selling
  pages open too, so every marketplace is one tab away.

With the CanadianShopper plugin installed you can also re-wire the
gallery photos. Two separate offers: "Wire this card's photos?" touches
only the one listing, matched by its full title, and writes nothing
unless exactly one staged row and one listing match - it needs plugin
1.0.14 or newer. "Wire the whole staged batch?" is the broader job from
the Wire the photos panel and is not limited to this card. Without the
plugin the pages still open and the photo upload stays manual."""

DOCS["markets"] = """\
Redo ONE marketplace without repeating the AI, split, or image steps.
Each button rebuilds only its own output and leaves every other file
alone - the renamed images are never moved or renamed again.

* WooCommerce CSV - rebuilds woocommerce_import_<time>.csv from the AI
  reply already saved on your PC.
* CanadianShopper CSV - rebuilds the CanadianShopper import CSV; when the
  plugin is installed it also stages the square front and back photos.
* Facebook feed + xlsx - asks the publish question again, refreshes the
  live feed, and writes the Marketplace delta xlsx. No CSV or image work.
* eBay Quick List - rebuilds the Quick List page for the same cards.

The panel checks for the AI text (the newest _card_input.txt the app
wrote beside card_pipeline.py). Use "Choose a different AI text..." to
point at another reply; if none is found the button asks for the file
before it starts. Only the marketplace you choose is rewritten, so a
mistyped answer at one step no longer means re-running the whole batch."""

DOCS_CORE = {
    "cookie": """\
Set your store URL, marketplace page links, AI page URL, store name, batch
folder, and scanner folder here. The scanner folder is where replacement
photos land. WooCommerce credentials stay in the
private woo-keys.txt file. CanadianShopper connection controls appear when its
optional plugin is installed.""",
    "pipeline": """\
Use this for a new batch of cards. Alex Collect remembers and opens your AI
chat page URL. Choose the matching prompt, upload the FRONT and optional
BACK scans, and paste the prompt manually. When you copy the full AI reply, the app detects
it and asks whether to split and build or split only. Alex Collect matches
descriptions to images and prepares import files and the Facebook feed in your
batch folder. Review them and import manually; nothing is published
automatically. Without the plugin, photo staging and back-photo wiring remain
manual.""",
    "importpanel": """\
Now the actual import happens on the website - the one step that always
runs behind your login in the browser (with or without the add-on):

  1. Open CanadianShopper (button below) and log in.
  2. Vendor dashboard -> Products -> upload / import the CSV.
     (A listing made from the stock panel writes the same file and can
     import it as drafts itself, when the plugin supports it.)
  3. Use the newest file from the cs-ready folder or your batch folder.
  4. Keep each file under 500 rows (that is what Combine ensures).
  5. When the import shows the products, publish them.

Photo staging and the back-photo wiring are the CanadianShopper
add-on's job - without it, square photos by hand with SquareImages.""",
    "sold": """\
A card sold. Choose where it sold; the checklist covers every other place the
card is advertised. Your cards can exist as several copies, so enter the
quantity sold—or mark the last copy—to get the right follow-up. For one typed
card, remaining seller pages open in Edge; the CanadianShopper store-search,
eBay and Facebook searches are manual (the title is copied for pasting).
Without the CanadianShopper plugin, its stock update stays a manual checklist task.""",
}

DOCS["logs"] = """\
Everything the GUI and the tools print is kept so a crash is never a
mystery: gui-log.txt (this window's runs), sold-cards-report.csv
(every stock change: before/after, order numbers), and the
image-sync reports from the staging/wiring runs."""


def console_lines_for(screen_height):
    """How many lines of output the window can spare.

    The console is a fixed number of lines of text, so on a small screen it
    used to take half the window and leave the page above it with almost
    nothing. It keeps its size on a big screen and gives room back on a small
    one - the console scrolls, the page needs the space.
    """
    return 8 if screen_height < 800 else (12 if screen_height < 1000 else 16)


def theme_background(widget):
    """The window colour the current ttk theme paints, so nothing is white."""
    try:
        style = ttk.Style(widget)
        for name in ("TFrame", "Frame", "TLabel"):
            colour = style.lookup(name, "background")
            if colour:
                return colour
    except Exception:
        pass
    for colour in (lambda: widget.winfo_toplevel().cget("background"),
                   lambda: widget.cget("background")):
        try:
            found = colour()
            if found and str(found).lower() not in ("white", "#ffffff"):
                return found
        except Exception:
            continue
    return "#f0f0f0"


class ScrollFrame(ttk.Frame):
    """A vertically scrollable container: tall content scrolls, the console
    below never gets squeezed out of view."""

    def __init__(self, parent):
        super().__init__(parent)
        #  A Tk canvas is white unless told otherwise, and this one fills the
        #  whole page area - so every panel that was shorter than the window
        #  left a white band under it, and the area looked empty rather than
        #  like the end of the page. Matching the theme's own background makes
        #  the page end where its content ends.
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0,
                                background=theme_background(self))
        vsb = ttk.Scrollbar(self, orient="vertical",
                            command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(2, 2))
        self._last_size = (0, 0)
        self.inner.bind("<Configure>", self._resize)
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw",
                                  tags="inner")
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(fill="both", expand=True, side="left")
        vsb.pack(fill="y", side="right")
        #  The page is stretched to at least the height of the window, not
        #  only to its own content. Without that a page shorter than the
        #  window left a dead band above the console, and a panel that itself
        #  expands - the settings form did - only claimed the height its
        #  widgets asked for, leaving most of the window unused.
        self.canvas.bind("<Configure>", self._resize)
        self.bind("<Enter>", lambda e: self._wheel(True))
        self.bind("<Leave>", lambda e: self._wheel(False))

    def _resize(self, _event=None):
        """Stretch the page to fill the window, then say how tall it is."""
        try:
            width = self.canvas.winfo_width()
            height = self.canvas.winfo_height()
            natural = self.inner.winfo_reqheight()
        except Exception:
            return
        wanted = (width, max(natural or 0, height or 0))
        if wanted != self._last_size:
            self._last_size = wanted
            try:
                self.canvas.itemconfigure("inner", width=wanted[0],
                                          height=wanted[1])
            except Exception:
                pass
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except Exception:
            pass

    def _wheel(self, on):
        def scroll(e):
            try:
                w = self.winfo_containing(e.x_root, e.y_root)
                while w is not None:
                    if w is self.canvas:
                        break
                    if isinstance(w, (tk.Text, tk.Listbox, tk.Canvas)):
                        return      # let nested text/list/canvas widgets scroll
                    w = w.master
            except Exception:
                pass
            self.canvas.yview_scroll(-1 * (getattr(e, "delta", 120) // 120
                                           or 1), "units")

        def scroll_lin(e):
            self.canvas.yview_scroll(-1 if e.num == 4 else 1, "units")
        try:
            if on:
                self.canvas.bind_all("<Mousewheel>", scroll)
                self.canvas.bind_all("<Button-4>", scroll_lin)
                self.canvas.bind_all("<Button-5>", scroll_lin)
            else:
                for seq in ("<Mousewheel>", "<Button-4>", "<Button-5>"):
                    self.canvas.unbind_all(seq)
        except tk.TclError:
            pass


class ToolTip:
    """Small, delayed Tk tooltip that does not steal focus or block input."""

    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = str(text or "").strip()
        self.delay = delay
        self.job = None
        self.window = None
        if self.text:
            widget.bind("<Enter>", self._schedule, add="+")
            widget.bind("<Leave>", self.hide, add="+")
            widget.bind("<ButtonPress>", self.hide, add="+")
            widget.bind("<Destroy>", self._destroyed, add="+")

    def _schedule(self, _event=None):
        self._cancel_job()
        self.job = self.widget.after(self.delay, self.show)

    def _cancel_job(self):
        if self.job is not None:
            try:
                self.widget.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None

    def show(self):
        self.job = None
        if self.window is not None or not self.widget.winfo_exists():
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
            self.window = tk.Toplevel(self.widget)
            self.window.wm_overrideredirect(True)
            self.window.wm_geometry("+%d+%d" % (x, y))
            ttk.Label(self.window, text=self.text, justify="left",
                      wraplength=300, padding=(7, 4),
                      relief="solid").pack()
        except tk.TclError:
            self.window = None

    def hide(self, _event=None):
        self._cancel_job()
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None

    def _destroyed(self, _event=None):
        self.hide()


def add_tooltip(widget, text):
    # Keep an explicit reference for clarity and for alternative Tk bindings.
    widget._alex_tooltip = ToolTip(widget, text)
    return widget


#  What every button does, in one place. The task page has had hover notes
#  since it was written; everywhere else the explanation lived only in the
#  panel's help text, so a button had to be pressed to find out what it did.
#  Keys are the button's text; a formatted one ("Put one back on sale...")
#  matches on its prefix, so a variant does not need its own entry.
TOOLTIPS = {
    # -- moving around ----------------------------------------------------
    "<- All tasks": "Go back to the list of task groups",
    "<- Back": "Go back to the previous wizard step",
    "Next step ->": "Save this step and continue the wizard",
    "Skip the wizard (task menu)": "Close the wizard and go straight to the task menu",
    "Finish": "Save the startup choice and open the task menu",
    "What this panel does": "Show what this panel is for, without leaving it",
    "Hide this help": "Fold the explanation away again",
    # -- connecting and settings -----------------------------------------
    "Test connection": "Check the saved store address and keys answer, without changing anything",
    "Save cookie": "Save the pasted cookie so the CanadianShopper tools can sign in",
    "Save user settings": "Save every field on this panel to gui-settings.json",
    "Save & open AI page": "Save the AI address and open it in your browser",
    "Open WooCommerce API keys": "Open woo-keys.txt so the store keys can be edited; the file persists across updates",
    "Open WordPress media upload": "Open the WordPress media library to upload by hand",
    "Pick a folder...": "Choose a folder and save it in the settings",
    "Browse...": "Choose a file or folder and save its path",
    "Use this browser": "Use the selected browser for every page Alex Collect opens",
    # -- selling to a customer -------------------------------------------
    "Build the order": "Match the pasted list to products and preview the order before writing it",
    "Create the order": "Write the previewed order to the store as pending; nothing is charged",
    "Open the order list": "Open the WooCommerce order screen to paste the list by hand",
    "Search": "Search the store for the typed card and list the matches",
    # -- a sale -----------------------------------------------------------
    "A card sold": "Open the sold panel: type what sold and tick off the other marketplaces",
    "Add to the checklist (and fix CS if ticked)": "Record the sale and add the other listings to the tick-off checklist",
    "CanadianShopper only: preview the stock change": "Show what the CanadianShopper plugin would change, without writing anything",
    "What is outstanding? (--status)": "List the cards still waiting to be ticked off",
    "Open the checklist viewer (tick things off)": "Open the checklist window and tick off what has been done",
    "Open the checklist (sold-cards-checklist.csv)": "Open the checklist file itself in your spreadsheet",
    "Open the stock report (sold-cards-report.csv)": "Open the report of sales that were applied",
    "Put one back on sale (--reactivate is in SoldCards.bat)": "Take a card off the checklist and put it back on sale",
    # -- a new batch ------------------------------------------------------
    "Run the card pipeline": "Open the pipeline dialog: choose the scans and run split then listing",
    "Split the scans and build the CSV": "Split the scans and run the listing step with the AI answer on the clipboard",
    "Continue": "Start the batch with the choice selected above; nothing has been written to your website yet",
    "Split the scans only": "Split the scans into card images and stop, so the AI steps can be done on their own",
    "Combine CSVs": "Join the marketplace CSVs into one import batch",
    "Combine now": "Join the CSVs now, after the preview",
    "Stage the photos": "Square, host and wire the batch photos through the plugin",
    "Stage the photos (square + host + rewrite CSVs)": "Square the photos, host them and rewrite the CSVs with their URLs",
    "Import / publish drafts": "Import the batch and preview or publish the vendor drafts",
    "Preview drafts": "Show what would be published; nothing is changed",
    "Publish ready drafts": "Publish the ready drafts after typing PUBLISH to confirm",
    "Wire the photos": "Set the batch photos on their listings without rebuilding anything",
    "Wire for real": "Apply the wiring instead of only reporting what it would do",
    "Re-point photos": "Point the listings at photos that are already hosted, from the cache",
    "Preview cached changes": "Show what the re-point would change, using cached URLs only",
    "Preview (--dry-run)": "Report what the combine would write, without creating the CSV",
    "Apply the previewed change": "Write exactly what the preview listed",
    "Clear": "Empty this list; the files on disk are left alone",
    "Type the cards...": "Open the editor for typing what sold, one card per line",
    "Add these": "Add only the orders shown above to the checklist - the rest of the website is left alone",
    "Compare stock": "Read both catalogues and list only the cards whose counts disagree; nothing is changed",
    "Compare this card": "Open the stock panel pointed at the one card this sale is about",
    "Compare the whole catalogue instead": "Drop the one-card filter and compare everything",
    "Compare stock with eBay": "Read your eBay active listings with your session cookie and list only the cards whose numbers disagree",
    "Compare stock with Facebook": "Read your Facebook selling page with your session cookie and list only the cards whose numbers disagree",
    "Set CanadianShopper to the website's counts...": "The usual fix: for every card whose two counts differ, set CanadianShopper's count to the website's count - always shown and confirmed first, write permission only",
    "Fix the selected cards...": "Set CanadianShopper to the website's count for just the rows selected in the list, after a confirmation listing them",
    "Set the website to the selected cards' counts...": "The reverse fix: set the website's stock count to the count the other site reports, for the selected cards - always shown and confirmed first; needs WooCommerce keys with Read/Write access",
    "Open the selected cards on the website": "Open the website's own product edit page for the selected cards - for a count a plugin owns, a variable product, or anything the stock panel should not touch",
    "List the selected cards on CanadianShopper...": "Write the CanadianShopper import file for the selected website-only cards from the website product - title, price, its own photo and stock count - then offer to import it as drafts and to publish them",
    "List every website-only card...": "The same file for every card that is on the website and not on CanadianShopper, then the same offer to import and publish the drafts",
    "Ignore the selected cards": "Stop comparing the selected cards: a card that is no longer sold on one site disappears from the list until it is restored; nothing on either site changes",
    "Publish the ready drafts...": "Scan CanadianShopper's drafts and activate only the ones that pass every readiness check - for cards whose listing exists but was never published; PUBLISH still has to be typed",
    "Restore ignored cards...": "Put every ignored card back into comparisons, after showing which ones they are",
    "Read a saved eBay page...": "Read an eBay page you saved from your own signed-in browser (Ctrl+S, HTML only) - the way round eBay's \"Pardon our interruption\" check, using the same reader",
    "Read a saved Facebook page...": "Read a Facebook selling page you saved from your own signed-in browser (Ctrl+S, HTML only) - the way round Facebook's HTTP 400, using the same reader",
    "Open the eBay cookie file": "Open ebay-cookie.txt so the eBay session cookie can be pasted; the file stays on this computer",
    "Open the Facebook cookie file": "Open fb-cookie.txt so the Facebook session cookie can be pasted; the file stays on this computer",
    "Preview new orders": "Read the orders that came in since you last looked, and write nothing",
    "Open plugins folder": "Open the folder plugins are installed into",
    "Open the tools folder": "Open the folder holding this app's tools",
    "Dry-run (writes nothing)": "Report what would happen without writing anything",
    # -- after a sale / archives -----------------------------------------
    "Preview: what sits at 0?": "List the CanadianShopper listings already at zero stock",
    "Archive listings at 0": "Archive those listings, one at a time, without deleting them",
    "Archive them": "Archive the listed zero-stock listings",
    "Refresh list": "Read the file again and rebuild this list",
    "Refresh": "Read the plugin list again",
    # -- photos -----------------------------------------------------------
    "Replace card photos": "Open the photo panel: find the card and replace its pictures",
    "Find the card...": "Look the card up on the store and start the replacement",
    "Add sheets...": "Load the scan sheets for this sitting; they stay loaded for the next card too",
    "Assign photos to cards...": "Line a whole sheet up with cards and replace them in a batch",
    "Read these": "Read the pasted titles or cards and fill one row per image",
    "Choose a card for this row": "Search the store for the card this image belongs to",
    "Apply the ready ones": "Replace the photos for every row that is unambiguously matched",
    "Square up a photo": "Crop one photo to the card and save a square copy for manual upload",
    "Pick photo(s)...": "Choose the photos this panel works on",
    "Use this image": "Take the picture selected above as this card's image",
    "Another scan...": "Load a different scan when the image is not on these sheets",
    # -- dialogs ----------------------------------------------------------
    "Cancel": "Close this window and change nothing",
    "Close": "Close this window",
    "Not now": "Skip this offer; nothing is changed",
    "Use this card": "Take the selected card as the one being replaced",
    "Use this product": "Take the selected product as the one whose photos change",
    "Use selected listing": "Use the listing selected above",
    "Replace the selected row": "Replace that gallery row with the new photo",
    "Remove this photo from the product": "Take that row off the product; the image file stays in the media library",
    "Keep every existing photo": "Add the new photo beside the old ones instead of replacing any",
    "No old back - keep every row and add the new back": "Leave the gallery as it is and add the new back beside it",
    "Leave this card unmatched": "Skip this card; nothing is written for it",
    "Leave remaining unmatched": "Finish with the cards matched so far and skip the rest",
    "Apply these changes": "Write the changes listed above",
    "Skip this one": "Leave this card for later and move to the next",
    "Cancel this card": "Stop this card; anything already written stays written",
    "Cancel all": "Stop the whole run; anything already written stays written",
    "Tick the selected ones": "Mark the selected checklist rows as done",
    "Tick EVERYTHING": "Mark every outstanding row as done, after a confirmation",
    "Open the selected row's link": "Open the marketplace page for the selected checklist row",
    # -- re-runs ----------------------------------------------------------
    "WooCommerce CSV": "Rebuild only the WooCommerce import CSV from the AI answer on disk",
    "CanadianShopper CSV": "Rebuild only the CanadianShopper CSV and its staged photos",
    "Facebook feed + xlsx": "Rebuild only the Facebook feed and the Marketplace delta workbook",
    "eBay Quick List": "Rebuild only the eBay Quick List page",
    "Choose a different AI text...": "Point this re-run at a different saved AI answer",
    "Re-run a marketplace": "Open the panel that rebuilds one marketplace at a time",
    # -- logs, reports and plugins ---------------------------------------
    "Preview old pipeline files": "List the older output files and where they would be moved",
    "Move old files into folders": "Move those files after a confirmation; nothing is deleted or overwritten",
    "Open the GUI log (gui-log.txt)": "Open this app's own log",
    "Open the pipeline output-file audit": "Open the list of every file the pipeline writes",
    "Open the publish report": "Open the report from the last draft publish",
    "Open the image-sync report": "Open the report from the last photo wiring",
    "Open the stock report (sold-cards-report.csv)": "Open the report of applied sales",
    "Open the CSV file": "Open this batch's CSV in your spreadsheet",
    "Open the CSV": "Open that CSV in your spreadsheet",
    "Open the batch folder": "Open the folder holding this batch's files",
    "Open the cs-ready folder": "Open the folder of photos prepared for CanadianShopper",
    "Open the Facebook feed folder (the delta xlsx lives here)": "Open the folder holding the Facebook feed and workbook",
    "Open the plugins folder": "Open the folder plugins are installed into",
    "Open the scanner folder": "Open the folder your scans are saved to",
    "Open the report (cs-image-report.csv)": "Open the report from the last image sync",
    "Open canadianshopper.ca": "Open the CanadianShopper site in your browser",
    "Your eBay listings": "Open your active eBay listings",
    "Your Facebook listings": "Open your Facebook Marketplace selling page",
    "Install from ZIP...": "Install a plugin from a ZIP you trust; plugin code runs as you",
    "Enable": "Turn this plugin back on",
    "Disable": "Turn this plugin off without uninstalling it",
    "Remove...": "Uninstall this plugin after a confirmation",
    "Remove selected": "Remove the selected item from this list",
    "New command": "Add a custom AI command button for the pipeline dialog",
    "Add / update button": "Save this command as a new button, or update the selected one",
    "Run the Facebook feed updater": "Run the Facebook feed companion on its own",
    "Split the scans and build the CSV": "Split the scans and run the listing step",
    # -- console ----------------------------------------------------------
    "Send": "Send what you typed to the running tool",
    "Enter": "Send a bare Enter to the running tool",
    "Stop": "Stop the running tool; anything already written stays written",
}


def tip_for(text):
    """The hover explanation for a button's text, or "" when there is none."""
    text = str(text or "").strip()
    if text in TOOLTIPS:
        return TOOLTIPS[text]
    best = ""
    for key in TOOLTIPS:
        if text.startswith(key) and len(key) > len(best):
            best = key
    return TOOLTIPS[best] if best else ""


def _descendants(widget):
    """Every widget under ``widget``, parents before children."""
    try:
        children = widget.winfo_children()
    except Exception:
        return
    for child in children:
        yield child
        yield from _descendants(child)


def tips_missing(root):
    """Button texts under ``root`` that have no hover explanation."""
    missing = []
    for widget in _descendants(root):
        text = button_text(widget)
        if text is None:
            continue
        existing = getattr(widget, "_alex_tooltip", None)
        if existing is not None and getattr(existing, "text", ""):
            continue
        if not tip_for(text):
            missing.append(text)
    return missing


def button_text(widget):
    """A button's caption, or None when the widget is not a button."""
    try:
        if not isinstance(widget, (ttk.Button, tk.Button)):
            return None
        return str(widget.cget("text") or "")
    except Exception:
        return None


def attach_tooltips(root):
    """Give every button under ``root`` a hover explanation it does not have.

    Called once a window or panel is built. A button that already carries an
    explanation (the task menu's own, or one written for a specific case) is
    left alone, so nothing is explained twice.
    """
    added = 0
    for widget in _descendants(root):
        text = button_text(widget)
        if text is None:
            continue
        existing = getattr(widget, "_alex_tooltip", None)
        if existing is not None and getattr(existing, "text", ""):
            continue
        tip = tip_for(text)
        if tip:
            add_tooltip(widget, tip)
            added += 1
    return added


# --------------------------------------------------------------------- app
class App(tk.Tk):
    def __init__(self, settings=None, scans=None):
        super().__init__()
        self.settings = settings or load_settings()
        self.cs_addon = cs_addon_present()
        self._boot_scans = [str(x) for x in (scans or [])
                            if Path(str(x)).is_file()]
        self.title("%s v%s" % (APP_NAME, VERSION))
        try:    # the card-pair icon, in the window and on the taskbar
            from PIL import Image as _Img, ImageTk as _ImgTk
            self._icon_img = _ImgTk.PhotoImage(
                _Img.open(BASE / "icon-256.png"))
            self.iconphoto(True, self._icon_img)
        except Exception:
            pass
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        #  Small screens get a small window: the old minimums (940x660) were
        #  larger than an 800x600 display, so the app opened bigger than the
        #  screen and the bottom of every panel was off it.
        width = min(1160, max(760, screen_width - 60))
        height = min(920, max(540, screen_height - 70))
        self.geometry("%dx%d" % (width, height))
        self.minsize(min(720, width), min(500, height))
        self.runner = Runner(self)
        self._saw_dangling_prompt = False
        self._hinted = set()
        self._build_styles()
        self._build_menu()
        self._build_statusbar()
        self._build_console()
        self._build_topbar()
        self._build_body()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        after = self.settings.get("startup_mode", "menu")
        if not self.settings.get("seen_wizard"):
            self.show_mode("wizard")
        elif after == "wizard":
            self.show_mode("wizard")
        elif after == "tabs":
            self.show_mode("tabs")
        else:
            self.show_mode("menu")
        self._poll_job = self.after(120, self._poll)
        self._boot_job = None
        if self._boot_scans:
            self._boot_job = self.after(400, self.open_pipeline_with_scans,
                                        self._boot_scans)

    # ---------------------------------------------------------- chrome
    def _build_styles(self):
        st = ttk.Style(self)
        try:
            if "vista" in st.theme_names():
                st.theme_use("vista")
            elif "clam" in st.theme_names():
                st.theme_use("clam")
        except Exception:
            pass
        st.configure("H1.TLabel", font=("TkDefaultFont", 14, "bold"))
        st.configure("H2.TLabel", font=("TkDefaultFont", 10, "bold"))
        st.configure("Dim.TLabel", foreground="#666666")
        st.configure("Task.TButton", padding=(7, 3))
        st.configure("TaskGroup.TLabelframe", padding=(10, 7),
                     borderwidth=2, relief="groove")
        #  One bordered box per panel in the tabs view: a heavier border than
        #  a group box, so the boundary between two panels is unmistakable.
        st.configure("PanelSection.TLabelframe", padding=(8, 6),
                     borderwidth=2, relief="groove")
        st.configure("PanelSection.TLabelframe.Label",
                     font=("TkDefaultFont", 10, "bold"),
                     foreground="#24476b")
        st.configure("TaskGroup.TLabelframe.Label",
                     font=("TkDefaultFont", 10, "bold"),
                     foreground="#24476b")
        st.configure("TaskMenu.TButton", padding=(9, 6), width=25)
        st.configure("TNotebook.Tab", padding=(8, 3))
        st.configure("TLabelframe", padding=4)
        try:
            st.configure("Task.TButton", wraplength=220)
        except Exception:
            pass

    def _build_menu(self):
        m = tk.Menu(self, tearoff=0)
        view = tk.Menu(m, tearoff=0)
        self._mode_var = tk.StringVar(
            value=self.settings.get("startup_mode", "menu"))
        view.add_radiobutton(label="Wizard on startup", variable=self._mode_var,
                             value="wizard", command=self._save_startup)
        view.add_radiobutton(label="Task menu on startup",
                             variable=self._mode_var, value="menu",
                             command=self._save_startup)
        view.add_radiobutton(label="Tabs on startup", variable=self._mode_var,
                             value="tabs", command=self._save_startup)
        view.add_separator()
        view.add_command(label="Show the wizard now",
                         command=lambda: self.show_mode("wizard"))
        view.add_command(label="Task menu", command=lambda: self.show_mode("menu"))
        view.add_command(label="Tabs", command=lambda: self.show_mode("tabs"))
        m.add_cascade(label="View", menu=view)
        m.add_command(label="User Settings", command=self.show_user_settings)
        m.add_command(label="Plugins", command=lambda: self.show_panel("plugins"))
        m.add_command(label="Logs & reports",
                      command=lambda: self.show_panel("logs"))
        help = tk.Menu(m, tearoff=0)
        help.add_command(label="Open README.md",
                         command=lambda: open_path(BASE / "README.md"))
        help.add_command(label="About",
                         command=lambda: messagebox.showinfo(
                             "Alex Collect Control Panel",
                             "One window for every tool.\n"
                             "Every button runs the same tested command as "
                             "the .bat launchers.\nVersion " + VERSION))
        m.add_cascade(label="Help", menu=help)
        self.config(menu=m)

    def _save_startup(self):
        self.settings["startup_mode"] = self._mode_var.get()
        save_settings(self.settings)

    def show_panel(self, panel_id):
        """Open a panel from the menu bar, regardless of current view."""
        self.show_mode("menu")
        self.update_idletasks()
        try:
            tasks = self._mode_frame.inner.winfo_children()[0]
            tasks.show_panel(panel_id)
        except (AttributeError, IndexError, tk.TclError):
            log("could not open %s panel" % panel_id)

    def show_user_settings(self):
        """Open the central settings panel from the menu bar."""
        self.show_panel("cookie")

    def _build_topbar(self):
        bar = ttk.Frame(self, padding=(8, 3, 8, 2))
        bar.pack(fill="x")
        ttk.Label(bar, text="Alex Collect", style="H1.TLabel").pack(side="left")
        for text, mode, tip in (("Wizard", "wizard", "Guided setup and workflow"),
                                ("Tasks", "menu", "Compact task launcher"),
                                ("Tabs", "tabs", "Show task panels as tabs")):
            button = ttk.Button(bar, text=text, width=8,
                                command=lambda m=mode: self.show_mode(m))
            button.pack(side="right", padx=(4, 0))
            add_tooltip(button, tip)

    def _build_body(self):
        # built BEFORE the console so the console keeps its space (Tk packs
        # in order); the body takes whatever is left and scrolls inside.
        self.body = ttk.Frame(self, padding=(6, 2))
        self.body.pack(fill="both", expand=True)
        self._mode_frame = None

    def _build_console(self):
        box = ttk.LabelFrame(self, text="Output (scrollback)",
                             padding=(4, 2))
        box.pack(fill="x", side="bottom", padx=6, pady=(1, 2))
        #  The console is a fixed number of lines, and on a small screen
        #  twenty of them were half the window - the page above got what was
        #  left. It keeps its share on a big screen and gives the page its
        #  room back on a small one; it still scrolls to everything.
        try:
            screen = self.winfo_screenheight()
        except Exception:
            screen = 900
        lines = console_lines_for(screen)
        self.console = tk.Text(
            box, height=lines, state="disabled", wrap="word", bg="#141414",
            fg="#e8e8e8", insertbackground="#e8e8e8",
            font=("Consolas", 9) if sys.platform == "win32"
                 else "TkFixedFont")
        ysb = ttk.Scrollbar(box, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=ysb.set)
        self.console.bind("<Control-End>", self._console_scroll_end)
        self.console.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        add_tooltip(ysb, "Scroll the output history; new output and entered replies stay visible at the bottom.")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.console.tag_configure("cmd", foreground="#9fd0ff")
        self.console.tag_configure("err", foreground="#ff9d9d")
        self.console.tag_configure("ok", foreground="#9de0a8")
        #  Not every outcome is a failure or a success: "the file was read and
        #  there was nothing new in it" is neither, and painting it red sends
        #  the person looking for a fault that is not there.
        self.console.tag_configure("warn", foreground="#ffd08a")
        self.console.tag_configure("dim", foreground="#8a8a8a")

        row = ttk.Frame(box)
        row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        ttk.Label(row, text="Reply:").pack(side="left")
        self.inp = ttk.Entry(row)
        self.inp.pack(side="left", fill="x", expand=True, padx=4)
        self.inp.bind("<Return>", lambda e: self._send_input())
        send_button = ttk.Button(row, text="Send", command=self._send_input)
        send_button.pack(side="left")
        add_tooltip(send_button, "Send your typed answer to the running tool")
        enter_button = ttk.Button(row, text="Enter", command=self._send_enter)
        enter_button.pack(side="left", padx=(3, 0))
        add_tooltip(enter_button, "Send a blank Enter response")
        stop_button = ttk.Button(row, text="Stop", command=self.runner.stop)
        stop_button.pack(side="left", padx=4)
        add_tooltip(stop_button, "Stop the currently running tool")
        self._input_enable(False)
        #  The version is the first line of the console on purpose: a pasted
        #  console then says which build produced it, which a question about
        #  "still broken after the rebuild" needs to be answerable.
        self.console_line("Alex Collect %s" % VERSION, "dim")
        plugin = plugin_version()
        if plugin:
            self.console_line("CanadianShopper plugin %s" % plugin, "dim")
        self.console_line(
            "Ready. Pick a task above. Nothing changes on any website "
            "without a preview and a confirmation.", "dim")

    def _build_statusbar(self):
        bar = ttk.Frame(self, padding=(8, 0, 8, 3))
        bar.pack(fill="x", side="bottom")
        bar.lower()
        self.status = ttk.Label(bar, text="Ready.")
        self.status.pack(side="left")
        ttk.Label(bar, text="v%s  -  previews first, asks before writing"
                  % VERSION, style="Dim.TLabel").pack(side="right")

    # -------------------------------------------------------- console io
    def _input_enable(self, on):
        state = "normal" if on else "disabled"
        self.inp.config(state=state)
        self.console.tag_configure("hint", foreground="#8a8a8a")

    def _console_scroll_end(self, _event=None):
        self.console.see("end")
        return "break"

    def console_write(self, chunk):
        """Insert tool output and keep the newest prompt/reply in view."""
        self.console.config(state="normal")
        self.console.insert("end", chunk)
        self.console.config(state="disabled")
        self.console.see("end")

    def console_line(self, text, tag=None):
        self.console.config(state="normal")
        self.console.insert("end", text + "\n", tag or ())
        # colour obvious problems
        if tag is None:
            low = text.lower()
            if low.startswith(("error", "traceback", "  error")) or \
                    "authentication required" in low:
                self.console.tag_add("err", "end-2linestart", "end-1linestart")
            elif low.startswith(("ok ", "done", "session ok", "all checks")):
                self.console.tag_add("ok", "end-2linestart", "end-1linestart")
        self.console.config(state="disabled")
        self.console.see("end")

    def _send_input(self):
        text = self.inp.get().strip()
        if self.runner.busy():
            self.runner.send(text)      # an empty box = a bare Enter
            self.console_line("> " + (text if text else "(Enter)"), "cmd")
            self.status.config(text="Answer sent - " + self.runner.title +
                               " carries on.")
        self.inp.delete(0, "end")

    def _send_enter(self):
        """Send Enter by itself - some questions expect exactly that."""
        if self.runner.busy():
            self.runner.send("")
            self.console_line("> (Enter)", "cmd")
            self.status.config(text="Enter sent - " + self.runner.title +
                               " carries on.")

    def _poll(self):
        if not self.winfo_exists():
            return
        self.runner.drain()
        try:
            self._poll_job = self.after(120, self._poll)
        except tk.TclError:
            self._poll_job = None

    def on_run_start(self, title, cmd):
        self._saw_dangling_prompt = False
        self._hinted = set()
        self.console_line("")
        self.console_line("---- " + title + " " + "-" * max(0, 60 - len(title)),
                          "cmd")
        self.console_line("$ " + cmd, "dim")
        self.status.config(text="Running: " + title)
        self._input_enable(True)

    def on_run_end(self, title, rc):
        ok = (rc == 0)
        self.console_line(
            "---- finished (%s, exit code %s) " %
            ("OK" if ok else "PROBLEM", rc) + "-" * 30,
            "ok" if ok else "err")
        self.status.config(
            text=("Finished: " if ok else "Stopped with a problem: ") + title +
            ("  -  the log keeps everything: " + LOG_FILE.name))
        self._input_enable(False)

    # ------------------------------------------------------------ modes
    def clear_action_bar(self):
        """Empty the pinned strip; a stale Save button is worse than none."""
        bar = getattr(self, "_action_bar", None)
        if bar is not None:
            try:
                if bar.winfo_exists():
                    bar.destroy()
            except Exception:
                pass
        self._action_bar = None

    def show_mode(self, mode):
        self.clear_action_bar()
        if self._mode_frame is not None:
            self._mode_frame.destroy()
        wrap = ScrollFrame(self.body)
        wrap.pack(fill="both", expand=True)
        self._mode_frame = wrap
        self._current_wizard = None
        if mode == "wizard":
            self._current_wizard = WizardFrame(wrap.inner, self)
            self._mark_wizard_seen_soon()
        elif mode == "tabs":
            TabsFrame(wrap.inner, self)
        else:
            TasksFrame(wrap.inner, self)

    def _mark_wizard_seen_soon(self):
        def mark():
            if not self.settings.get("seen_wizard"):
                self.settings["seen_wizard"] = True
                save_settings(self.settings)
        self.after(1500, mark)

    def destroy(self):
        """Cancel Tk polling/boot callbacks before destroying the root."""
        for name in ("_poll_job", "_boot_job"):
            job = getattr(self, name, None)
            if job:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, name, None)
        super().destroy()

    def _on_close(self):
        if self.runner.busy():
            if not messagebox.askyesno(
                    "Still running",
                    "\"%s\" is still running. Close anyway and stop it?"
                    % self.runner.title):
                return
            self.runner.stop()
        self.destroy()

    # --------------------------------------------- dropped-scan entry point
    def open_pipeline_with_scans(self, scans):
        """Started with scan files on the command line (drag-and-drop onto
        the desktop icon): the pipeline dialog opens pre-filled."""
        script = find_pipeline_script(self.settings)
        if script is None:
            self.console_line(
                "Scans received, but card_pipeline.py was not found - open "
                "the pipeline panel and browse for it once.", "err")
            self.show_mode("menu")
            return

        def on_run(args, on_done, title):
            return self.run_tool(str(script), args, title,
                                 cwd=str(script.parent), on_done=on_done)
        self.show_mode("menu")
        dlg = PipelineDialog(self, script, on_run,
                             front=scans[0] if len(scans) >= 1 else "",
                             back=scans[1] if len(scans) >= 2 else "")
        dlg.lift()
        dlg.focus_force()
        return dlg

    # -------------------------------------------------------- run helper
    def run_tool(self, tool, args, title, cwd=None, on_done=None, confirm=None):
        tool = str(tool)
        script = tool if os.path.isabs(tool) else TOOL(tool)
        return self.runner.start(script, args, cwd or self.settings.get(
            "pipeline_dir", WORK), title, on_done=on_done, confirm=confirm)

    def handle_tool_dialog(self, request):
        """Handle a structured CanadianShopper picker/approval from a tool."""
        kind = request.get("type")
        if kind == "confirm_cs":
            rows = request.get("rows", [])
            missing = request.get("unmatched", [])
            lines = []
            for row in rows:
                title = row.get("title") or "(untitled listing)"
                action = row.get("action", "change")
                before = row.get("inventory_before")
                after = row.get("inventory_after")
                detail = "stock %s -> %s" % (before, after)
                if row.get("status_after") and row.get("status_after") != row.get("status_before"):
                    detail += "; status %s -> %s" % (
                        row.get("status_before") or "?", row.get("status_after"))
                pid = str(row.get("product_id") or "")
                if pid:
                    detail += "; ID …%s" % pid[-8:]
                lines.append("• %s — %s (%s)" % (title, action, detail))
            if missing:
                lines.append("\nNot matched (will remain unchanged): " +
                             "; ".join(str(x)[:80] for x in missing))
            question = ("Apply these CanadianShopper changes?\n\n" +
                        "\n".join(lines) +
                        "\n\nOnly the listed changes will be written.")
            if len(rows) > 12 or len(question) > 1400:
                approved = self._confirm_cs_dialog(question)
            else:
                approved = messagebox.askyesno(
                    "Confirm CanadianShopper changes", question, parent=self)
            return {"answer": "yes" if approved else "no"}
        if kind == "match_cs":
            matches = self._pick_cs_matches(request)
            return {"matches": matches}
        if kind == "pick_back":
            return self._pick_cs_back(request)
        return {}

    def _confirm_cs_dialog(self, text):
        """Scrollable, full-list approval dialog for large CS write plans."""
        top = tk.Toplevel(self)
        top.title("Confirm CanadianShopper changes")
        top.transient(self)
        top.geometry("680x460")
        top.grab_set()
        ttk.Label(top, text="Review every CanadianShopper stock/status change "
                  "below before applying:", wraplength=650).pack(
                      anchor="w", padx=8, pady=(8, 4))
        body = ttk.Frame(top)
        body.pack(fill="both", expand=True, padx=8, pady=3)
        view = tk.Text(body, wrap="word", height=16, state="normal")
        scroll = ttk.Scrollbar(body, orient="vertical", command=view.yview)
        view.configure(yscrollcommand=scroll.set)
        view.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        view.insert("1.0", text)
        view.configure(state="disabled")
        result = tk.BooleanVar(master=top, value=False)
        buttons = ttk.Frame(top)
        buttons.pack(fill="x", padx=8, pady=6)
        ttk.Button(buttons, text="Apply these changes",
                   command=lambda: (result.set(True), top.destroy())).pack(
                       side="right")
        ttk.Button(buttons, text="Cancel",
                   command=lambda: (result.set(False), top.destroy())).pack(
                       side="right", padx=8)
        top.protocol("WM_DELETE_WINDOW",
                     lambda: (result.set(False), top.destroy()))
        self.wait_variable(result)
        return bool(result.get())

    def _pick_cs_matches(self, request):
        """Let the user resolve unmatched titles against ranked/searchable CS items."""
        products = request.get("products", [])
        unmatched = request.get("unmatched", [])
        chosen = {}
        if not unmatched or not products:
            return chosen
        top = tk.Toplevel(self)
        top.title("Find CanadianShopper listing")
        top.transient(self)
        top.geometry("680x500")
        top.grab_set()
        current = {"index": 0, "filtered": []}
        title_var = tk.StringVar(master=top)
        search_var = tk.StringVar(master=top)
        ttk.Label(top, textvariable=title_var, wraplength=650,
                  font=("TkDefaultFont", 10, "bold")).pack(
                      anchor="w", padx=8, pady=(8, 3))
        ttk.Label(top, text="Top suggestions appear first. Search by typing a "
                  "different title fragment; choose a listing to use.",
                  wraplength=650).pack(anchor="w", padx=8, pady=(0, 4))
        entry = ttk.Entry(top, textvariable=search_var)
        entry.pack(fill="x", padx=8, pady=(0, 4))
        listing = tk.Listbox(top, height=14, exportselection=False)
        listing.pack(fill="both", expand=True, padx=8, pady=3)
        status = ttk.Label(top, text="", style="Dim.TLabel")
        status.pack(anchor="w", padx=8)
        row = ttk.Frame(top)
        row.pack(fill="x", padx=8, pady=6)
        def render(*_):
            item = unmatched[current["index"]]
            query = search_var.get().strip().lower()
            title_var.set("Card %d of %d: %s" % (
                current["index"] + 1, len(unmatched), item.get("title", "")))
            suggestions = item.get("suggestions", [])
            by_id = {str(p.get("id")): p for p in products}
            ordered = [by_id[str(pid)] for pid in suggestions if str(pid) in by_id]
            if query:
                seen = {str(p.get("id")) for p in ordered}
                ordered.extend(p for p in products if str(p.get("id")) not in seen and
                               query in str(p.get("title", "")).lower())
            current["filtered"] = ordered[:100]
            listing.delete(0, "end")
            for p in current["filtered"]:
                inv = p.get("inventory")
                stock = "stock ?" if inv is None else "stock %s" % inv
                listing.insert("end", "%s  [ID …%s; %s; %s]" % (
                    p.get("title") or "(untitled)",
                    str(p.get("id") or "")[-8:], stock,
                    p.get("status") or "unknown status"))
            status.config(text=("%d result(s) shown" % len(current["filtered"]))
                          if current["filtered"] else
                          "No likely match yet - search the catalog above.")
        def use_selected():
            sel = listing.curselection()
            if not sel:
                messagebox.showinfo("Choose a listing",
                                    "Select a CanadianShopper listing first.",
                                    parent=top)
                return
            item = unmatched[current["index"]]
            product = current["filtered"][sel[0]]
            chosen[str(item["index"])] = str(product["id"])
            advance()
        def skip_one():
            advance()
        def advance():
            current["index"] += 1
            if current["index"] >= len(unmatched):
                top.destroy()
                return
            search_var.set("")
            render()
        def leave_rest():
            top.destroy()
        search_var.trace_add("write", render)
        ttk.Button(row, text="Use selected listing", command=use_selected
                   ).pack(side="left")
        ttk.Button(row, text="Leave this card unmatched", command=skip_one
                   ).pack(side="left", padx=8)
        ttk.Button(row, text="Leave remaining unmatched", command=leave_rest
                   ).pack(side="right")
        top.protocol("WM_DELETE_WINDOW", leave_rest)
        render()
        entry.focus_set()
        attach_tooltips(top)
        self.wait_window(top)
        return chosen

    def _pick_cs_back(self, request):
        """Ask which existing gallery row is the card's old back photo.

        CanadianShopper keeps a listing's main front apart from its gallery, so
        a listing with one gallery row is not a one-photo listing: that row can
        be an old back, a certificate, or packaging. The plugin asks rather than
        guessing, and this is the real dialog; without a handler for this type
        the app would answer {} and the plugin would fall back to numbered
        console choices.

        Answers ``{"row": <id>}`` (replace that row), ``{"row": null}`` (keep
        every row and add the new back), or ``{"cancel": true}``.
        """
        rows = [row for row in (request.get("rows") or [])
                if isinstance(row, dict)]
        allow_add = request.get("allow_add", True)
        title = str(request.get("title") or "this card")
        #  "Untouched" must not look like "add a back": a window that was never
        #  answered cancels, so no listing is changed by a stray click.
        answer = {"choice": "cancel", "row": None}
        top = tk.Toplevel(self)
        top.title("Which row is the old back?")
        top.transient(self)
        top.geometry("720x430")
        top.grab_set()
        ttk.Label(top, text="%s" % title, wraplength=690,
                  font=("TkDefaultFont", 10, "bold")).pack(
                      anchor="w", padx=10, pady=(10, 2))
        sent = " / ".join(str(request.get(key)) for key in ("front", "back")
                          if request.get(key))
        if sent:
            ttk.Label(top, text="Replacing with: %s" % sent,
                      style="Dim.TLabel", wraplength=690).pack(
                          anchor="w", padx=10)
        ttk.Label(top, text="CanadianShopper cannot tell which of these rows "
                  "is the card's old back photo, and it will not guess. Pick "
                  "the row to replace with the new back, or keep every row and "
                  "add the new back beside them.", wraplength=690,
                  justify="left").pack(anchor="w", padx=10, pady=(6, 6))
        listing = tk.Listbox(top, height=9, exportselection=False)
        listing.pack(fill="both", expand=True, padx=10)
        for row in rows:
            sort = row.get("sortOrder")
            name = str(row.get("filename") or "(no filename)")
            suffix = "" if sort in (None, "") else "   [position %s]" % sort
            listing.insert("end", "%s%s" % (name, suffix))
        if rows:
            listing.selection_set(0)

        def take_row(*_event):
            picked = listing.curselection()
            if not picked or not rows:
                messagebox.showinfo(
                    "Choose a row",
                    "Select the row that is the old back photo.", parent=top)
                return
            row = rows[picked[0]]
            if row.get("id") in (None, ""):
                messagebox.showwarning(
                    "That row has no ID",
                    "CanadianShopper did not send an ID for this row, so it "
                    "cannot be replaced safely.", parent=top)
                return
            answer["choice"] = "row"
            answer["row"] = str(row["id"])
            top.destroy()

        def add_new(*_event):
            answer["choice"] = "add"
            answer["row"] = None
            top.destroy()

        def cancel(*_event):
            answer["choice"] = "cancel"
            answer["row"] = None
            top.destroy()

        buttons = ttk.Frame(top)
        buttons.pack(fill="x", padx=10, pady=8)
        ttk.Button(buttons, text="Replace the selected row",
                   command=take_row).pack(side="left")
        if allow_add:
            ttk.Button(buttons, text="No old back - keep every row and add "
                       "the new one",
                       command=add_new).pack(side="left", padx=8)
        ttk.Button(buttons, text="Cancel this card",
                   command=cancel).pack(side="right")
        listing.bind("<Double-Button-1>", take_row)
        top.protocol("WM_DELETE_WINDOW", cancel)
        attach_tooltips(top)
        self.wait_window(top)
        if answer["choice"] == "row" and answer["row"] is not None:
            return {"row": answer["row"]}
        if answer["choice"] == "add":
            return {"row": None}
        return {"cancel": True}

    def set_setting(self, key, value):
        self.settings[key] = value
        save_settings(self.settings)

    def _choose_browser(self):
        """Ask once, on first use, which installed browser should open URLs."""
        choices = available_browsers()
        labels = [label for _key, label in choices]
        top = tk.Toplevel(self)
        top.title("Choose a browser")
        top.transient(self)
        top.resizable(False, False)
        ttk.Label(top, text="Which browser should Alex Collect use for web pages?",
                  wraplength=380, justify="left").pack(
                      anchor="w", padx=10, pady=(10, 5))
        labels.insert(0, "Ask me again next time")
        label_var = tk.StringVar(master=top, value=(
            labels[1] if len(labels) > 1 else labels[0]))
        ttk.Combobox(top, textvariable=label_var, values=labels,
                     state="readonly", width=34).pack(
                         fill="x", padx=10, pady=3)
        result = {"browser": None}
        buttons = ttk.Frame(top)
        buttons.pack(fill="x", padx=10, pady=(5, 10))

        def choose():
            label = label_var.get()
            if label != "Ask me again next time":
                result["browser"] = next(
                    (key for key, name in choices if name == label), "system")
            top.destroy()

        ttk.Button(buttons, text="Use this browser", command=choose).pack(
            side="right")
        ttk.Button(buttons, text="Cancel", command=top.destroy).pack(
            side="right", padx=(0, 8))
        top.protocol("WM_DELETE_WINDOW", top.destroy)
        top.grab_set()
        attach_tooltips(top)
        self.wait_window(top)
        return result["browser"]

    def open_webpages(self, urls, new_window=False):
        """Open one or more URLs using the saved browser preference."""
        urls = [str(url).strip() for url in urls if str(url).strip()]
        if not urls:
            return ""
        browser = self.settings.get("browser_name", "")
        if not browser:
            browser = self._choose_browser()
            if browser:
                self.settings["browser_name"] = browser
                save_settings(self.settings)
                field = getattr(self, "_user_setting_vars", {}).get(
                    "browser_name")
                if field is not None:
                    field.set(browser_label(browser))
            else:
                # Cancel leaves the setting unset and uses the OS default for
                # this one launch; the preference prompt will appear next time.
                browser = "system"
        return launch_urls(urls, browser, new_window=new_window)


# ----------------------------------------------------------------- panels
#  A panel = title + doc + controls. The same builder is used by the task
#  menu, the tabs view and the wizard pages.
PANEL_ORDER = ["cookie", "pipeline", "combine", "stage", "importpanel",
               "wire", "rerun", "sold", "checklist", "stock", "zerostock",
               "square",
               "newphotos", "ordertext", "markets", "logs", "plugins"]
GROUPS_FULL = [("Sell to a customer", ["ordertext"]),
               ("Sell a new batch", ["pipeline", "combine", "stage",
                                     "importpanel", "wire"]),
               ("After a sale", ["sold", "checklist", "stock", "zerostock"]),
               ("Photos", ["square", "rerun", "newphotos"]),
               ("Re-run a marketplace", ["markets"])]


def groups_for(has_cs):
    """Compact task groups. Settings, plugins, and logs live in the menu bar.

    Without the CanadianShopper add-on, its API steps disappear and the
    pipeline writes import files for manual upload instead.
    """
    if has_cs:
        return GROUPS_FULL
    return [("Sell to a customer", ["ordertext"]),
            ("Sell a new batch", ["pipeline", "combine", "importpanel"]),
            ("After a sale", ["sold", "checklist"]),
            ("Photos", ["square", "newphotos"]),
            ("Re-run a marketplace", ["markets"])]
TITLES = {
    "cookie": "User settings",
    "pipeline": "Run the card pipeline (new batch)",
    "combine": "Combine CSVs into import batches",
    "stage": "Stage the photos for the batch",
    "importpanel": "Import drafts / publish ready items",
    "wire": "Wire the photos (after the import)",
    "rerun": "Re-point photos",
    "sold": "A card sold - mark it everywhere",
    "checklist": "The tick-off checklist",
    "stock": "Stock on every site",
    "zerostock": "Archive CanadianShopper listings already at 0",
    "square": "Square up a photo (manual upload)",
    "plugins": "Plugins",
    "newphotos": "Replace a card's photos",
    "ordertext": "Make an order from a card list",
    "markets": "Re-run a marketplace step",
    "logs": "Logs and reports",
}
MENU_LABELS = {
    "cookie": "User settings",
    "pipeline": "Run the card pipeline",
    "combine": "Combine CSVs",
    "stage": "Stage the photos",
    "importpanel": "Import / publish drafts",
    "wire": "Wire the photos",
    "rerun": "Re-point photos",
    "sold": "A card sold",
    "checklist": "The checklist",
    "stock": "Compare stock",
    "zerostock": "Archive listings at 0",
    "square": "Square up a photo",
    "newphotos": "Replace card photos",
    "ordertext": "Order from a text list",
    "markets": "Re-run a marketplace",
    "logs": "Logs & reports",
    "plugins": "Plugins",
}
BLURBS = {
    "cookie": "Set your store, AI, marketplace, and folder preferences; manage connections.",
    "pipeline": "Turn card scans and AI descriptions into listing files.",
    "combine": "Merge the month's CSVs into 500-row import files.",
    "stage": "Square + host fronts and backs, rewrite the CSVs into cs-ready.",
    "importpanel": "Import the staged CSV on CanadianShopper, then preview drafts and publish ready items directly from Alex Collect.",
    "wire": "Attach the back photos and fix the main images after an import.",
    "rerun": "CanadianShopper plugin: restore cached front/back photos after an import. No Woo export or image uploads needed; preview before applying.",
    "sold": "Record where the sale happened and follow up on the other listings.",
    "checklist": "See what is still outstanding and tick it off.",
    "stock": "Find the cards whose counts disagree between your website "
             "and CanadianShopper.",
    "zerostock": "Sweep: archive everything sitting at quantity 0.",
    "square": "Pad a photo onto a white square for a manual dashboard upload.",
    "plugins": "Install and manage optional plugins.",
    "newphotos": "Find a card, open its replacement images, and refresh its pages.",
    "ordertext": "Paste the list a customer texted you and turn it into a website order.",
    "markets": "Redo just one marketplace (Woo, CanadianShopper, Facebook, eBay) without repeating the AI or image steps.",
    "logs": "Where every run is recorded.",
}


def action_bar(app, parent=None):
    """The strip above the page that does not scroll with it.

    A panel that puts its title row in here keeps its buttons in view however
    far down the page the reader is - the scrolling area is packed below this
    strip, so the header cannot be scrolled away. It is created only when a
    panel asks for it, so pages that do not pin anything keep every pixel.
    """
    bar = getattr(app, "_action_bar", None)
    try:
        if bar is not None and bar.winfo_exists():
            return bar
    except Exception:
        pass
    body = getattr(app, "body", None)
    if body is None or parent is None:
        return None
    try:
        bar = ttk.Frame(body)
        where = {"fill": "x", "side": "top", "padx": 6, "pady": (2, 3)}
        mode_frame = getattr(app, "_mode_frame", None)
        if mode_frame is not None and mode_frame is not body:
            where["before"] = mode_frame
        bar.pack(**where)
    except Exception:
        return None
    app._action_bar = bar
    return bar


def panel_header(parent, app, pid, with_doc=True, pin=False):
    """Title and its help button on one row; the help opens right below it.

    Two earlier arrangements were wrong for the same reason. The help used to
    sit under the title as eight lines of always-on prose, which pushed the
    buttons it explains off the bottom of the window; then it went to the
    bottom edge with its button, which meant the button that opens it was
    itself at the bottom of the panel, several screens below the title on a
    long one.

    Now the button sits beside the title, where a reader looks for "more about
    this", and the text it opens appears directly beneath that row - so
    clicking it always shows something at the point where the click happened.
    It still starts folded: a panel is opened to do something with it.
    """
    core = not getattr(app, "cs_addon", True)
    titles = TITLES
    docs = {**DOCS, **(DOCS_CORE if core else {})}
    #  Inside a section the frame itself carries the title, and printing it
    #  again would give the panel two headings a few pixels apart.
    sectioned = getattr(parent, "_section_titled", False)
    #  A wizard page already has its own step heading, so pinning the panel's
    #  title above it would stack two headings and put the button above the
    #  step it belongs to.
    pinned = (pin and not getattr(parent, "_wizard_page", False) and
              action_bar(app, parent) is not None)
    holder = action_bar(app, parent) if pinned else parent
    top = ttk.Frame(holder)
    top.pack(fill="x", pady=(0, 2))
    parent._title_row = top
    if not sectioned:
        ttk.Label(top, text=titles[pid], style="H2.TLabel").pack(side="left")
    if with_doc:
        text = docs.get(pid, DOCS.get(pid, "")).strip()
        #  Builders put their own explanations here (panel_note), so they end
        #  up below the work rather than between it and the title.
        notes = ttk.Frame(parent)
        notes.pack(side="bottom", fill="x", pady=(4, 0))
        #  The help lives in its own frame under the title row, and closing it
        #  takes the whole frame away. Hiding just the text used to leave the
        #  frame behind holding the space the text had taken, so the panel
        #  kept a gap where the words had been.
        held = ttk.Frame(parent)
        doc = ttk.Label(held, text=text, style="Dim.TLabel", wraplength=760,
                        justify="left")
        doc.pack(fill="x")
        open_now = pid in getattr(app, "_docs_open", set())

        def open_help():
            """Put the help right under the title row.

            The row is only a sibling of the help when the panel is not
            pinned. A pinned row lives in the strip above the page, and
            asking Tk to pack after a widget in another container raises -
            which is how the button on User Settings came to do nothing at
            all. There the help goes to the top of the page instead, which is
            still directly under the strip and so still under the title.
            """
            if held.master is top.master:
                held.pack(fill="x", pady=(0, 3), after=top)
                return
            siblings = [w for w in parent.winfo_children() if w is not held]
            if siblings:
                held.pack(fill="x", pady=(0, 3), before=siblings[0])
            else:
                held.pack(fill="x", pady=(0, 3))

        def toggle():
            showing = pid in getattr(app, "_docs_open", set())
            if showing:
                app._docs_open = getattr(app, "_docs_open", set()) - {pid}
                held.pack_forget()
                help_button.configure(text="What this panel does")
                return
            app._docs_open = getattr(app, "_docs_open", set()) | {pid}
            #  A Tk error here would leave the button doing nothing, which is
            #  exactly the failure this is fixing - so it is never silent.
            try:
                open_help()
                help_button.configure(text="Hide this help")
            except Exception as exc:
                app._docs_open = getattr(app, "_docs_open", set()) - {pid}
                messagebox.showwarning(
                    "Could not show the help",
                    "The explanation could not be shown in this window:\n%s"
                    % exc, parent=app)

        help_button = ttk.Button(top, text="Hide this help" if open_now else
                                 "What this panel does", command=toggle)
        help_button.pack(side="right")
        if open_now:
            try:
                open_help()
            except Exception:
                pass
        parent._notes_frame = notes
        parent._help_frame = held
        app._doc_label = doc          # the text itself, for tests and reading
        app._doc_button = help_button
    return top


def panel_section(parent, app, pid, expand=True):
    """Build one panel inside its own bordered, titled section.

    The tabs view used to stack a group's panels one after another with
    nothing between them but a heading, so five panels read as one long page
    and it was hard to tell where one job ended and the next began. Each panel
    now lives in its own groove-bordered box, the panel's own title on the
    border, a gap between boxes - so scrolling the group still shows several
    panels, but every one of them is visibly its own thing.
    """
    section = ttk.LabelFrame(parent, text=TITLES[pid],
                             style="PanelSection.TLabelframe",
                             padding=(8, 4, 8, 6))
    section.pack(fill="both" if expand else "x", expand=expand,
                 padx=2, pady=(0, 10))
    section._section_titled = True      # panel_header keeps its heading off
    PANEL_BUILDERS[pid](section, app)
    attach_tooltips(section)
    return section


SETTINGS_DOCS = {
    "startup": (
        "Which view opens when Alex Collect starts. The task menu is the "
        "shortest way to a job; the tabs view shows a whole group of panels at "
        "once; the wizard is for a first run. It can be changed at any time "
        "from the View menu."),
    "store": (
        "The store itself and the AI chat page. Store name, currency prefix, "
        "currency name, description word count and tag count are substituted "
        "into the AI prompts as {{STORE_NAME}}, {{CURRENCY_PREFIX}} and so on, "
        "so changing them changes what the AI is asked for. The browser choice "
        "is used for every page Alex Collect opens; \"Ask me the first "
        "time\" means it asks once and remembers. Nothing here is uploaded or "
        "written to the shop."),
    "store_pages": (
        "Three shortcuts that save this form first, then open a page: the "
        "WordPress media uploader, your AI chat, and woo-keys.txt itself. They "
        "only open a page - no listing, photo or product is changed."),
    "custom_ai": (
        "Extra copy-to-clipboard buttons for the pipeline dialog. Each one "
        "needs a name, a hover note and the command text, and they accept the "
        "same {{STORE_NAME}}, {{CURRENCY_PREFIX}}, {{CURRENCY_NAME}}, "
        "{{DESCRIPTION_MIN_WORDS}}, {{TAG_COUNT}} and {{LISTING_CONTEXT}} "
        "placeholders as the built-in prompts. A custom button copies its "
        "command - it never sends anything to the AI by itself."),
    "markets": (
        "The pages opened after a sale and by the photo panels: your eBay "
        "active listings, the Facebook selling page, and the CanadianShopper "
        "vendor page. They are only opened in the browser."),
    "ebay": (
        "Defaults for the generated eBay Quick List page. The template URLs "
        "point at the HTML you already use; the defaults fill in the fields an "
        "AI answer does not name. Nothing is submitted to eBay from this app - "
        "the page is a copy-and-drag helper."),
    "facebook": (
        "The columns of the Facebook workbook. The templates accept "
        "{placeholders} filled in per card from the live feed; the description "
        "is the long text, and its {product_url} is filled with each card's "
        "own address. Leave the price template as {price} to use the feed's "
        "price."),
    "cs_csv": (
        "Defaults for the CanadianShopper import CSV that the pipeline writes: "
        "category, where it ships from, and the shipping defaults. They are "
        "written into the CSV as column values, so the import needs no editing "
        "afterwards."),
    "folders": (
        "Where the tools write and where the scans are read from. The batch "
        "folder holds card_pipeline.py and its outputs; the scanner folder is "
        "where the scan dialog opens. Both are used by the GUI and by the "
        "command-line tools."),
    "cs_login": (
        "The CanadianShopper session cookie from a signed-in browser. It is a "
        "live login: it is stored locally in this folder, it can change stock "
        "on that site, and it should not be shared. Refresh it when the plugin "
        "reports that authentication has expired. Without the plugin none of "
        "these controls appear and CanadianShopper stays a manual import."),
}


def settings_section(app, parent, key, title, doc=""):
    """One titled group of settings, with its own explanation button.

    The settings page is ten unrelated jobs in one form - the store address,
    the AI page, the Facebook templates, the eBay defaults, the folders - and
    one explanation for the whole page described none of them well. Each group
    now has its own heading, its own rule underneath it, and its own "What
    this panel does" button for the part it actually covers.
    """
    section = ttk.Frame(parent)
    section.pack(fill="x", pady=(0, 2))
    header = ttk.Frame(section)
    header.pack(fill="x", pady=(8, 3))
    ttk.Label(header, text=title, style="H2.TLabel").pack(side="left")
    body = ttk.Frame(section)
    body.pack(fill="x")
    if doc:
        held = ttk.Frame(section)
        label = ttk.Label(held, text=doc, style="Dim.TLabel", wraplength=740,
                          justify="left")
        label.pack(fill="x")
        open_now = key in getattr(app, "_docs_open", set())
        #  The command is bound through a lambda because toggle() is defined
        #  below it - and a button whose command is set afterwards is exactly
        #  the bug this page already had once.
        button = ttk.Button(header, text="Hide this help" if open_now else
                            "What this panel does",
                            command=lambda: toggle())

        def toggle():
            showing = key in getattr(app, "_docs_open", set())
            if showing:
                app._docs_open = (getattr(app, "_docs_open", set()) -
                                  {key})
                held.pack_forget()
                button.configure(text="What this panel does")
            else:
                app._docs_open = getattr(app, "_docs_open", set()) | {key}
                held.pack(fill="x", pady=(0, 3), before=body)
                button.configure(text="Hide this help")

        button.pack(side="right")
        if open_now:
            held.pack(fill="x", pady=(0, 3), before=body)
        app._doc_labels = list(getattr(app, "_doc_labels", [])) + [label]
        app._doc_buttons = list(getattr(app, "_doc_buttons", [])) + [button]
        section._help_frame = held
        section._doc_button = button
    ttk.Separator(section).pack(fill="x", pady=(7, 0))
    return body


def panel_note(parent, text, wraplength=780):
    """An explanation, in the panel's help area below the actions.

    Anything the panel needs to *say* goes here rather than above the buttons:
    reading is what you do after the job, not before it.
    """
    holder = getattr(parent, "_notes_frame", parent)
    label = ttk.Label(holder, text=text, style="Dim.TLabel",
                      wraplength=wraplength, justify="left")
    label.pack(anchor="w", pady=(1, 0))
    return label


class ProgressWindow:
    """A small "working..." window for a step that takes seconds.

    Splitting a high-resolution scan is slow, and the app used to do it with
    nothing on screen at all: no dialog, no bar, no change - which is exactly
    what a hung program looks like. This puts the step on screen and moves a
    bar as it goes, pumping the event loop so Windows keeps painting the
    window instead of greying it out as "Not Responding".

    It never blocks and it never fails the job: anything it cannot draw (a
    headless test run, a window that will not open) is dropped on the floor,
    because a progress display must not be able to stop the work.
    """

    def __init__(self, parent, title="Working...", text="", total=None):
        self.window = None
        self.bar = None
        self.label = None
        try:
            self.window = tk.Toplevel(parent)
            self.window.title(title)
            self.window.transient(parent)
            self.window.resizable(False, False)
            try:
                self.window.grab_set()
            except Exception:
                pass
            frame = ttk.Frame(self.window, padding=14)
            frame.pack(fill="both", expand=True)
            self.label = ttk.Label(frame, text=text or title, wraplength=420,
                                   justify="left")
            self.label.pack(anchor="w", pady=(0, 8))
            mode = "determinate" if total else "indeterminate"
            self.bar = ttk.Progressbar(frame, length=380, mode=mode,
                                       maximum=100)
            self.bar.pack(fill="x")
            self.window.geometry("+%d+%d" % self._corner(parent))
            if total:
                self.bar.configure(value=0)
            else:
                try:
                    self.bar.start(12)
                except Exception:
                    pass
            self.pump()
        except Exception:
            self.window = None

    @staticmethod
    def _corner(parent):
        """Near the middle, so it is noticed without covering the window."""
        try:
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - 440) // 2)
            y = parent.winfo_rooty() + max(0, (parent.winfo_height() - 120) // 2)
            return int(x), int(y)
        except Exception:
            return 200, 200

    def pump(self):
        """Let Tk draw and answer the OS, without entering its main loop."""
        try:
            self.window.update_idletasks()
            self.window.update()
        except Exception:
            pass

    def step(self, text=None, done=None, total=None):
        """Say what is happening now, and how far along it is."""
        if self.window is None:
            return
        try:
            if text:
                self.label.configure(text=text)
            if done is not None and total:
                self.bar.configure(mode="determinate", maximum=total,
                                   value=done)
        except Exception:
            pass
        self.pump()

    def close(self):
        try:
            if self.bar is not None:
                self.bar.stop()
        except Exception:
            pass
        try:
            if self.window is not None:
                self.window.destroy()
        except Exception:
            pass
        self.window = None


# ---- individual panel builders (parent = container frame) ----------------

def build_cookie(parent, app):
    #  Pinned: the settings page is the longest form in the app, and its Save
    #  button used to be at the very bottom of it - so saving meant scrolling
    #  past every field first. The title row goes in the strip above the page
    #  and the Save button sits on that row, so both stay put as the fields
    #  scroll underneath.
    #  No panel-wide explanation: each group below has its own, next to the
    #  fields it describes. One button for ten unrelated jobs explained none
    #  of them.
    panel_header(parent, app, "cookie", pin=True, with_doc=False)
    #  This page owns its help per section, so it starts the list afresh
    #  rather than adding to whatever the last panel left behind.
    app._doc_buttons = []
    app._doc_labels = []
    #  The sections go straight into the page. This used to add a second
    #  scroll area inside the page's own, and a nested canvas only claims the
    #  height its own widgets ask for - so the settings stopped a third of the
    #  way down the window and the rest of it sat empty above the console.
    page = ttk.Frame(parent)
    page.pack(fill="both", expand=True)
    box = page

    def group(key, title):
        """Start a section; everything packed into ``box`` after this goes in it."""
        nonlocal box
        box = settings_section(app, page, key, title,
                               SETTINGS_DOCS.get(key, ""))
        return box

    fields = {}
    app._user_setting_vars = fields
    def field_row(container, row, label, key, width=68, hint=None):
        ttk.Label(container, text=label).grid(row=row, column=0, sticky="w",
                                              padx=(0, 5), pady=1)
        var = tk.StringVar(master=container,
                           value=str(app.settings.get(key, "")))
        fields[key] = var
        ttk.Entry(container, textvariable=var, width=width).grid(
            row=row, column=1, sticky="ew", padx=2, pady=1)
        if hint:
            ttk.Label(container, text=hint, style="Dim.TLabel").grid(
                row=row + 1, column=1, sticky="w", padx=2, pady=(0, 2))
        return var

    group("startup", "When Alex Collect opens")
    startup_var = tk.StringVar(
        master=box, value=app.settings.get("startup_mode", "menu"))
    startup_row = ttk.Frame(box)
    startup_row.pack(fill="x", pady=(0, 3))
    ttk.Label(startup_row, text="Startup view:").pack(side="left")
    ttk.Combobox(startup_row, textvariable=startup_var, state="readonly",
                 values=("menu", "tabs", "wizard"), width=14).pack(
                     side="left", padx=6)

    group("store", "Store and AI")
    general = ttk.Frame(box)
    general.pack(fill="x", pady=(1, 4))
    general.columnconfigure(1, weight=1)
    store_var = field_row(general, 0, "Store name (used in AI prompts):",
                          "store_name")
    currency_prefix_var = field_row(general, 1, "Price currency prefix:",
                                    "currency_prefix", width=18)
    currency_name_var = field_row(general, 2, "Currency name:",
                                  "currency_name")
    description_words_var = field_row(
        general, 3, "Minimum AI description words:", "description_min_words",
        width=12)
    tag_count_var = field_row(general, 4, "AI tags per product:",
                              "tag_count", width=12)
    listing_context_var = field_row(
        general, 5, "AI listing-specific notes:", "listing_context")
    woo_var = field_row(general, 6, "WooCommerce site URL:", "woo_site_url",
                        hint="Example: https://shop.example.com")
    ai_var = field_row(general, 8, "AI chat page URL:", "ai_agent_url")
    browser_row = ttk.Frame(general)
    browser_row.grid(row=9, column=0, columnspan=2, sticky="ew", pady=2)
    ttk.Label(browser_row, text="Browser for webpages opened by Alex Collect:").pack(
        side="left")
    browser_choices = available_browsers()
    browser_labels = [label for _key, label in browser_choices]
    browser_labels.insert(0, "Ask me the first time")
    saved_browser = app.settings.get("browser_name", "")
    browser_value = (browser_label(saved_browser) if saved_browser else
                     "Ask me the first time")
    browser_var = tk.StringVar(master=browser_row, value=browser_value)
    ttk.Combobox(browser_row, textvariable=browser_var,
                 values=browser_labels, state="readonly", width=26).pack(
                     side="left", padx=6)
    fields["browser_name"] = browser_var
    feed_var = field_row(general, 11, "Product feed URL (optional override):",
                         "woo_feed_url")
    refresh_var = field_row(general, 12, "Feed refresh URL (optional override):",
                            "woo_feed_refresh_url")

    group("store_pages", "Open the store pages")
    row = ttk.Frame(box)
    row.pack(fill="x", pady=(0, 4))
    def open_media_page():
        if not save_user_settings():
            return
        url = site_admin_url("wp-admin/media-new.php", app.settings)
        if not url:
            messagebox.showinfo("WooCommerce site URL needed",
                                "Set and save your WooCommerce site URL first.")
            return
        app.open_webpages([url])
        output_dir = Path(app.settings.get("pipeline_dir") or str(WORK)) / "output"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            open_path(output_dir)
        except OSError as exc:
            log("could not open output image folder %s: %s" % (output_dir, exc))
    def open_ai_page():
        if not save_user_settings():
            return
        url = normalize_web_url(app.settings.get("ai_agent_url", ""))
        if not url:
            messagebox.showinfo("AI page URL needed",
                                "Set and save your AI chat page URL first.")
            return
        app.open_webpages([url])
    ttk.Button(row, text="Open WordPress media upload",
               command=open_media_page).pack(side="left")
    ttk.Button(row, text="Save & open AI page",
               command=open_ai_page).pack(side="left", padx=(6, 0))
    ttk.Button(row, text="Open WooCommerce API keys",
               command=lambda: open_woo_keys_file(app, fields["woo_site_url"].get())
               ).pack(side="left", padx=(6, 0))

    group("custom_ai", "Custom AI commands")
    custom_frame = ttk.Frame(box)
    custom_frame.pack(fill="x", pady=(0, 6))
    custom_frame.columnconfigure(1, weight=1)
    custom_items = [dict(item) for item in custom_ai_commands(app.settings)]
    custom_list = tk.Listbox(custom_frame, height=5, width=28,
                             exportselection=False)
    custom_list.grid(row=0, column=0, rowspan=5, sticky="nsw", padx=(0, 8))
    custom_name_var = tk.StringVar(master=custom_frame)
    custom_tip_var = tk.StringVar(master=custom_frame)
    ttk.Label(custom_frame, text="Button name:").grid(
        row=0, column=1, sticky="w")
    custom_name_entry = ttk.Entry(custom_frame, textvariable=custom_name_var)
    custom_name_entry.grid(row=0, column=2, sticky="ew", padx=3, pady=1)
    ttk.Label(custom_frame, text="Hover note:").grid(
        row=1, column=1, sticky="w")
    ttk.Entry(custom_frame, textvariable=custom_tip_var).grid(
        row=1, column=2, sticky="ew", padx=3, pady=1)
    ttk.Label(custom_frame, text="AI command:").grid(
        row=2, column=1, sticky="nw")
    custom_prompt_text = tk.Text(custom_frame, height=6, wrap="word")
    custom_prompt_text.grid(row=2, column=2, sticky="ew", padx=3, pady=1)
    custom_frame.columnconfigure(2, weight=1)

    def refresh_custom_list(selected=None):
        custom_list.delete(0, "end")
        for item in custom_items:
            custom_list.insert("end", item["name"])
        if selected is not None and 0 <= selected < len(custom_items):
            custom_list.selection_set(selected)
            custom_list.activate(selected)
            custom_list.see(selected)
            load_custom_item()

    def load_custom_item(_event=None):
        selection = custom_list.curselection()
        if not selection:
            return
        item = custom_items[selection[0]]
        custom_name_var.set(item["name"])
        custom_tip_var.set(item.get("tooltip", ""))
        custom_prompt_text.delete("1.0", "end")
        custom_prompt_text.insert("1.0", item["prompt"])

    def clear_custom_fields():
        custom_list.selection_clear(0, "end")
        custom_name_var.set("")
        custom_tip_var.set("")
        custom_prompt_text.delete("1.0", "end")
        custom_name_entry.focus_set()

    def save_custom_item():
        name = custom_name_var.get().strip()
        tooltip_text = custom_tip_var.get().strip()
        prompt_text = custom_prompt_text.get("1.0", "end-1c").strip()
        if not name or not prompt_text:
            messagebox.showwarning(
                "Custom command needs a name and prompt",
                "Enter a button name and the AI command text.", parent=app)
            return
        selected = custom_list.curselection()
        index = selected[0] if selected else None
        for i, item in enumerate(custom_items):
            if i != index and item["name"].casefold() == name.casefold():
                messagebox.showwarning(
                    "Duplicate command name",
                    "Each custom AI button needs a different name.", parent=app)
                return
        record = {"id": custom_items[index]["id"] if index is not None else
                         uuid.uuid4().hex,
                  "name": name,
                  "tooltip": tooltip_text or
                             "Custom AI command. Copies this command to the clipboard.",
                  "prompt": prompt_text}
        if index is None:
            custom_items.append(record)
            index = len(custom_items) - 1
        else:
            custom_items[index] = record
        refresh_custom_list(index)

    def remove_custom_item():
        selected = custom_list.curselection()
        if not selected:
            return
        index = selected[0]
        custom_items.pop(index)
        refresh_custom_list(min(index, len(custom_items) - 1)
                            if custom_items else None)
        if not custom_items:
            clear_custom_fields()

    ttk.Button(custom_frame, text="New command", command=clear_custom_fields).grid(
        row=3, column=1, sticky="w", padx=2, pady=3)
    ttk.Button(custom_frame, text="Add / update button",
               command=save_custom_item).grid(row=3, column=2, sticky="w",
                                               padx=3, pady=3)
    ttk.Button(custom_frame, text="Remove selected",
               command=remove_custom_item).grid(row=4, column=1, sticky="w",
                                                 padx=2, pady=1)
    custom_list.bind("<<ListboxSelect>>", load_custom_item)
    refresh_custom_list()
    app._custom_ai_editor = {
        "items": custom_items, "list": custom_list,
        "name": custom_name_var, "tooltip": custom_tip_var,
        "prompt": custom_prompt_text, "add": save_custom_item,
        "remove": remove_custom_item,
    }

    group("markets", "Marketplace pages")
    market = ttk.Frame(box)
    market.pack(fill="x", pady=(1, 4))
    market.columnconfigure(1, weight=1)
    field_row(market, 0, "eBay active listings URL:", "ebay_selling_url")
    #  Stock comparison reads these pages. The label says which one, because
    #  the create-a-listing page is the one a person lands on first and it has
    #  no stock on it at all.
    field_row(market, 1, "Facebook selling page URL:",
              "facebook_selling_url")
    field_row(market, 2, "CanadianShopper vendor page URL:",
              "canadianshopper_store_url")

    group("ebay", "eBay Quick List handoff")
    ebay_box = ttk.Frame(box)
    ebay_box.pack(fill="x", pady=(1, 4))
    ebay_box.columnconfigure(1, weight=1)
    ebay_quicklist_var = tk.BooleanVar(
        master=ebay_box,
        value=bool(app.settings.get("ebay_quicklist_enabled", True)))
    ttk.Checkbutton(
        ebay_box,
        text="Ask which cards to prepare for eBay after each card-listing run",
        variable=ebay_quicklist_var).grid(
            row=0, column=1, sticky="w", padx=3, pady=2)
    field_row(ebay_box, 1, "Football template URL:", "ebay_template_football_url")
    field_row(ebay_box, 2, "Baseball template URL:", "ebay_template_baseball_url")
    field_row(ebay_box, 3, "Hockey template URL:", "ebay_template_hockey_url")
    field_row(ebay_box, 4, "Basketball template URL (optional):",
              "ebay_template_basketball_url")
    field_row(ebay_box, 5, "Default template URL:", "ebay_template_default_url")
    field_row(ebay_box, 6, "Image URL base (optional):", "ebay_image_base_url")
    field_row(ebay_box, 7, "Default condition:", "ebay_default_condition")
    field_row(ebay_box, 8, "Default year:", "ebay_default_year")
    field_row(ebay_box, 9, "Default manufacturer:", "ebay_default_manufacturer")
    field_row(ebay_box, 10, "Default card number:", "ebay_default_card_number")
    field_row(ebay_box, 11, "Default player:", "ebay_default_player")
    field_row(ebay_box, 12, "Default set:", "ebay_default_set")
    field_row(ebay_box, 13, "Default grade:", "ebay_default_grade")
    field_row(ebay_box, 14, "Default autographed value:",
              "ebay_default_autographed")
    field_row(ebay_box, 15, "Fallback description:", "ebay_default_description")
    ttk.Label(ebay_box, text=(
        "The eBay helper gathers copyable/draggable listing details and opens "
        "the selected sport template(s). It does not submit or publish listings."),
        style="Dim.TLabel", wraplength=720, justify="left").grid(
            row=16, column=1, sticky="w", padx=3, pady=(0, 3))

    group("facebook", "Facebook Marketplace export fields")
    facebook_box = ttk.Frame(box)
    facebook_box.pack(fill="x", pady=(1, 4))
    facebook_box.columnconfigure(1, weight=1)
    field_row(facebook_box, 0, "Title template:",
              "facebook_feed_title_template")
    field_row(facebook_box, 1, "Price template:",
              "facebook_feed_price_template", width=28)
    field_row(facebook_box, 2, "Condition:", "facebook_feed_condition",
              width=28)
    field_row(facebook_box, 3, "Category:", "facebook_feed_category")
    field_row(facebook_box, 4, "Product ID template:",
              "facebook_feed_id_template", width=40)
    field_row(facebook_box, 5, "Image URL template:",
              "facebook_feed_image_link_template", width=60)
    ttk.Label(facebook_box, text="Description template:").grid(
        row=6, column=0, sticky="nw", padx=(0, 6), pady=2)
    description_template = tk.Text(facebook_box, height=4, wrap="word")
    description_template.grid(row=6, column=1, sticky="ew", padx=3, pady=2)
    description_template.insert(
        "1.0", str(app.settings.get("facebook_feed_description_template", "")))
    fields["facebook_feed_description_template"] = description_template
    ttk.Label(facebook_box, text=(
        "Placeholders: {title}, {description}, {product_url}, {price}, {id}, "
        "{image_link}. Leave Price template as {price} to use the live-feed "
        "price."), style="Dim.TLabel",
        wraplength=720, justify="left").grid(
            row=7, column=1, sticky="w", padx=3, pady=(0, 3))

    group("cs_csv", "CanadianShopper CSV defaults")
    cs_config = ttk.Frame(box)
    cs_config.pack(fill="x", pady=(1, 4))
    cs_config.columnconfigure(1, weight=1)
    field_row(cs_config, 0, "Category:", "canadianshopper_category")
    field_row(cs_config, 1, "Ship-from province/region:",
              "canadianshopper_ship_from_province", width=16)
    field_row(cs_config, 2, "Flat shipping amount:",
              "canadianshopper_shipping_flat", width=16)
    cs_free_var = tk.BooleanVar(
        master=cs_config,
        value=bool(app.settings.get("canadianshopper_free_shipping", False)))
    ttk.Checkbutton(cs_config, text="Offer free shipping by default",
                    variable=cs_free_var).grid(row=3, column=1, sticky="w",
                                               padx=3, pady=2)
    field_row(cs_config, 4, "Handling days:",
              "canadianshopper_handling_days", width=16)
    field_row(cs_config, 5, "Transit days:",
              "canadianshopper_transit_days", width=16)

    group("folders", "Working folders")
    grid = ttk.Frame(box)
    grid.pack(fill="x", pady=(1, 4))
    grid.columnconfigure(1, weight=1)
    app._pipeline_var = tk.StringVar(
        master=grid, value=app.settings.get("pipeline_dir", str(WORK)))
    app._scan_var = tk.StringVar(
        master=grid, value=app.settings.get("scan_dir", DEFAULT_SCAN_DIR))
    fields["pipeline_dir"] = app._pipeline_var
    fields["scan_dir"] = app._scan_var
    for r, (label, var) in enumerate((
            ("Batch folder (card_pipeline.py):", app._pipeline_var),
            ("Scanner folder:", app._scan_var))):
        ttk.Label(grid, text=label).grid(row=r, column=0, sticky="w",
                                         padx=(0, 6), pady=2)
        ttk.Entry(grid, textvariable=var).grid(row=r, column=1, sticky="ew",
                                               padx=3, pady=2)
        def browse_dir(v=var, initial=WORK if r == 0 else Path.home()):
            directory = filedialog.askdirectory(initialdir=v.get() or str(initial))
            if directory:
                v.set(directory)
        ttk.Button(grid, text="Browse...", command=browse_dir).grid(
            row=r, column=2, padx=(3, 0))

    def setting_value(key):
        widget = fields[key]
        if isinstance(widget, tk.Text):
            return widget.get("1.0", "end-1c").strip()
        return widget.get().strip()

    def save_user_settings():
        template_keys = (
            "facebook_feed_title_template", "facebook_feed_price_template",
            "facebook_feed_description_template", "facebook_feed_id_template",
            "facebook_feed_image_link_template")
        allowed_placeholders = {
            "title", "description", "product_url", "price", "id", "image_link"
        }
        for key in template_keys:
            template = setting_value(key)
            try:
                found = {
                    field.split(".", 1)[0].split("[", 1)[0]
                    for _literal, field, _format, _conversion
                    in string.Formatter().parse(template) if field
                }
            except ValueError:
                found = {"<invalid>"}
            unknown = found - allowed_placeholders
            if unknown:
                messagebox.showwarning(
                    "Invalid Facebook feed template",
                    "%s uses unsupported placeholder(s): %s.\n\nUse only: "
                    "{title}, {description}, {product_url}, {price}, {id}, "
                    "{image_link}." % (key, ", ".join(sorted(unknown)))
                )
                return False

        url_keys = ("woo_site_url", "ai_agent_url", "woo_feed_url",
                    "woo_feed_refresh_url", "ebay_selling_url",
                    "ebay_template_football_url", "ebay_template_baseball_url",
                    "ebay_template_hockey_url", "ebay_template_basketball_url",
                    "ebay_template_default_url", "ebay_image_base_url",
                    "facebook_selling_url", "canadianshopper_store_url")
        normalized = {}
        for key in url_keys:
            value = fields[key].get().strip()
            if value:
                value = normalize_web_url(value)
                if not value:
                    messagebox.showwarning(
                        "Invalid URL", "Check the URL in the %s field. "
                        "Use an http:// or https:// web address." % key.replace(
                            "_", " "))
                    return False
            normalized[key] = value
        for key, value in normalized.items():
            app.settings[key] = value
        app.settings["startup_mode"] = startup_var.get()
        browser_display = setting_value("browser_name")
        app.settings["browser_name"] = next(
            (key for key, label in available_browsers()
             if label == browser_display), "")
        for key in (
                "facebook_feed_title_template", "facebook_feed_price_template",
                "facebook_feed_condition", "facebook_feed_description_template",
                "facebook_feed_category", "facebook_feed_id_template",
                "facebook_feed_image_link_template"):
            app.settings[key] = setting_value(key)
        for key in (
                "ebay_default_condition", "ebay_default_year",
                "ebay_default_manufacturer", "ebay_default_card_number",
                "ebay_default_player", "ebay_default_set",
                "ebay_default_grade", "ebay_default_autographed",
                "ebay_default_description"):
            app.settings[key] = setting_value(key)
        app.settings["ebay_quicklist_enabled"] = ebay_quicklist_var.get()
        if hasattr(app, "_mode_var"):
            app._mode_var.set(startup_var.get())
        app.settings["store_name"] = store_var.get().strip()
        app.settings["currency_prefix"] = currency_prefix_var.get().strip() or "$"
        app.settings["currency_name"] = currency_name_var.get().strip() or "your currency"
        try:
            description_words = int(description_words_var.get().strip())
            tag_count = int(tag_count_var.get().strip())
            if description_words <= 0 or tag_count <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                "Invalid AI prompt settings",
                "Description word count and tag count must be positive whole numbers.")
            return False
        app.settings["description_min_words"] = description_words
        app.settings["tag_count"] = tag_count
        app.settings["listing_context"] = listing_context_var.get().strip()
        app.settings["custom_ai_commands"] = [dict(item)
                                              for item in custom_items]
        try:
            shipping = float(fields["canadianshopper_shipping_flat"].get().strip())
            handling = int(fields["canadianshopper_handling_days"].get().strip())
            transit = int(fields["canadianshopper_transit_days"].get().strip())
            if shipping < 0 or handling < 0 or transit < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                "Invalid shipping defaults",
                "Shipping must be a non-negative amount; handling and transit "
                "days must be non-negative whole numbers.")
            return False
        app.settings["canadianshopper_shipping_flat"] = "%.2f" % shipping
        app.settings["canadianshopper_handling_days"] = handling
        app.settings["canadianshopper_transit_days"] = transit
        app.settings["canadianshopper_free_shipping"] = cs_free_var.get()
        app.settings["canadianshopper_category"] = fields[
            "canadianshopper_category"].get().strip()
        app.settings["canadianshopper_ship_from_province"] = fields[
            "canadianshopper_ship_from_province"].get().strip()
        app.settings["pipeline_dir"] = app._pipeline_var.get().strip() or str(WORK)
        app.settings["scan_dir"] = app._scan_var.get().strip() or DEFAULT_SCAN_DIR
        save_settings(app.settings)
        sync_site_url_to_woo_keys(app.settings["woo_site_url"])
        app.console_line("User settings saved.", "ok")
        return True

    app._save_user_settings_callback = save_user_settings
    #  Beside the title, not at the end of the form: everything above this
    #  line is the page the button applies to. In the wizard, where the title
    #  row is not pinned, it stays the plain button under the fields.
    title_row = getattr(parent, "_title_row", None)
    save_button = ttk.Button(title_row if title_row is not None else box,
                             text="Save user settings",
                             command=save_user_settings,
                             style="Task.TButton")
    if title_row is not None:
        save_button.pack(side="right", padx=(0, 6))
    else:
        save_button.pack(anchor="w", pady=(1, 4))
    add_tooltip(save_button, tip_for("Save user settings"))
    app._save_button = save_button

    if app.cs_addon:
        group("cs_login", "CanadianShopper connection")
        ttk.Label(box, text="Session cookie (private login; stored locally):"
                  ).pack(anchor="w", pady=(2, 0))
        txt = tk.Text(box, height=3, wrap="char", font=("Consolas", 9))
        txt.pack(fill="x", pady=4)

        def test_cookie():
            app.console_line("Testing the CanadianShopper connection...", "cmd")
            def work():
                ok, msg = test_connection()
                try:
                    app.after(0, lambda: (
                        app.console_line(msg, "ok" if ok else "err"),
                        messagebox.showinfo("Connection", msg) if ok else
                        messagebox.showwarning("Connection", msg)))
                except RuntimeError:
                    log("connection test finished (%s): %s" %
                        ("ok" if ok else "failed", msg))
            threading.Thread(target=work, daemon=True).start()

        def save_cookie():
            raw = txt.get("1.0", "end").strip()
            if not raw:
                messagebox.showinfo("Nothing pasted",
                                    "Paste the cookie value or whole row first.")
                return
            cookie = clean_cookie_row(raw)
            if not cookie or len(cookie) < 20:
                messagebox.showwarning(
                    "Does not look like a cookie",
                    "Copy the Value of __Secure-better-auth.session_token.")
                return
            CS_COOKIE_FILE.write_text(cookie + "\n", encoding="utf-8")
            log("cookie.txt saved (%d chars)" % len(cookie))
            txt.delete("1.0", "end")
            test_cookie()

        cookie_row = ttk.Frame(box)
        cookie_row.pack(fill="x", pady=(0, 6))
        ttk.Button(cookie_row, text="Save cookie", command=save_cookie).pack(
            side="left")
        ttk.Button(cookie_row, text="Test connection", command=test_cookie).pack(
            side="left", padx=6)
    else:
        ttk.Label(box, text="CanadianShopper cookie controls appear when the "
                  "optional plugin is installed.", style="Dim.TLabel").pack(
                      anchor="w", pady=(4, 8))


def in_background(app, work, done):
    """Run a slow call off the window thread, then draw with its answer.

    A website read can take a few seconds, and doing it inline froze the whole
    window - which on Windows is painted as "Not Responding" and reads as a
    hung program. The work runs on a daemon thread and its result (or its
    error) comes back through ``app.after``, so every Tk call still happens on
    the thread that owns the widgets.
    """
    def runner():
        try:
            result, error = work(), None
        except Exception as exc:      # the caller draws the message
            result, error = None, exc
        try:
            app.after(0, lambda: done(result, error))
        except Exception:
            #  The window was closed while the call was out; there is nobody
            #  left to draw for, and a progress display must never be able to
            #  turn a finished read into a traceback in the log.
            pass

    threading.Thread(target=runner, daemon=True).start()


def open_market_cookie(app, site_id):
    """Create/open the private cookie file for eBay or Facebook.

    The file is a paste target, not a form: the shipped lines explain what to
    copy, and every line starting with '#' is ignored when it is read, so the
    explanation cannot end up inside the cookie.
    """
    info = market_stock.SITES[site_id]
    path = BASE / info["cookie"]
    if not path.exists():
        path.write_text(
            "# Paste your %s session cookie below, then save this file.\n"
            "#\n"
            "# A signed-in site sends MANY cookies, not one - paste all of them.\n"
            "# In the browser: sign in, press F12, open the Network tab, reload\n"
            "# the page, click the page request itself, and copy the whole value\n"
            "# of the 'Cookie' request header. It is one long line of\n"
            "# name=value pairs separated by semicolons; paste it as it is.\n"
            "#\n"
            "# Several lines work too: each is joined into the same header, and a\n"
            "# line may start with 'Cookie:' - that part is removed for you.\n"
            "#\n"
            "# Lines starting with # are ignored, so this explanation is safe to\n"
            "# leave in place. The file stays on this computer and is never\n"
            "# included in the app or in a report.\n" % info["label"],
            encoding="utf-8")
    restrict_file_permissions(path)
    open_path(path)
    app.console_line("Opened the private %s cookie file; keep it out of public "
                     "repos and messages." % info["label"], "dim")


def open_woo_keys_file(app, current_site_url=""):
    """Create/open the local Woo REST-key file without exposing keys in GUI."""
    path = BASE / "woo-keys.txt"
    if not path.exists():
        example = BASE / "woo-keys.txt.example"
        if example.exists():
            text = example.read_text(encoding="utf-8")
            site = normalize_web_url(current_site_url)
            if site:
                text = text.replace("https://your-store.example", site, 1)
            path.write_text(text, encoding="utf-8")
        else:
            path.write_text((normalize_web_url(current_site_url) or "") +
                            "\nck_replace_with_your_consumer_key\n"
                            "cs_replace_with_your_consumer_secret\n"
                            "# Optional lines 4 and 5 for uploading photos:\n"
                            "wp_replace_with_your_wordpress_username\n"
                            "wp_replace_with_your_application_password\n",
                            encoding="utf-8")
    # Credentials belong to this Windows account only.
    restrict_file_permissions(path)
    open_path(path)
    app.console_line("Opened private WooCommerce credentials file; keep it "
                     "out of public repos and messages.", "dim")


class CreateProductsDialog(tk.Toplevel):
    """Asks whether this batch's cards become products on the website.

    The answer is one of ``"draft"``, ``"publish"`` or ``"none"``; closing the
    window answers ``None``, which cancels the batch instead of quietly
    choosing for the user.
    """

    def __init__(self, parent, site, keys_ready, cards=None):
        super().__init__(parent)
        self.answer = None
        self.title("Create the products on your website?")
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.grab_set()
        box = ttk.Frame(self, padding=(12, 10))
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="The cards become products on your website",
                  style="H2.TLabel").pack(anchor="w")
        site_text = site or "your website"
        if cards:
            what = "This batch's %d card%s" % (cards, "" if cards == 1 else "s")
        else:
            what = "This batch's cards"
        ttk.Label(box, text=(
            "%s can be created directly on %s, without "
            "WP All Import.\n\n"
            "Each product is made as an UNPUBLISHED DRAFT with its front and "
            "back photos uploaded first, and every one is read back from the "
            "site before it is reported as created. A card whose SKU is "
            "already there is skipped, so running the same batch twice never "
            "duplicates it.\n\n"
            "The WooCommerce CSV is written either way: it stays the record, "
            "the WP All Import fallback, and what the Facebook and "
            "CanadianShopper steps read."
            % (what, site_text)),
            wraplength=620, justify="left").pack(anchor="w", pady=(4, 0))
        if not keys_ready:
            ttk.Label(box, text=(
                "No WooCommerce keys are saved yet, so nothing can be created "
                "until they are in woo-keys.txt."),
                wraplength=620, justify="left",
                foreground="#b26a00").pack(anchor="w", pady=(6, 0))
        self.choice = tk.StringVar(master=self, value="draft"
                                   if keys_ready else "none")
        for value, text, tip in (
                ("draft", "Create them as drafts - I will publish when ready",
                 "Safest choice: the products are unpublished, so the shop "
                 "never shows a card before its photos and price are right."),
                ("publish", "Create them and put them on sale once the photos "
                            "are on",
                 "Only products whose front/back photos uploaded are put on "
                 "sale; one without photos stays a draft and the report says "
                 "why."),
                ("none", "Only build the CSV - no products are created",
                 "Use WP All Import as before. Nothing is written to the "
                 "website.")):
            row = ttk.Frame(box)
            row.pack(anchor="w", pady=(6, 0))
            button = ttk.Radiobutton(row, text=text, value=value,
                                     variable=self.choice)
            button.pack(side="left")
            add_tooltip(button, tip)
        ttk.Label(box, text=(
            "Publishing is always a second step, after the photos land: a "
            "product is never put on sale with an empty gallery."),
            style="Dim.TLabel", wraplength=620,
            justify="left").pack(anchor="w", pady=(8, 0))
        buttons = ttk.Frame(box)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Not now",
                   command=self.destroy).pack(side="right")
        go = ttk.Button(buttons, text="Continue", style="Task.TButton",
                        command=self.accept)
        go.pack(side="right", padx=(0, 8))
        add_tooltip(go, "Start the batch with the choice selected above; "
                        "nothing has been written to your website yet")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        attach_tooltips(self)

    def accept(self):
        self.answer = self.choice.get()
        self.destroy()


def ask_create_products(app, cards=None):
    """Ask about creating this batch on the website; None means don't run.

    Missing keys are put in front of the user instead of falling back to the
    CSV silently: the keys file is opened, and the answer is waiting for them
    when they come back.
    """
    site, key, secret = read_woo_credentials(BASE / "woo-keys.txt")
    ready = bool(site and key and secret)
    if not ready:
        enter = messagebox.askyesno(
            "Enter your WooCommerce keys?",
            "Alex Collect can create this batch's products directly on your "
            "website.\n\n"
            "That needs the WooCommerce keys in woo-keys.txt (lines 1-3), and "
            "the WordPress username and Application Password (lines 4-5) so "
            "the front and back photos upload with each product.\n\n"
            "Enter them now? Answer No to build only the CSV, which WP All "
            "Import can still use.", parent=app)
        if not enter:
            return "none"
        open_woo_keys_file(app, app.settings.get("woo_site_url", ""))
        messagebox.showinfo(
            "Save the keys, then continue",
            "woo-keys.txt is open. Fill in the site address, the consumer key "
            "and secret, and - if the photos should upload - the WordPress "
            "username and Application Password. Save the file, then continue.",
            parent=app)
        site, key, secret = read_woo_credentials(BASE / "woo-keys.txt")
        ready = bool(site and key and secret)
        if not ready:
            only_csv = messagebox.askyesno(
                "The keys are still missing",
                "woo-keys.txt does not hold a complete key pair yet, so no "
                "product can be created.\n\n"
                "Build the CSV only for now?", parent=app)
            return "none" if only_csv else None
    dialog = CreateProductsDialog(app, site, ready, cards)
    app.wait_window(dialog)
    return dialog.answer


def build_pipeline(parent, app):
    panel_header(parent, app, "pipeline")
    box = ttk.Frame(parent)
    box.pack(fill="x")
    pdir = app.settings.get("pipeline_dir", str(WORK))
    ttk.Label(box, text="Batch folder: %s" % pdir, style="Dim.TLabel").pack(
        anchor="w")

    def browse_for_pipeline():
        f = filedialog.askopenfilename(
            title="Find card_pipeline.py",
            initialdir=app.settings.get("pipeline_dir") or str(BASE))
        if not f:
            return None
        f = Path(f)
        if f.name != "card_pipeline.py":
            messagebox.showwarning(
                "Wrong file",
                "That is %s - I need the file named card_pipeline.py."
                % f.name)
            return None
        app.set_setting("pipeline_dir", str(f.parent))
        app.console_line("Batch folder set to %s" % f.parent, "ok")
        return f

    def run_pipeline():
        script = find_pipeline_script(app.settings)
        if script is None:
            if messagebox.askyesno(
                    "card_pipeline.py not found",
                    "I could not find card_pipeline.py in the batch "
                    "folder\n%s\n\nBrowse for it now?"
                    % app.settings.get("pipeline_dir", "")):
                script = browse_for_pipeline()
            if script is None:
                return

        def on_run(args, on_done, title):
            return app.run_tool(str(script), args, title,
                                cwd=str(script.parent), on_done=on_done)
        PipelineDialog(app, script, on_run)

    ttk.Button(box, text="Run the card pipeline", style="Task.TButton",
               command=run_pipeline).pack(anchor="w", pady=4)
    if app.cs_addon:
        ttk.Label(box, text="CanadianShopper drafts", style="H2.TLabel").pack(
            anchor="w", pady=(6, 1))
        _build_draft_publisher_controls(box, app)

    def run_feed_updater():
        feed = BASE / "pipeline" / "facebook_merchant_products" / \
            "facebook_feed.py"
        if not feed.is_file():
            messagebox.showinfo(
                "Not shipped",
                "facebook_feed.py is not in app\\pipeline\\"
                "facebook_merchant_products\\ - it builds the Marketplace "
                "delta xlsx from the live feed.")
            return
        app.run_tool(str(feed), [], "Facebook feed updater",
                     cwd=str(feed.parent))

    row_fb = ttk.Frame(box)
    row_fb.pack(anchor="w", pady=(2, 0))
    ttk.Button(row_fb, text="Run the Facebook feed updater",
               command=run_feed_updater).pack(side="left")
    ttk.Label(box, text="For AFTER the new cards are live on your "
               "website: it fetches the feed, diffs it against the "
               "history, and writes facebook_delta_<date>.xlsx for the "
               "Marketplace upload. Answer its Enter prompt in the "
               "console. The xlsx lands in app\\pipeline\\"
               "facebook_merchant_products (Logs panel has a shortcut).",
               style="Dim.TLabel", wraplength=680,
               justify="left").pack(anchor="w")
    ttk.Label(box, text="For a new batch: choose the FRONT scan and optional "
               "BACK scan. Alex Collect opens your saved AI page and copies "
               "the selected prompt; upload the scans and paste it manually. "
               "When you copy the complete reply, the app asks whether to "
               "split and build or split only.",
               style="Dim.TLabel", wraplength=680, justify="left").pack(
                   anchor="w")
    ttk.Label(box, text="Before it runs, it asks what to do with the "
               "products. With your WooCommerce keys saved it creates them "
               "straight on your website - drafts first, front and back "
               "photos uploaded with each one, and a card whose SKU is "
               "already there is skipped. Put them on sale as they are "
               "created, or leave them as drafts and publish when the price "
               "and photos look right. Without the keys it offers to open "
               "woo-keys.txt instead of quietly leaving you at the CSV.",
               style="Dim.TLabel", wraplength=680, justify="left").pack(
                   anchor="w", pady=(2, 0))
    next_steps = ("Next: combine pending batches if needed, stage the photos, "
                  "confirm the CanadianShopper draft import, then answer the "
                  "pipeline's v/y/n draft prompt (or use the controls above). "
                  "The CSV stays the record either way." if app.cs_addon else
                  "Next: combine pending batches if needed, then review and "
                  "publish what was created (or import the CSV with WP All "
                  "Import). Photo staging and back-photo wiring require the "
                  "CanadianShopper plugin.")
    ttk.Label(box, text=next_steps, style="Dim.TLabel", wraplength=680,
              justify="left").pack(anchor="w", pady=(4, 0))


def build_combine(parent, app):
    panel_header(parent, app, "combine")
    box = ttk.Frame(parent)
    box.pack(fill="x")

    def go(dry):
        app.run_tool("combine-cs-csvs.py", ["--dry-run"] if dry else [],
                     "Combine import CSVs" + (" (preview)" if dry else ""),
                     cwd=app.settings.get("pipeline_dir", str(WORK)))

    row = ttk.Frame(box)
    row.pack(anchor="w", pady=4)
    ttk.Button(row, text="Preview (--dry-run)", command=lambda: go(True)).pack(
        side="left")
    ttk.Button(row, text="Combine now", command=lambda: go(False)).pack(
        side="left", padx=8)
    ttk.Button(box, text="Open the batch folder",
               command=lambda: open_path(app.settings.get("pipeline_dir",
                                                          WORK))).pack(
        anchor="w")


def _rerun_input_for(app, script, choose=False):
    """The AI reply a re-run should reuse; asks for a file when none exists."""
    text = None if choose else newest_ai_text(app, script)
    if text is None:
        picked = filedialog.askopenfilename(
            title="Which AI listing text should the re-run use?",
            initialdir=str(script.parent),
            filetypes=[("AI listing text", "*.txt"), ("All files", "*.*")],
            parent=app)
        if not picked:
            messagebox.showinfo(
                "Re-run cancelled",
                "This step rebuilds a CSV from the AI reply used for the "
                "batch.\n\nRun the card pipeline once (it saves "
                "_card_input.txt beside card_pipeline.py), or press the "
                "button again and choose the text file.", parent=app)
            return None
        text = Path(picked)
    return text


def _rerun_market(app, market, input_path=None):
    """Start `card_pipeline.py rerun --market <market>` for one marketplace."""
    label = MARKET_RERUNS[market][0]
    script = find_pipeline_script(app.settings)
    if script is None:
        messagebox.showwarning(
            "Batch folder not found",
            "I could not find card_pipeline.py. Set your batch folder in "
            "User settings, then try this button again.", parent=app)
        return
    args = ["rerun", "--market", market]
    if market in RERUN_NEEDS_CARDS:
        text = input_path or _rerun_input_for(app, script)
        if text is None:
            return
        args += ["--input", str(text)]
    if market == "woocommerce":
        #  This button rebuilds the CSV. Creating the products from it is an
        #  extra that is only offered once the keys are there - asking a
        #  person to set up keys for a CSV rebuild would be the app mistaking
        #  what they pressed. The batch itself still asks every time.
        site, key, secret = read_woo_credentials(BASE / "woo-keys.txt")
        choice = "none" if not (site and key and secret) \
            else ask_create_products(app)
        if choice is None:
            return
        args += {
            "draft": ["--create-products", "--draft-products", "--confirmed"],
            "publish": ["--create-products", "--publish-products",
                        "--confirmed"],
            "none": ["--no-create-products", "--confirmed"],
        }[choice]
    app.run_tool(str(script), args, "Re-run: " + label,
                 cwd=str(script.parent))


def build_markets(parent, app):
    panel_header(parent, app, "markets")
    box = ttk.Frame(parent)
    box.pack(fill="x")
    chosen = {"path": None}

    status = ttk.Label(box, text="", style="Dim.TLabel", wraplength=780,
                       justify="left")
    status.pack(anchor="w", pady=(0, 4))

    def refresh():
        path = chosen["path"]
        if path is None or not Path(path).is_file():
            found = newest_ai_text(app)
            path = str(found) if found else None
            chosen["path"] = path
        status.config(text=(
            "AI listing text for re-runs: %s" % path if path else
            "No AI listing text found yet. The CSV re-runs will ask for the "
            "file; run the card pipeline once and it saves _card_input.txt "
            "beside card_pipeline.py."))

    def choose():
        script = find_pipeline_script(app.settings)
        if script is None:
            messagebox.showwarning(
                "Batch folder not found",
                "I could not find card_pipeline.py. Set your batch folder "
                "in User settings, then try again.", parent=app)
            return
        text = _rerun_input_for(app, script, choose=True)
        if text is not None:
            chosen["path"] = str(text)
            refresh()

    row = ttk.Frame(box)
    row.pack(anchor="w", pady=2)
    for index, market in enumerate(MARKET_RERUNS):
        label, tip = MARKET_RERUNS[market]
        button = ttk.Button(row, text=label,
                            command=lambda m=market: _rerun_market(
                                app, m, chosen["path"]))
        button.pack(side="left", padx=(0 if index == 0 else 6, 0))
        add_tooltip(button, tip)

    tools = ttk.Frame(box)
    tools.pack(anchor="w", pady=(6, 2))
    ttk.Button(tools, text="Choose a different AI text...",
               command=choose).pack(side="left")
    ttk.Button(tools, text="Open the batch folder",
               command=lambda: open_path(app.settings.get("pipeline_dir",
                                                          str(WORK)))
               ).pack(side="left", padx=8)
    ttk.Label(box, text="Images are never moved or renamed here, and the "
              "marketplace you do not choose is left untouched.",
              style="Dim.TLabel", wraplength=780,
              justify="left").pack(anchor="w", pady=(4, 0))
    refresh()


def canadianshopper_results_dir(app):
    return Path(app.settings.get("pipeline_dir") or str(WORK)) / "canadianshopper_products"


def canadianshopper_ready_dir(app):
    return canadianshopper_results_dir(app) / "cs-ready"


def canadianshopper_cache_path(app):
    return canadianshopper_results_dir(app) / "cs-image-cache.json"


def _build_draft_publisher_controls(parent, app):
    """Embed the preview/apply controls wherever the CS pipeline is shown."""
    report = canadianshopper_results_dir(app) / "cs-publish-report.csv"

    def run_publisher(apply=False):
        args = ["--cookie-file", str(CS_COOKIE_FILE), "--report", str(report)]
        confirm = None
        title = "Preview CanadianShopper drafts"
        if apply:
            args.append("--apply")
            title = "Publish ready CanadianShopper drafts"
            confirm = (
                "Scan your CanadianShopper drafts and offer to activate only "
                "products that pass all readiness checks?\n\nNothing is "
                "activated unless you also type PUBLISH in the output console.")
        app.run_tool("cs-publish-drafts.py", args, title,
                     cwd=app.settings.get("pipeline_dir", str(WORK)),
                     confirm=confirm)

    publish_row = ttk.Frame(parent)
    publish_row.pack(anchor="w", pady=(2, 2))
    preview_button = ttk.Button(
        publish_row, text="Preview drafts",
        command=lambda: run_publisher(False))
    preview_button.pack(side="left")
    add_tooltip(preview_button,
                "Read the vendor's drafts and write a readiness report; no products change.")
    publish_button = ttk.Button(
        publish_row, text="Publish ready drafts",
        command=lambda: run_publisher(True))
    publish_button.pack(side="left", padx=(6, 0))
    add_tooltip(publish_button,
                "Two confirmations are required. Only drafts passing every readiness check are activated.")
    ttk.Button(parent, text="Open the publish report",
               command=lambda: open_path(report) if report.is_file() else
               messagebox.showinfo("No report yet",
                                   "Preview drafts first to create the report.",
                                   parent=app)).pack(anchor="w", pady=(1, 0))


def consolidate_cs_staged_history(ready_dir, current_csvs, app):
    try:
        pipeline_tools = str(BASE / "pipeline")
        if pipeline_tools not in sys.path:
            sys.path.insert(0, pipeline_tools)
        from output_history import consolidate_csv_history
        result = consolidate_csv_history(
            ready_dir, "canadianshopper_import_*.csv",
            "canadianshopper_staged_history.csv",
            exclude_paths=current_csvs, key_fields=("title",))
        if result["files"]:
            app.console_line(
                "Staged CS history updated: %s (%d rows); removed %d old file(s)." %
                (result["history"], result["rows"], result["deleted"]), "ok")
        return result
    except Exception as exc:
        app.console_line("Could not consolidate older staged CSVs: %s" % exc, "err")
        app.console_line("Older files were kept; the current batch remains separate.", "dim")
        return None


def build_stage(parent, app):
    panel_header(parent, app, "stage")
    box = ttk.Frame(parent)
    box.pack(fill="x")

    def go():
        results = canadianshopper_results_dir(app)
        ready = canadianshopper_ready_dir(app)
        sources = sorted(results.glob("canadianshopper_import_*.csv"))
        if not sources:
            messagebox.showinfo(
                "No CanadianShopper batch",
                "Run the card pipeline first. Its current CSV batch will be "
                "saved in %s." % results, parent=app)
            return
        args = ["--mode", "prepare", "-y",
                "--cookie-file", str(CS_COOKIE_FILE),
                "--ready-dir", str(ready),
                "--cache", str(canadianshopper_cache_path(app)),
                "--report", str(results / "cs-image-report.csv")]
        for source in sources:
            args += ["--csv", str(source)]
        app.run_tool(TOOL_ACTION(CS_PHOTO_STAGE) or "cs-image-sync.py",
                     args, "Stage the photos",
                     cwd=app.settings.get("pipeline_dir", str(WORK)),
                     on_done=lambda rc: rc == 0 and _after_stage(sources))

    def _after_stage(sources):
        ready = canadianshopper_ready_dir(app)
        staged = [ready / source.name for source in sources
                  if (ready / source.name).is_file()]
        if not staged:
            app.console_line("Staging finished but no current CSVs were found in %s." % ready,
                             "err")
            return
        consolidate_cs_staged_history(ready, staged, app)
        app.console_line(
            "Staged. Next: import the current CSV batch from %s on the website, "
            "then come back and press Wire." % ready, "ok")

    row = ttk.Frame(box)
    row.pack(anchor="w", pady=4)
    ttk.Button(row, text="Stage the photos (square + host + rewrite CSVs)",
               style="Task.TButton", command=go).pack(side="left")
    ttk.Button(box, text="Open the cs-ready folder",
               command=lambda: open_path(canadianshopper_ready_dir(app))).pack(
                   anchor="w")
    ttk.Label(box, text="Cookie expired? The tool will ask right in the "
              "console - paste the answer there, or save it in the "
              "Connection panel first.", style="Dim.TLabel").pack(
                  anchor="w", pady=(4, 0))


def build_importpanel(parent, app):
    panel_header(parent, app, "importpanel")
    box = ttk.Frame(parent)
    box.pack(fill="x")
    row = ttk.Frame(box)
    row.pack(anchor="w", pady=4)
    ttk.Button(row, text="Open canadianshopper.ca",
               command=lambda: app.open_webpages([CS_HOME])).pack(side="left")
    ttk.Button(row, text="Open the cs-ready folder",
               command=lambda: open_path(canadianshopper_ready_dir(app))).pack(
                   side="left", padx=8)
    if getattr(app, "cs_addon", True):
        _build_draft_publisher_controls(box, app)
        ttk.Label(box, text=(
            "Preview changes nothing. Publishing uses the saved "
            "CanadianShopper cookie and requires the app confirmation plus "
            "typing PUBLISH in the console."),
            style="Dim.TLabel", wraplength=700, justify="left").pack(
                anchor="w", pady=(4, 0))
    else:
        ttk.Label(box, text="Photo staging and back-photo wiring are "
                  "provided by the CanadianShopper add-on. Until it is "
                  "installed, upload CSVs and photos in the website dashboard.",
                  style="Dim.TLabel", wraplength=640,
                  justify="left").pack(anchor="w", pady=(6, 0))


def build_wire(parent, app):
    panel_header(parent, app, "wire")
    box = ttk.Frame(parent)
    box.pack(fill="x")

    def go(dry):
        results = canadianshopper_results_dir(app)
        args = ["--mode", "wire", "--cookie-file", str(CS_COOKIE_FILE),
                "--ready-dir", str(canadianshopper_ready_dir(app)),
                "--cache", str(canadianshopper_cache_path(app))]
        if dry:
            args.append("--dry-run")
        app.run_tool(TOOL_ACTION(CS_PHOTO_WIRE) or "cs-image-sync.py", args,
                     "Wire the photos" + (" - DRY RUN" if dry else ""),
                     cwd=app.settings.get("pipeline_dir", str(WORK)),
                     confirm=None if dry else
                     "Attach the hosted front + back gallery photos to the "
                     "listings you just imported?\n\nRun the Dry-run first "
                     "if you have not seen the plan yet.")

    row = ttk.Frame(box)
    row.pack(anchor="w", pady=4)
    ttk.Button(row, text="Dry-run (writes nothing)", command=lambda: go(True)
               ).pack(side="left")
    ttk.Button(row, text="Wire for real", command=lambda: go(False)).pack(
        side="left", padx=8)
    rep = first_existing(canadianshopper_results_dir(app) / "cs-image-report.csv",
                         BASE / "cs-image-report.csv",
                         WORK / "cs-image-report.csv")
    if rep:
        ttk.Button(box, text="Open the report (cs-image-report.csv)",
                   command=lambda: open_path(rep)).pack(anchor="w")
    ttk.Label(box, text="ok = attached | skip = already right | unmatched = "
              "title not found (check spelling) | no-back = no back photo "
              "staged", style="Dim.TLabel").pack(anchor="w", pady=(4, 0))


def build_rerun(parent, app):
    panel_header(parent, app, "rerun")
    box = ttk.Frame(parent)
    box.pack(fill="x")

    def go(dry):
        results = canadianshopper_results_dir(app)
        args = ["--mode", "upload", "--repoint-cache", "--images", "front,back",
                "--cookie-file", str(CS_COOKIE_FILE),
                "--cache", str(canadianshopper_cache_path(app)),
                "--report", str(results / "cs-repoint-report.csv")]
        if dry:
            args.append("--dry-run")
        app.run_tool("pad-and-upload.py", args,
                     "CanadianShopper: Re-point photos" +
                     (" - DRY RUN" if dry else ""),
                     cwd=app.settings.get("pipeline_dir", str(WORK)),
                     confirm=None if dry else
                     "Re-point cached CanadianShopper listings to their "
                     "square front + back gallery photos?\n\nThe tool uses "
                     "the hosted URLs in the image cache; it needs no Woo "
                     "export and uploads no images. Review the dry-run first.")

    row = ttk.Frame(box)
    row.pack(anchor="w", pady=4)
    dry_button = ttk.Button(row, text="Preview cached changes",
                            command=lambda: go(True))
    dry_button.pack(side="left")
    add_tooltip(dry_button,
                "CanadianShopper plugin: create a review report; no listing changes or image uploads are made.")
    apply_button = ttk.Button(row, text="Re-point photos",
                              command=lambda: go(False))
    apply_button.pack(side="left", padx=8)
    add_tooltip(apply_button,
                "CanadianShopper plugin: apply the cached front/back photo URLs to matched listings.")


def build_sold(parent, app):
    #  The panel used to lead with two rows of radios and end with the buttons,
    #  so the first thing a person saw was configuration and the thing they
    #  actually came to do was below the fold - "I can't see how to run this".
    #  It now opens with the action: read what sold, look at it, then add it.
    panel_header(parent, app, "sold")
    box = ttk.Frame(parent)
    box.pack(fill="x")
    src = tk.StringVar(master=parent, value="typed")
    onch = tk.StringVar(master=parent, value="website")
    do_cs = tk.BooleanVar(master=parent, value=False)
    state = {"path": None, "preview": []}

    channel_names = {"website": "your website",
                     "canadianshopper": "CanadianShopper",
                     "facebook": "Facebook", "ebay": "eBay",
                     "inperson": "an in-person sale",
                     "other": "another place"}

    # ---------------------------------------------------------- credentials
    def keys_path():
        return BASE / "woo-keys.txt"

    def creds_or_offer():
        """(site, key, secret) or None, offering the one-time file when absent.

        The key file is the difference between a sale being one click and it
        being retyped by hand, so it is offered once, with that reason
        attached - and only when it is actually missing.
        """
        site, key, secret = read_woo_credentials()
        site = site or app.settings.get("woo_site_url", "")
        if site and key and secret:
            return site, key, secret
        if messagebox.askyesno(
                "One-time setup: your website's API keys",
                "I can read new orders straight from your website, so a sale "
                "is one click instead of retyping its title.\n\n"
                "That needs two lines in a private file beside the app:\n"
                "  woo-keys.txt\n"
                "  1. your website's address\n"
                "  2. a READ-ONLY WooCommerce key (Settings > Advanced > "
                "REST API > Add key)\n\n"
                "It is a one-time step, and it makes every later check one "
                "click. Fill it in now?"):
            open_woo_keys_file(app, app.settings.get("woo_site_url", ""))
            app.console_line("Fill in woo-keys.txt, save it, then press "
                             "Preview new orders again.", "dim")
        else:
            app.console_line("No website keys, so nothing can be read yet: "
                             "type the cards instead, or use the orders CSV.",
                             "dim")
        return None

    # ------------------------------------------------------------- preview
    def seen_numbers():
        return sale_preview.load_seen(SOLD_ORDERS_SEEN)

    def show_preview(rows, source_name, source="website"):
        """Put the previewed cards on screen. Writes nothing anywhere."""
        state["preview"] = rows
        state["preview_source"] = source
        listing.delete(0, "end")
        for row in rows:
            listing.insert("end", sale_preview.label(row))
        if rows:
            summary.configure(text=sale_preview.headline(rows))
            list_frame.pack(anchor="w", fill="x", pady=(3, 4))
            add_preview_btn.configure(
                text="Add these %d card%s to the checklist%s" % (
                    len(rows), "" if len(rows) == 1 else "s",
                    " and fix CanadianShopper" if do_cs.get() else ""))
            add_preview_btn.pack(anchor="w", pady=(0, 4))
            for line in sale_preview.describe(rows):
                app.console_line(line, "dim")
            app.console_line(
                "%s  (read from %s - nothing has been written yet)" %
                (sale_preview.headline(rows), source_name), "ok")
        else:
            list_frame.pack_forget()
            add_preview_btn.pack_forget()
            summary.configure(text="No new orders: everything %s has is "
                                   "already on the checklist." % source_name)
            app.console_line("No new orders on %s." % source_name, "ok")

    def preview_arrived(orders, error, source_name, source="website",
                        statuses=sale_preview.DEFAULT_STATUSES):
        """Draw what a read turned up - the only place a preview is decided."""
        if error is not None:
            message = getattr(error, "message", str(error))
            hint = getattr(error, "hint", "")
            messagebox.showerror("Could not read your orders",
                                 message +
                                 ("\n\n" + hint if hint else ""),
                                 parent=box.winfo_toplevel())
            app.console_line("Preview failed: %s %s" % (message, hint), "err")
            #  A failed read empties the list: an old preview must never stay
            #  on screen looking like today's answer, ready to be added.
            state["preview"] = []
            state["preview_source"] = ""
            listing.delete(0, "end")
            list_frame.pack_forget()
            add_preview_btn.pack_forget()
            summary.configure(text="Could not read your orders: " + message)
            return
        rows = sale_preview.unseen(
            sale_preview.order_rows(orders, statuses=statuses, source=source),
            seen_numbers())
        show_preview(rows, source_name, source)

    def read_website(creds):
        site, key, secret = creds
        summary.configure(text="Reading orders from %s..." % site)
        app.console_line("Reading orders from %s..." % site, "cmd")
        in_background(
            app,
            lambda: sale_preview.read_orders(woo_get, site, key, secret),
            lambda orders, error: preview_arrived(orders, error, "your website"))

    def read_canadianshopper():
        action = TOOL_ACTION(CS_ORDERS_ACTION)
        if not action:
            messagebox.showinfo(
                "CanadianShopper order list",
                "Reading CanadianShopper's own orders needs the plugin's order "
                "reader, and the installed plugin does not have it yet.\n\n"
                "Until it does, either choose \"my website\" if the sale went "
                "through the website, type the card with \"Type the cards...\", "
                "or search the store yourself - that is the secondary route "
                "and it needs no plugin at all.")
            app.console_line(
                "This CanadianShopper plugin has no order reader yet (%s). "
                "Website orders can still be previewed." % CS_ORDERS_ACTION,
                "dim")
            return
        out = BASE / "cs-orders.json"
        try:
            out.unlink()      # so an old answer can never be mistaken for this one
        except FileNotFoundError:
            pass
        args = ["--orders-out", str(out),
                "--days", str(sale_preview.DEFAULT_DAYS)]
        if CS_COOKIE_FILE.is_file():
            args += ["--cookie-file", str(CS_COOKIE_FILE)]
        summary.configure(text="Asking CanadianShopper for its orders...")

        def done(rc):
            if rc != 0:
                app.console_line("The CanadianShopper order read failed "
                                 "(exit %s); nothing was previewed." % rc, "err")
                summary.configure(text="CanadianShopper could not be read.")
                return False
            #  No status filter: WooCommerce's statuses are not
            #  CanadianShopper's, and the plugin already returns the orders it
            #  considers sold. Filtering here would silently drop every one.
            orders = sale_preview.read_orders_file(out)
            if orders is None:
                #  Exit 0 with no readable file is a failure, not an empty
                #  day: the plugin promised an answer and did not give one.
                preview_arrived(None, sale_preview.PreviewError(
                    "The CanadianShopper plugin finished but left no order "
                    "list to read.",
                    "Nothing was changed. The console above shows what the "
                    "plugin said."),
                    "CanadianShopper", source="canadianshopper",
                    statuses=())
                return False
            preview_arrived(orders, None, "CanadianShopper",
                            source="canadianshopper", statuses=())
            return True

        app.run_tool(action, args, "CanadianShopper orders",
                     cwd=app.settings.get("pipeline_dir", str(WORK)),
                     on_done=done)

    def preview_new():
        kind = sale_preview.channel_kind(onch.get())
        if kind == "plugin":
            read_canadianshopper()
            return
        if kind == "manual":
            messagebox.showinfo(
                "No order list to read",
                "%s keeps no order list this app can read, so there is nothing "
                "to preview.\n\nType the card with \"Type the cards...\", or "
                "search the title in the seller pages the checklist links to."
                % channel_names.get(onch.get(), "That channel").capitalize())
            return
        creds = creds_or_offer()
        if creds:
            read_website(creds)

    def add_previewed():
        """The previewed orders only - not everything the website has."""
        rows = state["preview"]
        if not rows:
            return
        if state.get("preview_source") == "canadianshopper":
            #  CanadianShopper's order numbers mean nothing to WooCommerce, so
            #  the cards go in by title - the same list the typed route uses,
            #  written from the preview instead of retyped by hand.
            card_list = BASE / "cs-sold-preview.txt"
            card_list.write_text("\n".join(
                row["card"] if int(row.get("qty") or 1) == 1
                else "%s, %d" % (row["card"], row["qty"])
                for row in rows) + "\n", encoding="utf-8")
            args = ["--list", str(card_list), "--sold-on", "canadianshopper",
                    "--checklist", str(CHECKLIST)]
        else:
            #  Only the website route needs the keys; a CanadianShopper sale
            #  is added by title and must not be blocked by a missing file.
            if not keys_path().is_file() and creds_or_offer() is None:
                return
            wanted = sorted({row["id"] or row["order"] for row in rows
                             if row["id"] or row["order"]})
            args = ["--woo-keys", str(keys_path()),
                    "--orders", ",".join(wanted),
                    "--checklist", str(CHECKLIST)]
        if do_cs.get():
            args.extend(["--cs", "--gui-dialogs", "--cs-tool",
                         TOOL("sold-cards.py"), "--cookie-file",
                         str(CS_COOKIE_FILE)])
        added = list(rows)

        def done(rc):
            #  Remembered only once the checklist tool says it succeeded: a
            #  preview whose sale was never written must come back next time.
            if rc != 0:
                app.console_line("The checklist tool did not finish (exit %s); "
                                 "these orders will still be previewed next "
                                 "time." % rc, "err")
                return False
            sale_preview.save_seen(SOLD_ORDERS_SEEN,
                                   sale_preview.remember(seen_numbers(), added))
            app.console_line("Added %s to the checklist." %
                             sale_preview.headline(added).rstrip("."), "ok")
            state["preview"] = []
            listing.delete(0, "end")
            list_frame.pack_forget()
            add_preview_btn.pack_forget()
            summary.configure(text="Added those cards. Press Preview new orders "
                                   "again for anything newer.")
            return True

        app.run_tool("sold-everywhere.py", args,
                     "Mark the sale(s) everywhere",
                     cwd=app.settings.get("pipeline_dir", str(WORK)),
                     on_done=done)

    def source_hint():
        """One line saying what Preview will read, for the chosen source."""
        kind = sale_preview.channel_kind(onch.get())
        if kind == "api":
            return ("Preview reads your website's orders since the last time "
                    "you added them. It uses the WooCommerce keys in "
                    "woo-keys.txt - reading needs no special permission - and "
                    "it is offered only when the keys are missing.")
        if kind == "plugin":
            if TOOL_ACTION(CS_ORDERS_ACTION):
                return ("Preview asks the CanadianShopper plugin for its own "
                        "orders, through the session cookie it already uses.")
            return ("The installed CanadianShopper plugin has no order reader "
                    "yet, so this source cannot be previewed - use your website "
                    "or type the card.")
        return ("%s has no order list this app can read: type the card, or "
                "search the title in that site." %
                channel_names.get(onch.get(), "That channel").capitalize())

    ttk.Label(box, text="New orders", style="H2.TLabel").pack(anchor="w")
    row_top = ttk.Frame(box)
    row_top.pack(anchor="w", pady=(2, 0))
    ttk.Button(row_top, text="Preview new orders", style="Task.TButton",
               command=preview_new).pack(side="left")

    summary = ttk.Label(box, text="Nothing previewed yet.", style="Dim.TLabel",
                        wraplength=680, justify="left")
    summary.pack(anchor="w", pady=(2, 0))

    list_frame = ttk.Frame(box)
    listing = tk.Listbox(list_frame, height=6, exportselection=False)
    scroll = ttk.Scrollbar(list_frame, orient="vertical",
                           command=listing.yview)
    listing.configure(yscrollcommand=scroll.set)
    listing.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    add_preview_btn = ttk.Button(box, text="Add these to the checklist",
                                 command=add_previewed)
    add_preview_btn.pack_forget()

    hint = ttk.Label(box, text=source_hint(), style="Dim.TLabel",
                     wraplength=680, justify="left")
    hint.pack(anchor="w", pady=(4, 0))

    def chosen_changed():
        hint.configure(text=source_hint())

    # --------------------------------------------------- where did it sell?
    ttk.Label(box, text="Where did it sell?", style="H2.TLabel").pack(
        anchor="w", pady=(10, 0))
    row = ttk.Frame(box)
    row.pack(anchor="w", pady=(2, 0))
    for txt, val in (("my website", "website"),
                     ("CanadianShopper", "canadianshopper"),
                     ("Facebook", "facebook"), ("eBay", "ebay"),
                     ("in person", "inperson"), ("somewhere else", "other")):
        ttk.Radiobutton(row, text=txt, value=val, variable=onch,
                        command=chosen_changed).pack(side="left", padx=(8, 0))

    # ------------------------------------------------------ how they are named
    ttk.Label(box, text="Name the cards", style="H2.TLabel").pack(
        anchor="w", pady=(10, 0))
    row2 = ttk.Frame(box)
    row2.pack(anchor="w", pady=(2, 0))
    for txt, val in (("type them", "typed"),
                     ("my website's orders CSV", "orders"),
                     ("website API key (woo-keys.txt)", "keys")):
        ttk.Radiobutton(row2, text=txt, value=val, variable=src).pack(
            side="left", padx=(8, 0))
    ttk.Label(
        box,
        text="These choices name the cards for the checklist below too; they "
             "are not plugin-only. Preview is the shortcut when the sale came "
             "from a site: it already knows the titles.",
        style="Dim.TLabel", wraplength=680, justify="left").pack(
            anchor="w", pady=(3, 0))

    # -------------------------------------------------- CanadianShopper stock
    if app.cs_addon:
        ttk.Label(box, text="CanadianShopper stock", style="H2.TLabel").pack(
            anchor="w", pady=(10, 0))
        ttk.Checkbutton(
            box, variable=do_cs,
            text="Also fix CanadianShopper now (separate from the sale source; "
                 "preview and approve before writing)",
            command=lambda: add_preview_btn.configure(
                text="Add these %d card%s to the checklist%s" % (
                    len(state["preview"]),
                    "" if len(state["preview"]) == 1 else "s",
                    " and fix CanadianShopper" if do_cs.get() else ""))
        ).pack(anchor="w", pady=(2, 2))
        ttk.Label(
            box,
            text="A stock comparison is a separate job: nothing here counts "
                 "your stock on other sites during a sale. The match picker "
                 "appears only after a valid session is loaded and a title is "
                 "unmatched or ambiguous.",
            style="Dim.TLabel", wraplength=680, justify="left").pack(
                anchor="w", pady=(0, 2))
    else:
        ttk.Label(box, text="Without the plugin, CanadianShopper stock changes "
                  "remain manual checklist tasks.", style="Dim.TLabel",
                  wraplength=680, justify="left").pack(anchor="w", pady=(10, 2))

    def source_args():
        """(args-for-sold-everywhere, args-for-sold-cards) or None."""
        if src.get() == "typed":
            if not state["path"]:
                messagebox.showinfo(
                    "Type the cards first",
                    "Press \"Type the cards...\" first - one card per "
                    "line:\n\n  Card title\n  Card title, 2        (two "
                    "copies sold)\n  Card title, last    (that was the "
                    "final copy - end listings)\n  Card title @facebook "
                    " (sold on Facebook, not the website)")
                return None
            se = ["--list", state["path"], "--sold-on", onch.get()]
            sc = ["--list", state["path"]]
            return se, sc
        if src.get() == "orders":
            f = filedialog.askopenfilename(
                title="Choose the orders CSV from your website",
                initialdir=app.settings.get("pipeline_dir", str(WORK)),
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
            if not f:
                return None
            a = ["--woo-orders-csv", f]
            return a, a
        kf = keys_path()
        if not kf.exists():
            ex = BASE / "woo-keys.txt.example"
            if ex.exists() and messagebox.askyesno(
                    "No woo-keys.txt yet",
                    "Copy woo-keys.txt.example to woo-keys.txt and fill it "
                    "in?\nIt holds your website's address and a READ-ONLY "
                    "REST key (WooCommerce -> Settings -> Advanced -> REST "
                    "API -> Add key)."):
                open_woo_keys_file(
                    app, app.settings.get("woo_site_url", ""))
            else:
                messagebox.showinfo("Needed",
                                    "Save your website's url + ck_.../cs_... "
                                    "key as %s first." % kf)
            return None
        return ["--woo-keys", str(kf)], ["--woo-keys", str(kf)]

    def add_rows():
        got = source_args()
        if not got:
            return
        se, sc = got
        args = se + ["--checklist", str(CHECKLIST)]
        if do_cs.get():
            args.extend(["--cs", "--gui-dialogs", "--cs-tool",
                         TOOL("sold-cards.py"), "--cookie-file",
                         str(CS_COOKIE_FILE)])

        # Keep the title as this sale's durable input, then help find the
        # remaining listings. Woo opens the orders list. CanadianShopper,
        # eBay and Facebook have seller pages, but no reliable search URL is
        # assumed; copy the title so the user can paste it into each search.
        source_was_typed = src.get() == "typed"
        sale_channel = onch.get()
        typed_text = ""
        if source_was_typed and state["path"]:
            try:
                typed_text = Path(state["path"]).read_text(
                    encoding="utf-8", errors="replace")
            except Exception as exc:
                log("could not read typed sale list: %s" % exc)

        started = app.run_tool("sold-everywhere.py", args,
                               "Mark the sale(s) everywhere",
                               cwd=app.settings.get("pipeline_dir", str(WORK)))
        # Launch search/follow-up pages as soon as the sale command starts,
        # independently of the optional plugin run. The CS leg can be waiting
        # for a cookie, a match choice, or explicit approval; don't make that
        # delay suppress the other follow-up channels.
        if started and source_was_typed:
            title = typed_sale_title(typed_text)
            if not title:
                app.console_line(
                    "Several cards were entered; use the checklist links one "
                    "card at a time to avoid opening many Edge tabs.", "dim")
            else:
                try:
                    app.clipboard_clear()
                    app.clipboard_append(title)
                    app.update_idletasks()
                except Exception as exc:
                    log("could not copy sale title: %s" % exc)
                browser = app.open_webpages(
                    sale_followup_urls(title, sale_channel, app.settings),
                    new_window=True)
                app.console_line(
                    "Opened the follow-up pages in %s. WooCommerce opens the "
                    "orders list. Paste the copied title into the "
                    "CanadianShopper store search and eBay/Facebook manually. "
                    "The optional CanadianShopper stock preview/approval runs "
                    "separately; no listing was changed by opening these pages." %
                    browser, "ok")

    def fix_cs(apply):
        got = source_args()
        if not got:
            return
        _se, sc = got
        # Preview mode is read-only but should still offer the interactive
        # title matcher when a sale title is fuzzy/unmatched.
        args = sc + ["--cookie-file", str(CS_COOKIE_FILE), "--gui-dialogs"]
        if apply:
            args.append("--apply")
        app.run_tool("sold-cards.py", args,
                     "CanadianShopper stock - " + ("APPLY" if apply else
                                                   "preview"),
                     cwd=app.settings.get("pipeline_dir", str(WORK)))

    def compare_this_card():
        """Hand one card to the stock panel, which does the comparing."""
        card = ""
        if len(state["preview"]) == 1:
            card = state["preview"][0]["card"]
        elif state["path"]:
            try:
                lines = [line.strip() for line in Path(state["path"]).read_text(
                    encoding="utf-8", errors="replace").splitlines()]
            except Exception as exc:
                log("could not read typed sale list: %s" % exc)
                lines = []
            lines = [line for line in lines
                     if line and not line.startswith("##")]
            if len(lines) == 1:
                card = lines[0].split(",")[0].strip()
        if not card:
            messagebox.showinfo(
                "Which card?",
                "This opens the stock panel for ONE card. Either preview the "
                "sale first (so the card is known), or type the card on its "
                "own with \"Type the cards...\".\n\nFor the whole catalogue "
                "at once, use the Stock panel from the After a sale menu.")
            return
        app._stock_filter = card
        app.show_panel("stock")

    def type_cards():
        Editor(self_toplevel=box, title="Cards that sold",
               hint="One card per line:\n"
                    "  Card title\n"
                    "  Card title, 2        two copies sold\n"
                    "  Card title, last     final copy -> end the listings\n"
                    "  Card title @facebook sold on Facebook\n"
                    "  Card title @cs       sold on CanadianShopper\n"
                    "  Card title @ebay     sold on eBay\n"
                    "  Card title @inperson sold in person\n"
                    "A card number such as #254 is part of the title; use ## for comments.",
               initial="",
               save_to=BASE / "sold-cards.txt",
               save_label="Save title",
               save_hint="Enter adds another card line. Ctrl+Enter saves this "
                         "title and returns; then click Add to the checklist.",
               on_saved=lambda p: state.update(path=str(p)))

    # --------------------------------------------------------- manual route
    ttk.Label(box, text="Type it instead", style="H2.TLabel").pack(
        anchor="w", pady=(10, 0))
    row3 = ttk.Frame(box)
    row3.pack(anchor="w", pady=(2, 0))
    ttk.Button(row3, text="Type the cards...", command=type_cards).pack(
        side="left")
    ttk.Button(row3, text="Add to the checklist (and fix CS if ticked)",
               style="Task.TButton", command=add_rows).pack(side="left", padx=8)
    ttk.Button(row3, text="Compare this card's stock...",
               command=compare_this_card).pack(side="left")
    if app.cs_addon:
        row4 = ttk.Frame(box)
        row4.pack(anchor="w", pady=(4, 0))
        ttk.Button(row4, text="CanadianShopper only: preview the stock "
                   "change", command=lambda: fix_cs(False)).pack(side="left")
        ttk.Button(row4, text="Apply the previewed change",
                   command=lambda: fix_cs(True)).pack(side="left", padx=8)

    ttk.Label(box,
              text="This route is for a sale the app cannot read: enter the "
                   "cards, save the list, then add it to the checklist. One "
                   "typed card opens the remaining seller pages in the "
                   "browser, with the title copied for pasting. The "
                   "plugin-only CanadianShopper stock checkbox is independent; "
                   "no listing is changed automatically.",
              style="Dim.TLabel", wraplength=680, justify="left").pack(
                  anchor="w", pady=(6, 0))


def build_stock(parent, app):
    #  One job, on demand: which cards have a different number on two sites,
    #  and then the correction. Nothing here runs during a sale - the sale
    #  panel says plainly that comparing is a separate job.
    #
    #  The list is the place the work happens, not a report: the usual answer
    #  is "the website is right", so setting the other site to the website's
    #  count is one confirmed click for the whole list, a selection for the
    #  exceptions, and a card that only exists on one side can be dismissed so
    #  it stops coming back.
    panel_header(parent, app, "stock")
    box = ttk.Frame(parent)
    box.pack(fill="x")

    #  A one-shot hand-off from the sale panel: "this card, please". It is
    #  consumed here so reopening the panel from the menu compares everything.
    focus = str(getattr(app, "_stock_filter", "") or "").strip()
    app._stock_filter = ""
    state = {"card": focus, "rows": [], "pairs": [], "only_woo": [],
             "only_other": [], "label": "CanadianShopper", "mode": "count",
             "skipped": 0, "catalog": {}, "items": []}
    statuses = {}

    def credentials():
        site, key, secret = read_woo_credentials()
        site = site or app.settings.get("woo_site_url", "")
        if site and key and secret:
            return site, key, secret
        messagebox.showinfo(
            "One-time setup: your website's API keys",
            "Comparing stock reads your website's catalogue with the same "
            "WooCommerce keys as everything else. Changing a count on the "
            "website needs a key pair with Read/Write access; a read-only "
            "pair can still compare and can still fix CanadianShopper.\n\n"
            "woo-keys.txt is about to open. Fill it in, save it, then press "
            "Compare again.")
        open_woo_keys_file(app, app.settings.get("woo_site_url", ""))
        return None

    # --------------------------------------------------------- the ignore list
    def ignored_path():
        return BASE / stock_compare.IGNORED_FILE

    def ignored_entries():
        return stock_compare.load_ignored(ignored_path())

    def hide(rows):
        """Dismiss these cards so they are not compared again."""
        if not rows:
            messagebox.showinfo("Nothing selected",
                                "Select one or more rows in the list first.")
            return
        entries = stock_compare.remember_ignored(ignored_entries(), rows)
        if not stock_compare.save_ignored(ignored_path(), entries):
            messagebox.showerror(
                "Could not save the list",
                "The list of cards to stop asking about could not be written "
                "to %s." % ignored_path(), parent=box.winfo_toplevel())
            return
        for row in rows:
            app.console_line("Ignoring %s - it will not be compared again."
                             % row["card"], "dim")
        app.console_line("%d card%s now ignored. Restore them with \"Restore "
                         "ignored cards...\"." %
                         (len(rows), "" if len(rows) == 1 else "s"), "ok")
        redraw()

    def restore_ignored():
        entries = ignored_entries()
        if not entries:
            messagebox.showinfo("Nothing is ignored",
                                "No card has been dismissed, so there is "
                                "nothing to restore.")
            return
        names = [entry.get("title") or entry.get("key") for entry in entries]
        shown = "\n".join("  " + name[:80] for name in names[:12])
        if len(names) > 12:
            shown += "\n  ... and %d more" % (len(names) - 12)
        if not messagebox.askyesno(
                "Restore %d ignored card%s?" % (len(names),
                                                "" if len(names) == 1 else "s"),
                "These cards are being left out of comparisons:\n\n%s\n\n"
                "Restore all of them, so they are compared again?" % shown,
                parent=box.winfo_toplevel()):
            return
        stock_compare.save_ignored(ignored_path(), [])
        app.console_line("%d ignored card%s restored; press Compare again to "
                         "see them." % (len(names),
                                        "" if len(names) == 1 else "s"), "ok")
        summary.configure(text="Ignored cards restored. Press Compare again.")

    # ------------------------------------------------------------- the list
    def selected_rows():
        try:
            indexes = list(listing.curselection())
        except Exception:
            indexes = []
        rows = state["rows"]
        return [rows[i] for i in indexes if 0 <= i < len(rows)]

    def redraw():
        rows = stock_compare.action_list(state["pairs"], state["only_woo"],
                                         state["only_other"],
                                         stock_compare.ignored_keys(
                                             ignored_entries()),
                                         state["label"])
        state["rows"] = rows
        listing.delete(0, "end")
        for row in rows:
            listing.insert("end", stock_compare.label_action(
                row, state["label"], state["mode"]))
        if rows:
            list_frame.pack(anchor="w", fill="x", pady=(3, 4))
            action_row.pack(anchor="w", pady=(0, 4))
        else:
            list_frame.pack_forget()
            action_row.pack_forget()
        hidden = stock_compare.hidden_count(state["pairs"], state["only_woo"],
                                            state["only_other"],
                                            stock_compare.ignored_keys(
                                                ignored_entries()))
        fixable = len([row for row in rows
                       if row["kind"] == stock_compare.FIX])
        text = stock_compare.summary([row for row in rows
                                      if row["kind"] == stock_compare.FIX],
                                     state["pairs"], state["only_woo"],
                                     state["only_other"], state["label"])
        if rows and not fixable:
            no_count = len(stock_compare.no_count_rows(rows))
            one_sided = len(rows) - no_count
            if no_count and one_sided:
                text = ("No counts disagree; %d card%s only on one side, %d "
                        "with no count on %s." %
                        (one_sided, "" if one_sided == 1 else "s", no_count,
                         state["label"]))
            elif no_count:
                text = ("No counts disagree; %d card%s on %s count nothing." %
                        (no_count, "" if no_count == 1 else "s",
                         state["label"]))
            else:
                text = "No counts disagree; %d card%s only on one side." % (
                    len(rows), "" if len(rows) == 1 else "s")
        no_count = len(stock_compare.no_count_rows(rows))
        if fixable and no_count:
            text += ("  %d more card%s on %s counting no stock." %
                     (no_count, "" if no_count == 1 else "s", state["label"]))
        if hidden:
            text += "  %d ignored." % hidden
        if state["card"]:
            text = "%s  (only this card)" % text.rstrip(".")
        summary.configure(text=text)
        return rows

    # ------------------------------------------------------- writing a change
    def copy_plan(plan):
        lines = ["%s -> %s %d" % (item["card"], state["label"], item["to"])
                 for item in plan]
        try:
            app.clipboard_clear()
            app.clipboard_append("\n".join(lines))
            app.update_idletasks()
            return True
        except Exception as exc:
            log("could not copy the stock plan: %s" % exc)
            return False

    def set_arrived(rc, plan, out, action):
        answer = {}
        if out.is_file():
            try:
                answer = json.loads(out.read_text(encoding="utf-8"))
            except Exception:
                answer = {}
        report = stock_compare.plugin_write_report(plan, answer)
        for entry in report["failed"]:
            app.console_line("Not changed: %s - %s" %
                             (entry["card"] or "a card", entry["why"]), "err")
        if rc != 0:
            #  The plugin's contract is "attempt nothing" on a non-zero exit, so
            #  the list is left exactly as it was.
            app.console_line("The stock change did not finish (exit %s). "
                             "Nothing was changed." % rc, "err")
            summary.configure(text="The stock change did not finish (exit %s)."
                                   % rc)
            return False
        changed = report["changed"]
        unknown = report["unknown"]
        if unknown:
            #  A card the plugin did not report on is not called fixed: it
            #  stays on the list and the console says why it is there.
            app.console_line(
                "%d card%s was not reported on by the plugin, so %s left on "
                "the list: compare again to see where it stands." %
                (len(unknown), "" if len(unknown) == 1 else "s",
                 "it is" if len(unknown) == 1 else "they are"), "err")
        if changed:
            #  The direction is spelled out in the success line too: this is
            #  the write that must never be mistaken for the opposite one.
            text = ("%d CanadianShopper count%s set to the website's count "
                    "(the website was not changed)" %
                    (len(changed), "" if len(changed) == 1 else "s"))
            if report["failed"]:
                text += "; %d could not be changed" % len(report["failed"])
            app.console_line(text + ". Press Compare again to confirm.", "ok")
            summary.configure(text=text + ". Compare again to confirm.")
        elif not unknown:
            app.console_line(
                "The plugin finished but reported no card as written, so the "
                "list is unchanged.", "err")
            summary.configure(text="The plugin reported no card as written.")
        #  Only the rows the plugin said it wrote leave the list, and only if
        #  the card really is no longer one this panel has anything to do about.
        done = {stock_compare.card_key(row["card"]) for row in changed}
        state["rows"] = [row for row in state["rows"]
                         if stock_compare.card_key(row["card"]) not in done]
        listing.delete(0, "end")
        for row in state["rows"]:
            listing.insert("end", stock_compare.label_action(
                row, state["label"], state["mode"]))
        if not state["rows"]:
            list_frame.pack_forget()
            action_row.pack_forget()
        return bool(changed)

    def run_set(rows):
        plan = stock_compare.plan_set(rows)
        if not plan:
            messagebox.showinfo(
                "Nothing to set",
                "Only a card that is on both sites can have its count set. "
                "Select one of the rows where the two numbers differ, or use "
                "\"Set CanadianShopper to the website's counts...\".")
            return
        lines = stock_compare.describe_plan(plan, state["label"])
        body = "\n".join(lines[:12])
        if len(lines) > 12:
            body += "\n  ... and %d more" % (len(lines) - 12)
        question = ("Direction: your website's count  ->  %s. Your website is "
                    "not changed.\n\n%s\n\n%s\n\nOnly those counts change: "
                    "nothing is added, removed or repriced. Write them now?" %
                    (state["label"],
                     stock_compare.plan_summary(plan, state["label"]), body))
        if not messagebox.askyesno("Set CanadianShopper to these counts?",
                                   question, parent=box.winfo_toplevel()):
            app.console_line("The stock change was not confirmed; nothing was "
                             "written.", "dim")
            return
        action = TOOL_ACTION(CS_STOCK_SET_ACTION)
        if not action:
            copied = copy_plan(plan)
            messagebox.showinfo(
                "This plugin cannot set stock yet",
                "The installed CanadianShopper plugin can list its stock but "
                "not write it, so nothing was changed.\n\nThe exact changes "
                "are in the console%s. Update the plugin to 1.0.21 or newer "
                "and this button will set them for you."
                % (" and on your clipboard" if copied else ""))
            for line in lines:
                app.console_line(line, "dim")
            app.console_line(
                "stock.set is not declared by the installed plugin (%s)." %
                CS_STOCK_SET_ACTION, "dim")
            return
        plan_path = BASE / "cs-stock-set.json"
        out = BASE / "cs-stock-set-result.json"
        try:
            out.unlink()
        except FileNotFoundError:
            pass
        plan_path.write_text(
            json.dumps({"items": plan}, indent=1, ensure_ascii=False),
            encoding="utf-8")
        args = ["--set-file", str(plan_path), "--set-out", str(out)]
        if CS_COOKIE_FILE.is_file():
            args += ["--cookie-file", str(CS_COOKIE_FILE)]
        summary.configure(text="Setting %d %s count%s..." %
                               (len(plan), state["label"],
                                "" if len(plan) == 1 else "s"))
        app.console_line(
            "Setting %d %s count%s from your website (your website is not "
            "changed)..." % (len(plan), state["label"],
                             "" if len(plan) == 1 else "s"), "cmd")
        app.run_tool(action, args, "Set CanadianShopper stock",
                     cwd=app.settings.get("pipeline_dir", str(WORK)),
                     on_done=lambda rc: set_arrived(rc, plan, out, action))

    def set_all():
        run_set([row for row in state["rows"]
                 if row["kind"] == stock_compare.FIX])

    def set_selected():
        run_set(selected_rows())

    def ignore_selected():
        hide(selected_rows())

    def set_website(rows):
        """The other direction: the website's count is the one that is wrong.

        The keys are the shop's own Read/Write pair - the same ones the photo
        wiring uses - so this writes the count the other site reports. It is
        never the default, because the website is right more often than not,
        and it is always named card by card before anything is sent.
        """
        plan = stock_write.plan_from_rows(rows, state["label"])
        if not plan:
            messagebox.showinfo(
                "Nothing to set",
                "Select a row where the two counts differ and the card exists "
                "on the website. A card that is only on the other site has "
                "nothing on the website to change.")
            return
        creds = site_creds.get("last") or credentials()
        if not creds:
            return
        site_creds["last"] = creds
        lines = stock_write.describe(plan, state["label"])
        body = "\n".join(lines[:12])
        if len(lines) > 12:
            body += "\n  ... and %d more" % (len(lines) - 12)
        question = ("Direction: %s's count  ->  your website. %s is not "
                    "changed.\n\n%s\n\n%s\n\nOnly those stock counts change: "
                    "nothing is added, removed or repriced. Write them to "
                    "the website now?" %
                    (state["label"], state["label"],
                     stock_write.summary(plan, state["label"]), body))
        if not messagebox.askyesno(
                "Write %s's counts onto your website?" % state["label"],
                question, parent=box.winfo_toplevel()):
            app.console_line("The website was not changed: the write was not "
                             "confirmed.", "dim")
            return
        summary.configure(text="Setting %d website count%s..." %
                               (len(plan), "" if len(plan) == 1 else "s"))
        app.console_line(
            "Setting %d website count%s from %s's counts (%s is not "
            "changed)..." % (len(plan), "" if len(plan) == 1 else "s",
                             state["label"], state["label"]), "cmd")
        site, key, secret = creds

        def arrived(result, error):
            if error is not None:
                message = getattr(error, "message", str(error))
                hint = getattr(error, "hint", "")
                messagebox.showerror(
                    "The website could not be changed",
                    message + ("\n\n" + hint if hint else "") +
                    "\n\nNo count was changed by this attempt.",
                    parent=box.winfo_toplevel())
                app.console_line("Website write stopped: %s %s" %
                                 (message, hint), "err")
                summary.configure(text="The website could not be changed.")
                return
            updated = result.get("updated") or []
            failed = result.get("failed") or []
            for entry in failed:
                app.console_line(
                    "Not changed: %s - %s %s" %
                    (entry.get("title") or entry.get("id"), entry.get("why"),
                     entry.get("hint") or ""), "err")
            for entry in updated:
                app.console_line("Website now shows %s: %s" %
                                 (entry.get("inventory"),
                                  entry.get("title") or entry.get("id")), "ok")
            done = {str(entry.get("id")) for entry in updated}
            state["rows"] = [row for row in state["rows"]
                             if str(row.get("woo_id")) not in done]
            listing.delete(0, "end")
            for row in state["rows"]:
                listing.insert("end", stock_compare.label_action(
                    row, state["label"], state["mode"]))
            if not state["rows"]:
                list_frame.pack_forget()
                action_row.pack_forget()
            text = "%d website count%s changed" % (
                len(updated), "" if len(updated) == 1 else "s")
            if failed:
                text += "; %d could not be changed" % len(failed)
            text += " (%s was not changed)" % state["label"]
            summary.configure(text=text + ". Compare again to confirm.")
            app.console_line(text + ". Compare again to confirm.", "ok")

        in_background(
            app,
            lambda: stock_write.set_counts(
                site, key, secret,
                [{"id": row["id"], "quantity": row["to"],
                  "title": row["title"]} for row in plan]),
            arrived)

    def set_website_selected():
        set_website(selected_rows())

    def list_rows(rows):
        """Offer to list these cards on CanadianShopper, from the website.

        A card that sold out here but is still stocked on the website is the
        one case where the panel can put it *back* rather than change a
        number. CanadianShopper has no API this app may write listings
        through, so this writes the import CSV the pipeline already writes -
        same fourteen columns, same filename, same folder - from the website
        product itself: its title, its price, its own photo URL and its stock
        count. Nothing on either site changes until that file is imported.
        """
        rows = [row for row in rows or []
                if row.get("kind") == stock_compare.ONLY_WOO]
        if not rows:
            messagebox.showinfo(
                "Nothing to list",
                "Select one or more rows that are on the website only. A card "
                "on both sites has nothing to list, and a card that is only on "
                "the other site cannot be listed on the website from here.")
            return
        wanted, missing = cs_listing.listing_products(rows, state["catalog"])
        if missing:
            app.console_line(
                "%d selected card%s not in the comparison's catalogue; compare "
                "again to list %s." %
                (len(missing), "" if len(missing) == 1 else "s",
                 "it" if len(missing) == 1 else "them"), "err")
        if not wanted:
            messagebox.showinfo(
                "Nothing to list",
                "The products behind those rows are no longer loaded. Press "
                "Compare again, then select the cards.")
            return
        values = cs_listing.defaults(app.settings)
        built, notes = cs_listing.build_rows(wanted, values)
        if not built:
            messagebox.showinfo(
                "Nothing to list",
                "Those products have no name, so there is nothing to list.")
            return
        lines = cs_listing.describe(built)
        if len(built) > 12:
            lines.append("  ... and %d more" % (len(built) - 12))
        body = "\n".join(lines)
        if notes:
            body += "\n\nWorth knowing:\n" + "\n".join(
                "  %s - %s" % note for note in notes[:6])
            if len(notes) > 6:
                body += "\n  ... and %d more" % (len(notes) - 6)
        question = ("%s\n\n%s\n\nAlex Collect writes the CanadianShopper "
                    "import file first - the same file a batch produces - then "
                    "offers to import it as drafts and to publish them, with "
                    "the publisher's own confirmations. Write the file "
                    "now?" %
                    (cs_listing.summary(built, values), body))
        if not messagebox.askyesno("List these cards on CanadianShopper?",
                                   question, parent=box.winfo_toplevel()):
            app.console_line("Nothing was written: the listing was not "
                             "confirmed.", "dim")
            return
        folder = canadianshopper_results_dir(app)
        try:
            written = cs_listing.write_rows(built, folder)
        except OSError as exc:
            messagebox.showerror(
                "Could not write the import file",
                "The CanadianShopper import file could not be written to "
                "%s:\n\n%s\n\nNothing on either site was changed."
                % (folder, exc), parent=box.winfo_toplevel())
            app.console_line("Could not write the CanadianShopper import "
                             "file: %s" % exc, "err")
            return
        total = sum(count for _path, count in written)
        for path, count in written:
            app.console_line("Wrote %s (%d listing%s)." %
                             (path, count, "" if count == 1 else "s"), "ok")
        for note in notes:
            app.console_line("Note: %s - %s" % note, "dim")
        summary.configure(
            text="%d listing%s written to %s." %
                 (total, "" if total == 1 else "s", written[0][0].name))
        import_written(written, total)

    def import_written(written, total):
        """Finish the job: hand the file to the plugin's own importer.

        The file is written either way - it is the same CSV a batch produces -
        so an older plugin still finishes the job by hand. What this adds is
        the click: the drafts appear without opening the folder, and nothing is
        published, because an import only ever creates drafts.
        """
        folder = written[0][0].parent
        names = "\n".join("  %s (%d row%s)" %
                          (path.name, count, "" if count == 1 else "s")
                          for path, count in written)
        action = TOOL_ACTION(CS_IMPORT_ACTION)
        if not action:
            messagebox.showinfo(
                "The file is ready to import",
                "%d listing%s written:\n\n%s\n\nThis plugin cannot import "
                "a CSV itself yet, so the file has to go in by hand: "
                "CanadianShopper -> vendor dashboard -> Products -> Import "
                "from CSV.\n\nWhen the plugin declares \"%s\", this button "
                "will do that step too." %
                (total, "" if total == 1 else "s", names, CS_IMPORT_ACTION),
                parent=box.winfo_toplevel())
            if messagebox.askyesno(
                    "Import file written",
                    "Open the folder so %s can be imported on CanadianShopper?"
                    % ("it" if len(written) == 1 else "they"),
                    parent=box.winfo_toplevel()):
                open_path(folder)
            return
        if not messagebox.askyesno(
                "Import %d listing%s on CanadianShopper now?" %
                (total, "" if total == 1 else "s"),
                "%s\n\nImported listings arrive as unpublished drafts: "
                "nothing is published and nothing goes live. They can be "
                "previewed and published from Import / publish drafts when "
                "you are ready." % names,
                parent=box.winfo_toplevel()):
            app.console_line(
                "The file was written but not imported; it is in %s." % folder,
                "dim")
            if messagebox.askyesno(
                    "Import file written",
                    "Open the folder so %s can be imported by hand?" %
                    ("it" if len(written) == 1 else "they"),
                    parent=box.winfo_toplevel()):
                open_path(folder)
            return
        result = folder / "cs-import-result.json"
        try:
            result.unlink()
        except FileNotFoundError:
            pass
        args = []
        for path, _count in written:
            args += ["--csv", str(path)]
        if CS_COOKIE_FILE.is_file():
            args += ["--cookie-file", str(CS_COOKIE_FILE)]
        args += ["--result", str(result)]
        summary.configure(text="Importing %d listing%s on CanadianShopper..." %
                               (total, "" if total == 1 else "s"))
        app.console_line("Importing %d listing%s on CanadianShopper..." %
                         (total, "" if total == 1 else "s"), "cmd")

        def arrived(rc):
            answer = {}
            if result.is_file():
                try:
                    answer = json.loads(result.read_text(encoding="utf-8"))
                except Exception:
                    answer = {}
            report = cs_listing.import_report(written, answer)
            for entry in report["failed"]:
                #  The plugin's own sentence, unedited - "every listing in
                #  this file already exists" is a good outcome and must not
                #  be dressed up as one of the bad ones, and a real refusal
                #  must not be softened.
                app.console_line("No new listing from %s: %s" %
                                 (entry["file"], entry["why"]), "warn")
            if rc != 0:
                app.console_line(
                    "The import did not finish (exit %s). The file is still "
                    "in %s, so it can be imported by hand." % (rc, folder),
                    "err")
                summary.configure(text="The import did not finish (exit %s); "
                                       "the file is still there." % rc)
                return
            made = sum(entry["drafts"] for entry in report["imported"])
            if made:
                app.console_line(
                    "%d draft%s created on CanadianShopper. They are not "
                    "live: Preview drafts lists which are ready and which "
                    "need work." %
                    (made, "" if made == 1 else "s"), "ok")
            if report["imported"] and not made:
                #  The plugin took the file but says it created nothing. That
                #  is not a success to report as one: either the importer
                #  made drafts it did not count, or it silently refused every
                #  row, and only the dashboard can say which.
                app.console_line(
                    "The plugin took the file but reported no drafts. Check "
                    "CanadianShopper -> Products before importing it again.",
                    "err")
            if report["unknown"]:
                app.console_line(
                    "%d file%s was not reported on by the plugin, so it is not "
                    "known whether those drafts exist: check CanadianShopper "
                    "-> Products before importing it again." %
                    (len(report["unknown"]),
                     "" if len(report["unknown"]) == 1 else "s"), "err")
            if report["failed"] and not report["imported"]:
                #  A file the plugin read and refused, or read and found
                #  nothing to do: the file stays where it is and nothing on
                #  CanadianShopper moved because of this run.
                app.console_line(
                    "Nothing new was created: the plugin read %d file%s and "
                    "added nothing. Nothing on CanadianShopper was changed by "
                    "this import." %
                    (len(report["failed"]),
                     "" if len(report["failed"]) == 1 else "s"), "warn")
                app.console_line(
                    "That means these cards already have a listing on "
                    "CanadianShopper - and the stock comparison could not see "
                    "it. A listing the stock reader does not return is usually "
                    "one that is not active: a draft, hidden, archived, or off "
                    "sale. Publishing (offered next) looks for drafts first "
                    "and puts any ready one back on sale; anything else has "
                    "to be found in the vendor dashboard.", "dim")
            elif not report["imported"] and not report["unknown"]:
                app.console_line(
                    "Nothing was imported: the plugin reported no file as "
                    "imported. The file is in %s." % folder, "err")
            if made:
                summary.configure(
                    text="%d draft%s created on CanadianShopper. Compare "
                         "again after you publish them." %
                         (made, "" if made == 1 else "s"))
            elif report["failed"] and not report["unknown"]:
                summary.configure(
                    text="No new listings were created; the plugin's reasons "
                         "are in the console above.")
            else:
                summary.configure(
                    text="The import reported no drafts; check CanadianShopper "
                         "-> Products.")
            #  The job the person actually wants is the card on sale again,
            #  so the publish offer comes first. The read-only report is the
            #  fallback - both when they decline and when nothing new was
            #  created, because the listing may already be an unpublished
            #  draft from an earlier run.
            if (made or report["failed"]) and publish_drafts(made):
                return
            if report["imported"]:
                preview_drafts()
            elif report["failed"] and not report["unknown"]:
                preview_drafts(
                    "Preview the drafts already there?",
                    "Nothing new was created. Any listing this card already "
                    "has on CanadianShopper is still there, and may still be a "
                    "draft.\n\nRead the drafts back and write a readiness "
                    "report - which can be published and which need work? "
                    "Nothing is published by this step.")

        app.run_tool(action, args, "Import CanadianShopper listings",
                     cwd=app.settings.get("pipeline_dir", str(WORK)),
                     on_done=arrived)

    def publish_drafts(count, reason=""):
        """Take the drafts live, through the publisher the app already has.

        The listing step left unpublished drafts; this is the rest of the job
        the person actually wants - the card on sale again. It is the existing
        publisher with --apply, so the same readiness checks decide what may
        go live and the same typed PUBLISH confirms it: nothing here weakens
        that gate, it only stops the person having to find the button in
        another panel.

        ``count`` is what the import says it created, and ``reason`` is what a
        comparison already found. When neither is known - the import created
        nothing, because every card already had a listing - nobody knows
        whether there is a draft at all, so the publisher is asked to *look*
        first and the typed PUBLISH is only asked for once there is something
        to publish. That is what stops a run ending in an empty report that
        answers nothing.
        """
        if not TOOL_ACTION("marketplace.publish_drafts"):
            return False
        if not count and not reason:
            return look_for_drafts()
        if count:
            title = ("Publish the %d new draft%s now?" %
                     (count, "" if count == 1 else "s"))
            detail = ("%d listing%s %s created as unpublished drafts. Take "
                      "%s live now?" %
                      (count, "" if count == 1 else "s",
                       "was" if count == 1 else "were",
                       "it" if count == 1 else "them"))
        else:
            title = "Publish the ready drafts now?"
            detail = reason
        if not messagebox.askyesno(
                title,
                "%s\n\nPublishing scans every draft on CanadianShopper and "
                "activates each one that passes all the readiness checks - "
                "drafts from earlier runs too. A draft that is not ready is "
                "left alone.\n\nYou will also be asked to type PUBLISH in "
                "the console, so nothing can go live on one click." % detail,
                parent=box.winfo_toplevel()):
            return False
        report = canadianshopper_results_dir(app) / "cs-publish-report.csv"
        args = ["--cookie-file", str(CS_COOKIE_FILE), "--report", str(report),
                "--apply"]
        app.console_line("Publishing the ready drafts...", "cmd")
        summary.configure(text="Publishing the ready drafts...")
        app.run_tool(
            "cs-publish-drafts.py", args,
            "Publish ready CanadianShopper drafts",
            cwd=app.settings.get("pipeline_dir", str(WORK)),
            confirm=("Scan your CanadianShopper drafts and activate only the "
                     "ones that pass all readiness checks?\n\nNothing is "
                     "activated unless you also type PUBLISH in the output "
                     "console."),
            on_done=lambda rc: published(rc, count, report))
        return True

    def look_for_drafts():
        """Ask the publisher whether there is a draft at all, before asking
        anyone to type PUBLISH.

        An import that created nothing leaves cards whose listings exist
        somewhere the stock reader cannot see. Publishing is the only thing
        the app can do about a draft, so it is worth one read-only look - and
        when that look finds nothing, "there is no draft" is the answer. What
        it must never do is ask for a typed PUBLISH and then hand back a
        report with no rows in it, which answers nothing.
        """
        report = canadianshopper_results_dir(app) / "cs-publish-report.csv"
        try:
            report.unlink()
        except FileNotFoundError:
            pass
        app.console_line(
            "Looking for drafts on CanadianShopper before asking to publish "
            "anything...", "cmd")
        summary.configure(text="Looking for drafts to publish...")
        app.run_tool(
            "cs-publish-drafts.py",
            ["--cookie-file", str(CS_COOKIE_FILE), "--report", str(report)],
            "Look for CanadianShopper drafts",
            cwd=app.settings.get("pipeline_dir", str(WORK)),
            on_done=lambda rc: found(rc, report))
        return True

    def found(rc, report):
        """What the read-only look found: publish only if there is something."""
        said = stock_compare.draft_count(last_tool_output(app))
        rows = stock_compare.report_rows(report)
        if rc != 0:
            app.console_line(
                "The look for drafts did not finish (exit %s), so nothing "
                "was published and nothing was changed." % rc, "err")
            summary.configure(text="Could not look for drafts (exit %s)." % rc)
            return
        #  The publisher's own sentence beats anything read out of its file:
        #  the file is its format, and a report with a header and a summary
        #  line in it is still "no drafts".
        if said is not None:
            rows = said
        if rows is None:
            #  Nothing readable either way is not the same as "there is no
            #  draft", and saying so would be a guess dressed as an answer.
            app.console_line(
                "The publisher finished but said nothing about how many "
                "drafts it found, so it is not known whether there is one. "
                "Nothing was published.", "err")
            summary.configure(text="The publisher did not say how many drafts "
                                   "it found.")
            return
        if not rows:
            app.console_line(
                "No drafts on CanadianShopper: there is nothing to publish, "
                "and nothing was changed.", "warn")
            app.console_line(
                "An empty report is not a missing answer: the publisher "
                "writes one row per draft, so no drafts means no rows.",
                "dim")
            app.console_line(
                "A listing that exists but is not a draft is hidden, "
                "archived, private or off sale - or a variation of a "
                "variable product, which the stock reader does not return. "
                "Those are put back on sale in the vendor dashboard, not "
                "from here.", "dim")
            #  Name the cards, so the dashboard search is a search for
            #  something rather than a hunt through 2,478 listings.
            one_sided = [row.get("card") or "" for row in state["rows"]
                         if row.get("kind") == stock_compare.ONLY_WOO]
            if one_sided:
                app.console_line(
                    "The %d card%s this comparison could not find on "
                    "CanadianShopper - search these in the vendor dashboard:"
                    % (len(one_sided), "" if len(one_sided) == 1 else "s"),
                    "dim")
                for name in one_sided[:12]:
                    app.console_line("  " + name, "dim")
                if len(one_sided) > 12:
                    app.console_line(
                        "  ... and %d more" % (len(one_sided) - 12), "dim")
            version = plugin_version()
            if version and not version_at_least(version,
                                                CS_STOCK_STATUS_VERSION):
                app.console_line(
                    "The installed CanadianShopper plugin is %s: its stock "
                    "list reports only the listings that are on sale, which "
                    "is why those cards came back one-sided. %s and later "
                    "report every listing with its own state, so the "
                    "comparison can name each one and offer publishing only "
                    "for the drafts. Update the plugin, then compare again."
                    % (version, CS_STOCK_STATUS_VERSION), "dim")
            summary.configure(text="No drafts to publish: the one-sided cards "
                                   "are not drafts.")
            return
        publish_drafts(
            0, "The publisher found %d draft%s on CanadianShopper to look "
               "at." % (rows, "" if rows == 1 else "s"))

    def published(rc, count, report):
        """Say what happened, without claiming more than the publisher did."""
        if rc != 0:
            if count:
                app.console_line(
                    "The publish step did not finish (exit %s). The %d "
                    "draft%s from this listing %s still there, unpublished." %
                    (rc, count, "" if count == 1 else "s",
                     "is" if count == 1 else "are"), "err")
                summary.configure(text="The drafts were created but not "
                                       "published (exit %s)." % rc)
            else:
                app.console_line(
                    "The publish step did not finish (exit %s). Nothing was "
                    "published and nothing was changed." % rc, "err")
                summary.configure(text="Nothing was published (exit %s)." % rc)
            return
        said = stock_compare.draft_count(last_tool_output(app))
        rows = stock_compare.report_rows(report)
        if said == 0 or rows == 0:
            #  The look said there was a draft and the publisher then found
            #  none: a race, not a failure. Say the plain thing rather than
            #  offering an empty report as if it were the answer.
            app.console_line(
                "The publisher scanned and found no drafts to look at, so "
                "nothing was published and nothing was changed.", "warn")
            summary.configure(text="No drafts to publish.")
            return
        app.console_line(
            "Publish finished. The report lists every draft it looked at and "
            "what it did: %s" % report, "ok")
        for hint in ("A draft the report leaves as a draft did not pass a "
                     "readiness check; its edit link is in the report.",
                     "Compare again: the cards that are now live on "
                     "CanadianShopper leave this list."):
            app.console_line(hint, "dim")
        summary.configure(text="Publishing finished. Compare again to confirm "
                               "the cards are on CanadianShopper.")
        if report.is_file() and messagebox.askyesno(
                "Open the publish report?",
                "The report lists every draft the publisher looked at and what "
                "it did with it.\n\n  %s\n\nOpen it?" % report,
                parent=box.winfo_toplevel()):
            open_path(report)

    def preview_drafts(title="Preview the new drafts?",
                       message="Read the drafts back and write a readiness "
                               "report - which can be published and which need "
                               "work?\n\nNothing is published by this step."):
        """Offer the read-only draft report that follows an import."""
        if not TOOL_ACTION("marketplace.publish_drafts"):
            return
        if not messagebox.askyesno(title, message,
                                   parent=box.winfo_toplevel()):
            return
        report = canadianshopper_results_dir(app) / "cs-publish-report.csv"
        args = ["--cookie-file", str(CS_COOKIE_FILE), "--report", str(report)]
        app.console_line("Reading the drafts back for a readiness report...",
                         "cmd")
        summary.configure(text="Reading the drafts back...")
        app.run_tool("cs-publish-drafts.py", args,
                     "Preview CanadianShopper drafts",
                     cwd=app.settings.get("pipeline_dir", str(WORK)))

    def list_selected():
        list_rows(selected_rows())

    def list_every_website_only_card():
        list_rows(state["rows"])

    def open_on_website():
        """Look at the product itself rather than changing its count.

        The reverse write is the button beside this one; this one is for the
        times a number is not the whole story - a variable product, a count a
        plugin owns, a price to fix while you are there. Nothing is written
        here, and the list is left alone: compare again afterwards.
        """
        rows = [row for row in selected_rows() if row.get("woo_id")]
        if not rows:
            messagebox.showinfo(
                "Nothing to open",
                "Select a row that exists on the website first. A card that is "
                "only on CanadianShopper or eBay has no website product to "
                "open, and one that is only on the website has nothing to set "
                "on the other side.")
            return
        urls = []
        for row in rows[:8]:
            url = product_edit_url(row["woo_id"], app.settings)
            if url:
                urls.append(url)
        if not urls:
            messagebox.showinfo(
                "No website address saved",
                "Set the store's address in User Settings first.")
            return
        app.open_webpages(urls)
        app.console_line(
            "Opening %d website product page%s. Change the count there, then "
            "compare again - nothing was changed by this app." %
            (len(urls), "" if len(urls) == 1 else "s"), "ok")
        if len(rows) > len(urls):
            app.console_line(
                "%d more selected card%s not opened: change those in the "
                "product list." % (len(rows) - len(urls),
                                   "" if len(rows) - len(urls) == 1 else "s"),
                "dim")

    # ---------------------------------------------------------- read results
    def clear_list():
        listing.delete(0, "end")
        list_frame.pack_forget()
        action_row.pack_forget()

    def failed(what, message, hint):
        messagebox.showerror("Could not compare with %s" % what,
                             message + ("\n\n" + hint if hint else ""),
                             parent=box.winfo_toplevel())
        app.console_line("Stock comparison stopped: %s %s" % (message, hint),
                         "err")
        summary.configure(text="Could not read %s: %s" % (what, message))
        clear_list()

    def show(rows_source, skipped):
        """Draw one comparison: ``rows_source`` is (pairs, only_woo, only_other)."""
        state["pairs"], state["only_woo"], state["only_other"] = rows_source
        state["skipped"] = skipped
        if skipped:
            app.console_line(
                "%d products were not compared: no stock count "
                "(unmanaged or variable)." % skipped, "dim")
        rows = redraw()
        fixable = [row for row in rows if row["kind"] == stock_compare.FIX]
        for row in fixable:
            app.console_line(stock_compare.describe(
                [{"card": row["card"], "woo": row["woo"], "other": row["other"],
                  "gap": row["gap"]}], other_label=state["label"],
                mode=state["mode"])[0], "dim")
        off_sale = stock_compare.off_sale_rows(rows)
        drafts = stock_compare.draft_rows(rows)
        for row in off_sale:
            app.console_line(
                "%s is on %s but not on sale (%s) - a count cannot fix that." %
                (row["card"], state["label"], row.get("state") or "not on sale"),
                "warn")
        unsold = stock_compare.out_of_stock_rows(rows)
        if unsold:
            #  The listing exists and is on sale; it simply has no stock. That
            #  is a count job, not a listing job, and saying so stops it being
            #  read as "this card is not on CanadianShopper".
            app.console_line(
                "%d of the disagreements are listings %s holds at 0: the "
                "listing exists, it just cannot be bought. \"Set "
                "CanadianShopper to the website's counts...\" puts the "
                "stock back." % (len(unsold), state["label"]), "warn")
        no_count = stock_compare.no_count_rows(rows)
        for row in no_count:
            app.console_line(
                "%s is on %s but that listing counts no stock - there is no "
                "number to compare or to write. Turn stock tracking on for "
                "that listing (or ignore the card)." %
                (row["card"], state["label"]), "warn")
        one_sided = len(rows) - len(fixable) - len(off_sale) - len(no_count)
        #  A card that is one-sided is either not listed there at all or
        #  listed under wording the pairing would not accept. Only the titles
        #  can say which, so the nearest one is shown - with the card-number
        #  rule the pairing uses, so "nothing close" means something.
        missing = [row for row in rows
                   if row["kind"] == stock_compare.ONLY_WOO]
        if missing and state.get("items"):
            near, nothing, twins = [], [], []
            for row in missing:
                item, score = stock_compare.closest(state["items"], row["card"])
                if item is None or score < 0.45:
                    nothing.append(row["card"])
                    continue
                owner = stock_compare.owner_of(state["pairs"], item)
                same = (owner is not None and
                        stock_compare.same_words(
                            row["card"], owner.get("name") or ""))
                near.append((row["card"], item.get("name") or "", score,
                             owner, same))
                if same:
                    twins.append((row["card"], owner))
            if near:
                held = [row for row in near if row[3] is not None]
                twins = [row for row in held if row[4]]
                free = [row for row in near if row[3] is None]
                if held:
                    app.console_line(
                        "%d of those %d %s a card %s already lists under a "
                        "different website product - the listing is there, so "
                        "nothing is missing:" %
                        (len(held), len(missing),
                         "names" if len(held) == 1 else "name",
                         state["label"]), "warn")
                    if twins:
                        app.console_line(
                            "  %d of them %s that product's exact title: a "
                            "duplicate on your website, not a card to list - "
                            "merge or delete it, or ignore the card here." %
                            (len(twins), "has" if len(twins) == 1 else "have"),
                            "dim")
                    others = len(held) - len(twins)
                    if others:
                        app.console_line(
                            "  %d are worded differently (another grade, copy "
                            "or condition): that copy is not listed, so it can "
                            "be listed if you sell it separately." % others,
                            "dim")
                    for card, other_name, score, owner, same in held[:8]:
                        app.console_line(
                            "  %s\n      nearest: %s (%d%%)  - held by %s" %
                            (card, other_name, round(score * 100),
                             owner.get("name") or "another product"), "dim")
                    if len(held) > 8:
                        app.console_line("  ... and %d more" % (len(held) - 8),
                                         "dim")
                if free:
                    app.console_line(
                        "%d of those %s a similar title on %s that no website "
                        "product holds yet - those are wording problems, not "
                        "missing cards:" %
                        (len(free), "has" if len(free) == 1 else "have",
                         state["label"]), "warn")
                    for card, other_name, score, owner, same in free[:6]:
                        app.console_line(
                            "  %s\n      nearest: %s (%d%%)" %
                            (card, other_name, round(score * 100)), "dim")
            if nothing:
                app.console_line(
                    "%d of those %d have nothing similar on %s: those cards "
                    "are not listed there, so the import is what creates "
                    "them." % (len(nothing), len(missing), state["label"]),
                    "dim")
        summary_line = (
            "Compared %d matched card%s against %s; %d disagree, %d not on "
            "sale there" % (len(state["pairs"]),
                            "" if len(state["pairs"]) == 1 else "s",
                            state["label"], len(fixable), len(off_sale)))
        if no_count:
            summary_line += ", %d counting no stock" % len(no_count)
        app.console_line(summary_line + ", %d only on one side. Nothing was "
                         "changed on either site yet." % one_sided, "ok")
        if one_sided and state["label"] == "CanadianShopper":
            #  A reader that only reports the listings that are on sale makes
            #  a draft or a hidden listing look missing entirely, which reads
            #  as "this card is not on CanadianShopper" - the opposite of what
            #  is true. Name the version that can tell the difference.
            version = plugin_version()
            if version and not version_at_least(version,
                                                CS_STOCK_STATUS_VERSION):
                app.console_line(
                    "The CanadianShopper reader in your plugin is %s: it "
                    "reports only the listings that are on sale, so a card "
                    "whose listing is a draft, hidden or archived looks "
                    "missing here. %s and later report every listing with "
                    "its own state. Update the plugin, then compare again." %
                    (version, CS_STOCK_STATUS_VERSION), "dim")
        if off_sale:
            #  Before 1.0.26 the reader could be handed a cached page, so a
            #  listing moved in the dashboard kept coming back in its old
            #  state. Say that here rather than let the person chase a change
            #  the app never saw.
            reader = plugin_version()
            if reader and not version_at_least(reader, CS_STOCK_CACHE_VERSION):
                app.console_line(
                    "The reader is plugin %s. It does not ask for a page the "
                    "site cannot serve from its cache, so a listing you moved "
                    "may still be reported in its old state. %s and later "
                    "re-read a repeated page once; update the plugin and "
                    "compare again before acting on the states above." %
                    (reader, CS_STOCK_CACHE_VERSION), "warn")
            publish_ready.pack(anchor="w", pady=(3, 0))
        else:
            publish_ready.pack_forget()
        if drafts:
            app.console_line(
                "%d of those is a draft: %s can activate it once it passes the "
                "readiness checks." %
                (len(drafts), "Publishing" if len(drafts) > 1 else "publishing"),
                "dim")

    def narrow(woo, items):
        """Keep only the one card this panel was opened for, if any."""
        wanted = state["card"]
        if not wanted:
            return woo, items
        keep = lambda rows: [item for item in rows
                             if woo_orders.score(wanted, item["name"]) >= 0.5]
        return keep(woo), keep(items)

    def compare_items(items, label, mode, creds):
        """Compare a list read from somewhere against the website."""
        site, key, secret = creds
        summary.configure(text="%s: %d listings. Reading your website..." %
                               (label, len(items)))
        app.console_line("%s: %d listings. Reading your website's catalogue..."
                         % (label, len(items)), "cmd")

        def arrived(products, error):
            if error is not None:
                failed("your website", getattr(error, "message", str(error)),
                       getattr(error, "hint", ""))
                return
            #  The whole product records, not just their counts: listing a
            #  card on the other site needs its price, its description and the
            #  photo URL the shop already serves.
            state["catalog"] = {str(product.get("id")): product
                                for product in products or []
                                if isinstance(product, dict)}
            woo, skipped = stock_compare.woo_items(products)
            woo, items_here = narrow(woo, items)
            pairs, only_woo, only_other = stock_compare.pair(woo, items_here)
            #  Kept for one diagnostic only: naming the nearest title on the
            #  other site when a card comes back one-sided.
            state["items"] = items_here
            show((pairs, only_woo, only_other), skipped)

        in_background(
            app,
            lambda: stock_compare.read_woo_stock(woo_get, site, key, secret),
            arrived)

    # ------------------------------------------------------- CanadianShopper
    def plugin_arrived(rc, out, creds, sent_cookie=False):
        if rc == 2 and sent_cookie:
            #  Exit 2 from a Python tool is a usage error: this plugin's reader
            #  predates --cookie-file. Ask again without it rather than telling
            #  the person to do something about a flag.
            app.console_line(
                "This plugin's stock reader does not take --cookie-file; "
                "asking it again without one.", "dim")
            app.run_tool(TOOL_ACTION(CS_STOCK_ACTION),
                         ["--stock-out", str(out)], "CanadianShopper stock",
                         cwd=app.settings.get("pipeline_dir", str(WORK)),
                         on_done=lambda code: plugin_arrived(code, out, creds,
                                                             False))
            return False
        if rc != 0:
            app.console_line("The CanadianShopper stock read failed (exit %s); "
                             "nothing was compared." % rc, "err")
            if CS_COOKIE_FILE.is_file():
                #  Say exactly what was sent, so a cookie problem is not a
                #  guessing game: the file, its age, and its size.
                try:
                    stamp = datetime.fromtimestamp(
                        CS_COOKIE_FILE.stat().st_mtime).strftime(
                            "%Y-%m-%d %H:%M")
                    size = CS_COOKIE_FILE.stat().st_size
                except OSError:
                    stamp, size = "?", 0
                app.console_line(
                    "The cookie sent was %s (%d bytes, saved %s). If that is "
                    "the one you just refreshed, the plugin is not reading it; "
                    "if it is old, paste a fresh one in User Settings."
                    % (CS_COOKIE_FILE.name, size, stamp), "dim")
            summary.configure(text="CanadianShopper could not be read.")
            clear_list()
            return False
        items = stock_compare.read_stock_file(out)
        if items is None:
            messagebox.showerror(
                "Could not read CanadianShopper's stock",
                "The plugin finished but left no stock list to read.\n\n"
                "Nothing was compared and nothing was changed.",
                parent=box.winfo_toplevel())
            app.console_line("No CanadianShopper stock list was written, so "
                             "nothing was compared.", "err")
            summary.configure(text="CanadianShopper wrote no stock list.")
            clear_list()
            return False
        state["label"], state["mode"] = "CanadianShopper", "count"
        #  The states the reader claims, in its own words: if a listing was
        #  moved in the dashboard and this still shows the old state, the
        #  reading is stale - and that is worth knowing before acting on it.
        #  The version goes in the same line because which reader produced it
        #  decides whether a repeated page was even looked for.
        version = plugin_version()
        who = ""
        if version:
            who = " (plugin %s%s)" % (
                version, ", cache-checked" if version_at_least(
                    version, CS_STOCK_CACHE_VERSION) else "")
        app.console_line("What the reader returned%s - %s."
                         % (who, stock_compare.tally_line(items)), "dim")
        compare_items(items, "CanadianShopper", "count", creds)
        return True

    def compare_cs():
        action = TOOL_ACTION(CS_STOCK_ACTION)
        if not action:
            messagebox.showinfo(
                "CanadianShopper stock list",
                "Comparing against CanadianShopper needs the plugin's stock "
                "reader, and the installed plugin does not have it yet.\n\n"
                "Nothing is wrong with the rest of the app: the plugin updates "
                "stock on a sale, it just cannot list the whole catalogue for "
                "comparison yet.")
            app.console_line(
                "This CanadianShopper plugin cannot list its stock yet (%s)."
                % CS_STOCK_ACTION, "dim")
            return
        creds = credentials()
        if not creds:
            return
        out = BASE / "cs-stock.json"
        try:
            out.unlink()
        except FileNotFoundError:
            pass
        cookie = CS_COOKIE_FILE if CS_COOKIE_FILE.is_file() else None
        args = ["--stock-out", str(out)]
        if cookie is not None:
            #  The same cookie the sale tools already use. Without this the
            #  reader falls back to whatever session the plugin itself last
            #  saw - which is why refreshing the app's cookie changed nothing.
            args += ["--cookie-file", str(cookie)]
        summary.configure(text="Reading CanadianShopper's stock...")
        app.console_line("Reading CanadianShopper's stock...", "cmd")
        if cookie is None:
            app.console_line(
                "No %s yet: paste a CanadianShopper cookie in User Settings "
                "first." % CS_COOKIE_FILE.name, "dim")
        app.run_tool(action, args, "CanadianShopper stock",
                     cwd=app.settings.get("pipeline_dir", str(WORK)),
                     on_done=lambda rc: plugin_arrived(rc, out, creds,
                                                       cookie is not None))

    # ------------------------------------------------------- eBay / Facebook
    #  Neither site offers a list this app can ask for, so the page the seller
    #  is already signed in to is read instead. Both sites check whether the
    #  request comes from a browser, and both can refuse it - so a saved page
    #  is a first-class route here, not a last resort.
    def market_read(site_id, info, url, cookie):
        if site_id == "ebay":
            items, pages, text = market_stock.read_ebay(
                market_stock.fetch, url, cookie)
            return {"items": items, "pages": pages, "text": text}
        status, text = market_stock.fetch(url, cookie)
        if status != 200 or market_stock.looks_like_login(text) or \
                market_stock.looks_like_blocked(text):
            raise market_stock.describe_refusal(
                info["label"], status, text, BASE / info["cookie"])
        return {"items": market_stock.parse_listings(site_id, text), "pages": 1,
                "text": text}

    def market_done(site_id, info, result, error, creds):
        if error is not None:
            message = getattr(error, "message", str(error))
            hint = getattr(error, "hint", "")
            kind = getattr(error, "kind", "")
            statuses[site_id].configure(
                text={"session": "not signed in", "blocked": "blocked"
                      }.get(kind, "could not be read"))
            if kind in ("session", "blocked"):
                messagebox.showwarning(
                    "%s could not be read" % info["label"],
                    message + ("\n\n" + hint if hint else "") +
                    "\n\nNothing was read and nothing was changed.",
                    parent=box.winfo_toplevel())
                app.console_line("%s: %s %s" % (info["label"], message, hint),
                                 "err")
                summary.configure(text="%s could not be read. %s" %
                                       (info["label"],
                                        "Save the page from your browser and "
                                        "press \"Read a saved %s page\"."
                                        % info["label"]
                                        if kind == "blocked" else
                                        "It is not signed in."))
                clear_list()
                return
            failed(info["label"], message, hint)
            return
        page = market_stock.save_page(BASE / info["page"], result["text"])
        items = result["items"]
        if not items:
            #  A page with no listing in it that this reader can recognise: the
            #  page's wording changed, and the saved copy is how that gets
            #  fixed. Saying "nothing is listed" would be a lie.
            statuses[site_id].configure(text="page not understood")
            messagebox.showwarning(
                "Nothing on the %s page could be read" % info["label"],
                "The page came back as %s, but no listing on it could be read."
                "\n\nNothing was compared and nothing was changed. The copy "
                "saved beside the app is what the reader is repaired against:"
                "\n\n  %s" % (market_stock.describe(result["text"], 200), page),
                parent=box.winfo_toplevel())
            app.console_line(
                "%s: the page loaded but no listing could be read; a copy is "
                "at %s" % (info["label"], page), "err")
            clear_list()
            summary.configure(text="%s's page could not be understood." %
                                   info["label"])
            return
        statuses[site_id].configure(text="%d listings" % len(items))
        state["label"] = info["label"]
        state["mode"] = "listed" if site_id == "facebook" else "count"
        app.console_line(
            "%s: %d listings read from %s (page copy at %s)." %
            (info["label"], len(items), market_stock.describe(result["text"]),
             page), "cmd")
        compare_items(items, info["label"], state["mode"], creds)
        if site_id == "facebook":
            app.console_line(
                "Facebook has no quantity: an Active listing counts as 1 and a "
                "Sold one as 0, so a card listed once never matches a website "
                "stock of 2 on the number alone.", "dim")

    site_creds = {}

    def compare_market(site_id):
        info = market_stock.SITES[site_id]
        url = str(app.settings.get("%s_selling_url" % site_id, "") or "").strip()
        cookie_path = BASE / info["cookie"]
        try:
            cookie, dropped = market_stock.read_cookie_report(cookie_path)
        except Exception:
            cookie, dropped = "", []
        if cookie and dropped:
            #  A tick or a curly quote pasted in with the cookie cannot go in a
            #  request; dropping it usually still works, so it is said rather
            #  than refused - and said here, before the site claims the session
            #  is bad.
            app.console_line(
                "%s: removed %s from the saved cookie - no header can carry "
                "them. If the site then says you are signed out, copy the "
                "Cookie header again." %
                (info["label"], ", ".join(repr(ch) for ch in dropped)), "dim")
        if not cookie:
            messagebox.showinfo(
                "%s needs your session cookie" % info["label"],
                "%s publishes no list this app can ask for, so it reads the "
                "page you are already signed in to - and that needs your "
                "session cookie, pasted once into:\n\n  %s\n\n"
                "That file is about to open. Paste the whole Cookie header "
                "(all of its cookies are fine, on one line or several), save "
                "it, then press this button again."
                % (info["label"], cookie_path))
            open_market_cookie(app, site_id)
            return
        if not url:
            messagebox.showinfo(
                "No address saved for %s" % info["label"],
                "Set the %s page address in User Settings first." % info["label"])
            return
        creds = credentials()
        if not creds:
            return
        site_creds[site_id] = creds
        statuses[site_id].configure(text="reading...")
        summary.configure(text="Reading %s ..." % info["label"])
        app.console_line("Reading %s ..." % url, "cmd")
        in_background(
            app,
            lambda: market_read(site_id, info, url, cookie),
            lambda result, error: market_done(site_id, info, result, error,
                                              creds))

    def read_saved_page(site_id):
        """Read a page the person saved from their own signed-in browser.

        This is how eBay and Facebook are read when the site refuses the app's
        request: the browser has the page, Ctrl+S keeps it, and the parser
        here is the same one that reads a fetched page.
        """
        info = market_stock.SITES[site_id]
        path = filedialog.askopenfilename(
            title="Choose the %s page you saved from your browser" %
                  info["label"],
            initialdir=str(BASE),
            filetypes=[("Saved page", "*.html *.htm"), ("All files", "*.*")])
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            messagebox.showerror("Could not open that file", str(exc),
                                 parent=box.winfo_toplevel())
            return
        items = market_stock.parse_listings(site_id, text)
        if not items:
            messagebox.showwarning(
                "No listing could be read from that page",
                "%s looks like %s, but no listing in it could be read.\n\n"
                "Make sure it is the signed-in %s page itself, not the sign-in "
                "page or a listing form." %
                (Path(path).name, market_stock.describe(text),
                 info["label"]), parent=box.winfo_toplevel())
            app.console_line("%s: %s has no listing this reader recognises."
                             % (info["label"], Path(path).name), "err")
            return
        creds = credentials()
        if not creds:
            return
        statuses[site_id].configure(text="%d listings" % len(items))
        state["label"] = info["label"]
        state["mode"] = "listed" if site_id == "facebook" else "count"
        app.console_line("%s: %d listings read from the saved page %s." %
                         (info["label"], len(items), Path(path).name), "cmd")
        compare_items(items, info["label"], state["mode"], creds)

    # --------------------------------------------------------------- layout
    ttk.Label(box, text="Compare with your website", style="H2.TLabel").pack(
        anchor="w")
    row = ttk.Frame(box)
    row.pack(anchor="w", pady=(2, 0))
    ttk.Button(row, text="Compare stock (WooCommerce and CanadianShopper)",
               style="Task.TButton", command=compare_cs).pack(side="left")
    ttk.Button(row, text="Compare stock with eBay",
               command=lambda: compare_market("ebay")).pack(side="left", padx=8)
    ttk.Button(row, text="Compare stock with Facebook",
               command=lambda: compare_market("facebook")).pack(side="left")

    row_saved = ttk.Frame(box)
    row_saved.pack(anchor="w", pady=(2, 0))
    ttk.Button(row_saved, text="Read a saved eBay page...",
               command=lambda: read_saved_page("ebay")).pack(side="left")
    ttk.Button(row_saved, text="Read a saved Facebook page...",
               command=lambda: read_saved_page("facebook")).pack(
                   side="left", padx=8)

    if focus:
        focus_label = ttk.Label(box, text="Only this card: " + focus,
                                style="H2.TLabel", wraplength=680,
                                justify="left")
        focus_label.pack(anchor="w", pady=(4, 0))

        def compare_everything():
            state["card"] = ""
            focus_label.pack_forget()
            clear_btn.pack_forget()
            app.console_line("Comparing the whole catalogue now.", "dim")

        clear_btn = ttk.Button(box, text="Compare the whole catalogue instead",
                               command=compare_everything)
        clear_btn.pack(anchor="w", pady=(2, 0))

    summary = ttk.Label(box, text="Nothing compared yet.", style="Dim.TLabel",
                        wraplength=680, justify="left")
    summary.pack(anchor="w", pady=(2, 0))

    list_frame = ttk.Frame(box)
    listing = tk.Listbox(list_frame, height=9, exportselection=False,
                         selectmode="extended")
    scroll = ttk.Scrollbar(list_frame, orient="vertical",
                           command=listing.yview)
    listing.configure(yscrollcommand=scroll.set)
    listing.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    #  The actions belong to the list and sit right under it, so "fix this" is
    #  never a scroll away from what it fixes.
    action_row = ttk.Frame(box)
    first = ttk.Frame(action_row)
    first.pack(anchor="w")
    ttk.Button(first, text="Set CanadianShopper to the website's counts...",
               style="Task.TButton", command=set_all).pack(side="left")
    ttk.Button(first, text="Fix the selected cards...",
               command=set_selected).pack(side="left", padx=6)
    second = ttk.Frame(action_row)
    second.pack(anchor="w", pady=(3, 0))
    ttk.Button(second, text="Set the website to the selected cards' counts...",
               command=set_website_selected).pack(side="left")
    ttk.Button(second, text="Open the selected cards on the website",
               command=open_on_website).pack(side="left", padx=6)
    third = ttk.Frame(action_row)
    third.pack(anchor="w", pady=(3, 0))
    ttk.Button(third, text="List the selected cards on CanadianShopper...",
               style="Task.TButton", command=list_selected).pack(side="left")
    ttk.Button(third, text="List every website-only card...",
               command=list_every_website_only_card).pack(side="left", padx=6)
    fourth = ttk.Frame(action_row)
    fourth.pack(anchor="w", pady=(3, 0))
    ttk.Button(fourth, text="Ignore the selected cards",
               command=ignore_selected).pack(side="left")
    ttk.Button(fourth, text="Restore ignored cards...",
               command=restore_ignored).pack(side="left", padx=6)
    action_row.pack_forget()

    #  Shown only when a comparison finds listings that exist but are not on
    #  sale: a count cannot activate those, publishing can.
    publish_ready = ttk.Button(
        box, text="Publish the ready drafts...",
        command=lambda: publish_drafts(
            0, "Some of these cards have a draft listing on CanadianShopper. "
               "Publishing activates the drafts that pass every readiness "
               "check; a draft that is not ready is left alone."))
    publish_ready.pack_forget()

    ttk.Label(box,
              text="The list is what needs attention: a card whose two counts "
                   "differ, a card whose listing on the other site is not on "
                   "sale, or a card that exists on one side only. The "
                   "website is usually the right one, so the first button sets "
                   "every differing count to the website's - after showing "
                   "exactly what would change and asking. Select rows to fix "
                   "or ignore just those; ignoring a card that is not on the "
                   "other site stops it being compared again, and nothing on "
                   "either site is changed by comparing or by ignoring. When "
                   "the website is the one that is wrong, select the card and "
                   "set the website to the other side's count - the same "
                   "confirmation applies, and Read/Write keys are needed - or "
                   "open its product page and change it there. A card that is "
                   "on the website and no longer on CanadianShopper can be put "
                   "back: the listing buttons write the same import file the "
                   "batch pipeline writes, from the website product itself, "
                   "then offer to import it and publish the drafts - all with "
                   "the publisher's own confirmations, including the typed "
                   "PUBLISH.",
              style="Dim.TLabel", wraplength=680, justify="left").pack(
                  anchor="w", pady=(6, 0))

    # ---------------------------------------------------------- sessions
    ttk.Label(box, text="Your eBay and Facebook sessions", style="H2.TLabel"
              ).pack(anchor="w", pady=(12, 0))
    for site_id, caption in (("ebay", "Open the eBay cookie file"),
                             ("facebook", "Open the Facebook cookie file")):
        info = market_stock.SITES[site_id]
        line = ttk.Frame(box)
        line.pack(anchor="w", pady=(2, 0))
        ttk.Button(line, text=caption,
                   command=lambda s=site_id: open_market_cookie(app, s)
                   ).pack(side="left")
        label = ttk.Label(line, text="no session saved" if not (
            BASE / info["cookie"]).is_file() else "session saved",
            style="Dim.TLabel")
        label.pack(side="left", padx=(6, 0))
        statuses[site_id] = label

    ttk.Label(box,
              text="Both sites need a signed-in session, and both check "
                   "whether a request comes from a browser - eBay answers "
                   "with a \"Pardon our interruption\" page and Facebook with "
                   "HTTP 400. When that happens the app says so and changes "
                   "nothing: save the page from your browser with Ctrl+S "
                   "(HTML only) and use the \"Read a saved page\" button, which "
                   "uses the same reader. The cookie goes in ebay-cookie.txt "
                   "or fb-cookie.txt; the whole Cookie header can be pasted at "
                   "once, on one line or several. A copy of every page read is "
                   "kept beside the app (ebay-active.html, fb-selling.html) "
                   "and is never sent anywhere.",
              style="Dim.TLabel", wraplength=680, justify="left").pack(
                  anchor="w", pady=(6, 0))



def build_plugins(parent, app):
    panel_header(parent, app, "plugins")
    box = ttk.Frame(parent)
    box.pack(fill="both", expand=True)
    panel_note(parent, (
        "Plugins are optional code packages. Install only ZIPs from a "
        "source you trust; a plugin can access files and accounts available "
        "to this Windows user. The app checks metadata but does not sandbox "
        "plugin code."))

    listing = ttk.Frame(box)
    listing.pack(fill="both", expand=True, pady=(2, 8))

    def refresh():
        for child in listing.winfo_children():
            child.destroy()
        plugins = PLUGIN_MANAGER.list_plugins()
        if not plugins:
            ttk.Label(listing, text="No plugins installed.",
                      style="Dim.TLabel").pack(anchor="w", pady=4)
            return
        for plugin in plugins:
            card = ttk.LabelFrame(listing, text=plugin["name"], padding=8)
            card.pack(fill="x", pady=4)
            status = ("Enabled" if plugin["enabled"] else "Disabled")
            if not plugin["compatible"]:
                status = "Needs attention"
            details = "%s  |  version %s  |  %s" % (
                plugin["id"], plugin.get("version") or "?", status)
            ttk.Label(card, text=details, style="Dim.TLabel").pack(anchor="w")
            if plugin.get("description"):
                ttk.Label(card, text=plugin["description"], wraplength=760,
                          justify="left").pack(anchor="w", pady=(3, 2))
            if not plugin["compatible"]:
                ttk.Label(card, text=plugin.get("error", "Invalid plugin"),
                          foreground="#a00000", wraplength=760,
                          justify="left").pack(anchor="w", pady=2)
            else:
                caps = ", ".join(plugin.get("capabilities", [])) or "No actions declared"
                ttk.Label(card, text="Actions: " + caps,
                          style="Dim.TLabel").pack(anchor="w", pady=(2, 4))
            buttons = ttk.Frame(card)
            buttons.pack(anchor="w")
            if plugin["compatible"]:
                next_enabled = not plugin["enabled"]
                ttk.Button(
                    buttons,
                    text="Enable" if next_enabled else "Disable",
                    command=lambda pid=plugin["id"], value=next_enabled:
                        change_enabled(pid, value)).pack(side="left")
            ttk.Button(
                buttons, text="Remove...",
                command=lambda pid=plugin["id"]: remove_plugin(pid)
                ).pack(side="left", padx=6)

    def install_zip():
        path = filedialog.askopenfilename(
            title="Choose a trusted Alex Collect plugin ZIP",
            filetypes=[("Plugin ZIP", "*.zip"), ("All files", "*.*")])
        if not path:
            return
        if not messagebox.askyesno(
                "Install plugin code?",
                "Only install a plugin from a source you trust. Plugin code "
                "runs with your account's permissions and is not sandboxed.\n\n"
                "Install this package?", parent=parent.winfo_toplevel()):
            return
        try:
            plugin = PLUGIN_MANAGER.install_zip(path)
        except Exception as exc:
            messagebox.showerror("Plugin not installed", str(exc),
                                 parent=parent.winfo_toplevel())
            return
        if plugin["id"] == CS_PLUGIN_ID:
            # Prevent the legacy v2.20 app-root copy from taking precedence
            # after the managed plugin has been installed.
            try:
                (BASE / "addon-canadianshopper.txt").unlink()
            except FileNotFoundError:
                pass
        refresh()
        messagebox.showinfo(
            "Plugin installed",
            "%s %s is installed. Restart Alex Collect to activate its "
            "actions." % (plugin["name"], plugin["version"]),
            parent=parent.winfo_toplevel())

    def change_enabled(plugin_id, enabled):
        try:
            plugin = PLUGIN_MANAGER.set_enabled(plugin_id, enabled)
        except PluginError as exc:
            messagebox.showerror("Could not update plugin", str(exc),
                                 parent=parent.winfo_toplevel())
            refresh()
            return
        refresh()
        messagebox.showinfo(
            "Plugin status saved",
            "%s will be %s after you restart Alex Collect." %
            (plugin["name"], "enabled" if enabled else "disabled"),
            parent=parent.winfo_toplevel())

    def remove_plugin(plugin_id):
        plugin = next((item for item in PLUGIN_MANAGER.list_plugins()
                       if item["id"] == plugin_id), None)
        if plugin is None:
            messagebox.showerror("Could not remove plugin",
                                 "Plugin is no longer installed.",
                                 parent=parent.winfo_toplevel())
            refresh()
            return
        version = plugin.get("version") or "(invalid package)"
        if not messagebox.askyesno(
                "Remove plugin?",
                "Remove %s %s? This deletes its installed code, but not "
                "separate app data or settings." %
                (plugin["name"], version),
                parent=parent.winfo_toplevel()):
            return
        try:
            PLUGIN_MANAGER.remove(plugin_id)
        except (PluginError, OSError) as exc:
            messagebox.showerror("Could not remove plugin", str(exc),
                                 parent=parent.winfo_toplevel())
            return
        refresh()
        messagebox.showinfo(
            "Plugin removed", "Restart Alex Collect to update its available actions.",
            parent=parent.winfo_toplevel())

    controls = ttk.Frame(box)
    controls.pack(anchor="w", pady=(4, 0))
    ttk.Button(controls, text="Install from ZIP...", style="Task.TButton",
               command=install_zip).pack(side="left")
    ttk.Button(controls, text="Open plugins folder",
               command=lambda: open_path(PLUGIN_MANAGER.root)).pack(
                   side="left", padx=8)
    ttk.Button(controls, text="Refresh list", command=refresh).pack(side="left")
    ttk.Label(box, text="Plugins are stored in your per-user Alex Collect data folder.",
              style="Dim.TLabel").pack(anchor="w", pady=(6, 0))
    refresh()


def build_checklist(parent, app):
    panel_header(parent, app, "checklist")
    box = ttk.Frame(parent)
    box.pack(fill="x")
    row = ttk.Frame(box)
    row.pack(anchor="w", pady=4)
    ttk.Button(row, text="Open the checklist viewer (tick things off)",
               style="Task.TButton",
               command=lambda: ChecklistViewer(app)).pack(side="left")
    row2 = ttk.Frame(box)
    row2.pack(anchor="w", pady=(4, 0))
    ttk.Button(row2, text="What is outstanding? (--status)",
               command=lambda: app.run_tool(
                   "sold-everywhere.py", ["--status", "--checklist",
                                          str(CHECKLIST)],
                   "What is still outstanding",
                   cwd=app.settings.get("pipeline_dir", str(WORK)))
               ).pack(side="left")
    ttk.Button(row2, text="Open the CSV file",
               command=lambda: open_path(CHECKLIST)).pack(side="left", padx=8)


def build_zerostock(parent, app):
    panel_header(parent, app, "zerostock")
    box = ttk.Frame(parent)
    box.pack(fill="x")

    def go(apply):
        args = ["--zero-stock"] + (["--apply", "--gui-dialogs"] if apply
                                    else [])
        app.run_tool("sold-cards.py", args,
                     "Archive listings at 0 - " + ("APPLY" if apply else
                                                   "preview"),
                     cwd=app.settings.get("pipeline_dir", str(WORK)))

    row = ttk.Frame(box)
    row.pack(anchor="w", pady=4)
    ttk.Button(row, text="Preview: what sits at 0?", command=lambda: go(False)
               ).pack(side="left")
    ttk.Button(row, text="Archive them", command=lambda: go(True)).pack(
        side="left", padx=8)
    ttk.Button(box, text="Put one back on sale (--reactivate is in "
               "SoldCards.bat)", command=lambda: messagebox.showinfo(
                   "Reactivate",
                   "Reactivating needs a stock number per card, so it lives "
                   "in SoldCards.bat (menu 5) for now:\n\n"
                   "SoldCards.bat -> 5 -> the card -> the quantity.")
               ).pack(anchor="w")


def build_square(parent, app):
    panel_header(parent, app, "square")
    box = ttk.Frame(parent)
    box.pack(fill="x")

    def go(paths):
        app.run_tool("make-square.py", paths, "Square up photos",
                     cwd=app.settings.get("pipeline_dir", str(WORK)))

    row = ttk.Frame(box)
    row.pack(anchor="w", pady=4)

    def files():
        fs = filedialog.askopenfilenames(
            title="Choose photo(s) to square up",
            initialdir=app.settings.get("scan_dir", str(BASE)),
            filetypes=[("Images", "*.jpg *.jpeg *.png *.tif *.tiff "
                              "*.bmp *.webp"),
                       ("All files", "*.*")])
        if fs:
            go(list(fs))

    def folder():
        d = filedialog.askdirectory(
            title="Choose a folder of photos",
            initialdir=app.settings.get("scan_dir", str(BASE)))
        if d:
            go([d])

    ttk.Button(row, text="Pick photo(s)...", command=files).pack(side="left")
    ttk.Button(row, text="Pick a folder...", command=folder).pack(
        side="left", padx=8)


def build_ordertext(parent, app):
    """Paste a customer's list of cards and turn it into a WooCommerce order.

    A customer texts a list; this matches each line to a real product and
    writes a draft order. Nothing is charged and no email is sent - the order
    lands in the dashboard as pending, for review, exactly like one typed by
    hand. Without API keys the order list opens and the pasted text is copied
    to the clipboard so it can be pasted into the dashboard.
    """
    panel_header(parent, app, "ordertext")
    box = ttk.Frame(parent)
    box.pack(fill="both", expand=True)

    text = tk.Text(box, height=11, wrap="word", font=("Consolas", 9))
    text.pack(fill="both", expand=True, pady=(2, 4))

    row = ttk.Frame(box)
    row.pack(fill="x")
    notes = getattr(parent, "_notes_frame", None) or box
    panel_note(parent, "Paste the list - one card per line. Numbering, "
               "bullets and a trailing price are ignored.")
    status = ttk.Label(notes, text="", style="Dim.TLabel", wraplength=760,
                       justify="left")
    status.pack(anchor="w", pady=(3, 0))

    def say(message):
        try:
            status.configure(text=message)
        except Exception:
            pass

    discount = tk.StringVar(value="")
    ttk.Label(row, text="Discount %:").pack(side="left")
    ttk.Entry(row, textvariable=discount, width=5).pack(side="left",
                                                       padx=(3, 14))
    ttk.Label(row, text="optional - one discount line on the order",
              style="Dim.TLabel").pack(side="left")

    # -- the pieces --------------------------------------------------------
    def discount_percent():
        """The discount as 0-100, or None when what was typed is unusable.

        None means "ask again": quietly charging full price because a box could
        not be read would be the worst possible outcome on a real order.
        """
        raw = str(discount.get() or "").strip().replace("%", "").strip()
        if not raw:
            return 0.0
        try:
            value = float(raw)
        except ValueError:
            return None
        if not 0 <= value <= 100:
            return None
        return value

    def confirm_order(question):
        """Ask before writing. A long list gets a scrollable window.

        A message box cannot hold 30 card names, and the whole point of the
        confirmation is that the user can read what is about to be created.
        """
        if len(question) < 1200 and question.count("\n") < 20:
            return messagebox.askyesno("Create the order?", question,
                                       parent=app)
        top = tk.Toplevel(app)
        top.title("Create the order?")
        top.transient(app)
        top.geometry("780x540")
        top.grab_set()
        body = ttk.Frame(top)
        body.pack(fill="both", expand=True, padx=8, pady=(8, 3))
        view = tk.Text(body, wrap="word", height=22, state="normal")
        scroll = ttk.Scrollbar(body, orient="vertical", command=view.yview)
        view.configure(yscrollcommand=scroll.set)
        view.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        view.insert("1.0", question)
        view.configure(state="disabled")
        result = {"ok": False}
        buttons = ttk.Frame(top)
        buttons.pack(fill="x", padx=8, pady=6)
        ttk.Button(buttons, text="Create the order",
                   command=lambda: (result.update(ok=True), top.destroy())
                   ).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=top.destroy).pack(
            side="right", padx=8)
        top.protocol("WM_DELETE_WINDOW", top.destroy)
        attach_tooltips(top)
        app.wait_window(top)
        return result["ok"]

    def open_orders(site=""):
        url = woo_orders.orders_admin_url(
            site or read_woo_credentials()[0] or
            app.settings.get("woo_site_url", ""))
        if url:
            app.open_webpages([url])
        return url

    def copy_to_clipboard(lines):
        """Leave the list on the clipboard for pasting into the dashboard."""
        try:
            app.clipboard_clear()
            app.clipboard_append("\n".join(lines))
            return True
        except Exception:
            return False

    def search_products(term, site, key, secret):
        """One product search, trimmed to what an order needs."""
        try:
            code, data = woo_get(site, "/wp-json/wc/v3/products",
                                 {"search": term, "per_page": 30}, key, secret)
        except Exception:
            return []
        if code != 200 or not isinstance(data, list):
            return []
        return [{"id": product.get("id"),
                 "name": (product.get("name") or "").strip(),
                 "price": product.get("price") or "",
                 "sku": (product.get("sku") or "").strip(),
                 "stock_status": product.get("stock_status") or ""}
                for product in data
                if isinstance(product, dict) and product.get("id")]

    def candidates_for(name, site, key, secret):
        """Every product worth showing for one pasted line."""
        found, seen = [], set()
        for term in woo_orders.search_terms(name):
            for product in search_products(term, site, key, secret):
                if product["id"] not in seen:
                    seen.add(product["id"])
                    found.append(product)
            if woo_orders.auto_pick(name, found):
                break
        return found

    def describe(product):
        """One list-row label: name, price, stock, match strength."""
        price = woo_orders.price_of(product)
        bits = [product.get("name") or "(untitled)"]
        if price is not None:
            bits.append("$%.2f" % price)
        if product.get("stock_status") == "outofstock":
            bits.append("OUT OF STOCK")
        return "   ".join(bits)

    def pick_card(name, candidates, site, key, secret):
        """Ask which product a line means. Product, "skip", or False to stop."""
        top = tk.Toplevel(app)
        top.title("Which card is this?")
        top.transient(app)
        top.geometry("760x360")
        top.grab_set()
        ttk.Label(top, text="Not sure which card this means:\n%s" % name,
                  wraplength=720, justify="left").pack(anchor="w", padx=8,
                                                       pady=(8, 4))
        ttk.Label(top, text="Pick the right one, or search again with other "
                            "words.", style="Dim.TLabel").pack(anchor="w",
                                                               padx=8)
        term = tk.StringVar(value=(woo_orders.search_terms(name) or [name])[0])
        search_row = ttk.Frame(top)
        search_row.pack(fill="x", padx=8, pady=4)
        entry = ttk.Entry(search_row, textvariable=term)
        entry.pack(side="left", fill="x", expand=True)
        listing = tk.Listbox(top, height=9, exportselection=False)
        listing.pack(fill="both", expand=True, padx=8)
        chosen = {"product": None, "stop": False, "shown": []}

        def show(products):
            chosen["shown"] = list(products)
            listing.delete(0, "end")
            for product in products:
                listing.insert("end", describe(product))
            if products:
                listing.selection_set(0)

        def do_search():
            show(search_products(term.get().strip(), site, key, secret))

        def use(*_event):
            picked = listing.curselection()
            if picked and chosen["shown"]:
                chosen["product"] = chosen["shown"][picked[0]]
            top.destroy()

        def skip():
            chosen["product"] = "skip"
            top.destroy()

        def stop():
            chosen["product"] = False
            top.destroy()

        buttons = ttk.Frame(top)
        buttons.pack(fill="x", padx=8, pady=6)
        ttk.Button(buttons, text="Use this card", command=use).pack(
            side="right")
        ttk.Button(buttons, text="Skip this one", command=skip).pack(
            side="right", padx=8)
        ttk.Button(buttons, text="Cancel all", command=stop).pack(side="left")
        ttk.Button(buttons, text="Search", command=do_search).pack(side="left",
                                                                 padx=8)
        listing.bind("<Double-Button-1>", use)
        entry.bind("<Return>", lambda *_: do_search())
        show(candidates)
        attach_tooltips(top)
        app.wait_window(top)
        return chosen["product"]

    def ask_target(site, key, secret):
        """("new"|"existing", order_id) - or (None, None) when cancelled."""
        choice = messagebox.askyesnocancel(
            "New order or an existing one?",
            "Yes  - start a NEW order for these cards\n"
            "No   - add them to an order that already exists\n"
            "Cancel - stop here", parent=app)
        if choice is None:
            return None, None
        if choice:
            return "new", None
        answer = simpledialog.askstring(
            "Which order?", "Order number (the # shown in the order list):",
            parent=app)
        if answer is None:
            return None, None
        try:
            order_id = int(str(answer).strip().lstrip("#"))
        except ValueError:
            messagebox.showwarning("Not an order number",
                                   "%r is not an order number." % answer,
                                   parent=app)
            return None, None
        try:
            order = woo_orders.read_order(site, key, secret, order_id)
        except woo_orders.OrderError as exc:
            messagebox.showwarning("Could not open that order", exc.message,
                                   parent=app)
            return None, None
        return "existing", order

    def confirm_text(plan, skipped, target, order, percent):
        """What is about to happen, in the words the user can check."""
        estimate = woo_orders.estimate_total(plan, percent)
        lines = ["%d lines read: %d matched, %d skipped." %
                 (len(plan) + len(skipped), len(plan), len(skipped)), ""]
        if target == "existing":
            lines.append("Added to order #%s, which already holds %d card(s)."
                         % (order.get("number") or order.get("id"),
                            len(order.get("line_items") or [])))
        else:
            lines.append("A new order will hold:")
        lines.append("")
        merged = woo_orders.merge_duplicates(plan)
        for item in merged[:22]:
            price = woo_orders.price_of(item.get("product") or {})
            lines.append("  %-2d  %s%s" % (
                item["quantity"], (item.get("product") or {}).get(
                    "name", "(untitled)"),
                "" if price is None else "   $%.2f" % price))
        if len(merged) > 22:
            lines.append("  ... and %d more" % (len(merged) - 22))
        lines.append("")
        if estimate["priced"]:
            lines.append("Subtotal  $%.2f" % estimate["subtotal"])
            if estimate["discount"]:
                lines.append("Discount %g%%  -$%.2f" % (percent,
                                                       estimate["discount"]))
            lines.append("Total     $%.2f" % estimate["total"])
        if estimate["unpriced"]:
            lines.append("(%d card(s) have no price on the website)"
                         % estimate["unpriced"])
        if skipped:
            lines.append("")
            lines.append("Not on the website (left out):")
            for name in skipped[:10]:
                lines.append("  %s" % name)
            if len(skipped) > 10:
                lines.append("  ... and %d more" % (len(skipped) - 10))
        lines.append("")
        lines.append("Nothing is charged and no email is sent. Continue?")
        return "\n".join(lines)

    def finish(target, order, site, key, secret, percent, names):
        """Look the lines up, ask about the unclear ones, then write."""
        say("Looking up %d cards..." % len(names))
        pairs = []

        def work():
            for index, name in enumerate(names, 1):
                try:
                    found = candidates_for(name, site, key, secret)
                except Exception:
                    #  A lookup that fails is not a match; the picker below
                    #  still lets the line be searched by hand.
                    found = []
                pairs.append((name, found))
                app.after(0, lambda i=index, n=name: say(
                    "Looked up %d of %d: %s" % (i, len(names), n[:50])))
            app.after(0, lambda: assemble(pairs))

        def assemble(pairs):
            plan, skipped = [], []
            for name, candidates in pairs:
                product = woo_orders.auto_pick(name, candidates)
                if product is None:
                    picked = pick_card(name, candidates, site, key, secret)
                    if picked is False:
                        say("Cancelled - nothing was sent.")
                        return
                    if picked == "skip" or picked is None:
                        skipped.append(name)
                        continue
                    product = picked
                plan.append({"product_id": product["id"], "quantity": 1,
                             "line": name, "product": product})
            say("")
            if not plan:
                messagebox.showinfo(
                    "Nothing matched",
                    "None of those lines matched a card on the website, so "
                    "no order was created.", parent=app)
                return
            #  Two lines asking for the same card become one row of quantity 2,
            #  so the order reads the way a person would write it.
            plan = woo_orders.merge_duplicates(plan)
            question = confirm_text(plan, skipped, target, order, percent)
            if not confirm_order(question):
                say("Cancelled - nothing was sent.")
                return
            say("Writing the order...")
            try:
                if target == "existing":
                    result = woo_orders.add_to_order(
                        site, key, secret, order["id"], plan,
                        discount_percent=percent)
                else:
                    result = woo_orders.create_order(
                        site, key, secret, plan, discount_percent=percent)
            except woo_orders.OrderError as exc:
                messagebox.showerror("The order was not written", exc.message,
                                     parent=app)
                app.console_line("Order: %s" % exc.message, "err")
                say("The order was not written.")
                return
            number = result.get("number") or result.get("id")
            app.console_line("Order #%s written on the website (%d cards%s)."
                             % (number, len(result.get("line_items") or []),
                                ", %d skipped" % len(skipped) if skipped
                                else ""), "ok")
            say("Order #%s is ready - opening it now." % number)
            url = woo_orders.order_edit_url(site, result.get("id"))
            if url:
                app.open_webpages([url])

        threading.Thread(target=work, daemon=True).start()

    def start():
        names = woo_orders.parse_card_list(text.get("1.0", "end"))
        if not names:
            messagebox.showinfo(
                "Paste a list first",
                "Paste the customer's list into the box, one card per line.",
                parent=app)
            return
        site, key, secret = read_woo_credentials()
        if not (site and key and secret):
            copied = copy_to_clipboard(names)
            open_orders(app.settings.get("woo_site_url", ""))
            messagebox.showinfo(
                "Order list opened",
                "%d card names read.\n\nNo website API keys are saved, so the "
                "order list is open instead%s." % (
                    len(names), " and the list is on your clipboard - paste it "
                    "into the order's card search" if copied else ""),
                parent=app)
            return
        percent = discount_percent()
        if percent is None:
            messagebox.showwarning(
                "Discount not understood",
                "Type a number between 0 and 100 in the discount box, or "
                "leave it empty to charge full price.", parent=app)
            return
        target, order = ask_target(site, key, secret)
        if target is None:
            say("Cancelled - nothing was sent.")
            return
        finish(target, order, site, key, secret, percent, names)

    ttk.Button(row, text="Build the order", command=start).pack(side="right")
    ttk.Button(row, text="Open the order list",
               command=lambda: open_orders()).pack(side="right", padx=8)


def build_newphotos(parent, app):
    """Replace one card's photos, then put every marketplace page on screen.

    The old version wrote reminder rows into the checklist; it now does the
    job instead of describing it: find the product, open the folder holding
    the replacements, offer the 9-card split, and open the WordPress edit page
    plus the other marketplaces. With the CanadianShopper plugin installed the
    staged photos can be re-wired too.
    """
    panel_header(parent, app, "newphotos")
    box = ttk.Frame(parent)
    box.pack(fill="x")
    #  What the panel *says* lives underneath the work: the sheets summary and
    #  the running status are read after the card is found, not before.
    notes = getattr(parent, "_notes_frame", None) or box

    keys_file = BASE / "woo-keys.txt"
    term = tk.StringVar(master=box)
    sheets_text = {"label": None}     # set once the strip is built below
    hint = ttk.Label(notes, text="", style="Dim.TLabel", wraplength=760,
                     justify="left")

    def status(text):
        hint.configure(text=text)

    # -- finding the product ------------------------------------------------
    def ask_for_keys():
        """Offer the API-key setup; True when the user wants it right now."""
        enter = messagebox.askyesno(
            "Save your website API keys?",
            "Alex Collect can look the card up on your website and open its "
            "product edit page directly.\n\n"
            "That uses the WooCommerce keys in woo-keys.txt - the same pair "
            "the rest of the app uses, read-only being enough for the lookup. "
            "It is a one-time setup, and every later photo replacement becomes "
            "one click instead of a search.\n\n"
            "Enter the keys now?", parent=app)
        if not enter:
            return False
        open_woo_keys_file(app, app.settings.get("woo_site_url", ""))
        status("Fill in woo-keys.txt, save it, then press Find again.")
        return True

    def choose_product(rows, query):
        """Pick one of several matching products; None means cancelled."""
        top = tk.Toplevel(app)
        top.title("Which product?")
        top.transient(app)
        top.geometry("640x360")
        top.grab_set()
        ttk.Label(top, text="Several products match %r. Pick the one whose "
                  "photos need replacing:" % query, wraplength=600,
                  justify="left").pack(anchor="w", padx=8, pady=(8, 4))
        listing = tk.Listbox(top, height=13, exportselection=False)
        for row in rows:
            text = row["name"] or "(untitled)"
            if row["sku"]:
                text += "   [%s]" % row["sku"]
            listing.insert("end", text)
        listing.pack(fill="both", expand=True, padx=8)
        listing.selection_set(0)
        chosen = {"row": None}

        def accept(*_event):
            picked = listing.curselection()
            if picked:
                chosen["row"] = rows[picked[0]]
            top.destroy()

        buttons = ttk.Frame(top)
        buttons.pack(fill="x", padx=8, pady=6)
        ttk.Button(buttons, text="Use this product",
                   command=accept).pack(side="right")
        ttk.Button(buttons, text="Cancel",
                   command=top.destroy).pack(side="right", padx=8)
        listing.bind("<Double-Button-1>", accept)
        attach_tooltips(top)
        app.wait_window(top)
        return chosen["row"]

    def find_product(query):
        """Product dict, None when no lookup was possible, False if cancelled."""
        site, key, secret = read_woo_credentials(keys_file)
        status("Looking for %r on %s ..." % (query, site))
        try:
            code, data = woo_get(site, "/wp-json/wc/v3/products",
                                 {"search": query, "per_page": 20}, key, secret)
        except Exception as exc:
            messagebox.showwarning(
                "Lookup failed",
                "Could not search your website:\n%s\n\nThe product list will "
                "open instead - pick the card there." % exc, parent=app)
            return None
        if code != 200 or not isinstance(data, list):
            messagebox.showwarning(
                "Lookup failed",
                "Your website answered HTTP %s.\n\nThe product list will open "
                "instead - pick the card there." % code, parent=app)
            return None
        # Keep the images: the replacement is named after the card's current
        # website image, so dropping them here would silently fall back to the
        # scan's own filename.
        rows = [{"id": p.get("id"), "name": (p.get("name") or "").strip(),
                 "sku": (p.get("sku") or "").strip(),
                 "images": p.get("images") or []}
                for p in data if isinstance(p, dict) and p.get("id")]
        if not rows:
            messagebox.showinfo(
                "No product found",
                "Nothing on your website matches %r.\n\nThe filtered product "
                "list will open so you can look by hand." % query, parent=app)
            return None
        if len(rows) == 1:
            return rows[0]
        return choose_product(rows, query) or False

    # -- the photo work -----------------------------------------------------
    def wire_args():
        """The wire arguments the whole-batch path uses."""
        return ["--mode", "wire", "--cookie-file", str(CS_COOKIE_FILE),
                "--ready-dir", str(canadianshopper_ready_dir(app)),
                "--cache", str(canadianshopper_cache_path(app))]

    def replace_args(title, front, back=None):
        """The CSV-free per-card arguments (plugin 1.0.15 and newer)."""
        args = ["--mode", "replace", "--title", str(title),
                "--front", str(front), "--cookie-file", str(CS_COOKIE_FILE)]
        if back:
            args += ["--back", str(back)]
        return args

    def replace_dir():
        """Where the chosen replacements are written for this batch."""
        folder = Path(app.settings.get("pipeline_dir") or WORK) / "replacements"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    #  The sheets stay loaded for the whole sitting, so the second card does
    #  not mean splitting the scan again - and the images already used are not
    #  offered for the next one.
    pool = getattr(app, "photo_pool", None)
    if pool is None:
        #  Kept on the app, not on the panel: the tab is rebuilt when it is
        #  opened again, and re-splitting the sheets each time would throw away
        #  which images had already been used.
        pool = photo_pool.PhotoPool()
        app.photo_pool = pool

    def sheet_files():
        return [("Images", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp"),
                ("All files", "*.*")]

    def add_sheets():
        """Load one or more replacement sheets; False when nothing was added."""
        chosen = filedialog.askopenfilenames(
            title="Which replacement sheets? (front first, then back)",
            initialdir=app.settings.get("scan_dir", str(BASE)),
            filetypes=sheet_files())
        if not chosen:
            return False
        chosen = list(chosen) if not isinstance(chosen, str) else [chosen]
        pool.tiles_dir = replace_dir()
        failed, added = [], 0
        #  Splitting a high-resolution scan takes seconds, and this used to run
        #  with nothing on screen at all - no dialog, no bar, no change - which
        #  is indistinguishable from a hung program. The window names the sheet
        #  being worked on and the bar moves once per sheet.
        total = len(chosen)
        status("Reading %d scan%s - a big one takes a few seconds..." % (
            total, "" if total == 1 else "s"))
        try:
            app.update_idletasks()
        except Exception:
            pass
        progress = ProgressWindow(
            app, "Reading your scans",
            "Splitting %s into card images. A high-resolution scan takes a "
            "few seconds; nothing is saved until it is done."
            % Path(chosen[0]).name, total=total)
        try:
            for index, path in enumerate(chosen, start=1):
                progress.step("Splitting %s (%d of %d)..." %
                              (Path(path).name, index, total),
                              done=index - 1, total=total)
                try:
                    pool.add_sheet(path, index=len(pool.sheets))
                except photo_pool.PhotoPoolError as exc:
                    failed.append("%s: %s" % (Path(path).name, exc))
                    continue
                added += 1
                progress.step(done=index, total=total)
        finally:
            progress.close()
        refresh_sheets()
        if failed:
            messagebox.showwarning(
                "Some sheets were not added", "\n".join(failed), parent=app)
        if added:
            status("%d sheet%s loaded - %d images to use." % (
                added, "" if added == 1 else "s", len(pool.unused())))
        return bool(added)

    def refresh_sheets():
        """Say what is loaded, and how much of it is still unused."""
        label = sheets_text["label"]
        if label is None:
            return
        if not pool.sheets:
            label.configure(text="No replacement sheets loaded yet - Add "
                            "sheets starts here, and they stay loaded for the "
                            "next card too.")
            return
        used, total = pool.progress()
        label.configure(text="  |  ".join(pool.summary()) +
                        "     (%d of %d images used)" % (used, total))

    def clear_sheets():
        pool.clear()
        #  The pictures belong to the sheets that just went away, so they go
        #  too rather than being kept for names that will never come back.
        if getattr(app, "_tile_thumbs", None) is not None:
            app._tile_thumbs.clear()
        refresh_sheets()
        status("Sheets cleared.")

    def ensure_images():
        """Make sure a free image is there to pick; say so when none is left.

        Sheets stay loaded for the whole sitting, and each card takes a front
        and a back off them, so a long sitting does eventually use the lot.
        Pressing Find then used to do nothing whatsoever - the button looked
        broken rather than finished - so the dead end is spoken instead.
        """
        if pool.unused():
            return True
        add_sheets()
        if pool.unused():
            return True
        if pool.sheets:
            _used, total = pool.progress()
            status("Every image on the loaded sheets has been used. Add "
                   "another sheet, or press Clear and load these again.")
            messagebox.showinfo(
                "That is the whole sheet",
                "All %d images on the loaded sheets already have a card.\n\n"
                "Add another scan to carry on, or press Clear and load the "
                "sheet again." % total, parent=app)
        return False

    def upload_to_site(app, product, front_path, back_path=None,
                       old_pair_ids=()):
        """Upload the pair and make it the product's photos on the website.

        Returns True when the website was updated. Nothing is sent when the
        site, the keys, or the user's consent are missing.
        """
        site, key, secret = read_woo_credentials()
        wp_site, username, app_password = read_wordpress_credentials()
        photos = " and ".join(Path(x).name for x in
                              (front_path, back_path) if x is not None)
        if not (key and secret):
            return False
        if not (username and app_password):
            #  Only ask once per session; a repeated nag is worse than a
            #  manual upload, and the offer is still here next time the app
            #  starts.
            if not getattr(app, "_wp_upload_asked", False):
                app._wp_upload_asked = True
                if messagebox.askyesno(
                        "Upload replacements straight from here?",
                        "Alex Collect can upload the new photos and set them "
                        "on the product by itself.\n\nThat needs two more "
                        "lines in woo-keys.txt: your WordPress username and an "
                        "Application Password (Users > Profile > Application "
                        "Passwords).\n\nAdd them now? The file is private and "
                        "only this account can read it.", parent=app):
                    open_woo_keys_file(app, site)
            return False
        base = woo_media.site_root(wp_site or site)
        if not base:
            return False
        if not woo_media.is_https(base):
            messagebox.showwarning(
                "HTTPS needed",
                "WordPress only accepts an Application Password over HTTPS, "
                "and the saved address is %s.\n\nThe photos are saved; "
                "upload them from the media library instead." % base,
                parent=app)
            return False

        #  The old pair comes off the product before the new one goes on, so a
        #  listing never carries two backs. Removing a photo from a product is
        #  not deleting it: the file stays in the media library.
        rows = woo_media.existing_images(product)
        remove_ids = list(old_pair_ids)
        if back_path is not None:
            #  A gallery that predates the -front/-back naming has no readable
            #  back, and pair_ids() would quietly treat the first row as the
            #  only one to replace - leaving the old back beside the new one.
            #  Ask instead of assuming.
            try:
                import photo_replace
                unread = photo_replace.unread_back_rows(rows)
            except ImportError:
                unread = []
            #  The row already being replaced as the front is not a candidate
            #  for the back, so it is not offered again.
            unread = [row for row in unread
                      if row["id"] not in set(remove_ids)]
            if unread:
                choice = choose_old_back(unread, product.get("name") or "")
                if choice.get("cancel"):
                    return False
                remove_ids += [i for i in (choice.get("remove") or [])
                               if i not in remove_ids]

        staying = [row for row in rows if row["id"] not in set(remove_ids)]
        leaving = [row for row in rows if row["id"] in set(remove_ids)]
        plan = ["Upload %s and make them the photos for:" % photos, "",
                product.get("name") or "(untitled product)"]
        if leaving:
            plan += ["", "Taken off this product (the image files stay in "
                     "your media library):"]
            plan += ["  - %s" % (row["name"] or row["id"]) for row in leaving]
        if staying:
            plan += ["", "Left alone:"]
            plan += ["  - %s" % (row["name"] or row["id"]) for row in staying]
        plan += ["", "Yes - take those off and put the new photos on",
                 "No - add the new photos and leave every existing one",
                 "Cancel - do not upload"]
        #  Yes means "replace the old pair", which is the opposite of keeping
        #  it - an easy inversion, so the name says what the answer means.
        replace_old = messagebox.askyesnocancel(
            "Put these photos on the website?", "\n".join(plan), parent=app)
        if replace_old is None:
            return False
        if replace_old:
            keep_ids = [row["id"] for row in staying]
        else:
            keep_ids = None
        status("Uploading %s..." % photos)
        try:
            result = woo_media.replace_product_photos(
                base, key, secret, username, app_password, product,
                front_path, back_path, keep_ids=keep_ids)
        except woo_media.MediaError as exc:
            (messagebox.showwarning if exc.partial else messagebox.showerror)(
                "The photos were not put on the product", exc.message,
                parent=app)
            app.console_line("Photo upload: %s" % exc.message, "err")
            status("The photos are saved, but the website was not updated.")
            return False
        front = result["front"]
        app.console_line("Uploaded %s to the website (media ID %s)." %
                         (Path(front_path).name, front["id"]), "ok")
        if result.get("back"):
            app.console_line("Uploaded %s to the website (media ID %s)." %
                             (Path(back_path).name, result["back"]["id"]), "ok")
        if replace_old and leaving:
            app.console_line(
                "Removed %s from the product gallery; the image files are "
                "still in your media library." %
                " and ".join(row["name"] or str(row["id"]) for row in leaving),
                "dim")
        status("The website now shows %s." % photos)
        for attachment in (front, result.get("back")):
            if attachment and attachment.get("source_url"):
                app.console_line(attachment["source_url"], "dim")
        return True

    def single_product(product):
        """True when one real product was picked, not a search fallback."""
        return bool(isinstance(product, dict) and product.get("id") and
                    str(product.get("name") or "").strip())

    def choose_tile(candidates, question, more_scan=None, preselect=None):
        """Let the user pick one image by looking at it; None means no choice.

        The tiles are named Scan01_4.webp and so on, which says nothing about
        what is on them, so they are shown as pictures captioned with the slot
        and sheet they came from. When Tk cannot draw the pictures (no image
        support, or a test stub) the same choices fall back to a plain list.

        ``more_scan`` is offered as a button when the wanted image is not on
        this sheet - the back of a card is often scanned with the front, but
        not always, and refusing to look elsewhere would be arbitrary.
        ``preselect`` is the tile proposed before the user decides: normally
        the back in the same slot as the chosen front.
        """
        if not candidates and more_scan is None:
            return None
        if len(candidates) == 1 and more_scan is None and preselect is None:
            return candidates[0]

        tiles_by_path = {str(t.get("path")): t for t in candidates}
        #  Decoding nine tiles is quick, but it used to happen before the
        #  window existed - so a slow first decode showed nothing at all and
        #  the program looked hung. One cache per sitting also means the
        #  second card reuses these pictures instead of reading them again.
        thumbs = getattr(app, "_tile_thumbs", None)
        if thumbs is None:
            thumbs = photo_thumbs.Thumbnails()
            app._tile_thumbs = thumbs
        keep = {}                     # PhotoImage objects Tk must not free
        pictures = {}
        sheet_order = list(dict.fromkeys(str(t.get("sheet_path") or
                                             t.get("sheet") or "")
                                         for t in candidates))
        mixed_sheets = len([x for x in sheet_order if x]) > 1
        mixed_sides = len({t.get("side") or "" for t in candidates}) > 1

        def short_caption(tile):
            """Slot and side, and the sheet only when the grid mixes them."""
            sheet = ""
            if mixed_sheets:
                key = str(tile.get("sheet_path") or tile.get("sheet") or "")
                if key in sheet_order:
                    sheet = "S%d" % (sheet_order.index(key) + 1)
            return photo_thumbs.caption(tile, sheet=sheet, side=mixed_sides)

        #  One picture, made before the window exists, decides whether this
        #  run can show pictures at all: Tk without image support falls back
        #  to the same choices as a plain list. It is also the slowest single
        #  decode, and it is cached, so the grid does not repeat it.
        if candidates:
            first_key = str(candidates[0].get("path"))
            first = photo_thumbs.as_photo(thumbs.get(first_key))
            if first is not None:
                keep[first_key] = first
                pictures[first_key] = first

        top = tk.Toplevel(app)
        top.title("Which image?")
        top.transient(app)
        top.grab_set()
        chosen = {"tile": None}
        shown = {"tiles": list(candidates)}

        def by_picture():
            """Actions on top, the grid in the middle, the words underneath.

            The buttons used to sit below a grid that could be taller than the
            window, so at 800x600 they were simply off-screen; the grid now
            scrolls instead, and every button is reachable without scrolling.
            """
            width = min(900, max(560, app.winfo_screenwidth() - 60))
            height = min(640, max(430, app.winfo_screenheight() - 90))
            top.geometry("%dx%d" % (width, height))
            bar = ttk.Frame(top)
            bar.pack(fill="x", padx=10, pady=(10, 4))
            accept_button = ttk.Button(bar, text="Use this image",
                                       command=lambda: accept())
            accept_button.pack(side="right")
            ttk.Button(bar, text="Cancel", command=top.destroy).pack(
                side="right", padx=8)
            if more_scan is not None:
                ttk.Button(bar, text="Another scan...",
                           command=lambda: another()).pack(side="right",
                                                          padx=8)
            chosen_line = ttk.Label(bar, text="", style="Dim.TLabel")
            chosen_line.pack(side="left")

            holder = ScrollFrame(top)
            holder.pack(fill="both", expand=True, padx=10, pady=(0, 4))
            cells = {}
            state = {"key": None}

            def accept(*_event):
                tile = tiles_by_path.get(state["key"] or "")
                if tile is not None:
                    chosen["tile"] = tile
                top.destroy()

            def choose(key):
                state["key"] = key
                for other, cell in cells.items():
                    picked = other == key
                    cell.configure(
                        highlightbackground="#2f6fd0" if picked else "#d8dce2",
                        highlightthickness=3 if picked else 1)
                tile = tiles_by_path.get(key or "")
                chosen_line.configure(text=short_caption(tile) if tile else "")

            def draw(tiles):
                for child in holder.inner.winfo_children():
                    child.destroy()
                cells.clear()
                shown["tiles"] = list(tiles)
                for row in photo_thumbs.rows(tiles):
                    line = ttk.Frame(holder.inner)
                    line.pack(anchor="w", pady=4)
                    for tile in row:
                        key = str(tile.get("path"))
                        cell = tk.Frame(line, highlightthickness=1,
                                        highlightbackground="#d8dce2")
                        cell.pack(side="left", padx=6)
                        label = ttk.Label(cell)
                        if key in pictures:
                            label.configure(image=pictures[key])
                        label.pack(padx=2, pady=(2, 0))
                        caption = short_caption(tile)
                        if preselect is not None and \
                                str(preselect.get("path")) == key:
                            caption += "  \u00b7 proposed"
                        ttk.Label(cell, text=caption, style="Dim.TLabel",
                                  wraplength=photo_thumbs.THUMB_SIZE[0]
                                  ).pack(padx=2, pady=(0, 2))
                        for widget in (cell, label):
                            widget.bind("<Button-1>",
                                        lambda _e, k=key: choose(k))
                            widget.bind("<Double-Button-1>",
                                        lambda _e, k=key: (choose(k), accept()))
                        cells[key] = cell
                if shown["tiles"]:
                    wanted = None
                    if preselect is not None and \
                            str(preselect.get("path")) in cells:
                        wanted = str(preselect.get("path"))
                    choose(wanted or str(shown["tiles"][0].get("path")))

            def load_pictures(tiles):
                """Fill in the pictures after the window is on screen."""
                for index, tile in enumerate(tiles, start=1):
                    key = str(tile.get("path"))
                    if key in pictures:
                        continue
                    photo = photo_thumbs.as_photo(thumbs.get(key))
                    if photo is not None:
                        keep[key] = photo
                        pictures[key] = photo
                        if index % 3 == 0:
                            #  Paint the ones already done rather than
                            #  showing an empty grid until the last tile.
                            try:
                                top.update_idletasks()
                            except Exception:
                                pass

            draw(candidates)
            #  The window is up and answering before the first picture is
            #  decoded, so even a slow scan shows "opening" instead of nothing.
            try:
                top.update_idletasks()
            except Exception:
                pass
            load_pictures(shown["tiles"])
            draw(shown["tiles"])

            def another():
                tiles = more_scan()
                if not tiles:
                    return
                for tile in tiles:
                    tiles_by_path[str(tile.get("path"))] = tile
                draw(tiles)
                load_pictures(tiles)
                draw(tiles)

            ttk.Label(top, text=question, wraplength=max(500, width - 40),
                      justify="left").pack(anchor="w", padx=10)
            ttk.Label(top, text="These are the card images on your sheets - "
                      "pick the one that belongs to this card. The grid "
                      "scrolls; double-click a picture to use it straight "
                      "away.", style="Dim.TLabel",
                      wraplength=max(500, width - 40),
                      justify="left").pack(anchor="w", padx=10, pady=(0, 8))
            accept_button.configure(command=accept)
            top.bind("<Return>", accept)
            attach_tooltips(top)
            app.wait_window(top)
            return chosen["tile"]

        def by_list():
            """The fallback: the same choices as names, without pictures."""
            top.geometry("460x320")
            ttk.Label(top, text=question, wraplength=430,
                      justify="left").pack(anchor="w", padx=8, pady=(8, 4))
            listing = tk.Listbox(top, height=11, exportselection=False)
            listing.pack(fill="both", expand=True, padx=8)

            def fill(tiles):
                shown["tiles"] = list(tiles)
                listing.delete(0, "end")
                keys = []
                for tile in tiles:
                    keys.append(str(tile.get("path")))
                    line = photo_thumbs.describe(tile)
                    if preselect is not None and keys[-1] == \
                            str(preselect.get("path")):
                        line += "   - proposed"
                    listing.insert("end", line)
                if not tiles:
                    return
                #  The proposed image is the one already selected, so pressing
                #  Use this image accepts the pairing without hunting for it.
                wanted = 0
                if preselect is not None and \
                        str(preselect.get("path")) in keys:
                    wanted = keys.index(str(preselect.get("path")))
                listing.selection_set(wanted)

            fill(candidates)

            def accept(*_event):
                picked = listing.curselection()
                if picked and shown["tiles"]:
                    chosen["tile"] = shown["tiles"][picked[0]]
                top.destroy()

            def another():
                tiles = more_scan()
                if tiles:
                    fill(tiles)

            row = ttk.Frame(top)
            row.pack(fill="x", padx=8, pady=6)
            ttk.Button(row, text="Use this image",
                       command=accept).pack(side="right")
            ttk.Button(row, text="Cancel",
                       command=top.destroy).pack(side="right", padx=8)
            if more_scan is not None:
                ttk.Button(row, text="Another scan...",
                           command=another).pack(side="left")
            listing.bind("<Double-Button-1>", accept)
            attach_tooltips(top)
            app.wait_window(top)
            return chosen["tile"]

        return by_picture() if pictures else by_list()

    def choose_old_back(rows, product_name):
        """Ask which gallery row is the old back, when the name does not say.

        A product gallery that predates the ``-front``/``-back`` convention
        cannot be read by filename. Choosing the first row as the front and
        ignoring the rest leaves the old back sitting beside the new one,
        which is how a listing ends up with two backs - so the user is asked.

        Returns ``{"remove": [ids]}``, or ``{"cancel": True}``.
        """
        top = tk.Toplevel(app)
        top.title("Remove the old back from the product?")
        top.transient(app)
        top.geometry("700x420")
        top.grab_set()
        answer = {"cancel": True, "remove": []}
        ttk.Label(top, text=product_name or "This product",
                  font=("TkDefaultFont", 10, "bold"),
                  wraplength=660).pack(anchor="w", padx=10, pady=(10, 2))
        ttk.Label(top, text="None of these photos says whether it is the "
                  "front or the back, so Alex Collect will not guess. Pick "
                  "the one that is the old BACK photo: it is taken off this "
                  "product before the new one goes on.\n\nThe image file is "
                  "not deleted - it stays in your media library.",
                  wraplength=660, justify="left").pack(anchor="w", padx=10,
                                                      pady=(0, 6))
        listing = tk.Listbox(top, height=8, exportselection=False)
        listing.pack(fill="both", expand=True, padx=10)
        for row in rows:
            listing.insert("end", str(row.get("name") or "(no filename)"))
        if rows:
            listing.selection_set(0)

        def take_row(*_event):
            picked = listing.curselection()
            if not picked or not rows:
                messagebox.showinfo("Choose a photo",
                                    "Select the photo that is the old back.",
                                    parent=top)
                return
            answer["cancel"] = False
            answer["remove"] = [rows[picked[0]]["id"]]
            top.destroy()

        def keep_all(*_event):
            answer["cancel"] = False
            answer["remove"] = []
            top.destroy()

        def cancel(*_event):
            answer["cancel"] = True
            top.destroy()

        buttons = ttk.Frame(top)
        buttons.pack(fill="x", padx=10, pady=8)
        ttk.Button(buttons, text="Remove this photo from the product",
                   command=take_row).pack(side="left")
        ttk.Button(buttons, text="Keep every existing photo",
                   command=keep_all).pack(side="left", padx=8)
        ttk.Button(buttons, text="Cancel this card", command=cancel).pack(
            side="right")
        listing.bind("<Double-Button-1>", take_row)
        top.protocol("WM_DELETE_WINDOW", cancel)
        attach_tooltips(top)
        app.wait_window(top)
        return answer

    def wire_card(product, front, back=None):
        """Replace the one card's photos on CanadianShopper, no CSV involved."""

        def after(rc):
            if not rc and back is not None:
                #  The plugin refuses to guess when it cannot identify the
                #  listing's back photo, which leaves the listing untouched.
                #  Saying so beats leaving the user to read the whole log.
                app.console_line(
                    "If that failed because the back photo could not be "
                    "identified, nothing was changed on CanadianShopper. "
                    "Run this card again and choose no back image to replace "
                    "only the front.", "dim")

        script = TOOL_ACTION(CS_PHOTO_REPLACE)
        app.run_tool(script, replace_args(product.get("name"), front, back),
                     "Replace this card's photos",
                     cwd=app.settings.get("pipeline_dir", str(WORK)),
                     on_done=after)
        return True

    def wire_batch(after=None):
        """Re-wire whatever is staged: the whole batch, not one card."""
        app.run_tool(TOOL_ACTION(CS_PHOTO_WIRE) or "cs-image-sync.py",
                     wire_args(), "Wire the replacement photos",
                     cwd=app.settings.get("pipeline_dir", str(WORK)),
                     on_done=after)

    def replace(query, product):
        """Sheet -> tiles -> one chosen image -> named copy -> every page."""
        urls = []
        if isinstance(product, dict) and product.get("id"):
            edit = product_edit_url(product["id"], app.settings)
            if edit:
                urls.append(edit)
            status("Editing %s (product ID %s)." %
                   (product["name"] or query, product["id"]))
        else:
            search = product_search_url(query, app.settings)
            if search:
                urls.append(search)
            status("Product list filtered to %r." % query)
        urls += marketplace_seller_urls(app.settings)

        try:
            import photo_replace
        except ImportError as exc:
            messagebox.showerror("Photo helper missing",
                                 "photo_replace.py could not be loaded:\n%s"
                                 % exc, parent=app)
            return

        def ask_for_sheet(title):
            """Add another sheet to the pool and offer its images."""
            chosen_path = filedialog.askopenfilename(
                title=title, initialdir=app.settings.get("scan_dir", str(BASE)),
                filetypes=sheet_files())
            if not chosen_path:
                return None
            try:
                pool.tiles_dir = replace_dir()
                sheet = pool.add_sheet(chosen_path, index=len(pool.sheets))
            except photo_pool.PhotoPoolError as exc:
                messagebox.showerror("Could not split the scan", "%s" % exc,
                                     parent=app)
                return None
            refresh_sheets()
            return [tile for tile in pool.unused()
                    if tile["sheet_path"] == sheet["path"]]

        #  Sheets first: this is where the sitting starts, and a sitting can
        #  run out - either way the user is told rather than left pressing a
        #  button that does nothing.
        if not ensure_images():
            if urls:
                app.open_webpages(urls)
            return

        label = (product.get("name") if isinstance(product, dict) else query)
        status("%d images left on %d sheet%s." % (
            len(pool.unused()), len(pool.sheets),
            "" if len(pool.sheets) == 1 else "s"))
        front = choose_tile(pool.front_candidates(),
                            "Which image is the FRONT of %s?" % label)
        if front is None:
            if urls:
                app.open_webpages(urls)
            return

        #  Both sheets were filled in the same order, so slot 4 of the back
        #  sheet is almost always the back of slot 4 of the front sheet. That
        #  is proposed, not assumed: when it is the only back left it is used
        #  without a question, and otherwise the picker opens on it.
        proposed = pool.same_slot(front)
        backs = pool.back_candidates(front)
        if proposed is not None and len(backs) == 1:
            back = proposed
            status("Using slot %d of %s as the back." % (
                back["position"], back["sheet"]))
        else:
            back = choose_tile(
                backs, "Which image is the BACK of %s?" % label,
                more_scan=lambda: ask_for_sheet("Which scan holds the BACK?"),
                preselect=proposed)
        if back is None:
            if not messagebox.askyesno(
                    "No back image",
                    "Only a front was chosen, so the back photo will be left "
                    "as it is.\n\nContinue with the front only?", parent=app):
                if urls:
                    app.open_webpages(urls)
                return

        try:
            current = photo_replace.woo_image_name(product)
            written = photo_replace.save_pair(
                replace_dir(), current, front["path"],
                back["path"] if back else None)
        except Exception as exc:
            messagebox.showerror("Could not save the replacement",
                                 "%s" % exc, parent=app)
            return
        saved = written["front"]
        saved_back = written.get("back")
        old_pair_ids = photo_replace.pair_ids(
            woo_media.existing_images(product)) if isinstance(product, dict) \
            else []
        status("Saved %s%s" % (saved.name,
                               " and %s" % saved_back.name if saved_back
                               else ""))
        #  The images are spoken for now, so the next card is not offered them
        #  again - this is what makes a whole sheet one sitting.
        pool.take(front, label)
        if back is not None:
            pool.take(back, label)
        refresh_sheets()

        # The website photo comes first: the shop is what customers buy from,
        # and the marketplace copies are wired from the same card afterwards.
        if single_product(product):
            upload_to_site(app, product, saved, saved_back, old_pair_ids)

        #  The plugin replaces one listing by its title, which only exists when
        #  a single product was chosen. The search-page fallback has no title,
        #  so offering it there would fail on a missing name.
        if (getattr(app, "cs_addon", True) and single_product(product) and
                photo_replace_available()):
            #  1.0.15 can replace the front but only APPENDS a back, which
            #  would leave the old back photo on the listing - so the back is
            #  held back rather than sent to a plugin that cannot honour it.
            send_back = saved_back if photo_back_replaceable() else None
            if saved_back is not None and send_back is None:
                messagebox.showwarning(
                    "The back was not sent",
                    "CanadianShopper plugin %s replaces a listing's back "
                    "photo; this copy is %s and would only add the new back "
                    "beside the old one.\n\nOnly the front will be sent now. "
                    "Update the plugin to replace both."
                    % (CS_PHOTO_BACK_VERSION, plugin_version() or "unknown"),
                    parent=app)
            if messagebox.askyesno(
                    "Replace the CanadianShopper photos?",
                    "Upload %s to CanadianShopper and set %s on this one "
                    "listing?\n\nExactly one listing must match the title, "
                    "or nothing is written. If the listing's back photo "
                    "cannot be identified, the plugin stops without changing "
                    "anything." % (" and ".join(
                        p.name for p in (saved, send_back) if p is not None),
                        "them" if send_back else "it"), parent=app):
                wire_card(product, saved, send_back)
        elif getattr(app, "cs_addon", True) and single_product(product):
            messagebox.showwarning(
                "Update the CanadianShopper plugin",
                "Replacing one card's photos needs CanadianShopper plugin "
                "%s or newer; this copy is %s. The image was saved for you, "
                "but nothing was sent to CanadianShopper."
                % (CS_PHOTO_REPLACE_VERSION, plugin_version() or "unknown"),
                parent=app)

        if urls:
            app.open_webpages(urls)
            #  The pages are where the same files get uploaded by hand, so the
            #  folder holding them is opened too - after the browser, so it is
            #  the window on top and the files can be dragged straight from it.
            if open_path(saved.parent):
                app.console_line("Opened %s for the saved images." %
                                 saved.parent, "dim")

    # -- the assignment window: cards first, three ways ---------------------
    def apply_ready(rows):
        """Save, upload and wire every row that is ready. Returns the count."""
        done = 0
        for row in photo_assign.ready(rows):
            product, tile = row["product"], row["tile"]
            label = product.get("name") or ""
            partner = pool.same_slot(tile)
            if partner is not None and partner["used_by"]:
                partner = None
            try:
                current = photo_replace.woo_image_name(product)
                written = photo_replace.save_pair(
                    replace_dir(), current, tile["path"],
                    partner["path"] if partner else None)
            except Exception as exc:
                app.console_line("Could not save %s: %s" % (label, exc), "err")
                continue
            saved = written["front"]
            saved_back = written.get("back")
            old_pair_ids = photo_replace.pair_ids(
                woo_media.existing_images(product))
            upload_to_site(app, product, saved, saved_back, old_pair_ids)
            if getattr(app, "cs_addon", True) and single_product(product) and \
                    photo_replace_available():
                send_back = saved_back if photo_back_replaceable() else None
                wire_card(product, saved, send_back)
            pool.take(tile, label)
            if partner is not None:
                pool.take(partner, label)
            row["status"] = photo_assign.EMPTY
            row["product"] = None
            done += 1
            app.console_line("Assigned %s." % (saved.name,), "ok")
        refresh_sheets()
        return done

    def open_assign_window():
        """Line the loaded images up with products, then apply them in a batch.

        Three ways to fill the same worksheet, because which one suits depends
        on the pile of scans: read the sheet's titles with an AI and paste
        them, paste the cards in the order they were scanned, or point at one
        image and search for its card.
        """
        if not ensure_images():
            return
        rows = []
        top = tk.Toplevel(app)
        app.photo_assign_window = top      # kept so a test can drive it
        top.title("Assign the images to cards")
        top.transient(app)
        #  Never bigger than the screen it opens on: this window used to be
        #  860 wide, which does not fit an 800x600 display at all.
        width = min(880, max(560, app.winfo_screenwidth() - 60))
        height = min(600, max(420, app.winfo_screenheight() - 90))
        top.geometry("%dx%d" % (width, height))
        method = tk.StringVar(master=top, value="titles")
        text = tk.Text(top, height=7, wrap="word")
        listing = tk.Listbox(top, height=10, exportselection=False)
        said = ttk.Label(top, text="", style="Dim.TLabel")

        def render():
            listing.delete(0, "end")
            for index, row in enumerate(rows):
                caption = photo_thumbs.caption(row["tile"])
                if row["product"]:
                    what = row["product"].get("name") or ""
                else:
                    what = "- %s" % row["status"]
                listing.insert("end", "%d. %s   %s" % (index + 1, caption, what))
            said.configure(text=photo_assign.headline(rows) if rows else
                           "Paste the list above, then press Read these.")

        def do_search(term):
            site, key, secret = read_woo_credentials(keys_file)
            if not (site and key and secret):
                return []
            try:
                code, data = woo_get(site, "/wp-json/wc/v3/products",
                                     {"search": term, "per_page": 20}, key,
                                     secret)
            except Exception:
                return []
            if code != 200 or not isinstance(data, list):
                return []
            return [{"id": p.get("id"), "name": (p.get("name") or "").strip(),
                     "sku": (p.get("sku") or "").strip(),
                     "images": p.get("images") or []}
                    for p in data if isinstance(p, dict) and p.get("id")]

        def read_list():
            del rows[:]
            pasted = text.get("1.0", "end")
            if method.get() == "titles":
                titles = photo_assign.parse_titles(pasted)
                if not titles:
                    messagebox.showinfo("Paste the titles first",
                                        "Paste the AI's answer, one title per "
                                        "line, then press Read these.",
                                        parent=top)
                    return
                rows.extend(photo_assign.rows_from_titles(
                    pool, titles, do_search))
            else:
                names = woo_orders.parse_card_list(pasted)
                if not names:
                    messagebox.showinfo("Paste the cards first",
                                        "Paste the cards in the order they "
                                        "were scanned, one per line.",
                                        parent=top)
                    return
                products = []
                for name in names:
                    found = do_search(name)
                    picked = woo_orders.auto_pick(name, found) if found else None
                    products.append(picked)
                rows.extend(photo_assign.rows_from_products(pool, products))
            render()
            status(photo_assign.headline(rows))

        def choose_for_row():
            picked = listing.curselection()
            if not picked or not rows:
                messagebox.showinfo("Choose a row",
                                    "Select a row first.", parent=top)
                return
            row = rows[picked[0]]
            term = row["title"] or ""
            product = find_product(term) if term else None
            if isinstance(product, dict) and product.get("id"):
                photo_assign.replace_title(rows, picked[0], product)
                render()

        def apply_all():
            ready_rows = photo_assign.ready(rows)
            if not ready_rows:
                messagebox.showinfo(
                    "Nothing is ready",
                    "No row has a card matched to it yet. Read the list, or "
                    "choose a card for a row.", parent=top)
                return
            if not messagebox.askyesno(
                    "Replace these photos?",
                    "%d card%s will be replaced, one at a time.\n\nA card "
                    "that fails stops itself and the rest carry on."
                    % (len(ready_rows), "" if len(ready_rows) == 1 else "s"),
                    parent=top):
                return
            done = apply_ready(rows)
            render()
            status("%d of %d replaced." % (done, len(ready_rows)))

        ttk.Label(top, text="How should the images find their cards?",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=10,
                                                          pady=(10, 2))
        choices = ttk.Frame(top)
        choices.pack(anchor="w", padx=10)
        ttk.Radiobutton(choices, text="Read the sheet's titles (AI answer)",
                        variable=method, value="titles").pack(side="left")
        ttk.Radiobutton(choices, text="Paste the cards in scan order",
                        variable=method, value="products").pack(side="left",
                                                                padx=12)
        ttk.Radiobutton(choices, text="One at a time (the card search below)",
                        variable=method, value="one").pack(side="left")
        ttk.Label(top, text="The AI's answer, or your cards in the order they "
                  "were scanned:", style="Dim.TLabel",
                  wraplength=width - 40).pack(anchor="w", padx=10, pady=(6, 2))
        text.pack(fill="x", padx=10)
        buttons = ttk.Frame(top)
        buttons.pack(fill="x", padx=10, pady=6)
        ttk.Button(buttons, text="Read these", command=read_list).pack(
            side="left")
        ttk.Button(buttons, text="Choose a card for this row",
                   command=choose_for_row).pack(side="left", padx=8)
        ttk.Button(buttons, text="Apply the ready ones",
                   command=apply_all).pack(side="right")
        ttk.Button(buttons, text="Close", command=top.destroy).pack(
            side="right", padx=8)
        listing.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        said.pack(anchor="w", padx=10, pady=(0, 8))
        attach_tooltips(top)
        render()

    def start():
        query = term.get().strip()
        if not query:
            messagebox.showinfo(
                "Which card?",
                "Type the card's name (or SKU) first, then press Find.",
                parent=app)
            return
        if not has_woo_credentials(keys_file):
            if ask_for_keys():
                return
            product = None
        else:
            product = find_product(query)
            if product is False:
                return
        replace(query, product)

    #  Sheets first: this is where the sitting starts, the way the pipeline
    #  starts from the scans rather than from a card name.
    sheets_row = ttk.Frame(box)
    sheets_row.pack(anchor="w", pady=(4, 0))
    ttk.Button(sheets_row, text="Add sheets...",
               command=add_sheets).pack(side="left")
    ttk.Button(sheets_row, text="Clear",
               command=clear_sheets).pack(side="left", padx=6)
    ttk.Button(sheets_row, text="Assign photos to cards...",
               command=open_assign_window).pack(side="left", padx=(10, 0))

    row = ttk.Frame(box)
    row.pack(anchor="w", pady=4)
    ttk.Label(row, text="Card name or SKU:").pack(side="left")
    entry = ttk.Entry(row, textvariable=term, width=42)
    entry.pack(side="left", padx=6)
    entry.bind("<Return>", lambda _event: start())
    ttk.Button(row, text="Find the card...", command=start).pack(side="left")
    ttk.Button(row, text="Open the scanner folder",
               command=lambda: (None if open_path(app.settings.get(
                   "scan_dir", DEFAULT_SCAN_DIR)) else
                   messagebox.showwarning(
                       "Not found",
                       "The scan folder does not exist:\n%s\nSet it in the "
                       "Connection panel." %
                       app.settings.get("scan_dir", DEFAULT_SCAN_DIR)))
               ).pack(side="left", padx=8)
    sheets_text["label"] = ttk.Label(notes, text="", style="Dim.TLabel",
                                     wraplength=780, justify="left")
    sheets_text["label"].pack(anchor="w", pady=(2, 0))
    hint.pack(anchor="w", pady=(2, 0))
    refresh_sheets()


def build_logs(parent, app):
    panel_header(parent, app, "logs")
    box = ttk.Frame(parent)
    box.pack(fill="x")

    panel_note(parent, (
        "Move older root-level marketplace outputs into their folders. "
        "Preview first; this organizer never deletes or overwrites files."))
    organizer = BASE / "pipeline" / "organize_pipeline_outputs.py"

    def run_organizer(apply=False):
        pipeline_dir = Path(app.settings.get("pipeline_dir") or str(WORK))
        if not organizer.is_file():
            messagebox.showerror("Organizer missing",
                                 "Could not find %s" % organizer)
            return
        if apply and not messagebox.askyesno(
                "Move legacy result files?",
                "Move recognized CanadianShopper, eBay, WooCommerce, and "
                "Facebook result files from the pipeline root into their "
                "folders?\n\nNo files will be deleted or overwritten.",
                parent=app):
            return
        args = ["--pipeline-dir", str(pipeline_dir)]
        if apply:
            args.append("--apply")
        app.run_tool(str(organizer), args,
                     "Organize pipeline result files", cwd=str(pipeline_dir))

    row = ttk.Frame(box)
    row.pack(fill="x", pady=(0, 5))
    preview_button = ttk.Button(
        row, text="Preview old pipeline files",
        command=lambda: run_organizer(False))
    preview_button.pack(side="left")
    add_tooltip(preview_button, "List recognized files and their destination folders without moving anything")
    move_button = ttk.Button(
        row, text="Move old files into folders",
        command=lambda: run_organizer(True))
    move_button.pack(side="left", padx=4)
    add_tooltip(move_button, "Move recognized files after a confirmation; existing content is never overwritten")

    rows = [
        ("Open the pipeline output-file audit", BASE / "pipeline" / "OUTPUT-FILES.md"),
        ("Open the tools folder", BASE),
        ("Open the batch folder", app.settings.get("pipeline_dir", WORK)),
        ("Open the Facebook feed folder (the delta xlsx lives here)",
         BASE / "pipeline" / "facebook_merchant_products"),
        ("Open the GUI log (gui-log.txt)", LOG_FILE),
        ("Open the stock report (sold-cards-report.csv)",
         BASE / "sold-cards-report.csv"),
        ("Open the checklist (sold-cards-checklist.csv)", CHECKLIST),
        ("Open the image-sync report",
         first_existing(BASE / "reports" / "image-sync-latest.csv",
                        BASE / "image-sync-report.csv",
                        WORK / "image-sync-report.csv") or LOG_FILE),
    ]
    for text, path in rows:
        def go(p=path):
            if not open_path(p):
                messagebox.showinfo("Not there yet",
                                    "%s\ndoes not exist yet - it appears "
                                    "after the first run that creates it."
                                    % p)
        ttk.Button(box, text=text, command=go).pack(anchor="w", pady=2)


DOCS["plugins"] = """\
Install optional plugin ZIPs you trust, review their declared actions,
and enable or remove them. Plugins run with your Windows account permissions;
the app checks their metadata but does not sandbox plugin code. Plugin
packages are stored separately from the core program and are not downloaded
automatically."""


PANEL_BUILDERS = {
    "cookie": build_cookie,
    "pipeline": build_pipeline,
    "combine": build_combine,
    "stage": build_stage,
    "importpanel": build_importpanel,
    "wire": build_wire,
    "rerun": build_rerun,
    "sold": build_sold,
    "checklist": build_checklist,
    "stock": build_stock,
    "zerostock": build_zerostock,
    "square": build_square,
    "newphotos": build_newphotos,
    "ordertext": build_ordertext,
    "markets": build_markets,
    "logs": build_logs,
    "plugins": build_plugins,
}


# --------------------------------------------------------------- dialogs
class PipelineDialog(tk.Toplevel):
    """The card-pipeline runner. Mirrors the working .bat exactly:
      1. the FRONT scan (required) and the BACK scan (optional) -
         drag-and-drop on the .bat becomes two Browse rows here;
      2. the saved AI page opens; the right command for the sheet (mixed
         grades -> grade in the titles; one grade -> no grade) is copied;
      3. the user uploads scans and pastes the command manually, then copies
         the AI answer; the clipboard monitor asks how to continue;
      4. `card_pipeline.py split --front ... [--back ...]` then optionally
         `card_pipeline.py listing --input _card_input.txt --facebook`.
         "Split the scans only" runs the split ALONE (no answer needed) and
         keeps the dialog open for the remaining steps.
    """

    def __init__(self, app, script, on_run, front="", back=""):
        super().__init__(app)
        self.app = app
        self.script = Path(script)
        self.on_run = on_run          # args, on_done -> start the runner
        # the last scans are remembered (gui-settings.json) so a manual
        # run never starts from an empty form
        if not front:
            front = app.settings.get("last_front_scan", "")
            if front and not Path(front).is_file():
                front = ""
        if not back:
            back = app.settings.get("last_back_scan", "")
            if back and not Path(back).is_file():
                back = ""
        self.title("Run the card pipeline")
        self.geometry("760x640")
        self.minsize(620, 500)
        box = ttk.Frame(self, padding=(8, 6))
        box.pack(fill="both", expand=True)

        # the action row is packed FIRST, from the bottom, so it can never
        # be pushed out of view by the answer box above it
        row2 = ttk.Frame(box)
        row2.pack(side="bottom", fill="x", pady=(4, 0))
        self.bind("<Return>", lambda e: self.run())
        ttk.Button(row2, text="Split the scans and build the CSV",
                   style="Task.TButton", command=self.run).pack(side="left")
        ttk.Button(row2, text="Split the scans only",
                   command=self.run_split_only).pack(side="left",
                                                     padx=(8, 0))
        ttk.Button(row2, text="Not now", command=self.destroy).pack(
            side="right")

        ttk.Label(box, text="1) Choose scans for this batch", style="H2.TLabel"
                  ).pack(anchor="w")
        ttk.Label(box, text=(
            "Choose the FRONT scan (required) and the BACK scan if you have one. "
            "Your choices are remembered for next time."),
            wraplength=740, justify="left").pack(anchor="w")
        self.front_var = tk.StringVar(master=self, value=front)
        self.back_var = tk.StringVar(master=self, value=back)
        for label, var in (("FRONT scan:", self.front_var),
                           ("BACK scan (optional):", self.back_var)):
            row = ttk.Frame(box)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=label, width=22).pack(side="left")

            def browse(v=var):
                f = filedialog.askopenfilename(
                    parent=self,
                    title="Choose the scan",
                    initialdir=self.app.settings.get("scan_dir", "")
                    or str(BASE),
                    filetypes=[("Images", "*.jpg *.jpeg *.png *.tif *.tiff "
                                      "*.bmp *.webp"), ("All", "*.*")])
                if f:
                    v.set(f)
                    self.app.set_setting("scan_dir", str(Path(f).parent))
                self.scan_note()
                # A native file chooser may leave the owner behind the main
                # window on Windows. Restore the pipeline dialog after it closes.
                try:
                    if self.winfo_exists():
                        self.deiconify()
                        self.lift()
                        self.focus_force()
                except tk.TclError:
                    pass
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x",
                                                  expand=True, padx=4)
            browse_button = ttk.Button(row, text="Browse...", command=browse)
            browse_button.pack(side="left")
            add_tooltip(browse_button, "Choose an image file")
        self.scan_label = ttk.Label(box, text="", foreground="#1b5e20")
        self.scan_label.pack(fill="x", pady=(2, 0))
        self.scan_note()

        # typing/pasting a path counts too
        for var in (self.front_var, self.back_var):
            var.trace_add("write", lambda *a: self.scan_note())

        ttk.Separator(box).pack(fill="x", pady=5)
        ttk.Label(box, text="2) The AI command for today's sheet",
                  style="H2.TLabel").pack(anchor="w")
        ttk.Label(box, text=(
            "Choose the matching prompt below; it is copied. Upload the scans "
            "to the saved AI page and paste the prompt there."),
            wraplength=700, justify="left").pack(anchor="w")
        ttk.Label(box, text=(
            "Add your own copy-to-clipboard buttons in User Settings. "
            "Commands used to build listings should request the same "
            "structured card output."), style="Dim.TLabel",
            wraplength=700, justify="left").pack(anchor="w", pady=(2, 0))
        row = ttk.Frame(box)
        row.pack(fill="x", pady=4)
        for index, (kind, title, tip) in enumerate(
                ai_prompt_buttons(self.app.settings)):
            button = ttk.Button(
                row, text=title, style="Task.TButton",
                command=lambda k=kind: self.pick(k))
            button.grid(row=index // 2, column=index % 2, sticky="ew",
                        padx=(0, 6), pady=2)
            row.columnconfigure(index % 2, weight=1)
            add_tooltip(button, tip)
        self.ai_url_status = ttk.Label(
            box, text="The saved AI page opens automatically; copy its full reply when done.",
            style="Dim.TLabel", wraplength=700, justify="left")
        self.ai_url_status.pack(fill="x", pady=(2, 0))
        self.status = ttk.Label(box, text="", foreground="#1b5e20",
                                wraplength=740, justify="left")
        self.status.pack(fill="x")
        attach_tooltips(self)

        ttk.Separator(box).pack(fill="x", pady=5)
        ttk.Label(box, text="3) The AI's answer", style="H2.TLabel").pack(
            anchor="w")
        ttk.Label(box, text=(
            "Copy the complete AI response. Alex Collect detects it and asks "
            "whether to build listings or split only."),
            wraplength=700, justify="left").pack(anchor="w")
        self._our_clip = ""           # the prompt WE put on the clipboard
        self._last_clipboard_text = None
        self._captured_answer = ""
        self._answer_choice_active = False
        self.clip_label = ttk.Label(box, text="", wraplength=740,
                                    justify="left")
        self.clip_label.pack(fill="x", pady=(3, 0))
        self.refresh_clip(initial=True)
        self._clip_job = self.after(400, self._clip_tick)
        # Give the dialog a chance to finish building before showing a URL prompt.
        self.after_idle(self._open_saved_ai_page_or_ask)

    def refresh_clip(self, initial=False):
        """Show what the clipboard holds RIGHT NOW - this is exactly what
        the button will use."""
        try:
            text = self.app.clipboard_get()
        except Exception:
            text = ""
        previous = self._last_clipboard_text
        self._last_clipboard_text = text
        kind, verdict = classify_clipboard(text, self.app.settings)
        if not initial and previous is not None and text.strip() != previous.strip():
            if kind == "answer":
                self._captured_answer = text.strip()
                if not self._answer_choice_active:
                    self._answer_choice_active = True
                    self.after_idle(
                        lambda answer=self._captured_answer:
                        self._ask_after_ai_answer(answer))
            else:
                self._captured_answer = ""
        shown = " ".join(text[:72].split())
        if self._our_clip and text.strip() == self._our_clip.strip():
            self.clip_label.config(
                text="Clipboard right now: the PROMPT you copied - paste "
                     "it into the AI chat with the sheet images. When the "
                     "AI replies, copy the reply and this line follows it.",
                foreground="#b26a00")
            return
        if not text.strip():
            self.clip_label.config(
                text="Clipboard right now: (empty or not text)  -  copy "
                     "the AI's reply and this line updates itself.",
                foreground="#555555")
            return
        if kind == "prompt":
            self.clip_label.config(
                text='Clipboard right now: the PROMPT ("%s...")  -  %s. '
                     "Copy the AI's REPLY instead."
                     % (shown, verdict), foreground="#b26a00")
        elif kind == "answer":
            self.clip_label.config(
                text='Clipboard right now: "%s..."  -  %s (%s characters) '
                     "-  ready." % (shown, verdict,
                                    "{:,}".format(len(text))),
                foreground="#1b5e20")
        elif kind == "short":
            self.clip_label.config(
                text='Clipboard right now: "%s"  -  %s.'
                     % (shown, verdict), foreground="#b26a00")
        else:
            self.clip_label.config(
                text='Clipboard right now: "%s..."  -  %s (%s characters); '
                     "if that is not the AI's reply, copy it now."
                     % (shown, verdict, "{:,}".format(len(text))),
                foreground="#555555")

    def _open_saved_ai_page_or_ask(self):
        """Open the saved AI page, or ask once for its URL and remember it."""
        if not self.winfo_exists():
            return
        self.open_ai_page()

    def open_ai_page(self):
        url = normalize_web_url(self.app.settings.get("ai_agent_url", ""))
        if not url:
            entered = simpledialog.askstring(
                "AI agent page",
                "Enter the URL of the AI chat page you use. Set it later in "
                "User settings if you need to change it.", parent=self)
            if entered is None:
                return
            url = normalize_web_url(entered)
        if not url:
            messagebox.showwarning(
                "Invalid AI page URL",
                "Enter a web URL such as https://chatgpt.com.", parent=self)
            return
        self.app.set_setting("ai_agent_url", url)
        try:
            opened = self.app.open_webpages([url])
        except Exception as exc:
            opened = False
            log("could not open AI page %s: %s" % (url, exc))
        self.ai_url_status.config(
            text=("Opened the saved AI page. Upload scans and paste the "
                  "chosen prompt manually." if opened else
                  "AI page URL saved, but the browser did not confirm opening: "
                  "%s" % url),
            foreground="#1b5e20" if opened else "#b26a00")

    def _ask_after_ai_answer(self, answer):
        """After the user copies a recognizable AI reply, ask which path to run."""
        try:
            if not self.winfo_exists():
                return
            choice = messagebox.askyesnocancel(
                "AI answer copied",
                "The clipboard now contains what looks like the AI's full "
                "answer (%s characters).\n\n"
                "Yes: split the scans and build the CSV.\n"
                "No: split the scans only and keep this dialog open.\n"
                "Cancel: do nothing for now." % "{:,}".format(len(answer)),
                parent=self)
            if choice is True:
                self.run(answer_override=answer)
            elif choice is False:
                self.run_split_only()
        finally:
            self._answer_choice_active = False

    def _clip_tick(self):
        if not self.winfo_exists():
            return
        self.refresh_clip()
        self._clip_job = self.after(800, self._clip_tick)

    def destroy(self):
        try:
            self.after_cancel(self._clip_job)
        except Exception:
            pass
        super().destroy()

    def scan_note(self):
        f = self.front_var.get().strip()
        b = self.back_var.get().strip()
        parts = []
        if f and Path(f).is_file():
            parts.append("FRONT scan ready: %s" % Path(f).name)
        elif f:
            parts.append("FRONT path set, but the file was not found")
        if b and Path(b).is_file():
            parts.append("BACK scan ready: %s" % Path(b).name)
        elif b:
            parts.append("BACK path set, but the file was not found")
        if not parts:
            self.scan_label.config(
                text="Choose the FRONT scan (Browse) - or drop the scans on "
                     "the Alex Collect desktop icon and they land here "
                     "already filled in.", foreground="#555555")
        else:
            self.scan_label.config(
                text="  |  ".join(parts) +
                     "  -  press \"Split the scans and build the CSV\" "
                     "when ready.", foreground="#1b5e20")

    def pick(self, kind):
        text = load_prompt(kind, self.app.settings)
        try:
            current = self.app.clipboard_get()
        except Exception:
            current = ""
        if current.strip() and current.strip() != text.strip() and \
                classify_clipboard(current, self.app.settings)[0] == "answer" and \
                not messagebox.askyesno(
                    "Replace the answer on the clipboard?",
                    "The clipboard holds the AI's answer (%s characters)."
                    "\n\nCopying the prompt now replaces it - you would "
                    "have to copy the answer again.\n\nCopy the prompt "
                    "anyway?" % "{:,}".format(len(current.strip())),
                    parent=self):
            return
        ok = to_clipboard(self.app, text)
        self._our_clip = text if ok else ""
        self.status.config(
            text=("Copied the prompt to your clipboard - paste it into "
                  "your AI chat with the FRONT and BACK sheet images. "
                  "When the AI replies, copy the reply: the line under "
                  "step 3 follows it, and the button uses it." if ok else
                  "Could not reach the clipboard - open %s in User Settings "
                  "and copy the text by hand." % PROMPT_FILES.get(
                      kind, "Custom AI commands")))
        self.refresh_clip()

    def _scan_args(self):
        """(["split", ...], (front, back)) when the scans check out, or
        (None, None) with a warning shown."""
        front = self.front_var.get().strip().strip('"')
        back = self.back_var.get().strip().strip('"')
        if not front or not Path(front).is_file():
            messagebox.showwarning(
                "FRONT scan missing",
                "Pick the FRONT 9-card sheet scan first (Browse, row 1).",
                parent=self)
            return None, None
        if back and not Path(back).is_file():
            messagebox.showwarning(
                "BACK scan not found",
                "The BACK scan path does not point at a file. Clear it or "
                "browse again.", parent=self)
            return None, None
        args = ["split", "--front", front] + (["--back", back] if back
                                              else [])
        return args, (front, back)

    def remember_scans(self, front, back):
        """The scans and their folder are remembered for next time."""
        try:
            self.app.set_setting("scan_dir", str(Path(front).parent))
            self.app.set_setting("last_front_scan", front)
            if back:
                self.app.set_setting("last_back_scan", back)
        except Exception:
            pass

    def run_split_only(self):
        """Split WITHOUT the AI answer: tiles only. The dialog stays open
        for the AI steps (2 and 3) afterwards."""
        args, scans = self._scan_args()
        if args is None:
            return
        self.remember_scans(*scans)

        def split_done(rc):
            if rc == 0:
                tiles = self.script.parent / "output"
                self.app.console_line(
                    "The split finished: the tile images are in %s."
                    % tiles, "ok")
                self.app.console_line(
                    "Next: copy one of the AI prompts (step 2 in the "
                    "dialog), paste it into your AI chat with the sheet "
                    "images, copy the FULL reply, then press \"Split the "
                    "scans and build the CSV\". Re-splitting the same "
                    "scans is fine.")
                self.status.config(
                    text="Tiles are ready - now step 2 (copy a prompt) "
                         "and step 3 (copy the AI's reply), then press "
                         "\"Split the scans and build the CSV\".")
            else:
                self.app.console_line(
                    "Split failed - read the error above.", "err")

        started = self.on_run(args, split_done, "Card pipeline: split")
        if started is False:
            self.app.console_line(
                "The split did not start - read the message above.", "err")

    def run(self, answer_override=None):
        args, scans = self._scan_args()
        if args is None:
            return
        front, back = scans
        if answer_override is not None:
            answer = answer_override.strip()
        else:
            try:
                answer = self.app.clipboard_get().strip()
            except Exception:
                answer = ""
        kind, verdict = classify_clipboard(answer, self.app.settings)
        if kind in ("short", "empty"):
            messagebox.showwarning(
                "No listing text yet",
                "The clipboard does not hold the AI's full answer\n(%s).\n\n"
                "Copy the COMPLETE reply from your AI chat (all nine "
                "cards), then press the button again.\n\nJust want the "
                "tile images right now? Press \"Split the scans only\" "
                "instead." % verdict,
                parent=self)
            return
        if kind == "prompt":
            messagebox.showwarning(
                "That is the question, not the answer",
                "The clipboard still holds the PROMPT (paste it into the "
                "AI chat with the sheet images).\n\nWhen the AI replies, "
                "copy the REPLY (all nine cards), then press the button "
                "again.\n\nJust want the tile images right now? Press "
                "\"Split the scans only\" instead.", parent=self)
            return
        if kind == "other" and not messagebox.askyesno(
                "Use this clipboard text?",
                "The clipboard holds %s (%s characters) and it does not "
                "look like the AI's reply.\n\nUse it anyway?"
                % (verdict, "{:,}".format(len(answer))),
                parent=self):
            return
        #  Ask about the products before the run starts: the answer decides
        #  the flags the pipeline gets, so the console never has to wonder.
        product_choice = ask_create_products(self.app)
        if product_choice is None:
            self.app.console_line(
                "Nothing was started: the batch was cancelled before the "
                "products question. No files were changed.", "dim")
            return
        product_flags = {
            "draft": ["--create-products", "--draft-products", "--confirmed"],
            "publish": ["--create-products", "--publish-products",
                        "--confirmed"],
            "none": ["--no-create-products", "--confirmed"],
        }[product_choice]
        self._product_choice = product_choice

        input_file = self.script.parent / "_card_input.txt"
        try:
            input_file.write_text(answer + "\n", encoding="utf-8-sig")
        except Exception as e:
            messagebox.showerror("Could not write %s" % input_file.name, e,
                                 parent=self)
            return
        log("wrote %s (%d chars of AI answer)" % (input_file, len(answer)))
        args = ["split", "--front", front] + (["--back", back] if back
                                              else [])

        def phase2(rc):
            if rc == 0:

                def listing_done(rc2):
                    if rc2 == 0:
                        self.app.console_line(
                            "listing finished. The Woo + CanadianShopper "
                            "CSVs are in the pipeline folder (%s)."
                            % self.script.parent)
                        if getattr(self, "_product_choice", "none") == "none":
                            self.app.console_line(
                                "No products were created: the CSV is ready "
                                "for WP All Import. Re-run the pipeline and "
                                "choose \"Create them as drafts\" to create "
                                "them straight on the website instead.")
                        else:
                            self.app.console_line(
                                "Products: read the \"PRODUCTS ON YOUR "
                                "WEBSITE\" block above - it lists what was "
                                "created, what already existed, what failed "
                                "and why, and where the photos landed. The "
                                "same lines are saved beside the CSV as "
                                "woo-create-result.json. Anything left as a "
                                "draft is unpublished on purpose: publish it "
                                "from the website when the price and photos "
                                "look right.", "ok")
                        self.app.console_line(
                            "No Facebook delta xlsx? That step only runs "
                            "after the cards are PUBLISHED on your website: "
                            "answer 'y' at its question, and if the cards "
                            "went live afterwards, use the Facebook feed "
                            "updater button on the pipeline panel - the "
                            "xlsx lands in app\\pipeline\\"
                            "facebook_merchant_products. After export, Alex "
                            "Collect opens the workbook, output folder, and "
                            "configured Facebook page for review.", "ok")
                    else:
                        self.app.console_line(
                            "The listing step finished with a problem - read "
                            "the \"NOT EVERY STEP FINISHED\" block above. "
                            "Everything it did write is on disk; the step "
                            "that failed changed nothing, so it can simply "
                            "be run again (Re-run a marketplace, or its own "
                            "button on the pipeline panel).", "err")

                self.on_run(["listing", "--input", str(input_file),
                             "--facebook"] + product_flags,
                            listing_done,
                            "Card pipeline: listing")
            else:
                self.app.console_line(
                    "Split failed - the listing step was not started. Read "
                    "the error above.", "err")
        self.remember_scans(front, back)
        started = self.on_run(args, phase2, "Card pipeline: split")
        if started is False:
            self.app.console_line(
                "The split did not start - the dialog stays open. Read "
                "the message above.", "err")
            return
        self.destroy()


class Editor(tk.Toplevel):
    """A small typing window whose content is saved to a tool's list file."""

    def __init__(self, self_toplevel, title, hint, initial, save_to, on_saved,
                 save_label="Save and use this list", save_hint=""):
        super().__init__(self_toplevel.winfo_toplevel())
        self.title(title)
        self.transient(self_toplevel.winfo_toplevel())
        self.geometry("700x480")
        ttk.Label(self, text=hint, wraplength=660, justify="left").pack(
            fill="x", padx=12, pady=(12, 5))
        if save_hint:
            ttk.Label(self, text=save_hint, wraplength=660, justify="left",
                      style="Dim.TLabel").pack(anchor="w", padx=12,
                                                pady=(0, 6))
        # Keep the actions above the expanding editor so resizing the
        # window can never push Save / Cancel below the visible area.
        row = ttk.Frame(self)
        row.pack(fill="x", padx=10, pady=(0, 6))
        txt = tk.Text(self, wrap="word", font=("Consolas", 10))
        txt.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        if initial:
            txt.insert("1.0", initial)

        def save():
            text = txt.get("1.0", "end").strip()
            if not text:
                messagebox.showinfo("Empty", "Type at least one line first.",
                                    parent=self)
                return
            p = Path(save_to)
            if p.exists() and not messagebox.askyesno(
                    "Replace the previous list?",
                    "%s already exists.\nReplace it with what you just "
                    "typed?" % p.name, parent=self):
                return
            p.write_text(text + "\n", encoding="utf-8")
            log("wrote %s (%d lines)" % (p, text.count("\n") + 1))
            self.destroy()
            on_saved(p)

        save_button = ttk.Button(
            row, text=save_label, style="Task.TButton", command=save)
        save_button.pack(side="right")
        ttk.Button(row, text="Cancel", command=self.destroy).pack(
            side="right", padx=8)

        def save_shortcut(event=None):
            save()
            return "break"

        txt.bind("<Control-Return>", save_shortcut)
        txt.bind("<Control-KP_Enter>", save_shortcut)
        self.after(100, txt.focus_set)


class ChecklistViewer(tk.Toplevel):
    """The tick-off list with real tick boxes."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Checklist - outstanding items")
        self.geometry("860x540")
        self.vars = {}          # row num -> BooleanVar
        self.rows = []
        head = ttk.Frame(self, padding=5)
        head.pack(fill="x")
        ttk.Label(head, text="Tick completed rows; unticked rows remain reminders.",
                  wraplength=820, justify="left").pack(anchor="w")
        self.canvas = tk.Canvas(self, highlightthickness=0)
        ysb = ttk.Scrollbar(self, orient="vertical",
                            command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(4, 2))
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(
                            scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw",
                                  tags="inner")
        self.canvas.configure(yscrollcommand=ysb.set)
        self.canvas.pack(fill="both", expand=True, side="top", padx=4)
        ysb.pack(fill="y", side="right")
        try:   # Windows wheel; Linux uses Button-4/5 below
            self.canvas.bind_all("<Mousewheel>",
                                 lambda e: self.canvas.yview_scroll(
                                     -1 * (e.delta // 120 or 1), "units"))
        except tk.TclError:
            pass
        self.canvas.bind_all("<Button-4>",
                             lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>",
                             lambda e: self.canvas.yview_scroll(1, "units"))
        row = ttk.Frame(self, padding=5)
        row.pack(fill="x", side="bottom")
        ttk.Button(row, text="Tick the selected ones",
                   command=self.tick_selected).pack(side="left")
        ttk.Button(row, text="Tick EVERYTHING",
                   command=self.tick_all).pack(side="left", padx=8)
        ttk.Button(row, text="Open the selected row's link",
                   command=self.open_link).pack(side="left")
        ttk.Button(row, text="Open the CSV", command=lambda: open_path(
            CHECKLIST)).pack(side="left", padx=8)
        ttk.Button(row, text="Refresh", command=self.reload).pack(
            side="right")
        self.reload()

    def reload(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.vars.clear()
        self.rows = []
        if not CHECKLIST.exists():
            ttk.Label(self.inner, text="No checklist yet - it appears after "
                      "the first sale is marked (A card sold).",
                      style="Dim.TLabel").pack(anchor="w")
            return
        import csv as _csv
        try:
            with open(CHECKLIST, newline="", encoding="utf-8-sig") as f:
                rd = _csv.reader(f)
                header = next(rd, None)
                data = [r for r in rd if r and any(c.strip() for c in r)]
        except Exception as e:
            ttk.Label(self.inner, text="Could not read the checklist: %s"
                      % e).pack(anchor="w")
            return
        col = {name.strip().lower(): i for i, name in enumerate(header or [])}
        i_num, i_done = col.get("num", 0), col.get("done", 1)
        i_card, i_chan = col.get("card", 2), col.get("channel", 3)
        i_what, i_link = col.get("what to do", 4), col.get("link", 5)
        for r in data:
            get = lambda i: r[i].strip() if i < len(r) and len(r) > i else ""
            num, done = get(i_num), get(i_done).lower()
            card, chan = get(i_card), get(i_chan)
            what, link = get(i_what), get(i_link)
            self.rows.append({"num": num, "link": link})
            line = ttk.Frame(self.inner)
            line.pack(fill="x", pady=1)
            if done in ("x", "done", "yes", "true", "1"):
                ttk.Label(line, text="[done] ", foreground="#3a8a3a",
                          font=("TkDefaultFont", 10, "bold")).pack(side="left")
                ttk.Label(line, text="%s. (%s) %s - %s" % (num, chan, card,
                                                           what),
                          style="Dim.TLabel", wraplength=700).pack(
                              side="left", anchor="w")
            else:
                var = tk.BooleanVar(master=line, value=False)
                self.vars[num] = var
                ttk.Checkbutton(line, variable=var).pack(side="left")
                ttk.Label(line, text="%s. (%s) %s - %s" % (num, chan, card,
                                                           what),
                          wraplength=700).pack(side="left", anchor="w")
            if link:
                ttk.Label(line, text="  link", foreground="#2255aa",
                          cursor="hand2").pack(side="right")
                def openit(ev, u=link):
                    self.app.open_webpages([u])
                lbls = [w for w in line.winfo_children()
                        if isinstance(w, ttk.Label)][-1]
                lbls.bind("<Button-1>", openit)

    def _selected_nums(self):
        return [n for n, v in self.vars.items() if v.get()]

    def tick_selected(self):
        nums = sorted(self._selected_nums(),
                      key=lambda n: int(n) if n.isdigit() else 0)
        if not nums:
            messagebox.showinfo("Nothing ticked",
                                "Tick at least one row first.")
            return
        self._run_done(",".join(nums))

    def tick_all(self):
        if not self.vars:
            messagebox.showinfo("Nothing to tick",
                                "Everything is already done - nice.")
            return
        if messagebox.askyesno(
                "Tick everything",
                "Mark ALL %d outstanding rows as done?" % len(self.vars)):
            self._run_done("all")

    def _run_done(self, spec):
        self.app.run_tool(
            "sold-everywhere.py",
            ["--done", spec, "--checklist", str(CHECKLIST)],
            "Tick off checklist rows",
            cwd=self.app.settings.get("pipeline_dir", str(WORK)),
            on_done=lambda rc: self.after(200, self.reload))

    def open_link(self):
        nums = set(self._selected_nums())
        for r in self.rows:
            if r["num"] in nums and r["link"]:
                self.app.open_webpages([r["link"]])
                return
        messagebox.showinfo("No link",
                            "Tick a row that has a link (eBay rows link to "
                            "your active listings, Facebook rows to your "
                            "selling page).")


# ------------------------------------------------------------ task menu
class TasksFrame(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        self.app = app
        self.menu = ttk.Frame(self)
        self.menu.pack(fill="both", expand=True)
        for group, ids in groups_for(self.app.cs_addon):
            section = ttk.LabelFrame(self.menu, text=group,
                                     style="TaskGroup.TLabelframe")
            section.pack(fill="x", pady=(5, 1))
            for index, pid in enumerate(ids):
                row, column = divmod(index, 2)
                button = ttk.Button(
                    section, text=MENU_LABELS[pid], style="TaskMenu.TButton",
                    command=lambda p=pid: self.show_panel(p))
                button.grid(row=row, column=column, sticky="w",
                            padx=(0, 8 if column == 0 else 0), pady=3)
                add_tooltip(button, BLURBS[pid])
        attach_tooltips(self.menu)

    def show_panel(self, pid):
        self.app.clear_action_bar()
        self.menu.destroy()
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        ttk.Button(wrap, text="<- All tasks",
                   command=lambda: self.app.show_mode("menu")).pack(
                       anchor="w", pady=(2, 6))
        PANEL_BUILDERS[pid](wrap, self.app)
        attach_tooltips(wrap)


# --------------------------------------------------------------- tabs
class TabsFrame(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        for group, ids in groups_for(app.cs_addon):
            tab = ttk.Frame(nb, padding=(6, 5))
            nb.add(tab, text=group)
            for pid in ids:
                panel_section(tab, app, pid, expand=False)


# --------------------------------------------------------------- wizard
WIZARD_PAGES = ["welcome", "cookie", "pipeline", "sold", "done"]


class WizardFrame(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        self.app = app
        self.page = 0
        self.content = ttk.Frame(self)
        self.content.pack(fill="both", expand=True)
        nav = ttk.Frame(self, padding=(0, 8))
        nav.pack(fill="x", side="bottom")
        ttk.Button(nav, text="<- Back", command=self.back).pack(side="left")
        ttk.Button(nav, text="Next step ->", command=self.next_page).pack(
            side="left", padx=8)
        ttk.Button(nav, text="Skip the wizard (task menu)",
                   command=self.skip_wizard).pack(side="right")
        self.dots = ttk.Label(nav, text="")
        self.dots.pack(side="right", padx=12)
        self.render()

    def render(self):
        self.app.clear_action_bar()
        self.content._wizard_page = True
        for w in self.content.winfo_children():
            w.destroy()
        pid = WIZARD_PAGES[self.page]
        self.dots.config(text="step %d of %d" % (self.page + 1,
                                                 len(WIZARD_PAGES)))
        if pid == "done":
            ttk.Label(self.content, text="You are set.", style="H1.TLabel"
                      ).pack(anchor="w", pady=(6, 6))
            sale_summary = (
                "  a sale:     A card sold -> CanadianShopper can be fixed "
                "after preview; other listings go on the checklist and stay "
                "there until ticked\n" if self.app.cs_addon else
                "  a sale:     choose the source -> other listings go on the "
                "checklist; CanadianShopper stock stays manual\n")
            ttk.Label(self.content, text=(
                "That is the whole loop:\n\n"
                "  new cards:  prepare files -> review -> import and publish\n" +
                sale_summary +
                "  new photos: find the card -> open the folder -> update "
                "every page\n\n"
                "Pick how the window should open from now on:"),
                wraplength=880, justify="left").pack(anchor="w")
            var = tk.StringVar(master=self.content,
                               value=self.app.settings.get("startup_mode",
                                                           "menu"))
            row = ttk.Frame(self.content)
            row.pack(anchor="w", pady=8)
            for txt, val in (("the wizard", "wizard"),
                             ("the task menu (recommended)", "menu"),
                             ("the tabs", "tabs")):
                ttk.Radiobutton(row, text=txt, value=val, variable=var).pack(
                    side="left", padx=(0, 12))

            def finish():
                self.app.set_setting("startup_mode", var.get())
                self.app.set_setting("seen_wizard", True)
                self.app.show_mode("menu")
            ttk.Button(self.content, text="Finish", style="Task.TButton",
                       command=finish).pack(anchor="w")
            attach_tooltips(self.content)
            return
        if pid == "welcome":
            ttk.Label(self.content, text="Welcome", style="H1.TLabel").pack(
                anchor="w", pady=(6, 6))
            ttk.Label(self.content, text=DOCS["welcome"], wraplength=880,
                      justify="left").pack(anchor="w")
            row = ttk.Frame(self.content)
            row.pack(anchor="w", pady=10)
            ttk.Button(row, text="Open canadianshopper.ca",
                       command=lambda: self.app.open_webpages([CS_HOME])).pack(
                           side="left")
            ttk.Button(row, text="Your eBay listings",
                       command=lambda: self.app.open_webpages([
                           self.app.settings.get("ebay_selling_url", "")])).pack(
                               side="left", padx=8)
            ttk.Button(row, text="Your Facebook listings",
                       command=lambda: self.app.open_webpages([
                           self.app.settings.get("facebook_selling_url", "")])).pack(
                               side="left")
            return
        if pid == "cookie":
            ttk.Label(self.content,
                      text="Step 1 - set your folders" if
                      not self.app.cs_addon else
                      "Step 1 - connect the tools",
                      style="H1.TLabel").pack(anchor="w", pady=(6, 6))
            PANEL_BUILDERS["cookie"](self.content, self.app)
            return
        if pid == "pipeline":
            ttk.Label(self.content,
                      text="Step 2 - the loop for new cards",
                      style="H1.TLabel").pack(anchor="w", pady=(6, 6))
            if self.app.cs_addon:
                steps = ("For each new batch:\n\n"
                         "  1. Choose the front scan and optional back scan; "
                         "send them with the matching prompt to your AI chat.\n"
                         "  2. Copy the complete card descriptions back. "
                         "Alex Collect prepares images and import files.\n"
                         "  3. Combine batches if needed.\n"
                         "  4. Stage photos, then import and publish on your "
                         "website.\n"
                         "  5. Wire the back photos after the import.\n\n"
                         "Nothing is published automatically; review the "
                         "files and previews before continuing.")
            else:
                steps = ("For each new batch:\n\n"
                         "  1. Choose the front scan and optional back scan; "
                         "send them with the matching prompt to your AI chat.\n"
                         "  2. Copy the complete card descriptions back. "
                         "Alex Collect prepares images and import files.\n"
                         "  3. Combine batches if needed.\n"
                         "  4. Review the files, then import and publish on "
                         "your website.\n\n"
                         "CanadianShopper remains a manual import. Photo "
                         "staging and back-photo wiring are manual without "
                         "the optional plugin. Nothing is published "
                         "automatically.")
            ttk.Label(self.content, text=steps,
                      wraplength=880, justify="left").pack(anchor="w")
            PANEL_BUILDERS["pipeline"](self.content, self.app)
            return
        if pid == "sold":
            ttk.Label(self.content,
                      text="Step 3 - when a card sells",
                      style="H1.TLabel").pack(anchor="w", pady=(6, 6))
            sale_intro = (
                "Choose the sale source; the checklist covers the other listings. "
                "Enter the quantity sold or mark the last copy. A separate "
                "CanadianShopper option lets you preview and approve a stock "
                "update; it is independent of the source choice." if self.app.cs_addon else
                "Choose the sale source; the checklist covers the other listings. "
                "Enter the quantity sold or mark the last copy. CanadianShopper "
                "stock updates are manual without the plugin.")
            ttk.Label(self.content, text=sale_intro, wraplength=880,
                      justify="left").pack(anchor="w")
            PANEL_BUILDERS["sold"](self.content, self.app)
            return

    def next_page(self):
        if WIZARD_PAGES[self.page] == "cookie":
            save = getattr(self.app, "_save_user_settings_callback", None)
            if save and not save():
                return
        if self.page < len(WIZARD_PAGES) - 1:
            self.page += 1
            self.render()

    def skip_wizard(self):
        if WIZARD_PAGES[self.page] == "cookie":
            save = getattr(self.app, "_save_user_settings_callback", None)
            if save and not save():
                return
        self.app.show_mode("menu")

    def back(self):
        if self.page > 0:
            self.page -= 1
            self.render()


# ----------------------------------------------------------------- main
def _dpi_aware():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def screenshot_mode(outdir):
    """Render the main screens to PNGs (used for design review)."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    app = App()

    def shot(name):
        app.update_idletasks()
        app.update()
        time.sleep(0.35)
        app.update()
        path = outdir / (name + ".png")
        disp = os.environ.get("DISPLAY")
        if shutil.which("import") and disp:
            subprocess.run(["import", "-display", disp, "-window", "root",
                            "-silent", str(path)], check=False)
        else:
            try:
                from PIL import ImageGrab
                ImageGrab.grab().save(path)
            except Exception as e:
                print("screenshot failed:", e)
        print("shot", path)

    def show_panel(pid):
        app.show_mode("menu")
        app._mode_frame.inner.winfo_children()[0].show_panel(pid)

    def wizard_at(page):
        def go():
            app.show_mode("wizard")
            w = app._mode_frame.inner.winfo_children()[0]
            w.page = page
            w.render()
        return go
    steps = [
        ("1-wizard", wizard_at(0)),
        ("2-wizard-connect", wizard_at(1)),
        ("3-wizard-sold", wizard_at(3)),
        ("4-tasks", lambda: app.show_mode("menu")),
        ("5-panel-sold", lambda: show_panel("sold")),
        ("6-panel-wire", lambda: show_panel("wire")),
        ("7-checklist", lambda: (show_panel("sold"),
                                 ChecklistViewer(app))),
        ("8-tabs", lambda: ([w.destroy() for w in app.winfo_children()
                             if isinstance(w, tk.Toplevel)],
                            app.show_mode("tabs"))),
    ]
    for name, fn in steps:
        fn()
        shot(name)
    app.destroy()


def main():
    _dpi_aware()
    argv = sys.argv[1:]
    if "--screenshot" in argv:
        i = argv.index("--screenshot")
        screenshot_mode(argv[i + 1] if len(argv) > i + 1 else
                        "gui-screenshots")
        return
    scans = [a for a in argv if not a.startswith("-")]
    app = App(scans=scans)
    app.mainloop()


if __name__ == "__main__":
    main()
