#!/usr/bin/env python3
"""The order sheet: the quote's own paper, with a picture of every card.

    python test-order-pdf.py

No network and no Tk. The facts an order holds are checked against what the
sheet prints, the pictures are checked by their colour appearing (or not) on
the page, and the paper itself is compared with the quote's - same band, same
colour, same logo plate - because "the same settings as the quote PDF" is a
claim about pixels, not about intentions.
"""
import tempfile
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

import order_pdf
import quote as quote_model
import quote_pdf

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


# ------------------------------------------------------------------ fixtures
def card_picture(colour, size=(300, 420)):
    """A card-shaped block of one colour, so its pixels are unmistakable."""
    image = Image.new("RGB", size, colour)
    draw = ImageDraw.Draw(image)
    draw.rectangle([10, 10, size[0] - 10, size[1] - 10], outline=(255, 255, 255),
                   width=4)
    return image


GREEN = (0, 255, 0)
RED = (255, 0, 0)


def quote_with_cards():
    quote = quote_model.new_quote(number="Q-2026-0001", company="Piskun Cards",
                                  currency="C$", today=date(2026, 10, 30))
    quote["customer"].update({"name": "Dana Whitfield",
                              "email": "dana@example.com",
                              "phone": "(519) 555-0142",
                              "address": "18 Maple Row\nOrangeville, ON L9W 2C3"})
    quote["notes"] = "Prices in Canadian dollars."
    quote["look"]["color"] = "#1F4E79"
    for product_id, name, price in (
            (501, "1989 O-Pee-Chee Batman #1 NM 7", "4.00"),
            (502, "1989 O-Pee-Chee Batman #2 EX-MT 6", "5.50")):
        quote_model.add_item(quote, {
            "id": product_id, "name": name, "price": price,
            "sku": "BAT-%02d" % product_id,
            "images": [{"src": "https://shop.example/card-%d.jpg" % product_id}]})
    quote_model.set_quantity(quote, 1, 2)
    quote["discount"] = {"kind": "amount", "value": 2.0}
    return quote


def order_for(quote, **overrides):
    order = {
        "id": 4321, "number": "4321", "status": "processing",
        "currency": "CAD", "date_created": "2026-10-30T14:00:00",
        "date_paid": "2026-10-30T14:05:00",
        "total": "12.50", "discount_total": "2.00", "shipping_total": "0.00",
        "total_tax": "0.00", "prices_include_tax": True,
        "fee_lines": [{"name": "Deposit taken", "total": "-2.00"}],
        "billing": {"first_name": "Dana", "last_name": "Whitfield",
                    "email": "dana@example.com", "phone": "(519) 555-0142",
                    "address_1": "18 Maple Row", "city": "Orangeville",
                    "state": "ON", "postcode": "L9W 2C3", "country": "CA"},
        "shipping": {"first_name": "Dana", "last_name": "Whitfield",
                     "address_1": "18 Maple Row", "city": "Orangeville",
                     "state": "ON", "postcode": "L9W 2C3", "country": "CA"},
        "line_items": [
            {"name": "1989 O-Pee-Chee Batman #1 NM 7", "product_id": 501,
             "quantity": 1, "price": 4.0, "total": "4.00", "sku": "BAT-01",
             "image": {"src": "https://shop.example/card-501.jpg"}},
            {"name": "1989 O-Pee-Chee Batman #2 EX-MT 6", "product_id": 502,
             "quantity": 2, "price": 5.5, "total": "11.00", "sku": "BAT-02",
             "image": {"src": "https://shop.example/card-502.jpg"}}],
        "customer_note": "Please pack well.",
    }
    order.update(overrides)
    return order


