"""The printed order: the quote's own paper, with a picture of every card.

A quote is what the customer is asked to agree to; an order is what gets
packed. The two documents are deliberately the same sheet - same logo, same
colour, same type, same margins - because they come from the same shop, and
building the order page out of :mod:`quote_pdf` is how "the same settings"
stays true instead of being a promise to keep two drawings in step.

What is different is the card table: every row carries the card's photograph,
so the person packing the box can hold a card against the sheet and see it is
the right one. That picture is a URL on the order (or on the quote row), and
this module downloads it once, caches it beside the documents, and draws a
"no photo" box rather than failing when a shop will not hand it over.

Nothing here talks to the website except :func:`fetch_images`, which only ever
fetches pictures: the facts of an order come from the caller, so the sheet can
be drawn from an order the website just returned, an order read back by its
number, or a quote that has one - with no network at all in a test.
"""
from __future__ import annotations

import hashlib
import urllib.request
from datetime import date
from pathlib import Path

from PIL import Image

import quote as quote_model
import quote_pdf

#: What the shop asks when we fetch a picture. A browser's own string would be
#: a lie; the shops that matter serve these to anything.
USER_AGENT = "AlexCollect order sheet"

#: Where the pictures are kept between prints, inside the documents folder.
CACHE_DIRNAME = ".images"

#: The shop's order states in words a packer can read. A status this file has
#: not met is printed as it came, capitalised, rather than being hidden.
STATUS_WORDS = {
    "pending": "Pending - not paid yet",
    "processing": "Processing - paid",
    "on-hold": "On hold",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "refunded": "Refunded",
    "failed": "Failed",
    "draft": "Not an order yet",
    "ordered": "Ordered",
}

#: A shop returns ``CAD`` where the quote prints ``C$``. When there is a quote
#: its own symbol is used, so both documents agree; an order on its own gets
#: the sign the shop's currency is normally written with.
CURRENCY_SIGNS = {"CAD": "C$", "USD": "$", "EUR": "\u20ac", "GBP": "\u00a3",
                  "AUD": "A$", "NZD": "NZ$", "JPY": "\u00a5"}

#: The picture column, in inches. A trading card is 2.5 by 3.5, so the box is
#: drawn at that shape and the image is fitted inside it.
PICTURE_WIDTH = 0.60
PICTURE_RATIO = 1.4


# ------------------------------------------------------------------- facts
def _text(value):
    """One line of text, with the runs of whitespace a shop sends flattened."""
    return " ".join(str(value or "").split())


def _number(value):
    """A price the shop sent, as a float - or ``None`` when it is not one."""
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _address_lines(fields):
    """Woo's address fields as the lines that go on an envelope."""
    lines = []
    for key in ("address_1", "address_2"):
        text = _text(fields.get(key))
        if text:
            lines.append(text)
    locality = " ".join(part for part in (_text(fields.get("state")),
                                          _text(fields.get("postcode"))) if part)
    town = ", ".join(part for part in (_text(fields.get("city")), locality)
                     if part)
    if town:
        lines.append(town)
    country = _text(fields.get("country")).upper()
    if country and country not in ("CA", "CAN", "CANADA"):
        #  The shop is Canadian, so "CA" on every sheet would be noise; an
        #  order going anywhere else says where it is going.
        lines.append(country)
    return "\n".join(lines)


def _customer_from_order(order):
    """Who the order is for: the shipping address if there is one."""
    billing = order.get("billing") or {}
    shipping = order.get("shipping") or {}
    has_shipping = any(_text(shipping.get(key))
                       for key in ("address_1", "address_2", "city"))
    fields = shipping if has_shipping else billing
    first = _text(fields.get("first_name")) or _text(billing.get("first_name"))
    last = _text(fields.get("last_name")) or _text(billing.get("last_name"))
    return {"name": ("%s %s" % (first, last)).strip(),
            "address": _address_lines(fields) if fields else "",
            "email": _text(billing.get("email")),
            "phone": _text(billing.get("phone"))}


