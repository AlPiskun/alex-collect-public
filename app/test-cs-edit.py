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
import cs_edit                                        # noqa: E402
import cs_proof                                       # noqa: E402
import cs_record                                      # noqa: E402
import stock_compare                                  # noqa: E402

#  A list as plugin 1.0.31 reports it: every listing keeps its own catalogue
#  id, and carries the product id its API patches beside it. A list read before
#  that - one row without a product id - is built by the tests that are about
#  exactly that.
LISTINGS = [
    {"id": 101, "product_id": 1101,
     "title": "1973-74 O-Pee-Chee Walt Tkaczuk #25 EX-MT",
     "sku": "OPC73-25", "inventory": 3, "status": "active",
     "price": "CA$8.50", "url": "https://cs.example/l/101"},
    {"id": 102, "product_id": 1102,
     "title": "1973-74 O-Pee-Chee Joe Watson #91 EX-MT",
     "sku": "OPC73-91", "inventory": 0, "status": "Archived",
     "price": "5.00", "url": "https://cs.example/l/102"},
    {"id": 103, "product_id": 1103,
     "title": "1989 O-Pee-Chee Wayne Gretzky #1",
     "sku": "OPC89-1", "inventory": 1, "status": "Draft", "price": "12"},
    {"id": 104, "product_id": 1104,
     "title": "1971-72 O-Pee-Chee Eddie Shack #60",
     "sku": "OPC71-60", "inventory": 2, "status": "active"},
    {"id": 105, "product_id": 1105,
     "title": "1971-72 O-Pee-Chee Jean Beliveau #20",
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
          set(entry) == {"id", "sku", "title", "card", "url",
                         "product_id"}, str(entry))
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


def summary_text(parent):
    """The panel's summary line - the label that says what the list is doing."""
    texts = [str(w.cget("text") or "") for w in parent.walk()
             if isinstance(w, gui.ttk.Label)]
    return next((text for text in texts
                 if "listings read from CanadianShopper" in text), "")


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


def test_every_field_is_proved_in_one_job():
    """The whole listing, proved by one confirmed click - not six.

    Asked for after every field had been proved one at a time: "can the
    program create the proofs instead of the user". It cannot run unattended -
    a proof is a real change to a live listing - but it can do the whole job
    from one confirmation, skip what an earlier proof settled, find the photos
    itself, and say what to do about whatever did not settle.
    """
    print()
    print("== the whole listing proved, one confirmed click ==")
    folder, app, parent = build_panel()
    cookie = folder / "cookie.txt"
    rows = [{"id": "94b93f6040f5401daabaa9c936efa5a7", "product_id": 0,
             "sku": "OPC1973-74-112", "title": "Jim Pappin #112",
             "status": "active", "inventory": 1, "price": "12.50",
             "images": ["https://cs.example/api/file/current.webp",
                        "https://cs.example/api/file/other-back.webp"]}]
    record = json.dumps({
        "id": rows[0]["id"], "title": "Jim Pappin #112",
        "primaryImageUrl": "https://cs.example/api/file/current.webp",
        "images": ["https://cs.example/api/file/current.webp",
                   "https://cs.example/api/file/gallery.webp"]})
    asked, questions, shown = [], [], []

    def fake_prove(field, url, cookie="", staged_url="", listing=None,
                   **kwargs):
        asked.append({"field": field, "staged": staged_url})
        good = field != "inventory"
        return {"field": field, "label": cs_proof.field_label(field),
                "verdict": "written" if good else "refused", "written": good,
                "restored": True if good else None, "status": 403 if not good
                else 200, "restore_status": 200 if good else 0,
                "old": 1, "trial": 2, "restore": 1, "after": 2, "final": 1,
                "url": url, "why": "the site's answer",
                "steps": [{"step": "GET the record", "status": 200}],
                "at": "2026-11-03 09:00:00"}

    def yes(title, question, **kwargs):
        questions.append((title, question))
        return True

    def sync_background(app_, work, done):
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        return done(result, error)

    harness._BOX.shown[:] = []
    harness._BOX.askyesno = yes
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "open_path", lambda path: True), \
            patch.object(cs_proof, "staged_photo",
                         lambda folder, title, extra_folders=(): ""), \
            patch.object(cs_proof, "staged_photos",
                         lambda folder, **kwargs: []), \
            patch.object(cs_proof, "read_record",
                         lambda url, cookie="": (200, record)), \
            patch.object(cs_proof, "photo_alive",
                         lambda url, **k: (True, "image/webp")), \
            patch.object(cs_proof, "prove", fake_prove):
        read_into(app, folder, parent, rows)
        select(parent, "Pappin")
        app.lines[:] = []
        find(parent, gui.ttk.Button, "Prove every field...").invoke()

    check("one question at the start, not one per field",
          len(questions) == 1, str([title for title, _q in questions]))
    check("and it names every field it is about to write",
          all(label in questions[0][1] for label in cs_proof.labels()),
          questions[0][1] if questions else "")
    check("every field is proved, in the order they are offered",
          [entry["field"] for entry in asked] == cs_proof.proof_fields(),
          str([entry["field"] for entry in asked]))
    photo_writes = {entry["field"]: entry["staged"] for entry in asked
                    if entry["staged"]}
    check("a photo is found for each photo field, without asking",
          photo_writes.get("primaryImageUrl", "").endswith("gallery.webp") and
          photo_writes.get("images", "").endswith("other-back.webp"),
          str(photo_writes))
    check("and the two never get the same photo, because a gallery that "
          "already holds it proves nothing",
          photo_writes.get("images") != photo_writes.get("primaryImageUrl"),
          str(photo_writes))
    check("the listing's sentence says how it went",
          any("of 6 fields are settled" in line for _tag, line in app.lines),
          str(app.lines[-5:]))
    check("the field that would not settle is named with what to do",
          any("What to do" in line and "not allowed" in line
              for _tag, line in app.lines), str(app.lines[-6:]))
    check("the problem is put in front of the person, not only in the log",
          any(kind == "showwarning" for kind, _a in harness._BOX.shown),
          str(harness._BOX.shown)[:300])
    proof_files = sorted(folder.glob("cs-proof-*.txt"))
    check("one proof file holds every field tried",
          len(proof_files) == 1 and
          all(cs_proof.field_label(field) in
              proof_files[0].read_text(encoding="utf-8")
              for field in cs_proof.proof_fields()), str(proof_files))
    text = proof_files[0].read_text(encoding="utf-8") if proof_files else ""
    check("and it names the field that needs attention",
          "Needs attention:" in text and "Stock:" in text, text[:300])
    saved = cs_proof.load_proofs(folder)
    check("the fields that settled are remembered; the refused one is not",
          cs_proof.settled("priceCad", saved) and
          not cs_proof.settled("inventory", saved), str(saved))

    #  A field an earlier proof settled is not written again - a proof is a
    #  real change to a live listing, and repeating it proves nothing new.
    folder2, app2, parent2 = build_panel()
    cookie2 = folder2 / "cookie.txt"
    (folder2 / cs_proof.PROOFS_FILE).write_text(json.dumps({
        "priceCad": {"at": "2026-11-01 10:00:00", "verdict": "written",
                     "restored": True, "proven": True, "listing": "a",
                     "title": "Jim Pappin #112"}}), encoding="utf-8")
    asked[:] = []
    questions[:] = []
    harness._BOX.shown[:] = []
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "CS_COOKIE_FILE", cookie2), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "open_path", lambda path: True), \
            patch.object(cs_proof, "staged_photo",
                         lambda folder, title, extra_folders=(): ""), \
            patch.object(cs_proof, "staged_photos",
                         lambda folder, **kwargs: []), \
            patch.object(cs_proof, "read_record",
                         lambda url, cookie="": (200, record)), \
            patch.object(cs_proof, "photo_alive",
                         lambda url, **k: (True, "image/webp")), \
            patch.object(cs_proof, "prove", fake_prove):
        read_into(app2, folder2, parent2, rows)
        select(parent2, "Pappin")
        app2.lines[:] = []
        find(parent2, gui.ttk.Button, "Prove every field...").invoke()

    check("a settled field is left alone",
          [entry["field"] for entry in asked] ==
          [field for field in cs_proof.proof_fields() if field != "priceCad"],
          str([entry["field"] for entry in asked]))
    check("and the question says which field was already settled",
          questions and "Already settled, so not written again: Price"
          in questions[0][1], questions[0][1] if questions else "")
    check("the job still counts it as done, and the listing has six fields",
          any("of 6 fields are settled" in line for _tag, line in app2.lines),
          str(app2.lines[-4:]))
    check("nothing is left behind for the skipped field",
          cs_proof.settled("priceCad", cs_proof.load_proofs(folder2)), "")
    harness._BOX.askyesno = lambda *a, **k: True


def test_a_settled_field_is_not_reported_as_broken():
    """The run from the report, exactly: five settled, one gallery, and a
    batch full of other people's cards.

    What came back was "the write was accepted but not readable back" for five
    fields that had not been written at all, "No field is settled" underneath
    them, and two photos of *different cards* lined up for the gallery. Settled
    is not broken, and a photo the app is not sure is this card is never
    written to a live listing.
    """
    print()
    print("== a settled field reads as settled, and never another card's photo ==")
    folder, app, parent = build_panel()
    cookie = folder / "cookie.txt"
    wurmple = "#006/196 Wurmple SWSH11: Lost Origin - Pokémon TCG"
    rows = [{"id": "a2304e72dbca4e678e7111d011ade22d", "product_id": 0,
             "sku": "PKM-SWSH11-006", "title": wurmple,
             "status": "active", "inventory": 1, "price": "1.00"}]
    record = json.dumps({
        "id": rows[0]["id"], "title": wurmple, "priceCad": 1.0,
        "inventory": 1, "description": "A card.",
        "primaryImageUrl":
            "https://canadianshopper.ca/api/file/wurmple-front.jpg"})
    #  Every field but the gallery was settled by an earlier proof.
    (folder / cs_proof.PROOFS_FILE).write_text(json.dumps({
        field: {"at": "2026-11-02 15:34:38", "verdict": "written",
                "restored": True, "proven": True, "listing": rows[0]["id"],
                "title": wurmple}
        for field in ("priceCad", "title", "description", "inventory",
                      "primaryImageUrl")}), encoding="utf-8")
    asked, questions = [], []
    harness._BOX.shown[:] = []

    def fake_prove(field, url, cookie="", staged_url="", listing=None,
                   **kwargs):
        asked.append({"field": field, "staged": staged_url})
        return {"field": field, "label": cs_proof.field_label(field),
                "verdict": "written", "written": True, "restored": True,
                "status": 200, "restore_status": 200, "url": url,
                "why": "the site's answer", "steps": [],
                "at": "2026-11-03 07:24:03"}

    def yes(title, question, **kwargs):
        questions.append((title, question))
        return True

    def sync_background(app_, work, done):
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        return done(result, error)

    harness._BOX.askyesno = yes
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "open_path", lambda path: True), \
            patch.object(cs_proof, "staged_photo",
                         lambda folder, title, extra_folders=(): ""), \
            patch.object(cs_proof, "staged_photos",
                         lambda folder, **kwargs: [
                             {"title": "56 Syl Apps 1978-79 O-Pee-Chee "
                                       "Baseball Card",
                              "url": "https://canadianshopper.ca/api/file/"
                                     "56-Syl-Apps-front.jpg"},
                             {"title": "73 Pit Martin 1973-74 O-Pee-Chee",
                              "url": "https://canadianshopper.ca/api/file/"
                                     "73-Pit-Martin-front.jpg"}]), \
            patch.object(cs_proof, "read_record",
                         lambda url, cookie="": (200, record)), \
            patch.object(cs_proof, "photo_alive",
                         lambda url, **k: (False, "")), \
            patch.object(cs_proof, "prove", fake_prove):
        read_into(app, folder, parent, rows)
        select(parent, "Wurmple")
        app.lines[:] = []
        find(parent, gui.ttk.Button, "Prove every field...").invoke()

    check("the question names only the field that is left to prove",
          questions and "Prove 1 field" in questions[0][0] and
          "Already settled, so not written again: Price, Title, Description, "
          "Stock, Main photo" in questions[0][1],
          questions[0][1] if questions else "")
    check("nothing at all was written - not a different card's photo either",
          asked == [], str(asked))
    check("a settled field reads as settled, not as unreadable",
          any("Price was settled by an earlier proof" in line
              for _tag, line in app.lines) and
          not any("not readable back" in line for _tag, line in app.lines),
          str(app.lines[:6]))
    check("the gallery says the record has no gallery, and names its keys",
          any("carries no gallery" in line and "primaryImageUrl" in line
              for _tag, line in app.lines), str(app.lines[-4:]))
    check("a skipped photo field does not claim its photo was written",
          not any("The photo used" in line or "The photo added" in line
                  for _tag, line in app.lines), str(app.lines[-6:]))
    check("no other card's photo is used, named as written, or left behind",
          not any("Syl-Apps" in line or "Pit-Martin" in line
                  for _tag, line in app.lines) and
          "Syl-Apps" not in json.dumps(asked), str(asked))
    check("five fields are settled, and the gallery is not on this record",
          any("5 of 6 fields are settled" in line and
              "Gallery photos is not on this site's record" in line
              for _tag, line in app.lines), str(app.lines[-4:]))
    infos = [str(payload) for kind, payload in harness._BOX.shown
             if kind == "showinfo"]
    check("and it is put in front of the person as information, not a warning",
          any("no such field" in text and "Gallery photos" in text
              for text in infos) and
          not any(kind == "showwarning" for kind, _payload
                  in harness._BOX.shown),
          str(harness._BOX.shown)[:500])
    saved = cs_proof.load_proofs(folder)
    check("the earlier proofs are still remembered",
          all(cs_proof.settled(field, saved) for field in
              ("priceCad", "title", "description", "inventory",
               "primaryImageUrl")), str(sorted(saved)))
    harness._BOX.askyesno = lambda *a, **k: True


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

    # ---- the panel asks before spending a write that could only fail
    #
    #  One row without a product id among rows that have one: a list read
    #  before this listing had one, or a listing the plugin has just started
    #  reporting. Either way one read settles it.
    mixed = [dict(row) for row in LISTINGS]
    mixed[1].pop("product_id")            # Watson: no product id
    folder, app, parent = build_panel()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app, folder, parent, mixed)
    check("a mixed read says how many of it can be edited",
          any("4 with a product id, so 4 can be edited here" in text
              for _tag, text in app.lines), str(app.lines[-4:]))
    find(parent, gui.ttk.Button, "Search").invoke()
    select(parent, "Watson")
    answers = []
    harness._BOX.askyesno = lambda title, *a, **k: (answers.append(title),
                                                   True)[1]

    def tools(action):
        #  Both actions stay resolvable for the whole sequence: the retry is a
        #  read followed by another write, and a test that only patched the
        #  write would be testing a read that never starts.
        return ("/plugins/cs/edit.py" if action == gui.CS_LISTING_UPDATE_ACTION
                else "/plugins/cs/stock.py")

    runs_before = len(app.runs)
    with patch.object(gui, "TOOL_ACTION", tools):
        find(parent, gui.ttk.Button,
             "Put the selected listing on sale").invoke()
    check("a row with no product id sends no write at all",
          all("--set-file" not in run["args"] for run in app.runs[runs_before:]),
          str(app.runs[runs_before:]))
    check("the panel says why, before anything is spent",
          any("has no product id in the list on screen" in text
              for _tag, text in app.lines), str(app.lines[-3:]))
    check("and offers the read that would give it one",
          answers == ["Read the listings again?"], str(answers))
    check("which starts the read", len(app.runs) == runs_before + 1 and
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
    check("the same change is made from the fresh row",
          len(app.runs) == writes_before + 1 and
          "--set-file" in app.runs[-1]["args"], str(app.runs[-1:]))
    plan = json.loads((folder / "cs-listing-update.json").read_text(
        encoding="utf-8"))["items"][0]
    check("and it carries the product id this time",
          plan["product_id"] == 4321 and plan["status"] == "active" and
          plan["id"] == 102, str(plan))
    check("the change is named again before it is written",
          answers.count("Change this listing?") == 1, str(answers))

    # ---- and when the site gives no product id for one listing at all
    folder, app, parent = build_panel()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app, folder, parent, mixed)
    find(parent, gui.ttk.Button, "Search").invoke()
    select(parent, "Watson")
    answers.clear()
    runs_before = len(app.runs)
    with patch.object(gui, "TOOL_ACTION", tools):
        find(parent, gui.ttk.Button,
             "Put the selected listing on sale").invoke()
    read_run = app.runs[-1]
    #  The fresh list still has no product id for this listing.
    Path(read_run["args"][1]).write_text(json.dumps({"items": [
        {"id": 102, "title": "1973-74 O-Pee-Chee Joe Watson #91 EX-MT",
         "sku": "OPC73-91", "inventory": 0, "status": "Archived"}]}),
        encoding="utf-8")
    with patch.object(gui, "TOOL_ACTION", tools):
        read_run["on_done"](0)
    check("a listing the site gives no product id for is not written",
          all("--set-file" not in run["args"]
              for run in app.runs[runs_before + 1:]),
          str(app.runs[runs_before:]))
    check("and the panel says where it has to be changed instead",
          any("vendor dashboard" in str(payload)
              for _kind, payload in harness._BOX.shown) and
          any("no product id" in text for _tag, text in app.lines),
          str(harness._BOX.shown[-1:]) + str(app.lines[-2:]))

    # ---- a plugin that refuses one anyway is still handled
    report = cs_edit.report([entry], refusal)
    check("a refusal after a write is still read as a failure",
          cs_edit.wants_product_id(report) and not report["changed"],
          str(report))