# ------------------------------------------------------------------- 1. facts
def test_facts():
    print()
    print("== 1. what the order sheet says ==")
    quote = quote_with_cards()
    order = order_for(quote)
    sheet = order_pdf.document(quote=quote, order=order)
    check("the order's own number is the sheet's number",
          sheet["number"] == "4321", sheet["number"])
    check("and the quote it came from is named on it",
          sheet["quote_number"] == "Q-2026-0001", sheet["quote_number"])
    check("the state reads as words, not the shop's slug",
          sheet["status"] == "Processing - paid", sheet["status"])
    check("a paid order says when it was paid", sheet["paid"] == "2026-10-30",
          sheet["paid"])
    check("the cards come from the order, quantities and all",
          [(item["quantity"], item["total"]) for item in sheet["items"]] ==
          [(1, 4.0), (2, 11.0)], sheet["items"])
    check("a row's price is the order's own, not the quote's",
          [item["price"] for item in sheet["items"]] == [4.0, 5.5],
          sheet["items"])
    check("the delivery address is the shipping one, as lines",
          sheet["customer"]["address"] ==
          "18 Maple Row\nOrangeville, ON L9W 2C3",
          sheet["customer"]["address"])
    check("the customer keeps their name and contacts", sheet["customer"]
          ["name"] == "Dana Whitfield" and sheet["customer"]["email"] ==
          "dana@example.com", sheet["customer"])
    check("the picture travels with the card",
          [bool(item["image"]) for item in sheet["items"]] == [True, True],
          sheet["items"])
    check("the discount is named as the order named it",
          sheet["discount"] == 2.0 and sheet["discount_label"] ==
          "Deposit taken", (sheet["discount"], sheet["discount_label"]))
    check("the sheet's own figures add up to the order's total",
          round(sheet["subtotal"] - sheet["discount"] + sheet["shipping"]
                + sheet["tax"] + sheet["other"], 2) == sheet["total"],
          (sheet["subtotal"], sheet["discount"], sheet["other"],
           sheet["total"]))
    check("the currency signs the way the quote did", sheet["currency"] == "C$",
          sheet["currency"])
    check("the customer's note is carried over, not dropped",
          sheet["customer_note"] == "Please pack well.", sheet["customer_note"])

    #  An order on its own, with no quote to lean on.
    alone = order_pdf.document(order=order, look={"company": "Piskun Cards"})
    check("an order with no quote still prints its cards",
          len(alone["items"]) == 2, alone["items"])
    check("and takes the shop's own currency when nothing says otherwise",
          alone["currency"] == "C$", alone["currency"])
    check("it invents no quote number", alone["quote_number"] == "",
          alone["quote_number"])

    #  A quote with no order: what the no-keys path prints.
    draft = quote_model.new_quote(number="Q-2026-0009", currency="C$",
                                  today=date(2026, 10, 30))
    quote_model.add_item(draft, {"id": 7, "name": "A typed card",
                                 "price": "3.00"})
    solo = order_pdf.document(quote=draft, look={"color": "#C62828"})
    check("a quote that never became an order prints as a quote-shaped sheet",
          solo["number"] == "" or solo["number"] == "Q-2026-0009",
          solo["number"])
    check("with the quote's own total", solo["total"] == 3.0, solo["total"])
    check("and the look that was handed to it",
          solo["look"]["color"] == "#C62828", solo["look"])
    lined = order_pdf.document(quote=quote, order=order,
                               look={"contact": "18 Maple Row\npiskuncards.ca"})
    check("a two-line contact block is not run onto one line",
          lined["look"]["contact"] == "18 Maple Row\npiskuncards.ca",
          lined["look"]["contact"])

    #  Totals the order states but the rows do not add up to: named, not hidden.
    #  15.00 of cards less a 2.00 discount plus 1.50 of tax is 14.50.
    taxed = order_pdf.document(order=order_for(
        quote, total="14.50", total_tax="1.50", prices_include_tax=False))
    check("a tax line is printed when the shop charges tax apart",
          taxed["tax"] == 1.5 and taxed["other"] == 0.0
          and round(taxed["subtotal"] - taxed["discount"] + taxed["shipping"]
                    + taxed["tax"], 2) == taxed["total"],
          (taxed["subtotal"], taxed["tax"], taxed["total"]))
    included = order_pdf.document(order=order_for(
        quote, total="13.00", total_tax="1.50", prices_include_tax=True))
    check("and no tax line when the prices already hold it",
          included["tax"] == 0.0, (included["tax"], included["other"]))
    check("so the column adds up to the total the customer was charged",
          included["other"] == 0.0
          and round(included["subtotal"] - included["discount"]
                    + included["shipping"] + included["tax"], 2) ==
          included["total"], (included["subtotal"], included["total"]))
    #  A charge this sheet has no line for is named, never swallowed.
    odd = order_pdf.document(order=order_for(quote, total="16.00"))
    check("a charge nothing explains is named rather than hidden",
          odd["other"] == 3.0, odd["other"])

    unknown = order_pdf.document(order=order_for(quote, status="wc-custom"))
    check("a state this file has not met is printed rather than hidden",
          unknown["status"] == "Wc custom", unknown["status"])


