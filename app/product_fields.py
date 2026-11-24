#!/usr/bin/env python3
"""The fields a website's products are missing, and the words that fill them.

A product created before a field was part of the batch sits on the website
without it: no brand in WooCommerce's Brands list, no Rank Math focus keyword,
no category of its own, no SKU, no tags. Every one of those is a field the app
can fill in from the product's **own SEO title**, which is where the card's
facts are already written - and with ``card_words``, the same rules the batch
uses, so a brand filled in here and a brand written by a batch are the same
brand.

Two rules run through all of it, because this writes to a live shop:

* **Only the field that is missing is written.** A product that already has a
  brand, a keyword, a category, a SKU or tags is not in the list at all, so
  nothing anybody typed by hand is replaced.
* **A title that does not say it gets no value.** An entry whose ``value`` is
  empty is one the title cannot settle, and those are counted and named with
  the reason rather than given a guess - an invented brand on a live listing
  is worse than no brand.

A SKU is the one field this does not hold for, because a SKU is not a claim
about the card: it is the identifier the shop, the CSV and the comparison tell
two products apart by, and a product without one is a product nothing can
address. So a title that states too little for the batch's own SKU (year,
number and player) still gets one - **what it does say, plus random digits** -
shown with everything else before anything is written, and never a SKU another
product already holds. A brand, a keyword, a category or a tag invented the
same way would be a lie about the card; a made-up SKU is only an address.
"""
from __future__ import annotations

import html
import random
import re

import card_words
import woo_create

#: The five fields, in the order the panel offers them.
FIELDS = ("brand", "keyword", "categories", "sku", "tags")

#: The words a window uses for each one.
FIELD_WORDS = {
    "brand": "brand",
    "keyword": "focus keyword",
    "categories": "category",
    "sku": "SKU",
    "tags": "tags",
}

#: The Rank Math meta the focus keyword is kept in, and the one SEO plugins
#: keep the product's own title in. A product's title is what its facts are
#: read from - its SEO title first, because that is the words the seller wrote
#: for the search engines and the words its own name comes from.
KEYWORD_META = "rank_math_focus_keyword"
TITLE_META = "rank_math_title"

#: The attribute the batch writes a maker into. A product that already carries
#: one has its brand written down by the seller, so that word is used before
#: the title is read at all.
BRAND_ATTRIBUTES = ("brand", "manufacturer")

_TAG_RE = re.compile(r"<[^>]+>")


# ------------------------------------------------------------------ reading
def meta_rows(product):
    """The product's own ``meta_data`` rows, as a list of dicts."""
    rows = (product or {}).get("meta_data")
    return [row for row in rows or [] if isinstance(row, dict)]


def meta_row(product, wanted):
    """The meta row for one key - id, key and value - or ``None``."""
    wanted = str(wanted or "").strip().lower()
    for row in meta_rows(product):
        if str(row.get("key") or "").strip().lower() == wanted:
            return row
    return None


def meta_value(product, wanted):
    """What one meta key holds, as a stripped string ("" when it holds nothing)."""
    row = meta_row(product, wanted)
    if row is None:
        return ""
    value = row.get("value")
    if isinstance(value, (list, tuple)):
        value = " ".join(str(part) for part in value if str(part).strip())
    return str(value or "").strip()


def title_of(product):
    """The words this product's facts are read from.

    Its Rank Math title when it has one - that is the title the seller wrote
    for the search engines, and the product's name is usually its copy - and
    its name otherwise. Nothing else is invented into it.
    """
    return (meta_value(product, TITLE_META)
            or str((product or {}).get("name") or "").strip())


def titles_of(product):
    """The product's own titles, SEO title first, each one once."""
    titles = []
    for text in (meta_value(product, TITLE_META),
                 str((product or {}).get("name") or "")):
        text = str(text or "").strip()
        if text and text not in titles:
            titles.append(text)
    return titles


def description_text(product):
    """The product's description and short description, as plain words."""
    words = []
    for key in ("description", "short_description"):
        text = _TAG_RE.sub(" ", str((product or {}).get(key) or ""))
        words.append(html.unescape(text))
    return " ".join(words)