def _picture_of_order_row(row, quote_images):
    image = row.get("image")
    if isinstance(image, dict) and _text(image.get("src")):
        return _text(image.get("src"))
    if isinstance(image, str) and image.strip():
        return image.strip()
    try:
        product_id = int(row.get("product_id") or 0)
    except (TypeError, ValueError):
        product_id = 0
    return quote_images.get(product_id, "")


def _items_from_order(order, quote_images):
    items = []
    for row in order.get("line_items") or []:
        if not isinstance(row, dict):
            continue
        quantity = max(1, int(row.get("quantity") or 1))
        price = _number(row.get("price"))
        total = _number(row.get("total"))
        if total is None and price is not None:
            total = price * quantity
        items.append({"name": _text(row.get("name")) or "Card",
                      "sku": _text(row.get("sku")),
                      "quantity": quantity,
                      "price": price,
                      "total": total,
                      "image": _picture_of_order_row(row, quote_images)})
    return items


def _items_from_quote(quote):
    items = []
    for row in quote_model.items_of(quote):
        items.append({"name": _text(row.get("name")) or "Card",
                      "sku": _text(row.get("sku")),
                      "quantity": quote_model.item_quantity(row),
                      "price": quote_model.item_price(row),
                      "total": quote_model.line_total(row),
                      "image": quote_model.item_image(row)})
    return items


def _totals_from_order(order, items):
    """Subtotal, discount, shipping and total, as the order states them.

    The subtotal is added up from the rows that are printed rather than read
    from the order, so the sheet always adds up to its own figures; the total
    is the order's own, because that is what the customer is charged.
    """
    known = [item["total"] for item in items if item["total"] is not None]
    subtotal = round(sum(known), 2) if known else None
    discount = _number(order.get("discount_total")) if order else None
    shipping = _number(order.get("shipping_total")) if order else None
    total = _number(order.get("total")) if order else None
    #  A shop that prices its products with the tax already in them has no
    #  tax line of its own, and printing one would read as a second charge.
    tax = 0.0 if (not order or order.get("prices_include_tax")) else \
        (_number(order.get("total_tax")) or 0.0)
    if total is None and subtotal is not None:
        total = round(subtotal - (discount or 0) + (shipping or 0) + tax, 2)
    if subtotal is None and total is not None:
        subtotal = round(total + (discount or 0) - (shipping or 0) - tax, 2)
    #  Anything left over is a charge this sheet has no line for - a coupon,
    #  a handling fee from another plugin. It is named rather than hidden, so
    #  the column always adds up to the total the customer was charged.
    other = 0.0
    if subtotal is not None and total is not None:
        other = round(total - (subtotal - (discount or 0) + (shipping or 0)
                               + tax), 2)
        if abs(other) < 0.01:
            other = 0.0
    label = ""
    for fee in order.get("fee_lines") or []:
        if not isinstance(fee, dict):
            continue
        if (_number(fee.get("total")) or 0) < 0:
            label = _text(fee.get("name"))
            break
    ship_label = "Shipping"
    for line in order.get("shipping_lines") or []:
        if isinstance(line, dict) and _text(line.get("method_title")):
            ship_label = _text(line.get("method_title"))
            break
    return {"subtotal": subtotal, "discount": discount or 0.0,
            "discount_label": label or "Discount",
            "shipping": shipping or 0.0, "shipping_label": ship_label,
            "tax": tax, "other": other, "total": total}


