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

import datetime
import html
import re
import time
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
#  What a site's automatic-check page says. eBay calls it "Pardon our
#  interruption", Facebook answers 400 with a script shell. Neither is a
#  listing page, and saying "nothing is listed" about one of them would be a
#  lie the person would act on.
_BLOCK_MARKERS = (
    "pardon our interruption",
    "unusual traffic",
    "are you a robot",
    "verify you are a human",
    "enable javascript",
    "please turn on javascript",
    "javascript is disabled",
    "request blocked",
    "access denied",
    "sorry, something went wrong",
)

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

#  How many listings one read asks for. eBay serves 200 rows to a page, and a
#  free store holds no more than 250 listings in total, so two pages covers a
#  free store completely and a paid store is read in the same number of
#  requests as before - the cap is a ceiling, not a target. It is a parameter
#  rather than a constant at the call site so a store that grows only needs the
#  number changed in one place.
EBAY_MAX_ITEMS = 250

#  How many listings one page load hands over. eBay hands out up to 200 rows;
#  Facebook's selling page renders its first batch and lazy-loads the rest as
#  the reader scrolls, which a request cannot do. Below the window, the page is
#  a first screen rather than a catalogue - which is when a page saved from a
#  real browser (after scrolling) is worth looking for.
SITE_WINDOW = {"ebay": _EBAY_PER_PAGE, "facebook": 20}

#  How old a page saved from a browser may be before it is too stale to stand
#  in for a live read. A listing that sold last week is exactly the sort of
#  thing a stock comparison must not be told is still there.
SAVED_MAX_AGE_DAYS = 14

#  A saved page is HTML from a browser: a handful of them, not a download
#  folder's worth. The cap keeps a comparison from reading a whole disk.
SAVED_SCAN_LIMIT = 25
SAVED_MAX_BYTES = 25 * 1024 * 1024


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


def detect_site(text, order=("ebay", "facebook")):
    """``(site_id, items)`` for a page whose site is not known, or ``None``.

    A picked file has no filename worth trusting, so the page is recognised by
    its contents: eBay's Seller Hub markup is three rows away from anything
    else, and Facebook's is a price line with a state under it. The order is
    fixed - eBay first - so a page that could read as both is decided the same
    way every time rather than by whichever parser happens to be longer.
    """
    for site_id in order:
        items = parse_listings(site_id, text)
        if items:
            return site_id, items
    return None


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


def read_ebay(fetch_page, url, cookie, max_pages=10, max_items=EBAY_MAX_ITEMS):
    """Every page of active listings, through an injected page fetcher.

    ``fetch_page(url, cookie)`` returns ``(status, text)``. Pages are followed
    until one comes back short, empty or identical to the last - never by
    counting to a fixed total, because the total is the site's business - and
    no more than ``max_items`` listings are kept, which is 250 by default: the
    whole of a free store, and what keeps a very large store from turning one
    comparison into twenty requests.
    """
    items, pages, text = [], 0, ""
    seen = set()
    offset = 0
    max_items = max(1, int(max_items))
    #  Every page read is kept, not only the last one: the copy saved beside
    #  the app is what a later run falls back to when the site refuses, and a
    #  copy holding one page of five would quietly compare a fifth of the shop.
    chunks = []
    while pages < max(1, max_pages) and len(items) < max_items:
        status, text = fetch_page(page_url(url, offset), cookie)
        #  Seller Hub answers a scripted request with its "Pardon our
        #  interruption" check page and HTTP 200, so the page itself has to be
        #  looked at: parsing it yields no listings, and reporting "you have
        #  none" about a page that was never a listing page would be a lie the
        #  person would act on.
        if status != 200 or looks_like_login(text) or looks_like_blocked(text):
            if pages:
                #  Some pages were read before the site started checking: keep
                #  them rather than throw the work away.
                break
            raise describe_refusal("eBay", status, text)
        chunks.append(text)
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
    return items[:max_items], pages, "\n".join(chunks) if chunks else text


# ------------------------------------------------------- saved pages
#  eBay and Facebook both refuse a scripted read often enough that the page
#  saved from a signed-in browser has to be a first-class source - and the
#  person should not have to find the file every time. So the app looks for
#  it: the copy it writes itself on every read, and anything saved out of a
#  browser, in the two folders a browser saves to.


def saved_page_dirs(base, extra=()):
    """The folders a page saved from a browser could be sitting in.

    The app's own folder comes first because that copy is fresh by
    construction; ``extra`` is for a caller that wants another place tried
    (a folder chosen in the settings, say). Duplicates and missing folders are
    dropped here rather than at every call site.
    """
    folders, seen = [], set()
    candidates = [Path(base)] + [Path(path) for path in extra or []]
    home = Path.home()
    candidates += [home / "Downloads", home / "Desktop"]
    for folder in candidates:
        try:
            resolved = folder.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key in seen or not resolved.is_dir():
            continue
        seen.add(key)
        folders.append(resolved)
    return folders


def saved_pages(folders, limit=SAVED_SCAN_LIMIT):
    """``[(path, mtime)]`` of the HTML pages in those folders, newest first.

    Only HTML, only files of a sane size, and only the newest ``limit`` of
    them: a comparison must not read a whole disk to find one page. The order
    is newest first because the newest page is the one most likely to still be
    true.
    """
    found = []
    for folder in folders or []:
        try:
            entries = list(Path(folder).iterdir())
        except OSError:
            continue
        for path in entries:
            try:
                if not path.is_file() or path.suffix.lower() not in (".html", ".htm"):
                    continue
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size > SAVED_MAX_BYTES:
                continue
            found.append((path, stat.st_mtime))
    #  Newest first, and by name within the same second: two files written by
    #  one save can share a timestamp, and a list that reorders itself between
    #  runs is a list that cannot be reasoned about.
    found.sort(key=lambda row: (-row[1], str(row[0]).lower()))
    return found[:max(1, int(limit))]


