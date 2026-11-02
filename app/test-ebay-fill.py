#!/usr/bin/env python3
"""Checks for ebay_fill - which cards go on eBay next, and the page for them.

No network, no eBay and no shop: the catalogue is a list of products, the
store's listings are a list of rows the eBay reader would have returned, and
the page is a string. The deciding is what is worth testing, because a list
that misses a card or repeats one is a month of listings done twice.
"""
import importlib.util
import sys
import tempfile
from datetime import datetime
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
import ebay_fill                                      # noqa: E402
import market_stock                                   # noqa: E402


def product(**overrides):
    """One website product, with everything a real one carries."""
    base = {
        "id": 1,
        "name": "1973-74 O-Pee-Chee Jim Pappin #112 Chicago Black Hawks EX 5",
        "sku": "OPC1973-74-112-Pappin-EX-5",
        "price": "1250.00",
        "status": "publish",
        "stock_status": "instock",
        "manage_stock": True,
        "stock_quantity": 1,
        "permalink": "https://shop.example/?p=1",
        "short_description": "<p>Sharp corners &amp; a clean back.</p>",
        "attributes": [
            {"name": "Player", "options": ["Jim Pappin"]},
            {"name": "Card number", "options": ["112"]},
            {"name": "Year", "options": ["1973-74"]},
            {"name": "Set", "options": ["O-Pee-Chee"]},
            {"name": "Condition", "options": ["EX 5"]},
        ],
        "categories": [{"name": "Hockey Cards"}],
        "tags": [{"name": "O-Pee-Chee"}],
        "images": [{"src": "https://shop.example/a.jpg"},
                   {"src": "https://shop.example/b.jpg"}],
    }
    base.update(overrides)
    return base


SETTINGS = {
    "ebay_template_hockey_url": "https://ebay.example/hockey",
    "ebay_template_default_url": "https://ebay.example/default",
    "ebay_default_condition": "Mint",
    "ebay_default_year": "Unknown",
    "ebay_default_manufacturer": "Unknown",
    "ebay_default_card_number": "N/A",
    "ebay_default_player": "Unknown",
    "ebay_default_set": "Vintage",
    "ebay_default_grade": "",
    "ebay_default_autographed": "No",
    "ebay_default_description": "Vintage card.",
}


def test_prices_and_titles():
    print()
    print("== 1. what a product says about itself ==")
    check("a plain price is a number",
          ebay_fill.price_of({"price": "1250.00"}) == 1250.0, "")
    check("a price with a comma and a currency is read, not dropped",
          ebay_fill.price_of({"price": "CA$1,250.00"}) == 1250.0, "")
    check("a product with no price has none, rather than zero",
          ebay_fill.price_of({}) is None and
          ebay_fill.price_of({"price": ""}) is None, "")
    check("the sale price is used when there is no price",
          ebay_fill.price_of({"sale_price": "8.50"}) == 8.5, "")
    check("a title keeps its words and loses its extra spaces",
          ebay_fill.title_of({"name": "  A   card  "}) == "A card", "")
    long_name = ("1973-74 O-Pee-Chee Jim Pappin #112 Chicago Black Hawks "
                 "EX 5 Chicago Stadium Photograph Card Rare Bilingual Back")
    title = ebay_fill.listing_title({"name": long_name})
    check("an eBay title is cut at 80 characters or fewer",
          len(title) <= 80, str(len(title)))
    check("and cut between words, not through one",
          long_name.startswith(title) and not long_name[len(title)].isalnum(),
          title)
    check("a title that fits is left exactly as it is",
          ebay_fill.listing_title({"name": "Short card"}) == "Short card", "")

    check("the card's own attributes are read by name",
          ebay_fill.attribute(product(), "Player") == "Jim Pappin" and
          ebay_fill.attribute(product(), "card number") == "112" and
          ebay_fill.attribute(product(), "CARD_NUMBER") == "112", "")
    check("a product with no attribute says nothing rather than guessing",
          ebay_fill.attribute(product(), "Grade") == "", "")
    check("the pictures are the shop's own addresses, front first",
          ebay_fill.images_of(product()) == ["https://shop.example/a.jpg",
                                             "https://shop.example/b.jpg"], "")
    check("a product with one picture has no back",
          ebay_fill.images_of(product(images=[{"src": "https://x/a.jpg"}])) ==
          ["https://x/a.jpg"], "")

    check("stock management switched off is not sold out",
          ebay_fill.stock_left(product(manage_stock=False,
                                       stock_quantity=None)) is None, "")
    check("a counted product at zero is sold out",
          ebay_fill.stock_left(product(stock_quantity=0)) == 0, "")
    check("a product marked out of stock is sold out however it is counted",
          ebay_fill.stock_left(product(stock_status="outofstock",
                                       stock_quantity=4)) == 0, "")


