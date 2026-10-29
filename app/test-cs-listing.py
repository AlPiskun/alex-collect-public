#!/usr/bin/env python3
"""Checks for cs_listing - putting a website product onto CanadianShopper.

No network and no shop: a product is a dict shaped like the WooCommerce API's
own answer, and the import file is read back with the csv module. What matters
is that the row is the pipeline's fourteen columns, that nothing is invented,
and that the file the importer reads is named the way the rest of the tooling
expects.
"""
import csv
import sys
import tempfile
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]

import cs_listing                                     # noqa: E402

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


SETTINGS = {
    "canadianshopper_category": "Sports Card > Hockey Card",
    "canadianshopper_ship_from_province": "BC",
    "canadianshopper_shipping_flat": "5.50",
    "canadianshopper_free_shipping": True,
    "canadianshopper_handling_days": 3,
    "canadianshopper_transit_days": 6,
}

PRODUCT = {
    "id": 41,
    "name": "1989 O-Pee-Chee Wayne Gretzky #1 EX-MT 6",
    "price": "12.00",
    "regular_price": "14.00",
    "short_description": "<p>A sharp <strong>Gretzky</strong> from the 1989 set.</p>",
    "description": "<p>Longer words about the card.</p>",
    "images": [{"id": 7, "src": "https://shop.example/wp-content/uploads/2026/10/gretzky-front.webp"}],
    "sku": "GR-1",
}


def test_defaults():
    print("== 1. the import defaults are the pipeline's own ==")
    values = cs_listing.defaults(SETTINGS)
    check("the saved category and shipping are used",
          values["category"] == "Sports Card > Hockey Card" and
          values["ship_from_province"] == "BC" and
          values["shipping_flat_cad"] == "5.50", str(values))
    check("free shipping is the importer's own true/false word",
          values["free_shipping"] == "true", str(values))
    check("handling and transit are strings, as the CSV needs",
          values["handling_days"] == "3" and values["transit_days"] == "6",
          str(values))
    blank = cs_listing.defaults({})
    check("with nothing saved the pipeline's fallbacks are used",
          blank["category"] == "Antiques & Collectibles" and
          blank["ship_from_province"] == "ON" and
          blank["shipping_flat_cad"] == "4.00" and
          blank["free_shipping"] == "false", str(blank))


def test_row():
    print()
    print("== 2. one row, from what the website already has ==")
    values = cs_listing.defaults(SETTINGS)
    row = cs_listing.row_for(PRODUCT, 3, values)
    check("the fourteen columns are the importer's own, in order",
          list(row) == cs_listing.CANADIANSHOPPER_FIELDNAMES, str(list(row)))
    check("the title is the product's name",
          row["title"] == PRODUCT["name"], row["title"])
    check("the price is the product's, not the regular price behind it",
          row["price_cad"] == "12.00", row["price_cad"])
    check("the description is plain words, not markup",
          row["description"] == "A sharp Gretzky from the 1989 set.",
          row["description"])
    check("the photo is the one the website already serves",
          row["image_url"].endswith("/gretzky-front.webp"), row["image_url"])
    check("the stock count is the website's",
          row["inventory"] == "3", row["inventory"])
    check("a listed card is not made to order",
          row["is_made_to_order"] == "false", row["is_made_to_order"])
    check("the settings travel into the shipping columns",
          row["category"] == "Sports Card > Hockey Card" and
          row["free_shipping"] == "true" and row["handling_days"] == "3",
          str(row))
    check("sizes and colors are empty strings, never absent",
          row["sizes"] == "" and row["colors"] == "", str(row))

    sparse = {"id": 2, "name": "  Card   with  spaces  "}
    bare = cs_listing.row_for(sparse, None)
    check("a product with no price, photo or stock still makes a row",
          bare["price_cad"] == "" and bare["image_url"] == "" and
          bare["inventory"] == "0", str(bare))
    check("and its name is tidied rather than left with runs of spaces",
          bare["title"] == "Card with spaces", bare["title"])
    check("a negative or unreadable count is written as nothing in stock",
          cs_listing.row_for(sparse, -4)["inventory"] == "0" and
          cs_listing.row_for(sparse, "lots")["inventory"] == "0", "")

    check("a long description is cut, with an ellipsis saying so",
          len(cs_listing.plain_text("<p>%s</p>" % ("word " * 500))) <= 900 and
          cs_listing.plain_text("x " * 900).endswith("\u2026"), "")
    check("an html-escaped ampersand is read as an ampersand",
          cs_listing.plain_text("Antiques &amp; Collectibles")
          == "Antiques & Collectibles", "")
    check("a photo that is not a web address is not used",
          cs_listing.image_url({"images": [{"src": "C:\\pics\\front.jpg"}]}) == "",
          "")
    check("the second photo is used when the first is unusable",
          cs_listing.image_url({"images": [{"src": "nope.jpg"},
                                           {"src": "https://x/y.jpg"}]})
          == "https://x/y.jpg", "")
    check("a price written as a number is still 12.00",
          cs_listing.price_text({"price": 12}) == "12.00", "")
    check("nonsense in the price field is not turned into 0.00",
          cs_listing.price_text({"price": "ask"}) == "", "")


