#!/usr/bin/env python3
"""Checks for market_stock - reading eBay and Facebook with your own session.

No network and no account: the request is a fake opener and the pages are
strings. What is worth testing is everything around the request - which of the
three ways of pasting a cookie is read, whether a login wall is recognised as
one, and whether the panel saves a copy instead of pretending to compare.
"""
import importlib.util
import io
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s %s" % (name, extra))


def load_harness():
    spec = importlib.util.spec_from_file_location(
        "panel", str(APP / "test-photo-panel.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["panel"] = module
    spec.loader.exec_module(module)
    return module


harness = load_harness()
gui = harness.gui
import market_stock                                  # noqa: E402
import stock_compare                                 # noqa: E402

LISTINGS_PAGE = """<!DOCTYPE html><html><head>
<title>Active listings | eBay</title></head><body>
<div class="listing"><span>1989 O-Pee-Chee Wayne Gretzky #1</span>
<span>Qty available: 2</span></div></body></html>"""

LOGIN_PAGE = """<html><head><title>Sign in to eBay</title></head>
<body><h1>Please sign in</h1><p>You must log in to continue.</p></body></html>"""


#  eBay's actual answer to a scripted request, and Facebook's: neither is a
#  listing page, and neither can be turned into one by a better parser.
EBAY_WALL = """<!DOCTYPE html><html><head>
<title>Pardon Our Interruption</title></head><body>
<h1>Pardon our interruption...</h1>
<p>Before you continue, please verify you are a human by completing the
verification below.</p><div id="challenge"></div></body></html>"""

FB_400 = """<!DOCTYPE html><html><head><title>Error</title></head><body>
<div id="mount"></div><script>window.__error={"code":1357004};</script>
<noscript>Please turn on JavaScript in your browser.</noscript>
</body></html>"""


def test_cookies():
    print("== 1. the three ways a person pastes a cookie ==")
    folder = Path(tempfile.mkdtemp())
    path = folder / "ebay-cookie.txt"

    path.write_text("# explanation line\nSID=abc; token=xyz\n", encoding="utf-8")
    check("a single name=value line is read",
          market_stock.read_cookie(path) == "SID=abc; token=xyz",
          market_stock.read_cookie(path))
    check("comment lines never become part of the cookie",
          "#" not in market_stock.read_cookie(path), "")

    path.write_text("Cookie: SID=abc; token=xyz\n", encoding="utf-8")
    check("a pasted 'Cookie:' header is unwrapped",
          market_stock.read_cookie(path) == "SID=abc; token=xyz",
          market_stock.read_cookie(path))

    path.write_text("SID=abc\ntoken=xyz\n\n", encoding="utf-8")
    check("several lines are joined the way a header needs",
          market_stock.read_cookie(path) == "SID=abc; token=xyz",
          market_stock.read_cookie(path))

    path.write_text("SID=abc\ntoken=xyz;\n", encoding="utf-8-sig")
    check("a byte-order mark does not become part of the name",
          market_stock.read_cookie(path).startswith("SID=abc"),
          market_stock.read_cookie(path))
    check("a trailing semicolon is not doubled",
          ";;" not in market_stock.read_cookie(path), "")

    path.write_text("# nothing pasted yet\n", encoding="utf-8")
    check("an untouched template reads as no cookie",
          market_stock.read_cookie(path) == "", market_stock.read_cookie(path))


def test_header_safety():
    print()
    print("== 1b. a cookie copied out of a page cannot break the request ==")
    folder = Path(tempfile.mkdtemp())
    path = folder / "ebay-cookie.txt"
    #  A tick, a curly quote and a real non-breaking space, as a copy from a
    #  rendered page or a chat window brings.
    path.write_text("SID=abc\u2713; tok=\u2019en; nb\u00a0=1\n", encoding="utf-8")
    cookie, dropped = market_stock.read_cookie_report(path)
    check("the cookie keeps every part that can be sent",
          cookie == "SID=abc; tok=en; nb=1", cookie)
    check("the characters that cannot be sent are reported",
          set(dropped) == {"\u2713", "\u2019", "\u00a0"}, str(dropped))
    check("a header value is printable ASCII only",
          all(" " <= ch <= "~" for ch in cookie), repr(cookie))
    check("a newline cannot smuggle a second header in",
          "\n" not in market_stock.clean_header_value("a=1\nb=2") and
          "\r" not in market_stock.clean_header_value("a=1\rb=2"), "")

    seen = {}

    class Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(request, timeout=None):
        #  What http.client actually does with a header, and what used to raise.
        #  urllib normalises header names, so ask for it the way the wire does.
        seen["cookie"] = request.get_header("Cookie").encode("latin-1")
        return Response(LISTINGS_PAGE.encode("utf-8"))

    status, _text = market_stock.fetch("https://x/lst", cookie, opener=opener)
    check("the request is made with the cleaned cookie", status == 200 and
          seen["cookie"] == b"SID=abc; tok=en; nb=1", str(seen))

    path.write_text("\u2713\u2713\u2713\n", encoding="utf-8")
    cookie, _dropped = market_stock.read_cookie_report(path)
    check("a file with nothing sendable in it reads as no cookie",
          cookie == "", cookie)
    try:
        market_stock.fetch("https://x/lst", cookie, opener=opener)
        check("and is refused before a request is attempted", False, "")
    except market_stock.MarketError as exc:
        check("and is refused before a request is attempted",
              "No cookie is saved" in exc.message, exc.message)


def test_fetch():
    print()
    print("== 2. one request, and what the site said ==")
    seen = {}

    class Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(request, timeout=None):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        seen["timeout"] = timeout
        return Response(LISTINGS_PAGE.encode("utf-8"))

    status, text = market_stock.fetch("https://www.ebay.ca/sh/lst/active",
                                      "SID=abc", opener=opener)
    check("a normal answer is returned as text", status == 200 and
          "Gretzky" in text, str(status))
    check("the cookie is sent as the Cookie header",
          seen["headers"].get("Cookie") == "SID=abc", str(seen["headers"]))
    check("it looks like a browser, which these sites require",
          "Mozilla" in seen["headers"].get("User-agent", ""),
          str(seen["headers"]))
    check("it asks the saved address", seen["url"].endswith("/sh/lst/active"),
          seen["url"])

    def not_http_error():
        raise urllib.error.HTTPError(
            "https://x", 403, "Forbidden", {}, io.BytesIO(LOGIN_PAGE.encode()))

    status, text = market_stock.fetch("https://x", "SID=abc",
                                      opener=lambda *a, **k: not_http_error())
    check("an HTTP refusal comes back with its page, not as a crash",
          status == 403 and "sign in" in text.lower(), str(status))

    def offline():
        raise urllib.error.URLError("getaddrinfo failed")

    try:
        market_stock.fetch("https://x", "SID=abc",
                           opener=lambda *a, **k: offline())
        check("being offline is reported, not swallowed", False, "")
    except market_stock.MarketError as exc:
        check("being offline is reported, not swallowed",
              "Could not reach" in exc.message and "connection" in exc.hint,
              exc.message + " / " + exc.hint)
    for bad in (("", "SID=abc"), ("https://x", "")):
        try:
            market_stock.fetch(*bad, opener=opener)
            check("a missing address or cookie is refused before any request",
                  False, "")
        except market_stock.MarketError:
            check("a missing address or cookie is refused before any request",
                  True, "")


def test_pages():
    print()
    print("== 3. a page from a seller, or a login wall ==")
    check("a listing page is not a login page",
          not market_stock.looks_like_login(LISTINGS_PAGE), "")
    check("a login wall is recognised",
          market_stock.looks_like_login(LOGIN_PAGE), "")
    check("'log in to Facebook' is recognised",
          market_stock.looks_like_login(
              "<title>Facebook</title> Log in to Facebook"), "")
    check("an eBay sign-in URL is recognised",
          market_stock.looks_like_login(
              '<a href="https://signin.ebay.ca/ws/eBayISAPI.dll">x</a>'), "")
    check("the page's own title is read",
          market_stock.page_title(LISTINGS_PAGE) == "Active listings | eBay",
          market_stock.page_title(LISTINGS_PAGE))
    check("a page with no title says so by saying nothing",
          market_stock.page_title("<html></html>") == "", "")
    check("a good answer is described by its title and size",
          "Active listings | eBay" in market_stock.describe(LISTINGS_PAGE),
          market_stock.describe(LISTINGS_PAGE))
    check("a login wall is described as a sign-in page",
          market_stock.describe(LOGIN_PAGE).startswith("a sign-in page"),
          market_stock.describe(LOGIN_PAGE))
    check("a refusal still says the status",
          market_stock.describe(LOGIN_PAGE, 403).startswith("HTTP 403"),
          market_stock.describe(LOGIN_PAGE, 403))

    folder = Path(tempfile.mkdtemp())
    page = market_stock.save_page(folder / "deep" / "page.html", LISTINGS_PAGE)
    check("a copy is written, folders and all",
          page.is_file() and "Gretzky" in page.read_text(encoding="utf-8"), "")


EBAY_PAGE = """<html><head><title>Manage active listings - eBay Seller Hub</title>
</head><body><table><tbody>
<tr data-id="389440929928" data-site="2" class="grid-row">
<td class="shui-dt--selector"><div class="checkbox"><input aria-label="Select
 this item for performing bulk action - #75 Bert Campaneris"></div></td>
<td class="shui-dt-column__title shui-dt--left"><div class="cell-wrapper">
<div class="column-title"><div class="column-title__text-wrapper">
<div class="column-title__text"><a href="https://www.ebay.ca/itm/389440929928">
#75 Bert Campaneris 1967 O-Pee-Chee Baseball Card</a></div>
<div class="column-title__subtext"><span>Buy It Now &middot; 389440929928</span>
</div></div></div></div></td>
<td class="shui-dt-column__listingSKU shui-dt--left"><div class="cell-wrapper">
<div class="shui-dt--text-column"><div><span></span></div></div></div></td>
<td class="shui-dt-column__price shui-dt--right"><div class="cell-wrapper">
<div class="col-price"><div class="col-price__current"><span>C $34.10</span>
</div></div></div></td>
<td class="shui-dt-column__availableQuantity shui-dt--right"><div
 class="cell-wrapper"><div class="shui-dt--text-column"><div><span>1</span>
</div></div></div></td>
<td class="shui-dt-column__visitCount shui-dt--right">0</td></tr>
<tr data-id="389440982416" data-site="2" class="grid-row">
<td class="shui-dt-column__title shui-dt--left"><div class="cell-wrapper">
<div class="column-title"><div class="column-title__text-wrapper">
<div class="column-title__text"><a href="https://www.ebay.ca/itm/389440982416">
#189 Gene Tenace 1972 O-Pee-Chee Baseball Card</a></div></div></div></div></td>
<td class="shui-dt-column__listingSKU shui-dt--left"><div class="cell-wrapper">
<div class="shui-dt--text-column"><div><span>GT-189</span></div></div></div></td>
<td class="shui-dt-column__availableQuantity shui-dt--right"><div
 class="cell-wrapper"><div class="shui-dt--text-column"><div><span>3</span>
</div></div></div></td></tr>
<tr data-id="389441056820" data-site="2" class="grid-row">
<td class="shui-dt-column__title shui-dt--left"><div class="cell-wrapper">
<div class="column-title"><div class="column-title__text-wrapper">
<div class="column-title__text"><a href="https://www.ebay.ca/itm/389441056820">
#149 Chico Maki (EX) 1970-71 O-Pee-Chee Hockey Card</a></div></div></div>
</div></td>
<td class="shui-dt-column__availableQuantity shui-dt--right"><div
 class="cell-wrapper"><div class="shui-dt--text-column"><div><span>0</span>
</div></div></div></td></tr>
</tbody></table></body></html>"""

FB_PAGE = """<html><head><title>Facebook</title></head><body>
<div><span>Status</span><span>All</span><span>Available &amp; in stock</span>
<span>Sold &amp; out of stock</span><span>Pending</span><span>Draft</span></div>
<div><a aria-label="1973-74 O-Pee-Chee Walt Tkaczuk #25 New York Rangers Center
 EX-MT Dark Back Trading Card" href="/marketplace/item/1"></a>
<div><span>1973-74 O-Pee-Chee Walt Tkaczuk #25 NY Rangers Center EX-MT Dark
 Back Trading Card</span><span>CA$8</span><span>Active</span>
<span>&middot; Listed on 10/25</span><span>Mark as sold</span></div></div>
<div><div><span>1973-74 O-Pee-Chee Joe Watson #91 Flyers Defense EX-MT
 Dark Back Trading Card</span><span>CA$5</span><span>Sold</span>
<span>&middot; Listed on 10/20</span></div></div>
<div><div><span>1973-74 O-Pee-Chee Real Lemieux #122 LA Kings LW EX-MT Light
 Back Trading Card</span><span>CA$4</span><span>Pending</span>
</div></div>
<div><div><span>1973-74 O-Pee-Chee Rod Seiling #9 Dark Back NY Rangers NHL
 Trading Card</span><span>CA$6</span><span>Draft</span></div></div>
</body></html>"""


def test_panel_with_a_stray_character():
    print()
    print("== 5a. the panel says what it removed from the cookie ==")
    folder, app, parent = build_panel()
    (folder / "ebay-cookie.txt").write_text("SID=abc\u2713\n", encoding="utf-8")
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(market_stock, "fetch",
                         lambda url, cookie: (200, EBAY_PAGE)), \
            patch.object(stock_compare, "read_woo_stock",
                         lambda *a, **k: WOO_PRODUCTS), \
            patch.object(gui, "in_background", sync_background):
        find(parent, gui.ttk.Button, "Compare stock with eBay").invoke()
    check("a cookie with a tick still reads the page",
          any("removed" in text and "\u2713" in text
              for _tag, text in app.lines),
          str([t for _tag, t in app.lines][:3]))
    check("and the comparison still happened",
          any("matched cards against eBay" in text
              for _tag, text in app.lines), str(app.lines[-2:]))


def test_parsing():
    print()
    print("== 4. reading the two pages ==")
    items = market_stock.parse_ebay_listings(EBAY_PAGE)
    check("every row on an eBay page becomes a listing", len(items) == 3,
          str(items))
    check("the title is the row's own title",
          items[0]["name"] == "#75 Bert Campaneris 1967 O-Pee-Chee Baseball Card",
          items[0]["name"])
    check("the listing id comes with it", items[0]["id"] == "389440929928",
          items[0]["id"])
    check("the available quantity is a number",
          [item["qty"] for item in items] == [1, 3, 0],
          str([item["qty"] for item in items]))
    check("a zero is a listing at zero, not a missing row",
          items[2]["qty"] == 0, str(items[2]))
    check("a custom label is read when the seller uses one",
          items[1]["sku"] == "GT-189", items[1]["sku"])
    check("an empty custom label is empty, not a stray word",
          items[0]["sku"] == "", repr(items[0]["sku"]))

    broken = EBAY_PAGE.replace("<span>3</span>", "<span>out of stock</span>")
    check("a row whose quantity cannot be read is skipped, never counted as 0",
          [item["qty"] for item in market_stock.parse_ebay_listings(broken)]
          == [1, 0], str(market_stock.parse_ebay_listings(broken)))
    check("a page with no rows is an empty list, not a crash",
          market_stock.parse_ebay_listings("<html></html>") == [], "")
    check("junk is an empty list too",
          market_stock.parse_ebay_listings(None) == [], "")

    fb = market_stock.parse_facebook_listings(FB_PAGE)
    check("each Facebook listing becomes a row", len(fb) == 3, str(fb))
    check("an Active listing counts as one",
          fb[0]["status"] == "Active" and fb[0]["qty"] == 1, str(fb[0]))
    check("a Sold listing counts as none",
          fb[1]["status"] == "Sold" and fb[1]["qty"] == 0, str(fb[1]))
    check("a Pending listing still counts as one, and says Pending",
          fb[2]["status"] == "Pending" and fb[2]["qty"] == 1, str(fb[2]))
    check("a Draft is not on the site, so it is left out",
          all("Rod Seiling" not in item["name"] for item in fb), str(fb))
    check("the title is the line above the price",
          fb[0]["name"].startswith("1973-74 O-Pee-Chee Walt Tkaczuk #25"),
          fb[0]["name"])
    check("the price is kept for the record", fb[0]["price"] == "CA$8",
          fb[0]["price"])
    check("the status filter's own words are not mistaken for a listing",
          all(item["name"] not in ("All", "Sold & out of stock")
              for item in fb), str(fb))
    check("one dispatcher serves both sites",
          len(market_stock.parse_listings("ebay", EBAY_PAGE)) == 3 and
          len(market_stock.parse_listings("facebook", FB_PAGE)) == 3, "")


def test_pages_of_ebay():
    print()
    print("== 4b. eBay is read page by page ==")
    check("an offset is added to the address",
          market_stock.page_url("https://www.ebay.ca/sh/lst/active", 200)
          .endswith("?offset=200"),
          market_stock.page_url("https://www.ebay.ca/sh/lst/active", 200))
    check("an offset already in the address is replaced, not doubled",
          market_stock.page_url("https://x/sh/lst/active?offset=0&a=1", 400)
          == "https://x/sh/lst/active?a=1&offset=400",
          market_stock.page_url("https://x/sh/lst/active?offset=0&a=1", 400))

    def full_page(base, count=200):
        rows = "".join(
            '<tr data-id="%d" class="grid-row"><td class="shui-dt-column__'
            'title"><div class="column-title__text"><a href="#">#%d Card</a>'
            '</div></td><td class="shui-dt-column__availableQuantity"><div>'
            '<span>1</span></div></td></tr>' % (base + i, base + i)
            for i in range(count))
        return "<html><table><tbody>%s</tbody></table></html>" % rows

    asked = []

    def fetch_page(url, cookie):
        asked.append(url)
        page = len(asked) - 1
        return 200, (full_page(1000) if page == 0 else full_page(2000, 5))

    items, pages, _text = market_stock.read_ebay(fetch_page, "https://x/lst", "c")
    check("a full first page is followed by the next one", pages == 2,
          str(pages))
    check("both pages' listings are kept", len(items) == 205, str(len(items)))
    check("the second page is asked for by offset",
          "offset=200" in asked[1], str(asked))
    check("a short page ends the walk", pages == 2, str(pages))

    def repeats(url, cookie):
        return 200, full_page(1000, 200)

    items, pages, _ = market_stock.read_ebay(repeats, "https://x/lst", "c")
    check("a site that keeps serving the same page cannot loop forever",
          pages == 2 and len(items) == 200, "%d pages, %d items" %
          (pages, len(items)))

    def refused(url, cookie):
        return 403, "denied"

    try:
        market_stock.read_ebay(refused, "https://x/lst", "c")
        check("a refused page is reported, not read as an empty shop", False, "")
    except market_stock.MarketError as exc:
        check("a refused page is reported, not read as an empty shop",
              "403" in exc.message and "expired" in exc.hint,
              exc.message + " / " + exc.hint)


def test_site_rows():
    print()
    print("== 4. the two sites are declared in one place ==")
    check("eBay has a cookie file and a page file",
          market_stock.SITES["ebay"]["cookie"] == "ebay-cookie.txt" and
          market_stock.SITES["ebay"]["page"] == "ebay-active.html", "")
    check("Facebook has its own, so the two sessions cannot mix",
          market_stock.SITES["facebook"]["cookie"] == "fb-cookie.txt" and
          market_stock.SITES["facebook"]["page"] == "fb-selling.html", "")
    try:
        market_stock.site("kijiji")
        check("an unknown site is refused rather than guessed", False, "")
    except market_stock.MarketError as exc:
        check("an unknown site is refused rather than guessed",
              "kijiji" in exc.message, exc.message)


def build_panel(folder=None):
    folder = folder or Path(tempfile.mkdtemp())
    harness.install_plugin("1.0.20", folder / "plugin")
    app = harness.FakeApp(folder)
    parent = harness.FakeWidget()
    gui.build_stock(parent, app)
    return folder, app, parent


def find(parent, kind, text, exact=True):
    for widget in parent.walk():
        if not isinstance(widget, kind):
            continue
        got = str(widget.cget("text"))
        if (got == text) if exact else (got.startswith(text)):
            return widget
    return None


def sync_background(app, work, done):
    try:
        result, error = work(), None
    except Exception as exc:
        result, error = None, exc
    return done(result, error)


EBAY_FIRST_PAGE = EBAY_PAGE          # three rows: qty 1, 3, 0

WOO_PRODUCTS = [
    {"id": 1, "name": "#75 Bert Campaneris 1967 O-Pee-Chee Baseball Card",
     "sku": "", "manage_stock": True, "stock_quantity": 1, "type": "simple"},
    {"id": 2, "name": "#189 Gene Tenace 1972 O-Pee-Chee Baseball Card",
     "sku": "", "manage_stock": True, "stock_quantity": 1, "type": "simple"},
    {"id": 3, "name": "#149 Chico Maki 1970-71 O-Pee-Chee Hockey Card",
     "sku": "", "manage_stock": True, "stock_quantity": 0, "type": "simple"},
]


def test_panel():
    print()
    print("== 5. the panel compares eBay and Facebook on demand ==")
    folder, app, parent = build_panel()
    ebay = find(parent, gui.ttk.Button, "Compare stock with eBay")
    fb = find(parent, gui.ttk.Button, "Compare stock with Facebook")
    check("there is one comparison button per site",
          ebay is not None and fb is not None, "")
    check("the CanadianShopper comparison is still there",
          find(parent, gui.ttk.Button,
               "Compare stock (WooCommerce and CanadianShopper)") is not None,
          "")
    check("both sites show they have no session yet",
          len([w for w in parent.walk() if isinstance(w, gui.ttk.Label)
               and str(w.cget("text")) == "no session saved"]) == 2,
          str([w.cget("text") for w in parent.walk()
               if isinstance(w, gui.ttk.Label)]))

    opened, shown = [], []
    harness._BOX.showinfo = lambda *a, **k: shown.append(a)
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "open_market_cookie",
                         lambda app, site_id: opened.append(site_id)):
        ebay.invoke()
    check("with no cookie it offers the private file",
          opened == ["ebay"], str(opened))
    check("and says every cookie can be pasted at once",
          any("Cookie header" in str(a) for a in shown), str(shown))
    check("nothing is fetched without a cookie", not app.runs, "")

    (folder / "ebay-cookie.txt").write_text("SID=abc; token=xyz\n",
                                            encoding="utf-8")
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(market_stock, "fetch",
                         lambda url, cookie: (200, EBAY_FIRST_PAGE)), \
            patch.object(stock_compare, "read_woo_stock",
                         lambda *a, **k: WOO_PRODUCTS), \
            patch.object(gui, "in_background", sync_background):
        ebay.invoke()
    listing = next((w for w in parent.walk()
                    if isinstance(w, gui.tk.Listbox)), None)
    check("the disagreement between eBay and the website is listed",
          listing is not None and len(listing.items) == 1,
          str(listing and listing.items))
    check("the row names eBay and both counts",
          listing and "eBay 3" in listing.items[0], str(listing and listing.items))
    check("the summary counts it against eBay",
          find(parent, gui.ttk.Label, "1 of 3 matched cards disagree.")
          is not None,
          str([w.cget("text") for w in parent.walk()
               if isinstance(w, gui.ttk.Label)][:4]))
    saved = folder / "ebay-active.html"
    check("the page read is kept beside the app",
          saved.is_file() and "Bert Campaneris" in
          saved.read_text(encoding="utf-8"), str(saved))
    check("the status shows how many listings were read",
          find(parent, gui.ttk.Label, "3 listings") is not None, "")
    check("nothing on the site was changed",
          any("Nothing was changed on either site" in text
              for _tag, text in app.lines), str(app.lines[-2:]))
    check("no tool was started: both reads are plain page reads",
          not app.runs, str(app.runs))

    # ---- a login wall is a login wall, not an empty shop
    warned = []
    real_warning = harness._BOX.showwarning
    harness._BOX.showwarning = lambda *a, **k: warned.append(a)
    (folder / "fb-cookie.txt").write_text("c_user=1; xs=2\n", encoding="utf-8")
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(market_stock, "fetch",
                         lambda url, cookie: (200, LOGIN_PAGE)), \
            patch.object(gui, "in_background", sync_background):
        fb.invoke()
    check("an expired Facebook cookie is reported as a sign-in page",
          warned and "sign-in page" in str(warned[0]), str(warned))
    check("the dialog says how to fix it",
          warned and "fresh Cookie header" in str(warned[0]), str(warned))
    check("and that nothing was read or changed",
          warned and "Nothing was read" in str(warned[0]), str(warned))
    check("the status says it is not signed in",
          find(parent, gui.ttk.Label, "not signed in") is not None, "")
    check("the old eBay list is cleared rather than left looking current",
          not listing.items, str(listing.items))
    harness._BOX.showwarning = real_warning

    # ---- a page nobody understands says so, and keeps the copy
    warned[:] = []
    harness._BOX.showwarning = lambda *a, **k: warned.append(a)
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(market_stock, "fetch",
                         lambda url, cookie: (200, "<html><body>nothing"
                                                    " here</body></html>")), \
            patch.object(gui, "in_background", sync_background):
        fb.invoke()
    harness._BOX.showwarning = real_warning
    check("a page with no readable listing is not called an empty shop",
          warned and "no listing on it could be read" in str(warned[0]),
          str(warned))
    check("and the saved copy is pointed at",
          warned and "fb-selling.html" in str(warned[0]), str(warned))

    # ---- a site that cannot be reached
    errors = []
    real_error = harness._BOX.showerror
    harness._BOX.showerror = lambda *a, **k: errors.append(a)

    def offline(url, cookie):
        raise market_stock.MarketError("Could not reach that page.",
                                       "Check the address.")

    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(market_stock, "fetch", offline), \
            patch.object(gui, "in_background", sync_background):
        fb.invoke()
    harness._BOX.showerror = real_error
    check("a site that cannot be reached is reported",
          errors and "Could not reach" in str(errors[0]), str(errors))
    check("and it does not claim a copy was kept",
          find(parent, gui.ttk.Label, "could not be read") is not None, "")


def test_one_card_market():
    print()
    print("== 5b. one card, for eBay too ==")
    folder = Path(tempfile.mkdtemp())
    harness.install_plugin("1.0.20", folder / "plugin")
    app = harness.FakeApp(folder)
    app._stock_filter = "#189 Gene Tenace 1972 O-Pee-Chee Baseball Card"
    parent = harness.FakeWidget()
    gui.build_stock(parent, app)
    (folder / "ebay-cookie.txt").write_text("SID=abc\n", encoding="utf-8")
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(market_stock, "fetch",
                         lambda url, cookie: (200, EBAY_FIRST_PAGE)), \
            patch.object(stock_compare, "read_woo_stock",
                         lambda *a, **k: WOO_PRODUCTS), \
            patch.object(gui, "in_background", sync_background):
        find(parent, gui.ttk.Button, "Compare stock with eBay").invoke()
    listing = next(w for w in parent.walk() if isinstance(w, gui.tk.Listbox))
    check("the one-card hand-off narrows the eBay comparison too",
          len(listing.items) == 1 and "#189" in listing.items[0],
          str(listing.items))
    check("and the summary says so",
          any("(only this card)" in str(w.cget("text")) for w in parent.walk()
              if isinstance(w, gui.ttk.Label)), "")


def test_cookie_file():
    print()
    print("== 6. the file the app opens explains itself ==")
    folder, app, parent = build_panel()
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "open_path", lambda path: None), \
            patch.object(gui, "restrict_file_permissions", lambda path: None):
        gui.open_market_cookie(app, "facebook")
    path = folder / "fb-cookie.txt"
    check("the file is created where the reader looks for it",
          path.is_file(), str(path))
    text = path.read_text(encoding="utf-8")
    check("it says what to paste and how to find it",
          "Cookie" in text and "Network" in text, text[:80])
    check("it says a site sends many cookies, not one",
          "MANY cookies" in text and "semicolons" in text, text[:200])
    check("its explanation is ignored when the cookie is read",
          market_stock.read_cookie(path) == "",
          market_stock.read_cookie(path))
    check("it promises the file stays here",
          "stays on this computer" in text.lower() and
          "never" in text.lower(), text[:120])
    path.write_text("keep me\n", encoding="utf-8")
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "open_path", lambda path: None), \
            patch.object(gui, "restrict_file_permissions", lambda path: None):
        gui.open_market_cookie(app, "facebook")
    check("opening it again never overwrites a pasted cookie",
          path.read_text(encoding="utf-8") == "keep me\n", "")