def test_what_can_be_listed():
    print()
    print("== 2. what can and cannot be listed ==")
    check("a published, priced, stocked card can",
          ebay_fill.listable(product()) == (True, ""), "")
    check("a draft cannot, and says so",
          ebay_fill.listable(product(status="draft")) ==
          (False, "it is not published on the website (draft)"), "")
    check("a card with no price cannot",
          ebay_fill.listable(product(price=""))[1] ==
          "it has no price on the website", "")
    check("a card priced at zero cannot",
          ebay_fill.listable(product(price="0.00"))[1] ==
          "its price is zero", "")
    check("a card the website has none of cannot",
          ebay_fill.listable(product(stock_quantity=0))[1] ==
          "the website has none in stock", "")
    check("a product with no name cannot",
          ebay_fill.listable(product(name="  "))[1] ==
          "it has no name on the website", "")


def test_the_selection():
    print()
    print("== 3. which cards are chosen, and why ==")
    products = [
        product(id=1, name="Dear card #1", price="900.00"),
        product(id=2, name="Middle card #2", price="500.00"),
        product(id=3, name="Cheap card #3", price="10.00"),
        product(id=4, name="Already listed #4", price="800.00",
                sku="LISTED-4"),
        product(id=5, name="Sold out #5", price="700.00", stock_quantity=0),
        product(id=6, name="Draft card #6", price="600.00", status="draft"),
        product(id=7, name="Unpriced card #7", price=""),
    ]
    listings = [{"id": "1", "name": "Already listed #4", "sku": "LISTED-4",
                 "qty": 1}]
    answer = ebay_fill.plan(products, listings, limit=3)
    check("the limit minus what is listed is the room",
          (answer["active"], answer["limit"], answer["room"]) == (1, 3, 2),
          str(answer["active"]))
    check("the dearest unlisted cards fill the room",
          [row["name"] for row in answer["chosen"]] ==
          ["Dear card #1", "Middle card #2"],
          str([row["name"] for row in answer["chosen"]]))
    check("a card already on eBay is not chosen",
          not any(row["id"] == 4 for row in answer["chosen"]), "")
    check("and the ones left below the cut are counted",
          answer["left"] == 1, str(answer["left"]))
    reasons = {row["product"]["id"]: row["why"] for row in answer["skipped"]}
    check("every card that could not be listed carries its reason",
          reasons == {5: "the website has none in stock",
                      6: "it is not published on the website (draft)",
                      7: "it has no price on the website"}, str(reasons))

    full = ebay_fill.plan(products, [{"id": str(n), "name": "x",
                                      "sku": "", "qty": 1}
                                    for n in range(3)], limit=3)
    check("a full store chooses nothing",
          full["room"] == 0 and full["chosen"] == [], str(full["room"]))
    empty = ebay_fill.plan(products, [], limit=250)
    check("an empty store fills up with every listable card, dearest first",
          [row["name"] for row in empty["chosen"]] ==
          ["Dear card #1", "Already listed #4", "Middle card #2",
           "Cheap card #3"],
          str([row["name"] for row in empty["chosen"]]))

    #  The matcher is the one the stock panel uses, so a title that differs
    #  only in the card number is not the same card - and a listing that names
    #  the product by SKU is matched whatever its title says.
    by_sku = ebay_fill.plan(
        [product(id=1, name="A card #1", sku="S-1", price="50.00")],
        [{"id": "1", "name": "Something else entirely", "sku": "S-1",
          "qty": 1}], limit=250)
    check("a listing is matched by its SKU when both sides carry one",
          by_sku["chosen"] == [], str(by_sku["chosen"]))
    by_title = ebay_fill.plan(
        [product(id=1, name="1973-74 O-Pee-Chee Jim Pappin #112",
                 sku="", price="50.00")],
        [{"id": "1", "name": "Jim Pappin 1973-74 O-Pee-Chee #112 Chicago",
          "sku": "", "qty": 1}], limit=250)
    check("a listing is matched by its title when neither carries a SKU",
          by_title["chosen"] == [], str(by_title["chosen"]))
    different = ebay_fill.plan(
        [product(id=1, name="1973-74 O-Pee-Chee Jim Pappin #112",
                 sku="", price="50.00")],
        [{"id": "1", "name": "1973-74 O-Pee-Chee Jim Pappin #114",
          "sku": "", "qty": 1}], limit=250)
    check("two different card numbers are two different cards",
          len(different["chosen"]) == 1, str(different["chosen"]))

    #  A quantity of zero on a listing is still a listing: an ended one is not
    #  in the active list at all.
    zero = ebay_fill.plan([product(id=1, name="A card #1", price="5.00")],
                          [{"id": "1", "name": "A card #1", "sku": "",
                            "qty": 0}], limit=250)
    check("a zero-quantity active listing still counts as listed",
          zero["chosen"] == [], str(zero["chosen"]))

    text = ebay_fill.summary(answer)
    check("the summary says how full the store is and how much room is left",
          "1 active listing" in text and "room for 2 more" in text and
          "limit of 3" in text, text)
    check("and names the price range of the cards chosen",
          "$900.00" in text and "$500.00" in text, text)
    check("and counts what stayed behind",
          "1 more unlisted card" in text, text)
    check("a full store is told plainly that it is full",
          "The store is full" in ebay_fill.summary(full), "")
    check("an empty shop with no listings says so rather than inventing one",
          "no product" in ebay_fill.summary(
              ebay_fill.plan([], [], limit=250)), "")


