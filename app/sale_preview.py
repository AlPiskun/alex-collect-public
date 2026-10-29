"""What sold since the last time you looked - before anything is written.

The sold panel could read orders from the website, but only as a side effect
of adding them to the checklist: choosing the API key option and pressing the
button wrote rows, and there was no way to see what the website had returned
first. On a live sale that is the wrong order of operations.

This module holds the read-only half. It turns order records into one row per
card, remembers which orders have already been turned into checklist rows, and
reports what is left - no Tk, no writes to a checklist, and the network call is
injected so the whole thing can be tested without a shop.

"New" here means "not added to the checklist yet", not "not looked at": a
preview that ran and was then ignored must come back on the next preview, or
a sale would quietly disappear. The marker moves forward only after the
checklist tool reports success.
"""

import json
from pathlib import Path

SEEN_FILE = "sold-orders-seen.json"
DEFAULT_STATUSES = ("processing", "completed")
DEFAULT_DAYS = 60


class PreviewError(Exception):
    """The website could not be read, with a sentence saying why."""

    def __init__(self, message, hint=""):
        super().__init__(message)
        self.message = str(message)
        self.hint = str(hint or "")


def channel_kind(channel):
    """How a sale channel can be previewed.

    ``website`` is read straight from the REST API. ``canadianshopper`` needs
    the optional plugin, because the core has no login there. The others have
    no order feed this app can read, so they stay manual.
    """
    channel = str(channel or "").strip().lower()
    if channel == "website":
        return "api"
    if channel in ("canadianshopper", "cs"):
        return "plugin"
    return "manual"


def _items(order):
    """The cards on an order, in either the website's or the plugin's shape.

    WooCommerce calls them ``line_items`` with ``quantity``; the plugin writes
    ``items`` with ``qty``. Both are read here so one preview path serves both
    sources and the plugin does not have to imitate the REST payload.
    """
    for key in ("line_items", "items"):
        items = order.get(key)
        if isinstance(items, list):
            return items
    return []


def order_rows(orders, statuses=DEFAULT_STATUSES, source=""):
    """One row per card on each order, newest first.

    An order is a sale of one or more cards, and the checklist works per card,
    so the flattening happens here rather than in the panel. Rows carry the
    order number, which is what makes "not added yet" possible - and a ``key``
    that includes the source, because a CanadianShopper order 42 and a website
    order 42 are two different sales.
    """
    #  ``statuses`` are WooCommerce's; another source passes () and decides
    #  for itself which of its orders were sales.
    wanted = {str(s).lower() for s in (statuses or ())}
    rows = []
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        number = str(order.get("number") or order.get("id") or "").strip()
        if not number:
            #  Without a number there is nothing to remember the order by, so
            #  it would either be added twice or never again. Both the website
            #  and the plugin always send one; a record that does not is junk.
            continue
        status = str(order.get("status") or "").strip().lower()
        if wanted and status and status not in wanted:
            continue
        date = str(order.get("date_created") or order.get("date") or "")
        date = date.replace("T", " ")[:19]
        for item in _items(order):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("title") or "").strip()
            if not name:
                continue
            try:
                qty = int(item.get("quantity") or item.get("qty") or 1)
            except (TypeError, ValueError):
                qty = 1
            rows.append({"order": number, "id": str(order.get("id") or ""),
                         "date": date, "status": status, "card": name,
                         "qty": qty, "sku": str(item.get("sku") or "").strip(),
                         "key": ("%s:%s" % (source, number)) if source else number})
    merged = {}
    for row in rows:
        #  A plugin may send the same order twice, or split one card across
        #  two line items. Either way it is one row with one quantity: two rows
        #  would add the card to the checklist twice.
        ident = (row["key"], row["card"].lower(), row["sku"])
        if ident in merged:
            merged[ident]["qty"] += row["qty"]
        else:
            merged[ident] = row
    rows = list(merged.values())
    rows.sort(key=lambda r: (r["date"] or "", r["order"] or ""), reverse=True)
    return rows


def _key(row):
    """How a row is remembered: its source plus its order number."""
    return str(row.get("key") or row.get("order") or "")


def unseen(rows, seen):
    """The rows belonging to orders that are not in ``seen``."""
    seen = set(seen or ())
    return [row for row in rows if _key(row) and _key(row) not in seen]


