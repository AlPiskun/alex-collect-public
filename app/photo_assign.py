"""Line the card images up with the products they belong to.

Replacing a photo means answering one question over and over: which product is
this picture? Answering it one card at a time is slow, and a sheet holds nine
cards, so this builds the worksheet a sitting fills in: one row per card image
on the front sheets, each row carrying a product and a status, in the order the
images were scanned.

The cards arrive as an ordered list - the nine the photo queue picked out of an
order, or the names pasted into the panel and matched one by one. A line that
matches nothing keeps its words so the row can be searched for by hand.

Nothing here talks to Tk or the network: ``search`` is a callable, so the whole
worksheet can be built and checked without a display or a store.
"""

#  Row statuses. "matched" is the only one that can be applied without asking.
MATCHED = "matched"
MISSING = "no match"
EMPTY = "no card"


def front_tiles(pool):
    """The card images a sitting photographs, in reading order.

    Fronts come first and images whose sheet was never marked follow them.
    Backs are excluded: a card is named once, and its back belongs to the same
    row through the slot it was scanned in.
    """
    tiles = [tile for tile in pool.tiles()
             if tile.get("side") in ("front", "")]
    return sorted(tiles, key=lambda t: (
        0 if t.get("side") == "front" else 1,
        str(t.get("sheet") or ""),
        int(t.get("position") or 0)))


def rows_from_products(pool, products, names=None):
    """A worksheet from an ordered list of cards - the Nth card, the Nth image.

    ``products`` holds a product or ``None`` per card: ``None`` is a card the
    website search could not match, and it keeps its ``names`` entry instead of
    being dropped, so the row still says what it was and can be searched for by
    hand. Both lists come from the same sitting, so their order is the one the
    user already arranged.
    """
    tiles = front_tiles(pool)
    products = list(products or [])
    names = list(names or [])
    rows = []
    for index, tile in enumerate(tiles):
        product = products[index] if index < len(products) else None
        said = str(names[index]).strip() if index < len(names) else ""
        row = {"tile": tile, "title": said, "product": None,
               "status": EMPTY, "terms": [], "candidates": []}
        if isinstance(product, dict) and product.get("id"):
            row["product"] = product
            row["title"] = str(product.get("name") or said)
            row["status"] = MATCHED
        elif said:
            #  The card was named and the search did not find it. Saying "no
            #  match" keeps it visible; the typed words stay so the row can be
            #  looked up again without pasting the whole list.
            row["status"] = MISSING
        rows.append(row)
    return rows


def summary(rows):
    """Counts per status, for the one line the window shows."""
    counts = {MATCHED: 0, MISSING: 0, EMPTY: 0}
    for row in rows or []:
        counts[row.get("status", MISSING)] = \
            counts.get(row.get("status", MISSING), 0) + 1
    return counts


def ready(rows):
    """The rows that can be applied without asking anything."""
    return [row for row in rows or []
            if row.get("status") == MATCHED and row.get("product")
            and row.get("tile")]


def headline(rows):
    """One sentence describing the worksheet, for the panel and the console."""
    counts = summary(rows)
    parts = []
    if counts[MATCHED]:
        parts.append("%d ready" % counts[MATCHED])
    if counts[MISSING]:
        parts.append("%d matched nothing" % counts[MISSING])
    if counts[EMPTY]:
        parts.append("%d with no card" % counts[EMPTY])
    return ", ".join(parts) if parts else "nothing to assign"


def replace_title(rows, index, product):
    """Point one row at a product the user picked by hand."""
    if not (0 <= index < len(rows)):
        return False
    row = rows[index]
    row["product"] = product
    row["status"] = MATCHED if product and product.get("id") else MISSING
    return True
