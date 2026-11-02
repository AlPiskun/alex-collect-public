#!/usr/bin/env python3
"""Fill an eBay store from the website's most valuable cards.

eBay holds a fixed number of active listings - 250 on a free store - and the
store is worth more with the dearest cards in it. Keeping it full is a monthly
job done by hand: open the website's products, sort by price, work out which of
the top ones are not on eBay yet, and list as many as there is room for.

Every number that job needs is already read by the app: the website's
catalogue (price, stock, photos, the card's own attributes), and the store's
active listings (read live or from a saved page, the same way the stock
comparison reads them). So this module does the arithmetic and nothing else:

* :func:`plan` decides which products are next and why each one that was left
  out was left out;
* :func:`values` turns a product into the fields a listing form asks for,
  taking the card's own facts from its attributes rather than inventing them;
* :func:`render` writes the same drag-and-drop / click-to-copy page the batch's
  eBay Quick List writes, so the last step is still the one thing the app does
  not do: a person pasting a title and pressing "list".

Nothing here changes a site, and nothing is listed automatically. A product
that is already on eBay is not chosen again - matched by SKU first and then by
title, with the same matcher the stock comparison uses, because two notions of
"the same card" in one app is how the wrong card gets listed twice.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

import cs_listing
import stock_compare

#: How many active listings a free eBay store may have. A setting, because a
#: paid store has a different number - and because this is the one number that
#: decides how much of the page is worth reading.
DEFAULT_LIMIT = 250

#: eBay refuses a title longer than 80 characters, and a title cut in the
#: middle of a word reads like a typo. Cut between words, never past the limit.
TITLE_LIMIT = 80

#: How many of a card's pictures the listing gets: the front, and the back when
#: the product has one. Both are the shop's own URLs, so nothing is uploaded.
PICTURE_LIMIT = 2

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_MONEY = re.compile(r"[^0-9.\-]")


def _bare(key):
    """A name with everything but its letters and digits removed, lowercased."""
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


def limit_of(value, default=DEFAULT_LIMIT):
    """The store's listing limit, as a positive whole number.

    A blank, a zero and a word all mean "what a free store holds": the number
    decides how many cards are chosen, so a typo must not choose none.
    """
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return int(default)
    return number if number > 0 else int(default)


def price_of(product):
    """The product's price as a number, or ``None`` when it has none.

    WooCommerce writes a plain decimal, but a hand-edited product or an old
    import can carry ``1,250.00`` or ``CA$8.50``; both are read rather than
    dropped, because a card with a price that cannot be read and a card with no
    price are different things to tell a person.
    """
    for key in ("price", "regular_price", "sale_price"):
        raw = str((product or {}).get(key) or "").strip()
        if not raw:
            continue
        cleaned = _MONEY.sub("", raw.replace(",", ""))
        try:
            return float(cleaned)
        except (TypeError, ValueError):
            continue
    return None


def title_of(product):
    """The product's name, without the whitespace a title field cannot carry."""
    return _SPACE.sub(" ", str((product or {}).get("name") or "")).strip()


def listing_title(product, limit=TITLE_LIMIT):
    """The name as an eBay title: whole words, and never over the limit."""
    text = title_of(product)
    if len(text) <= int(limit):
        return text
    cut = text[:int(limit)]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.strip(" ,-")


def attribute(product, name):
    """One of the product's own attributes (``Player``, ``Year``, ...), or "".

    WooCommerce reports them as ``{"name": "Card number", "options": ["112"]}``
    and the app itself writes them with those names, so the card's facts come
    from the product rather than from a guess at its title.
    """
    wanted = _bare(name)
    for attr in (product or {}).get("attributes") or []:
        if not isinstance(attr, dict) or _bare(attr.get("name")) != wanted:
            continue
        options = attr.get("options")
        values = options if isinstance(options, (list, tuple)) else [options]
        text = ", ".join(str(value).strip() for value in values
                         if str(value or "").strip())
        if text:
            return text
    return ""


def images_of(product, limit=PICTURE_LIMIT):
    """The product's own photo URLs, the main one first."""
    urls = []
    for image in (product or {}).get("images") or []:
        if isinstance(image, dict):
            src = str(image.get("src") or "").strip()
        else:
            src = str(image or "").strip()
        if src.lower().startswith(("http://", "https://")) and src not in urls:
            urls.append(src)
    return urls[:int(limit)] if limit else urls


def stock_left(product):
    """Copies a person could sell, ``None`` when the shop does not count them.

    ``None`` is not zero: a product with stock management off is always
    available, and treating that as "sold out" would quietly drop half a shop
    from the list.
    """
    if str((product or {}).get("stock_status") or "") == "outofstock":
        return 0
    quantity = (product or {}).get("stock_quantity")
    if quantity is None:
        return None
    try:
        return int(quantity)
    except (TypeError, ValueError):
        return None


