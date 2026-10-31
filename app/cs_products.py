"""Make the website's product for a card that only exists on CanadianShopper.

The comparison can go both ways. A card that is on the website and not on
CanadianShopper is put *back* with the import file ``cs_listing.py`` writes.
This is the other direction: a listing that exists only on the vendor site -
one created there by hand, or left behind by an import that half finished -
becomes a product on the website.

Four things are needed, and only one of them is the website's API:

* **what it is** - the listing's title, its SKU, its stock count and its price,
  all read from the stock list the reader already returned;
* **a price**, when the reader is older than plugin 1.0.28 and does not report
  one: read off the listing's own page, and said out loud when it came from
  there;
* **pictures** - the listing's own photos, which are square because the
  storefront crops everything into a square box. They are cropped back to the
  card's own shape with ``photo_unsquare.py`` before they are uploaded, so the
  website shows a card rather than a card floating on a white square;
* **the product itself** - ``woo_create.run`` creates it as a draft, photos
  first, and never publishes a product whose photos did not land.

Nothing here invents anything: a listing with no price is created without one
and named in the notes, a listing with no picture is created without one and
named, and no category is guessed - the vendor's category is the vendor's, not
the website's.

The network is injectable (``fetch``) so the whole of this can be tested
without a site, and every failure is a sentence rather than an exception
through the window.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

from PIL import Image

import photo_replace
import photo_unsquare

#: What the shop is told when a listing page or a picture is fetched.
USER_AGENT = "Mozilla/5.0 (compatible; AlexCollect/3.02; +card listing check)"

#: How many of a listing's pictures are used: the front is the card, the second
#: is what a trading card almost always has on its other side. A third picture
#: is the vendor's business.
PHOTO_LIMIT = 2

#: A picture bigger than this is not a card photo, and is not worth downloading.
MAX_BYTES = 20 * 1024 * 1024

#: How wide a picture may be before it is made smaller on the way in.
MAX_WIDTH = 1600

#  The minus is kept so a negative price can be refused rather than read as a
#  positive one.
_PRICE = re.compile(r"(-?\d+(?:[.,]\d{1,2})?)")
_IMAGE_URL = re.compile(
    r"""(?:src|href|content|data-src)\s*=\s*["']([^"']+\.(?:jpe?g|png|webp|"""
    r"""avif|gif)(?:\?[^"']*)?)["']""", re.I)
_OG_IMAGE = re.compile(
    r"""<meta[^>]+(?:property|name)\s*=\s*["'](?:og:image(?::url)?|"""
    r"""twitter:image)["'][^>]*content\s*=\s*["']([^"']+)["']""", re.I)
_OG_IMAGE_REVERSED = re.compile(
    r"""<meta[^>]+content\s*=\s*["']([^"']+)["'][^>]*(?:property|name)\s*=\s*["']"""
    r"""(?:og:image(?::url)?|twitter:image)["']""", re.I)
_JSON_IMAGE = re.compile(
    r"""["']image["']\s*:\s*(?:"([^"]+)"|\[\s*"([^"]+)")""", re.I)
_JSON_PRICE = re.compile(
    r"""["'](?:price|lowPrice|highPrice)["']\s*:\s*["']?([\d.,]+)""", re.I)
_CURRENCY_PRICE = re.compile(
    r"""(?:CA\$|C\$|CAD\s*\$?|\$)\s*(\d[\d.,]*)""", re.I)
_TAG = re.compile(r"<[^>]+>")

#: Names a product page's own furniture carries; they are never the card.
_NOT_THE_CARD = ("logo", "icon", "favicon", "sprite", "avatar", "placeholder",
                 "banner", "payment", "badge", "flag", "stripe", "spinner")