def test_the_walls_have_names():
    print()
    print("== 9. a site that refuses the app is named, not misread ==")
    check("eBay's check page is recognised by its own title",
          market_stock.looks_like_blocked(EBAY_WALL), "")
    check("and a real listing page is not mistaken for one",
          not market_stock.looks_like_blocked(EBAY_PAGE), "")
    check("a check page is described as the site's check page",
          market_stock.describe(EBAY_WALL).startswith("the site's check page"),
          market_stock.describe(EBAY_WALL))
    check("a Facebook 400 answers with a script shell, not a shop",
          market_stock.looks_like_blocked(FB_400), "")

    session = market_stock.describe_refusal("eBay", 200, LOGIN_PAGE, "f.txt")
    check("a sign-in page with HTTP 200 is an expired session, not a 200",
          session.kind == "session" and "HTTP 200" not in session.message,
          session.message)
    check("and it says which file to put a fresh cookie in",
          "fresh Cookie header" in session.hint and "f.txt" in session.hint,
          session.hint)

    wall = market_stock.describe_refusal("eBay", 200, EBAY_WALL, "f.txt")
    check("eBay's wall is reported as a wall",
          wall.kind == "blocked" and "check page" in wall.message, wall.message)
    check("and the person is not told their cookie is stale",
          "expired" not in wall.message and "expired" not in wall.hint,
          wall.message + wall.hint)
    check("the way round it is the saved page, named with its button",
          "Read the saved eBay page" in wall.hint, wall.hint)

    face = market_stock.describe_refusal("Facebook", 400, FB_400)
    check("Facebook's HTTP 400 is the same wall, not a bad cookie",
          face.kind == "blocked" and "Nothing is wrong with your cookie"
          in face.hint, face.hint)
    check("a plain server error is neither of those",
          market_stock.describe_refusal("eBay", 500, "<html>oops</html>").kind
          == "http", "")

    try:
        market_stock.read_ebay(lambda url, cookie: (200, EBAY_WALL),
                               "https://www.ebay.ca/sh/lst/active", "a=1")
        check("the eBay reader refuses a wall instead of calling it an empty shop",
              False, "")
    except market_stock.MarketError as exc:
        check("the eBay reader refuses a wall instead of calling it an empty shop",
              exc.kind == "blocked" and "check page" in exc.message,
              exc.message)

    try:
        market_stock.read_ebay(lambda url, cookie: (403, LOGIN_PAGE),
                               "https://www.ebay.ca/sh/lst/active", "a=1")
        check("a 403 with a sign-in page is a session, not a blocked page",
              False, "")
    except market_stock.MarketError as exc:
        check("a 403 with a sign-in page is a session, not a blocked page",
              exc.kind == "session", exc.message)

    pages = []

    def wall_after_one(url, cookie):
        pages.append(url)
        return (200, EBAY_PAGE) if len(pages) == 1 else (200, EBAY_WALL)
    #  A page shorter than the site's page size ends the paging unless the
    #  page size itself is the test's - here a 3-row page is a full one, so the
    #  second request is made and meets the wall.
    with patch.object(market_stock, "_EBAY_PER_PAGE", 3):
        items, count, text = market_stock.read_ebay(
            wall_after_one, "https://www.ebay.ca/sh/lst/active", "a=1")
    check("a wall part-way through keeps what was already read",
          len(items) == 3 and count == 1 and len(pages) == 2,
          str((len(items), count, len(pages))))


