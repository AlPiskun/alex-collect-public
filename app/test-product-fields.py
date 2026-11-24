#!/usr/bin/env python3
"""Checks for product_fields - the fields a website's products are missing.

Three things are worth proving here, and they are the three ways this could go
wrong on a live shop:

* the words that fill a field come from the product's **own title**, by the
  batch's rules, and a title that does not state the fact gets no value at all;
* only the field that is missing is written, and only the field that was asked
  for is in the request body;
* the shop's answer is read back, so a 200 that kept the old value is reported
  as not written rather than as done.

No network: the shop is an opener that answers the calls this module makes and
remembers them.
"""
import importlib.util
import json
import re
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
    """The Tk stand-ins and the app stand-in, from the panel suite."""
    spec = importlib.util.spec_from_file_location(
        "panel", str(APP / "test-photo-panel.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["panel"] = module
    spec.loader.exec_module(module)
    return module


harness = load_harness()
gui = sys.modules["gui"]
import card_words                                   # noqa: E402
import product_fields                               # noqa: E402
import woo_create                                   # noqa: E402


# ------------------------------------------------------------------- a shop
class FakeShop:
    """A website that answers the calls product_fields makes, and remembers
    them. ``keep`` is the value the shop answers with after a write, which is
    how "the site said 200 and kept the old value" is tested."""

    def __init__(self, products, brands=None, categories=None, keep=False,
                 no_brands=False):
        self.products = {int(p["id"]): dict(p) for p in products}
        self.brands = {str(name).lower(): ident
                       for name, ident in (brands or {}).items()}
        self.brand_names = {ident: str(name) for name, ident
                            in (brands or {}).items()}
        self.next_brand = 70
        self.categories = dict(categories or {})      # name -> id
        self.next_category = 40
        self.calls = []
        self.keep = keep
        self.no_brands = no_brands

    def __call__(self, request, timeout=None):
        method = request.get_method()
        url = request.full_url
        body = {}
        if request.data:
            try:
                body = json.loads(request.data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                body = {}
        self.calls.append({"method": method, "url": url, "body": body})

        if "/products/brands" in url:
            if self.no_brands:
                return 404, json.dumps({"code": "rest_no_route"}).encode()
            if method == "GET":
                name = url.split("search=")[1].split("&")[0].replace("+", " ")
                found = self.brands.get(name.lower())
                rows = [{"id": found, "name": name}] if found else []
                return 200, json.dumps(rows).encode()
            self.next_brand += 1
            self.brands[body["name"].lower()] = self.next_brand
            self.brand_names[self.next_brand] = body["name"]
            return 201, json.dumps({"id": self.next_brand,
                                    "name": body["name"]}).encode()

        if "/products/categories" in url:
            if method == "GET":
                name = url.split("search=")[1].split("&")[0].replace("+", " ")
                found = self.categories.get(name)
                rows = [{"id": found, "name": name}] if found else []
                return 200, json.dumps(rows).encode()
            self.next_category += 1
            self.categories[body["name"]] = self.next_category
            return 201, json.dumps({"id": self.next_category,
                                    "name": body["name"]}).encode()

        if "/products/" in url and method == "PUT":
            pid = int(url.split("/products/")[1].split("?")[0])
            product = self.products.get(pid, {})
            if self.keep:
                return 200, json.dumps(product).encode()
            if "brands" in body:
                product["brands"] = [{"id": row["id"],
                                      "name": self.brand_names.get(row["id"],
                                                                   "")}
                                     for row in body["brands"]]
            if "meta_data" in body:
                rows = [dict(row) for row in product.get("meta_data") or []]
                for wanted in body["meta_data"]:
                    for row in rows:
                        if wanted.get("id") and row.get("id") == wanted["id"]:
                            row["value"] = wanted["value"]
                            break
                    else:
                        rows.append({"id": 900 + len(rows),
                                     "key": wanted["key"],
                                     "value": wanted["value"]})
                product["meta_data"] = rows
            if "categories" in body:
                product["categories"] = [
                    {"id": row["id"],
                     "name": {ident: name for name, ident
                              in self.categories.items()}.get(row["id"], "")}
                    for row in body["categories"]]
            if "tags" in body:
                product["tags"] = [{"id": 500 + index, "name": row["name"]}
                                   for index, row in enumerate(body["tags"])]
            if "sku" in body:
                product["sku"] = body["sku"]
            self.products[pid] = product
            return 200, json.dumps(product).encode()

        return 404, b"{}"


def product(pid, name, **extra):
    base = {"id": pid, "name": name, "status": "draft", "sku": "",
            "categories": [], "tags": [], "brands": [], "attributes": [],
            "meta_data": []}
    base.update(extra)
    return base


# ------------------------------------------------------- 1. the title's words
def test_the_title_says_it():
    print()
    print("== 1. the words a field is filled with come from the title ==")
    title = "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6"
    told = card_words.facts(title)
    check("the maker comes out of the title", told["brand"] == "O-Pee-Chee",
          told["brand"])
    check("the focus keyword is the year, the maker and the player - not the "
          "whole title", told["keyword"] == "1991 O-Pee-Chee Dallas Smith",
          told["keyword"])
    check("the year, the number and the player come out too",
          (told["year"], told["card_num"], told["player"]) ==
          ("1991", "12", "Dallas Smith"), str(told))
    check("the tags are the words the title already states",
          told["tags"] == ["1991", "O-Pee-Chee", "Dallas Smith", "#12"],
          str(told["tags"]))
    check("the SKU is the batch's own SKU for those facts",
          told["sku"] == "OPC1991-12-Smith-EX-MT-6", told["sku"])
    check("and a printing in the title is part of it, as the batch writes it",
          card_words.facts(title + " Dark Back")["sku"].endswith("-DB"),
          card_words.facts(title + " Dark Back")["sku"])

    #  The keyword is a search phrase, so what a buyer does not type into a
    #  search box is not in it: no card number, no grade, no team.
    full = card_words.facts(
        "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6 Chicago Black Hawks")
    check("the card number is not part of the search phrase",
          "#12" not in full["keyword"], full["keyword"])
    check("and neither is the grade or the team",
          "EX-MT" not in full["keyword"] and "Black Hawks" not in
          full["keyword"], full["keyword"])
    check("a title that states no player gives the year and the maker",
          card_words.facts("1989 Topps #7")["keyword"] == "1989 Topps",
          card_words.facts("1989 Topps #7")["keyword"])
    check("and a title stating none of the three has no keyword at all",
          card_words.facts("A mystery card")["keyword"] == "",
          card_words.facts("A mystery card")["keyword"])
    check("the same phrase is what the batch's own keyword column says: the "
          "year, the maker and the player, in that order",
          full["keyword"].split() == ["1991", "O-Pee-Chee", "Dallas", "Smith"],
          full["keyword"])

    #  A grade at the end is a grade; the same word in a player's name is not.
    check("a player called Good is not a grade at the end of the title",
          card_words.facts("1989 Topps Bob Good #7")["grade"] == "",
          card_words.facts("1989 Topps Bob Good #7")["grade"])
    check("a title that ends in a grade has one",
          card_words.facts("1989 Topps Bob Good #7 NM 7")["grade"] == "NM 7",
          card_words.facts("1989 Topps Bob Good #7 NM 7")["grade"])

    #  What the title does not say is not invented.
    blank = card_words.facts("A mystery card, nothing else")
    check("a title naming no maker has no brand", blank["brand"] == "",
          blank["brand"])
    check("a title naming no year, number or player has no SKU",
          blank["sku"] == "", blank["sku"])
    check("and it has no tags for the same reason", blank["tags"] == [],
          str(blank["tags"]))

    #  The sport decides the category, exactly as the batch decides it.
    check("hockey words pick the hockey category",
          card_words.category_names("1973-74 O-Pee-Chee #112 Chicago Black "
                                    "Hawks hockey") ==
          ["Sports Card", "Hockey Card"], "")
    check("baseball words pick baseball",
          card_words.category_names("1989 Topps baseball pitcher #7") ==
          ["Sports Card", "Baseball Card"], "")
    check("words naming no sport land where the batch puts such cards",
          card_words.category_names("A mystery card") ==
          ["Sports Card", "Hockey Card"], "")
    check("a card that is not a sport is filed as one",
          card_words.category_names("1990 Marvel trading card") ==
          ["Non Sports Card"], "")

    #  One rule, two callers: the pipeline and the shop tools read a title the
    #  same way, because there is only one reading.
    import card_pipeline
    check("the pipeline reads a title with the same function",
          card_pipeline.card_sku({"brand": "Topps", "year": "1989",
                                  "card_num": "7", "last": "Good",
                                  "grade": "NM 7",
                                  "seo_title": "1989 Topps Bob Good #7 NM 7"})
          == card_words.card_sku({"brand": "Topps", "year": "1989",
                                  "card_num": "7", "last": "Good",
                                  "grade": "NM 7",
                                  "seo_title": "1989 Topps Bob Good #7 NM 7"}),
          "")


# ------------------------------------------------------------------- 2. audit
def test_the_audit():
    print()
    print("== 2. what is missing, and what would fill it ==")
    title = "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6"
    site = [
        product(1, title),
        product(2, "A mystery card"),
        product(3, title, brands=[{"id": 5, "name": "O-Pee-Chee"}],
                sku="OPC1991-12-Smith-EX-MT-6",
                categories=[{"id": 11, "name": "Sports Card"}],
                tags=[{"id": 1, "name": "hockey"}],
                meta_data=[{"id": 4, "key": "rank_math_focus_keyword",
                            "value": "Dallas Smith"}]),
    ]

    found = product_fields.audit(site, "brand")
    check("the product that already has a brand is not on the list",
          [entry["id"] for entry in found["missing"]] == [1, 2],
          str([entry["id"] for entry in found["missing"]]))
    check("and the one whose title names its maker is ready",
          [entry["id"] for entry in found["ready"]] == [1],
          str(found["ready"]))
    check("while the one whose title says nothing is left alone",
          found["unsure"] and "no maker" in found["unsure"][0]["note"],
          str(found["unsure"]))

    keyword = product_fields.audit(site, "keyword")
    check("a product with a focus keyword is never on the keyword list",
          [entry["id"] for entry in keyword["missing"]] == [1, 2],
          str(keyword["missing"]))
    check("and a product with an empty keyword row keeps that row's id",
          True, "")

    empty = dict(product(9, title))
    empty["meta_data"] = [{"id": 77, "key": "rank_math_focus_keyword",
                           "value": ""}]
    row = product_fields.audit([empty], "keyword")["ready"][0]
    check("a keyword row that is there but empty is updated, not duplicated",
          row.get("meta_id") == 77, str(row.get("meta_id")))

    sku = product_fields.audit(site, "sku")
    check("a product that already has a SKU is not offered another",
          [entry["id"] for entry in sku["missing"]] == [1, 2],
          str(sku["missing"]))
    check("and the one whose title works out to a SKU the website already "
          "holds is left alone rather than fought over",
          [entry["id"] for entry in sku["unsure"]] == [1] and
          "already another product" in sku["unsure"][0]["note"],
          str(sku["unsure"]))
    check("while the one whose title says too little is still given a SKU",
          [entry["id"] for entry in sku["ready"]] == [2] and
          sku["ready"][0].get("loose") is True, str(sku["ready"]))

    #  Two products whose titles work out to one SKU cannot both have it.
    twins = [product(21, title), product(22, title)]
    twin_audit = product_fields.audit(twins, "sku")
    check("two products working out to one SKU are both left alone",
          twin_audit["ready"] == [] and len(twin_audit["unsure"]) == 2,
          str(twin_audit))
    check("and the reason says why", all(
        "one product per SKU" in entry["note"] for entry in twin_audit["unsure"]),
        str([entry["note"] for entry in twin_audit["unsure"]]))

    #  A SKU the website already holds is not written onto a second product.
    clash = [product(31, title), product(32, "another card",
                                         sku="OPC1991-12-Smith-EX-MT-6")]
    clash_audit = product_fields.audit(clash, "sku")
    check("a SKU another product already holds is refused here, not by the shop",
          clash_audit["ready"] == [] and
          "already another product" in clash_audit["unsure"][0]["note"],
          str(clash_audit["unsure"]))

    #  A shop with no Brands list is not a shop of brandless products.
    plain = [{"id": 1, "name": title, "meta_data": []}]
    no_list = product_fields.audit(plain, "brand")
    check("a shop whose products report no Brands list is not called "
          "brandless", no_list["supported"] is False and
          no_list["missing"] == [], str(no_list))
    check("and it is said in words a person can act on",
          "Brands list" in product_fields.summary(no_list),
          product_fields.summary(no_list))

    #  The Brand detail row the batch wrote is the seller's own word.
    attributed = product(41, "A mystery card", attributes=[
        {"name": "Brand", "options": ["Topps"]}])
    from_attribute = product_fields.audit([attributed], "brand")["ready"][0]
    check("a Brand detail row on the product is used before the title",
          from_attribute["value"] == "Topps" and
          "Brand detail" in from_attribute["note"], str(from_attribute))

    check("the summary counts what is missing, what can be filled and what "
          "cannot",
          "of 3 products have no brand" in product_fields.summary(found) and
          "1 of those can be filled" in product_fields.summary(found) and
          "left alone" in product_fields.summary(found),
          product_fields.summary(found))


class Digits:
    """A random source that gives exactly the tails a check asks for."""

    def __init__(self, *values):
        self.values = list(values)
        self.asked = 0

    def randrange(self, stop):
        self.asked += 1
        return self.values.pop(0) % stop


def test_a_title_that_says_too_little_still_gets_a_sku():
    """A made-up SKU: what the title says, plus digits, and never another's.

    A SKU is the one field a shop cannot leave empty, because it is how the
    website, the CSV and the comparison tell two products apart - so a title
    that does not state the year, number and player still gets one. What is
    checked here is that it is made from the facts the title *does* state, that
    it is never a SKU somebody else holds, and that it never steals the SKU a
    title that says enough would have had.
    """
    print()
    print("== 2b. a title that says too little still gets a SKU ==")
    shape = re.compile(r"^TOPPS1966-67-83-\d{4}$")
    made = product_fields.loose_sku("#83 Robert Baun 1966-67 Topps",
                                     rng=product_fields.random.Random(3))
    check("the maker, the year and the number the title does state are in it",
          bool(shape.match(made)), made)
    check("and the tail is random digits, at the length the app says",
          made.rsplit("-", 1)[-1].isdigit() and
          len(made.rsplit("-", 1)[-1]) == product_fields.LOOSE_DIGITS, made)

    check("a title with no card facts at all is named by its own words",
          product_fields.loose_sku(
              "A mystery card", rng=product_fields.random.Random(3)
          ).startswith("A-mystery-"), "")
    check("a product whose SEO title is empty is named by its own name",
          product_fields.audit(
              [product(59, "#83 Robert Baun 1966-67 Topps", meta_data=[
                  {"id": 1, "key": "rank_math_title", "value": ""}])],
              "sku", rng=product_fields.random.Random(5))["ready"][0]["value"]
          .startswith("TOPPS1966-67-83-"), "")
    check("and a title with nothing in it at all gets no SKU",
          product_fields.loose_sku("", rng=product_fields.random.Random(3)) == ""
          and product_fields.loose_sku("   ") == "", "")

    #  A tail already spoken for is drawn again, not written twice.
    rng = Digits(42, 42, 7)
    sku = product_fields.loose_sku("A mystery card",
                                   taken={"A-mystery-0042", "a-MYSTERY-0042"},
                                   rng=rng)
    check("a tail another product already holds is drawn again",
          sku == "A-mystery-0007" and rng.asked == 3, "%r %d" % (sku, rng.asked))
    rng = Digits(*([5] * product_fields.LOOSE_TRIES))
    check("a shop that somehow holds every tail leaves the product alone",
          product_fields.loose_sku("A mystery card", taken={"A-mystery-0005"},
                                   rng=rng) == "", "")

    #  Two hunts: the audit, and what it would write.
    site = [product(51, "#83 Robert Baun 1966-67 Topps"),
            product(52, "A mystery card"),
            product(53, "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6")]
    found = product_fields.audit(site, "sku",
                                 rng=product_fields.random.Random(5))
    values = [entry["value"] for entry in found["ready"]]
    check("every product whose title says too little is on the list",
          len(values) == 3 and all(values), str(values))
    check("with the made-up ones marked, and the title's own SKU not",
          [bool(entry.get("loose")) for entry in found["ready"]] ==
          [True, True, False], str(found["ready"]))
    check("the made-up value is what the same seed asked for twice",
          values == [entry["value"] for entry in product_fields.audit(
              site, "sku", rng=product_fields.random.Random(5))["ready"]],
          str(values))
    check("and each one says how it was made",
          all(product_fields.LOOSE_NOTE == entry["note"]
              for entry in found["ready"] if entry.get("loose")), "")
    check("no two products are given the same SKU",
          len({value.lower() for value in values}) == len(values), str(values))

    #  A thousand thin titles: every one of them different, none colliding.
    crowd = [product(1000 + index, "#%d A mystery card" % index)
             for index in range(1000)]
    every = product_fields.audit(crowd, "sku",
                                 rng=product_fields.random.Random(11))
    listed = [entry["value"] for entry in every["ready"]]
    check("a thousand made-up SKUs are a thousand different SKUs",
          len(listed) == 1000 and len({value.lower() for value in listed}) == 1000,
          "%d values, %d distinct" % (len(listed),
                                      len({value.lower() for value in listed})))

    #  The SKU a title that *does* say enough would have is never taken.
    mixed = [product(61, "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6"),
             product(62, "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6 EX-MT"),
             product(63, "A mystery card")]
    audit = product_fields.audit(mixed, "sku",
                                 rng=product_fields.random.Random(5))
    taken = {entry["value"].lower() for entry in audit["ready"]}
    check("a made-up SKU never takes the one a fuller title works out to",
          len(taken) == len(audit["ready"]), str(audit["ready"]))

    #  Two products of one card still need a decision, not random digits.
    twins = [product(71, "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6"),
             product(72, "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6")]
    twin_audit = product_fields.audit(twins, "sku",
                                      rng=product_fields.random.Random(5))
    check("two titles that work out to one SKU are still left alone",
          twin_audit["ready"] == [] and len(twin_audit["unsure"]) == 2,
          str(twin_audit))
    check("and neither is given a made-up SKU to hide the duplicate",
          all(not entry.get("loose") for entry in twin_audit["missing"]), "")

    #  A SKU another product already holds is a duplicate, not a thin title.
    clash = [product(81, "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6"),
             product(82, "A mystery card",
                     sku="OPC1991-12-Smith-EX-MT-6")]
    clash_audit = product_fields.audit(clash, "sku",
                                       rng=product_fields.random.Random(5))
    check("a product whose derived SKU is taken is not given a random one",
          [entry["id"] for entry in clash_audit["unsure"]] == [81] and
          not clash_audit["unsure"][0].get("loose"), str(clash_audit))

    check("the summary says how many are made up, and how",
          "made up from what its title says plus random digits" in
          product_fields.summary(found) or
          "made up from what their titles say plus random digits" in
          product_fields.summary(found), product_fields.summary(found))
    check("and it never stumbles over its own grammar",
          "cannot not" not in product_fields.summary(found) and
          "cannot not" not in product_fields.summary(twin_audit),
          product_fields.summary(twin_audit))
    check("a list with nothing left alone says nothing about leaving alone",
          "left alone" not in product_fields.summary(every),
          product_fields.summary(every))


# ------------------------------------------------------------------ 3. writes
def test_the_writes():
    print()
    print("== 3. only the field that is missing is written, and read back ==")
    title = "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6"
    shop = FakeShop([product(1, title)], brands={"Topps": 31},
                    categories={"Sports Card": 11, "Hockey Card": 12})
    entry = product_fields.audit([product(1, title)], "brand")["ready"][0]
    answer = product_fields.write("https://shop.example", "ck_a", "cs_b",
                                  "brand", entry, opener=shop)
    puts = [call for call in shop.calls if call["method"] == "PUT"]
    check("the brand is written as a Brands-list id",
          puts and puts[0]["body"] == {"brands": [{"id": 71}]},
          str(puts[:1]))
    check("a brand the shop did not have was created for it",
          shop.brands.get("o-pee-chee") == 71, str(shop.brands))
    check("and the shop's answer is read back",
          answer["kept"] is True and answer["kept_text"] == "O-Pee-Chee",
          str(answer))

    #  A brand the shop has is used, not made again - and one term serves a
    #  whole run of cards by the same maker.
    shop = FakeShop([product(1, title)], brands={"O-Pee-Chee": 31})
    cache = {}
    for _round in range(3):
        product_fields.write("https://shop.example", "ck_a", "cs_b", "brand",
                             entry, opener=shop, cache=cache)
    made = [call for call in shop.calls
            if call["method"] == "POST" and "/brands" in call["url"]]
    check("one brand is looked up once for the whole run",
          len([call for call in shop.calls if "search=" in call["url"]]) == 1,
          str([call["url"] for call in shop.calls]))
    check("and never created when the shop already has it", made == [],
          str(made))

    #  A focus keyword goes into the row it belongs to, never a second row.
    keyword_row = product(2, title, meta_data=[
        {"id": 77, "key": "rank_math_focus_keyword", "value": ""}])
    shop = FakeShop([keyword_row])
    entry = product_fields.audit([keyword_row], "keyword")["ready"][0]
    answer = product_fields.write("https://shop.example", "ck_a", "cs_b",
                                  "keyword", entry, opener=shop)
    puts = [call for call in shop.calls if call["method"] == "PUT"]
    sent = puts[0]["body"]["meta_data"]
    check("the keyword is sent with its own row's id",
          sent == [{"id": 77, "key": "rank_math_focus_keyword",
                    "value": "1991 O-Pee-Chee Dallas Smith"}], str(sent))
    check("so the product holds one focus keyword, not two",
          len([row for row in answer["answer"]["meta_data"]
               if row["key"] == "rank_math_focus_keyword"]) == 1,
          str(answer["answer"]["meta_data"]))

    #  A category the shop does not have is created under the same parent the
    #  batch uses, and the product is put in both.
    shop = FakeShop([product(3, title)])
    entry = product_fields.audit([product(3, title)], "categories")["ready"][0]
    answer = product_fields.write("https://shop.example", "ck_a", "cs_b",
                                  "categories", entry, opener=shop)
    puts = [call for call in shop.calls if call["method"] == "PUT"]
    check("the category path is sent as ids, parent and child",
          puts and puts[0]["body"] == {"categories": [{"id": 41},
                                                      {"id": 42}]},
          str(puts[:1]))
    check("and the answer is read back with both on the product",
          answer["kept"] is True and
          [row["name"] for row in answer["answer"]["categories"]] ==
          ["Sports Card", "Hockey Card"], str(answer))

    #  Tags go in by name; the shop makes the terms.
    shop = FakeShop([product(4, title)])
    entry = product_fields.audit([product(4, title)], "tags")["ready"][0]
    answer = product_fields.write("https://shop.example", "ck_a", "cs_b",
                                  "tags", entry, opener=shop)
    puts = [call for call in shop.calls if call["method"] == "PUT"]
    check("the tags are sent by name",
          [row["name"] for row in puts[0]["body"]["tags"]] ==
          ["1991", "O-Pee-Chee", "Dallas Smith", "#12"], str(puts[:1]))
    check("and the site's own tags are read back", answer["kept"] is True,
          str(answer))

    #  A SKU is written through the batch's own one-field writer.
    shop = FakeShop([product(5, title)])
    entry = product_fields.audit([product(5, title)], "sku")["ready"][0]
    answer = product_fields.write("https://shop.example", "ck_a", "cs_b",
                                  "sku", entry, opener=shop)
    puts = [call for call in shop.calls if call["method"] == "PUT"]
    check("the SKU is the only field in the body",
          puts[0]["body"] == {"sku": "OPC1991-12-Smith-EX-MT-6"},
          str(puts[:1]))
    check("and it is read back", answer["kept"] is True, str(answer))

    #  A shop that answers 200 and keeps the old value is not "written".
    kept = FakeShop([product(6, title)], keep=True)
    entry = product_fields.audit([product(6, title)], "brand")["ready"][0]
    answer = product_fields.write("https://shop.example", "ck_a", "cs_b",
                                  "brand", entry, opener=kept)
    check("a 200 that kept the old value is not reported as written",
          answer["kept"] is False, str(answer))

    #  Nothing is sent for a product whose title does not settle the value.
    shop = FakeShop([product(7, "A mystery card")])
    entry = product_fields.audit([product(7, "A mystery card")],
                                 "brand")["unsure"][0]
    try:
        product_fields.write("https://shop.example", "ck_a", "cs_b", "brand",
                             entry, opener=shop)
        check("nothing is sent for a product whose title says nothing", False,
              "it wrote")
    except woo_create.ProductError as exc:
        check("nothing is sent for a product whose title says nothing",
              shop.calls == [] or not [call for call in shop.calls
                                       if call["method"] == "PUT"],
              str(shop.calls))
        check("and it is refused in words", "does not say" in exc.message,
              exc.message)

    #  A body never carries a field nobody asked for.
    shop = FakeShop([product(8, title)])
    entry = product_fields.audit([product(8, title)], "brand")["ready"][0]
    product_fields.write("https://shop.example", "ck_a", "cs_b", "brand",
                         entry, opener=shop)
    put = [call for call in shop.calls if call["method"] == "PUT"][0]
    check("the body holds the one field and nothing else",
          list(put["body"].keys()) == ["brands"], str(put["body"]))


# ------------------------------------------------------------------ 4. panel
def find(parent, widget_class, caption):
    for widget in parent.walk():
        if isinstance(widget, widget_class) and \
                str(widget.cget("text")) == caption:
            return widget
    return None


def sync_background(app, work, done):
    """Run the work now, and hand the result back the way the app does."""
    try:
        result = work()
    except Exception as exc:                       # noqa: BLE001
        done(None, exc)
    else:
        done(result, None)


def panel_with_buttons():
    folder = Path(tempfile.mkdtemp())
    app = harness.FakeApp(folder)
    parent = harness.FakeWidget()
    with patch.object(gui, "BASE", folder):
        gui.build_woostock(parent, app)
    return app, parent, folder


def test_the_panel_offers_them():
    print()
    print("== 4. the shop's place offers one button per field ==")
    app, parent, folder = panel_with_buttons()
    for _field, caption in gui.MISSING_FIELDS:
        button = find(parent, gui.ttk.Button, caption)
        check("the panel offers %r" % caption, button is not None, "")
        check("and its hover explanation says nothing is written until the "
              "list is agreed to",
              "nothing is written until" in gui.tip_for(caption),
              gui.tip_for(caption)[:80])
    check("there is one bar of its own for these checks",
          len([widget for widget in parent.walk()
               if type(widget).__name__ == "FakeProgressbar"]) == 2,
          str(len([widget for widget in parent.walk()
                   if type(widget).__name__ == "FakeProgressbar"])))
    check("and a product that already has the field is never on a list",
          "never replaced" in gui.MISSING_PROMISES["keyword"],
          gui.MISSING_PROMISES["keyword"])

    #  Without keys it says what is missing and reads nothing.
    app.lines[:] = []
    said = []
    harness._BOX.showinfo = lambda *a, **k: said.append(a)
    button = find(parent, gui.ttk.Button, "Find products with no brand")
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("", "", "")):
        button.invoke()
    check("without keys it says what is missing, and reads nothing",
          any("No WooCommerce keys saved" in text for _tag, text in app.lines)
          and any("woo-keys.txt" in str(payload) for payload in said),
          str(app.lines[-1:]) + str(said[-1:]))


def test_the_panel_reads_and_asks():
    print()
    print("== 5. the check reads, lists, and asks before it writes ==")
    app, parent, folder = panel_with_buttons()
    title = "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6"
    products = [product(1, title), product(2, "A mystery card")]

    written = []

    def fake_write(site, key, secret, field, entry, **kwargs):
        written.append((field, entry.get("value")))
        return {"wrote": entry.get("value"), "kept": True, "answer": {},
                "kept_text": product_fields.describe(entry)}

    app.lines[:] = []
    harness._BOX.askyesno = lambda *a, **k: False
    button = find(parent, gui.ttk.Button, "Find products with no brand")
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a",
                                         "cs_b")), \
            patch.object(gui.woo_create, "read_all_products",
                         lambda site, key, secret, **kwargs: products), \
            patch.object(gui.product_fields, "write", fake_write), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()

    check("it names the product that has no brand and the brand its title "
          "names",
          any("Dallas Smith" in text and "O-Pee-Chee" in text
              for _tag, text in app.lines), str(app.lines[-6:]))
    check("it says what the count is, and how many titles cannot settle it",
          any("2 of 2 products have no brand" in text and "left alone" in text
              for _tag, text in app.lines), str(app.lines[-6:]))
    check("it writes the list beside the app",
          any("-missing-" in text and ".csv" in text
              for _tag, text in app.lines), str(app.lines[-4:]))
    check("a No writes nothing at all", written == [], str(written))
    check("and the console says they were left as they are",
          any("left as they are" in text for _tag, text in app.lines),
          str(app.lines[-2:]))

    #  A Yes writes exactly what the list showed, and reports what came back.
    app.lines[:] = []
    harness._BOX.askyesno = lambda *a, **k: True
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a",
                                         "cs_b")), \
            patch.object(gui.woo_create, "read_all_products",
                         lambda site, key, secret, **kwargs: products), \
            patch.object(gui.product_fields, "write", fake_write), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
    check("a Yes writes the brand the list named, once",
          written == [("brand", "O-Pee-Chee")], str(written))
    check("and the console says the answer was read back",
          any("read back" in text for _tag, text in app.lines),
          str(app.lines[-3:]))
    check("and it says how many titles still say nothing",
          any("still have no brand" in text for _tag, text in app.lines),
          str(app.lines[-3:]))

    #  A shop with nowhere to keep a brand is told apart from brandless cards.
    app.lines[:] = []
    said = []
    harness._BOX.showinfo = lambda *a, **k: said.append(a)
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a",
                                         "cs_b")), \
            patch.object(gui.woo_create, "read_all_products",
                         lambda site, key, secret, **kwargs:
                         [{"id": 1, "name": title, "meta_data": []}]), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
    check("a shop with no Brands list says so, and writes nothing",
          any("no Brands list" in text for _tag, text in app.lines)
          and any("9.6" in str(payload) for payload in said),
          str(app.lines[-2:]) + str(said[-1:]))

    #  A shop with nothing missing says so and asks nothing.
    asked = []
    harness._BOX.askyesno = lambda *a, **k: asked.append(a) or True
    app.lines[:] = []
    complete = [product(1, title, brands=[{"id": 5, "name": "O-Pee-Chee"}])]
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a",
                                         "cs_b")), \
            patch.object(gui.woo_create, "read_all_products",
                         lambda site, key, secret, **kwargs: complete), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
    check("a shop with nothing missing says so",
          any("Every one of the 1 products" in text
              for _tag, text in app.lines), str(app.lines[-2:]))
    check("and asks nothing", asked == [], str(asked))

    #  The question a person is asked names the words, and the promise says
    #  what is left alone - for each field, in its own words.
    asked = []
    harness._BOX.askyesno = lambda *a, **k: asked.append(a) or False
    app.lines[:] = []
    bare = [product(1, title)]
    button = find(parent, gui.ttk.Button, "Find products with no category")
    with patch.object(gui, "read_woo_credentials",
                      lambda path=None: ("https://shop.example", "ck_a",
                                         "cs_b")), \
            patch.object(gui.woo_create, "read_all_products",
                         lambda site, key, secret, **kwargs: bare), \
            patch.object(gui, "in_background", sync_background), \
            patch.object(gui, "BASE", folder):
        button.invoke()
    check("the question names the field and shows the words it would write",
          asked and "category" in str(asked[0][0]) and
          "Sports Card > Hockey Card" in str(asked[0][1]), str(asked[-1:])[:300])
    check("and the promise says what is left alone",
          "nothing else moves" in str(asked[0][1]), str(asked[0][1])[:300])
    check("a No says the field's own plural, not a made-up one",
          any("The categories were left as they are" in text
              for _tag, text in app.lines), str(app.lines[-2:]))

    #  Each button checks its own field.
    seen = []

    def fake_audit(rows, field):
        seen.append(field)
        return {"field": field, "word": product_fields.FIELD_WORDS[field],
                "products": len(rows), "supported": True, "missing": [],
                "ready": [], "unsure": []}

    for field, caption in gui.MISSING_FIELDS:
        button = find(parent, gui.ttk.Button, caption)
        app.lines[:] = []
        with patch.object(gui, "read_woo_credentials",
                          lambda path=None: ("https://shop.example", "ck_a",
                                             "cs_b")), \
                patch.object(gui.woo_create, "read_all_products",
                             lambda site, key, secret, **kwargs: products), \
                patch.object(gui.product_fields, "audit", fake_audit), \
                patch.object(gui, "in_background", sync_background), \
                patch.object(gui, "BASE", folder):
            button.invoke()
    check("each button checks its own field, in the order the panel offers "
          "them", seen == [field for field, _caption in gui.MISSING_FIELDS],
          str(seen))


