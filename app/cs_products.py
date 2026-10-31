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

import json
import re
import urllib.error
import urllib.request
from html import unescape
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

from PIL import Image

import photo_replace
import photo_unsquare
import stock_compare

#: What the shop is told when a listing page or a picture is fetched.
USER_AGENT = "Mozilla/5.0 (compatible; AlexCollect/3.04; +card listing check)"

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

#: Keys a stock reader might use for the listing's own words and facts.
_DESCRIPTION_KEYS = ("description", "details", "body_html", "long_description",
                     "longDescription", "about", "content", "body")
_SHORT_KEYS = ("short_description", "shortDescription", "summary", "excerpt")
_TAG_KEYS = ("tags", "keywords", "keyword", "labels", "topics")
#: A reader that reports the card's own facts under these names is believed;
#: the title is only read when it reports none of them.
_FACT_KEYS = (("condition", "Condition"), ("grade", "Grade"),
              ("year", "Year"), ("set", "Set"), ("set_name", "Set"),
              ("card_number", "Card number"), ("cardNumber", "Card number"),
              ("number", "Card number"), ("player", "Player"),
              ("brand", "Brand"), ("manufacturer", "Brand"),
              ("language", "Language"), ("sport", "Sport"))

#: The ways a card's grade is written on a listing, longest first so that
#: "EX-MT" is never read as "EX" with something after it.
_GRADES = ("GEM MT", "GEM-MT", "GEM MINT", "NM-MT", "NM/MT", "VG-EX", "VG/EX",
           "EX-MT", "EX/MT", "MINT", "NM", "EX", "VG", "GD", "FR", "PR", "POOR")
_GRADE = re.compile(
    r"\b(?:%s)\b" % "|".join(re.escape(word) for word in _GRADES), re.I)

#: The makers whose name on a title is the set, not part of the player's name.
_BRANDS = ("O-Pee-Chee", "OPC", "Opeechee", "Topps", "Upper Deck", "Panini",
           "Fleer", "Score", "Donruss", "Bowman", "Parkhurst", "Pro Set",
           "Leaf", "Skybox", "Pacific", "In The Game", "ITG", "Select",
           "Collector's Choice", "Stadium Club", "SP Authentic", "Ultra")
_BRAND = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(word) for word in _BRANDS),
                    re.I)
_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})(?:\s*[-/]\s*(\d{2}))?\b")
_CARD_NUMBER = re.compile(r"#\s*([A-Za-z0-9][A-Za-z0-9-]*)")
_BLOCK_OPEN = re.compile(r"<(div|section|article|table)\b([^>]*)>", re.I)
_JSON_SCRIPT = re.compile(
    r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.I | re.S)
_META = re.compile(r"<meta\b[^>]*>", re.I)
_META_NAME = re.compile(
    r"""(?:property|name)\s*=\s*["']([^"']+)["']""", re.I)
_META_CONTENT = re.compile(r"""content\s*=\s*["']([^"']*)["']""", re.I)
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
_BREAK = re.compile(r"<\s*(?:br|/p|/div|/li|/h[1-6])\b[^>]*>", re.I)

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


