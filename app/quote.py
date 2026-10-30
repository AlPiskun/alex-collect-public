"""A quote for a batch of cards - priced, saved, printed, and turned into an order.

A customer asks "how much for these?". The answer used to be a tap on a
calculator and a typed email. A quote is the same list of cards the order
builder works with, but it is a *file*: it can be saved, edited next week,
printed as a PDF with a logo and a colour, and only then turned into the
order it was describing.

This module is the part that has nothing to do with a window:

  * the quote itself (its cards, its customer, its discount) and the sums;
  * reading and writing it as JSON, one file per quote;
  * the body that creates the order on the website, and the read-back that
    says whether the site kept the number the customer was quoted.

The PDF is drawn in :mod:`quote_pdf`; the panel is in ``gui.build_quote``.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import woo_orders

QUOTES_DIRNAME = "quotes"
ORDERS_PATH = "/wp-json/wc/v3/orders"
#  A quote is a promise with a shelf life; two weeks is the trade convention.
VALID_DAYS = 14
DEFAULT_COLOR = "#1F4E79"
#  What a cart's worth of cards is called on the printed page.
STATUS_WORDS = {"draft": "Draft - not sent yet",
                "sent": "Sent to the customer",
                "ordered": "Ordered"}


class QuoteError(Exception):
    """Anything that stops a quote being saved, printed or ordered."""

    def __init__(self, message, hint=""):
        super().__init__(message)
        self.message = str(message)
        self.hint = str(hint or "")


# ------------------------------------------------------------------ numbers
def money(value, currency=""):
    """``C$12.50`` - the way a price is written on the page and in the app."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "-"
    sign = "-" if amount < 0 else ""
    text = "%s%.2f" % (sign, abs(amount))
    return ("%s%s" % (currency, text)).strip()


def parse_money(value):
    """A typed price as a float, or ``None`` when it is not a price.

    An empty box is not a price either: a card with no price is shown as
    "price on request" rather than counted as free, because a quote that
    quietly adds up to nothing is worse than one that says it does not know.
    """
    text = str(value or "").strip().replace(",", "")
    for junk in ("$", "\u00a0"):
        text = text.replace(junk, "")
    if not text:
        return None
    try:
        amount = float(text)
    except ValueError:
        return None
    if amount < 0:
        return None
    return round(amount, 2)


def item_price(item):
    """The quoted price of one line, or ``None`` when it has none."""
    return parse_money((item or {}).get("price"))


def item_quantity(item):
    try:
        quantity = int((item or {}).get("quantity") or 1)
    except (TypeError, ValueError):
        quantity = 1
    return max(1, quantity)


def line_total(item):
    price = item_price(item)
    if price is None:
        return None
    return round(price * item_quantity(item), 2)


def discount_amount(quote):
    """The discount in money, given whatever kind was chosen."""
    subtotal = sum(line_total(item) or 0.0 for item in items_of(quote))
    disc = (quote or {}).get("discount") or {}
    kind = str(disc.get("kind") or "").strip().lower()
    try:
        value = float(disc.get("value") or 0)
    except (TypeError, ValueError):
        return 0.0
    if value <= 0:
        return 0.0
    if kind == "percent":
        return round(subtotal * min(value, 100.0) / 100.0, 2)
    if kind == "amount":
        #  Never below zero: a discount bigger than the quote is a typo, and
        #  a total that goes negative on a printed page is a mistake the
        #  customer will keep.
        return round(min(value, subtotal), 2)
    return 0.0


def discount_label(quote):
    """How the discount is described on the page - empty when there is none."""
    disc = (quote or {}).get("discount") or {}
    kind = str(disc.get("kind") or "").strip().lower()
    amount = discount_amount(quote)
    if amount <= 0:
        return ""
    if kind == "percent":
        try:
            percent = float(disc.get("value") or 0)
        except (TypeError, ValueError):
            percent = 0.0
        return "Discount %s%%" % ("%g" % percent)
    return "Discount"


