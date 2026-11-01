"""Where the stock numbers disagree - and nothing else.

A card can sit on four sites at once. When one of them sells it, the other
listings keep offering it until somebody goes and changes them; the app can
already *write* that change on CanadianShopper, but it could not tell you
*where* the numbers had drifted apart. Checking that by hand means opening four
dashboards and reading very similar titles, which is exactly the kind of job
that gets skipped.

This module is the read-only half: two lists of (card, quantity) go in, the
cards are matched up, and only the pairs whose numbers disagree come out. No
Tk, no network (the GET and the plugin's file are both injected), and nothing
is written anywhere.

Matching is deliberately conservative. A wrong pair would report stock trouble
on a card that is fine, and a missed pair only means it was not compared - so
the SKU is used when both sides have one, and titles are matched by the same
weighing the order panel uses (numbers count double, missing "the" counts for
nothing). A card that cannot be matched is reported as not compared, never as
a disagreement.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import woo_orders

#  Below this the two titles are not the same card. Higher than the order
#  panel's search threshold on purpose: that list is a suggestion a person
#  picks from, this one is an accusation.
DEFAULT_MIN_SCORE = 0.55
IGNORED_FILE = "stock-ignored.json"

#  Every row of the action list is one of these three, because they need
#  different things done about them:
#    a disagreement can be corrected by writing the website's count across;
#    a card on one side only cannot - it is either expected (the card sold out
#    there) and gets ignored, or it is a mistake to look at.
FIX = "fix"
ONLY_WOO = "only-woo"
ONLY_OTHER = "only-other"
#  A card that is on both sites but whose other-site listing is not ON SALE.
#  It is not a disagreement to correct - a count written to a draft or an
#  archived listing changes nothing anyone can buy - so it needs its own words
#  and its own fix: publishing, or the vendor dashboard.
OFF_SALE = "off-sale"
#  A card that IS on the other site, paired by title, but whose listing carries
#  no stock count at all - no inventory value to compare. It is not missing and
#  it is not a disagreement: there is nothing to write in either direction, and
#  saying "only on your website" would be a plain lie about a listing that
#  exists. It needs its own words because the fix is on that listing itself.
NO_COUNT = "no-count"

#  Words a vendor dashboard uses for a listing nobody can buy yet. Anything not
#  in here is treated as active, because a status the core does not recognise
#  must never make a live listing look broken.
_OFF_SALE_WORDS = {
    "draft", "hidden", "archived", "archive", "inactive", "unpublished",
    "private", "pending", "disabled", "deleted", "trash", "trashed",
    "sold out", "sold_out", "soldout", "out of stock", "out_of_stock",
    "outofstock", "off sale", "off_sale", "offsale", "not active",
    "expired", "paused", "on hold", "on_hold",
}
_DRAFT_WORDS = {"draft", "pending", "unpublished", "private"}


class StockError(Exception):
    """A stock list could not be read, with a sentence saying why."""

    def __init__(self, message, hint=""):
        super().__init__(message)
        self.message = str(message)
        self.hint = str(hint or "")


def woo_items(products):
    """``([item], skipped)`` for the products whose stock is actually counted.

    Only a product with stock management switched on has a number to compare.
    Variable products keep their count on each variation, and an unmanaged
    product means "always available", so neither belongs in a comparison - they
    are counted instead, so the panel can say how much was left out.
    """
    items, skipped = [], 0
    for product in products or []:
        if not isinstance(product, dict):
            continue
        managed = product.get("manage_stock")
        quantity = product.get("stock_quantity")
        if not managed or quantity is None or product.get("type") == "variable":
            skipped += 1
            continue
        try:
            qty = int(quantity)
        except (TypeError, ValueError):
            skipped += 1
            continue
        items.append({"name": str(product.get("name") or "").strip(),
                      "sku": str(product.get("sku") or "").strip(),
                      "qty": qty,
                      "id": product.get("id")})
    return items, skipped


#: How many product pages are asked for at once. The catalogue is read a
#: hundred cards a page, and a shop with 2,500 products used to wait for
#: twenty-five round trips one after another; four at a time is the same
#: request count in a quarter of the wall-clock time, and it is deliberately
#: modest so a small shared host is not hammered.
PAGE_WORKERS = 4


def _answer_parts(answer):
    """``(status, data, headers)`` from whatever the injected GET returned.

    The reader was written against ``(status, data)`` and every caller and test
    still returns that; a caller that can also give the response headers - which
    say how many pages there are - gets a progress bar that knows where it ends.
    """
    if isinstance(answer, tuple) and len(answer) >= 3:
        return answer[0], answer[1], answer[2] or {}
    if isinstance(answer, tuple) and len(answer) == 2:
        return answer[0], answer[1], {}
    return 0, answer, {}


def _total_pages(headers):
    """The page count WooCommerce states in its own headers, or ``None``."""
    for key, value in (headers or {}).items():
        if str(key).strip().lower().replace("_", "-") == "x-wp-totalpages":
            try:
                return max(1, int(str(value).strip()))
            except (TypeError, ValueError):
                return None
    return None


def read_woo_stock(fetch, base, key, secret, per_page=100, pages=40,
                   progress=None, workers=PAGE_WORKERS):
    """Every published product, page by page, through an injected GET.

    Pages are asked for a few at a time and reassembled in order, because the
    wait is almost entirely the round trip: a catalogue of 2,500 cards is
    twenty-five requests, and doing them one after another is what made a
    comparison feel broken. ``progress(page_done, total_pages, cards_read)`` is
    called after each page as it lands in order, so a caller can draw a bar;
    ``total_pages`` is ``None`` until (or unless) the site's own
    ``X-WP-TotalPages`` header says how many there are.
    """
    if not base:
        raise StockError("No website address is saved yet.",
                         "Set the WooCommerce site URL in User Settings.")
    if not (key and secret):
        raise StockError("No website API keys are saved yet.",
                         "Add the read-only key and secret to woo-keys.txt.")
    pages = max(1, int(pages))
    workers = max(1, int(workers or 1))
    products = []
    total = {"pages": None}

    def page_rows(page):
        #  Ordered by id so the pages are a stable window: they are read a few
        #  at a time now, and an unordered catalogue could hand the same card
        #  to two pages (or to none) while the reads overlap.
        params = {"per_page": per_page, "page": page, "status": "publish",
                  "orderby": "id", "order": "asc"}
        status, data, headers = _answer_parts(
            fetch(base, "/wp-json/wc/v3/products", params, key, secret))
        if status in (401, 403):
            raise StockError(
                "Your website refused the API keys (HTTP %s)." % status,
                "In WooCommerce > Settings > Advanced > REST API the key must "
                "have Read permission.")
        if status != 200:
            raise StockError(
                "Could not read your products (HTTP %s)." % status,
                str(data)[:200])
        if total["pages"] is None:
            total["pages"] = _total_pages(headers)
        return data if isinstance(data, list) else []

    def say(page, cards):
        if progress is None:
            return
        try:
            progress(page, total["pages"], cards)
        except Exception:
            #  A progress display must never be able to fail a read.
            pass

    page = 1
    rows = page_rows(1)
    products.extend(rows)
    say(1, len(products))
    short = len(rows) < per_page
    while not short and page < pages:
        batch = list(range(page + 1, min(pages, page + workers) + 1))
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = [(number, pool.submit(page_rows, number))
                       for number in batch]
            for number, future in futures:
                rows = future.result()
                products.extend(rows)
                page = number
                say(page, len(products))
                if len(rows) < per_page:
                    short = True
                    break
            if short:
                #  The short page is the end of the catalogue; the pages asked
                #  for beside it are not needed, and holding up the caller for
                #  them is the delay this is here to remove.
                for _number, future in futures:
                    future.cancel()
        if short:
            break
    return products


def status_of(item):
    """A listing's own state, as one of the words the panel can explain.

    Plugin 1.0.25 sends ``status`` for every listing, including the ones that
    are not on sale; the vendor spells them in its own way and in its own case,
    so the word is folded here once. A missing status is ``active`` - an older
    plugin only ever sent listings that were live.
    """
    raw = str((item or {}).get("status") or "").strip().lower()
    if not raw or raw == "unknown":
        return "active"
    folded = " ".join(raw.replace("-", " ").replace("_", " ").split())
    if folded in _DRAFT_WORDS or raw in _DRAFT_WORDS:
        return "draft"
    if folded in _OFF_SALE_WORDS or raw in _OFF_SALE_WORDS:
        return "off-sale"
    if folded.replace(" ", "_") in _OFF_SALE_WORDS:
        return "off-sale"
    return "active"


def is_on_sale(item):
    """Whether this listing can be bought - what a stock count is worth on."""
    return status_of(item) == "active"


#  The vendor's word for a listing that has been put away rather than merely
#  not published. Spelling variants are folded because the vendor spells it in
#  its own way and in its own case.
_ARCHIVED_WORDS = {"archived", "archive", "archiviert", "inactive archived"}
_ARCHIVED_STATES = {"archived", "archive"}


def is_archived(item):
    """Whether this listing has been archived, as opposed to merely off sale.

    Archived is the vendor's "put away" - the card is not coming back by
    itself. A draft or a hidden listing is a different story: someone is in
    the middle of something with it, or it is one publish away from selling.
    """
    raw = str((item or {}).get("status") or "").strip().lower()
    folded = " ".join(raw.replace("_", " ").replace("-", " ").split())
    return folded in _ARCHIVED_STATES or raw in _ARCHIVED_WORDS


def archived_sold_out(pairs):
    """Pairs where the other site archived the listing and the website is dry.

    There is nothing to do about that pair: the website has nothing to sell,
    the other site has put the card away on purpose, and the only way out is
    restocking the card, which is a different job in a different place. Listed
    with the other count disagreements, it reads as work that is not there.
    """
    found = []
    for row in pairs or []:
        other = row.get("other") or {}
        if not is_archived(other):
            continue
        if int(row.get("woo", {}).get("qty") or 0) <= 0:
            found.append(row)
    return found


def status_words(item):
    """The state in the words the person sees, or "" when it is on sale."""
    kind = status_of(item)
    if kind == "active":
        return ""
    raw = str((item or {}).get("status") or "").strip()
    if kind == "draft":
        return "a %s" % (raw or "draft")
    return raw or kind


#: Names a reader may use for the id its *write* endpoint takes, beside the
#: ``id`` it lists the row under. A catalogue's listings and its products are
#: not always the same object - one is what the shopfront shows, the other is
#: what an API patches - and a reader that reports both must not have the
#: second one dropped on the way to the writer.
_ID_NAME_SHAPES = ("productid", "listingid", "postid", "wpid", "itemid",
                   "productidentifier")


def _bare_name(key):
    """A key with everything but its letters and digits removed, lowercased."""
    return "".join(char for char in str(key).lower() if char.isalnum())


def extra_ids(row):
    """The listing's other identifiers, as ``{key: value}``.

    Anything a reader reports that names an id and is a plain value travels
    with the row; a title-shaped key never does, because a title is not an
    identifier and matching a write on one is how the wrong listing gets
    changed.
    """
    found = {}
    for key, value in (row or {}).items():
        shape = _bare_name(key)
        #  ``listing_product_id``, ``parent_product_id``: a reader that keeps
        #  its own spelling of the product key still means the product key.
        if shape not in _ID_NAME_SHAPES and not shape.endswith("productid"):
            continue
        if value in (None, "") or isinstance(value, (dict, list, tuple)):
            continue
        found[str(key)] = value
    return found


#: What a reader might call a listing's picture, in the order worth trying.
_PICTURE_KEYS = ("images", "photos", "pictures", "image", "photo", "picture",
                 "image_url", "imageUrl", "imageurl", "photo_url", "photoUrl",
                 "thumbnail", "thumbnail_url", "main_image", "mainImage",
                 "cover", "cover_url", "primary_image", "featured_image")


def listing_pictures(row):
    """The picture addresses a reader put on a listing, in a stable order.

    A reader is free to report nothing - the stock list has never needed
    pictures - so this is best-effort by design and never raises. Anything
    that is not a web address is dropped rather than carried into a download.
    """
    found = []
    for key in _PICTURE_KEYS:
        if key not in row:
            continue
        value = row.get(key)
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if isinstance(item, dict):
                item = (item.get("src") or item.get("url")
                        or item.get("href") or "")
            url = str(item or "").strip()
            if url.startswith(("http://", "https://")) and url not in found:
                found.append(url)
    return found


#: What a reader may report about a listing beyond its title, count and state.
#: They travel with the row because the creation step copies them onto the
#: product, and reading them here is what saves that step a page read.
_CARRIED_KEYS = ("price", "url", "description", "short_description",
                 "keywords", "tags", "condition", "grade", "year", "set",
                 "set_name", "card_number", "player", "brand", "manufacturer",
                 "language", "sport")


def plugin_items(payload):
    """The listings a plugin reported, in this module's one shape.

    The plugin writes ``{"items": [...]}``, each entry with a title, a SKU when
    it has one, an inventory number, and from 1.0.25 a status.

    Every listing the reader reports is kept, even one with no stock number:
    a listing with no number still exists, and dropping it is how a card that
    is really there comes back as "only on your website". Rows with no usable
    title are the only ones dropped, because nothing can be matched against
    them.
    """
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("listings") or []
    items = []
    for row in payload or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("title") or row.get("name") or "").strip()
        if not name:
            continue
        quantity = row.get("inventory")
        if quantity is None:
            quantity = row.get("quantity")
        entry = {"name": name,
                 "sku": str(row.get("sku") or "").strip(),
                 "qty": None,
                 "id": row.get("id"),
                 "status": str(row.get("status") or "").strip()}
        #  Anything else the reader reported travels with the row rather than
        #  being thrown away: the listing panel edits a price and opens a
        #  listing's page, and both need what only the vendor knows. A reader
        #  that reports the listing's own description and card details saves
        #  the creation step a page read, so those travel too.
        carried = {extra: row[extra] for extra in _CARRIED_KEYS
                   if row.get(extra) not in (None, "")}
        for key, value in row.items():
            #  A reader spells its keys its own way: ``cardNumber``,
            #  ``Card Number`` and ``card_number`` are one key, the same rule
            #  the listing ids already follow.
            shape = _bare_name(key)
            for extra in _CARRIED_KEYS:
                if extra in carried:
                    continue
                if _bare_name(extra) == shape and value not in (None, ""):
                    carried[extra] = value
        entry.update(carried)
        pictures = listing_pictures(row)
        if pictures:
            entry["images"] = pictures
        ids = extra_ids(row)
        if ids:
            entry["ids"] = ids
        if quantity is not None and str(quantity).strip() != "":
            try:
                entry["qty"] = int(quantity)
            except (TypeError, ValueError):
                #  A number the core cannot read is no better than no number,
                #  and dropping the row would turn a listing that exists into
                #  a card that "is not there".
                entry["qty"] = None
        items.append(entry)
    return items


def read_stock_file(path):
    """The plugin's answer, or ``None`` when there is nothing readable there."""
    import json
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict):
        #  "items": [] is an empty catalogue, not a missing answer - so the
        #  key is looked for rather than its truthiness.
        for key in ("items", "listings"):
            if key in payload:
                rows = payload[key]
                break
        else:
            return None
        if not isinstance(rows, list):
            return None
    elif isinstance(payload, list):
        rows = payload
    else:
        return None
    return plugin_items(rows)