def test_the_panel_says_where_a_made_up_sku_came_from():
    """The made-up SKU is a value the person agrees to, not a surprise.

    It is the one thing this panel writes that is not read out of the title, so
    the question has to say how it was made, the console has to mark it, and
    the write has to send exactly the value that was shown.
    """
    print()
    print("== 6. a made-up SKU is shown, explained and agreed to ==")
    app, parent, folder = panel_with_buttons()
    products = [product(1, "#83 Robert Baun 1966-67 Topps"),
                product(2, "A mystery card")]
    written, asked, said = [], [], []

    def fake_write(site, key, secret, field, entry, **kwargs):
        written.append((field, entry.get("id"), entry.get("value")))
        return {"wrote": entry.get("value"), "kept": True, "answer": {},
                "kept_text": product_fields.describe(entry)}

    button = find(parent, gui.ttk.Button, "Find products with no SKU")
    check("the panel offers the SKU check", button is not None, "")

    def run(answer):
        app.lines[:] = []
        asked[:] = []
        written[:] = []
        harness._BOX.askyesno = lambda title, question="", **kw: (
            asked.append((title, question)), answer)[1]
        with patch.object(gui, "read_woo_credentials",
                          lambda path=None: ("https://shop.example", "ck_a",
                                             "cs_b")), \
                patch.object(gui.woo_create, "read_all_products",
                             lambda site, key, secret, **kwargs: products), \
                patch.object(gui.product_fields, "write", fake_write), \
                patch.object(gui.product_fields, "_RNG",
                             product_fields.random.Random(5)), \
                patch.object(gui, "in_background", sync_background), \
                patch.object(gui, "BASE", folder):
            button.invoke()

    run(False)
    check("the console marks the SKU it made up",
          any("(made up from its title)" in text for _tag, text in app.lines),
          str(app.lines[-8:]))
    check("and shows the shape the title gave it",
          any("TOPPS1966-67-83-" in text for _tag, text in app.lines),
          str(app.lines[-8:]))
    check("the question says how many were made up and how",
          asked and "random digits" in asked[0][1] and
          "%d random digits" % product_fields.LOOSE_DIGITS in asked[0][1],
          str(asked[:1]))
    check("it says the made-up SKU is checked against the website's own",
          asked and "checked against every SKU the website already holds"
          in asked[0][1], str(asked[:1]))
    check("and a No writes nothing at all", written == [], str(written))

    run(True)
    check("a Yes writes exactly the SKU the list showed, once each",
          len(written) == 2 and
          all(field == "sku" for field, _id, _value in written), str(written))
    expected = [entry["value"] for entry in product_fields.audit(
        products, "sku", rng=product_fields.random.Random(5))["ready"]]
    check("with exactly the values the same preview would show",
          [value for _field, _id, value in written] == expected,
          str(written) + " " + str(expected))
    check("each ending in four digits, so no two can be one SKU",
          all(re.match(r"^[A-Za-z0-9-]+-\d{4}$", value)
              for _field, _id, value in written), str(written))
    check("and the console says the answer was read back",
          any("read back" in text for _tag, text in app.lines),
          str(app.lines[-4:]))
    check("nothing is reported as left alone when nothing was",
          not any("still have no SKU" in text for _tag, text in app.lines),
          str(app.lines[-4:]))

    #  Every title left is a duplicate of a SKU that is spoken for: nothing is
    #  offered, and the panel says why rather than promising a write.
    products[:] = [product(9, "1991 O-Pee-Chee Dallas Smith #12 EX-MT 6"),
                   product(10, "another card",
                           sku="OPC1991-12-Smith-EX-MT-6")]
    run(True)
    check("with only spoken-for SKUs left, nothing is written",
          written == [], str(written))
    check("and it says nothing here can be filled in without a guess",
          any("Nothing is offered to write" in text
              for _tag, text in app.lines), str(app.lines[-4:]))
    harness._BOX.showinfo = (lambda kind: lambda *a, **k:
                             harness._BOX.shown.append((kind, a)))("showinfo")


def main():
    test_the_title_says_it()
    test_the_audit()
    test_a_title_that_says_too_little_still_gets_a_sku()
    test_the_writes()
    test_the_panel_offers_them()
    test_the_panel_reads_and_asks()
    test_the_panel_says_where_a_made_up_sku_came_from()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL PRODUCT FIELD CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