def test_a_read_with_no_product_ids_at_all():
    """The live case: 2,541 listings, not one product id.

    That is not 2,541 listings to edit by hand - it is a reading that does not
    carry product ids. The panel must say so once, must not offer to read the
    same nothing again, and must still lead somewhere: the listing's own page.
    """
    print()
    print("== 5d0. a read in which no listing has a product id ==")
    nothing = [{key: value for key, value in row.items()
                if key != "product_id"} for row in LISTINGS]
    check("the note says what the reading is missing, not what to do by hand",
          "none can be edited here yet" in
          cs_edit.editable_note(0, len(nothing)) and
          "vendor dashboard" not in cs_edit.editable_note(0, len(nothing)),
          cs_edit.editable_note(0, len(nothing)))
    check("and the whole-read case is told apart from a single missing row",
          cs_edit.nothing_editable(nothing) and
          not cs_edit.nothing_editable(items()) and
          not cs_edit.nothing_editable([]), "")
    #  Once a proof has settled the price, "none can be edited here" is a
    #  sentence that stops someone using the button that works: the price is
    #  written to the record these rows already address.
    proven = cs_edit.editable_note(0, len(nothing), price_proven=True)
    check("with the price proven, the note names the fields that are blocked",
          "no title, stock count or state" in proven, proven)
    check("and says the price can be set from here",
          "price" in proven and "can be set from here" in proven, proven)
    check("without a proof it does not promise a price write",
          "can be set from here" not in cs_edit.editable_note(0, len(nothing)),
          cs_edit.editable_note(0, len(nothing)))
    unaddressed = [{"id": row["id"], "title": row["title"]}
                   for row in nothing]
    check("a read with no listing addresses says so once, for the reader",
          "No listing in that read carried its own address" in
          cs_edit.address_gap(unaddressed) and
          "1 listing)" in cs_edit.address_gap(unaddressed[:1]) and
          cs_edit.address_gap(
              [{"id": "a", "url": "https://cs.example/l/a"}]) == "",
          cs_edit.address_gap(unaddressed)[:120])
    gap = cs_edit.product_id_gap(nothing, plugin="1.0.39", works=False,
                                 price_proven=True)
    check("the gap sentence names the fields the plugin cannot send",
          "cannot send a title, a stock count or a state" in gap, gap[:200])
    check("and no longer claims no edit button can send anything",
          "edit buttons cannot send anything" not in gap, gap[:200])
    check("it points at the price button that does reach the row",
          "Set the selected listing's price" in gap, gap[-300:])

    folder, app, parent = build_panel()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app, folder, parent, nothing)
    check("the read says so in one line",
          any("none of them with a product id" in text
              for _tag, text in app.lines), str(app.lines[-4:]))
    check("and the console explains it is the reader, not this list",
          any("reader is not reporting one" in text
              for _tag, text in app.lines), str(app.lines[-3:]))
    check("and points at the one button that gathers the evidence for it",
          any('Press "Save a read diagnosis..."' in text
              for _tag, text in app.lines), str(app.lines[-3:]))

    find(parent, gui.ttk.Button, "Search").invoke()
    select(parent, "Watson")          # archived, so a change is available
    harness._BOX.shown.clear()
    answers = []
    runs_before = len(app.runs)
    harness._BOX.askyesno = lambda title, *a, **k: (answers.append(title),
                                                   True)[1]
    app.opened[:] = []
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/edit.py"):
        find(parent, gui.ttk.Button,
             "Put the selected listing on sale").invoke()
    check("nothing is sent", len(app.runs) == runs_before, str(app.runs[-1:]))
    check("the panel does not offer to read the same nothing again",
          answers == ["That listing has to be changed on the site"],
          str(answers))
    check("it opens the listing's own page so it can be changed there",
          app.opened == ["https://cs.example/l/102"], str(app.opened))
    check("and says nothing in the read can be addressed",
          any("no listing in that read carried a product id" in text.lower()
              for _tag, text in app.lines), str(app.lines[-3:]))


def test_a_reader_that_says_zero():
    """The other shape of "no product ids": every row says 0.

    Plugin 1.0.31 emitted ``"product_id": 0`` for all 2,541 listings. A zero
    is not an id - no product has one - so the panel must not count it as
    editable, must not put it in a write, and must not explain a failure by it.
    """
    print()
    print("== 5d1. a reader that reports 0 for every listing ==")
    zeroed = [dict(row, product_id=0) for row in LISTINGS]
    check("a zero is not an id",
          cs_edit.product_id({"product_id": 0}) == "" and
          cs_edit.product_id({"product_id": "0"}) == "" and
          cs_edit.product_id({"product_id": " 0.0 "}) == "" and
          cs_edit.product_id({"ids": {"productId": 0}}) == "", "")
    check("a real id still is one, whatever shape the vendor uses",
          cs_edit.product_id({"product_id": " 4321 "}) == "4321" and
          cs_edit.product_id({"product_id": 4321}) == "4321" and
          cs_edit.product_id({"ids": {"product_id": "14effcaceb8a4b66"}}) ==
          "14effcaceb8a4b66", "")
    check("a zero beside a real id loses to the real one",
          cs_edit.product_id({"product_id": 0, "productId": 4321}) == "4321"
          and cs_edit.product_id({"product_id": 4321,
                                  "ids": {"productId": 0}}) == "4321", "")
    check("every row of that read counts as having no product id",
          cs_edit.product_id_counts(zeroed) == (0, len(zeroed)) and
          cs_edit.nothing_editable(zeroed), "")

    zeros, total = cs_edit.zero_product_id_counts(zeroed)
    check("and the reader's zeros are counted as zeros, not as missing keys",
          (zeros, total) == (len(zeroed), len(zeroed)) and
          cs_edit.zero_product_id_counts(items()) == (0, len(LISTINGS)), "")
    note = cs_edit.zero_product_id_note(zeros, total)
    check("the note says what the plugin did, and that 0 is not an id",
          "product_id 0" in note and "0 is not an id" in note, note)
    check("it does not send anyone to the dashboard for 2,541 listings",
          "vendor dashboard" not in note, note)
    check("and it names the buttons that still do work, not just a panel",
          "stock.set" in note and
          "Set CanadianShopper to the website's counts..." in note and
          "Fix the selected cards..." in note, note)
    check("a read with no zeros has nothing to say",
          cs_edit.zero_product_id_note(0, 5) == "", "")

    #  A write must never carry a zero: it addresses a product that cannot
    #  exist, so the answer could only be another failure.
    entry = cs_edit.plan(stock_compare.plugin_items(
        {"items": [dict(LISTINGS[0], product_id=0)]})[0], inventory=9)
    check("the plan carries the listing id and no product id at all",
          entry.get("id") == 101 and "product_id" not in entry,
          str(entry))
    entry = cs_edit.plan(items()[0], inventory=9)
    check("a real product id still travels with the change",
          entry.get("product_id") == 1101, str(entry))
    check("and a failure is not explained by 'product id 0'",
          "product id" not in cs_edit.identified_by(
              {"id": 101, "product_id": 0, "sku": "OPC73-25"}),
          cs_edit.identified_by({"id": 101, "product_id": 0,
                                 "sku": "OPC73-25"}))

    #  ---- the panel, with a plugin that reports zeros
    folder, app, parent = build_panel()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app, folder, parent, zeroed)
    check("the read still lists every listing",
          len(listing_box(parent).items) == len(LISTINGS), "")
    check("the console names the plugin's zeros, not a missing key",
          any("product_id 0" in text and "0 is not an id" in text
              for _tag, text in app.lines), str(app.lines[-3:]))
    check("and it does not promise the edits can be made",
          not any("every one with a product id" in text
                  for _tag, text in app.lines), str(app.lines[-4:]))

    find(parent, gui.ttk.Button, "Search").invoke()
    select(parent, "Watson")
    harness._BOX.shown.clear()
    answers = []
    runs_before = len(app.runs)
    harness._BOX.askyesno = lambda title, *a, **k: (answers.append(title),
                                                   True)[1]
    app.opened[:] = []
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/edit.py"):
        find(parent, gui.ttk.Button,
             "Put the selected listing on sale").invoke()
    check("an edit is never sent to /api/products/0/",
          len(app.runs) == runs_before, str(app.runs[-1:]))
    check("the panel does not offer to read the same zeros again",
          answers == ["That listing has to be changed on the site"],
          str(answers))
    check("it opens the listing so it can be changed there",
          app.opened == ["https://cs.example/l/102"], str(app.opened))
    check("and says the zero out loud",
          any("product_id 0" in text for _tag, text in app.lines),
          str(app.lines[-3:]))


def test_the_version_that_reports_product_ids():
    """Which plugin version reports real ids, and what a read without them gets.

    Plugin 1.0.34 emits each listing's real product id as a string and leaves
    the key out when there is none. So a read with no usable id is two
    different things depending on the plugin: an old one that needs updating,
    or a current one with a defect - and the console has to say which.
    """
    print()
    print("== 5d2. the plugin version that reports real product ids ==")
    check("the core and the edit panel name the same version",
          gui.CS_PRODUCT_ID_VERSION == cs_edit.PRODUCT_ID_VERSION and
          cs_edit.PRODUCT_ID_VERSION == "1.0.34",
          "%r %r" % (gui.CS_PRODUCT_ID_VERSION, cs_edit.PRODUCT_ID_VERSION))

    older = cs_edit.needed_version_note("1.0.31", "1.0.34")
    check("an older plugin is told which version fixes it",
          "1.0.31" in older and "1.0.34" in older and
          "updating the plugin is the fix" in older, older)
    current = cs_edit.needed_version_note("1.0.34", "1.0.34")
    check("the version that reports them is not told to update",
          "updating the plugin" not in current and "defect" in current,
          current)
    newer = cs_edit.needed_version_note("1.0.35", "1.0.34")
    check("and neither is a newer one",
          "defect" in newer and "updating the plugin" not in newer, newer)
    unknown = cs_edit.needed_version_note("", "1.0.34")
    check("an unreadable version only names the version",
          "1.0.34" in unknown and "defect" not in unknown and
          "updating the plugin" not in unknown, unknown)
    check("with nothing to compare against it says nothing",
          cs_edit.needed_version_note("1.0.31", "") == "", "")
    check("a version that is not a number is never treated as new enough",
          "updating the plugin is the fix" in
          cs_edit.needed_version_note("unknown", "1.0.34"), "")

    zeroed = [dict(row, product_id=0) for row in LISTINGS]
    said = cs_edit.product_id_gap(zeroed, plugin="1.0.31")
    check("the whole sentence carries the zeros and the version that fixes it",
          "product_id 0" in said and "1.0.31" in said and "1.0.34" in said and
          "updating the plugin is the fix" in said, said)
    check("and ends with what still works",
          said.endswith("all still work."), said[-80:])
    quiet = cs_edit.product_id_gap(zeroed, plugin="1.0.31", works=False)
    check("a refusal that names the card does not repeat that tail",
          "still work" not in quiet, quiet)
    check("a read that can be written says nothing at all",
          cs_edit.product_id_gap(items(), plugin="1.0.34") == "", "")
    check("an empty read says nothing either",
          cs_edit.product_id_gap([], plugin="1.0.34") == "", "")

    #  ---- the panel, with an older plugin behind it
    folder, app, parent = build_panel()          # installs 1.0.19
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app, folder, parent, zeroed)
    said = " ".join(text for _tag, text in app.lines[-3:])
    check("the console names the plugin that read it and the version needed",
          "read by plugin 1.0.19" in said and "1.0.34" in said and
          "updating the plugin is the fix" in said, said)

    #  ---- and with the version that does report them
    folder2 = Path(tempfile.mkdtemp())
    harness.install_plugin("1.0.34", folder2 / "plugin")
    gui.BASE = folder2
    app2 = harness.FakeApp(folder2)
    parent2 = harness.FakeWidget()
    gui.build_csledit(parent2, app2)
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app2, folder2, parent2, zeroed)
    said = " ".join(text for _tag, text in app2.lines[-3:])
    check("a current plugin reporting zeros is called a defect, not an update",
          "is a defect in the reader" in said and
          "updating the plugin" not in said, said)
    check("and it still lists everything that was read",
          len(listing_box(parent2).items) == len(LISTINGS), "")

    #  ---- 1.0.34's real shape: ids as strings, key omitted when absent
    strings = [dict(row, product_id=str(row["product_id"])) for row in LISTINGS]
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app2, folder2, parent2, strings)
    said = str(app2.lines[-1][1])
    check("string ids from 1.0.34 are editable, with nothing said against it",
          "every one with a product id" in said and "defect" not in said,
          said)
    check("and the read is listed like any other",
          len(listing_box(parent2).items) == len(LISTINGS),
          str(listing_box(parent2).items))
    plan = cs_edit.plan(stock_compare.plugin_items(
        {"items": [dict(strings[0])]})[0], inventory=9)
    check("the id the plugin sent is the id the write carries, unchanged",
          plan.get("product_id") == "1101", str(plan))


def test_what_the_read_did_carry():
    """2,587 listings, 0 with a real product id, 2,587 without the key.

    Plugin 1.0.34's own console said exactly that, which means the reader is
    reading listings that carry no product reference at all. Nothing the core
    can do invents one - but what the read *did* carry decides whether the
    reader could resolve one, so the console counts it instead of only saying
    what is missing.
    """
    print()
    print("== 5d3. what the read did carry ==")
    full = [{"id": "a%04d" % n, "sku": "OPC73-%d" % n,
             "url": "https://canadianshopper.ca/l/%d" % n,
             "title": "card %d" % n} for n in range(2587)]
    counts = cs_edit.identity_counts(full)
    check("every identifier a row carries is counted",
          counts == {"product_id": 0, "id": 2587, "sku": 2587, "url": 2587},
          str(counts))
    note = cs_edit.identity_note(full)
    check("the line says what the read did carry, with the counts",
          "2587 listing ids" in note and "2587 SKUs" in note and
          "2587 listing addresses" in note and "(of 2587 listings)" in note,
          note)
    check("and that resolving is therefore possible for the reader",
          "resolving a listing to its product takes" in note and
          "it is only the product id itself that never arrived" in note, note)
    check("a product id appears in the counts only when one is there",
          cs_edit.identity_counts(items())["product_id"] == len(LISTINGS), "")

    partial = [{"id": "a", "sku": "S1"}, {"id": "b"}, {"id": "c"}]
    note = cs_edit.identity_note(partial)
    check("a read where only some rows have an SKU says how many would be left",
          "resolving by SKU would leave 0 listings behind" not in note and
          "3 listing ids" in note, note)
    note = cs_edit.identity_note([{"id": "a"}, {"id": "b"}, {"title": "x"}])
    check("a read with no SKU on any row says the product has to come from "
          "the vendor's data",
          "no SKU on any row" in note and "vendor's own data" in note, note)
    check("a read with no identifier at all is said plainly",
          "not reading the listings' own identifiers" in
          cs_edit.identity_note([{"title": "x"}, {"title": "y"}]), "")
    check("and an empty read says nothing at all",
          cs_edit.identity_note([]) == "", "")

    #  ---- it is part of the sentence the panel prints, not a second one
    gap = cs_edit.product_id_gap(full, plugin="1.0.34")
    check("the gap sentence carries the identity line",
          "What the read did carry" in gap, gap)
    check("in the right place: after the version, before what still works",
          gap.index("1.0.34") < gap.index("What the read did carry") <
          gap.index("still work"), gap)

    #  ---- and the panel prints it when a read cannot be written
    folder, app, parent = build_panel()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app, folder, parent, full)
    said = " ".join(text for _tag, text in app.lines[-3:])
    check("the console names what the read did carry",
          "2587 SKUs" in said and "2587 listing addresses" in said, said)
    check("the read itself keeps every listing, so the count is the read's",
          any("2587 listings read" in text for _tag, text in app.lines),
          str(app.lines[-4:]))
    check("and every listing the read brought is in the list, not the first "
          "200 of them",
          len(listing_box(parent).items) == len(full) == 2587,
          str(len(listing_box(parent).items)))
    check("the summary says the whole read is on screen",
          "2587 listings read" in summary_text(parent) and
          "All 2587 listings shown" in summary_text(parent),
          summary_text(parent))
    check("and the row that sorts last is really there",
          any("card 2586" in text for text in listing_box(parent).items),
          str(listing_box(parent).items[-1:]))


