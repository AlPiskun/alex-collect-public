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
import urllib.request
from datetime import datetime
from pathlib import Path

import cs_edit

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

FIELD_LABELS = {field: label for field, label in FIELDS}

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
    return [label for _field, label in FIELDS]


def field_for(label):
    """The field a chosen label stands for, or ``""``."""
    wanted = str(label or "").strip().casefold()
    for field, text in FIELDS:
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
    return str(left if left is not None else "").strip() == \
        str(right if right is not None else "").strip()


def value_text(field, value):
    """A value as the report says it: quoted, or named as empty."""
    if value is None:
        return "(not there)"
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
    found, old = record_value(record, field)
    label = field_label(field)
    if not found:
        return {"field": field, "label": label,
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
            "restore": old, "note": note}


#: What the image staging step writes its rows into. The staging command takes
#: the batch's import CSV and rewrites each row's ``image_url`` to the hosted
#: square photo it uploaded, so a row still pointing at the website is a row
#: that has not been staged.
STAGED_PATTERN = "canadianshopper_import_*.csv"
STAGED_PHOTO = "/api/file/"


def _fold(text):
    return " ".join(str(text or "").split()).casefold()


def staged_photo(folder, title=""):
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
    folder = Path(folder or ".")
    #  The staging step of plugin 1.0.40 writes its rewritten CSVs into
    #  ``cs-ready`` beside the batch, while the batch itself sits one level
    #  above it - and the older command wrote them beside the batch. Both are
    #  searched, newest first across the two, because the newest staged row is
    #  the one that matches the photo the site is holding today.
    found = []
    for where in (folder, folder / "cs-ready"):
        try:
            found.extend(where.glob(STAGED_PATTERN))
        except OSError:
            continue
    try:
        files = sorted(found, key=lambda path: path.stat().st_mtime,
                       reverse=True)
    except OSError:
        return ""
    for path in files[:8]:
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


def primary_photo(item=None, record=None):
    """The photo the listing shows now, from the record when there is one."""
    if record:
        found, value = record_value(record, "primaryImageUrl")
        if found and str(value or "").strip():
            return absolute_photo(value)
    for text in _photo_values(item):
        return absolute_photo(text)
    return ""


def photo_candidates(item=None, record=None, staged=""):
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
        result["verdict"] = "unreadable"
        result["why"] = planned["why"]
        return result
    result.update({key: planned[key] for key in
                   ("old", "trial", "restore", "note", "label")})

    written_status, written_body = send(url, cookie, {field: planned["trial"]})
    result["status"] = written_status
    result["steps"].append({"step": "PATCH %s" % field, "status": written_status,
                            "sent": planned["trial"],
                            "body": "" if 200 <= written_status < 300
                            else _snippet(written_body)})
    if not 200 <= written_status < 300:
        #  A refused write is an answer about the field, and the read-back is
        #  what keeps the report honest if a refusal came with a change.
        after_status, after_body = fetch(url, cookie)
        after_record = _record(after_body) if after_status == 200 else None
        result["after"] = (record_value(after_record, field)[1]
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
        result["after"] = record_value(after_record, field)[1]

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
                                        {field: planned["restore"]})
    result["restore_status"] = restore_status
    result["steps"].append({"step": "PATCH %s (put back)" % field,
                            "status": restore_status,
                            "sent": planned["restore"],
                            "body": "" if 200 <= restore_status < 300
                            else _snippet(restore_body)})
    final_status, final_body = fetch(url, cookie)
    final_record = _record(final_body) if final_status == 200 else None
    result["steps"].append({"step": "GET the record", "status": final_status})
    if final_record is not None:
        result["final"] = record_value(final_record, field)[1]
        result["restored"] = same(field, result["final"], planned["old"])
    else:
        result["restored"] = None
    if result["verdict"] == "ignored" and result["restored"]:
        result["why"] += (" The old value was sent once more and the record "
                          "still shows it, so nothing is left behind.")
    return result


def sentence(result):
    """The one line the console says when the proof is done."""
    result = result or {}
    label = result.get("label") or field_label(result.get("field"))
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
              "In short:   %s" % sentence(result),
              "", "Steps:"]
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
