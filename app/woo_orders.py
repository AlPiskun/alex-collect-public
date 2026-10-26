"""Turn a pasted list of card names into a WooCommerce order.

A customer texts a list of cards. The useful thing to do is turn that list into
a draft order on the website, matched to real products, without typing each one
into the dashboard. Three pieces live here, all testable without a window or a
site:

  * reading the pasted list (numbered, bulleted, one per line, messy)
  * choosing which product each line means, and how sure we are
  * creating an order, or adding to one that already exists

The uncertain part is deliberately visible: anything not matched confidently is
left for the user to pick by hand rather than guessed.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

ORDERS_PATH = "/wp-json/wc/v3/orders"
PRODUCTS_PATH = "/wp-json/wc/v3/products"
USER_AGENT = "Mozilla/5.0 (compatible; AlexCollectTools/1.0)"

#  A line has to clear this to be used without asking. Set high on purpose:
#  putting the wrong card on an order is worse than one extra click.
AUTO_MATCH = 0.90
#  Below this a candidate is not worth showing at all.
SHOW_MATCH = 0.30

_DROP = re.compile(r"^[\s\-\u2022\u00b7*]+")
_NUMBERING = re.compile(r"^\(?\d{1,3}[.)\]:-]\s*")
_LINE_NOTES = re.compile(r"\s+[-\u2013]\s+\$?\d+(?:[.,]\d{2})?\s*$")


class OrderError(Exception):
    """A refused or impossible order, safe to show to the user."""

    def __init__(self, message, status=0):
        super().__init__(message)
        self.message = message
        self.status = status


# ------------------------------------------------------------ the pasted list
def clean_card_line(line):
    """One card name from one pasted line, with list furniture removed.

    A text message arrives numbered, bulleted, or quoted, sometimes with the
    price after a dash. None of that is part of the card's name.
    """
    text = str(line or "").strip()
    if not text:
        return ""
    text = _DROP.sub("", text)
    text = _NUMBERING.sub("", text)
    text = text.strip().strip('"').strip("'").strip()
    #  "1989 Gretzky #1 - $40" keeps the name; a trailing price is noise.
    text = _LINE_NOTES.sub("", text)
    return " ".join(text.split())


def parse_card_list(text):
    """The card names in a pasted block, in the order they were written.

    Blank lines and ``#`` comments are dropped. Duplicates are kept: a customer
    asking for two of the same card is a real thing to say, and the order
    builder merges them into one line with quantity 2.
    """
    names = []
    for raw in str(text or "").splitlines():
        if raw.strip().startswith("#"):
            continue
        name = clean_card_line(raw)
        if name:
            names.append(name)
    return names


# ------------------------------------------------------------- fuzzy matching
_WORD = re.compile(r"[a-z0-9]+")


def normalise(name):
    """A name reduced to the words that carry meaning, for comparison."""
    words = _WORD.findall(str(name or "").lower())
    return " ".join(words)


#  Words that say nothing about which card it is. "card" and "the" appear in
#  most titles; grades are short and shared by nearly every listing.
_STOP = {"the", "and", "for", "with", "card", "cards", "of", "to", "in",
         "ex", "nm", "mt", "vg", "gd", "fr", "pr", "op", "rc"}


def _tokens(name):
    """``{token: weight}`` for the words that identify a card.

    Numbers weigh double. A card is filed under its number and its year, and
    #87 versus #88 is the difference between two different cards, while a
    missing "the" is not.
    """
    weights = {}
    for word in normalise(name).split():
        if word in _STOP:
            continue
        if word.isdigit():
            weights[word] = 2.0
        elif len(word) > 2:
            weights[word] = 1.0
    return weights


def _numbers(name):
    return {w for w in normalise(name).split() if w.isdigit()}


def analyse(query, name):
    """``(score, numbers_ok)`` for one candidate.

    The score is how much of the *customer's* wording the product title
    accounts for. Containment is the right shape here: a full title ("1989
    O-Pee-Chee Wayne Gretzky #1 EX-MT 6") should not be penalised for having
    words the customer left out, but a customer line that names things the
    title does not have is a warning sign.
    """
    wanted = _tokens(query)
    if not wanted:
        return 0.0, False
    have = _tokens(name)
    matched = sum(weight for word, weight in wanted.items() if word in have)
    containment = matched / sum(wanted.values())
    query_numbers = _numbers(query)
    product_numbers = _numbers(name)
    numbers_ok = bool(query_numbers) and query_numbers <= product_numbers
    #  A number the title does not contain is evidence of a different card.
    if query_numbers and not query_numbers <= product_numbers:
        containment *= 0.5
    #  One word is never enough to be sure: "Gretzky" fits many cards.
    if len(wanted) == 1:
        containment = min(containment, 0.6)
    shape = SequenceMatcher(None, normalise(query), normalise(name)).ratio()
    value = min(1.0, 0.85 * containment + 0.15 * shape)
    return value, numbers_ok


def score(query, name):
    """How strongly ``name`` answers ``query``, from 0 to 1."""
    return analyse(query, name)[0]


def rank(query, products, minimum=SHOW_MATCH):
    """Products answering ``query``, best first, as ``[(score, product)]``."""
    scored = []
    for product in products or []:
        if not isinstance(product, dict) or not product.get("id"):
            continue
        value = score(query, product.get("name") or "")
        if value >= minimum:
            scored.append((value, product))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("name") or "")))
    return scored


def auto_pick(query, products, threshold=AUTO_MATCH):
    """The one product a line clearly means, or None when it is ambiguous.

    Two ways to be sure, both of which need the numbers to line up when the
    customer gave any: a near-exact title, or a clearly best candidate that
    leaves the runner-up well behind. A tie is never a match - picking between
    two equal candidates is how the wrong card reaches a customer.
    """
    scored = rank(query, products)
    if not scored:
        return None
    best, product = scored[0]
    _value, numbers_ok = analyse(query, product.get("name") or "")
    if numbers_ok and best >= 0.75:
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if best - runner_up >= 0.20:
            return product
    if best < threshold:
        return None
    if len(scored) > 1 and scored[1][0] == best:
        return None
    if _numbers(query) and not numbers_ok:
        return None
    return product


def search_terms(line):
    """Progressively broader search terms for one pasted line.

    Sites match on the words they store, and a customer's wording often misses
    ("OPC" for "O-Pee-Chee"). Trying the whole line first keeps an exact title
    fast; falling back to the distinctive words still finds the card when the
    set name does not survive the trip.
    """
    text = clean_card_line(line)
    terms = [text]
    words = [w for w in normalise(text).split() if len(w) > 2]
    #  Longest first: players and sets are longer than grades and numbers.
    if len(words) > 1:
        terms.append(" ".join(sorted(words, key=len, reverse=True)[:2]))
    if words:
        terms.append(max(words, key=len))
    seen, unique = set(), []
    for term in terms:
        key = term.lower()
        if term and key not in seen:
            seen.add(key)
            unique.append(term)
    return unique


def merge_duplicates(plan):
    """Collapse repeated products into one line item with a quantity."""
    order, index = [], {}
    for item in plan or []:
        product_id = item.get("product_id")
        if not product_id:
            continue
        if product_id in index:
            order[index[product_id]]["quantity"] += int(item.get("quantity") or 1)
        else:
            index[product_id] = len(order)
            order.append({"product_id": product_id,
                          "quantity": int(item.get("quantity") or 1),
                          "line": item.get("line", ""),
                          #  Kept so the price can be shown before sending.
                          "product": item.get("product") or {}})
    return order


# ------------------------------------------------------------- the order itself
def line_item_payload(plan):
    """``line_items`` for the REST API from a matched plan."""
    return [{"product_id": int(item["product_id"]),
             "quantity": int(item.get("quantity") or 1)}
            for item in merge_duplicates(plan)]


def price_of(product):
    """A product's active price as a float, or None when it has none."""
    try:
        return float(str((product or {}).get("price") or "").strip())
    except (TypeError, ValueError):
        return None


def estimate_total(plan, discount_percent=0):
    """What the order should come to, for showing the user before sending."""
    total, priced = 0.0, 0
    for item in merge_duplicates(plan):
        price = price_of(item.get("product") or {})
        if price is None:
            continue
        total += price * int(item.get("quantity") or 1)
        priced += 1
    discount = 0.0
    if discount_percent:
        discount = round(total * float(discount_percent) / 100.0, 2)
    return {"subtotal": round(total, 2), "discount": discount,
            "total": round(total - discount, 2), "priced": priced,
            "unpriced": len(merge_duplicates(plan)) - priced}


def fee_lines(discount_percent, discount_amount):
    """A manual discount, as the negative fee line WooCommerce understands.

    Only produced when a discount was actually asked for, so an ordinary
    order carries no fee rows at all.
    """
    if not discount_percent or discount_amount <= 0:
        return []
    return [{"name": "Discount %s%%" % ("%g" % float(discount_percent)),
             "total": "%.2f" % -float(discount_amount)}]


def order_payload(plan, discount_percent=0, note=None, status="pending"):
    """The body for a new order. Nothing is paid and nothing is emailed.

    ``pending`` is deliberate: the order is a draft to review in the dashboard,
    not something the customer is asked to pay for before it has been checked.
    """
    estimate = estimate_total(plan, discount_percent)
    payload = {"status": status,
               "set_paid": False,
               "line_items": line_item_payload(plan)}
    fees = fee_lines(discount_percent, estimate["discount"])
    if fees:
        payload["fee_lines"] = fees
    if note:
        payload["customer_note"] = str(note)
    return payload


def merge_line_items(existing, new_items):
    """``line_items`` that add to an order without duplicating what is on it.

    Existing rows are addressed by their own line-item id, which is what tells
    WooCommerce to update a row rather than create another one. A product
    already on the order has its quantity raised instead of being added twice.
    """
    merged = []
    by_product = {}
    for line in existing or []:
        if not isinstance(line, dict) or not line.get("id"):
            continue
        row = {"id": int(line["id"]),
               "quantity": int(line.get("quantity") or 1)}
        if line.get("variation_id"):
            row["variation_id"] = int(line["variation_id"])
        merged.append(row)
        product_id = line.get("product_id")
        if product_id:
            by_product[product_id] = row
    for item in new_items or []:
        product_id = item.get("product_id")
        if not product_id:
            continue
        if product_id in by_product:
            by_product[product_id]["quantity"] += int(item.get("quantity") or 1)
        else:
            row = {"product_id": int(product_id),
                   "quantity": int(item.get("quantity") or 1)}
            merged.append(row)
            by_product[product_id] = row
    return merged


# ------------------------------------------------------------------- transport
def orders_admin_url(site):
    """The dashboard's order list, for when the API cannot be used."""
    root = str(site or "").strip().rstrip("/")
    if not root.lower().startswith(("http://", "https://")):
        return ""
    return root + "/wp-admin/admin.php?page=wc-orders"


def order_edit_url(site, order_id):
    root = str(site or "").strip().rstrip("/")
    if not root.lower().startswith(("http://", "https://")) or not order_id:
        return ""
    return "%s/wp-admin/post.php?post=%s&action=edit" % (root, order_id)


def _http(request, timeout, opener=None):
    if opener is None:
        def opener(req, timeout):
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, response.read()
    try:
        return opener(request, timeout)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        return exc.code, body
    except urllib.error.URLError as exc:
        raise OrderError("Could not reach the website (%s)."
                         % getattr(exc, "reason", exc))
    except OrderError:
        raise
    except Exception as exc:
        raise OrderError("Could not reach the website (%s)." % exc)


def _json(body):
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return body.decode("utf-8", "replace")[:300]


def _wp_message(payload):
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return ""


def _explain(status, payload, action):
    wp = _wp_message(payload)
    if status == 401:
        base = ("The website rejected the WooCommerce keys (HTTP 401). "
                "Changing orders needs Read/Write keys, not Read-only.")
    elif status == 403:
        base = ("Those keys cannot change orders (HTTP 403). Re-create them "
                "with Read/Write access.")
    elif status == 404:
        base = "That order number does not exist on the website (HTTP 404)."
    else:
        base = "The website refused to %s (HTTP %s)." % (action, status)
    return base + (" WordPress said: %s" % wp if wp else "")


def api_request(site, key, secret, path, method="GET", params=None,
                payload=None, timeout=60, retries=2, opener=None):
    """One REST call. Returns ``(status, parsed)``; raises on a failed write."""
    root = str(site or "").strip().rstrip("/")
    if not root.lower().startswith(("http://", "https://")):
        raise OrderError("No website address is saved, so the order cannot be "
                         "created.")
    if not (key and secret):
        raise OrderError("The order needs WooCommerce keys saved in "
                         "woo-keys.txt.")
    query = dict(params or {})
    query["consumer_key"] = key
    query["consumer_secret"] = secret
    url = "%s%s?%s" % (root, path, urllib.parse.urlencode(query))
    data = None
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method,
                                     headers=headers)
    last = ""
    for _attempt in range(max(1, retries)):
        try:
            status, raw = _http(request, timeout, opener)
        except OrderError as exc:
            last = exc.message
            continue
        parsed = _json(raw)
        if 200 <= status < 300:
            return status, parsed
        if status >= 500:
            last = _explain(status, parsed, "read the order")
            continue
        raise OrderError(_explain(status, parsed, "create the order"),
                         status=status)
    raise OrderError(last or "The website did not answer.")


