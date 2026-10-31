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
    import re
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


def label(item):
    """One row of the list: the card, its state, its stock, its price."""
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
    return "  -  ".join(part for part in parts if part)


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