def remember(seen, rows):
    """``seen`` plus every order in ``rows``, as a sorted list."""
    return sorted(set(seen or ()) | {_key(row) for row in rows if _key(row)})


def headline(rows):
    """One line saying how much sold, in the words of a person."""
    if not rows:
        return "No new orders."
    orders = {row["order"] for row in rows}
    cards = sum(max(1, int(row.get("qty") or 1)) for row in rows)
    return "%d card%s on %d order%s, still to add." % (
        cards, "" if cards == 1 else "s",
        len(orders), "" if len(orders) == 1 else "s")


def describe(rows, limit=40):
    """Console lines for a preview: what sold, and nothing about writing it."""
    lines = []
    for row in rows:
        qty = "" if int(row.get("qty") or 1) == 1 else "  x%d" % row["qty"]
        line = "  #%s  %s  %s%s" % (row.get("order") or "?", row.get("date") or "",
                                    row.get("card") or "", qty)
        if row.get("sku"):
            line += "  [%s]" % row["sku"]
        lines.append(line.rstrip())
    if len(lines) > limit:
        hidden = len(lines) - limit
        lines = lines[:limit] + ["  ... and %d more card%s." %
                                 (hidden, "" if hidden == 1 else "s")]
    return lines


def label(row):
    """One preview row as it appears in the list: order, date, card."""
    qty = "" if int(row.get("qty") or 1) == 1 else "  x%d" % row["qty"]
    return "#%s  %s  %s%s" % (row.get("order") or "", (row.get("date") or "")[:10],
                              row.get("card") or "", qty)


def read_orders(fetch, base, key, secret, days=DEFAULT_DAYS,
                statuses=DEFAULT_STATUSES, per_page=100, pages=10, since=""):
    """Every order in the window, page by page, through an injected GET.

    ``fetch`` has sale_inputs.woo_get's shape - (base, path, params, key,
    secret) -> (status, parsed) - so the panel passes the real one and the
    tests pass a dict of canned replies.
    """
    if not base:
        raise PreviewError("No website address is saved yet.",
                           "Set the WooCommerce site URL in User Settings.")
    if not (key and secret):
        raise PreviewError("No website API keys are saved yet.",
                           "Add the read-only key and secret to woo-keys.txt.")
    window = str(since or "").strip()
    if not window and days:
        from datetime import datetime, timedelta, timezone
        start = datetime.now(timezone.utc) - timedelta(days=int(days))
        window = start.strftime("%Y-%m-%dT%H:%M:%S")
    orders = []
    for page in range(1, max(1, pages) + 1):
        params = {"per_page": per_page, "page": page, "orderby": "date",
                  "order": "desc", "status": ",".join(statuses)}
        if window:
            params["after"] = window
        status, data = fetch(base, "/wp-json/wc/v3/orders", params, key, secret)
        if status == 400 and page == 1:
            raise PreviewError(
                "Your website rejected the date window (HTTP 400).",
                "Use a full start date for \"%s\" in User Settings, or clear "
                "the day limit." % window)
        if status in (401, 403):
            raise PreviewError(
                "Your website refused the API keys (HTTP %s)." % status,
                "In WooCommerce > Settings > Advanced > REST API the key must "
                "have Read permission.")
        if status != 200:
            raise PreviewError(
                "Could not read orders from your website (HTTP %s)." % status,
                str(data)[:200])
        rows = data if isinstance(data, list) else []
        orders.extend(rows)
        if len(rows) < per_page:
            break
    return orders


def read_orders_file(path):
    """Orders a plugin wrote as JSON: a list, or an object holding one.

    ``None`` means the file is missing or is not the expected JSON, which is a
    different answer from an empty list: "I could not read it" must never be
    shown as "nothing sold", because the sale that is missing is exactly the
    one the person came to record.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, dict):
        for key in ("orders", "results", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        return None
    return data if isinstance(data, list) else None


def load_seen(path):
    """The order numbers already looked at; an unreadable file is empty."""
    path = Path(path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("orders") or []
    return [str(x) for x in data if str(x).strip()]


def save_seen(path, numbers):
    """Write the order numbers, creating the folder if it is missing."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"orders": sorted(set(numbers or ()))},
                                   indent=1), encoding="utf-8")
    except OSError:
        return False
    return True
