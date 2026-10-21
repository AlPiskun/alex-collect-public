import os
import glob
import csv
import unicodedata
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import re
from datetime import datetime
import pandas as pd
import requests

APP_DIR = Path(__file__).resolve().parents[2]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
from user_settings import feed_urls, load_user_settings

USER_SETTINGS = load_user_settings(APP_DIR / "gui-settings.json")
_, _configured_feed_url = feed_urls(USER_SETTINGS)

# Windows often starts redirected Python output with cp1252 (e.g. the GUI's
# pipe or PowerShell Tee-Object). This script prints Unicode symbols; force
# UTF-8 so output never crashes before the preview or file-generation step.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

# -------------------------
# CONFIG
# -------------------------
NS = {"g": "http://base.google.com/ns/1.0"}
FEED_URL = _configured_feed_url

# Optional diagnostic: put WooCommerce product IDs here to have the
# diagnostic block below confirm whether each one is present in the
# fetched feed and/or already in the history. Empty = nothing to check.
CHECK_IDS = []

# -------------------------
# HELPERS
# -------------------------
def parse_price_to_int(price_text: str) -> int:
    if not price_text:
        return 0
    m = re.search(r"\d+(\.\d+)?", price_text)
    return int(float(m.group(0))) if m else 0


def format_feed_value(template_key, default_template, values):
    """Render a saved feed-field template, falling back safely if malformed."""
    template = str(USER_SETTINGS.get(template_key, default_template) or
                   default_template)
    try:
        return template.format_map(values)
    except (KeyError, ValueError, IndexError):
        return default_template.format_map(values)


def format_feed_price(values):
    """Keep the default numeric price; allow a user template override."""
    template = str(USER_SETTINGS.get("facebook_feed_price_template", "{price}")
                   or "{price}")
    if template.strip() == "{price}":
        return values["price"]
    try:
        rendered = template.format_map(values).strip()
        return float(rendered) if "." in rendered else int(rendered)
    except (KeyError, ValueError, IndexError):
        return values["price"]


def parse_feed():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AlexCollectFeedBot/1.0)"}
    cache_bust_url = f"{FEED_URL}?_={int(datetime.now().timestamp())}"
    resp = requests.get(cache_bust_url, timeout=30, headers=headers)

    # --- DIAGNOSTIC: confirm we're not getting a cached/stale response ---
    print("\n--- Feed fetch diagnostics ---")
    print(f"HTTP status      : {resp.status_code}")
    print(f"CF-Cache-Status  : {resp.headers.get('CF-Cache-Status', 'not present')}")
    print(f"Age              : {resp.headers.get('Age', 'not present')}")
    print(f"Last-Modified    : {resp.headers.get('Last-Modified', 'not present')}")
    print(f"Date             : {resp.headers.get('Date', 'not present')}")
    print(f"Content-Length   : {resp.headers.get('Content-Length', len(resp.content))}")
    print(f"CF-Ray           : {resp.headers.get('CF-Ray', 'not present')}")
    print("--- End fetch diagnostics ---\n")
    # -----------------------------------------------------------------

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        debug_file = "feed_debug_response.txt"
        with open(debug_file, "wb") as f:
            f.write(resp.content)
        print("\n" + "=" * 60)
        print("❌ XML PARSE ERROR - DIAGNOSTIC INFO")
        print("=" * 60)
        print(f"HTTP status code : {resp.status_code}")
        print(f"Content-Type     : {resp.headers.get('Content-Type')}")
        print(f"Content-Length   : {resp.headers.get('Content-Length', len(resp.content))}")
        print(f"Server header    : {resp.headers.get('Server')}")
        print(f"CF-Ray header    : {resp.headers.get('CF-Ray')}  (present = Cloudflare touched this request)")
        print(f"Parse error      : {e}")
        # Show context around the failing line/column if we can determine it
        text = resp.content.decode("utf-8", errors="replace")
        lines = text.splitlines()
        err_line = getattr(e, "lineno", None)
        try:
            err_line = int(err_line)
            print(f"\n--- Lines around line {err_line} ---")
            start = max(0, err_line - 3)
            end = min(len(lines), err_line + 2)
            for i in range(start, end):
                marker = ">> " if (i + 1) == err_line else "   "
                print(f"{marker}{i+1}: {lines[i][:300]}")
        except Exception:
            pass
        print(f"\n--- First 500 characters of response ---")
        print(text[:500])
        print(f"\n--- Last 200 characters of response ---")
        print(text[-200:])
        print(f"\n📄 Full raw response saved to: {debug_file}")
        print("=" * 60 + "\n")
        raise

    items = root.findall(".//item")
    rows = []
    for it in items:
        pid = it.findtext("g:id", "", namespaces=NS)
        title = it.findtext("g:title", "", namespaces=NS)
        description = it.findtext("g:description", "", namespaces=NS)
        product_url = it.findtext("g:link", "", namespaces=NS)
        image_link = it.findtext("g:image_link", "", namespaces=NS)
        price_text = it.findtext("g:price", "0", namespaces=NS)
        price_value = parse_price_to_int(price_text)
        if not title or not product_url:
            continue
        values = {
            "id": str(pid), "title": title, "description": description,
            "product_url": product_url, "price": price_value,
            "image_link": image_link,
        }
        row = {
            "_SOURCE_TITLE": title,
            "TITLE": str(format_feed_value(
                "facebook_feed_title_template", "{title} Trading Card", values
            ))[:150],
            "PRICE": format_feed_price(values),
            "CONDITION": str(USER_SETTINGS.get(
                "facebook_feed_condition", "Used - Good") or "Used - Good"),
            "DESCRIPTION": str(format_feed_value(
                "facebook_feed_description_template",
                "Trading Card\n\nView and purchase here: {product_url}\n\n"
                "See the store listing for current payment and shipping details.",
                values)),
            "CATEGORY": str(USER_SETTINGS.get(
                "facebook_feed_category", "Antiques & Collectibles") or ""),
            "id": str(format_feed_value(
                "facebook_feed_id_template", "{id}", values)),
            "image_link": str(format_feed_value(
                "facebook_feed_image_link_template", "{image_link}", values)),
        }
        rows.append(row)
    return pd.DataFrame(rows)