def test_the_readers_own_numbers():
    """The run that started this: 2,596 listings, 0 with a real product id.

    Plugin 1.0.38 printed its own line for exactly that -
    ``stock.list: 2596 listings, 0 with a real product id, 2596 without the
    key, 0 reported as 0`` - and the panel's answer has to quote it: the
    numbers are what a defect report is built from, and "without the key" is a
    different problem from a reader writing a placeholder zero.
    """
    print()
    print("== 5d4. what the reader said it found ==")
    line = ("stock.list: 2596 listings, 0 with a real product id, 2596 "
            "without the key, 0 reported as 0")
    check("the reader's count line is read as four numbers",
          cs_edit.reader_id_counts(line) == (2596, 0, 2596, 0),
          str(cs_edit.reader_id_counts(line)))
    check("a line for one listing is read too",
          cs_edit.reader_id_counts(
              "stock.list: 1 listing, 0 with a real product id, 1 without "
              "the key, 0 reported as 0") == (1, 0, 1, 0), "")
    check("a console with no such line says nothing rather than inventing one",
          cs_edit.reader_id_counts("Stock read finished.") is None and
          cs_edit.reader_says_note("Stock read finished.") == "", "")

    said = cs_edit.reader_says_note(line)
    check("the sentence quotes the reader's own numbers",
          "2596 listings" in said and "0 with a real product id" in said and
          "2596 without the key at all" in said and
          "0 reported as 0" in said, said)

    rows = [{"id": "a%04d" % n, "sku": "OPC73-%d" % n,
             "url": "https://canadianshopper.ca/l/%d" % n,
             "title": "card %d" % n} for n in range(2596)]
    gap = cs_edit.product_id_gap(rows, plugin="1.0.38", needed="1.0.34",
                                 reader_text=line)
    check("the gap sentence carries the reader's line", said in gap, gap)
    check("and says this read was not the list-only one",
          "not the fast, list-only one" in gap and
          "never asks for that flag" in gap, gap)
    check("so the lookups are the thing to report, not the shop",
          "came back empty" in gap, gap)
    check("the version sentence is still there, after it",
          gap.index(said) < gap.index("defect in the reader"), gap)
    check("and what still works comes last",
          gap.index("came back empty") < gap.index("still work"), gap)

    #  A read whose lookups failed says that instead - the two sentences point
    #  at different things, and only one of them is a plugin defect.
    failed = cs_edit.ids_were_asked_for_note(text_has_lookups=True)
    check("a read with failed lookups names the failures",
          "reports failures above" in failed and
          "came back empty" not in failed, failed)
    check("and a read without any says the lookups never ran or came back "
          "empty",
          "either did not run or came back empty" in
          cs_edit.ids_were_asked_for_note(False), "")

    #  The comparison panel asks for the list-only read. Its rows come back
    #  with no ids by design, and this sentence must never be printed there.
    check("a gap with no reader line says nothing about which read it was",
          "list-only" not in cs_edit.product_id_gap(rows, plugin="1.0.38",
                                                   needed="1.0.34"), "")


