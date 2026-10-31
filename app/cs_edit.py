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
from pathlib import Path

import stock_compare
import woo_orders

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
        if key not in entry and value not in (None, ""):
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


def product_id(entry):
    """The product id a mapping carries, as text, or "" when it carries none."""
    entry = entry or {}
    for key in PRODUCT_KEYS:
        value = entry.get(key) if isinstance(entry, dict) else None
        if value not in (None, ""):
            return str(value)
    ids = entry.get("ids") if isinstance(entry, dict) else None
    if isinstance(ids, dict):
        for key in PRODUCT_KEYS:
            value = ids.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


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
        if value not in (None, ""):
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