def read_page(path):
    """The text of a saved page, or "" when it cannot be read."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _fresh_enough(mtime, max_age_days):
    """Whether a page is recent enough to stand in for a live read."""
    if not max_age_days:
        return True
    return mtime >= (time.time() - float(max_age_days) * 86400)


def saved_page(site_id, folders, limit=SAVED_SCAN_LIMIT,
               max_age_days=SAVED_MAX_AGE_DAYS):
    """The newest saved page holding this site's listings, or ``None``.

    Which file belongs to which site is decided by **what is in it**, not by
    its name: a browser saves a page under the page's title ("Seller Hub |
    eBay" today, something else tomorrow), and guessing at filenames is how a
    reader ends up being told a Facebook page is an eBay one. So each recent
    HTML file is parsed with that site's own reader and the first that yields
    listings is it.

    ``max_age_days`` skips pages too old to be trusted as a stand-in for a
    live read; ``None`` accepts any age (the person pressing a button that
    says "read the saved page" means the one they saved).
    """
    for path, mtime in saved_pages(folders, limit):
        if not _fresh_enough(mtime, max_age_days):
            continue
        text = read_page(path)
        items = parse_listings(site_id, text)
        if not items:
            continue
        return {"path": path, "text": text, "items": items, "mtime": mtime}
    return None


def better_saved_page(site_id, folders, live_items, limit=SAVED_SCAN_LIMIT,
                      max_age_days=SAVED_MAX_AGE_DAYS):
    """A saved page that holds more listings than the live read did.

    Facebook's selling page renders its first batch and loads the rest as the
    reader scrolls, so a request sees a window and a page saved from a real
    browser after scrolling sees the shop. When such a page exists and is
    recent, it is the better source - a card missing from the window looks
    *missing from the site*, which is the one wrong answer this panel must not
    give. It is the item count that decides, because covering more of the shop
    is what the page is being used for at all.
    """
    want = len(live_items or [])
    best = None
    for path, mtime in saved_pages(folders, limit):
        if not _fresh_enough(mtime, max_age_days):
            continue
        text = read_page(path)
        items = parse_listings(site_id, text)
        if len(items) <= want:
            continue
        if best is None or (len(items), mtime) > (len(best["items"]),
                                                  best["mtime"]):
            best = {"path": path, "text": text, "items": items, "mtime": mtime}
    return best


def describe_page(found):
    """One phrase naming a saved page and the day it was saved."""
    try:
        day = datetime.datetime.fromtimestamp(found["mtime"]).strftime(
            "%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError, KeyError, TypeError):
        day = "?"
    return "%s (%d listing%s, saved %s)" % (
        Path(found.get("path") or "").name, len(found.get("items") or []),
        "" if len(found.get("items") or []) == 1 else "s", day)


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


def looks_like_blocked(text):
    """Whether a page is the site's automatic-check page, not its content."""
    low = str(text or "").lower()
    return any(marker in low for marker in _BLOCK_MARKERS)


def describe_refusal(site_label, status, text, cookie_path=""):
    """The error for a site that answered with something other than a page.

    Three different things need three different sentences: a session that has
    expired (fix the file), a request the site refused as automated (the app
    cannot fetch this one - save the page instead), and the site being down.
    A 400 with a script shell is the second, which is what Facebook does.
    """
    #  A sign-in page can arrive with HTTP 200, so the page itself is asked
    #  first: an answer that is a login form is an expired session whatever
    #  number came with it, and saying "HTTP 200" about one would send the
    #  person looking for a server fault.
    if looks_like_login(text) or status in (401, 403):
        kind = "session"
    elif looks_like_blocked(text) or status == 400:
        kind = "blocked"
    else:
        kind = "http"
    if kind == "session":
        return MarketError(
            "%s sent %s back instead of your listings - it does not accept "
            "that session." % (site_label, describe(text, status)),
            "The saved cookie has expired. Sign in, copy a fresh Cookie header "
            "into %s, and try again." %
            (cookie_path or "the site's cookie file"), kind="session")
    if kind == "blocked":
        title = page_title(text)
        return MarketError(
            "%s answered with its automatic check page%s, not your listings - "
            "the app's request was refused before the page was served." %
            (site_label, " (\"%s\")" % title if title else ""),
            "Nothing is wrong with your cookie. Open the page in your browser, "
            "save it with Ctrl+S (HTML only), and press \"Read the saved %s "
            "page\" - the app finds the newest saved page itself, in its own "
            "folder or in Downloads." % site_label, kind="blocked")
    return MarketError(
        "%s answered HTTP %s." % (site_label, status),
        "Nothing was read. Try again, and if it repeats, save the page from "
        "your browser and press \"Read the saved %s page\"." % site_label,
        kind="http")


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
    if looks_like_blocked(text):
        return "the site's check page (%s)" % title
    if looks_like_login(text):
        return "a sign-in page (%s)" % title
    return "%s (%d characters)" % (title, size)


def save_page(path, text):
    """Write a checked copy beside the app; returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")
    return path