def test_the_diagnosis_file():
    """The three things the plugin's author asked for, and the sanitiser.

    A round trip with the reader's author ended in *send the console output,
    whether the ids phase appeared, and one row with its detail response* -
    the plugin could not reproduce 0 ids, which means the next answer has to
    be evidence rather than another theory. Everything below is what makes
    that file safe to paste: the row's shape without its secrets, and a detail
    request that answers instead of raising.
    """
    print()
    print("== 5d5. the file a plugin author asked for ==")

    #  ---- the sanitiser: shapes, not accounts
    secret = cs_edit.sanitize({"sessionToken": "abc123", "title": "Walt Tkaczuk"})
    check("a key that names a secret has its value hidden, not printed",
          "hidden" in secret and "abc123" not in secret, secret)
    long_text = cs_edit.sanitize({"title": "W" * 120})
    check("a long string is cut, and still says how long it was",
          "str(120)" in long_text and "W" * 60 not in long_text and
          "\u2026" in long_text, long_text)
    check("a zero is kept as a zero: that is the question being asked",
          "product_id: int 0" in cs_edit.sanitize({"product_id": 0}), "")
    many = cs_edit.sanitize({"images": list(range(30))})
    check("a long list is capped and says how many were left out",
          "... 18 more" in many and "29" not in many, many)
    deep = cs_edit.sanitize({"a": {"b": {"c": {"d": "e"}}}})
    check("nesting stops at three, as an object with a key count",
          "object(1 keys)" in deep and "d:" not in deep, deep)

    #  ---- which key (if any) is the product reference
    check("a key holding zero is reported as a key - and as not an id",
          cs_edit.product_reference_keys({"product_id": 0}) ==
          [("product_id", "zero - not an id")], "")
    check("a real id is reported present",
          cs_edit.product_reference_keys({"product_id": "4321"}) ==
          [("product_id", "present")], "")
    check("an empty key is told apart from a missing one",
          cs_edit.product_reference_keys({"product_id": ""}) ==
          [("product_id", "empty")], "")
    check("a row with no product key at all reports nothing",
          cs_edit.product_reference_keys({"id": "a1", "sku": "X"}) == [], "")
    check("the camel-case spelling is found too",
          cs_edit.product_reference_keys({"productId": 7}) ==
          [("productId", "present")], "")

    #  ---- whether the reader's own progress says its lookups ran
    ran = cs_edit.phases_note(["read", "ids"])
    check("a reported ids phase means the lookups ran",
          "the lookups ran" in ran and "not usable" in ran, ran)
    failed = cs_edit.phases_note(["read", "ids"], 3)
    check("and with failures said, it says some of them failed",
          "some of them failed" in failed and "not usable" not in failed,
          failed)
    missing = cs_edit.phases_note(["read", "list"])
    check("phases without an id phase mean the lookups never started",
          "did not run at all" in missing and "ids" not in missing, missing)
    none = cs_edit.phases_note([])
    check("a reader that reports no phases is said to report none",
          "no progress phases at all" in none, none)

    #  ---- the one address, and the listing id it is built from
    check("the detail address is the one the plugin's reader uses",
          cs_edit.detail_url("94b93f60") ==
          "https://canadianshopper.ca/api/data/product/94b93f60", "")
    check("a base with a trailing slash does not double it",
          cs_edit.detail_url("abc", base="https://x.example/") ==
          "https://x.example/api/data/product/abc", "")
    check("no listing id, no address to call",
          cs_edit.detail_url("") == "", "")
    check("a row's own id is not its product id",
          cs_edit.listing_id({"id": "14effcaceb8a", "product_id": 4321}) ==
          "14effcaceb8a", "")

    #  ---- one request, answering instead of raising
    seen = []

    def opener(url, cookie):
        seen.append((url, cookie))
        return 200, "application/json", '{"product": {"id": "999"}}'

    check("the request is made and its answer handed back",
          cs_edit.fetch_detail("https://cs.example/api/data/product/x",
                              "session_token=z", opener=opener) ==
          (200, "application/json", '{"product": {"id": "999"}}'), "")
    check("and it was made with the person's own session",
          seen and seen[0][1] == "session_token=z", str(seen))
    check("no address, no request at all",
          cs_edit.fetch_detail("", "cookie", opener=opener) == (0, "", "") and
          len(seen) == 1, str(seen))

    def refusing(url, cookie):
        raise OSError("no route to host")

    import urllib.error
    with patch.object(urllib.request, "urlopen",
                      side_effect=urllib.error.URLError("dns")):
        answer = cs_edit.fetch_detail("https://cs.example/api/data/product/x")
    check("a request that cannot be made is an answer, never an exception",
          answer[0] == 0 and "dns" in answer[2], str(answer))

    #  ---- the file itself
    row = {"id": "94b93f6040f5401daabaa9c936efa5a7", "product_id": 0,
           "sku": "OPC1973-74-112", "sessionToken": "abc123",
           "title": "1973-74 O-Pee-Chee Jim Pappin #112", "images": []}
    output = ("stock.list: 2596 listings, 0 with a real product id, 2596 "
              "without the key, 0 reported as 0\nStock resolution: 2596 "
              "detail requests, 0 usable references, 2596 HTTP 200s without a "
              "usable reference, 0 ambiguous SKUs, 0 hard failures")
    detail = {"url": cs_edit.detail_url("94b93f60"), "status": 200,
              "content_type": "application/json",
              "body": json.dumps({"product": {"id": "999"}, "sku": "OPC-1",
                                  "owner": {"email": "a@b.c"}})}
    text = cs_edit.diagnosis_text(row=row, output=output,
                                  stages=["read", "ids"], plugin="1.0.38",
                                  command="cs-stock.py --stock-out cs-stock.json",
                                  detail=detail, total=2596, editable=0,
                                  app_version="3.30")
    check("the file carries the reader's own count line",
          "2596 listings, 0 with a real product id" in text, "")
    check("the app's own count is beside it, so the two can be compared",
          "2596 listing(s), 0 with a usable product id" in text, "")
    check("the phases are in it, with the sentence they mean",
          "Phases the reader reported: read, ids" in text and
          "the lookups ran" in text, "")
    check("so is the row, with every product-reference key priced",
          "product_id (zero - not an id)" in text and "sku:" in text, "")
    check("and the detail request, with its status and its answer",
          "GET https://canadianshopper.ca/api/data/product/94b93f60" in text
          and "HTTP 200, application/json" in text and
          'product:' in text, "")
    check("the command the app ran is in it, because the flag matters",
          "cs-stock.py --stock-out cs-stock.json" in text, "")
    check("and nothing in it is a session: the token and the email are gone",
          "abc123" not in text and "a@b.c" not in text, "")
    folder_of_test = Path(tempfile.mkdtemp())
    first = cs_edit.diagnosis_path(folder_of_test)
    second = cs_edit.diagnosis_path(folder_of_test)
    check("before anything is written, two calls name the same file",
          first == second and first.name.startswith("cs-read-diagnosis-") and
          first.name.endswith(".txt"), "%s / %s" % (first.name, second.name))
    first.write_text("one", encoding="utf-8")
    third = cs_edit.diagnosis_path(folder_of_test)
    check("after one is written, the next goes beside it, nothing replaced",
          third != first and third.name.endswith("-2.txt") and
          first.read_text(encoding="utf-8") == "one",
          "%s / %s" % (first.name, third.name))
    #  A real diagnosis came back with "... 26 more key(s)" where the answer
    #  was: a 38-key detail record, and the product reference could have been
    #  in any of the hidden ones. A cap that hides a key name hides the answer.
    wide = {"id": "a2304e72dbca", "title": "Wurmple", "category": "cards"}
    for number in range(1, 31):
        wide["field%02d" % number] = number
    wide["productId"] = "the-product"
    wide["sessionToken"] = "abc123"
    body = cs_edit._body_for_diagnosis(json.dumps(wide))
    check("a 38-key detail record is shown key by key, not counted",
          "productId:" in body and "field30:" in body, body[-300:])
    check("and its secret is still hidden at key 35",
          "abc123" not in body and "sessionToken: (hidden" in body,
          body[-200:])
    narrow = cs_edit.sanitize(dict(("k%02d" % n, n) for n in range(20)))
    check("a capped record names what it did not print",
          "... 8 more key(s), names only:" in narrow and "k19" in narrow and
          "k12: int" not in narrow, narrow)

    #  ---- does the record name a product anywhere, or nowhere at all
    found = cs_edit.productish_keys({"productId": "9", "product": {"id": 1},
                                     "category": "x", "products": [1, 2]})
    check("every key mentioning a product is found, in any spelling",
          [key for key, _state in found] == ["productId", "product",
                                             "products"], str(found))
    check("and what it holds is described, not pasted",
          found[0][1] == 'str(1) "9"' and
          found[1][1] == "a record with 1 key(s)" and
          found[2][1] == "a list of 2", str(found))
    check("a record naming no product says so rather than saying nothing",
          cs_edit.productish_keys({"id": "a", "category": "b"}) == [], "")
    silent = cs_edit.diagnosis_text(
        row={"id": "a", "sku": ""}, detail={"url": "u", "status": 200,
                                            "body": json.dumps({"id": "a"})})
    check("a detail response with no product key is called that in the file",
          "No key in that response names a product" in silent, silent)
    named = cs_edit.diagnosis_text(
        row={"id": "a", "sku": "OPC-1"},
        detail={"url": "u", "status": 200,
                "body": json.dumps({"id": "a", "productId": "9"})})
    check("and one that does names the key, what is in it, and that it holds "
          "an id",
          "Keys in that response that mention a product: productId" in named and
          "one of them holds an id: productId" in named, named)

    nested = cs_edit.diagnosis_text(
        row={"id": "a", "product": {"id": 1}, "product_id": 0})
    check("a row naming its product in a key that is not an id says so",
          "Also naming a product: product (a record with 1 key(s))" in nested,
          nested)
    check("and the id-shaped key is not printed twice",
          "Also naming a product: product_id" not in nested, nested)
    check("a row with no such key gets no extra line",
          "Also naming a product" not in named, named)

    #  The real 38-key record from this shop: two keys mention a product, both
    #  null. Saying "names a product" about them would read as a lead.
    cart = {"id": "a2304e72dbca", "title": "Wurmple", "sku": "",
            "isDemoProduct": None, "productOptions": None,
            "availableSizes": [], "tags": None}
    cart_text = cs_edit.diagnosis_text(
        row={"id": "a2304e72dbca", "sku": ""},
        detail={"url": "u", "status": 200, "body": json.dumps(cart)})
    check("a key like isDemoProduct is reported, but not as holding an id",
          "isDemoProduct (empty)" in cart_text and
          "productOptions (empty)" in cart_text and
          "none of them holds an id" in cart_text, cart_text[-600:])

    #  ---- the row's SKU is what a reader resolves by: empty is a fact
    check("an empty SKU on the row is said to be empty - and not blamed",
          "The listing's SKU is empty" in silent and
          "not the reason an id is absent" in silent, silent)
    check("a row with a SKU is not told it has none",
          "SKU is empty" not in named, named)
    check("and a row that carries no SKU key at all says nothing about it",
          "SKU is empty" not in cs_edit.diagnosis_text(row={"id": "a"}), "")
    check("the reader's resolution line is in the file, quoted",
          "The reader's resolution line: Stock resolution: 2596 detail "
          "requests" in text, text[:800])
    check("and its numbers are turned into the sentence they mean",
          "vendor's data rather than a defect in the reader" in text and
          "no read of this shop produces a product id" in text, text[:900])
    check("so the file never calls that read a reader defect",
          "is a defect in the reader" not in text, text[:900])
    check("and it says what that verdict costs: these rows cannot be edited",
          "not something reading again can fix" in text and
          "vendor dashboard" in text, text[:1200])
    check("a detail response naming no product agrees with those counts",
          "same answer as the reader's own resolution line" in text,
          text[-500:])

    #  A plugin that cannot print the counts is told which one does.
    quiet = cs_edit.diagnosis_text(row=row, output="stock.list: 20 listings",
                                   plugin="1.0.38")
    check("a 1.0.38 read's missing resolution line names the version that "
          "prints one",
          "(none printed - plugin 1.0.39 prints its own resolution counts"
          in quiet, quiet[:600])
    plain = cs_edit.diagnosis_text(row=row, output="", plugin="1.0.39")
    check("and a current one just says none was printed",
          "The reader's resolution line: (none printed)" in plain and
          "prints its own" not in plain, plain[:600])

    #  ---- whether the vendor's own route can be written at all: asked, not assumed
    check("an Allow header is read into method names, in a stable order",
          cs_edit.allowed_methods("get, HEAD , patch") ==
          ["GET", "HEAD", "PATCH"], cs_edit.allowed_methods("get, HEAD , patch"))
    check("an empty header is no methods at all",
          cs_edit.allowed_methods("") == [] and
          cs_edit.allowed_methods(None) == [], "")

    class FakeResponse:
        status = 200
        headers = {"Allow": "GET, HEAD, PATCH",
                   "Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *_args):
            return b"{}"

    import urllib.request as urlreq
    seen_requests = []

    def answer(request, timeout=0):
        seen_requests.append(request)
        return FakeResponse()

    with patch.object(urlreq, "urlopen", answer):
        probe = cs_edit.fetch_options("https://cs.example/api/data/product/x",
                                      "session_token=z")
    check("the probe is an OPTIONS request - it asks, it does not write",
          seen_requests and
          seen_requests[0].get_method() == "OPTIONS",
          str([r.get_method() for r in seen_requests]))
    check("and the route's answer is kept as methods",
          probe["allow"] == ["GET", "HEAD", "PATCH"] and probe["status"] == 200,
          str(probe))

    def error_opener(status, allow=""):
        import email.message
        import urllib.error
        headers = email.message.Message()
        if allow:
            headers["Allow"] = allow
        raise urllib.error.HTTPError("u", status, "no", headers, None)

    refused = cs_edit.fetch_options("https://cs.example/x", opener=lambda *a: {
        "status": 405, "allow": [], "allow_header": "", "note": "405"})
    check("a 405 with no Allow header is inconclusive, never a refusal",
          "Inconclusive" in cs_edit.methods_note(refused) and
          "nothing was changed" in cs_edit.methods_note(refused),
          cs_edit.methods_note(refused))
    check("and an inconclusive answer licenses no write at all",
          "no write is attempted" in cs_edit.methods_note(refused) and
          "question stays open" in cs_edit.methods_note(refused),
          cs_edit.methods_note(refused))

    #  The shop's real answer: 204 on OPTIONS, no Allow header at all. Not a
    #  refusal and not permission - the one thing it must not be read as is
    #  either of those.
    real = {"status": 204, "allow": [], "allow_header": "", "note": ""}
    real_note = cs_edit.methods_note(real)
    check("a 204 with no Allow header is called inconclusive, not read-only",
          "Inconclusive" in real_note and "read-only" in real_note and
          "does not say which methods" in real_note, real_note)
    check("and it names 204 on OPTIONS as a way of saying handled",
          "204 on OPTIONS" in real_note, real_note)
    check("and it adds no write path and says the question stays open",
          "none is designed from it" in real_note and
          "question stays open" in real_note, real_note)
    writable = cs_edit.methods_note({"status": 200,
                                     "allow": ["GET", "HEAD", "PATCH"]})
    check("PATCH advertised settles the method, and says only that",
          "states it accepts PATCH" in writable and
          "settles the method, not the fields" in writable and
          "still unproven" in writable, writable)
    check("and it does not offer a no-op write as proof of the fields",
          "tolerated it" in writable and
          "can accept a request and ignore a field" in writable and
          "would confirm that" not in writable, writable)
    check("while naming what would settle them",
          "vendor's documentation" in writable and
          "reversible change" in writable and
          "timestamps included" in writable, writable)
    read_only = cs_edit.methods_note({"status": 200, "allow": ["GET", "HEAD"]})
    check("GET and HEAD alone mean read-only, and make the verdict final",
          "read-only" in read_only and "final answer" in read_only, read_only)
    check("a request that could not be made says nothing either way",
          "says nothing either way" in cs_edit.methods_note(
              {"status": 0, "allow": [], "note": "dns"}), "")
    check("and licenses no write either",
          "no write is attempted" in cs_edit.methods_note(
              {"status": 0, "allow": [], "note": "dns"}), "")

    probed = cs_edit.diagnosis_text(
        row={"id": "a", "sku": "S1"},
        detail={"url": "https://cs.example/api/data/product/a", "status": 200,
                "content_type": "application/json", "body": '{"id": "a"}'},
        probe={"status": 200, "allow": ["GET", "HEAD", "PATCH"],
               "allow_header": "GET, HEAD, PATCH", "note": ""})
    check("a diagnosis carries the probe and what it means",
          "OPTIONS https://cs.example/api/data/product/a" in probed and
          "Allow: GET, HEAD, PATCH" in probed and
          "states it accepts PATCH" in probed, probed[-700:])
    check("and says the probe itself changed nothing",
          "carries no body" in probed and "nothing was changed" in probed, "")
    check("no probe, no section",
          "whether that record can be written" not in
          cs_edit.diagnosis_text(row={"id": "a"}), "")

    check("a body that is not JSON is described instead of pasted whole",
          "not JSON" in cs_edit._body_for_diagnosis("<html>denied</html>"), "")
    check("an empty detail is not invented",
          "the detail request" not in cs_edit.diagnosis_text(row=row),
          "")
    check("a file written from a read this window made says so",
          "Where this list came from: the read this window made" in
          cs_edit.diagnosis_text(row=row, source="the read this window made"),
          "")
    thin = cs_edit.diagnosis_text(row=row)
    check("a file with no output does not claim the reader printed nothing",
          "no console output was kept for this list" in thin and
          "nothing was printed" not in thin, thin)


def test_the_readers_own_resolution_counts():
    """Plugin 1.0.39's line: did the reader ask, and what did the answers hold.

    Every round trip with this reader's author was spent on one ambiguity -
    "0 ids and no failure line" is either the lookups never running, or every
    one answering 200 without naming a product. The reader now says which, and
    the app has to use it: a read whose answers all came back empty is the
    vendor's data, not a defect in the reader, and telling the reader's author
    to fix a fault the numbers rule out is how the next round trip is wasted.
    """
    print()
    print("== 5d6. the reader's own resolution counts ==")
    line = ("Stock resolution: 2596 detail requests, 0 usable references, 2596 "
            "HTTP 200s without a usable reference, 0 ambiguous SKUs, 0 hard "
            "failures")
    counts = cs_edit.resolution_counts(line)
    check("the five numbers are read from the reader's own line",
          counts == {"requested": 2596, "usable": 0, "empty": 2596,
                     "ambiguous": 0, "failed": 0}, str(counts))
    check("the line itself is quoted, not rebuilt",
          cs_edit.resolution_line("Stock read: ok\n" + line) == line, "")
    check("a read with only the count line has no resolution line",
          cs_edit.resolution_counts("stock.list: 3 listings, 0 with a real "
                                    "product id") is None and
          cs_edit.resolution_line("nothing") == "", "")
    check("a one-listing read's singulars are read too",
          cs_edit.resolution_counts(
              "Stock resolution: 1 detail request, 1 usable reference, 0 HTTP "
              "200s without a usable reference, 0 ambiguous SKUs, 0 hard "
              "failures") == {"requested": 1, "usable": 1, "empty": 0,
                              "ambiguous": 0, "failed": 0}, "")

    vendor = cs_edit.resolution_note(counts)
    check("all answers 200 and none naming a product is called the vendor's "
          "data",
          "vendor's data" in vendor and "defect in the reader" in vendor,
          vendor)
    check("and it says no read of this shop will produce an id",
          "no read of this shop produces a product id" in vendor, vendor)
    partial = cs_edit.resolution_note({
        "requested": 6, "usable": 4, "empty": 1, "ambiguous": 1, "failed": 0})
    check("a mixed read says how many became ids, and names the ambiguous one",
          "turned 4 into usable product ids" in partial and
          "1 listing was left without an id" in partial, partial)
    none_asked = cs_edit.resolution_note({
        "requested": 0, "usable": 0, "empty": 0, "ambiguous": 0, "failed": 0})
    check("a read that asked for nothing says so",
          "made no detail lookups at all" in none_asked, none_asked)
    failed = cs_edit.resolution_note({
        "requested": 2, "usable": 0, "empty": 0, "ambiguous": 0, "failed": 2})
    check("hard failures alone are named as failures",
          "2 detail requests failed outright" in failed, failed)
    check("no line, no sentence",
          cs_edit.resolution_note(None) == "", "")

    #  ---- the version sentence must not contradict the reader's numbers
    old_verdict = cs_edit.needed_version_note("1.0.34", "1.0.34")
    check("without the counts, a current plugin is still pointed at a defect",
          "defect in the reader" in old_verdict, old_verdict)
    quiet = cs_edit.needed_version_note("1.0.34", "1.0.34", site_silent=True)
    check("with the counts, the reader is not accused of a defect",
          "defect in the reader" not in quiet and
          "lookups ran" in quiet and "not the reader failing to try" in quiet,
          quiet)
    hint = cs_edit.needed_version_note("1.0.38", "1.0.34")
    check("a plugin that cannot print the counts is told 1.0.39 does",
          "1.0.39 prints the reader's own resolution counts" in hint, hint)
    check("and one that can print them is not told to update",
          "1.0.39 prints" not in cs_edit.needed_version_note("1.0.39",
                                                            "1.0.34"), "")

    #  ---- the whole sentence, on the read that started all of this
    rows = [{"id": "a%04d" % n, "sku": "", "title": "card %d" % n}
            for n in range(20)]
    output = ("stock.list: 20 listings, 0 with a real product id, 20 without "
              "the key, 0 reported as 0\nStock resolution: 20 detail "
              "requests, 0 usable references, 20 HTTP 200s without a usable "
              "reference, 0 ambiguous SKUs, 0 hard failures")
    gap = cs_edit.product_id_gap(rows, plugin="1.0.39", needed="1.0.34",
                                 reader_text=output, stages=["read", "ids"])
    check("the gap sentence quotes the reader's resolution and calls it the "
          "site",
          "vendor's data" in gap and "no read of this shop" in gap, gap)
    check("and no longer calls a read with those counts a reader defect",
          "is a defect in the reader" not in gap and
          "that is what to send with a report" not in gap, gap)
    check("while keeping what still works last",
          gap.index("still work") > gap.index("vendor's data"), gap)
    check("and the phases are not said twice over the resolution line",
          "so the lookups ran." in gap and
          "the ids it sent back were not usable" not in gap, gap)
    check("and it says plainly that reading again cannot fix these rows",
          "not something reading again can fix" in gap and
          "vendor dashboard" in gap and
          "stock.set names the listing itself" in gap, gap)
    check("while not claiming the stock write is known to work here",
          "writes those to the listing itself" not in gap, gap)

    #  The plugin's author confirmed the updater will not resolve a listing
    #  without a product reference, so the sentence must not exist for a read
    #  whose counts do not say the site is silent.
    failed_only = cs_edit.product_id_gap(
        rows, plugin="1.0.39", needed="1.0.34",
        reader_text=("stock.list: 20 listings, 0 with a real product id, 20 "
                     "without the key, 0 reported as 0\nStock resolution: 20 "
                     "detail requests, 0 usable references, 0 HTTP 200s "
                     "without a usable reference, 0 ambiguous SKUs, 20 hard "
                     "failures"))
    check("a read whose lookups failed is not told its records are silent",
          "vendor's data" not in failed_only and
          "not something reading again can fix" not in failed_only,
          failed_only)
    check("and its failures are named as the reason, with reading again "
          "offered",
          "20 detail requests failed outright" in failed_only and
          "those failed lookups are why the ids are missing" in failed_only and
          "reading again may resolve them" in failed_only.lower(), failed_only)

    #  "hard failures" and "lookups failed" are two lines and must not be read
    #  as each other: the second is the reader's older failure count.
    check("the older failure line is still read, and a resolution line is not "
          "mistaken for it",
          stock_compare.failed_lookups("Stock read: 2 listings, 0 with a real "
                                       "product id, 2 lookups failed") == 2 and
          stock_compare.failed_lookups(line) == 0, "")


def test_the_real_diagnosis_from_the_shop():
    """The 1.0.39 file this shop produced, and what it exposed in the app.

    Two things were wrong with the app's own file and one with its wording:
    250 ``ALEX_COLLECT_PROGRESS:`` lines buried the three lines that matter,
    eight failed lookups were folded into "the site names nothing" as though
    their records had been read, and two keys that merely mention a product
    (both null) were listed as though they were a lead. All three are fixed
    here, against the exact counts and record the shop sent.
    """
    print()
    print("== 5d7. the shop's real 1.0.39 diagnosis ==")
    markers = "\n".join(
        'ALEX_COLLECT_PROGRESS:{"stage": "ids", "index": %d, "total": 2596}'
        % n for n in range(1, 251))
    output = (markers + "\nstock.list: 2596 listings, 0 with a real product "
              "id, 2596 without the key, 0 reported as 0\n"
              "stock     : 2596 listing(s) written to cs-stock.json\n"
              "Stock resolution: 2596 detail requests, 0 usable references, "
              "2588 HTTP 200s without a usable reference, 0 ambiguous SKUs, "
              "8 hard failures\n"
              "Stock read: 2596 listings, 0 with a real product id, 8 lookups "
              "failed")

    spoken, omitted = cs_edit.without_progress(output)
    check("the progress channel is cut out of what a person reads",
          omitted == 250 and "ALEX_COLLECT_PROGRESS" not in spoken, str(omitted))
    check("and every line the reader actually said is kept, and nothing else",
          spoken.splitlines() == [
              "stock.list: 2596 listings, 0 with a real product id, 2596 "
              "without the key, 0 reported as 0",
              "stock     : 2596 listing(s) written to cs-stock.json",
              "Stock resolution: 2596 detail requests, 0 usable references, "
              "2588 HTTP 200s without a usable reference, 0 ambiguous SKUs, "
              "8 hard failures",
              "Stock read: 2596 listings, 0 with a real product id, 8 lookups "
              "failed"], spoken)

    #  The record the shop's own site returned, key and all - 38 keys, and
    #  every one of them about the listing rather than about a product.
    record = {"id": "a2304e72dbca4e678e7111d011ade22d",
              "createdAt": "2026-10-15T16:42:16Z",
              "updatedAt": "2026-10-16T11:16:38.234Z",
              "vendor": "fc5c0fd1fb80c161b529b0bb287dfd30",
              "title": "#006/196 Wurmple SWSH11", "slug": "006-196-wurmple",
              "description": "SWSH11: Lost Origin #006/196 Wurmple",
              "primaryImageUrl": "https://cs/api/file/006.jpg",
              "priceCad": 1, "inventory": 1, "status": "active",
              "category": "f78bf500fcdc7507e4d32b8cb5b2b698",
              "shipFromProvince": "ON", "shippingFlatCad": 4,
              "freeShipping": False, "handlingDays": 2, "transitDays": 5,
              "isFeatured": False, "featuredOrder": None, "isFlagged": False,
              "titleFr": "Chenipotte", "descriptionFr": "Origine Perdue",
              "rating2Count": None, "rating3Count": None, "totalReviews": None,
              "rating5Count": None, "averageRating": None, "rating4Count": None,
              "rating1Count": None, "isDemoProduct": None, "availableSizes": [],
              "availableColors": [], "canadianOriginConfirmed": False,
              "isMadeToOrder": False, "localPickup": False,
              "productOptions": None, "shippingSettings": None, "tags": None}
    row = {"name": "#006/196 Wurmple SWSH11", "sku": "", "qty": 1,
           "id": "a2304e72dbca4e678e7111d011ade22d", "status": "active",
           "price": "1.00", "images": ["https://cs/api/file/006.jpg"]}
    text = cs_edit.diagnosis_text(
        row=row, output=output, stages=["read", "ids"], plugin="1.0.39",
        command="pythonw.exe -u cs-stock.py --stock-out cs-stock.json "
                "--cookie-file cookie.txt",
        detail={"url": cs_edit.detail_url(row["id"]), "status": 200,
                "content_type": "application/json", "body": json.dumps(record)},
        total=2596, editable=0, app_version="3.30",
        source="the read this window made at 2026-11-02 13:03:59")

    check("the file no longer carries the progress markers",
          "ALEX_COLLECT_PROGRESS" not in text, "")
    check("but says how many lines it left out, and why",
          "250 progress-marker line(s) omitted" in text and
          "not the reader's words" in text, "")
    check("the reader's own lines survive intact",
          "stock.list: 2596 listings" in text and
          "Stock resolution: 2596 detail requests" in text and
          "Stock read: 2596 listings, 0 with a real product id, 8 lookups "
          "failed" in text, "")
    check("the eight failed lookups are told apart from the silent answers",
          "8 failed lookups are a separate matter" in text and
          "a later read may still resolve them" in text, text[:2000])
    check("and the consequence carves them out rather than giving up on them",
          "8 listings are not covered by that" in text and
          "read once more before giving up on them" in text, text[:2000])
    check("the two product-ish keys are named but not offered as a lead",
          "isDemoProduct (empty)" in text and
          "none of them holds an id" in text, text[-900:])
    check("and the reader's side is called settled, without settling editing",
          "settles the reader's side" in text and
          "nothing more to report about the resolver" in text and
          "depends on the check below" in text, text[-1400:])
    check("and the one question the file cannot answer is put to the vendor",
          "the fields an edit changes" in text and
          "/api/products/<product_id>/" in text and
          "before the shop is written off as uneditable" in text,
          text[-1400:])
    check("the editable fields are named in the vendor's own spelling",
          cs_edit.editable_shape(record) ==
          ["title", "priceCad", "inventory", "status", "description",
           "primaryImageUrl", "category"], str(cs_edit.editable_shape(record)))
    check("a record with none of them raises no such question",
          "fields an edit changes" not in cs_edit.diagnosis_text(
              row={"id": "a"},
              detail={"url": "u", "status": 200, "body": '{"id": "a"}'}), "")
    check("nothing is called a reader defect anywhere in that file",
          "defect in the reader" not in text.replace(
              "rather than a defect in the reader", ""), "")


def test_plugin_1_0_35():
    """2,587 listings, every one with a string product id, resolved by the reader.

    1.0.35 resolves a missing id through each listing's own detail, using the
    same SKU matching stock.set does, and emits it as a string. Two things
    follow for the core: an id is an id whether it arrives as "4321", 4321 or
    4321.0 - otherwise a write that happened reads as *unknown* - and two
    listings can now resolve to one product, which no count of edits shows.
    """
    print()
    print("== 5d4. plugin 1.0.35: string ids, and one product two listings share ==")
    rows = [{"id": "a%04d" % n, "product_id": str(40000 + n),
             "sku": "OPC73-%d" % n, "inventory": 1, "status": "active",
             "price": "8.50", "url": "https://canadianshopper.ca/l/%d" % n,
             "title": "1973-74 O-Pee-Chee Card #%d" % n} for n in range(2587)]
    items_ = stock_compare.plugin_items({"items": rows})
    editable, total = cs_edit.product_id_counts(items_)
    check("every one of the 2587 is editable",
          (editable, total) == (2587, 2587), "%s %s" % (editable, total))
    check("nothing is said against a read that is complete",
          cs_edit.product_id_gap(items_, plugin="1.0.35") == "" and
          cs_edit.zero_product_id_counts(items_) == (0, 2587) and
          not cs_edit.shared_product_ids(items_), "")
    plan = cs_edit.plan(items_[7], inventory=4)
    check("the string id the reader sent is the id the write carries",
          plan.get("product_id") == "40007", str(plan))
    check("and it is not renumbered on the way",
          isinstance(plan.get("product_id"), str), repr(plan.get("product_id")))

    #  ---- one id, spelled four ways
    check("a string id, a number id, a padded one and a float are one id",
          {stock_compare.id_key("4321"), stock_compare.id_key(4321),
           stock_compare.id_key(" 4321 "), stock_compare.id_key(4321.0),
           stock_compare.id_key("4321.00")} == {"4321"}, "")
    check("an opaque id is kept exactly as it was given",
          stock_compare.id_key("14effcaceb8a4b66") == "14effcaceb8a4b66" and
          stock_compare.id_key("14EFFCACEb8a4b66") == "14EFFCACEb8a4b66", "")
    check("a leading zero is somebody's code, not twelve",
          stock_compare.id_key("0012") == "0012", "")
    check("nothing at all is the empty string",
          stock_compare.id_key(None) == "" and stock_compare.id_key("") == ""
          and stock_compare.id_key(True) == "", "")

    plan_row = {"id": "a1", "product_id": "4321", "sku": "OPC73-1",
                "title": "1973-74 O-Pee-Chee Card #1"}

    def outcome(answer):
        result = stock_compare.plugin_write_report([plan_row], answer)
        return ("changed" if result["changed"] else
                "failed" if result["failed"] else "unknown")

    check("an answer naming the id as a number confirms the write",
          outcome({"updated": [{"product_id": 4321}]}) == "changed", "")
    check("an answer naming it as a string confirms it too",
          outcome({"updated": [{"product_id": "4321"}]}) == "changed", "")
    check("an answer naming the listing id still confirms it",
          outcome({"updated": [{"id": "a1"}]}) == "changed", "")
    check("and another product's id does not",
          outcome({"updated": [{"product_id": 4322}]}) == "unknown", "")

    #  ---- two listings on one product
    shared = [dict(row) for row in rows[:3]]
    shared[1]["product_id"] = shared[0]["product_id"]
    shared_items = stock_compare.plugin_items({"items": shared})
    found = cs_edit.shared_product_ids(shared_items)
    check("two listings resolving to one product are found",
          len(found) == 1 and found[0][0] == "40000" and
          len(found[0][1]) == 2, str(found))
    note = cs_edit.shared_product_note(shared_items)
    check("and named, with both listings",
          "product 40000" in note and "Card #0" in note and "Card #1" in note,
          note)
    check("with what it means for a write",
          "changes what every listing sharing it shows" in note, note)
    check("a read where every id is its own has nothing to say",
          cs_edit.shared_product_note(items_) == "", "")

    #  ---- the panel, with 1.0.35's read
    folder = Path(tempfile.mkdtemp())
    harness.install_plugin("1.0.35", folder / "plugin")
    gui.BASE = folder
    app = harness.FakeApp(folder)
    parent = harness.FakeWidget()
    gui.build_csledit(parent, app)
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app, folder, parent, rows)
    said = str(app.lines[-1][1])
    check("the panel says every listing can be edited, with nothing against it",
          "every one with a product id" in said and "defect" not in said,
          said)
    check("no shared-id warning on a clean read",
          not any("claimed by more than one listing" in text
                  for _tag, text in app.lines), str(app.lines[-3:]))

    folder2 = Path(tempfile.mkdtemp())
    harness.install_plugin("1.0.35", folder2 / "plugin")
    gui.BASE = folder2
    app2 = harness.FakeApp(folder2)
    parent2 = harness.FakeWidget()
    gui.build_csledit(parent2, app2)
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app2, folder2, parent2, shared)
    check("the panel warns when two listings share a product",
          any("claimed by more than one listing" in text
              for _tag, text in app2.lines), str(app2.lines[-3:]))
    check("and still lists both",
          len(listing_box(parent2).items) == 3,
          str(len(listing_box(parent2).items)))


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