def text_of(markup, limit=4000):
    """The words of an HTML block: tags out, entities in, lines kept.

    The vendor's markup is theirs, not this app's: scripts, styles and tags are
    thrown away rather than copied into a product description, and what is left
    is plain text with one line per paragraph. That is what gets wrapped back
    into simple ``<p>`` tags on the website, so nothing the vendor embedded -
    an iframe, a tracking pixel, a script - travels with the words.
    """
    text = str(markup or "")
    text = _SCRIPT_STYLE.sub(" ", text)
    text = _BREAK.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = unescape(text)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    joined = "\n".join(lines)
    if limit and len(joined) > limit:
        joined = joined[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return joined


def paragraphs(text, limit=12):
    """Plain lines as the simplest HTML a WooCommerce description can hold."""
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    body = "\n".join("<p>%s</p>" % _escape(line) for line in lines[:limit])
    return body


def _escape(text):
    return (str(text or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _sentence(text, limit=220):
    """The first sentence of a description, for the short description box."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
    first = cut[0] if cut else text
    if len(first) < 24:
        first = text
    return first[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") + "\u2026"


def _values(value):
    """A reader's or a page's list of keywords, as a clean list of strings."""
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        value = value.get("name") or value.get("value") or ""
    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            parts.extend(_values(item))
        return parts
    text = str(value)
    parts = re.split(r"[,;|]", text)
    found = []
    for part in parts:
        part = part.strip().strip("#").strip()
        if part and part.lower() not in [item.lower() for item in found]:
            found.append(part)
    return found


def _categories(value):
    """A structured-data category path (``Sports > Hockey > Cards``)."""
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            parts.extend(_categories(item))
        return parts
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[>/]", text) if part.strip()]


def _json_objects(markup):
    """Every dictionary in the page's structured data."""
    found = []
    for block in _JSON_SCRIPT.findall(str(markup or "")):
        try:
            #  ``strict=False``: a shop may put a raw newline inside a JSON
            #  string, and that block is still the page's structured data.
            data = json.loads(block.strip(), strict=False)
        except (ValueError, TypeError):
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                found.append(item)
                for key in ("@graph", "itemListElement", "mainEntity",
                            "hasVariant"):
                    if isinstance(item.get(key), (list, tuple, dict)):
                        stack.append(item[key])
            elif isinstance(item, (list, tuple)):
                stack.extend(item)
    return found


def _meta_tags(markup):
    """The page's ``<meta>`` tags as ``{name: content}``, the first one wins."""
    found = {}
    for tag in _META.findall(str(markup or "")):
        name = _META_NAME.search(tag)
        content = _META_CONTENT.search(tag)
        if not name or not content:
            continue
        found.setdefault(name.group(1).strip().lower(), unescape(content.group(1)))
    return found


def _block_text(markup, hints=("description", "product-details", "details")):
    """The longest block on the page whose class or id says "description".

    A shop that publishes no structured data still writes the card's
    description in a block it names. This reads that block whole - nested
    tags included - and never guesses at a block it cannot name.
    """
    markup = str(markup or "")
    best = ""
    for match in _BLOCK_OPEN.finditer(markup):
        tag, attributes = match.group(1).lower(), match.group(2).lower()
        if not any(hint in attributes for hint in hints):
            continue
        depth, index = 1, match.end()
        pattern = re.compile(r"<(/?)%s\b[^>]*>" % re.escape(tag), re.I)
        while depth and index < len(markup):
            step = pattern.search(markup, index)
            if not step:
                break
            depth += -1 if step.group(1) else 1
            index = step.end()
        inner = markup[match.end():step.start() if step else len(markup)]
        text = text_of(inner)
        if len(text) > len(best):
            best = text
    return best


def _fact_label(key):
    """The nice name of a fact a reader or a page reports."""
    shape = "".join(char for char in str(key).lower() if char.isalnum())
    for known, label in _FACT_KEYS:
        if "".join(char for char in known.lower() if char.isalnum()) == shape:
            return label
    return str(key or "").strip().title()


def facts_from_title(title):
    """What a listing's title states outright: the year, set, number, grade.

    Only what is written there is read, and nothing is guessed at: a title
    with no brand in it gets no set, and no player's name is cut out of a title
    whose maker is unknown - a wrong player is worse than no player.
    """
    title = str(title or "")
    facts = {}
    year = _YEAR.search(title)
    if year:
        value = year.group(1)
        if year.group(2):
            value += "-" + year.group(2)
        facts["Year"] = value
    brand = _BRAND.search(title)
    if brand:
        facts["Set"] = brand.group(0)
    number = _CARD_NUMBER.search(title)
    if number:
        facts["Card number"] = number.group(1)
    grade = _GRADE.search(title)
    if grade:
        facts["Condition"] = grade.group(0).upper()
    if brand:
        rest = title
        for value in (year.group(0) if year else "", brand.group(0),
                      number.group(0) if number else "",
                      grade.group(0) if grade else ""):
            if value:
                rest = rest.replace(value, " ", 1)
        rest = re.sub(r"[|,()\[\]{}]+", " ", rest)
        rest = re.sub(r"\s{2,}", " ", rest).strip(" -/")
        if rest and not any(char.isdigit() for char in rest):
            words = rest.split()
            if 1 <= len(words) <= 5:
                facts["Player"] = rest
    return facts


def details_from_listing(listing, row=None):
    """What a reader already told us about the listing, without a page read."""
    listing, row = listing or {}, row or {}
    sources = (listing, row)

    def first(keys):
        for source in sources:
            for key in keys:
                value = source.get(key)
                if value not in (None, ""):
                    return value
        return ""

    description = text_of(first(_DESCRIPTION_KEYS))
    short = text_of(first(_SHORT_KEYS), limit=400)
    tags = _values(first(_TAG_KEYS))
    facts = {}
    for source in sources:
        normalized = {}
        for key, value in source.items():
            shape = "".join(char for char in str(key).lower() if char.isalnum())
            normalized.setdefault(shape, value)
        for key, label in _FACT_KEYS:
            shape = "".join(char for char in key.lower() if char.isalnum())
            value = normalized.get(shape)
            if isinstance(value, (str, int, float)) and str(value).strip():
                facts.setdefault(label, str(value).strip())
    return {"description": description, "short": short, "tags": tags,
            "facts": facts}


def details_in_html(markup, base=""):
    """The listing's description, keywords and card facts, off its own page."""
    markup = str(markup or "")
    description, keywords, facts = "", [], {}
    for item in _json_objects(markup):
        kinds = item.get("@type")
        kinds = kinds if isinstance(kinds, (list, tuple)) else [kinds]
        if not any(str(kind).lower() == "product" for kind in kinds if kind):
            continue
        if not description:
            description = text_of(item.get("description"))
        keywords += _values(item.get("keywords"))
        keywords += _categories(item.get("category"))
        brand = item.get("brand") or item.get("manufacturer")
        if isinstance(brand, dict):
            brand = brand.get("name")
        if brand:
            facts.setdefault("Brand", str(brand).strip())
        for prop in item.get("additionalProperty") or []:
            if not isinstance(prop, dict):
                continue
            label = _fact_label(prop.get("name") or "")
            value = prop.get("value")
            if label and value not in (None, ""):
                facts.setdefault(label, str(value).strip())
    meta = _meta_tags(markup)
    if not description:
        description = text_of(meta.get("og:description")
                              or meta.get("description") or "")
    keywords += _values(meta.get("keywords"))
    if not facts.get("Brand"):
        brand = meta.get("product:brand") or meta.get("og:brand")
        if brand:
            facts["Brand"] = str(brand).strip()
    if not description:
        description = _block_text(markup)
    return {"description": description, "keywords": keywords, "facts": facts}


def _attributes(facts):
    """The facts as WooCommerce custom attributes, in a card's own order."""
    order = ("Year", "Set", "Player", "Card number", "Condition", "Grade",
             "Brand", "Sport", "Language")
    names = [name for name in order if name in facts]
    names += [name for name in facts if name not in names]
    return [{"name": name, "options": [str(facts[name])], "visible": True,
             "variation": False}
            for name in names if str(facts[name]).strip()]


def details(listing=None, row=None, page=""):
    """Everything that should be copied onto the product, and where it came from.

    A reader that reports the listing's description and keywords is believed
    and no page is needed. Otherwise the listing's own page is read once -
    which is also where a card's back picture lives - and what it states is
    copied. The card's title is the last resort, and only for facts that are
    written in it (the year, the maker, the card number, the grade).
    """
    listing, row = listing or {}, row or {}
    known = details_from_listing(listing, row)
    page_found = details_in_html(page) if page else {"description": "",
                                                     "keywords": [],
                                                     "facts": {}}
    description = known["description"] or page_found["description"]
    facts = {}
    for source in (known["facts"], page_found["facts"],
                   facts_from_title(row.get("other_name") or row.get("card")
                                    or listing.get("name") or "")):
        for name, value in source.items():
            facts.setdefault(name, value)
    tags = []
    seen = set()
    for tag in (known["tags"] + page_found["keywords"]
                + [facts.get("Year") or "", facts.get("Set") or "",
                   facts.get("Player") or "",
                   ("#" + facts["Card number"]) if facts.get("Card number") else "",
                   facts.get("Condition") or ""]):
        tag = str(tag or "").strip()
        if not tag or tag.lower() in seen:
            continue
        seen.add(tag.lower())
        tags.append(tag)
    short = known["short"] or (_sentence(description)
                              if len(description) > 240 else "")
    notes = []
    if not description:
        notes.append("no description on the listing, so the product's "
                     "description is left empty")
    return {"description": paragraphs(description) if description else "",
            "short": short, "tags": tags, "attributes": _attributes(facts),
            "facts": facts, "plain": description, "notes": notes}


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


def readable_urls(values):
    """The web addresses in a reader's picture list, in the order given.

    A reader is free to send a dict (``{"src": ...}``), a local path or an
    empty string; only absolute web addresses can be downloaded, and the order
    is the vendor's own - the primary picture first - so it is never sorted.
    """
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        values = [values] if values else []
    urls = []
    for value in values:
        if isinstance(value, dict):
            value = (value.get("src") or value.get("url")
                     or value.get("href") or "")
        url = str(value or "").strip()
        if url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    return urls


def picture_urls(listing, fetch_page=None, limit=PHOTO_LIMIT, want_page=False):
    """Every picture address known for one listing, best first.

    The reader's own answer is used first - it is the vendor's data, and it is
    already in the order the vendor shows them (its primary picture first,
    then the gallery in the vendor's own order), so it is never re-sorted.

    The listing's page is read once when the reader did not give enough
    pictures - a single photo cannot show the back of a card - and when the
    caller wants the description and details off it (``want_page``). What the
    page adds goes after the reader's own pictures, so the reader's primary
    photo is still the front.
    """
    urls = readable_urls(listing.get("images"))
    if not urls:
        #  A reader that spells the picture key another way still gets read,
        #  through the same list of spellings the comparison uses.
        urls = stock_compare.listing_pictures(listing)
    page = ""
    if (listing.get("url") and fetch_page is not None
            and (want_page or len(urls) < limit)):
        page = fetch_page(listing["url"]) or ""
        for url in images_in_html(page, listing["url"]):
            if url not in urls:
                urls.append(url)
    return urls[:limit], page


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
    detail = details(listing, dict(row, card=name))
    return {
        "name": name,
        "sku": str(row.get("other_sku") or listing.get("sku") or "").strip(),
        "stock": stock,
        "price": price_of(listing.get("price") or row.get("price")),
        "url": str(listing.get("url") or row.get("url") or "").strip(),
        "id": row.get("other_id") or listing.get("id"),
        "images": (readable_urls(listing.get("images"))
                   or stock_compare.listing_pictures(listing)
                   or stock_compare.listing_pictures(row)),
        "description": detail["description"],
        "short": detail["short"],
        "tags": detail["tags"],
        "attributes": detail["attributes"],
        "facts": detail["facts"],
        "page_read": False,    # the listing's page, once it has been read
        "photos": [],          # file names, once the pictures are saved
        "backs": [],           # the gallery: everything after the front
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
    #  The reader may have given both pictures and the description; only what
    #  is still missing is worth a page read, and a single picture always is
    #  (a card has a back, and the reader reported one picture).
    want_page = not (card.get("description") and card.get("tags"))
    urls, page = picture_urls(card, fetch_page=fetch_page, limit=limit,
                              want_page=want_page)
    if page:
        card["page_read"] = True
        if not card.get("price"):
            #  An older reader reports no price; the page the pictures came
            #  from carries one, and the note says where it came from.
            price = price_in_html(page)
            if price:
                card["price"] = price
                card["notes"].append("price %s read from its listing page"
                                     % price)
        #  The listing's own description, keywords and card facts. What the
        #  reader already reported is kept; the page fills the gaps.
        found = details(card, page=page)
        if not card.get("description") and found["description"]:
            card["description"] = found["description"]
            card["notes"].append("description copied from its listing")
        if not card.get("short") and found["short"]:
            card["short"] = found["short"]
        for tag in found["tags"]:
            if tag.lower() not in [known.lower() for known in card["tags"]]:
                card["tags"].append(tag)
        known_names = [attr.get("name") for attr in card.get("attributes") or []]
        for attr in found["attributes"]:
            if attr.get("name") not in known_names:
                card.setdefault("attributes", []).append(attr)
        card["facts"] = dict(found["facts"], **(card.get("facts") or {}))
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
        #  Named by the pictures that were really saved, not by the address
        #  that was tried: a front that will not download must not leave the
        #  back as the product's only picture under a file called "back".
        kept = len(result["files"])
        suffix = ("-front" if kept == 0 else
                  "-back" if kept == 1 else "-%d" % (kept + 1))
        name = _free_name(folder / ("%s%s.webp" % (stem, suffix)))
        try:
            photo_replace.save_card_image(cropped, name)
        except Exception as exc:
            result["notes"].append("%s could not be saved: %s" % (name.name, exc))
            continue
        result["files"].append({"name": name.name, "path": name, "url": url,
                                "measure": measure})
        if kept == 0:
            card["photos"] = [name.name]
        else:
            card.setdefault("backs", []).append(name.name)
    if not result["files"]:
        result["notes"].append(
            "%s: none of its %d picture%s could be used"
            % (card.get("name") or "a card", len(urls),
               "" if len(urls) == 1 else "s"))
    return result


def apply_pictures(card, saved):
    """File what ``save_pictures`` returned onto the card.

    The first picture is the product's main image and the rest are the
    gallery - the back of a card, almost always - so they are kept apart here
    rather than being one list the website has to guess at.
    """
    files = (saved or {}).get("files") or []
    names = [entry["name"] for entry in files]
    card["photos"] = names[:1]
    card["backs"] = names[1:]
    card["crops"] = files
    for note in (saved or {}).get("notes") or []:
        card.setdefault("notes", []).append(note)
    return card


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
        photos = [entry for entry in (card.get("photos") or []) if entry]
        backs = [entry for entry in (card.get("backs") or []) if entry]
        if not backs:
            #  A card built by hand with every picture in one list still gets
            #  a front and a gallery, in the order it was given.
            backs, photos = photos[1:], photos[:1]
        stock = int(card.get("stock") or 0)
        item = {
            "name": name,
            "sku": str(card.get("sku") or "").strip(),
            "published": False,
            "short": str(card.get("short") or ""),
            #  The listing's own words, copied: it is what the vendor wrote
            #  about this card, and the website's description is empty
            #  otherwise. Nothing is invented here.
            "description": str(card.get("description") or ""),
            "price": str(card.get("price") or ""),
            "stock": stock,
            "in_stock": stock > 0,
            "categories": [],
            "tags": [tag for tag in (card.get("tags") or []) if tag],
            "images": photos + backs,
            "gallery": backs,
            "attributes": [attr for attr in (card.get("attributes") or [])
                           if attr],
            "meta": {},
            "row": {},
        }
        if not item["price"]:
            notes.append("%s has no price on the listing, so the product is "
                         "created without one" % name)
        if not photos:
            notes.append("%s has no picture to upload, so the product is "
                         "created without a photo" % name)
        elif not backs:
            notes.append("%s has no second picture, so the product has a "
                         "main photo and an empty gallery" % name)
        if not item["description"]:
            notes.append("%s has no description on the listing, so its "
                         "description is left empty" % name)
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
            if item.get("gallery"):
                line += " (%d in the gallery)" % len(item["gallery"])
        else:
            line += "  |  no photo"
        if item.get("description"):
            line += "  |  description"
        if item.get("tags"):
            line += "  |  %d tag%s" % (len(item["tags"]),
                                       "" if len(item["tags"]) == 1 else "s")
        if item.get("attributes"):
            line += "  |  %d detail%s" % (
                len(item["attributes"]),
                "" if len(item["attributes"]) == 1 else "s")
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
