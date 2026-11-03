#!/usr/bin/env python3
"""Prove which fields of a CanadianShopper listing the site will really write.

The app has one question left about the vendor's own record - the thing
``/api/data/product/<listing-id>`` returns - and it cannot be answered by
reading: a route that answers ``OPTIONS`` with a method list has told you which
methods it accepts, not which fields it honours, and a ``PATCH`` that comes back
``200`` has told you the request was tolerated, not that the value was kept. A
server can accept a request and ignore a field, so the only thing that settles a
field is a *controlled, reversible change*: write one field, read the record
back, put the old value back, read it once more.

That is what this module does, one listing and one field at a time. It is
deliberately narrow:

* the address is the **record's own id** - the id the reader reports for the
  listing, the one its detail lookup uses - and never the product id;
* exactly one field is written per proof, and the old value is read from the
  record itself, so a listing that changed since the panel was read cannot be
  "restored" to something it never was;
* only fields whose old value can be read are offered. A field that is not in
  the record cannot be put back, so it is not touched;
* ``status`` is never proven: hiding a listing and putting it back is not
  reversible with certainty (an archived-then-active listing is not the same
  record as a draft-then-active one), and a visibility change on a live listing
  is not something a proof should be allowed to do by itself;
* the main photo is proven only with a URL from the image staging step, so the
  picture a shopper sees is the same card - writing an unfamiliar URL to a live
  listing for a few seconds is not a proof, it is a mistake with a rollback.

Nothing here is an edit feature. It writes one marked value, puts it back, and
writes down what the site did at each step; :func:`verdict_text` says whether
that leaves the field proven, ignored, refused, or still unknown.
"""
from __future__ import annotations

import csv
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import cs_edit
import woo_orders

#: The fields a proof may be run on, in the order they are offered, with the
#: vendor's spelling of the key and the word a person reads. ``status`` is not
#: here on purpose - see :data:`UNPROVABLE`.
FIELDS = (
    ("priceCad", "Price"),
    ("title", "Title"),
    ("description", "Description"),
    ("inventory", "Stock"),
    ("primaryImageUrl", "Main photo"),
)

#: A field a proof can settle that the record-edit form does not offer, and
#: why: the gallery is a *list* of photos, and a row of text in a form is the
#: wrong shape for it. It is proved all the same - one more photo on the end,
#: read back, then the list put back exactly as it was - because "does the site
#: keep a gallery" is a question with an answer, and the only way to have it is
#: to ask the record.
PROOF_ONLY = (
    ("images", "Gallery photos"),
)

#: Everything a proof may be run on, in the order it is offered.
PROOF_FIELDS = FIELDS + PROOF_ONLY

FIELD_LABELS = {field: label for field, label in PROOF_FIELDS}

#: The one field that is never proven by this module, and why. Named rather
#: than silently left out, because "why is state not in the list" is a fair
#: question with a real answer.
UNPROVABLE = {
    "status": ("a listing's state is not proven this way: archiving a live "
               "listing and putting it back is not the same record as it was "
               "before, and a visibility change is not something a proof "
               "should do to a live listing to find out"),
}

#: What marks the trial value in the fields a person will see. It has to be
#: recognisable in a read-back and in a browser tab that is open for a few
#: seconds - "Alex Collect write proof" is not a card title, and not a sentence
#: anyone would mistake for the vendor's.
MARK = "Alex Collect write proof"

TITLE_MARK = " PROOF"

#: Titles are short on a marketplace, and appending to a full one is how a
#: proof becomes a refusal that says nothing about the field. The base is cut
#: so the trial stays inside this many characters.
TITLE_ROOM = 76

PROOFS_FILE = "cs-field-proofs.json"


def field_label(field):
    """The word for a field, or the field itself when it is not one of ours."""
    return FIELD_LABELS.get(str(field or ""), str(field or ""))


def labels():
    """The field names as a person reads them, in the order they are offered."""
    return [label for _field, label in PROOF_FIELDS]


def proof_fields():
    """Every field a proof may be run on, in the order it is offered."""
    return [field for field, _label in PROOF_FIELDS]


def photo_fields():
    """The fields whose trial value is a photo, in the order they are offered."""
    return ["primaryImageUrl", "images"]


def field_for(label):
    """The field a chosen label stands for, or ``""``."""
    wanted = str(label or "").strip().casefold()
    for field, text in PROOF_FIELDS:
        if text.casefold() == wanted or field.casefold() == wanted:
            return field
    return ""


def vendor_key(record, field):
    """The key the vendor uses for a field, matched without case."""
    wanted = str(field or "").casefold()
    for key in (record or {}):
        if str(key).casefold() == wanted:
            return key
    return ""


def record_value(record, field):
    """``(found, value)`` for one field of a detail record."""
    key = vendor_key(record, field)
    if not key:
        return False, None
    return True, (record or {}).get(key)


def _number(value):
    return cs_edit.price_number({"price": value})


def photo_id(url):
    """One photo, however its address is spelled.

    The site answers with its own host and the staging CSV with a bare path,
    and the same picture must not read as two: the path is what names the file.
    """
    text = absolute_photo(url)
    if not text:
        return ""
    parts = urllib.parse.urlsplit(text)
    return (parts.path or text).rstrip("/")


def gallery_keys(value):
    """Every photo address in a gallery value, as web addresses, sorted.

    A gallery is compared as the *set of photos it holds*, not as a list: the
    site is free to answer with the photos in another order, and a reordering
    is not a lost photo. Addresses are made whole first, because the record may
    answer ``/api/file/x.webp`` where the write sent the whole address - the
    same picture, and not a difference worth reporting.
    """
    entries = value if isinstance(value, (list, tuple)) else [value]
    keys = []
    for entry in entries:
        if isinstance(entry, dict):
            entry = (entry.get("url") or entry.get("src") or
                     entry.get("image") or entry.get("path") or "")
        text = absolute_photo(entry).rstrip("/")
        if text:
            keys.append(text)
    return sorted(keys)


def _same_photo(like, url):
    """A new gallery entry shaped like the one beside it.

    A gallery that holds objects (``{"url": ...}``) must be given back an
    object, not a bare string: the shape is the site's, and the proof's job is
    to add a photo, not to change how the field is written.
    """
    if isinstance(like, dict):
        for key in ("url", "src", "image", "path"):
            if key in like:
                entry = dict(like)
                entry[key] = url
                return entry
    return url


def same(field, left, right):
    """Whether two values of one field are the same value to the site.

    A price is money, not text: ``12.5``, ``"12.50"`` and ``"12.500"`` are the
    same price and the site is free to answer with any of them. A stock count
    is a whole number. Everything else is compared as the words or the address
    it is.
    """
    if field == "priceCad":
        left_number, right_number = _number(left), _number(right)
        if left_number is None or right_number is None:
            return False
        return abs(left_number - right_number) < 0.005
    if field == "inventory":
        try:
            return int(left) == int(right)
        except (TypeError, ValueError):
            return False
    if field == "images":
        #  Compared by the file each address names, so a bare path and the
        #  site's own host are one photo and not a difference.
        return sorted(photo_id(url) for url in gallery_keys(left)) == \
            sorted(photo_id(url) for url in gallery_keys(right))
    return str(left if left is not None else "").strip() == \
        str(right if right is not None else "").strip()


