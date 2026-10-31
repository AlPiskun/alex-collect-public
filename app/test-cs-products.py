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


def main():
    test_prices()
    test_picture_addresses()
    test_the_crop()
    test_a_card_from_a_row()
    test_saving_the_pictures()
    test_the_plan()
    test_the_names()
    test_the_cookie()
    print()
    print("=" * 60)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL CS PRODUCT CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