def test_panel_names_the_wall():
    print()
    print("== 10. the panel says what the site did, and offers the way round ==")
    folder, app, parent = build_panel()
    (folder / "ebay-cookie.txt").write_text("SID=abc\n", encoding="utf-8")
    warned, errors = [], []
    harness._BOX.showwarning = lambda *a, **k: warned.append(a)
    harness._BOX.showerror = lambda *a, **k: errors.append(a)

    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(market_stock, "fetch",
                         lambda url, cookie: (200, EBAY_WALL)), \
            patch.object(gui, "in_background", sync_background):
        find(parent, gui.ttk.Button, "Compare stock with eBay").invoke()
    check("the eBay wall is named by its own words, not called unreadable",
          warned and "automatic check page" in str(warned[-1]) and
          "Pardon Our Interruption" in str(warned[-1]), str(warned))
    check("and not an error about the page being unreadable",
          not errors, str(errors))
    check("the status says the site blocked it",
          find(parent, gui.ttk.Label, "blocked") is not None,
          str([w.cget("text") for w in parent.walk()
               if isinstance(w, gui.ttk.Label)][:6]))
    check("nothing was compared and nothing ran",
          not app.runs, str(app.runs))

    warned[:] = []
    (folder / "fb-cookie.txt").write_text("c_user=1\n", encoding="utf-8")
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(market_stock, "fetch",
                         lambda url, cookie: (400, FB_400)), \
            patch.object(gui, "in_background", sync_background):
        find(parent, gui.ttk.Button, "Compare stock with Facebook").invoke()
    check("Facebook's 400 is reported as a refusal, not a stale cookie",
          warned and "Nothing is wrong with your cookie" in str(warned[-1]),
          str(warned))
    check("and it does not say the session expired",
          warned and "expired" not in str(warned[-1]).lower(), str(warned))

    # ---- the way round: a page saved from the browser
    saved_copy = folder / "fb-selling.html"
    saved_copy.write_text(FB_PAGE, encoding="utf-8")
    app.lines.clear()
    with patch.object(gui, "BASE", folder), \
            patch.object(gui.filedialog, "askopenfilename",
                         lambda **k: str(saved_copy)), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(stock_compare, "read_woo_stock",
                         lambda *a, **k: WOO_PRODUCTS), \
            patch.object(gui, "in_background", sync_background):
        find(parent, gui.ttk.Button, "Read the saved Facebook page").invoke()
    check("a saved page is read by the same reader",
          any("read from the saved page" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and the comparison runs from it",
          any("matched cards against Facebook" in text
              for _tag, text in app.lines), str(app.lines[-3:]))

    saved_copy.write_text("<html><body>not a listing page</body></html>",
                          encoding="utf-8")
    harness._BOX.shown.clear()
    with patch.object(gui, "BASE", folder), \
            patch.object(gui.filedialog, "askopenfilename",
                         lambda **k: str(saved_copy)), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "in_background", sync_background):
        find(parent, gui.ttk.Button, "Read the saved Facebook page").invoke()
    check("a wrong saved page says so instead of comparing nothing",
          any("no listing in it could be read" in str(payload)
              for payload in warned), str(warned[-1:]))