def price_of(value):
    """A listing's price as the website wants it: ``"8.50"``, or ``""``.

    CanadianShopper writes prices with a currency and a thousands separator
    (``"CA$1,250.00"``), WooCommerce wants the number. A price that cannot be
    read is no price at all - guessing one would under- or over-charge.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    #  "CA$1,250.00" - a comma with three digits behind it is a thousands
    #  separator; a comma with one or two is a decimal point, as half of
    #  CanadianShopper's neighbours write it.
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    match = _PRICE.search(text)
    if not match:
        return ""
    try:
        number = float(match.group(1).replace(",", "."))
    except ValueError:
        return ""
    if number <= 0:
        return ""
    return "%.2f" % number


def slugify(title, limit=64):
    """A file name that says which card it is, safe on every system."""
    text = re.sub(r"[^A-Za-z0-9]+", "-", str(title or "")).strip("-").lower()
    text = re.sub(r"-{2,}", "-", text)
    if len(text) > limit:
        text = text[:limit].rstrip("-")
    return text or "card"


def images_in_html(markup, base=""):
    """The picture addresses on a listing page, best guess first.

    A page is the vendor's own HTML and this app does not get to demand a
    shape from it, so three places are looked at in the order that has been
    reliable: the page's own social/og picture (the card, on every shop that
    has one), its structured data, then the pictures in the markup itself -
    with the site's furniture (logos, icons, badges) left out.
    """
    markup = str(markup or "")
    found = []

    def add(url):
        url = str(url or "").strip().replace("\\/", "/")
        if not url or url.startswith("data:"):
            return
        url = urljoin(base, url) if base else url
        if url.startswith(("http://", "https://")) and url not in found:
            found.append(url)

    for pattern in (_OG_IMAGE, _OG_IMAGE_REVERSED):
        for match in pattern.findall(markup):
            add(match)
    for first, second in _JSON_IMAGE.findall(markup):
        add(first or second)
    for match in _IMAGE_URL.findall(markup):
        lowered = match.lower()
        if any(word in lowered for word in _NOT_THE_CARD):
            continue
        add(match)
    return found


def price_in_html(markup):
    """The price on a listing page, when the stock list did not carry one."""
    markup = str(markup or "")
    for first in _JSON_PRICE.findall(markup):
        price = price_of(first)
        if price:
            return price
    plain = _TAG.sub(" ", markup)
    for match in _CURRENCY_PRICE.findall(plain):
        price = price_of(match)
        if price:
            return price
    return ""


def read_cookie(path):
    """A saved session cookie as a header value, or ``""``.

    The file is a paste target with explanation lines in it (every line that
    starts with ``#`` is one), so blank and comment lines are dropped and what
    is left is joined - a signed-in site sends several cookies at once.
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    parts = [line.strip() for line in text.splitlines()
             if line.strip() and not line.strip().startswith("#")]
    return "; ".join(parts)


def fetch_bytes(url, cookie="", timeout=25, opener=None, limit=MAX_BYTES):
    """Download one address; returns the bytes.

    ``opener`` takes the same three arguments and is what the tests use. A
    browser's own User-Agent is sent because a shop may serve its pictures to
    anything but its pages only to a browser.
    """
    if opener is not None:
        return opener(url, cookie, timeout)
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(limit)


def fetch_text(url, cookie="", timeout=25, opener=None):
    """One page as text; an unreadable page is an empty string, not a crash."""
    try:
        data = fetch_bytes(url, cookie=cookie, timeout=timeout, opener=opener)
    except Exception:
        return ""
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def picture_urls(listing, fetch_page=None):
    """Every picture address known for one listing, best first.

    The reader's own answer is used first - it is the vendor's data. When it
    has none, the listing's page is read once and its pictures taken from
    there, which is what makes this work with a reader that reports no
    pictures at all.
    """
    urls = [url for url in (listing.get("images") or [])
            if str(url).startswith(("http://", "https://"))]
    page = ""
    if not urls and listing.get("url") and fetch_page is not None:
        page = fetch_page(listing["url"]) or ""
        urls = images_in_html(page, listing["url"])
    return urls[:PHOTO_LIMIT], page


def card_from(row, listing=None):
    """One comparison row (and the listing behind it) as a card to create."""
    row, listing = row or {}, listing or {}
    name = str(row.get("other_name") or row.get("card")
               or listing.get("name") or "").strip()
    stock = row.get("other")
    if stock is None:
        stock = listing.get("qty")
    try:
        stock = max(0, int(stock or 0))
    except (TypeError, ValueError):
        stock = 0
    return {
        "name": name,
        "sku": str(row.get("other_sku") or listing.get("sku") or "").strip(),
        "stock": stock,
        "price": price_of(listing.get("price") or row.get("price")),
        "url": str(listing.get("url") or row.get("url") or "").strip(),
        "id": row.get("other_id") or listing.get("id"),
        "images": list(listing.get("images") or []),
        "photos": [],          # file names, once the pictures are saved
        "crops": [],           # what the crop did, for the console
        "notes": [],
    }


def save_pictures(card, folder, fetch=None, fetch_page=None, limit=PHOTO_LIMIT):
    """Fetch a card's pictures, crop each back to the card, and save them.

    Returns ``{"files": [...], "notes": [...]}``; ``files`` is empty when the
    listing has no picture, which the caller reports rather than hides.
    """
    folder = Path(folder)
    result = {"files": [], "notes": []}
    fetch = fetch or fetch_bytes
    urls, page = picture_urls(card, fetch_page=fetch_page)
    if page and not card.get("price"):
        #  An older reader reports no price; the page the pictures came from
        #  carries one, and the note says where it came from.
        price = price_in_html(page)
        if price:
            card["price"] = price
            card["notes"].append("price %s read from its listing page" % price)
    if not urls:
        result["notes"].append(
            "%s: no picture address on the listing%s"
            % (card.get("name") or "a card",
               "" if card.get("url") else ", and no page address either"))
        return result
    folder.mkdir(parents=True, exist_ok=True)
    stem = slugify(card.get("name") or card.get("sku") or "card")
    for index, url in enumerate(urls[:limit]):
        try:
            data = fetch(url, "", 25)
        except Exception as exc:
            result["notes"].append("%s could not be fetched: %s" % (url, exc))
            continue
        try:
            image = Image.open(BytesIO(data))
            image.load()
        except Exception as exc:
            result["notes"].append("%s is not a picture this app can read: %s"
                                   % (url, exc))
            continue
        if image.size[0] > MAX_WIDTH:
            height = int(MAX_WIDTH * image.size[1] / float(image.size[0]))
            image = image.resize((MAX_WIDTH, max(1, height)), Image.LANCZOS)
        cropped, measure = photo_unsquare.de_square(image)
        suffix = ("-front" if index == 0 else
                  "-back" if index == 1 else "-%d" % (index + 1))
        name = _free_name(folder / ("%s%s.webp" % (stem, suffix)))
        try:
            photo_replace.save_card_image(cropped, name)
        except Exception as exc:
            result["notes"].append("%s could not be saved: %s" % (name.name, exc))
            continue
        result["files"].append({"name": name.name, "path": name, "url": url,
                                "measure": measure})
    if not result["files"]:
        result["notes"].append(
            "%s: none of its %d picture%s could be used"
            % (card.get("name") or "a card", len(urls),
               "" if len(urls) == 1 else "s"))
    return result


def _free_name(path):
    """``name.webp``, or ``name (2).webp`` when that name is already taken."""
    path = Path(path)
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name("%s (%d)%s"
                                   % (path.stem, counter, path.suffix))
        if not candidate.exists():
            return candidate
        counter += 1


def plan(cards, folder=None):
    """What creating these cards would make, in ``woo_create``'s own shape."""
    items, problems, notes = [], [], []
    for card in cards or []:
        name = str(card.get("name") or "").strip()
        if not name:
            problems.append({"card": card, "why": "the listing has no title"})
            continue
        photos = list(card.get("photos") or [])
        stock = int(card.get("stock") or 0)
        item = {
            "name": name,
            "sku": str(card.get("sku") or "").strip(),
            "published": False,
            "short": "",
            #  Deliberately empty: the vendor's description was written for
            #  the vendor's site, and copying it here would be a guess at
            #  what belongs on this one.
            "description": "",
            "price": str(card.get("price") or ""),
            "stock": stock,
            "in_stock": stock > 0,
            "categories": [],
            "tags": [],
            "images": photos,
            "attributes": [],
            "meta": {},
            "row": {},
        }
        if not item["price"]:
            notes.append("%s has no price on the listing, so the product is "
                         "created without one" % name)
        if not photos:
            notes.append("%s has no picture to upload, so the product is "
                         "created without a photo" % name)
        items.append(item)
    return {"items": items, "problems": problems, "notes": notes,
            "folder": Path(folder) if folder else None}


def describe_cards(cards, limit=12):
    """The first confirmation: what each card would become, before any work."""
    lines = []
    for card in (cards or [])[:limit]:
        line = "  %s" % (card.get("name") or "(no title)")
        if card.get("sku"):
            line += "\n      SKU %s" % card["sku"]
        line += "  |  %s  |  stock %d" % (
            "$" + card["price"] if card.get("price") else "no price",
            int(card.get("stock") or 0))
        lines.append(line)
    if cards and len(cards) > limit:
        lines.append("  ... and %d more" % (len(cards) - limit))
    return lines


def describe(plan_result, limit=12):
    """The second: what was actually gathered, photos included."""
    items = (plan_result or {}).get("items") or []
    lines = []
    for item in items[:limit]:
        line = "  %s" % item["name"]
        if item["sku"]:
            line += "  |  SKU %s" % item["sku"]
        line += "  |  %s  |  stock %d" % (
            "$" + item["price"] if item["price"] else "no price", item["stock"])
        if item["images"]:
            line += "  |  %d photo%s" % (len(item["images"]),
                                         "" if len(item["images"]) == 1 else "s")
        else:
            line += "  |  no photo"
        lines.append(line)
    if len(items) > limit:
        lines.append("  ... and %d more" % (len(items) - limit))
    return lines


def summary(plan_result, site=""):
    """One sentence saying what creating these cards would do."""
    items = (plan_result or {}).get("items") or []
    if not items:
        return "Nothing to create."
    photos = sum(1 for item in items if item["images"])
    line = "%d product%s would be created on %s as drafts" % (
        len(items), "" if len(items) == 1 else "s", site or "your website")
    if photos:
        line += ", %d with photos cropped back to the card's own shape and " \
                "uploaded first" % photos
    return line + "."


def crop_text(files):
    """One line per picture saying what the crop did, for the console."""
    lines = []
    for entry in files or []:
        measure = entry.get("measure") or {}
        if measure.get("padded"):
            lines.append("%s: %s cropped to %s"
                         % (entry.get("name"),
                            photo_unsquare.shape_text(measure.get("before")),
                            photo_unsquare.shape_text(measure.get("after"))))
        elif measure.get("why"):
            lines.append("%s: kept %s as it is - %s"
                         % (entry.get("name"),
                            photo_unsquare.shape_text(measure.get("before")),
                            measure["why"]))
    return lines