#  The two sites do not spell a set the same way: the website says
#  "O-Pee-Chee", a listing often says "OPC"; the website says "Upper Deck",
#  a listing says "UD". Those are the same card, and the order panel's word
#  weighing cannot know that - so the spellings are folded into one before
#  anything is weighed. Without this, a catalogue of real listings matches
#  only the handful whose titles happen to be worded identically.
_ALIASES = (
    (re.compile(r"\bo[\s._-]?pee[\s._-]?chee\b", re.I), " opeechee "),
    (re.compile(r"\bopc\b", re.I), " opeechee "),
    (re.compile(r"\bupper[\s._-]?deck\b", re.I), " upperdeck "),
    (re.compile(r"\bud\b", re.I), " upperdeck "),
    (re.compile(r"\bparkie?s?\b", re.I), " parkhurst "),
    (re.compile(r"\bpro[\s._-]?set\b", re.I), " proset "),
    (re.compile(r"\btops\b", re.I), " topps "),
)


#  A card's condition, as the two sites write it. Two titles that otherwise
#  agree but name different conditions are two different items - the same card
#  number in a different grade sells for different money - so pairing them
#  would write one copy's count onto the other's listing.
_GRADES = (
    ("near mint-mint", "nm-mt"), ("nm-mt", "nm-mt"), ("nmmt", "nm-mt"),
    ("excellent-mint", "ex-mt"), ("ex-mt", "ex-mt"), ("exmt", "ex-mt"),
    ("very good-excellent", "vg-ex"), ("vg-ex", "vg-ex"), ("vgex", "vg-ex"),
    ("near mint", "nm"), ("nm", "nm"),
    ("excellent", "ex"), ("ex", "ex"),
    ("very good", "vg"), ("vg", "vg"),
    ("good", "gd"), ("gd", "gd"),
    ("fair", "fr"), ("fr", "fr"),
    ("poor", "pr"), ("pr", "pr"),
    ("mint", "mt"), ("mt", "mt"),
)
_GRADE_PATTERNS = [(re.compile(r"(?<![a-z])%s(?![a-z])" %
                               re.escape(word).replace(r"\ ", r"[\s-]+"), re.I),
                    label) for word, label in _GRADES]
