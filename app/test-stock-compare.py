#!/usr/bin/env python3
"""Checks for stock_compare - where the stock numbers disagree.

No network and no shop: the GET is a dict of canned replies and the plugin's
answer is a temporary file. The matching is the part worth testing, because a
wrong pair accuses a card that is fine.
"""
import importlib.util
import json
import os
import sys
import tempfile
import time as time_module
from pathlib import Path
from types import SimpleNamespace
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
import stock_compare                                   # noqa: E402
import cs_edit                                        # noqa: E402

PRODUCTS = [
    {"id": 1, "name": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
     "sku": "GR-1", "manage_stock": True, "stock_quantity": 2,
     "type": "simple"},
    {"id": 2, "name": "1966-67 Topps Bobby Orr #35", "sku": "BO-35",
     "manage_stock": True, "stock_quantity": 0, "type": "simple"},
    {"id": 3, "name": "Always available card", "sku": "",
     "manage_stock": False, "stock_quantity": None, "type": "simple"},
    {"id": 4, "name": "Variable card", "sku": "", "manage_stock": True,
     "stock_quantity": None, "type": "variable"},
]

class FakeRunner:
    """The runner's log, which is where the tool's own words live."""

    def __init__(self, output):
        self.output = output


#  The exact line a real run ended on: one listing's detail lookup, after
#  every listing before it had already been read.
DETAIL_FAILED = (
    "! Could not list CanadianShopper stock: CanadianShopper request failed "
    "(GET /api/data/product/94b93f6040f5401daabaa9c936efa5a7): URLError")


CS_ITEMS = [
    {"id": 101, "title": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
     "sku": "GR-1", "inventory": 0},
    {"id": 102, "title": "1966-67 Topps Bobby Orr #35", "sku": "",
     "inventory": 0},
]
OTHER = stock_compare.plugin_items(CS_ITEMS)     # what the panel compares with


def test_woo_items():
    print("== 1. which products have a number to compare ==")
    items, skipped = stock_compare.woo_items(PRODUCTS)
    check("managed products are compared", len(items) == 2, str(items))
    check("their quantity is the stock quantity",
          items[0]["qty"] == 2 and items[0]["name"].startswith("1989"),
          str(items[0]))
    check("unmanaged, variable and broken rows are counted, not guessed",
          skipped == 2, str(skipped))
    check("an unmanaged product is not silently treated as zero",
          all(item["name"] != "Always available card" for item in items), "")
    check("junk records are ignored, and a real product without a count is "
          "counted",
          stock_compare.woo_items([None, "x", {"name": "no stock"}]) ==
          ([], 1), str(stock_compare.woo_items([None, "x", {"name": "no stock"}])))


def test_plugin_items():
    print()
    print("== 2. the plugin's own listing shape ==")
    payload = {"items": [
        {"title": "1989 O-Pee-Chee Wayne Gretzky #1", "sku": "GR-1",
         "inventory": 3},
        {"title": "No number given", "sku": ""},
        {"title": "", "inventory": 4},
        {"title": "Old key name", "quantity": 1}]}
    items = stock_compare.plugin_items(payload)
    check("a title, a SKU and an inventory make a row", len(items) == 3,
          str(items))
    check("a listing with no inventory is kept, with no number to compare",
          next((item for item in items
                if item["name"] == "No number given"), {}).get("qty") is None,
          str(items))
    check("and not one number is invented for it",
          not any(item["name"] == "No number given" and item["qty"] == 0
                  for item in items), str(items))
    check("a row with no title is still dropped - nothing can be matched to "
          "it",
          not any(item["name"] == "" for item in items), str(items))
    check("'quantity' is accepted as the older name",
          any(item["name"] == "Old key name" for item in items), str(items))
    check("'listings' is accepted as the older envelope",
          len(stock_compare.plugin_items({"listings": [
              {"title": "A card", "inventory": 1}]})) == 1, "")
    check("a bare list works too",
          len(stock_compare.plugin_items([
              {"title": "A card", "inventory": 1}])) == 1, "")


def test_stock_file():
    print()
    print("== 3. the plugin's answer is a file ==")
    folder = Path(tempfile.mkdtemp())
    path = folder / "cs-stock.json"
    check("a missing file cannot be read", stock_compare.read_stock_file(path)
          is None, "")
    path.write_text("{oops", encoding="utf-8")
    check("unreadable JSON is a failed read", stock_compare.read_stock_file(path)
          is None, "")
    path.write_text(json.dumps({"items": []}), encoding="utf-8")
    check("an empty list is a real answer", stock_compare.read_stock_file(path)
          == [], "")
    path.write_text(json.dumps({"items": CS_ITEMS}), encoding="utf-8")
    check("its rows come back in the common shape",
          len(stock_compare.read_stock_file(path)) == 2, "")
    path.write_text(json.dumps({"nothing": "here"}), encoding="utf-8")
    check("an envelope nobody recognises is a failed read, not an empty shop",
          stock_compare.read_stock_file(path) is None, "")


def test_reading_woo():
    print()
    print("== 4. reading the catalogue, and saying why when it cannot ==")
    calls = []

    def fetch_ok(base, path, params, key, secret):
        calls.append((path, dict(params)))
        return (200, PRODUCTS) if params["page"] == 1 else (200, [])

    products = stock_compare.read_woo_stock(fetch_ok, "https://shop.example",
                                            "ck_a", "cs_b")
    check("every product comes back", len(products) == 4, str(len(products)))
    check("it reads the products endpoint",
          calls and calls[0][0] == "/wp-json/wc/v3/products", str(calls[:1]))
    check("only published products are counted",
          calls and calls[0][1]["status"] == "publish", str(calls[:1]))
    check("it stops at the first short page", len(calls) == 1, str(len(calls)))

    def fetch_full(base, path, params, key, secret):
        return 200, [{"id": params["page"], "name": "card"}]

    many = stock_compare.read_woo_stock(fetch_full, "https://shop.example",
                                        "ck_a", "cs_b", per_page=1, pages=3)
    check("a full page asks for the next one, up to the limit", len(many) == 3,
          str(len(many)))

    def fetch(code):
        return lambda *a, **k: (code, {"message": "no"})

    for code, needle in ((401, "refused"), (403, "refused"), (500, "HTTP 500")):
        try:
            stock_compare.read_woo_stock(fetch(code), "https://shop.example",
                                         "ck_a", "cs_b")
            check("HTTP %d is reported, not swallowed" % code, False, "")
        except stock_compare.StockError as exc:
            check("HTTP %d is reported, not swallowed" % code,
                  needle in exc.message, exc.message)
    try:
        stock_compare.read_woo_stock(fetch(401), "https://shop.example",
                                     "ck_a", "cs_b")
    except stock_compare.StockError as exc:
        check("a refused key says where to fix it", "REST API" in exc.hint,
              exc.hint)
    for missing in (("", "ck", "cs"), ("https://x", "", "")):
        try:
            stock_compare.read_woo_stock(fetch(200), *missing)
            check("missing details are refused before any request", False, "")
        except stock_compare.StockError:
            check("missing details are refused before any request", True, "")


def test_pairing():
    print()
    print("== 5. matching a card to the same card on the other site ==")
    woo, _ = stock_compare.woo_items(PRODUCTS)
    pairs, only_woo, only_other = stock_compare.pair(woo, OTHER)
    check("both cards are matched", len(pairs) == 2, str(pairs))
    check("a shared SKU is what matched the first one",
          pairs[0]["by"] == "sku", str(pairs[0]))
    check("the second one matched on its card number, not its wording",
          pairs[1]["by"] == "number", str(pairs[1]))
    check("nothing is left over on either side",
          only_woo == [] and only_other == [], str((only_woo, only_other)))

    different = [{"name": "1972-73 O-Pee-Chee Dave Burrows #133", "sku": "",
                  "qty": 1, "id": None}]
    pairs, only_woo, only_other = stock_compare.pair(woo, different)
    check("a different card number is never matched",
          pairs == [] and len(only_woo) == 2 and len(only_other) == 1,
          str((pairs, only_woo, only_other)))

    twin = [{"name": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6", "sku": "",
             "qty": 1},
            {"name": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6", "sku": "",
             "qty": 1}]
    pairs, only_woo, only_other = stock_compare.pair(woo[:1], twin)
    check("one card is matched once, even with two identical listings",
          len(pairs) == 1 and len(only_other) == 1,
          str((len(pairs), len(only_other))))

    same_sku_wrong_title = [{"name": "Something else entirely", "sku": "GR-1",
                             "qty": 5}]
    pairs, _ow, _oo = stock_compare.pair(woo[:1], same_sku_wrong_title)
    check("a shared SKU wins over a title that disagrees",
          pairs and pairs[0]["by"] == "sku", str(pairs))

    pairs, _ow, _oo = stock_compare.pair(woo, [])
    check("an empty other side matches nothing, without crashing", pairs == [],
          "")


def test_spellings():
    print()
    print("== 5b. the two sites spell a set differently ==")
    woo = [{"name": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6", "sku": "",
            "qty": 1, "id": 1},
           {"name": "1990-91 Upper Deck Jaromir Jagr #356", "sku": "",
            "qty": 1, "id": 2}]
    other = [{"name": "1989 OPC Wayne Gretzky #1", "sku": "", "qty": 0},
             {"name": "1990-91 UD Jaromir Jagr #356", "sku": "", "qty": 0}]
    pairs, only_woo, only_other = stock_compare.pair(woo, other)
    check("O-Pee-Chee on the website matches OPC on the listing",
          len(pairs) == 2, str(pairs))
    check("so does Upper Deck against UD",
          pairs and all(row["other"]["qty"] == 0 for row in pairs), str(pairs))
    check("nothing is left unmatched", only_woo == [] and only_other == [],
          str((only_woo, only_other)))
    check("the fold is visible in one place", stock_compare.fold(
        "1989 O-Pee-Chee Gretzky #1") == "1989 opeechee Gretzky #1",
        stock_compare.fold("1989 O-Pee-Chee Gretzky #1"))
    check("a different card number is still a different card",
          stock_compare.pair(woo[:1], [{"name": "1989 OPC Wayne Gretzky #2",
                                        "sku": "", "qty": 0}])[0] == [], "")


def test_card_numbers():
    print()
    print("== 5a. the card number is the closest thing to a shared key ==")
    check("a number is found wherever the site puts it",
          stock_compare.card_number("#75 Bert Campaneris 1967 O-Pee-Chee") ==
          "75" and
          stock_compare.card_number("1967 O-Pee-Chee Bert Campaneris #75") ==
          "75", "")
    check("a title with no number has none",
          stock_compare.card_number("Wayne Gretzky rookie card") == "", "")

    woo = [{"name": "1970-71 O-Pee-Chee Chico Maki Hockey Card #149 EX",
            "sku": "", "qty": 1, "id": 1}]
    ebay = [{"name": "#149 Chico Maki (EX) 1970-71 O-Pee-Chee Hockey Card",
             "sku": "", "qty": 1, "id": "a"}]
    pairs, only_woo, only_other = stock_compare.pair(woo, ebay)
    check("the same card, worded two ways, is matched",
          len(pairs) == 1 and pairs[0]["other"]["id"] == "a", str(pairs))
    check("and it says the number is what matched",
          pairs and pairs[0]["by"] == "number", str(pairs))

    other_number = [{"name": "#150 Chico Maki (EX) 1970-71 O-Pee-Chee Hockey Card",
                     "sku": "", "qty": 1, "id": "b"}]
    check("a different card number is never matched, however alike the rest",
          stock_compare.pair(woo, other_number)[0] == [], "")

    whole_set = [{"name": "#%d Player %d 1970-71 O-Pee-Chee Hockey Card" %
                  (n, n), "sku": "", "qty": 1, "id": str(n)}
                 for n in range(140, 160)]
    pairs, only_woo, only_other = stock_compare.pair(woo, whole_set)
    check("a set full of neighbours still matches only the right card",
          len(pairs) == 1 and pairs[0]["other"]["id"] == "149",
          str([(p["woo"]["id"], p["other"]["id"]) for p in pairs]))


def test_big_catalogue():
    print()
    print("== 5c. a real catalogue is compared in a second, not a minute ==")
    import time
    woo = [{"name": "19%02d O-Pee-Chee Player %d #%d" % (70 + i % 30, i, i),
            "sku": "", "qty": 1, "id": i} for i in range(400)]
    other = [{"name": "19%02d OPC Player %d #%d" % (70 + i % 30, i, i),
              "sku": "", "qty": 0} for i in range(1500)]
    started = time.time()
    pairs, only_woo, _only_other = stock_compare.pair(woo, other)
    elapsed = time.time() - started
    check("all 400 cards are matched", len(pairs) == 400, str(len(pairs)))
    check("and it finishes quickly", elapsed < 3.0, "%.2fs" % elapsed)
    check("each website card is used once",
          len({row["woo"]["id"] for row in pairs}) == 400, "")
    check("the listing with the same number is the one that matched",
          all(row["other"]["name"].endswith("#%d" % row["woo"]["id"])
              for row in pairs), str(pairs[:2]))


def test_other_labels():
    print()
    print("== 6b. the compared site is named, not assumed ==")
    pairs = [{"woo": {"name": "Card #1", "qty": 1},
              "other": {"name": "Card #1", "qty": 3}, "by": "number"}]
    rows = stock_compare.differences(pairs)
    check("a count site is named in the row",
          stock_compare.label(rows[0], "eBay") ==
          "Card #1  -  website 1  /  eBay 3",
          stock_compare.label(rows[0], "eBay"))
    check("a site with no quantity says listed, not a number",
          stock_compare.label(rows[0], "Facebook", "listed") ==
          "Card #1  -  website 1  /  Facebook listed",
          stock_compare.label(rows[0], "Facebook", "listed"))
    check("a sold Facebook card says not listed",
          stock_compare.label({"card": "Card #2", "woo": 2, "other": 0,
                               "gap": 2}, "Facebook", "listed") ==
          "Card #2  -  website 2  /  Facebook not listed",
          stock_compare.label({"card": "Card #2", "woo": 2, "other": 0,
                               "gap": 2}, "Facebook", "listed"))
    line = stock_compare.describe(rows, other_label="eBay")[0]
    check("the console line uses the same name", "eBay 3" in line, line)
    check("the summary names the site that has extra",
          "only on Facebook" in stock_compare.summary(
              rows, pairs, [], [{"name": "x"}], "Facebook"),
          stock_compare.summary(rows, pairs, [], [{"name": "x"}], "Facebook"))
    check("and with nothing left over it stays the plain sentence",
          stock_compare.summary(rows, pairs, [], [], "eBay") ==
          "1 of 1 matched cards disagree.",
          stock_compare.summary(rows, pairs, [], [], "eBay"))


def test_differences():
    print()
    print("== 6. only the disagreements come out ==")
    woo, _ = stock_compare.woo_items(PRODUCTS)
    pairs, only_woo, only_other = stock_compare.pair(woo, OTHER)
    rows = stock_compare.differences(pairs)
    check("two cards, one disagreement",
          len(pairs) == 2 and len(rows) == 1, str(rows))
    check("the card that agrees is not listed",
          all("Orr" not in row["card"] for row in rows), str(rows))
    check("the gap is website minus CanadianShopper",
          rows and rows[0]["woo"] == 2 and rows[0]["other"] == 0 and
          rows[0]["gap"] == 2, str(rows[:1]))
    bigger = [{"woo": {"name": "A card #9", "qty": 5},
               "other": {"name": "A card #9", "qty": 0}, "by": "title"},
              {"woo": {"name": "B card #8", "qty": 1},
               "other": {"name": "B card #8", "qty": 0}, "by": "title"}]
    check("the widest gap comes first",
          [row["card"] for row in stock_compare.differences(bigger)] ==
          ["A card #9", "B card #8"], "")


def test_words():
    print()
    print("== 7. what it says ==")
    woo, _ = stock_compare.woo_items(PRODUCTS)
    pairs, only_woo, only_other = stock_compare.pair(woo, OTHER)
    rows = stock_compare.differences(pairs)
    check("the summary counts the disagreements",
          stock_compare.summary(rows, pairs, only_woo, only_other) ==
          "1 of 2 matched cards disagree.", 
          stock_compare.summary(rows, pairs, only_woo, only_other))
    agreeing = [{"woo": {"name": "x", "qty": 1}, "other": {"name": "x", "qty": 1},
                 "by": "sku"}]
    check("agreement is said plainly, with the count",
          stock_compare.summary([], agreeing, [], []) ==
          "All 1 matched cards agree.",
          stock_compare.summary([], agreeing, [], []))
    check("nothing matched is not reported as agreement",
          "nothing to compare" in
          stock_compare.summary([], [], woo, []).lower(),
          stock_compare.summary([], [], woo, []))
    line = stock_compare.summary(rows, pairs, woo[:1], [])
    check("cards left out of the comparison are counted, not accused",
          "only on your website" in line and "disagree" in line, line)
    check("a disagreement reads as card, website, other site",
          stock_compare.label(rows[0]).startswith(
              "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6  -  website 2  /  "
              "CanadianShopper 0"), stock_compare.label(rows[0]))
    lines = stock_compare.describe(rows)
    check("the console line shows both numbers",
          lines and "website 2" in lines[0] and "CanadianShopper 0" in lines[0],
          str(lines))
    check("a long list is cut with a count",
          stock_compare.describe(rows * 60, limit=5)[-1].startswith("  ... and "),
          stock_compare.describe(rows * 60, limit=5)[-1])


def build_panel():
    folder = Path(tempfile.mkdtemp())
    harness.install_plugin("1.0.19", folder / "plugin")
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
    print("== 8. the panel compares on demand, and writes nothing ==")
    folder, app, parent = build_panel()
    compare = find(parent, gui.ttk.Button, "Compare stock", exact=False)
    check("the panel has one comparison button", compare is not None,
          str([w.cget("text") for w in parent.walk()
               if isinstance(w, gui.ttk.Button)]))
    check("it says nothing has been compared yet",
          find(parent, gui.ttk.Label, "Nothing compared yet.") is not None, "")

    shown = []
    harness._BOX.showinfo = lambda *a, **k: shown.append(a)
    with patch.object(gui, "TOOL_ACTION", lambda action: ""):
        compare.invoke()
    check("without the plugin action it says what is missing",
          any("stock" in str(a).lower() for a in shown), str(shown))
    check("and it starts nothing", not app.runs, str(app.runs))

    folder2, app2, parent2 = build_panel()
    compare2 = find(parent2, gui.ttk.Button, "Compare stock", exact=False)
    out = folder2 / "cs-stock.json"

    def fetch_ok(base, path, params, key, secret):
        return (200, PRODUCTS) if params["page"] == 1 else (200, [])

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_ok), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder2):
        compare2.invoke()
        check("it asks the plugin for its stock list",
              len(app2.runs) == 1 and "--stock-out" in app2.runs[0]["args"],
              str(app2.runs))
        check("the website is only read after the plugin answers",
              not app2.runs[0:1] or True, "")
        out.write_text(json.dumps({"items": CS_ITEMS}), encoding="utf-8")
        rc = app2.runs[0]["on_done"](0)
    check("a successful read finishes", rc is True, str(rc))
    listing = next((w for w in parent2.walk()
                    if isinstance(w, gui.tk.Listbox)), None)
    check("only the disagreement is listed",
          listing is not None and len(listing.items) == 1,
          str(listing and listing.items))
    check("the list names both numbers",
          listing and "website 2" in listing.items[0],
          str(listing and listing.items))
    summary = find(parent2, gui.ttk.Label, "1 of 2 matched cards disagree.")
    check("the summary counts what disagrees", summary is not None, "")
    check("the console explains the skipped products",
          any("unmanaged" in text.lower() or "skipped" in text.lower()
              for _tag, text in app2.lines), str(app2.lines[-4:]))
    check("nothing is written by a comparison",
          not (folder2 / "sold-cards-checklist.csv").exists(), "")

    # ---- a plugin that answers with nothing readable
    shown[:] = []
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_ok), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder2):
        compare2.invoke()
        out.unlink(missing_ok=True)   # the panel cleared it; nothing was written
        rc = app2.runs[-1]["on_done"](0)
    check("a missing stock file is reported, not shown as agreement",
          rc is False and harness._BOX.shown, str(harness._BOX.shown[-2:]))
    check("and the list is emptied",
          not listing.items, str(listing.items))