def test_the_criteria():
    print()
    print("== 3b. what decides which cards come first ==")
    old_dear = product(id=1, name="Old dear #1", price="900.00",
                       date_created="2024-01-02T10:00:00",
                       categories=[{"name": "Hockey Cards"}])
    new_cheap = product(id=2, name="New cheap #2", price="5.00",
                        date_created="2026-10-30T09:00:00",
                        categories=[{"name": "Baseball Cards"}])
    middle = product(id=3, name="Middle #3", price="50.00",
                     date_created="2025-06-01T12:00:00",
                     categories=[{"name": "Hockey Cards"}])
    undated = product(id=4, name="Undated #4", price="80.00",
                      date_created="", categories=[{"name": "Football Cards"}])
    catalogue = [old_dear, new_cheap, middle, undated]

    def names(sort, **kw):
        answer = ebay_fill.plan(catalogue, [], 250, sort=sort, **kw)
        return [row["name"] for row in answer["chosen"]], answer

    order, _answer = names("dearest")
    check("dearest first is the default, and sorts by price",
          order == ["Old dear #1", "Undated #4", "Middle #3", "New cheap #2"],
          str(order))
    check("cheapest first is the same list the other way",
          names("cheapest")[0] == ["New cheap #2", "Middle #3", "Undated #4",
                                   "Old dear #1"], str(names("cheapest")[0]))
    order, _ = names("newest")
    check("newest first puts the most recently created products on top",
          order[:2] == ["New cheap #2", "Middle #3"], str(order))
    check("and a product with no date sorts last, not as the newest",
          order[-1] == "Undated #4", str(order))
    order, _ = names("oldest")
    check("oldest first is the earliest created first",
          order[:2] == ["Old dear #1", "Middle #3"], str(order))
    check("and the undated one is last here too, not the oldest",
          order[-1] == "Undated #4", str(order))

    #  -- the typed list
    order, answer = names("custom", wanted="Middle #3, New cheap #2")
    check("the typed cards come first, in the order typed",
          order[:2] == ["Middle #3", "New cheap #2"], str(order))
    check("and everything else follows, dearest first",
          order[2:] == ["Old dear #1", "Undated #4"], str(order))
    check("nothing is missing when every typed card is there",
          answer["wanted_missing"] == [], str(answer["wanted_missing"]))
    order, answer = names("custom", wanted="Middle #3, Nosuch #9")
    check("a typed card that is not there is named, not silently dropped",
          answer["wanted_missing"] == ["Nosuch #9"],
          str(answer["wanted_missing"]))
    check("a typed SKU finds its card",
          names("custom", wanted="OPC1973-74-112-Pappin-EX-5")[0][0] ==
          "Old dear #1", "")
    check("a typed product id finds its card",
          names("custom", wanted="3")[0][0] == "Middle #3", "")
    check("a typed list split on commas and new lines",
          ebay_fill.wanted_terms("a, b\nc;d\n\n b ") == ["a", "b", "c", "d"],
          str(ebay_fill.wanted_terms("a, b\nc;d\n\n b ")))
    check("and no typed list means the default order",
          names("custom", wanted="")[0] == names("dearest")[0], "")

    #  -- the category filter
    order, answer = names("dearest", only_category="hockey")
    check("only the category named is considered",
          order == ["Old dear #1", "Middle #3"], str(order))
    check("the count left outside it is carried",
          answer["outside"] == 2, str(answer["outside"]))
    check("part of a category's name is enough, in any case",
          names("dearest", only_category="BASEBALL")[0] == ["New cheap #2"], "")
    check("a category nothing is filed under leaves nothing",
          names("dearest", only_category="stamps")[0] == [], "")
    check("a blank filter considers the whole catalogue",
          names("dearest", only_category="")[0] == names("dearest")[0], "")

    #  -- what the settings hold, and what a hand-edited value means
    check("each order is read back from its own label",
          [ebay_fill.sort_key(label) for label in ebay_fill.sort_labels()] ==
          ["dearest", "newest", "oldest", "cheapest", "custom"],
          str([ebay_fill.sort_key(label) for label in ebay_fill.sort_labels()]))
    check("words a person might have written mean the same thing",
          ebay_fill.sort_key("Most expensive") == "dearest" and
          ebay_fill.sort_key("Newest") == "newest" and
          ebay_fill.sort_key("newest first") == "newest" and
          ebay_fill.sort_key("Price low") == "cheapest", "")
    check("an order nobody knows falls back to dearest rather than failing",
          ebay_fill.sort_key("sideways") == "dearest" and
          ebay_fill.sort_key(None) == "dearest", "")
    check("the chooser shows the label for a stored key",
          ebay_fill.sort_label("newest") == "Newest first" and
          ebay_fill.sort_label("nonsense") == "Dearest first", "")

    text = ebay_fill.summary(names("newest")[1])
    check("the summary says which order chose the cards",
          "Chosen newest first." in text, text)
    text = ebay_fill.summary(names("custom", wanted="Middle #3, Nosuch")[1])
    check("and says when the order was the one typed",
          "Chosen in the order you typed." in text, text)
    check("and names the typed cards that were not found",
          "1 typed card was not among the unlisted ones: Nosuch" in text, text)
    text = ebay_fill.summary(names("dearest", only_category="hockey")[1])
    check("the category filter is stated with what it left out",
          "matching \u201chockey\u201d" in text and
          "left out 2 other products" in text, text)


