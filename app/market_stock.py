"""Reading a marketplace page with the session you are already signed in to.

eBay and Facebook do not publish an API for "what am I selling, and how many
have I got". The only honest way to read those two is the page itself, fetched
with the session the seller already has - so the app needs a pasted cookie and
a reader for whatever the page actually returns.

The reader is the part that cannot be guessed: a saved page from a signed-in
account shows the real markup, and anything written without it is fiction that
fails on the first real run. So this module holds everything that does not
depend on the markup:

  * reading the private cookie file (a whole Cookie header, a single name=value
    pair, or several lines of them);
  * one GET with those headers, on a normal browser's user agent;
  * telling a real page from a login wall, which is what an expired cookie
    looks like - and the difference between "you are not signed in" and
    "nothing is listed" is the difference between a fix and a panic;
  * saving the page so it can be inspected and matched against.

No Tk, no writes to a site, and the request is injected so this can be tested
without a network or an account.
"""

import html
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

#  One row per marketplace: the private file the cookie goes in, and the page
#  a checked copy is written to. Both live beside the app, never in the repo.
SITES = {
    "ebay": {"label": "eBay",
             "cookie": "ebay-cookie.txt",
             "page": "ebay-active.html"},
    "facebook": {"label": "Facebook",
                 "cookie": "fb-cookie.txt",
                 "page": "fb-selling.html"},
}

#  An HTTP header is latin-1 by definition. A cookie copied out of a page (or
#  out of a chat window) can carry a tick, a curly quote or a non-breaking
#  space - and the request then dies with "latin-1 codec can't encode", which
#  says nothing about the file that needs fixing.
_COOKIE_SAFE = "".join(chr(c) for c in range(0x20, 0x7f))


def clean_header_value(value):
    """A string a browser could actually put in a header: printable ASCII."""
    text = str(value or "").replace("\r", "").replace("\n", "")
    return "".join(ch for ch in text if ch in _COOKIE_SAFE)


def dropped_characters(value):
    """The characters in ``value`` that no header can carry, without repeats."""
    text = str(value or "").replace("\r", "").replace("\n", "")
    out = []
    for ch in text:
        if ch not in _COOKIE_SAFE and ch not in out:
            out.append(ch)
    return out


#  Sites answer a browser; they often refuse a bare urllib request outright.
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-CA,en;q=0.9",
}

#  What a signed-out answer looks like. These are page markers, not guesses:
#  every one of them appears on a login wall and on no listing page.
_LOGIN_MARKERS = (
    "log in to facebook",
    "log into facebook",
    "you must log in to continue",
    "please sign in",
    "sign in or register",
    "signin.ebay",
    "login.ebay",
    "checkpoint/challenge",
    "/login?",
    "not you?",
)

TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")

#  eBay's Seller Hub renders one <tr> per listing in this shape:
#    <tr data-id="389440929928" ... class="grid-row">
#      ... <td class="shui-dt-column__title ..."> <a ...>TITLE</a>
#      ... <td class="shui-dt-column__listingSKU ..."><span>SKU</span>
#      ... <td class="shui-dt-column__availableQuantity ..."><span>3</span>
#  Every one of the 200 rows on a saved page has a title and a quantity; the
#  SKU is empty unless the seller uses custom labels. Read from the saved page
#  itself, not from guesses about it.
_EBAY_ROW = re.compile(r'<tr\s+data-id="(\d+)"[^>]*class="[^"]*grid-row', re.I)
_EBAY_PER_PAGE = 200


class MarketError(Exception):
    """A page could not be read, with a sentence saying why.

    ``kind`` separates the two things that go wrong here, because they deserve
    different words on screen: ``session`` means the site answered, but not as
    a signed-in seller - an expired cookie, which the person can fix in a
    minute - and anything else is a real failure.
    """

    def __init__(self, message, hint="", kind=""):
        super().__init__(message)
        self.message = str(message)
        self.hint = str(hint or "")
        self.kind = str(kind or "")


def _cell(row, column):
    """The text of one table cell, by its eBay column name."""
    match = re.search(r'<td class="[^"]*shui-dt-column__%s[^"]*"[^>]*>'
                      r'(.*?)(?=<td class=|</tr>)' % column, row, re.S | re.I)
    if not match:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", match.group(1)))
    return re.sub(r"\s+", " ", text).strip()