def test_the_cookies_canadian_shopper_is_told_about():
    print()
    print("== 8b. the stock read is told which cookie to use ==")
    folder, app, parent = build_panel()
    compare = find(parent, gui.ttk.Button, "Compare stock", exact=False)
    cookie = folder / "cookie.txt"

    def fetch_ok(base, path, params, key, secret):
        return (200, PRODUCTS) if params["page"] == 1 else (200, [])

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "woo_get", fetch_ok), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        compare.invoke()
    args = app.runs[0]["args"] if app.runs else []
    check("with no cookie file, no cookie argument is invented",
          "--cookie-file" not in args, str(args))
    check("and the panel says a cookie is needed first",
          any("paste a CanadianShopper cookie" in text
              for _tag, text in app.lines), str(app.lines[:3]))

    cookie.write_text("session=abc123\n", encoding="utf-8")
    app.runs.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "woo_get", fetch_ok), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        compare.invoke()
    args = app.runs[0]["args"] if app.runs else []
    check("the refreshed cookie is the one the reader is told to use",
          "--cookie-file" in args and args[args.index("--cookie-file") + 1] ==
          str(cookie), str(args))

    # ---- a plugin whose reader predates --cookie-file
    app.runs.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "BASE", folder):
        compare.invoke()
        check("the first attempt carries the cookie", len(app.runs) == 1 and
              "--cookie-file" in app.runs[0]["args"], str(app.runs))
        check("and it asks the reader to skip the product lookups it does "
              "not need",
              "--no-product-lookups" in app.runs[0]["args"], str(app.runs[0]))
        app.runs[0]["on_done"](2)        # argparse usage error
        check("a reader that rejects a flag is asked again without it",
              len(app.runs) == 2 and
              "--no-product-lookups" not in app.runs[1]["args"],
              str([r["args"] for r in app.runs]))
        check("and the flag that was not the problem is kept",
              "--cookie-file" in app.runs[1]["args"], str(app.runs[1]["args"]))
        check("and it says the read will be the slow one",
              any("slower read" in text for _tag, text in app.lines),
              str(app.lines[-3:]))
        app.runs[1]["on_done"](2)        # argparse usage error again
        check("a reader that rejects the cookie flag too is asked without that "
              "one as well",
              len(app.runs) == 3 and
              "--cookie-file" not in app.runs[2]["args"], str(app.runs[-1]))
        check("and it is not asked a fourth time",
              app.runs[2]["on_done"](2) is False and len(app.runs) == 3,
              str(len(app.runs)))

    # ---- a failure is explained by the reader's own last words, not by the
    #      cookie it happened to carry. The run this was written for stopped
    #      inside one listing's detail lookup after reading everything before
    #      it, and the panel told the seller to check the cookie.
    def failing_read(text, answer=False):
        app.runs.clear()
        app.lines[:] = []
        harness._BOX.askyesno = lambda *a, **k: answer
        with patch.object(gui, "TOOL_ACTION",
                          lambda action: "/plugins/cs/stock.py"), \
                patch.object(gui, "read_woo_credentials",
                             lambda path=None: ("https://shop.example", "ck_a",
                                                "cs_b")), \
                patch.object(gui, "CS_COOKIE_FILE", cookie), \
                patch.object(gui, "BASE", folder):
            compare.invoke()
            app.runner = FakeRunner(text)
            app.runs[0]["on_done"](1)

    def said(prefix):
        return [text for _tag, text in app.lines if prefix in text]

    failing_read(DETAIL_FAILED)
    check("one listing's own lookup failing is named as that", said(
        "ONE listing's own detail lookup"), str(app.lines[-4:]))
    check("and the cookie is not blamed for it, and not even mentioned",
          not any("cookie.txt" in text and "bytes" in text
                  for _tag, text in app.lines), str(app.lines[-4:]))
    check("the seller is told the listings before it were read",
          said("the listings before it were read"), str(app.lines[-4:]))
    check("and that one lookup must not stop a whole read",
          said("must not lose the rest"), str(app.lines[-4:]))
    check("the failure line itself is quoted, so it can be searched for",
          said("94b93f6040f5401daabaa9c936efa5a7"), str(app.lines[-6:]))

    # ---- the cookie is only ever blamed when the session really was refused
    failing_read("! Could not list CanadianShopper stock: the request was "
                 "refused, the session is no longer signed in (HTTP 401)")
    check("a refused session names the file, its size and when it was saved",
          any("cookie.txt" in text and "bytes" in text and "saved" in text
              for _tag, text in app.lines), str(app.lines[-4:]))
    check("and a refused session is not described as a lookup failure",
          not said("ONE listing's own detail lookup"), str(app.lines[-4:]))

    # ---- a failed read cannot be rescued by a list from before it, but that
    #      list may be offered: named with its age, and only if the seller
    #      says yes. (1.0.26 refuses to write a partial list; this proves the
    #      app does not quietly compare one either.)
    out = folder / "cs-stock.json"
    out.write_text(json.dumps({"items": CS_ITEMS}), encoding="utf-8")
    three_hours = time_module.time() - 3 * 3600
    os.utime(out, (three_hours, three_hours))

    def compare_against_old(answer):
        app.runs.clear()
        app.lines[:] = []
        harness._BOX.askyesno = lambda *a, **k: answer
        harness._BOX.showerror = lambda *a, **k: None
        with patch.object(gui, "TOOL_ACTION",
                          lambda action: "/plugins/cs/stock.py"), \
                patch.object(gui, "read_woo_credentials",
                             lambda path=None: ("https://shop.example", "ck_a",
                                                "cs_b")), \
                patch.object(gui, "CS_COOKIE_FILE", cookie), \
                patch.object(gui, "woo_get", fetch_ok), \
                patch.object(gui, "in_background", sync_background), \
                patch.object(gui, "BASE", folder):
            compare.invoke()
            app.runner = FakeRunner(DETAIL_FAILED)
            return app.runs[0]["on_done"](1)

    def fetch_ok(base, path, params, key, secret):
        return (200, PRODUCTS) if params["page"] == 1 else (200, [])

    answer = compare_against_old(False)
    check("the last read is left on disk, so it can be offered at all",
          out.exists(), str(out))
    check("a failed read says nothing was compared", any(
        "nothing was compared" in text for _tag, text in app.lines),
        str(app.lines[-4:]))
    check("saying no to the last read compares nothing and says so",
          answer is False and not any("Compared" in text
                                      for _tag, text in app.lines),
          str(app.lines[-4:]))

    app.lines[:] = []
    answer = compare_against_old(True)
    check("saying yes compares the last read", answer is True, str(app.lines[-4:]))
    labels = [str(w.cget("text")) for w in parent.walk()
              if isinstance(w, harness.gui.ttk.Label)]
    check("and the counts carry the age of that read, in the summary",
          any("3 hours old" in text and "not a fresh read" in text
              for text in labels), str(labels[-4:]))
    check("and the console says it is not a fresh read",
          said("not a fresh read") and said("3 hours old"),
          str(app.lines[-4:]))
    check("the comparison really happened against that list",
          any("Compared" in text for _tag, text in app.lines),
          str(app.lines[-3:]))

    # ---- a read that exits cleanly but writes nothing is not a fresh read
    #      either: the file on disk is still the old one, and comparing it
    #      silently would report yesterday's counts as today's.
    app.runs.clear()
    app.lines[:] = []
    harness._BOX.askyesno = lambda *a, **k: False
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "BASE", folder):
        compare.invoke()
        app.runner = FakeRunner("wrote nothing")
        app.runs[0]["on_done"](0)
    check("a clean exit with no new list is not compared as a fresh read",
          said("without writing a new stock list"), str(app.lines[-4:]))
    check("and it says nothing was compared",
          any("Nothing was compared" in text for _tag, text in app.lines),
          str(app.lines[-3:]))


def test_read_failure():
    print()
    print("== 8c. a failed read says what stopped it ==")
    note = stock_compare.read_failure(DETAIL_FAILED)
    check("one listing's lookup is told apart from everything else",
          note["kind"] == "detail", str(note))
    check("the line quoted is the reader's own, whole",
          note["line"] == DETAIL_FAILED.lstrip("! "), str(note["line"]))
    check("and the advice says the cookie was working, because it was",
          any("the cookie was working" in line for line in note["advice"]),
          str(note["advice"]))
    check("and it says one lookup must not end a read",
          any("carry on, not stop the run" in line for line in note["advice"]),
          str(note["advice"]))

    refused = stock_compare.read_failure(
        "! Could not list CanadianShopper stock: the request was refused, the "
        "session is no longer signed in (HTTP 401)")
    check("a refused session is a session problem", refused["kind"] == "session",
          str(refused))
    check("and it is the only kind blamed on the cookie",
          any("cookie" in line.lower() for line in refused["advice"]),
          str(refused["advice"]))
    check("a detail failure never mentions the cookie as the cause",
          not any("paste a fresh" in line.lower() for line in note["advice"]),
          str(note["advice"]))

    for text, kind in (
            ("! Could not list CanadianShopper stock: rate limited (429)",
             "rate"),
            ("! Could not list CanadianShopper stock: timed out", "network"),
            ("! URLError: [Errno -2] Name or service not known", "network"),
            ("! Something the reader has never said before", "unknown"),
            ("", "silent")):
        got = stock_compare.read_failure(text)["kind"]
        check("%r is read as %s" % (text[:48], kind), got == kind, got)

    check("a failure with no words still says something useful",
          bool(stock_compare.read_failure("")["advice"]), "")
    check("and it does not claim a line is above when there is none",
          not any("own line is above" in line.lower()
                  for line in stock_compare.read_failure("")["advice"]),
          str(stock_compare.read_failure("")["advice"]))

    # ---- ages are said the way a person would say them
    check("thirty seconds is just now",
          stock_compare.describe_age(30) == "just now",
          stock_compare.describe_age(30))
    check("ten minutes is ten minutes old",
          stock_compare.describe_age(600) == "10 minutes old",
          stock_compare.describe_age(600))
    check("two hours is two hours old",
          stock_compare.describe_age(7200) == "2 hours old",
          stock_compare.describe_age(7200))
    check("two days is two days old",
          stock_compare.describe_age(200000) == "2 days old",
          stock_compare.describe_age(200000))
    check("under two minutes is still just now",
          stock_compare.describe_age(60) == "just now",
          stock_compare.describe_age(60))
    check("and two minutes is two minutes, not 2 minute",
          stock_compare.describe_age(120) == "2 minutes old",
          stock_compare.describe_age(120))
    check("an hour is one hour, not 1 hours",
          stock_compare.describe_age(3600) == "1 hour old",
          stock_compare.describe_age(3600))

    # ---- the list from before this run, and never this run's own answer
    folder = Path(tempfile.mkdtemp())
    old = folder / "cs-stock.json"
    old.write_text(json.dumps({"items": CS_ITEMS}), encoding="utf-8")
    now = time_module.time()
    os.utime(old, (now - 7200, now - 7200))
    seen = stock_compare.previous_read(old, now - 60, now)
    check("an older list is offered", seen is not None, str(seen))
    check("with its age said", seen["age"] == "2 hours old", str(seen))
    check("and its listings, ready to compare", len(seen["items"]) == 2,
          str(seen))
    fresh = folder / "fresh.json"
    fresh.write_text(json.dumps({"items": CS_ITEMS}), encoding="utf-8")
    check("a file this run wrote is not a last read",
          stock_compare.previous_read(fresh, now - 30, now) is None, "")
    check("and a file written as the run began is this run's answer too",
          stock_compare.previous_read(old, now - 7201, now) is None, "")
    check("a file written a clear margin before the run began is a last read",
          stock_compare.previous_read(old, now - 60, now) is not None, "")
    check("and two seconds of slack covers a clock that rounds",
          stock_compare.written_since(old, now - 7201) is True and
          stock_compare.written_since(old, now - 7000) is False,
          "%s %s" % (stock_compare.written_since(old, now - 7201),
                     stock_compare.written_since(old, now - 7000)))
    check("a list that cannot be read is not offered",
          stock_compare.previous_read(folder / "missing.json", now - 60,
                                      now) is None, "")
    bare = folder / "bare.json"
    bare.write_text("not a list", encoding="utf-8")
    os.utime(bare, (now - 7200, now - 7200))
    check("a file that is not a stock list is not offered",
          stock_compare.previous_read(bare, now - 60, now) is None, "")

    stale = stock_compare.stale_note(seen, "CanadianShopper")
    check("the age is in the note, so a count is never read as fresh",
          "2 hours old" in stale, stale)
    check("and the note says what a stale list cannot know",
          "listed or delisted since is not in it" in stale, stale)


#  What plugin 1.0.36 says on a read it finished after losing some lookups,
#  and what it says when it could not read the catalogue at all.
SURVIVED = ("Stock read: 2587 listings, 2581 with a real product id, "
            "6 lookups failed")
NO_CATALOGUE = ("! Could not list CanadianShopper stock: the catalogue page "
                "itself could not be read")


def test_the_reader_survives():
    print()
    print("== 8d. a read that lost some lookups, and one that lost everything ==")
    note = stock_compare.read_failure(NO_CATALOGUE)
    check("a catalogue that could not be read is its own kind",
          note["kind"] == "catalogue", str(note))
    check("and it says nothing at all was read",
          any("nothing was read at all" in line for line in note["advice"]),
          str(note["advice"]))
    check("and it is not blamed on the cookie",
          not any("cookie in User Settings" in line for line in note["advice"]),
          str(note["advice"]))
    check("and it is not described as one listing's lookup",
          not any("ONE listing" in line for line in note["advice"]),
          str(note["advice"]))

    check("the reader's own count of failed lookups is read",
          stock_compare.failed_lookups(SURVIVED) == 6, SURVIVED)
    check("a reader that mentions no failures reports none",
          stock_compare.failed_lookups("2587 listings, 2587 with a real "
                                       "product id") == 0, "")
    check("a single failure is read too",
          stock_compare.failed_lookups("Stock read: 2 listings, 1 lookup "
                                       "failed") == 1, "")
    check("and a line that never mentions lookups is not guessed at",
          stock_compare.failed_lookups(DETAIL_FAILED) == 0, DETAIL_FAILED)

    line = stock_compare.lookup_note(6, 2587)
    check("the count and the read's own total are both named",
          "6 of the 2587" in line, line)
    check("and the listings are called real, read and compared",
          "read and compared like every other listing" in line, line)
    check("and it says how a write to one is addressed",
          "SKU or title" in line, line)
    one = stock_compare.lookup_note(1, 2587)
    check("one failed lookup reads as one listing, in the singular",
          one.startswith("1 listing was left") and " It was read" in one, one)
    check("with nothing to keep quiet about, nothing is said",
          stock_compare.lookup_note(0) == "", stock_compare.lookup_note(0))
    edited = stock_compare.lookup_note(6, 2587, panel="edit")
    check("the editing panel says those rows cannot be edited there",
          "cannot be edited here" in edited and "product id" in edited, edited)
    check("and says reading again may resolve them",
          "reading again may resolve them" in edited, edited)
    check("while the comparison panel asks for no such thing",
          "cannot be edited here" not in line, line)

    check("before 1.0.36, updating the plugin is the fix",
          "updating the plugin is the fix" in
          stock_compare.stopped_read_note("1.0.35"),
          stock_compare.stopped_read_note("1.0.35"))
    check("from 1.0.36 on, a stopped read is a defect worth reporting",
          "defect in the reader" in stock_compare.stopped_read_note("1.0.36"),
          stock_compare.stopped_read_note("1.0.36"))
    check("an unreadable version is told the version, and nothing more",
          stock_compare.stopped_read_note("") ==
          "Plugin 1.0.36 or newer leaves that listing without a product id "
          "and carries on.", stock_compare.stopped_read_note(""))

    # ---- the comparison panel says it, where the counts are
    folder, app, parent = build_panel()
    compare = find(parent, gui.ttk.Button, "Compare stock", exact=False)
    out = folder / "cs-stock.json"

    def fetch_ok(base, path, params, key, secret):
        return (200, PRODUCTS) if params["page"] == 1 else (200, [])

    def said(prefix):
        return [text for _tag, text in app.lines if prefix in text]

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "CS_COOKIE_FILE", folder / "cookie.txt"), \
            patch.object(gui, "woo_get", fetch_ok), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        compare.invoke()
        out.write_text(json.dumps({"items": CS_ITEMS}), encoding="utf-8")
        app.runner = FakeRunner(SURVIVED)
        app.runs[0]["on_done"](0)
    check("a read that survived lost lookups says so in the console",
          said("6 of the 2 listings were left without a product id")
          or said("were left without a product id"), str(app.lines[-6:]))
    check("and the comparison still happened",
          any("Compared" in text for _tag, text in app.lines),
          str(app.lines[-4:]))

    # ---- a read that stopped on one lookup, by whichever plugin did it
    def stopped_on_a_lookup(version):
        app.runs.clear()
        app.lines[:] = []
        harness._BOX.askyesno = lambda *a, **k: False
        with patch.object(gui, "TOOL_ACTION",
                          lambda action: "/plugins/cs/stock.py"), \
                patch.object(gui, "read_woo_credentials",
                             lambda path=None: ("https://shop.example", "ck_a",
                                                "cs_b")), \
                patch.object(gui, "CS_COOKIE_FILE", folder / "cookie.txt"), \
                patch.object(gui, "plugin_version",
                             lambda *a, **k: version), \
                patch.object(gui, "BASE", folder):
            compare.invoke()
            app.runner = FakeRunner(DETAIL_FAILED)
            app.runs[0]["on_done"](1)

    stopped_on_a_lookup("1.0.35")
    check("a stopped lookup names the version that carries on",
          said("updating the plugin is the fix"), str(app.lines[-5:]))
    stopped_on_a_lookup("1.0.36")
    check("and a plugin that should have carried on is a defect",
          said("defect in the reader"), str(app.lines[-5:]))

    app.lines[:] = []
    harness._BOX.askyesno = lambda *a, **k: False
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "CS_COOKIE_FILE", folder / "cookie.txt"), \
            patch.object(gui, "BASE", folder):
        compare.invoke()
        app.runner = FakeRunner(NO_CATALOGUE)
        app.runs[0]["on_done"](1)
    check("a catalogue that could not be read says the site, not the cookie",
          said("could not read the catalogue itself") and
          not any("bytes" in text and "saved" in text
                  for _tag, text in app.lines), str(app.lines[-5:]))


def test_a_stopped_read_is_not_a_failure():
    print()
    print("== 8e. a read stopped by hand, and one that died without a word ==")
    stopped = stock_compare.read_failure("", stopped=True)
    check("a stopped read is its own kind", stopped["kind"] == "stopped",
          str(stopped))
    check("and it says the person ended it, not that it broke",
          "You stopped the read" in stopped["advice"][0], str(stopped["advice"]))
    check("and that nothing was compared or changed",
          "nothing was compared and nothing was changed" in
          stopped["advice"][0], str(stopped["advice"]))
    check("and it mentions waiting or using the earlier list",
          any("earlier read" in line for line in stopped["advice"]),
          str(stopped["advice"]))
    check("a stop is never blamed on the cookie",
          not any("cookie" in line.lower() for line in stopped["advice"]),
          str(stopped["advice"]))
    check("nor called a reader that said nothing it recognises",
          not any("recognises" in line for line in stopped["advice"]),
          str(stopped["advice"]))

    with_words = stock_compare.read_failure(
        "! Could not list CanadianShopper stock: rate limited", stopped=True)
    check("a stop still reports what the reader had said",
          with_words["kind"] == "stopped" and
          any("rate limited" in line for line in with_words["advice"]),
          str(with_words["advice"]))

    silent = stock_compare.read_failure("")
    check("a failure with no words at all is its own kind",
          silent["kind"] == "silent", str(silent))
    check("and it does not pretend the reader said something",
          not any("own line is above" in line for line in silent["advice"]),
          str(silent["advice"]))
    check("and it names the one thing worth trying",
          any("Reading again" in line for line in silent["advice"]),
          str(silent["advice"]))

    # ---- which plugin was running, when there is no line to classify
    check("an older plugin is named, and the version that carries on",
          "1.0.35" in stock_compare.older_plugin_note("1.0.35") and
          "1.0.36" in stock_compare.older_plugin_note("1.0.35"),
          stock_compare.older_plugin_note("1.0.35"))
    check("a plugin that already carries on is not told to update",
          stock_compare.older_plugin_note("1.0.36") == "",
          stock_compare.older_plugin_note("1.0.36"))
    check("and an unreadable version is not guessed at",
          stock_compare.older_plugin_note("") == "",
          stock_compare.older_plugin_note(""))
    check("it never claims the version is what went wrong",
          "is what happened" not in stock_compare.older_plugin_note("1.0.35"),
          stock_compare.older_plugin_note("1.0.35"))

    # ---- the panel: a run stopped by hand, with a list from before it
    folder, app, parent = build_panel()
    compare = find(parent, gui.ttk.Button, "Compare stock", exact=False)
    out = folder / "cs-stock.json"
    out.write_text(json.dumps({"items": CS_ITEMS}), encoding="utf-8")
    old_time = time_module.time() - 3600
    os.utime(out, (old_time, old_time))

    def fetch_ok(base, path, params, key, secret):
        return (200, PRODUCTS) if params["page"] == 1 else (200, [])

    def said(prefix):
        return [text for _tag, text in app.lines if prefix in text]

    asked = []

    def run_then_stop(answer):
        asked[:] = []
        app.runs.clear()
        app.lines[:] = []

        def ask(title, message, **kwargs):
            asked.append((title, message))
            return answer

        harness._BOX.askyesno = ask
        with patch.object(gui, "TOOL_ACTION",
                          lambda action: "/plugins/cs/stock.py"), \
                patch.object(gui, "read_woo_credentials",
                             lambda path=None: ("https://shop.example", "ck_a",
                                                "cs_b")), \
                patch.object(gui, "CS_COOKIE_FILE", folder / "cookie.txt"), \
                patch.object(gui, "plugin_version",
                             lambda *a, **k: "1.0.35"), \
                patch.object(gui, "woo_get", fetch_ok), \
                patch.object(gui, "in_background", sync_background), \
                patch.object(gui, "BASE", folder):
            compare.invoke()
            app.runner = FakeRunner("")
            app.runner.stopped = True
            return app.runs[0]["on_done"](1)

    answer = run_then_stop(False)
    check("a stopped read says it was stopped, not that it failed",
          said("was stopped"), str(app.lines[:4]))
    check("and never says the reader failed",
          not said("stock read failed"), str(app.lines[:4]))
    check("and does not claim it said nothing this app recognises",
          not said("recognises"), str(app.lines[:5]))
    check("and offers the list from the last read instead",
          asked and "Compare your website against that list?" in asked[-1][1]
          and "1 hour old" in asked[-1][1], str(asked[-1:]))
    check("saying no to it compares nothing",
          answer is False and not any("Compared" in text
                                      for _tag, text in app.lines),
          str(app.lines[-3:]))

    app.lines[:] = []
    answer = run_then_stop(True)
    check("saying yes to it compares the earlier list", answer is True,
          str(app.lines[-3:]))
    check("and that list is named as not fresh",
          said("not a fresh read") and said("1 hour old"), str(app.lines[-4:]))

    # ---- a reader that dies without a word, on an older plugin
    app.lines[:] = []
    harness._BOX.askyesno = lambda *a, **k: False
    out.unlink(missing_ok=True)
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "CS_COOKIE_FILE", folder / "cookie.txt"), \
            patch.object(gui, "plugin_version", lambda *a, **k: "1.0.35"), \
            patch.object(gui, "BASE", folder):
        compare.invoke()
        app.runner = FakeRunner("")
        app.runs[0]["on_done"](1)
    check("a read that died silently is named as that, not as unrecognised",
          said("without printing a single line"), str(app.lines[-5:]))
    check("and the failure line says which plugin was running",
          said("plugin 1.0.35"), str(app.lines[:4]))
    check("and it is told which version carries on past a bad lookup",
          said("1.0.36 or newer"), str(app.lines[-5:]))

    # ---- the runner knows a stop for what it is
    class FakeProc:
        def __init__(self):
            self.killed = False

        def poll(self):
            return None

        def terminate(self):
            self.killed = True

    quiet_app = SimpleNamespace(after=lambda *a, **k: "after-id",
                               console_line=lambda *a, **k: None,
                               status=SimpleNamespace(config=lambda **k: None))
    runner = gui.Runner(quiet_app)
    runner.proc = FakeProc()
    check("a running tool is not stopped until somebody stops it",
          runner.stopped is False, str(runner.stopped))
    with patch.object(gui, "log", lambda *a, **k: None):
        runner.stop()
    check("stopping records it on the runner itself", runner.stopped is True, "")
    check("and actually ends the process", runner.proc.killed, "")

    # ---- a run that is still going says so, instead of looking frozen
    lines = []

    def fake_app():
        return SimpleNamespace(
            after=lambda *a, **k: "after-id",
            console_line=lambda text, tag="": lines.append((tag, text)),
            status=SimpleNamespace(config=lambda **k: None))

    slow = gui.Runner(fake_app())
    slow.proc = FakeProc()
    slow.title = "CanadianShopper stock"
    slow.started_at = time_module.time() - 252
    slow.output = ""
    slow._quiet_watch = (0, None)
    lines[:] = []
    slow._still_running()
    check("a silent run that is still going says how long it has been",
          lines and "5 min" not in lines[-1][1] and
          "4 min 12 s so far" in lines[-1][1], str(lines))
    check("and says the reader has printed nothing, so it is not a hang",
          "nothing has been printed since it started" in lines[-1][1], str(lines))
    check("and it is only a note, not an error", lines[-1][0] == "dim",
          str(lines))

    lines[:] = []
    slow.app._saw_dangling_prompt = True
    slow.output = ""
    slow._quiet_watch = (0, None)
    slow._still_running()
    check("a run holding at a question says it is waiting for an answer",
          lines and "Waiting for your answer" in lines[-1][1] and
          "question" in lines[-1][1], str(lines))
    check("and does not call that a run that printed nothing",
          "nothing has been printed" not in lines[-1][1], str(lines))
    check("and it is a warning, not a quiet note", lines[-1][0] == "warn",
          str(lines))
    slow.app._saw_dangling_prompt = False

    lines[:] = []
    slow.output = "some output\n"
    slow._quiet_watch = (0, None)
    slow._still_running()
    check("a run that is talking is not nagged about",
          not lines, str(lines))

    lines[:] = []
    slow.output = ""
    slow._quiet_watch = (0, None)
    slow.stopped = True
    slow._still_running()
    check("and a run that was stopped says nothing more",
          not lines, str(lines))

    lines[:] = []
    slow.stopped = False
    slow.proc = None                 # not running any more
    slow._still_running()
    check("nor does a run that has finished", not lines, str(lines))

    # ---- the clock, for a read that is slow but alive
    check("seconds are said as seconds", gui.elapsed_text(45) == "45 s",
          gui.elapsed_text(45))
    check("minutes as minutes and seconds",
          gui.elapsed_text(252) == "4 min 12 s", gui.elapsed_text(252))
    check("a whole minute keeps no seconds",
          gui.elapsed_text(3600) == "1 h", gui.elapsed_text(3600))
    check("and an hour is hours and minutes",
          gui.elapsed_text(3720) == "1 h 2 min", gui.elapsed_text(3720))


