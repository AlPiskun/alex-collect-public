#!/usr/bin/env python3
"""Write a stock count onto one website product - the reverse of the usual fix.

The stock panel's default direction is CanadianShopper <- website, because the
website is right far more often than not. This module exists for the other
case: the card is sold out on the website but still listed elsewhere, or the
count elsewhere is the one that was kept up to date, and the *website* is the
side that is wrong.

It changes one field, ``stock_quantity``, on one product, by id, and then reads
the answer back: a 200 that did not actually store the number is reported as a
failure rather than a success, because a wrong count is what the whole panel
exists to catch. Nothing else is touched - no price, no status, no images, no
product creation, no deletion.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "AlexCollect/2.90"
WC_PRODUCTS_PATH = "/wp-json/wc/v3/products"


class StockWriteError(Exception):
    """A count could not be written, with a sentence saying why.

    ``status`` is the site's HTTP status when it answered at all; ``hint`` is
    what the person can do about it, and is empty when there is nothing to do.
    """

    def __init__(self, message, hint="", status=0):
        super().__init__(message)
        self.message = str(message)
        self.hint = str(hint or "")
        self.status = int(status or 0)


def _explain(status, payload):
    """The site's refusal, in the words of the person who has to fix it."""
    said = ""
    if isinstance(payload, dict):
        said = str(payload.get("message") or "").strip()
    said = said[:300]
    if status == 401:
        return StockWriteError(
            "The website rejected the WooCommerce keys (HTTP 401).",
            "Writing a stock count needs a key pair with Read/Write access; "
            "the keys in woo-keys.txt are read-only. Replace them, or fix these "
            "counts on the website itself.", status)
    if status == 403:
        return StockWriteError(
            "Those keys are not allowed to change products (HTTP 403).",
            "Re-create the WooCommerce keys with Read/Write access.", status)
    if status == 404:
        return StockWriteError(
            "That product is no longer on the website (HTTP 404).",
            "It was deleted or its id changed since the comparison. Compare "
            "again.", status)
    return StockWriteError(
        "The website refused to change the count (HTTP %s)." % status,
        ("WordPress said: %s" % said) if said else "", status)


def _http(request, timeout, opener=None):
    """Send ``request``; ``(status, body)``. Connection trouble is an error."""
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
        raise StockWriteError("Could not reach the website (%s)." %
                              getattr(exc, "reason", exc))
    except StockWriteError:
        raise
    except Exception as exc:
        raise StockWriteError("Could not reach the website (%s)." % exc)


def _json(body):
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return {}


def product_url(site, product_id, key, secret):
    """The product's own REST address, with the keys where hosts keep them.

    The keys travel as query parameters rather than an Authorization header
    because some hosts strip that header before PHP sees it - the same choice
    the photo wiring already makes.
    """
    root = str(site or "").strip().rstrip("/")
    if not root.lower().startswith(("http://", "https://")):
        return ""
    pid = str(product_id or "").strip()
    if not pid.isdigit():
        return ""
    query = urllib.parse.urlencode({"consumer_key": key,
                                    "consumer_secret": secret})
    return "%s%s/%s?%s" % (root, WC_PRODUCTS_PATH, pid, query)


