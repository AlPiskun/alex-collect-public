"""An order's cards, nine at a time, and which ones still need a photograph.

A card sheet holds nine cards, so photographing replacements for a batch is a
job in nines: split one sheet, match nine images to nine cards, do the next
nine. After a sale the cards that need new pictures are the ones the order
took a copy from **and** that can still be bought - a card that went to zero
is sold out, and nobody needs a photograph of a card that is no longer for
sale.

The queue remembers which cards have already been photographed, so the second
sitting starts at the tenth card instead of at the first one again, and the
order of the nine can be rearranged when the scans do not come off the sheet
in the order the website lists the cards.

Nothing here talks to Tk or to the network: the order and its products are
read by the caller and handed in, so the whole thing can be checked without a
display and without a shop.
"""

from __future__ import annotations

import json
from pathlib import Path

#: A card sheet holds nine cards, so nine is the size of one sitting.
SHEET = 9
#: Where the app remembers which cards have been photographed.
STATE_NAME = "photo-queue.json"
#: How many orders are remembered. Older ones are dropped rather than growing
#: the file for ever; a card that is still waiting keeps its place because the
#: order it came from is the one being worked on.
STATE_LIMIT = 20


class QueueError(Exception):
    """A queue that cannot be built or read, in words the person can act on."""


def _int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def stock_of(product):
    """How many of a product can still be bought, or ``None`` when unknown.

    A product that does not track its stock has no number to compare - and
    guessing one would put a card in a queue whose listing may not even be for
    sale any more.
    """
    product = product or {}
    if not product.get("manage_stock"):
        return None
    quantity = product.get("stock_quantity")
    if quantity is None:
        return None
    return _int(quantity, 0) if str(quantity).strip().lstrip("-").isdigit() \
        else None


def from_order(order, products):
    """The order's cards that still need photographing, in the order sold.

    ``products`` maps a product id to the product as the website returns it.
    Every line item that is a real product is accounted for: the ones that go
    in the queue, and - in ``skipped`` - the ones that do not, each with the
    reason, because a card that quietly disappears from a queue is a card
    nobody photographs.
    """
    order = order or {}
    products = products or {}
    rows, skipped, seen = [], [], {}
    for line in order.get("line_items") or []:
        if not isinstance(line, dict):
            continue
        product_id = _int(line.get("product_id") or line.get("variation_id"), 0)
        if not product_id:
            #  A fee, shipping, or a custom line: not a card, and not
            #  something to apologise for.
            continue
        name = " ".join(str(line.get("name") or "").split())
        quantity = max(1, _int(line.get("quantity"), 1))
        if product_id in seen:
            #  The shop merges duplicate lines, but an imported order can
            #  still carry the same card twice; one photograph is enough.
            seen[product_id]["sold"] += quantity
            continue
        product = products.get(product_id)
        if not isinstance(product, dict) or not product:
            skipped.append({"name": name or "product %d" % product_id,
                            "id": product_id,
                            "why": "the website did not return this product, "
                                   "so its stock could not be read"})
            continue
        row = {"id": product_id,
               "name": " ".join(str(product.get("name") or name).split()),
               "sku": str(product.get("sku") or line.get("sku") or "").strip(),
               "stock": stock_of(product),
               "sold": quantity,
               "images": len(product.get("images") or [])}
        seen[product_id] = row
        if row["stock"] is None:
            skipped.append({"name": row["name"], "id": product_id,
                            "why": "this product does not track its stock, so "
                                   "there is no count that says it is still "
                                   "for sale"})
            continue
        if row["stock"] <= 0:
            skipped.append({"name": row["name"], "id": product_id,
                            "why": "sold out - nothing left to photograph"})
            continue
        rows.append(row)
    return {"number": str(order.get("number") or order.get("id") or "").strip(),
            "customer": _customer(order),
            "rows": rows,
            "skipped": skipped}


def _customer(order):
    billing = (order or {}).get("billing") or {}
    name = " ".join(part for part in
                    (str(billing.get("first_name") or "").strip(),
                     str(billing.get("last_name") or "").strip()) if part)
    return name or str((order or {}).get("customer_name") or "").strip()