def test_where_the_saved_pages_live():
    print()
    print("== 4c. the page saved from a browser is found, not chosen ==")
    folder = Path(tempfile.mkdtemp())
    empty = folder / "nothing-here"
    dirs = market_stock.saved_page_dirs(folder, extra=[empty, folder])
    check("a folder that does not exist is skipped, not guessed at",
          empty not in dirs, str(dirs))
    check("and a folder named twice is tried once",
          len([d for d in dirs if d == folder.resolve()]) == 1, str(dirs))
    check("the app's own folder comes first", dirs[0] == folder.resolve(),
          str(dirs))

    import os
    import time
    now = time.time()
    older = folder / "older.html"
    older.write_text(EBAY_PAGE, encoding="utf-8")
    os.utime(older, (now - 7200, now - 7200))
    newer = folder / "Slugger - Seller Hub.htm"
    newer.write_text(EBAY_PAGE, encoding="utf-8")
    os.utime(newer, (now - 60, now - 60))
    (folder / "notes.txt").write_text("not a page", encoding="utf-8")
    (folder / "fb.html").write_text(FB_PAGE, encoding="utf-8")
    os.utime(folder / "fb.html", (now - 120, now - 120))
    pages = market_stock.saved_pages([folder])
    check("only pages are considered, newest first",
          [p.name for p, _m in pages][:2] == ["Slugger - Seller Hub.htm",
                                              "fb.html"],
          str([p.name for p, _m in pages]))
    check("a note is never read as a page",
          all(p.suffix != ".txt" for p, _m in pages),
          str([p.name for p, _m in pages]))
    check("the list is capped so a disk is never read whole",
          len(market_stock.saved_pages([folder], limit=1)) == 1, "")

    #  Which site a page belongs to comes from its contents: the browser names
    #  the file after the page title, which says nothing reliable.
    found = market_stock.saved_page("ebay", [folder], max_age_days=None)
    check("the eBay page is recognised by what is in it, not its name",
          found is not None and
          [item["name"] for item in found["items"]][0].startswith(
              "#75 Bert Campaneris"), str(found and found["path"]))
    check("and the newest eBay page is the one used",
          found["path"].name == "Slugger - Seller Hub.htm",
          found["path"].name)
    fb = market_stock.saved_page("facebook", [folder], max_age_days=None)
    check("Facebook's page is recognised the same way",
          fb is not None and len(fb["items"]) >= 3, str(fb and fb["path"]))
    check("a page of the wrong site is never used for the other",
          fb["path"].name == "fb.html", str(fb and fb["path"]))
    check("an ancient page is too stale to stand in for a live read",
          market_stock.saved_page("ebay", [folder], max_age_days=-1) is None,
          "")
    check("a folder with no page of that site finds nothing",
          market_stock.saved_page("ebay", [Path(tempfile.mkdtemp())],
                                  max_age_days=None) is None, "")

    #  The contents decide the site for a picked file too.
    detected = market_stock.detect_site(EBAY_PAGE)
    check("a page with no name says which site it is",
          detected is not None and detected[0] == "ebay", str(detected))
    check("and neither page is mistaken for an unreadable one",
          market_stock.detect_site("<html>nothing here</html>") is None, "")

    #  More listings beats fewer: that is what a saved page is for.
    live = market_stock.parse_listings("facebook", FB_PAGE)[:1]
    better = market_stock.better_saved_page("facebook", [folder], live,
                                            max_age_days=None)
    check("a saved page holding more than the live read wins",
          better is not None and len(better["items"]) > len(live),
          str(better and len(better["items"])))
    check("but only when it really holds more",
          market_stock.better_saved_page("facebook", [folder],
                                         live * 40,
                                         max_age_days=None) is None, "")
    check("and a stale one never wins",
          market_stock.better_saved_page("facebook", [folder], live,
                                         max_age_days=-1) is None, "")
    check("the phrase naming a page says what and when",
          "saved " in market_stock.describe_page(better) and
          "listing" in market_stock.describe_page(better),
          market_stock.describe_page(better))