def parse_ebay_listings(text):
    """Every listing on a saved eBay Seller Hub active-listings page.

    A row without a title is skipped rather than guessed at, and a row whose
    quantity is not a number is skipped too: a listing the reader cannot count
    must not turn into a comparison that says "0".
    """
    text = str(text or "")
    items = []
    for match in _EBAY_ROW.finditer(text):
        start = match.start()
        end = text.find("</tr>", start)
        #  The closing tag is kept: it is what tells the last cell in the row
        #  where it ends, and the last cell of a row is usually the quantity.
        row = text[start:end + 5 if end != -1 else len(text)]
        title = re.search(r'<div class="column-title__text">\s*<a[^>]*>(.*?)</a>',
                          row, re.S | re.I)
        if not title:
            continue
        name = html.unescape(re.sub(r"<[^>]+>", "", title.group(1)))
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            continue
        quantity = _cell(row, "availableQuantity")
        if not re.fullmatch(r"\d+", quantity or ""):
            continue
        items.append({"id": match.group(1), "name": name,
                      "sku": _cell(row, "listingSKU"), "qty": int(quantity)})
    return items


#  Facebook renders each listing as plain text in this order, with the title
#  on the line above the price and the state on the line below it:
#    1973-74 O-Pee-Chee Walt Tkaczuk #25 ... Trading Card
#    CA$8
#    Active
#    ·  Listed on 10/25 ...
#  The class names are machine-generated and change without notice, so the
#  page's own words are what the reader reads.
_PRICE = re.compile(r"^(?:CA|US|C|A|\u00a3|\u20ac)?\s?\$\s?\d[\d,]*(?:\.\d{1,2})?$")
_FB_STATES = {"active": ("Active", 1),
              "pending": ("Pending", 1),
              "sold": ("Sold", 0),
              "out of stock": ("Sold", 0)}


def _page_lines(text):
    """The page as visible lines, the way a person reads it."""
    stripped = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ",
                      str(text or ""))
    stripped = html.unescape(re.sub(r"<[^>]+>", "\n", stripped))
    return [line.strip() for line in stripped.splitlines() if line.strip()]


_TITLE_HINT = re.compile(r"#\s*\d+")


def _looks_like_a_listing_title(line):
    """Whether a line could be a listing's title rather than page furniture.

    A price followed by a state word is a card; the same two lines appear in
    Facebook's own status filter and in promo panels, where the line above the
    price is a heading like "Your listings". Requiring a card number or a
    real length keeps those out - and a title that has neither is better left
    unlisted than reported as the wrong card.
    """
    line = str(line or "").strip()
    return bool(_TITLE_HINT.search(line)) or len(line) >= 25


def _title_before(lines, index):
    """The listing's title, which sits on the line above its price.

    A long title can land on two lines when the page wraps it, so a line that
    is too short to be a title is joined with the one above it - but only when
    the result looks like a title and the fragment itself is short enough to be
    a wrap rather than a separate row.
    """
    line = lines[index - 1]
    if _looks_like_a_listing_title(line):
        return line
    if index >= 2 and len(line) < 40:
        joined = "%s %s" % (lines[index - 2], line)
        if _looks_like_a_listing_title(joined):
            return joined
    return ""


def parse_facebook_listings(text):
    """Every listing on a saved Facebook Marketplace selling page.

    Facebook has no quantity: a listing is one item, so an Active or Pending
    listing counts as 1 and a Sold one as 0. Drafts are not on the site yet and
    are left out rather than compared as if they were.
    """
    lines = _page_lines(text)
    items = []
    for index, line in enumerate(lines):
        if not _PRICE.match(line) or index == 0 or index + 1 >= len(lines):
            continue
        state = _FB_STATES.get(lines[index + 1].strip().lower())
        if not state:
            continue
        name = _title_before(lines, index)
        if not name:
            continue
        status, qty = state
        if status == "Draft":
            continue
        items.append({"name": name, "price": line,
                      "status": status, "qty": qty, "sku": ""})
    return items


def parse_listings(site_id, text):
    """The listings on a saved page for one site, in one shape."""
    if site_id == "ebay":
        return parse_ebay_listings(text)
    if site_id == "facebook":
        return parse_facebook_listings(text)
    raise MarketError("Unknown marketplace: %s" % site_id,
                      "Expected one of: %s." % ", ".join(sorted(SITES)))


def page_url(url, offset):
    """The same address with eBay's offset set, so page two can be asked for."""
    parts = urllib.parse.urlsplit(url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query)
             if k.lower() != "offset"]
    if offset:
        query.append(("offset", str(offset)))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path,
                                    urllib.parse.urlencode(query),
                                    parts.fragment))


