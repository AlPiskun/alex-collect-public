#!/usr/bin/env python3
"""Checks for the CanadianShopper listing panel - finding one, changing it.

No network, no vendor account: the plugin's stock list is a JSON file and the
write is a recorded tool run. What is worth testing is everything that decides
*what* gets written - the fuzzy search, the change plan that carries only the
fields that changed, and the reading of the plugin's answer - because a
listing edit that goes wrong is a title or a price on a live shop.
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
import cs_edit                                        # noqa: E402
import stock_compare                                  # noqa: E402

LISTINGS = [
    {"id": 101, "title": "1973-74 O-Pee-Chee Walt Tkaczuk #25 EX-MT",
     "sku": "OPC73-25", "inventory": 3, "status": "active",
     "price": "CA$8.50", "url": "https://cs.example/l/101"},
    {"id": 102, "title": "1973-74 O-Pee-Chee Joe Watson #91 EX-MT",
     "sku": "OPC73-91", "inventory": 0, "status": "Archived",
     "price": "5.00", "url": "https://cs.example/l/102"},
    {"id": 103, "title": "1989 O-Pee-Chee Wayne Gretzky #1",
     "sku": "OPC89-1", "inventory": 1, "status": "Draft", "price": "12"},
    {"id": 104, "title": "1971-72 O-Pee-Chee Eddie Shack #60",
     "sku": "OPC71-60", "inventory": 2, "status": "active"},
    {"id": 105, "title": "1971-72 O-Pee-Chee Jean Beliveau #20",
     "sku": "OPC71-20", "inventory": None, "status": "active"},
]


def items():
    """The five listings, in the shape the plugin's reader produces."""
    return stock_compare.plugin_items({"items": [dict(row) for row in LISTINGS]})


# ---------------------------------------------------------------- the search
def test_finding_a_listing():
    print()
    print("== 1. a card's name finds its listing, however it is worded ==")
    rows = items()
    found = cs_edit.search(rows, "tkaczuk")
    check("a remembered surname finds the card",
          [row["name"] for row in found] ==
          ["1973-74 O-Pee-Chee Walt Tkaczuk #25 EX-MT"],
          str([row["name"] for row in found]))
    check("a card number finds it too",
          [row["name"] for row in cs_edit.search(rows, "watson 91")] ==
          ["1973-74 O-Pee-Chee Joe Watson #91 EX-MT"], "")
    check("two cards from one set are told apart by their names",
          len(cs_edit.search(rows, "gretzky")) == 1 and
          len(cs_edit.search(rows, "shack")) == 1, "")
    check("a SKU typed exactly is a hit on its own",
          [row["id"] for row in cs_edit.search(rows, "OPC73-91")] == [102], "")
    check("so is a listing id",
          [row["id"] for row in cs_edit.search(rows, "103")] == [103], "")
    check("a miss is an empty list, not everything",
          cs_edit.search(rows, "zzzz not a card") == [], "")
    check("an empty box is every listing, in name order",
          [row["name"][:4] for row in cs_edit.search(rows, "")] ==
          sorted(row["name"][:4] for row in rows), "")

    #  The state filter is how the archived listings are worked through.
    archived = cs_edit.search(rows, "", "archived")
    check("the archived filter shows only what was put away",
          [row["id"] for row in archived] == [102], str(archived))
    check("the on-sale filter shows only what can be bought",
          sorted(row["id"] for row in cs_edit.search(rows, "", "active")) ==
          [101, 104, 105], "")
    check("the draft filter shows what is one publish away",
          [row["id"] for row in cs_edit.search(rows, "", "draft")] == [103], "")
    check("anything not on sale is the off-sale filter",
          sorted(row["id"] for row in cs_edit.search(rows, "", "off-sale")) ==
          [102, 103], "")
    check("a search and a filter work together",
          [row["id"] for row in cs_edit.search(rows, "gretzky", "active")] ==
          [], "")
    check("any state is every state",
          len(cs_edit.search(rows, "", "any")) == len(rows), "")
    check("the chooser's words and keys agree both ways",
          all(cs_edit.state_key(cs_edit.state_label(key)) == key
              for key, _label in cs_edit.STATES), str(cs_edit.state_labels()))
    check("a state nobody knows asks for everything",
          cs_edit.state_key("sort by magic") == "any", "")
    check("the list is capped so a catalogue cannot become a spreadsheet",
          len(cs_edit.search(rows, "", limit=2)) == 2, "")


def test_what_a_row_says():
    print()
    print("== 2. a row says the card, its state, its stock and its price ==")
    rows = items()
    live = cs_edit.label(rows[0])
    check("a live listing reads as on sale",
          "on sale" in live and "3 in stock" in live and "CA$8.50" in live and
          "OPC73-25" in live, live)
    check("an archived one says so in the vendor's word",
          "archived" in cs_edit.label(rows[1]).lower(), cs_edit.label(rows[1]))
    check("a draft is named as one",
          "a Draft" in cs_edit.label(rows[2]), cs_edit.label(rows[2]))
    check("a listing with no count says nothing rather than zero",
          "in stock" not in cs_edit.label(rows[4]), cs_edit.label(rows[4]))
    check("no price is printed when the reader reports none",
          "CA$" not in cs_edit.label(rows[3]), cs_edit.label(rows[3]))
    check("a price is read as a number whatever the vendor prefixes",
          cs_edit.price_number(rows[0]) == 8.5 and
          abs(cs_edit.price_number({"price": "1,250.00"}) - 1250.0) < 0.001 and
          cs_edit.price_number({"price": ""}) is None, "")