def grade_of(name):
    """The condition a title names, as a short label, or "" when it names none.

    Deliberately literal: only conditions, never "creased" or "miscut" (those
    are notes about one copy, not a grade). A title with no grade is "". The
    caller only compares two grades when *both* are known, so a listing that
    never states one still pairs as it always did.
    """
    text = str(name or "")
    for pattern, label in _GRADE_PATTERNS:
        if pattern.search(text):
            #  The words only. "VG-EX 4" and "VG-EX" are the same condition
            #  written with and without its number, and refusing to pair those
            #  would invent a difference instead of finding one.
            return label
    return ""


def fold(name):
    """A title with the set names spelled one way, before weighing."""
    text = str(name or "")
    for pattern, replacement in _ALIASES:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s+", " ", text).strip()


_CARD_NUMBER = re.compile(r"#\s*(\d+)")


def card_number(name):
    """The card's number as both sites write it ("#25"), or "" when absent.

    A number is the closest thing to a shared key a card title has: the two
    sites word everything else differently, but #25 is #25. eBay puts it at the
    front of the title, the website puts it at the end, and neither is more
    right - so it is searched for rather than sliced off an end.
    """
    match = _CARD_NUMBER.search(str(name or ""))
    return match.group(1) if match else ""


def _digits(name):
    return {word for word in woo_orders.normalise(fold(name)).split()
            if word.isdigit()}