def test_the_editing_panel_says_what_stopped_a_read():
    print()
    print("== 5g. a read that stopped, and one that lost a lookup ==")
    folder, app, parent = build_panel()

    def said(prefix):
        return [text for _tag, text in app.lines if prefix in text]

    #  The reader stopped on ONE listing's own detail lookup. The panel used to
    #  say only that the read failed, which tells nobody what to do about it.
    run = None
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "plugin_version", lambda *a, **k: "1.0.35"):
        find(parent, gui.ttk.Button,
             "Read CanadianShopper's listings").invoke()
        run = app.runs[-1]
        app.runner = SimpleNamespace(
            output="! Could not list CanadianShopper stock: CanadianShopper "
                   "request failed (GET /api/data/product/94b93f6040f5401daa"
                   "baa9c936efa5a7): URLError")
        run["on_done"](1)
    check("the panel names the listing lookup that stopped the read",
          said("ONE listing's own detail lookup"), str(app.lines[-5:]))
    check("and names the plugin version that carries on past it",
          said("updating the plugin is the fix"), str(app.lines[-5:]))
    check("and does not blame the cookie",
          not any("bytes" in text and "saved" in text
                  for _tag, text in app.lines), str(app.lines[-5:]))

    #  A read that finished after losing some lookups: those rows are real but
    #  this panel cannot edit them, which is worth saying before it is tried.
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        app.runs.clear()
        app.lines[:] = []
        find(parent, gui.ttk.Button,
             "Read CanadianShopper's listings").invoke()
        run = app.runs[-1]
        Path(run["args"][1]).write_text(
            json.dumps({"items": LISTINGS}), encoding="utf-8")
        app.runner = SimpleNamespace(
            output="Stock read: %d listings, %d with a real product id, "
                   "1 lookup failed" % (len(LISTINGS), len(LISTINGS) - 1))
        run["on_done"](0)
    check("a read that lost a lookup says which rows cannot be edited here",
          said("cannot be edited here"), str(app.lines[-5:]))
    check("and says how many, and that reading again may fix it",
          said("1 listing was left without a product id") and
          said("reading again may resolve it"), str(app.lines[-5:]))
    check("while the rest of the list is still there to edit",
          len(listing_box(parent).items) == len(LISTINGS),
          str(len(listing_box(parent).items)))

    #  A read the person stopped is not a reader failure there either, and the
    #  plugin's age is worth saying before the wait rather than after it.
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "plugin_version", lambda *a, **k: "1.0.35"):
        app.lines[:] = []
        find(parent, gui.ttk.Button,
             "Read CanadianShopper's listings").invoke()
        run = app.runs[-1]
        check("before a long read with an older plugin, it says so first",
              said("or newer carries on past it"), str(app.lines[:4]))
        app.runner = SimpleNamespace(output="", stopped=True)
        run["on_done"](1)
    check("a stopped read is said to be stopped, not failed",
          said("was stopped") and not said("read failed"), str(app.lines[-4:]))
    check("and nobody is told the reader said nothing it recognises",
          not said("recognises"), str(app.lines[-5:]))
    check("and a list that was already on screen is still there",
          len(listing_box(parent).items) == len(LISTINGS),
          str(len(listing_box(parent).items)))

    #  A reader that dies without a word: said plainly, with the version.
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "plugin_version", lambda *a, **k: "1.0.36"):
        app.lines[:] = []
        find(parent, gui.ttk.Button,
             "Read CanadianShopper's listings").invoke()
        check("a plugin new enough warns about nothing before a read",
              not said("carries on past it"), str(app.lines[:3]))
        run = app.runs[-1]
        app.runner = SimpleNamespace(output="")
        run["on_done"](1)
    check("a silent death is named as one", said("without printing a single line"),
          str(app.lines[-5:]))
    check("and a 1.0.36 read is not told to update anything",
          not said("1.0.36 or newer"), str(app.lines[-5:]))


def test_the_panel_writes_a_diagnosis():
    """The button: one file, from the read that is on screen.

    The person who has just been asked for evidence should not have to copy a
    console by hand - the panel already has the run's output, its phases and a
    row, and can read the one detail response the reader's lookup would read.
    """
    print()
    print("== 5h. the diagnosis button writes one file ==")
    folder, app, parent = build_panel()
    cookie = folder / "cookie.txt"
    cookie.write_text("session_token=secret-value\n", encoding="utf-8")

    def sync_background(app_, work, done):
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        return done(result, error)

    zeroed = [{"id": "94b93f6040f5401daabaa9c936efa5a7", "product_id": 0,
               "sku": "OPC1973-74-112", "title": "Jim Pappin #112",
               "status": "active", "inventory": 1}]
    output = ("stock.list: 1 listing, 0 with a real product id, 1 without the "
              "key, 0 reported as 0")
    asked = []

    def fake_detail(url, cookie_text="", **kwargs):
        asked.append(url)
        return (200, "application/json", json.dumps({"product": {"id": "9"}}))

    def fake_options(url, cookie_text="", **kwargs):
        return {"status": 200, "allow": ["GET", "HEAD", "PATCH"],
                "allow_header": "GET, HEAD, PATCH", "note": ""}

    harness._BOX.shown[:] = []
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "open_path", lambda path: True), \
            patch.object(cs_edit, "fetch_detail", fake_detail), \
            patch.object(cs_edit, "fetch_options", fake_options):
        app.stages_seen = lambda: ["read", "ids"]
        app.runner = SimpleNamespace(output=output, cmd="cs-stock.py --stock-out x")
        find(parent, gui.ttk.Button,
             "Read CanadianShopper's listings").invoke()
        run = app.runs[-1]
        Path(run["args"][1]).write_text(json.dumps({"items": zeroed}),
                                        encoding="utf-8")
        run["on_done"](0)
        app.lines[:] = []
        find(parent, gui.ttk.Button,
             "Save a read diagnosis...").invoke()

    written = sorted(folder.glob("cs-read-diagnosis-*.txt"))
    check("pressing it writes exactly one file, in the app's folder",
          len(written) == 1, str(written))
    text = written[0].read_text(encoding="utf-8") if written else ""
    check("with the read's output, the phases and the listing's row in it",
          output in text and "read, ids" in text and
          "94b93f6040f5401daabaa9c936efa5a7" in text, text[:400])
    check("and the detail request for the listing that was on screen",
          asked == ["https://canadianshopper.ca/api/data/product/"
                    "94b93f6040f5401daabaa9c936efa5a7"], str(asked))
    check("the cookie is used but never written into the file",
          "secret-value" not in text, text[:400])
    check("the console says where it went, and that it is safe to send",
          any("Diagnosis written" in line and "no cookie" in line
              for _tag, line in app.lines), str(app.lines[-6:]))
    check("the file answers whether the vendor's record can be written",
          "Allow: GET, HEAD, PATCH" in text and
          "states it accepts PATCH" in text and
          "nothing was changed" in text, text[-800:])
    check("and the console says what the route allows, read-only",
          any("the vendor's own route for that listing accepts: GET, HEAD, "
              "PATCH" in line for _tag, line in app.lines),
          str(app.lines[-4:]))

    #  A second press is a second piece of evidence: the same read diagnosed
    #  later, or after a change - so the first file stays where it is.
    with patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "open_path", lambda path: True), \
            patch.object(cs_edit, "fetch_detail", fake_detail), \
            patch.object(cs_edit, "fetch_options", fake_options):
        find(parent, gui.ttk.Button, "Save a read diagnosis...").invoke()
    again = sorted(folder.glob("cs-read-diagnosis-*.txt"))
    check("pressing it again keeps both files instead of replacing the first",
          len(again) == 2 and again[-1].read_text(encoding="utf-8"), str(again))

    #  Nothing read yet: a file made of nothing would be worse than a word.
    folder2, app2, parent2 = build_panel()
    harness._BOX.shown[:] = []
    find(parent2, gui.ttk.Button, "Save a read diagnosis...").invoke()
    check("with nothing read, it asks for a read instead of writing",
          harness._BOX.shown and
          "Read CanadianShopper's listings first" in
          str(harness._BOX.shown[0][1]), str(harness._BOX.shown))
    check("and writes no file at all",
          not list(folder2.glob("cs-read-diagnosis-*.txt")), "")