def totals(quote):
    """Everything the page prints at the bottom, worked out once."""
    items = items_of(quote)
    subtotal = 0.0
    units = 0
    unpriced = 0
    for item in items:
        total = line_total(item)
        units += item_quantity(item)
        if total is None:
            unpriced += 1
            continue
        subtotal += total
    subtotal = round(subtotal, 2)
    discount = discount_amount(quote)
    return {"subtotal": subtotal, "discount": discount,
            "discount_label": discount_label(quote),
            "total": round(max(0.0, subtotal - discount), 2),
            "lines": len(items), "units": units, "unpriced": unpriced}


# --------------------------------------------------------------- the object
def items_of(quote):
    return list((quote or {}).get("items") or [])


def new_quote(number="", today=None, currency="C$", company="", valid_days=None):
    """A blank quote, numbered and dated, ready for cards."""
    today = today or date.today()
    days = VALID_DAYS if valid_days is None else int(valid_days)
    return {
        "number": number or "",
        "issued": today.isoformat(),
        "valid_until": (today + timedelta(days=days)).isoformat(),
        "status": "draft",
        "order_id": 0,
        "order_number": "",
        "currency": currency or "",
        "customer": {"name": "", "email": "", "phone": "", "address": ""},
        "items": [],
        "discount": {"kind": "", "value": 0.0},
        "notes": "",
        "look": {"company": company or "", "contact": "", "color": DEFAULT_COLOR,
                 "logo": ""},
        "created": datetime.now().isoformat(timespec="seconds"),
        "updated": "",
    }


def normalise(quote):
    """Fill in anything an older or hand-edited file is missing.

    A quote file is a JSON file in the user's folder, so it can be edited,
    truncated by a bad merge, or written by an older version. Reading one
    must never be a traceback: every field is defaulted, and the cards that
    survive are the ones that carry a name.
    """
    quote = dict(quote or {})
    blank = new_quote()
    for key, value in blank.items():
        quote.setdefault(key, value)
    for key in ("customer", "discount", "look"):
        merged = dict(blank[key])
        saved = quote.get(key)
        if isinstance(saved, dict):
            merged.update({k: v for k, v in saved.items()})
        quote[key] = merged
    clean = []
    for item in quote.get("items") or []:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        entry = {"product_id": int(item.get("product_id") or 0),
                 "sku": str(item.get("sku") or "").strip(),
                 "name": " ".join(str(item.get("name")).split()),
                 "price": str(item.get("price") or "").strip(),
                 "quantity": item_quantity(item),
                 "image": item_image(item)}
        clean.append(entry)
    quote["items"] = clean
    quote["number"] = str(quote.get("number") or "").strip()
    quote["status"] = str(quote.get("status") or "draft")
    try:
        quote["discount"]["value"] = float(quote["discount"].get("value") or 0)
    except (TypeError, ValueError):
        quote["discount"]["value"] = 0.0
    kind = str(quote["discount"].get("kind") or "").lower()
    quote["discount"]["kind"] = kind if kind in ("percent", "amount") else ""
    return quote


# ------------------------------------------------------------------- cards
def add_item(quote, product, quantity=1, replace_price=False):
    """Put one card on the quote; return the row's index.

    The same product twice is one row with the quantity raised - a quote that
    lists the same card on two lines looks like a mistake, and the customer
    reads it as one. A price already on the quote is kept unless asked
    otherwise: the printed price is what the customer was promised.
    """
    product = product or {}
    name = " ".join(str(product.get("name") or "").split())
    if not name:
        raise QuoteError("That card has no name, so it cannot go on a quote.")
    product_id = int(product.get("id") or product.get("product_id") or 0)
    sku = str(product.get("sku") or "").strip()
    price = parse_money(product.get("price"))
    items = quote.setdefault("items", [])
    for index, item in enumerate(items):
        same = (product_id and int(item.get("product_id") or 0) == product_id)
        if not same and sku:
            same = str(item.get("sku") or "") == sku
        if same:
            item["quantity"] = item_quantity(item) + max(1, int(quantity or 1))
            if replace_price and price is not None:
                item["price"] = "%.2f" % price
            if not item.get("image"):
                #  A row saved before pictures were kept gains one now, so an
                #  old quote can print its cards' photographs.
                item["image"] = first_image(product)
            return index
    items.append({"product_id": product_id, "sku": sku, "name": name,
                  "price": "" if price is None else "%.2f" % price,
                  "quantity": max(1, int(quantity or 1)),
                  "image": first_image(product)})
    return len(items) - 1