def _tokens(name):
    """The words a card is recognised by, for a cheap pre-sorting only."""
    return {word for word in woo_orders.normalise(fold(name)).split()
            if len(word) > 2 or word.isdigit()}


#  Scored candidates per website card. A catalogue has hundreds of products
#  and two thousand listings; without a cap the comparison becomes minute-long
#  arithmetic on the window's thread. The pre-filter below keeps only the
#  listings that could plausibly be the same card, so this cap is never
#  reached by a real catalogue - it is a guard, not a filter.
MAX_CANDIDATES = 25


def pair(woo, other, minimum=DEFAULT_MIN_SCORE):
    """Match the two lists card by card: ``(pairs, only_woo, only_other)``.

    The SKU decides when both sides carry one, because it is the only join that
    cannot be fooled by a title. Everything else is matched by title, best pair
    first, and each card is used once - a catalogue of identical titles must not
    produce one website card comparing against three listings.
    """
    pairs = []
    used_other = set()
    left = []

    by_sku = {}
    for index, item in enumerate(other):
        sku = item["sku"].lower()
        if sku:
            by_sku.setdefault(sku, index)

    for item in woo:
        index = by_sku.get(item["sku"].lower()) if item["sku"] else None
        if index is not None and index not in used_other:
            used_other.add(index)
            pairs.append({"woo": item, "other": other[index], "by": "sku"})
        else:
            left.append(item)

    #  Prepared once per card rather than once per pair: the inner loop is the
    #  whole catalogue, and normalising a title there is what makes a
    #  comparison take a minute instead of a second.
    prepared = [(index, _digits(row["name"]), _tokens(row["name"]))
                for index, row in enumerate(other)]

    scored = []
    for item in left:
        numbers = _digits(item["name"])
        words = _tokens(item["name"])
        candidates = []
        for index, digits, tokens in prepared:
            if index in used_other:
                continue
            #  Two cards whose numbers share nothing are two different cards,
            #  and a catalogue is mostly cards.
            if numbers and digits and not (numbers & digits):
                continue
            candidates.append((len(words & tokens), index))
        if len(candidates) > MAX_CANDIDATES:
            candidates.sort(reverse=True)
            candidates = candidates[:MAX_CANDIDATES]
        number = card_number(item["name"])
        for _shared, index in candidates:
            #  Both directions, best one wins. The website title carries the
            #  grade ("EX-MT 6") and the listing usually does not, so a title
            #  that only accounts for the other one way round is still the
            #  same card - what matters is that one side names everything the
            #  other side says.
            here, other_name = fold(item["name"]), fold(other[index]["name"])
            other_number = card_number(other[index]["name"])
            grade, other_grade = grade_of(item["name"]), grade_of(other[index]["name"])
            if grade and other_grade and grade != other_grade:
                #  Two copies of one card in different conditions are two
                #  items: pairing them would set one copy's count on the
                #  other's listing.
                continue
            if number and other_number and number != other_number:
                #  Two different card numbers are two different cards, however
                #  alike the rest of the words are - a set has one #25.
                continue
            forward, forward_numbers = woo_orders.analyse(here, other_name)
            backward, backward_numbers = woo_orders.analyse(other_name, here)
            value = max(forward, backward)
            numbers_ok = forward_numbers or backward_numbers
            shared_number = bool(number) and number == other_number
            if shared_number:
                #  The same card number in the same set is the strongest
                #  evidence after a SKU, and it rescues the pairs whose wording
                #  is furthest apart ("#75 Bert Campaneris 1967 O-Pee-Chee").
                value = min(1.0, value + 0.2)
                if value < minimum and value >= minimum - 0.15:
                    value = minimum
            if value < minimum:
                continue
            scored.append((value, numbers_ok, item, index,
                           "number" if shared_number else "title"))
    #  When two website products score identically - which is what a
    #  duplicate does - the one that can actually sell is the one that should
    #  hold the listing. Otherwise a sold-out copy quietly owns the only
    #  listing and the live product beside it is reported as missing.
    scored.sort(key=lambda row: (-row[0], not row[1],
                                 -int((row[2].get("qty") or 0) > 0)))

    used_woo = set()
    for value, _numbers_ok, item, index, how in scored:
        if index in used_other or id(item) in used_woo:
            continue
        used_other.add(index)
        used_woo.add(id(item))
        pairs.append({"woo": item, "other": other[index], "by": how})

    matched = {id(pair_row["woo"]) for pair_row in pairs}
    only_woo = [item for item in woo if id(item) not in matched]
    only_other = [item for index, item in enumerate(other)
                  if index not in used_other]
    return pairs, only_woo, only_other


def differences(pairs):
    """The pairs whose quantities disagree, worst gap first.

    Each row carries both sides' identity, not just their numbers, because the
    list is now the place the correction is made: the other site's listing id,
    SKU and title are what a write needs, and the website side has to be named
    in the confirmation.
    """
    rows = []
    for row in pairs or []:
        #  A pair whose other side counts nothing is not a disagreement, and
        #  turning "no number" into 0 would invent one - it gets its own row.
        if row["other"].get("qty") is None:
            continue
        woo_qty = int(row["woo"].get("qty") or 0)
        other_qty = int(row["other"].get("qty") or 0)
        if woo_qty == other_qty:
            continue
        rows.append(difference(row["woo"], row["other"], row.get("by", "title")))
    rows.sort(key=lambda row: (-abs(row["gap"]), row["card"].lower()))
    return rows


def difference(woo, other, by="title"):
    """One disagreement, with everything a correction needs to name it."""
    woo_qty = int(woo.get("qty") or 0)
    other_qty = int(other.get("qty") or 0)
    return {"card": woo.get("name") or other.get("name") or "",
            "woo": woo_qty, "other": other_qty, "gap": woo_qty - other_qty,
            "by": by, "kind": FIX,
            "woo_id": woo.get("id"), "woo_sku": woo.get("sku") or "",
            "other_id": other.get("id"), "other_name": other.get("name") or "",
            "other_sku": other.get("sku") or ""}