def test_the_values_and_the_page():
    print()
    print("== 4. the fields, and the page they go on ==")
    values = ebay_fill.values(product(), SETTINGS)
    check("the title, price and SKU come from the product",
          (values["title"].startswith("1973-74 O-Pee-Chee"), values["price"],
           values["sku"]) == (True, "1250.00",
                              "OPC1973-74-112-Pappin-EX-5"),
          str(values))
    check("the card's own facts come from its attributes",
          (values["player"], values["card_number"], values["year"],
           values["set"], values["condition"]) ==
          ("Jim Pappin", "112", "1973-74", "O-Pee-Chee", "EX 5"), str(values))
    check("what the product does not say falls back to the saved default",
          values["manufacturer"] == "Unknown" and
          values["autographed"] == "No", str(values["manufacturer"]))
    check("the sport decides the template, and the template is the saved one",
          values["sport"] == "Hockey" and
          ebay_fill.template_url(product(), SETTINGS) ==
          "https://ebay.example/hockey", "")
    check("a product naming no sport gets the default template",
          ebay_fill.template_url({"name": "A card"}, SETTINGS) ==
          "https://ebay.example/default", "")
    check("no template configured is no template, not a guess",
          ebay_fill.template_url({"name": "A card"}, {}) == "", "")
    check("the description is the product's own words, tags stripped",
          values["description"] == "Sharp corners & a clean back.", str(
              values["description"]))
    check("both of the shop's pictures travel with it",
          (values["front_image"], values["back_image"]) ==
          ("https://shop.example/a.jpg", "https://shop.example/b.jpg"), "")

    page, templates = ebay_fill.render([product()], SETTINGS)
    check("the page is the Quick List page: draggable, click-to-copy fields",
          'draggable="true"' in page and "click to copy" in page, "")
    check("it carries the card's own fields",
          "Jim Pappin" in page and "1250.00" in page and
          "OPC1973-74-112-Pappin-EX-5" in page, "")
    check("and its pictures are the shop's URLs",
          "https://shop.example/a.jpg" in page and
          "https://shop.example/b.jpg" in page, "")
    check("an ampersand in a description is escaped, not left to break the page",
          "sharp corners &amp; a clean back" in page.lower() and
          "sharp corners & a clean back" not in page.lower(), "")
    check("the template link is on the card, once",
          templates == ["https://ebay.example/hockey"] and
          "https://ebay.example/hockey" in page, str(templates))
    check("a page without a template says so instead of linking nowhere",
          "No eBay template is set" in
          ebay_fill.render([{"name": "A card", "price": "5.00"}], {})[0], "")

    print()
    print("== 4b. the whole description, not a preview of it ==")
    #  A card's write-up is a page of words: the website's marketing prose, a
    #  condition report, and a line at the very end. The eBay form has room for
    #  all of it, so the page it is copied from must hold all of it.
    long_words = " ".join("Sentence %d about the card." % number
                          for number in range(1, 61))
    long_body = ("<p>The full write-up of this card.</p>"
                 "<p>Condition Report: sharp corners and a clean back.</p>"
                 "<p>%s</p><p>THE LAST LINE OF IT</p>" % long_words)
    full = ebay_fill.values(product(description=long_body), SETTINGS)
    check("the full description is what the page offers, not just the summary",
          full["description"].startswith("The full write-up of this card."),
          full["description"][:60])
    check("nothing is cut off the end of a long description",
          "THE LAST LINE OF IT" in full["description"] and
          "\u2026" not in full["description"] and
          len(full["description"]) > 900, str(len(full["description"])))
    check("the description keeps the paragraphs the website has it in",
          ("The full write-up of this card.\n\nCondition Report: sharp corners "
           "and a clean back.") in full["description"],
          repr(full["description"][:90]))
    check("a summary that says something else is kept beside it",
          full["short_description"] == "Sharp corners & a clean back.",
          repr(full["short_description"]))
    check("a summary already inside the full text is not shown twice",
          ebay_fill.values(
              product(description="<p>Sharp corners &amp; a clean back.</p>"),
              SETTINGS)["short_description"] == "", "")
    check("a product with only a summary uses it as its description",
          ebay_fill.values(product(), SETTINGS)["description"] ==
          "Sharp corners & a clean back.", "")
    check("a product with no words at all has no description, not a placeholder",
          (ebay_fill.values({"name": "A card"}, SETTINGS)["description"],
           ebay_fill.values({"name": "A card"}, SETTINGS)["short_description"])
          == ("", ""), "")
    check("a line break in the description stays a line",
          ebay_fill.plain_description("<p>Line one<br>Line two</p>") ==
          "Line one\nLine two", "")
    check("markup and scripts are not words: only the text is kept",
          ebay_fill.plain_description(
              "<p>A card</p><script>track()</script><style>p{}</style>"
              "<p>From 1973</p>") == "A card\n\nFrom 1973", "")

    page, _ = ebay_fill.render([product(description=long_body)], SETTINGS)
    check("the page carries the whole description, last line and all",
          "THE LAST LINE OF IT" in page and
          "The full write-up of this card." in page, "")
    check("the description box is not a scrolling window over half the words",
          "max-height:260px" not in page and
          'class="description snippet"' in page, "")
    check("the page says how many words of description there are",
          "all %d word" % len(full["description"].split()) in page, "")
    check("the summary travels too, as its own click-to-copy field",
          "Short description" in page and
          "Sharp corners &amp; a clean back." in page, "")
    noisy = "<p>Condition Report: fine.</p><script>track()</script>"
    noisy_page, _ = ebay_fill.render([product(description=noisy)], SETTINGS)
    check("markup from the product never reaches the page",
          "<p>Condition Report" not in noisy_page and
          "track()" not in noisy_page, "")

    page_short, _ = ebay_fill.render([product()], SETTINGS)
    check("a product with only a summary gets one description, not two",
          "Short description" not in page_short and
          "all %d word" % len("Sharp corners & a clean back.".split())
          in page_short, "")
    page_none, _ = ebay_fill.render([{"name": "A card", "price": "5.00"}],
                                    SETTINGS)
    check("a card with no description says so instead of showing an empty box",
          "no description for this card" in page_none and
          'class="description snippet"' not in page_none, "")

    page, _ = ebay_fill.render([], SETTINGS, note="Nothing fits.")
    check("a page with nothing on it still says why",
          "Nothing fits." in page and "<article>" not in page, "")
    page, _ = ebay_fill.render([product()], SETTINGS, note="A <b>note</b>")
    check("the note is text, not markup",
          "A &lt;b&gt;note&lt;/b&gt;" in page, "")

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        first = ebay_fill.write_page("<html></html>", folder)
        second = ebay_fill.write_page(
            "<html></html>", folder, built=datetime(2026, 11, 2, 9, 30, 5))
        check("each page is written with the minute in its name",
              first.name.startswith("ebay_fill_") and
              first.suffix == ".html" and
              second.name == "ebay_fill_20261102_093005.html", second.name)
        check("and both are kept, not overwritten",
              len(list(folder.glob("ebay_fill_*.html"))) == 2, "")


