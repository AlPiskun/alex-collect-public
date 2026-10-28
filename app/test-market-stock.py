#!/usr/bin/env python3
"""Checks for market_stock - reading eBay and Facebook with your own session.

No network and no account: the request is a fake opener and the pages are
strings. What is worth testing is everything around the request - which of the
three ways of pasting a cookie is read, whether a login wall is recognised as
one, and whether the panel saves a copy instead of pretending to compare.
"""
import importlib.util
import io
import json
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

LISTINGS_PAGE = """<!DOCTYPE html><html><head>
<title>Active listings | eBay</title></head><body>
<div class="listing"><span>1989 O-Pee-Chee Wayne Gretzky #1</span>
<span>Qty available: 2</span></div></body></html>"""

LOGIN_PAGE = """<html><head><title>Sign in to eBay</title></head>
<body><h1>Please sign in</h1><p>You must log in to continue.</p></body></html>"""


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


def test_panel():
    print()
    print("== 5. the panel checks a session instead of pretending ==")
    folder, app, parent = build_panel()
    ebay = find(parent, gui.ttk.Button, "Check eBay and save the page")
    facebook = find(parent, gui.ttk.Button, "Check Facebook and save the page")
    check("there is one button per site", ebay is not None and
          facebook is not None, "")
    check("both start unchecked",
          find(parent, gui.ttk.Label, "not checked yet") is not None, "")

    opened = []
    shown = []
    harness._BOX.showinfo = lambda *a, **k: shown.append(a)
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "open_market_cookie",
                         lambda app, site_id: opened.append(site_id)):
        ebay.invoke()
    check("with no cookie it offers the private file",
          opened == ["ebay"], str(opened))
    check("and says what to paste",
          any("Cookie header" in str(a) for a in shown), str(shown))
    check("nothing is fetched without a cookie", not app.runs, "")

    (folder / "ebay-cookie.txt").write_text("SID=abc\n", encoding="utf-8")
    with patch.object(gui, "BASE", folder), \
            patch.object(market_stock, "fetch",
                         lambda url, cookie: (200, LISTINGS_PAGE)), \
            patch.object(gui, "in_background", sync_background):
        ebay.invoke()
    saved = folder / "ebay-active.html"
    check("a good answer is saved beside the app",
          saved.is_file() and "Gretzky" in saved.read_text(encoding="utf-8"),
          str(saved))
    check("and the panel says it kept a copy",
          find(parent, gui.ttk.Label, "saved a copy") is not None,
          str([w.cget("text") for w in parent.walk()
               if isinstance(w, gui.ttk.Label)]))
    check("the console says nothing on the site was changed",
          any("nothing on eBay was changed" in text
              for _tag, text in app.lines), str(app.lines[-2:]))

    warned = []
    real_warning = harness._BOX.showwarning
    harness._BOX.showwarning = lambda *a, **k: warned.append(a)
    (folder / "fb-cookie.txt").write_text("c_user=1; xs=2\n", encoding="utf-8")
    with patch.object(gui, "BASE", folder), \
            patch.object(market_stock, "fetch",
                         lambda url, cookie: (200, LOGIN_PAGE)), \
            patch.object(gui, "in_background", sync_background):
        facebook.invoke()
    check("a login wall is reported as a stale cookie",
          warned and "expired" in str(warned[0]), str(warned))
    check("the status says it is not signed in",
          find(parent, gui.ttk.Label, "not signed in") is not None, "")
    check("nothing is compared from a login page",
          not any(w.packed for w in parent.walk()
                  if isinstance(w, gui.tk.Listbox)
                  and getattr(w, "items", [])), "")
    harness._BOX.showwarning = real_warning

    errors = []
    real_error = harness._BOX.showerror
    harness._BOX.showerror = lambda *a, **k: errors.append(a)

    def offline(url, cookie):
        raise market_stock.MarketError("Could not reach that page.",
                                       "Check the address.")

    with patch.object(gui, "BASE", folder), \
            patch.object(market_stock, "fetch", offline), \
            patch.object(gui, "in_background", sync_background):
        facebook.invoke()
    harness._BOX.showerror = real_error
    check("a site that cannot be reached is reported",
          errors and "Could not reach" in str(errors[0]), str(errors))
    check("and the status does not claim a copy was kept",
          find(parent, gui.ttk.Label, "could not be reached") is not None, "")


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


def main():
    test_cookies()
    test_fetch()
    test_pages()
    test_site_rows()
    test_panel()
    test_cookie_file()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL MARKET STOCK CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