def listable(product):
    """``(yes, why not)`` for one product as an eBay candidate.

    A card is only worth listing when it has a name, is published, has a price
    to sell at, and there is at least one copy left. Anything else would put a
    listing on eBay that cannot be bought or cannot be priced - and the reason
    is carried, so the panel can say what was left out instead of shrinking
    without explanation.
    """
    if not title_of(product):
        return False, "it has no name on the website"
    status = str((product or {}).get("status") or "publish")
    if status != "publish":
        return False, "it is not published on the website (%s)" % status
    price = price_of(product)
    if price is None:
        return False, "it has no price on the website"
    if price <= 0:
        return False, "its price is zero"
    left = stock_left(product)
    if left == 0:
        return False, "the website has none in stock"
    return True, ""


def _names(entries):
    """The ``name`` of each category/tag, which is how WooCommerce sends them."""
    found = []
    for entry in entries or []:
        if isinstance(entry, dict):
            found.append(str(entry.get("name") or ""))
        else:
            found.append(str(entry or ""))
    return " ".join(found)


def sport_of(product):
    """Which of the four templates fits, from the product's own words."""
    text = " ".join([
        title_of(product),
        _names((product or {}).get("categories")),
        _names((product or {}).get("tags")),
    ]).casefold()
    for sport in ("hockey", "baseball", "basketball", "football"):
        if sport in text:
            return sport
    return ""


def template_url(product, settings=None):
    """The eBay template for this card, falling back to the default one.

    The same keys the Quick List page uses, so a template changed in User
    Settings applies to both without being set twice.
    """
    settings = settings or {}
    sport = sport_of(product)
    for key in (("ebay_template_%s_url" % sport) if sport else "",
                "ebay_template_default_url"):
        value = str(settings.get(key) or "").strip()
        if value:
            return value
    return ""


def _product_rows(products):
    """The products in the shape the stock matcher pairs on.

    ``qty`` is only ever a tie-break there, and a product whose stock is not
    counted gets 1 rather than 0 so it is not ranked as sold out.
    """
    rows = []
    for product in products or []:
        if not isinstance(product, dict) or not title_of(product):
            continue
        left = stock_left(product)
        rows.append({"name": title_of(product),
                     "sku": str(product.get("sku") or "").strip(),
                     "qty": 1 if left is None else max(0, left),
                     "id": product.get("id"),
                     "product": product})
    return rows


def plan(products, items, limit=DEFAULT_LIMIT):
    """Which products to list next, and what stands behind every number.

    ``products`` are the website's whole catalogue and ``items`` the store's
    *active* listings, as the eBay reader returns them. The answer carries the
    chosen products in the order worth listing them (dearest first, ties
    alphabetical), the room left under the limit, and every group that was
    left out - already on eBay, out of stock, unpriced - with its count.
    """
    catalogue = [product for product in products or [] if isinstance(product, dict)]
    active = [item for item in items or [] if isinstance(item, dict)]
    allowed = limit_of(limit)
    room = max(0, allowed - len(active))
    pairs, unlisted_rows, only_ebay = stock_compare.pair(
        _product_rows(catalogue), active)
    candidates, skipped = [], []
    for row in unlisted_rows:
        product = row["product"]
        ok, why = listable(product)
        if ok:
            candidates.append(product)
        else:
            skipped.append({"product": product, "why": why})
    candidates.sort(key=lambda product: (-(price_of(product) or 0),
                                         title_of(product).lower()))
    chosen = candidates[:room]
    return {"products": len(catalogue), "active": len(active), "limit": allowed,
            "room": room, "listed": len(pairs), "only_ebay": only_ebay,
            "candidates": len(candidates), "chosen": chosen,
            "left": max(0, len(candidates) - len(chosen)), "skipped": skipped}