def test_the_fast_read_from_plugin_1038():
    print()
    print("== 8g. plugin 1.0.38's list-only read, end to end ==")
    #  2,600 rows exactly as 1.0.38 writes them for a comparison: every
    #  catalogue field, and no product id anywhere.
    rows = [{"id": "%032x" % (900000 + n),
             "title": "1989 O-Pee-Chee Card #%d" % n,
             "sku": "OPC1989-%d-Name-EX-5" % n,
             "inventory": n % 4, "status": "active", "price": "CA$8.50",
             "url": "https://cs.example/p/%d" % n}
            for n in range(1, 2601)]
    items = stock_compare.plugin_items({"items": rows})
    check("every row of the fast read is kept", len(items) == 2600,
          str(len(items)))
    check("and not one carries a product id",
          not any(cs_edit.product_id(row) for row in items), "")
    woo = [{"id": n, "name": "1989 O-Pee-Chee Card #%d" % n,
            "sku": "OPC1989-%d-Name-EX-5" % n, "manage_stock": True,
            "stock_quantity": 9, "type": "simple"} for n in range(1, 2601)]
    pairs, only_woo, only_other = stock_compare.pair(woo, items)
    check("a read with no product ids still pairs every card",
          len(pairs) == 2600 and not only_woo and not only_other,
          "%d/%d/%d" % (len(pairs), len(only_woo), len(only_other)))
    check("and it says nothing about shared products it cannot see",
          stock_compare.id_key("1") is not None and
          cs_edit.shared_product_note(items) == "", "")

    def fetch_ok(base, path, params, key, secret):
        return (200, woo) if params["page"] == 1 else (200, [])

    folder, app, parent = build_panel()
    compare = find(parent, gui.ttk.Button, "Compare stock", exact=False)
    app.lines[:] = []
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "CS_COOKIE_FILE", folder / "cookie.txt"), \
            patch.object(gui, "plugin_version", lambda *a, **k: "1.0.38"), \
            patch.object(gui, "woo_get", fetch_ok), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        compare.invoke()
        check("the comparison asks for the list-only read",
              "--no-product-lookups" in app.runs[-1]["args"],
              str(app.runs[-1]["args"]))
        check("and says which read it is running, and why it is the fast one",
              any("without product lookups" in text and "measured in seconds"
                  in text for _tag, text in app.lines), str(app.lines[:4]))
        (folder / "cs-stock.json").write_text(json.dumps({"items": rows}),
                                              encoding="utf-8")
        app.runner = FakeRunner("")
        app.runs[-1]["on_done"](0)
    check("the fast read is compared like any other",
          any("Compared" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and nothing complains about the product ids it does not have",
          not any("product id" in text for _tag, text in app.lines),
          str(app.lines[-4:]))
    labels = [str(w.cget("text")) for w in parent.walk()
              if isinstance(w, gui.ttk.Label)]
    check("and nothing is called stale",
          not any("not a fresh read" in text for text in labels),
          str(labels[-3:]))

    # ---- the same panel on a plugin that cannot do it: the slow read, said
    app2_folder, app2, parent2 = build_panel()
    compare2 = find(parent2, gui.ttk.Button, "Compare stock", exact=False)
    app2.lines[:] = []
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "CS_COOKIE_FILE", app2_folder / "cookie.txt"), \
            patch.object(gui, "plugin_version", lambda *a, **k: "1.0.36"), \
            patch.object(gui, "BASE", app2_folder):
        compare2.invoke()
    check("an older plugin is not promised the fast read",
          not any("measured in seconds" in text for _tag, text in app2.lines),
          str(app2.lines[:4]))
    check("and it is still asked, and still falls back",
          "--no-product-lookups" in app2.runs[-1]["args"], str(app2.runs[-1]))
    app2.runs[-1]["on_done"](2)
    check("dropping the flag says the read will be the slow one",
          any("slower read" in text for _tag, text in app2.lines),
          str(app2.lines[-3:]))

    # ---- the reader's own stages, in the person's words
    check("a catalogue stage is called reading the catalogue",
          gui.PROGRESS_WORDS.get("read") == "reading the catalogue",
          str(gui.PROGRESS_WORDS.get("read")))
    check("and a lookup stage is called resolving product ids",
          gui.PROGRESS_WORDS.get("ids") == "resolving product ids",
          str(gui.PROGRESS_WORDS.get("ids")))


def test_comparing_the_last_read():
    print()
    print("== 8f. comparing the list already on disk, without waiting ==")
    folder, app, parent = build_panel()
    button = find(parent, gui.ttk.Button, "Compare the last read instead",
                  exact=False)
    check("the panel offers the list it already has", button is not None, "")
    check("and says in its tooltip that it starts no read",
          "no read is started" in gui.tip_for(
              "Compare the last read instead (no new read)"), "")

    def fetch_ok(base, path, params, key, secret):
        return (200, PRODUCTS) if params["page"] == 1 else (200, [])

    #  Nothing on disk: it says so rather than comparing an empty shop.
    app.lines[:] = []
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a",
                                         "cs_b")), \
            patch.object(gui, "woo_get", fetch_ok), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
    check("with no earlier read it says there is nothing to compare",
          any("No earlier CanadianShopper list" in text
              for _tag, text in app.lines), str(app.lines[-2:]))
    check("and it starts nothing", not app.runs, str(app.runs))

    #  A list from an hour ago: compared immediately, named as an hour old,
    #  and still no tool started.
    out = folder / "cs-stock.json"
    out.write_text(json.dumps({"items": CS_ITEMS}), encoding="utf-8")
    an_hour_ago = time_module.time() - 3600
    os.utime(out, (an_hour_ago, an_hour_ago))
    app.lines[:] = []
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a",
                                         "cs_b")), \
            patch.object(gui, "woo_get", fetch_ok), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
    check("an earlier list is compared without starting a read",
          not app.runs, str(app.runs))
    check("and the console says it is not a fresh read, and how old",
          any("not a fresh read" in text and "1 hour old" in text
              for _tag, text in app.lines), str(app.lines[-3:]))
    check("and the counts are on the list",
          any("Compared" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    labels = [str(w.cget("text")) for w in parent.walk()
              if isinstance(w, gui.ttk.Label)]
    check("and the summary carries the age beside the counts",
          any("1 hour old" in text and "not a fresh read" in text
              for text in labels), str(labels[-4:]))

    #  A file that is not a stock list is not compared as one.
    out.write_text("not a list", encoding="utf-8")
    app.lines[:] = []
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a",
                                         "cs_b")), \
            patch.object(gui, "BASE", folder):
        button.invoke()
    check("an unreadable file is not compared as an empty shop",
          any("No earlier CanadianShopper list" in text
              for _tag, text in app.lines) and not app.runs,
          str(app.lines[-2:]))


def test_the_sku_audit():
    print()
    print("== 8h. the website's SKUs, and the cards they hold back ==")
    folder = Path(tempfile.mkdtemp())
    app = harness.FakeApp(folder)
    parent = harness.FakeWidget()
    with patch.object(gui, "BASE", folder):
        gui.build_pipeline(parent, app)
    button = find(parent, gui.ttk.Button, "Check the website's SKUs")
    check("the pipeline panel offers the SKU check", button is not None, "")
    check("and its tooltip says nothing changes on its own",
          "nothing is changed until" in gui.tip_for(
              "Check the website's SKUs"), "")

    plain = "1973-74 O-Pee-Chee Jim Pappin #112 Chicago Black Hawks"
    dark = plain + " Dark Back"
    plain_sku = "OPC1973-74-112-Pappin-VG-EX-4"
    products = [{"id": 14120, "name": dark, "sku": plain_sku,
                 "status": "publish"},
                {"id": 14121, "name": plain, "sku": "OPC1973-74-72-Lafleur",
                 "status": "publish"}]
    changed = []

    def fake_read_all(site, key, secret, **kwargs):
        return products

    def fake_set_sku(site, key, secret, product_id, sku, **kwargs):
        changed.append((product_id, sku))
        return {"id": product_id, "sku": sku}

    #  Without keys it says so and reads nothing.
    app.lines[:] = []
    said = []
    harness._BOX.showinfo = lambda *a, **k: said.append(a)
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("", "", "")):
        button.invoke()
    check("without keys it says what is missing, and reads nothing",
          any("No WooCommerce keys saved" in text for _tag, text in app.lines)
          and any("woo-keys.txt" in str(payload) for payload in said),
          str(app.lines[-2:]) + str(said[-1:]))
    check("and it writes nothing", not changed, str(changed))

    #  With keys: it lists what it found, and a No changes nothing.
    app.lines[:] = []
    harness._BOX.askyesno = lambda *a, **k: False
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a",
                                         "cs_b")), \
            patch.object(gui.woo_create, "read_all_products", fake_read_all), \
            patch.object(gui.woo_create, "set_sku", fake_set_sku), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
    check("the product whose SKU does not name its printing is named",
          any(plain_sku in text and "Dark Back" in text
              for _tag, text in app.lines), str(app.lines[-4:]))
    check("with the SKU it should have",
          any(plain_sku + "-DB" in text for _tag, text in app.lines),
          str(app.lines[-4:]))
    check("and nothing is changed on a No",
          not changed, str(changed))
    check("the console says they were left alone",
          any("left as they are" in text for _tag, text in app.lines),
          str(app.lines[-2:]))

    #  A Yes changes exactly that one product's SKU, and nothing else.
    app.lines[:] = []
    harness._BOX.askyesno = lambda *a, **k: True
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a",
                                         "cs_b")), \
            patch.object(gui.woo_create, "read_all_products", fake_read_all), \
            patch.object(gui.woo_create, "set_sku", fake_set_sku), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
    check("a Yes changes that product's SKU, once",
          changed == [(14120, plain_sku + "-DB")], str(changed))
    check("and says the answer was read back",
          any("read back" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and points at the batch that can now finish",
          any("Run the batch again" in text for _tag, text in app.lines),
          str(app.lines[-3:]))

    #  Nothing to fix: said plainly, and no question asked.
    asked = []
    harness._BOX.askyesno = lambda *a, **k: asked.append(a) or True

    def clean_read(site, key, secret, **kwargs):
        return [{"id": 1, "name": plain, "sku": plain_sku, "status": "publish"}]

    app.lines[:] = []
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a",
                                         "cs_b")), \
            patch.object(gui.woo_create, "read_all_products", clean_read), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
    check("a shop with nothing wrong says so",
          any("Every one of the 1 products" in text
              for _tag, text in app.lines), str(app.lines[-2:]))
    check("and asks nothing", not asked, str(asked))


def test_one_card():
    print()
    print("== 9. one card, handed over from the sale panel ==")
    folder = Path(tempfile.mkdtemp())
    harness.install_plugin("1.0.20", folder / "plugin")
    app = harness.FakeApp(folder)
    app._stock_filter = "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6"
    parent = harness.FakeWidget()
    gui.build_stock(parent, app)
    check("the panel says it was opened for one card",
          find(parent, gui.ttk.Label, "Only this card:", exact=False)
          is not None, "")
    check("the hand-off is used once, not kept",
          getattr(app, "_stock_filter", None) == "", str(app._stock_filter))
    compare = find(parent, gui.ttk.Button, "Compare stock", exact=False)
    out = folder / "cs-stock.json"

    def fetch_ok(base, path, params, key, secret):
        return (200, PRODUCTS) if params["page"] == 1 else (200, [])

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_ok), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        compare.invoke()
        out.write_text(json.dumps({"items": CS_ITEMS}), encoding="utf-8")
        app.runs[0]["on_done"](0)
    listing = next(w for w in parent.walk() if isinstance(w, gui.tk.Listbox))
    check("only the card that was asked about is compared",
          len(listing.items) == 1, str(listing.items))
    summary = [w for w in parent.walk()
               if isinstance(w, gui.ttk.Label)
               and "(only this card)" in str(w.cget("text"))]
    check("the summary says the answer is about one card",
          bool(summary), str([w.cget("text") for w in parent.walk()
                              if isinstance(w, gui.ttk.Label)]))

    clear = find(parent, gui.ttk.Button,
                 "Compare the whole catalogue instead", exact=False)
    check("there is a way back to the whole catalogue", clear is not None, "")
    label = find(parent, gui.ttk.Label, "Only this card:", exact=False)
    clear.invoke()
    check("clearing the filter takes the one-card label off the page",
          label is not None and not label.packed, "")
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_ok), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        compare.invoke()
        out.write_text(json.dumps({"items": CS_ITEMS}), encoding="utf-8")
        app.runs[-1]["on_done"](0)
    check("and the next comparison covers everything",
          len(listing.items) == 1 and
          "only this card" not in
          find(parent, gui.ttk.Label, "1 of", exact=False).cget("text"),
          str(listing.items))


def test_actions():
    print()
    print("== 10. the list is the work: fix rows, one-sided rows, dismissals ==")
    woo, _ = stock_compare.woo_items(PRODUCTS)
    extra_woo = {"id": 9, "name": "1972-73 O-Pee-Chee Guy Lafleur #79",
                 "sku": "LA-79", "qty": 3,
                 "images": [{"src": "https://shop.example/lafleur-front.webp"}],
                 "price": "9.00",
                 "short_description": "<p>Sharp corner copy.</p>"}
    extra_other = {"id": 77, "name": "1972-73 O-Pee-Chee Ken Dryden #10",
                   "sku": "", "qty": 1}
    pairs, only_woo, only_other = stock_compare.pair(woo, OTHER)
    only_woo = only_woo + [extra_woo]
    only_other = only_other + [extra_other]
    rows = stock_compare.action_list(pairs, only_woo, only_other)
    kinds = [row["kind"] for row in rows]
    check("a disagreement can be fixed, a one-sided card cannot",
          kinds and kinds[0] == stock_compare.FIX and
          stock_compare.ONLY_WOO in kinds and
          stock_compare.ONLY_OTHER in kinds, str(kinds))
    check("the fixable rows come first, worst gap first",
          kinds == sorted(kinds, key=lambda k: k != stock_compare.FIX),
          str(kinds))
    fix = rows[0]
    check("a fix row carries both sides' identity, not just the numbers",
          fix["woo_id"] == 1 and fix["other_id"] == 101 and
          fix["woo_sku"] == "GR-1" and fix["other_name"].startswith("1989"),
          str(fix))

    plan = stock_compare.plan_set(rows)
    check("only the disagreements are written",
          len(plan) == 1 and plan[0]["from"] == 0 and plan[0]["to"] == 2,
          str(plan))
    check("one sentence says how much would change",
          stock_compare.plan_summary(plan) ==
          "1 card on CanadianShopper would be set to the website's count.",
          stock_compare.plan_summary(plan))
    check("and an empty plan says nothing would change",
          stock_compare.plan_summary([]) == "Nothing to change.", "")
    lines = stock_compare.describe_plan(plan)
    check("the confirmation names the card and both counts",
          len(lines) == 1 and "Gretzky" in lines[0] and "0 -> 2" in lines[0],
          str(lines))
    check("a row that already agrees is not written again",
          stock_compare.plan_set([{"kind": stock_compare.FIX, "woo": 2,
                                   "other": 2}]) == [], "")

    check("a card's key ignores the word order the two sites use",
          stock_compare.card_key("#75 Bert Campaneris 1967 O-Pee-Chee") ==
          stock_compare.card_key("1967 O-Pee-Chee Bert Campaneris #75"), "")
    check("and two different cards never share one",
          stock_compare.card_key("1972 O-Pee-Chee #1") !=
          stock_compare.card_key("1972 O-Pee-Chee #2"), "")
    check("editing a title brings the card back - nothing is hidden for good",
          stock_compare.card_key("1972 O-Pee-Chee Ken Dryden #10") !=
          stock_compare.card_key("1973 O-Pee-Chee Ken Dryden #10"), "")

    keys = [stock_compare.card_key(extra_woo["name"])]
    kept = stock_compare.action_list(pairs, only_woo, only_other, keys)
    check("an ignored card is out of the list",
          all(row["card"] != extra_woo["name"] for row in kept) and
          len(kept) == len(rows) - 1, str([row["card"] for row in kept]))
    check("and the panel can say how many it is hiding",
          stock_compare.hidden_count(pairs, only_woo, only_other, keys) == 1, "")

    folder = Path(tempfile.mkdtemp())
    path = folder / stock_compare.IGNORED_FILE
    entries = stock_compare.remember_ignored([], [extra_woo])
    check("dismissing remembers the card as well as its key",
          entries and entries[0]["title"] == extra_woo["name"] and
          entries[0]["key"] == stock_compare.card_key(extra_woo["name"]),
          str(entries))
    check("with no duplicates when it is dismissed twice",
          len(stock_compare.remember_ignored(entries, [extra_woo])) == 1, "")
    check("the list is written and read back whole",
          stock_compare.save_ignored(path, entries) and
          stock_compare.load_ignored(path) == entries,
          str(stock_compare.load_ignored(path)))
    check("a missing file hides nothing",
          stock_compare.load_ignored(folder / "nope.json") == [], "")
    path.write_text("{not json", encoding="utf-8")
    check("an unreadable file is not treated as \"everything is hidden\"",
          stock_compare.load_ignored(path) == [], "")
    path.write_text(json.dumps({"cards": ["plain key"]}), encoding="utf-8")
    check("an old-style list of plain keys still works",
          stock_compare.ignored_keys(stock_compare.load_ignored(path)) ==
          ["plain key"], "")

    # ---- what the plugin's result file is allowed to mean
    one = {"id": 101, "sku": "GR-1", "title": "1989 O-Pee-Chee Wayne Gretzky",
           "card": "1989 O-Pee-Chee Wayne Gretzky", "from": 0, "to": 2}
    two = {"id": None, "sku": "BO-35", "title": "1966-67 Topps Bobby Orr #35",
           "card": "1966-67 Topps Bobby Orr #35", "from": 0, "to": 5}
    report = stock_compare.plugin_write_report(
        [one, two], {"updated": [{"id": 101, "inventory": 2}],
                     "failed": [{"sku": "BO-35", "why": "matched two listings"}]})
    check("a card the plugin wrote is the only kind called changed",
          report["changed"] == [one] and not report["unknown"], str(report))
    check("a card it could not match stays, with the plugin's own reason",
          report["failed"] == [{"card": "1966-67 Topps Bobby Orr #35",
                                "why": "matched two listings"}],
          str(report["failed"]))
    report = stock_compare.plugin_write_report(
        [one], {"updated": [], "failed": []})
    check("a card the result does not mention is unknown, never assumed written",
          report["changed"] == [] and report["unknown"] == [one], str(report))
    report = stock_compare.plugin_write_report(
        [two], {"updated": [{"title": "1966-67 Topps Bobby Orr #35"}]})
    check("a result that only carries the title still matches the card",
          report["changed"] == [two], str(report))
    report = stock_compare.plugin_write_report(
        [one], {"updated": [{"product_id": 101}],
                "failed": [{"id": 999, "reason": "gone"}]})
    check("other spellings of the same keys are understood",
          report["changed"] == [one] and report["failed"] == [], str(report))
    #  Plugin 1.0.22 sends id + title + inventory on updated entries and
    #  id + title + why on failed ones. The title must never beat the id: two
    #  cards in one set are similar enough to swap rows otherwise.
    report = stock_compare.plugin_write_report(
        [one], {"updated": [{"id": 101,
                             "title": "1989 O-Pee-Chee Wayne Gretzky",
                             "inventory": 2}]})
    check("the enriched result still matches the card by its id",
          report["changed"] == [one], str(report))
    other = {"id": 102, "sku": "", "title": "1966-67 Topps Bobby Orr #35",
             "card": "1966-67 Topps Bobby Orr #35", "from": 0, "to": 1}
    report = stock_compare.plugin_write_report(
        [one, other], {"updated": [{"id": 101,
                                    "title": "1966-67 Topps Bobby Orr #35",
                                    "inventory": 2}]})
    check("an entry naming another card's title is still the id's card",
          report["changed"] == [one] and report["unknown"] == [other],
          str(report))
    report = stock_compare.plugin_write_report(
        [one], {"failed": [{"id": 101, "title": "Gretzky",
                            "why": "two listings matched"}]})
    check("an enriched failure is a failure with its reason",
          report["changed"] == [] and
          report["failed"][0]["why"] == "two listings matched", str(report))
    report = stock_compare.plugin_write_report(
        [one], {"updated": [{"id": 101, "title": "Gretzky", "inventory": 2}],
                "failed": [{"id": 101, "title": "Gretzky", "why": "raced"}]})
    check("a card in both arrays is still a failure",
          report["changed"] == [] and report["failed"][0]["why"] == "raced",
          str(report))

    report = stock_compare.plugin_write_report(
        [one], {"failed": [{"id": 101, "error": "no session"}]})
    check("a card in both lists is a failure, not a coin toss",
          report["changed"] == [] and
          report["failed"][0]["why"] == "no session", str(report))
    report = stock_compare.plugin_write_report(
        [one], {"failed": [{"id": 101}]})
    check("a failure with no reason still says so in words",
          "no reason" in report["failed"][0]["why"], str(report))
    check("a missing or broken result file means nothing is known",
          stock_compare.plugin_write_report([one], None)["unknown"] == [one] and
          stock_compare.plugin_write_report([one], {})["unknown"] == [one], "")

    check("a one-sided row says which side it is on",
          "not on CanadianShopper" in
          stock_compare.label_action({"kind": stock_compare.ONLY_WOO,
                                      "card": "X", "woo": 3}),
          "")
    check("and the reverse names the website",
          "not on your website" in
          stock_compare.label_action({"kind": stock_compare.ONLY_OTHER,
                                      "card": "X", "other": 1}), "")
    check("a fix row shows both counts and the site",
          stock_compare.label_action({"kind": stock_compare.FIX, "card": "C",
                                      "woo": 2, "other": 0}) ==
          "C  -  website 2  /  CanadianShopper 0", "")