def test_what_the_edit_form_is_filled_with():
    print()
    print("== 2b. the edit form opens on the listing as it stands ==")
    rows = items()
    live = cs_edit.edit_values(rows[0])
    check("the form is filled with the price, the count and the state",
          live == {"title": "1973-74 O-Pee-Chee Walt Tkaczuk #25 EX-MT",
                   "price": "8.50", "count": "3", "state": "On sale"},
          str(live))
    check("an archived listing opens on Archived, not on On sale",
          cs_edit.edit_values(rows[1])["state"] == "Archived",
          str(cs_edit.edit_values(rows[1])))
    draft = rows[2]
    check("a draft is offered in its own words, and both real states",
          cs_edit.edit_state_words(draft) ==
          ["Draft (as it is)", "On sale", "Archived"],
          str(cs_edit.edit_state_words(draft)))
    check("choosing the state it is already in changes nothing",
          cs_edit.edit_status(draft, "Draft (as it is)") is None and
          cs_edit.edit_status(rows[0], "On sale") is None, "")
    check("and choosing the other one does",
          cs_edit.edit_status(draft, "On sale") == "active" and
          cs_edit.edit_status(rows[0], "Archived") == "archived" and
          cs_edit.edit_status(rows[1], "On sale") == "active", "")
    check("a listing with no price or count opens with those boxes empty",
          cs_edit.edit_values(rows[4])["price"] == "" and
          cs_edit.edit_values(rows[4])["count"] == "",
          str(cs_edit.edit_values(rows[4])))


def test_rows_are_numbered():
    print()
    print("== 2c. the rows are numbered, from one, in the order shown ==")
    rows = items()
    first = cs_edit.label(rows[0], number=1, width=1)
    check("a numbered row starts with its place in the list",
          first.startswith("1. ") and "Tkaczuk" in first, first)
    check("the numbers line up when the list runs to two digits",
          cs_edit.label(rows[0], number=2, width=2).startswith(" 2. ") and
          cs_edit.label(rows[0], number=12, width=2).startswith("12. "),
          cs_edit.label(rows[0], number=2, width=2))
    check("an unnumbered row is the row it always was",
          cs_edit.label(rows[0]) == cs_edit.label(rows[0], number=None), "")


# ---------------------------------------------------------------- the change
def test_only_what_changed_is_sent():
    print()
    print("== 3. a change carries the fields that changed, and nothing else ==")
    rows = items()
    entry = cs_edit.plan(rows[1], status="active")
    check("putting an archived listing back on sale sends its state",
          entry["status"] == "active" and "title" in entry and
          entry["title"] == rows[1]["name"], str(entry))
    check("and not its price, which was not asked about",
          "price" not in entry, str(entry))
    check("nor its stock", "inventory" not in entry, str(entry))
    entry = cs_edit.plan(rows[0], title="1973-74 O-Pee-Chee Walt Tkaczuk #25 "
                                       "EX-MT New York Rangers")
    check("a rename sends the new title",
          entry["title"].endswith("New York Rangers") and entry["id"] == 101,
          str(entry))
    check("and nothing else but how the listing is found",
          set(entry) == {"id", "sku", "title", "card", "url"}, str(entry))
    check("the address the reader reported travels with the plan",
          entry["url"] == "https://cs.example/l/101", str(entry))
    entry = cs_edit.plan(rows[0], price=9.5, inventory=2)
    check("a reprice and a recount are two fields",
          entry["price"] == "9.50" and entry["inventory"] == 2, str(entry))
    check("an unchanged field is not sent at all",
          cs_edit.plan(rows[0], title=rows[0]["name"], price=8.5,
                       inventory=3) is None, "")
    check("nothing asked is nothing sent", cs_edit.plan(rows[0]) is None, "")
    check("a count of zero is a real change, not an empty one",
          cs_edit.plan(rows[0], inventory=0)["inventory"] == 0, "")
    check("a title the plugin reports with odd spacing is not a change",
          cs_edit.plan({"name": "A  card", "sku": "", "qty": 1,
                        "status": "active"},
                       title=" A card ") is None, "")
    check("the state the plan compares against is the listing's own",
          cs_edit.current(rows[1])["status"] == "archived" and
          cs_edit.current(rows[2])["status"] == "off", str(cs_edit.current(rows[2])))
    check("a listing with no id can still be planned by SKU and title",
          cs_edit.plan({"name": "No id card", "sku": "NI-1", "qty": 1,
                        "status": "active"}, inventory=4)["sku"] == "NI-1", "")

    # ---- every id the reader reports reaches the writer
    #
    #  A catalogue's listing and the product its API patches are not always
    #  the same key, and a reader that reports both must not have one dropped
    #  on the way: the writer is left addressing something the site does not
    #  know, which is a 404 and no change at all.
    page_id = "14effcaceb8a4b66b6f14e7aded86e2d"
    reader_row = {"id": page_id, "product_id": 4321,
                  "name": "1970-71 O-Pee-Chee Larry Hillman #81 (Mint)",
                  "sku": "OPC70-81", "inventory": 1, "status": "active",
                  "url": "https://cs.example/l/81"}
    rows_with_ids = stock_compare.plugin_items({"items": [reader_row]})
    check("a product id reported beside the listing id is kept",
          rows_with_ids[0].get("ids") == {"product_id": 4321},
          str(rows_with_ids[0]))
    entry = cs_edit.plan(rows_with_ids[0], inventory=2)
    check("and it travels in the plan, so the writer can address the product",
          entry.get("product_id") == 4321 and entry["id"] == page_id,
          str(entry))
    check("a key that names a title is not an identifier however it looks",
          stock_compare.plugin_items({"items": [
              {"id": 5, "name": "A card", "product_name": "A card",
               "productId": "not-an-id-either"}]})[0].get("ids") ==
          {"productId": "not-an-id-either"},
          str(stock_compare.plugin_items({"items": [
              {"id": 5, "name": "A card", "product_name": "A card"}]})))