def values(product, settings=None):
    """The fields a listing form asks for, from the product and its attributes.

    A card's own facts (year, set, player, card number, grade) are taken from
    its WooCommerce attributes when the app put them there; the marketplace
    defaults fill in what the product does not say, exactly as the batch's
    Quick List does. Nothing is read out of the title and presented as fact.
    """
    settings = settings or {}
    price = price_of(product)
    pictures = images_of(product)
    sport = sport_of(product)

    def fact(name, default_key):
        return (attribute(product, name)
                or str(settings.get(default_key, "") or "").strip())

    return {
        "title": listing_title(product),
        "price": ("%.2f" % price) if price is not None else "",
        "sku": str((product or {}).get("sku") or "").strip(),
        "sport": sport.title() if sport else "Sports Cards",
        "year": fact("Year", "ebay_default_year"),
        "manufacturer": fact("Brand", "ebay_default_manufacturer"),
        "card_number": fact("Card number", "ebay_default_card_number"),
        "player": fact("Player", "ebay_default_player"),
        "set": fact("Set", "ebay_default_set"),
        "condition": fact("Condition", "ebay_default_condition"),
        "grade": fact("Grade", "ebay_default_grade"),
        "autographed": str(settings.get("ebay_default_autographed", "No") or "No"),
        "description": (cs_listing.plain_text((product or {}).get("short_description"))
                        or cs_listing.plain_text((product or {}).get("description"))),
        "front_image": pictures[0] if pictures else "",
        "back_image": pictures[1] if len(pictures) > 1 else "",
        "product_url": str((product or {}).get("permalink") or ""),
    }


def summary(answer):
    """The sentence a person needs before reading the page.

    It says what the store looks like (how full, how much room), what was
    compared (the catalogue against the active listings), and what was left
    out and why. A list of cards without those numbers is a list a person
    cannot tell is right.
    """
    answer = answer or {}
    active = int(answer.get("active") or 0)
    allowed = int(answer.get("limit") or DEFAULT_LIMIT)
    room = int(answer.get("room") or 0)
    chosen = answer.get("chosen") or []
    left = int(answer.get("left") or 0)
    skipped = answer.get("skipped") or []
    if not active and not chosen:
        return ("eBay shows no active listings and the website has no product "
                "to fill them with.")
    head = ("eBay has %d active listing%s, so there is room for %d more under "
            "a limit of %d." % (active, "" if active == 1 else "s", room, allowed))
    if not room:
        head += (" The store is full: nothing is chosen until a listing ends "
                 "or the limit goes up.")
    if not chosen:
        head += (" No unlisted product was ready to go on the page.")
    else:
        first, last = chosen[0], chosen[-1]
        head += (" %d card%s chosen, dearest first: %s to %s." %
                 (len(chosen), "" if len(chosen) == 1 else "s",
                  _money(first), _money(last)))
    if left:
        head += " %d more unlisted card%s stayed behind, below the cut." % (
            left, "" if left == 1 else "s")
    if skipped:
        names = sorted({entry.get("why") or "" for entry in skipped})
        head += " %d unlisted product%s could not be listed: %s." % (
            len(skipped), "" if len(skipped) == 1 else "s", "; ".join(names))
    return head


def _money(product):
    """``$12.00`` for a product, for a sentence about prices."""
    price = price_of(product)
    return "$%.2f" % price if price is not None else "(no price)"


def _page_text(text):
    return html.escape(str(text or ""), quote=False)


def render(chosen, settings=None, note="", built=None):
    """The Quick List page for the chosen products: ``(html, template_urls)``.

    The same contract as the batch's page - one draggable, click-to-copy button
    per field, each card's own pictures linked by the URL the shop serves, and
    a link straight to the matching eBay template - because this page is used
    the same way: one card at a time, pasted into a form.
    """
    settings = settings or {}
    built = built or datetime.now()
    cards, templates = [], []
    for index, product in enumerate(chosen or [], 1):
        fields = values(product, settings)
        template = template_url(settings=settings, product=product)
        if template and template not in templates:
            templates.append(template)
        snippets = []
        for label, value in (("Title", fields["title"]),
                             ("Buy It Now price (CAD)", fields["price"]),
                             ("SKU", fields["sku"]),
                             ("Sport / Game", fields["sport"]),
                             ("Year", fields["year"]),
                             ("Manufacturer", fields["manufacturer"]),
                             ("Card Number", fields["card_number"]),
                             ("Player", fields["player"]),
                             ("Set", fields["set"]),
                             ("Condition", fields["condition"]),
                             ("Grade", fields["grade"]),
                             ("Autographed", fields["autographed"])):
            escaped = html.escape(str(value or ""), quote=True)
            snippets.append(
                '<button class="snippet" draggable="true" data-value="%s" '
                'title="Drag to eBay or click to copy"><b>%s</b><br>%s</button>'
                % (escaped, html.escape(label), escaped or "(blank)"))
        description = html.escape(fields["description"], quote=True)
        pictures = []
        for label, url in (("Front", fields["front_image"]),
                           ("Back", fields["back_image"])):
            if not url:
                continue
            pictures.append(
                '<div class="image"><a href="%s" target="_blank" '
                'rel="noopener"><img src="%s" alt="%s image"></a>'
                '<button class="snippet" draggable="true" data-value="%s" '
                'title="Drag image URL to eBay or click to copy">%s image URL'
                '<br>%s</button></div>'
                % (html.escape(url, quote=True), html.escape(url, quote=True),
                   label, html.escape(url, quote=True), label,
                   _page_text(url)))
        link = ('<a class="template" href="%s" target="_blank" rel="noopener">'
                'Open the eBay template</a>'
                % html.escape(template, quote=True) if template else
                '<span class="template missing">No eBay template is set: add '
                'one in User Settings</span>')
        product_url = fields["product_url"]
        product_link = ('<p class="product"><a href="%s" target="_blank" '
                        'rel="noopener">This card on the website</a></p>'
                        % html.escape(product_url, quote=True)
                        if product_url else "")
        cards.append(
            '<article><h2>%d. %s</h2><p class="price">$%s CAD</p>%s'
            '<p class="sport">Sport template: %s</p>'
            '<div class="snippets">%s</div>'
            '<h3>Description (drag or click to copy)</h3>'
            '<pre class="description snippet" draggable="true" data-value="%s" '
            'title="Drag to eBay or click to copy">%s</pre>'
            '<div class="images">%s</div>%s%s</article>'
            % (index, _page_text(fields["title"]), _page_text(fields["price"]),
               product_link, _page_text(fields["sport"]), "".join(snippets),
               description, _page_text(fields["description"]),
               "".join(pictures), link,
               '<p class="product"><small>%s</small></p>'
               % _page_text(fields["product_url"]) if product_url else ""))
    page = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alex Collect - eBay fill list</title>