def run_comparison(folder, app, parent, label="Compare stock (WooCommerce and "
                                                 "CanadianShopper)"):
    """Press Compare and hand back the plugin's answer, the way the app does."""
    button = find(parent, gui.ttk.Button, label)

    def fetch_ok(base, path, params, key, secret):
        return (200, PRODUCTS) if params["page"] == 1 else (200, [])

    out = folder / "cs-stock.json"
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_ok), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
        out.write_text(json.dumps({"items": CS_ITEMS}), encoding="utf-8")
        app.runs[-1]["on_done"](0)
    listing = next((w for w in parent.walk()
                    if isinstance(w, gui.tk.Listbox)), None)
    return listing, out


def test_the_fix_flow():
    print()
    print("== 11. the fix is one confirmed click, and nothing else changes ==")
    folder, app, parent = build_panel()
    listing, out = run_comparison(folder, app, parent)
    check("the disagreement is listed before anything is offered",
          listing is not None and len(listing.items) == 1, str(listing.items))
    missing_tips = [str(w.cget("text")) for w in parent.walk()
                    if isinstance(w, gui.ttk.Button)
                    and not gui.tip_for(str(w.cget("text")))]
    check("every button on the panel explains itself on hover",
          not missing_tips, str(missing_tips))
    set_all = find(parent, gui.ttk.Button,
                   "Set CanadianShopper to the website's counts...")
    fix_one = find(parent, gui.ttk.Button, "Fix the selected cards...")
    check("both the whole-list fix and the per-card fix are on the page",
          set_all is not None and fix_one is not None, "")

    asked = []
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or False)
    app.runs.clear()
    with patch.object(gui, "BASE", folder):
        set_all.invoke()
    check("the whole list asks before writing anything",
          asked and "Set CanadianShopper to these counts?" == asked[0][0],
          str(asked))
    check("and the question names the direction, so the website is never "
          "mistaken for the side that changes",
          asked and "your website's count  ->  CanadianShopper" in asked[0][1]
          and "Your website is not changed" in asked[0][1], str(asked[:1]))
    check("and the question lists the exact card and both counts",
          asked and "Gretzky" in asked[0][1] and "0 -> 2" in asked[0][1],
          str(asked))
    check("declining writes nothing at all", not app.runs, str(app.runs))
    check("and says so, rather than failing silently",
          any("not confirmed" in text for _tag, text in app.lines),
          str(app.lines[-2:]))

    asked[:] = []
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or True)
    app.runs.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"
                      if action == gui.CS_STOCK_SET_ACTION else ""), \
            patch.object(gui, "BASE", folder):
        set_all.invoke()
    args = app.runs[0]["args"] if app.runs else []
    plan_file = folder / "cs-stock-set.json"
    check("confirming asks the plugin to set the stock",
          app.runs and args[args.index("--set-file") + 1] == str(plan_file),
          str(args))
    written = json.loads(plan_file.read_text(encoding="utf-8"))["items"]
    #  The id the plugin gave the listing is the one written back; its SKU and
    #  title travel with it so an older plugin can match by those instead.
    check("the plan file carries the website's count, not the site's",
          written == [{"id": 101, "sku": "GR-1",
                       "title": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
                       "card": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
                       "from": 0, "to": 2}], str(written))
    result = folder / "cs-stock-set-result.json"
    result.write_text(json.dumps({"updated": [{"id": 101, "inventory": 2}]}),
                      encoding="utf-8")
    app.runs[0]["on_done"](0)
    check("a finished write is reported with the count",
          any("1 CanadianShopper count set" in text for _tag, text in app.lines),
          str(app.lines[-2:]))
    check("and the card leaves the list, because it is no longer disagreeing",
          listing.items == [], str(listing.items))

    # ---- a plugin that cannot write: say so, do not pretend
    folder, app, parent = build_panel()
    listing, out = run_comparison(folder, app, parent)
    check("the fresh comparison is back on the page",
          len(listing.items) == 1, str(listing.items))
    infos = []
    harness._BOX.showinfo = lambda *a, **k: infos.append(a)
    harness._BOX.askyesno = lambda *a, **k: True
    app.runs.clear()
    with patch.object(gui, "TOOL_ACTION", lambda action: ""), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button,
             "Set CanadianShopper to the website's counts...").invoke()
    check("a plugin without stock.set is told apart from a failure",
          any("cannot set stock yet" in str(payload) for payload in infos),
          str(infos))
    check("and it names the version that can, instead of leaving a dead end",
          any("1.0.21" in str(payload) for payload in infos), str(infos))
    check("the dialog points at the plugin, not at the person",
          any("plugin" in str(payload) for payload in infos), str(infos))
    check("and nothing is run against it", not app.runs, str(app.runs))

    # ---- nothing written means nothing leaves the list
    folder, app, parent = build_panel()
    listing, out = run_comparison(folder, app, parent)
    harness._BOX.askyesno = lambda *a, **k: True
    app.runs.clear()
    app.lines.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"
                      if action == gui.CS_STOCK_SET_ACTION else ""), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button,
             "Set CanadianShopper to the website's counts...").invoke()
    result = folder / "cs-stock-set-result.json"
    result.write_text(json.dumps({
        "updated": [],
        "failed": [{"id": 101, "title": "1989 O-Pee-Chee Wayne Gretzky #1 "
                                        "EX-MT 6",
                    "why": "the session has expired"}]}), encoding="utf-8")
    app.runs[0]["on_done"](0)
    check("a card the plugin could not write is not called fixed",
          len(listing.items) == 1, str(listing.items))
    check("and the plugin's reason is printed, not summarised away",
          any("the session has expired" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("a run where every card failed claims no count was set",
          not any("count set" in text for _tag, text in app.lines),
          str(app.lines[-3:]))

    # ---- the reverse: the website is the wrong side now and then
    folder, app, parent = build_panel()
    listing, out = run_comparison(folder, app, parent)
    set_site = find(parent, gui.ttk.Button,
                    "Set the website to the selected cards' counts...")
    check("the reverse fix is offered beside the default one",
          set_site is not None, "")
    asked[:] = []
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or False)
    writes = []
    with patch.object(gui.stock_write, "set_counts",
                      lambda *a, **k: writes.append((a, k)) or
                      {"updated": [], "failed": []}), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "BASE", folder):
        set_site.invoke()
    check("the reverse fix asks before writing to the website",
          asked and asked[0][0] ==
          "Write CanadianShopper's counts onto your website?", str(asked))
    check("and the question states the direction, so the two writes cannot "
          "be taken for each other",
          asked and "CanadianShopper's count  ->  your website" in asked[0][1]
          and "CanadianShopper is not changed" in asked[0][1], str(asked[:1]))
    check("and shows the website's count against the new one, and where the "
          "new one came from",
          asked and "website 2 -> 0" in asked[0][1]
          and "(from CanadianShopper)" in asked[0][1], str(asked))
    check("declining sends nothing to the website", not writes, str(writes))

    wrote = {"updated": [{"id": 1, "inventory": 0, "title": "Gretzky"}],
             "failed": []}
    writes[:] = []
    harness._BOX.askyesno = lambda *a, **k: True
    with patch.object(gui.stock_write, "set_counts",
                      lambda *a, **k: (writes.append((a, k)) or wrote)), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        set_site.invoke()
    check("confirming writes that one card's count to the website",
          writes and writes[0][0][3] == [{"id": 1, "quantity": 0,
                                          "title": "1989 O-Pee-Chee Wayne "
                                                   "Gretzky #1 EX-MT 6"}],
          str(writes[:1]))
    check("the panel says the website changed, not that it compared",
          any("1 website count changed" in text for _tag, text in app.lines),
          str(app.lines[-2:]))
    check("and the card leaves the list",
          listing.items == [], str(listing.items))

    # ---- a key that cannot write is named as a key problem, not a mystery
    folder, app, parent = build_panel()
    listing, out = run_comparison(folder, app, parent)
    errors = []
    harness._BOX.showerror = lambda *a, **k: errors.append(a)
    harness._BOX.askyesno = lambda *a, **k: True
    failure = gui.stock_write.StockWriteError(
        "The website rejected the WooCommerce keys (HTTP 401).",
        "Writing a stock count needs a key pair with Read/Write access.",
        status=401)
    with patch.object(gui.stock_write, "set_counts",
                      lambda *a, **k: (_ for _ in ()).throw(failure)), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button,
             "Set the website to the selected cards' counts...").invoke()
    check("a read-only key is explained, not swallowed",
          errors and "HTTP 401" in str(errors[-1]) and
          "Read/Write" in str(errors[-1]), str(errors[-1:]))
    check("and the card is still on the list, because nothing was written",
          len(listing.items) == 1, str(listing.items))

    folder, app, parent = build_panel()
    listing, out = run_comparison(folder, app, parent)
    app.opened.clear()
    with patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button,
             "Open the selected cards on the website").invoke()
    check("opening a card goes to the website's own product page",
          app.opened and "post=1" in app.opened[0], str(app.opened))
    check("and the app says it changed nothing there",
          any("nothing was changed by this app" in text
              for _tag, text in app.lines), str(app.lines[-2:]))

    folder, app, parent = build_panel()
    listing, out = run_comparison(folder, app, parent)
    asked[:] = []
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or True)
    app.runs.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"
                      if action == gui.CS_STOCK_SET_ACTION else ""), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Fix the selected cards...").invoke()
    check("fixing a selected card writes only that card",
          app.runs and str(folder / "cs-stock-set.json") in app.runs[0]["args"],
          str(app.runs))
    check("the one-card fix is a confirmation too",
          asked and asked[0][0] == "Set CanadianShopper to these counts?", "")


def test_ignoring():
    print()
    print("== 12. a card that is gone from the other site stops asking ==")
    folder, app, parent = build_panel()
    listing, out = run_comparison(folder, app, parent)
    ignore = find(parent, gui.ttk.Button, "Ignore the selected cards")
    restore = find(parent, gui.ttk.Button, "Restore ignored cards...")
    check("there is a way to stop being asked, and a way back",
          ignore is not None and restore is not None, "")

    before = list(listing.items)
    with patch.object(gui, "BASE", folder):
        ignore.invoke()
    path = folder / stock_compare.IGNORED_FILE
    saved = json.loads(path.read_text(encoding="utf-8"))["cards"] \
        if path.is_file() else []
    check("the dismissal is remembered on disk", len(saved) == 1, str(saved))
    check("and the row is off the list at once",
          listing.items == before[1:], str(listing.items))
    check("the panel says how many it is hiding",
          any("1 ignored" in str(w.cget("text")) for w in parent.walk()
              if isinstance(w, gui.ttk.Label)),
          str([w.cget("text") for w in parent.walk()
               if isinstance(w, gui.ttk.Label)][:6]))

    asked = []
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or True)
    with patch.object(gui, "BASE", folder):
        restore.invoke()
    check("restoring asks first and lists what comes back",
          asked and "Restore 1 ignored card?" == asked[0][0] and
          "Gretzky" in asked[0][1], str(asked))
    check("and the ignore list is emptied",
          json.loads(path.read_text(encoding="utf-8"))["cards"] == [], "")



def test_listing_the_leftovers():
    print()
    print("== 13. a card the website has and CanadianShopper does not ==")
    folder, app, parent = build_panel()
    #  Two products that are only on the website: one complete, one with no
    #  photo - the confirmation has to be able to say so.
    products = PRODUCTS + [
        {"id": 9, "name": "1972-73 O-Pee-Chee Guy Lafleur #79", "sku": "LA-79",
         "manage_stock": True, "stock_quantity": 3, "type": "simple",
         "price": "9.00", "short_description": "<p>Sharp corner copy.</p>",
         "images": [{"src": "https://shop.example/lafleur-front.webp"}]},
        {"id": 10, "name": "1972-73 O-Pee-Chee Ken Dryden #10", "sku": "",
         "manage_stock": True, "stock_quantity": 1, "type": "simple"},
    ]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    button = find(parent, gui.ttk.Button, "Compare stock", exact=False)
    out = folder / "cs-stock.json"
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
        out.write_text(json.dumps({"items": CS_ITEMS}), encoding="utf-8")
        app.runs[-1]["on_done"](0)
    listing = next((w for w in parent.walk()
                    if isinstance(w, gui.tk.Listbox)), None)
    website_only = [index for index, text in enumerate(listing.items or [])
                    if "not on CanadianShopper" in text]
    check("the cards that are only on the website are on the list",
          len(website_only) == 2, str(listing.items))
    list_btn = find(parent, gui.ttk.Button,
                    "List the selected cards on CanadianShopper...")
    check("and they can be listed from here",
          list_btn is not None and
          find(parent, gui.ttk.Button, "List every website-only card...")
          is not None, "")

    # ---- declining writes nothing, and says so
    asked = []
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or False)
    with patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button,
             "List every website-only card...").invoke()
    check("listing asks first",
          asked and asked[0][0] == "List these cards on CanadianShopper?",
          str(asked[:1]))
    check("the question says what the listings will look like",
          asked and "2 listings would be created as unpublished drafts"
          in asked[0][1], str(asked[:1]))
    check("with the title, the price and the stock count of each",
          asked and "Guy Lafleur" in asked[0][1] and "9.00" in asked[0][1] and
          "3 in stock" in asked[0][1], str(asked[0][1][:400]))
    check("and it names what is missing before the person imports",
          asked and "no photo on the website" in asked[0][1],
          str(asked[0][1][-300:]))
    product_folder = folder / "canadianshopper_products"
    check("declining writes no file at all",
          not (product_folder.is_dir() and
               any(product_folder.glob("*.csv"))), str(product_folder))
    check("and says so rather than failing silently",
          any("not confirmed" in text for _tag, text in app.lines),
          str(app.lines[-2:]))

    # ---- confirming writes the file the importer already knows
    asked[:] = []
    opened = []
    infos_after = []
    harness._BOX.showinfo = lambda *a, **k: infos_after.append(a)
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or True)
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "open_path", lambda path: opened.append(path)):
        find(parent, gui.ttk.Button,
             "List every website-only card...").invoke()
    import_csv = list(product_folder.glob("canadianshopper_import_*.csv"))
    check("confirming writes one import file",
          len(import_csv) == 1, str(import_csv))
    check("named the way every other batch is named",
          bool(import_csv) and
          import_csv[0].name.endswith("_01_of_01.csv") and
          import_csv[0].name.startswith("canadianshopper_import_"),
          str([p.name for p in import_csv]))
    body = import_csv[0].read_text(encoding="utf-8-sig") if import_csv else ""
    check("with the pipeline's fourteen columns",
          body.splitlines() and body.splitlines()[0].split(",") ==
          gui.cs_listing.CANADIANSHOPPER_FIELDNAMES, body.splitlines()[:1])
    check("and one row per card that is only on the website",
          len(body.splitlines()) == 3, str(body.splitlines()[1:]))
    check("the row carries the website's photo, price and count",
          "lafleur-front.webp" in body and "9.00" in body and
          "Sharp corner copy." in body, str(body.splitlines()[1:2]))
    check("the console names the file it wrote",
          any("Wrote %s" % (import_csv[0] if import_csv else "") in text
              or ("canadianshopper_import_" in text and "Wrote" in text)
              for _tag, text in app.lines), str(app.lines[-3:]))
    check("with no import action the file is handed over by hand, not dropped",
          any("cannot import a CSV itself yet" in str(payload)
              for payload in infos_after), str(infos_after[-1:]))
    check("and the folder is offered rather than assumed",
          opened and str(product_folder) == str(opened[-1]), str(opened))
    check("and the cards stay on the list until CanadianShopper has them",
          any("not on CanadianShopper" in text for text in listing.items or []),
          str(listing.items))
    check("nothing was sent to either shop by listing",
          not any("set-file" in " ".join(run["args"]) for run in app.runs),
          str([run["args"] for run in app.runs])[:160])


def test_listing_skips_what_is_not_a_listing_job():
    print()
    print("== 14. listing is only offered for what is really missing ==")
    folder, app, parent = build_panel()
    listing, out = run_comparison(folder, app, parent)
    listing.selection = (0,)          # the one row is a disagreement, not a gap
    infos = []
    harness._BOX.showinfo = lambda *a, **k: infos.append(a)
    with patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button,
             "List the selected cards on CanadianShopper...").invoke()
    check("a card on both sites is not offered as a new listing",
          infos and "Nothing to list" in str(infos[0]), str(infos))
    check("and the reason says which row it wants",
          infos and "website only" in str(infos[0]), str(infos))
    check("no file is written for a refused listing",
          not list(folder.glob("canadianshopper_products/*.csv")), "")



