"""Shared, non-secret user configuration for the GUI and command-line tools.

WooCommerce REST credentials remain in the git-ignored woo-keys.txt file.
This module reads the GUI settings file and provides URL/path defaults to the
standalone tools as well as the desktop interface.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote_plus, urlparse

APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "gui-settings.json"
WOO_KEYS_FILE = APP_DIR / "woo-keys.txt"
#: Kept as a constant so the Windows branch can be tested from Linux.
IS_WINDOWS = sys.platform.startswith("win")
#: This module is copied around on its own by the tools, so it carries its
#: own copy of the no-console flag instead of importing process_utils.
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _no_window():
    """Popen keyword arguments that hide a child console window."""
    return {"creationflags": _CREATE_NO_WINDOW} if IS_WINDOWS else {}


def default_scan_dir() -> str:
    """A portable default; users can choose their scanner's real folder."""
    return str(Path.home() / "Pictures" / "Scan")


def restrict_file_permissions(path: Path) -> bool:
    """Make a secrets file readable only by the current user.

    woo-keys.txt holds API credentials. It is already git-ignored and never
    leaves the machine, but by default any account on the PC can read it.
    On Windows the inherited permissions are removed and only the current
    user is granted access; elsewhere the file becomes mode 600.

    Returns True when the restriction was applied. A failure is not fatal -
    the caller keeps working with the file as it is.
    """
    path = Path(path)
    if not path.exists():
        return False
    try:
        if IS_WINDOWS:
            user = os.environ.get("USERNAME", "").strip()
            if not user:
                return False
            result = subprocess.run(
                ["icacls", str(path), "/inheritance:r",
                 "/grant:r", user + ":F"],
                capture_output=True, text=True, **_no_window())
            return result.returncode == 0
        os.chmod(path, 0o600)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def read_woo_keys_site_url(path: Path = WOO_KEYS_FILE) -> str:
    """Read the legacy first-line site URL, if a Woo keys file already exists."""
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            value = line.strip()
            if value and not value.startswith("#") and value.lower().startswith(
                    ("http://", "https://")):
                return value.rstrip("/")
    except (OSError, UnicodeError):
        pass
    return ""


def load_user_settings(path: Path = SETTINGS_FILE) -> dict:
    """Load saved settings with portable defaults and legacy URL migration."""
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            saved = {}
    except (OSError, ValueError, UnicodeError):
        saved = {}
    site_url = saved.get("woo_site_url")
    if site_url is None:
        site_url = read_woo_keys_site_url(path.parent / "woo-keys.txt")
    return {
        "startup_mode": "menu",
        "seen_wizard": False,
        "pipeline_dir": "",
        "scan_dir": default_scan_dir(),
        "ai_agent_url": "",
        "browser_name": "",
        "store_name": "",
        "currency_prefix": "C$",
        "currency_name": "Canadian dollars",
        "description_min_words": 400,
        "tag_count": 8,
        "listing_context": "When relevant, identify Canadian O-Pee-Chee bilingual backs or puzzle backs.",
        "custom_ai_commands": [],
        "woo_site_url": str(site_url or "").rstrip("/"),
        "woo_feed_url": "",
        "woo_feed_refresh_url": "",
        "canadianshopper_store_url": "",
        "canadianshopper_category": "Antiques & Collectibles",
        "canadianshopper_ship_from_province": "ON",
        "canadianshopper_shipping_flat": "4.00",
        "canadianshopper_free_shipping": False,
        "canadianshopper_handling_days": 2,
        "canadianshopper_transit_days": 5,
        "facebook_feed_title_template": "{title} Trading Card",
        "facebook_feed_price_template": "{price}",
        "facebook_feed_condition": "Used - Good",
        "facebook_feed_description_template": (
            "Trading Card\\n\\nView and purchase here: {product_url}\\n\\n"
            "See the store listing for current payment and shipping details."),
        "facebook_feed_category": "Antiques & Collectibles",
        "facebook_feed_id_template": "{id}",
        "facebook_feed_image_link_template": "{image_link}",
        "ebay_selling_url": "https://www.ebay.ca/sh/lst/active",
        "ebay_quicklist_enabled": True,
        "ebay_template_football_url": "https://www.ebay.ca/lstng?mode=AddItem&templateId=6755372012&radixTrackingId=e5f71b04-6dd5-4e2f-853e-37d1af3d979b",
        "ebay_template_baseball_url": "https://www.ebay.ca/lstng?mode=AddItem&templateId=6683628012&radixTrackingId=e5f71b04-6dd5-4e2f-853e-37d1af3d979b",
        "ebay_template_hockey_url": "https://www.ebay.ca/lstng?mode=AddItem&templateId=6683629012&radixTrackingId=e5f71b04-6dd5-4e2f-853e-37d1af3d979b",
        "ebay_template_basketball_url": "",
        "ebay_template_default_url": "https://www.ebay.ca/lstng?mode=AddItem&templateId=6683629012&radixTrackingId=e5f71b04-6dd5-4e2f-853e-37d1af3d979b",
        "ebay_image_base_url": "",
        "ebay_default_condition": "Mint",
        "ebay_default_year": "Unknown",
        "ebay_default_manufacturer": "Unknown",
        "ebay_default_card_number": "N/A",
        "ebay_default_player": "Unknown",
        "ebay_default_set": "Vintage",
        "ebay_default_grade": "",
        "ebay_default_autographed": "No",
        "ebay_default_description": "Vintage trading card from the original manufacturer.",
        "facebook_selling_url": "https://www.facebook.com/marketplace/you/selling",
        **saved,
    }