def test_the_panel_writes_a_proof():
    """The proof button: one field on the listing on screen, put back.

    The same rule as the diagnosis button - the person who has just been asked
    "does the site honour this field" should not have to build the request by
    hand - but this one *writes*, so what it writes has to be one field, on one
    listing, addressed by the record's own id, and put back; and what it says
    afterwards must never call a field proven when the record did not keep it.
    """
    print()
    print("== 5i. the proof button writes one field and puts it back ==")
    folder, app, parent = build_panel()
    cookie = folder / "cookie.txt"
    cookie.write_text("session_token=secret-value\n", encoding="utf-8")

    def sync_background(app_, work, done):
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        return done(result, error)

    rows = [{"id": "94b93f6040f5401daabaa9c936efa5a7", "product_id": 0,
             "sku": "OPC1973-74-112", "title": "Jim Pappin #112",
             "status": "active", "inventory": 1, "price": "12.50",
             #  The gallery the reader reports, as the plugin uploads it: the
             #  first is the photo the listing shows now.
             "images": ["https://cs.example/api/file/current.webp",
                        "https://cs.example/api/file/other-back.webp"]}]
    asked, questions = [], []

    def fake_prove(field, url, cookie="", staged_url="", listing=None,
                   **kwargs):
        asked.append({"field": field, "url": url, "staged": staged_url,
                      "listing": dict(listing or {})})
        return {"field": field, "label": cs_proof.field_label(field),
                "verdict": "written", "written": True, "restored": True,
                "old": 12.5, "trial": "12.51", "restore": 12.5,
                "after": "12.51", "final": 12.5, "status": 200,
                "restore_status": 200, "url": url,
                "why": "The site accepted the price and the record shows it.",
                "steps": [{"step": "GET the record", "status": 200}],
                "at": "2026-11-02 09:00:00"}

    def yes(title, question, **kwargs):
        questions.append((title, question))
        return True

    harness._BOX.shown[:] = []
    harness._BOX.askyesno = yes
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "open_path", lambda path: True), \
            patch.object(cs_proof, "prove", fake_prove):
        find(parent, gui.ttk.Button,
             "Read CanadianShopper's listings").invoke()
        run = app.runs[-1]
        Path(run["args"][1]).write_text(json.dumps({"items": rows}),
                                       encoding="utf-8")
        run["on_done"](0)
        listing_box = next(widget for widget in parent.walk()
                           if isinstance(widget, gui.tk.Listbox))
        listing_box.selection_set(0)
        app.lines[:] = []
        find(parent, gui.ttk.Button, "Write the proof").invoke()

    check("the field chooser offers every field a proof can settle",
          any(set(cs_proof.labels()) <= set(widget.cget("values") or ())
              for widget in parent.walk()
              if isinstance(widget, gui.ttk.Combobox)),
          str([widget.cget("values") for widget in parent.walk()
               if isinstance(widget, gui.ttk.Combobox)]))
    check("pressing it writes exactly one field on the listing on screen",
          len(asked) == 1 and asked[0]["field"] == "priceCad",
          str(asked))
    check("and addresses the record's own id, never a product id",
          asked[0]["url"] == "https://canadianshopper.ca/api/data/product/"
          "94b93f6040f5401daabaa9c936efa5a7" and
          "product_id" not in asked[0]["url"], str(asked[0]["url"]))
    check("the question says it is a real change and what is not touched",
          questions and "record's own id" in questions[0][1] and
          "No product id is used" in questions[0][1] and
          "website is not touched" in questions[0][1], str(questions))

    proof_files = sorted(folder.glob("cs-proof-*.txt"))
    check("a proof file is written beside the app", len(proof_files) == 1,
          str(proof_files))
    text = proof_files[0].read_text(encoding="utf-8") if proof_files else ""
    check("with the listing, the field and the record's address in it",
          "94b93f6040f5401daabaa9c936efa5a7" in text and
          "Price (priceCad)" in text and
          "/api/data/product/94b93f6040f5401daabaa9c936efa5a7" in text,
          text[:400])
    check("the cookie is used but never written into it",
          "secret-value" not in text, text[:400])
    check("what is settled is said out loud on the console",
          any("is settled" in line for _tag, line in app.lines),
          str(app.lines[-6:]))
    check("and the console says where the proof went",
          any("Proof saved" in line for _tag, line in app.lines),
          str(app.lines[-6:]))
    saved = cs_proof.load_proofs(folder)
    check("the field is remembered as proven",
          cs_proof.settled("priceCad", saved), str(saved))

    #  The main photo is proven with a photo of the same card, and the squared
    #  photos on the site were uploaded by the plugin - so the proof offers the
    #  ones the app can point at (the staging step's upload, the listing's own
    #  gallery) and lets the person pick, instead of asking them to paste an
    #  address into a box where the wrong card's URL would be accepted.
    proof_box = next(widget for widget in parent.walk()
                     if isinstance(widget, gui.ttk.Combobox) and
                     "Main photo" in (widget.cget("values") or ()))
    opened = {}

    def fake_askstring(title, question, **kwargs):
        opened.update(dict(kwargs, title=title, question=question))
        return kwargs.get("initialvalue") or ""

    def press_photo(url, button="Use this photo"):
        """Pick a photo in the chooser, the way a person does.

        The chooser is a list, not a column of radio buttons - a batch can hold
        hundreds of staged photos - so the row whose address ends with ``url``
        is clicked, then the button is pressed.
        """
        def press(window):
            for widget in window.walk():
                if not isinstance(widget, gui.tk.Listbox):
                    continue
                for index, text in enumerate(widget.items):
                    if str(text).rstrip().endswith(url):
                        widget.selection_set(index)
                        break
            target = next((w for w in window.walk()
                           if isinstance(w, gui.ttk.Button) and
                           str(w.cget("text")) == button), None)
            if target is not None:
                target.invoke()
        return press

    record_body = json.dumps({
        "id": rows[0]["id"],
        "primaryImageUrl": "https://cs.example/api/file/current.webp",
        "images": ["https://cs.example/api/file/current.webp",
                   "https://cs.example/api/file/gallery.webp"]})

    def with_photo_proof(lookup=None, ask=fake_askstring, press=None,
                         record=record_body, alive=True):
        harness.PICKER["press"] = press or (lambda window: None)
        staged_lookup = lookup if callable(lookup) else \
            (lambda folder, title, extra_folders=(): lookup or "")
        try:
            with patch.object(gui, "TOOL_ACTION",
                              lambda action: "/plugins/cs/stock.py"), \
                    patch.object(gui, "CS_COOKIE_FILE", cookie), \
                    patch.object(gui, "in_background", sync_background), \
                    patch.object(gui, "open_path", lambda path: True), \
                    patch.object(gui, "simpledialog") as dialog, \
                    patch.object(cs_proof, "staged_photo", staged_lookup), \
                    patch.object(cs_proof, "read_record",
                                 lambda url, cookie="": (200, record)), \
                    patch.object(cs_proof, "photo_alive",
                                 lambda url, **k: (alive, "image/webp")), \
                    patch.object(cs_proof, "prove", fake_prove):
                dialog.askstring = ask
                find(parent, gui.ttk.Button, "Write the proof").invoke()
        finally:
            harness.PICKER["press"] = lambda window: None

    proof_box._kw["textvariable"].set("Main photo")
    with_photo_proof(None, press=press_photo(
        "https://cs.example/api/file/other-back.webp"))
    check("with no staged photo the gallery is still offered, and writable",
          asked and asked[-1]["staged"] ==
          "https://cs.example/api/file/other-back.webp", str(asked[-1:]))

    #  No staged photo and no gallery at all: the box is the only way in, and
    #  it says which step would have filled the list.
    folder3, app3, parent3 = build_panel()
    bare = [{"id": "b" * 32, "title": "Bare card", "status": "active",
             "inventory": 1, "price": "1.00"}]
    bare_asked, bare_opened = [], []
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder3):
        read_into(app3, folder3, parent3, bare)
    select(parent3, "Bare")

    def bare_ask(title, question, **kwargs):
        bare_opened.append(dict(kwargs, title=title, question=question))
        return ""

    bare_box = next(widget for widget in parent3.walk()
                    if isinstance(widget, gui.ttk.Combobox) and
                    "Main photo" in (widget.cget("values") or ()))
    harness.PICKER["press"] = lambda window: None
    bare_record = json.dumps({"id": "b" * 32,
                              "primaryImageUrl": "",
                              "title": "Bare card"})
    with patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder3), \
            patch.object(gui, "simpledialog") as dialog, \
            patch.object(cs_proof, "staged_photo",
                         lambda folder, title, extra_folders=(): ""), \
            patch.object(cs_proof, "read_record",
                         lambda url, cookie="": (200, bare_record)), \
            patch.object(cs_proof, "photo_alive",
                         lambda url, **k: (False, "")), \
            patch.object(cs_proof, "prove",
                         lambda *a, **k: bare_asked.append((a, k))):
        dialog.askstring = bare_ask
        bare_box._kw["textvariable"].set("Main photo")
        find(parent3, gui.ttk.Button, "Write the proof").invoke()
    check("with no photo to offer, the proof asks for the address",
          bare_opened and "run the image staging step" in
          bare_opened[0].get("question", ""),
          str(bare_opened[:1]))
    check("and an empty box writes nothing at all", not bare_asked, "")
    check("the console says which folders held no staged CSV",
          any("No staged CSV was found. Searched:" in text
              for _tag, text in app3.lines), str(app3.lines[:6]))

    #  One staged photo, and the row's own gallery beside it.
    asked[:] = []
    opened.clear()
    questions[:] = []
    with_photo_proof("https://cs.example/api/file/staged.webp",
                     press=press_photo(
                         "https://cs.example/api/file/staged.webp"))
    check("the chooser opens on the staged photo, and it is offered first",
          not opened and asked and asked[-1]["field"] == "primaryImageUrl",
          str(asked[-1:]))
    check("and the staged address is the one written",
          asked and asked[-1]["staged"] ==
          "https://cs.example/api/file/staged.webp", str(asked[-1:]))
    check("the confirmation names the photo, not only the field",
          questions and "The photo written" in questions[0][1] and
          "staged.webp" in questions[0][1], str(questions[:1]))

    #  Choosing one of the listing's own photos instead: the plugin uploaded
    #  those, so they are the same card and just as safe.
    asked[:] = []
    with_photo_proof("https://cs.example/api/file/staged.webp",
                     press=press_photo(
                         "https://cs.example/api/file/other-back.webp"))
    check("a photo the listing already shows can be chosen instead",
          asked and asked[-1]["staged"] ==
          "https://cs.example/api/file/other-back.webp", str(asked[-1:]))

    #  Cancelling the chooser is an answer: nothing is written, and it says so.
    asked[:] = []
    app.lines[:] = []
    with_photo_proof("https://cs.example/api/file/staged.webp",
                     press=lambda window: find(
                         window, gui.ttk.Button, "Cancel").invoke())
    check("closing the chooser writes no proof",
          not asked and any("photo question was closed" in text
                            for _tag, text in app.lines), str(app.lines[-2:]))

    #  The report that started this: the site's title and the batch CSV's are
    #  not the same words, so the exact-title lookup finds nothing and the
    #  person was left with a paste box. The batch's own staged rows are
    #  offered instead, best title match first, each with the title it was
    #  staged under - and the right one can be clicked.
    asked[:] = []
    app.lines[:] = []
    import csv as _csv
    batch = folder / "canadianshopper_products" / "cs-ready"
    batch.mkdir(parents=True, exist_ok=True)
    with (batch / "canadianshopper_import_20260301_01_of_01.csv").open(
            "w", newline="", encoding="utf-8") as handle:
        writer = _csv.DictWriter(handle, ["title", "image_url"])
        writer.writeheader()
        writer.writerow({"title": "1973-74 O-Pee-Chee Jim Pappin #112 EX-MT",
                         "image_url": "/api/file/pappin.webp"})
        writer.writerow({"title": "1966-67 Topps Bobby Orr #35",
                         "image_url": "/api/file/orr.webp"})
    with_photo_proof(None, press=press_photo(
        "https://canadianshopper.ca/api/file/pappin.webp"))
    check("a staged row whose title is not the same words is still offered",
          any("pappin.webp" in text for _tag, text in app.lines),
          str(app.lines[-6:]))
    check("and clicking it writes that photo",
          asked and asked[-1]["staged"] ==
          "https://canadianshopper.ca/api/file/pappin.webp", str(asked[-1:]))

    #  The list is ranked by the title it was staged under, so the card's own
    #  row is the one already selected.
    picked = {}
    with_photo_proof(None, press=lambda window: picked.update(
        {"rows": next((w.items for w in window.walk()
                       if isinstance(w, gui.tk.Listbox)), [])}) or find(
        window, gui.ttk.Button, "Cancel").invoke())
    check("the list says which title each photo was staged for",
          picked.get("rows") and "Jim Pappin #112 EX-MT" in picked["rows"][0],
          str(picked.get("rows")))

    #  An empty address box is a different answer from a closed question, and
    #  the console says which one happened.
    app.lines[:] = []
    bare_asked[:] = []
    with_photo_proof(None, ask=lambda *a, **k: None,
                     press=lambda window: find(
                         window, gui.ttk.Button, "Cancel").invoke())
    check("a closed chooser and an empty box read differently",
          any("photo question was closed" in text
              for _tag, text in app.lines) and
          not any("address box was left empty" in text
                  for _tag, text in app.lines), str(app.lines[-3:]))

    #  The report: no staged CSV anywhere, and a record that carries one photo
    #  - the squared one the plugin uploaded, whose name pairs it with the
    #  card's back. That sibling is the same card and already on the site, so
    #  it is offered without a single local file, and only because the site
    #  answered with an image.
    asked[:] = []
    app.lines[:] = []
    front_only = json.dumps({
        "id": rows[0]["id"],
        "primaryImageUrl": "https://canadianshopper.ca/api/file/pappin-front.webp",
        "title": rows[0]["title"]})
    with_photo_proof(None, record=front_only, press=press_photo(
        "https://canadianshopper.ca/api/file/pappin-back.webp"))
    check("with no staged CSV the card's other photo is offered",
          asked and asked[-1]["staged"] ==
          "https://canadianshopper.ca/api/file/pappin-back.webp",
          str(asked[-1:]))
    check("it says which photo the listing shows now",
          any("The listing shows this photo now" in text
              for _tag, text in app.lines), str(app.lines[-6:]))

    #  A sibling address the site does not answer for is never offered: a
    #  guess about a name is not a photo, and a 404 written to a live listing
    #  is a broken picture.
    asked[:] = []
    app.lines[:] = []
    with_photo_proof(None, record=front_only, alive=False,
                     press=lambda window: find(window, gui.ttk.Button,
                                               "Cancel").invoke())
    check("a sibling the site does not have is not offered",
          not asked and any("is not on the site, so it is not offered" in text
                            for _tag, text in app.lines), str(app.lines[-4:]))

    #  A record that cannot be read says so, and still uses what the list holds.
    asked[:] = []
    app.lines[:] = []
    with_photo_proof(None, record=None, press=press_photo(
        "https://cs.example/api/file/other-back.webp"))
    check("a record that cannot be read is named, not hidden",
          any("could not be read" in text for _tag, text in app.lines),
          str(app.lines[:4]))
    check("and the list's own photos are still offered",
          asked and asked[-1]["staged"] ==
          "https://cs.example/api/file/other-back.webp", str(asked[-1:]))

    #  Pasting an address the list does not know still works.
    asked[:] = []

    def paste(title, question, **kwargs):
        opened.update(dict(kwargs, title=title, question=question))
        return "https://cs.example/api/file/pasted.webp"

    with_photo_proof(
        "https://cs.example/api/file/staged.webp", ask=paste,
        press=lambda window: find(window, gui.ttk.Button,
                                  "Paste an address...").invoke())
    check("pasting an address is still a way in",
          asked and asked[-1]["staged"] ==
          "https://cs.example/api/file/pasted.webp", str(asked[-1:]))
    check("and the paste box says the picture has to be the same card",
          "same card" in opened.get("question", ""), str(opened.get("question")))

    #  The staging step is handed the batch folder - `canadianshopper_products`
    #  beside cs-ready - because that is where the CSVs it rewrote are. An
    #  address written without the site on the front (the older staging run)
    #  is completed before it is offered: the record wants a web address, and
    #  it is the same file on the same site.
    asked[:] = []
    looked = {}

    def eyes(folder, title, extra_folders=()):
        looked["folder"] = str(folder)
        looked["extra"] = [str(path) for path in extra_folders]
        return "/api/file/staged.webp"

    with_photo_proof(eyes, press=press_photo(
        "https://canadianshopper.ca/api/file/staged.webp"))
    check("the staging lookup is given the batch folder, not the app's",
          looked.get("folder") == str(folder / "canadianshopper_products"),
          str(looked))
    check("and an address with no site on the front is completed",
          asked and asked[-1]["staged"] ==
          "https://canadianshopper.ca/api/file/staged.webp", str(asked[-1:]))

    #  Nothing read: a proof of nothing is worse than a word.
    folder2, app2, parent2 = build_panel()
    harness._BOX.shown[:] = []
    harness._BOX.askyesno = lambda *a, **k: True
    find(parent2, gui.ttk.Button, "Write the proof").invoke()
    check("with nothing read it asks for a read instead of writing",
          harness._BOX.shown and
          "Read CanadianShopper's listings first" in
          str(harness._BOX.shown[0][1]), str(harness._BOX.shown))
    check("and writes no proof at all",
          not list(folder2.glob("cs-proof-*.txt")), "")

    #  A row with no id cannot be addressed - and a proof is a write, so it is
    #  refused before anything is sent rather than guessed at.
    folder3, app3, parent3 = build_panel()
    cookie3 = folder3 / "cookie.txt"
    cookie3.write_text("session_token=secret-value\n", encoding="utf-8")
    harness._BOX.shown[:] = []
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "CS_COOKIE_FILE", cookie3), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "open_path", lambda path: True), \
            patch.object(cs_proof, "prove", fake_prove):
        find(parent3, gui.ttk.Button,
             "Read CanadianShopper's listings").invoke()
        run = app3.runs[-1]
        Path(run["args"][1]).write_text(
            json.dumps({"items": [{"name": "A row with no id",
                                   "status": "active", "price": "5.00"}]}),
            encoding="utf-8")
        run["on_done"](0)
        before = len(asked)
        find(parent3, gui.ttk.Button, "Write the proof").invoke()
    check("a listing with no record id is refused, not guessed at",
          any("no id" in str(payload) for _kind, payload in harness._BOX.shown),
          str(harness._BOX.shown))
    check("and nothing was written for it", len(asked) == before, str(asked))
    check("no proof file was made for it either",
          not list(folder3.glob("cs-proof-*.txt")), "")
    harness._BOX.askyesno = lambda *a, **k: False
    #  Leave the module's dialog answers as the rest of the suite expects them.



def test_the_gallery_has_its_own_button():
    """A photo can go into the gallery even when no proof can reach it.

    The gallery is the one field a proof cannot settle on a record that does
    not carry it: there is no value to put back, so the field would have to be
    created - and a field that is not there cannot be proved. Which is how a
    person could see every field proved and still have no way to change the
    gallery. This is the button that does it, and the checks are about what it
    says before it writes and where the photo goes.
    """
    print()
    print("== 5j. the gallery has its own button ==")
    folder, app, parent = build_panel()
    cookie = folder / "cookie.txt"
    cookie.write_text("session_token=secret-value\n", encoding="utf-8")

    def sync_background(app_, work, done):
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        return done(result, error)

    listing_id = "94b93f6040f5401daabaa9c936efa5a7"
    rows = [{"id": listing_id, "product_id": 0, "sku": "OPC1973-74-112",
             "title": "#006/196 Wurmple SWSH11", "status": "active",
             "inventory": 1, "price": "12.50",
             "images": ["https://cs.example/api/file/current.webp"]}]
    photo = "https://cs.example/api/file/back.webp"
    #  The record the shop answers with: 39 keys and no gallery among them.
    record = {"id": listing_id, "title": "#006/196 Wurmple SWSH11",
              "priceCad": 12.5, "inventory": 1,
              "primaryImageUrl": "https://cs.example/api/file/current.webp",
              "tags": ["vintage"]}
    asked, questions, added = [], [], []

    def fake_read(url, cookie=""):
        asked.append(url)
        return 200, json.dumps(record)

    def fake_auto(**kwargs):
        return {"main": "", "gallery": photo, "why_main": "",
                "why_gallery": ""}

    def fake_add(url, cookie, photo_url, **kwargs):
        added.append(dict(kwargs, url=url, photo=photo_url))
        return {"field": "images", "label": "Gallery photos",
                "key": kwargs.get("key") or "images", "photo": photo_url,
                "verdict": "added", "written": True, "created": True,
                "before": 0, "after": 1,
                "why": "The record shows the photo in its images field.",
                "steps": [{"step": "GET the record", "status": 200}],
                "at": "2026-11-03 09:00:00"}

    def yes(title, question, **kwargs):
        questions.append((title, question))
        return True

    harness._BOX.shown[:] = []
    harness._BOX.askyesno = yes
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "open_path", lambda path: True), \
            patch.object(cs_proof, "read_record", fake_read), \
            patch.object(cs_proof, "auto_photos", fake_auto), \
            patch.object(cs_record, "add_gallery_photo", fake_add):
        find(parent, gui.ttk.Button,
             "Read CanadianShopper's listings").invoke()
        run = app.runs[-1]
        Path(run["args"][1]).write_text(json.dumps({"items": rows}),
                                       encoding="utf-8")
        run["on_done"](0)
        listing_box(parent).selection_set(0)
        app.lines[:] = []
        find(parent, gui.ttk.Button, "Add a photo to the gallery...").invoke()

    check("the gallery has its own button beside the proof buttons",
          find(parent, gui.ttk.Button, "Add a photo to the gallery...")
          is not None, "")
    check("pressing it asks once, before anything is written",
          len(questions) == 1, str(questions))
    question = questions[0][1] if questions else ""
    check("the question names the photo that would be added",
          photo in question, question[:200])
    check("and says the photo is kept, because that is what was asked for",
          "KEPT" in question, question[:300])
    check("and that the record is read back afterwards",
          "read afterwards" in question, question[:400])
    check("exactly one photo is added, at the listing's own record",
          len(added) == 1 and added[0]["url"].endswith("/" + listing_id)
          and added[0]["photo"] == photo, str(added))
    check("under the name the site uses, not a product id",
          added[0].get("key") == "images" and
          "product_id" not in added[0], str(added[0]))
    said = "\n".join(text for _tag, text in app.lines)
    check("and the console says the gallery holds the photo now",
          "gallery holds it" in said or "in the listing's gallery" in said,
          said[-400:])

    #  Declining writes nothing - the one thing a confirmation is for.
    added[:] = []
    questions[:] = []
    with patch.object(gui, "in_background", sync_background), \
            patch.object(cs_proof, "read_record", fake_read), \
            patch.object(cs_proof, "auto_photos", fake_auto), \
            patch.object(cs_record, "add_gallery_photo", fake_add):
        harness._BOX.askyesno = lambda *args, **kwargs: False
        app.lines[:] = []
        find(parent, gui.ttk.Button, "Add a photo to the gallery...").invoke()
    check("declining the question writes nothing", added == [], str(added))
    check("and says so plainly",
          any("not added" in text for _tag, text in app.lines),
          str(app.lines[-3:]))