def document(quote=None, order=None, look=None, currency="", today=None):
    """Everything the order sheet prints, from a quote, an order, or both.

    ``order`` wins wherever it has an answer - it is what the website actually
    holds - and the quote fills the rest, so the sheet can be printed from the
    order that was just returned, from an order read back by its number, or
    from a quote alone when the website cannot be reached at all.
    """
    quote = dict(quote or {})
    order = dict(order or {})
    currency = (_text(currency) or _text(quote.get("currency"))
                or CURRENCY_SIGNS.get(_text(order.get("currency")).upper(),
                                      _text(order.get("currency"))).strip())
    merged = {key: value for key, value in (quote.get("look") or {}).items()}
    for key in ("company", "contact", "color", "logo"):
        if key == "contact":
            #  The contact block is several lines under the shop's name, so
            #  flattening it the way a single line is flattened would run the
            #  address into the website.
            value = str((look or {}).get(key) or "").strip()
        else:
            value = _text((look or {}).get(key))
        if value:
            merged[key] = value
    if not _text(merged.get("color")):
        merged["color"] = quote_model.DEFAULT_COLOR

    quote_images = {int(item.get("product_id") or 0): quote_model.item_image(item)
                    for item in quote_model.items_of(quote)}
    quote_images.pop(0, None)
    items = _items_from_order(order, quote_images) if order.get("line_items") \
        else _items_from_quote(quote)

    customer = _customer_from_order(order) if order else {}
    quote_customer = quote.get("customer") or {}
    for key in ("name", "address", "email", "phone"):
        if not _text(customer.get(key)):
            customer[key] = _text(quote_customer.get(key))

    sums = _totals_from_order(order, items) if order else {}
    if not sums:
        totals = quote_model.totals(quote) if quote else {}
        sums = {"subtotal": totals.get("subtotal"),
                "discount": totals.get("discount") or 0.0,
                "discount_label": totals.get("discount_label") or "Discount",
                "shipping": 0.0, "shipping_label": "Shipping",
                "tax": 0.0, "other": 0.0, "total": totals.get("total")}

    number = (_text(order.get("number")) or _text(order.get("id"))
              or _text(quote.get("order_number")))
    created = _text(order.get("date_created")) or _text(order.get("date_created_gmt"))
    issued = _text(quote.get("issued"))
    stamp = (created or issued
             or (today or date.today()).isoformat())
    state = (_text(order.get("status")).lower()
             or ("ordered" if _text(quote.get("order_number"))
                 else _text(quote.get("status")).lower())
             or "draft")
    paid = _text(order.get("date_paid")) or _text(order.get("date_paid_gmt"))
    notes = _text(quote.get("notes"))
    customer_note = _text(order.get("customer_note"))
    units = sum(item["quantity"] for item in items)
    return {
        "kind": "order",
        "number": number,
        "quote_number": _text(quote.get("number")),
        "date": stamp[:10],
        "state": state,
        "status": STATUS_WORDS.get(state, state.replace("-", " ").capitalize()),
        "paid": paid[:10] if paid else "",
        "customer": customer,
        "items": items,
        "lines": len(items),
        "units": units,
        "currency": currency,
        "subtotal": sums.get("subtotal"),
        "discount": sums.get("discount") or 0.0,
        "discount_label": sums.get("discount_label") or "Discount",
        "shipping": sums.get("shipping") or 0.0,
        "shipping_label": sums.get("shipping_label") or "Shipping",
        "tax": sums.get("tax") or 0.0,
        "other": sums.get("other") or 0.0,
        "total": sums.get("total"),
        "notes": notes,
        "customer_note": customer_note,
        "look": merged,
    }


# ---------------------------------------------------------------- pictures
def picture_urls(document):
    """Every picture the sheet needs, once each and in card order."""
    urls = []
    for item in (document or {}).get("items") or []:
        url = _text(item.get("image"))
        if url and url not in urls:
            urls.append(url)
    return urls


def _cache_name(url):
    return hashlib.sha1(str(url).encode("utf-8")).hexdigest()[:20] + ".img"


