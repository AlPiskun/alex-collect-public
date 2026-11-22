#!/usr/bin/env python3
"""Put one listing on sale, or put it away, at the listing's own record.

``marketplace.listing_update`` is the documented way to change a listing's
state, and it addresses ``/api/products/<product_id>/`` - so on a shop whose
read carries no product id (the vendor's detail records name none, 2,704 of
2,704 in the read this was written for) it refuses every listing before it
writes anything. That left "put this card back on sale" with no road at all
from the app, and the answer *change it in the vendor dashboard* for a job the
app already does for a listing's price and stock.

The record at ``/api/data/product/<listing-id>`` is the address this app
already writes proven fields to, keyed by the listing's own id - the id
``stock.set`` addresses the listing by, and the id whose detail record carries
the listing's ``status``. This module uses it for exactly one field:

* **one listing, one field, one request** - ``{"status": "active"}`` or
  ``{"status": "archived"}``, and nothing else is ever sent;
* **the record is read first**, and its own id must be the listing that was
  chosen, and its state must be the one the person was looking at when they
  confirmed - a listing that moved in the dashboard since is not acted on;
* **the write is read back**, because a 200 is not a state: the record is read
  again and the answer is *written*, *ignored* (the record still shows the old
  state - this address does not change it), *refused*, or *unknown*;
* **nothing is guessed and nothing is inferred** - the state word is the one
  the app writes everywhere else (``active`` / ``archived``), and whatever the
  record answers afterwards is reported in the record's own words.

This is not a proof and it is not the record-edit form: a proof is a
controlled, reversible trial on a live listing (see ``cs_proof.UNPROVABLE``,
which is why ``status`` is not one of its fields), while this is a change a
person asked for by name, confirmed by name, and then checked. A state change
that is not kept is reported as not kept - it is never assumed.
"""
from __future__ import annotations

import cs_edit
import cs_proof
import cs_record
import stock_compare

#: The two states a listing can be moved to, and the word each is written as.
#: ``marketplace.listing_update`` uses the same two words, so a listing written
#: here and a listing written through the plugin read the same on the site.
WORDS = {"active": "active", "archived": "archived"}

#: What a person reads for each state.
LABELS = {"active": "on sale", "archived": "archived"}


def word_for(state):
    """The word to write for a state the app asks for, or ``""``."""
    raw = str(state or "").strip().lower()
    if raw in WORDS:
        return WORDS[raw]
    if raw in ("on sale", "onsale", "archive", "put away"):
        return "active" if raw in ("on sale", "onsale") else "archived"
    return ""


def label_for(state):
    """The word a person reads for a state: *on sale*, *archived*."""
    return LABELS.get(word_for(state) or str(state or "").strip().lower(),
                      str(state or "").strip() or "that state")


def state_of(value):
    """A record's own state, folded into one of the app's words.

    The vendor spells its states in its own case and its own vocabulary, and
    the app already folds those words in one place (``stock_compare``) for
    every panel that shows a state. An archived listing is archived before it
    is anything else: it is the one state the app has a button for that is not
    merely "not published".
    """
    raw = " ".join(str(value or "").split())
    if not raw:
        return ""
    if stock_compare.is_archived({"status": raw}):
        return "archived"
    return stock_compare.status_of({"status": raw})


def same_state(value, wanted):
    """Whether a record's state is the state that was asked for."""
    found = state_of(value)
    return bool(found) and found == state_of(wanted)


def record_state(record):
    """``(found, text)`` for the state a detail record carries."""
    return cs_proof.record_value(record, "status")


#: The fields a plan can change that the record road does not write. A plan
#: that names any of them is a job for the plugin, not for this module.
OTHER_FIELDS = ("price", "inventory", "description", "primaryImageUrl")


def changes_only_state(entry):
    """Whether a plan asks for a state change and nothing else.

    A plan carries the ids and the old title it would be addressed by, so
    "only the state" is not "one key": it is the state being asked for, the
    title being the one that is already on the site, and no other field in it.
    """
    entry = entry or {}
    if not word_for(entry.get("status")):
        return False
    if any(key in entry for key in OTHER_FIELDS):
        return False
    return str(entry.get("title") or "") == str(entry.get("card") or "")


def describe(to, name="That listing"):
    """The line a confirmation shows for one state change."""
    return "%s: %s" % (name, label_for(to))


