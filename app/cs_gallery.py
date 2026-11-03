#!/usr/bin/env python3
"""A listing's gallery: rows of their own, not a field on the product record.

For six releases this app looked for a gallery *inside* the product record - a
list of photos under ``images``, ``galleryImages``, ``media`` and the rest - and
every listing it met answered the same way: thirty-nine keys, one
``primaryImageUrl``, and no gallery. The conclusion drawn from that was wrong,
and the plugin's own 1.0.40 answer says why:

    Additional photos are separate ``productImage`` records, keyed by the
    listing record's own id. They are not embedded under a gallery key in
    ``GET /api/data/product/<listing-id>``.

So a listing can have a gallery and show none in its record, which is exactly
the listing this app kept telling people had nothing to prove. The rows live
here instead::

    GET    /api/data/productImage?where=<url-encoded filter>&limit=1000
    POST   /api/data/productImage   {"product": id, "imageUrl": url, "sortOrder": n}
    DELETE /api/data/productImage/<gallery-row-id>

with the filter ``{"field":"product","operator":"eq","value":"<listing-id>"}``
and an answer of ``{"data": [{id, product, imageUrl, sortOrder}, ...]}``.

Two rules this module keeps, both learned from the plugin's answer:

**A failed read is not an empty gallery.** The legacy tools turn a non-200 into
``[]``, which reads as "this listing has no photos" and is how a proof would
be written on top of a gallery nobody could see. Here an unreadable gallery is
``None`` and the caller is told.

**A proof is add, read, delete, read.** The photo is written as a new row, read
back, that row *alone* is deleted by the id the read-back gave, and the gallery
is read once more to show it gone. Nothing that was there before is touched:
the row created is the row removed, matched by its own id and by the photo.

Nothing here decides *which* photo to add - that is ``cs_proof.auto_photos``,
whose rule is that a photo of the card is certain, never merely well scored.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import cs_proof

#: The site, and the collection the gallery rows live in.
BASE = "https://canadianshopper.ca"
PATH = "/api/data/productImage"

#: The filter the site is asked with, as JSON, before it is url-encoded.
FILTER = '{"field":"product","operator":"eq","value":"%s"}'

#: How many rows one read asks for. A card listing has a front and a back; a
#: number this high is the site's own limit for a single read, not a promise
#: that a gallery this long exists.
LIMIT = 1000


def read_url(listing_id, base=BASE):
    """The address that answers with this listing's gallery rows."""
    identifier = str(listing_id or "").strip()
    if not identifier:
        return ""
    where = urllib.parse.quote(FILTER % identifier, safe="")
    return "%s%s?where=%s&limit=%d" % (str(base or "").rstrip("/"), PATH,
                                       where, LIMIT)


def row_url(row_id, base=BASE):
    """The address of one gallery row, which is how one row is removed."""
    identifier = str(row_id or "").strip()
    if not identifier:
        return ""
    return "%s%s/%s" % (str(base or "").rstrip("/"), PATH, identifier)


