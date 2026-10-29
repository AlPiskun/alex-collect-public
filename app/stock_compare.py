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


def read_woo_stock(fetch, base, key, secret, per_page=100, pages=40):
    """Every published product, page by page, through an injected GET."""
    if not base:
        raise StockError("No website address is saved yet.",
                         "Set the WooCommerce site URL in User Settings.")
    if not (key and secret):
        raise StockError("No website API keys are saved yet.",
                         "Add the read-only key and secret to woo-keys.txt.")
    products = []
    for page in range(1, max(1, pages) + 1):
        params = {"per_page": per_page, "page": page, "status": "publish"}
        status, data = fetch(base, "/wp-json/wc/v3/products", params, key, secret)
        if status in (401, 403):
            raise StockError(
                "Your website refused the API keys (HTTP %s)." % status,
                "In WooCommerce > Settings > Advanced > REST API the key must "
                "have Read permission.")
        if status != 200:
            raise StockError(
                "Could not read your products (HTTP %s)." % status,
                str(data)[:200])
        rows = data if isinstance(data, list) else []
        products.extend(rows)
        if len(rows) < per_page:
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


def status_words(item):
    """The state in the words the person sees, or "" when it is on sale."""
    kind = status_of(item)
    if kind == "active":
        return ""
    raw = str((item or {}).get("status") or "").strip()
    if kind == "draft":
        return "a %s" % (raw or "draft")
    return raw or kind


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
    scored.sort(key=lambda row: (-row[0], not row[1]))

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
    rows = []
    live = []
    for row in pairs or []:
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
    for item in only_woo or []:
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
    #  is usually a listing that needs creating.
    order = {FIX: 0, OFF_SALE: 1, NO_COUNT: 2, ONLY_OTHER: 3, ONLY_WOO: 4}
    visible.sort(key=lambda row: (order.get(row["kind"], 9),
                                  -abs(row["gap"]), row["card"].lower()))
    return visible


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


def _matches(row, entry):
    """Whether a result entry is about this plan row.

    The id decides whenever both sides have one: an entry that names the same
    card but a different listing is a different listing, and letting a title
    override that would mark one row written because another one was - the
    cards in a catalogue are exactly similar enough for that to happen. SKU and
    title are the fallback only when one side has no id at all, which is what a
    plugin that does not report ids, or a plan built without them, looks like.
    """
    entry_id = str(_first(entry, "id", "product_id", "listing_id") or "")
    row_id = str(row.get("id") or "")
    if entry_id and row_id:
        return entry_id == row_id
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


def label_action(row, other_label="CanadianShopper", mode="count"):
    """One row of the action list, as it is shown."""
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
    if only_woo:
        left_out.append("%d only on your website" % len(only_woo))
    if only_other:
        left_out.append("%d only on %s" % (len(only_other), other_label))
    if left_out:
        line += " Not compared: " + ", ".join(left_out) + "."
    return line


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