def listed_only_woo(items):
    """Website cards that are worth showing as *not on the other site*.

    A card at zero cannot be listed anywhere - the other site would refuse it
    as out of stock, and the website has nothing to sell - so "it is not on
    CanadianShopper" is not a job, it is the natural state of a sold-out card.
    Showing it made the list look like work; the count is kept so the panel can
    still say how many were left out.
    """
    return [item for item in items or [] if int(item.get("qty") or 0) > 0]


def sold_out_only_woo(items):
    """The website cards at zero that the other site does not list either."""
    return [item for item in items or [] if int(item.get("qty") or 0) <= 0]


def card_key(name):
    """A card's identity for the ignore list: the words, in a fixed order.

    The two sites put the same card's words in a different order ("#75 Bert
    Campaneris 1967 O-Pee-Chee" against "1967 O-Pee-Chee Bert Campaneris
    #75"), so sorting the words makes one key out of both. It is deliberately
    strict about everything else: an ignored card whose title is later edited
    comes back, which is the right way round - a card nobody asked to hide
    should not be hidden.
    """
    words = set(woo_orders.normalise(fold(name)).split())
    return " ".join(sorted(words))


def action_list(pairs, only_woo, only_other, ignored=(), other_label=""):
    """Everything the panel can act on, as one list of rows.

    Ignored cards are left out of all three kinds: the point of ignoring a card
    that only exists on one side is to stop being asked about it.
    """
    hidden = set(ignored or ())
    #  A pair whose other-site listing is not on sale is not a count
    #  disagreement: setting the count would leave the card unbuyable, and
    #  stock.set refuses it by design. It becomes its own row instead.
    #  A pair where the other site archived the listing and the website has
    #  nothing left is not a job: it needs a restock, not a count or a publish.
    #  The pairs are counted instead, so the panel can say how many there are.
    dry = {id(row) for row in archived_sold_out(pairs)}
    rows = []
    live = []
    for row in pairs or []:
        if id(row) in dry:
            continue
        if is_on_sale(row.get("other")) and row["other"].get("qty") is not None:
            live.append(row)
            continue
        other = row["other"]
        if is_on_sale(other):
            #  On sale, paired, but counting nothing: there is no number to
            #  compare or write, so the listing is named for what it is.
            rows.append({"card": row["woo"].get("name") or other.get("name") or "",
                         "woo": int(row["woo"].get("qty") or 0),
                         "other": None, "gap": 0, "by": row.get("by", "title"),
                         "kind": NO_COUNT, "status": status_of(other),
                         "state": "",
                         "woo_id": row["woo"].get("id"),
                         "woo_sku": row["woo"].get("sku") or "",
                         "other_id": other.get("id"),
                         "other_name": other.get("name") or "",
                         "other_sku": other.get("sku") or ""})
            continue
        rows.append({"card": row["woo"].get("name") or other.get("name") or "",
                     "woo": int(row["woo"].get("qty") or 0),
                     "other": (None if other.get("qty") is None
                               else int(other.get("qty") or 0)),
                     "gap": 0, "by": row.get("by", "title"),
                     "kind": OFF_SALE, "status": status_of(other),
                     "state": status_words(other),
                     "woo_id": row["woo"].get("id"),
                     "woo_sku": row["woo"].get("sku") or "",
                     "other_id": other.get("id"),
                     "other_name": other.get("name") or "",
                     "other_sku": other.get("sku") or ""})
    rows += differences(live)
    for item in listed_only_woo(only_woo):
        rows.append({"card": item.get("name") or "", "woo": int(item.get("qty") or 0),
                     "other": None, "gap": int(item.get("qty") or 0),
                     "by": "", "kind": ONLY_WOO, "woo_id": item.get("id"),
                     "woo_sku": item.get("sku") or "", "other_id": None,
                     "other_name": "", "other_sku": ""})
    for item in only_other or []:
        #  A listing that exists but is not on sale is not "only on the other
        #  site" - it is on both, and the fix is to put it back on sale.
        rows.append({"card": item.get("name") or "", "woo": None,
                     "other": int(item.get("qty") or 0),
                     "gap": -int(item.get("qty") or 0), "by": "",
                     "kind": ONLY_OTHER, "woo_id": None, "woo_sku": "",
                     "other_id": item.get("id"),
                     "other_name": item.get("name") or "",
                     "other_sku": item.get("sku") or "",
                     "status": status_of(item), "state": status_words(item)})
    visible = [row for row in rows if card_key(row["card"]) not in hidden]
    #  Fixable first, then the cards that exist but cannot be bought, then the
    #  ones that are missing entirely: the first two have a fix, the last one
    #  is usually a listing that needs creating. The panel can re-order the
    #  list with sort_rows(); this is the order it opens in.
    return sort_rows(visible, DEFAULT_SORT)


#  The orders the list can be read in. ``attention`` is what the list has
#  always used - the fixable rows first, worst gap first - so choosing nothing
#  changes nothing; the others are for finding one card in a list of two
#  hundred, which is the other thing a person does with it.
SORTS = (("attention", "What needs attention first"),
         ("name", "Card name (A-Z)"),
         ("name-desc", "Card name (Z-A)"),
         ("gap", "Biggest difference first"),
         ("woo", "Most on the website first"),
         ("other", "Most on the other site first"))
DEFAULT_SORT = "attention"
_SORT_ORDER = {FIX: 0, OFF_SALE: 1, NO_COUNT: 2, ONLY_OTHER: 3, ONLY_WOO: 4}


def sort_labels():
    """The chooser's words, in order."""
    return [label for _key, label in SORTS]


def sort_key(label=None):
    """The sort a chooser's label means; anything unknown is the default."""
    for key, text in SORTS:
        if text == label:
            return key
    return DEFAULT_SORT


def sort_label(key=None):
    """The chooser's words for a sort key."""
    for wanted, text in SORTS:
        if wanted == key:
            return text
    return SORTS[0][1]


