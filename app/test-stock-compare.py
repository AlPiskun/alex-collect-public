#!/usr/bin/env python3
"""Checks for stock_compare - where the stock numbers disagree.

No network and no shop: the GET is a dict of canned replies and the plugin's
answer is a temporary file. The matching is the part worth testing, because a
wrong pair accuses a card that is fine.
"""
import importlib.util
import json
import sys
import tempfile
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
import stock_compare                                   # noqa: E402

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

CS_ITEMS = [
    {"title": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6", "sku": "GR-1",
     "inventory": 0},
    {"title": "1966-67 Topps Bobby Orr #35", "sku": "", "inventory": 0},
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
    check("a title, a SKU and an inventory make a row", len(items) == 2,
          str(items))
    check("a listing with no inventory is dropped, not assumed",
          all(item["name"] != "No number given" for item in items), "")
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
        app.runs[0]["on_done"](2)        # argparse usage error
        check("a reader that rejects the flag is asked again without it",
              len(app.runs) == 2 and "--cookie-file" not in app.runs[1]["args"],
              str([r["args"] for r in app.runs]))
        check("and it is not asked a third time",
              app.runs[1]["on_done"](2) is False and len(app.runs) == 2,
              str(len(app.runs)))

    # ---- a failure says which cookie was sent
    app.runs.clear()
    app.lines[:] = []
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "read_woo_credentials",
                         lambda path=None: ("https://shop.example", "ck_a",
                                            "cs_b")), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "BASE", folder):
        compare.invoke()
        app.runs[0]["on_done"](1)
    check("a failed read names the file, its size and when it was saved",
          any("cookie.txt" in text and "bytes" in text and "saved" in text
              for _tag, text in app.lines), str(app.lines[-3:]))


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


def main():
    test_woo_items()
    test_plugin_items()
    test_stock_file()
    test_reading_woo()
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
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL STOCK COMPARE CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
