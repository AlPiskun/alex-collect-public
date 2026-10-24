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
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from browser_utils import available_browsers, browser_label, open_urls as launch_urls
from plugin_manager import PluginError, PluginManager
from user_settings import (default_scan_dir, load_user_settings,
                           normalize_web_url, site_admin_url,
                           sync_site_url_to_woo_keys)

<<<<<<< HEAD
VERSION = "2.29"
=======
VERSION = "2.28"
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65

DEFAULT_SCAN_DIR = default_scan_dir()
APP_NAME = "Alex Collect Control Panel"

BASE = Path(__file__).resolve().parent          # the tools folder
HERE_HAS_PIPELINE = (BASE.parent / "card_pipeline.py").exists()
WORK = BASE.parent if HERE_HAS_PIPELINE else BASE   # where card_pipeline.py + CSVs live

PLUGIN_MANAGER = PluginManager(core_version=VERSION)
CS_PLUGIN_ID = "canadianshopper"
CS_TOOL_ACTIONS = {
    "sold-cards.py": "after_sale.stock_update",
    "cs-image-sync.py": "batch.photo_stage",
    "pad-and-upload.py": "batch.photo_cache_repair",
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
    "multi": 'I am listing 9 single trading cards for {{STORE_NAME}}. I need high-conversion, SEO-friendly product listings based on images of 9-card sheets. Do not use bulleted lists or — in the output.\nI\'m uploading two images of the same 3x3 sheet of trading cards in a protective sleeve:\n1. FRONT of all 9 cards\n2. BACK of all 9 cards (same 9 cards, sheet flipped horizontally like a page)\n\nGRID NUMBERING (based on the FRONT image):\n[1][2][3]\n[4][5][6]\n[7][8][9]\n\nPosition 1 = top-left, reading left-to-right then top-to-bottom, like English text.\n\nMAPPING BACK IMAGE TO FRONT POSITIONS:\nBecause the sheet is flipped horizontally (like a page turn), each row stays in the same row, but the column order reverses:\n- Left column on BACK = Right column on FRONT\n- Middle column on BACK = Middle column on FRONT\n- Right column on BACK = Left column on FRONT\n\nSo: BACK position 1 → FRONT position 3, BACK position 2 → FRONT position 2, BACK position 3 → FRONT position 1, BACK position 4 → FRONT position 6, BACK position 5 → FRONT position 5, BACK position 6 → FRONT position 4, BACK position 7 → FRONT position 9, BACK position 8 → FRONT position 8, BACK position 9 → FRONT position 7.\n\nWAIT until both images are uploaded before responding.\n\nOnce both images are provided, output results in FRONT position order (1 through 9), using this format for each:\n\nPosition [X] [card details] \nSEO Image titles (must be unique):\n[Manufactures Card #]-[Player Name]-[Year(s)]-[Brand]-front-[grade]\n[Manufactures Card #]-[Player Name]-[Year(s)]-[Brand]-back-[grade]\n\nSEO Title: (Format: \n[Year] [Brand] [Player/Character Name] #[Card #] [Key Rookie/Insert Info] [Team/Series]) Product Description: ({{DESCRIPTION_MIN_WORDS}}+ words. Write a seamless, paragraph-only narrative with a hook intro, historical context, specific pop-culture or sporting achievements, and a \'Condition Report\' section detailing the exact corner wear, edge chipping, and centering seen in the photos. {{LISTING_CONTEXT}} Include a conservative grade estimate explanation). \n\nGrade Estimate: \n(Carefully analyse for creases, wrinkles and marks. Provide a conservative raw grade estimate based on photos e.g., EX-MT 6). Price \n\nRecommendation: \n(Single price rounded up to the nearest {{CURRENCY_NAME}} based on current market value of RAW grade). \n\nPrimary SEO Keyword: \n(Best high-volume search phrase, matching the title exactly and woven naturally into the description). \n\nWooCommerce Tag Bundle: \n(A comma-separated string of exactly {{TAG_COUNT}} relevant tags).\n\nSTRICT OUTPUT FORMAT — DO NOT DEVIATE: This output gets parsed automatically by a script, so the seven headers below must appear EXACTLY as written, character-for-character, every time, with no variation across cards or across responses:\n\nSEO Image titles: SEO Title: Product Description: Grade Estimate: Price Recommendation: Primary SEO Keyword: WooCommerce Tag Bundle:\n\nFollow these rules with no exceptions:\n\nUse these exact seven header strings, spelled and worded exactly as shown above. Never rename, reword, or paraphrase a header (for example, never write "Raw Grade Estimate:" instead of "Grade Estimate:", and never split "SEO Image titles:" into separate "Front SEO Image Title:" / "Back SEO Image Title:" headers).\nEach header goes on its own line, followed immediately by a colon and nothing else on that line — no parenthetical notes, no asides, no instructions repeated back (for example, never write "SEO Image titles (must be unique):").\nDo not bold, italicize, or otherwise wrap any header in markdown (no Grade Estimate:).\n"SEO Image titles:" is always followed by exactly two lines: the front filename, then the back filename, in that order, with no blank line between them and nothing else on those lines.\nThe "Condition Report" sentence inside the Product Description must begin with the literal words "Condition Report:" (with the colon) so it can be identified within the paragraph, but it stays embedded in the Product Description narrative as instructed above — do not give it its own top-level header.\nThe content under "Grade Estimate:" should lead with the short letter/number grade itself (e.g. "EX 5" or "VG-EX 4") before any explanatory sentence, so the grade is the very first thing after the header.\nThe content under "Price Recommendation:" should be a single price only, formatted as "{{CURRENCY_PREFIX}}" followed by a whole number (e.g. "{{CURRENCY_PREFIX}}9"), with no extra words.\nDo not insert any other headers, section titles, or labels anywhere in the output beyond the seven listed above.',
    "single": 'I am listing 9 single trading cards for {{STORE_NAME}}. I need high-conversion, SEO-friendly product listings based on images of 9-card sheets. Do not use bulleted lists or — in the output.\nI\'m uploading two images of the same 3x3 sheet of trading cards in a protective sleeve:\n1. FRONT of all 9 cards\n2. BACK of all 9 cards (same 9 cards, sheet flipped horizontally like a page)\n\nGRID NUMBERING (based on the FRONT image):\n[1][2][3]\n[4][5][6]\n[7][8][9]\n\nPosition 1 = top-left, reading left-to-right then top-to-bottom, like English text.\n\nMAPPING BACK IMAGE TO FRONT POSITIONS:\nBecause the sheet is flipped horizontally (like a page turn), each row stays in the same row, but the column order reverses:\n- Left column on BACK = Right column on FRONT\n- Middle column on BACK = Middle column on FRONT\n- Right column on BACK = Left column on FRONT\n\nSo: BACK position 1 → FRONT position 3, BACK position 2 → FRONT position 2, BACK position 3 → FRONT position 1, BACK position 4 → FRONT position 6, BACK position 5 → FRONT position 5, BACK position 6 → FRONT position 4, BACK position 7 → FRONT position 9, BACK position 8 → FRONT position 8, BACK position 9 → FRONT position 7.\n\nWAIT until both images are uploaded before responding.\n\nOnce both images are provided, output results in FRONT position order (1 through 9), using this format for each:\n\nPosition [X] [card details] \nSEO Image titles: \n[Manufactures Card #]-[Player/Character Name]-[Year(s)]-[Brand]-front \n[Manufactures Card #]-[Player/Character Name]-[Year(s)]-[Brand]-back\n \nSEO Title: (Format: \n[Year] [Brand] [Player/Character Name] #[Card #] [Key Rookie/Insert Info] [Team/Series]) Product Description: ({{DESCRIPTION_MIN_WORDS}}+ words. Write a seamless, paragraph-only narrative with a hook intro, historical context, specific pop-culture or sporting achievements, and a \'Condition Report\' section detailing the exact corner wear, edge chipping, and centering seen in the photos. {{LISTING_CONTEXT}} Include a conservative grade estimate explanation). \n\nGrade Estimate: \n(Carefully analyse for creases, wrinkles and marks. Provide a conservative raw grade estimate based on photos e.g., EX-MT 6). Price \n\nRecommendation: \n(Single price rounded up to the nearest {{CURRENCY_NAME}} based on current market value of RAW grade). \n\nPrimary SEO Keyword: \n(Best high-volume search phrase, matching the title exactly and woven naturally into the description). \n\nWooCommerce Tag Bundle: \n(A comma-separated string of exactly {{TAG_COUNT}} relevant tags).\n\nSTRICT OUTPUT FORMAT — DO NOT DEVIATE: This output gets parsed automatically by a script, so the seven headers below must appear EXACTLY as written, character-for-character, every time, with no variation across cards or across responses:\n\nSEO Image titles: SEO Title: Product Description: Grade Estimate: Price Recommendation: Primary SEO Keyword: WooCommerce Tag Bundle:\n\nFollow these rules with no exceptions:\n\nUse these exact seven header strings, spelled and worded exactly as shown above. Never rename, reword, or paraphrase a header (for example, never write "Raw Grade Estimate:" instead of "Grade Estimate:", and never split "SEO Image titles:" into separate "Front SEO Image Title:" / "Back SEO Image Title:" headers).\nEach header goes on its own line, followed immediately by a colon and nothing else on that line — no parenthetical notes, no asides, no instructions repeated back (for example, never write "SEO Image titles (must be unique):").\nDo not bold, italicize, or otherwise wrap any header in markdown (no Grade Estimate:).\n"SEO Image titles:" is always followed by exactly two lines: the front filename, then the back filename, in that order, with no blank line between them and nothing else on those lines.\nThe "Condition Report" sentence inside the Product Description must begin with the literal words "Condition Report:" (with the colon) so it can be identified within the paragraph, but it stays embedded in the Product Description narrative as instructed above — do not give it its own top-level header.\nThe content under "Grade Estimate:" should lead with the short letter/number grade itself (e.g. "EX 5" or "VG-EX 4") before any explanatory sentence, so the grade is the very first thing after the header.\nThe content under "Price Recommendation:" should be a single price only, formatted as "{{CURRENCY_PREFIX}}" followed by a whole number (e.g. "{{CURRENCY_PREFIX}}9"), with no extra words.\nDo not insert any other headers, section titles, or labels anywhere in the output beyond the seven listed above.',
}
PROMPT_FILES = {
    "multi": "card description command - with grade.txt",
    "single": "card description command.txt",
}
PROMPT_TITLES = {
    "multi": ("Multiple grades on the sheet\n"
              "(the grade goes into the image titles)"),
    "single": ("One grade for the whole sheet\n"
               "(titles stay without the grade)"),
}