def sync_background(app, work, done):
    """Run a background job the way the window's thread would have.

    The real ``in_background`` catches whatever the work raises and hands it
    to the caller's ``done``; a test that let it escape would never reach the
    error path this panel is supposed to explain.
    """
    try:
        result, error = work(), None
    except Exception as exc:
        result, error = None, exc
    return done(result, error)


def build_panel(folder, limit=250):
    app = harness.FakeApp(folder)
    app.settings["ebay_listing_limit"] = limit
    parent = harness.FakeWidget()
    with patch.object(gui, "BASE", folder), \
            patch.object(gui, "save_settings", lambda s: None):
        gui.build_ebayfill(parent, app)
    return app, parent


def field_after(parent, caption, kind="FakeEntry"):
    """The input sitting beside a caption, in the same row, as a person sees it.

    Found by the caption rather than by position: the panel has several one-line
    boxes, and "the third entry" is a fact about the layout rather than about
    the setting being tested.
    """
    for frame in parent.walk():
        texts = [str(child.cget("text")) for child in getattr(frame, "children", [])
                 if type(child).__name__ == "FakeLabel"]
        if str(caption) not in texts:
            continue
        for child in frame.children:
            if type(child).__name__ == kind:
                return child
    return None


def limit_box(parent):
    """The entry that holds the listing limit, as the person sees it."""
    entry = field_after(parent, "Active listings eBay allows:")
    return None if entry is None else entry._kw.get("textvariable")


