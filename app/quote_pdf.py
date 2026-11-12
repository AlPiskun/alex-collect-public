"""The printed quote: an A4 page with a logo, a colour, and the sums.

Pillow is already a dependency of the pipeline, and it can write a multi-page
PDF, so a quote needs nothing new installed: the page is drawn as an image at
print resolution and the images become the PDF's pages. That also means the
page cannot come out with a missing font or a broken table - what is checked
in the tests is what the customer receives.

Two things are deliberately not left to chance:

  * the theme colour is read as a colour, and the text drawn on it is chosen
    by how dark it is, so a yellow quote still has readable headings;
  * a quote too long for one page continues onto another with the table
    header repeated, instead of shrinking the type until it fits.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import doc_images
import pdf_writer
import quote as quote_model
from user_settings import restrict_file_permissions

#  A4, in inches. The page is drawn at PRINT_DPI and saved at the same
#  resolution, so a 10pt line is 28 pixels tall and stays sharp when printed.
PAGE_INCHES = (8.268, 11.693)
PRINT_DPI = 200

#  Margin from the paper's edge, and the band across the top.
MARGIN = 0.55
BAND = 1.00
FOOTER = 0.45

INK = (33, 37, 41)
SOFT = (108, 117, 125)
RULE = (222, 226, 230)
WHITE = (255, 255, 255)

#  Fonts, in the order they are looked for. A quote is printed on Windows,
#  where Segoe UI is the system face; the others are the fallbacks for a
#  machine that has none of them (and for the Linux the tests run on).
FONT_FILES = {
    False: ("segoeui.ttf", "arial.ttf", "calibri.ttf", "tahoma.ttf",
            "DejaVuSans.ttf", "LiberationSans-Regular.ttf",
            "Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf"),
    True: ("segoeuib.ttf", "arialbd.ttf", "calibrib.ttf", "tahomabd.ttf",
           "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf",
           "Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
}


@lru_cache(maxsize=None)
def find_font(bold=False, size=20):
    """A font that can be drawn at this size, whatever this machine has.

    The last resort is Pillow's own bundled face, so a machine without any of
    the above still prints a readable quote instead of an empty page.
    """
    for name in FONT_FILES[bool(bold)]:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, ValueError):
            continue
        #  A bare file name is searched for by Pillow only on Windows; look
        #  it up in the usual Linux and macOS places by hand.
        path = _search_system_font(name)
        if path is not None:
            try:
                return ImageFont.truetype(str(path), size)
            except (OSError, ValueError):
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                     # Pillow older than 10.1
        return ImageFont.load_default()


def _search_system_font(name):
    if "/" in name:
        path = Path(name)
        return path if path.is_file() else None
    for folder in ("/usr/share/fonts/truetype/dejavu",
                   "/usr/share/fonts/truetype/liberation",
                   "/usr/share/fonts", "/Library/Fonts",
                   "/System/Library/Fonts"):
        base = Path(folder)
        if not base.is_dir():
            continue
        direct = base / name
        if direct.is_file():
            return direct
        for found in base.rglob(name):
            if found.is_file():
                return found
    return None


# ------------------------------------------------------------------ colours
#  Three pieces of this page are used by the order sheet as well (the logo
#  loader, the type sizes, and the strip no row may be drawn into). They are
#  named without the underscore for that reason; the quote's own code below
#  keeps the shorter names it has always had.
def parse_colour(value, fallback=quote_model.DEFAULT_COLOR):
    """``#1f4e79``, ``1F4E79`` or ``#1a4`` as RGB; the fallback if it is none.

    A colour typed by hand is a string in a JSON file, so this never raises -
    a quote printed in the default blue is better than a quote that will not
    print because someone typed "#1F4E7".
    """
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3 and all(char in "0123456789abcdefABCDEF" for char in text):
        text = "".join(char * 2 for char in text)
    if len(text) == 6 and all(char in "0123456789abcdefABCDEF" for char in text):
        return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
    text = str(fallback or "").strip().lstrip("#")
    if len(text) == 6:
        try:
            return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError:
            pass
    return (31, 78, 121)


def text_on(colour):
    """Black or white, whichever can be read on this background."""
    red, green, blue = colour[:3]
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255.0
    return INK if luminance > 0.62 else WHITE


def mix(colour, target, amount):
    """``colour`` moved towards ``target``; 0 keeps it, 1 is the target."""
    amount = max(0.0, min(1.0, float(amount)))
    return tuple(int(round(channel + (other - channel) * amount))
                 for channel, other in zip(colour[:3], target[:3]))


def tint(colour, amount):
    """``colour`` mixed towards white; ``amount`` 0 is the colour, 1 is white."""
    return mix(colour, WHITE, amount)


def shade(colour, amount):
    """``colour`` mixed towards black - used for the totals bar's edge."""
    amount = max(0.0, min(1.0, float(amount)))
    return tuple(int(round(channel * (1.0 - amount))) for channel in colour[:3])