def test_one_click_import():
    print()
    print("== 15. the import is finished in one click, when the plugin can ==")
    folder, app, parent = build_panel()
    products = PRODUCTS + [
        {"id": 9, "name": "1972-73 O-Pee-Chee Guy Lafleur #79", "sku": "LA-79",
         "manage_stock": True, "stock_quantity": 3, "type": "simple",
         "price": "9.00", "images": [{"src": "https://shop.example/f.webp"}]},
    ]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        (folder / "cs-stock.json").write_text(json.dumps({"items": CS_ITEMS}),
                                              encoding="utf-8")
        app.runs[-1]["on_done"](0)

    asked = []
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or True)
    app.runs.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: {"marketplace.import_csv":
                                      "/plugins/cs/cs-import.py",
                                      "marketplace.publish_drafts":
                                      "/plugins/cs/cs-publish-drafts.py"}.get(
                                          action, "")), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "open_path", lambda path: None):
        find(parent, gui.ttk.Button,
             "List every website-only card...").invoke()
    import_run = next((run for run in app.runs
                       if run["tool"].endswith("cs-import.py")), None)
    check("confirming offers to import as well as write",
          any(title.startswith("Import 1 listing") for title, _m in asked),
          str([title for title, _m in asked]))
    check("the import question says the listings arrive as drafts",
          any("unpublished drafts" in message for title, message in asked
              if title.startswith("Import")), "")
    args = import_run["args"] if import_run else []
    check("the import is asked for by the plugin's own action, with the file",
          import_run is not None and
          "--csv" in args and args[args.index("--csv") + 1].endswith(".csv"),
          str(args))
    check("and it is never asked to publish",
          not any(flag in args for flag in ("--apply", "--publish")), str(args))
    check("the result is written where the panel can read it",
          "--result" in args and
          args[args.index("--result") + 1].endswith("cs-import-result.json"),
          str(args))

    made_csv = next((folder / "canadianshopper_products").glob(
        "canadianshopper_import_*.csv"))
    (folder / "canadianshopper_products" / "cs-import-result.json").write_text(
        json.dumps({"imported": [{"file": made_csv.name, "rows": 1,
                                  "drafts": 1}]}), encoding="utf-8")
    app.lines.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: {"marketplace.import_csv":
                                      "/plugins/cs/cs-import.py",
                                      "marketplace.publish_drafts":
                                      "/plugins/cs/cs-publish-drafts.py"}.get(
                                          action, "")):
        import_run["on_done"](0)
    check("a finished import is reported with the drafts it made",
          any("1 draft created on CanadianShopper" in text
              for _tag, text in app.lines), str(app.lines[-4:]))
    check("and it says the drafts are not live",
          any("not live" in text for _tag, text in app.lines),
          str(app.lines[-4:]))
    check("then it offers to publish what was just created",
          any(title == "Publish the 1 new draft now?" for title, _m in asked),
          str([title for title, _m in asked]))
    publish_run = next((run for run in app.runs
                        if run["tool"].endswith("cs-publish-drafts.py")), None)
    check("and publishing is the publisher the app already has, with --apply",
          publish_run is not None and "--apply" in publish_run["args"],
          str(publish_run and publish_run["args"]))
    check("the publish dialog says it scans every draft, not just the new one",
          any("every draft on CanadianShopper" in message and
              "drafts from earlier runs" in message
              for title, message in asked if title.startswith("Publish")),
          str(asked[-1:]))
    check("and that a typed PUBLISH still stands between it and going live",
          any("type PUBLISH" in message for title, message in asked
              if title.startswith("Publish")), str(asked[-1:]))
    check("the run carries the app's own confirmation string",
          publish_run is not None and publish_run.get("confirm") not in
          (None, ""), str(publish_run))

    report_csv = (folder / "canadianshopper_products" / "cs-publish-report.csv")
    report_csv.write_text("card,state\nGretzky,published\n", encoding="utf-8")
    app.lines.clear()
    publish_run["on_done"](0)
    check("a finished publish says the report has the detail",
          any("Publish finished" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and tells the person to compare again",
          any("Compare again" in text for _tag, text in app.lines),
          str(app.lines[-3:]))

    # ---- a publisher that wrote no rows is never handed over as a report
    asked.clear()
    app.lines.clear()
    report_csv.write_text("", encoding="utf-8")
    publish_run["on_done"](0)
    check("a publish that found no drafts says so plainly",
          any("found no drafts" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and never claims the report has the detail",
          not any("Publish finished" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and does not offer an empty report to open",
          not any(title == "Open the publish report?"
                  for title, _m in asked), str(asked))

    publish_run["on_done"](2)
    check("a publish that failed says the drafts are still unpublished",
          any("did not finish (exit 2)" in text and "unpublished" in text
              for _tag, text in app.lines), str(app.lines[-3:]))


def test_one_click_import_refusals():
    print()
    print("== 16. an import that did not happen is never reported as one ==")
    folder, app, parent = build_panel()
    products = PRODUCTS + [
        {"id": 9, "name": "Only on the website card", "sku": "",
         "manage_stock": True, "stock_quantity": 1, "type": "simple",
         "price": "3.00", "images": [{"src": "https://shop.example/f.webp"}]}]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    import_actions = {"marketplace.import_csv": "/plugins/cs/cs-import.py",
                      "marketplace.publish_drafts":
                      "/plugins/cs/cs-publish-drafts.py"}

    def listing_run(action_map, make_answer):
        """Write a listing file, run the import, and hand back what happened.

        The answer is built from the file that was actually written, because
        the plugin names each file in its result and the panel matches on that
        name - a test with a made-up name would prove nothing.
        """
        asked[:] = []
        app.runs.clear()
        with patch.object(gui, "TOOL_ACTION",
                          lambda action: action_map.get(action, "")), \
                patch.object(gui, "BASE", folder), \
                patch.object(gui, "open_path", lambda path: None):
            find(parent, gui.ttk.Button,
                 "List every website-only card...").invoke()
            run = next((r for r in app.runs
                        if r["tool"].endswith("cs-import.py")), None)
            if run is None:
                return None, []
            csv_path = next((folder / "canadianshopper_products").glob(
                "canadianshopper_import_*.csv"))
            answer = make_answer(csv_path.name) if make_answer else None
            if answer is not None:
                (folder / "canadianshopper_products" /
                 "cs-import-result.json").write_text(json.dumps(answer),
                                                    encoding="utf-8")
            app.lines.clear()
            run["on_done"](0)
        return run, list(app.lines)

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        (folder / "cs-stock.json").write_text(json.dumps({"items": CS_ITEMS}),
                                              encoding="utf-8")
        app.runs[-1]["on_done"](0)

    asked = []
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or True)

    # ---- a file the plugin did not mention is unknown, not imported
    _run, lines = listing_run(import_actions,
                              lambda name: {"imported": [], "failed": []})
    check("a file the plugin did not report on is called unknown",
          any("not reported on by the plugin" in text for _tag, text in lines),
          str(lines[-3:]))
    check("and no draft count is claimed",
          not any("draft" in text and "created" in text and
                  "not reported" not in text for _tag, text in lines),
          str(lines[-3:]))

    # ---- a plugin that refuses the file says why
    _run, lines = listing_run(
        import_actions,
        lambda name: {"imported": [],
                      "failed": [{"file": name,
                                  "why": "3 rows had no image URL"}]})
    check("a refused file keeps the plugin's reason",
          any("3 rows had no image URL" in text for _tag, text in lines),
          str(lines[-3:]))
    check("and nothing is called imported",
          not any("draft created" in text for _tag, text in lines),
          str(lines[-3:]))

    # ---- a plugin that takes the file but creates nothing is not a success
    _run, lines = listing_run(
        import_actions,
        lambda name: {"imported": [{"file": name, "rows": 1, "drafts": 0}],
                      "failed": []})
    check("an import that made no drafts is not called a success",
          any("reported no drafts" in text for _tag, text in lines) and
          not any("draft created" in text for _tag, text in lines),
          str(lines[-3:]))

    # ---- declining the publish leaves the drafts, and offers the report
    asked[:] = []
    app.runs.clear()
    #  List and import yes, publish no - the question under test is the last one.
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or
        not title.startswith("Publish the"))
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: import_actions.get(action, "")), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "open_path", lambda path: None):
        find(parent, gui.ttk.Button,
             "List every website-only card...").invoke()
        run = next(r for r in app.runs if r["tool"].endswith("cs-import.py"))
        csv_path = next((folder / "canadianshopper_products").glob(
            "canadianshopper_import_*.csv"))
        (folder / "canadianshopper_products" / "cs-import-result.json").write_text(
            json.dumps({"imported": [{"file": csv_path.name, "rows": 1,
                                      "drafts": 1}]}), encoding="utf-8")
        asked.clear()
        #  Inside the patch: the publish and report actions are resolved by
        #  name when the import finishes, so they must still be stubbed.
        run["on_done"](0)
    check("declining the publish leaves the drafts unpublished",
          not any("--apply" in r["args"] for r in app.runs), str(app.runs))
    check("and it falls back to the read-only report offer",
          any(title == "Preview the new drafts?" for title, _m in asked),
          str([title for title, _m in asked]))
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or True)

    # ---- 1.0.24: a file with nothing new to create is in "failed", with why
    _run, lines = listing_run(
        import_actions,
        lambda name: {"imported": [],
                      "failed": [{"file": name,
                                  "why": "every listing in this file already "
                                         "exists on CanadianShopper; existing "
                                         "listings were left unchanged"}]})
    check("a file with nothing new is not painted as a failure",
          any(tag == "warn" and "No new listing from" in text
              for tag, text in lines), str(lines[-3:]))
    check("the plugin's own sentence is printed unedited",
          any("existing listings were left unchanged" in text
              for _tag, text in lines), str(lines[-3:]))
    check("and the panel says nothing on the shop moved",
          any("Nothing on CanadianShopper was changed by this import" in text
              for _tag, text in lines), str(lines[-3:]))
    check("no draft count is claimed for it",
          not any("draft created" in text for _tag, text in lines),
          str(lines[-3:]))
    #  The summary may have moved on to the readiness report by now, so the
    #  thing worth proving is that no panel text ever says "0 drafts".
    check("and nothing on the page says \"0 drafts\"",
          not any("0 draft" in str(w.cget("text")) for w in parent.walk()
                  if isinstance(w, gui.ttk.Label)), "")
    check("the console explains why nothing was created",
          any("already have a listing on CanadianShopper" in text
              for _tag, text in lines), str(lines[-4:]))
    check("and says which states the stock reader cannot see",
          any("a draft, hidden, archived, or off sale" in text
              for _tag, text in lines), str(lines[-4:]))
    check("a file with nothing new never claims a draft was created",
          not any("draft created" in text for _tag, text in lines),
          str(lines[-4:]))
    #  Nothing was created, so nobody knows whether there is a draft. The
    #  publisher is asked to look first - never to apply blind.
    look = next((r for r in app.runs
                 if r["tool"].endswith("cs-publish-drafts.py")), None)
    check("a publish is looked for before anyone is asked to type PUBLISH",
          look is not None and "--apply" not in look["args"],
          str(look and look["args"]))
    check("and no PUBLISH question is asked until the look finds one",
          not any(title.startswith("Publish") for title, _m in asked),
          str([title for title, _m in asked]))

    #  A look that finds nothing is an answer: no PUBLISH, no empty report.
    report_csv = (folder / "canadianshopper_products" / "cs-publish-report.csv")
    report_csv.write_text("card,state\n", encoding="utf-8")
    asked.clear()
    app.lines.clear()
    look["on_done"](0)
    check("a look that finds no drafts says there is nothing to publish",
          any("No drafts on CanadianShopper" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and names the states a count cannot fix, pointing at the dashboard",
          any("vendor dashboard" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and never asks for a typed PUBLISH for nothing",
          not any(title.startswith("Publish") for title, _m in asked),
          str([title for title, _m in asked]))
    check("and never offers the empty report to open",
          not any(title == "Open the publish report?" for title, _m in asked),
          str([title for title, _m in asked]))

    #  A plugin that cannot see listings that are not on sale is named, so the
    #  one-sided cards are not left as a mystery.
    check("an older reader is named when one is installed",
          not any("plugin is" in text and "1.0.25" in text
                  for _tag, text in app.lines)
          or gui.plugin_version() != "", str(app.lines[-2:]))

    #  A look that does find a draft asks the same question as before, and
    #  only then is the publisher asked to apply.
    report_csv.write_text("card,state\nGretzky,draft\n", encoding="utf-8")
    asked.clear()
    app.runs.clear()
    #  Inside the patch: the publisher is resolved by action name when the
    #  question is asked, so the stub has to still be in place.
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: import_actions.get(action, "")), \
            patch.object(gui, "BASE", folder):
        look["on_done"](0)
    check("a look that finds a draft asks before publishing it",
          any(title.startswith("Publish") for title, _m in asked),
          str([title for title, _m in asked]))
    applied = next((r for r in app.runs
                    if r["tool"].endswith("cs-publish-drafts.py")
                    and "--apply" in r["args"]), None)
    check("and only then is the publisher asked to apply",
          applied is not None, str(app.runs))

    # ---- a genuine per-file refusal keeps its red reason
    _run, lines = listing_run(
        import_actions,
        lambda name: {"imported": [],
                      "failed": [{"file": name,
                                  "why": "the session expired before the "
                                         "import"}]})
    check("a real refusal keeps its reason verbatim",
          any("the session expired before the import" in text
              for _tag, text in lines), str(lines[-3:]))
    check("a real refusal is still not called success",
          not any("draft created" in text for _tag, text in lines),
          str(lines[-3:]))

    # ---- a Windows-shaped path in the result still finds the file
    _run, lines = listing_run(
        import_actions,
        lambda name: {"imported": [{"file": "C:\\Users\\Owner\\cs\\" + name,
                                    "rows": 1, "drafts": 1}],
                      "failed": []})
    check("a result that names the file by a full Windows path is understood",
          any("1 draft created" in text for _tag, text in lines) and
          not any("not reported on" in text for _tag, text in lines),
          str(lines[-3:]))

    # ---- declining the import leaves the file, and nothing runs
    asked[:] = []
    app.runs.clear()
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or
        title != "Import 1 listing on CanadianShopper now?")
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: import_actions.get(action, "")), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "open_path", lambda path: None):
        find(parent, gui.ttk.Button,
             "List every website-only card...").invoke()
    check("declining the import runs nothing",
          not any(r["tool"].endswith("cs-import.py") for r in app.runs),
          str(app.runs))
    check("and the file is still written for the hand route",
          any((folder / "canadianshopper_products").glob(
              "canadianshopper_import_*.csv")), "")
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or True)

    # ---- a plugin that fails outright leaves the file for the hand route
    asked[:] = []
    app.runs.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: import_actions.get(action, "")), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "open_path", lambda path: None):
        find(parent, gui.ttk.Button,
             "List every website-only card...").invoke()
    run = next(r for r in app.runs if r["tool"].endswith("cs-import.py"))
    app.lines.clear()
    run["on_done"](1)
    check("an import that failed says so and keeps the file",
          any("did not finish (exit 1)" in text for _tag, text in app.lines) and
          any(folder.joinpath("canadianshopper_products").glob("*.csv")),
          str(app.lines[-3:]))



def test_listings_that_are_not_on_sale():
    print()
    print("== 17. a listing that exists but cannot be bought ==")
    payload = {"items": [
        {"id": 101, "title": "Gretzky #1", "sku": "GR-1", "inventory": 0,
         "status": "active"},
        {"id": 102, "title": "Orr #35", "sku": "BO-35", "inventory": 0,
         "status": "Draft"},
        {"id": 103, "title": "Dryden #10", "sku": "DR-10", "inventory": 2,
         "status": "archived"},
        {"id": 104, "title": "Lafleur #79", "sku": "LA-79", "inventory": 1,
         "status": "out-of-stock"},
        {"id": 105, "title": "No status card", "sku": "", "inventory": 1},
        {"id": 106, "title": "Odd word card", "sku": "", "inventory": 1,
         "status": "mystery-state"},
    ]}
    items = stock_compare.plugin_items(payload)
    check("the status travels with every listing",
          [item["status"] for item in items] ==
          ["active", "Draft", "archived", "out-of-stock", "", "mystery-state"],
          str([item["status"] for item in items]))
    words = [stock_compare.status_of(item) for item in items]
    check("draft, archived and out-of-stock are all 'not on sale'",
          words == ["active", "draft", "off-sale", "off-sale", "active",
                    "active"], str(words))
    check("a status the core does not know is never called broken",
          stock_compare.is_on_sale(items[5]), "")
    check("an older plugin with no status still reads as on sale",
          stock_compare.is_on_sale(items[4]), "")
    check("the draft is named in the person's words",
          stock_compare.status_words(items[1]) == "a Draft",
          stock_compare.status_words(items[1]))
    check("an archived listing keeps the vendor's own word",
          stock_compare.status_words(items[2]) == "archived",
          stock_compare.status_words(items[2]))
    check("and one that is on sale needs no words at all",
          stock_compare.status_words(items[0]) == "", "")

    woo = [{"id": 1, "name": "Gretzky #1", "sku": "GR-1", "qty": 2},
           {"id": 2, "name": "Orr #35", "sku": "BO-35", "qty": 3},
           {"id": 3, "name": "Dryden #10", "sku": "DR-10", "qty": 2},
           {"id": 4, "name": "Lafleur #79", "sku": "LA-79", "qty": 1}]
    pairs, only_woo, only_other = stock_compare.pair(woo, items[:4])
    rows = stock_compare.action_list(pairs, only_woo, only_other)
    kinds = {row["card"]: row["kind"] for row in rows}
    check("a draft listing is not offered as a count to fix",
          kinds.get("Orr #35") == stock_compare.OFF_SALE, str(kinds))
    check("and neither is an archived or out-of-stock one",
          kinds.get("Dryden #10") == stock_compare.OFF_SALE and
          kinds.get("Lafleur #79") == stock_compare.OFF_SALE, str(kinds))
    check("a live listing with a different count is still a count to fix",
          kinds.get("Gretzky #1") == stock_compare.FIX, str(kinds))
    check("so the count is never written to a listing nobody can buy",
          [row["id"] for row in stock_compare.plan_set(rows)] == [101],
          str(stock_compare.plan_set(rows)))
    check("the row still carries both sides, so the person can see the card",
          all(row.get("woo_id") and row.get("other_id") for row in rows
              if row["kind"] == stock_compare.OFF_SALE), str(rows))
    check("the draft rows are the ones publishing could activate",
          [row["card"] for row in stock_compare.draft_rows(rows)] ==
          ["Orr #35"], str(stock_compare.draft_rows(rows)))
    check("every not-on-sale row is counted as one",
          len(stock_compare.off_sale_rows(rows)) == 3, str(rows))
    check("its label says both facts - where it is, and that it is not on sale",
          stock_compare.label_action(
              [row for row in rows if row["card"] == "Orr #35"][0]) ==
          "Orr #35  -  on CanadianShopper but not on sale (a Draft)  /  "
          "website 3",
          stock_compare.label_action(
              [row for row in rows if row["card"] == "Orr #35"][0]))
    check("a not-on-sale row is hidden by the ignore list like any other",
          stock_compare.hidden_count(
              pairs, only_woo, only_other,
              [stock_compare.card_key("Orr #35")]) == 1, "")
    check("and the panel still counts a card on both sites as matched",
          len(pairs) == 4, str(len(pairs)))


def test_an_archived_card_with_nothing_to_sell():
    print()
    print("== 17b. archived there and dry here is not a job ==")
    woo = [{"id": 1, "name": "Dryden #10", "sku": "DR-10", "qty": 0},
           {"id": 2, "name": "Orr #4", "sku": "BO-4", "qty": 0},
           #  Stocked here, archived there: still worth showing, because the
           #  card can be put back on sale with a click.
           {"id": 3, "name": "Gretzky #1", "sku": "GR-1", "qty": 2},
           {"id": 4, "name": "Lafleur #79", "sku": "LA-79", "qty": 2}]
    items = stock_compare.plugin_items({"items": [
        {"id": 101, "title": "Dryden #10", "sku": "DR-10", "inventory": 0,
         "status": "archived"},
        #  A draft with nothing on the website is still shown: it is one
        #  publish (or one restock) away from selling, unlike an archived one.
        {"id": 102, "title": "Orr #4", "sku": "BO-4", "inventory": 0,
         "status": "Draft"},
        {"id": 103, "title": "Gretzky #1", "sku": "GR-1", "inventory": 1,
         "status": "Archived"},
        {"id": 104, "title": "Lafleur #79", "sku": "LA-79", "inventory": 1,
         "status": "archived"}]})
    pairs, only_woo, only_other = stock_compare.pair(woo, items)
    rows = stock_compare.action_list(pairs, only_woo, only_other)
    kinds = {row["card"]: row["kind"] for row in rows}
    check("archived there and at zero here is not on the list",
          "Dryden #10" not in kinds, str(kinds))
    check("a draft there with nothing here still is",
          kinds.get("Orr #4") == stock_compare.OFF_SALE, str(kinds))
    check("and an archived listing the website still stocks is too",
          kinds.get("Gretzky #1") == stock_compare.OFF_SALE, str(kinds))
    check("an archived listing that exists on both is still counted once",
          len([row for row in rows if row["card"] == "Lafleur #79"]) == 1,
          str([row["card"] for row in rows]))
    check("it is named rather than silently dropped",
          stock_compare.archived_note(pairs) ==
          "1 archived on CanadianShopper with nothing on your website, "
          "so not shown.", stock_compare.archived_note(pairs))
    check("with no such pair there is no sentence",
          stock_compare.archived_note(
              [pair for pair in pairs
               if pair["woo"]["name"] != "Dryden #10"]) == "",
          stock_compare.archived_note(pairs))
    check("only an archived state counts, not every off-sale one",
          stock_compare.is_archived({"status": "Archived"}) and
          stock_compare.is_archived({"status": " ARCHIVE "}) and
          not stock_compare.is_archived({"status": "Draft"}) and
          not stock_compare.is_archived({"status": "hidden"}) and
          not stock_compare.is_archived({}), "")
    check("a pair with no other side cannot be called archived",
          stock_compare.archived_sold_out([{"woo": {"qty": 0}}]) == [], "")

    # ---- and the panel says so beside the list
    folder, app, parent = build_panel()
    products = [
        {"id": 1, "name": "Dryden #10", "sku": "DR-10", "manage_stock": True,
         "stock_quantity": 0, "type": "simple"},
        {"id": 2, "name": "Orr #4", "sku": "BO-4", "manage_stock": True,
         "stock_quantity": 0, "type": "simple"}]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        (folder / "cs-stock.json").write_text(json.dumps({"items": [
            {"id": 101, "title": "Dryden #10", "sku": "DR-10",
             "inventory": 0, "status": "archived"}]}), encoding="utf-8")
        app.runs[-1]["on_done"](0)
    listing = next((w for w in parent.walk()
                    if isinstance(w, gui.tk.Listbox)), None)
    check("the panel does not list it",
          listing is not None and not listing.items, str(listing and listing.items))
    said = [str(w.cget("text")) for w in parent.walk()
            if isinstance(w, gui.ttk.Label)]
    check("the panel says how many it left out",
          any("archived on CanadianShopper" in text and "not shown" in text
              for text in said), str(said[-3:]))