def add_items(quote, products, quantity=1, skip_existing=False):
    """One of each product, in order.

    Returns ``(added, already)``. ``skip_existing`` is what "add all the
    matches" wants: pressing it twice must not quietly double the quote, so a
    card already on it is counted and left alone instead of gaining a copy.
    """
    have = set()
    for item in items_of(quote):
        if item.get("product_id"):
            have.add(int(item["product_id"]))
        if item.get("sku"):
            have.add(str(item["sku"]))
    added = already = 0
    for product in products or []:
        key = int((product or {}).get("id") or 0) or \
            str((product or {}).get("sku") or "")
        if skip_existing and key and key in have:
            already += 1
            continue
        add_item(quote, product, quantity=quantity)
        if key:
            have.add(key)
        added += 1
    return added, already


def merge_same_products(quote):
    """One row per product, quantities added up; returns how many merged.

    Two rows pointing at the same product become two lines on an order, and
    the site is entitled to refuse that - so they are folded together first.
    A row with no product id is left exactly where it is: it is a different
    card, and there is nothing to fold it into.
    """
    items = quote.setdefault("items", [])
    seen, kept, merged = {}, [], 0
    for item in items:
        product_id = int(item.get("product_id") or 0)
        if not product_id:
            kept.append(item)
            continue
        first = seen.get(product_id)
        if first is None:
            seen[product_id] = item
            kept.append(item)
            continue
        first["quantity"] = item_quantity(first) + item_quantity(item)
        merged += 1
    quote["items"] = kept
    return merged


def remove_item(quote, index):
    items = quote.get("items") or []
    if not 0 <= int(index) < len(items):
        raise QuoteError("That row is not on the quote any more.")
    return items.pop(int(index))


def set_quantity(quote, index, quantity):
    items = quote.get("items") or []
    if not 0 <= int(index) < len(items):
        raise QuoteError("That row is not on the quote any more.")
    items[int(index)]["quantity"] = max(1, int(quantity or 1))
    return items[int(index)]


def set_price(quote, index, value):
    """Set one line's price by hand (a card with no price on the website)."""
    items = quote.get("items") or []
    if not 0 <= int(index) < len(items):
        raise QuoteError("That row is not on the quote any more.")
    amount = parse_money(value)
    items[int(index)]["price"] = "" if amount is None else "%.2f" % amount
    return items[int(index)]


def refresh_prices(quote, products):
    """Re-price the quote from what the website says today.

    Returns ``(changed, missing)``: the rows whose price moved (old and new,
    so the person can see what the customer would notice) and the rows whose
    product is no longer on the site at all. Nothing is written here - the
    caller decides - because a quote sent to a customer must not silently
    change its numbers.
    """
    by_id = {}
    for product in products or []:
        try:
            by_id[int(product.get("id") or 0)] = product
        except (TypeError, ValueError):
            continue
    changed, missing = [], []
    for item in items_of(quote):
        product = by_id.get(int(item.get("product_id") or 0))
        if product is None:
            missing.append(item)
            continue
        new_price = parse_money(product.get("price"))
        old_price = item_price(item)
        if new_price is None or new_price == old_price:
            continue
        changed.append({"name": item["name"], "old": old_price,
                        "new": new_price})
    return changed, missing


def apply_prices(quote, products):
    """Take today's prices for the rows that still exist."""
    by_id = {int(product.get("id") or 0): product
             for product in products or []}
    for item in items_of(quote):
        product = by_id.get(int(item.get("product_id") or 0))
        if product is None:
            continue
        price = parse_money(product.get("price"))
        if price is not None:
            item["price"] = "%.2f" % price
    return quote


def first_image(product):
    """The shop's first picture of a card, as a URL, or ``""``.

    Kept on the quote row so an order sheet can show the card weeks later -
    without asking the website again, and without the row being a picture
    itself. The URL is what gets stored; the sheet downloads it when it is
    printed, and a card whose picture cannot be fetched still prints.
    """
    product = product or {}
    images = product.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict) and str(image.get("src") or "").strip():
                return str(image["src"]).strip()
    image = product.get("image")
    if isinstance(image, dict):
        return str(image.get("src") or "").strip()
    if isinstance(image, str):
        return image.strip()
    return ""


