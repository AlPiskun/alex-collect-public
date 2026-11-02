"""Finding one CanadianShopper listing, and changing it.

The comparison panel answers "where do the two sites disagree". This module
answers the other question: *I know the card - where is it on the other site,
and can I change it?* A card can be worded differently there, can have been
archived months ago, can be sitting at a price from last year; the vendor
dashboard is the only place all of that is visible, and going there for one
listing at a time is the work this panel is meant to remove.

Everything here is a pure function of the listing rows the plugin's stock
reader returns, so it can be tested without a network, a browser or a vendor
account:

  * a **fuzzy search** over the catalogue - a card name typed the way a person
    remembers it, not the way the listing spells it;
  * a **state filter** so the archived listings can be worked through on their
    own;
  * an **edit plan**: the fields that changed, and nothing else, because a
    write that carries every field is a write that can silently revert one;
  * the **confirmation lines** and the reading of the plugin's answer.

The write itself belongs to the plugin (`marketplace.listing_update`); nothing
in this module touches a site.
"""

import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import stock_compare
import woo_orders
from plugin_manager import version_at_least

#: The states the chooser offers. The keys are the words the core already uses
#: for a listing's state, so the filter and the comparison agree.
STATES = (("any", "Any state"),
          ("active", "On sale"),
          ("archived", "Archived"),
          ("draft", "Drafts"),
          ("off-sale", "Off sale (not on sale)"))

#: Below this, a search result is noise: two card titles from one set share
#: most of their words, and a list of forty near-misses is not a search.
SEARCH_MINIMUM = 0.34

#: How many matches the search shows. A card catalogue is thousands of rows;
#: a list longer than this is a spreadsheet, not an answer.
SEARCH_LIMIT = 200


def state_labels():
    """The chooser's words, in order."""
    return [label for _key, label in STATES]


def state_key(label):
    """The state a chooser label means; anything unknown is "any"."""
    for key, text in STATES:
        if text == label:
            return key
    return "any"


def state_label(key):
    """The chooser's words for a state key."""
    for wanted, text in STATES:
        if wanted == key:
            return text
    return STATES[0][1]


def has_state(item, state="any"):
    """Whether a listing is in the state the chooser is asking for."""
    if not state or state == "any":
        return True
    kind = stock_compare.status_of(item)
    if state == "active":
        return kind == "active"
    if state == "archived":
        return stock_compare.is_archived(item)
    if state == "off-sale":
        return kind != "active"
    #  "draft" is the vendor's own word, folded: a listing that is one publish
    #  away from selling is the one this filter is for.
    return kind == "draft"


def price_text(item):
    """A listing's price as it should read, or "" when it does not say."""
    raw = (item or {}).get("price")
    if raw is None or str(raw).strip() == "":
        return ""
    return str(raw).strip()


def price_number(item):
    """A listing's price as a plain number, or ``None``.

    The plugin may report ``"8.50"``, ``8.5`` or ``"CA$8.50"``; all three are
    the same money, and the plan needs the number.
    """
    text = price_text(item).replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def stock_text(item):
    """A listing's stock as it should read, or "" when it has no number."""
    qty = (item or {}).get("qty")
    if qty is None:
        return ""
    return "%d in stock" % int(qty)


def label(item, number=None, width=1):
    """One row of the list: its number, the card, state, stock, price, SKU.

    ``number`` is the row's place in the list as it is shown, so a search can
    be talked about - "the third one" - and a re-sorted or re-filtered list
    still counts from one.
    """
    parts = [str((item or {}).get("name") or "")]
    state = stock_compare.status_words(item)
    parts.append(state or "on sale")
    stock = stock_text(item)
    if stock:
        parts.append(stock)
    price = price_text(item)
    if price:
        parts.append(price)
    sku = str((item or {}).get("sku") or "").strip()
    if sku:
        parts.append(sku)
    text = "  -  ".join(part for part in parts if part)
    if number is None:
        return text
    return "%*d. %s" % (max(1, int(width)), int(number), text)


def score(query, item):
    """How well one listing answers what was typed, from 0 to 1.

    The weighing is the order panel's own - the same one that matches a
    customer's line to a product - because it is the one part of this app that
    has been tuned against real card names. A SKU or an id typed exactly is a
    hit however the title is worded, since that is what those fields are for.
    """
    query = str(query or "").strip()
    if not query:
        return 0.0
    name = str((item or {}).get("name") or "")
    sku = str((item or {}).get("sku") or "")
    listing_id = str((item or {}).get("id") or "")
    folded = query.lower()
    if folded and folded == sku.lower():
        return 1.0
    if folded and folded == listing_id.lower():
        return 1.0
    value = woo_orders.score(query, name)
    #  A typed word that appears in the title is always worth showing, even
    #  when the rest of the title makes the overall score low: someone typing
    #  "tkaczuk" means the Tkaczuk cards, and a title with three more names in
    #  it is still one of them.
    words = [word for word in folded.split() if len(word) > 2]
    haystack = ("%s %s" % (name, sku)).lower()
    if words and any(word in haystack for word in words):
        value = max(value, 0.55)
    return value


def search(items, query="", state="any", limit=SEARCH_LIMIT):
    """The listings answering ``query``, best first; everything when empty.

    An empty box is not an empty list: it means "show me that state", which is
    how the archived listings are worked through.
    """
    rows = [item for item in items or [] if has_state(item, state)]
    query = str(query or "").strip()
    if not query:
        rows.sort(key=lambda item: (str(item.get("name") or "").lower(),
                                    str(item.get("sku") or "")))
        return rows[:max(1, int(limit))]
    scored = [(score(query, item), item) for item in rows]
    scored = [pair for pair in scored if pair[0] >= SEARCH_MINIMUM]
    scored.sort(key=lambda pair: (-pair[0],
                                  str(pair[1].get("name") or "").lower()))
    return [item for _value, item in scored][:max(1, int(limit))]


def current(item):
    """The editable fields of a listing, as the plan names them."""
    #  The title as it reads, with runs of spaces folded: a rename that only
    #  collapses a double space is not a change worth writing, and comparing
    #  the raw strings would send it every time.
    return {"title": " ".join(str((item or {}).get("name") or "").split()),
            "price": price_number(item),
            "inventory": (None if (item or {}).get("qty") is None
                          else int((item or {}).get("qty"))),
            "status": ("active" if stock_compare.status_of(item) == "active"
                       else ("archived"
                             if stock_compare.is_archived(item) else "off")),
            }


#: The two states a listing can be moved to. A listing can be in a third - a
#: draft, a hidden one - and that word is offered first so the chooser opens on
#: the truth instead of on a state the listing is not in.
EDIT_STATES = (("active", "On sale"), ("archived", "Archived"))

#: The keys a plugin may report a listing's own page under. ``url`` is the one
#: the interface documents; the rest cost nothing and turn "no link for that
#: listing" into a working button for a plugin that spells it differently.
LINK_KEYS = ("url", "link", "permalink", "href", "product_url", "producturl",
             "listing_url", "listingurl", "web_url", "weburl", "view_url",
             "viewurl", "address", "page")

#: A key is compared with everything but its letters and digits removed, so
#: ``product_url``, ``productUrl`` and ``Product URL`` are one key: a plugin
#: that names the field in its own language should not lose the link over it.
_LINK_BY_SHAPE = {}


def _shape(key):
    return "".join(char for char in str(key).lower() if char.isalnum())