def load_prompt(kind):
    p = BASE / PROMPT_FILES[kind]
    try:
        t = p.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
        if not t:
            t = PROMPT_FALLBACKS[kind]
    except Exception:
        t = PROMPT_FALLBACKS[kind]
    settings = load_settings()
    store_name = str(settings.get("store_name", "")).strip() or "my online store"
    currency_prefix = str(settings.get("currency_prefix", "C$")).strip() or "$"
    currency_name = str(settings.get("currency_name", "Canadian dollars")).strip() or "your currency"
    description_words = str(settings.get("description_min_words", 400))
    tag_count = str(settings.get("tag_count", 8))
    listing_context = str(settings.get("listing_context", "")).strip()
    return (t.replace("{{STORE_NAME}}", store_name)
             .replace("{{CURRENCY_PREFIX}}", currency_prefix)
             .replace("{{CURRENCY_NAME}}", currency_name)
             .replace("{{DESCRIPTION_MIN_WORDS}}", description_words)
             .replace("{{TAG_COUNT}}", tag_count)
             .replace("{{LISTING_CONTEXT}}", listing_context))


def classify_clipboard(text):
    """(kind, verdict) for whatever the clipboard holds:
    short / prompt / answer / other."""
    t = (text or "").strip()
    if len(t) < 200:
        return "short", "too short to be the full answer"
    for k in ("multi", "single"):
        if t.startswith(load_prompt(k)[:60]):
            return "prompt", "still the PROMPT you copied for the AI chat"
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
    ("Have you finished the WP All Import",
     "The pipeline asks whether the new cards are already PUBLISHED on "
     "your website. 'y' + Send continues to the Facebook files (they only "
     "include published products); 'n' or an empty Send stops here - the "
     "Woo + CanadianShopper CSVs are already written, nothing is lost. "
     "If the cards are not live yet: publish first, then use the "
     "Facebook feed updater button afterwards."),
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
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        self.cmd = " ".join(cmd)
        self.title = title
        self.on_done = on_done
        self._dialog_buffer = ""
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=str(cwd), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=env)
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
                shown = self._consume_dialog_protocol(payload)
                if shown:
                    self.app.console_write(shown)
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