def item_image(item):
    """The picture a quote row carries, if it kept one."""
    return str((item or {}).get("image") or "").strip()


def search(woo_get, site, key, secret, term, per_page=100):
    """The products whose name matches what was typed, as quote rows."""
    term = str(term or "").strip()
    if not term:
        raise QuoteError("Type something to search for - a player, a year, "
                         "or a card number.")
    code, data = woo_get(site, "/wp-json/wc/v3/products",
                         {"search": term, "per_page": per_page},
                         key, secret)
    if code in (401, 403):
        raise QuoteError("The website refused the keys (HTTP %s), so the "
                         "stock could not be read." % code,
                         "woo-keys.txt holds the key pair; reading products "
                         "needs Read access.")
    if code != 200:
        raise QuoteError("The website did not answer the search (HTTP %s)."
                         % (code or "no answer"),
                         "Check that the store address and keys are right.")
    rows = data if isinstance(data, list) else []
    products = []
    for product in rows:
        if not isinstance(product, dict) or not product.get("id"):
            continue
        products.append({"id": int(product["id"]),
                         "name": " ".join(str(product.get("name") or "")
                                          .split()),
                         "sku": str(product.get("sku") or "").strip(),
                         "price": str(product.get("price") or "").strip(),
                         "stock_status": str(product.get("stock_status") or ""),
                         "stock_quantity": product.get("stock_quantity"),
                         "image": first_image(product)})
    return products


#: The shop's own word for "you can sell this today". Everything else - either
#: out-of-stock state, or a product that did not say - is not quoted.
IN_STOCK = "instock"

#: The orders the search results can be put in, as (key, label).
SORTS = (("name", "Name (A to Z)"),
         ("price", "Price (low to high)"),
         ("price_desc", "Price (high to low)"),
         ("newest", "Newest first"))


def in_stock(products):
    """Only the rows the shop says are on the shelf right now.

    A quote is an offer to sell, so a card that cannot be bought is not a
    result to add: the shop's own word for it is ``instock``, and a product
    that says anything else - out of stock, on backorder, or nothing at all -
    is left out. The panel says how many were left out, so a card missing from
    the list is explained rather than a mystery.
    """
    return [product for product in products or []
            if str(product.get("stock_status") or "").strip().lower()
            == IN_STOCK]


def _name_key(product):
    return " ".join(str(product.get("name") or "").split()).casefold()


def sort_products(products, how="name"):
    """The same rows, in the order the chooser names.

    A row whose price cannot be read goes last whichever way the prices run: a
    card with no price is not the cheapest one on the sheet. Ties fall back to
    the name, so two cards at the same price always come back in one order.
    """
    rows = list(products or [])

    def number(product):
        try:
            return int(product.get("id") or 0)
        except (TypeError, ValueError):
            return 0

    if how in ("price", "price_desc"):
        def key(product):
            price = parse_money(product.get("price"))
            if price is None:
                return (1, 0.0, _name_key(product))
            return (0, -price if how == "price_desc" else price,
                    _name_key(product))
        return sorted(rows, key=key)
    if how == "newest":
        return sorted(rows, key=lambda product: (-number(product),
                                                 _name_key(product)))
    return sorted(rows, key=_name_key)


def sort_key_for(label):
    """The sort key a chooser label stands for, or ``name`` if it is odd."""
    for key, text in SORTS:
        if text == str(label or ""):
            return key
    return "name"


def sort_label_for(how):
    """The chooser label a stored sort key stands for."""
    for key, text in SORTS:
        if key == str(how or ""):
            return text
    return SORTS[0][1]


# ------------------------------------------------------------------ saving
def folder_for(base):
    """``<base>/quotes`` - the folder a machine keeps its quotes in."""
    return Path(str(base)) / QUOTES_DIRNAME