def _count(value):
    """A stock number for sorting, where "not listed at all" is below zero.

    A card that is not on the other site is not a card with no stock - it is a
    card with nothing there at all - so it belongs at the back of "most stock
    first" rather than mixed in with the zeros.
    """
    if value is None:
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def sort_rows(rows, how=DEFAULT_SORT):
    """The same rows, in the order asked for. Never drops one."""
    rows = list(rows or [])
    if how == "name":
        return sorted(rows, key=lambda row: (row.get("card") or "").lower())
    if how == "name-desc":
        return sorted(rows, key=lambda row: (row.get("card") or "").lower(),
                      reverse=True)
    if how == "gap":
        return sorted(rows, key=lambda row: (-abs(int(row.get("gap") or 0)),
                                             (row.get("card") or "").lower()))
    if how == "woo":
        return sorted(rows, key=lambda row: (-_count(row.get("woo")),
                                             (row.get("card") or "").lower()))
    if how == "other":
        return sorted(rows, key=lambda row: (-_count(row.get("other")),
                                             (row.get("card") or "").lower()))
    return sorted(rows, key=lambda row: (_SORT_ORDER.get(row.get("kind"), 9),
                                         -abs(int(row.get("gap") or 0)),
                                         (row.get("card") or "").lower()))


def off_sale_rows(rows):
    """The rows whose other-site listing exists but is not on sale."""
    return [row for row in rows or [] if row.get("kind") == OFF_SALE]


def no_count_rows(rows):
    """The rows whose other-site listing carries no stock count at all."""
    return [row for row in rows or [] if row.get("kind") == NO_COUNT]


def closest(items, name):
    """The other site's nearest title to ``name``, as ``(item, score)``.

    Only a diagnostic, never a pair: when a card comes back one-sided, the
    question that decides what to do is whether the listing is missing or
    merely worded differently. This answers it with the same weighing the
    pairing uses, so "nothing here comes close" is a fact rather than a guess.
    """
    here = fold(name)
    number = card_number(name)
    digits = _digits(name)
    best, best_score = None, 0.0
    for item in items or []:
        other = fold(item.get("name") or "")
        if not other:
            continue
        #  The same rule the pairing uses: two different card numbers are two
        #  different cards, however alike the rest of the words are. Without
        #  it every title in a set looks like a near miss.
        if number and card_number(item.get("name") or "") not in ("", number):
            continue
        other_digits = _digits(item.get("name") or "")
        if digits and other_digits and not (digits & other_digits):
            continue
        forward, _n1 = woo_orders.analyse(here, other)
        backward, _n2 = woo_orders.analyse(other, here)
        value = max(forward, backward)
        if value > best_score:
            best, best_score = item, value
    return best, round(best_score, 3)


def owner_of(pairs, item):
    """The website product a listing is already compared with, or ``None``."""
    if item is None:
        return None
    for row in pairs or []:
        if row.get("other") is item:
            return row.get("woo")
    return None


def same_words(a, b):
    """Whether two titles are the same card's words, in any order and case."""
    return bool(str(a or "").strip()) and card_key(a) == card_key(b)


def status_tally(items):
    """How many listings the reader reported in each state, in its own words.

    Printed after the read so the person can check it against the dashboard:
    if a listing was moved there and this still says "archived", the reading
    is stale and that is the plugin's page, not the comparison's.
    """
    counts, spelled = {}, {}
    for item in items or []:
        kind = status_of(item)
        if kind == "active":
            word = "on sale"
        else:
            word = (str((item or {}).get("status") or "").strip()
                    or "not on sale")
        #  The same word in two cases is one state: the vendor's own spelling
        #  is kept for the line, but it must not be counted twice.
        key = word.lower()
        counts[key] = counts.get(key, 0) + 1
        spelled.setdefault(key, word)
    return {spelled[key]: counts[key] for key in counts}


def tally_line(items):
    """One sentence saying what states the reader reported."""
    tally = status_tally(items)
    if not tally:
        return ""
    on_sale = tally.pop("on sale", 0)
    parts = ["%d on sale" % on_sale]
    for word in sorted(tally):
        parts.append("%d %s" % (tally[word], word))
    return "%d listing(s): %s" % (sum(tally.values()) + on_sale,
                                  ", ".join(parts))


def out_of_stock_rows(rows):
    """Rows the other site holds at zero - the listing exists, unsold stock
    is what it has none of."""
    return [row for row in rows or []
            if row.get("kind") == FIX and int(row.get("other") or 0) == 0]


def held_elsewhere(pairs, only_woo, other_items, minimum=0.45):
    """One-sided cards whose card number is listed under another product.

    A card cannot be matched twice, so a website product whose listing is
    already held by a different product with a similar title is not missing
    from the other site - the listing is there, under something else. Whether
    that means "duplicate" or "another grade" is decided by the words, and
    both are reported, because only the person knows which copy is which.
    """
    found = []
    for item in only_woo or []:
        listing, score = closest(other_items, item.get("name") or "")
        if listing is None or score < minimum:
            continue
        owner = owner_of(pairs, listing)
        if owner is None:
            continue
        found.append({
            "card": item.get("name") or "",
            "listing": listing.get("name") or "",
            "owner": owner.get("name") or "",
            "score": score,
            "same": same_words(item.get("name"), owner.get("name")),
        })
    return found


def no_count(items):
    """How many of these listings carry no stock number."""
    return len([item for item in items or [] if item.get("qty") is None])


def draft_rows(rows):
    """The off-sale rows that are drafts - publishing can activate those."""
    return [row for row in rows or []
            if row.get("kind") == OFF_SALE and row.get("status") == "draft"]


def hidden_count(pairs, only_woo, only_other, ignored):
    """How many rows the ignore list is keeping off the screen."""
    if not ignored:
        return 0
    #  Counted by asking the same function twice, so the number can never
    #  disagree with what the list actually shows - a pair whose listing is not
    #  on sale is one row there whatever its count is, and adding the kinds up
    #  by hand got that wrong.
    return (len(action_list(pairs, only_woo, only_other, ())) -
            len(action_list(pairs, only_woo, only_other, ignored)))


#  The publisher states its own tally in the console - "Drafts found: 0 |
#  ready: 0 | blocked: 0" - and that sentence is the one fact the core can act
#  on. Its report file is the plugin's format, not the core's, so an empty
#  file, a header-only file and a file of preamble lines all have to mean the
#  same thing: not a single draft.
_DRAFT_TALLY = re.compile(r"drafts?\s*found\s*[:=\-]?\s*(\d+)", re.I)
_SCANNED = re.compile(r"scanned\s+(\d+)\s+drafts?", re.I)