<style>
:root{color-scheme:light;font:15px/1.5 system-ui,sans-serif;color:#172033;background:#eef2f7}body{max-width:1100px;margin:24px auto;padding:0 16px}h1{color:#183153}article{background:white;border:1px solid #d7dfeb;border-radius:12px;padding:20px;margin:18px 0;box-shadow:0 4px 18px #1b365010}h2{margin:0;color:#183153}.price{font-size:1.35rem;color:#08652c;font-weight:700}.sport{color:#52627a}.snippets{display:flex;flex-wrap:wrap;gap:8px}.snippet{font:13px/1.4 ui-monospace,monospace;text-align:left;color:#183153;background:#f5f8fc;border:1px solid #cdd8e6;border-radius:8px;padding:9px 12px;cursor:grab;max-width:100%;overflow-wrap:anywhere}.snippet:hover{background:#e9f1fb}.description{white-space:pre-wrap;max-height:260px;overflow:auto;background:#fafbfd;border:1px solid #e1e6ee;border-radius:8px;padding:12px}.images{display:flex;flex-wrap:wrap;gap:14px;margin:14px 0}.image{display:flex;flex-direction:column;gap:6px;max-width:280px}.image img{max-width:260px;max-height:190px;object-fit:contain;background:#f5f5f5;border:1px solid #ddd;border-radius:8px}.template{display:inline-block;margin-top:14px;background:#e53238;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700}.missing{color:#9b3c00}.note{background:#fff7e8;border:1px solid #f0d29d;border-radius:8px;padding:12px}.status{color:#087044;font-weight:600}
</style>
<body><h1>Alex Collect - these cards are next for eBay</h1>
<p class="note">__NOTE__</p>
<p class="status">Click a field to copy it. Drag a field onto the matching eBay form field. Nothing here lists or submits anything: sign in, open a template, check each field, and submit.</p>
__CARD_SECTIONS__
<script>
document.querySelectorAll('.snippet').forEach(function(btn){btn.addEventListener('dragstart',function(e){e.dataTransfer.setData('text/plain',btn.dataset.value||'');e.dataTransfer.effectAllowed='copy'});btn.addEventListener('click',async function(){var value=btn.dataset.value||'';try{await navigator.clipboard.writeText(value)}catch(_){var box=document.createElement('textarea');box.value=value;document.body.appendChild(box);box.select();document.execCommand('copy');box.remove()}var old=btn.innerHTML;btn.innerHTML='Copied';setTimeout(function(){btn.innerHTML=old},900)})});
</script></body></html>"""
    page = page.replace("__NOTE__", _page_text(
        note or "The cards chosen for the room left under your eBay limit, "
                "dearest first."))
    page = page.replace("__CARD_SECTIONS__", "".join(cards))
    return page, templates


def write_page(page, folder, built=None):
    """Write the page beside the app and return its path.

    One file per run, named with the minute, so yesterday's selection is still
    there to compare against and nothing is overwritten by accident.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (built or datetime.now()).strftime("%Y%m%d_%H%M%S")
    path = folder / ("ebay_fill_%s.html" % stamp)
    path.write_text(page, encoding="utf-8")
    return path