* Scan folder - where your scanner drops files. Choose it here; the "card
  needs new photos" tool opens the folder after writing the reminder list."""

DOCS["pipeline"] = """\
Use this for a new batch of cards. Choose the FRONT scan and, if you have
one, the BACK scan. The saved AI chat page opens in your selected browser
(or Alex Collect asks you to choose a browser the first time). Select one of
the two prompts; it is copied to the clipboard. Upload the scans and paste the prompt into the AI page manually.
When you copy the complete AI reply, the app detects it and asks whether to
split and build or split only. Alex Collect matches descriptions to images
and prepares the import files and photos in your batch folder. Nothing is
uploaded or published by this step; review the files and do the website import
yourself. After products are published, the workflow can refresh your Facebook
feed. If the CanadianShopper plugin is enabled, its photo-staging actions are
available too."""

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
Now the actual import happens on the website - the one step the tools
cannot do for you, because it runs behind your login in the browser:

  1. Open CanadianShopper (button below) and log in.
  2. Vendor dashboard -> Products -> upload / import the CSV.
  3. Use the newest file from the cs-ready folder - the name starts
     with canadianshopper_import_ and ends _01_of_NN.csv. The pipeline
     opens the folder containing the generated import file for you.
  4. Keep each file under 500 rows (that is what Combine ensures).
  5. When the import shows the products, publish them.

Then come back and press "Wire the photos" - that is what puts the
back of each card behind the front."""

DOCS["wire"] = """\
After the import, this step attaches what the importer could not:
it points every new listing's main photo at the hosted square front
and adds the back photo as a gallery row behind it, using the
back-map.json from the staging step.

Always Dry-run first: the report (cs-image-report.csv) marks every
card ok / skip / unmatched / no-back, and nothing is changed. When the
dry run looks right, press Wire for real."""

DOCS["rerun"] = """\
The repair button. If a fresh CSV import has replaced your photos with
the original portrait files again, this re-points EVERY Alex Collect
listing at the square front + back gallery - using the URL cache, so
it uploads NOTHING. It is the same one click as rerun.bat and it is
safe to run any time; Dry-run shows the plan first."""

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

DOCS["square"] = """\
Square up a photo (or a whole folder) by padding it onto a white
square - for the occasional card you upload by hand through the
dashboard instead of through a batch. The square copy is written next
to the original; the original is never touched. No cookie needed."""

DOCS["newphotos"] = """\
A card's photo needs replacing (better scan, condition change...).
Type the card names; the tool writes the reminder rows into the
checklist - including "scan the replacement into your scan folder"
- and opens the scan folder so you can start right away. The checklist
then walks you through updating the photo on the website, on
CanadianShopper (WirePhotos), and on eBay and Facebook."""

DOCS_CORE = {
    "cookie": """\
Set your store URL, marketplace page links, AI page URL, store name, batch
folder, and scanner folder here. The scanner folder is user-selectable and
opens automatically for photo reminders. WooCommerce credentials stay in the
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