def test_the_confirmation_says_what_will_change():
    print()
    print("== 4. the confirmation names every field, old and new ==")
    rows = items()
    lines = cs_edit.describe(cs_edit.plan(rows[1], status="active"), rows[1])
    check("a state change reads both ways round",
          len(lines) == 1 and "Archived" in lines[0] and
          "->" in lines[0] and "on sale" in lines[0], str(lines))
    lines = cs_edit.describe(cs_edit.plan(rows[0], inventory=5, price=11),
                             rows[0])
    check("a stock change names both counts",
          any("Stock:  3 in stock  ->  5" == line for line in lines), str(lines))
    check("a price change names both prices",
          any("CA$8.50" in line and "11.00" in line for line in lines),
          str(lines))
    entry = cs_edit.plan(rows[0], title="A better title entirely")
    lines = cs_edit.describe(entry, rows[0])
    check("a rename shows the old title and the new one",
          any(rows[0]["name"] in line for line in lines) and
          any("A better title entirely" in line for line in lines), str(lines))
    check("the summary counts the listings, not the fields",
          cs_edit.summary([entry]) ==
          "1 listing would be changed on CanadianShopper." and
          "2 listings" in cs_edit.summary([entry, entry]), "")


def test_the_plugins_answer_is_read_conservatively():
    print()
    print("== 5. what the plugin did not confirm did not happen ==")
    folder = Path(tempfile.mkdtemp())
    rows = items()
    entry = cs_edit.plan(rows[1], status="active")
    check("a missing result file is no answer at all",
          cs_edit.read_result(folder / "nothing.json") == {}, "")
    (folder / "broken.json").write_text("{oops", encoding="utf-8")
    check("unreadable JSON is no answer either",
          cs_edit.read_result(folder / "broken.json") == {}, "")
    answer = {"updated": [{"id": 102}], "failed": []}
    report = cs_edit.report([entry], answer)
    check("the listing the plugin reports is changed",
          report["changed"] == [entry] and not report["failed"], str(report))
    #  A writer that resolves the page id to the product id answers with the
    #  product id. That is the listing that was written, and calling it
    #  unknown would report a change that happened as one that did not.
    pair = cs_edit.plan(stock_compare.plugin_items({"items": [
        {"id": "14effcaceb8a4b66b6f14e7aded86e2d", "product_id": 4321,
         "name": "1971-72 O-Pee-Chee Larry Hillman #81", "sku": "OPC71-81",
         "inventory": 1, "status": "active"}]})[0], inventory=2)
    report = cs_edit.report([pair], {"updated": [{"product_id": 4321}],
                                     "failed": []})
    check("an answer naming the product id confirms the listing",
          report["changed"] == [pair] and not report["unknown"], str(report))
    report = cs_edit.report([pair], {"updated": [{"product_id": 9999}],
                                     "failed": []})
    check("but another product's id is another listing",
          not report["changed"] and report["unknown"] == [pair], str(report))
    check("a failure message can say how the listing was named",
          cs_edit.identified_by(pair) ==
          "id 14effcaceb8a4b66b6f14e7aded86e2d, product id 4321, SKU OPC71-81",
          cs_edit.identified_by(pair))

    report = cs_edit.report([entry], {"updated": [], "failed": [
        {"id": 102, "why": "that listing is not editable"}]})
    check("a failure keeps the plugin's own sentence",
          report["failed"] and
          report["failed"][0]["why"] == "that listing is not editable",
          str(report))
    report = cs_edit.report([entry], {"updated": []})
    check("a listing the answer does not mention is unknown, never changed",
          report["unknown"] == [entry] and not report["changed"], str(report))
    check("the id decides when both sides have one, even over the title",
          cs_edit.report([entry], {"updated": [{"id": 999}]})["unknown"] ==
          [entry], "")
    updated = cs_edit.apply_to_item(rows[1], entry)
    check("the row becomes what was written",
          updated["name"] == rows[1]["name"] and updated["qty"] == 0 and
          updated["status"] == "active", str(updated))
    check("and the listing it came from is not one of the changes",
          rows[1]["status"] == "Archived", rows[1]["status"])
    check("a price the reader reports as a number is still read",
          cs_edit.price_number({"price": 8.5}) == 8.5, "")


# ------------------------------------------------------------------ the panel
def build_panel():
    """A panel built in a throwaway folder, with the app pointed at it.

    ``gui.BASE`` is left pointing at the folder for the rest of the test: the
    panel's own closures read it when a button is pressed, so patching it only
    while the panel is built would have the buttons write their plan into the
    real application folder.
    """
    folder = Path(tempfile.mkdtemp())
    harness.install_plugin("1.0.19", folder / "plugin")
    gui.BASE = folder
    app = harness.FakeApp(folder)
    parent = harness.FakeWidget()
    gui.build_csledit(parent, app)
    return folder, app, parent


def find(parent, kind, text, exact=True):
    for widget in parent.walk():
        if not isinstance(widget, kind):
            continue
        got = str(widget.cget("text"))
        if (got == text) if exact else (got.startswith(text)):
            return widget
    return None


def listing_box(parent):
    return next((w for w in parent.walk()
                 if isinstance(w, gui.tk.Listbox)), None)


def query_box(parent):
    return next((w for w in parent.walk() if isinstance(w, gui.ttk.Entry)),
                None)


def read_into(app, folder, parent, payload=None):
    """Press the read button and hand it the plugin's stock list."""
    find(parent, gui.ttk.Button, "Read CanadianShopper's listings").invoke()
    run = app.runs[-1]
    out = Path(run["args"][1])
    out.write_text(json.dumps({"items": payload or LISTINGS}), encoding="utf-8")
    run["on_done"](0)
    return out