def draft_count(text):
    """How many drafts a publisher's own output says it found, or ``None``.

    ``None`` means it did not say, which is not zero: a caller that cannot
    read the tally must not tell someone their drafts do not exist.
    """
    said = str(text or "")
    for pattern in (_DRAFT_TALLY, _SCANNED):
        found = pattern.search(said)
        if found:
            try:
                return int(found.group(1))
            except (TypeError, ValueError):
                return None
    return None


def report_rows(path):
    """How many rows of detail a CSV report holds, the header excluded.

    ``None`` means the file could not be read, which is not the same as an
    empty report: a report nobody can read must not be described as "no
    drafts". A file that holds only a header - or nothing at all, which is what
    a publisher that found no drafts leaves behind - is a real, countable
    zero.
    """
    try:
        text = Path(str(path)).read_text(encoding="utf-8-sig",
                                         errors="replace")
    except (OSError, TypeError, ValueError):
        return None
    rows = 0
    seen_header = False
    for line in text.splitlines():
        if not line.strip():
            continue
        if not seen_header:
            #  The first non-blank line is the header a report always writes.
            seen_header = True
            continue
        rows += 1
    return rows


def plan_set(rows):
    """What to write so the other site matches the website, card by card.

    Only rows where both sides exist can be written: a card that is missing
    from the other site has nothing to set. Every entry names the listing three
    ways, because the plugin may know it by id, by SKU or only by its title.
    """
    items = []
    for row in rows or []:
        if row.get("kind") != FIX:
            continue
        if int(row.get("woo") or 0) == int(row.get("other") or 0):
            continue
        items.append({"id": row.get("other_id"), "sku": row.get("other_sku") or "",
                      "title": row.get("other_name") or row.get("card") or "",
                      "card": row.get("card") or "",
                      "from": int(row.get("other") or 0),
                      "to": int(row.get("woo") or 0)})
    return items


def _first(entry, *keys):
    """The first non-empty value under any of these names.

    The plugin's result file is a contract, not a Python object the core
    controls: a key renamed between plugin versions must not turn a written
    count into a silent unknown, and an old name must still be understood.
    """
    for key in keys:
        value = (entry or {}).get(key)
        if value not in (None, ""):
            return value
    return ""


def id_key(value):
    """One identifier as the string another identifier is compared with.

    The same id arrives spelled differently depending on who is holding it: a
    reader that reports ``"product_id": "4321"`` (plugin 1.0.35 does, because a
    JSON number and a string are different things in some vendor APIs), a
    result file that answers with the number ``4321``, a form that padded it
    with a space, and a source that wrote it as ``4321.0``. They are one id, and
    comparing them as raw strings is how a write that happened is reported as
    *unknown* - the panel then leaves the row on the screen and the person
    writes it a second time.

    Only a plain whole number is folded: an opaque id such as
    ``14effcaceb8a4b66`` is kept exactly as it was given, case and all, because
    nothing here knows whether a vendor's ids are case-sensitive. So is a
    number-shaped code with a leading zero (``"0012"``): it may be somebody's
    own identifier, and two different listings are worse than one *unknown*.
    """
    if value is None or isinstance(value, (dict, list, tuple, bool)):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if number != number or number in (float("inf"), float("-inf")):
        return text
    if number != int(number):
        return text
    whole = str(int(number))
    #  "0012" is somebody's code, not twelve; a negative id is not an id.
    if text.lstrip("-").startswith("0") and len(text.lstrip("-")) > 1:
        return text
    return whole


def _matches(row, entry):
    """Whether a result entry is about this plan row.

    The id decides whenever both sides have one: an entry that names the same
    card but a different listing is a different listing, and letting a title
    override that would mark one row written because another one was - the
    cards in a catalogue are exactly similar enough for that to happen. SKU and
    title are the fallback only when one side has no id at all, which is what a
    plugin that does not report ids, or a plan built without them, looks like.
    """
    entry_id = id_key(_first(entry, "id", "product_id", "listing_id",
                             "productId", "listingId"))
    #  Every id the row carries counts, not only the one it is listed under:
    #  a writer that answers with the product id of a listing it knows by its
    #  page id has still written *that* listing, and calling it unknown would
    #  report a change that happened as a change that did not.
    row_ids = {id_key(row.get("id"))}
    row_ids |= {id_key(value) for value in (row.get("ids") or {}).values()}
    #  A plan carries those ids at its top level (``product_id`` beside ``id``)
    #  because that is what the writer is handed, so both shapes are read.
    for key, value in (row or {}).items():
        if _bare_name(key) in _ID_NAME_SHAPES and not isinstance(
                value, (dict, list, tuple)):
            row_ids.add(id_key(value))
    row_ids.discard("")
    if entry_id and row_ids:
        return entry_id in row_ids
    entry_sku = str(_first(entry, "sku") or "").strip().lower()
    row_sku = str(row.get("sku") or "").strip().lower()
    if entry_sku and row_sku:
        return entry_sku == row_sku
    entry_title = str(_first(entry, "title", "card", "name") or "")
    if entry_title:
        return card_key(entry_title) == card_key(row.get("title") or
                                                 row.get("card") or "")
    return False


def plugin_write_report(plan, answer):
    """What the plugin's ``stock.set`` result says about each planned card.

    ``{"changed": [...], "failed": [{"card", "why"}], "unknown": [...]}``.
    A card the result does not mention is *unknown*, never assumed written: a
    count that was not confirmed is exactly what this panel exists to catch,
    and leaving the row on the screen costs one more click while taking it off
    costs a wrong number on the shop.
    """
    plan = list(plan or [])
    if not isinstance(answer, dict):
        answer = {}
    updated = [entry for entry in (answer.get("updated") or [])
               if isinstance(entry, dict)]
    failed = [entry for entry in (answer.get("failed") or [])
              if isinstance(entry, dict)]
    changed, could_not, unknown = [], [], []
    for row in plan:
        failure = next((entry for entry in failed if _matches(row, entry)), None)
        success = next((entry for entry in updated if _matches(row, entry)), None)
        if failure is not None:
            could_not.append({
                "card": row.get("title") or row.get("card") or "",
                "why": str(_first(failure, "why", "reason", "error", "message")
                           or "the plugin gave no reason"),
            })
        elif success is not None:
            changed.append(row)
        else:
            unknown.append(row)
    return {"changed": changed, "failed": could_not, "unknown": unknown}