def value_text(field, value):
    """A value as the report says it: quoted, or named as empty."""
    if value is None:
        return "(not there)"
    if isinstance(value, (list, tuple)):
        keys = gallery_keys(value)
        if not keys:
            return "(no photos)"
        shown = ", ".join(keys[:3]) + (" ..." if len(keys) > 3 else "")
        return "%d photo%s: %s" % (len(keys), "" if len(keys) == 1 else "s",
                                   shown)
    if isinstance(value, str) and not value.strip():
        return "(empty)"
    text = str(value)
    if field == "description" and len(text) > 120:
        return "%r and %d more characters" % (text[:120], len(text) - 120)
    return repr(text) if field != "priceCad" else str(text)


def plan(field, record, staged_url="", now=None):
    """What would be written for one field, and what would be put back.

    Refuses rather than guesses in every case where a proof would be unsafe or
    unreadable: an unknown field, a field the record does not carry (nothing to
    restore), an empty one, a price that is not a number, and a photo URL that
    is missing or is already the listing's own picture.
    """
    field = str(field or "").strip()
    if field in UNPROVABLE:
        return {"field": field, "why": "The %s is not proven this way: %s."
                % (field_label(field).lower(), UNPROVABLE[field])}
    if field not in FIELD_LABELS:
        return {"field": field, "why": "%r is not a field this can prove."
                % field}
    #  The gallery's key is the site's to choose, so it is found on the record
    #  rather than assumed. Everything else is addressed by its own name.
    planned_key = field
    if field == "images":
        planned_key = gallery_key(record)
        found = bool(planned_key)
        old = (record or {}).get(planned_key) if found else None
    else:
        found, old = record_value(record, field)
    label = field_label(field)
    if not found:
        if field == "images":
            return {"field": field, "label": label, "missing": True,
                    "why": gallery_refusal(record)}
        return {"field": field, "label": label, "missing": True,
                "why": "The record does not carry %s (%s), so there would be "
                       "nothing to put back - and a field that cannot be put "
                       "back is not touched." % (label.lower(), field)}
    if old is None or (isinstance(old, str) and not old.strip()):
        return {"field": field, "label": label,
                "why": "The record carries %s but no value for it, so there "
                       "would be nothing to put back." % label.lower()}
    note = ""
    if field == "priceCad":
        number = _number(old)
        if number is None:
            return {"field": field, "label": label,
                    "why": "%r does not read as a price, so a trial price "
                           "cannot be worked out from it." % (old,)}
        trial = "%.2f" % (number + 0.01)
        note = ("A cent above the current price, so a shopper who saw the "
                "listing in the seconds it is up is not offered a bargain.")
    elif field == "inventory":
        try:
            trial = int(old) + 1
        except (TypeError, ValueError):
            return {"field": field, "label": label,
                    "why": "%r does not read as a whole number of cards." %
                           (old,)}
        note = "One more than the count now."
    elif field == "title":
        text = " ".join(str(old).split())
        room = max(1, TITLE_ROOM - len(TITLE_MARK))
        trial = (text if len(text) + len(TITLE_MARK) <= TITLE_ROOM
                 else text[:room].rstrip()) + TITLE_MARK
        note = ("The title with %r on the end, cut first if the title is near "
                "a marketplace's limit so the write is not refused for length "
                "instead of for the field." % TITLE_MARK.strip())
    elif field == "description":
        stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        trial = "%s\n\n%s %s." % (str(old).rstrip(), MARK, stamp)
        note = "The description with one marker line on the end."
    elif field == "images":
        key = str(planned_key or "")
        entries = (old if isinstance(old, (list, tuple)) else [old])
        have = gallery_keys(entries)
        if not have:
            return {"field": field, "label": label,
                    "why": "The record carries a gallery (%s) with no photo "
                           "address in it that could be read, so there is "
                           "nothing to put back." % key}
        trial_photo = absolute_photo(staged_url)
        if not trial_photo:
            return {"field": field, "label": label,
                    "why": "The gallery is proven with one more photo from the "
                           "image staging step - a picture of the same card. "
                           "Without one there is nothing safe to write."}
        if not trial_photo.lower().startswith(("http://", "https://")):
            return {"field": field, "label": label,
                    "why": "%r is not a web address, so it is not a photo the "
                           "gallery can hold." % trial_photo}
        if trial_photo.rstrip("/") in have:
            return {"field": field, "label": label,
                    "why": "That photo is already in the listing's gallery, so "
                           "writing the gallery again would prove nothing."}
        trial = list(entries) + [_same_photo(entries[-1], trial_photo)]
        note = ("The gallery with one more photo on the end, which is put "
                "back to the list it holds now.")
        return {"field": field, "label": label, "old": old, "trial": trial,
                "restore": old, "note": note, "key": key}
    else:                                             # primaryImageUrl
        trial = str(staged_url or "").strip()
        if not trial:
            return {"field": field, "label": label,
                    "why": "The main photo is proven with a photo URL from the "
                           "image staging step: a URL that shows the same card. "
                           "Without one there is nothing safe to write."}
        if not trial.lower().startswith(("http://", "https://")):
            return {"field": field, "label": label,
                    "why": "%r is not a web address, so it is not a photo the "
                           "listing can show." % trial}
        if same(field, trial, old):
            return {"field": field, "label": label,
                    "why": "That address is already the listing's main photo, "
                           "so writing it would prove nothing."}
        note = ("The staged photo of the same card, which replaces the current "
                "main photo for the seconds the proof runs and is then put "
                "back.")
    return {"field": field, "label": label, "old": old, "trial": trial,
            "restore": old, "note": note, "key": planned_key}


#: What the image staging step writes its rows into. The staging command takes
#: the batch's import CSV and rewrites each row's ``image_url`` to the hosted
#: square photo it uploaded, so a row still pointing at the website is a row
#: that has not been staged.
STAGED_PATTERN = "canadianshopper_import_*.csv"

#: Where older staged batches go: the app consolidates finished CSVs into one
#: history file, so a card staged a fortnight ago has no ``import`` CSV of its
#: own any more - only a row in here.
STAGED_HISTORY = "canadianshopper_staged_history.csv"

STAGED_PHOTO = "/api/file/"


def _fold(text):
    return " ".join(str(text or "").split()).casefold()


def staged_roots(folder, extra_folders=()):
    """The folders a staged-photo lookup searches, without duplicates.

    The batch folder is where the newest CSVs are, ``cs-ready`` inside it is
    where plugin 1.0.40 writes them, and the folders a caller adds are where a
    person's own copies or an older batch may be. Saying which folders were
    searched is part of the answer when nothing is found: "no staged photo"
    without that is a dead end nobody can act on.
    """
    roots = []
    for value in [folder] + list(extra_folders or []):
        text = str(value or "").strip()
        if not text:
            continue
        try:
            path = Path(text)
            if path.is_dir() and path not in roots:
                roots.append(path)
        except OSError:
            continue
    return roots


def staged_files(folder, extra_folders=(), limit=40):
    """The staged CSVs to read, newest first, across every folder searched."""
    found = []
    for root in staged_roots(folder, extra_folders):
        for pattern in (STAGED_PATTERN, STAGED_HISTORY):
            try:
                found.extend(root.rglob(pattern))
            except OSError:
                continue
    unique = {}
    for path in found:
        try:
            if path.is_file():
                unique[str(path.resolve())] = path
        except OSError:
            continue
    try:
        return sorted(unique.values(), key=lambda path: path.stat().st_mtime,
                      reverse=True)[:max(1, int(limit or 40))]
    except OSError:
        return []