def test_rows_and_notes():
    print()
    print("== 3. what the person is warned about before importing ==")
    values = cs_listing.defaults(SETTINGS)
    rows, notes = cs_listing.build_rows(
        [(PRODUCT, 3),
         ({"id": 2, "name": "No photo card", "price": "1.00"}, 1),
         ({"id": 3, "name": "No price card",
           "images": [{"src": "https://x/y.jpg"}]}, 1),
         ({"id": 4, "name": "Sold out card", "price": "1.00",
           "images": [{"src": "https://x/y.jpg"}]}, 0),
         ({"id": 5, "name": "  "}, 1)], values)
    check("every product with a name becomes a row", len(rows) == 4, str(rows))
    check("a product with no name is left out and said so",
          any("no name" in note[0] for note in notes), str(notes))
    check("a missing photo is named", any("no photo" in note[1]
                                          for note in notes), str(notes))
    check("a blank price is named",
          ("No price card", "no price on the website, so the price is blank")
          in notes, str(notes))
    check("a card at zero is named as going up out of stock",
          any("out of stock" in note[1] for note in notes), str(notes))
    check("a complete card gets no note at all",
          not any(note[0] == PRODUCT["name"] for note in notes), str(notes))

    check("one sentence says what the import would create",
          cs_listing.summary(rows, values).startswith(
              "4 listings would be created as unpublished drafts") and
          "Sports Card > Hockey Card" in cs_listing.summary(rows, values),
          cs_listing.summary(rows, values))
    check("and nothing to list says exactly that",
          cs_listing.summary([], values) == "Nothing to list.", "")
    check("the confirmation reads card by card",
          cs_listing.describe(rows)[0].startswith("  " + PRODUCT["name"][:20]),
          str(cs_listing.describe(rows)[:1]))
    check("and it names the photo source rather than assuming one",
          "photo from the website" in cs_listing.describe(rows)[0] and
          "no photo" in cs_listing.describe(rows)[1],
          str(cs_listing.describe(rows)[:2]))


def test_file():
    print()
    print("== 4. the file the importer reads ==")
    folder = Path(tempfile.mkdtemp())
    values = cs_listing.defaults(SETTINGS)
    rows, _notes = cs_listing.build_rows([(PRODUCT, 3)], values)
    written = cs_listing.write_rows(rows, folder,
                                   when=datetime(2026, 10, 28, 14, 5, 6))
    path = written[0][0]
    check("it is named like every other import batch",
          path.name == "canadianshopper_import_20261028_140506_01_of_01.csv",
          path.name)
    check("and it lands in the folder it was given",
          path.parent == folder, str(path.parent))
    with open(path, newline="", encoding="utf-8-sig") as handle:
        read = list(csv.DictReader(handle))
    check("the importer can read it back as one row",
          len(read) == 1 and read[0]["title"] == PRODUCT["name"], str(read))
    check("with every column present and no extras",
          list(read[0]) == cs_listing.CANADIANSHOPPER_FIELDNAMES, str(list(read[0])))
    raw = path.read_bytes()
    check("it is written as utf-8 with a BOM, as the importer expects",
          raw.startswith(b"\xef\xbb\xbf"), str(raw[:4]))
    check("the lines end in a newline, not a Windows pair",
          b"\r\n" not in raw, str(raw[:80]))

    many = [dict(rows[0], title="Card %d" % n) for n in range(1101)]
    written = cs_listing.write_rows(many, folder / "big",
                                   when=datetime(2026, 1, 1, 0, 0, 0))
    check("more rows than one file may hold are split into batches",
          [count for _path, count in written] == [500, 500, 101],
          str([count for _path, count in written]))
    check("and each name carries its own place in the set",
          [path.name for path, _count in written] == [
              "canadianshopper_import_20260101_000000_01_of_03.csv",
              "canadianshopper_import_20260101_000000_02_of_03.csv",
              "canadianshopper_import_20260101_000000_03_of_03.csv"],
          str([path.name for path, _count in written]))
    check("nothing to write means no file at all",
          cs_listing.write_rows([], folder / "empty") == [], "")