class ScrollFrame(ttk.Frame):
    """A vertically scrollable container: tall content scrolls, the console
    below never gets squeezed out of view."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical",
                            command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(2, 2))
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(
                            scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw",
                                  tags="inner")
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(fill="both", expand=True, side="left")
        vsb.pack(fill="y", side="right")
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure("inner",
                                                             width=e.width))
        self.bind("<Enter>", lambda e: self._wheel(True))
        self.bind("<Leave>", lambda e: self._wheel(False))

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
        self.geometry("1020x760")
        self.minsize(880, 620)
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
        st.configure("TNotebook.Tab", padding=(8, 3))
        st.configure("TLabelframe", padding=4)
        try:
            st.configure("Task.TButton", wraplength=220)
        except Exception:
            pass

    def _build_menu(self):
        m = tk.Menu(self)
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
<<<<<<< HEAD
        m.add_command(label="Plugins", command=lambda: self.show_panel("plugins"))
        m.add_command(label="Logs & reports",
                      command=lambda: self.show_panel("logs"))
=======
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
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

<<<<<<< HEAD
    def show_panel(self, panel_id):
        """Open a panel from the menu bar, regardless of current view."""
=======
    def show_user_settings(self):
        """Open the central settings panel from any view."""
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
        self.show_mode("menu")
        self.update_idletasks()
        try:
            tasks = self._mode_frame.inner.winfo_children()[0]
<<<<<<< HEAD
            tasks.show_panel(panel_id)
        except (AttributeError, IndexError, tk.TclError):
            log("could not open %s panel" % panel_id)

    def show_user_settings(self):
        """Open the central settings panel from the menu bar."""
        self.show_panel("cookie")
=======
            tasks.show_panel("cookie")
        except (AttributeError, IndexError, tk.TclError):
            log("could not open User Settings panel")
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65

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
        self.console = tk.Text(
            box, height=16, state="disabled", wrap="word", bg="#141414",
            fg="#e8e8e8", insertbackground="#e8e8e8",
            font=("Consolas", 9) if sys.platform == "win32"
                 else "TkFixedFont")
        ysb = ttk.Scrollbar(box, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=ysb.set)
        self.console.bind("<Control-End>", self._console_scroll_end)
        self.console.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        add_tooltip(ysb, "Scroll the output history. New output won't pull you back down after you scroll up.")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.console.tag_configure("cmd", foreground="#9fd0ff")
        self.console.tag_configure("err", foreground="#ff9d9d")
        self.console.tag_configure("ok", foreground="#9de0a8")
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

    def _console_following_tail(self):
        """Keep following new output only while the user is already at the end."""
        try:
            return self.console.yview()[1] >= 0.98
        except (tk.TclError, IndexError):
            return True

    def console_write(self, chunk):
        """Insert tool output without yanking the view away from scrollback."""
        follow = self._console_following_tail()
        self.console.config(state="normal")
        self.console.insert("end", chunk)
        self.console.config(state="disabled")
        if follow:
            self.console.see("end")

    def console_line(self, text, tag=None):
        follow = self._console_following_tail()
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
        if follow:
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
    def show_mode(self, mode):
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
        self.wait_window(top)
        return chosen

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
<<<<<<< HEAD
                      anchor="w", padx=10, pady=(10, 5))
=======
                      anchor="w", padx=14, pady=(14, 8))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
        labels.insert(0, "Ask me again next time")
        label_var = tk.StringVar(master=top, value=(
            labels[1] if len(labels) > 1 else labels[0]))
        ttk.Combobox(top, textvariable=label_var, values=labels,
                     state="readonly", width=34).pack(
<<<<<<< HEAD
                         fill="x", padx=10, pady=3)
        result = {"browser": None}
        buttons = ttk.Frame(top)
        buttons.pack(fill="x", padx=10, pady=(5, 10))
=======
                         fill="x", padx=14, pady=4)
        result = {"browser": None}
        buttons = ttk.Frame(top)
        buttons.pack(fill="x", padx=14, pady=(8, 14))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65

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
               "wire", "rerun", "sold", "checklist", "zerostock", "square",
               "newphotos", "logs", "plugins"]
<<<<<<< HEAD
GROUPS_FULL = [("Sell a new batch", ["pipeline", "combine", "stage",
=======
GROUPS_FULL = [("User settings", ["cookie"]),
               ("Sell a new batch", ["pipeline", "combine", "stage",
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
                                     "importpanel", "wire"]),
               ("After a sale", ["sold", "checklist", "zerostock",
                                 "newphotos"]),
               ("Photos", ["square", "rerun"])]


def groups_for(has_cs):
    """Compact task groups. Settings, plugins, and logs live in the menu bar.

    Without the CanadianShopper add-on, its API steps disappear and the
    pipeline writes import files for manual upload instead.
    """
    if has_cs:
        return GROUPS_FULL
<<<<<<< HEAD
    return [("Sell a new batch", ["pipeline", "combine", "importpanel"]),
=======
    return [("User settings", ["cookie"]),
            ("Sell a new batch", ["pipeline", "combine", "importpanel"]),
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
            ("After a sale", ["sold", "checklist", "newphotos"]),
            ("Photos", ["square"])]
TITLES = {
    "cookie": "User settings",
    "pipeline": "Run the card pipeline (new batch)",
    "combine": "Combine CSVs into import batches",
    "stage": "Stage the photos for the batch",
    "importpanel": "Import & publish (on the website)",
    "wire": "Wire the photos (after the import)",
    "rerun": "Re-point every listing from the cache (repair)",
    "sold": "A card sold - mark it everywhere",
    "checklist": "The tick-off checklist",
    "zerostock": "Archive CanadianShopper listings already at 0",
    "square": "Square up a photo (manual upload)",
    "plugins": "Plugins",
    "newphotos": "A card needs new photos",
    "logs": "Logs and reports",
}
MENU_LABELS = {
    "cookie": "User settings",
    "pipeline": "Run the card pipeline",
    "combine": "Combine CSVs",
    "stage": "Stage the photos",
    "importpanel": "Import & publish",
    "wire": "Wire the photos",
    "rerun": "Re-point photos (repair)",
    "sold": "A card sold",
    "checklist": "The checklist",
    "zerostock": "Archive listings at 0",
    "square": "Square up a photo",
    "newphotos": "New photos needed",
    "logs": "Logs & reports",
    "plugins": "Plugins",
}
BLURBS = {
    "cookie": "Set your store, AI, marketplace, and folder preferences; manage connections.",
    "pipeline": "Turn card scans and AI descriptions into listing files.",
    "combine": "Merge the month's CSVs into 500-row import files.",
    "stage": "Square + host fronts and backs, rewrite the CSVs into cs-ready.",
    "importpanel": "The one step on the website: upload the CSV, publish.",
    "wire": "Attach the back photos and fix the main images after an import.",
    "rerun": "Import clobbered the photos? Re-point everything, zero uploads.",
    "sold": "Record where the sale happened and follow up on the other listings.",
    "checklist": "See what is still outstanding and tick it off.",
    "zerostock": "Sweep: archive everything sitting at quantity 0.",
    "square": "Pad a photo onto a white square for a manual dashboard upload.",
    "plugins": "Install and manage optional plugins.",
    "newphotos": "Reminder rows + opens the scanner folder.",
    "logs": "Where every run is recorded.",
}


def panel_header(parent, app, pid, with_doc=True):
    """Title + doc text shared by every panel view (core-aware)."""
    core = not getattr(app, "cs_addon", True)
    titles = TITLES
    docs = {**DOCS, **(DOCS_CORE if core else {})}
    top = ttk.Frame(parent)
    top.pack(fill="x", pady=(0, 3))
    ttk.Label(top, text=titles[pid], style="H2.TLabel").pack(anchor="w")
    if with_doc:
        text = docs.get(pid, DOCS.get(pid, "")).strip()
        ttk.Label(top, text=text, style="Dim.TLabel", wraplength=780,
                  justify="left").pack(fill="x", pady=(1, 4))
    return top


# ---- individual panel builders (parent = container frame) ----------------

def build_cookie(parent, app):
    panel_header(parent, app, "cookie")
    scroller = ScrollFrame(parent)
    scroller.pack(fill="both", expand=True)
    box = ttk.Frame(scroller.inner)
    box.pack(fill="x", expand=True)

    fields = {}
    app._user_setting_vars = fields
    def field_row(container, row, label, key, width=68, hint=None):
        ttk.Label(container, text=label).grid(row=row, column=0, sticky="w",
<<<<<<< HEAD
                                              padx=(0, 5), pady=1)
=======
                                              padx=(0, 6), pady=2)
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
        var = tk.StringVar(master=container,
                           value=str(app.settings.get(key, "")))
        fields[key] = var
        ttk.Entry(container, textvariable=var, width=width).grid(
<<<<<<< HEAD
            row=row, column=1, sticky="ew", padx=2, pady=1)
        if hint:
            ttk.Label(container, text=hint, style="Dim.TLabel").grid(
                row=row + 1, column=1, sticky="w", padx=2, pady=(0, 2))
=======
            row=row, column=1, sticky="ew", padx=3, pady=2)
        if hint:
            ttk.Label(container, text=hint, style="Dim.TLabel").grid(
                row=row + 1, column=1, sticky="w", padx=3, pady=(0, 3))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
        return var

    startup_var = tk.StringVar(
        master=box, value=app.settings.get("startup_mode", "menu"))
    startup_row = ttk.Frame(box)
<<<<<<< HEAD
    startup_row.pack(fill="x", pady=(0, 3))
=======
    startup_row.pack(fill="x", pady=(0, 4))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
    ttk.Label(startup_row, text="Startup view:").pack(side="left")
    ttk.Combobox(startup_row, textvariable=startup_var, state="readonly",
                 values=("menu", "tabs", "wizard"), width=14).pack(
                     side="left", padx=6)

    ttk.Label(box, text="Store and AI", style="H2.TLabel").pack(anchor="w")
    general = ttk.Frame(box)
<<<<<<< HEAD
    general.pack(fill="x", pady=(1, 4))
=======
    general.pack(fill="x", pady=(2, 6))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
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

    row = ttk.Frame(box)
<<<<<<< HEAD
    row.pack(fill="x", pady=(0, 4))
=======
    row.pack(fill="x", pady=(0, 8))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
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

    ttk.Label(box, text="Marketplace pages", style="H2.TLabel").pack(
<<<<<<< HEAD
        anchor="w", pady=(2, 0))
    market = ttk.Frame(box)
    market.pack(fill="x", pady=(1, 4))
=======
        anchor="w", pady=(4, 0))
    market = ttk.Frame(box)
    market.pack(fill="x", pady=(2, 8))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
    market.columnconfigure(1, weight=1)
    field_row(market, 0, "eBay active listings URL:", "ebay_selling_url")
    field_row(market, 1, "Facebook listing/review page URL:",
              "facebook_selling_url")
    field_row(market, 2, "CanadianShopper vendor page URL:",
              "canadianshopper_store_url")

    ttk.Label(box, text="eBay Quick List handoff", style="H2.TLabel").pack(
<<<<<<< HEAD
        anchor="w", pady=(2, 0))
    ebay_box = ttk.Frame(box)
    ebay_box.pack(fill="x", pady=(1, 4))
=======
        anchor="w", pady=(4, 0))
    ebay_box = ttk.Frame(box)
    ebay_box.pack(fill="x", pady=(2, 8))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
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
<<<<<<< HEAD
            row=16, column=1, sticky="w", padx=3, pady=(0, 3))

    ttk.Label(box, text="Facebook Marketplace export fields",
              style="H2.TLabel").pack(anchor="w", pady=(2, 0))
    facebook_box = ttk.Frame(box)
    facebook_box.pack(fill="x", pady=(1, 4))
=======
            row=16, column=1, sticky="w", padx=3, pady=(0, 4))

    ttk.Label(box, text="Facebook Marketplace export fields",
              style="H2.TLabel").pack(anchor="w", pady=(4, 0))
    facebook_box = ttk.Frame(box)
    facebook_box.pack(fill="x", pady=(2, 8))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
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
<<<<<<< HEAD
    description_template = tk.Text(facebook_box, height=4, wrap="word")
=======
    description_template = tk.Text(facebook_box, height=5, wrap="word")
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
    description_template.grid(row=6, column=1, sticky="ew", padx=3, pady=2)
    description_template.insert(
        "1.0", str(app.settings.get("facebook_feed_description_template", "")))
    fields["facebook_feed_description_template"] = description_template
    ttk.Label(facebook_box, text=(
        "Placeholders: {title}, {description}, {product_url}, {price}, {id}, "
        "{image_link}. Leave Price template as {price} to use the live-feed "
        "price."), style="Dim.TLabel",
        wraplength=720, justify="left").grid(
<<<<<<< HEAD
            row=7, column=1, sticky="w", padx=3, pady=(0, 3))

    ttk.Label(box, text="CanadianShopper CSV defaults", style="H2.TLabel").pack(
        anchor="w", pady=(2, 0))
    cs_config = ttk.Frame(box)
    cs_config.pack(fill="x", pady=(1, 4))
=======
            row=7, column=1, sticky="w", padx=3, pady=(0, 4))

    ttk.Label(box, text="CanadianShopper CSV defaults", style="H2.TLabel").pack(
        anchor="w", pady=(4, 0))
    cs_config = ttk.Frame(box)
    cs_config.pack(fill="x", pady=(2, 8))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
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

    ttk.Label(box, text="Working folders", style="H2.TLabel").pack(
<<<<<<< HEAD
        anchor="w", pady=(2, 0))
    grid = ttk.Frame(box)
    grid.pack(fill="x", pady=(1, 4))
=======
        anchor="w", pady=(4, 0))
    grid = ttk.Frame(box)
    grid.pack(fill="x", pady=(2, 6))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
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
    ttk.Button(box, text="Save user settings", command=save_user_settings).pack(
<<<<<<< HEAD
        anchor="w", pady=(1, 4))

    if app.cs_addon:
        ttk.Separator(box).pack(fill="x", pady=(1, 4))
=======
        anchor="w", pady=(2, 8))

    if app.cs_addon:
        ttk.Separator(box).pack(fill="x", pady=(2, 6))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
        ttk.Label(box, text="CanadianShopper connection",
                  style="H2.TLabel").pack(anchor="w")
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
                            "\nck_replace_with_read_only_consumer_key\n"
                            "cs_replace_with_read_only_consumer_secret\n",
                            encoding="utf-8")
    open_path(path)
    app.console_line("Opened private WooCommerce credentials file; keep it "
                     "out of public repos and messages.", "dim")


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
               "split and build or split only. Review the prepared import files "
               "before importing; this step does not publish listings.",
               style="Dim.TLabel", wraplength=680, justify="left").pack(
                   anchor="w")
    next_steps = ("Next: combine pending batches if needed, stage the photos, "
                  "then import and publish on your website." if app.cs_addon else
                  "Next: combine pending batches if needed, then review and "
                  "manually import and publish the files. Photo staging and "
                  "back-photo wiring require the CanadianShopper plugin.")
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


def canadianshopper_results_dir(app):
    return Path(app.settings.get("pipeline_dir") or str(WORK)) / "canadianshopper_products"


def canadianshopper_ready_dir(app):
    return canadianshopper_results_dir(app) / "cs-ready"


def canadianshopper_cache_path(app):
    return canadianshopper_results_dir(app) / "cs-image-cache.json"


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
        app.run_tool("cs-image-sync.py", args, "Stage the photos",
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
    if not getattr(app, "cs_addon", True):
        ttk.Label(box, text="Photo staging and the back-photo wiring are "
                  "the CanadianShopper add-on's job - until it is "
                  "installed, square photos by hand (Photos -> Square up "
                  "a photo) and upload them in the dashboard.",
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
        app.run_tool("cs-image-sync.py", args,
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
        args = ["--mode", "upload", "--images", "front,back",
                "--cookie-file", str(CS_COOKIE_FILE),
                "--cache", str(BASE / "image-cache.json"),
                "--report", str(BASE / "reports" / "image-sync-latest.csv")]
        if dry:
            args.append("--dry-run")
        app.run_tool("pad-and-upload.py", args,
                     "Re-point listings from the cache" +
                     (" - DRY RUN" if dry else ""),
                     cwd=str(BASE),
                     confirm=None if dry else
                     "Re-point every Alex Collect listing at the cached "
                     "square front + back gallery?\n\nNo photos are "
                     "uploaded - they are already hosted.")

    row = ttk.Frame(box)
    row.pack(anchor="w", pady=4)
    ttk.Button(row, text="Dry-run (writes nothing)", command=lambda: go(True)
               ).pack(side="left")
    ttk.Button(row, text="Re-point for real", command=lambda: go(False)).pack(
        side="left", padx=8)


def build_sold(parent, app):
    panel_header(parent, app, "sold")
    box = ttk.Frame(parent)
    box.pack(fill="x")
    src = tk.StringVar(master=parent, value="typed")
    onch = tk.StringVar(master=parent, value="website")
    do_cs = tk.BooleanVar(master=parent, value=False)

    row = ttk.Frame(box)
    row.pack(anchor="w", pady=(0, 4))
    ttk.Label(row, text="Where did it sell?").pack(side="left")
    for txt, val in (("my website", "website"), ("CanadianShopper", "canadianshopper"),
                     ("Facebook", "facebook"), ("eBay", "ebay"),
                     ("in person", "inperson"), ("somewhere else", "other")):
        ttk.Radiobutton(row, text=txt, value=val, variable=onch).pack(
            side="left", padx=(8, 0))

    row2 = ttk.Frame(box)
    row2.pack(anchor="w")
    ttk.Label(row2, text="How do you want to name the cards?").pack(
        side="left")
    for txt, val in (("type them", "typed"),
                     ("my website's orders CSV", "orders"),
                     ("website API key (woo-keys.txt)", "keys")):
        ttk.Radiobutton(row2, text=txt, value=val, variable=src).pack(
            side="left", padx=(8, 0))
    ttk.Label(
        box,
        text="These choices provide card names for the core follow-up checklist "
             "too; they are not CanadianShopper-plugin-only.",
        style="Dim.TLabel", wraplength=640, justify="left").pack(
            anchor="w", pady=(3, 0))

    if app.cs_addon:
        ttk.Checkbutton(
            box, variable=do_cs,
            text="Also fix CanadianShopper now (separate from the sale source; "
                 "preview and approve before writing)").pack(anchor="w", pady=(6, 2))
        ttk.Label(
            box,
            text="The match picker appears only after a valid session is loaded "
                 "and a title is unmatched or ambiguous. Check the console for "
                 "cookie/session errors or the preview details.",
            style="Dim.TLabel", wraplength=640, justify="left").pack(
                anchor="w", pady=(0, 2))
    else:
        ttk.Label(box, text="Without the plugin, CanadianShopper stock changes "
                  "remain manual checklist tasks.", style="Dim.TLabel",
                  wraplength=640, justify="left").pack(anchor="w", pady=(6, 2))

    state = {"path": None}

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
        kf = BASE / "woo-keys.txt"
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

    ttk.Label(box,
              text="Typed-sale flow: enter the cards, save the list, then add it to "
                   "the checklist. Choose the sale source above; the checklist "
                   "covers the other channels. One typed card opens the remaining "
                   "seller pages in Edge, including the CanadianShopper store. "
                   "Paste the copied title into CanadianShopper, eBay and "
                   "Facebook searches manually; WooCommerce opens the orders list. "
                   "The plugin-only CanadianShopper stock checkbox is independent; "
                   "no listing is changed automatically.",
              style="Dim.TLabel", wraplength=680, justify="left").pack(
                  anchor="w", pady=(4, 0))

    row3 = ttk.Frame(box)
    row3.pack(anchor="w", pady=(4, 0))

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

    ttk.Button(row3, text="Type the cards...", command=type_cards).pack(
        side="left")
    ttk.Button(row3, text="Add to the checklist (and fix CS if ticked)",
               style="Task.TButton", command=add_rows).pack(side="left", padx=8)
    if app.cs_addon:
        row4 = ttk.Frame(box)
        row4.pack(anchor="w", pady=(4, 0))
        ttk.Button(row4, text="CanadianShopper only: preview the stock "
                   "change", command=lambda: fix_cs(False)).pack(side="left")
        ttk.Button(row4, text="Apply the previewed change",
                   command=lambda: fix_cs(True)).pack(side="left", padx=8)


def build_plugins(parent, app):
    panel_header(parent, app, "plugins")
    box = ttk.Frame(parent)
    box.pack(fill="both", expand=True)
    ttk.Label(box, text=(
        "Plugins are optional code packages. Install only ZIPs from a "
        "source you trust; a plugin can access files and accounts available "
        "to this Windows user. The app checks metadata but does not sandbox "
        "plugin code."), style="Dim.TLabel", wraplength=780,
        justify="left").pack(anchor="w", pady=(0, 8))

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


def build_newphotos(parent, app):
    panel_header(parent, app, "newphotos")
    box = ttk.Frame(parent)
    box.pack(fill="x")

    def remind():
        Editor(self_toplevel=box, title="Cards that need new photos",
               hint="One card title per line.",
               initial="", save_to=BASE / "needs-photos.txt",
               on_saved=lambda p: app.run_tool(
                   "sold-everywhere.py",
                   ["--images-file", str(p), "--scan-dir",
                    app.settings.get("scan_dir", DEFAULT_SCAN_DIR),
                    "--checklist", str(CHECKLIST)],
                   "Write the photo reminders",
                   cwd=app.settings.get("pipeline_dir", str(WORK))))

    row = ttk.Frame(box)
    row.pack(anchor="w", pady=4)
    ttk.Button(row, text="Type the cards...", command=remind).pack(side="left")
    ttk.Button(row, text="Open the scanner folder",
               command=lambda: (None if open_path(app.settings.get(
                   "scan_dir", DEFAULT_SCAN_DIR)) else
                   messagebox.showwarning("Not found",
                                          "The scan folder does not exist:"
                                          "\n%s\nSet it in the Connection "
                                          "panel." %
                                          app.settings.get(
                                              "scan_dir",
                                              DEFAULT_SCAN_DIR)))
               ).pack(side="left", padx=8)


def build_logs(parent, app):
    panel_header(parent, app, "logs")
    box = ttk.Frame(parent)
    box.pack(fill="x")

    ttk.Label(box, text=(
        "Move older root-level marketplace outputs into their folders. "
        "Preview first; this organizer never deletes or overwrites files."),
        style="Dim.TLabel", wraplength=780, justify="left").pack(
            anchor="w", pady=(0, 3))
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
    "zerostock": build_zerostock,
    "square": build_square,
    "newphotos": build_newphotos,
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
<<<<<<< HEAD
            "Choose the matching prompt below; it is copied. Upload the scans "
            "to the saved AI page and paste the prompt there."),
            wraplength=700, justify="left").pack(anchor="w")
=======
            "The saved AI page opens when this dialog starts. Choose the "
            "command that matches the sheet; it is copied to your clipboard. "
            "Upload the FRONT and BACK images to the AI page and paste the "
            "command there manually."),
            wraplength=740, justify="left").pack(anchor="w")
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
        row = ttk.Frame(box)
        row.pack(fill="x", pady=4)
        for kind in ("multi", "single"):
            ttk.Button(row, text=PROMPT_TITLES[kind], style="Task.TButton",
                       width=40,
                       command=lambda k=kind: self.pick(k)).pack(
<<<<<<< HEAD
                           side="left", padx=(0, 6))
        self.ai_url_status = ttk.Label(
            box, text="The saved AI page opens automatically; copy its full reply when done.",
            style="Dim.TLabel", wraplength=700, justify="left")
=======
                           side="left", padx=(0, 10))
        self.ai_url_status = ttk.Label(
            box, text="The AI page URL is in User settings. Upload the scans "
                     "and paste the prompt manually; the clipboard monitor "
                     "will detect a copied reply.",
            style="Dim.TLabel", wraplength=740, justify="left")
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
        self.ai_url_status.pack(fill="x", pady=(2, 0))
        self.status = ttk.Label(box, text="", foreground="#1b5e20",
                                wraplength=740, justify="left")
        self.status.pack(fill="x")

        ttk.Separator(box).pack(fill="x", pady=5)
        ttk.Label(box, text="3) The AI's answer", style="H2.TLabel").pack(
            anchor="w")
        ttk.Label(box, text=(
<<<<<<< HEAD
            "Copy the complete AI response. Alex Collect detects it and asks "
            "whether to build listings or split only."),
            wraplength=700, justify="left").pack(anchor="w")
=======
            "When the AI finishes, use its Copy button (or select and copy "
            "the full reply). Alex Collect detects the copied answer, holds it "
            "for this run, and asks whether to split and build or split only."),
            wraplength=740, justify="left").pack(anchor="w")
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
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
        kind, verdict = classify_clipboard(text)
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
        text = load_prompt(kind)
        try:
            current = self.app.clipboard_get()
        except Exception:
            current = ""
        if current.strip() and current.strip() != text.strip() and \
                classify_clipboard(current)[0] == "answer" and \
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
                  "Could not reach the clipboard - open %s and copy the "
                  "text by hand." % (BASE / PROMPT_FILES[kind])))
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
        kind, verdict = classify_clipboard(answer)
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

                self.on_run(["listing", "--input", str(input_file),
                             "--facebook"],
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
        ttk.Label(self.menu, text="What do you want to do today?",
                  style="H1.TLabel").pack(anchor="w", pady=(2, 4))
        for group, ids in groups_for(self.app.cs_addon):
            ttk.Label(self.menu, text=group, style="H2.TLabel").pack(
                anchor="w", pady=(5, 1))
            grid = ttk.Frame(self.menu)
            grid.pack(fill="x")
            for c, pid in enumerate(ids):
                cell = ttk.Frame(grid)
                cell.grid(row=0, column=c, sticky="nsew", padx=(0, 6))
                grid.columnconfigure(c, weight=1)
<<<<<<< HEAD
                button = ttk.Button(
                    cell, text=MENU_LABELS[pid], width=20,
                    command=lambda p=pid: self.show_panel(p))
                button.pack(anchor="w")
                add_tooltip(button, BLURBS[pid])
=======
                label = MENU_LABELS[pid]
                ttk.Button(cell, text=label, width=22,
                           command=lambda p=pid: self.show_panel(p)).pack(
                               anchor="w")
                ttk.Label(cell, text=BLURBS[pid], style="Dim.TLabel",
                          wraplength=150, justify="left").pack(
                              anchor="w", pady=(2, 0))
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65

    def show_panel(self, pid):
        self.menu.destroy()
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        ttk.Button(wrap, text="<- All tasks",
                   command=lambda: self.app.show_mode("menu")).pack(
                       anchor="w", pady=(2, 6))
        PANEL_BUILDERS[pid](wrap, self.app)


# --------------------------------------------------------------- tabs
class TabsFrame(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        for group, ids in groups_for(app.cs_addon):
            tab = ttk.Frame(nb, padding=(5, 3))
            nb.add(tab, text=group)
            for pid in ids:
                box = ttk.Frame(tab, padding=(2, 1))
                box.pack(fill="x", pady=(0, 4))
                PANEL_BUILDERS[pid](box, app)


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
                "  new photos: scan -> the reminder list -> update everywhere\n\n"
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
    app.geometry("1020x760+0+0")

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