HISTORY_FILE = "facebook_history.xlsx"


def load_history():
    # Preferred path: a single consolidated history file
    if os.path.exists(HISTORY_FILE):
        try:
            return pd.read_excel(HISTORY_FILE, dtype={"id": str})
        except Exception as e:
            print(f"⚠ Could not read {HISTORY_FILE}: {e}")
            return pd.DataFrame()
    # Fallback / one-time migration: no master file yet, so build it from
    # whatever old batch/delta files are still lying around.
    legacy_files = sorted(glob.glob("facebook_batch_*.xlsx") + glob.glob("facebook_delta_*.xlsx"))
    if not legacy_files:
        return pd.DataFrame()
    print(f"ℹ No {HISTORY_FILE} found - migrating "
          f"{len(legacy_files)} legacy delta/batch file(s) into history.")
    frames = []
    for f in legacy_files:
        try:
            df = pd.read_excel(f, dtype={"id": str})
            frames.append(df)
        except Exception as e:
            print(f"⚠ Skipped {f}: {e}")
    history_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not history_df.empty:
        history_df = history_df.drop_duplicates(subset="id", keep="last")
    return history_df


# -------------------------
# FIRST-RUN BOOTSTRAP
# -------------------------
PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def normalize_title(value):
    """Normalize product titles so Woo CSV names match the feed titles."""
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    value = re.sub(r"\btrading\s+card\s*$", "", value).strip()
    return " ".join(re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).split())


def match_latest_woo_batch(feed_df):
    """Return the live-feed rows named in the newest Woo import CSV.

    On a fresh install, there is no history to distinguish this batch from
    older live products. The newest generated Woo CSV is the batch marker.
    Fail closed if it is missing or any name is absent/ambiguous in the feed.
    """
    candidates = list(Path(PIPELINE_DIR).glob(
        "woocommerce_import_*.csv"))
    if not candidates:
        raise ValueError("No woocommerce_import_*.csv found in " + PIPELINE_DIR)
    source = max(candidates, key=lambda path: path.stat().st_mtime)

    with source.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "Name" not in reader.fieldnames:
            raise ValueError("Latest Woo CSV has no 'Name' column: " + source.name)
        names = [str(row.get("Name", "")).strip() for row in reader
                 if str(row.get("Name", "")).strip()]
    if not names:
        raise ValueError("Latest Woo CSV contains no product names: " + source.name)

    by_title = {}
    source_titles = (feed_df["_SOURCE_TITLE"] if "_SOURCE_TITLE" in feed_df
                     else feed_df["TITLE"])
    for index, title in source_titles.items():
        by_title.setdefault(normalize_title(title), []).append(index)

    selected = []
    problems = []
    for name in names:
        matches = by_title.get(normalize_title(name), [])
        if len(matches) != 1:
            problems.append("%s (%s match%s)" %
                            (name, len(matches), "" if len(matches) == 1 else "es"))
        elif matches[0] in selected:
            problems.append(name + " (duplicate name in Woo CSV)")
        else:
            selected.append(matches[0])
    if problems:
        raise ValueError("Could not uniquely match every row in %s to the "
                         "live feed: %s" % (source.name, "; ".join(problems)))
    return source, feed_df.loc[selected].copy()


# -------------------------
# MAIN
# -------------------------
today = datetime.today().strftime("%Y-%m-%d")
if not FEED_URL:
    raise SystemExit("Set the WooCommerce site or product feed URL in User Settings.")