def words_of(product):
    """Every word a product states about itself: title, name, description,
    tags and the focus keyword it already has. The batch detects a card's sport
    from exactly these, so the audit does too."""
    parts = [title_of(product), str((product or {}).get("name") or ""),
             description_text(product)]
    parts.extend(str(tag.get("name") or "") for tag in
                 (product or {}).get("tags") or [] if isinstance(tag, dict))
    parts.append(meta_value(product, KEYWORD_META))
    return " ".join(part for part in parts if part)


def brands_of(product):
    """The Brands-list names on one product, in the site's own order."""
    names = []
    for row in (product or {}).get("brands") or []:
        if isinstance(row, dict):
            name = str(row.get("name") or "").strip()
            if name:
                names.append(name)
        elif str(row or "").strip():
            names.append(str(row).strip())
    return names


def categories_of(product):
    """The product's categories as ``(id, name)`` pairs."""
    found = []
    for row in (product or {}).get("categories") or []:
        if isinstance(row, dict):
            found.append((int(row.get("id") or 0),
                          str(row.get("name") or "").strip()))
    return found


def tags_of(product):
    """The product's tag names."""
    return [str(row.get("name") or "").strip()
            for row in (product or {}).get("tags") or []
            if isinstance(row, dict) and str(row.get("name") or "").strip()]


def field_value(product, field):
    """What one product holds in one field, as text ("" when it holds nothing)."""
    if field == "brand":
        return ", ".join(brands_of(product))
    if field == "keyword":
        return meta_value(product, KEYWORD_META)
    if field == "categories":
        return " > ".join(name for _id, name in categories_of(product) if name)
    if field == "sku":
        return str((product or {}).get("sku") or "").strip()
    if field == "tags":
        return ", ".join(tags_of(product))
    raise ValueError("no such field: %r" % (field,))


def has(product, field):
    """Whether this product already has the field - the only ones left alone."""
    return bool(field_value(product, field).strip())


def brand_list_answering(products):
    """Whether the site's own answer carries a Brands list at all.

    A shop that has no Brands taxonomy answers with products that have no
    ``brands`` key. That is not "every product is missing a brand" - it is a
    website with nowhere to put one - so it is told apart before anything is
    listed, and the panel says which WooCommerce version brought the list.
    """
    for product in products or []:
        if isinstance(product, dict) and "brands" in product:
            return True
    return False


# --------------------------------------------------------------- the values
def _brand_attribute(product):
    """The maker the product's own Brand detail row holds, or ""."""
    for attr in (product or {}).get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        if str(attr.get("name") or "").strip().lower() not in BRAND_ATTRIBUTES:
            continue
        for option in attr.get("options") or []:
            word = str(option or "").strip()
            if word:
                return word
    return ""


def value_for(product, field, taken=None):
    """``(value, note)`` - what would be written in this field, and where it
    came from. An empty value is a title that does not settle it.

    ``taken`` is the SKUs the website already holds, ``{sku_lower: name}``, so
    a SKU the audit would write onto a second product is refused here instead
    of by the shop (which answers a duplicate SKU with a refusal, after the
    person has already said yes to a list that said it would work).
    """
    title = title_of(product)
    told = card_words.facts(title)

    if field == "brand":
        written = _brand_attribute(product)
        if written:
            return written, "from the product's own Brand detail"
        #  The SEO title and the name are usually the same words, and a maker
        #  named in either is this product's maker - so a product whose name
        #  still carries "O-Pee-Chee" is not called brandless because its SEO
        #  title was rewritten without it.
        for text in titles_of(product):
            found = card_words.facts(text)["brand"]
            if found:
                return found, "from its title"
        return "", "its title names no maker this app knows"

    if field == "keyword":
        keyword = told["keyword"]
        if keyword:
            return keyword, ("the year, the maker and the player its title "
                             "states - the phrase a buyer searches for")
        return "", ("its title states no year, maker or player to make a "
                    "search phrase from")

    if field == "categories":
        names = card_words.category_names(words_of(product))
        if not names:
            return [], "its words name no kind of card"
        if card_words.names_sport(words_of(product)):
            return names, "from the sport its own words name"
        return names, ("its words name no sport, so it goes where the batch "
                       "puts those cards")

    if field == "sku":
        sku = told["sku"]
        if not sku:
            return "", "its title does not state the year, number and player a SKU is made of"
        if taken and sku.lower() in taken:
            other = str(taken[sku.lower()] or "").strip()
            return "", ("that SKU is already another product's (%s)" % other
                        if other else "that SKU is already another product's")
        return sku, "the batch's own SKU, from its title"

    if field == "tags":
        tags = told["tags"]
        if tags:
            return tags, "the words its title already states"
        return [], "its title states no year, maker, player or number"

    raise ValueError("no such field: %r" % (field,))