def rows(payload):
    """The gallery rows in one answer, in the order the site gave them.

    Only ``data`` is read. A row that is not a map, or that names no photo, is
    dropped rather than guessed at - it is not a photo the app could write,
    compare or remove.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return []
    if isinstance(payload, dict):
        entries = payload.get("data")
        if entries is None:
            entries = payload.get("items")
    else:
        entries = payload
    found = []
    for entry in entries if isinstance(entries, (list, tuple)) else []:
        if not isinstance(entry, dict):
            continue
        photo = str(entry.get("imageUrl") or entry.get("url") or "").strip()
        if not photo:
            continue
        found.append({"id": str(entry.get("id") or "").strip(),
                      "product": str(entry.get("product") or "").strip(),
                      "imageUrl": photo,
                      "sortOrder": entry.get("sortOrder")})
    return found


def photo_ids(rows_):
    """The photos a gallery holds, by the file each address names."""
    return {cs_proof.photo_id(row.get("imageUrl")) for row in rows_ or ()}


def holds(rows_, photo):
    """Whether a gallery already holds this photo, compared as the file."""
    return cs_proof.photo_id(photo) in photo_ids(rows_)


def next_sort(rows_):
    """Where a new row goes: after every row the site already has."""
    numbers = []
    for row in rows_ or ():
        try:
            numbers.append(int(row.get("sortOrder")))
        except (TypeError, ValueError):
            continue
    return max(numbers) + 1 if numbers else 1


def _send(method, url, cookie, payload=None, timeout=25):
    """One request; ``(status, body)``. ``status`` 0 when it did not answer."""
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method=method,
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
            text = exc.read(200000).decode("utf-8", "replace")
        except Exception:
            text = ""
        return exc.code, text
    except Exception as exc:
        return 0, str(exc)


def read(url, cookie="", fetch=None):
    """This listing's gallery rows, or ``None`` when it could not be read.

    ``None`` is the whole point: an unreadable gallery is not an empty one, and
    a caller that cannot tell the two apart will happily write a photo into a
    gallery it never saw.
    """
    fetch = fetch or (lambda address, session: _send("GET", address, session))
    status, body = fetch(url, cookie)
    if status != 200:
        return {"status": status, "rows": None,
                "why": ("The gallery could not be read (%s)."
                        % ("HTTP %s" % status if status else "no answer"))}
    return {"status": status, "rows": rows(body), "why": ""}


def _result(listing, photo, rows_before, now=None):
    return {"field": "images", "label": cs_proof.field_label("images"),
            "listing": str(listing or ""), "photo": str(photo or ""),
            "before": len(rows_before or ()), "after": len(rows_before or ()),
            "row": "", "verdict": "", "written": False, "restored": None,
            "steps": [], "why": "",
            "at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")}


def add(listing_id, cookie, photo, base=BASE, fetch=None, send=None,
        now=None):
    """Add one photo to a listing's gallery, and read the gallery back.

    ``added``      the POST was accepted and the read-back holds the photo;
    ``same``       the gallery already held it, so nothing was sent;
    ``ignored``    the POST was accepted and the read-back does not show it;
    ``unreadable`` the gallery could not be read, so nothing was written;
    ``refused``    the site answered the POST with anything but 200/201;
    ``unknown``    the POST was accepted and the read-back could not be read.

    ``row`` is the id of the row this call created, once a read-back has given
    it - which is what makes it safe to remove again.
    """
    fetch = fetch or (lambda address, session: _send("GET", address, session))
    send = send or (lambda method, address, session, payload:
                    _send(method, address, session, payload))
    photo = cs_proof.absolute_photo(photo, base)
    result = _result(listing_id, photo, [], now)
    if not photo or not photo.lower().startswith(("http://", "https://")):
        result.update(verdict="refused",
                      why=("There is no web address for the photo to add, so "
                           "nothing was sent. A gallery holds pictures the "
                           "site can show, not a file on this computer."))
        return result
    address = read_url(listing_id, base)
    if not address:
        result.update(verdict="unreadable",
                      why="There is no listing id to address, so nothing was "
                          "sent.")
        return result

    looked = read(address, cookie, fetch=fetch)
    result["steps"].append({"step": "GET the gallery", "status":
                            looked["status"]})
    if looked["rows"] is None:
        result.update(verdict="unreadable", why=(
            "%s Nothing was written: a photo added blind could be a second "
            "copy of one already in the gallery." % looked["why"]))
        return result
    before = looked["rows"]
    result["before"] = result["after"] = len(before)
    if holds(before, photo):
        result.update(verdict="same",
                      why="The listing's gallery already holds that photo.")
        return result

    payload = {"product": str(listing_id), "imageUrl": photo,
               "sortOrder": next_sort(before)}
    status, body = send("POST", "%s%s" % (str(base or "").rstrip("/"), PATH),
                        cookie, payload)
    result["steps"].append({"step": "POST the gallery row", "status": status,
                            "sent": payload})
    if status not in (200, 201):
        result.update(verdict="refused", why=(
            "The site refused the gallery row (%s), so nothing was added. %s"
            % ("HTTP %s" % status if status else "no answer",
               cs_proof._snippet(body))))
        return result
    result["written"] = True

    #  The POST body is not a contract: what proves the row is the gallery
    #  read afterwards, and only that read can say what the row's id is.
    looked = read(address, cookie, fetch=fetch)
    result["steps"].append({"step": "GET the gallery back",
                            "status": looked["status"]})
    if looked["rows"] is None:
        result.update(verdict="unknown", why=(
            "%s The site accepted the photo and the gallery could not be read "
            "back, so whether it is there is unknown. Look at the listing "
            "before adding it again." % looked["why"]))
        return result
    after = looked["rows"]
    result["after"] = len(after)
    if not holds(after, photo):
        result.update(verdict="ignored", why=(
            "The site accepted the gallery row and the read-back does not "
            "hold the photo: the gallery still has %d row%s. Nothing was "
            "added, and nothing was left behind."
            % (len(after), "" if len(after) == 1 else "s")))
        return result
    result["verdict"] = "added"
    result["row"] = _row_id(after, photo, before)
    result["why"] = ("The gallery holds the photo, as row %s at position %s."
                     % (result["row"] or "(no id given)",
                        next((row.get("sortOrder") for row in after
                              if cs_proof.photo_id(row.get("imageUrl"))
                              == cs_proof.photo_id(photo)), "?")))
    return result


def _row_id(after, photo, before):
    """The id of the row this call created, and only ever that one.

    A row that was already there cannot be the row this call created, so the
    ids present before are subtracted first: removing the wrong row would take
    a photo off a live listing that nobody asked to remove.
    """
    known = {row.get("id") for row in before or () if row.get("id")}
    wanted = cs_proof.photo_id(photo)
    for row in after or ():
        if cs_proof.photo_id(row.get("imageUrl")) == wanted and \
                row.get("id") and row["id"] not in known:
            return row["id"]
    return ""


def remove(listing_id, cookie, row_id, base=BASE, fetch=None, send=None,
           now=None):
    """Remove one gallery row by its own id, and read the gallery back."""
    fetch = fetch or (lambda address, session: _send("GET", address, session))
    send = send or (lambda method, address, session, payload:
                    _send(method, address, session, payload))
    result = _result(listing_id, "", [], now)
    result["row"] = str(row_id or "")
    address = row_url(row_id, base)
    if not address:
        result.update(verdict="refused",
                      why="There is no gallery row id to remove, so nothing "
                          "was sent.")
        return result
    status, body = send("DELETE", address, cookie, None)
    result["steps"].append({"step": "DELETE the gallery row",
                            "status": status})
    if status not in (200, 202, 204):
        result.update(verdict="refused", why=(
            "The site refused to remove the gallery row (%s). %s"
            % ("HTTP %s" % status if status else "no answer",
               cs_proof._snippet(body))))
        return result
    result["written"] = True
    looked = read(read_url(listing_id, base), cookie, fetch=fetch)
    result["steps"].append({"step": "GET the gallery back",
                            "status": looked["status"]})
    if looked["rows"] is None:
        result.update(verdict="unknown", why=(
            "%s The row was removed and the gallery could not be read back."
            % looked["why"]))
        return result
    result["after"] = len(looked["rows"])
    if any(row.get("id") == str(row_id) for row in looked["rows"]):
        result.update(verdict="unrestored", why=(
            "The site accepted the removal and the gallery still lists row "
            "%s. Check that listing on CanadianShopper before anything else."
            % row_id))
        return result
    result.update(verdict="removed", restored=True,
                  why="The row is gone from the gallery.")
    return result


def prove(listing_id, cookie, photo, base=BASE, fetch=None, send=None,
          now=None):
    """Prove a listing's gallery is writable: add, read, delete, read.

    The photo is written as a new row, the gallery is read to show it there
    and to learn the row's own id, that row is removed, and the gallery is
    read once more to show it gone. Nothing that was there before is touched,
    so the listing is left exactly as it was - which is what makes this a
    proof rather than an edit.

    ``written``  all four steps agreed; ``restored`` is True;
    ``unrestored`` the photo is there and the row could not be removed - the
                 listing has been changed and must be looked at by hand;
    ``added``    the row was created and the read-back gave no id for it, so
                 it was left in place rather than removed by guesswork;
    ``ignored``  the site took the row and the gallery does not show it;
    ``refused``  a request was answered with anything but a success;
    ``unreadable`` the gallery could not be read, so nothing was written;
    ``unknown``  a read-back failed after a write.
    """
    added = add(listing_id, cookie, photo, base=base, fetch=fetch, send=send,
                now=now)
    result = dict(added)
    result["steps"] = list(added.get("steps") or [])
    if added.get("verdict") != "added":
        return result
    if not result.get("row"):
        #  The photo is there but the read-back gave no id for its row, so it
        #  cannot be removed by id - and removing a row that was not this
        #  call's is not something this will ever do.
        result.update(verdict="added", restored=None, why=(
            "The gallery holds the photo and the read-back gave no id for its "
            "row, so it was left in place. Take it off on CanadianShopper if "
            "it should not stay."))
        return result
    removal = remove(listing_id, cookie, result["row"], base=base, fetch=fetch,
                     send=send, now=now)
    result["steps"] += list(removal.get("steps") or [])
    result["restore_status"] = (removal.get("steps") or [{}])[0].get("status")
    result["after"] = removal.get("after", result.get("after"))
    if removal.get("verdict") == "removed":
        result.update(verdict="written", restored=True,
                      why=("The gallery showed the photo as row %s, and that "
                           "row is gone again: the listing is as it was."
                           % result["row"]))
        return result
    result.update(verdict=("unrestored" if removal.get("verdict") == "refused"
                           else "unknown"),
                  restored=False,
                  why=("The photo is in the gallery as row %s and could not "
                       "be removed: %s Take it off on CanadianShopper."
                       % (result["row"], removal.get("why") or "")))
    return result


def sentence(result):
    """What happened, in one sentence a person reads once."""
    result = result or {}
    verdict = result.get("verdict")
    if verdict == "written":
        return ("Gallery photos is settled: the photo was added as a row of "
                "its own, the gallery showed it, and the row was removed "
                "again - %d row%s before and after."
                % (result.get("before") or 0,
                   "" if (result.get("before") or 0) == 1 else "s"))
    if verdict == "added":
        return ("The photo is in the listing's gallery now, as row %s. It was "
                "kept, because that is what was asked for."
                % (result.get("row") or "(no id given)"))
    if verdict == "same":
        return ("That photo was already in the listing's gallery, so nothing "
                "was sent.")
    if verdict == "ignored":
        return ("The site accepted the gallery row and the gallery does not "
                "show it, so the photo is not there.")
    if verdict == "refused":
        return "The photo was not added: %s" % (result.get("why") or
                                                "the site refused it.")
    if verdict == "unrestored":
        if result.get("photo"):
            return ("The photo is in the listing's gallery as row %s and "
                    "could not be removed: take it off on CanadianShopper."
                    % (result.get("row") or "(no id given)"))
        return ("The gallery still lists the row after the removal: check "
                "that listing on CanadianShopper.")
    if verdict == "unknown":
        return ("The site took the write, but the gallery could not be read "
                "back - check the listing before trying again.")
    if verdict == "unreadable":
        return "Nothing was written: %s" % (result.get("why") or "")
    return result.get("why") or "Nothing was written."


def advice(result):
    """What to do about it, when there is anything to do."""
    result = result or {}
    verdict = result.get("verdict")
    if verdict == "written":
        return ("The gallery is writable on this listing, so every gallery "
                "edit is now added, read back and (when it is a proof) taken "
                "off again by its own row id.")
    if verdict == "added":
        return ("The listing's gallery has one more photo. Nothing needs "
                "doing unless it should come off, which is one click on the "
                "listing itself - or run the proof, which removes its own "
                "row.")
    if verdict == "ignored":
        return ("Nothing changed on the site and there is nothing to fix "
                "here: the gallery route answered and did not keep the row. "
                "The proof file is the evidence for a plugin report.")
    if verdict == "unrestored" and result.get("photo"):
        return ("The listing's gallery has one photo more than it had, and "
                "this app could not take it off. Remove that row on the "
                "listing itself; nothing else should be added until it is "
                "gone.")
    if verdict in ("unknown", "unrestored"):
        return ("Open the listing on CanadianShopper and look before adding "
                "anything: the site took a write this app could not confirm.")
    return "Nothing was written." if verdict in ("refused", "unreadable") else ""
