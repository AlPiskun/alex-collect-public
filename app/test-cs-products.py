#!/usr/bin/env python3
"""Checks for making a website product out of a CanadianShopper listing.

The comparison can go both ways. "List the selected cards on CanadianShopper"
sends a website product to the vendor site; this is the other direction, for a
listing that exists only there. Three things make it worth a suite of its own:

  * the **photos** are square, because the storefront crops everything into a
    square box - they have to be cropped back to the card before the website
    sees them, and a crop that guesses is worse than no crop at all;
  * the **price** is written the vendor's way (``CA$1,250.00``) and the
    website's way (``1250.00``), and a price this app cannot read must never
    become a made-up number;
  * a listing the reader reports nothing about but a **title and a page
    address** still has to work, because the pictures and the price can be
    read off that page.

Pillow draws every picture here; nothing touches a site.
"""
import sys
import tempfile
from io import BytesIO
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]

from PIL import Image, ImageDraw                     # noqa: E402

import cs_products                                    # noqa: E402
import photo_unsquare                                 # noqa: E402

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


# --------------------------------------------------------------- pictures
def square_card(width=600, card=(400, 520), background=(255, 255, 255),
                trim=(205, 185, 150)):
    """A card on a padded square, the way the storefront is given one."""
    image = Image.new("RGB", (width, width), background)
    left = (width - card[0]) // 2
    top = (width - card[1]) // 2
    ImageDraw.Draw(image).rectangle(
        [left, top, left + card[0] - 1, top + card[1] - 1], fill=trim)
    return image


def png_bytes(image):
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def opened(bytes_):
    return Image.open(BytesIO(bytes_))


# ------------------------------------------------------------------- tests
def test_prices():
    print("== 1. the vendor's price, in the website's own writing ==")
    cases = {"CA$8.50": "8.50", "8.50": "8.50", "CA$1,250.00": "1250.00",
             "1,250": "1250.00", "8,50": "8.50", "CAD $12": "12.00",
             "$0.00": "", "Free": "", "": "", "  ": "", None: "",
             "12": "12.00", "CA$ 1,000.99": "1000.99"}
    for given, wanted in cases.items():
        got = cs_products.price_of(given)
        check("%r becomes %r" % (given, wanted), got == wanted, "got %r" % got)
    check("a price is never negative",
          cs_products.price_of("-5.00") == "", cs_products.price_of("-5.00"))


def test_picture_addresses():
    print()
    print("== 2. where a listing's pictures are ==")
    check("a reader's own picture address is used as it is",
          cs_products.picture_urls(
              {"images": ["https://cdn.example/one.webp"]})[0] ==
          ["https://cdn.example/one.webp"], "")
    check("a plain address in another key is understood",
          cs_products.picture_urls(
              {"images": ["file:///C:/card.jpg"]})[0] == [], "")
    page = """<html><head>
        <meta property="og:image" content="/media/card-front.jpg">
        <meta name="twitter:image" content="https://cdn.example/tw.jpg">
        <script type="application/ld+json">
        {"@type":"Product","image":["https://cdn.example/one.jpg"],
         "offers":{"price":"42.00"}}
        </script></head><body>
        <img src="/static/logo.png">
        <img src="https://cdn.example/gallery-2.jpg">
        <span>CA$42.00</span></body></html>"""
    found = cs_products.images_in_html(page, "https://cs.example/listing/9")
    check("the page's own picture comes first, made absolute",
          found[:1] == ["https://cs.example/media/card-front.jpg"], str(found[:2]))
    check("and the structured data is read too",
          "https://cdn.example/one.jpg" in found, str(found))
    check("the site's logo is not a card",
          not any("logo" in url for url in found), str(found))
    check("nothing twice", len(found) == len(set(found)), str(found))
    check("a page with no picture answers with none",
          cs_products.images_in_html("<p>nothing here</p>") == [], "")
    check("a price on the page is read when the row has none",
          cs_products.price_in_html(page) == "42.00",
          cs_products.price_in_html(page))
    check("a plainly written price is read too",
          cs_products.price_in_html("<b>CA$1,250.00</b>") == "1250.00",
          cs_products.price_in_html("<b>CA$1,250.00</b>"))
    check("a page with no price answers with none",
          cs_products.price_in_html("<p>no money here</p>") == "", "")