def create_order(site, key, secret, plan, discount_percent=0, note=None,
                 timeout=60, opener=None):
    """Create a draft order for the matched plan. Returns the order."""
    payload = order_payload(plan, discount_percent, note)
    if not payload["line_items"]:
        raise OrderError("No cards are matched, so there is nothing to order.")
    status, order = api_request(site, key, secret, ORDERS_PATH, method="POST",
                                payload=payload, timeout=timeout,
                                opener=opener)
    if not isinstance(order, dict) or not order.get("id"):
        raise OrderError("The website accepted the order but did not return "
                         "its number, so check the order list before sending "
                         "the customer anything.")
    return order


def read_order(site, key, secret, order_id, timeout=60, opener=None):
    """One order, by its number or id."""
    try:
        order_id = int(str(order_id).strip().lstrip("#"))
    except (TypeError, ValueError):
        raise OrderError("%r is not an order number." % (order_id,))
    _status, order = api_request(site, key, secret,
                                 "%s/%d" % (ORDERS_PATH, order_id),
                                 timeout=timeout, opener=opener)
    if not isinstance(order, dict) or not order.get("id"):
        raise OrderError("Order %s was not found on the website." % order_id)
    return order


def add_to_order(site, key, secret, order_id, plan, discount_percent=0,
                 note=None, timeout=60, opener=None):
    """Add the matched cards to an order that already exists.

    The order's own line-item ids are sent back with the new rows, so existing
    cards keep their place and a card already on the order gains quantity
    instead of appearing twice.
    """
    order = read_order(site, key, secret, order_id, timeout=timeout,
                       opener=opener)
    new_items = line_item_payload(plan)
    if not new_items:
        raise OrderError("No cards are matched, so there is nothing to add.")
    payload = {"line_items": merge_line_items(order.get("line_items"),
                                             new_items)}
    if discount_percent:
        existing_fees = [{"name": f.get("name") or "Fee",
                          "total": str(f.get("total") or "0")}
                         for f in order.get("fee_lines") or []
                         if isinstance(f, dict)]
        estimate = estimate_total(plan, discount_percent)
        payload["fee_lines"] = existing_fees + fee_lines(
            discount_percent, estimate["discount"])
    if note:
        payload["customer_note"] = str(note)
    status, updated = api_request(
        site, key, secret, "%s/%d" % (ORDERS_PATH, int(order["id"])),
        method="PUT", payload=payload, timeout=timeout, opener=opener)
    if not isinstance(updated, dict) or not updated.get("id"):
        raise OrderError("The website did not confirm the order update.")
    return updated