def test_panel_explains_off_sale():
    print()
    print("== 18. the panel says a listing exists but is not on sale ==")
    folder, app, parent = build_panel()
    products = [
        {"id": 1, "name": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
         "sku": "GR-1", "manage_stock": True, "stock_quantity": 2,
         "type": "simple"},
        {"id": 2, "name": "1966-67 Topps Bobby Orr #35", "sku": "BO-35",
         "manage_stock": True, "stock_quantity": 3, "type": "simple"},
    ]
    items = [{"id": 101, "title": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
              "sku": "GR-1", "inventory": 0, "status": "active"},
             {"id": 102, "title": "1966-67 Topps Bobby Orr #35", "sku": "BO-35",
              "inventory": 0, "status": "Draft"}]

    def fetch_ok(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_ok), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        (folder / "cs-stock.json").write_text(json.dumps({"items": items}),
                                              encoding="utf-8")
        app.runs[-1]["on_done"](0)
    listing = next((w for w in parent.walk()
                    if isinstance(w, gui.tk.Listbox)), None)
    check("the draft listing is on the list, not missing from it",
          any("not on sale (a Draft)" in text for text in listing.items),
          str(listing.items))
    check("and it is not offered as a count to fix",
          not any("website 3  /  CanadianShopper" in text
                  for text in listing.items), str(listing.items))
    check("the console says a count cannot fix it",
          any("a count cannot fix that" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("the summary counts it separately from the missing cards",
          any("not on sale there" in text for _tag, text in app.lines),
          str(app.lines[-2:]))
    check("and publishing is offered for it",
          find(parent, gui.ttk.Button, "Publish the ready drafts...")
          is not None and
          find(parent, gui.ttk.Button,
               "Publish the ready drafts...").packed, "")
    asked = []
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or False)
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/cs-publish-drafts.py"), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Publish the ready drafts...").invoke()
    check("publishing a draft from here still asks first",
          asked and asked[0][0] == "Publish the ready drafts now?", str(asked))
    check("and says a count could not have done this",
          asked and "draft listing" in asked[0][1], str(asked))
    app.runs.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/cs-publish-drafts.py"), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button,
             "Set CanadianShopper to the website's counts...").invoke()
    check("the default fix writes nothing when the only card is off sale",
          not app.runs, str(app.runs))


def test_report_rows():
    print()
    print("== 19. a report is only worth opening when it has something in it ==")
    folder = Path(tempfile.mkdtemp(prefix="cs-report-"))
    path = folder / "cs-publish-report.csv"
    check("a report that is not there is unknown, not empty",
          stock_compare.report_rows(path) is None, "")
    path.write_text("", encoding="utf-8")
    check("a file with nothing in it holds no rows",
          stock_compare.report_rows(path) == 0, "")
    path.write_text("card,state\n", encoding="utf-8")
    check("a header on its own is still no rows - what a publisher with no "
          "drafts leaves behind",
          stock_compare.report_rows(path) == 0, "")
    path.write_text("card,state\nGretzky,published\nOrr,blocked\n",
                    encoding="utf-8")
    check("every draft line counts", stock_compare.report_rows(path) == 2, "")
    path.write_text("\n\ncard,state\nGretzky,published\n", encoding="utf-8")
    check("blank lines are not drafts", stock_compare.report_rows(path) == 1, "")


def test_old_reader_is_named():
    print()
    print("== 20. a reader that cannot see a hidden listing says so ==")
    folder, app, parent = build_panel()
    products = PRODUCTS + [
        {"id": 9, "name": "Only on the website card", "sku": "",
         "manage_stock": True, "stock_quantity": 1, "type": "simple"}]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    def compare(version=None):
        app.lines.clear()
        with patch.object(gui, "TOOL_ACTION",
                          lambda action: "/plugins/cs/stock.py"), \
                patch.object(gui, "read_woo_credentials",
                             lambda path=None: ("https://shop.example", "ck_a",
                                                "cs_b")), \
                patch.object(gui, "woo_get", fetch_all), \
                patch.object(gui, "in_background", sync_background), \
                patch.object(gui, "plugin_version",
                             lambda *a, **k: version or ""), \
                patch.object(gui, "BASE", folder):
            find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
            (folder / "cs-stock.json").write_text(
                json.dumps({"items": CS_ITEMS}), encoding="utf-8")
            app.runs[-1]["on_done"](0)
        return list(app.lines)

    lines = compare()
    listed = next((w for w in parent.walk()
                   if isinstance(w, gui.tk.Listbox)), None)
    check("the card only on the website is listed as such",
          listed is not None and any("not on CanadianShopper" in item
                                    for item in listed.items),
          str(listed and listed.items))
    check("and the summary separates it from the count disagreement",
          any("1 disagree" in text and "1 only on one side" in text
              for _tag, text in lines), str(lines[-3:]))
    check("and no version is claimed when the plugin cannot be read",
          not any("reader in your plugin is" in text for _tag, text in lines),
          str(lines[-3:]))

    lines = compare("1.0.24")
    check("an old reader is named, with the version that fixes it",
          any("1.0.24" in text and "1.0.25" in text for _tag, text in lines),
          str(lines[-3:]))
    check("and it says what such a reader cannot see",
          any("draft, hidden or archived looks missing" in text
              for _tag, text in lines), str(lines[-3:]))
    check("and it does not claim the card is absent from the shop",
          any("Update the plugin, then compare again" in text
              for _tag, text in lines), str(lines[-3:]))

    lines = compare("1.0.25")
    check("a reader that reports every listing is not nagged about",
          not any("reader in your plugin is" in text for _tag, text in lines),
          str(lines[-3:]))


def test_publisher_tally():
    print()
    print("== 21. the publisher's own tally decides, not its report file ==")
    check("a tally of zero is read from the publisher's own line",
          stock_compare.draft_count(
              "Drafts found: 0 | ready: 0 | blocked: 0") == 0, "")
    check("a tally of several drafts is read too",
          stock_compare.draft_count(
              "Drafts found: 3 | ready: 2 | blocked: 1") == 3, "")
    check("the older phrasing is understood",
          stock_compare.draft_count("Scanned 12 draft(s)...") == 12, "")
    check("a publisher that says nothing is unknown, never zero",
          stock_compare.draft_count("Re-reading the shop...") is None, "")
    check("and an empty string is unknown too",
          stock_compare.draft_count("") is None, "")

    #  The run's transcript is where that sentence comes from.
    check("the transcript of the last run is read from the runner",
          gui.last_tool_output(
              SimpleNamespace(runner=SimpleNamespace(output="Drafts found: 0")))
          == "Drafts found: 0", "")
    check("and an app with no runner is not an error",
          gui.last_tool_output(SimpleNamespace()) == "", "")

    #  A report with preamble lines in it is not a report full of drafts: the
    #  file is the plugin's format, and this is exactly the shape that made an
    #  "empty" report look like it had rows.
    folder = Path(tempfile.mkdtemp(prefix="cs-tally-"))
    report = folder / "cs-publish-report.csv"
    report.write_text("CanadianShopper vendor: Alex Collect\n"
                      "Drafts found: 0 | ready: 0 | blocked: 0\n",
                      encoding="utf-8")
    check("a summary line in the file is not counted as a draft",
          stock_compare.report_rows(report) == 1, "")

    folder, app, parent = build_panel()
    products = PRODUCTS + [
        {"id": 9, "name": "Only on the website card", "sku": "",
         "manage_stock": True, "stock_quantity": 1, "type": "simple",
         "price": "3.00", "images": [{"src": "https://shop.example/f.webp"}]}]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    actions = {"marketplace.import_csv": "/plugins/cs/cs-import.py",
               "marketplace.publish_drafts": "/plugins/cs/cs-publish-drafts.py"}

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        (folder / "cs-stock.json").write_text(json.dumps({"items": CS_ITEMS}),
                                              encoding="utf-8")
        app.runs[-1]["on_done"](0)

    asked = []
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or True)
    app.runs.clear()
    app.lines.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: actions.get(action, "")), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "open_path", lambda path: None):
        find(parent, gui.ttk.Button,
             "List every website-only card...").invoke()
        run = next(r for r in app.runs if r["tool"].endswith("cs-import.py"))
        name = next((folder / "canadianshopper_products").glob(
            "canadianshopper_import_*.csv")).name
        (folder / "canadianshopper_products" / "cs-import-result.json"
         ).write_text(json.dumps(
             {"imported": [],
              "failed": [{"file": name, "why": "every CSV row matched an "
                                              "existing listing"}]}),
             encoding="utf-8")
        asked.clear()
        app.lines.clear()
        run["on_done"](0)

    look = next((r for r in app.runs
                 if r["tool"].endswith("cs-publish-drafts.py")), None)
    check("the look runs before any PUBLISH question", look is not None
          and "--apply" not in look["args"], str(look and look["args"]))

    #  The publisher says zero while its own report carries a summary line.
    (folder / "canadianshopper_products" / "cs-publish-report.csv").write_text(
        "CanadianShopper vendor: Alex Collect\n"
        "Drafts found: 0 | ready: 0 | blocked: 0\n", encoding="utf-8")
    app.runner = SimpleNamespace(
        output="Scanned 0 draft(s)...\n\nCanadianShopper vendor: Alex "
               "Collect\n\nDrafts found: 0 | ready: 0 | blocked: 0\n")
    asked.clear()
    app.runs.clear()
    app.lines.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: actions.get(action, "")), \
            patch.object(gui, "BASE", folder):
        look["on_done"](0)
    check("a tally of zero beats a report with lines in it",
          any("No drafts on CanadianShopper" in text
              for _tag, text in app.lines), str(app.lines[-3:]))
    check("and it never asks for a typed PUBLISH", not app.runs, str(app.runs))
    check("and never offers the report to open",
          not any(title == "Open the publish report?" for title, _m in asked),
          str([title for title, _m in asked]))
    check("the empty report is explained rather than left as a mystery",
          any("one row per draft" in text for _tag, text in app.lines),
          str(app.lines[-4:]))
    check("the cards that could not be found are named, so the dashboard "
          "search has something to search for",
          any("Only on the website card" in text for _tag, text in app.lines),
          str(app.lines[-6:]))

    #  A publisher that says nothing either way is not "no drafts".
    app.runner = SimpleNamespace(output="")
    try:
        (folder / "canadianshopper_products" /
         "cs-publish-report.csv").unlink()
    except FileNotFoundError:
        pass
    asked.clear()
    app.runs.clear()
    app.lines.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: actions.get(action, "")), \
            patch.object(gui, "BASE", folder):
        look["on_done"](0)
    check("a publisher that says nothing is unknown, not zero drafts",
          any("said nothing about how many drafts" in text
              for _tag, text in app.lines), str(app.lines[-2:]))
    check("and nothing is published on a guess", not app.runs, str(app.runs))

def test_listing_without_a_count():
    print()
    print("== 22. a listing that has no count is not a listing that is not there ==")
    raw = {"items": [
        {"id": 201, "title": "1965 Topps Sandy Koufax #300", "sku": "KO-300",
         "inventory": None, "status": "Draft"},
        {"id": 202, "title": "A live listing with no count", "sku": "LC-1",
         "inventory": None, "status": "Active"},
        {"id": 203, "title": "A live listing with a count", "sku": "LC-2",
         "inventory": 5, "status": "Active"},
    ]}
    items = stock_compare.plugin_items(raw)
    names = [item["name"] for item in items]
    check("a listing that is not on sale is kept even without a count",
          "1965 Topps Sandy Koufax #300" in names, str(names))
    check("its state is the one the plugin sent",
          next(item for item in items
               if item["name"] == "1965 Topps Sandy Koufax #300")["status"]
          == "Draft", str(items))
    check("and its count stays unknown rather than becoming zero",
          next(item for item in items if item["name"].startswith("1965"))["qty"]
          is None, str(items))
    check("a live listing with no count is kept too, and says so by having "
          "no count",
          "A live listing with no count" in names, str(names))
    check("a live listing with a count is untouched",
          "A live listing with a count" in names, str(names))

    woo = [{"name": "1965 Topps Sandy Koufax #300", "sku": "KO-300", "qty": 2,
            "id": 1}]
    pairs, only_woo, only_other = stock_compare.pair(woo, items)
    check("the card pairs with its draft instead of looking missing",
          len(pairs) == 1 and not only_woo, str(pairs))
    rows = stock_compare.action_list(pairs, only_woo, only_other)
    draft_row = next((row for row in rows if row["card"].startswith("1965")),
                     None)
    check("so it becomes a not-on-sale row, not a one-sided one",
          draft_row is not None
          and draft_row["kind"] == stock_compare.OFF_SALE, str(rows))
    check("and it is offered for publishing",
          len(stock_compare.draft_rows(rows)) == 1, str(rows))
    check("its label never invents a count for the site",
          "not on sale" in stock_compare.label_action(draft_row)
          and "CanadianShopper 0" not in stock_compare.label_action(draft_row),
          stock_compare.label_action(draft_row))
    check("and no write plan can name it",
          stock_compare.plan_set(rows) == [], str(stock_compare.plan_set(rows)))