def test_the_12030_reproduction():
    """The row and the answer plugin 1.0.30 sends, end to end.

    This is the exact pair from the bug: a catalogue id that is not a product
    id, a product id reported beside it, and a writer that answers with the
    product id it patched. The listing must come back *changed* - not UNKNOWN,
    which is what the panel said while the writer was 404ing.
    """
    print()
    print("== 5b. the row and the answer plugin 1.0.30 sends ==")
    row = {"id": "14effcaceb8a4b66b6f14e7aded86e2d", "inventory": 1,
           "price": "8.50", "product_id": 4321, "sku": "OPC70-81",
           "status": "active",
           "title": "1970-71 O-Pee-Chee Larry Hillman #81 (Mint)",
           "url": "https://canadianshopper.ca/listing/81"}
    item = stock_compare.plugin_items({"items": [row]})[0]
    check("the catalogue id is kept, and so is the product id beside it",
          item["id"] == "14effcaceb8a4b66b6f14e7aded86e2d" and
          item["ids"] == {"product_id": 4321}, str(item))
    entry = cs_edit.plan(item, inventory=2)
    check("the plan carries both ids, so the writer can address the product",
          entry["id"] == "14effcaceb8a4b66b6f14e7aded86e2d" and
          entry["product_id"] == 4321 and entry["inventory"] == 2,
          str(entry))
    report = cs_edit.report([entry], {"updated": [{"id": 4321}],
                                      "failed": []})
    check("an answer naming the product id is one changed listing",
          len(report["changed"]) == 1 and not report["unknown"] and
          not report["failed"], str(report))
    report = cs_edit.report([entry], {"updated": [{"product_id": 4321}],
                                      "failed": []})
    check("and so is one that names it by key",
          len(report["changed"]) == 1 and not report["unknown"], str(report))
    check("the row says what the plugin said, price and all",
          cs_edit.label(item, number=1, width=1).endswith("8.50  -  OPC70-81") and
          "Larry Hillman" in cs_edit.label(item), cs_edit.label(item))
    check("the form opens on the listing as it stands",
          cs_edit.edit_values(item) == {
              "title": "1970-71 O-Pee-Chee Larry Hillman #81 (Mint)",
              "price": "8.50", "count": "1", "state": "On sale"},
          str(cs_edit.edit_values(item)))

    #  A plugin that cannot resolve a product must say so rather than patch
    #  something else, and the core reports its sentence as a failure - never
    #  as a change.
    report = cs_edit.report([entry], {"updated": [], "failed": [{
        "id": 4321, "why": "this listing has no product id; nothing was "
                           "changed"}]})
    check("a listing the plugin refuses is a failure, in its own words",
          not report["changed"] and report["failed"] and
          "no product id" in report["failed"][0]["why"], str(report))
    check("and the console can say how the plan named it",
          cs_edit.identified_by(entry) ==
          "id 14effcaceb8a4b66b6f14e7aded86e2d, product id 4321, SKU OPC70-81",
          cs_edit.identified_by(entry))


def test_a_list_read_before_product_ids():
    """The plugin's refusal to guess a product id, and what the panel does.

    A row from a list read before the plugin reported product ids has none to
    send. Shouting at the person to edit it by hand would be wrong: the panel
    re-reads, re-plans the same change from the fresh row, and asks again.
    """
    print()
    print("== 5c. a list read before the plugin knew product ids ==")
    entry = cs_edit.plan(items()[1], status="active")
    refusal = {"updated": [], "failed": [{
        "id": 102, "why": "The matched listing has no explicit "
                          "product_id/productId; refusing to guess a product "
                          "id from its listing id, slug, or title."}]}
    report = cs_edit.report([entry], refusal)
    check("the plugin's refusal is read as a failure, not a change",
          not report["changed"] and len(report["failed"]) == 1,
          str(report))
    check("and it is understood as a missing product id",
          cs_edit.wants_product_id(report) and
          not cs_edit.wants_product_id(
              {"failed": [{"why": "that listing is protected"}]}), "")
    check("a row that carries a product id is not the case",
          cs_edit.product_id({"product_id": 4321}) == "4321" and
          cs_edit.product_id({"ids": {"productId": 7}}) == "7" and
          cs_edit.product_id({"id": "14effcac"}) == "", "")

    #  The same change, planned again from a row that has what it needs.
    fresh = dict(items()[1])
    fresh["ids"] = {"product_id": 4321}
    fresh["name"] = "1973-74 O-Pee-Chee Joe Watson #91 EX-MT"
    again = cs_edit.replan(entry, fresh)
    check("the change is re-planned for the fresh row, product id and all",
          again["status"] == "active" and again["id"] == 102 and
          again["product_id"] == 4321 and
          cs_edit.product_id(again) == "4321", str(again))
    same = dict(items()[0])
    same["qty"] = 9
    check("a re-planned change the fresh row already has is not sent",
          cs_edit.replan(cs_edit.plan(items()[0], inventory=9), same) is None,
          str(cs_edit.replan(cs_edit.plan(items()[0], inventory=9), same)))

    # ---- the panel offers the re-read, then makes the same change
    folder, app, parent = build_panel()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app, folder, parent)
    find(parent, gui.ttk.Button, "Search").invoke()
    select(parent, "Watson")
    answers = []
    harness._BOX.askyesno = lambda title, *a, **k: (answers.append(title), True)[1]

    def tools(action):
        #  Both actions stay resolvable for the whole sequence: the retry is a
        #  read followed by another write, and a test that only patched the
        #  write would be testing a read that never starts.
        return ("/plugins/cs/edit.py" if action == gui.CS_LISTING_UPDATE_ACTION
                else "/plugins/cs/stock.py")

    with patch.object(gui, "TOOL_ACTION", tools):
        find(parent, gui.ttk.Button,
             "Put the selected listing on sale").invoke()
    run = app.runs[-1]
    Path(run["args"][3]).write_text(json.dumps(refusal), encoding="utf-8")
    reads_before = len(app.runs)
    with patch.object(gui, "TOOL_ACTION", tools):
        run["on_done"](1)
    check("the panel says the list is older than the plugin's product ids",
          any("read before the plugin reported product ids" in text
              for _tag, text in app.lines), str(app.lines[-3:]))
    check("and offers to read the listings again, once",
          answers.count("Read the listings again?") == 1, str(answers))
    check("which starts the read", len(app.runs) == reads_before + 1 and
          "--stock-out" in app.runs[-1]["args"], str(app.runs[-1:]))

    refreshed = [{"id": 102, "product_id": 4321,
                  "title": "1973-74 O-Pee-Chee Joe Watson #91 EX-MT",
                  "sku": "OPC73-91", "inventory": 0, "status": "Archived",
                  "price": "5.00"}]
    read_run = app.runs[-1]
    Path(read_run["args"][1]).write_text(json.dumps({"items": refreshed}),
                                        encoding="utf-8")
    writes_before = len(app.runs)
    with patch.object(gui, "TOOL_ACTION", tools):
        read_run["on_done"](0)
    check("the same change is made again from the fresh row",
          len(app.runs) == writes_before + 1 and
          "--set-file" in app.runs[-1]["args"], str(app.runs[-1:]))
    plan = json.loads((folder / "cs-listing-update.json").read_text(
        encoding="utf-8"))["items"][0]
    check("and it carries the product id this time",
          plan["product_id"] == 4321 and plan["status"] == "active" and
          plan["id"] == 102, str(plan))
    check("the change is named again before it is written",
          answers.count("Change this listing?") == 1, str(answers))


