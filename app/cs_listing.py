#!/usr/bin/env python3
"""Put a website product onto CanadianShopper - the CSV the shop already imports.

CanadianShopper has no API this app may write listings through, and it does not
need one: the import template the pipeline already writes is the supported way
in, and it is the same fourteen columns here. What changes is where the values
come from. The pipeline reads them from the AI's listing text for cards scanned
in a batch; this module reads them from the product that is *already on the
website* - its title, its price, its own photo URL, its stock count - so a card
that sold out on CanadianShopper and only lives on the website can be put back
by exporting exactly the row the pipeline would have written.

Two things are deliberately not done here: nothing is invented (a product with
no price gets a blank price, not a guess) and nothing is imported (the CSV is
written; importing is the shop's own step, and the drafts it creates are what
the Import / publish drafts panel then reviews).
"""
import csv
import html
import re
from datetime import datetime
from pathlib import Path

#  The CanadianShopper import template, in the importer's own order. Defined
#  here once and imported by the pipeline, so the batch writer and this one
#  cannot drift apart.
CANADIANSHOPPER_FIELDNAMES = [
    "title", "price_cad", "category", "description", "image_url",
    "inventory", "is_made_to_order", "ship_from_province",
    "shipping_flat_cad", "free_shipping", "handling_days", "transit_days",
    "sizes", "colors",
]
CANADIANSHOPPER_BATCH_SIZE = 500

#  A description longer than this is a page of marketing, not a card listing.
MAX_DESCRIPTION = 900

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def defaults(settings=None):
    """The category and shipping the import uses, from the same settings.

    These are the keys the pipeline reads, with the same fallbacks, so a card
    listed from this panel arrives on CanadianShopper looking exactly like a
    card that came out of a batch.
    """
    if settings is None:
        from user_settings import load_user_settings
        settings = load_user_settings()
    settings = settings or {}
    return {
        "category": str(settings.get("canadianshopper_category",
                                     "Antiques & Collectibles")),
        "ship_from_province": str(settings.get("canadianshopper_ship_from_province",
                                               "ON")),
        "shipping_flat_cad": str(settings.get("canadianshopper_shipping_flat",
                                              "4.00")),
        "free_shipping": ("true" if settings.get("canadianshopper_free_shipping",
                                                 False) else "false"),
        "handling_days": str(settings.get("canadianshopper_handling_days", 2)),
        "transit_days": str(settings.get("canadianshopper_transit_days", 5)),
    }


def plain_text(value, limit=MAX_DESCRIPTION):
    """A product's description as one line of plain words."""
    text = html.unescape(_TAG.sub(" ", str(value or "")))
    text = _SPACE.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[:max(1, limit - 1)].rstrip() + "\u2026"
    return text


def image_url(product):
    """The product's main photo, as the shop already serves it.

    The website hosts the picture, so the listing points at that URL rather
    than at a file this app would have to upload again - and a product whose
    photo was never set gets a blank, never a broken link.
    """
    for image in (product or {}).get("images") or []:
        if not isinstance(image, dict):
            continue
        src = str(image.get("src") or "").strip()
        if src.lower().startswith(("http://", "https://")):
            return src
    return ""


def price_text(product):
    """The product's price as ``12.00``, or blank when it has none."""
    for key in ("price", "regular_price", "sale_price"):
        raw = str((product or {}).get(key) or "").strip()
        if not raw:
            continue
        try:
            return "%.2f" % float(raw)
        except (TypeError, ValueError):
            continue
    return ""


def title_of(product):
    """The card's name, with the whitespace a title field cannot carry."""
    return _SPACE.sub(" ", str((product or {}).get("name") or "")).strip()


def row_for(product, inventory, values=None):
    """One import row: the product as it should appear on CanadianShopper."""
    values = values or defaults()
    description = plain_text((product or {}).get("short_description")) or \
        plain_text((product or {}).get("description"))
    try:
        quantity = max(0, int(inventory))
    except (TypeError, ValueError):
        quantity = 0
    return {
        "title": title_of(product),
        "price_cad": price_text(product),
        "category": values["category"],
        "description": description,
        "image_url": image_url(product),
        "inventory": str(quantity),
        "is_made_to_order": "false",
        "ship_from_province": values["ship_from_province"],
        "shipping_flat_cad": values["shipping_flat_cad"],
        "free_shipping": values["free_shipping"],
        "handling_days": values["handling_days"],
        "transit_days": values["transit_days"],
        "sizes": "",
        "colors": "",
    }


def build_rows(products, values=None):
    """``(rows, notes)`` for ``[(product, inventory), ...]``.

    ``notes`` says what is missing from each row that could make the importer
    refuse it or make the listing look wrong - a card without a photo or a
    price is still written (dropping it silently would leave the person
    wondering where it went), but the person is told before importing.
    """
    rows, notes = [], []
    for product, inventory in products or []:
        title = title_of(product)
        if not title:
            notes.append(("a product with no name", "it cannot be listed "
                          "without a title"))
            continue
        row = row_for(product, inventory, values)
        if not row["image_url"]:
            notes.append((title, "no photo on the website, so the listing has "
                                 "no image"))
        if not row["price_cad"]:
            notes.append((title, "no price on the website, so the price is "
                                 "blank"))
        if row["inventory"] == "0":
            notes.append((title, "the website has none in stock, so it would "
                                 "be listed out of stock"))
        rows.append(row)
    return rows, notes