def sort_box(parent):
    """The order chooser, as a person sees it: its own variable, and its values."""
    box = field_after(parent, "Choose the cards:", "FakeCombobox")
    return box


def category_box(parent):
    entry = field_after(parent, "Only this category:")
    return None if entry is None else entry._kw.get("textvariable")


def wanted_box(parent):
    entry = field_after(parent, "These cards first:")
    return None if entry is None else entry._kw.get("textvariable")


def find(parent, kind, text):
    """The first widget of that Tk class carrying that label, or None.

    By class *name* rather than the class itself: the harness builds one fake
    class per Tk widget, and importing ttk here would import the real one.
    """
    for widget in parent.walk():
        if type(widget).__name__ == kind and \
                str(widget.cget("text")) == text:
            return widget
    return None


def test_the_panel():
    print()
    print("== 5. the panel: choosing, and opening what it chose ==")
    folder = Path(tempfile.mkdtemp())
    app, parent = build_panel(folder)
    button = find(parent, "FakeButton", "Find the cards to list next")
    check("the panel offers the one job it does", button is not None, "")
    check("and says what it changes: nothing",
          "Nothing is listed" in str(
              [w.cget("text") for w in parent.walk()
               if type(w).__name__ == "FakeLabel"]), "")
    check("its tooltip says the same",
          "nothing is listed or changed" in gui.tip_for(
              "Find the cards to list next"), "")
    box = limit_box(parent)
    check("the limit shows the saved setting",
          box is not None and str(box.get()) == "250",
          str(None if box is None else box.get()))

    #  -- without the website's keys nothing is read and nothing is written
    app.lines[:] = []
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("", "", "")):
        button.invoke()
    check("without keys it says what is missing",
          any("No WooCommerce keys saved" in text for _tag, text in app.lines),
          str(app.lines[-1:]))
    check("and writes no page at all",
          not any((folder / "ebay_fill").glob("ebay_fill_*.html"))
          if (folder / "ebay_fill").is_dir() else True, "")

    #  -- with keys: it reads, chooses, writes the page and opens it
    products = [
        product(id=1, name="Dear card #1", price="900.00"),
        product(id=2, name="Middle card #2", price="500.00"),
        product(id=3, name="Cheap card #3", price="10.00"),
        product(id=4, name="Already listed #4", price="800.00", sku="L-4"),
        product(id=5, name="Sold out #5", price="700.00", stock_quantity=0),
    ]
    listings = [{"id": "1", "name": "Already listed #4", "sku": "L-4",
                 "qty": 1}]
    opened = []
    app.lines[:] = []
    app, parent = build_panel(folder, limit=3)
    button = find(parent, "FakeButton", "Find the cards to list next")
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck", "cs")), \
            patch.object(market_stock, "read_cookie", lambda path: "a=1"), \
            patch.object(market_stock, "read_ebay",
                         lambda fetch, url, cookie: (listings, 1, "<html>")), \
            patch.object(gui.woo_create, "read_all_products",
                         lambda site, key, secret, progress=None, **kw:
                         products), \
            patch.object(gui, "open_path", lambda path:
                         opened.append(Path(path)) or True), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "save_settings", lambda s: None):
        button.invoke()
    check("it reads the store's listings and the whole catalogue",
          any("eBay: 1 active listing" in text for _tag, text in app.lines) and
          any("website: 5 products" in text for _tag, text in app.lines),
          str(app.lines[:3]))
    wrote = sorted((folder / "ebay_fill").glob("ebay_fill_*.html"))
    check("it writes the page beside the app", len(wrote) == 1, str(wrote))
    check("and opens it", len(opened) == 1 and opened[0] == wrote[0],
          str(opened))
    page = wrote[0].read_text(encoding="utf-8")
    check("the page holds the two cards that fit, dearest first",
          page.index("Dear card #1") < page.index("Middle card #2") and
          "Cheap card #3" not in page, "")
    check("a card already on eBay and a sold-out card are not on it",
          "Already listed #4" not in page and "Sold out #5" not in page, "")
    check("the console names the cards it chose, with their prices",
          any("Dear card #1" in text and "900.00" in text
              for _tag, text in app.lines), str(app.lines[-6:]))
    check("and says plainly that nothing was listed",
          any("Nothing was listed" in text for _tag, text in app.lines),
          str(app.lines[-2:]))
    check("the summary counts what could not be listed",
          any("could not be listed" in text and "none in stock" in text
              for _tag, text in app.lines), str(app.lines[-4:]))

    #  -- a store that cannot be read live falls back to the saved page
    found = {"path": "C:/Users/Owner/Downloads/Seller Hub eBay.html",
             "items": [{"id": "1", "name": "Already listed #4", "sku": "L-4",
                        "qty": 1}], "text": "", "mtime": 0}
    app.lines[:] = []

    def refuse(fetch, url, cookie):
        raise market_stock.MarketError("eBay refused the request (blocked)",
                                       kind="blocked")

    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck", "cs")), \
            patch.object(market_stock, "read_cookie", lambda path: "a=1"), \
            patch.object(market_stock, "read_ebay", refuse), \
            patch.object(market_stock, "saved_page",
                         lambda site, folders, **kw: found), \
            patch.object(gui.woo_create, "read_all_products",
                         lambda site, key, secret, progress=None, **kw:
                         products), \
            patch.object(gui, "open_path", lambda path: True), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "save_settings", lambda s: None):
        button.invoke()
    check("a refused live read is answered from the saved page",
          any("saved page Seller Hub eBay.html" in text
              for _tag, text in app.lines), str(app.lines[:3]))

    #  -- and nothing to fall back on is said plainly, not guessed at
    app.lines[:] = []
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck", "cs")), \
            patch.object(market_stock, "read_cookie", lambda path: "a=1"), \
            patch.object(market_stock, "read_ebay", refuse), \
            patch.object(market_stock, "saved_page",
                         lambda site, folders, **kw: None), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "save_settings", lambda s: None):
        button.invoke()
    check("with no saved page it says what to do instead of choosing blind",
          any("no saved page" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and nothing was added to the folder on that path",
          len(sorted((folder / "ebay_fill").glob("*.html"))) == 1, "")

    #  -- the limit is a setting, saved where the others are
    seen = {}
    real_plan = ebay_fill.plan

    def fake_plan(products, items, limit, **criteria):
        seen["limit"] = limit
        seen.update(criteria)
        return real_plan(products, items, limit, **criteria)

    app, parent = build_panel(folder)
    button = find(parent, "FakeButton", "Find the cards to list next")
    limit_box(parent).set("200")
    app.lines[:] = []
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck", "cs")), \
            patch.object(market_stock, "read_cookie", lambda path: "a=1"), \
            patch.object(market_stock, "read_ebay",
                         lambda fetch, url, cookie: (listings, 1, "")), \
            patch.object(gui.woo_create, "read_all_products",
                         lambda site, key, secret, progress=None, **kw:
                         products), \
            patch.object(gui.ebay_fill, "plan", fake_plan), \
            patch.object(gui, "open_path", lambda path: True), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder), \
            patch.object(gui, "save_settings", lambda s: None):
        button.invoke()
    check("the limit typed on the panel is the one the selection uses",
          seen.get("limit") == 200, str(seen))
    check("and it is remembered in the settings",
          app.settings.get("ebay_listing_limit") == 200,
          str(app.settings.get("ebay_listing_limit")))
    check("a nonsense limit falls back to what a free store holds",
          ebay_fill.limit_of("lots") == 250 and ebay_fill.limit_of("0") == 250
          and ebay_fill.limit_of("") == 250, "")


