#!/usr/bin/env python3
"""Write a price to a CanadianShopper listing's own record - and only a proven one.

A proof (``cs_proof.py``) settles one field at one address: it writes a marked
value to ``/api/data/product/<listing-id>``, reads the record back, puts the old
value back and reads it again. When that says *written and restored*, the field
is proven at that address - which is the only evidence this module accepts.

So the rules here are short and hard:

* **the address is the record's own id**, the one the reader reports for the
  listing and the one a proof wrote to. It is never called a product id, it is
  never taken from ``/api/products/<product_id>/``, and a row that does not say
  its own id is not addressed at all;
* **only a proven field is written**. :data:`PROVEN_FIELDS` is the list, and a
  field joins it when a proof saved in ``cs-field-proofs.json`` says the site
  kept the value and gave the old one back. Without that file the write path is
  closed - deliberately: an app that cannot show why it is allowed to write is
  an app that will write something nobody proved;
* **the record is read first**, and its own id must be the id that was asked
  for. A record at that address that names a different id is not the listing
  that was chosen, and nothing is sent;
* **the price the person confirmed is the price that must still be there**. If
  the record shows a different price now, nothing is written and the panel says
  what it found - a confirmation about 8.50 must never turn into a write of
  something else;
* **the write is read back**, because a 200 is not a price. The answer says
  what the record shows afterwards: the new price (written), the old one
  (ignored), or nothing readable (unknown - and the console says so rather
  than claiming success);
* **one field, one request**: the body is ``{"priceCad": "12.50"}`` and
  nothing else, so no other field can be changed by a price write.

Nothing here touches the website, the plugin, or ``/api/products/...``.
"""
from __future__ import annotations

import urllib.error
import urllib.request

import cs_edit
import cs_listing
import cs_proof

#: The fields this module will write, in a person's words. A field is added
#: here only after a saved proof has settled it; the proof file is re-read on
#: every write, so deleting it closes the path again.
PROVEN_FIELDS = ("priceCad",)

FIELD_LABELS = {"priceCad": "Price"}

#: A price of zero is not written from here: on a marketplace a zero is almost
#: always a mistake, and it makes the card free while the shop keeps selling
#: it. If a card is really being given away, that is set in the dashboard.
REFUSE_ZERO = True


def field_label(field):
    return FIELD_LABELS.get(str(field or ""), str(field or ""))


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


def refuse_reason(field, price):
    """Why a price cannot be written at all, or ``""`` when it can."""
    field = str(field or "")
    if field not in PROVEN_FIELDS:
        return ("%s is not a field this app writes: only a field a proof has "
                "settled is ever sent." % (field_label(field) or field))
    if "-" in str(price if price is not None else ""):
        return ("A price cannot be negative: %r is not a price this app will "
                "write." % (price,))
    text = money(price)
    if not text:
        return ("%r is not a price, so there is nothing to write." % (price,))
    number = float(text)
    if REFUSE_ZERO and number == 0:
        return ("A price of zero is not written from here - on a marketplace "
                "that is almost always a mistake, and it makes the card free. "
                "Set a zero price in the vendor dashboard if it is really "
                "meant.")
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


def plan(item, price, proofs=None):
    """One listing's price change: what would be sent, or why nothing would be.

    The plan carries the row's own price as the *expected* one. It is not
    trusted as the truth - the record is read again before anything is sent -
    but it is what the person was looking at when they agreed, and a record
    that no longer matches it is not written.
    """
    item = item or {}
    field = "priceCad"
    listing_id = cs_edit.listing_id(item)
    #  A zero is not an id (see cs_edit.is_id): addressing /api/data/product/0
    #  would be a write at a record that cannot exist.
    entry = {"field": field, "label": field_label(field),
             "card": str(item.get("name") or item.get("title") or "").strip(),
             "id": listing_id if cs_edit.is_id(listing_id) else ""}
    if not cs_proof.settled(field, proofs):
        return {"why": ("%s has not been proven writable on this site, so "
                        "nothing is sent. Run \"Prove a field can be written\" "
                        "for %s first: a write path with no proof behind it is "
                        "exactly what must not exist."
                        % (field_label(field), field_label(field).lower())),
                "card": entry["card"], "id": entry["id"], "field": field}
    if not entry["id"]:
        return {"why": ("The list carries no record id for %s, so there is no "
                        "record to address. Nothing was sent."
                        % (entry["card"] or "that listing")),
                "card": entry["card"], "id": "", "field": field}
    why = refuse_reason(field, price)
    if why:
        return {"why": why, "card": entry["card"], "id": entry["id"],
                "field": field}
    entry["price"] = money(price)
    old = cs_edit.price_number(item)
    entry["old"] = "" if old is None else "%.2f" % old
    return entry


def describe(entry):
    """``old -> new`` in the words the confirmation uses."""
    entry = entry or {}
    old = entry.get("old") or "no price on the list"
    return "%s:  %s  ->  %s" % (entry.get("card") or "That listing",
                                old, entry.get("price") or "?")


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


