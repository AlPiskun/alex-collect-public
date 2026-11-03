#!/usr/bin/env python3
"""Find one product on the website, and change the count it holds.

The SKU check beside this does the catalogue-wide job: it reads every product
and names the ones whose SKU does not say which printing they are. This does
the other half of the same work, one product at a time - a card came back in,
a card was found in a box, a listing was counted wrong - because a count is
usually a single correction and reading the whole shop to make it is a
detour.

Nothing here reads the website by itself: the caller hands in the products it
already has, so the search costs no requests and the list on screen is the
list that was read. The write goes through :mod:`stock_write`, which sends
one field and reads the answer back - the count that comes back is the count
that is reported, never the one that was typed.
"""
import re

import stock_write

#  A count is a whole number of cards: 0 means sold out and there is no such
#  thing as half a card.
ID_LIKE = re.compile(r"^#?(\d+)$")
SPACES = re.compile(r"\s+")


#  What the window says when a product has no count to change - and the one
#  setting on the product's own page that gives it one. Two sentences in one
#  place, because the module refuses the write and the window explains it
#  before the button is pressed, and they must say the same thing.
UNCOUNTED = ("The website does not count this product's stock, so it has no "
             "number to change.")
UNCOUNTED_HINT = ("On the product's own page, tick \"Track stock quantity for "
                  "this product\", save it, then set the count here.")


class WooEditError(Exception):
    """A count could not be written, with a sentence saying why.

    ``hint`` is what the person can do about it, and is empty when there is
    nothing to do; ``status`` is the website's HTTP status when it answered.
    """

    def __init__(self, message, hint="", status=0):
        super().__init__(message)
        self.message = str(message)
        self.hint = str(hint or "")
        self.status = int(status or 0)


def count_of(product):
    """The count the shop holds, or None when the shop does not count it.

    A product whose ``manage_stock`` is off has no number to edit: the site
    lets it be ordered without one. It is not zero - "sold out" and "not
    counted" are two different products, and the list says which one it is.
    """
    if not stock_write.stock_is_managed(product):
        return None
    value = (product or {}).get("stock_quantity")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def count_label(product):
    """The count in words, so a row never shows a blank where a number goes."""
    count = count_of(product)
    if count is None:
        return "the website does not count it"
    if count == 0:
        return "0 in stock - sold out"
    return "%d in stock" % count


def label(product, number=None, width=0):
    """One list row: the card, the count, and the SKU that finds it again."""
    product = product if isinstance(product, dict) else {}
    name = str(product.get("name") or "").strip() or "(no title)"
    sku = str(product.get("sku") or "").strip()
    text = "%s   %s   [%s]" % (name, count_label(product),
                               sku if sku else "no SKU")
    if number:
        text = "%s  %s" % (str(number).rjust(width or 1), text)
    return text


def describe(product):
    """The picked product in full: what it is, and which product it is."""
    product = product if isinstance(product, dict) else {}
    name = str(product.get("name") or "").strip() or "(no title)"
    sku = str(product.get("sku") or "").strip() or "(none)"
    product_id = str(product.get("id") or "").strip() or "(none)"
    price = str(product.get("price") or product.get("regular_price") or "")
    parts = ["SKU %s" % sku, "product %s" % product_id]
    if price:
        parts.append("%s each" % price)
    parts.append(count_label(product))
    return "%s\n%s" % (name, "   -   ".join(parts))


def parse_count(text):
    """The number a person typed, or a sentence saying why it is not one."""
    text = str(text if text is not None else "").strip()
    if not text:
        raise WooEditError("Type the count the website should show.",
                           "0 means sold out.")
    cleaned = text.replace(",", "").replace(" ", "")
    try:
        value = int(cleaned, 10)
    except (TypeError, ValueError):
        raise WooEditError("%r is not a whole number of cards." % text,
                           "Type digits only: 0 for sold out, 12 for twelve.")
    if value < 0:
        raise WooEditError("A stock count cannot be negative (%d)." % value,
                           "Type 0 for sold out.")
    return value


def find(products, query, limit=300):
    """The products a search means, the closest match first.

    An id finds that product and nothing else; a SKU finds the product whose
    SKU it is before it finds the ones that merely contain it; the card's own
    words find the products whose title holds all of them, so a second word
    narrows the list instead of replacing it.
    """
    rows = [row for row in products or [] if isinstance(row, dict)]
    query = str(query if query is not None else "").strip()
    if not query:
        return rows[:limit]
    needle = query.casefold()
    whole = ID_LIKE.match(needle)
    words = [word for word in SPACES.split(needle) if word]
    exact, sku, named, partial = [], [], [], []
    for product in rows:
        product_id = str(product.get("id") or "")
        product_sku = str(product.get("sku") or "").strip().casefold()
        name = str(product.get("name") or "").casefold()
        if whole and product_id == whole.group(1):
            exact.append(product)
        elif product_sku and product_sku == needle:
            sku.append(product)
        elif all(word in name for word in words):
            named.append(product)
        elif all(word in "%s %s" % (name, product_sku) for word in words):
            partial.append(product)
    return (exact + sku + named + partial)[:limit]


def written_note(product, before, after):
    """What the website now holds, in one sentence a person can check."""
    product = product if isinstance(product, dict) else {}
    name = str(product.get("name") or "").strip() or "that product"
    if before is None:
        return "The website now shows %d in stock on %s." % (after, name)
    if before == after:
        return "The website still shows %d in stock on %s." % (after, name)
    return ("The website now shows %d in stock on %s (it was %d)."
            % (after, name, before))


def uncounted_note():
    """The refusal and its fix, as the window has to say them together."""
    return "%s  %s" % (UNCOUNTED, UNCOUNTED_HINT)


def set_count(site, key, secret, product, text, opener=None):
    """Set one product's count from what was typed, and report what stuck.

    Returns ``{"id", "wanted", "before", "after", "note"}``. ``after`` is the
    number the website answered with, so a site that accepted the call and
    kept its own count is reported as the count it kept - by
    :func:`stock_write.set_count`, which raises rather than returning it.
    """
    product = product if isinstance(product, dict) else {}
    product_id = str(product.get("id") or "").strip()
    if not product_id:
        raise WooEditError("No product is picked, so there is nothing to "
                           "change.",
                           "Find the card and pick it in the list first.")
    if not stock_write.stock_is_managed(product):
        raise WooEditError(UNCOUNTED, UNCOUNTED_HINT)
    wanted = parse_count(text)
    before = count_of(product)
    answer = stock_write.set_count(site, key, secret, product_id, wanted,
                                   opener=opener)
    after = answer.get("inventory")
    after = wanted if after is None else int(after)
    return {"id": answer.get("id") or product_id, "wanted": wanted,
            "before": before, "after": after,
            "note": written_note(product, before, after)}