def test_two_hundred_and_fifty_listings():
    print()
    print("== 4d. eBay is read up to 250 listings, every page kept ==")
    def page(start, count):
        rows = "".join(
            '<tr data-id="%d" class="grid-row"><td class="shui-dt-column__'
            'title"><div class="column-title__text"><a href="#">#%d Card</a>'
            '</div></td><td class="shui-dt-column__availableQuantity"><div>'
            '<span>1</span></div></td></tr>' % (start + i, start + i)
            for i in range(count))
        return "<html><table><tbody>%s</tbody></table></html>" % rows

    asked = []

    def fetch_page(url, cookie):
        asked.append(url)
        page_no = len(asked) - 1
        #  Two full pages of 200: a paid store. The cap is what stops the
        #  third request, not the site running out of listings.
        return 200, page(1000 + page_no * 200, 200)

    items, pages, text = market_stock.read_ebay(fetch_page, "https://x/lst", "c")
    check("the read stops at the product limit of a free store, not the disk",
          len(items) == 250 and pages == 2, "%d items, %d pages" %
          (len(items), pages))
    check("no third page is asked for once the limit is reached",
          len(asked) == 2, str(asked))
    check("the saved copy keeps every page that was read",
          text.count("grid-row") == 400, str(text.count("grid-row")))
    check("the default limit is named in one place",
          market_stock.EBAY_MAX_ITEMS == 250, str(market_stock.EBAY_MAX_ITEMS))
    items, pages, _text = market_stock.read_ebay(fetch_page, "https://x/lst",
                                                 "c", max_items=20)
    check("a smaller limit is honoured", len(items) == 20 and pages == 1,
          "%d items, %d pages" % (len(items), pages))
    check("one page load is what Facebook's window is measured against",
          market_stock.SITE_WINDOW["ebay"] == 200 and
          market_stock.SITE_WINDOW["facebook"] > 0,
          str(market_stock.SITE_WINDOW))