def staged_photo(folder, title="", extra_folders=()):
    """The staged photo URL a batch's CSV holds for one card, or ``""``.

    The image staging step uploads a square photo and rewrites the import row's
    ``image_url`` to the hosted file (``/api/file/...``). That address is what a
    photo proof writes: it is the same card's picture, already prepared for
    CanadianShopper, so replacing the listing's main photo with it for the
    seconds a proof runs shows a shopper the card and not a stand-in.

    Only an exact title matches, and only an address the staging step produced:
    a row still carrying the website's own URL has not been staged, and picking
    between two similar titles is how one card's photo lands on another.
    """
    wanted = _fold(title)
    if not wanted:
        return ""
    for path in staged_files(folder, extra_folders, limit=8):
        try:
            with path.open(newline="", encoding="utf-8-sig",
                           errors="replace") as handle:
                for row in csv.DictReader(handle):
                    url = str((row or {}).get("image_url") or "").strip()
                    if STAGED_PHOTO not in url:
                        continue
                    if _fold((row or {}).get("title")) == wanted:
                        return url
        except (OSError, csv.Error, TypeError):
            continue
    return ""


#: The keys a listing record or a reader's row may carry its photos under.
#: ``primaryImageUrl`` is deliberately not one of them: that is the photo the
#: listing shows *now*, so it is what a proof puts back, never what it writes.
PHOTO_KEYS = ("images", "photos", "gallery", "imageUrls", "imageUrl", "image")

#: Where the site's own uploads live. The image staging step posts a squared
#: photo and the site answers with this path, so a URL holding it is a photo
#: that is already on CanadianShopper - and one that shows this card.
HOSTED_PHOTO = "/api/file/"


def absolute_photo(url, base="https://canadianshopper.ca"):
    """A photo address as a web address, whenever the site gave only a path.

    The staging step's own CSV says ``/api/file/<name>``: it is the right photo
    and the right site, and the record wants the whole address, so the site is
    put on the front here instead of at four call sites.
    """
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        return "https:" + text
    if text.startswith("/"):
        return str(base or "").rstrip("/") + text
    return text


def _photo_values(container):
    """Every photo address in one row or record, in the order it was given."""
    found = []
    for key, value in (container or {}).items():
        if str(key).casefold() not in tuple(k.casefold() for k in PHOTO_KEYS):
            continue
        entries = value if isinstance(value, (list, tuple)) else [value]
        for entry in entries:
            if isinstance(entry, dict):
                entry = entry.get("src") or entry.get("url") or ""
            text = str(entry or "").strip()
            if text:
                found.append(text)
    return found


#: The record's own key for its list of photos, when it has one. The vendor
#: spells it as it likes - the shop's own record is not the only shape this
#: app has seen - so the key is *found* on the record rather than assumed, and
#: a field that is not there is never invented.
GALLERY_KEYS = ("images", "galleryImages", "imageUrls", "image_urls",
                "gallery", "photos", "imageList", "additionalImages",
                "media", "productImages", "secondaryImages", "extraImages",
                "imageGallery", "galleryUrls")

#: Names a gallery may go by that are *not* conclusive on their own - a record
#: can hold files that are not pictures. These are only believed when what is
#: in them looks like photos.
GALLERY_WEAK_KEYS = ("attachments", "files", "assets", "uploads", "imageset",
                     "pictures", "photosList")

#: What a photo file name ends with. A list of these under a name nobody
#: predicted is a gallery; a list of "vintage", "hockey" is not.
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp",
                  ".tiff", ".tif", ".heic")


def looks_like_photo(text):
    """Whether a value reads as the address of a picture."""
    value = str(text or "").strip().casefold()
    if not value:
        return False
    if value.startswith(("http://", "https://")):
        return True
    if HOSTED_PHOTO.casefold() in value:
        return True
    if value.startswith(("uploads/", "/uploads/", "media/", "/media/",
                         "files/", "/files/", "./", "../")):
        return True
    return value.split("?")[0].endswith(IMAGE_SUFFIXES)


#: The key an entry keeps its photo under, in the order shops tend to use
#: them. A gallery of maps is common - the photo, its thumbnail, its id - and
#: reading only ``url`` is how a record with a gallery reads as having none.
ENTRY_URL_KEYS = ("url", "src", "image", "path", "href", "file", "filename",
                  "originalUrl", "cdnUrl", "large", "medium", "thumb",
                  "thumbnail", "imageUrl", "srcUrl")


def _entry_url(entry, depth=0):
    """The address inside one gallery entry, whether it is a string or a map."""
    if isinstance(entry, dict):
        for key in ENTRY_URL_KEYS:
            value = entry.get(key)
            if isinstance(value, dict) and depth < 2:
                found = _entry_url(value, depth + 1)
                if found:
                    return found
            elif value:
                return str(value)
        return ""
    return str(entry or "")


def gallery_key(record):
    """The record's own key for the gallery, or ``""`` when it carries none.

    A key is the gallery when it is one of the names marketplaces use, or when
    it holds a list of photo addresses and is not the main photo. A record with
    only ``primaryImageUrl`` has no gallery: there is one picture, and a proof
    cannot add a second to a field the site does not have.
    """
    record = record or {}
    if not isinstance(record, dict):
        return ""
    for wanted in GALLERY_KEYS:
        key = vendor_key(record, wanted)
        if key:
            return key
    #  A name that is only a hint: believed when the list really holds photos.
    for wanted in GALLERY_WEAK_KEYS:
        key = vendor_key(record, wanted)
        if key and _holds_photos(record.get(key), record):
            return key
    #  No recognised name at all: a list of photo addresses under a name nobody
    #  predicted is still the gallery - it is the only list of pictures on the
    #  record, and that is what a gallery is.
    for key, value in record.items():
        if not _holds_photos(value, record):
            continue
        if str(key).casefold() == "primaryimageurl":
            continue
        return str(key)
    return ""


def _holds_photos(value, record=None):
    """Whether a value is a list of photos, and not the main photo alone."""
    entries = value if isinstance(value, (list, tuple)) else []
    if not entries:
        return False
    urls = [_entry_url(entry) for entry in entries]
    if not all(urls):
        return False
    photos = [url for url in urls if looks_like_photo(url)]
    if len(photos) != len(urls):
        #  A mixed list is not evidence of a gallery: one picture beside a
        #  paragraph of prose is a record describing itself, not a gallery.
        return False
    main = str((record or {}).get("primaryImageUrl") or "")
    key_main = photo_id(main)
    if key_main and len(urls) == 1 and photo_id(urls[0]) == key_main:
        return False
    return True


def record_keys(record, limit=0):
    """The record's keys, for a message that has to name what is not there.

    Every one of them by default: "and 24 more" is exactly the part a person
    cannot check, and the key that is not named is the one being looked for.
    """
    keys = [str(key) for key in (record or {}) if str(key).strip()]
    if not keys:
        return "(the record carries no keys)"
    if limit and len(keys) > limit:
        return "%s and %d more" % (", ".join(keys[:limit]), len(keys) - limit)
    return ", ".join(keys)


def gallery_refusal(record):
    """"There is no gallery on this record", with everything needed to check.

    A refusal has to be as useful as an answer: the record's every key, and
    what each field that could hold photos actually holds. That is what says
    whether the site has no gallery at all, or has one under a name this app
    does not know yet - and it is the same text the proof file keeps, so it can
    be attached to a plugin report as it is.
    """
    lines = ["The record carries no gallery, so a photo written there would "
             "create a field with nothing to put back.",
             "Every key it holds: %s." % record_keys(record)]
    shaped = photo_field_report(record)
    if shaped:
        lines.append("The fields that could have held photos:")
        lines += ["  " + line for line in shaped]
    else:
        lines.append("None of them is a list of photos, and none is named for "
                     "pictures: there is no gallery on this record at all.")
    return "\n".join(lines)


