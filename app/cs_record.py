#!/usr/bin/env python3
"""Write a listing's own record - every field a proof has settled, and no other.

A proof (``cs_proof.py``) settles one field at one address: it writes a marked
value to ``/api/data/product/<listing-id>``, reads the record back, puts the old
value back and reads it again. When that says *written and restored*, the field
is proven at that address - which is the only evidence this module accepts.

So the rules here are short and hard:

* **the address is the record's own id**, the one the reader reports for the
  listing and the one a proof wrote to. It is never called a product id, it is
  never taken from ``/api/products/<product_id>/``, and a row that does not say
  its own id is not addressed at all;
* **only a proven field is written.** :func:`writable_fields` reads
  ``cs-field-proofs.json`` and returns the fields whose last proof kept the
  value and gave the old one back. Every write re-reads it, so deleting the file
  closes the path again. A field nobody proved is never sent, however sure the
  panel is about it;
* **the record is read first**, and its own id must be the id that was asked
  for. A record at that address that names a different id is not the listing
  that was chosen, and nothing is sent;
* **the values the person confirmed must still be there.** Each change carries
  what the row said; if the record now differs, nothing is written and the
  panel says what it found. A confirmation about 8.50 must never turn into a
  write of something else;
* **one request, only the changed fields.** A form where a title and a price
  were both edited sends both, and nothing else - so a field nobody touched
  cannot move with a field they did;
* **the write is read back, field by field**, because a 200 is not a value. Each
  field is reported as written, ignored (the record still shows the old value),
  or unknown (the read-back said nothing) - never guessed.

``status`` is not a field here at all: it is not one a proof can settle (see
``cs_proof.UNPROVABLE``), so there is nothing to send and no button for it.

Nothing here touches the website, the plugin, or ``/api/products/...``.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime

import cs_edit
import cs_listing
import cs_proof

#: The fields this module can write, in the order a form shows them: exactly
#: the fields a proof can settle. ``status`` is absent on purpose.
KNOWN_FIELDS = tuple(field for field, _label in cs_proof.FIELDS)

FIELD_LABELS = dict(cs_proof.FIELD_LABELS)

#: A price of zero is not written from here: on a marketplace a zero is almost
#: always a mistake, and it makes the card free while the shop keeps selling
#: it. If a card is really being given away, that is set in the dashboard.
REFUSE_ZERO = True

#: eBay refuses a title longer than 80 characters; CanadianShopper may allow
#: more, but a title pasted from an eBay listing that is refused there is
#: better refused here, before a write, with the reason.
TITLE_LIMIT = 80

#: The fields whose row value is checked against the record before a write.
#: The main photo is not one of them: a catalogue row carries the shop's own
#: URL while the record carries the site's hosted file, so a difference there
#: is normal - the read-back still proves what happened.
GUARDED = ("priceCad", "title", "description", "inventory")


def field_label(field):
    return FIELD_LABELS.get(str(field or ""), str(field or ""))


def writable_fields(proofs=None):
    """The fields a saved proof has settled, in form order."""
    return tuple(field for field in KNOWN_FIELDS
                 if cs_proof.settled(field, proofs))


def locked_fields(proofs=None):
    """The fields with no proof behind them - offered, never written."""
    settled = set(writable_fields(proofs))
    return tuple(field for field in KNOWN_FIELDS if field not in settled)


def money(value):
    """A price as the write sends it: ``"12.50"``, or ``""`` when unreadable.

    A minus sign is honoured rather than stripped: the app's price reader takes
    the digits out of ``"CA$8.50"``, and it would take the digits out of
    ``-1`` as well - which would turn a rejected price into a written one.
    """
    text = str(value if value is not None else "").strip()
    if not text or "-" in text.replace("\u2013", "-"):
        return ""
    number = cs_edit.price_number({"price": text})
    if number is None or number < 0:
        return ""
    return "%.2f" % number


def clean(field, value):
    """A field's value as it is sent, or ``""`` when it cannot be read.

    The shape each field takes is the site's own: money as ``"12.50"``, a
    count as a whole number, a title with its runs of spaces folded, a
    description exactly as typed, and a photo as a web address.
    """
    field = str(field or "")
    if field == "priceCad":
        return money(value)
    if field == "inventory":
        text = str(value if value is not None else "").strip()
        try:
            number = int(text)
        except (TypeError, ValueError):
            return ""
        return number if number >= 0 else ""
    if field == "title":
        return " ".join(str(value or "").split())
    if field == "description":
        return str(value if value is not None else "").strip()
    if field == "primaryImageUrl":
        text = str(value or "").strip()
        return text if text.lower().startswith(("http://", "https://")) else ""
    return ""


def refuse_reason(field, value, proofs=None):
    """Why one field cannot be written at all, or ``""`` when it can."""
    field = str(field or "")
    if field not in KNOWN_FIELDS:
        if field in cs_proof.UNPROVABLE:
            return ("%s is not written from here: %s."
                    % (field_label(field) or field,
                       cs_proof.UNPROVABLE[field]))
        return "%s is not a field this app writes." % (field_label(field) or
                                                       field)
    if proofs is not None and not cs_proof.settled(field, proofs):
        return ("%s has not been proven writable on this site, so nothing is "
                "sent. Run \"Prove a field can be written\" for %s first: a "
                "write path with no proof behind it is exactly what must not "
                "exist." % (field_label(field), field_label(field).lower()))
    text = str(value if value is not None else "")
    if field == "priceCad":
        if "-" in text:
            return ("A price cannot be negative: %r is not a price this app "
                    "will write." % (value,))
        if not money(value):
            return ("%r is not a price, so there is nothing to write."
                    % (value,))
        if REFUSE_ZERO and float(money(value)) == 0:
            return ("A price of zero is not written from here - on a "
                    "marketplace that is almost always a mistake, and it makes "
                    "the card free. Set a zero price in the vendor dashboard if "
                    "it is really meant.")
    elif field == "inventory":
        if clean(field, value) == "":
            return ("%r is not a whole number of cards, so there is nothing to "
                    "write." % (value,))
    elif field == "title":
        title = clean(field, value)
        if not title:
            return ("A listing needs a title - an empty one leaves the card "
                    "with nothing to be found by.")
        if len(title) > TITLE_LIMIT:
            return ("That title is %d characters; a marketplace refuses one "
                    "longer than %d. Cut it first - nothing was sent."
                    % (len(title), TITLE_LIMIT))
    elif field == "description":
        if not clean(field, value):
            return "An empty description is not written from here."
    elif field == "primaryImageUrl":
        if not clean(field, value):
            return "%r is not a web address, so it is not a photo." % (value,)
    return ""


def note_for(field, proofs=None):
    """The one line a panel shows about the evidence behind a write."""
    entry = (proofs or {}).get(str(field or "")) or {}
    if not entry.get("proven"):
        return ""
    return ("%s was proven writable%s%s." %
            (field_label(field),
             " at %s" % entry.get("at") if entry.get("at") else "",
             " on %s" % entry.get("title") if entry.get("title") else ""))


def evidence_note(proofs=None):
    """What can be edited on this machine, in one sentence."""
    open_fields = writable_fields(proofs)
    if not open_fields:
        return ("No field has been proven writable on this site yet, so this "
                "app will not write to a listing's record. Run \"Prove a field "
                "can be written\" for the field to change.")
    words = ", ".join(field_label(field).lower() for field in open_fields)
    locked = locked_fields(proofs)
    said = "Proven writable here: %s." % words
    if locked:
        said += (" Not proven, so never sent: %s."
                 % ", ".join(field_label(field).lower() for field in locked))
    return said


def _row_value(item, field):
    """What the row on the panel said a field holds, as the form shows it."""
    item = item or {}
    if field == "priceCad":
        text = cs_edit.price_text(item)
        return money(text) or text
    if field == "title":
        return str(item.get("name") or item.get("title") or "").strip()
    if field == "inventory":
        qty = item.get("qty")
        return "" if qty is None else str(int(qty))
    if field == "description":
        return str(item.get("description") or "").strip()
    if field == "primaryImageUrl":
        for image in item.get("images") or []:
            if isinstance(image, str) and image.strip():
                return image.strip()
            if isinstance(image, dict) and image.get("src"):
                return str(image["src"]).strip()
        return ""
    return ""


def current_value(item, field):
    """What the row on the panel says a field holds, as a form opens it."""
    return _row_value(item, field)


def plan_update(item, changes, proofs=None):
    """One listing's edit: what would be sent, or why nothing would be.

    ``changes`` is ``{field: value}`` as the form holds them. Only fields whose
    value actually differs from the row are kept - a form saved untouched is
    not a write of the values it opened with.
    """
    item = item or {}
    listing_id = cs_edit.listing_id(item)
    card = str(item.get("name") or item.get("title") or "").strip()
    entry = {"id": listing_id if cs_edit.is_id(listing_id) else "",
             "card": card, "fields": []}
    if not entry["id"]:
        return {"why": ("The list carries no record id for %s, so there is no "
                        "record to address. Nothing was sent."
                        % (card or "that listing")),
                "card": card, "id": "", "fields": []}
    if not proofs or not writable_fields(proofs):
        return {"why": ("No field has been proven writable on this site, so "
                        "nothing is sent. Run \"Prove a field can be written\" "
                        "first."), "card": card, "id": entry["id"],
                "fields": []}
    wanted = []
    for field, value in (changes or {}).items():
        field = str(field or "")
        if field not in KNOWN_FIELDS:
            continue
        old = _row_value(item, field)
        new = clean(field, value)
        #  An untouched field is not a change, however it is spelled: the form
        #  opens on the row's own values, and comparing the cleaned forms is
        #  what keeps "8.5" from reading as a change of "8.50".
        if not new and not str(value or "").strip():
            continue
        if old and cs_proof.same(field, new, old):
            continue
        if not new and old:
            #  Cleared on purpose: refused per field, with the reason.
            return {"why": refuse_reason(field, "", proofs) or
                    ("%s cannot be emptied from here." % field_label(field)),
                    "card": card, "id": entry["id"], "fields": []}
        why = refuse_reason(field, value, proofs)
        if why:
            return {"why": why, "card": card, "id": entry["id"],
                    "fields": []}
        wanted.append({"field": field, "label": field_label(field),
                       "old": old, "value": new})
    if not wanted:
        return {"why": "", "card": card, "id": entry["id"], "fields": [],
                "same": True}
    entry["fields"] = wanted
    return entry


def plan(item, price, proofs=None):
    """:func:`plan_update` for the one field a quick price change touches."""
    entry = plan_update(item, {"priceCad": price}, proofs)
    entry.update(field="priceCad", label="Price")
    #  The price dialog needs both numbers even when nothing would be sent:
    #  "already shows 1.00" is a sentence built from them.
    entry.setdefault("old", _row_value(item, "priceCad"))
    entry.setdefault("price", clean("priceCad", price))
    if entry.get("fields"):
        change = entry["fields"][0]
        entry.update(old=change["old"], price=change["value"])
    return entry


def describe(entry, change=None):
    """``old -> new`` in the words the confirmation uses."""
    entry = entry or {}
    if change is None:
        old = entry.get("old") or "no price on the list"
        return "%s:  %s  ->  %s" % (entry.get("card") or "That listing",
                                    old, entry.get("price") or "?")
    return "%s:  %s  ->  %s" % (
        change.get("label") or field_label(change.get("field")),
        change.get("old") or "(empty)",
        change.get("value") if not isinstance(change.get("value"), str)
        else (change["value"] or "(empty)"))


def describe_lines(entry):
    """Every change in a plan, one per line, for a confirmation."""
    return [describe(entry, change) for change in (entry or {}).get("fields")]


def url_for(listing_id, base="https://canadianshopper.ca"):
    """The record's address, from the record's own id and nothing else."""
    return cs_edit.detail_url(listing_id, base)


def _record_id(record):
    """The id a record says it has, as text, or ``""``."""
    for key in ("id", "listing_id", "listingId", "listing"):
        if key not in (record or {}):
            continue
        value = record.get(key)
        if isinstance(value, (dict, list)) or value in (None, ""):
            continue
        return str(value).strip()
    return ""


def _snippet(body, limit=240):
    text = " ".join(str(body or "").split())
    return text[:limit] + ("\u2026" if len(text) > limit else "")


def send_fields(url, cookie, payload, opener=None, timeout=25):
    """``PATCH`` one record with the changed fields; ``(status, body)``.

    The body is exactly what the caller built - one field for a price, or the
    handful a form changed - and never a whole record read back from the site.
    """
    if opener is not None:
        return opener(url, cookie, payload)
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        method="PATCH",
        headers={"User-Agent": "Mozilla/5.0 (AlexCollect-GUI)",
                 "Accept": "application/json",
                 "Content-Type": "application/json",
                 "Cookie": str(cookie or "")})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (getattr(response, "status", 200),
                    response.read(200000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(200000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, body
    except Exception as exc:
        return 0, str(exc)


#: The old name of the sender, kept because a caller (and a test) may name it.
send_price = send_fields


def update(url, cookie, changes, expect_id="", listing=None, proofs=None,
           fetch=None, send=None, expected=None):
    """Read the record, write the changed proven fields, read it back.

    ``changes`` is ``{field: value}``; ``expected`` is what the row said those
    fields held, used to refuse a write when the record has moved since. The
    answer carries one verdict per field and one for the whole edit, so a form
    that changed three things gets three answers rather than one guess.
    """
    fetch = fetch or cs_proof.read_record
    send = send or send_fields
    listing = listing or {}
    expected = dict(expected or {})
    result = {"url": url, "id": str(expect_id or ""),
              "card": str(listing.get("name") or listing.get("title") or ""),
              "status": 0, "verdict": "", "written": False, "steps": [],
              "fields": [], "why": ""}
    prepared, refused = [], []
    for field, value in (changes or {}).items():
        field = str(field or "")
        label = field_label(field)
        why = refuse_reason(field, value, proofs)
        if why:
            refused.append({"field": field, "label": label, "why": why})
            continue
        prepared.append({"field": field, "label": label,
                         "value": clean(field, value),
                         "expected": expected.get(field)})
    if refused:
        result.update(verdict="unproven" if all(
            "proven writable" in entry["why"] for entry in refused)
            else "refused",
            why=" ".join(entry["why"] for entry in refused))
        result["fields"] = [dict(entry, verdict="refused") for entry in refused]
        return result
    if not prepared:
        result.update(verdict="same", why="Nothing was changed, so nothing "
                                           "was sent.")
        return result
    if not url or not cs_edit.is_id(expect_id):
        result.update(verdict="unreadable",
                      why=("There is no record id to address, so nothing was "
                           "sent."))
        return result

    status, body = fetch(url, cookie)
    result["steps"].append({"step": "GET the record", "status": status})
    record = cs_proof._record(body) if status == 200 else None
    if record is None:
        result.update(verdict="unreadable",
                      why=("The record could not be read (%s), so nothing was "
                           "written: the values that are there now cannot be "
                           "checked or compared."
                           % ("HTTP %s" % status if status else "no answer")))
        return result

    found_id = _record_id(record)
    if not found_id or str(found_id).strip() != str(expect_id).strip():
        result["steps"].append({"step": "the record names %s"
                                % (found_id or "no id"), "status": 200})
        result.update(
            verdict="refused",
            why=("The record at that address says it is listing %s, not %s. "
                 "Nothing was written: writing the wrong listing's details is "
                 "the one mistake this path must never make."
                 % (found_id or "(no id)", expect_id)))
        return result

    payload, plans = {}, []
    for entry in prepared:
        found, old = cs_proof.record_value(record, entry["field"])
        if not found:
            entry.update(old=None, verdict="refused",
                         why=("The record does not carry %s, so a write to it "
                              "cannot be read back. Nothing was sent."
                              % entry["label"].lower()))
            plans.append(entry)
            continue
        if cs_proof.same(entry["field"], old, entry["value"]):
            entry.update(old=old, verdict="same",
                         why="The record already holds that value.")
            plans.append(entry)
            continue
        wanted = entry.get("expected")
        if (entry["field"] in GUARDED and wanted not in (None, "")
                and not cs_proof.same(entry["field"], old, wanted)):
            entry.update(old=old, verdict="changed",
                         why=("The record shows %s now, not the %s that was "
                              "confirmed. Nothing was written for it."
                              % (_value_text(entry["field"], old),
                                 _value_text(entry["field"], wanted))))
            plans.append(entry)
            continue
        entry["old"] = old
        payload[entry["field"]] = entry["value"]
        plans.append(entry)
    result["fields"] = plans
    if not payload:
        verdicts = {entry["verdict"] for entry in plans}
        if verdicts == {"same"}:
            result.update(verdict="same",
                          why=("The record already holds those values, so "
                               "nothing was sent."))
        elif verdicts == {"refused"}:
            result.update(verdict="refused",
                          why=" ".join(entry.get("why") or "" for entry in
                                       plans))
        else:
            result.update(verdict="changed",
                          why=" ".join(entry.get("why") or "" for entry in
                                       plans))
        return result

    written_status, written_body = send(url, cookie, payload)
    result["status"] = written_status
    result["steps"].append({"step": "PATCH %s" % ", ".join(payload),
                            "status": written_status,
                            "sent": dict(payload),
                            "body": "" if 200 <= written_status < 300
                            else _snippet(written_body)})
    if not 200 <= written_status < 300:
        for entry in plans:
            if entry["field"] in payload:
                entry.update(verdict="refused",
                             why=("The site refused the write (%s). The "
                                  "listing still shows what it did."
                                  % ("HTTP %s" % written_status
                                     if written_status
                                     else written_body or "no answer")))
        result.update(verdict="refused",
                      why=("The site refused the write (%s). Nothing was "
                           "changed for the field%s that were sent."
                           % ("HTTP %s" % written_status if written_status
                              else "no answer",
                              "" if len(payload) == 1 else "s")))
        return result

    after_status, after_body = fetch(url, cookie)
    result["steps"].append({"step": "GET the record", "status": after_status})
    after_record = cs_proof._record(after_body) if after_status == 200 else None
    if after_record is None:
        for entry in plans:
            if entry["field"] in payload:
                entry.update(verdict="unknown",
                             why=("The write was accepted but could not be read "
                                  "back, so the field is unconfirmed."))
        result.update(verdict="unknown",
                      why=("The site accepted the write but the record could "
                           "not be read back (%s), so this app cannot say what "
                           "the listing holds now. Check that listing on "
                           "CanadianShopper."
                           % ("HTTP %s" % after_status if after_status
                              else "no answer")))
        return result

    for entry in plans:
        if entry["field"] not in payload:
            continue
        after = cs_proof.record_value(after_record, entry["field"])[1]
        entry["after"] = after
        if cs_proof.same(entry["field"], after, entry["value"]):
            entry.update(verdict="written",
                         why=_written_note(entry, after))
        elif cs_proof.same(entry["field"], after, entry["old"]):
            entry.update(verdict="ignored",
                         why=("The site answered HTTP %s but the record still "
                              "shows %s: the write was accepted and %s was not "
                              "kept. The listing is unchanged."
                              % (written_status,
                                 _value_text(entry["field"], entry["old"]),
                                 entry["label"].lower())))
        else:
            entry.update(verdict="written",
                         why=("The record shows %s rather than the %s that was "
                              "sent - the value was kept, and the site stored "
                              "it its own way."
                              % (_value_text(entry["field"], after),
                                 _value_text(entry["field"], entry["value"]))))

    verdicts = [entry.get("verdict") for entry in plans
                if entry["field"] in payload]
    written = [name for name in verdicts if name == "written"]
    result["written"] = bool(written)
    if verdicts and len(written) == len(verdicts):
        result["verdict"] = "written"
    elif written:
        result["verdict"] = "partial"
    elif verdicts and all(name == "ignored" for name in verdicts):
        result["verdict"] = "ignored"
    else:
        result["verdict"] = "ignored"
    result["why"] = " ".join(entry.get("why") or "" for entry in plans
                             if entry["field"] in payload)
    return result


def add_gallery_photo(url, cookie, photo, expect_id="", listing=None, key="",
                      shape="", fetch=None, send=None, now=None):
    """Add one photo to a listing's gallery - and keep it there.

    This is the one write in this app that does not put the old value back,
    because the old value is what the person is changing: they want a second
    picture on the listing. It is used where a *proof* cannot help - a record
    that carries no gallery at all has no value to restore, so the field would
    have to be created, and nothing can be proved about a field that is not
    there yet.

    So the rule is different, and stated before anything is sent: the photo
    written is the photo the person chose, never a placeholder; the record is
    read back afterwards; and if the site does not show it, nothing changed and
    the answer says so.

    ``key`` is the name the site gives a gallery when a caller has learned it
    (see ``cs_proof.gallery_survey``); ``images`` is used when it has not.
    ``shape`` is ``"map"`` when the site's gallery holds objects rather than
    addresses. Returns the result, with a ``verdict``:

    ``added``      the site took it and the record shows the photo now;
    ``same``       the gallery already held that photo, so nothing was sent;
    ``ignored``    the site answered and the record does not show it;
    ``refused``    the site answered with anything but a 2xx;
    ``unreadable`` the record could not be read, so nothing was written;
    ``unknown``    the write was accepted but the read-back could not be read.
    """
    fetch = fetch or cs_proof.read_record
    send = send or send_fields
    now = now or datetime.now()
    listing = listing or {}
    photo = cs_proof.absolute_photo(photo)
    result = {"url": url, "id": str(expect_id or ""), "field": "images",
              "label": cs_proof.field_label("images"), "key": str(key or ""),
              "photo": photo, "before": 0, "after": 0, "created": False,
              "steps": [], "verdict": "", "written": False, "why": "",
              "at": now.strftime("%Y-%m-%d %H:%M:%S"),
              "card": str(listing.get("name") or listing.get("title") or "")}
    if not photo or not photo.lower().startswith(("http://", "https://")):
        result.update(verdict="refused",
                      why=("There is no web address for the photo to add, so "
                           "nothing was sent. A gallery holds pictures the "
                           "site can show, not a file on this computer."))
        return result
    if not url or not cs_edit.is_id(expect_id):
        result.update(verdict="unreadable",
                      why=("There is no record id to address, so nothing was "
                           "sent."))
        return result

    status, body = fetch(url, cookie)
    result["steps"].append({"step": "GET the record", "status": status})
    record = cs_proof._record(body) if status == 200 else None
    if record is None:
        result.update(verdict="unreadable",
                      why=("The record could not be read (%s), so nothing was "
                           "written: what the gallery holds now cannot be "
                           "checked, and a photo added blind could be a second "
                           "copy of one already there."
                           % ("HTTP %s" % status if status else "no answer")))
        return result

    found_id = _record_id(record)
    if found_id and str(found_id).strip() != str(expect_id).strip():
        result["steps"].append({"step": "the record names %s" % found_id,
                                "status": 200})
        result.update(
            verdict="refused",
            why=("The record at that address says it is listing %s, not %s. "
                 "Nothing was written: adding a photo to the wrong listing is "
                 "the one mistake this path must never make."
                 % (found_id, expect_id)))
        return result

    #  The site's own key when it has one; the surveyed name when a caller
    #  learned it from the site's other records; ``images`` as the fallback.
    key = str(key or "").strip() or cs_proof.gallery_key(record) or "images"
    result["key"] = key
    entries = []
    if key in record:
        value = record.get(key)
        entries = list(value) if isinstance(value, (list, tuple)) else [value]
        #  A field with that name is only a gallery when it holds addresses a
        #  browser could open: a list of words is not a gallery, and writing
        #  into it would be writing into somebody else's field.
        addresses = [url for url in cs_proof.gallery_keys(entries)
                     if str(url).lower().startswith(("http://", "https://"))]
        if not addresses:
            result.update(
                verdict="refused",
                why=("The record's %s field does not hold photo addresses, so "
                     "it is not a gallery and is not written. Nothing was "
                     "sent." % key))
            return result
    result["before"] = len(addresses if key in record else ())
    result["created"] = key not in record
    #  Compared by the file each address names: the site may write the same
    #  picture as a path, a host and a path, or a resized variant, and one
    #  photo written twice is how a gallery grows a duplicate.
    have = {cs_proof.photo_id(url) for url in cs_proof.gallery_keys(entries)}
    if cs_proof.photo_id(photo) in have:
        result.update(verdict="same",
                      why="The listing's gallery already holds that photo.")
        return result
    entry = cs_proof.like_others(entries, photo)
    if entry is None:
        result.update(verdict="refused",
                      why="The photo could not be written as a gallery entry.")
        return result
    payload = {key: entries + [entry]}

    status, body = send(url, cookie, payload)
    result["steps"].append({"step": "PATCH the gallery", "status": status,
                            "sent": key})
    if not 200 <= int(status or 0) < 300:
        result.update(verdict="refused",
                      why=("The site refused the write (%s), so nothing was "
                           "added. %s"
                           % ("HTTP %s" % status if status else "no answer",
                              _snippet(body))))
        return result
    result["written"] = True

    status, body = fetch(url, cookie)
    result["steps"].append({"step": "GET the record back", "status": status})
    after = cs_proof._record(body) if status == 200 else None
    if after is None:
        result.update(verdict="unknown",
                      why=("The site accepted the photo but the record could "
                           "not be read back (%s), so whether it is in the "
                           "gallery is unknown. Look at the listing before "
                           "adding it again."
                           % ("HTTP %s" % status if status else "no answer")))
        return result
    shown = cs_proof.gallery_keys(after.get(key) or [])
    result["after"] = len(shown)
    if cs_proof.photo_id(photo) in {cs_proof.photo_id(url) for url in shown}:
        result.update(verdict="added",
                      why=("The record shows the photo in its %s field, so the "
                           "listing's gallery holds it now." % key))
        return result
    result.update(verdict="ignored",
                  why=("The site accepted the write and the record does not "
                       "show the photo: %s holds %d photo%s, as it did before. "
                       "Nothing was added, and nothing was left behind."
                       % (key, len(shown), "" if len(shown) == 1 else "s")))
    return result


def add_sentence(result):
    """What happened when a photo was added, in one sentence."""
    result = result or {}
    what = cs_proof.field_label(result.get("field") or "images").lower()
    key = str(result.get("key") or "images")
    verdict = result.get("verdict")
    if verdict == "added":
        return ("The photo is in the listing's gallery: %s now holds %d "
                "photo%s. It was kept, because that is what was asked for."
                % (key, result.get("after") or 1,
                   "" if (result.get("after") or 1) == 1 else "s"))
    if verdict == "same":
        return ("That photo was already in the listing's gallery, so nothing "
                "was sent.")
    if verdict == "ignored":
        return ("The site accepted the photo and the record does not show it, "
                "so the %s field it was sent to is not one this listing "
                "writes." % what)
    if verdict == "refused":
        return "The photo was not added: %s" % (result.get("why") or
                                                "the site refused it.")
    if verdict == "unknown":
        return ("The site took the write, but the record could not be read "
                "back - check the listing before adding the photo again.")
    return "The photo was not added: %s" % (result.get("why") or "no answer.")


def add_advice(result):
    """What to do about it, when there is anything to do."""
    verdict = (result or {}).get("verdict")
    if verdict == "added":
        return ("The gallery is a field on this listing now, so 'Prove every "
                "field' can settle it and every later gallery edit is read "
                "back like the rest.")
    if verdict == "ignored":
        return ("Nothing changed on the site and there is nothing to fix "
                "here: this site does not keep a gallery on the listing's "
                "record. The proof file is the evidence for a plugin report.")
    if verdict == "unknown":
        return ("Open the listing on CanadianShopper and look before adding "
                "the photo again - the site took the write, so it may be "
                "there.")
    if verdict == "refused":
        return ("Nothing was written. %s" % (result.get("why") or ""))
    return ""


def _written_note(entry, after):
    label = entry.get("label") or field_label(entry.get("field"))
    return ("%s now reads %s, read back after the write."
            % (label, _value_text(entry.get("field"), after)))


def _value_text(field, value):
    """A value as a sentence quotes it, short for words nobody reads in full."""
    if value is None:
        return "nothing"
    if field == "priceCad":
        return money(value) or str(value)
    if field == "description":
        text = " ".join(str(value).split())
        return "%r and %d more characters" % (text[:60], len(text) - 60) \
            if len(text) > 60 else repr(text)
    text = str(value)
    return text if len(text) <= 80 else "%s\u2026" % text[:80]


def write(url, cookie, price, expect_id="", expect_old=None, listing=None,
          field="priceCad", proofs=None, fetch=None, send=None):
    """One field, the quick way - :func:`update` with a single change.

    Kept as its own function because it is what the price-only callers use (a
    bulk reprice, a one-line price change) and because its answer is one
    field's, not a form's.
    """
    result = update(url, cookie, {field: price}, expect_id=expect_id,
                    listing=listing, proofs=proofs, fetch=fetch, send=send,
                    expected={field: expect_old})
    if len(result.get("fields") or []) == 1:
        entry = result["fields"][0]
        result.update(old=entry.get("old"), after=entry.get("after"),
                      sent=entry.get("value"),
                      why=entry.get("why") or result.get("why"))
        if (entry.get("verdict") and result.get("verdict") != "unproven"):
            #  One field's answer is that field's verdict - except when the
            #  field was never sent at all, which "unproven" already says.
            result["verdict"] = entry["verdict"]
            result["written"] = entry["verdict"] == "written"
    result["field"] = field
    result["label"] = field_label(field)
    return result


def sentence(result):
    """One line for the console, in the words the outcome deserves."""
    result = result or {}
    card = result.get("card") or "that listing"
    verdict = result.get("verdict")
    fields = [entry for entry in result.get("fields") or []]
    labels = ", ".join(entry.get("label") or field_label(entry.get("field"))
                       for entry in fields) or "The change"
    if verdict == "written":
        written = [entry for entry in fields
                   if entry.get("verdict") == "written"]
        if len(fields) == 1 and written:
            return ("%s: %s (your website was not touched)."
                    % (card, written[0].get("why") or "the value was written"))
        return ("%s changed on CanadianShopper (%s; your website was not "
                "touched)." % (card, labels))
    if verdict == "partial":
        kept = ", ".join(entry.get("label") for entry in fields
                         if entry.get("verdict") == "written")
        lost = ", ".join(entry.get("label") for entry in fields
                         if entry.get("verdict") != "written")
        return ("%s: %s now, %s not kept - see the lines above."
                % (card, kept or "nothing", lost or "nothing"))
    if verdict == "same":
        return "%s already holds those values; nothing was sent." % card
    if verdict in ("changed",):
        return "Not written for %s: %s" % (card, result.get("why"))
    if verdict == "ignored":
        return ("Not changed for %s: the site answered HTTP 200 and kept the "
                "old value - the write was accepted and not kept, so the "
                "listing is unchanged." % card)
    if verdict == "unknown":
        return ("%s: the write was accepted but not readable back, so nothing "
                "here can say it took. Check that listing on CanadianShopper."
                % card)
    if verdict == "unproven":
        return "No change was written: %s" % result.get("why")
    if verdict == "refused":
        return "Not changed for %s: %s" % (card, result.get("why"))
    return ("%s: %s" % (card, result.get("why") or "the write's outcome is "
                        "unknown."))


#  --------------------------------------------------------------------------
#  What differs, for the comparison panel
#  --------------------------------------------------------------------------

def price_plan(pairs, catalog=None, proofs=None):
    """The listings whose price on the site differs from the website's.

    ``pairs`` are the comparison's own pairs (a website product and the listing
    it was matched to), and ``catalog`` is the website product behind each one.
    A card whose two prices already agree is left out - this is a list of what
    to change, not a list of the store. Everything that is left out for a
    reason a person can act on is counted, so a short list never shrinks
    silently.
    """
    catalog = catalog or {}
    items, notes = [], {"no_id": 0, "no_site_price": 0, "no_listing_price": 0,
                        "free": 0, "skipped": 0}
    for pair in pairs or []:
        woo = (pair or {}).get("woo") or {}
        other = (pair or {}).get("other") or {}
        if not isinstance(woo, dict) or not isinstance(other, dict):
            notes["skipped"] += 1
            continue
        product = catalog.get(str(woo.get("id"))) if woo.get("id") is not None \
            else None
        website_price = money(cs_listing.price_text(product or {}))
        if not website_price:
            notes["no_site_price"] += 1
            continue
        listing_price = cs_edit.price_number(other)
        if listing_price is None:
            notes["no_listing_price"] += 1
            continue
        if float(website_price) == 0:
            notes["free"] += 1
            continue
        listing_id = cs_edit.listing_id(other)
        if not cs_edit.is_id(listing_id):
            notes["no_id"] += 1
            continue
        old = "%.2f" % listing_price
        if abs(float(old) - float(website_price)) < 0.005:
            continue
        items.append({"field": "priceCad", "label": field_label("priceCad"),
                      "id": listing_id,
                      "card": str(woo.get("name") or other.get("name") or ""),
                      "old": old, "price": website_price,
                      "state": ""})
    return {"items": items, "notes": notes,
            "proven": cs_proof.settled("priceCad", proofs)}


def plan_summary(plan_result, label="CanadianShopper"):
    """One sentence saying what a price plan would change."""
    plan_result = plan_result or {}
    items = plan_result.get("items") or []
    if not items:
        return "Nothing to reprice: no compared card has a different price."
    return ("%d listing%s on %s would be set to the website's price."
            % (len(items), "" if len(items) == 1 else "s", label))


def plan_lines(plan_result, limit=12):
    """The plan card by card, cut to what a confirmation can show."""
    items = (plan_result or {}).get("items") or []
    lines = ["%s:  %s  ->  %s" % (item["card"] or "That listing", item["old"],
                                  item["price"]) for item in items]
    if limit and len(lines) > limit:
        lines = lines[:limit] + ["  ... and %d more" % (len(lines) - limit)]
    return lines


def write_all(items, cookie, base="https://canadianshopper.ca", proofs=None,
              fetch=None, send=None, on_step=None):
    """Write one price at a time, in order, collecting every answer.

    One listing at a time on purpose: a bulk call to a route nobody documents
    is exactly where a wrong id would take a hundred listings with it. A
    failure does not stop the rest - each listing is addressed and read back on
    its own - but the report keeps every answer, so a run is never summed up
    as "done".
    """
    results = []
    for number, item in enumerate(items or [], 1):
        result = write(url_for(item.get("id"), base), cookie,
                       item.get("price"), expect_id=item.get("id"),
                       expect_old=item.get("old"), listing=item,
                       proofs=proofs, fetch=fetch, send=send)
        results.append(result)
        if on_step is not None:
            try:
                on_step(number, len(items), result)
            except Exception:
                pass
    return results


def tally(results):
    """``(written, unchanged, failed)`` for a finished run."""
    written, unchanged, failed = 0, 0, 0
    for result in results or []:
        if result.get("verdict") == "written":
            written += 1
        elif result.get("verdict") == "same":
            unchanged += 1
        else:
            failed += 1
    return written, unchanged, failed


def tally_text(results, label="CanadianShopper"):
    """The sentence a finished run ends on."""
    written, unchanged, failed = tally(results)
    bits = ["%d price%s set" % (written, "" if written == 1 else "s")]
    if unchanged:
        bits.append("%d already right" % unchanged)
    if failed:
        bits.append("%d not changed" % failed)
    return "%s (%s was not touched)." % (", ".join(bits),
                                         "your website"
                                         if label == "CanadianShopper"
                                         else label)