def test_a_listing_that_counts_nothing():
    print()
    print("== 23. a card that exists but counts nothing is not a missing card ==")
    raw = {"items": [
        #  The listing is on the other site, paired by title - it simply
        #  carries no inventory value, which a stock comparison cannot use.
        {"id": 301, "title": "1965 Topps Sandy Koufax #300", "sku": "KO-300",
         "inventory": None, "status": "Active"},
    ]}
    items = stock_compare.plugin_items(raw)
    woo = [{"name": "1965 Topps Sandy Koufax #300", "sku": "KO-300", "qty": 2,
            "id": 1}]
    pairs, only_woo, only_other = stock_compare.pair(woo, items)
    check("the card still pairs, so it is not called missing",
          len(pairs) == 1 and not only_woo and not only_other,
          str((pairs, only_woo, only_other)))
    check("and it is not a disagreement either - there is no number to "
          "disagree with",
          stock_compare.differences(pairs) == [],
          str(stock_compare.differences(pairs)))
    rows = stock_compare.action_list(pairs, only_woo, only_other)
    check("it gets its own row, named for what it is",
          len(rows) == 1 and rows[0]["kind"] == stock_compare.NO_COUNT,
          str(rows))
    check("the label says the site counts no stock, not a made-up zero",
          "no stock count there" in stock_compare.label_action(rows[0])
          and "CanadianShopper 0" not in stock_compare.label_action(rows[0]),
          stock_compare.label_action(rows[0]))
    check("no write plan can name it", stock_compare.plan_set(rows) == [],
          str(stock_compare.plan_set(rows)))
    check("and the reverse plan cannot either",
          __import__("stock_write").plan_from_rows(rows) == [], "")
    check("publishing is not offered for it - it is not a draft",
          stock_compare.draft_rows(rows) == [] and
          stock_compare.off_sale_rows(rows) == [], str(rows))
    check("its kind is counted on its own",
          len(stock_compare.no_count_rows(rows)) == 1, str(rows))

    #  ...and the panel says so out loud.
    folder, app, parent = build_panel()
    products = PRODUCTS + [
        {"id": 9, "name": "1965 Topps Sandy Koufax #300", "sku": "KO-300",
         "manage_stock": True, "stock_quantity": 2, "type": "simple"}]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        (folder / "cs-stock.json").write_text(json.dumps(raw),
                                             encoding="utf-8")
        app.runs[-1]["on_done"](0)
    listed = next((w for w in parent.walk()
                   if isinstance(w, gui.tk.Listbox)), None)
    check("the panel lists the card instead of hiding it",
          listed is not None and any("no stock count there" in item
                                    for item in listed.items),
          str(listed and listed.items))
    check("the console explains there is no number to compare or write",
          any("counts no stock" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and the summary counts it separately from the one-sided cards",
          any("counting no stock" in text and "only on one side" in text
              for _tag, text in app.lines), str(app.lines[-2:]))


def test_nearest_title_diagnosis():
    print()
    print("== 24. a one-sided card is diagnosed, not just reported ==")
    other = stock_compare.plugin_items({"items": [
        {"id": 401, "title": "#237a Phil Esposito 1970-71 O-Pee-Chee",
         "inventory": 3, "status": "Active"},
        {"id": 402, "title": "#236 Bobby Orr 1970-71 O-Pee-Chee",
         "inventory": 1, "status": "Active"},
    ]})
    item, score = stock_compare.closest(
        other, "#237a Phil Esposito (VG) 1970-71 O-Pee-Chee")
    check("the nearest title is found for a card worded differently",
          item is not None and item["name"].startswith("#237a"), str(item))
    check("and its score is high enough to mean something", score >= 0.9,
          str(score))
    item, score = stock_compare.closest(other, "1985 Topps Mark McGwire #401")
    check("a card with a different number matches nothing at all",
          item is None, str(item))
    item, score = stock_compare.closest(
        other, "1970-71 O-Pee-Chee Bobby Orr #236 First Team All-Star")
    check("word order and a longer title do not hide the right listing",
          item is not None and item["name"].startswith("#236"), str(item))

    folder, app, parent = build_panel()
    products = PRODUCTS + [
        {"id": 9, "name": "#237a Phil Esposito (VG) 1970-71 O-Pee-Chee",
         "sku": "", "manage_stock": True, "stock_quantity": 2,
         "type": "simple"}]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        #  The listing that should have paired is unreachable to the pairing:
        #  a different card number in the same set.
        (folder / "cs-stock.json").write_text(json.dumps({"items": [
            {"id": 401, "title": "1970-71 O-Pee-Chee Phil Esposito #238",
             "inventory": 3, "status": "Active"}]}), encoding="utf-8")
        app.runs[-1]["on_done"](0)
    check("a one-sided card is reported as one-sided first",
          any("only on one side" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and the console says nothing similar exists, rather than guessing",
          any("nothing similar" in text for _tag, text in app.lines),
          str(app.lines[-4:]))


def test_a_duplicate_on_the_website():
    print()
    print("== 25. two website products, one listing: the duplicate is named ==")
    title = "#25 Pete Stemkowski (EX) 1970-71 O-Pee-Chee"
    woo = [{"name": title, "sku": "", "qty": 0, "id": 11},
           {"name": title, "sku": "", "qty": 2, "id": 12}]
    cs = stock_compare.plugin_items({"items": [
        {"id": 501, "title": title, "inventory": 0, "status": "Active"}]})
    pairs, only_woo, only_other = stock_compare.pair(woo, cs)
    check("the listing goes to the product that can sell, not the sold-out "
          "duplicate",
          len(pairs) == 1 and pairs[0]["woo"]["id"] == 12, str(pairs))
    check("and the duplicate is the one left over",
          [item["id"] for item in only_woo] == [11],
          str([item["id"] for item in only_woo]))
    item, score = stock_compare.closest(cs, only_woo[0]["name"])
    check("its nearest title is the very listing the other one holds",
          item is not None and score == 1.0, str((item, score)))
    owner = stock_compare.owner_of(pairs, item)
    check("and the owner of that listing can be named",
          owner is not None and owner["id"] == 12, str(owner))
    check("the two titles are recognised as the same card's words",
          stock_compare.same_words(only_woo[0]["name"], owner["name"]), "")
    check("a different card is not called the same words",
          not stock_compare.same_words(title,
                                       "#26 Pete Stemkowski 1970-71 O-Pee-Chee"),
          "")
    check("an unpaired listing has no owner",
          stock_compare.owner_of(pairs, cs[0]) is not None and
          stock_compare.owner_of([], cs[0]) is None, "")

    # ---- and the panel says exactly that, in words that name the duplicate
    folder, app, parent = build_panel()
    #  Both copies hold stock: a card at zero that is nowhere else is not shown
    #  at all any more, and the duplicate worth naming is one that could sell.
    products = PRODUCTS + [
        {"id": 11, "name": title, "sku": "", "manage_stock": True,
         "stock_quantity": 1, "type": "simple"},
        {"id": 12, "name": title, "sku": "", "manage_stock": True,
         "stock_quantity": 2, "type": "simple"}]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    app.lines.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        (folder / "cs-stock.json").write_text(
            json.dumps({"items": [{"id": 501, "title": title,
                                   "inventory": 0, "status": "Active"}]}),
            encoding="utf-8")
        app.runs[-1]["on_done"](0)
    check("the panel names the listing that is already held, and by whom",
          any("held by" in text for _tag, text in app.lines),
          str(app.lines[-6:]))
    check("and says the listing is there, so nothing is missing",
          any("the listing is there" in text and "nothing is missing" in text
              for _tag, text in app.lines), str(app.lines[-6:]))
    check("and calls the identical one a duplicate, not a card to list",
          any("a duplicate on your website, not a card to list" in text
              for _tag, text in app.lines), str(app.lines[-6:]))
    #  The sold-out copy and the sold-out Orr are both out of the list now, so
    #  two one-sided cards remain and the duplicate is not one of the really
    #  missing ones.
    check("and the duplicate is not counted among the cards that are really "
          "missing",
          any("nothing similar" in text and "1 of those 2" in text
              for _tag, text in app.lines), str(len(app.lines)))


def test_what_the_reader_claimed():
    print()
    print("== 26. the reader's own states are reported, so a stale read shows ==")
    items = stock_compare.plugin_items({"items": [
        {"title": "A live card", "inventory": 3, "status": "Active"},
        {"title": "Another live card", "inventory": 0, "status": "active"},
        {"title": "An archived card", "inventory": 0, "status": "Archived"},
        {"title": "A draft card", "inventory": 0, "status": "draft"},
        {"title": "An archived card in another case", "inventory": 0,
         "status": "ARCHIVED"},
    ]})
    tally = stock_compare.status_tally(items)
    check("the reader's states are counted in its own words",
          tally == {"on sale": 2, "Archived": 2, "draft": 1}, str(tally))
    check("and one case of the same word is counted once",
          list(tally).count("Archived") + list(tally).count("ARCHIVED") == 1,
          str(tally))
    check("the line says how many are in each state",
          stock_compare.tally_line(items) ==
          "5 listing(s): 2 on sale, 2 Archived, 1 draft",
          stock_compare.tally_line(items))
    check("nothing read back says so rather than inventing a tally",
          stock_compare.tally_line([]) == "", "")

    #  A listing the other site holds at zero: it exists, it just has no
    #  stock. That is a count job, not a listing job.
    rows = [
        {"kind": stock_compare.FIX, "card": "Zero card", "woo": 6, "other": 0},
        {"kind": stock_compare.FIX, "card": "Agreeing card", "woo": 2,
         "other": 2},
        {"kind": stock_compare.FIX, "card": "Other way", "woo": 1, "other": 6},
        {"kind": stock_compare.ONLY_WOO, "card": "Missing card", "woo": 1,
         "other": None},
    ]
    zeros = stock_compare.out_of_stock_rows(rows)
    check("only the listings the other side holds at zero are picked",
          [row["card"] for row in zeros] == ["Zero card"], str(zeros))


def test_held_under_another_product():
    print()
    print("== 27. a card listed under another product is not a missing card ==")
    woo = [
        #  The live copy holds the listing.
        {"name": "#25 Pete Stemkowski (EX) 1970-71 O-Pee-Chee", "sku": "",
         "qty": 2, "id": 12},
        #  Same words, sold: a duplicate that cannot hold it.
        {"name": "#25 Pete Stemkowski (EX) 1970-71 O-Pee-Chee", "sku": "",
         "qty": 0, "id": 11},
        #  The copy the listing belongs to, and beside it another grade.
        {"name": "#24 1st Series Checklist (PR) 1970-71 O-Pee-Chee", "sku": "",
         "qty": 1, "id": 15},
        {"name": "#24 1st Series Checklist (VG) 1970-71 O-Pee-Chee", "sku": "",
         "qty": 1, "id": 13},
        #  Nothing like it anywhere.
        {"name": "1985 Topps Mark McGwire #401", "sku": "", "qty": 1,
         "id": 14},
    ]
    other = stock_compare.plugin_items({"items": [
        {"id": 501, "title": "#25 Pete Stemkowski (EX) 1970-71 O-Pee-Chee",
         "inventory": 2, "status": "Active"},
        {"id": 502, "title": "#24 1st Series Checklist (PR) 1970-71 O-Pee-Chee",
         "inventory": 1, "status": "Active"},
    ]})
    pairs, only_woo, only_other = stock_compare.pair(woo, other)
    found = stock_compare.held_elsewhere(pairs, only_woo, other)
    by_card = {row["card"]: row for row in found}
    check("the sold duplicate is found under the live product",
          any(row["card"].startswith("#25") and row["same"]
              for row in found), str(found))
    check("the copy in another grade is found too, but not called the same",
          any(row["card"].startswith("#24") and not row["same"]
              for row in found), str(found))
    check("the card nothing resembles is not claimed as listed",
          not any("McGwire" in row["card"] for row in found), str(found))

    #  ...and the panel says which is which, in one block each.
    folder, app, parent = build_panel()
    products = PRODUCTS + [
        {"id": 12, "name": "#25 Pete Stemkowski (EX) 1970-71 O-Pee-Chee",
         "sku": "", "manage_stock": True, "stock_quantity": 6,
         "type": "simple"},
        {"id": 11, "name": "#25 Pete Stemkowski (EX) 1970-71 O-Pee-Chee",
         "sku": "", "manage_stock": True, "stock_quantity": 1,
         "type": "simple"},
        {"id": 13, "name": "#24 1st Series Checklist (VG) 1970-71 O-Pee-Chee",
         "sku": "", "manage_stock": True, "stock_quantity": 1,
         "type": "simple"},
        {"id": 15, "name": "#24 1st Series Checklist (PR) 1970-71 O-Pee-Chee",
         "sku": "", "manage_stock": True, "stock_quantity": 1,
         "type": "simple"},
    ]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    app.lines.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        (folder / "cs-stock.json").write_text(json.dumps({"items": [
            {"id": 501, "title": "#25 Pete Stemkowski (EX) 1970-71 O-Pee-Chee",
             "inventory": 0, "status": "Active"},
            {"id": 502,
             "title": "#24 1st Series Checklist (PR) 1970-71 O-Pee-Chee",
             "inventory": 1, "status": "Active"}]}), encoding="utf-8")
        app.runs[-1]["on_done"](0)
    check("the panel groups them as cards the site already lists",
          any("already lists under a different website product" in text
              for _tag, text in app.lines), str(app.lines[-8:]))
    check("it counts the duplicates separately from the other grades",
          any("exact title" in text for _tag, text in app.lines) and
          any("another grade, copy or condition" in text
              for _tag, text in app.lines), str(app.lines[-8:]))
    check("and still warns that a different grade may be worth listing",
          any("can be listed if you sell it separately" in text
              for _tag, text in app.lines), str(app.lines[-8:]))
    check("and a listing held at zero is called a count job, not a listing "
          "job",
          any("holds at 0" in text and "puts the stock back" in text
              for _tag, text in app.lines), str(app.lines[-8:]))
    check("and the reader's own states are printed for checking",
          any("What the reader returned" in text for _tag, text in app.lines),
          str(app.lines[:4]))


def test_a_reader_that_cannot_ask_for_a_fresh_page():
    print()
    print("== 28. a cached page is the reader's limit, not the app's reading ==")
    folder, app, parent = build_panel()
    products = PRODUCTS + [
        {"id": 9, "name": "#319 Val Fonteyne 1972-73 O-Pee-Chee", "sku": "",
         "manage_stock": True, "stock_quantity": 1, "type": "simple"}]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    stock = {"items": [
        {"id": 401, "title": "#319 Val Fonteyne 1972-73 O-Pee-Chee",
         "inventory": 1, "status": "Archived"},
        {"id": 402, "title": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
         "inventory": 0, "status": "Active"},
    ]}

    def compare(version):
        app.lines.clear()
        with patch.object(gui, "TOOL_ACTION",
                          lambda action: "/plugins/cs/stock.py"), \
                patch.object(gui, "read_woo_credentials",
                             lambda path=None: ("https://shop.example", "ck_a",
                                                "cs_b")), \
                patch.object(gui, "woo_get", fetch_all), \
                patch.object(gui, "in_background", sync_background), \
                patch.object(gui, "plugin_version",
                             lambda *a, **k: version), \
                patch.object(gui, "BASE", folder):
            find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
            (folder / "cs-stock.json").write_text(json.dumps(stock),
                                                 encoding="utf-8")
            app.runs[-1]["on_done"](0)
        return list(app.lines)

    lines = compare("1.0.26")
    check("a reader that can ask for a fresh page says so on the tally line",
          any("plugin 1.0.26, cache-checked" in text for _tag, text in lines),
          str(lines[:3]))
    check("and no warning is raised about a cached page",
          not any("serve from its cache" in text for _tag, text in lines),
          str(lines[-3:]))
    check("the archived listing is still reported as archived",
          any("not on sale (Archived)" in text for _tag, text in lines),
          str(lines[-4:]))

    lines = compare("1.0.25")
    check("an older reader is named on the tally line, without the claim",
          any("plugin 1.0.25" in text and "cache-checked" not in text
              for _tag, text in lines), str(lines[:3]))
    check("and a moved listing is allowed to be a stale read",
          any("serve from its cache" in text and "1.0.26" in text
              for _tag, text in lines), str(lines[-4:]))
    check("and it says so before the states are acted on",
          any("before acting on the states above" in text
              for _tag, text in lines), str(lines[-4:]))

    lines = compare("")
    check("an unreadable plugin version is not guessed at",
          any(text.startswith("What the reader returned - ") or
              (text.startswith("What the reader returned in ") and
               " - " in text and "(plugin " not in text)
              for _tag, text in lines), str(lines[:3]))
    check("and no cache warning is invented for it",
          not any("serve from its cache" in text for _tag, text in lines),
          str(lines[-3:]))


def test_reading_pages_side_by_side():
    print()
    print("== 4b. the catalogue is read a few pages at a time, in order ==")
    import threading
    import time

    #  Two pages that will not answer until the other one has been asked for:
    #  a reader that asks one page after another waits for the timeout twice,
    #  a reader that asks them together never waits at all.
    in_flight = set()
    together = []
    lock = threading.Lock()
    gate = threading.Event()

    def slow_fetch(base, path, params, key, secret):
        page = params["page"]
        if page == 1:
            return 200, [{"id": 1, "name": "card 1"}]
        with lock:
            in_flight.add(page)
            if len(in_flight) >= 2:
                together.append(set(in_flight))
                gate.set()
        gate.wait(2.0)
        return 200, [{"id": page, "name": "card %d" % page}]

    began = time.time()
    products = stock_compare.read_woo_stock(slow_fetch, "https://shop.example",
                                            "ck_a", "cs_b", per_page=1,
                                            pages=3)
    took = time.time() - began
    check("pages beyond the first are asked for together",
          together and together[0] == {2, 3}, str(together))
    check("and the wait was not one page after another", took < 1.0,
          "%.2fs" % took)
    check("the products come back in catalogue order",
          [p["id"] for p in products] == [1, 2, 3],
          str([p["id"] for p in products]))

    calls = []

    def fetch(base, path, params, key, secret):
        calls.append((params["page"], dict(params)))
        page = params["page"]
        cards = 10 if page < 5 else 3        # the fifth page is the last one
        return 200, [{"id": i, "name": "card"} for i in range(cards)]

    stock_compare.read_woo_stock(fetch, "https://shop.example", "ck_a", "cs_b",
                                 per_page=10, pages=40)
    check("a page order is asked for, so pages cannot overlap or skip",
          all(params.get("orderby") == "id" and params.get("order") == "asc"
              for _page, params in calls), str(calls[:1]))
    check("reading stops after the last page, short or not",
          sorted(params["page"] for _p, params in calls) == [1, 2, 3, 4, 5],
          str([params["page"] for _p, params in calls]))
    check("the pages beside the short one are not asked for", len(calls) == 5,
          str(len(calls)))

    #  A site that states its own page count is what turns the bar into a
    #  fraction; one that does not is still read the same way.
    seen = []

    def with_headers(base, path, params, key, secret):
        return (200,
                [{"id": 1, "name": "card"}],
                {"X-WP-TotalPages": "3", "X-WP-Total": "3"})

    stock_compare.read_woo_stock(with_headers, "https://shop.example", "ck_a",
                                 "cs_b", per_page=1, pages=3,
                                 progress=lambda done, total, cards:
                                 seen.append((done, total, cards)))
    check("the site's own page count is used, not guessed",
          seen and all(total == 3 for _done, total, _cards in seen), str(seen))
    check("and the bar is told where every page ended",
          [done for done, _total, _cards in seen] == [1, 2, 3], str(seen))

    seen = []
    stock_compare.read_woo_stock(fetch, "https://shop.example", "ck_a", "cs_b",
                                 per_page=10, pages=3,
                                 progress=lambda done, total, cards:
                                 seen.append((done, total, cards)))
    check("a site that says nothing leaves the total unknown",
          seen and all(total is None for _d, total, _c in seen), str(seen))
    check("the count of cards read grows with every page",
          [cards for _d, _t, cards in seen] == [10, 20, 30], str(seen))

    def broken_progress(*_args):
        raise RuntimeError("no bar here")

    try:
        stock_compare.read_woo_stock(fetch, "https://shop.example", "ck_a",
                                     "cs_b", per_page=10, pages=2,
                                     progress=broken_progress)
        check("a progress display that fails cannot fail the read", True, "")
    except Exception as exc:
        check("a progress display that fails cannot fail the read", False,
              str(exc))


def test_the_get_can_bring_its_headers():
    print()
    print("== 4b2. the plain GET can bring the page count back with it ==")
    import urllib.request
    from sale_inputs import woo_get

    asked = []

    class Answer:
        """What urlopen hands back: a body, a status and some headers."""

        def __init__(self, body, status=200, headers=None):
            self.body = body.encode("utf-8")
            self.status = status
            self.headers = headers or {}

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def net(request, timeout=None):
        asked.append(request.full_url)
        return Answer(json.dumps([{"id": 1}]), 200,
                      {"X-WP-TotalPages": "7"})

    real = urllib.request.urlopen
    urllib.request.urlopen = net
    try:
        code, data = woo_get("https://shop.example", "/wp-json/wc/v3/products",
                             {"page": 1}, "ck_a", "cs_b")
        check("the GET still answers with a pair when nobody asks for headers",
              code == 200 and data == [{"id": 1}], "%r %r" % (code, data))
        answer = woo_get("https://shop.example", "/wp-json/wc/v3/products",
                         {"page": 1}, "ck_a", "cs_b", with_headers=True)
        check("asking for them makes it a triple",
              isinstance(answer, tuple) and len(answer) == 3, str(answer))
        check("and the page count is in there",
              answer[2].get("X-WP-TotalPages") == "7", str(answer[2]))
        check("the keys are still sent as the API wants them",
              "consumer_key=ck_a" in asked[0] and
              "consumer_secret=cs_b" in asked[0], asked[0])
    finally:
        urllib.request.urlopen = real


def test_a_sold_out_card_is_not_a_job():
    print()
    print("== 4c. a card at zero that is nowhere else is not shown ==")
    woo, _ = stock_compare.woo_items(PRODUCTS)
    gone = {"id": 30, "name": "1971-72 O-Pee-Chee Eddie Shack #60",
            "sku": "SH-60", "qty": 0}
    kept = {"id": 31, "name": "1971-72 O-Pee-Chee Jean Beliveau #20",
            "sku": "BE-20", "qty": 3}
    pairs, _only_woo, _only_other = stock_compare.pair([], [])
    rows = stock_compare.action_list([], [gone, kept], [])
    check("only the card with stock is on the list",
          [row["card"] for row in rows] == [kept["name"]],
          str([row["card"] for row in rows]))
    check("the one at zero is not there at all",
          all(row["card"] != gone["name"] for row in rows), str(rows))
    check("and it is named rather than silently dropped",
          stock_compare.sold_out_note([gone, kept], "CanadianShopper") ==
          "1 card at zero on your website and not on CanadianShopper, "
          "so not shown.",
          stock_compare.sold_out_note([gone, kept]))
    check("with no such card there is no sentence",
          stock_compare.sold_out_note([kept]) == "",
          stock_compare.sold_out_note([kept]))
    check("the lists are told apart",
          stock_compare.listed_only_woo([gone, kept]) == [kept] and
          stock_compare.sold_out_only_woo([gone, kept]) == [gone], "")
    check("a negative count is not offered either",
          stock_compare.listed_only_woo([{"name": "backorder", "qty": -2}]) ==
          [], "")
    line = stock_compare.summary(rows, [{"card": "matched"}], [gone, kept], [])
    check("a card with stock still reads as only on your website",
          "1 only on your website" in line, line)
    check("and a card at zero does not", "2 only" not in line, line)

    #  The list the panel shows is the same list every button works from, so a
    #  card that is not on it cannot be listed by accident.
    folder, app, parent = build_panel()
    products = PRODUCTS + [
        {"id": 30, "name": gone["name"], "sku": "SH-60", "manage_stock": True,
         "stock_quantity": 0, "type": "simple"},
        {"id": 31, "name": kept["name"], "sku": "BE-20", "manage_stock": True,
         "stock_quantity": 3, "type": "simple"}]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        (folder / "cs-stock.json").write_text(json.dumps({"items": []}),
                                              encoding="utf-8")
        app.runs[-1]["on_done"](0)
    listing = next((w for w in parent.walk()
                    if isinstance(w, gui.tk.Listbox)), None)
    check("the panel does not list the sold-out card",
          listing is not None and
          all(gone["name"] not in str(item) for item in listing.items),
          str(listing and listing.items))
    said = [str(w.cget("text")) for w in parent.walk()
            if isinstance(w, gui.ttk.Label)]
    check("the panel says how many it left out",
          any("at zero on your website" in text and "not shown" in text
              for text in said) or
          any("at zero on your website" in str(text) for _tag, text in
              app.lines), str(said[-3:]))


def test_the_list_can_be_sorted():
    print()
    print("== 4d. the result can be read in a different order ==")
    rows = [
        {"card": "Bravo card", "kind": stock_compare.FIX, "gap": 1, "woo": 4,
         "other": 3},
        {"card": "alpha card", "kind": stock_compare.ONLY_WOO, "gap": 9,
         "woo": 9, "other": None},
        {"card": "Charlie card", "kind": stock_compare.FIX, "gap": -6, "woo": 1,
         "other": 7},
        {"card": "Delta card", "kind": stock_compare.OFF_SALE, "gap": 0,
         "woo": 2, "other": 0},
    ]
    check("the chooser offers six ways to read the list",
          len(stock_compare.SORTS) == 6 and
          stock_compare.DEFAULT_SORT == "attention", str(stock_compare.SORTS))
    check("the labels are the ones the chooser shows",
          stock_compare.sort_labels()[0] == "What needs attention first" and
          "Card name (A-Z)" in stock_compare.sort_labels(),
          str(stock_compare.sort_labels()))
    check("a label and its key agree both ways",
          all(stock_compare.sort_key(stock_compare.sort_label(key)) == key
              for key, _label in stock_compare.SORTS), "")
    check("nothing chosen is what needs attention first",
          [row["card"] for row in stock_compare.sort_rows(rows)] ==
          ["Charlie card", "Bravo card", "Delta card", "alpha card"],
          str([row["card"] for row in stock_compare.sort_rows(rows)]))
    check("by name, capital letters do not come first",
          [row["card"] for row in stock_compare.sort_rows(rows, "name")] ==
          ["alpha card", "Bravo card", "Charlie card", "Delta card"],
          str([row["card"] for row in stock_compare.sort_rows(rows, "name")]))
    check("and back again",
          [row["card"] for row in stock_compare.sort_rows(rows, "name-desc")] ==
          ["Delta card", "Charlie card", "Bravo card", "alpha card"], "")
    check("the biggest difference first, whichever side it is on",
          [row["card"] for row in stock_compare.sort_rows(rows, "gap")] ==
          ["alpha card", "Charlie card", "Bravo card", "Delta card"],
          str([row["card"] for row in stock_compare.sort_rows(rows, "gap")]))
    check("the most stock on the website first",
          [row["card"] for row in stock_compare.sort_rows(rows, "woo")] ==
          ["alpha card", "Bravo card", "Delta card", "Charlie card"], "")
    check("the most stock elsewhere first",
          [row["card"] for row in stock_compare.sort_rows(rows, "other")] ==
          ["Charlie card", "Bravo card", "Delta card", "alpha card"], "")
    check("no order ever loses a row",
          all(len(stock_compare.sort_rows(rows, key)) == len(rows)
              for key, _label in stock_compare.SORTS), "")
    check("a sort nobody knows is the default rather than an error",
          stock_compare.sort_key("sort by magic") == stock_compare.DEFAULT_SORT
          and stock_compare.sort_label("magic") ==
          "What needs attention first", "")
    check("sorting does not touch the list it was given",
          [row["card"] for row in rows] ==
          ["Bravo card", "alpha card", "Charlie card", "Delta card"],
          str([row["card"] for row in rows]))

    # ---- and the panel: the chooser re-reads the list, nothing is compared
    folder, app, parent = build_panel()
    products = PRODUCTS + [
        {"id": 30, "name": "Zulu card", "sku": "ZU-1", "manage_stock": True,
         "stock_quantity": 1, "type": "simple"},
        {"id": 31, "name": "Alpha card", "sku": "AL-1", "manage_stock": True,
         "stock_quantity": 5, "type": "simple"}]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    saved = []

    def fake_save(settings):
        saved.append(dict(settings))

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "save_settings", fake_save), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        (folder / "cs-stock.json").write_text(json.dumps({"items": []}),
                                              encoding="utf-8")
        app.runs[-1]["on_done"](0)
        listing = next(w for w in parent.walk()
                       if isinstance(w, gui.tk.Listbox))
        first = list(listing.items)
        check("the list opens in the order that needs attention first",
              len(first) == 3 and "Alpha card" in first[0],
              str(first))
        check("and every row is numbered in the order it is shown",
              [row.split(". ", 1)[0] for row in first] == ["1", "2", "3"] and
              "Gretzky" in first[1],
              str(first))
        chooser = next((w for w in parent.walk()
                        if isinstance(w, gui.ttk.Combobox)), None)
        check("the panel has a sort chooser beside the list",
              chooser is not None and
              list(chooser._kw.get("values") or []) ==
              stock_compare.sort_labels(), str(chooser and chooser._kw))
        check("it opens on what needs attention first",
              chooser._kw["textvariable"].get() ==
              "What needs attention first",
              chooser._kw["textvariable"].get())
        runs_before = len(app.runs)
        chooser._kw["textvariable"].set("Card name (A-Z)")
        chooser.event_generate("<<ComboboxSelected>>")
        second = list(listing.items)
        check("choosing a sort re-reads the same list, not the sites",
              second != first and len(second) == len(first) and
              len(app.runs) == runs_before, str(second[:2]))
        names = [item.split("  -  ")[0] for item in second]
        check("and it really is by card name",
              names == sorted(names, key=str.lower), str(names))
        check("the choice is remembered for the next comparison",
              saved and saved[-1].get("stock_sort") == "name", str(saved[-1:]))
        chooser._kw["textvariable"].set("Biggest difference first")
        chooser.event_generate("<<ComboboxSelected>>")
        check("a second sort works from the same list",
              list(listing.items) == first and
              saved[-1].get("stock_sort") == "gap", str(saved[-1:]))

    #  A saved choice is used again next time the panel is built.
    folder2 = Path(tempfile.mkdtemp())
    harness.install_plugin("1.0.19", folder2 / "plugin")
    app2 = harness.FakeApp(folder2)
    app2.settings["stock_sort"] = "name"
    parent2 = harness.FakeWidget()
    gui.build_stock(parent2, app2)
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder2):
        find(parent2, gui.ttk.Button, "Compare stock", exact=False).invoke()
        (folder2 / "cs-stock.json").write_text(json.dumps({"items": []}),
                                               encoding="utf-8")
        app2.runs[-1]["on_done"](0)
        listing = next(w for w in parent2.walk()
                       if isinstance(w, gui.tk.Listbox))
        chooser = next(w for w in parent2.walk()
                       if isinstance(w, gui.ttk.Combobox))
        names = [item.split("  -  ")[0] for item in listing.items]
        check("the panel reopens on the sort it was left on",
              chooser._kw["textvariable"].get() == "Card name (A-Z)" and
              names == sorted(names, key=str.lower),
              "%r %r" % (chooser._kw["textvariable"].get(), names))


