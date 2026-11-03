#!/usr/bin/env python3
"""Cards marked to skip: never offered on an eBay Quick List again.

Both Quick Lists - **Fill your eBay store** in the app and the batch's own
**eBay Quick List** prompt - offer cards that are not on eBay yet. Some of
them should never be listed: a card that is damaged, one the shop wants to
keep, one whose photos are wrong. Retyping that judgement every month is how
a card gets listed by accident on the run where nobody was looking.

So a card can be marked once and it is left out of that list, the page that
was just written, and every list after it. What identifies a card is its SKU
- the same string the website's product carries and the batch's CSV writes -
and only when there is no SKU does a product id or the title stand in, because
a title is a match by words and an id changes if a product is ever recreated.

The file is one small JSON document beside ``gui-settings.json`` in the app
folder, so a bare batch folder that has no app simply finds no skips and
offers every card exactly as it did before: nothing here is required for a
Quick List to work.

Nothing in this module reads a site, writes a listing, or knows about Tk. A
skip is remembered, not applied: the two callers decide which cards they were
about to offer.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

#: The file, beside the app's other settings.
FILE_NAME = "ebay-skips.json"

#: What the file is, so a later version can tell an old one from a new one.
VERSION = 1


def path_for(folder):
    """The skip file in ``folder`` - the app folder, in both callers."""
    return Path(folder) / FILE_NAME


def _text(value):
    return " ".join(str(value if value is not None else "").split())


def title_of(card):
    """The card's name as the shop or the batch spells it."""
    card = card if isinstance(card, dict) else {}
    return _text(card.get("name") or card.get("title") or card.get("seo_title"))


def key_of(card):
    """What identifies this card across lists: its SKU, or a stand-in.

    A SKU is the same string on the website's product, in the batch's CSV and
    on every later list, so it is the key when there is one. A product id is
    next (good enough, though it changes if a product is recreated), and the
    title last, because two cards can share one.
    """
    card = card if isinstance(card, dict) else {}
    sku = _text(card.get("sku")).upper()
    if sku:
        return sku
    product_id = _text(card.get("id") or card.get("product_id"))
    if product_id:
        return "id:%s" % product_id
    title = title_of(card).casefold()
    return "title:%s" % title if title else ""


def clean(key):
    """A key in the one spelling every lookup uses.

    A SKU is compared without its case, and a caller that hands one in as the
    shop spells it must still match the key a later list computes. The two
    stand-in shapes (``id:`` and ``title:``) keep their case, because a title
    is already folded to lower case and an id is the shop's own.
    """
    key = str(key or "").strip()
    if key.casefold().startswith(("id:", "title:")):
        return key
    return key.upper()


def cards(entries):
    """The marked cards in an answer, whatever shape the file had."""
    if isinstance(entries, dict):
        found = entries.get("cards")
        if isinstance(found, dict):
            return found
        #  A file written by hand as just ``{key: entry}`` is read the same
        #  way: the skips are the point, not the wrapper.
        return {key: value for key, value in entries.items()
                if not str(key).startswith("_") and isinstance(value, dict)}
    return {}


def load(path):
    """Every marked card, or none when there is no file yet.

    A file that cannot be read is *not* an error to the caller: the worst a
    lost skip file can do is offer a card that will then be declined by hand.
    It is reported to whoever asks, though, because a file that keeps being
    ignored is worth fixing.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, UnicodeError):
        return {}
    return {str(key): dict(value) for key, value in cards(data).items()
            if isinstance(value, dict)}


def problem(path):
    """Why the file could not be read, or ``""`` when it can be.

    Kept apart from :func:`load` so the panel can say "there is a file here I
    cannot read" instead of quietly acting as if nobody had marked anything.
    """
    path = Path(path)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        return "The skip file %s could not be read (%s)." % (path.name, exc)
    if not isinstance(data, dict):
        return "The skip file %s does not hold the shape this app writes." % (
            path.name,)
    return ""


def save(path, entries):
    """Write the file. ``False`` when it could not be written."""
    payload = {"version": VERSION, "_what": (
        "Cards marked to skip on the eBay Quick List: key -> the card's title, "
        "id and when it was marked. Delete a line to offer the card again."),
        "cards": dict(entries or {})}
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        return True
    except OSError:
        return False


def mark(entries, key, card=None, note="", now=None):
    """A copy of ``entries`` with this card marked. Nothing is written here."""
    key = clean(key)
    if not key:
        return dict(entries or {})
    marked = {str(name): dict(value) for name, value in (entries or {}).items()}
    card = card if isinstance(card, dict) else {}
    marked[key] = {
        "title": title_of(card),
        "sku": _text(card.get("sku")).upper(),
        "id": _text(card.get("id") or card.get("product_id")),
        "at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "note": _text(note),
    }
    return marked


def unmark(entries, key):
    """A copy of ``entries`` without this card."""
    key = clean(key)
    return {str(name): dict(value) for name, value in (entries or {}).items()
            if clean(name) != key}


def is_marked(entries, key):
    wanted = clean(key)
    return bool(wanted) and any(clean(name) == wanted
                                for name in (entries or {}))


def split(cards_, entries, key=key_of):
    """``(kept, marked)`` - the cards to offer, and the ones left out.

    The order of ``kept`` is the order it was given in, because the order is
    the caller's decision (dearest first, the typed list, the batch's own) and
    a skip must not reshuffle it.
    """
    kept, marked = [], []
    for card in cards_ or []:
        if is_marked(entries, key(card)):
            marked.append(card)
        else:
            kept.append(card)
    return kept, marked


def rows(entries):
    """The marked cards as rows for a list, newest mark first."""
    found = []
    for key, entry in (entries or {}).items():
        entry = entry if isinstance(entry, dict) else {}
        found.append({"key": str(key),
                      "title": entry.get("title") or str(key),
                      "at": str(entry.get("at") or ""),
                      "skipped": entry.get("note") or ""})
    found.sort(key=lambda row: (row["at"], row["title"].casefold()),
               reverse=True)
    return found


def summary(entries):
    """One sentence for a panel or a console line; "" when nothing is marked."""
    count = len(entries or {})
    if not count:
        return ""
    return ("%d card%s marked to skip: %s%s." % (
        count, "" if count == 1 else "s",
        ", ".join(row["title"] for row in rows(entries)[:3]),
        " ..." if count > 3 else ""))


def left_out(entries, count):
    """What the summary of a selection says about the cards it left out."""
    if not count:
        return ""
    return ("%d card%s marked to skip %s left out of this list; the Skipped "
            "cards button puts %s back." % (
                count, "" if count == 1 else "s",
                "was" if count == 1 else "were",
                "it" if count == 1 else "them"))


def marked_sentence(card, saved, path=""):
    """What the panel says after a card was marked to skip.

    ``saved`` is whether the file was written: a mark that could not be saved
    is not a skip for the next list, and saying it is would be the worst of
    the two answers.
    """
    name = title_of(card) or "That card"
    if not saved:
        return ("%s was not marked: %s could not be written, so the next list "
                "would offer it again. Nothing was changed."
                % (name, Path(path).name if path else "the skip file"))
    return ("%s is marked to skip: it is off this list and every later list, "
            "in the panel and in the batch." % name)


def unmarked_sentence(card, saved, path=""):
    """What the panel says after a card was put back."""
    name = title_of(card) or "That card"
    if not saved:
        return ("%s was not put back: %s could not be written, so it is still "
                "marked." % (name, Path(path).name if path else "the skip file"))
    return ("%s is no longer marked: the next selection offers it again."
            % name)