def change(url, cookie, to, expect=None, listing_id="", listing=None,
           fetch=None, send=None):
    """Move one listing to another state at its own record, and read it back.

    ``to`` is ``active`` or ``archived``; ``expect`` is the state the row said
    the listing was in, refused rather than ignored when the record has moved
    since. Returns one result: what was asked for, what the record held, what
    it holds now, and which of those the site actually did.
    """
    fetch = fetch or cs_proof.read_record
    send = send or cs_record.send_fields
    listing = listing or {}
    wanted = word_for(to)
    listing_id = str(listing_id or "").strip()
    result = {"url": url, "id": listing_id,
              "card": str(listing.get("name") or listing.get("title") or ""),
              "to": wanted, "was": "", "now": "", "verdict": "",
              "why": "", "written": False, "status": 0, "steps": [],
              "sent": {}, "raw": {"was": "", "now": ""}}
    if not wanted:
        result.update(verdict="refused",
                      why="No state was asked for, so nothing was sent.")
        return result
    if not url or not cs_edit.is_id(listing_id):
        result.update(verdict="unreadable",
                      why=("There is no record id to address, so the state "
                           "was not sent."))
        return result

    status, body = fetch(url, cookie)
    result["steps"].append({"step": "GET the record", "status": status})
    record = cs_proof._record(body) if status == 200 else None
    if record is None:
        result.update(verdict="unreadable",
                      why=("The record could not be read (%s), so nothing "
                           "was written: the state that is there now cannot "
                           "be checked."
                           % ("HTTP %s" % status if status else "no answer")))
        return result

    found_id = cs_record._record_id(record)
    if not found_id or found_id.strip() != listing_id:
        result["steps"].append({"step": "the record names %s"
                                % (found_id or "no id"), "status": 200})
        result.update(
            verdict="refused",
            why=("The record at that address says it is listing %s, not %s. "
                 "Nothing was written: changing the wrong listing's state is "
                 "the one mistake this must never make."
                 % (found_id or "(no id)", listing_id)))
        return result

    found, raw_was = record_state(record)
    result["raw"]["was"] = "" if raw_was is None else str(raw_was)
    if not found or not str(raw_was or "").strip():
        result.update(verdict="refused",
                      why=("The record does not carry its own state, so a "
                           "change could not be read back. Nothing was "
                           "sent."))
        return result
    result["was"] = state_of(raw_was)
    if same_state(raw_was, wanted):
        result.update(verdict="same", now=result["was"],
                      why=("The record already says %s, so nothing was sent."
                           % label_for(result["was"])))
        return result
    if expect:
        looked = state_of(expect)
        if looked and not same_state(raw_was, looked):
            result.update(verdict="changed", now=result["was"],
                          why=("The record shows it as %s now, not the %s "
                               "that was confirmed. Nothing was written - the "
                               "listing moved since the list was read."
                               % (label_for(result["was"]),
                                  label_for(looked))))
            return result

    payload = {"status": wanted}
    result["sent"] = dict(payload)
    written_status, written_body = send(url, cookie, payload)
    result["status"] = written_status
    result["steps"].append({"step": "PATCH status", "status": written_status,
                            "sent": dict(payload),
                            "body": "" if 200 <= written_status < 300
                            else cs_record._snippet(written_body)})
    if not 200 <= written_status < 300:
        result.update(
            verdict="refused",
            why=("The site refused the change (%s). The listing is still %s."
                 % ("HTTP %s" % written_status if written_status
                    else written_body or "no answer",
                    label_for(result["was"]))))
        return result

    after_status, after_body = fetch(url, cookie)
    result["steps"].append({"step": "GET the record", "status": after_status})
    after_record = cs_proof._record(after_body) if after_status == 200 else None
    if after_record is None:
        result.update(verdict="unknown",
                      why=("The site accepted the change but the record could "
                           "not be read back (%s), so this app cannot say "
                           "what state that listing holds now. Check it on "
                           "CanadianShopper."
                           % ("HTTP %s" % after_status if after_status
                              else "no answer")))
        return result

    _found, raw_now = record_state(after_record)
    result["raw"]["now"] = "" if raw_now is None else str(raw_now)
    result["now"] = state_of(raw_now)
    if not same_state(raw_now, wanted) and same_state(raw_now, raw_was):
        result.update(
            verdict="ignored",
            why=("The site answered HTTP %s but the record still says it is "
                 "%s: the request was accepted and the state was not kept, so "
                 "this address does not change it. The listing is unchanged - "
                 "its state has to be changed in the vendor dashboard."
                 % (written_status, label_for(result["was"]))))
        return result
    if same_state(raw_now, wanted):
        result.update(verdict="written", written=True,
                      why=("It is %s now, read back after the write."
                           % label_for(wanted)))
        return result
    result.update(verdict="other",
                  why=("The record now says it is %s, which is neither the %s "
                       "it held nor the %s that was sent. Check that listing "
                       "on CanadianShopper before doing anything else."
                       % (label_for(result["now"]) if result["now"]
                          else "something this app does not know",
                          label_for(result["was"]), label_for(wanted))))
    return result


def sentence(result, name=""):
    """The one line a person reads for one state change."""
    result = result or {}
    card = str(name or result.get("card") or "That listing").strip()
    asked = label_for(result.get("to"))
    verdict = str(result.get("verdict") or "")
    if verdict == "written":
        return ("%s: CanadianShopper shows it as %s now, read back after the "
                "write (your website was not touched)." % (card, asked))
    if verdict == "same":
        return ("%s: it is already %s on CanadianShopper, so nothing was sent."
                % (card, asked))
    if verdict == "ignored":
        return ("%s: the site accepted the change but the record still shows "
                "%s - this address does not change a listing's state. Nothing "
                "was changed; it has to be done in the vendor dashboard."
                % (card, label_for(result.get("was"))))
    if verdict == "other":
        return ("%s: %s" % (card, result.get("why") or "The state could not "
                                                   "be confirmed."))
    if verdict in ("refused", "unreadable", "changed", "unknown"):
        return "%s: %s" % (card, result.get("why")
                           or "The state was not changed.")
    return "%s: the state was not changed." % card


def changed(result):
    """Whether a result is a state the person can now see on the row."""
    return str((result or {}).get("verdict") or "") == "written"