def test_nothing_left_to_prove_is_not_a_run():
    """A field the record does not carry does not start a proof again.

    The run that ended in \"Proving 1 field ... each is written, read back and put
    back\" and then wrote nothing is the behaviour this stops: the field was
    the gallery, the record has no gallery, and that is now remembered.
    """
    print()
    print("== 5k. nothing left to prove does not start a run ==")
    folder, app, parent = build_panel()
    cookie = folder / "cookie.txt"
    cookie.write_text("session_token=secret-value\n", encoding="utf-8")

    def sync_background(app_, work, done):
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        return done(result, error)

    listing_id = "94b93f6040f5401daabaa9c936efa5a7"
    rows = [{"id": listing_id, "product_id": 0, "title": "Wurmple",
             "status": "active", "inventory": 1, "price": "12.50"}]
    proofs = {field: {"at": "2026-11-03 08:00:00", "verdict": "written",
                      "restored": True, "proven": True, "listing": listing_id,
                      "field_missing": False}
              for field in ("priceCad", "title", "description", "inventory",
                            "primaryImageUrl")}
    proofs["images"] = {"at": "2026-11-03 08:00:00", "verdict": "unreadable",
                        "restored": None, "proven": False,
                        "listing": listing_id, "field_missing": True}
    (folder / cs_proof.PROOFS_FILE).write_text(json.dumps(proofs),
                                               encoding="utf-8")
    written = []
    questions = []

    def fake_prove(*args, **kwargs):
        written.append((args, kwargs))
        return {"field": "images", "verdict": "unreadable",
                "field_missing": True, "why": ""}

    harness._BOX.shown[:] = []
    harness._BOX.askyesno = lambda title, question, **kwargs: questions.append(
        (title, question)) or True
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(cs_proof, "prove", fake_prove):
        find(parent, gui.ttk.Button,
             "Read CanadianShopper's listings").invoke()
        run = app.runs[-1]
        Path(run["args"][1]).write_text(json.dumps({"items": rows}),
                                       encoding="utf-8")
        run["on_done"](0)
        listing_box(parent).selection_set(0)
        app.lines[:] = []
        find(parent, gui.ttk.Button, "Prove every field...").invoke()

    said = "\n".join(text for _tag, text in app.lines)
    check("no proof is started for a field the record does not carry",
          written == [], str(written))
    check("and nothing is asked, because nothing would be written",
          questions == [], str(questions))
    check("the console says it in one line, naming the field",
          "gallery photos" in said.casefold() and "not a field" in said,
          said[-300:])
    check("and points at the button that does reach the gallery",
          "Add a photo to the gallery" in said, said[-300:])
    check("it does not claim a run started", "Proving" not in said,
          said[-300:])
    check("the summary says the same thing", "Nothing left" in
          str(next((w.cget("text") for w in parent.walk()
                    if isinstance(w, gui.ttk.Label)
                    and "Nothing left" in str(w.cget("text"))), "")), "")


def test_the_panel_sets_a_proven_price():
    """The price button: one listing, one field, and only after a proof.

    The proof button settles the field; this one uses it. What the checks are
    about is that the price is not a way around the rule - no proof means no
    write, the record's own id is the address, and the answer the panel shows
    is the price the record really holds afterwards.
    """
    print()
    print("== 5k. the panel sets a price the proof settled ==")
    folder, app, parent = build_panel()
    cookie = folder / "cookie.txt"
    cookie.write_text("session_token=secret-value\n", encoding="utf-8")
    rows = [{"id": "a2304e72dbca4e678e7111d011ade22d", "product_id": 0,
             "title": "Wurmple SWSH11: Lost Origin", "sku": "PKM-006",
             "status": "active", "inventory": 1, "price": "1.00"}]

    def sync_background(app_, work, done):
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        return done(result, error)

    def read_rows():
        with patch.object(gui, "TOOL_ACTION",
                          lambda action: "/plugins/cs/stock.py"), \
                patch.object(gui, "CS_COOKIE_FILE", cookie), \
                patch.object(gui, "in_background", sync_background), \
                patch.object(gui, "BASE", folder):
            find(parent, gui.ttk.Button,
                 "Read CanadianShopper's listings").invoke()
            run = app.runs[-1]
            Path(run["args"][1]).write_text(json.dumps({"items": rows}),
                                           encoding="utf-8")
            run["on_done"](0)
        listing_box = next(widget for widget in parent.walk()
                           if isinstance(widget, gui.tk.Listbox))
        listing_box.selection_set(0)
        return listing_box

    read_rows()
    button = find(parent, gui.ttk.Button, "Set the selected listing's price...")
    check("the panel offers to set the selected listing's price",
          button is not None, "")

    said, asked, written = [], [], []
    harness._BOX.shown[:] = []
    harness._BOX.askyesno = lambda *a, **k: asked.append(a) or True
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "simpledialog") as dialog, \
            patch.object(cs_record, "write", lambda *a, **k: written.append(
                (a, k)) or {"verdict": "written", "written": True,
                            "after": 2.5, "old": 1.0, "field": "priceCad",
                            "label": "Price", "id": rows[0]["id"]}):
        dialog.askstring = lambda *a, **k: "2.50"
        button.invoke()
    check("without a saved proof the price is not written",
          not written and not asked, str(written))
    check("and the panel says which proof settles it",
          harness._BOX.shown and
          "Prove a field can be written" in str(harness._BOX.shown[0][1]),
          str(harness._BOX.shown[:1]))

    (folder / "cs-field-proofs.json").write_text(
        json.dumps({"priceCad": {"at": "2026-11-02 15:34:38", "proven": True,
                                 "verdict": "written", "restored": True,
                                 "listing": rows[0]["id"],
                                 "title": "Wurmple"}}), encoding="utf-8")
    written[:] = []
    asked[:] = []
    harness._BOX.shown[:] = []
    app.lines[:] = []
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "simpledialog") as dialog, \
            patch.object(cs_record, "write", lambda *a, **k: written.append(
                (a, k)) or {"verdict": "written", "written": True,
                            "after": 2.5, "old": 1.0, "field": "priceCad",
                            "label": "Price", "id": rows[0]["id"]}):
        dialog.askstring = lambda *a, **k: "2.50"
        button.invoke()
    check("a proven price is written once, after a question",
          len(written) == 1 and asked, str(written))
    check("addressed at the record's own id, with the old price expected",
          written and written[0][0][0] ==
          "https://canadianshopper.ca/api/data/product/"
          "a2304e72dbca4e678e7111d011ade22d" and
          written[0][1].get("expect_id") == rows[0]["id"] and
          written[0][1].get("expect_old") == "1.00", str(written))
    check("the question names the price change and the promise",
          asked and "1.00" in str(asked[0]) and "2.50" in str(asked[0]) and
          "no product id" in str(asked[0]), str(asked))
    check("only the one field is sent", written and
          written[0][1].get("field", "priceCad") == "priceCad", "")
    check("the console says what the site shows now",
          any("2.50" in text for _tag, text in app.lines), str(app.lines[-4:]))

    #  The price that is already there is not a change.
    written[:] = []
    said[:] = []
    harness._BOX.shown[:] = []
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "simpledialog") as dialog, \
            patch.object(cs_record, "write", lambda *a, **k: written.append(a)):
        #  The panel applied the written price to the row, so the listing now
        #  reads 2.50 - and that is the price it must refuse to write again.
        dialog.askstring = lambda *a, **k: "2.50"
        button.invoke()
    check("typing the price the listing already has writes nothing",
          not written and harness._BOX.shown, str(written))
    check("and it says there is nothing to change",
          "already shows" in str(harness._BOX.shown[0][1]),
          str(harness._BOX.shown[:1]))

    #  A zero is refused before anything is asked.
    written[:] = []
    harness._BOX.shown[:] = []
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "simpledialog") as dialog, \
            patch.object(cs_record, "write", lambda *a, **k: written.append(a)):
        dialog.askstring = lambda *a, **k: "0"
        button.invoke()
    check("a zero price is refused with the reason",
          not written and harness._BOX.shown and
          "zero" in str(harness._BOX.shown[0][1]).lower(),
          str(harness._BOX.shown[:1]))
    harness._BOX.askyesno = lambda *a, **k: False


def test_the_edit_button_takes_the_price_road():
    """A row the plugin cannot address is offered its price, not a dead end.

    This is the console that prompted it: a read of 2,596 listings with no
    product ids, *Edit the selected listing...*, and a form closed without
    saving - while the price was already proven and writable on that very row.
    Nothing here may open the four-field form for such a row.
    """
    print()
    print("== 5l. Edit on a row with no product id goes to the price ==")
    folder, app, parent = build_panel()
    cookie = folder / "cookie.txt"
    cookie.write_text("session_token=secret-value\n", encoding="utf-8")
    rows = [{"id": "a2304e72dbca4e678e7111d011ade22d", "product_id": 0,
             "title": "#006/196 Wurmple SWSH11: Lost Origin - Pokemon TCG",
             "sku": "PKM-006", "status": "active", "inventory": 1,
             "price": "1.00"}]

    def sync_background(app_, work, done):
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        return done(result, error)

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        read_into(app, folder, parent, payload=rows)
    select(parent, "Wurmple")

    said, written, asked = [], [], []
    harness._BOX.shown[:] = []
    harness._BOX.askyesno = lambda title, question, **k: (
        asked.append((title, question)) or True)
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "simpledialog") as dialog, \
            patch.object(cs_record, "write", lambda *a, **k: written.append(
                (a, k)) or {"verdict": "written", "written": True,
                            "after": 2.5, "old": 1.0, "field": "priceCad",
                            "label": "Price", "id": rows[0]["id"]}):
        dialog.askstring = lambda *a, **k: "2.50"
        find(parent, gui.ttk.Button, "Edit the selected listing",
             exact=False).invoke()
    check("with no proof the edit form still opens, as it always did",
          not written, str(written))

    (folder / "cs-field-proofs.json").write_text(
        json.dumps({"priceCad": {"at": "2026-11-02 15:34:38", "proven": True,
                                 "verdict": "written", "restored": True,
                                 "listing": rows[0]["id"],
                                 "title": "Wurmple"}}), encoding="utf-8")
    written[:] = []
    asked[:] = []
    harness._BOX.shown[:] = []
    app.lines[:] = []
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "simpledialog") as dialog, \
            patch.object(cs_record, "write", lambda *a, **k: written.append(
                (a, k)) or {"verdict": "written", "written": True,
                            "after": 2.5, "old": 1.0, "field": "priceCad",
                            "label": "Price", "id": rows[0]["id"]}):
        dialog.askstring = lambda *a, **k: "2.50"
        find(parent, gui.ttk.Button, "Edit the selected listing",
             exact=False).invoke()
    check("with the price proven, Edit offers the price instead of the form",
          asked and "price" in asked[0][0].lower(), str(asked))
    check("and the question says which fields the plugin cannot send",
          asked and "title, stock count or state" in str(asked[0][1]),
          str(asked[:1]))
    check("the price is then written to the record, once",
          len(written) == 1 and written[0][0][0].endswith(rows[0]["id"]),
          str(written))
    check("the console never says the edit was closed without saving",
          not any("closed without saving" in text for _tag, text in app.lines),
          str(app.lines[-4:]))

    #  Declining is a real answer: nothing written, and the way in is named.
    written[:] = []
    app.lines[:] = []
    harness._BOX.askyesno = lambda *a, **k: False
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "simpledialog") as dialog, \
            patch.object(cs_record, "write", lambda *a, **k: written.append(a)):
        dialog.askstring = lambda *a, **k: "2.50"
        find(parent, gui.ttk.Button, "Edit the selected listing",
             exact=False).invoke()
    check("declining writes nothing", not written, str(written))
    check("and points at the button that does reach the row",
          any("Set the selected listing's price" in text
              for _tag, text in app.lines), str(app.lines[-3:]))
    harness._BOX.askyesno = lambda *a, **k: True


def test_a_form_of_every_proven_field():
    """The panel's own form: one row per field, open only where a proof is.

    The price write proved the road, and the road is the record's - so the
    title, the description, the stock count and the main photo travel it too,
    each behind the proof that settled it. What this checks is that the form
    is that map: a proven field can be typed in, an unproven one is shown
    with the button that would prove it, and only the fields changed are sent.
    """
    print()
    print("== 5m. a form of every proven field ==")
    folder, app, parent = build_panel()
    cookie = folder / "cookie.txt"
    cookie.write_text("session_token=secret-value\n", encoding="utf-8")
    row = {"id": "a2304e72dbca4e678e7111d011ade22d", "product_id": 0,
           "title": "#006/196 Wurmple SWSH11: Lost Origin - Pokemon TCG",
           "sku": "PKM-006", "status": "active", "inventory": 1,
           "price": "1.00"}

    def sync_background(app_, work, done):
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        return done(result, error)

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        read_into(app, folder, parent, payload=[row])
    select(parent, "Wurmple")

    (folder / "cs-field-proofs.json").write_text(json.dumps({
        "priceCad": {"at": "2026-11-02 15:34:38", "proven": True,
                     "verdict": "written", "restored": True,
                     "listing": row["id"], "title": "Wurmple"},
        "title": {"at": "2026-11-02 16:02:11", "proven": True,
                  "verdict": "written", "restored": True,
                  "listing": row["id"], "title": "Wurmple"}}),
        encoding="utf-8")

    sent, questions, shown = [], [], []
    old_title = row["title"]
    new_title = "#006/196 Wurmple SWSH11: Lost Origin - Pokemon TCG (NM)"

    def press(window):
        """Fill the proven title in, then press the form's write button."""
        for widget in window.walk():
            var = widget.cget("textvariable") if isinstance(
                widget, gui.ttk.Entry) else ""
            if var and hasattr(var, "get") and var.get() == old_title:
                var.set(new_title)
        button = next((w for w in window.walk()
                       if isinstance(w, gui.ttk.Button) and
                       str(w.cget("text")) == "Write the changed fields"), None)
        if button is not None:
            button.invoke()

    harness._BOX.shown[:] = []
    harness._BOX.askyesno = lambda title, question, **k: (
        questions.append((title, question)) or True)
    harness.PICKER["press"] = press

    def fake_update(url, cookie_, changes, **kwargs):
        sent.append((url, dict(changes), kwargs))
        return {"verdict": "written", "written": True,
                "card": "Wurmple", "id": row["id"],
                "fields": [{"field": "title", "label": "Title",
                            "verdict": "written", "old": old_title,
                            "value": new_title, "after": new_title,
                            "why": "Title now reads the new value."}]}

    try:
        with patch.object(gui, "BASE", folder), \
                patch.object(gui, "CS_COOKIE_FILE", cookie), \
                patch.object(gui, "in_background", sync_background), \
                patch.object(cs_record, "update", fake_update):
            find(parent, gui.ttk.Button,
                 "Edit the record's fields...").invoke()
    finally:
        harness.PICKER["press"] = lambda window: None

    check("the form opens on the record's own id and writes what changed",
          len(sent) == 1 and sent[0][0].endswith(row["id"]), str(sent[:1]))
    check("only the field that was typed in is sent",
          len(sent) == 1 and list(sent[0][1]) == ["title"], str(sent[:1]))
    check("and the record's own id is the address, not a product id",
          sent and sent[0][2].get("expect_id") == row["id"] and
          "/api/data/product/" in sent[0][0] and
          "/api/products/" not in sent[0][0], str(sent[:1]))
    check("the row's old value travels with the write, for the guard",
          sent and sent[0][2].get("expected", {}).get("title") == old_title,
          str(sent[:1]))
    check("the confirmation names every change",
          questions and new_title in questions[0][1], str(questions[:1]))
    check("and it says the website is not touched",
          questions and "website" in questions[0][1], str(questions[:1]))
    check("the console says what changed, once",
          any("Title" in text or "title" in text for _tag, text in app.lines),
          str(app.lines[-3:]))

    #  A field with no proof is on the form, greyed, with the way to prove it:
    #  a form that hid it would say the app writes less than it does.
    shown_form = {}

    def look(window):
        shown_form["labels"] = [str(w.cget("text")) for w in window.walk()
                                if isinstance(w, gui.ttk.Label)]
        shown_form["buttons"] = [str(w.cget("text")) for w in window.walk()
                                 if isinstance(w, gui.ttk.Button)]

    harness.PICKER["press"] = look
    try:
        with patch.object(gui, "BASE", folder), \
                patch.object(gui, "in_background", sync_background):
            find(parent, gui.ttk.Button,
                 "Edit the record's fields...").invoke()
    finally:
        harness.PICKER["press"] = lambda window: None
    check("the unproven fields are on the form, named",
          any("Description" in text for text in shown_form.get("labels", []))
          and any("Main photo" in text
                  for text in shown_form.get("labels", [])),
          str(shown_form.get("labels")))
    check("each one offers the proof that would open it",
          shown_form.get("buttons", []).count("Prove this field...") == 3,
          str(shown_form.get("buttons")))
    check("and the form says what is proven and what is never sent",
          any("Proven writable here" in text and "never sent" in text
              for text in shown_form.get("labels", [])),
          str(shown_form.get("labels")))

    #  A long field the stock list does not carry: proven, so typeable - and
    #  the form has to say that typing there replaces the whole description,
    #  because the empty box is not the same fact as an empty description.
    proofs = json.loads((folder / "cs-field-proofs.json").read_text())
    proofs["description"] = {"at": "2026-11-02 16:20:00", "proven": True,
                             "verdict": "written", "restored": True,
                             "listing": row["id"], "title": "Wurmple"}
    (folder / "cs-field-proofs.json").write_text(json.dumps(proofs),
                                                 encoding="utf-8")
    shown_form.clear()
    harness.PICKER["press"] = look
    try:
        with patch.object(gui, "BASE", folder), \
                patch.object(gui, "in_background", sync_background):
            find(parent, gui.ttk.Button,
                 "Edit the record's fields...").invoke()
    finally:
        harness.PICKER["press"] = lambda window: None
    check("a proven field the row does not carry is typeable all the same",
          any("Description" in text for text in shown_form.get("labels", [])),
          str(shown_form.get("labels")))
    check("and the form says typing there replaces the whole description",
          any("replaces the whole description" in text
              for text in shown_form.get("labels", [])),
          str(shown_form.get("labels")))
    check("while the photo, still unproven, offers its proof",
          shown_form.get("buttons", []).count("Prove this field...") == 2,
          str(shown_form.get("buttons")))