def describe_plan(plan, other_label="CanadianShopper"):
    """The confirmation: exactly what would be written, one line per card.

    Every line names the side the number comes from, because the same dialog
    exists for the other direction and the direction is the one thing that
    must never be guessed at.
    """
    lines = []
    for item in plan or []:
        lines.append("  %s\n      %s %d -> %d   (from your website)" % (
            item["card"][:90], other_label, item["from"], item["to"]))
    return lines


def plan_summary(plan, other_label="CanadianShopper"):
    """One sentence saying how much the plan would change."""
    count = len(plan or [])
    if not count:
        return "Nothing to change."
    return "%d card%s on %s would be set to the website's count." % (
        count, "" if count == 1 else "s", other_label)


def label_action(row, other_label="CanadianShopper", mode="count", number=None,
                 width=1):
    """One row of the action list, as it is shown - numbered, when asked.

    The number is the row's place in the list the panel is showing, so the
    same card can be pointed at after a sort or while working down the list.
    """
    text = _action_text(row, other_label, mode)
    if number is None:
        return text
    return "%*d. %s" % (max(1, int(width)), int(number), text)


def _action_text(row, other_label="CanadianShopper", mode="count"):
    """The words of one row, without its number."""
    if row.get("kind") == ONLY_WOO:
        return "%s  -  website %s only, not on %s" % (
            row["card"], row["woo"], other_label)
    if row.get("kind") == OFF_SALE:
        return "%s  -  on %s but not on sale (%s)  /  website %s" % (
            row["card"], other_label, row.get("state") or "not on sale",
            row.get("woo"))
    if row.get("kind") == NO_COUNT:
        return "%s  -  on %s but no stock count there  /  website %s" % (
            row["card"], other_label, row["woo"])
    if row.get("kind") == ONLY_OTHER:
        return "%s  -  %s only, not on your website" % (row["card"], other_label)
    if mode == "listed":
        return label(row, other_label, mode)
    return "%s  -  website %d  /  %s %d" % (
        row["card"], row["woo"], other_label, row["other"])


def load_ignored(path):
    """The dismissed cards, as ``[{"key","title"}]``; unreadable hides nothing."""
    import json
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("cards") or []
    entries = []
    for entry in data or []:
        if isinstance(entry, dict):
            key = str(entry.get("key") or "").strip()
            title = str(entry.get("title") or "").strip()
            why = str(entry.get("why") or "").strip()
        else:
            key, title, why = str(entry).strip(), "", ""
        if key:
            entries.append({"key": key, "title": title, "why": why})
    return entries


def ignored_keys(entries):
    """Just the keys, for filtering a comparison."""
    return [entry.get("key") for entry in entries or [] if entry.get("key")]


def save_ignored(path, entries):
    """Write the dismissed cards. ``entries`` is ``[{"key","title"}]``."""
    import json
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"cards": list(entries or [])}, indent=1,
                                   ensure_ascii=False), encoding="utf-8")
    except OSError:
        return False
    return True


def remember_ignored(entries, rows):
    """The ignore entries plus these rows, without duplicates."""
    known = {entry.get("key") for entry in entries or []}
    out = list(entries or [])
    for row in rows or []:
        #  Rows from the list carry "card"; a raw catalogue item carries "name".
        title = row.get("card") or row.get("name") or ""
        key = card_key(title)
        if not key or key in known:
            continue
        known.add(key)
        out.append({"key": key, "title": title,
                    "why": row.get("kind") or ""})
    return out


def summary(rows, pairs, only_woo, only_other, other_label="CanadianShopper"):
    """One sentence a person can act on."""
    if not pairs:
        return "Nothing matched on both sites, so there is nothing to compare."
    if not rows:
        return "All %d matched cards agree." % len(pairs)
    line = "%d of %d matched cards disagree." % (len(rows), len(pairs))
    left_out = []
    shown_only_woo = listed_only_woo(only_woo)
    if shown_only_woo:
        left_out.append("%d only on your website" % len(shown_only_woo))
    if only_other:
        left_out.append("%d only on %s" % (len(only_other), other_label))
    if left_out:
        line += " Not compared: " + ", ".join(left_out) + "."
    return line


def archived_note(pairs, other_label="CanadianShopper"):
    """The sentence for the archived pairs that were left off the list."""
    dry = archived_sold_out(pairs)
    if not dry:
        return ""
    return ("%d archived on %s with nothing on your website, so not shown." %
            (len(dry), other_label))


def sold_out_note(only_woo, other_label="CanadianShopper"):
    """The sentence for the cards left out because there is nothing to buy.

    Named rather than silently dropped: a card at zero that the other site does
    not list either has nothing to fix, and saying so is the difference between
    a list that was cleaned up and a card that went missing.
    """
    sold_out = sold_out_only_woo(only_woo)
    if not sold_out:
        return ""
    return ("%d card%s at zero on your website and not on %s, so not shown." %
            (len(sold_out), "" if len(sold_out) == 1 else "s", other_label))


def describe(rows, limit=40, other_label="CanadianShopper", mode="count"):
    """Console lines for the disagreements.

    ``mode`` is how the other site expresses stock: "count" for a site that
    keeps a number (eBay, CanadianShopper), "listed" for one that only knows
    whether the card is being offered (Facebook).
    """
    lines = []
    for row in rows:
        gap = "" if row["gap"] == 0 else "  (%+d)" % row["gap"]
        if mode == "listed":
            state = "listed" if row["other"] else "not listed"
            lines.append("  %-52s website %-4d %s %s" % (
                row["card"][:52], row["woo"], other_label, state))
        else:
            lines.append("  %-52s website %-4d %s %-4d%s" % (
                row["card"][:52], row["woo"], other_label, row["other"], gap))
    if len(lines) > limit:
        hidden = len(lines) - limit
        lines = lines[:limit] + ["  ... and %d more." % hidden]
    return lines


def label(row, other_label="CanadianShopper", mode="count"):
    """One disagreement as it appears in the panel list."""
    if mode == "listed":
        return "%s  -  website %d  /  %s %s" % (
            row["card"], row["woo"], other_label,
            "listed" if row["other"] else "not listed")
    return "%s  -  website %d  /  %s %d" % (
        row["card"], row["woo"], other_label, row["other"])
