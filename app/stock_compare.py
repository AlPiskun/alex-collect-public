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

from pathlib import Path

import woo_orders

#  Below this the two titles are not the same card. Higher than the order
#  panel's search threshold on purpose: that list is a suggestion a person
#  picks from, this one is an accusation.
DEFAULT_MIN_SCORE = 0.55


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


def plugin_items(payload):
    """The listings a plugin reported, in this module's one shape.

    The plugin writes ``{"items": [...]}``, each entry with a title, a SKU when
    it has one, and an inventory number. Rows without a usable number are
    dropped rather than guessed at.
    """
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("listings") or []
    items = []
    for row in payload or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("title") or row.get("name") or "").strip()
        quantity = row.get("inventory")
        if quantity is None:
            quantity = row.get("quantity")
        if not name or quantity is None:
            continue
        try:
            qty = int(quantity)
        except (TypeError, ValueError):
            continue
        items.append({"name": name,
                      "sku": str(row.get("sku") or "").strip(),
                      "qty": qty,
                      "id": row.get("id")})
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


def _digits(name):
    return {word for word in woo_orders.normalise(name).split()
            if word.isdigit()}


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

    scored = []
    for item in left:
        numbers = _digits(item["name"])
        for index, candidate in enumerate(other):
            if index in used_other:
                continue
            #  Cheap rejection: two cards whose numbers share nothing are two
            #  different cards, and a catalogue is mostly cards.
            if numbers and _digits(candidate["name"]) and \
                    not (numbers & _digits(candidate["name"])):
                continue
            value, numbers_ok = woo_orders.analyse(item["name"],
                                                   candidate["name"])
            if value < minimum:
                continue
            scored.append((value, numbers_ok, item, index))
    scored.sort(key=lambda row: (-row[0], not row[1]))

    used_woo = set()
    for value, _numbers_ok, item, index in scored:
        if index in used_other or id(item) in used_woo:
            continue
        used_other.add(index)
        used_woo.add(id(item))
        pairs.append({"woo": item, "other": other[index], "by": "title"})

    matched = {id(pair_row["woo"]) for pair_row in pairs}
    only_woo = [item for item in woo if id(item) not in matched]
    only_other = [item for index, item in enumerate(other)
                  if index not in used_other]
    return pairs, only_woo, only_other


def differences(pairs):
    """The pairs whose quantities disagree, worst gap first."""
    rows = []
    for row in pairs or []:
        woo_qty = int(row["woo"].get("qty") or 0)
        other_qty = int(row["other"].get("qty") or 0)
        if woo_qty == other_qty:
            continue
        rows.append({"card": row["woo"].get("name") or row["other"].get("name") or "",
                     "woo": woo_qty, "other": other_qty,
                     "gap": woo_qty - other_qty, "by": row.get("by", "title")})
    rows.sort(key=lambda row: (-abs(row["gap"]), row["card"].lower()))
    return rows


def summary(rows, pairs, only_woo, only_other):
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
        left_out.append("%d only on CanadianShopper" % len(only_other))
    if left_out:
        line += " Not compared: " + ", ".join(left_out) + "."
    return line


def describe(rows, limit=40):
    """Console lines for the disagreements."""
    lines = []
    for row in rows:
        gap = "" if row["gap"] == 0 else "  (%+d)" % row["gap"]
        lines.append("  %-52s website %-4d CanadianShopper %-4d%s" % (
            row["card"][:52], row["woo"], row["other"], gap))
    if len(lines) > limit:
        hidden = len(lines) - limit
        lines = lines[:limit] + ["  ... and %d more." % hidden]
    return lines


def label(row):
    """One disagreement as it appears in the panel list."""
    return "%s  -  website %d  /  CanadianShopper %d" % (
        row["card"], row["woo"], row["other"])