def test_the_list_says_which_plugin_read_it():
    print()
    print("== 5d. the list on screen says which plugin read it ==")
    folder = Path(tempfile.mkdtemp())
    harness.install_plugin("1.0.30", folder / "plugin")
    gui.BASE = folder
    (folder / "cs-stock.json").write_text(json.dumps({"items": LISTINGS}),
                                          encoding="utf-8")
    (folder / "cs-stock-meta.json").write_text(json.dumps(
        {"plugin": "1.0.29", "count": len(LISTINGS)}), encoding="utf-8")
    parent = harness.FakeWidget()
    gui.build_csledit(parent, harness.FakeApp(folder))
    notes = [str(w.cget("text")) for w in parent.walk()
             if isinstance(w, gui.ttk.Label)]
    check("a list read by an older plugin is described as one",
          any("read by plugin 1.0.29" in note and "1.0.30 is installed" in note
              for note in notes), str(notes[-3:]))
    check("and it still lists, so reading is not blocked by it",
          len(listing_box(parent).items) == len(LISTINGS),
          str(listing_box(parent).items))

    folder2 = Path(tempfile.mkdtemp())
    harness.install_plugin("1.0.30", folder2 / "plugin")
    gui.BASE = folder2
    (folder2 / "cs-stock.json").write_text(json.dumps({"items": LISTINGS}),
                                           encoding="utf-8")
    (folder2 / "cs-stock-meta.json").write_text(json.dumps(
        {"plugin": "1.0.30", "count": len(LISTINGS)}), encoding="utf-8")
    parent2 = harness.FakeWidget()
    gui.build_csledit(parent2, harness.FakeApp(folder2))
    notes2 = [str(w.cget("text")) for w in parent2.walk()
              if isinstance(w, gui.ttk.Label)]
    check("a list read by the installed plugin is not",
          not any("read by plugin" in note for note in notes2), str(notes2[-3:]))


def test_the_panel_reads_and_lists():
    print()
    print("== 6. the panel lists the catalogue and searches it ==")
    folder, app, parent = build_panel()
    check("it opens saying nothing has been read",
          find(parent, gui.ttk.Label, "Nothing read yet", exact=False)
          is not None,
          str([w.cget("text") for w in parent.walk()
               if isinstance(w, gui.ttk.Label)]))
    check("with nothing read the list is empty and out of the way",
          listing_box(parent) is not None and not listing_box(parent).items and
          not listing_box(parent).parent.packed, "")

    harness._BOX.shown.clear()
    with patch.object(gui, "TOOL_ACTION", lambda action: ""):
        find(parent, gui.ttk.Button, "Read CanadianShopper's listings").invoke()
    check("without the plugin's reader it says what is missing",
          harness._BOX.shown and "stock reader" in str(harness._BOX.shown[-1]),
          str(harness._BOX.shown))
    check("and starts nothing", not app.runs, str(app.runs))

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        out = read_into(app, folder, parent)
    run = app.runs[-1]
    check("it asks the plugin for the whole stock list",
          "--stock-out" in run["args"] and Path(run["args"][1]) == out, str(run))
    check("the plugin is the one that lists the catalogue",
          run["tool"] == "/plugins/cs/stock.py", run["tool"])
    check("every listing is on the list",
          len(listing_box(parent).items) == len(LISTINGS),
          str(listing_box(parent).items))
    check("the rows are numbered in the list",
          listing_box(parent).items[0].startswith("1. ") and
          listing_box(parent).items[1].startswith("2. "),
          str(listing_box(parent).items[:2]))
    check("and the summary says how many came back",
          find(parent, gui.ttk.Label, "%d listings read" % len(LISTINGS),
               exact=False) is not None,
          str([w.cget("text") for w in parent.walk()
               if isinstance(w, gui.ttk.Label)][-3:]))

    #  Typing a name, then pressing Search.
    entry = query_box(parent)
    entry._kw["textvariable"].set("tkaczuk")
    find(parent, gui.ttk.Button, "Search").invoke()
    check("a search narrows the list to the card",
          len(listing_box(parent).items) == 1 and
          "Tkaczuk" in listing_box(parent).items[0],
          str(listing_box(parent).items))
    check("and the summary counts what is shown",
          find(parent, gui.ttk.Label, "1 of %d listings shown" % len(LISTINGS),
               exact=False) is not None, "")

    #  The plugin's own file is the only place a price or an address comes
    #  from: a row that loses them in the reader would show neither, and the
    #  Open button would have nothing to open.
    kept = stock_compare.read_stock_file(folder / "cs-stock.json")
    tkaczuk = next(row for row in kept
                   if "Tkaczuk" in str(row.get("name") or row.get("title")))
    check("the reader keeps the price and the address the plugin sent",
          tkaczuk.get("price") == "CA$8.50" and
          tkaczuk.get("url") == "https://cs.example/l/101", str(tkaczuk))
    check("and the row shows the price as the vendor wrote it",
          "8.50" in listing_box(parent).items[0],
          str(listing_box(parent).items))
    entry._kw["textvariable"].set("zzzz nothing")
    find(parent, gui.ttk.Button, "Search").invoke()
    check("a search that matches nothing says so",
          find(parent, gui.ttk.Label, "No listing matches", exact=False)
          is not None, "")
    check("and the list is out of the way rather than empty",
          not listing_box(parent).parent.packed, "")

    #  The state chooser works on its own, which is how the archived listings
    #  are worked through.
    entry._kw["textvariable"].set("")
    chooser = next(w for w in parent.walk()
                   if isinstance(w, gui.ttk.Combobox))
    chooser._kw["textvariable"].set("Archived")
    chooser.event_generate("<<ComboboxSelected>>")
    check("the archived filter shows the archived listing alone",
          len(listing_box(parent).items) == 1 and
          "Watson" in listing_box(parent).items[0],
          str(listing_box(parent).items))
    check("and the filtered list counts from one again",
          listing_box(parent).items[0].startswith("1. "),
          str(listing_box(parent).items))
    chooser._kw["textvariable"].set("Any state")
    chooser.event_generate("<<ComboboxSelected>>")
    check("and any state brings the catalogue back",
          len(listing_box(parent).items) == len(LISTINGS), "")