def still_to_do(queue, done):
    """The rows that have not been photographed yet, in queue order."""
    done = {str(item) for item in (done or ())}
    return [row for row in (queue or {}).get("rows") or []
            if str(row.get("id")) not in done]


def next_batch(queue, done, size=SHEET):
    """One sitting: the next nine cards, and how many wait behind them."""
    left = still_to_do(queue, done)
    size = max(1, _int(size, SHEET))
    return left[:size], left[size:]


def move(rows, index, delta):
    """Move one row up or down inside the sitting; returns where it landed.

    The nine cards are photographed in the order the scan holds them, so when
    the sheet and the website disagree the list has to be rearrangeable before
    the images are matched to it.
    """
    rows = rows if isinstance(rows, list) else []
    if not rows:
        return index
    try:
        index = int(index)
    except (TypeError, ValueError):
        return index
    target = index + (1 if _int(delta, 0) > 0 else -1)
    if not (0 <= index < len(rows)) or not (0 <= target < len(rows)):
        return index
    rows[index], rows[target] = rows[target], rows[index]
    return target


def describe_batch(batch, total=None):
    """One line per card for the list the panel shows."""
    lines = []
    for index, row in enumerate(batch or [], start=1):
        stock = row.get("stock")
        left = "%d in stock" % stock if isinstance(stock, int) else "stock unknown"
        line = "%d. %s" % (index, row.get("name") or "(untitled)")
        if row.get("sku"):
            line += "   [%s]" % row["sku"]
        lines.append("%s  -  %s" % (line, left))
    return lines


def headline(queue, batch, waiting, done_count=0):
    """One sentence saying which nine this sitting is and what is left."""
    queue = queue or {}
    number = queue.get("number") or "?"
    if not (queue.get("rows") or []):
        return ("No card on order %s still needs a photograph." % number
                if number != "?" else
                "No queue yet - type an order number and build one.")
    if not batch:
        return ("Every card on order %s has been photographed." % number
                if not waiting else
                "%d card%s photographed; %d still waiting."
                % (done_count, "" if done_count == 1 else "s", len(waiting)))
    text = ("Order %s: %d card%s in this sitting"
            % (number, len(batch), "" if len(batch) == 1 else "s"))
    if waiting:
        text += ", %d behind %s" % (len(waiting),
                                    "it" if len(batch) == 1 else "them")
    text += "."
    if done_count:
        text += " %d already photographed." % done_count
    return text


def load_state(path):
    """The remembered queues; an unreadable file remembers nothing."""
    try:
        data = json.loads(Path(str(path)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"orders": {}}
    if not isinstance(data, dict) or not isinstance(data.get("orders"), dict):
        return {"orders": {}}
    return {"orders": data["orders"]}


def save_state(path, state):
    """Write the remembered queues, keeping only the most recent orders."""
    orders = dict((state or {}).get("orders") or {})
    if len(orders) > STATE_LIMIT:
        keep = list(orders)[-STATE_LIMIT:]
        orders = {key: orders[key] for key in keep}
    path = Path(str(path))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"orders": orders}, indent=1,
                                   ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        raise QueueError("What has been photographed so far could not be "
                         "saved to %s (%s)." % (path, exc))
    return path


def done_for(state, number):
    """The cards of one order that have already been photographed."""
    entry = ((state or {}).get("orders") or {}).get(str(number)) or {}
    return [str(item) for item in (entry.get("done") or [])]


def remember(state, number, ids):
    """Add photographed cards to an order's memory, in place."""
    state = state if isinstance(state, dict) else {"orders": {}}
    orders = state.setdefault("orders", {})
    entry = orders.setdefault(str(number), {"done": []})
    done = [str(item) for item in (entry.get("done") or [])]
    for item in ids or []:
        text = str(item)
        if text and text not in done:
            done.append(text)
    entry["done"] = done
    #  Re-inserted so the order just worked on is the last one kept when the
    #  file is trimmed.
    orders.pop(str(number), None)
    orders[str(number)] = entry
    return done


def forget(state, number):
    """Drop an order's memory, so every card is offered again."""
    orders = (state or {}).get("orders") or {}
    orders.pop(str(number), None)
    return orders