def shape_of(value):
    """What a value is, in a few words: a count for a list, a kind for a map."""
    if isinstance(value, dict):
        keys = [str(key) for key in value if str(key).strip()]
        return "a map with %s" % (", ".join(keys[:6]) or "no keys")
    if isinstance(value, (list, tuple)):
        kinds = {type(entry).__name__ for entry in value}
        return "a list of %d (%s)" % (len(value),
                                      ", ".join(sorted(kinds)) or "empty")
    if isinstance(value, str):
        text = value.strip()
        return "text (%s...)" % text[:40] if text else "empty text"
    return type(value).__name__


#: Words that make a key worth looking at when hunting for a gallery that the
#: app did not recognise.
PHOTO_WORDS = ("image", "photo", "picture", "gallery", "media", "thumb",
               "attachment", "file", "asset", "upload")


def photo_field_report(record):
    """Every field that could be a gallery, and what is in it.

    This is the sentence that answers "does this record have a gallery at
    all": a site that calls the list something unexpected, or holds a list of
    objects rather than addresses, is named here with its shape and a sample -
    rather than a flat "no gallery" over a record with thirty-nine keys in it,
    twenty-four of which nobody ever saw.
    """
    lines = []
    for key, value in (record or {}).items():
        name = str(key)
        wanted = any(word in name.casefold() for word in PHOTO_WORDS)
        interesting = wanted or isinstance(value, (list, tuple, dict))
        if not interesting:
            continue
        sample = ""
        entries = value if isinstance(value, (list, tuple)) else [value]
        for entry in entries:
            text = _entry_url(entry) if isinstance(entry, dict) else str(entry)
            if str(text or "").strip():
                sample = str(text).strip()[:90]
                break
        lines.append("%s is %s%s" % (name, shape_of(value),
                                     (" - e.g. %s" % sample) if sample else ""))
    return lines


def primary_photo(item=None, record=None):
    """The photo the listing shows now, from the record when there is one."""
    if record:
        found, value = record_value(record, "primaryImageUrl")
        if found and str(value or "").strip():
            return absolute_photo(value)
    for text in _photo_values(item):
        return absolute_photo(text)
    return ""


def staged_photos(folder, batches=8, extra_folders=()):
    """Every staged photo the batch holds: ``[{"title", "url"}]``, newest first.

    The exact-title lookup answers "is *this* card staged". When it does not -
    the site's title and the CSV's are rarely the same words, a grade on the end
    of one and not the other - the person still needs a way in, and the batch's
    own staged rows are it: the same photos the plugin uploaded for this batch,
    listed with the title each was staged under so the right card can be picked
    by eye.
    """
    rows, seen = [], set()
    for path in staged_files(folder, extra_folders,
                             limit=max(1, int(batches or 8))):
        try:
            with path.open(newline="", encoding="utf-8-sig",
                           errors="replace") as handle:
                for row in csv.DictReader(handle):
                    url = str((row or {}).get("image_url") or "").strip()
                    if STAGED_PHOTO not in url:
                        continue
                    url = absolute_photo(url)
                    if url in seen:
                        continue
                    seen.add(url)
                    rows.append({"title": str((row or {}).get("title")
                                              or "").strip(), "url": url})
        except (OSError, csv.Error, TypeError):
            continue
    return rows


def sibling_photos(url):
    """The card's other photo, guessed from the one the listing shows now.

    The plugin uploads a card's front and its back, and names the back by
    swapping ``front`` for ``back`` in the file it staged. So a listing whose
    main photo is ``…/wurmple-front.webp`` almost always has a
    ``…/wurmple-back.webp`` beside it - the same card, already on the site, and
    the one address a proof can write with no local file at all.

    It is a *guess about a name*, so it is never offered on its own: the caller
    asks the site whether that address answers with an image (``photo_alive``)
    and only offers the ones that do.
    """
    text = str(url or "").strip()
    if not text:
        return []
    head, _, tail = text.rpartition("/")
    lowered = tail.casefold()
    found = []
    for old_word, new_word in (("front", "back"), ("back", "front")):
        index = lowered.find(old_word)
        while index != -1:
            token = tail[index:index + len(old_word)]
            replacement = (new_word.upper() if token.isupper() else
                           new_word.capitalize() if token[:1].isupper()
                           else new_word)
            candidate = "%s/%s" % (head, tail[:index] + replacement +
                                   tail[index + len(old_word):])
            if candidate != text and candidate not in found:
                found.append(candidate)
            index = lowered.find(old_word, index + 1)
    return found