def test_the_panel_shows_the_whole_read():
    """2,596 listings read, and 2,596 on screen - not the first 200.

    The report: *"I'm only shown 200 products from CS stock."* The read brought
    the whole shop; the list capped itself at 200 rows, and the read's own
    sentence replaced the count of what was on screen - so a shop of 2,596
    listings looked like a shop of 200, and the only way to reach the other
    2,396 was to guess a search term for them.
    """
    print()
    print("== 5n. the whole read is on screen ==")
    rows = [{"id": "b%04d" % n, "sku": "SKU-%04d" % n,
             "title": "zzz card %04d" % n, "price": "1.00",
             "inventory": 1, "status": "active"} for n in range(2596)]
    folder, app, parent = build_panel()
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"):
        read_into(app, folder, parent, rows)
    check("every listing the read brought is in the list",
          len(listing_box(parent).items) == len(rows) == 2596,
          str(len(listing_box(parent).items)))
    check("and the summary says all of them are shown",
          "All 2596 listings shown" in summary_text(parent),
          summary_text(parent))
    check("the last card in the read is on screen, not past a cut",
          any("zzz card 2595" in text for text in listing_box(parent).items),
          str(listing_box(parent).items[-1:]))

    entry = query_box(parent)
    entry._kw["textvariable"].set("SKU-2595")
    find(parent, gui.ttk.Button, "Search").invoke()
    check("a card that sorts past the old 200 is found by searching",
          len(listing_box(parent).items) == 1 and
          "SKU-2595" in listing_box(parent).items[0],
          str(listing_box(parent).items[:3]))

    check("search returns every match unless a caller asks for fewer",
          len(cs_edit.search(rows, "")) == 2596, "")
    check("a caller that does ask for a short list still gets one",
          len(cs_edit.search(rows, "", limit=cs_edit.SEARCH_LIMIT)) ==
          cs_edit.SEARCH_LIMIT == 200, "")
    check("and a caller asking for everything gets everything, cap or no cap",
          len(cs_edit.search(rows, "SKU-25", limit=0)) ==
          len(cs_edit.search(rows, "SKU-25")) >= 1, "")



def test_the_shop_is_reached_only_with_the_plugin():
    """No plugin, no proof and no write: the plugin owns the site's API.

    These four features - the proof, the price, the record's fields and the
    diagnosis probe - talk to CanadianShopper's own API from this app. That is
    the plugin's conversation: it holds the session and the actions the vendor
    documents, and a core that reached past it would be writing to a live shop
    on an arrangement nobody installed. So without the plugin each button says
    so and sends nothing - it does not try and fail, and it never asks for a
    value it would then have nowhere to send.
    """
    print()
    print("== 5o. the shop is reached only while the plugin is installed ==")
    folder, app, parent = build_panel()
    cookie = folder / "cookie.txt"
    cookie.write_text("session_token=secret-value\n", encoding="utf-8")
    rows = [{"id": "a2304e72dbca4e678e7111d011ade22d", "product_id": 4321,
             "title": "#006/196 Wurmple SWSH11: Lost Origin - Pokemon TCG",
             "sku": "PKM-006", "status": "active", "inventory": 1,
             "price": "1.00"}]

    def sync_background(app_, work, done):
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        return done(result, error)

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "CS_COOKIE_FILE", cookie), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        read_into(app, folder, parent, payload=rows)
    select(parent, "Wurmple")
    (folder / "cs-field-proofs.json").write_text(
        json.dumps({"priceCad": {"at": "2026-11-02 15:34:38", "proven": True,
                                 "verdict": "written", "restored": True,
                                 "listing": rows[0]["id"],
                                 "title": "Wurmple"}}), encoding="utf-8")

    said, written, proved, opened, typed = [], [], [], [], []
    harness._BOX.shown[:] = []
    harness._BOX.showinfo = lambda *a, **k: said.append(a)
    harness.PICKER["press"] = lambda window: opened.append(window)
    app.cs_addon = False
    try:
        with patch.object(gui, "BASE", folder), \
                patch.object(gui, "CS_COOKIE_FILE", cookie), \
                patch.object(gui, "cs_addon_present", lambda: False), \
                patch.object(gui, "in_background", sync_background), \
                patch.object(gui, "simpledialog") as dialog, \
                patch.object(cs_record, "write",
                             lambda *a, **k: written.append((a, k))), \
                patch.object(cs_record, "update",
                             lambda *a, **k: written.append((a, k))), \
                patch.object(cs_record, "send_fields",
                             lambda *a, **k: written.append((a, k))), \
                patch.object(cs_proof, "prove",
                             lambda *a, **k: proved.append((a, k))):
            dialog.askstring = lambda *a, **k: typed.append(a) or "2.50"
            find(parent, gui.ttk.Button,
                 "Set the selected listing's price...").invoke()
            check("with no plugin the price button asks for nothing",
                  not typed, str(typed))
            check("and writes nothing", not written, str(written))
            check("and says the plugin is what talks to the shop",
                  said and "CanadianShopper plugin" in str(said[-1]),
                  str(said[-1:]))
            check("and puts the refusal on the console",
                  any("which is not installed; nothing was sent" in text
                      for _tag, text in app.lines), str(app.lines[-2:]))

            said[:] = []
            before = len(opened)
            find(parent, gui.ttk.Button,
                 "Edit the record's fields...").invoke()
            check("with no plugin the field form does not open",
                  len(opened) == before, str(opened[before:]))
            check("and nothing is written from it", not written, str(written))

            said[:] = []
            find(parent, gui.ttk.Button, "Write the proof").invoke()
            check("with no plugin a proof is not written",
                  not proved, str(proved))
            check("and the button says why",
                  said and "CanadianShopper plugin" in str(said[-1]),
                  str(said[-1:]))

            said[:] = []
            find(parent, gui.ttk.Button,
                 "Save a read diagnosis...").invoke()
            check("with no plugin the diagnosis probe is not run either",
                  said and "CanadianShopper plugin" in str(said[-1]),
                  str(said[-1:]))
    finally:
        app.cs_addon = True
        harness._BOX.showinfo = lambda *a, **k: (
            harness._BOX.shown.append(("showinfo", a)))
        harness.PICKER["press"] = lambda window: None


def test_the_panel_quotes_the_readers_resolution():
    """A read that asked and got nothing back says so, on the console.

    The person reading the console is the one who would otherwise carry "still
    no ids" to the plugin's author, so the reader's own counts belong there -
    once, quoted, with the sentence they mean - and the "would have to update
    the plugin" advice must not be printed over the top of them.
    """
    print()
    print("== 5j. a read that asked and was answered with nothing ==")
    folder, app, parent = build_panel()
    line = ("Stock resolution: 20 detail requests, 0 usable references, 20 "
            "HTTP 200s without a usable reference, 0 ambiguous SKUs, 0 hard "
            "failures")
    nothing = [{key: value for key, value in row.items() if key != "product_id"}
               for row in LISTINGS]
    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "plugin_version", lambda *a, **k: "1.0.39"):
        find(parent, gui.ttk.Button,
             "Read CanadianShopper's listings").invoke()
        run = app.runs[-1]
        Path(run["args"][1]).write_text(json.dumps({"items": nothing}),
                                        encoding="utf-8")
        app.runner = SimpleNamespace(
            output=("stock.list: %d listings, 0 with a real product id"
                    % len(nothing) + "\n" + line), cmd="cs-stock.py")
        run["on_done"](0)

    said = [text for _tag, text in app.lines]
    check("the reader's own resolution line is quoted on the console",
          any(text.startswith("The reader's own resolution line: Stock "
                              "resolution: 20 detail requests") for text in said),
          str(said[-5:]))
    check("and the console says what those numbers mean",
          any("vendor's data rather than a defect in the reader" in text
              for text in said), str(said[-5:]))
    check("a 1.0.39 read is not told to update the plugin",
          not any("0.39 or newer" in text or "0.39 prints the reader" in text
                  for text in said), str(said[-5:]))
    check("and the rows are still on screen to read and open",
          len(listing_box(parent).items) == len(nothing), "")


def test_the_evidence_outlives_the_window():
    """A diagnosis written after a restart still has the run's own account.

    The first real diagnosis came back with "(not recorded)", "(no console
    output was kept)" and "(none)" against a list of 2,596 rows: the panel had
    restored the last read from disk, so the window had no run to quote - and
    its author's three questions went unanswered again. A read now keeps its
    output, its stages and its command beside the list it wrote.
    """
    print()
    print("== 5i. the read's evidence outlives the window ==")
    folder, app, parent = build_panel()

    def sync_background(app_, work, done):
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        return done(result, error)

    output = ("stock.list: 3 listings, 0 with a real product id, 3 without the "
              "key, 0 reported as 0")

    def fake_detail(url, cookie_text="", **kwargs):
        return (200, "application/json", json.dumps({"id": "a", "sku": "S1"}))

    def fake_options(url, cookie_text="", **kwargs):
        return {"status": 204, "allow": ["GET", "HEAD"],
                "allow_header": "GET, HEAD", "note": ""}

    with patch.object(gui, "TOOL_ACTION",
                      lambda action: "/plugins/cs/stock.py"), \
            patch.object(gui, "in_background", sync_background):
        app.stages_seen = lambda: ["read", "ids"]
        app.runner = SimpleNamespace(
            output=output, cmd="python cs-stock.py --stock-out x")
        find(parent, gui.ttk.Button,
             "Read CanadianShopper's listings").invoke()
        run = app.runs[-1]
        Path(run["args"][1]).write_text(json.dumps({"items": LISTINGS}),
                                        encoding="utf-8")
        run["on_done"](0)

    kept = json.loads((folder / "cs-stock-meta.json").read_text(encoding="utf-8"))
    check("the run's output, its stages and its command are kept by the list",
          kept.get("output") == output and kept.get("stages") == ["read", "ids"]
          and "cs-stock.py" in str(kept.get("command")), str(kept))

    def press(panel):
        """Press the button and return the file *this* press wrote.

        Two files can be written in the same second and this filesystem can
        give them the same mtime, so the new one is the one that was not there
        before rather than whichever sorts last.
        """
        before = set(folder.glob("cs-read-diagnosis-*.txt"))
        find(panel, gui.ttk.Button, "Save a read diagnosis...").invoke()
        written = set(folder.glob("cs-read-diagnosis-*.txt")) - before
        return max(written, key=lambda item: item.name).read_text(
            encoding="utf-8") if written else ""

    #  A new window: nothing in it ran, and the list is the one on disk.
    app2 = harness.FakeApp(folder)
    parent2 = harness.FakeWidget()
    with patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "open_path", lambda path: True), \
            patch.object(cs_edit, "fetch_detail", fake_detail), \
            patch.object(cs_edit, "fetch_options", fake_options):
        gui.build_csledit(parent2, app2)
        text = press(parent2)
    check("a fresh window's diagnosis still quotes the run's own output",
          output in text, text[:600])
    check("and still says which phases the reader reported",
          "Phases the reader reported: read, ids" in text and
          "the lookups ran" in text, text[:600])
    check("and the command, so 'no flag was passed' is in the file",
          "cs-stock.py --stock-out x" in text and
          "(not recorded)" not in text, text[:400])
    check("it says the list came from disk, not from this window",
          "Where this list came from: the last read on disk" in text, text[:400])
    check("and that read's count line is answered by its phases, not guessed",
          "cannot say whether its lookups ran" not in text, text[:600])

    #  A list read before the app kept any of it: the log still has the
    #  command, and the file says plainly that the rest was not kept.
    (folder / "cs-stock-meta.json").write_text(json.dumps(
        {"plugin": "1.0.38", "count": len(LISTINGS),
         "at": "2026-11-02T11:16:38"}), encoding="utf-8")
    log = folder / "gui-log.txt"
    log.write_text(
        "[2026-11-02 11:00:00] START CanadianShopper listings | py cs-stock.py"
        " --stock-out old.json\n"
        "[2026-11-02 11:16:37] START CanadianShopper listings | py cs-stock.py"
        " --stock-out new.json --cookie-file cookie.txt\n"
        "[2026-11-02 11:20:00] START Something else | py other.py\n",
        encoding="utf-8")
    check("the last command of that read is taken from the app's log",
          gui.command_from_log("CanadianShopper listings", path=log)
          .endswith("--cookie-file cookie.txt"),
          gui.command_from_log("CanadianShopper listings", path=log))
    check("a log with no such run answers nothing",
          gui.command_from_log("Nothing ran", path=log) == "", "")
    check("a missing log answers nothing rather than raising",
          gui.command_from_log("CanadianShopper listings",
                               path=folder / "none.log") == "", "")

    parent3 = harness.FakeWidget()
    with patch.object(gui, "LOG_FILE", log), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "open_path", lambda path: True), \
            patch.object(cs_edit, "fetch_detail", fake_detail), \
            patch.object(cs_edit, "fetch_options", fake_options):
        gui.build_csledit(parent3, harness.FakeApp(folder))
        old_text = press(parent3)
    check("an older list's command still comes from the log",
          "--cookie-file cookie.txt" in old_text, old_text[:400])
    check("and the file says the app kept none of that read's output",
          "did not keep that run's console output" in old_text and
          "reading the listings again" in old_text, old_text[:600])


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
    check("the read says how much of the list can be edited here",
          any("every one with a product id, so every one can be edited here"
              in text for _tag, text in app.lines), str(app.lines[-4:]))
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
          set(plan) == {"id", "sku", "title", "card", "url",
                        "product_id"} and
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
          set(plan) == {"id", "sku", "title", "card", "url", "status",
                        "product_id"},
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
    test_every_field_is_proved_in_one_job()
    test_a_settled_field_is_not_reported_as_broken()
    test_the_12030_reproduction()
    test_a_list_read_before_product_ids()
    test_a_read_with_no_product_ids_at_all()
    test_a_reader_that_says_zero()
    test_the_version_that_reports_product_ids()
    test_what_the_read_did_carry()
    test_the_readers_own_numbers()
    test_the_diagnosis_file()
    test_the_readers_own_resolution_counts()
    test_the_real_diagnosis_from_the_shop()
    test_plugin_1_0_35()
    test_the_list_says_which_plugin_read_it()
    test_the_editing_panel_says_what_stopped_a_read()
    test_the_panel_writes_a_diagnosis()
    test_the_panel_writes_a_proof()
    test_the_gallery_has_its_own_button()
    test_nothing_left_to_prove_is_not_a_run()
    test_the_panel_sets_a_proven_price()
    test_the_edit_button_takes_the_price_road()
    test_a_form_of_every_proven_field()
    test_the_panel_shows_the_whole_read()
    test_the_shop_is_reached_only_with_the_plugin()
    test_the_panel_quotes_the_readers_resolution()
    test_the_evidence_outlives_the_window()
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