def ensure_folder(folder):
    folder = Path(str(folder))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def next_number(folder, today=None):
    """The next free ``Q-2026-0001`` in this folder.

    The number is the file name, so it is also what the customer quotes at
    you on the phone; it never repeats, even if a quote is deleted later.
    """
    today = today or date.today()
    prefix = "Q-%d-" % today.year
    highest = 0
    try:
        names = [path.stem for path in Path(str(folder)).glob(prefix + "*.json")]
    except OSError:
        names = []
    for name in names:
        try:
            highest = max(highest, int(name.split("-")[-1]))
        except (IndexError, ValueError):
            continue
    return "%s%04d" % (prefix, highest + 1)


def save(quote, folder):
    """Write the quote as ``<folder>/<number>.json``; returns the path.

    The dict that was passed in is updated to what was written - its number
    most of all. A first save is where a quote *gets* its number, and the
    caller that goes on to print the PDF has to know it.
    """
    written = normalise(quote)
    if not written["number"]:
        written["number"] = next_number(folder)
    folder = ensure_folder(folder)
    written["updated"] = datetime.now().isoformat(timespec="seconds")
    path = folder / ("%s.json" % written["number"])
    try:
        path.write_text(json.dumps(written, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    except OSError as exc:
        raise QuoteError("The quote could not be saved to %s (%s)."
                         % (path, exc))
    if isinstance(quote, dict) and quote is not written:
        quote.clear()
        quote.update(written)
    return path


def load(path):
    """Read one quote file, whatever state it is in."""
    path = Path(str(path))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise QuoteError("The quote %s could not be read (%s)." % (path, exc))
    except ValueError:
        raise QuoteError(
            "The quote %s is not readable JSON." % path.name,
            "It can be opened in Notepad and repaired, or left alone: nothing "
            "else uses it.")
    if not isinstance(raw, dict):
        raise QuoteError("The quote %s does not hold a quote." % path.name)
    quote = normalise(raw)
    if not quote["number"]:
        quote["number"] = path.stem
    return quote


def list_quotes(folder):
    """Every saved quote, newest first, as ``{number, path, customer, ...}``.

    A file that cannot be read is still listed, because a quote the user
    cannot see is worse than one that says it is broken.
    """
    rows = []
    try:
        paths = sorted(Path(str(folder)).glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        try:
            quote = load(path)
        except QuoteError as exc:
            rows.append({"number": path.stem, "path": path, "broken": True,
                         "why": exc.message, "customer": "", "total": None,
                         "issued": "", "status": ""})
            continue
        sums = totals(quote)
        rows.append({"number": quote["number"], "path": path,
                     "broken": False, "why": "",
                     "customer": (quote.get("customer") or {}).get("name", ""),
                     "total": sums["total"], "issued": quote.get("issued", ""),
                     "status": quote.get("status", ""),
                     "currency": quote.get("currency", "")})
    rows.sort(key=lambda row: (row.get("issued") or "", row["number"]),
              reverse=True)
    return rows


# ---------------------------------------------------------------- the order
def split_address(text):
    """Turn a typed address into the fields WooCommerce keeps.

    A quote is written the way the customer wrote it - a couple of lines, a
    province, a postal code - while an order has separate boxes. This reads
    the common shapes and keeps every line, so nothing is dropped:

        Jane's Cards            -> address_2
        12 Main St              -> address_1
        Toronto, ON  M5V 2T6    -> city Toronto, state ON, postcode M5V 2T6
    """
    lines = [line.strip() for line in str(text or "").splitlines()
             if line.strip()]
    fields = {"address_1": "", "address_2": "", "city": "", "state": "",
              "postcode": "", "country": ""}
    if not lines:
        return fields
    tail = lines[-1]
    tokens = tail.replace(",", " ").split()
    postcode = ""
    #  Canadian postal code: A1A 1A1, with or without the space.
    for index in range(len(tokens) - 1, -1, -1):
        word = tokens[index]
        single = re.fullmatch(r"[A-Za-z]\d[A-Za-z]\d[A-Za-z]\d", word)
        if single:
            postcode = (word[:3] + " " + word[3:]).upper()
            tokens.pop(index)
            break
        if index and re.fullmatch(r"[A-Za-z]\d[A-Za-z]", tokens[index - 1]) \
                and re.fullmatch(r"\d[A-Za-z]\d", word):
            postcode = (tokens[index - 1] + " " + word).upper()
            del tokens[index - 1:index + 1]
            break
    state = ""
    if len(tokens) >= 2 and len(tokens[-1]) == 2 and tokens[-1].isalpha():
        state = tokens[-1].upper()
        tokens.pop()
    else:
        for name, code in (("Ontario", "ON"), ("Quebec", "QC"),
                           ("Alberta", "AB"), ("Manitoba", "MB"),
                           ("Saskatchewan", "SK"), ("Nova Scotia", "NS"),
                           ("New Brunswick", "NB"),
                           ("British Columbia", "BC"),
                           ("Newfoundland", "NL"),
                           ("Prince Edward Island", "PE"),
                           ("Yukon", "YT"), ("Nunavut", "NU"),
                           ("Northwest Territories", "NT")):
            if tokens and tokens[-1].lower() == name.lower():
                state = code
                tokens.pop()
                break
    city = " ".join(tokens).strip()
    streets = lines[:-1]
    if (city or state or postcode) and (len(lines) > 1 or postcode or state):
        fields.update({"city": city, "state": state, "postcode": postcode})
    else:
        #  One line with no city or postal code in it is a street, and an
        #  unrecognised shape keeps the whole line as the street: the order
        #  still shows everything the customer wrote.
        streets = lines
    if streets:
        fields["address_1"] = streets[0]
        if len(streets) > 1:
            fields["address_2"] = ", ".join(streets[1:])
    #  The shop is Canadian; the country is only worth filling in on an order
    #  that actually carries an address.
    if any(fields[key] for key in ("address_1", "address_2", "city",
                                   "postcode")):
        fields["country"] = "CA"
    return fields


def _join(first, second):
    first, second = str(first or "").strip(), str(second or "").strip()
    if first and second:
        return first + ", " + second
    return first or second


def split_name(full_name):
    """``("Jane", "Smith")`` from "Jane Smith"; the whole thing if unsure."""
    words = str(full_name or "").split()
    if not words:
        return "", ""
    if len(words) == 1:
        return words[0], ""
    return words[0], " ".join(words[1:])


def billing_payload(quote):
    """The ``billing`` block for the order, from the quote's customer block."""
    customer = (quote or {}).get("customer") or {}
    first, last = split_name(customer.get("name"))
    billing = {"first_name": first, "last_name": last}
    for key in ("email", "phone"):
        value = str(customer.get(key) or "").strip()
        if value:
            billing[key] = value
    address = split_address(customer.get("address"))
    billing.update({key: value for key, value in address.items() if value})
    if not any(value for value in billing.values()):
        #  Nobody was typed in: an order with an empty "billing" block is
        #  noise in the dashboard, not information.
        return {}
    return billing


def order_payload(quote, status="pending"):
    """The body that turns a quote into a pending order on the website.

    The prices on the quote are *not* sent: WooCommerce prices a line from
    the product itself, so an order always costs what the shop says today.
    That is checked instead - :func:`create_order` reads the total back and
    names any difference, which is the only honest way to find out that a
    card was repriced after the quote went out.
    """
    items = [item for item in items_of(quote)
             if int(item.get("product_id") or 0)]
    if not items:
        raise QuoteError(
            "None of the cards on this quote came from the website, so there "
            "is nothing for an order to point at.",
            "A quote built by hand can still be printed and sent; turning it "
            "into an order needs the cards searched from your stock.")
    sums = totals(quote)
    payload = {"status": status, "set_paid": False,
               "line_items": [{"product_id": int(item["product_id"]),
                               "quantity": item_quantity(item)}
                              for item in items]}
    if sums["discount"] > 0:
        payload["fee_lines"] = [{"name": sums["discount_label"],
                                 "total": "%.2f" % -sums["discount"]}]
    billing = billing_payload(quote)
    if billing:
        payload["billing"] = billing
    note = ["Quote %s" % (quote.get("number") or "")]
    if quote.get("valid_until"):
        note.append("valid until %s" % quote["valid_until"])
    if (quote.get("notes") or "").strip():
        note.append(str(quote["notes"]).strip())
    payload["customer_note"] = " - ".join(part for part in note if part)
    payload["meta_data"] = [{"key": "_alex_quote",
                             "value": str(quote.get("number") or "")}]
    return payload


def create_order(quote, site, key, secret, api=None, timeout=60):
    """Create the order, then check what the website actually kept.

    Returns ``{order, total, quoted, difference, note}``: the order the site
    answered with, the total it came to, the total that was quoted, and the
    difference between them when a price moved in between. A difference is
    not an error - the order exists and is right - but it must be said out
    loud, because the customer holds the other number on paper.
    """
    api = api or woo_orders.api_request
    if not (site and key and secret):
        raise QuoteError(
            "Turning a quote into an order needs the WooCommerce keys.",
            "woo-keys.txt holds them (lines 1-3). Until they are saved the "
            "quote can still be printed and sent.")
    payload = order_payload(quote)
    sums = totals(quote)
    try:
        _status, order = api(site, key, secret, ORDERS_PATH, method="POST",
                             payload=payload, timeout=timeout)
    except woo_orders.OrderError as exc:
        raise QuoteError("The website refused the order. %s" % exc.message)
    if not isinstance(order, dict) or not order.get("id"):
        raise QuoteError(
            "The website accepted the order but sent no number back, so it "
            "cannot be confirmed.",
            "Check the order list on the website before sending anything to "
            "the customer.")
    try:
        kept = float(str(order.get("total") or "0").replace(",", ""))
    except ValueError:
        kept = None
    difference = None
    if kept is not None:
        difference = round(kept - sums["total"], 2)
        if abs(difference) < 0.005:
            difference = None
    note = ""
    if difference:
        note = ("The order came to %s but the quote says %s - a price changed "
                "on the website after the quote was written."
                % (money(kept, quote.get("currency")),
                   money(sums["total"], quote.get("currency"))))
    return {"order": order, "total": kept, "quoted": sums["total"],
            "difference": difference, "note": note,
            "number": str(order.get("number") or order.get("id")),
            "id": int(order.get("id") or 0)}


def mark_ordered(quote, result, folder=None):
    """Record on the quote that it became an order - and save it."""
    quote["status"] = "ordered"
    quote["order_id"] = int((result or {}).get("id") or 0)
    quote["order_number"] = str((result or {}).get("number") or "")
    if folder:
        save(quote, folder)
    return quote


# ------------------------------------------------------------------- text
def as_text(quote):
    """The quote as plain text: the clipboard version, and the console's.

    It is also what gets pasted into a dashboard by hand when the keys are
    missing, so every line a person would need is here - the cards, the
    prices, the customer and the total.
    """
    sums = totals(quote)
    currency = quote.get("currency") or ""
    customer = quote.get("customer") or {}
    lines = ["Quote %s" % (quote.get("number") or "(unnumbered)"),
             "Issued %s%s" % (quote.get("issued") or "-",
                              "   valid until %s" % quote["valid_until"]
                              if quote.get("valid_until") else "")]
    if customer.get("name"):
        lines.append("For: %s" % customer["name"])
    for key in ("email", "phone"):
        if customer.get(key):
            lines.append("     %s" % customer[key])
    if customer.get("address"):
        for line in str(customer["address"]).splitlines():
            if line.strip():
                lines.append("     %s" % line.strip())
    lines.append("")
    for index, item in enumerate(items_of(quote), 1):
        price = item_price(item)
        lines.append("%2d. %-58s x%d  %s" % (
            index, item["name"][:58], item_quantity(item),
            money(price, currency) if price is not None else "no price"))
    lines.append("")
    lines.append("%d card%s, %d item%s"
                 % (sums["lines"], "" if sums["lines"] == 1 else "s",
                    sums["units"], "" if sums["units"] == 1 else "s"))
    lines.append("Subtotal  %s" % money(sums["subtotal"], currency))
    if sums["discount"]:
        lines.append("%s  -%s" % (sums["discount_label"],
                                  money(sums["discount"], currency)))
    lines.append("TOTAL     %s" % money(sums["total"], currency))
    if sums["unpriced"]:
        lines.append("(%d card%s on this quote has no price yet)"
                     % (sums["unpriced"], "" if sums["unpriced"] == 1
                        else "s"))
    if (quote.get("notes") or "").strip():
        lines.append("")
        lines.append(str(quote["notes"]).strip())
    return "\n".join(lines)