#  How a SKU is made up when the title does not state the batch's three facts.
#: Four digits is 10,000 tails, which is far more than a shop of a few thousand
#: products needs; the tail is drawn again when it collides, so the size is the
#: length of the SKU and not a limit on how many products can have one.
LOOSE_DIGITS = 4
#: How many tails are drawn before a product is left alone instead. With
#: 10,000 tails and a few thousand products, sixty draws failing is not a thing
#: that happens - it is here so the loop cannot be an infinite one.
LOOSE_TRIES = 60
_RNG = random.Random()

#: What the audit says about a SKU it made up, in the words a window shows.
LOOSE_NOTE = ("made up from what its title says plus %d random digits - its "
              "title does not state the year, number and player the batch's "
              "own SKU is made of" % LOOSE_DIGITS)


def loose_parts(title, facts=None):
    """The pieces of a made-up SKU: what the title does say, in SKU order.

    The same order the batch's own SKU uses - maker and year, card number,
    player, grade - so a made-up SKU still reads like the others and sorts
    beside the card it belongs to. A title that states none of it is named by
    its own first words, because those are still the only thing there is.
    """
    facts = facts or card_words.facts(title)
    parts = []
    code = card_words.brand_code(facts["brand"]) if facts["brand"] else ""
    year = str(facts["year"] or "").strip()
    if code and year:
        parts.append(code + year)
    elif code:
        parts.append(code)
    elif year:
        parts.append(year)
    if facts["card_num"]:
        parts.append(str(facts["card_num"]))
    if facts["last"]:
        parts.append(str(facts["last"]))
    if facts["grade"]:
        parts.append(card_words.grade_slug(facts["grade"]))
    if not parts:
        parts = [word for word in str(title or "").split()[:2] if word]
    return [piece for piece in (card_words.sku_component(part) for part in parts)
            if piece]


def loose_sku(title, taken=(), rng=None, facts=None):
    """A SKU made from what a title says plus random digits, or ``""``.

    ``taken`` is every SKU already spoken for - the shop's own and the ones
    this audit is proposing - and the tail is drawn again until this one is not
    among them, so a made-up SKU is never one another product holds. The value
    is fixed for the audit that made it: what the preview shows is exactly what
    the write sends.
    """
    rng = rng or _RNG
    head = "-".join(loose_parts(title, facts=facts))
    if not head:
        return ""
    spoken = {str(sku).strip().lower() for sku in taken or ()}
    span = 10 ** LOOSE_DIGITS
    for _attempt in range(LOOSE_TRIES):
        tail = "%0*d" % (LOOSE_DIGITS, rng.randrange(span))
        sku = "%s-%s" % (head, tail)
        if sku.lower() not in spoken:
            return sku
    return ""


def describe(entry):
    """One ``value`` as the words a window shows."""
    value = entry.get("value")
    if isinstance(value, (list, tuple)):
        joiner = " > " if entry.get("field") == "categories" else ", "
        return joiner.join(str(part) for part in value)
    return str(value or "")