def test_the_panel_finds_the_page_itself():
    print()
    print("== 10b. the panel finds the saved page, and writes its own ==")
    folder, app, parent = build_panel()
    (folder / "ebay-cookie.txt").write_text("SID=abc\n", encoding="utf-8")
    warned = []
    harness._BOX.showwarning = lambda *a, **k: warned.append(a)

    # ---- a wall, and a page saved from the browser already sitting there
    saved = folder / "Seller Hub.html"
    saved.write_text(EBAY_PAGE, encoding="utf-8")
    app.lines.clear()
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(market_stock, "fetch",
                         lambda url, cookie: (200, EBAY_WALL)), \
            patch.object(stock_compare, "read_woo_stock",
                         lambda *a, **k: WOO_PRODUCTS), \
            patch.object(gui, "in_background", sync_background):
        find(parent, gui.ttk.Button, "Compare stock with eBay").invoke()
    check("the wall is not a dead end: the saved page is read without a picker",
          any("reading the saved page" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and no dialog is raised about it",
          not warned, str(warned))
    check("the comparison runs from that page",
          any("matched cards against eBay" in text
              for _tag, text in app.lines), str(app.lines[-2:]))
    check("the save is never overwritten with a page the app did not fetch",
          not (folder / "ebay-active.html").exists(),
          str(sorted(p.name for p in folder.iterdir())))

    # ---- the button: no file dialog, the newest page is used
    harness._BOX.warned = []
    asked = []
    with patch.object(gui, "BASE", folder), \
            patch.object(gui.filedialog, "askopenfilename",
                         lambda **k: asked.append(k) or ""), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(stock_compare, "read_woo_stock",
                         lambda *a, **k: WOO_PRODUCTS), \
            patch.object(gui, "in_background", sync_background):
        app.lines.clear()
        find(parent, gui.ttk.Button, "Read the saved eBay page").invoke()
    check("the saved page is read with no file dialog at all", not asked,
          str(asked))
    check("and it is the page that was there",
          any("read from the saved page Seller Hub.html" in text
              for _tag, text in app.lines), str(app.lines[-3:]))

    # ---- a live read that covers less than a saved page loses
    fb_saved = folder / "Marketplace - Selling.html"
    fb_saved.write_text(FB_PAGE * 6, encoding="utf-8")
    (folder / "fb-cookie.txt").write_text("c_user=1\n", encoding="utf-8")
    app.lines.clear()
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(market_stock, "fetch",
                         lambda url, cookie: (200, FB_PAGE)), \
            patch.object(stock_compare, "read_woo_stock",
                         lambda *a, **k: WOO_PRODUCTS), \
            patch.object(gui, "in_background", sync_background):
        find(parent, gui.ttk.Button, "Compare stock with Facebook").invoke()
    check("a saved page that covers more than the live one is used",
          any("the page saved on this computer holds" in text
              for _tag, text in app.lines), str(app.lines[-3:]))
    check("and the app's own copy is still the page the site really sent",
          (folder / "fb-selling.html").exists(),
          str(sorted(p.name for p in folder.iterdir())))
    check("nothing on either site was changed",
          any("Nothing was changed" in text for _tag, text in app.lines),
          str(app.lines[-2:]))


def main():
    test_cookies()
    test_header_safety()
    test_fetch()
    test_pages()
    test_parsing()
    test_pages_of_ebay()
    test_where_the_saved_pages_live()
    test_two_hundred_and_fifty_listings()
    test_panel_with_a_stray_character()
    test_site_rows()
    test_panel()
    test_one_card_market()
    test_cookie_file()
    test_the_walls_have_names()
    test_panel_names_the_wall()
    test_the_panel_finds_the_page_itself()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL MARKET STOCK CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