def photo_alive(url, opener=None, timeout=15):
    """``(True, content_type)`` when a photo address answers with an image.

    Read-only, never raises, and deliberately anonymous: a hosted photo is
    public, and a proof has no business sending somebody's session to fetch a
    picture. A site that refuses ``HEAD`` is asked for the first bytes with
    ``GET`` instead, so a photo that exists is not called missing because of
    the method.
    """
    text = str(url or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        return False, ""
    if opener is not None:
        return opener(text)
    headers = {"User-Agent": "Mozilla/5.0 (AlexCollect-GUI)",
               "Accept": "image/*,*/*;q=0.8"}
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(text, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                kind = str(response.headers.get("Content-Type") or "")
                if method == "GET":
                    response.read(2048)
                status = getattr(response, "status", 200)
            if 200 <= status < 300:
                return True, kind
            return False, kind
        except urllib.error.HTTPError as exc:
            if method == "GET" or exc.code not in (403, 405, 501):
                return False, ""
            continue
        except Exception:
            return False, ""
    return False, ""


def photo_candidates(item=None, record=None, staged="", staged_rows=None,
                     siblings=None):
    """Every photo a proof could safely write, best first, with where it came from.

    A proof of the main photo must write a picture of *the same card*, because
    the listing really shows it for the seconds the proof runs. Three sources
    meet that test, and all three are things this app can point at:

    * the **staged photo** - the image staging step's own upload of this card
      (``/api/file/...``), which is what the CSV row already carries;
    * the **listing's own gallery** - the squared photos the plugin uploaded
      for this very listing, which the reader reports on its row and which a
      record may carry under ``images`` and similar keys;
    * anything the person pastes.

    The photo the listing shows now is never a candidate: writing it would
    prove nothing, and it is the value a proof has to put back.
    """
    current = primary_photo(item=item, record=record).rstrip("/")
    seen, found = set(), []

    def add(url, source):
        text = absolute_photo(url)
        key = text.rstrip("/")
        if not text or key == current or key in seen:
            return
        seen.add(key)
        found.append({"url": text, "source": source})

    add(staged, "the image staging step's photo of this card")
    #  The card's other photo, at the address the plugin names its pairs with -
    #  offered only after the caller has asked the site whether it is there.
    for text in siblings or []:
        add(text, "the card's other photo, already on CanadianShopper")
    #  The batch's other staged rows, already ranked by the caller: the site's
    #  title and the CSV's are rarely the same words, and a person can see
    #  which card a photo was staged for from the title beside it.
    for row in staged_rows or []:
        title = str((row or {}).get("title") or "").strip()
        add((row or {}).get("url"),
            "the batch's staged photo of %r" % title if title else
            "a staged photo in this batch")
    for text in _photo_values(record or {}):
        add(text, "a photo on this listing's own record")
    for text in _photo_values(item or {}):
        add(text, "a photo this listing already shows")
    return found


def read_record(url, cookie="", opener=None, timeout=25):
    """``(status, body_text)`` for one detail request; never raises."""
    status, _content_type, body = cs_edit.fetch_detail(
        url, cookie, timeout=timeout, opener=opener)
    return status, body


def send(url, cookie, payload, opener=None, timeout=25):
    """``PATCH`` one record with one field; ``(status, body_text)``, never raises.

    The same request shape the vendor's own tools use - JSON body, the person's
    own session cookie, one field - so a refusal is about the field and not
    about how the app asked.
    """
    if opener is not None:
        return opener(url, cookie, payload)
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="PATCH",
        headers={"User-Agent": "Mozilla/5.0 (AlexCollect-GUI)",
                 "Accept": "application/json",
                 "Content-Type": "application/json",
                 "Cookie": str(cookie or "")})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(200000).decode("utf-8", "replace")
            return getattr(response, "status", 200), body
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(200000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, body
    except Exception as exc:
        return 0, str(exc)


def record_from(body):
    """The record in a detail response, or ``None`` - the public reading."""
    return _record(body)


def _record(body):
    """The JSON object in a detail response, or ``None``."""
    parsed = cs_edit.parsed_body(body)
    if isinstance(parsed, dict):
        return parsed
    return None


def _snippet(body, limit=240):
    text = " ".join(str(body or "").split())
    return text[:limit] + ("\u2026" if len(text) > limit else "")


def prove(field, url, cookie="", staged_url="", now=None, fetch=None,
          send=None, listing=None):
    """Write one field, read it back, put it back - and say what happened.

    The record is read first and the plan is made from *that* read, not from
    the list the panel showed: a value that changed in the dashboard while the
    panel was open must not be "restored" to an older one.

    Every step is kept in ``steps`` so the report can show the statuses in
    order, and the result carries a ``verdict``:

    ``written``   the site accepted it and the read-back showed it;
    ``ignored``   the site accepted it and the record still shows the old value;
    ``refused``   the site answered with anything but a 2xx;
    ``unreadable`` the record could not be read, so nothing was written;
    ``unknown``   the write was accepted but the read-back could not be read.

    Nothing is written when ``plan`` refuses or the first read fails.
    """
    fetch = fetch or read_record
    send = send or globals()["send"]
    now = now or datetime.now()
    field = str(field or "").strip()
    result = {"field": field, "label": field_label(field), "url": url,
              "steps": [], "verdict": "", "written": False, "restored": None,
              "old": None, "trial": None, "restore": None, "after": None,
              "final": None, "status": 0, "restore_status": 0, "why": "",
              "at": now.strftime("%Y-%m-%d %H:%M:%S")}
    if listing:
        result["listing"] = str(listing.get("id") or "")
        result["title"] = str(listing.get("name") or listing.get("title") or "")

    status, body = fetch(url, cookie)
    record = _record(body) if status == 200 else None
    result["steps"].append({"step": "GET the record", "status": status,
                            "body": "" if record is not None
                            else _snippet(body)})
    if record is None:
        result["verdict"] = "unreadable"
        result["why"] = ("The record could not be read (%s), so nothing was "
                         "written: a value that cannot be read cannot be put "
                         "back." % ("HTTP %s" % status if status else
                                    "the request failed"))
        return result

    planned = plan(field, record, staged_url=staged_url, now=now)
    if "why" in planned:
        #  The record was read and the *plan* said no: nothing was sent, and
        #  nothing on the site is wrong. Said apart from a failed read, because
        #  the fix is different - there is nothing to sign in to.
        result["verdict"] = "unreadable"
        result["plan_refused"] = True
        result["field_missing"] = bool(planned.get("missing"))
        result["why"] = planned["why"]
        #  The record itself is the evidence for a refusal that is about the
        #  record's shape: its keys, and what each field that could hold photos
        #  holds. Kept on the result so the proof file carries it without the
        #  record ever being written into a file - the values are cut to a line
        #  each and the session is not in it.
        result["record_shape"] = {
            "keys": record_keys(record),
            "photo_fields": photo_field_report(record)}
        return result
    result.update({key: planned[key] for key in
                   ("old", "trial", "restore", "note", "label")})
    #  The key the site actually uses for the field - the gallery's is found on
    #  the record, so it is not always the field's own name.
    key = str(planned.get("key") or field)
    result["key"] = key

    written_status, written_body = send(url, cookie, {key: planned["trial"]})
    result["status"] = written_status
    result["steps"].append({"step": "PATCH %s" % key, "status": written_status,
                            "sent": planned["trial"],
                            "body": "" if 200 <= written_status < 300
                            else _snippet(written_body)})
    if not 200 <= written_status < 300:
        #  A refused write is an answer about the field, and the read-back is
        #  what keeps the report honest if a refusal came with a change.
        after_status, after_body = fetch(url, cookie)
        after_record = _record(after_body) if after_status == 200 else None
        result["after"] = (record_value(after_record, key)[1]
                           if after_record is not None else None)
        result["steps"].append({"step": "GET the record",
                                "status": after_status})
        result["verdict"] = "refused"
        result["why"] = (
            "The site refused the write (%s), so %s is not proven writable. "
            "Nothing was put back because nothing was taken: %s"
            % ("HTTP %s" % written_status if written_status else
               written_body or "the request never reached the site",
               field_label(field).lower(),
               "the record still shows the value it had."
               if after_record is not None and
               same(field, result["after"], planned["old"])
               else "the read-back could not confirm what the record holds."))
        return result

    after_status, after_body = fetch(url, cookie)
    after_record = _record(after_body) if after_status == 200 else None
    result["steps"].append({"step": "GET the record", "status": after_status})
    if after_record is not None:
        result["after"] = record_value(after_record, key)[1]

    if after_record is None:
        #  The write was accepted and cannot be read back. That is not proof;
        #  the old value is put back at once, because something may have been
        #  changed.
        result["verdict"] = "unknown"
        result["why"] = ("The site accepted the write but the record could not "
                         "be read back (%s), so there is no proof that the "
                         "field was honoured. The old value is being put back "
                         "anyway." % ("HTTP %s" % after_status
                                      if after_status else "the request failed"))
    elif same(field, result["after"], planned["old"]):
        result["verdict"] = "ignored"
        result["why"] = (
            "The site answered %s but the record still shows the old value "
            "(%s): the request was accepted and the field was not honoured. A "
            "200 alone is not proof of a field, and %s is not proven writable."
            % ("HTTP %s" % written_status, value_text(field, planned["old"]),
               field_label(field).lower()))
    else:
        result["verdict"] = "written"
        result["written"] = True
        if same(field, result["after"], planned["trial"]):
            result["why"] = ("The site accepted %s%s and the record shows it "
                             "on the next read."
                             % (field_label(field).lower(),
                                " (%s)" % value_text(field, planned["trial"])))
        else:
            result["why"] = (
                "The site accepted %s and the record now shows %s rather than "
                "the value sent (%s): the field is honoured and the site "
                "normalised what it stored - which is still a write."
                % (field_label(field).lower(),
                   value_text(field, result["after"]),
                   value_text(field, planned["trial"])))

    #  Put it back, whatever the verdict: "ignored" left the old value in
    #  place, and sending it again is harmless; "written" needs it.
    restore_status, restore_body = send(url, cookie,
                                        {key: planned["restore"]})
    result["restore_status"] = restore_status
    result["steps"].append({"step": "PATCH %s (put back)" % key,
                            "status": restore_status,
                            "sent": planned["restore"],
                            "body": "" if 200 <= restore_status < 300
                            else _snippet(restore_body)})
    final_status, final_body = fetch(url, cookie)
    final_record = _record(final_body) if final_status == 200 else None
    result["steps"].append({"step": "GET the record", "status": final_status})
    if final_record is not None:
        result["final"] = record_value(final_record, key)[1]
        result["restored"] = same(field, result["final"], planned["old"])
    else:
        result["restored"] = None
    if result["verdict"] == "ignored" and result["restored"]:
        result["why"] += (" The old value was sent once more and the record "
                          "still shows it, so nothing is left behind.")
    return result


def skipped(field, why, earlier=False):
    """A result for a field that was not attempted, and the reason why not.

    ``earlier`` says the field was already settled by a previous proof: that is
    a *done* field, not a problem, and the difference matters - one reads as
    "nothing to do", the other as "something is wrong".
    """
    return {"field": str(field or ""), "label": field_label(field),
            "verdict": "skipped", "settled_earlier": bool(earlier),
            "why": str(why or ""), "steps": [],
            "written": False, "restored": None, "status": 0,
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def advice(result):
    """What the person can do about one field's outcome, in their words.

    A proof that only says "not proven" is a dead end: every verdict this
    module can reach has a cause and an action, and this is where the action
    is said. Empty when nothing needs doing.
    """
    result = result or {}
    verdict = result.get("verdict") or ""
    field = result.get("field") or ""
    label = field_label(field) or field
    status = int(result.get("status") or 0)
    if verdict == "written" and result.get("restored") is False:
        return ("Put %s back by hand now: open the listing on CanadianShopper "
                "and set it to %s. Nothing else should be done until it is "
                "back." % (label.lower(),
                           value_text(field, result.get("restore"))))
    if verdict == "written":
        return ""
    if verdict == "skipped":
        #  The sentence already says why it was not written; a "what to do"
        #  line under a field that needs nothing is noise.
        return ""
    if verdict == "refused":
        if status == 401:
            return ("Sign in to CanadianShopper again, then save the session "
                    "cookie in User settings: the site refused the request as "
                    "signed out.")
        if status == 403:
            return ("The account behind the saved session is not allowed to "
                    "change that listing: sign in as the shop's owner, save "
                    "the cookie again, and prove %s once more."
                    % label.lower())
        if status == 422:
            return ("The site rejected the value itself (HTTP 422). The exact "
                    "answer is in the proof file: if it names the shape it "
                    "expects for %s, that shape is what the field needs."
                    % label.lower())
        if status == 429:
            return ("The site is rate-limiting this session: wait a minute, "
                    "then prove %s again." % label.lower())
        if status >= 500:
            return ("The site had an internal error (HTTP %s): try again in a "
                    "few minutes." % status)
        if not status:
            return ("The request never reached the site: check the connection "
                    "and prove %s again." % label.lower())
        return ("The site's answer is in the proof file - attach it to the "
                "plugin report so the field's route can be checked.")
    if verdict == "ignored":
        return ("Open the listing in the CanadianShopper dashboard and set %s "
                "there once. If the dashboard keeps it, the record endpoint "
                "does not carry that field and the plugin has to pass it "
                "through: the proof file is the evidence, and no write path "
                "should be built on it until it is settled."
                % label.lower())
    if not_here(result):
        return ("Nothing to do on the site and nothing to fix here: this "
                "listing's record has no such field, so there is nothing a "
                "proof could write or put back. The keys above are everything "
                "the record holds - if the field should exist, that is a "
                "plugin question, and the proof file is the evidence for it.")
    if verdict == "unreadable" and result.get("plan_refused"):
        #  The record answered; the plan said no. Signing in again would change
        #  nothing, so it is not suggested.
        return ("Nothing to fix on the site: the record was read and the field "
                "was left alone. The proof file names the record's own keys, "
                "which is what a plugin change would have to work with.")
    if verdict == "unreadable":
        return ("Open the listing on CanadianShopper in a browser. If it asks "
                "you to sign in, the saved session has expired: sign in, save "
                "the cookie again in User settings, then prove %s once more."
                % label.lower())
    if verdict == "unknown":
        return ("Check that listing on CanadianShopper before anything else: "
                "the write was accepted and could not be read back, so the "
                "field may or may not have changed.")
    return ""


#: How sure the app has to be that a staged title is *this* card before it
#: writes that photo to a live listing without a person looking. High on
#: purpose: a shared brand ("O-Pee-Chee") is not a shared card, and the cost of
#: being wrong is another card's picture on somebody's listing for a few
#: seconds - or, worse, kept if the restore fails.
PHOTO_MATCH_SCORE = 0.75


def same_card(card, title, threshold=PHOTO_MATCH_SCORE):
    """Whether a staged row's title is this card, closely enough to use.

    Two ways to be sure: a title that is near-exact, or a good title match
    whose *card numbers* line up as well. The number is the part that tells two
    cards of the same set apart, which is exactly the mistake an automatic
    choice must not make.
    """
    card = str(card or "").strip()
    title = str(title or "").strip()
    if not card or not title:
        return False
    value = cs_edit.score(card, {"name": title})
    if value >= 0.9:
        return True
    try:
        _value, numbers_ok = woo_orders.analyse(card, title)
    except Exception:
        numbers_ok = False
    return bool(numbers_ok) and value >= threshold


def auto_photos(item=None, record=None, staged="", staged_rows=None,
                siblings=None, alive=None, card="", threshold=PHOTO_MATCH_SCORE):
    """The photos a proof may write without asking, and why when there are none.

    A proof of a photo field puts a picture on a live listing, so the automatic
    run may only use a picture that is *certainly this card*: the staging step's
    own upload for it, the card's other photo once the site has answered for
    that address with an image, a photo the listing already shows, or a staged
    row whose title is this card (``same_card``). A row from the batch that
    merely scored well is not a photo of this card, and writing it is how a
    Wurmple listing ends up showing a 1978 baseball card.

    Returns ``{"main": url, "gallery": url, "why_main": "", "why_gallery": ""}``.
    """
    card = str(card or "").strip()
    current = primary_photo(item=item, record=record).rstrip("/")

    def usable(url):
        text = absolute_photo(url)
        return text if text and text.rstrip("/") != current else ""

    safe = []
    staged_url = usable(staged)
    if staged_url:
        safe.append(staged_url)
    if siblings is None:
        siblings = sibling_photos(current)
    check = alive or photo_alive
    for url in siblings or []:
        text = usable(url)
        if text and check(text)[0]:
            safe.append(text)
    for url in _photo_values(record or {}) + _photo_values(item or {}):
        text = usable(url)
        if text and text not in safe:
            safe.append(text)
    best = {}
    for row in staged_rows or []:
        title = str((row or {}).get("title") or "")
        text = usable((row or {}).get("url"))
        if not text:
            continue
        if not best:
            best = {"title": title, "url": text,
                    "score": cs_edit.score(card, {"name": title})}
        if same_card(card, title, threshold) and text not in safe:
            safe.append(text)

    why = ""
    if not safe:
        why = ("no photo of this card could be found: the staged upload, the "
               "card's other photo on the site and the listing's own photos "
               "were all checked")
        if best:
            why += (". The closest staged row - %r, %d%% - is not this card, "
                    "so it was not used" % (best["title"][:80],
                                            int(best["score"] * 100)))
        why += ". Prove it with the photo chooser and pick the row for this "                "card, or paste its address."
    main = safe[0] if safe else ""
    gallery = ""
    have = set()
    if record:
        for url in gallery_keys((record or {}).get(gallery_key(record) or "")):
            have.add(photo_id(url))
    for url in safe:
        if photo_id(url) not in have and url != main:
            gallery = url
            break
    if not gallery and main and photo_id(main) not in have:
        gallery = main
    why_gallery = ""
    if not gallery:
        if record and not gallery_key(record):
            #  The field is not there at all: that is a different sentence from
            #  "everything is already in it", and only the first one explains
            #  why a gallery proof can never work on this listing.
            why_gallery = ("the record carries no gallery - no list of photos "
                           "under any of the names marketplaces use - so there "
                           "is nothing to add to and nothing to put back. The "
                           "record holds: %s" % record_keys(record))
        else:
            why_gallery = ("every photo of this card the app can point at is "
                           "already in the listing's gallery, so there is "
                           "nothing new to add")
    return {"main": main, "gallery": gallery, "why_main": why,
            "why_gallery": why_gallery}


def photo_for_proof(item=None, record=None, staged="", staged_rows=None,
                    siblings=None, alive=None):
    """The photo to prove the photo fields with, found rather than asked for.

    The first candidate whose address is a picture of this card and *not* the
    photo the listing shows now. A sibling - a name guessed from the current
    main photo - is only used after the site answers for it with an image, so a
    guess never becomes a write. ``alive`` is injected for tests.
    """
    if siblings is None:
        #  Nothing has looked the pair up yet: the names come from the photo
        #  the listing shows now, and each one is checked before it is used.
        siblings = sibling_photos(primary_photo(item=item, record=record))
    candidates = photo_candidates(item=item, record=record, staged=staged,
                                  staged_rows=staged_rows, siblings=siblings)
    if not candidates:
        return ""
    if not siblings:
        return candidates[0]["url"]
    siblings_set = {str(url).rstrip("/") for url in siblings}
    for candidate in candidates:
        url = candidate["url"]
        if url.rstrip("/") not in siblings_set:
            return url
        check = alive or photo_alive
        ok, _kind = check(url)
        if ok:
            return url
    return ""


def missing_result(field, record=None, why=""):
    """A field the site's record does not have, reported like the proof would.

    The proof knows this when it reads the record, and so does a caller that
    has already read it: a field that is not there must not be turned into a
    "no photo found" skip, because that reads as something a person could fix.
    """
    result = skipped(field, str(why or "the record does not carry it"))
    result["verdict"] = "unreadable"
    result["plan_refused"] = True
    result["field_missing"] = True
    if record is not None:
        result["record_shape"] = {"keys": record_keys(record),
                                  "photo_fields": photo_field_report(record)}
    return result


def prove_listing(url, cookie="", listing=None, fields=None, photo="",
                  gallery_photo="", skip=None, why=None, absent=None,
                  record=None, now=None, fetch=None,
                  send=None, on_step=None):
    """Prove every field on one listing, one after another, and collect it.

    This is the same proof the panel runs one field at a time - write, read
    back, put back - done as one job, because a person asking "can this app
    write to this listing" should not have to answer it five times. Nothing
    runs unattended: the caller asks first, and this does the rest.

    ``skip`` is the fields an earlier proof already settled; they are reported
    as skipped rather than written again. A photo field with no photo to write
    is skipped with the reason, never guessed at.
    """
    results = []
    already = {str(field) for field in (skip or ())}
    reasons = dict(why or {})
    absent = {str(field) for field in (absent or ())}
    for field in (fields or proof_fields()):
        if field in absent:
            #  The record was read and has no such field: said as that, not as
            #  a photo that could not be found.
            results.append(missing_result(field, record=record,
                                          why=reasons.get(field, "")))
            continue
        if field in already:
            results.append(skipped(
                field, "was settled by an earlier proof and was not written "
                       "again.", earlier=True))
            continue
        trial = ""
        if field in photo_fields():
            #  Each photo field gets the photo chosen for it: the gallery must
            #  add one it does not already hold, so the caller's gallery choice
            #  is never quietly replaced with the main photo's.
            trial = absolute_photo(gallery_photo if field == "images" else photo)
            if not trial:
                reason = str(reasons.get(field) or
                             "no photo of this card could be found to prove it "
                             "with").strip()
                if not reason.endswith("."):
                    reason += "."
                results.append(skipped(field, "was not attempted: " + reason))
                continue
        result = prove(field, url, cookie, staged_url=trial, now=now,
                       fetch=fetch, send=send, listing=listing)
        results.append(result)
        if on_step is not None:
            try:
                on_step(result)
            except Exception:                      # a display must not stop it
                pass
    return results


def settled_result(result):
    """Whether this field is settled: proved now, or proved earlier and left."""
    if proven(result):
        return True
    return bool(result) and result.get("verdict") == "skipped" and \
        bool(result.get("settled_earlier"))


def proven_results(results):
    """The results that settled their field now or earlier."""
    return [result for result in (results or []) if settled_result(result)]


def not_here(result):
    """Whether the site's own record has no such field.

    That is not a failure to fix and not a fault in the app: the listing's
    record does not carry the field at all, so there is nothing to write and
    nothing to put back. It is said plainly, once, and it is not counted as
    something that needs attention - there is no action a person can take on
    the site.
    """
    return bool(result) and bool(result.get("field_missing")) and \
        bool(result.get("plan_refused"))


def unavailable_results(results):
    """The fields this site's record cannot hold."""
    return [result for result in (results or []) if not_here(result)]


def problem_results(results):
    """The fields that still need attention: refused, ignored, unknown, or not
    attempted at all - but not a field the site does not have."""
    return [result for result in (results or [])
            if not settled_result(result) and not not_here(result)]


def listing_sentence(results):
    """One line saying how a whole listing's proofs went."""
    results = list(results or [])
    if not results:
        return "No field was proved."
    good = proven_results(results)
    bad = problem_results(results)
    fresh = [result for result in good if proven(result)]
    earlier = len(good) - len(fresh)
    absent = unavailable_results(results)
    absent_names = ", ".join(result.get("label") or result.get("field")
                             for result in absent)
    if not bad and absent:
        return ("%d of %d fields are settled on this listing; %s %s not on "
                "this site's record, so there is nothing to prove or write "
                "there." % (len(good), len(results), absent_names,
                            "is" if len(absent) == 1 else "are"))
    if not bad:
        if earlier:
            return ("All %d fields are settled on this listing: %d proved now, "
                    "%d already settled by an earlier proof."
                    % (len(results), len(fresh), earlier))
        return ("All %d fields are settled on this listing: every one was "
                "written, read back and put back." % len(good))
    names = ", ".join(result.get("label") or result.get("field")
                      for result in bad)
    if not good:
        return ("No field is settled on this listing: %s need%s attention."
                % (names, "s" if len(bad) == 1 else ""))
    return ("%d of %d fields are settled; %s need%s attention."
            % (len(good), len(results), names,
               "s" if len(bad) == 1 else ""))


def listing_report_text(results, listing=None, app_version="", when=None):
    """Every field's proof as one file, with the problems and their fixes.

    A single proof is evidence for one field; this is evidence for the
    listing, which is what a plugin report needs when one field works and
    another does not.
    """
    results = list(results or [])
    listing = listing or {}
    stamp = when or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = str(listing.get("name") or listing.get("title") or "")
    listing_id = str(listing.get("id") or "")
    lines = ["CanadianShopper listing proof - %s" % stamp, "",
             "Alex Collect %s. Each field below was written to one listing, "
             "read back, and put back." % (app_version or ""),
             "No other field was sent, and your website was not touched.", ""]
    if title:
        lines.append("Listing:    %s" % title)
    if listing_id:
        lines.append("Listing id: %s   (the record's own id, not a product id)"
                     % listing_id)
    if results and results[0].get("url"):
        lines.append("Record:     %s" % results[0]["url"])
    lines += ["", "In short:   %s" % listing_sentence(results), ""]
    problems = problem_results(results)
    if problems:
        lines.append("Needs attention:")
        for result in problems:
            lines.append("  %-16s %s" % (field_label(result.get("field")) + ":",
                                         sentence(result)))
            fix = advice(result)
            if fix:
                lines.append("  %-16s %s" % ("", fix))
        lines.append("")
    for result in results:
        lines.append("-" * 70)
        lines.append(report_text(result, listing=listing, when=stamp,
                                 app_version=app_version).rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def sentence(result):
    """The one line the console says when the proof is done."""
    result = result or {}
    label = result.get("label") or field_label(result.get("field"))
    if result.get("verdict") == "skipped":
        why = str(result.get("why") or "").strip() or "it was not written."
        return "%s %s" % (label, why)
    if result.get("verdict") == "written" and result.get("restored"):
        return ("%s can be written at the record's own id: the site kept the "
                "new value and the old one is back." % label)
    if result.get("verdict") == "written" and result.get("restored") is False:
        return ("%s was written, but the old value was NOT put back - the "
                "record still shows %s. Put it back by hand before doing "
                "anything else." % (label,
                                    value_text(result.get("field"),
                                               result.get("final"))))
    if result.get("verdict") == "ignored":
        return ("%s is not proven: the site accepted the write and the record "
                "did not change." % label)
    if result.get("verdict") == "refused":
        return ("%s was refused by the site (HTTP %s); nothing was changed."
                % (label, result.get("status") or "?"))
    if result.get("verdict") == "unreadable":
        return ("No proof was attempted for %s: %s"
                % (label, result.get("why") or "the record could not be read."))
    return ("%s: the write was accepted but not readable back, so the field is "
            "still unknown." % label)


def report_text(result, listing=None, when=None, app_version=""):
    """The proof as a file: what was sent, what came back, what it means.

    Short on purpose - it is evidence, not a log. The request headers are never
    written, so the session cookie cannot be in it; the record's address is,
    because that is the thing the vendor's author needs to look at.
    """
    result = result or {}
    listing = listing or {}
    field = result.get("field") or ""
    label = result.get("label") or field_label(field)
    stamp = when or result.get("at") or datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S")
    lines = ["CanadianShopper field proof - %s" % stamp,
             "",
             "Alex Collect %s. One field was sent to one listing, read back, "
             "and put back." % (app_version or ""),
             "No other field was sent, and your website was not touched.",
             ""]
    title = (listing.get("name") or listing.get("title") or
             result.get("title") or "")
    listing_id = (listing.get("id") or result.get("listing") or "")
    if title:
        lines.append("Listing:    %s" % title)
    if listing_id:
        lines.append("Listing id: %s   (the record's own id, not a product id)"
                     % listing_id)
    if result.get("url"):
        lines.append("Record:     %s" % result["url"])
    lines += ["", "Field:      %s (%s)" % (label, field)]
    if result.get("old") is not None or result.get("verdict") == "written":
        lines.append("Before:     %s" % value_text(field, result.get("old")))
        lines.append("Wrote:      %s" % value_text(field, result.get("trial")))
        lines.append("Read back:  %s" % value_text(field, result.get("after")))
        if result.get("trial") is not None:
            lines.append("Put back:   %s"
                         % value_text(field, result.get("restore")))
        if result.get("final") is not None:
            lines.append("Final:      %s"
                         % value_text(field, result.get("final")))
    lines += ["", "Result:     %s" % (result.get("why") or sentence(result)),
              "In short:   %s" % sentence(result)]
    shape = result.get("record_shape") or {}
    if shape and str(shape.get("keys") or "") in str(result.get("why") or ""):
        #  The refusal sentence already carries every key and the photo-bearing
        #  fields; repeating them under a heading is the same paragraph twice.
        shape = {}
    if shape:
        #  A refusal about the record's shape is only useful with the shape in
        #  the file: this is what a plugin author needs to see, and it is what
        #  the person can read to know there is nothing to fix on the site.
        lines += ["", "The record's keys: %s" % shape.get("keys", "")]
        fields = shape.get("photo_fields") or []
        if fields:
            lines.append("Fields that could hold photos:")
            lines += ["  " + line for line in fields]
        else:
            lines.append("No field on the record is a list of photos, and none "
                         "is named for pictures.")
    lines += ["", "Steps:"]
    for number, step in enumerate(result.get("steps") or [], 1):
        status = step.get("status")
        lines.append("  %d. %s -> %s" % (
            number, step.get("step"),
            "HTTP %s" % status if status else "no answer"))
        if step.get("sent") not in (None, ""):
            lines.append("       sent: %s" % value_text(field, step["sent"]))
        if step.get("body"):
            lines.append("       answer: %s" % step["body"])
    if result.get("verdict") == "written":
        lines += ["", "What this settles:",
                  "  %s is written at the record's own id, read back, and put "
                  "back." % field]
        if not result.get("restored"):
            lines += ["",
                      "  ! The old value was not read back after the restore.",
                      "  ! The record still shows %s."
                      % value_text(field, result.get("final"))]
    lines += ["", "No cookie, token or password is in this file."]
    return "\n".join(lines) + "\n"


def proof_path(folder, now=None):
    """Where a proof file goes: dated to the second, never overwriting one."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = Path(folder) / ("cs-proof-%s" % stamp)
    path = base.with_suffix(".txt")
    number = 2
    while path.exists():
        path = Path("%s-%d.txt" % (base, number))
        number += 1
    return path


def load_proofs(folder):
    """What earlier proofs settled, ``{field: entry}``; ``{}`` when none have."""
    try:
        data = json.loads((Path(folder) / PROOFS_FILE).read_text(
            encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def remember(folder, result, listing=None, now=None):
    """Record one proof's outcome, so a later question does not re-run it.

    A field is kept as proven only while the last proof that touched it was
    **written and put back**: a refusal, an ignored write or a failed restore
    replaces the entry, because a proof that stopped being true is worse than
    no proof at all.
    """
    folder = Path(folder)
    data = load_proofs(folder)
    result = result or {}
    listing = listing or {}
    field = str(result.get("field") or "")
    if not field:
        return {}
    data[field] = {"at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
                   "verdict": result.get("verdict") or "",
                   "restored": result.get("restored"),
                   "proven": proven(result),
                   "listing": str(listing.get("id") or
                                  result.get("listing") or ""),
                   "title": str(listing.get("name") or
                                result.get("title") or "")[:200]}
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / PROOFS_FILE).write_text(
            json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True),
            encoding="utf-8")
    except OSError:
        return {}
    return data


def proven(result):
    """Whether one result leaves its field proven - written *and* put back."""
    return bool(result) and result.get("verdict") == "written" \
        and result.get("restored") is True


def settled(field, proofs):
    """Whether the saved proofs say a field is proven writable."""
    entry = (proofs or {}).get(str(field or "")) or {}
    return bool(entry.get("proven"))