def _fill_made_up_skus(result, taken, rng=None):
    """Give every title that states too little a SKU made from what it does.

    Only those. A title the batch's own rule *can* read, whose SKU is spoken
    for - by the shop or by a second product here - is left alone, because that
    is a product that already exists or two products that need a decision, not
    a title that says too little; a made-up SKU there would hide the duplicate
    instead of naming it.
    """
    spoken = {str(sku).strip().lower() for sku in taken}
    for entry in result["missing"]:
        if entry["settled"]:
            spoken.add(str(entry["value"]).strip().lower())
    for entry in result["missing"]:
        if entry["settled"]:
            continue
        #  The SEO title is what a value is read from, and the product's own
        #  name is the same words when the shop never had an SEO title.
        text = str(entry.get("title") or entry.get("name") or "").strip()
        facts = card_words.facts(text)
        if facts["sku"]:
            continue
        sku = loose_sku(text, taken=spoken, rng=rng, facts=facts)
        if not sku:
            entry["note"] = ("its title says nothing a SKU could be made from")
            continue
        spoken.add(sku.lower())
        entry["value"] = sku
        entry["settled"] = True
        entry["loose"] = True
        entry["note"] = LOOSE_NOTE


def audit(products, field, rng=None):
    """The products with nothing in one field, and what would fill it.

    ``missing`` is every product the field is absent from; ``ready`` are the
    ones a value can be worked out for, and ``unsure`` the rest - each with the
    sentence that says why its title is not enough, because a list that said
    nothing about them would look like a shop with nothing to do.

    For a SKU, a title that states too little is not the end of it: the entry
    is filled with a made-up SKU (``loose`` is set, and its ``note`` says how
    it was made) from everything the title does say, with a random tail that is
    checked against every SKU already spoken for. ``rng`` is the source of
    those digits, so a check can be run twice and get the same list.
    """
    products = [p for p in products or [] if isinstance(p, dict)]
    result = {"field": field, "word": FIELD_WORDS.get(field, field),
              "products": len(products), "supported": True,
              "missing": [], "ready": [], "unsure": []}
    if field == "brand" and products and not brand_list_answering(products):
        result["supported"] = False
        return result

    taken = {}
    for product in products:
        sku = str(product.get("sku") or "").strip()
        if sku:
            taken.setdefault(sku.lower(), str(product.get("name") or ""))

    for product in products:
        if has(product, field):
            continue
        value, note = value_for(product, field, taken=taken)
        entry = {"field": field, "id": product.get("id"),
                 "name": str(product.get("name") or "").strip(),
                 "title": title_of(product), "value": value, "note": note,
                 #  A focus keyword's own meta row: writing it back with its id
                 #  updates the row, writing it without one adds a second.
                 "meta_id": (meta_row(product, KEYWORD_META) or {}).get("id")}
        entry["settled"] = bool(value)
        result["missing"].append(entry)

    #  Two products proposing one SKU is the same collision as one proposing a
    #  SKU another already holds, and the shop would refuse the second after
    #  the confirmation said both would be written.
    if field == "sku":
        counted = {}
        for entry in result["missing"]:
            if entry["settled"]:
                counted.setdefault(str(entry["value"]).lower(), []).append(entry)
        for sku, entries in counted.items():
            if len(entries) < 2:
                continue
            for entry in entries:
                entry["value"] = ""
                entry["settled"] = False
                entry["note"] = ("%d products here work out to that one SKU, "
                                 "and a website holds one product per SKU"
                                 % len(entries))
        _fill_made_up_skus(result, taken, rng)

    for entry in result["missing"]:
        (result["ready"] if entry["settled"] else result["unsure"]).append(entry)
    return result


def summary(result):
    """One sentence saying what an audit found."""
    result = result or {}
    field = FIELD_WORDS.get(result.get("field"), result.get("field") or "")
    total = int(result.get("products") or 0)
    if not result.get("supported", True):
        return ("The website does not report a Brands list, so there is no "
                "brand field to fill in.")
    missing = result.get("missing") or []
    if not missing:
        return "Every one of the %d products has a %s." % (total, field)
    ready = result.get("ready") or []
    made = [entry for entry in ready if entry.get("loose")]
    from_title = len(ready) - len(made)
    line = "%d of %d products have no %s" % (len(missing), total, field)
    if from_title:
        line += ", and %d of those can be filled in from the card's own title" \
                % from_title
    if made:
        everyone = len(made) == len(ready) and len(made) > 1
        line += (", and %s given a SKU made up from what %s plus random digits"
                 % ("all %d of those can be" % len(made) if everyone
                    else "%d of those can be" % len(made),
                    "its title says" if len(made) == 1 else "their titles say"))
    unsure = len(result.get("unsure") or [])
    if unsure:
        line += ("; %d cannot be filled in, and %s left alone"
                 % (unsure, "it is" if unsure == 1 else "they are"))
    return line + "."