# ---------------------------------------------------------------- 2. pictures
def test_pictures():
    print()
    print("== 2. the pictures on the sheet ==")
    folder = Path(tempfile.mkdtemp())
    served = {"https://shop.example/a.jpg": GREEN and
              _bytes(card_picture(GREEN)),
              "https://shop.example/b.jpg": _bytes(card_picture(RED))}
    asked = []

    def opener(url, timeout):
        asked.append(url)
        if url not in served:
            raise OSError("404")
        return served[url]

    urls = ["https://shop.example/a.jpg", "https://shop.example/b.jpg"]
    found = order_pdf.fetch_images(urls, folder, opener=opener)
    check("every picture that answered is kept", len(found) == 2, found)
    check("and kept in the documents folder", all(
        Path(path).parent == folder / order_pdf.CACHE_DIRNAME
        for path in found.values()), found)
    check("the file on disk is a real picture",
          Image.open(found[urls[0]]).size == (300, 420))

    again = order_pdf.fetch_images(urls, folder, opener=opener)
    check("a second print reads the kept copy instead of the shop",
          len(asked) == 2 and len(again) == 2, asked)

    nothing = order_pdf.fetch_images(["https://shop.example/gone.jpg"], folder,
                                     opener=opener)
    check("a picture the shop will not give costs that card its photo, "
          "nothing more", nothing == {}, nothing)

    progress = []
    order_pdf.fetch_images(["https://shop.example/gone.jpg"], folder,
                           opener=opener,
                           progress=lambda done, total: progress.append(
                               (done, total)))
    check("and it says how far along it is while it tries",
          progress == [(1, 1)], progress)


def _bytes(image):
    import io
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