def test_pipeline_shares_it():
    print()
    print("== 5. the pipeline and this panel write the same file ==")
    import card_pipeline                              # noqa: E402
    check("the pipeline's columns are these columns",
          card_pipeline.CANADIANSHOPPER_FIELDNAMES
          is cs_listing.CANADIANSHOPPER_FIELDNAMES or
          card_pipeline.CANADIANSHOPPER_FIELDNAMES ==
          cs_listing.CANADIANSHOPPER_FIELDNAMES, "")
    check("the batch size is the importer's limit, in one place",
          card_pipeline.CANADIANSHOPPER_BATCH_SIZE == 500, "")
    check("and the defaults are the same function's answer",
          (card_pipeline.CANADIANSHOPPER_CATEGORY,
           card_pipeline.CANADIANSHOPPER_PROVINCE,
           card_pipeline.CANADIANSHOPPER_FLAT_SHIPPING,
           card_pipeline.CANADIANSHOPPER_FREE_SHIPPING) ==
          (cs_listing.defaults()["category"],
           cs_listing.defaults()["ship_from_province"],
           cs_listing.defaults()["shipping_flat_cad"],
           cs_listing.defaults()["free_shipping"]), "")


def test_import_report():
    print()
    print("== 6. what the plugin's import result is allowed to mean ==")
    written = [(Path("/x/canadianshopper_import_1_01_of_02.csv"), 2),
               (Path("/x/canadianshopper_import_1_02_of_02.csv"), 1)]
    report = cs_listing.import_report(written, {
        "imported": [{"file": "canadianshopper_import_1_01_of_02.csv",
                      "rows": 2, "drafts": 2}],
        "failed": [{"file": "/x/canadianshopper_import_1_02_of_02.csv",
                    "why": "the importer refused row 1"}]})
    check("a file the plugin imported is counted with its drafts",
          report["imported"] == [{"file": "canadianshopper_import_1_01_of_02.csv",
                                  "rows": 2, "drafts": 2}], str(report))
    check("a file it refused keeps the reason",
          report["failed"] == [{"file": "canadianshopper_import_1_02_of_02.csv",
                                "why": "the importer refused row 1"}],
          str(report["failed"]))
    check("and a refused file is never also counted as imported",
          not any(entry["file"].endswith("02_of_02.csv")
                  for entry in report["imported"]), str(report))

    report = cs_listing.import_report(written, {"imported": [], "failed": []})
    check("a file the result ignores is unknown, never assumed imported",
          len(report["unknown"]) == 2 and not report["imported"], str(report))
    report = cs_listing.import_report(written, None)
    check("a missing result file means nothing is claimed",
          len(report["unknown"]) == 2, str(report))
    report = cs_listing.import_report(written, {
        "imported": [{"file": "canadianshopper_import_1_01_of_02.csv"}],
        "failed": []})
    check("a result without a draft count falls back to the rows written",
          report["imported"][0]["drafts"] == 2, str(report))
    check("an unreadable draft count is not a reason to claim zero",
          cs_listing.import_report(
              [(Path("a.csv"), 3)],
              {"imported": [{"file": "a.csv", "drafts": "many"}]})
          ["imported"][0]["drafts"] == 3, "")
    check("only the file name is compared, not the whole path",
          cs_listing.import_report(
              [(Path("C:/deep/folder/a.csv"), 1)],
              {"imported": [{"file": "a.csv", "drafts": 1}]})["imported"],
          "")


def test_listing_products():
    print()
    print("== 7. only a product the comparison actually read can be listed ==")
    rows = [{"kind": "only-woo", "woo_id": 41, "woo": 3, "card": "A"},
            {"kind": "only-woo", "woo_id": 99, "woo": 1, "card": "B"},
            {"kind": "fix", "woo_id": 41, "woo": 3, "other": 0, "card": "C"}]
    wanted, missing = cs_listing.listing_products(rows, {"41": PRODUCT})
    check("the card whose product is known is offered",
          len(wanted) == 1 and wanted[0][0]["id"] == 41, str(wanted)[:120])
    check("a row that is on both sites is never a listing job",
          all(row[0]["id"] != 41 for row in wanted[1:]) and len(wanted) == 1,
          str(len(wanted)))
    check("the inventory offered is the website's own count",
          wanted[0][1] == 3, str(wanted))
    check("a card whose product is gone is reported, not guessed at",
          missing == ["B"], str(missing))
    wanted, missing = cs_listing.listing_products([], {})
    check("nothing selected is nothing to do",
          wanted == [] and missing == [], "")


def main():
    test_defaults()
    test_row()
    test_rows_and_notes()
    test_file()
    test_pipeline_shares_it()
    test_import_report()
    test_listing_products()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL CS LISTING CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