def import_report(written, answer):
    """What the plugin's own import result says about each file written.

    ``written`` is ``[(path, row_count), ...]``; ``answer`` the plugin's
    ``{"imported": [...], "failed": [...]}``. A file the result does not
    mention is *unknown*, never assumed imported: an import that did not
    confirm itself has not happened as far as the person's shop is concerned,
    and saying so costs nothing while the opposite would hide a batch of
    drafts that is not there.
    """
    written = list(written or [])
    if not isinstance(answer, dict):
        answer = {}

    def entries(name):
        rows = []
        for entry in answer.get(name) or []:
            if isinstance(entry, dict):
                rows.append(entry)
        return rows

    imported, failed, unknown = [], [], []
    for path, count in written:
        name = Path(str(path)).name
        hit_fail = None
        for entry in entries("failed"):
            label = str(entry.get("file") or entry.get("csv") or
                        entry.get("path") or "")
            if label and Path(label).name == name:
                hit_fail = entry
                break
        if hit_fail is not None:
            failed.append({"file": name,
                           "why": str(hit_fail.get("why") or
                                      hit_fail.get("reason") or
                                      hit_fail.get("message") or
                                      "the plugin gave no reason")})
            continue
        hit = None
        for entry in entries("imported"):
            label = str(entry.get("file") or entry.get("csv") or
                        entry.get("path") or "")
            if label and Path(label).name == name:
                hit = entry
                break
        if hit is None:
            unknown.append({"file": name, "rows": count})
            continue
        try:
            made = int(hit.get("drafts") if hit.get("drafts") is not None
                       else hit.get("rows") or count)
        except (TypeError, ValueError):
            made = count
        imported.append({"file": name, "rows": count, "drafts": made})
    return {"imported": imported, "failed": failed, "unknown": unknown}


def write_rows(rows, folder, batch_size=CANADIANSHOPPER_BATCH_SIZE,
               when=None):
    """Write the import CSV(s); returns ``[(path, row_count), ...]``.

    The filename is the pipeline's own (``canadianshopper_import_<stamp>_NN_of_MM``),
    so the batch that lists a card from this panel is picked up by the same
    tools as any other batch - the combiner, the cs-ready step, and the
    importer itself.
    """
    rows = list(rows or [])
    if not rows:
        return []
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    size = max(1, int(batch_size))
    total = (len(rows) + size - 1) // size
    written = []
    for index in range(total):
        batch = rows[index * size:(index + 1) * size]
        path = folder / ("canadianshopper_import_%s_%02d_of_%02d.csv" %
                         (stamp, index + 1, total))
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=CANADIANSHOPPER_FIELDNAMES,
                                    lineterminator="\n",
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(batch)
        written.append((path, len(batch)))
    return written


def describe(rows, limit=12):
    """The confirmation's lines: what would appear on CanadianShopper."""
    lines = []
    for row in (rows or [])[:limit]:
        price = row["price_cad"] or "no price"
        photo = "photo from the website" if row["image_url"] else "no photo"
        lines.append("  %s\n      %s  -  %s in stock  -  %s" %
                     (row["title"][:90], price, row["inventory"], photo))
    return lines


def summary(rows, values=None):
    """One sentence saying exactly what an import file would create."""
    values = values or defaults()
    count = len(rows or [])
    if not count:
        return "Nothing to list."
    return ("%d listing%s would be created as unpublished drafts: %s, shipping "
            "flat %s from %s, handling %s day(s), transit %s day(s)." %
            (count, "" if count == 1 else "s", values["category"],
             values["shipping_flat_cad"], values["ship_from_province"],
             values["handling_days"], values["transit_days"]))


def listing_products(rows, catalog):
    """``([(product, inventory), ...], missing)`` for the stock panel's rows.

    ``rows`` are the panel's action rows, ``catalog`` the products the last
    comparison read, keyed by ``str(id)``. Only a card that exists on the
    website can be listed, and only one the comparison actually saw - a row
    whose product is no longer in memory is reported as missing rather than
    fetched again behind the person's back. A row that is on both sites is not
    a listing job at all, so it is skipped here too rather than trusting the
    caller to have filtered it.
    """
    wanted, missing = [], []
    for row in rows or []:
        if row.get("kind") not in (None, "only-woo"):
            continue
        product = (catalog or {}).get(str(row.get("woo_id")))
        if not isinstance(product, dict):
            missing.append(row.get("card") or "a card")
            continue
        wanted.append((product, row.get("woo")))
    return wanted, missing