def read_ebay(fetch_page, url, cookie, max_pages=10):
    """Every page of active listings, through an injected page fetcher.

    ``fetch_page(url, cookie)`` returns ``(status, text)``. Pages are followed
    until one comes back short, empty or identical to the last - never by
    counting to a fixed total, because the total is the site's business.
    """
    items, pages, text = [], 0, ""
    seen = set()
    offset = 0
    while pages < max(1, max_pages):
        status, text = fetch_page(page_url(url, offset), cookie)
        if status != 200:
            raise MarketError(
                "eBay answered HTTP %s for the listings page." % status,
                "That is usually a session that has expired: sign in and paste "
                "a fresh cookie.", kind="session")
        page_items = parse_ebay_listings(text)
        fresh = [item for item in page_items if item["id"] not in seen]
        pages += 1
        if not fresh:
            break
        seen.update(item["id"] for item in fresh)
        items.extend(fresh)
        if len(page_items) < _EBAY_PER_PAGE:
            break
        offset += _EBAY_PER_PAGE
    return items, pages, text


def site(name):
    """The row for one marketplace, or raise: a typo must not look like a site."""
    try:
        return SITES[str(name).lower()]
    except KeyError:
        raise MarketError("Unknown marketplace: %s" % name,
                          "Expected one of: %s." % ", ".join(sorted(SITES)))


def read_cookie(path):
    """The Cookie header to send, read from the private file.

    People paste three different things and all three are correct: the whole
    ``Cookie: a=1; b=2`` header from the browser's network tab, one
    ``name=value`` pair, or several lines of them. Comment lines (``#``) are
    ignored so the shipped template can explain itself without becoming part of
    the cookie - a cookie that contains the instructions fails as a login wall,
    which is a confusing way to learn that.
    """
    return read_cookie_report(path)[0]


def read_cookie_report(path):
    """``(cookie, dropped)``: the header to send, and what could not be sent.

    ``dropped`` lists the characters that were removed because no header can
    carry them. They are removed rather than raised on, because a cookie with a
    stray tick pasted into it usually still works - but the caller says so, in
    case the session then does not.
    """
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    #  A file saved by an editor that adds its own BOM can carry a second one;
    #  it would otherwise become part of the first cookie name and the site
    #  would say the session is invalid for no visible reason.
    text = text.lstrip("\ufeff")
    pairs, dropped = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("cookie:"):
            line = line.split(":", 1)[1].strip()
        for ch in dropped_characters(line):
            if ch not in dropped:
                dropped.append(ch)
        line = clean_header_value(line).rstrip(";")
        if line:
            pairs.append(line)
    return "; ".join(pairs), dropped


def fetch(url, cookie, timeout=30, opener=None):
    """``(status, text)`` for one GET, carrying the session cookie.

    The answer is returned rather than raised for anything the site itself
    said: a 403 is the site's opinion about the cookie, and the panel has to
    show it. Only a failure to reach the site at all raises.
    """
    if not url:
        raise MarketError("No address is saved for this site.",
                          "Set it in User Settings.")
    if not cookie:
        raise MarketError("No cookie is saved for this site.",
                          "Paste one into the site's cookie file first.")
    #  Belt and braces: whatever came from the file, the header is ASCII by the
    #  time it leaves here, so a stray tick can never become a codec error.
    cookie = clean_header_value(cookie)
    if not cookie:
        raise MarketError(
            "The saved cookie has nothing a browser could send in it.",
            "Re-copy the Cookie request header and paste it into the file.")
    headers = dict(BROWSER_HEADERS)
    headers["Cookie"] = cookie
    request = urllib.request.Request(url, headers=headers)
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            body = response.read()
    except urllib.error.HTTPError as exc:
        #  An HTTP error still carries a page, and that page is often the
        #  login wall that explains everything.
        try:
            body = exc.read()
        except Exception:
            body = b""
        return int(exc.code), _text(body)
    except (urllib.error.URLError, OSError) as exc:
        raise MarketError(
            "Could not reach %s." % url,
            "%s. Check the address and this computer's connection."
            % getattr(exc, "reason", exc))
    except UnicodeEncodeError as exc:
        #  Only reachable if a caller passes a cookie straight through without
        #  clean_header_value; the message names the real culprit anyway.
        raise MarketError(
            "The saved cookie contains a character a browser never sends.",
            "%r cannot go in a request header. Re-copy the Cookie header into "
            "the file." % exc.object[exc.start:exc.end])
    return int(status), _text(body)


def _text(body):
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return str(body or "")


def looks_like_login(text):
    """Whether a page is a login wall rather than the seller's listings."""
    low = str(text or "").lower()
    return any(marker in low for marker in _LOGIN_MARKERS)


def page_title(text):
    """The page's own title, for saying what came back."""
    match = TITLE.search(str(text or ""))
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()[:120]


def describe(text, status=200):
    """A short, human account of what came back from a page."""
    title = page_title(text) or "untitled page"
    size = len(text or "")
    if status != 200:
        return "HTTP %d - %s (%d characters)" % (status, title, size)
    if looks_like_login(text):
        return "a sign-in page (%s)" % title
    return "%s (%d characters)" % (title, size)


def save_page(path, text):
    """Write a checked copy beside the app; returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")
    return path