def set_count(site, key, secret, product_id, quantity, timeout=60, retries=2,
              opener=None):
    """Set one product's stock count and confirm the website kept it.

    Returns ``{"id": int, "inventory": int}`` as the website reports it.
    """
    if not (key and secret):
        raise StockWriteError(
            "Writing a count needs the WooCommerce keys.",
            "Fill in woo-keys.txt first.")
    url = product_url(site, product_id, key, secret)
    if not url:
        raise StockWriteError(
            "No website address or product id is available.",
            "Set the store address in User Settings and compare again.")
    if isinstance(quantity, bool) or (
            isinstance(quantity, float) and not quantity.is_integer()):
        raise StockWriteError("That count is not a whole number: %r." %
                              (quantity,))
    try:
        wanted = int(quantity)
    except (TypeError, ValueError):
        raise StockWriteError("That count is not a whole number: %r." %
                              (quantity,))
    if wanted < 0:
        raise StockWriteError("A stock count cannot be negative (%d)." % wanted)
    #  Only the count. A product's manage_stock flag, price and status are the
    #  shop's business and are not this panel's to change.
    body = json.dumps({"stock_quantity": wanted}).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="PUT",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": USER_AGENT})
    last = ""
    for _attempt in range(max(1, retries)):
        try:
            status, raw = _http(request, timeout, opener)
        except StockWriteError as exc:
            last = exc
            continue
        payload = _json(raw)
        if status in (200, 201):
            if not isinstance(payload, dict) or not payload.get("id"):
                raise StockWriteError(
                    "The website answered but did not return the product, so "
                    "the change could not be confirmed.",
                    "Compare again: if the count did change, the row will be "
                    "gone.", status)
            landed = payload.get("stock_quantity")
            if stock_is_managed(payload) and landed is not None and \
                    str(landed).strip() != str(wanted):
                raise StockWriteError(
                    "The website kept its own count (%s) instead of %d." %
                    (landed, wanted),
                    "The product may be stock-managed by a plugin or a "
                    "variable product; change that one on the website.",
                    status)
            return {"id": int(payload["id"]),
                    "inventory": int(landed) if landed is not None else wanted}
        if status >= 500:
            last = _explain(status, payload)
            continue
        raise _explain(status, payload)
    if isinstance(last, StockWriteError):
        raise last
    raise StockWriteError(str(last) or "The website did not finish the change.",
                          "Compare again before trying once more.")


def stock_is_managed(product):
    """Whether the product's count is the one the panel read and wrote."""
    value = (product or {}).get("manage_stock")
    return value is True or str(value).lower() == "true"


def set_counts(site, key, secret, items, opener=None, on_item=None):
    """Write several counts, one product at a time, and survive a failure.

    Every item is ``{"id", "quantity", "title"}``. One card failing must not
    stop the others - the report says exactly what landed and what did not, so
    a half-finished run is not mistaken for a finished one.
    """
    updated, failed = [], []
    for item in items or []:
        entry = None
        try:
            result = set_count(site, key, secret, item.get("id"),
                               item.get("quantity"), opener=opener)
            entry = {"id": result["id"], "inventory": result["inventory"],
                     "title": item.get("title") or ""}
            updated.append(entry)
        except StockWriteError as exc:
            entry = {"id": item.get("id"),
                     "title": item.get("title") or "",
                     "why": exc.message, "hint": exc.hint,
                     "status": exc.status}
            failed.append(entry)
        if callable(on_item):
            try:
                on_item(entry)
            except Exception:
                pass
    return {"updated": updated, "failed": failed}


def describe(items, other_label="CanadianShopper"):
    """The confirmation's lines: the card, the website's count and the new one.

    Each line says where the new number comes from: this is the write in the
    direction that is *not* the default, and the source has to be unmistakable
    at the moment a shop's counts are about to change.
    """
    lines = []
    for item in items or []:
        lines.append("  %s\n      website %s -> %s   (from %s)" % (
            item.get("title") or item.get("card") or "",
            item.get("from"), item.get("to"), other_label))
    return lines


def summary(items, other_label="CanadianShopper"):
    """One sentence saying what a write would do."""
    count = len(items or [])
    if not count:
        return "Nothing to change."
    return "%d website count%s would be set to %s's count." % (
        count, "" if count == 1 else "s", other_label)


def plan_from_rows(rows, other_label="CanadianShopper"):
    """The write plan for the rows of the stock panel, by website product id.

    Only rows where the other site's count is known and a website product
    exists can be written: a card that is only elsewhere has nothing to write.
    """
    plan = []
    for row in rows or []:
        if row.get("kind") != "fix":
            continue
        if row.get("woo_id") is None or row.get("other") is None:
            continue
        if int(row.get("woo") or 0) == int(row.get("other") or 0):
            continue
        plan.append({"id": row["woo_id"], "from": int(row["woo"] or 0),
                     "to": int(row["other"] or 0),
                     "title": row.get("card") or "",
                     "other_label": other_label})
    return plan