def select(parent, word):
    """Select the one row whose card name contains ``word``."""
    box = listing_box(parent)
    for index, text in enumerate(box.items):
        if word in text:
            box.selection_set(index)
            return index
    raise AssertionError("no row for %r in %r" % (word, box.items))


def open_edit_form(parent, values=(None, None, None, None), agree=True):
    """Press Edit on the selected row, fill the form and press Save.

    ``values`` is (title, price, quantity, state); ``None`` leaves a field as
    the form opened it, which is how "did not touch it" is expressed.
    """
    seen = {"fields": [], "asked": []}

    def press(window):
        fields = [w for w in window.walk()
                  if w._kw.get("textvariable") is not None]
        seen["fields"] = [field._kw["textvariable"].get() for field in fields]
        for field, value in zip(fields, values):
            if value is not None:
                field._kw["textvariable"].set(value)
        buttons = {w.cget("text"): w for w in window.walk() if w.cget("text")}
        buttons["Save the change"].invoke()
        seen["still_open"] = not window.destroyed
        buttons["Cancel"].invoke()

    def answer(*args, **kwargs):
        seen["asked"].append(args)
        return agree

    harness.PICKER["press"] = press
    harness._BOX.askyesno = answer
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/edit.py"):
        find(parent, gui.ttk.Button, "Edit the selected listing",
             exact=False).invoke()
    return seen


def test_the_edit_form():
    print()
    print("== 7. one form changes the title, the price, the count and the state ==")
    folder, app, parent = build_panel()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app, folder, parent)
    find(parent, gui.ttk.Button, "Search").invoke()

    # ---- the form opens on the listing as it stands, and saves nothing
    select(parent, "Tkaczuk")
    harness._BOX.shown.clear()
    runs_before = len(app.runs)
    seen = open_edit_form(parent)
    check("the form holds the title, the price, the count and the state",
          len(seen["fields"]) == 4, str(seen["fields"]))
    check("and every one of them opens as the listing is now",
          seen["fields"][:3] == ["1973-74 O-Pee-Chee Walt Tkaczuk #25 EX-MT",
                                 "8.50", "3"] and
          seen["fields"][3] == "On sale", str(seen["fields"]))
    check("a form whose fields were not touched writes nothing",
          len(app.runs) == runs_before and
          any("Nothing changed" in str(payload)
              for _kind, payload in harness._BOX.shown),
          str(harness._BOX.shown) + str(len(app.runs)))

    # ---- price, quantity and state in one visit
    harness._BOX.shown.clear()
    runs_before = len(app.runs)
    seen = open_edit_form(parent, (None, "9.5", "2", "Archived"))
    check("a price, a count and a state are sent together",
          len(app.runs) == runs_before + 1, str(app.runs[-1:]))
    plan = json.loads((folder / "cs-listing-update.json").read_text(
        encoding="utf-8"))["items"][0]
    check("the plan carries the three fields that changed",
          plan.get("price") == "9.50" and plan.get("inventory") == 2 and
          plan.get("status") == "archived" and
          plan.get("title") == "1973-74 O-Pee-Chee Walt Tkaczuk #25 EX-MT",
          str(plan))
    check("the confirmation names every one of them",
          seen["asked"] and all(word in str(seen["asked"][-1])
                                for word in ("9.50", "2", "archived")),
          str(seen["asked"]))
    run = app.runs[-1]
    Path(run["args"][3]).write_text(json.dumps(
        {"updated": [{"id": 101}], "failed": []}), encoding="utf-8")
    run["on_done"](0)
    check("the row shows the new price, count and state",
          any("Tkaczuk" in text and "9.50" in text and "2 in stock" in text and
              "archived" in text.lower() for text in listing_box(parent).items),
          str(listing_box(parent).items))

    # ---- a title can be changed on its own
    select(parent, "Tkaczuk")
    runs_before = len(app.runs)
    open_edit_form(parent,
                   ("1973-74 O-Pee-Chee Walt Tkaczuk #25 EX-MT Rangers",
                    None, None, None))
    plan = json.loads((folder / "cs-listing-update.json").read_text(
        encoding="utf-8"))["items"][0]
    check("the title alone is sent when it is the only thing changed",
          plan.get("title", "").endswith("Rangers") and
          set(plan) == {"id", "sku", "title", "card", "url"} and
          len(app.runs) == runs_before + 1, str(plan))
    check("and a state the form was merely showing is not written back",
          "status" not in plan and "inventory" not in plan and
          "price" not in plan, str(plan))
    run = app.runs[-1]
    Path(run["args"][3]).write_text(json.dumps(
        {"updated": [{"id": 101}], "failed": []}), encoding="utf-8")
    run["on_done"](0)
    check("and the row is renamed",
          any("Rangers" in text for text in listing_box(parent).items),
          str(listing_box(parent).items))

    # ---- what the form refuses, it refuses without closing
    harness._BOX.shown.clear()
    runs_before = len(app.runs)
    seen = open_edit_form(parent, (None, "eight dollars", None, None))
    check("a price that is not a number is refused",
          seen["still_open"] and
          any("showwarning" == kind for kind, _payload in harness._BOX.shown),
          str(harness._BOX.shown))
    check("and nothing was written",
          len(app.runs) == runs_before, str(len(app.runs)))

    harness._BOX.shown.clear()
    seen = open_edit_form(parent, ("", None, None, None))
    check("a listing cannot be saved with no title",
          seen["still_open"] and
          any("title" in str(payload).lower()
              for _kind, payload in harness._BOX.shown),
          str(harness._BOX.shown))
    check("and that was not written either",
          len(app.runs) == runs_before, str(len(app.runs)))

    # ---- a declined confirmation writes nothing
    runs_before = len(app.runs)
    select(parent, "Shack")
    open_edit_form(parent, (None, "7.00", None, None), agree=False)
    check("an edit that is not confirmed is not written",
          len(app.runs) == runs_before, str(len(app.runs)))
    check("and the console says so",
          any("not confirmed" in text for _tag, text in app.lines),
          str(app.lines[-2:]))

    # ---- the two state buttons still do just the state
    select(parent, "Watson")
    runs_before = len(app.runs)
    harness._BOX.askyesno = lambda *a, **k: True
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/edit.py"):
        find(parent, gui.ttk.Button,
             "Put the selected listing on sale").invoke()
    plan = json.loads((folder / "cs-listing-update.json").read_text(
        encoding="utf-8"))["items"][0]
    check("the state button sends the state and nothing else",
          plan["id"] == 102 and plan["status"] == "active" and
          set(plan) == {"id", "sku", "title", "card", "url", "status"},
          str(plan))
    run = app.runs[-1]
    Path(run["args"][3]).write_text(json.dumps(
        {"updated": [{"id": 102}], "failed": []}), encoding="utf-8")
    run["on_done"](0)
    check("the row on the list now says it is on sale",
          any("Watson" in text and "on sale" in text
              for text in listing_box(parent).items),
          str(listing_box(parent).items))
    check("and the console says the website was not touched",
          any("your website was not touched" in text.lower()
              for _tag, text in app.lines), str(app.lines[-2:]))

    # ---- archiving from the state button
    select(parent, "Gretzky")
    runs_before = len(app.runs)
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/edit.py"):
        find(parent, gui.ttk.Button, "Archive the selected listing").invoke()
    plan = json.loads((folder / "cs-listing-update.json").read_text(
        encoding="utf-8"))["items"][0]
    check("archiving sends the archived state and nothing else",
          plan["status"] == "archived" and plan["id"] == 103 and
          len(app.runs) == runs_before + 1, str(plan))