# ------------------------------------------------------------------- 3. paper
def test_paper():
    print()
    print("== 3. the same paper as the quote ==")
    quote = quote_with_cards()
    order = order_for(quote)
    sheet = order_pdf.document(quote=quote, order=order)
    dpi = 100
    quote_page = quote_pdf.build_pages(quote, dpi=dpi)[0]
    pages, counts = order_pdf.build_pages(sheet, dpi=dpi)
    page = pages[0]
    check("a page is A4, exactly as the quote's is",
          page.size == quote_page.size == (827, 1169), page.size)
    band = int(round(0.05 * quote_pdf.PAGE_INCHES[1] * dpi))
    margin = int(round(quote_pdf.MARGIN * dpi))
    check("the band is the quote's own colour, not a second palette",
          page.getpixel((margin - 2, band)) ==
          quote_page.getpixel((margin - 2, band)) == (31, 78, 121),
          (page.getpixel((margin - 2, band)),
           quote_page.getpixel((margin - 2, band))))
    check("the sheet says ORDER where the quote says QUOTE",
          page.tobytes() != quote_page.tobytes())

    #  A logo, drawn on the same white plate the quote uses.
    logo = card_picture((10, 10, 10), size=(240, 120))
    logo_path = Path(tempfile.mkdtemp()) / "logo.png"
    logo.save(logo_path)
    sheet["look"]["logo"] = str(logo_path)
    quote["look"]["logo"] = str(logo_path)
    with_logo = order_pdf.build_pages(sheet, dpi=dpi)[0][0]
    quote_logo = quote_pdf.build_pages(quote, dpi=dpi)[0]
    box = [margin, int(0.02 * quote_pdf.PAGE_INCHES[1] * dpi)]
    strip = [with_logo.getpixel((x, box[1] + 8)) for x in range(box[0], 300)]
    quote_strip = [quote_logo.getpixel((x, box[1] + 8)) for x in range(box[0], 300)]
    check("a dark logo still gets its white plate on the order too",
          quote_pdf.WHITE in strip and quote_pdf.WHITE in quote_strip, strip[:6])
    check("and the plate is in the same place as the quote's",
          strip.index(quote_pdf.WHITE) == quote_strip.index(quote_pdf.WHITE),
          (strip.index(quote_pdf.WHITE), quote_strip.index(quote_pdf.WHITE)))

    #  The pictures are on the page: their exact colour is nowhere else.
    images = {"https://shop.example/card-501.jpg": card_picture(GREEN),
              "https://shop.example/card-502.jpg": card_picture(RED)}
    with_pictures, counts = order_pdf.build_pages(sheet, images=images, dpi=dpi)
    drawn = with_pictures[0].getcolors(maxcolors=1 << 24) or []
    colours = {colour for count, colour in drawn if count > 50}
    check("each card's picture is drawn on its row",
          GREEN in colours and RED in colours, sorted(colours)[:6])
    check("and the count says how many were found", counts == {"pictures": 2,
                                                              "missing": 0},
          counts)
    without, counts = order_pdf.build_pages(sheet, dpi=dpi)
    colours = {colour for count, colour in
               (without[0].getcolors(maxcolors=1 << 24) or []) if count > 50}
    check("a card with no picture gets a box that says so, not a blank",
          GREEN not in colours and RED not in colours and counts["missing"] == 2,
          counts)


# ------------------------------------------------------------------ 4. pages
def test_pages():
    print()
    print("== 4. a long order, and the file itself ==")
    quote = quote_with_cards()
    order = order_for(quote)
    many = [{"name": "1989 O-Pee-Chee Batman #%d NM 7" % number,
             "product_id": 1000 + number, "quantity": 1, "price": 4.0,
             "total": "4.00", "sku": "BAT-%03d" % number,
             "image": ""} for number in range(1, 31)]
    long_sheet = order_pdf.document(order=dict(order, line_items=many,
                                               total="120.00"))
    pages, _counts = order_pdf.build_pages(long_sheet, dpi=100)
    check("thirty cards overrun one page", len(pages) > 1, len(pages))
    check("every page is A4", all(page.size == (827, 1169) for page in pages),
          [page.size for page in pages])

    root = Path(tempfile.mkdtemp())
    info = order_pdf.render(long_sheet, root / "order.pdf", dpi=100)
    check("the PDF is written where it was asked for",
          info["path"].is_file() and info["path"].stat().st_size > 5000, info)
    check("with every page of the sheet in it", info["pages"] == len(pages),
          info)
    raw = (root / "order.pdf").read_bytes()
    check("and the file really is a PDF",
          raw.startswith(b"%PDF-1.") and raw.rstrip().endswith(b"%%EOF"),
          raw[:8] + b" ... " + raw.rstrip()[-6:])
    check("with one page object per sheet page",
          raw.count(b"/Type /Page\n") + raw.count(b"/Type /Page ") ==
          info["pages"], raw.count(b"/Type /Page"))

    empty = order_pdf.document(order={"number": "1", "line_items": []})
    pages, _counts = order_pdf.build_pages(empty, dpi=100)
    check("an order with no cards still prints one page rather than nothing",
          len(pages) == 1, len(pages))


def main():
    print("Order sheet checks")
    print("=" * 60)
    test_facts()
    test_pictures()
    test_paper()
    test_pages()
    print()
    print("=" * 60)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        raise SystemExit(1)
    print("ALL ORDER SHEET CHECKS PASSED (%d)" % PASS)


if __name__ == "__main__":
    main()