new_df = parse_feed()
history_df = load_history()

new_products = pd.DataFrame()

# Ensure IDs are strings in both dataframes
new_df["id"] = new_df["id"].astype(str)
if not history_df.empty:
    history_df["id"] = history_df["id"].astype(str)

# --- DIAGNOSTIC: confirm total item counts and whether specific new
# product IDs are present in the fetched feed and/or already in history ---
print("--- Product presence diagnostics ---")
print(f"Total items in fetched feed : {len(new_df)}")
print(f"Total items in history file : {len(history_df)}")
for cid in CHECK_IDS:
    in_feed = cid in new_df["id"].values
    in_history = (not history_df.empty) and (cid in history_df["id"].values)
    print(f"  ID {cid}: in fetched feed = {in_feed}, already in history = {in_history}")
print("--- End product presence diagnostics ---\n")
# -----------------------------------------------------------------

first_run = history_df.empty
if first_run:
    print("\nNo facebook_history.xlsx found - first-run bootstrap: "
          "matching the latest Woo import CSV to identify this batch; "
          "the full live feed becomes history.")
    try:
        batch_csv, new_products = match_latest_woo_batch(new_df)
    except Exception as e:
        print("!! Safe first-run bootstrap stopped: %s" % e, file=sys.stderr)
        print("   No delta or history was written. Confirm the latest Woo CSV "
              "is in the pipeline folder and its products are live.")
        sys.exit(2)
    print("First-run batch source: %s" % batch_csv.name)
    print("Matched %d batch product(s) from the CSV; baseline will contain "
          "%d live product(s)." % (len(new_products), len(new_df)))
else:
    merged = new_df.merge(
        history_df, on="id", how="left", suffixes=("", "_old"), indicator=True
    )
    new_products = merged[merged["_merge"] == "left_only"][new_df.columns]

# -------------------------
# PREVIEW SUMMARY
# -------------------------
print("======================================")
print(f" Marketplace Feed Update Preview ({today})")
print("======================================")
print(f"🆕 New products: {len(new_products)}")
if not new_products.empty:
    print(new_products[["id", "TITLE"]].head(10).to_string(index=False))
    if len(new_products) > 10:
        print(f"... and {len(new_products)-10} more")
print("======================================\n")

# -------------------------
# CONFIRMATION PROMPT
# -------------------------
try:
    confirm = input("Press Enter to generate Excel/log files, or type anything else to cancel: ")
except EOFError:
    confirm = ""          # no keyboard attached: treat like Enter
if confirm.strip():
    print("⚠ Operation cancelled by user.")
    exit()

# -------------------------
# SAVE FILES
# -------------------------
out_new = None
if not new_products.empty:
    out_new = f"facebook_delta_{today}.xlsx"
    export_products = new_products.drop(columns=["_SOURCE_TITLE"], errors="ignore")
    export_products.to_excel(out_new, index=False)
    print(f"✅ New file saved: {out_new}")

# -------------------------
# UPDATE MASTER HISTORY FILE
# -------------------------
# A first run uses the current batch CSV only for the delta, but saves the
# ENTIRE current feed as the baseline so later runs are truly incremental.
updated_history = (new_df.copy() if first_run else
                   pd.concat([history_df, new_products], ignore_index=True))
if not updated_history.empty:
    updated_history = updated_history.drop_duplicates(subset="id", keep="last")
updated_history = updated_history.drop(columns=["_SOURCE_TITLE"], errors="ignore")
updated_history.to_excel(HISTORY_FILE, index=False)
print(f"📚 Master history updated: {HISTORY_FILE} ({len(updated_history)} total products)")

# -------------------------
# CLEAN UP OLD DELTA / BATCH FILES
# -------------------------
legacy_files = sorted(glob.glob("facebook_batch_*.xlsx") + glob.glob("facebook_delta_*.xlsx"))
# Never touch today's deltas: the one created this run, or one an
# earlier run today created (a same-day rerun finds nothing new and
# must not delete that morning's delta).
legacy_files = [f for f in legacy_files if f != out_new and today not in f]
removed = 0
for f in legacy_files:
    try:
        os.remove(f)
        removed += 1
    except Exception as e:
        print(f"⚠ Could not remove {f}: {e}")
if removed:
    print(f"🧹 Removed {removed} old delta/batch file(s) — consolidated into {HISTORY_FILE}")

# -------------------------
# RUN LOG
# -------------------------
log_file = f"facebook_runlog_{today}.txt"
with open(log_file, "w", encoding="utf-8") as f:
    f.write(f"Run {today}\n")
    f.write(f"New: {len(new_products)}\n\n")
    if not new_products.empty:
        f.write("--- New Products ---\n")
        for _, r in new_products.iterrows():
            f.write(f"{r['id']} | {r['TITLE']} | {r['PRICE']}\n")

print("✅ Run complete. See runlog + Excel files.")