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

import re
import urllib.error
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


class MarketError(Exception):
    """A page could not be read, with a sentence saying why."""

    def __init__(self, message, hint=""):
        super().__init__(message)
        self.message = str(message)
        self.hint = str(hint or "")


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
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    #  A file saved by an editor that adds its own BOM can carry a second one;
    #  it would otherwise become part of the first cookie name and the site
    #  would say the session is invalid for no visible reason.
    text = text.lstrip("\ufeff")
    pairs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("cookie:"):
            line = line.split(":", 1)[1].strip()
        pairs.append(line.rstrip(";"))
    return "; ".join(part for part in pairs if part)


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