for _key in LINK_KEYS:
    _LINK_BY_SHAPE.setdefault(_shape(_key), _key)

#: Anything with a scheme of its own that is not the web is not a listing page.
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


def link(item, base=""):
    """A listing's own page address, or "" when the plugin sent none.

    A relative address is joined onto ``base`` (the site itself), because a
    plugin reading its own dashboard has the path to hand long before it has
    the host name. Anything that carries another scheme - ``javascript:``,
    ``mailto:``, a Windows path - is refused rather than opened, and a plugin
    that guesses an address is no help: an empty answer is what the panel's
    store-and-clipboard fallback is for.
    """
    if not isinstance(item, dict):
        return ""
    found = {}
    for key, value in item.items():
        if not _LINK_BY_SHAPE.get(_shape(key)):
            continue
        text = str(value or "").strip()
        if text:
            found.setdefault(_LINK_BY_SHAPE[_shape(key)], text)
    #  A key that holds something unusable is skipped rather than answered
    #  with: a plugin that reports both a bad ``href`` and a good ``url`` is
    #  one whose link still works.
    for wanted in LINK_KEYS:
        candidate = _absolute(found.get(wanted, ""), base)
        if candidate:
            return candidate
    return ""


def _absolute(raw, base=""):
    """``raw`` as an http(s) address, or "" when it is not one."""
    raw = str(raw or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered.startswith(("http://", "https://")):
        return raw
    if raw.startswith("//"):
        return "https:" + raw
    if _SCHEME.match(raw):
        return ""
    if not str(base or "").strip():
        return ""
    return str(base).rstrip("/") + "/" + raw.lstrip("/")


def edit_values(item):
    """What the edit form is filled with before anybody touches it."""
    now = current(item)
    return {"title": now["title"],
            "price": "" if now["price"] is None else "%.2f" % now["price"],
            "count": "" if now["inventory"] is None else str(now["inventory"]),
            "state": edit_state_word(item)}


def edit_state_word(item):
    """The word for the state a listing is in now, as the form names it.

    A listing is *archived* in the vendor's own spelling as often as in the
    core's, and a draft is neither of the two states the form can write - so
    the current state is matched by what it means, not by how it is spelled,
    and anything else is offered in the vendor's own words.
    """
    now = current(item)["status"]
    for key, word in EDIT_STATES:
        if key == now:
            return word
    #  A draft or a hidden listing: named as the vendor names it, and marked
    #  so that choosing it again is understood to change nothing.
    word = (stock_compare.status_words(item) or "not on sale").strip()
    if word[:2].lower() == "a ":
        word = word[2:]
    word = word[:1].upper() + word[1:]
    return "%s (as it is)" % word


def edit_state_words(item):
    """The words the edit form offers for a listing's state, current first."""
    here = edit_state_word(item)
    return [here] + [word for _key, word in EDIT_STATES if word != here]


def edit_status(item, word):
    """The status an edit-form word means; ``None`` means leave it as it is."""
    now = current(item)["status"]
    for key, text in EDIT_STATES:
        if text == word:
            return None if key == now else key
    return None


def plan(item, **changes):
    """One entry for the writer: the listing, and only what changed.

    A field that was not asked for is not sent at all. Sending the current
    value of every field would work until the listing changed in the dashboard
    while this panel was open - and then that write would quietly put the old
    value back.
    """
    item = item or {}
    now = current(item)
    entry = {"id": item.get("id"),
             "sku": str(item.get("sku") or "").strip(),
             "title": now["title"],
             "card": now["title"]}
    #  Everything else the reader said identifies this listing goes with it -
    #  the product id its write endpoint takes beside the id it is listed
    #  under, say - and so does the address it reported. These are not fields
    #  being changed; they are how the writer finds the listing at all, and a
    #  writer left holding the wrong one answers 404 and changes nothing.
    for key, value in (item.get("ids") or {}).items():
        #  A zero is not an id (see is_id): sending it would give the writer a
        #  resource that cannot exist, and the answer would be another
        #  failure instead of the one read that actually helps.
        if key not in entry and is_id(value):
            entry[key] = value
    page = link(item)
    if page:
        entry["url"] = page
    changed = False
    if "title" in changes:
        title = " ".join(str(changes.get("title") or "").split())
        if title and title != now["title"]:
            entry["title"] = title
            changed = True
    if "price" in changes:
        price = changes.get("price")
        if price is not None and abs(float(price) - (now["price"] or 0.0)) > 0.004:
            entry["price"] = "%.2f" % float(price)
            changed = True
    if "inventory" in changes:
        inventory = changes.get("inventory")
        if inventory is not None and int(inventory) != now["inventory"]:
            entry["inventory"] = int(inventory)
            changed = True
    if "status" in changes:
        status = str(changes.get("status") or "").strip().lower()
        if status and status != now["status"]:
            entry["status"] = status
            changed = True
    return entry if changed else None


#: The names a reader or a writer uses for the id an API patches. A listing's
#: own ``id`` is its catalogue id and is not one of these.
PRODUCT_KEYS = ("product_id", "productId", "productid")


def is_id(value):
    """Whether a reader's value is an identifier at all.

    ``0`` is not an id. No product on any of these sites has one, so a reader
    that emits ``"product_id": 0`` for every listing is saying it does not have
    the id, not that the product is zero. The difference matters: counting a
    zero as an id makes the panel promise an edit it cannot make and sends a
    write to ``/api/products/0/`` that can only fail. A missing key and a zero
    take the same path here - the row cannot be written from this panel, and
    the console says which of the two the reader did.

    Anything else travels exactly as it was given. The core never renumbers an
    id and never learns what shape a vendor's id is, so a twelve-character
    catalogue key is as good an identifier as ``4321``.
    """
    if value is None or isinstance(value, (dict, list, tuple, bool)):
        return False
    text = str(value).strip()
    if not text:
        return False
    try:
        return float(text) != 0.0
    except ValueError:
        return True


def _id_values(entry):
    """Every value the entry carries under a product-id name, in order."""
    entry = entry if isinstance(entry, dict) else {}
    found = []
    for source in (entry, entry.get("ids") or {}):
        if not isinstance(source, dict):
            continue
        for key in PRODUCT_KEYS:
            value = source.get(key)
            if value not in (None, ""):
                found.append(value)
    return found


def product_id(entry):
    """The product id a mapping carries, as text, or "" when it carries none.

    A zero is "carries none": see :func:`is_id`.
    """
    for value in _id_values(entry):
        if is_id(value):
            return str(value).strip()
    return ""


def zero_product_id(entry):
    """Whether the reader said ``0`` rather than saying nothing at all.

    Not a failure of the listing and not a missing key: a reader emitting
    zeros is a reader that is not reporting product ids, which is the plugin's
    job, not the person's. The two are told apart so the console can name the
    one that is happening.
    """
    values = _id_values(entry)
    return bool(values) and not any(is_id(value) for value in values)


def zero_product_id_counts(items):
    """How many rows a reader reported as ``0``, and how many rows there are."""
    rows = list(items or [])
    return len([row for row in rows if zero_product_id(row)]), len(rows)


def zero_product_id_note(count, total):
    """The sentence for a read whose product ids are all zeros.

    Says what the plugin did, that reading again changes nothing, and what
    still works from here - because "0" is a bug report about the reader, and
    the person cannot fix a plugin from this panel.
    """
    count, total = int(count or 0), int(total or 0)
    if not count:
        return ""
    return ("the plugin reported product_id 0 for %s listing%s, and 0 is not "
            "an id: no product has one, so nothing from this read can be "
            "written, and reading again will return the same zeros. Stock "
            "counts can still be written from **Compare Woo vs CS** with "
            "**Set CanadianShopper to the website's counts...** (or **Fix the "
            "selected cards...** for one row), whose writer (%s) addresses the "
            "listing itself rather than a product."
            % ("all %d" % total if count == total else "%d of %d" % (count, total),
               "" if total == 1 else "s", "stock.set"))


def product_id_counts(items):
    """How many listings carry a product id, and how many there are.

    A listing without one is not broken and is not hidden: it lists, searches,
    is priced and opens. It just cannot be written from here, because the
    plugin will not guess which product a listing id belongs to - so the panel
    says the count after every read rather than letting an edit find out.
    """
    rows = list(items or [])
    return len([row for row in rows if product_id(row)]), len(rows)


def editable_note(editable, total):
    """How much of a read the editor can actually write, in words.

    Three different situations, and they must not read alike: a list where
    every row is editable, a list where some are, and a list where **none** is
    - which is not 2,541 listings that cannot be edited but a reader that is
    not reporting product ids at all. Telling someone to change 2,541 listings
    in the dashboard when the reading is what is missing would be advice that
    costs them an evening.
    """
    editable, total = int(editable or 0), int(total or 0)
    if not total:
        return "none to edit"
    if editable == total:
        return ("every one with a product id, so every one can be edited "
                "here")
    if not editable:
        return ("none of them with a product id, so none can be edited here "
                "yet - the plugin is not reporting one for any listing, and "
                "reading them again will not change that")
    return ("%d with a product id, so %d can be edited here; the rest have "
            "to be changed in the vendor dashboard" % (editable, editable))


#: The plugin version that reports each listing's real product id, as the
#: vendor gives it and never as 0. Before it a whole read could come back with
#: ``"product_id": 0`` on every row, which is not an id and was why nothing in
#: such a list could be written - so the version decides which sentence a read
#: like that gets: *update the plugin* or *this one is a defect*.
PRODUCT_ID_VERSION = "1.0.34"

#: The plugin version that prints the reader's own resolution counts. Written
#: for exactly the question this shop's read could not answer - did the lookups
#: run, and what did their answers hold - so an older one is told so.
RESOLUTION_VERSION = "1.0.39"


def needed_version_note(plugin="", needed=PRODUCT_ID_VERSION,
                        site_silent=False, failures=0):
    """Which plugin version reports real product ids, given what is installed.

    Three different situations and they must not read alike: an installed
    plugin older than the version that reports ids (the fix is one update), an
    installed plugin that *does* report them (then a read with none is a
    defect worth reporting, not an old list), and a version nobody could read
    (name the version and leave it there - an unreadable manifest is not
    evidence of anything).
    """
    needed = str(needed or "").strip()
    plugin = str(plugin or "").strip()
    if not needed:
        return ""
    if not plugin:
        return ("Plugin %s or newer reports each listing's real product id."
                % needed)
    if version_at_least(plugin, needed):
        failures = int(failures or 0)
        if failures and not site_silent:
            #  The reader said its lookups failed outright, so "a defect in
            #  the reader" would be the wrong report: the failing lookups are
            #  the reason, and reading again is what may resolve them.
            return ("The list was read by plugin %s, which does report real "
                    "product ids, so this is not the reader failing to try: "
                    "those failed lookups are why the ids are missing, and "
                    "reading again may resolve them." % plugin)
        if site_silent:
            #  The reader's own counts say it asked and every answer came
            #  back without a product reference, so the version sentence must
            #  not send anybody to report a defect that the numbers rule out.
            return ("The list was read by plugin %s, which does report real "
                    "product ids - and its own resolution line says the "
                    "lookups ran, so this is not an old list and not the "
                    "reader failing to try." % plugin)
        note = ("The list was read by plugin %s, which does report real "
                "product ids, so a read without them is a defect in the "
                "reader rather than a list that needs reading again - worth "
                "reporting with the plugin's own console line." % plugin)
        if not version_at_least(plugin, RESOLUTION_VERSION):
            #  Before 1.0.39 the reader says nothing about its resolution, so
            #  "defect" is the app's best guess rather than the reader's word.
            note += (" Plugin %s prints the reader's own resolution counts "
                     "for exactly this read, which says whether the lookups "
                     "ran and what their answers held." % RESOLUTION_VERSION)
        return note
    return ("The list was read by plugin %s, and %s or newer is the version "
            "that reports each listing's real product id - so updating the "
            "plugin is the fix." % (plugin, needed))


#: The identifiers a row can be recognised by, and what each is called in
#: words. The product id is the only one a write can be addressed with, but the
#: others are what a reader could resolve one *from*, so a read that has them
#: and no product id is a reader with something to work with rather than an
#: empty list.
IDENTIFIERS = (("product_id", "product id", "product ids"),
               ("id", "listing id", "listing ids"),
               ("sku", "SKU", "SKUs"),
               ("url", "listing address", "listing addresses"))


def identity_counts(items):
    """How many rows carry each identifier, in :data:`IDENTIFIERS` order."""
    counts = {key: 0 for key, _word, _words in IDENTIFIERS}
    for row in list(items or []):
        if not isinstance(row, dict):
            continue
        if product_id(row):
            counts["product_id"] += 1
        if is_id(row.get("id")):
            counts["id"] += 1
        if str(row.get("sku") or "").strip():
            counts["sku"] += 1
        if link(row):
            counts["url"] += 1
    return counts


def identity_note(items):
    """One line saying which identifiers a read did carry, and what that means.

    Written for the person who has to take it to the plugin's author: a reader
    that emitted 2,541 rows with no product id is a different problem depending
    on whether it had a listing id, an SKU and an address for each one. With
    those, resolving each listing to its product is something the reader can
    do; with none of them, the reader is not reading the listing at all.
    """
    rows = list(items or [])
    if not rows:
        return ""
    counts = identity_counts(rows)
    total = len(rows)
    said = ", ".join("%d %s" % (counts[key], word if counts[key] == 1
                                 else words)
                     for key, word, words in IDENTIFIERS if counts[key])
    if not said:
        return ("Not one row carried a listing id, an SKU or an address "
                "either, so the reader is not reading the listings' own "
                "identifiers at all.")
    line = "What the read did carry: %s (of %d listing%s)" % (
        said, total, "" if total == 1 else "s")
    if counts["sku"] == total or counts["id"] == total:
        line += (", so the reader has what resolving a listing to its product "
                 "takes; it is only the product id itself that never arrived.")
    elif counts["sku"]:
        line += (", but not for every row: resolving by SKU would leave %d "
                 "listing%s behind." % (total - counts["sku"],
                                        "" if total - counts["sku"] == 1
                                        else "s"))
    else:
        line += (", and no SKU on any row, so the product each listing belongs "
                 "to has to come from the vendor's own data.")
    return line


def shared_product_ids(items):
    """Product ids that more than one listing in a read claims.

    ``[(product_id, [listing names])]``, emptiest first is not a rule here -
    the order is the order the ids were first met, so the console reads in the
    order the catalogue does.

    Since plugin 1.0.35 resolves a missing product id through each listing's
    own detail - the same SKU matching ``stock.set`` uses - two listings can
    legitimately resolve to one product: a duplicate listing, or two SKUs the
    vendor maps onto the same product. That is worth saying *before* a write,
    because an edit addressed by that product id changes what both listings
    show, and the panel's confirmation names one.
    """
    order, seen = [], {}
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        found = product_id(item)
        if not found:
            continue
        key = str(found).strip()
        if key not in seen:
            seen[key] = []
            order.append(key)
        seen[key].append(str(item.get("name") or item.get("title")
                             or item.get("sku") or "a listing"))
    return [(key, seen[key]) for key in order if len(seen[key]) > 1]


def shared_product_note(items, limit=3):
    """One line naming the products two listings share, or "" when none do.

    Not a refusal: the panel still edits, because one of the two listings is
    usually the one the person means. But a write to a product both listings
    show is a change to both, and that is not something a count of edits makes
    visible.
    """
    shared = shared_product_ids(items)
    if not shared:
        return ""
    said = "; ".join("product %s is claimed by %s" % (key, " and ".join(
        repr(name) for name in names))
        for key, names in shared[:limit])
    more = len(shared) - limit
    line = ("%d product id%s in that read %s claimed by more than one "
            "listing: %s%s. An edit addressed by one of them changes what "
            "every listing sharing it shows."
            % (len(shared), "" if len(shared) == 1 else "s",
               "is" if len(shared) == 1 else "are", said,
               "; and %d more" % more if more > 0 else ""))
    return line


#: The reader's own summary of what a read carried. Plugin 1.0.34 and later
#: print it, and it is the one piece of evidence that tells the three ways this
#: ends apart: no product reference in the vendor's data (``without the key``),
#: a placeholder (``reported as 0``), or lookups that came back empty.
_READER_COUNTS = re.compile(
    r"(\d+)\s+listings?,\s*(\d+)\s+with a real product id,\s*"
    r"(\d+)\s+without the key,\s*(\d+)\s+reported as 0",
    re.IGNORECASE)


def reader_id_counts(text):
    """``(listings, with a real id, without the key, reported as 0)`` or None.

    The reader's own numbers, quoted rather than recomputed: the app counts
    the rows the reader emitted, and a reader that says the same thing in its
    own line is agreeing with it - or, when the two disagree, saying something
    worth reading.
    """
    found = _READER_COUNTS.findall(str(text or ""))
    if not found:
        return None
    return tuple(int(value) for value in found[-1])


def reader_says_note(text):
    """One sentence quoting the reader's own count line, or "".

    A read with no product ids is answered here with what the *reader* said it
    found, because that is what a defect report is built from - and because
    "without the key" is a different problem from "reported as 0": the first
    is the vendor's data carrying no product reference, the second a reader
    writing a placeholder it was told never to write.
    """
    counts = reader_id_counts(text)
    if counts is None:
        return ""
    listings, real, missing, zeros = counts
    said = ("The reader's own line says the same: %d listing%s, %d with a real "
            "product id, %d without the key at all, %d reported as 0."
            % (listings, "" if listings == 1 else "s", real, missing, zeros))
    return said


def ids_were_asked_for_note(text_has_lookups=False):
    """Why a read that asked for product ids still has none.

    The comparison panel asks the reader to skip product ids - it never reads
    one - and this panel never does: resolving them is the whole point of its
    read. So a read here with no ids either never ran the lookups or had every
    one of them come back empty, and saying which read this was is the
    difference between reporting a defect and chasing the wrong thing.
    """
    if text_has_lookups:
        return ("This read asked for the lookups - the edit panel never asks "
                "the reader to skip them - and it reports failures above, so "
                "those listings are the ones that lost their id.")
    return ("This read was not the fast, list-only one (the edit panel never "
            "asks for that flag), so the reader's own lookups either did not "
            "run or came back empty for every listing - and that, with the "
            "reader's line above, is what to send with a report.")


#: The reader's own resolution counts: detail requests made, usable
#: references, HTTP 200s that named none, ambiguous SKUs and hard failures.
#: Plugin 1.0.39 prints it after every successful ordinary read, and it is the
#: one line that says whether a read with no ids *asked* and got nothing back.
_RESOLUTION = re.compile(
    r"Stock resolution:\s*"
    r"(\d+)\s+detail requests?,\s*"
    r"(\d+)\s+usable references?,\s*"
    r"(\d+)\s+HTTP 200s? without a usable reference,\s*"
    r"(\d+)\s+ambiguous SKUs?,\s*"
    r"(\d+)\s+hard failures?", re.IGNORECASE)


def resolution_line(text):
    """The reader's own ``Stock resolution:`` line, or "" when it printed none."""
    for line in reversed(str(text or "").splitlines()):
        if "stock resolution:" in line.casefold():
            return line.strip()
    return ""


def resolution_counts(text):
    """The five numbers in the reader's resolution line, or ``None``.

    ``requested`` includes failed attempts (the reader says so itself), so
    ``empty`` is the number of answers that came back 200 and still named no
    product - which is the count that decides whether a read with no ids is
    the reader being wrong or the site's records being silent.
    """
    found = _RESOLUTION.findall(str(text or ""))
    if not found:
        return None
    requested, usable, empty, ambiguous, failed = (int(value)
                                                   for value in found[-1])
    return {"requested": requested, "usable": usable, "empty": empty,
            "ambiguous": ambiguous, "failed": failed}


def resolution_note(counts, total=0):
    """What the reader's own resolution counts mean, in one or two sentences.

    The line exists because "0 ids and no failure line" was ambiguous between
    three code paths. With it, the ambiguity is gone: a read whose every detail
    answered 200 and named nothing is not a broken reader at all - it is a shop
    whose records carry no product reference, and saying so is the difference
    between a defect report and a dead end.
    """
    if not counts:
        return ""
    asked = int(counts.get("requested") or 0)
    usable = int(counts.get("usable") or 0)
    empty = int(counts.get("empty") or 0)
    ambiguous = int(counts.get("ambiguous") or 0)
    failed = int(counts.get("failed") or 0)
    if not asked and not usable:
        return ("The reader's own resolution line says it made no detail "
                "lookups at all for this read, so its ids cannot have come "
                "from one.")
    vendor_side = usable == 0 and empty > 0
    said = ""
    if vendor_side:
        said = ("The reader's own resolution line settles it: %d detail "
                "%s made, %d of them answering HTTP 200 without a usable "
                "reference%s. The reader looked and the site's own records "
                "name no product, so this is the vendor's data rather than a "
                "defect in the reader - and no read of this shop produces a "
                "product id until those records carry one."
                % (asked, "request was" if asked == 1 else "requests were",
                   empty, "" if not failed else
                   ", plus %d hard %s" % (failed, "failure" if failed == 1
                                          else "failures")))
        if failed:
            #  Those listings are a different case: their records were never
            #  read, so "the site names nothing" is not yet known about them.
            said += (" The %d failed %s a separate matter - %s record was "
                     "never read, so a later read may still resolve %s."
                     % (failed, "lookup is" if failed == 1 else "lookups are",
                        "that listing's" if failed == 1 else "those listings'",
                        "it" if failed == 1 else "them"))
    elif usable:
        said = ("The reader's own resolution line says it made %d detail "
                "%s and turned %d into %s."
                % (asked, "request" if asked == 1 else "requests", usable,
                   "a usable product id" if usable == 1
                   else "usable product ids"))
        if empty:
            said += " %d of them answered without naming one." % empty
    if ambiguous:
        said += (" %d %s left without an id because more than one product "
                 "matched its SKU." % (ambiguous,
                                       "listing was" if ambiguous == 1
                                       else "listings were"))
    if failed and not vendor_side:
        said += (" %d detail %s failed outright." %
                 (failed, "request" if failed == 1 else "requests"))
    return " ".join(said.split())


#: Stage names a reader may use for its product-id phase. The plugin's own
#: word is ``ids``; the others are the spellings a later reader might pick, and
#: recognising a few costs nothing while missing one costs a wrong sentence.
_ID_PHASES = ("ids", "id", "product-ids", "product_ids", "productids",
              "resolving ids", "lookups")


def phases_note(stages, lookups_failed=0, site_silent=False):
    """What the reader's own progress phases say about whether it looked ids up.

    This is the question that decided a round trip with the plugin's author:
    the same reader resolves ids when the phase runs, so a read with none is
    either *the lookups never ran* or *they ran and came back empty* - and the
    progress markers the reader emits answer which. A reader that emits no
    phases costs nothing but this sentence, which then says so instead of
    guessing.
    """
    stages = [str(stage).strip() for stage in (stages or []) if str(stage).strip()]
    if not stages:
        return ("The reader reported no progress phases at all, so this "
                "console cannot say whether its lookups ran.")
    listed = ", ".join(stages)
    if any(stage.casefold() in _ID_PHASES for stage in stages):
        if site_silent:
            #  The resolution line already says what the answers held; saying
            #  it twice reads as two problems.
            return ("The reader reported its product-id phase during this "
                    "read (%s), so the lookups ran." % listed)
        return ("The reader reported its product-id phase during this read "
                "(%s), so the lookups ran%s." %
                (listed, " and some of them failed" if lookups_failed else
                 " - and the ids it sent back were not usable"))
    return ("The reader reported these phases - %s - and never a product-id "
            "phase, so its lookups did not run at all." % listed)


#: Key names whose values are never put in a diagnosis file. The file is meant
#: to be pasted into a conversation about a plugin, and a cookie or a token in
#: it would be a login handed over by accident.
_SECRET_KEY = re.compile(
    r"token|cookie|secret|password|passwd|session|auth|credential|apikey|"
    r"api_key|email|phone|address", re.IGNORECASE)


def sanitize(value, limit=40, depth=0, max_items=12):
    """A value reduced to what a plugin author needs and nothing more.

    Key names, value types, lengths and short previews: enough to see whether a
    product reference is there and in what shape, and not enough to be somebody's
    account. Anything under a key that names a secret is hidden, strings are
    cut, collections are capped, and nesting stops at ``depth`` 3.
    """
    if isinstance(value, dict):
        if depth >= 3:
            return "object(%d keys)" % len(value)
        pairs = list(value.items())
        lines = []
        for key, item in pairs[:max_items]:
            name = str(key)
            if _SECRET_KEY.search(name):
                lines.append("%s: (hidden - it is not part of the question)" % name)
                continue
            lines.append("%s: %s" % (name, sanitize(item, limit, depth + 1,
                                                    max_items)))
        if len(pairs) > max_items:
            #  The *names* of what was not shown are the question, when the
            #  question is "does this record name a product at all" - a
            #  response whose product reference sits at key 30 of 38 is exactly
            #  the evidence a count of hidden keys throws away. A key name is
            #  not a secret; its value is, and values stay cut.
            rest = [str(key) for key, _ in pairs[max_items:]]
            shown = rest[:80]
            lines.append("... %d more key(s), names only: %s%s"
                         % (len(rest), ", ".join(shown),
                            "" if len(rest) <= 80 else ", ..."))
        return "{\n" + "\n".join("  " * (depth + 1) + line for line in lines) \
            + "\n" + "  " * depth + "}"
    if isinstance(value, (list, tuple)):
        if depth >= 3:
            return "list(%d)" % len(value)
        items = [sanitize(item, limit, depth + 1, max_items)
                 for item in list(value)[:max_items]]
        if len(value) > max_items:
            items.append("... %d more" % (len(value) - max_items))
        if not items:
            return "[]"
        return "[\n" + "\n".join("  " * (depth + 1) + "  " * depth + item
                                  for item in items) + "\n" + "  " * depth + "]"
    if isinstance(value, str):
        text = value.replace("\r", " ").replace("\n", " ").strip()
        if len(text) > limit:
            text = text[:max(1, limit - 1)] + "\u2026"
        return 'str(%d) "%s"' % (len(value), text)
    if isinstance(value, bool):
        return "bool %s" % ("true" if value else "false")
    if value is None:
        return "null"
    return "%s %s" % (type(value).__name__, value)


def product_reference_keys(row):
    """The id-shaped keys a row carries, and the ones it does not.

    The question a plugin author asks first: is there a product reference in
    this payload at all? A key that holds ``0`` is reported as one, because
    zero is not an id and that difference has already cost one diagnosis.
    """
    keys = []
    for key in (row or {}):
        shape = "".join(char for char in str(key).lower() if char.isalnum())
        if shape.endswith("productid") or shape in (
                "productid", "postid", "wpid", "productidentifier"):
            value = (row or {}).get(key)
            if value in (None, ""):
                state = "empty"
            elif str(value).strip() in ("0", "0.0"):
                state = "zero - not an id"
            else:
                state = "present"
            keys.append((str(key), state))
    return keys


def productish_keys(row):
    """Every key whose name mentions a product, with a shape for its value.

    ``product_reference_keys`` answers the narrow question - is there a key
    that *is* a product id. This answers the wider one a reader's author needs
    next: does the record mention a product at all, under ``product``,
    ``productId``, ``productData`` or a spelling the exact list misses. A
    record naming none of them anywhere is the answer to "can the reader
    resolve one from here", and it is a different answer from "the value was
    empty".
    """
    found = []
    for key, value in (row or {}).items():
        name = str(key)
        shape = "".join(char for char in name.lower() if char.isalnum())
        if "product" not in shape:
            continue
        if isinstance(value, dict):
            state = "a record with %d key(s)" % len(value)
        elif isinstance(value, (list, tuple)):
            state = "a list of %d" % len(value)
        elif value in (None, ""):
            state = "empty"
        elif not isinstance(value, bool) and str(value).strip() in ("0", "0.0"):
            state = "zero - not an id"
        else:
            state = sanitize(value, 40)
        found.append((name, state))
    return found


#: The fields this record would have to carry for the vendor's own record to
#: be the thing an edit writes. Named because a record that carries all of them
#: is one the write path could address directly, which is a different (and much
#: shorter) road than resolving a second identifier out of it.
EDITABLE_FIELDS = ("title", "priceCad", "inventory", "status", "description",
                   "primaryImageUrl", "category", "sku")


def editable_shape(record):
    """Which editable fields a detail record carries, in the vendor's spelling."""
    if not isinstance(record, dict):
        return []
    folded = {str(key).casefold(): key for key in record}
    return [folded[name.casefold()] for name in EDITABLE_FIELDS
            if name.casefold() in folded]


def listing_id(item):
    """The listing's *own* id - the key the vendor's detail endpoint takes.

    Not the product id: this is what names the page or the detail record, and
    the two are different things on every one of these sites.
    """
    for key in ("id", "listing_id", "listingId", "listing"):
        value = (item or {}).get(key)
        if value in (None, "") or isinstance(value, (dict, list)):
            continue
        return str(value).strip()
    return ""


def detail_url(listing_id, base="https://canadianshopper.ca"):
    """The vendor endpoint a reader's own lookup reads for one listing.

    Kept in one place because the plugin names the same path in its own
    diagnostics (``/api/data/product/<listing-id>``), and a diagnosis that
    calls a different address than the reader does is evidence about the wrong
    thing.
    """
    identifier = str(listing_id or "").strip()
    if not identifier:
        return ""
    return "%s/api/data/product/%s" % (str(base or "").rstrip("/"), identifier)


def diagnosis_path(folder, now=None):
    """Where a diagnosis file goes: a dated name, an earlier one never lost.

    Two presses in one minute are two pieces of evidence - a before and an
    after, or two different listings - so the second gets its own file rather
    than quietly replacing the first.
    """
    when = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = Path(folder) / ("cs-read-diagnosis-%s" % when)
    path = base.with_suffix(".txt")
    number = 2
    while path.exists():
        path = Path("%s-%d.txt" % (base, number))
        number += 1
    return path


def fetch_detail(url, cookie="", timeout=25, opener=None):
    """``(status, content_type, body_text)`` for one detail request; never raises.

    Read-only, one request, the person's own session: what the plugin's reader
    would have read, so its answer can be looked at instead of guessed. A
    refusal is returned as a status and a body, not an exception - the status
    is half the evidence.
    """
    if not url:
        return 0, "", ""
    if opener is not None:
        return opener(url, cookie)
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (AlexCollect-GUI)",
                      "Accept": "application/json",
                      "Cookie": str(cookie or "")})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(200000).decode("utf-8", "replace")
            return (getattr(response, "status", 200),
                    response.headers.get("Content-Type", ""), body)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(200000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, str(getattr(exc, "headers", "") or ""), body
    except Exception as exc:
        return 0, "", str(exc)


#: Methods that mean "this route can be written", in the order they matter.
WRITE_METHODS = ("PATCH", "PUT", "POST")


def allowed_methods(header):
    """The method names in an ``Allow`` header, uppercased and in a stable order."""
    words = []
    for part in str(header or "").replace(";", ",").split(","):
        word = part.strip().upper()
        if word and word not in words:
            words.append(word)
    known = [name for name in ("GET", "HEAD", "OPTIONS", "PATCH", "PUT",
                               "POST", "DELETE") if name in words]
    return known + [word for word in words if word not in known]


def fetch_options(url, cookie="", timeout=15, opener=None):
    """Ask a route which methods it accepts; never raises, never changes anything.

    ``OPTIONS`` carries no body and asks the server what it supports, so it is
    the one way to find out whether the record that holds a listing's editable
    fields can be written *without* writing to it. A site that does not
    implement OPTIONS answers 405/501 or omits ``Allow``; that is inconclusive
    and is reported as such rather than as a refusal.
    """
    blank = {"status": 0, "allow": [], "allow_header": "", "note": ""}
    if not url:
        return dict(blank, note="no address to ask")
    if opener is not None:
        return opener(url, cookie)
    request = urllib.request.Request(
        url, method="OPTIONS",
        headers={"User-Agent": "Mozilla/5.0 (AlexCollect-GUI)",
                 "Accept": "application/json",
                 "Cookie": str(cookie or "")})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            header = response.headers.get("Allow", "") or ""
            return {"status": getattr(response, "status", 200),
                    "allow": allowed_methods(header), "allow_header": header,
                    "note": ""}
    except urllib.error.HTTPError as exc:
        header = ""
        try:
            header = (getattr(exc, "headers", None) or {}).get("Allow", "") or ""
        except Exception:
            header = ""
        return {"status": exc.code, "allow": allowed_methods(header),
                "allow_header": header,
                "note": "" if header else str(exc.reason or exc)}
    except Exception as exc:
        return dict(blank, note=str(exc))


def methods_note(probe):
    """What an endpoint's advertised methods mean for editing one listing.

    Two answers matter and one does not: a route that advertises ``PATCH`` or
    ``PUT`` is one the vendor says can be written, which makes the listing id
    enough to address it; a route that advertises only ``GET``/``HEAD`` is
    read-only and the edit panel's verdict is final. Anything else - 405, 501,
    no ``Allow`` header - is inconclusive and must not be read as either.
    """
    if not probe:
        return ""
    status = probe.get("status") or 0
    allowed = list(probe.get("allow") or [])
    if not status:
        return ("The vendor's own route could not be asked which methods it "
                "accepts (%s). Nothing was changed, and this says nothing "
                "either way." % (probe.get("note") or "no answer"))
    if not allowed:
        return ("The vendor's own route answered HTTP %s without an Allow "
                "header, so it does not say which methods it accepts - some "
                "sites answer OPTIONS that way without meaning the route is "
                "read-only. Inconclusive; nothing was changed." % status)
    writable = [name for name in allowed if name in WRITE_METHODS]
    if any(name in ("PATCH", "PUT") for name in writable):
        return ("**The vendor's own route states it accepts %s.** That is the "
                "record which holds a listing's title, price, stock and state, "
                "addressed by the listing id the reader already has - so it "
                "can be written, and the product id is not needed to address "
                "it. Which fields it accepts is still unproven: a PATCH "
                "carrying the values a listing already has would confirm that "
                "without changing anything, and only with your say-so."
                % ", ".join(writable))
    return ("The vendor's own route states it accepts only %s, so it is "
            "read-only: the record that holds the listing's title, price and "
            "state cannot be written there, and 'not editable on "
            "CanadianShopper' is the final answer for those fields."
            % ", ".join(allowed))


def without_progress(text):
    """``(spoken, omitted)`` for a tool's output with its progress markers cut.

    A reader that emits the progress channel leaves those markers in the text
    the app keeps, because the app keeps what the tool printed. They are the
    window's progress bar, not the reader's words - 250 lines of
    ``ALEX_COLLECT_PROGRESS:{"stage": "ids", ...}`` is what a diagnosis file
    looks like with them left in, and the three lines that matter are lost
    inside it. The count is returned so the file can say what it did not print.
    """
    kept, omitted = [], 0
    for line in str(text or "").splitlines():
        if "ALEX_COLLECT_PROGRESS:" in line:
            omitted += 1
            continue
        kept.append(line.replace("\x1e", "").replace("\x1f", ""))
    return "\n".join(kept).strip("\n"), omitted


def parsed_body(body):
    """A response body as data when it is JSON, or ``None`` when it is not."""
    try:
        return json.loads(str(body or ""))
    except (ValueError, TypeError):
        return None


def _body_for_diagnosis(body, limit=40):
    """A response body as a sanitised structure when it is JSON, text if not.

    The detail record is the one whose key *names* matter most - a reader
    resolving a product reads exactly this, and where a product reference sits
    in it is the whole question - so it keeps sixty keys with their values
    rather than the twelve a catalogue row gets, and names the rest.
    """
    parsed = parsed_body(body)
    if parsed is None:
        text = str(body or "")
        snippet = text.strip().replace("\r", " ")
        return ("not JSON (%d characters): %s" %
                (len(text), snippet[:240] + ("\u2026" if len(snippet) > 240
                                             else "")))
    return sanitize(parsed, limit, max_items=60)


def diagnosis_text(row=None, output="", stages=(), plugin="", command="",
                   detail=None, total=0, editable=0, now=None,
                   app_version="", source="", probe=None):
    """The three things a plugin author needs, in one file they can read.

    Written because a round trip with the reader's author ended in *"send the
    console output, whether the ids phase appeared, and one row with its detail
    response"*: everything here is evidence the app already has or can fetch
    once, and none of it is a credential.
    """
    when = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    lines = ["CanadianShopper read diagnosis", "=" * 32,
             "Written: %s" % when]
    if app_version:
        lines.append("Alex Collect: %s" % app_version)
    lines.append("Plugin: %s" % (plugin or "(version not readable)"))
    lines.append("Command the app ran: %s" % (command or "(not recorded)"))
    if source:
        lines.append("Where this list came from: %s" % source)
    lines.append("")
    lines.append("The app's count: %d listing(s), %d with a usable product id."
                 % (int(total or 0), int(editable or 0)))
    counts = reader_id_counts(output)
    lines.append("The reader's own line: %s" % (
        ("%d listings, %d with a real product id, %d without the key, %d "
         "reported as 0" % counts) if counts else "(none printed)"))
    resolution = resolution_counts(output)
    resolution_said = resolution_line(output)
    if resolution_said:
        lines.append("The reader's resolution line: %s" % resolution_said)
    elif plugin and not version_at_least(plugin, RESOLUTION_VERSION):
        lines.append("The reader's resolution line: (none printed - plugin "
                     "%s prints its own resolution counts for this read)"
                     % RESOLUTION_VERSION)
    else:
        lines.append("The reader's resolution line: (none printed)")
    missed = stock_compare.failed_lookups(output)
    lines.append("Lookups the reader says failed: %s" %
                 (missed if missed else "none said"))
    lines.append("Phases the reader reported: %s" %
                 (", ".join(str(stage) for stage in stages) if stages else
                  "(none)"))
    lines.append(phases_note(
        stages, missed,
        site_silent=bool(resolution and resolution["usable"] == 0 and
                         resolution["empty"])))
    if resolution:
        lines.append(resolution_note(resolution))
        if resolution["usable"] == 0 and resolution["empty"]:
            #  The file is what somebody reads next month, so it carries the
            #  consequence and not only the cause.
            lines.append(uneditable_note(resolution["failed"]))
    lines.append("")
    lines.append("--- the reader's output, as it read on the console " + "-" * 6)
    spoken, progress_lines = without_progress(output)
    lines.append(spoken or "(no console output was kept for this list - see "
                           "where it came from, above)")
    if progress_lines:
        lines.append("")
        lines.append("(%d progress-marker line(s) omitted: they are the "
                     "window's progress bar, not the reader's words. The "
                     "phases they carried are listed above.)" % progress_lines)
    lines.append("")
    if row is not None:
        lines.append("--- one catalogue row, sanitised " + "-" * 18)
        references = product_reference_keys(row)
        if references:
            lines.append("Product-reference keys: " + ", ".join(
                "%s (%s)" % (key, state) for key, state in references))
        else:
            lines.append("Product-reference keys: none - no key in this row "
                         "names a product, not even as a zero")
        lines.append(sanitize(row))
        extra = [(key, state) for key, state in productish_keys(row)
                 if key not in [name for name, _state in references]]
        if extra:
            #  A row may name its product in a key that is not an id at all -
            #  a nested record, or a spelling the exact list does not know.
            lines.append("Also naming a product: " +
                         "; ".join("%s (%s)" % (key, state)
                                   for key, state in extra))
        if isinstance(row, dict) and "sku" in row and \
                not str(row.get("sku") or "").strip():
            #  The reader resolves a listing to its product by its SKU first,
            #  and an empty one leaves nothing to match on - which is one way
            #  ids go missing while every request still answers 200.
            lines.append("The listing's SKU is empty. Plugin 1.0.39 resolves "
                         "such a listing through its own detail request rather "
                         "than by SKU, so a missing SKU is not the reason an "
                         "id is absent here - the response's own keys are.")
        lines.append("")
    if detail:
        lines.append("--- the detail request the reader's lookup would make "
                     + "-" * 10)
        lines.append("GET %s" % (detail.get("url") or "(no listing id)"))
        lines.append("HTTP %s, %s" % (detail.get("status") or "(no answer)",
                                      detail.get("content_type") or
                                      "(no content type)"))
        lines.append(_body_for_diagnosis(detail.get("body")))
        named = productish_keys(parsed_body(detail.get("body")))
        #  A key that *mentions* a product is not a key that holds one: this
        #  vendor's record has isDemoProduct and productOptions, both null.
        holds = [key for key, state in named
                 if state.startswith(("str(", "int ", "float ")) and
                 not state.startswith("zero")]
        if named:
            lines.append("Keys in that response that mention a product: " +
                         "; ".join("%s (%s)" % (key, state)
                                   for key, state in named) +
                         (" - and %s holds an id: %s" %
                          ("one of them" if len(holds) == 1
                           else "%d of them" % len(holds), ", ".join(holds))
                          if holds else
                          " - none of them holds an id"))
        else:
            lines.append("No key in that response names a product - not "
                         "product, not productId, not any spelling of one - so "
                         "a reader cannot resolve this listing's product from "
                         "this endpoint at all: the reference lives somewhere "
                         "the stock reader never asks.")
        shape = editable_shape(parsed_body(detail.get("body")))
        if not holds and len(shape) >= 3:
            #  Not a conclusion, a question worth putting in front of the
            #  vendor: the record the reader already reads is keyed by the
            #  listing id and holds the very fields an edit changes - while the
            #  update action writes a different path, /api/products/<id>/.
            lines.append("This endpoint's record carries %s - the fields an "
                         "edit changes - and it is keyed by the listing's own "
                         "id, while the plugin's update action writes "
                         "/api/products/<product_id>/. Whether the vendor's "
                         "own record is meant to be written directly is the "
                         "one question this file cannot answer; it is worth "
                         "asking before the shop is written off as uneditable."
                         % ", ".join(shape))
        if resolution and resolution["usable"] == 0 and resolution["empty"]:
            lines.append("That is the same answer as the reader's own "
                         "resolution line: %d lookups, %d answers and none "
                         "naming a product. This settles the reader's side "
                         "for these listings - the vendor's data carries no "
                         "product reference to resolve, so there is nothing "
                         "more to report about the resolver."
                         % (resolution["requested"], resolution["empty"]))
            lines.append("Whether those listings can still be edited depends "
                         "on the check below, not on the reader: a record the "
                         "vendor lets the app write can be edited without any "
                         "product id at all.")
        lines.append("")
    if probe:
        lines.append("--- whether that record can be written (a read-only "
                     "check) " + "-" * 4)
        lines.append("OPTIONS %s" % (detail.get("url") if detail else "") if
                     detail and detail.get("url") else "OPTIONS (no address)")
        if probe.get("status"):
            lines.append("HTTP %s; Allow: %s" % (
                probe.get("status"),
                probe.get("allow_header") or "(no Allow header)"))
        else:
            lines.append("No answer: %s" % (probe.get("note") or "unknown"))
        note = methods_note(probe)
        if note:
            lines.append(note.replace("**", ""))
        lines.append("An OPTIONS request carries no body: nothing on the site "
                     "was read beyond the answer to this question, and "
                     "nothing was changed.")
        lines.append("")
    lines.append("Nothing in this file is a cookie, a token or a password: "
                 "values under those names are hidden, and long text is cut.")
    return "\n".join(lines)


def uneditable_note(failures=0):
    """What a shop whose records name no product means for the edit buttons.

    Confirmed by the plugin's author for 1.0.39: ``marketplace.listing_update``
    matches a listing by id, SKU or title but refuses to write without an
    explicit product reference, and there is no server-side resolver behind it.
    So a read in which no record names a product is not a list that a later
    read fixes - those listings cannot have their title, price or state changed
    from here at all, and saying "read again" would be advice that cannot work.
    """
    said = ("Editing one of these is not something reading again can fix: the "
            "plugin's update action finds the listing but refuses to write "
            "without an explicit product reference, and these records carry "
            "none. Title, price and state have to be changed in the vendor "
            "dashboard. Stock counts are the one exception in address: the "
            "comparison panel's stock.set names the listing itself, so a "
            "missing product id does not stand in its way.")
    failures = int(failures or 0)
    if failures:
        said += (" %d %s not covered by that: %s lookup did not answer at "
                 "all, so read once more before giving up on %s."
                 % (failures, "listing is" if failures == 1
                    else "listings are",
                    "its" if failures == 1 else "their",
                    "it" if failures == 1 else "them"))
    return said


def product_id_gap(items, plugin="", needed=PRODUCT_ID_VERSION, works=True,
                   reader_text="", stages=None):
    """The whole sentence for a read nothing can be written from, or "".

    Said once, where it can be read, instead of three paragraphs in three
    places: what the reader did (a key holding 0, or no key at all), what its
    own count line says when it printed one, which plugin version fixes it,
    and - for the console - what still works from here. A read that can be
    written returns "" and says nothing.
    """
    rows = list(items or [])
    if not rows or not nothing_editable(rows):
        return ""
    zeros, total = zero_product_id_counts(rows)
    if zeros:
        said = zero_product_id_note(zeros, total)
    else:
        said = ("No listing in that read carried a product id, so the edit "
                "buttons cannot send anything: the plugin's reader is not "
                "reporting one.")
    said_by_reader = reader_says_note(reader_text)
    #  The reader's own phases decide *which read this was*, so when they were
    #  reported they are used instead of the general sentence - and a reader
    #  that says nothing keeps the general one.
    resolution = resolution_counts(reader_text)
    site_silent = bool(resolution and resolution["usable"] == 0 and
                       resolution["empty"] > 0)
    phases = (phases_note(stages, stock_compare.failed_lookups(reader_text),
                          site_silent=site_silent) if stages else "")
    parts = [said, said_by_reader,
             #  The general "they did not run or came back empty" sentence is
             #  only worth printing while nobody knows which: phases and the
             #  resolution line each answer it, and printing all three would
             #  contradict the sentence that actually knows.
             (ids_were_asked_for_note(
                 bool(stock_compare.failed_lookups(reader_text)))
              if said_by_reader and not phases and not resolution else ""),
             phases,
             resolution_note(resolution),
             (uneditable_note() if site_silent else ""),
             needed_version_note(
                 plugin, needed, site_silent=site_silent,
                 failures=(resolution["failed"] if resolution else
                           stock_compare.failed_lookups(reader_text))),
             identity_note(rows)]
    if works:
        parts.append("Searching, opening a listing and editing in the vendor "
                     "dashboard all still work.")
    return " ".join(part for part in parts if part)


def nothing_editable(items):
    """Whether a whole read carries no product id at all.

    The difference matters: one row missing an id is a listing the vendor does
    not expose, but no row having one is a reading that does not include them,
    and the answer to that is the plugin, not the dashboard.
    """
    editable, total = product_id_counts(items)
    return bool(total) and not editable


def wants_product_id(report):
    """Whether a failure is the plugin refusing to guess a product id.

    That is not a broken listing - it is a list that was read before the plugin
    started reporting product ids, so the answer is a fresh read, not an edit
    of the row on the screen.
    """
    for failure in (report or {}).get("failed") or []:
        said = str((failure or {}).get("why") or "").lower()
        if "product id" in said or "product_id" in said:
            return True
    return False


def replan(entry, item):
    """The same change again, planned for a freshly read row.

    Used after a re-read: the row the person selected is stale, the change they
    confirmed is not, and the new plan is built from what the site says now.
    """
    entry = entry or {}
    changes = {}
    for key in ("inventory", "status"):
        if key in entry:
            changes[key] = entry[key]
    if "price" in entry:
        changes["price"] = price_number({"price": entry["price"]})
    if "title" in entry and entry["title"] != str(entry.get("card") or ""):
        changes["title"] = entry["title"]
    if not changes:
        return None
    return plan(item, **changes)


def identified_by(entry):
    """How a plan entry names its listing, in words, for a failure message.

    A write that comes back "not found" is a question about *which* listing
    was addressed, and the answer is only useful if it says what was sent.
    """
    parts = []
    for key in ("id", "product_id", "productId", "listing_id", "listingId",
                "post_id"):
        value = (entry or {}).get(key)
        if value not in (None, "") and (key == "id" or is_id(value)):
            parts.append("%s %s" % (key.replace("_", " "), value))
    sku = str((entry or {}).get("sku") or "").strip()
    if sku:
        parts.append("SKU %s" % sku)
    return ", ".join(parts) or "nothing that identifies it"


def describe(entry, item=None):
    """The confirmation: exactly what would change, in the person's words.

    ``item`` supplies the old side when the caller has the listing to hand;
    without it the lines still name the field and the new value, because a
    confirmation that hides a change is worse than one that reads oddly.
    """
    item = item or {}
    lines = []
    old_title = str(item.get("name") or "").strip()
    if "status" in entry:
        lines.append("State:  %s  ->  %s" % (
            stock_compare.status_words(item) or "on sale",
            "on sale" if entry["status"] == "active"
            else (entry["status"] if entry["status"] != "archived"
                  else "archived")))
    if "inventory" in entry:
        lines.append("Stock:  %s  ->  %d" % (
            stock_text(item) or "no count", entry["inventory"]))
    if "price" in entry:
        lines.append("Price:  %s  ->  %s" % (
            price_text(item) or "no price", entry["price"]))
    if "title" in entry and entry["title"] != old_title:
        lines.append("Title:  %s\n     -> %s" % (old_title or "(none)",
                                                 entry["title"]))
    return lines


def summary(plan):
    """One sentence saying what the plan would change."""
    count = len(plan or [])
    if not count:
        return "Nothing to change."
    return "1 listing would be changed on CanadianShopper." if count == 1 \
        else "%d listings would be changed on CanadianShopper." % count


def read_result(path):
    """The plugin's answer as a dict, or ``{}`` when it wrote none."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def report(plan_items, answer):
    """``{"changed", "failed", "unknown"}`` for a plan and the plugin's answer.

    The same reading the stock writer uses, so a listing the plugin did not
    mention is *unknown* here too - never a change this panel claims happened.
    """
    return stock_compare.plugin_write_report(plan_items or [], answer or {})


def apply_to_item(item, entry):
    """The listing as it stands once ``entry`` was written.

    Only the fields the plan names are touched, so the row the person is
    looking at keeps the information the plugin reported for everything else.
    """
    item = dict(item or {})
    if "title" in entry:
        item["name"] = entry["title"]
    if "price" in entry:
        item["price"] = entry["price"]
    if "inventory" in entry:
        item["qty"] = int(entry["inventory"])
    if "status" in entry:
        item["status"] = entry["status"]
    return item