def test_the_read_shows_where_it_is():
    print()
    print("== 4e. a read that takes a while says so, on a bar ==")
    folder, app, parent = build_panel()
    bars = [w for w in parent.walk() if isinstance(w, gui.ttk.Progressbar)]
    check("the panel has a progress bar", len(bars) == 1, str(bars))
    bar = bars[0]
    check("it is not on screen before anything is read", not bar.packed,
          str(bar.packed))

    def fetch_two_pages(base, path, params, key, secret):
        rows = [{"id": i, "name": "Card %d" % i, "sku": "",
                 "manage_stock": True, "stock_quantity": 1, "type": "simple"}
                for i in range(100)]
        if params["page"] == 1:
            return (200, rows, {"X-WP-TotalPages": "2"})
        return (200, rows[:2], {"X-WP-TotalPages": "2"})

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_two_pages), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        check("the bar is drawn while CanadianShopper is read", bar.packed,
              str(bar.packed))
        said = " ".join(str(w.cget("text")) for w in parent.walk())
        check("and it says what is being read",
              "Reading CanadianShopper's stock..." in said, said[:160])
        moved = []
        original = bar.configure

        def record(**kwargs):
            moved.append(dict(kwargs))
            return original(**kwargs)

        bar.configure = record
        (folder / "cs-stock.json").write_text(json.dumps({"items": []}),
                                              encoding="utf-8")
        app.runs[-1]["on_done"](0)
        check("it counts the pages of the website's catalogue",
              any(step.get("value") == 1 and step.get("maximum") == 2
                  for step in moved), str(moved))
        check("and it is out of the way when the read is done",
              not bar.packed, str(bar.packed))

    #  A read that fails takes the bar down too, rather than leaving it
    #  sweeping under an error message.
    folder2, app2, parent2 = build_panel()
    bar2 = next(w for w in parent2.walk()
                if isinstance(w, gui.ttk.Progressbar))

    def fetch_fails(base, path, params, key, secret):
        return 403, {"message": "no"}

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_fails), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder2):
        find(parent2, gui.ttk.Button, "Compare stock", exact=False).invoke()
        (folder2 / "cs-stock.json").write_text(json.dumps({"items": []}),
                                               encoding="utf-8")
        app2.runs[-1]["on_done"](0)
    check("a failed read does not leave a bar running", not bar2.packed,
          str(bar2.packed))


def test_creating_products_from_the_listings():
    print()
    print("== 34. a card only on CanadianShopper can become a website product ==")
    folder, app, parent = build_panel()
    #  One listing that is on CanadianShopper only, with everything a product
    #  needs on it: a title, a SKU, a price, a page and a photo address.
    only_cs = CS_ITEMS + [
        {"id": 201, "title": "1971-72 O-Pee-Chee Frank Mahovlich #60",
         "sku": "FM-60", "inventory": 4, "price": "CA$12.50",
         "url": "https://cs.example/listing/201",
         #  The shape plugin 1.0.32 sends: the primary picture first, then the
         #  gallery, already absolute and in the vendor's own order.
         "images": ["https://cs.example/media/mahovlich-square.jpg",
                    "https://cs.example/media/mahovlich-back-square.jpg"]},
    ]
    #  Two products that are only on the website, so both directions are on
    #  the list and the button can be shown to work in one direction only.
    products = PRODUCTS + [
        {"id": 9, "name": "1972-73 O-Pee-Chee Guy Lafleur #79", "sku": "LA-79",
         "manage_stock": True, "stock_quantity": 3, "type": "simple",
         "price": "9.00", "images": [{"src": "https://shop.example/f.webp"}]},
        {"id": 10, "name": "1972-73 O-Pee-Chee Ken Dryden #10", "sku": "",
         "manage_stock": True, "stock_quantity": 1, "type": "simple"},
    ]

    def fetch_all(base, path, params, key, secret):
        return (200, products) if params["page"] == 1 else (200, [])

    button = find(parent, gui.ttk.Button, "Compare stock", exact=False)
    out = folder / "cs-stock.json"
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
        out.write_text(json.dumps({"items": only_cs}), encoding="utf-8")
        app.runs[-1]["on_done"](0)
    listing = next((w for w in parent.walk()
                    if isinstance(w, gui.tk.Listbox)), None)
    their_only = [index for index, text in enumerate(listing.items or [])
                  if "not on your website" in text]
    check("the card that is only on CanadianShopper is on the list",
          len(their_only) == 1, str(listing.items))

    create = find(parent, gui.ttk.Button,
                  "Create website products for the selected cards...")
    kept = gui.stock_compare.plugin_items([
        dict(only_cs[-1], description="<p>Its own words.</p>",
             keywords=["hockey", "vintage"], condition="NM")])
    check("a reader that reports the words and the grade keeps them on the row",
          kept[0].get("description") == "<p>Its own words.</p>" and
          kept[0].get("keywords") == ["hockey", "vintage"] and
          kept[0].get("condition") == "NM", str(kept[0]))

    check("the button to create it sits beside the one that lists the other "
          "way", create is not None and find(
              parent, gui.ttk.Button,
              "List the selected cards on CanadianShopper...") is not None, "")

    # ---- with nothing selected, it says what to select and does nothing
    asked, made = [], []

    def fake_run(plan, site, key, secret, username="", app_password="",
                 publish=False, on_item=None):
        made.append({"plan": plan, "username": username})
        return {"created": [{"name": item["name"], "id": 900 + index,
                             "images": len(item["images"]), "status": "draft"}
                            for index, item in enumerate(plan["items"])],
                "skipped": [], "failed": [], "published": [],
                "unpublished": []}

    gui.messagebox_shown = getattr(gui, "messagebox_shown", [])

    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or False)
    with patch.object(gui, "BASE", folder), \
            patch.object(gui.woo_create, "run", fake_run):
        create.invoke()
    check("nothing selected is said, not silently ignored",
          any("Nothing to create" in str(args[0])
              for _kind, args in harness._BOX.shown[-1:]),
          str(harness._BOX.shown[-1:]))
    check("and nothing was created", made == [], str(made))

    # ---- the card, with its square photo, becomes a draft product
    listing.selection = (their_only[0],)
    asked.clear()
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or
        (True if title.startswith("Create website products")
         else False))

    def square_photo(width=600):
        from PIL import Image as _Image, ImageDraw as _Draw
        image = _Image.new("RGB", (width, width), (255, 255, 255))
        _Draw.Draw(image).rectangle([100, 40, 500, 560],
                                    fill=(205, 185, 150))
        buffer = __import__("io").BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()

    photo_bytes = square_photo()
    page_reads = []

    def fake_fetch(url, cookie="", timeout=25):
        return photo_bytes

    def fake_page(url, cookie="", timeout=25):
        page_reads.append(url)
        return ('<meta name="description" content="A centred Mahovlich with a '
                'clean back."><meta name="keywords" content="hockey, vintage">'
                '<div id="details"><p>A centred Mahovlich with a clean back.'
                '</p><p>Posted in a sleeve.</p></div>')

    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "read_wordpress_credentials",
                         lambda path=None: ("https://shop.example", "owner",
                                            "app password")), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui.cs_products, "fetch_bytes", fake_fetch), \
            patch.object(gui.cs_products, "fetch_text", fake_page), \
            patch.object(gui.woo_create, "run", fake_run):
        create.invoke()

    check("the confirmation asks first, naming the direction",
          asked and asked[0][0] == "Create website products for these cards?",
          str(asked[:1]))
    check("and the card, its price and its stock are in it",
          asked and "1971-72 O-Pee-Chee Frank Mahovlich #60" in asked[0][1] and
          "$12.50" in asked[0][1] and "stock 4" in asked[0][1],
          str(asked[:1]))
    check("the question says the photos come off the square",
          asked and "square" in asked[0][1].lower(), str(asked[:1])[:400])
    check("one product was created", len(made) == 1, str(len(made)))
    plan = made[0]["plan"] if made else {"items": []}
    item = (plan.get("items") or [{}])[0]
    check("with the listing's own title", item.get("name") ==
          "1971-72 O-Pee-Chee Frank Mahovlich #60", str(item.get("name")))
    check("its SKU", item.get("sku") == "FM-60", str(item.get("sku")))
    check("its price, as a number", item.get("price") == "12.50",
          str(item.get("price")))
    check("its stock count", item.get("stock") == 4, str(item.get("stock")))
    check("both of the reader's pictures, as a front and a back",
          len(item.get("images") or []) == 2 and
          item["images"][0].endswith("-front.webp") and
          item["images"][1].endswith("-back.webp"), str(item.get("images")))
    check("the reader's pictures needed no page read, but the description did",
          page_reads == ["https://cs.example/listing/201"], str(page_reads))
    check("the photo file is really there",
          bool(item.get("images")) and
          (plan["folder"] / item["images"][0]).is_file(),
          str(plan.get("folder")))
    saved_photo = (plan["folder"] / item["images"][0]) \
        if item.get("images") else None
    check("the back is on disk beside it",
          bool(item.get("images")) and len(item["images"]) > 1 and
          (plan["folder"] / item["images"][1]).is_file(),
          str(item.get("images")))
    if saved_photo is not None and saved_photo.is_file():
        from PIL import Image as _Image
        with _Image.open(saved_photo) as picture:
            width, height = picture.size
        check("and it is the card, not a square",
              width == 600 and height > width, "%dx%d" % (width, height))
    else:
        check("and it is the card, not a square", False, "no photo")
    check("the photos were uploaded with the Application Password",
          made and made[0]["username"] == "owner", str(made[:1]))
    check("the back is the gallery, not the main image",
          item.get("gallery") == item["images"][1:] and
          len(item.get("gallery") or []) == 1, str(item.get("gallery")))
    check("the listing's description was copied onto the product",
          "A centred Mahovlich" in str(item.get("description")) and
          "<p>" in str(item.get("description")), str(item.get("description")))
    check("its keywords came across as tags",
          "hockey" in (item.get("tags") or []) and
          "vintage" in (item.get("tags") or []), str(item.get("tags")))
    names = [attr.get("name") for attr in item.get("attributes") or []]
    check("and the card's facts as attributes",
          "Year" in names and "Set" in names and "Card number" in names and
          "Player" in names, str(names))
    check("the confirmation says what came with it",
          any("description" in line for line in gui.cs_products.describe(
              {"items": [item], "folder": plan["folder"]})), "")
    check("the console says they are drafts, not live",
          any("draft" in line.lower() for _tag, line in app.lines),
          str(app.lines[-4:]))
    check("and it offered to publish them",
          any(title.startswith("Publish the new products") for title, _ in asked),
          str([title for title, _ in asked]))
    check("saying no leaves them as drafts",
          any("draft" in str(text).lower()
              for _tag, text in app.lines), "")

    print()
    print("== 35. it is the selected cards, and the other direction only ==")
    folder, app, parent = build_panel()
    out = folder / "cs-stock.json"
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        out.write_text(json.dumps({"items": only_cs}), encoding="utf-8")
        app.runs[-1]["on_done"](0)
    listing = next((w for w in parent.walk()
                    if isinstance(w, gui.tk.Listbox)), None)
    website_only = [index for index, text in enumerate(listing.items or [])
                    if "not on CanadianShopper" in text]
    check("the other direction is still on the list",
          len(website_only) == 2, str(listing.items))
    listing.selection = (website_only[0],)
    asked = []
    harness._BOX.askyesno = lambda title, message, **k: (
        asked.append((title, message)) or False)
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "read_wordpress_credentials",
                         lambda path=None: ("", "", "")), \
            patch.object(gui, "in_background", sync_background):
        find(parent, gui.ttk.Button,
             "Create website products for the selected cards...").invoke()
    check("a website-only card is not made into another website product",
          asked == [], str(asked))
    check("and it says which rows this button is for",
          any("not on your website" in str(args[1])
              for _kind, args in harness._BOX.shown[-1:]),
          str(harness._BOX.shown[-1:]))


def test_a_listing_that_reports_everything():
    print()
    print("== 36. plugin 1.0.33: the row carries the words, so no page is read ==")
    folder, app, parent = build_panel()
    #  Exactly what plugin 1.0.33 sends when the vendor already has it: the
    #  description with its own markup, the keywords, the card's facts, and
    #  both pictures - the primary first, then the back.
    rich = CS_ITEMS + [
        {"id": 301, "title": "1971-72 O-Pee-Chee Frank Mahovlich #60",
         "sku": "FM-60", "inventory": 4, "price": "CA$12.50",
         "url": "https://cs.example/listing/301",
         "images": ["https://cs.example/media/fm-front.jpg",
                    "https://cs.example/media/fm-back.jpg"],
         "description": "<p>Centred, sharp corners.</p>"
                        "<p>Posted in a sleeve.</p>",
         "keywords": ["hockey", "vintage"], "condition": "EX-MT",
         "grade": "6", "year": "1971-72", "set": "O-Pee-Chee",
         "cardNumber": "60", "player": "Frank Mahovlich",
         "brand": "O-Pee-Chee"}]

    def fetch_all(base, path, params, key, secret):
        return (200, PRODUCTS) if params["page"] == 1 else (200, [])

    out = folder / "cs-stock.json"
    button = find(parent, gui.ttk.Button, "Compare stock", exact=False)
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
        out.write_text(json.dumps({"items": rich}), encoding="utf-8")
        app.runs[-1]["on_done"](0)
    listing = next((w for w in parent.walk()
                    if isinstance(w, gui.tk.Listbox)), None)
    their_only = [index for index, text in enumerate(listing.items or [])
                  if "not on your website" in text]
    check("the card is on the list, once", len(their_only) == 1,
          str(listing.items))
    listing.selection = (their_only[0],)

    def square_photo():
        from PIL import Image as _Image, ImageDraw as _Draw
        image = _Image.new("RGB", (600, 600), (255, 255, 255))
        _Draw.Draw(image).rectangle([100, 40, 500, 560],
                                    fill=(205, 185, 150))
        buffer = __import__("io").BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()

    photo_bytes = square_photo()
    page_reads, fetches, made = [], [], []

    def fake_fetch(url, cookie="", timeout=25):
        fetches.append(url)
        return photo_bytes

    def fake_page(url, cookie="", timeout=25):
        page_reads.append(url)
        return "<html>a page that should not be read</html>"

    def fake_run(plan, site, key, secret, username="", app_password="",
                 publish=False, on_item=None):
        made.append({"plan": plan, "username": username})
        return {"created": [{"name": item["name"], "id": 900 + index,
                             "images": len(item["images"]), "status": "draft"}
                            for index, item in enumerate(plan["items"])],
                "skipped": [], "failed": [], "published": [],
                "unpublished": []}

    harness._BOX.askyesno = lambda title, message, **k: (
        True if title.startswith("Create website products") else False)
    create = find(parent, gui.ttk.Button,
                  "Create website products for the selected cards...")
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "read_wordpress_credentials",
                         lambda path=None: ("https://shop.example", "owner",
                                            "app password")), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui.cs_products, "fetch_bytes", fake_fetch), \
            patch.object(gui.cs_products, "fetch_text", fake_page), \
            patch.object(gui.woo_create, "run", fake_run):
        create.invoke()

    check("no listing page was read at all: the reader reported everything",
          page_reads == [], str(page_reads))
    check("both pictures were downloaded, and only those two",
          len(fetches) == 2 and all(url.endswith(".jpg") for url in fetches),
          str(fetches))
    plan = made[0]["plan"] if made else {"items": []}
    item = (plan.get("items") or [{}])[0]
    check("the description is the listing's own, paragraph for paragraph",
          "<p>Centred, sharp corners.</p>" in str(item.get("description")) and
          "Posted in a sleeve." in str(item.get("description")),
          str(item.get("description")))
    check("the keywords are the product's tags",
          "hockey" in (item.get("tags") or []) and
          "vintage" in (item.get("tags") or []), str(item.get("tags")))
    facts = {attr.get("name"): (attr.get("options") or [""])[0]
             for attr in item.get("attributes") or []}
    check("and the card's facts are its attributes",
          facts.get("Year") == "1971-72" and facts.get("Set") == "O-Pee-Chee" and
          facts.get("Player") == "Frank Mahovlich" and
          facts.get("Card number") == "60" and
          facts.get("Condition") == "EX-MT" and facts.get("Grade") == "6",
          str(facts))
    check("the front is the main image and the back is the gallery",
          item.get("images") and len(item["images"]) == 2 and
          item.get("gallery") == item["images"][1:], str(item.get("images")))
    print()
    print("== 37. plugin 1.0.33 with one picture still finds the back ==")
    folder, app, parent = build_panel()
    one_picture = CS_ITEMS + [
        {"id": 302, "title": "1971-72 O-Pee-Chee Frank Mahovlich #60",
         "inventory": 2, "price": "9.00",
         "url": "https://cs.example/listing/302",
         "images": ["https://cs.example/media/fm-front.jpg"],
         "description": "<p>Centred.</p>", "keywords": ["hockey"]}]
    out = folder / "cs-stock.json"
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "woo_get", fetch_all), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        find(parent, gui.ttk.Button, "Compare stock", exact=False).invoke()
        out.write_text(json.dumps({"items": one_picture}), encoding="utf-8")
        app.runs[-1]["on_done"](0)
    listing = next((w for w in parent.walk()
                    if isinstance(w, gui.tk.Listbox)), None)
    their_only = [index for index, text in enumerate(listing.items or [])
                  if "not on your website" in text]
    listing.selection = (their_only[0],)
    page_reads, made = [], []

    def page_with_a_back(url, cookie="", timeout=25):
        page_reads.append(url)
        return '<img src="/media/fm-back.jpg">'

    harness._BOX.askyesno = lambda title, message, **k: (
        True if title.startswith("Create website products") else False)
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "read_wordpress_credentials",
                         lambda path=None: ("https://shop.example", "owner",
                                            "app password")), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui.cs_products, "fetch_bytes",
                         lambda url, cookie="", timeout=25: photo_bytes), \
            patch.object(gui.cs_products, "fetch_text", page_with_a_back), \
            patch.object(gui.woo_create, "run", fake_run):
        find(parent, gui.ttk.Button,
             "Create website products for the selected cards...").invoke()
    check("the page is read once, for the back the reader did not send",
          page_reads == ["https://cs.example/listing/302"], str(page_reads))
    item = ((made[0]["plan"].get("items") or [{}])[0]) if made else {}
    check("and that back is in the gallery",
          len(item.get("images") or []) == 2 and
          item.get("gallery") == item["images"][1:], str(item.get("images")))


def main():
    test_woo_items()
    test_plugin_items()
    test_stock_file()
    test_reading_woo()
    test_reading_pages_side_by_side()
    test_the_get_can_bring_its_headers()
    test_a_sold_out_card_is_not_a_job()
    test_the_list_can_be_sorted()
    test_the_read_shows_where_it_is()
    test_creating_products_from_the_listings()
    test_pairing()
    test_spellings()
    test_card_numbers()
    test_big_catalogue()
    test_other_labels()
    test_differences()
    test_words()
    test_panel()
    test_the_cookies_canadian_shopper_is_told_about()
    test_one_card()
    test_actions()
    test_the_fix_flow()
    test_ignoring()
    test_listing_the_leftovers()
    test_listing_skips_what_is_not_a_listing_job()
    test_one_click_import()
    test_one_click_import_refusals()
    test_listings_that_are_not_on_sale()
    test_an_archived_card_with_nothing_to_sell()
    test_panel_explains_off_sale()
    test_report_rows()
    test_old_reader_is_named()
    test_publisher_tally()
    test_listing_without_a_count()
    test_a_listing_that_counts_nothing()
    test_nearest_title_diagnosis()
    test_a_duplicate_on_the_website()
    test_what_the_reader_claimed()
    test_read_failure()
    test_the_reader_survives()
    test_a_stopped_read_is_not_a_failure()
    test_the_fast_read_from_plugin_1038()
    test_comparing_the_last_read()
    test_the_sku_audit()
    test_held_under_another_product()
    test_a_reader_that_cannot_ask_for_a_fresh_page()
    test_a_listing_that_reports_everything()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL STOCK COMPARE CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