def test_the_panel_criteria_and_templates():
    print()
    print("== 6. the panel: which cards, in what order, and the template tabs ==")
    folder = Path(tempfile.mkdtemp())
    app, parent = build_panel(folder, limit=250)
    app.settings["ebay_template_hockey_url"] = "https://ebay.example/hockey"
    app.settings["ebay_template_default_url"] = "https://ebay.example/default"
    button = find(parent, "FakeButton", "Find the cards to list next")

    choices = sort_box(parent)
    check("the panel offers the order chooser, with every order in it",
          choices is not None and list(choices._kw.get("values") or []) ==
          ebay_fill.sort_labels(),
          str(None if choices is None else choices._kw.get("values")))
    check("and it starts on the saved order",
          str(choices._kw["textvariable"].get()) == "Dearest first", "")
    check("the category and typed boxes are there, and empty to begin with",
          str(category_box(parent).get()) == "" and
          str(wanted_box(parent).get()) == "", "")

    products = [
        product(id=1, name="Dear hockey #1", price="900.00",
                categories=[{"name": "Hockey Cards"}],
                date_created="2024-01-01T10:00:00"),
        product(id=2, name="New hockey #2", price="40.00",
                categories=[{"name": "Hockey Cards"}],
                date_created="2026-10-30T09:00:00"),
        product(id=3, name="Baseball card #3", price="70.00",
                categories=[{"name": "Baseball Cards"}],
                date_created="2025-05-05T09:00:00"),
    ]
    #  What the fake website hands back; the last case empties the shop.
    shelf = {"products": products, "listings": []}
    seen = {}
    real_plan = ebay_fill.plan

    def watch_plan(items_products, listings, limit, **criteria):
        seen.update(criteria)
        seen["limit"] = limit
        return real_plan(items_products, listings, limit, **criteria)

    def run():
        app.lines[:] = []
        app.opened[:] = []
        with patch.object(gui, "read_woo_credentials",
                          lambda path=None: ("https://shop.example", "ck",
                                             "cs")), \
                patch.object(market_stock, "read_cookie", lambda path: "a=1"), \
                patch.object(market_stock, "read_ebay",
                             lambda fetch, url, cookie:
                             (list(shelf["listings"]), 0, "")), \
                patch.object(gui.woo_create, "read_all_products",
                             lambda site, key, secret, progress=None, **kw:
                             shelf["products"]), \
                patch.object(gui.ebay_fill, "plan", watch_plan), \
                patch.object(gui, "open_path", lambda path: True), \
                patch.object(gui, "in_background", sync_background), \
                patch.object(gui, "BASE", folder), \
                patch.object(gui, "save_settings", lambda s: None):
            button.invoke()

    #  -- newest, in one category, with two cards typed first
    choices._kw["textvariable"].set("Newest first")
    choices.event_generate("<<ComboboxSelected>>")   # as a real chooser does
    category_box(parent).set("hockey")
    wanted_box(parent).set("Dear hockey #1")
    run()
    check("the chooser's order is what the selection uses",
          ebay_fill.sort_key(seen.get("sort")) == "newest", str(seen.get("sort")))
    check("the category typed on the panel narrows the catalogue",
          seen.get("only_category") == "hockey", str(seen))
    check("and the typed cards travel with it",
          seen.get("wanted") == "Dear hockey #1", str(seen))
    check("choosing an order remembers it with the other settings",
          app.settings.get("ebay_fill_sort") == "newest",
          str(app.settings.get("ebay_fill_sort")))
    wrote = sorted((folder / "ebay_fill").glob("ebay_fill_*.html"))
    page = wrote[-1].read_text(encoding="utf-8") if wrote else ""
    check("the baseball card is not on the page: it is outside the category",
          "Baseball card #3" not in page and "Dear hockey #1" in page, "")
    check("the baseball card is counted as left out, on the console",
          any("left out 1 other product" in text for _tag, text in app.lines),
          str(app.lines[-3:]))

    #  -- the template pages open, once each, and only for the chosen sports
    check("the template for the cards' sport is opened",
          "https://ebay.example/hockey" in app.opened, str(app.opened))
    check("and the one template is opened once, not once per card",
          app.opened.count("https://ebay.example/hockey") == 1, str(app.opened))
    check("the console says the template pages were opened",
          any("Opened 1 eBay template page" in text for _tag, text in app.lines),
          str(app.lines[-4:]))
    check("and repeats that nothing is submitted there",
          any("Nothing is submitted there without you" in text
              for _tag, text in app.lines), str(app.lines[-2:]))

    #  -- no template configured is said, not silently skipped
    app.settings["ebay_template_hockey_url"] = ""
    app.settings["ebay_template_default_url"] = ""
    category_box(parent).set("")
    wanted_box(parent).set("")
    choices._kw["textvariable"].set("Dearest first")
    run()
    check("with no template set the page still opens",
          any((folder / "ebay_fill").glob("ebay_fill_*.html")) and
          len(app.opened) == 0, str(app.opened))
    check("and the console says a template would open it next time",
          any("No eBay template is set" in text for _tag, text in app.lines),
          str(app.lines[-3:]))

    #  -- a shop whose every product is already listed chooses nothing, and a
    #     selection with nothing on it opens no page and no template.
    app.settings["ebay_template_hockey_url"] = "https://ebay.example/hockey"
    shelf["listings"] = [{"id": str(row["id"]), "name": row["name"],
                          "sku": row["sku"], "qty": 1} for row in products]
    before = len(sorted((folder / "ebay_fill").glob("*.html")))
    run()
    check("a shop with every card already on eBay chooses nothing",
          any("No unlisted product was ready" in text
              for _tag, text in app.lines), str(app.lines[-3:]))
    check("no template is opened for a selection with no cards",
          len(app.opened) == 0, str(app.opened))
    check("and no page is written for it",
          len(sorted((folder / "ebay_fill").glob("*.html"))) == before, "")


def main():
    try:
        test_prices_and_titles()
        test_what_can_be_listed()
        test_the_selection()
        test_the_criteria()
        test_the_values_and_the_page()
        test_the_panel()
        test_the_panel_criteria_and_templates()
    except AssertionError:
        raise
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL EBAY FILL CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