def test_the_panel_refuses_what_it_cannot_do():
    print()
    print("== 8. what the panel cannot do, it says - and changes nothing ==")
    folder, app, parent = build_panel()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app, folder, parent)
    find(parent, gui.ttk.Button, "Search").invoke()
    listing_box(parent).selection_set(0)

    box = listing_box(parent)
    for index, text in enumerate(box.items):
        if "Watson" in text:          # archived: a state change is possible
            box.selection_set(index)
            break
    harness._BOX.shown.clear()
    runs_before = len(app.runs)
    with patch.object(gui, "TOOL_ACTION", lambda action: ""):
        find(parent, gui.ttk.Button,
             "Put the selected listing on sale").invoke()
    check("a plugin that cannot edit is named, with the version that can",
          harness._BOX.shown and "1.0.28" in str(harness._BOX.shown[-1]),
          str(harness._BOX.shown))
    check("and nothing was started", len(app.runs) == runs_before, "")

    #  A listing that is already in the state asked for is not written at all.
    box = listing_box(parent)
    for index, text in enumerate(box.items):
        if "Tkaczuk" in text:
            box.selection_set(index)
            break
    harness._BOX.shown.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/edit.py"):
        find(parent, gui.ttk.Button,
             "Put the selected listing on sale").invoke()
    check("a listing already on sale is not written again",
          any("already on sale" in str(payload)
              for _kind, payload in harness._BOX.shown),
          str(harness._BOX.shown))

    #  A result that does not mention the listing leaves it exactly as it was.
    box = listing_box(parent)
    for index, text in enumerate(box.items):
        if "Shack" in text:
            box.selection_set(index)
            break
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/edit.py"):
        find(parent, gui.ttk.Button, "Archive the selected listing").invoke()
    run = app.runs[-1]
    Path(run["args"][3]).write_text(json.dumps({"updated": []}),
                                    encoding="utf-8")
    run["on_done"](0)
    check("an unconfirmed change is not shown as done",
          any("did not confirm" in text or "did not report" in text
              for _tag, text in app.lines), str(app.lines[-2:]))
    check("and the row still says what it said",
          any("Shack" in text and "on sale" in text
              for text in listing_box(parent).items),
          str(listing_box(parent).items))

    #  A failure keeps the plugin's own words.
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/edit.py"):
        find(parent, gui.ttk.Button, "Archive the selected listing").invoke()
    run = app.runs[-1]
    Path(run["args"][3]).write_text(json.dumps(
        {"updated": [], "failed": [{"id": 104,
                                    "why": "that listing is protected"}]}),
        encoding="utf-8")
    run["on_done"](0)
    check("a failure is printed in the plugin's own words",
          any("that listing is protected" in text for _tag, text in app.lines),
          str(app.lines[-3:]))

    #  A 404 is a question about which listing was addressed, so the console
    #  says how the plan named it - the one fact the plugin (and the person
    #  reading the console) needs to fix an id the site does not know.
    select(parent, "Beliveau")
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/edit.py"):
        find(parent, gui.ttk.Button, "Archive the selected listing").invoke()
    run = app.runs[-1]
    Path(run["args"][3]).write_text(json.dumps(
        {"updated": [], "failed": [{
            "id": 105, "why": "CanadianShopper API returned HTTP 404 for "
                              "PATCH /api/products/abc/: Not Found."}]}),
        encoding="utf-8")
    run["on_done"](1)
    check("a 404 says how the plan named the listing",
          any("The plan named it:" in text and "105" in text
              for _tag, text in app.lines), str(app.lines[-4:]))
    check("and says the site was not changed by it",
          any("does not know a listing by that id" in text
              for _tag, text in app.lines), str(app.lines[-4:]))
    check("and the row is left exactly as it was",
          any("Beliveau" in text and "on sale" in text
              for text in listing_box(parent).items),
          str(listing_box(parent).items))

    #  Nothing selected is a question, not a guess. An empty list is the one
    #  state the test's stand-in can express it in.
    entry = query_box(parent)
    entry._kw["textvariable"].set("zzzz nothing")
    find(parent, gui.ttk.Button, "Search").invoke()
    harness._BOX.shown.clear()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/edit.py"):
        find(parent, gui.ttk.Button, "Archive the selected listing").invoke()
    check("with nothing selected it asks which listing",
          any("Which listing" in str(payload)
              for _kind, payload in harness._BOX.shown), str(harness._BOX.shown))