def luminance(colour):
    """How bright a colour looks to the eye: 0 is black, 1 is white."""
    def channel(value):
        value = value / 255.0
        return (value / 12.92 if value <= 0.03928
                else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = colour[:3]
    return (0.2126 * channel(red) + 0.7152 * channel(green)
            + 0.0722 * channel(blue))


def contrast(first, second):
    """How far apart two colours are to the eye - 1 is the same, 21 is black
    on white. The ratio a printed page is judged by."""
    one, other = luminance(first), luminance(second)
    return (max(one, other) + 0.05) / (min(one, other) + 0.05)


def quiet_on(colour, ratio=4.5):
    """A second colour for writing on ``colour`` that can still be read.

    The letterhead used to be ``tint(colour, 0.35)`` - the band mixed a third
    of the way to white - and on a dark band that is only 2.5:1 against its
    own background: a shop's address and website nobody can read off the
    paper. So the quiet colour is mixed towards whichever text colour the band
    gets (white on a dark one, ink on a pale one) and only as far as it must be
    to clear ``ratio`` - 4.5:1 is what a page of print is asked for, and it is
    the same rule on a yellow quote as on a navy one.
    """
    text = text_on(colour)
    for step in range(1, 101):
        candidate = mix(colour, text, step / 100.0)
        if contrast(candidate, colour) >= ratio:
            return candidate
    return text


# --------------------------------------------------------------------- page
class Page:
    """One sheet, with the helpers a quote needs drawn on it.

    Everything is in pixels at ``dpi``; the caller only ever says "write this
    here" and gets back the height it used, so the layout below reads like the
    page it draws.
    """

    def __init__(self, dpi=PRINT_DPI):
        self.dpi = dpi
        width = int(round(PAGE_INCHES[0] * dpi))
        height = int(round(PAGE_INCHES[1] * dpi))
        self.image = Image.new("RGB", (width, height), WHITE)
        self.draw = ImageDraw.Draw(self.image)
        self.width, self.height = width, height
        self.margin = int(round(MARGIN * dpi))
        self.right = width - self.margin

    # a point measurement, so sizes below are written the way a printer would
    def pt(self, points):
        return int(round(points * self.dpi / 72.0))

    def font(self, points, bold=False):
        return find_font(bold=bold, size=max(6, self.pt(points)))

    def text_width(self, text, font):
        try:
            return self.draw.textlength(str(text), font=font)
        except (AttributeError, TypeError):       # very old Pillow
            return font.getsize(str(text))[0]

    def wrap(self, text, font, width):
        """``text`` broken into lines that fit ``width`` pixels."""
        lines = []
        for paragraph in str(text or "").splitlines() or [""]:
            words = paragraph.split()
            if not words:
                lines.append("")
                continue
            current = ""
            for word in words:
                trial = (current + " " + word).strip()
                if self.text_width(trial, font) <= width or not current:
                    #  A single word longer than the column is cut, not
                    #  allowed to run over the price beside it.
                    if not current and self.text_width(trial, font) > width:
                        while self.text_width(trial, font) > width and \
                                len(trial) > 1:
                            trial = trial[:-1]
                    current = trial
                else:
                    lines.append(current)
                    current = word
            lines.append(current)
        return lines

    def line(self, x1, y, x2, colour=RULE, thickness=1):
        self.draw.line([(x1, y), (x2, y)], fill=colour, width=thickness)
        return y + thickness

    def bar(self, x1, y1, x2, y2, colour):
        self.draw.rectangle([x1, y1, x2, y2], fill=colour)
        return y2

    def note(self, x, y, text, font, colour=SOFT):
        self.draw.text((x, y), text, font=font, fill=colour)
        return y + self.pt(4)


# ------------------------------------------------------------------- layout
#: The picture column: a card's shape, narrower than the order sheet's,
#: because a quote is a price document with a picture beside each price.
PICTURE_WIDTH = 0.52


def picture_box(page):
    """The thumbnail's size in pixels, at this page's resolution."""
    width = page.pt(PICTURE_WIDTH * 72)
    return width, int(round(width * doc_images.CARD_RATIO))


def _items(quote):
    return quote_model.items_of(quote)


def _table_rows(page, quote, fonts):
    """Every row of the table, with its wrapped description and its numbers."""
    currency = quote.get("currency") or ""
    rows = []
    _pic_w, pic_h = picture_box(page)
    description_width = (_columns(page)["quantity"] - card_column(page)
                         - page.pt(8))
    body = fonts["body"]
    for index, item in enumerate(_items(quote), 1):
        name = str(item.get("name") or "")
        lines = page.wrap(name, body, description_width)
        price = quote_model.item_price(item)
        total = quote_model.line_total(item)
        text_height = (page.pt(7) + len(lines) * page.pt(13) +
                       (page.pt(11) if item.get("sku") else 0))
        rows.append({
            "index": index,
            "lines": lines,
            "sku": str(item.get("sku") or ""),
            "quantity": quote_model.item_quantity(item),
            "price": quote_model.money(price, currency) if price is not None
                     else "-",
            "amount": quote_model.money(total, currency) if total is not None
                      else "-",
            "image": doc_images.url_of(item),
            "url": quote_model.item_url(item),
            "height": max(pic_h + page.pt(8), text_height + page.pt(10)),
        })
    return rows


def contact_lines(contact, room):
    """The shop's contact block, cut down to ``room`` lines.

    The lines past the last that fits are joined onto it with a dot rather
    than dropped, because the website is usually the one that would fall off
    the edge. The band no longer needs this - it grows to hold the whole
    block, and only uses this for a letterhead taller than any band may be -
    but it is the rule that keeps a line from being silently lost.
    """
    lines = [line.strip() for line in str(contact or "").splitlines()
             if line.strip()]
    room = int(room)
    if room <= 0 or not lines:
        return []
    if len(lines) <= room:
        return lines
    return lines[:room - 1] + [" \u00b7 ".join(lines[room - 1:])]


#: The most the band may grow to, in inches, to hold the shop's letterhead.
#: Past this the remaining lines are joined onto the last one with a dot.
MAX_BAND = 1.75

#: The letterhead's own size, in points, and the smallest it may be reduced
#: to so that one unbreakable line - a long web address - still fits.
CONTACT_POINTS = 9.4
CONTACT_SMALLEST = 6.8


def contact_layout(page, contact, fonts, x, top, title):
    """The shop's lines, wrapped, and the band that holds them.

    Returns ``{lines, font, line_height, top, height}``.

    A shop that lists a street, a town, a phone and a website gave four lines,
    and the band holds two under the shop's name. The lines used to be cut to
    two and *then* wrapped, so the website wrapped onto a third line that was
    thrown away - the shop's sheet went out with no address for its own web
    page on it. Nothing is dropped now: the band grows to hold the whole
    block (up to :data:`MAX_BAND`), and past that the rest is joined onto the
    last line rather than lost. A line with no space in it to break at - a
    long web address is one word - is drawn a little smaller until it fits,
    because half a web address is not a web address.
    """
    space = page.pt(2)
    #  The letterhead starts under the shop's name rather than at a height
    #  guessed from the band's top: with a logo the name sits a little lower,
    #  and a guessed line put the address through the name.
    try:
        company_ascent, company_descent = fonts["company"].getmetrics()
        company_height = company_ascent + company_descent
    except AttributeError:
        company_height = page.pt(18)
    contact_top = top + company_height + page.pt(3)
    width = max(page.pt(120), page.right
                - page.text_width(title, fonts["title"]) - page.pt(16) - x)
    typed = [line.strip() for line in str(contact or "").splitlines()
             if line.strip()]
    size = CONTACT_POINTS
    while True:
        font = page.font(size)
        longest = max([page.text_width(word, font)
                       for line in typed for word in line.split()] or [0])
        if longest <= width or size <= CONTACT_SMALLEST:
            break
        size -= 0.2
    try:
        ascent, descent = font.getmetrics()
        line_height = ascent + descent + space
    except AttributeError:                # a face that reports no metrics
        line_height = page.pt(13) + space
    lines = []
    for line in typed:
        lines.extend(page.wrap(line, font, width))
    room = max(1, int((page.pt(MAX_BAND * 72) - page.pt(6) - contact_top)
                      // line_height))
    if len(lines) > room:
        lines = contact_lines("\n".join(lines), room)[:room]
    needed = contact_top + len(lines) * line_height + page.pt(6)
    return {"lines": lines, "font": font, "line_height": line_height,
            "top": contact_top, "height": max(page.pt(BAND * 72), needed)}


def draw_band(page, look, title, number, fonts, first_page=True):
    """The coloured block across the top: logo, company, and the number.

    Shared by the quote and the order sheet on purpose. "The same settings"
    is not a promise to keep two drawings in step - it is one drawing, called
    with a different word on the right ("QUOTE", "ORDER") and a different
    number under it.

    The heading goes in the band's own text colour, and everything under it -
    the shop's address and website, and the document's number - in a second
    colour that is light enough to read on the band but not so light that it
    fades into it. Both are chosen from the colour the shop picked, so a navy
    quote and a yellow one are equally legible.
    """
    look = look or {}
    colour = page.colour
    on_colour = page.on_colour
    base = page.pt(BAND * 72) if first_page else page.pt(52)
    x = page.margin
    top = page.pt(18)
    pad = page.pt(5)
    plate = None
    drawn_logo = False
    if page.logo is not None:
        logo = page.logo
        #  The logo is drawn on a white plate rather than straight onto the
        #  band: a shop's logo is often dark, and a dark logo on a dark
        #  colour is a quote that arrives looking blank. The plate is only as
        #  big as the logo, so it reads as part of the design.
        logo_height = base - page.pt(30)
        scale = min((logo_height - pad * 2) / logo.height,
                    (page.width * 0.24) / max(1, logo.width))
        size = (max(1, int(logo.width * scale)),
                max(1, int(logo.height * scale)))
        logo = logo.resize(size, Image.LANCZOS)
        plate = [x - pad, top + max(0, (logo_height - size[1]) // 2) - pad,
                 x + size[0] + pad, top + max(0, (logo_height - size[1]) // 2)
                 + size[1] + pad]
        x += size[0] + pad * 2 + page.pt(12)
        drawn_logo = True

    contact = str(look.get("contact") or "").strip() if first_page else ""
    company_y = top + (page.pt(6) if drawn_logo or not first_page else 0)
    band_height = base
    layout = None
    if contact:
        layout = contact_layout(page, contact, fonts, x, company_y, title)
        band_height = layout["height"]

    page.bar(0, 0, page.width, band_height, colour)
    if plate is not None:
        page.draw.rounded_rectangle(plate, radius=page.pt(4), fill=WHITE)
        page.image.paste(logo, (plate[0] + pad, plate[1] + pad),
                         logo if logo.mode == "RGBA" else None)
    company = str(look.get("company") or "").strip() or "Alex Collect"
    page.draw.text((x, company_y), company, font=fonts["company"],
                   fill=on_colour)
    if first_page:
        if layout and layout["lines"]:
            page.draw.multiline_text((x, layout["top"]),
                                     "\n".join(layout["lines"]),
                                     font=layout["font"],
                                     fill=quiet_on(colour, 5.5),
                                     spacing=page.pt(2))
        width = page.text_width(title, fonts["title"])
        page.draw.text((page.right - width, top), title, font=fonts["title"],
                       fill=on_colour)
        #  The number is how the sheet is found again among a day's papers, so
        #  it is drawn in the number face - larger than the letterhead's quiet
        #  lines, brighter still, and under the document's title.
        number = "#%s" % (number or "-")
        width = page.text_width(number, fonts["number"])
        page.draw.text((page.right - width, top + page.pt(22)), number,
                       font=fonts["number"], fill=quiet_on(colour, 7.0))
    else:
        number = "#%s" % (number or "-")
        width = page.text_width(number, fonts["number"])
        page.draw.text((page.right - width, page.pt(17)), number,
                       font=fonts["number"], fill=quiet_on(colour, 7.0))
    return band_height


def _draw_parties(page, quote, fonts, y):
    """Who the quote is for, and the dates, side by side under the band."""
    left_width = int((page.right - page.margin) * 0.58)
    customer = quote.get("customer") or {}
    label = fonts["label"]
    page.draw.text((page.margin, y), "PREPARED FOR", font=label,
                   fill=page.colour)
    y_text = y + page.pt(15)
    name = str(customer.get("name") or "").strip()
    page.draw.text((page.margin, y_text), name or "Customer", font=fonts["h2"],
                   fill=INK)
    y_text += page.pt(17)
    body = fonts["body"]
    for field in ("address",):
        text = str(customer.get(field) or "").strip()
        if not text:
            continue
        for line in page.wrap(text, body, left_width):
            page.draw.text((page.margin, y_text), line, font=body, fill=INK)
            y_text += page.pt(13)
    for field in ("email", "phone"):
        text = str(customer.get(field) or "").strip()
        if not text:
            continue
        page.draw.text((page.margin, y_text), text, font=body, fill=SOFT)
        y_text += page.pt(13)

    sums = quote_model.totals(quote)
    x = page.margin + int((page.right - page.margin) * 0.64)
    rows = [("QUOTE", quote.get("number") or "-"),
            ("ISSUED", quote.get("issued") or "-"),
            ("VALID UNTIL", quote.get("valid_until") or "-"),
            ("CARDS", "%d (%d item%s)" % (sums["lines"], sums["units"],
                                          "" if sums["units"] == 1 else "s"))]
    y_row = y
    value = fonts["body_bold"]
    for heading, value_text in rows:
        page.draw.text((x, y_row), heading, font=label, fill=page.colour)
        page.draw.text((x + page.pt(78), y_row), str(value_text), font=value,
                       fill=INK)
        y_row += page.pt(15)
    return max(y_text, y_row) + page.pt(10)


def _table_header(page, y, fonts):
    """The grey-blue strip over the cards, on every page."""
    height = page.pt(22)
    page.draw.rectangle([page.margin, y, page.right, y + height],
                        fill=tint(page.colour, 0.86))
    label = fonts["label"]
    colour = shade(page.colour, 0.35)
    columns = _columns(page)
    page.draw.text((card_column(page), y + page.pt(7)), "CARD", font=label,
                   fill=colour)
    for key, heading in (("quantity", "QTY"), ("price", "EACH"),
                         ("amount", "AMOUNT")):
        width = page.text_width(heading, label)
        page.draw.text((columns[key] - width, y + page.pt(7)), heading,
                       font=label, fill=colour)
    return y + height


def card_column(page):
    """Where a card's name starts - to the right of its picture."""
    width, _height = picture_box(page)
    return page.margin + width + page.pt(8)


def _columns(page):
    """Where each column's edge sits, in pixels."""
    right = page.right
    return {"quantity": right - int((right - page.margin) * 0.36),
            "price": right - int((right - page.margin) * 0.18),
            "amount": right}


def _draw_row(page, y, row, fonts, zebra, images=None, links=None):
    """One card: its picture, its name, its numbers - and the name as a link.

    Returns ``(y, was_drawn)`` so the caller can count the pictures that were
    not there.
    """
    columns = _columns(page)
    height = row["height"]
    if zebra:
        page.draw.rectangle([page.margin, y, page.right, y + height],
                            fill=tint(page.colour, 0.965))
    width, box_height = picture_box(page)
    drawn = doc_images.draw_picture(
        page, page.margin, y + page.pt(4), width, box_height,
        doc_images.load_picture((images or {}).get(row["image"])),
        background=tint(page.colour, 0.95), border=RULE, note_colour=SOFT)
    body = fonts["body"]
    right = fonts["body"]
    left = card_column(page)
    text_y = y + page.pt(7)
    for line in row["lines"]:
        page.draw.text((left, text_y), line, font=body, fill=INK)
        text_y += page.pt(13)
    if row["sku"]:
        page.draw.text((left, text_y), row["sku"], font=fonts["small"],
                       fill=SOFT)
    if links is not None and row.get("url"):
        #  The name is the link: the box covers the card's title and nothing
        #  beside it, so clicking the price does not open the product page.
        hit = [left, y + page.pt(4), columns["quantity"] - page.pt(6),
               y + page.pt(7) + max(1, len(row["lines"])) * page.pt(13)]
        links.append((hit[0], hit[1], hit[2], hit[3], row["url"]))
    quantity = str(row["quantity"])
    page.draw.text((columns["quantity"] - page.text_width(quantity, right),
                    y + page.pt(7)), quantity, font=right, fill=INK)
    for key in ("price", "amount"):
        value = row[key]
        page.draw.text((columns[key] - page.text_width(value, right),
                        y + page.pt(7)), value, font=right, fill=INK)
    page.line(page.margin, y + height, page.right, RULE)
    return y + height, drawn


def _draw_totals(page, quote, fonts, y):
    """Subtotal, the discount, and the total in a bar of the theme colour."""
    sums = quote_model.totals(quote)
    currency = quote.get("currency") or ""
    right = page.right
    box_left = right - int((right - page.margin) * 0.42)
    body = fonts["body"]
    amount_font = fonts["body_bold"]
    for label, value in (("Subtotal", quote_model.money(sums["subtotal"],
                                                        currency)),):
        page.draw.text((box_left, y), label, font=body, fill=SOFT)
        page.draw.text((right - page.text_width(value, amount_font), y), value,
                       font=amount_font, fill=INK)
        y += page.pt(17)
    if sums["discount"]:
        label = sums["discount_label"]
        value = "\u2212" + quote_model.money(sums["discount"], currency)
        page.draw.text((box_left, y), label, font=body, fill=SOFT)
        page.draw.text((right - page.text_width(value, amount_font), y), value,
                       font=amount_font, fill=INK)
        y += page.pt(17)
    if sums["unpriced"]:
        text = "%d card%s has no price yet - shown as -" % (
            sums["unpriced"], "" if sums["unpriced"] == 1 else "s")
        page.draw.text((box_left, y), text, font=fonts["small"], fill=SOFT)
        y += page.pt(12)
    y += page.pt(3)
    height = page.pt(30)
    page.draw.rounded_rectangle([box_left - page.pt(10), y, right + 2,
                                 y + height], radius=page.pt(4),
                                fill=page.colour)
    total = quote_model.money(sums["total"], currency)
    label_font = fonts["label"]
    page.draw.text((box_left, y + page.pt(10)), "TOTAL", font=label_font,
                   fill=page.on_colour)
    page.draw.text((right - page.text_width(total, fonts["h2"]) - page.pt(2),
                    y + page.pt(5)), total, font=fonts["h2"],
                   fill=page.on_colour)
    return y + height


def _draw_acceptance(page, quote, fonts, y):
    """The two lines a customer signs and dates - and how to order.

    A quote that is expected back with a signature says so, and it fills the
    lower half of a short quote with the one thing that turns it into an
    order instead of leaving it blank.
    """
    bottom = _reserve_footer(page)
    if y + page.pt(54) > bottom:
        return y
    y += page.pt(10)
    left, right = page.margin, page.right
    width = int((right - left) * 0.44)
    body = fonts["body"]
    label = fonts["label"]
    page.draw.text((left, y), "ACCEPTED BY", font=label, fill=page.colour)
    page.draw.text((left + int((right - left) * 0.52), y), "DATE",
                   font=label, fill=page.colour)
    line_y = y + page.pt(20)
    page.line(left, line_y, left + width, shade(page.colour, 0.6))
    page.line(left + int((right - left) * 0.52), line_y,
              right - int((right - left) * 0.18), shade(page.colour, 0.6))
    y = line_y + page.pt(14)
    contact = str((quote.get("look") or {}).get("contact") or "").strip()
    how = ("To order, reply to this quote with the cards you would like"
           + (" or contact %s." % contact.splitlines()[0].strip()
              if contact else "."))
    for line in page.wrap(how, body, right - left):
        if y + page.pt(13) > bottom:
            break
        page.draw.text((left, y), line, font=body, fill=SOFT)
        y += page.pt(13)
    return y + page.pt(2)


def _draw_notes(page, quote, fonts, y):
    notes = str(quote.get("notes") or "").strip()
    available = _reserve_footer(page) - y
    if not notes or available < page.pt(30):
        return y
    body = fonts["body"]
    lines = page.wrap(notes, body, page.right - page.margin - page.pt(24))
    height = page.pt(12) + len(lines) * page.pt(13)
    if height > available:
        lines = lines[:max(1, (available - page.pt(12)) // page.pt(13))]
        height = page.pt(12) + len(lines) * page.pt(13)
    page.draw.rounded_rectangle([page.margin, y, page.right, y + height],
                                radius=page.pt(4), fill=tint(page.colour, 0.93))
    text_y = y + page.pt(7)
    for line in lines:
        page.draw.text((page.margin + page.pt(10), text_y), line, font=body,
                       fill=INK)
        text_y += page.pt(13)
    return y + height


def _fonts(page):
    return {"title": page.font(21, True), "company": page.font(15, True),
            "h2": page.font(13, True), "body": page.font(10),
            "body_bold": page.font(10, True), "small": page.font(8.4),
            "small_bold": page.font(8.4, True), "label": page.font(7.6, True),
            #  The band's own two: the letterhead's address and website, and
            #  the document's number. Both were smaller than a footnote.
            "contact": page.font(9.4), "number": page.font(12, True)}


def _load_logo(path):
    """The logo file as an image, or ``None`` when it is not usable."""
    text = str(path or "").strip()
    if not text:
        return None
    try:
        image = Image.open(text)
        image.load()
    except (OSError, ValueError):
        return None
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    if image.mode == "RGB":
        image = image.convert("RGBA")
    return image


def _reserve_footer(page):
    """The strip at the bottom that no row may be drawn into."""
    return page.height - page.margin - page.pt(FOOTER * 72)


def draw_footers(pages, left_text, dpi):
    """``Page N of M`` and one line of the document's own, once M is known."""
    total = len(pages)
    for number, image in enumerate(pages, 1):
        page = Page(dpi)
        page.image = image
        page.draw = ImageDraw.Draw(image)
        fonts = _fonts(page)
        y = page.height - page.margin + page.pt(2)
        page.draw.rectangle([0, y - 2, page.width, page.height], fill=WHITE)
        page.line(page.margin, y, page.right, RULE)
        page.draw.text((page.margin, y + page.pt(6)), left_text,
                       font=fonts["small"], fill=SOFT)
        right = "Page %d of %d" % (number, total)
        page.draw.text((page.right - page.text_width(right, fonts["small"]),
                        y + page.pt(6)), right, font=fonts["small"], fill=SOFT)
    return pages


def band_bottom(image, dpi=PRINT_DPI):
    """How far the colour block at the top of ``image`` reaches, in pixels.

    Read back off the drawn page - the band's height is not a constant any
    more, it is whatever the shop's letterhead needed - so a check can say
    where the colour ends and the white paper begins.
    """
    x = max(0, image.width - 2)
    colour = image.getpixel((x, 0))
    if colour == WHITE:
        return 0
    y = 0
    while y + 1 < image.height and image.getpixel((x, y + 1)) == colour:
        y += 1
    return y


#  The shared pieces, under names a second document may call.
load_logo = _load_logo
fonts_for = _fonts
reserve_footer = _reserve_footer


def build_pages(quote, dpi=PRINT_DPI, images=None, links=None, counts=None):
    """Every page of the quote, as images; the PDF is these pages in order.

    Returned rather than saved so the tests can look at the pixels - which is
    the only way to prove the logo is on the page and the colour is the one
    that was chosen.

    ``images`` maps a card's picture URL to a file or an open image. ``links``
    is a dict that gains the clickable card names, keyed by page number, and
    ``counts`` gains how many pictures were drawn and how many were missing -
    filled in rather than returned, because the page list is what every caller
    already expects back.
    """
    quote = quote_model.normalise(quote)
    colour = parse_colour((quote.get("look") or {}).get("color"))
    pages = []
    rows = None
    index = 0
    while True:
        page = Page(dpi)
        page.colour = colour
        page.on_colour = text_on(colour)
        page.logo = _load_logo((quote.get("look") or {}).get("logo"))
        fonts = _fonts(page)
        if not pages:
            y = draw_band(page, quote.get("look"), "QUOTE",
                          quote.get("number"), fonts, first_page=True)
            y = _draw_parties(page, quote, fonts, y + page.pt(16))
        else:
            y = draw_band(page, quote.get("look"), "QUOTE",
                          quote.get("number"), fonts, first_page=False)
            y += page.pt(12)
        if rows is None:
            rows = _table_rows(page, quote, fonts)
        if rows:
            y = _table_header(page, y, fonts)
        #  The totals and the signature lines are only drawn after the last
        #  card, where a reader looks for them - so a page either holds its
        #  cards *and* that tail, or it is filled edge to edge with cards and
        #  the tail waits for the page that ends the quote. Reserving the tail
        #  on every page left two inches of white under the last row.
        full = _reserve_footer(page) - page.pt(10)
        tail = page.pt(190)
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
        page_links = []
        while placed < take and index < len(rows):
            y, was_drawn = _draw_row(page, y, rows[index], fonts,
                                     zebra=index % 2 == 1, images=images,
                                     links=page_links)
            if counts is not None:
                key = "pictures" if was_drawn else "missing"
                counts[key] = counts.get(key, 0) + 1
            index += 1
            placed += 1
        if links is not None and page_links:
            links[len(pages)] = page_links
        more = index < len(rows) and placed > 0
        if not more:
            if not rows:
                page.draw.text((page.margin, y + page.pt(12)),
                               "No cards on this quote yet.",
                               font=fonts["body"], fill=SOFT)
                y += page.pt(30)
            y += page.pt(14)
            y = _draw_totals(page, quote, fonts, y)
            y = _draw_notes(page, quote, fonts, y + page.pt(16))
            _draw_acceptance(page, quote, fonts, y + page.pt(6))
        pages.append(page.image)
        if index >= len(rows):
            break
    left = ("This quote is held until %s." % quote["valid_until"]
            if quote.get("valid_until") else "Thank you for your interest.")
    return draw_footers(pages, left, dpi)


def render(quote, path, dpi=PRINT_DPI, images=None):
    """Write the quote as a PDF; returns ``{path, pages, logo, ...}``.

    ``logo`` says whether the logo file was readable, so a quote printed with
    a missing logo can say so instead of quietly arriving without it;
    ``pictures`` and ``missing`` count the card pictures the same way.
    """
    links = {}
    counts = {}
    pages = build_pages(quote, dpi, images=images, links=links,
                        counts=counts)
    target = Path(str(path))
    try:
        pdf_writer.write(pages, target, links=links, dpi=dpi,
                         title="Quote %s" % (quote.get("number") or ""))
    except (OSError, ValueError) as exc:
        raise quote_model.QuoteError(
            "The PDF could not be written to %s (%s)." % (target, exc),
            "Close the file if it is open in a viewer, then print it again.")
    #  The printed quote holds the customer's name and address, so the file
    #  is readable by this Windows account only - as the keys file is.
    restrict_file_permissions(target)
    logo = str((quote.get("look") or {}).get("logo") or "").strip()
    return {"path": target, "pages": len(pages),
            "logo": bool(logo) and _load_logo(logo) is not None,
            "pictures": counts.get("pictures", 0),
            "missing": counts.get("missing", 0)}
