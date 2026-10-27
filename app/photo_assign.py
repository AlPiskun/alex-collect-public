"""Line the card images up with the products they belong to.

Replacing a photo means answering one question over and over: which product is
this picture? The Images panel can answer it one card at a time, but a whole
sheet is quicker when the answer arrives in a batch. This builds the worksheet
that a batch fills in - one row per card image on the front sheets, each row
carrying a product and a status - from either of two sources:

* **titles**, read off the sheet by an AI and pasted in, one per line, in the
  same order as the slots;
* **products**, listed by the user or by an order, in the same order as the
  slots.

Nothing here talks to Tk or the network: ``search`` is a callable, so the whole
worksheet can be built and checked without a display or a store.
"""

import woo_orders

#  Row statuses. "matched" is the only one that can be applied without asking.
MATCHED = "matched"
CHOOSE = "choose"
MISSING = "no match"
EMPTY = "no title"

#  How far ahead the winner has to be before a row may be applied unattended.
#  The order panel accepts a clearly best candidate; replacing a card's photos
#  is destructive and hard to undo, so a near-tie is offered instead. Two
#  cards that share a set and a number score within a thousandth of each
#  other, and that is exactly the pair a wrong pick would confuse.
CLOSE_CALL = 0.05


def parse_titles(text):
    """The titles in a pasted list, one per line, in slot order.

    Numbering, bullets and blank lines are dropped: an AI answer usually
    arrives as ``1. 1972-73 O-Pee-Chee Dave Burrows #133`` or ``- ...``. A line
    beginning with ``#`` is not a comment here - a card number starts that way
    - so only a line that is entirely a comment is skipped.
    """
    titles = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        line = _strip_bullet(line)
        if line:
            titles.append(line)
    return titles


def _strip_bullet(line):
    """Drop a leading ``1.``, ``1)`` or ``-`` marker, keeping card numbers."""
    text = line
    head = text.split(None, 1)
    if head and head[0].rstrip(".)").isdigit() and len(head) > 1:
        #  "12. Card" is a list number. "12 Card" with no dot is kept whole,
        #  because a leading bare number is more likely part of the title.
        if head[0][-1] in ".)":
            text = head[1]
    for marker in ("- ", "* ", "\u2022 "):
        if text.startswith(marker):
            text = text[len(marker):]
            break
    return text.strip()


def front_tiles(pool):
    """The card images a title list can describe, in reading order.

    Titles are read off the front sheet, so fronts come first and images whose
    sheet was never marked are included after them. Backs are excluded: a
    title describes the card, not the reverse of it.
    """
    tiles = [tile for tile in pool.tiles()
             if tile.get("side") in ("front", "")]
    return sorted(tiles, key=lambda t: (
        0 if t.get("side") == "front" else 1,
        str(t.get("sheet") or ""),
        int(t.get("position") or 0)))


def propose(tile, title, search):
    """One row: the image, its title, and the product that best fits it.

    Matches are only "matched" when the pick is unambiguous. Otherwise the row
    keeps the candidates so the user can choose, rather than the run guessing
    and replacing the wrong card.
    """
    row = {"tile": tile, "title": title, "product": None,
           "status": MISSING, "terms": [], "candidates": []}
    if not str(title or "").strip():
        row["status"] = EMPTY
        return row
    terms = woo_orders.search_terms(title)
    row["terms"] = terms
    candidates = []
    for term in terms:
        found = search(term) or []
        if found:
            candidates = [p for p in found if isinstance(p, dict) and p.get("id")]
            if candidates:
                break
    row["candidates"] = candidates
    if not candidates:
        row["status"] = MISSING
        return row
    picked = woo_orders.auto_pick(title, candidates)
    if picked is not None and clear_winner(title, candidates, picked):
        row["product"] = picked
        row["status"] = MATCHED
    else:
        row["status"] = CHOOSE
    return row


def clear_winner(title, candidates, picked, margin=CLOSE_CALL):
    """True when ``picked`` is ahead of every other candidate by ``margin``.

    ``auto_pick`` returns the higher of two near-equal scores; that is fine
    when a person is about to read an order preview, and not fine when the
    difference decides whose photos are replaced.
    """
    try:
        scored = woo_orders.rank(title, candidates)
    except Exception:                                  # never block on scoring
        return True
    picked_id = picked.get("id")
    best = None
    others = []
    for score, product in scored:
        if product.get("id") == picked_id:
            best = score if best is None else max(best, score)
        else:
            others.append(score)
    if best is None or not others:
        return True
    return (best - max(others)) >= margin


def rows_from_titles(pool, titles, search):
    """A worksheet from titles read off the sheets, in slot order.

    A title list longer than the images is trimmed; a sheet with more images
    than titles leaves the extra rows waiting, which is honest - nothing is
    invented for them.
    """
    tiles = front_tiles(pool)
    titles = list(titles or [])
    rows = []
    for index, tile in enumerate(tiles):
        title = titles[index] if index < len(titles) else ""
        rows.append(propose(tile, title, search))
    return rows


def rows_from_products(pool, products):
    """A worksheet from an ordered list of products - cards first.

    The Nth product goes with the Nth card image. Both lists come from the same
    sitting, so their order is the one the user already arranged.
    """
    tiles = front_tiles(pool)
    rows = []
    for index, tile in enumerate(tiles):
        product = products[index] if index < len(products) else None
        row = {"tile": tile, "title": "", "product": None,
               "status": EMPTY, "terms": [], "candidates": []}
        if isinstance(product, dict) and product.get("id"):
            row["product"] = product
            row["title"] = str(product.get("name") or "")
            row["status"] = MATCHED
        rows.append(row)
    return rows


def summary(rows):
    """Counts per status, for the one line the window shows."""
    counts = {MATCHED: 0, CHOOSE: 0, MISSING: 0, EMPTY: 0}
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
    if counts[CHOOSE]:
        parts.append("%d need a choice" % counts[CHOOSE])
    if counts[MISSING]:
        parts.append("%d matched nothing" % counts[MISSING])
    if counts[EMPTY]:
        parts.append("%d with no title" % counts[EMPTY])
    return ", ".join(parts) if parts else "nothing to assign"


def replace_title(rows, index, product):
    """Point one row at a product the user picked by hand."""
    if not (0 <= index < len(rows)):
        return False
    row = rows[index]
    row["product"] = product
    row["status"] = MATCHED if product and product.get("id") else MISSING
    return True