def save_user_settings(settings: dict, path: Path = SETTINGS_FILE) -> bool:
    """Persist user preferences as UTF-8 JSON without secrets."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        return True
    except (OSError, TypeError, ValueError):
        return False


def normalize_web_url(value: str) -> str:
    """Normalize a user-entered HTTP(S) URL; return empty for invalid input."""
    value = (value or "").strip()
    if not value:
        return ""
    if "://" in value and not value.lower().startswith(("http://", "https://")):
        return ""
    if not value.lower().startswith(("http://", "https://")):
        value = "https://" + value
    try:
        parsed = urlparse(value)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            return ""
        return value.rstrip("/")
    except ValueError:
        return ""


def site_url(settings: dict | None = None) -> str:
    settings = settings if settings is not None else load_user_settings()
    return normalize_web_url(settings.get("woo_site_url", ""))


def site_admin_url(path: str, settings: dict | None = None) -> str:
    base = site_url(settings)
    if not base:
        return ""
    return base + "/" + path.lstrip("/")


PLACEHOLDER_KEY_PREFIXES = ("ck_replace", "cs_replace")


def read_woo_credentials(path: Path = WOO_KEYS_FILE) -> tuple[str, str, str]:
    """Read ``(site, consumer key, consumer secret)`` from the private file.

    The file is one value per line: the site URL, then the read-only key, then
    the secret, with ``#`` comments ignored. The shipped example's placeholder
    values are treated as missing so an untouched template never looks like a
    working key.
    """
    values: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                values.append(value)
    except (OSError, UnicodeError):
        return "", "", ""

    site = ""
    rest: list[str] = []
    for value in values:
        if not site and value.lower().startswith(("http://", "https://")):
            site = value.rstrip("/")
        elif not value.lower().startswith(("http://", "https://")):
            rest.append(value)
    key, secret = (rest + ["", ""])[:2]
    if key.lower().startswith(PLACEHOLDER_KEY_PREFIXES):
        key = ""
    if secret.lower().startswith(PLACEHOLDER_KEY_PREFIXES):
        secret = ""
    return site, key, secret


def has_woo_credentials(path: Path = WOO_KEYS_FILE) -> bool:
    """True when a usable site + read-only key pair is already saved."""
    site, key, secret = read_woo_credentials(path)
    return bool(site and key and secret)


def product_search_url(term: str, settings: dict | None = None) -> str:
    """The product list filtered by a typed term - the no-API-keys lookup."""
    base = site_admin_url("wp-admin/edit.php", settings)
    if not base or not (term or "").strip():
        return ""
    return base + "?post_type=product&s=" + quote_plus(term.strip())


def product_edit_url(product_id, settings: dict | None = None) -> str:
    """The dashboard page that edits one product, when its ID is known."""
    base = site_admin_url("wp-admin/post.php", settings)
    pid = str(product_id or "").strip()
    if not base or not pid:
        return ""
    return base + "?post=" + quote_plus(pid) + "&action=edit"


def marketplace_seller_urls(settings: dict | None = None) -> list:
    """The saved seller pages for the other marketplaces, in a stable order."""
    settings = settings if settings is not None else load_user_settings()
    urls = []
    for name in ("canadianshopper_store_url", "ebay_selling_url",
                 "facebook_selling_url"):
        url = normalize_web_url(settings.get(name, ""))
        if url and url not in urls:
            urls.append(url)
    return urls


def feed_urls(settings: dict | None = None) -> tuple[str, str]:
    """Return (refresh URL, product feed URL), honoring user overrides."""
    settings = settings if settings is not None else load_user_settings()
    base = site_url(settings)
    feed = normalize_web_url(settings.get("woo_feed_url", ""))
    refresh = normalize_web_url(settings.get("woo_feed_refresh_url", ""))
    if not feed and base:
        feed = base + "/feed/facebook.xml"
    if not refresh and base:
        refresh = base + "/?force_facebook_feed=1"
    return refresh, feed


def sync_site_url_to_woo_keys(site_url_value: str,
                              path: Path = WOO_KEYS_FILE) -> bool:
    """Keep the URL in a legacy Woo keys file aligned, preserving its secrets.

    Does not create a credentials file; it only updates one that already exists.
    Returns True if an existing file was updated.
    """
    site = normalize_web_url(site_url_value)
    if not site or not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return False
    for i, line in enumerate(lines):
        if line.strip().lower().startswith(("http://", "https://")):
            lines[i] = site
            break
    else:
        lines.insert(0, site)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    restrict_file_permissions(path)
    return True