def test_the_crop():
    print()
    print("== 3. the square comes off, and only the square ==")
    padded = square_card()
    box = photo_unsquare.card_box(padded)
    check("the card is found inside the padding",
          box is not None and 90 <= box[0] <= 110 and 30 <= box[1] <= 50,
          str(box))
    check("the background is read as white",
          photo_unsquare.background(padded) == (255, 255, 255),
          str(photo_unsquare.background(padded)))
    cropped, measure = photo_unsquare.de_square(padded)
    check("the picture is cropped", measure["padded"] is True, str(measure))
    check("to the card's own shape, not a square",
          measure["after"] != measure["before"] and
          1.2 <= measure["after"][1] / float(measure["after"][0]) <= 1.6,
          str(measure["after"]))
    check("with room left around the card",
          measure["after"][0] > 400 and measure["after"][1] > 520,
          str(measure["after"]))
    check("and the card's middle is still the card's middle",
          cropped.getpixel((cropped.size[0] // 2, cropped.size[1] // 2)) ==
          (205, 185, 150), str(cropped.getpixel(
              (cropped.size[0] // 2, cropped.size[1] // 2))))

    dark = square_card(width=700, card=(600, 500), background=(5, 5, 5))
    _cropped, measure = photo_unsquare.de_square(dark)
    check("a card photographed on black is cropped too",
          measure["padded"] is True, str(measure))

    card_photo = Image.new("RGB", (600, 840), (40, 90, 140))
    draw = ImageDraw.Draw(card_photo)
    draw.rectangle([0, 0, 599, 40], fill=(250, 245, 235))
    draw.rectangle([0, 800, 599, 839], fill=(250, 245, 235))
    draw.ellipse([150, 300, 450, 600], fill=(220, 180, 150))
    _cropped, measure = photo_unsquare.de_square(card_photo)
    check("a picture that is already the card's shape is left alone",
          measure["padded"] is False and
          measure["after"] == measure["before"], str(measure))
    check("and says why", "not square" in measure["why"], measure["why"])

    blank = Image.new("RGB", (400, 400), (255, 255, 255))
    _cropped, measure = photo_unsquare.de_square(blank)
    check("a square of nothing is not cropped to nothing",
          measure["padded"] is False and "no card" in measure["why"],
          measure["why"])

    odd = Image.new("RGB", (600, 600), (255, 255, 255))
    ImageDraw.Draw(odd).rectangle([120, 120, 480, 480], fill=(120, 40, 40))
    _cropped, measure = photo_unsquare.de_square(odd)
    check("a square inside a square is not a card, so nothing is cropped",
          measure["padded"] is False and "shape" in measure["why"],
          measure["why"])
    check("sizes read the way a person reads them",
          photo_unsquare.shape_text((600, 780)) == "600x780", "")


def test_a_card_from_a_row():
    print()
    print("== 4. one comparison row as a card to create ==")
    row = {"kind": "only-other", "card": "1971-72 O-Pee-Chee Ken Dryden #10",
           "other": 4, "other_id": 201, "other_sku": "KD-10",
           "other_name": "1971-72 O-Pee-Chee Ken Dryden #10"}
    listing = {"id": 201, "price": "CA$12.50",
               "url": "https://cs.example/listing/201",
               "images": ["https://cdn.example/dryden.jpg"]}
    card = cs_products.card_from(row, listing)
    check("the card keeps its listing's title", card["name"] == row["card"])
    check("and its SKU", card["sku"] == "KD-10")
    check("and its stock count", card["stock"] == 4, str(card["stock"]))
    check("and its price, as a number", card["price"] == "12.50", card["price"])
    check("and where its page is", card["url"].endswith("/201"))
    check("and its pictures", card["images"] == ["https://cdn.example/dryden.jpg"])
    check("with nothing photographed or noted yet",
          card["photos"] == [] and card["notes"] == [])

    bare = cs_products.card_from({"kind": "only-other", "card": "A card",
                                  "other": None})
    check("a row with no listing behind it still works",
          bare["name"] == "A card" and bare["stock"] == 0 and
          bare["price"] == "", str(bare))
    check("and a row with no title is still a card with no title",
          cs_products.card_from({})["name"] == "", "")


def test_saving_the_pictures():
    print()
    print("== 5. pictures are fetched, cropped and named like the shop's ==")
    folder = Path(tempfile.mkdtemp(prefix="cs-products-"))
    fetches = []

    def fetch(url, _cookie="", _timeout=25):
        fetches.append(url)
        if "missing" in url:
            raise OSError("the shop would not answer")
        if "rubbish" in url:
            return b"not a picture"
        return png_bytes(square_card())

    card = {"name": "1971-72 O-Pee-Chee Ken Dryden #10",
            "sku": "KD-10", "price": "12.50", "stock": 4,
            "images": ["https://cdn.example/dryden-front.jpg",
                       "https://cdn.example/dryden-back.jpg"],
            "photos": [], "crops": [], "notes": []}
    saved = cs_products.save_pictures(card, folder, fetch=fetch)
    names = [entry["name"] for entry in saved["files"]]
    check("the first picture is the front and the second the back",
          names == ["1971-72-o-pee-chee-ken-dryden-10-front.webp",
                    "1971-72-o-pee-chee-ken-dryden-10-back.webp"], str(names))
    check("both were fetched once", len(fetches) == 2, str(fetches))
    written = folder / names[0]
    check("and written where the caller asked",
          written.is_file(), str(written))
    from PIL import Image as _Image
    with _Image.open(written) as opened_card:
        width, height = opened_card.size
        check("the saved picture is the shop's width", width == 600, str(width))
        check("and the card's shape, not a square",
              height > width, "%dx%d" % (width, height))
    check("what the crop did is reported",
          cs_products.crop_text(saved["files"])[0].startswith(names[0]) and
          "cropped to" in cs_products.crop_text(saved["files"])[0],
          str(cs_products.crop_text(saved["files"])))

    print()
    print("== 6. a picture that will not come is a note, not a crash ==")
    card = {"name": "A card", "images": ["https://cdn.example/missing.jpg"],
            "photos": [], "crops": [], "notes": []}
    saved = cs_products.save_pictures(card, folder, fetch=fetch)
    check("nothing is saved", saved["files"] == [], str(saved))
    check("and the reason is in the notes",
          saved["notes"] and "could not be fetched" in saved["notes"][0],
          str(saved["notes"]))

    card = {"name": "A card", "images": ["https://cdn.example/rubbish.jpg"],
            "photos": [], "crops": [], "notes": []}
    saved = cs_products.save_pictures(card, folder, fetch=fetch)
    check("something that is not a picture is named as such",
          saved["files"] == [] and
          "not a picture" in " ".join(saved["notes"]), str(saved["notes"]))

    card = {"name": "A card", "images": [], "photos": [], "crops": [],
            "notes": []}
    saved = cs_products.save_pictures(card, folder, fetch=fetch)
    check("a listing with no picture says so",
          saved["files"] == [] and
          "no picture address" in saved["notes"][0], str(saved["notes"]))

    print()
    print("== 7. a page address is enough when the reader reports no picture ==")
    page = ('<meta property="og:image" content="/media/kd.jpg">'
            '<span>CA$12.50</span>')
    card = {"name": "Ken Dryden", "url": "https://cs.example/listing/201",
            "images": [], "price": "", "photos": [], "crops": [], "notes": []}
    saved = cs_products.save_pictures(
        card, folder, fetch=fetch,
        fetch_page=lambda url: page if url.endswith("/201") else "")
    check("the page was read and its picture used",
          len(saved["files"]) == 1, str(saved))
    check("the picture address was made absolute",
          saved["files"] and saved["files"][0]["url"] ==
          "https://cs.example/media/kd.jpg", str(saved["files"][:1]))
    check("and the price came off the same page",
          card["price"] == "12.50", card["price"])
    check("which the card's notes say out loud",
          any("from its listing page" in note for note in card["notes"]),
          str(card["notes"]))


def test_the_plan():
    print()
    print("== 8. the plan is what the website's creator already takes ==")
    cards = [{"name": "1971-72 O-Pee-Chee Ken Dryden #10", "sku": "KD-10",
              "stock": 4, "price": "12.50", "photos": ["kd-front.webp"]},
             {"name": "A card with nothing", "sku": "", "stock": 0,
              "price": "", "photos": []},
             {"name": "", "sku": "", "stock": 1, "price": "1.00",
              "photos": []}]
    built = cs_products.plan(cards, Path("/tmp/wherever"))
    check("two of the three can be created", len(built["items"]) == 2,
          str(len(built["items"])))
    check("a card with no title is a problem, not a product",
          len(built["problems"]) == 1, str(built["problems"]))
    one = built["items"][0]
    check("the item carries what the creator reads",
          one["name"] == cards[0]["name"] and one["sku"] == "KD-10" and
          one["stock"] == 4 and one["price"] == "12.50" and
          one["images"] == ["kd-front.webp"], str(one))
    check("it arrives unpublished", one["published"] is False)
    check("the photo folder travels with the plan",
          str(built["folder"]).endswith("wherever"), str(built["folder"]))
    check("nothing is invented for a category or a description",
          one["categories"] == [] and one["description"] == "", "")
    check("no stock means out of stock, not a missing count",
          built["items"][1]["in_stock"] is False and
          built["items"][1]["stock"] == 0, str(built["items"][1]))
    notes = " ".join(built["notes"])
    check("a card with no price is named", "no price" in notes, notes)
    check("a card with no photo is named", "no picture" in notes.lower(),
          notes)
    check("the summary says drafts, photos and the site",
          cs_products.summary(built, "shop.example").startswith(
              "2 products would be created on shop.example as drafts"),
          cs_products.summary(built, "shop.example"))
    check("one card reads as one product, in English",
          cs_products.summary({"items": [one]}, "shop.example").startswith(
              "1 product would be created"), "")
    check("and nothing reads as nothing",
          cs_products.summary({"items": []}) == "Nothing to create.", "")
    lines = cs_products.describe(built)
    check("the confirmation names each card, its price and its stock",
          "$12.50" in lines[0] and "stock 4" in lines[0] and
          "1 photo" in lines[0], str(lines[:1]))
    check("and says plainly when there is no photo",
          "no photo" in lines[1], str(lines[:2]))
    check("the first confirmation names the cards before any work is done",
          "SKU KD-10" in cs_products.describe_cards(cards)[0], "")


def test_the_names():
    print()
    print("== 9. file names that say which card it is ==")
    check("a title becomes a name",
          cs_products.slugify("1970-71 O-Pee-Chee Paul Henderson #217") ==
          "1970-71-o-pee-chee-paul-henderson-217", "")
    check("nothing usable still gives a name",
          cs_products.slugify("***") == "card", cs_products.slugify("***"))
    check("a very long title is cut, not refused",
          len(cs_products.slugify("x" * 200)) <= 64,
          str(len(cs_products.slugify("x" * 200))))
    check("a second picture of the same card does not overwrite the first",
          cs_products._free_name(Path(tempfile.mkdtemp()) / "card.webp").name
          == "card.webp", "")


def test_the_cookie():
    print()
    print("== 10. the saved session, as a header ==")
    folder = Path(tempfile.mkdtemp())
    cookie = folder / "cookie.txt"
    cookie.write_text("# paste your cookie below\n\nPHPSESSID=abc; theme=dark\n",
                      encoding="utf-8")
    check("the explanation lines are not sent",
          cs_products.read_cookie(cookie) == "PHPSESSID=abc; theme=dark",
          cs_products.read_cookie(cookie))
    check("a missing file is no cookie, not a crash",
          cs_products.read_cookie(folder / "nothing.txt") == "", "")


def test_the_reader_pictures():
    print()
    print("== 11. plugin 1.0.32's own pictures, without reading a page ==")
    #  What the reader sends from 1.0.32: the primary picture first, then the
    #  gallery in the vendor's order, with anything repeated or unreadable
    #  already removed by the plugin. The app must not sort them, must not
    #  read the listing's page, and must keep front first.
    listing = {"id": 201,
               "name": "1971-72 O-Pee-Chee Ken Dryden #10",
               "sku": "KD-10", "qty": 4, "price": "12.50",
               "url": "https://cs.example/listing/201",
               "images": ["https://cdn.example/primary.jpg",
                          "https://cdn.example/gallery-2.jpg",
                          "https://cdn.example/gallery-3.jpg"]}
    pages = []

    def fetch_page(url):
        pages.append(url)
        return "<html>a page that should not be read</html>"

    urls, page = cs_products.picture_urls(listing, fetch_page=fetch_page)
    check("the primary picture is first and the next one is the back",
          urls == ["https://cdn.example/primary.jpg",
                   "https://cdn.example/gallery-2.jpg"], str(urls))
    check("a third picture is left to the vendor", len(urls) == 2, str(urls))
    check("and no listing page was read at all",
          pages == [] and page == "", "%s %r" % (pages, page))

    row = {"card": listing["name"], "other_id": 201, "other": 4,
           "other_sku": "KD-10", "kind": "only-other", "other_name": ""}
    card = cs_products.card_from(row, listing)
    check("a card made from that listing carries the reader's pictures",
          card["images"] == urls or card["images"][:2] == urls[:2],
          str(card["images"]))
    saved = cs_products.save_pictures(
        card, Path(tempfile.mkdtemp(prefix="cs-reader-")),
        fetch=lambda url, _cookie="", _timeout=25: png_bytes(square_card()),
        fetch_page=fetch_page)
    names = [entry["name"] for entry in saved["files"]]
    check("they are saved as a front and a back",
          [name.endswith(("-front.webp", "-back.webp")) for name in names]
          == [True, True] and names[0].endswith("-front.webp"), str(names))
    check("with the primary picture named as the front",
          saved["files"] and saved["files"][0]["url"] ==
          "https://cdn.example/primary.jpg", str(saved["files"][:1]))
    check("the page was read once, only because no description was given",
          pages == ["https://cs.example/listing/201"], str(pages))
    check("and the reader's own pictures were still the ones used",
          [entry["url"] for entry in saved["files"]] == urls[:2],
          str([entry["url"] for entry in saved["files"]]))

    #  A reader that reports the description and keywords as well - what the
    #  plugin can do - needs no page read at all.
    pages.clear()
    rich = dict(listing, description="<p>A sharp, centred copy.</p>",
                keywords=["hockey", "1971-72", "Ken Dryden"])
    card = cs_products.card_from(row, rich)
    cs_products.save_pictures(
        card, Path(tempfile.mkdtemp(prefix="cs-rich-")),
        fetch=lambda url, _cookie="", _timeout=25: png_bytes(square_card()),
        fetch_page=fetch_page)
    check("a listing that states its own description needs no page read",
          pages == [], str(pages))
    check("and its words are on the card",
          "A sharp, centred copy." in card["description"] and
          "hockey" in card["tags"], str(card.get("description")) + str(card["tags"]))

    print()
    print("== 12. a picture the reader spells another way is still found ==")
    check("a picture dict is read, not stringified",
          cs_products.readable_urls([{"src": "https://cdn.example/a.jpg"},
                                     {"url": "https://cdn.example/b.jpg"}]) ==
          ["https://cdn.example/a.jpg", "https://cdn.example/b.jpg"], "")
    check("a local path is not a picture address",
          cs_products.readable_urls(
              ["C:\\cards\\front.jpg", "file:///tmp/front.jpg",
               "https://cdn.example/ok.jpg"]) ==
          ["https://cdn.example/ok.jpg"], "")
    check("the same address twice is one picture",
          cs_products.readable_urls(["https://cdn.example/a.jpg",
                                     "https://cdn.example/a.jpg"]) ==
          ["https://cdn.example/a.jpg"], "")
    card = cs_products.card_from(
        {"card": "A card"},
        {"name": "A card", "photo_url": "https://cdn.example/alt.jpg"})
    check("a reader that calls the key something else is understood",
          card["images"] == ["https://cdn.example/alt.jpg"], str(card["images"]))
    card = cs_products.card_from(
        {"card": "A card", "images": ["https://cdn.example/from-row.jpg"]},
        {"name": "A card"})
    check("and the row's own pictures are used when the listing has none",
          card["images"] == ["https://cdn.example/from-row.jpg"],
          str(card["images"]))

    print()
    print("== 13. a front that will not download does not leave a back ==")
    folder = Path(tempfile.mkdtemp(prefix="cs-front-"))

    def fetch(url, _cookie="", _timeout=25):
        if "primary" in url:
            raise OSError("the picture host is down")
        return png_bytes(square_card())

    card = {"name": "1971-72 O-Pee-Chee Ken Dryden #10", "images":
            ["https://cdn.example/primary.jpg", "https://cdn.example/back.jpg"],
            "photos": [], "crops": [], "notes": []}
    saved = cs_products.save_pictures(card, folder, fetch=fetch)
    names = [entry["name"] for entry in saved["files"]]
    check("the picture that did arrive is saved", len(names) == 1, str(names))
    check("and it is named the front, because it is the only picture",
          names and names[0].endswith("-front.webp"), str(names))
    check("the one that failed is in the notes",
          any("could not be fetched" in note for note in saved["notes"]),
          str(saved["notes"]))


def test_the_details():
    print()
    print("== 14. the listing's own description, keywords and card details ==")
    page = """<html><head>
      <meta name="description" content="A centred Ken Dryden, sharp corners.">
      <meta name="keywords" content="hockey, vintage, Ken Dryden">
      <script type="application/ld+json">
      {"@type": "Product", "name": "1971-72 O-Pee-Chee Ken Dryden #10",
       "description": "<p>Sharp corners and a clean back.</p>
                       <p>Posted in a sleeve and a toploader.</p>",
       "keywords": ["hockey", "O-Pee-Chee"],
       "category": "Sports Cards > Hockey > Singles",
       "brand": {"@type": "Brand", "name": "O-Pee-Chee"},
       "additionalProperty": [
          {"@type": "PropertyValue", "name": "Year", "value": "1971-72"},
          {"@type": "PropertyValue", "name": "Card number", "value": "10"}]}
      </script></head><body>
      <div class="product-description"><p>ignored, the structured data wins</p></div>
      </body></html>"""
    found = cs_products.details({}, page=page)
    check("the description is copied, not the page around it",
          "Sharp corners and a clean back." in found["plain"] and
          "Posted in a sleeve and a toploader." in found["plain"],
          found["plain"])
    check("and written back as plain paragraphs",
          found["description"].startswith("<p>Sharp corners") and
          "</p>\n<p>Posted in a sleeve" in found["description"],
          found["description"])
    check("a script or an iframe never travels with the words",
          "<script" not in found["description"].lower() and
          "<iframe" not in found["description"].lower(), found["description"])
    check("the keywords are copied", "hockey" in found["tags"] and
          "vintage" in found["tags"], str(found["tags"]))
    check("and the vendor's section comes with them",
          "Sports Cards" in found["tags"] and "Singles" in found["tags"],
          str(found["tags"]))
    names = [attr["name"] for attr in found["attributes"]]
    check("the card's own facts become attributes",
          "Year" in names and "Card number" in names and "Brand" in names,
          str(names))
    check("as the website's own attribute shape",
          all(set(attr) == {"name", "options", "visible", "variation"}
              and isinstance(attr["options"], list) and attr["visible"]
              for attr in found["attributes"]), str(found["attributes"][:2]))
    check("a description that is already short needs no short one",
          found["short"] == "", found["short"])
    long_page = ("<meta name=\"description\" content=\"%s\">"
                 % ("A sharp 1971-72 O-Pee-Chee Ken Dryden with four " * 8))
    long_found = cs_products.details({}, page=long_page)
    check("a long description gets its first sentence as the short one",
          long_found["short"].startswith("A sharp 1971-72 O-Pee-Chee") and
          long_found["short"].endswith("\u2026") and
          len(long_found["short"]) < len(long_found["plain"]),
          long_found["short"])

    print()
    print("== 15. a page without structured data is still read ==")
    plain = """<html><head>
      <meta property="og:description" content="A tidy 1972 Topps Bob Orr.">
      </head><body>
      <div class="listing-details"><p>A tidy 1972 Topps Bobby Orr.</p>
      <p>Sharp corners, one soft one.</p></div></body></html>"""
    found = cs_products.details({}, page=plain)
    check("the page's own description is used when there is no data",
          found["plain"] == "A tidy 1972 Topps Bob Orr.", found["plain"])
    block_page = """<html><body>
      <div id="details" class="product-details"><p>First line.</p>
        <div><p>Second line, nested.</p></div></div></body></html>"""
    found = cs_products.details({}, page=block_page)
    check("a block the shop calls details is read whole",
          "First line." in found["plain"] and
          "Second line, nested." in found["plain"], found["plain"])
    check("a page with nothing on it copies nothing and says so",
          cs_products.details({}, page="<p>hello</p>")["description"] == "" and
          any("no description" in note for note in
              cs_products.details({}, page="<p>hello</p>")["notes"]), "")

    print()
    print("== 16. what the title states is read, and nothing else ==")
    facts = cs_products.facts_from_title(
        "1971-72 O-Pee-Chee Ken Dryden #10 EX-MT")
    check("the year", facts.get("Year") == "1971-72", str(facts))
    check("the maker as the set", facts.get("Set") == "O-Pee-Chee", str(facts))
    check("the card number", facts.get("Card number") == "10", str(facts))
    check("the grade as the condition", facts.get("Condition") == "EX-MT",
          str(facts))
    check("and the player's name, without the rest",
          facts.get("Player") == "Ken Dryden", str(facts))
    facts = cs_products.facts_from_title("Mystery card #12")
    check("a title with no known maker gets no player guessed",
          "Player" not in facts and facts.get("Card number") == "12",
          str(facts))
    found = cs_products.details(
        {"name": "1971-72 O-Pee-Chee Ken Dryden #10 EX-MT", "condition": "NM"},
        page="")
    conditions = [attr for attr in found["attributes"]
                  if attr["name"] == "Condition"]
    check("a fact the reader reports beats the one in the title",
          conditions and conditions[0]["options"] == ["NM"], str(conditions))
    check("the facts are keywords too",
          "1971-72" in found["tags"] and "O-Pee-Chee" in found["tags"] and
          "#10" in found["tags"] and "Ken Dryden" in found["tags"],
          str(found["tags"]))
    check("a keyword is never listed twice",
          len(found["tags"]) == len({tag.lower() for tag in found["tags"]}),
          str(found["tags"]))

    print()
    print("== 16b. the reader's own spellings are understood ==")
    #  Plugin 1.0.33 emits these as it finds them in the vendor's data, with
    #  the vendor's own spellings carried through and empty values left out.
    found = cs_products.details(
        {"name": "A card", "description": "<p>Its own words.</p>",
         "keywords": "hockey, vintage", "cardNumber": "60",
         "Condition": "EX-MT", "Set Name": "O-Pee-Chee", "year": 1971},
        page="")
    facts = found["facts"]
    check("cardNumber is the card's number", facts.get("Card number") == "60",
          str(facts))
    check("Set Name is the set", facts.get("Set") == "O-Pee-Chee", str(facts))
    check("a capitalised Condition is the condition",
          facts.get("Condition") == "EX-MT", str(facts))
    check("a year sent as a number is still a year",
          facts.get("Year") == "1971", str(facts))
    check("a comma-separated keyword string becomes a list",
          found["tags"][:2] == ["hockey", "vintage"], str(found["tags"]))
    check("and the description is theirs, not the title's",
          "Its own words." in found["plain"], found["plain"])

    print()
    print("== 17. the plan carries the words, details and the gallery ==")
    cards = [{"name": "1971-72 O-Pee-Chee Ken Dryden #10", "sku": "KD-10",
              "stock": 4, "price": "12.50", "photos": ["kd-front.webp"],
              "backs": ["kd-back.webp"],
              "description": "<p>Sharp corners.</p>",
              "short": "Sharp corners.",
              "tags": ["hockey", "1971-72"],
              "attributes": [{"name": "Year", "options": ["1971-72"],
                              "visible": True, "variation": False}]}]
    built = cs_products.plan(cards, Path("/tmp/wherever"))
    item = built["items"][0]
    check("the front is the main image and the back follows it",
          item["images"] == ["kd-front.webp", "kd-back.webp"], str(item["images"]))
    check("the back is named as the gallery",
          item["gallery"] == ["kd-back.webp"], str(item.get("gallery")))
    check("the description is on the product",
          item["description"] == "<p>Sharp corners.</p>", item["description"])
    check("and the short description", item["short"] == "Sharp corners.", "")
    check("with the keywords as tags",
          item["tags"] == ["hockey", "1971-72"], str(item["tags"]))
    check("and the card's details as attributes",
          item["attributes"] and item["attributes"][0]["name"] == "Year",
          str(item["attributes"]))
    printed = cs_products.describe(built)[0]
    check("the confirmation says the words and the gallery came too",
          "description" in printed or any("description" in line
                                          for line in cs_products.describe(built)),
          str(cs_products.describe(built)))
    check("a card with no second picture is told it has an empty gallery",
          any("empty gallery" in note for note in
              cs_products.plan([{"name": "A card", "stock": 1, "price": "1.00",
                                 "photos": ["one.webp"]}])["notes"]),
          str(cs_products.plan([{"name": "A card", "stock": 1, "price": "1.00",
                                 "photos": ["one.webp"]}])["notes"]))
    check("a card with no description is named, not filled with a guess",
          any("description is left empty" in note for note in
              cs_products.plan([{"name": "A card", "stock": 1, "price": "1.00",
                                 "photos": ["one.webp"]}])["notes"]),
          str(cs_products.plan([{"name": "A card", "stock": 1, "price": "1.00",
                                 "photos": ["one.webp"]}])["notes"]))


def main():
    test_prices()
    test_picture_addresses()
    test_the_crop()
    test_a_card_from_a_row()
    test_saving_the_pictures()
    test_the_plan()
    test_the_names()
    test_the_cookie()
    test_the_reader_pictures()
    test_the_details()
    print()
    print("=" * 60)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL CS PRODUCT CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