def test_opening_a_listing_and_the_last_read():
    print()
    print("== 9. the listing's own page, and the list from the last read ==")
    folder, app, parent = build_panel()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app, folder, parent)
    find(parent, gui.ttk.Button, "Search").invoke()

    box = listing_box(parent)
    for index, text in enumerate(box.items):
        if "Tkaczuk" in text:
            box.selection_set(index)
            break
    find(parent, gui.ttk.Button,
         "Open the selected listing on CanadianShopper").invoke()
    check("the listing's own page opens in the browser",
          app.opened == ["https://cs.example/l/101"], str(app.opened))

    #  A row the reader reported no address for still leads somewhere: the
    #  seller's own store, with the card and its listing id on the clipboard.
    for index, text in enumerate(box.items):
        if "Shack" in text:
            box.selection_set(index)
            break
    harness._BOX.shown.clear()
    app.opened[:] = []
    find(parent, gui.ttk.Button,
         "Open the selected listing on CanadianShopper").invoke()
    check("a listing with no address opens the store instead of a dead end",
          app.opened == ["https://cs.example/x"], str(app.opened))
    check("and puts the card and its listing id on the clipboard",
          "Eddie Shack" in app.clipboard and "104" in app.clipboard,
          app.clipboard)
    check("and says in the console what it did and why",
          any("was not in the list" in text for _tag, text in app.lines),
          str(app.lines[-2:]))

    #  A relative address is a real address once it is joined to the site.
    check("a short address from the plugin is joined to the site",
          cs_edit.link({"url": "/listing/9"}, "https://canadianshopper.ca") ==
          "https://canadianshopper.ca/listing/9",
          cs_edit.link({"url": "/listing/9"}, "https://canadianshopper.ca"))
    check("another plugin's word for the address is read too",
          cs_edit.link({"permalink": "https://cs.example/l/7"}) ==
          "https://cs.example/l/7" and
          cs_edit.link({"href": "//cs.example/l/8"}) ==
          "https://cs.example/l/8", "")
    check("and the same key in another spelling is the same key",
          cs_edit.link({"productUrl": "https://cs.example/l/2"}) ==
          "https://cs.example/l/2" and
          cs_edit.link({"PRODUCT_URL": "/listing/3"},
                       "https://canadianshopper.ca") ==
          "https://canadianshopper.ca/listing/3" and
          cs_edit.link({"Product URL": "https://cs.example/l/4"}) ==
          "https://cs.example/l/4",
          str([cs_edit.link({key: "https://cs.example/l/2"})
               for key in ("productUrl", "PRODUCT_URL", "Product URL")]))
    check("every address key the plugin may use is read",
          all(cs_edit.link({key: "https://cs.example/l/5"}) ==
              "https://cs.example/l/5" for key in
              ("url", "link", "permalink", "href", "product_url", "productUrl",
               "listing_url", "web_url", "view_url", "address", "page")), "")
    check("an address that is not the web is refused, not opened",
          cs_edit.link({"permalink": "javascript:alert(1)"}) == "" and
          cs_edit.link({"url": "mailto:shop@example.com"}) == "" and
          cs_edit.link({"href": "C:\\tmp\\x.html"}) == "",
          str([cs_edit.link({"permalink": "javascript:alert(1)"}),
               cs_edit.link({"url": "mailto:shop@example.com"})]))
    check("and a bad address does not hide a good one beside it",
          cs_edit.link({"href": "javascript:alert(1)",
                        "url": "https://cs.example/l/9"}) ==
          "https://cs.example/l/9", "")
    check("an empty address is no address",
          cs_edit.link({"url": "", "link": None}) == "", "")

    #  A panel opened again offers the list that is already on disk, so a
    #  search works before anything is read.
    (folder / "cs-stock.json").write_text(
        json.dumps({"items": LISTINGS}), encoding="utf-8")
    parent2 = harness.FakeWidget()
    gui.build_csledit(parent2, harness.FakeApp(folder))
    box2 = listing_box(parent2)
    check("the last read is used when the panel opens again",
          box2 is not None and len(box2.items) == len(LISTINGS),
          str(box2 and box2.items))
    check("and the panel says where the list came from",
          any("from the last read" in str(w.cget("text"))
              for w in parent2.walk() if isinstance(w, gui.ttk.Label)),
          str([w.cget("text") for w in parent2.walk()
               if isinstance(w, gui.ttk.Label)][-2:]))


def main():
    test_finding_a_listing()
    test_what_a_row_says()
    test_what_the_edit_form_is_filled_with()
    test_rows_are_numbered()
    test_only_what_changed_is_sent()
    test_the_confirmation_says_what_will_change()
    test_the_plugins_answer_is_read_conservatively()
    test_the_12030_reproduction()
    test_a_list_read_before_product_ids()
    test_the_list_says_which_plugin_read_it()
    test_the_panel_reads_and_lists()
    test_the_edit_form()
    test_the_panel_refuses_what_it_cannot_do()
    test_opening_a_listing_and_the_last_read()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL CS EDIT CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