def _download(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_images(urls, folder, timeout=20, progress=None, opener=None):
    """Download the cards' pictures into the cache; returns ``{url: path}``.

    A picture that cannot be fetched is simply not in the answer: one broken
    image must not stop a forty-card order from printing, and the sheet draws
    a "no photo" box in its place. The cache is keyed by the URL, so printing
    the same order again - or an order holding the same card - reads the file
    instead of the shop.
    """
    cache = Path(str(folder)) / CACHE_DIRNAME
    opener = opener or _download
    found = {}
    urls = [url for url in (urls or []) if _text(url)]
    for index, url in enumerate(urls, 1):
        target = cache / _cache_name(url)
        if target.is_file() and target.stat().st_size:
            found[url] = target
        else:
            try:
                cache.mkdir(parents=True, exist_ok=True)
                data = opener(url, timeout)
                if data:
                    #  Written beside the name and moved into place, so a
                    #  download cut off halfway is never read back as a
                    #  complete picture.
                    partial = target.with_suffix(".part")
                    partial.write_bytes(data)
                    partial.replace(target)
                    found[url] = target
            except Exception:            # noqa: BLE001 - one bad picture
                pass
        if progress is not None:
            try:
                progress(index, len(urls))
            except Exception:            # noqa: BLE001 - a progress bar
                pass
    return found


def _load_picture(value):
    """A picture file, or an already-open image, as an image or ``None``."""
    if value is None:
        return None
    if isinstance(value, Image.Image):
        return value.convert("RGBA")
    try:
        picture = Image.open(str(value))
        picture.load()
    except (OSError, ValueError):
        return None
    return picture.convert("RGBA")


# ------------------------------------------------------------------ layout
def _picture_box(page):
    width = page.pt(PICTURE_WIDTH * 72)
    return width, int(round(width * PICTURE_RATIO))


def _card_column(page):
    """Where the card's name starts - to the right of the picture column."""
    width, _height = _picture_box(page)
    return page.margin + width + page.pt(8)


def _columns(page):
    right = page.right
    return {"quantity": right - int((right - page.margin) * 0.36),
            "price": right - int((right - page.margin) * 0.18),
            "amount": right}


def _table_rows(page, document, fonts):
    """Every row, wrapped to fit beside its picture, with the height it needs."""
    currency = document.get("currency") or ""
    body = fonts["body"]
    width = _columns(page)["quantity"] - _card_column(page) - page.pt(8)
    _pic_w, pic_h = _picture_box(page)
    rows = []
    for index, item in enumerate(document.get("items") or [], 1):
        lines = page.wrap(item.get("name"), body, width)
        price = item.get("price")
        total = item.get("total")
        text_height = (page.pt(6) + len(lines) * page.pt(13)
                       + (page.pt(11) if item.get("sku") else 0))
        rows.append({
            "index": index,
            "lines": lines,
            "sku": item.get("sku") or "",
            "quantity": item.get("quantity") or 1,
            "price": quote_model.money(price, currency) if price is not None
                     else "-",
            "amount": quote_model.money(total, currency) if total is not None
                      else "-",
            "image": item.get("image") or "",
            "height": max(pic_h + page.pt(8), text_height + page.pt(10)),
        })
    return rows


def _party_block(page, document, fonts, y):
    """Who it is going to, and the order's own facts, under the band."""
    left_width = int((page.right - page.margin) * 0.58)
    customer = document.get("customer") or {}
    label = fonts["label"]
    page.draw.text((page.margin, y), "DELIVER TO", font=label,
                   fill=page.colour)
    y_text = y + page.pt(15)
    name = _text(customer.get("name"))
    page.draw.text((page.margin, y_text), name or "No customer name",
                   font=fonts["h2"], fill=quote_pdf.INK)
    y_text += page.pt(17)
    body = fonts["body"]
    address = str(customer.get("address") or "").strip()
    if not address:
        page.draw.text((page.margin, y_text), "No address on this order",
                       font=fonts["small"], fill=quote_pdf.SOFT)
        y_text += page.pt(13)
    for line in page.wrap(address, body, left_width) if address else []:
        page.draw.text((page.margin, y_text), line, font=body,
                       fill=quote_pdf.INK)
        y_text += page.pt(13)
    for key in ("email", "phone"):
        text = _text(customer.get(key))
        if not text:
            continue
        page.draw.text((page.margin, y_text), text, font=body,
                       fill=quote_pdf.SOFT)
        y_text += page.pt(13)

    x = page.margin + int((page.right - page.margin) * 0.64)
    rows = [("ORDER", "#%s" % (document.get("number") or "-")),
            ("DATE", document.get("date") or "-"),
            ("STATUS", document.get("status") or "-"),
            ("CARDS", "%d (%d item%s)" % (document.get("lines") or 0,
                                          document.get("units") or 0,
                                          "" if (document.get("units") or 0) == 1
                                          else "s"))]
    if document.get("paid"):
        #  Only when money actually arrived: "Not paid yet" would just repeat
        #  the status line a row above it.
        rows.append(("PAID", document["paid"]))
    if document.get("quote_number"):
        rows.append(("FROM QUOTE", document["quote_number"]))
    y_row = y
    value = fonts["body_bold"]
    for heading, value_text in rows:
        page.draw.text((x, y_row), heading, font=label, fill=page.colour)
        page.draw.text((x + page.pt(80), y_row), str(value_text), font=value,
                       fill=quote_pdf.INK)
        y_row += page.pt(15)
    return max(y_text, y_row) + page.pt(10)


def _table_header(page, y, fonts):
    height = page.pt(22)
    page.draw.rectangle([page.margin, y, page.right, y + height],
                        fill=quote_pdf.tint(page.colour, 0.86))
    label = fonts["label"]
    colour = quote_pdf.shade(page.colour, 0.35)
    columns = _columns(page)
    page.draw.text((_card_column(page), y + page.pt(7)), "CARD", font=label,
                   fill=colour)
    for key, heading in (("quantity", "QTY"), ("price", "EACH"),
                         ("amount", "AMOUNT")):
        width = page.text_width(heading, label)
        page.draw.text((columns[key] - width, y + page.pt(7)), heading,
                       font=label, fill=colour)
    return y + height


def _draw_picture(page, x, y, picture):
    """The card's photograph in its box; ``False`` when there is none."""
    width, height = _picture_box(page)
    box = [x, y, x + width, y + height]
    page.draw.rectangle(box, fill=quote_pdf.tint(page.colour, 0.95),
                        outline=quote_pdf.RULE)
    if picture is None:
        text = "no photo"
        font = page.font(6.4)
        page.draw.text((x + (width - page.text_width(text, font)) / 2,
                        y + height / 2 - page.pt(4)), text, font=font,
                       fill=quote_pdf.SOFT)
        return False
    copy = picture.copy()
    copy.thumbnail((max(1, width - page.pt(3)), max(1, height - page.pt(3))),
                   Image.LANCZOS)
    page.image.paste(copy, (int(x + (width - copy.width) / 2),
                            int(y + (height - copy.height) / 2)),
                     copy if copy.mode == "RGBA" else None)
    return True


def _draw_row(page, y, row, fonts, zebra, images):
    columns = _columns(page)
    height = row["height"]
    if zebra:
        page.draw.rectangle([page.margin, y, page.right, y + height],
                            fill=quote_pdf.tint(page.colour, 0.965))
    picture = _load_picture((images or {}).get(row["image"]))
    drawn = _draw_picture(page, page.margin, y + page.pt(4), picture)
    body = fonts["body"]
    right = fonts["body"]
    x = _card_column(page)
    text_y = y + page.pt(7)
    for line in row["lines"]:
        page.draw.text((x, text_y), line, font=body, fill=quote_pdf.INK)
        text_y += page.pt(13)
    if row["sku"]:
        page.draw.text((x, text_y), row["sku"], font=fonts["small"],
                       fill=quote_pdf.SOFT)
    quantity = str(row["quantity"])
    page.draw.text((columns["quantity"] - page.text_width(quantity, right),
                    y + page.pt(7)), quantity, font=right, fill=quote_pdf.INK)
    for key in ("price", "amount"):
        value = row[key]
        page.draw.text((columns[key] - page.text_width(value, right),
                        y + page.pt(7)), value, font=right, fill=quote_pdf.INK)
    page.line(page.margin, y + height, page.right, quote_pdf.RULE)
    return y + height, drawn


def _draw_totals(page, document, fonts, y):
    currency = document.get("currency") or ""
    right = page.right
    box_left = right - int((right - page.margin) * 0.42)
    body = fonts["body"]
    amount_font = fonts["body_bold"]
    lines = [("Subtotal", quote_model.money(document.get("subtotal"), currency))]
    if (document.get("discount") or 0) > 0:
        lines.append((document.get("discount_label") or "Discount",
                      "\u2212" + quote_model.money(document["discount"],
                                                   currency)))
    if (document.get("shipping") or 0) > 0:
        lines.append((document.get("shipping_label") or "Shipping",
                      quote_model.money(document["shipping"], currency)))
    if (document.get("tax") or 0) > 0:
        lines.append(("Tax", quote_model.money(document["tax"], currency)))
    if (document.get("other") or 0) != 0:
        lines.append(("Other", quote_model.money(document["other"], currency)))
    for label, value in lines:
        page.draw.text((box_left, y), label, font=body, fill=quote_pdf.SOFT)
        page.draw.text((right - page.text_width(value, amount_font), y), value,
                       font=amount_font, fill=quote_pdf.INK)
        y += page.pt(17)
    y += page.pt(3)
    height = page.pt(30)
    page.draw.rounded_rectangle([box_left - page.pt(10), y, right + 2,
                                 y + height], radius=page.pt(4),
                                fill=page.colour)
    total = quote_model.money(document.get("total"), currency)
    page.draw.text((box_left, y + page.pt(10)), "TOTAL",
                   font=fonts["label"], fill=page.on_colour)
    page.draw.text((right - page.text_width(total, fonts["h2"]) - page.pt(2),
                    y + page.pt(5)), total, font=fonts["h2"],
                   fill=page.on_colour)
    return y + height


def _draw_notes(page, document, fonts, y):
    blocks = []
    if document.get("customer_note"):
        blocks.append("Customer's note: %s" % document["customer_note"])
    if document.get("notes"):
        blocks.append(document["notes"])
    if not blocks:
        return y
    text = "\n".join(blocks)
    available = quote_pdf.reserve_footer(page) - y
    if available < page.pt(30):
        return y
    body = fonts["body"]
    lines = page.wrap(text, body, page.right - page.margin - page.pt(24))
    height = page.pt(12) + len(lines) * page.pt(13)
    if height > available:
        lines = lines[:max(1, (available - page.pt(12)) // page.pt(13))]
        height = page.pt(12) + len(lines) * page.pt(13)
    page.draw.rounded_rectangle([page.margin, y, page.right, y + height],
                                radius=page.pt(4),
                                fill=quote_pdf.tint(page.colour, 0.93))
    text_y = y + page.pt(7)
    for line in lines:
        page.draw.text((page.margin + page.pt(10), text_y), line, font=body,
                       fill=quote_pdf.INK)
        text_y += page.pt(13)
    return y + height


def _draw_signoff(page, fonts, y):
    """Two lines to write on when the box is closed, not a signature block."""
    bottom = quote_pdf.reserve_footer(page)
    if y + page.pt(46) > bottom:
        return y
    y += page.pt(10)
    left, right = page.margin, page.right
    width = int((right - left) * 0.36)
    label = fonts["label"]
    page.draw.text((left, y), "PACKED BY", font=label, fill=page.colour)
    page.draw.text((left + int((right - left) * 0.52), y), "DATE",
                   font=label, fill=page.colour)
    line_y = y + page.pt(20)
    page.line(left, line_y, left + width, quote_pdf.shade(page.colour, 0.6))
    page.line(left + int((right - left) * 0.52), line_y,
              right - int((right - left) * 0.28),
              quote_pdf.shade(page.colour, 0.6))
    return line_y + page.pt(8)


def build_pages(document, images=None, dpi=quote_pdf.PRINT_DPI):
    """Every page of the order sheet, as images - the PDF is these in order."""
    colour = quote_pdf.parse_colour((document.get("look") or {}).get("color"))
    rows = None
    index = 0
    pages = []
    drawn = [0, 0]
    while True:
        page = quote_pdf.Page(dpi)
        page.colour = colour
        page.on_colour = quote_pdf.text_on(colour)
        page.logo = quote_pdf.load_logo((document.get("look") or {}).get("logo"))
        fonts = quote_pdf.fonts_for(page)
        if not pages:
            y = quote_pdf.draw_band(page, document.get("look"), "ORDER",
                                    document.get("number"), fonts,
                                    first_page=True)
            y = _party_block(page, document, fonts, y + page.pt(16))
        else:
            y = quote_pdf.draw_band(page, document.get("look"), "ORDER",
                                    document.get("number"), fonts,
                                    first_page=False)
            y += page.pt(12)
        if rows is None:
            rows = _table_rows(page, document, fonts)
        if rows:
            y = _table_header(page, y, fonts)
        #  Same rule as the quote: a page either holds its cards *and* the
        #  totals beneath them, or it is filled edge to edge with cards and
        #  the totals wait for the page that ends the order.
        full = quote_pdf.reserve_footer(page) - page.pt(10)
        tail = page.pt(210)
        fits_full, cursor = 0, y
        while index + fits_full < len(rows) and \
                cursor + rows[index + fits_full]["height"] <= full:
            cursor += rows[index + fits_full]["height"]
            fits_full += 1
        roomy, cursor = 0, y
        while index + roomy < len(rows) and \
                cursor + rows[index + roomy]["height"] <= full - tail:
            cursor += rows[index + roomy]["height"]
            roomy += 1
        remaining = len(rows) - index
        take = remaining if remaining <= roomy else max(1, fits_full)
        placed = 0
        while placed < take and index < len(rows):
            y, was_drawn = _draw_row(page, y, rows[index], fonts,
                                     zebra=index % 2 == 1, images=images)
            drawn[0 if was_drawn else 1] += 1
            index += 1
            placed += 1
        more = index < len(rows) and placed > 0
        if not more:
            if not rows:
                page.draw.text((page.margin, y + page.pt(12)),
                               "No cards on this order yet.",
                               font=fonts["body"], fill=quote_pdf.SOFT)
                y += page.pt(30)
            y += page.pt(14)
            y = _draw_totals(page, document, fonts, y)
            y = _draw_notes(page, document, fonts, y + page.pt(16))
            _draw_signoff(page, fonts, y + page.pt(6))
        pages.append(page.image)
        if index >= len(rows):
            break
    left = "Order #%s - %s - %s" % (document.get("number") or "-",
                                   document.get("date") or "-",
                                   document.get("status") or "")
    if document.get("quote_number"):
        left += " (from quote %s)" % document["quote_number"]
    pages = quote_pdf.draw_footers(pages, left, dpi)
    return pages, {"pictures": drawn[0], "missing": drawn[1]}


def render(document, path, images=None, dpi=quote_pdf.PRINT_DPI):
    """Write the order sheet as a PDF; returns ``{path, pages, pictures}``."""
    pages, counts = build_pages(document, images=images, dpi=dpi)
    target = Path(str(path))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        pages[0].save(target, "PDF", resolution=float(dpi), save_all=True,
                      append_images=pages[1:], quality=92)
    except (OSError, ValueError) as exc:
        raise quote_model.QuoteError(
            "The PDF could not be written to %s (%s)." % (target, exc),
            "Close the file if it is open in a viewer, then print it again.")
    return {"path": target, "pages": len(pages),
            "pictures": counts["pictures"], "missing": counts["missing"]}


def render_with_pictures(document, path, folder, fetch=None, progress=None,
                         dpi=quote_pdf.PRINT_DPI):
    """Fetch the cards' pictures, then draw the sheet - one call for the panel.

    ``folder`` is where the pictures are cached, which is the documents folder
    the sheet itself is written to. A shop that will not give up a picture
    costs that row its photograph and nothing else.
    """
    urls = picture_urls(document)
    images = {}
    if urls:
        images = (fetch or fetch_images)(urls, folder, progress=progress)
    return render(document, path, images=images, dpi=dpi)