def send_price(url, cookie, price, opener=None, timeout=25):
    """``PATCH`` one record with one price; ``(status, body)``, never raises."""
    if opener is not None:
        return opener(url, cookie, price)
    import json
    request = urllib.request.Request(
        url, data=json.dumps({"priceCad": price}).encode("utf-8"),
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


def write(url, cookie, price, expect_id="", expect_old=None, listing=None,
          field="priceCad", proofs=None, fetch=None, send=None):
    """Read the record, write one price, read it back. Never raises.

    ``expect_old`` is what the person was shown. The record is read first and a
    price that no longer matches it stops the write there and then: a
    confirmation is a promise about a number, not a licence to replace whatever
    is there now.
    """
    fetch = fetch or cs_proof.read_record
    send = send or send_price
    listing = listing or {}
    result = {"field": field, "label": field_label(field),
              "url": url, "id": str(expect_id or ""),
              "card": str(listing.get("name") or listing.get("title") or ""),
              "sent": "", "old": None, "after": None, "status": 0,
              "verdict": "", "written": False, "steps": [], "why": ""}
    if field not in PROVEN_FIELDS:
        result.update(verdict="unproven",
                      why="%s is not a field this app writes." % field_label(field))
        return result
    if not cs_proof.settled(field, proofs):
        result.update(
            verdict="unproven",
            why=("%s has not been proven writable on this site, so nothing was "
                 "sent. Run the field proof first." % field_label(field)))
        return result
    why = refuse_reason(field, price)
    if why:
        result.update(verdict="refused", why=why)
        return result
    price = money(price)
    result["sent"] = price
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
                           "written: the price that is there now cannot be "
                           "checked or compared."
                           % ("HTTP %s" % status if status else "no answer")))
        return result

    found_id = _record_id(record)
    if not found_id:
        result["steps"].append({"step": "the record names no id", "status": 200})
        result.update(verdict="refused",
                      why=("The record at that address does not name its own "
                           "id, so this app cannot confirm it is the listing "
                           "that was chosen. Nothing was written."))
        return result
    if str(found_id).strip() != str(expect_id).strip():
        result["steps"].append({"step": "the record names %s" % found_id,
                                "status": 200})
        result.update(verdict="refused",
                      why=("The record at that address says it is listing %s, "
                           "not %s. Nothing was written: writing the wrong "
                           "listing's price is the one mistake this path must "
                           "never make." % (found_id, expect_id)))
        return result

    found, old = cs_proof.record_value(record, field)
    if not found or old is None or str(old).strip() == "":
        result.update(verdict="refused",
                      why=("The record carries no %s to compare with, so this "
                           "app cannot tell a write from a coincidence. "
                           "Nothing was written." % field_label(field).lower()))
        return result
    result["old"] = old
    if cs_proof.same(field, old, price):
        result.update(verdict="same",
                      why=("The listing already shows %s, so there is nothing "
                           "to write." % money(old)))
        return result
    if expect_old not in (None, "") and not cs_proof.same(field, old,
                                                          expect_old):
        result.update(
            verdict="changed",
            why=("The listing's price is %s now, not the %s that was confirmed. "
                 "Nothing was written - look at the new price and confirm "
                 "again if it is still the one to replace."
                 % (money(old), money(expect_old))))
        return result

    written_status, written_body = send(url, cookie, price)
    result["status"] = written_status
    result["steps"].append({"step": "PATCH %s" % field,
                            "status": written_status, "sent": price,
                            "body": "" if 200 <= written_status < 300
                            else _snippet(written_body)})
    if not 200 <= written_status < 300:
        result.update(verdict="refused",
                      why=("The site refused the write (%s). The listing still "
                           "shows %s."
                           % ("HTTP %s" % written_status if written_status
                              else written_body or "no answer", money(old))))
        return result

    after_status, after_body = fetch(url, cookie)
    result["steps"].append({"step": "GET the record", "status": after_status})
    after_record = cs_proof._record(after_body) if after_status == 200 else None
    if after_record is None:
        result.update(verdict="unknown",
                      why=("The site accepted the write but the record could "
                           "not be read back (%s), so this app cannot say the "
                           "price took. Check that listing on CanadianShopper."
                           % ("HTTP %s" % after_status if after_status
                              else "no answer")))
        return result
    result["after"] = cs_proof.record_value(after_record, field)[1]
    if cs_proof.same(field, result["after"], price):
        result.update(verdict="written", written=True,
                      why=("The record now shows %s, read back after the "
                           "write." % money(result["after"])))
    elif cs_proof.same(field, result["after"], old):
        result.update(verdict="ignored",
                      why=("The site answered %s but the record still shows %s: "
                           "the write was accepted and the price was not "
                           "kept. The listing is unchanged."
                           % ("HTTP %s" % written_status, money(old))))
    else:
        result.update(verdict="written", written=True,
                      why=("The record shows %s rather than the %s that was "
                           "sent - the price was kept, and the site stored it "
                           "its own way." % (money(result["after"]), price)))
    return result


def sentence(result):
    """One line for the console, in the words the outcome deserves."""
    result = result or {}
    label = result.get("label") or field_label(result.get("field"))
    card = result.get("card") or "that listing"
    verdict = result.get("verdict")
    if verdict == "written":
        return ("%s now shows %s on CanadianShopper (your website was not "
                "touched)." % (card, money(result.get("after"))))
    if verdict == "same":
        return "%s already shows %s; nothing was sent." % (
            card, money(result.get("old")))
    if verdict == "changed":
        return ("Not written for %s: %s" % (card, result.get("why")))
    if verdict == "ignored":
        return ("Not changed for %s: %s" % (card, result.get("why")))
    if verdict == "unproven":
        return ("No price was written: %s is not proven writable yet."
                % label)
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