# --------------------------------------------------------------- the writing
def _request(site, key, secret, path, method="GET", payload=None, params=None,
             timeout=60, opener=None, what=""):
    """One call to the shop, refusing to guess when it says no.

    The plumbing is ``woo_create``'s - one address builder, one retry rule and
    one explanation of a refusal, so a 401 here reads like a 401 there.
    """
    url = woo_create.api_url(site, path, key, secret, params)
    if not url:
        raise woo_create.ProductError("No website address or keys are available.")
    status, answer = woo_create._send(url, method, payload, timeout, opener)
    if status in (401, 403) or status >= 400:
        raise woo_create._explain(status, answer, what or "write to the shop")
    return answer


def write(site, key, secret, field, entry, timeout=60, opener=None, cache=None):
    """Write one field on one product, and read the shop's answer back.

    Only the field asked for is in the body, so a write cannot move a title, a
    price, a photo or a state - and the answer is read back, because a 200
    that quietly kept the old value would otherwise be reported as done.
    """
    product_id = str((entry or {}).get("id") or "").strip()
    if not product_id:
        raise woo_create.ProductError("That product has no id, so it cannot be "
                                      "written.")
    value = (entry or {}).get("value")
    if not value:
        raise woo_create.ProductError("That product's title does not say what "
                                      "to write, so nothing was sent.")
    path = "%s/%s" % (woo_create.PRODUCTS_PATH, product_id)

    if field == "brand":
        #  The same resolution a batch uses when it creates a card, so a brand
        #  filled in here and a brand written at creation are one term.
        ident = woo_create.brand_id(site, key, secret, value, timeout=timeout,
                                    opener=opener, cache=cache)
        answer = _request(site, key, secret, path, "PUT",
                          {"brands": [{"id": ident}]}, timeout=timeout,
                          opener=opener, what="set the brand on a product")
        kept = str(value).lower() in [name.lower() for name in
                                      brands_of(answer)]

    elif field == "keyword":
        rows = []
        existing = {"id": (entry or {}).get("meta_id")}
        if existing.get("id"):
            #  Sent with its own row id: a meta row without one is a *second*
            #  row with the same key, and Rank Math would then hold two focus
            #  keywords for one product.
            rows.append({"id": existing["id"], "key": KEYWORD_META,
                         "value": value})
        else:
            rows.append({"key": KEYWORD_META, "value": value})
        answer = _request(site, key, secret, path, "PUT",
                          {"meta_data": rows}, timeout=timeout, opener=opener,
                          what="set the focus keyword on a product")
        kept = meta_value(answer, KEYWORD_META) == value

    elif field == "categories":
        ids = woo_create.category_ids(site, key, secret, list(value),
                                      timeout=timeout, opener=opener)
        if not ids:
            raise woo_create.ProductError("The website has no category to put "
                                          "this card in.")
        answer = _request(site, key, secret, path, "PUT",
                          {"categories": [{"id": ident} for ident in ids]},
                          timeout=timeout, opener=opener,
                          what="put a product in a category")
        kept = set(ids) <= {ident for ident, _name in categories_of(answer)}

    elif field == "sku":
        answer = woo_create.set_sku(site, key, secret, product_id, value,
                                    timeout=timeout, opener=opener)
        kept = str(answer.get("sku") or "").strip() == str(value)

    elif field == "tags":
        answer = _request(site, key, secret, path, "PUT",
                          {"tags": [{"name": tag} for tag in value]},
                          timeout=timeout, opener=opener,
                          what="put tags on a product")
        held = {name.lower() for name in tags_of(answer)}
        kept = {str(tag).lower() for tag in value} <= held

    else:
        raise ValueError("no such field: %r" % (field,))

    return {"wrote": value, "kept": kept, "answer": answer,
            "kept_text": field_value(answer if isinstance(answer, dict) else {},
                                     field)}


def writes_nothing(result):
    """Whether an audit would write anything, for a caller that asks first."""
    return not (result or {}).get("ready")
