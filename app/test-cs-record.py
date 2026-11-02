#!/usr/bin/env python3
"""Checks for cs_record - writing a proven price at a listing's own record.

No site and no network: a fake record answers the reads and a fake site keeps,
ignores or refuses the write. Every check is about one of the two things that
matter here - that only a proven field is ever sent, and that what is sent is
the listing that was chosen, at the address a proof settled.

The failures are the interesting half. A write path that says "written" when
the record still shows the old price is worse than no write path at all.
"""
import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP), str(APP / "pipeline")]

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s %s" % (name, extra))


import cs_record                                       # noqa: E402

LISTING_ID = "a2304e72dbca4e678e7111d011ade22d"
URL = "https://canadianshopper.ca/api/data/product/" + LISTING_ID

#: The record as the shop answered it, at the price the proof found.
RECORD = {"id": LISTING_ID,
          "title": "#006/196 Wurmple SWSH11: Lost Origin - Pokémon TCG",
          "priceCad": 1,
          "inventory": 1,
          "status": "active"}

#: What the proof that was actually run on this shop saved.
PROOFS = {"priceCad": {"at": "2026-11-02 15:34:38", "verdict": "written",
                       "restored": True, "proven": True,
                       "listing": LISTING_ID,
                       "title": "#006/196 Wurmple SWSH11: Lost Origin"}}


class Site:
    """A record, and the three ways a site answers a price write."""

    def __init__(self, record=None, keep=True, refuse=(), normalise=None,
                 fail_reads=(), id_in_record=True, unkeeps=()):
        self.record = dict(RECORD if record is None else record)
        if not id_in_record:
            self.record.pop("id", None)
        self.keep = keep
        self.refuse = set(refuse)
        self.normalise = normalise
        self.fail_reads = set(fail_reads)      # which read number fails
        self.unkeeps = set(unkeeps)            # accepted, not kept
        self.reads = 0
        self.sent = []

    def fetch(self, url, cookie=""):
        self.reads += 1
        if self.reads in self.fail_reads:
            return 500, "<html>read failed</html>"
        import json
        return 200, json.dumps(self.record)

    def send(self, url, cookie, payload):
        self.sent.append(dict(payload))
        if "price" in self.refuse:
            return 403, "<html>denied</html>"
        if self.keep:
            for field, value in payload.items():
                if field in self.unkeeps:
                    continue
                self.record[field] = (self.normalise
                                      if (self.normalise is not None and
                                          field == "priceCad") else value)
        return 200, '{"ok": true}'


def test_only_a_proven_field_is_written():
    print()
    print("== 1. nothing is written without a proof ==")
    site = Site()
    result = cs_record.write(URL, "", "1.01", expect_id=LISTING_ID,
                             proofs={}, fetch=site.fetch, send=site.send)
    check("with no proof the write is refused before any request",
          result["verdict"] == "unproven" and site.sent == [] and
          site.reads == 0, str(result["verdict"]))
    check("and the answer says to run the proof, not to retry",
          "Prove a field can be written" in result["why"], result["why"])

    result = cs_record.write(URL, "", "1.01", expect_id=LISTING_ID,
                             proofs=PROOFS, field="inventory",
                             fetch=site.fetch, send=site.send)
    check("a field that is not in the proven list is never sent",
          result["verdict"] == "unproven" and site.sent == [],
          str(result["verdict"]))
    check("the proof of another field does not open this one",
          not cs_record.plan({"id": LISTING_ID}, "1.01",
                             {"title": {"proven": True}}).get("fields"), "")

    stale = {"priceCad": dict(PROOFS["priceCad"], proven=False)}
    result = cs_record.write(URL, "", "1.01", expect_id=LISTING_ID,
                             proofs=stale, fetch=site.fetch, send=site.send)
    check("a proof that stopped being true closes the path again",
          result["verdict"] == "unproven" and site.sent == [], "")


def test_the_price_that_is_sent():
    print()
    print("== 2. the price, as the site is told it ==")
    check("a whole number is written as money", cs_record.money(1) == "1.00", "")
    check("a currency string is read, not passed through",
          cs_record.money("CA$8.50") == "8.50", "")
    check("a price with a comma is one price",
          cs_record.money("1,250.00") == "1250.00", "")
    check("words are not a price", cs_record.money("ask") == "", "")
    check("zero is refused with the reason a shop can act on",
          "almost always a mistake" in cs_record.refuse_reason("priceCad", 0),
          "")
    check("a negative price is refused", "negative" in
          cs_record.refuse_reason("priceCad", "-1"), "")
    check("a normal price is not refused",
          cs_record.refuse_reason("priceCad", "8.50") == "", "")
    check("the evidence is described with the day it was proven",
          "2026-11-02 15:34:38" in cs_record.note_for("priceCad", PROOFS), "")

    print()
    print("== 3. the plan for one listing ==")
    row = {"id": LISTING_ID, "name": "Wurmple", "price": "1"}
    entry = cs_record.plan(row, "2.50", PROOFS)
    check("the plan carries the record's id, the old price and the new one",
          (entry["id"], entry["old"], entry["price"]) ==
          (LISTING_ID, "1.00", "2.50"), str(entry))
    check("and reads as a change in one line",
          cs_record.describe(entry) == "Wurmple:  1.00  ->  2.50",
          cs_record.describe(entry))
    missing_id = cs_record.plan({"name": "Wurmple", "price": "1"}, "2", PROOFS)
    check("a row with no record id cannot be planned at all",
          "no record id" in missing_id["why"], str(missing_id))
    zero_id = cs_record.plan({"id": "0", "name": "Wurmple"}, "2", PROOFS)
    check("a zero is not an id, so it is not addressed",
          "no record id" in zero_id["why"], str(zero_id))


def test_a_price_that_is_written():
    print()
    print("== 4. a price the site keeps ==")
    site = Site()
    result = cs_record.write(URL, "secret-session", "1.01",
                             expect_id=LISTING_ID, expect_old="1.00",
                             listing={"id": LISTING_ID, "name": "Wurmple"},
                             proofs=PROOFS, fetch=site.fetch, send=site.send)
    check("the verdict is written", result["verdict"] == "written",
          result.get("why"))
    check("the site kept the new price", site.record["priceCad"] == "1.01",
          str(site.record["priceCad"]))
    check("exactly one write was made, carrying one price",
          site.sent == [{"priceCad": "1.01"}], str(site.sent))
    check("the record was read before the write and again after it",
          [step["step"] for step in result["steps"]] ==
          ["GET the record", "PATCH priceCad", "GET the record"],
          str(result["steps"]))
    check("the answer names the price the record shows",
          "1.01" in result["why"] and "read back" in result["why"],
          result["why"])
    check("the console line says the website was not touched",
          "your website was not touched" in cs_record.sentence(result),
          cs_record.sentence(result))

    print()
    print("== 5. prices that must not be written ==")
    site = Site()
    result = cs_record.write(URL, "", "1.00", expect_id=LISTING_ID,
                             proofs=PROOFS, fetch=site.fetch, send=site.send)
    check("the price that is already there is not sent again",
          result["verdict"] == "same" and site.sent == [], str(result["verdict"]))
    check("and the answer says there was nothing to write",
          "already holds that value" in result["why"], result["why"])

    site = Site()
    result = cs_record.write(URL, "", "2.00", expect_id=LISTING_ID,
                             expect_old="1.50", proofs=PROOFS,
                             fetch=site.fetch, send=site.send)
    check("a price that changed since the confirmation is not overwritten",
          result["verdict"] == "changed" and site.sent == [],
          str(result["verdict"]))
    check("and the answer says what the record shows instead",
          "1.00" in result["why"] and "Nothing was written" in result["why"],
          result["why"])

    site = Site(record=dict(RECORD, id="some-other-listing"))
    result = cs_record.write(URL, "", "2.00", expect_id=LISTING_ID,
                             expect_old="1.00", proofs=PROOFS,
                             fetch=site.fetch, send=site.send)
    check("a record that says it is a different listing is never written",
          result["verdict"] == "refused" and site.sent == [],
          str(result["verdict"]))
    check("and the answer names both ids",
          "some-other-listing" in result["why"] and
          LISTING_ID in result["why"], result["why"])

    site = Site(id_in_record=False)
    result = cs_record.write(URL, "", "2.00", expect_id=LISTING_ID,
                             proofs=PROOFS, fetch=site.fetch, send=site.send)
    check("a record that does not name its own id is not written",
          result["verdict"] == "refused" and site.sent == [],
          str(result["verdict"]))

    site = Site(record={"id": LISTING_ID, "title": "no price here"})
    result = cs_record.write(URL, "", "2.00", expect_id=LISTING_ID,
                             proofs=PROOFS, fetch=site.fetch, send=site.send)
    check("a record with no price to compare is not written either",
          result["verdict"] == "refused" and site.sent == [],
          str(result["verdict"]))


def test_what_the_site_answers():
    print()
    print("== 6. accepted, ignored, refused, unreadable ==")
    site = Site(refuse={"price"})
    result = cs_record.write(URL, "", "2.00", expect_id=LISTING_ID,
                             expect_old="1.00", proofs=PROOFS,
                             fetch=site.fetch, send=site.send)
    check("a refusal is a refusal, with its status",
          result["verdict"] == "refused" and result["status"] == 403,
          str(result["verdict"]))
    check("the record is untouched and still shows the old price",
          site.record["priceCad"] == 1, str(site.record["priceCad"]))
    check("the site's own answer is kept", "denied" in result["steps"][1]["body"],
          str(result["steps"][1]))

    site = Site(keep=False)
    result = cs_record.write(URL, "", "2.00", expect_id=LISTING_ID,
                             expect_old="1.00", proofs=PROOFS,
                             fetch=site.fetch, send=site.send)
    check("a 200 that changed nothing is called ignored, not written",
          result["verdict"] == "ignored" and not result["written"],
          str(result["verdict"]))
    check("and it says the listing is unchanged",
          "unchanged" in result["why"], result["why"])

    site = Site(fail_reads={1})
    result = cs_record.write(URL, "", "2.00", expect_id=LISTING_ID,
                             proofs=PROOFS, fetch=site.fetch, send=site.send)
    check("a record that cannot be read is no write at all",
          result["verdict"] == "unreadable" and site.sent == [],
          str(result["verdict"]))

    site = Site(fail_reads={2})
    result = cs_record.write(URL, "", "2.00", expect_id=LISTING_ID,
                             expect_old="1.00", proofs=PROOFS,
                             fetch=site.fetch, send=site.send)
    check("a write that cannot be read back is unknown, not success",
          result["verdict"] == "unknown" and not result["written"],
          str(result["verdict"]))
    check("and the console tells the person to check the listing",
          "Check that listing" in cs_record.sentence(result),
          cs_record.sentence(result))

    site = Site(normalise=1.5)
    result = cs_record.write(URL, "", "1.50", expect_id=LISTING_ID,
                             expect_old="1.00", proofs=PROOFS,
                             fetch=site.fetch, send=site.send)
    check("a value the site stores its own way is still a write",
          result["verdict"] == "written" and result["written"], "")


def test_the_address_is_the_records_own():
    print()
    print("== 7. the address, and nothing else ==")
    check("the address is built from the record's id",
          cs_record.url_for(LISTING_ID) == URL, cs_record.url_for(LISTING_ID))
    check("and never from a product id",
          "product_id" not in cs_record.url_for(LISTING_ID), "")
    result = cs_record.write("", "", "2.00", expect_id="", proofs=PROOFS)
    check("no id is no address, and nothing is sent",
          result["verdict"] == "unreadable" and not result["written"], "")
    numeric = Site(record={"id": 101, "priceCad": "5.00"})
    result = cs_record.write("https://cs.example/api/data/product/101", "",
                             "6.00", expect_id=101, expect_old="5.00",
                             proofs=PROOFS, fetch=numeric.fetch,
                             send=numeric.send)
    check("a number and the same number as text are one id",
          result["verdict"] == "written", str(result["verdict"]))
    result = cs_record.write("https://cs.example/api/data/product/101", "",
                             "6.00", expect_id="101 ", expect_old="5.00",
                             proofs=PROOFS, fetch=numeric.fetch,
                             send=numeric.send)
    check("an id with a space round it is the same id",
          result["verdict"] in ("written", "same"), str(result["verdict"]))


def test_the_comparison_panel_s_plan():
    print()
    print("== 8. every compared card whose price differs ==")
    catalog = {"1": {"id": 1, "price": "12.50"},
               "2": {"id": 2, "price": "8.50"},
               "3": {"id": 3, "price": "5.00"},
               "4": {"id": 4, "price": ""},
               "5": {"id": 5, "price": "0"}}
    pairs = [
        {"woo": {"id": 1, "name": "A card"}, "other": {"id": "cs-1",
                                                       "price": "8.50"}},
        {"woo": {"id": 2, "name": "Same price"}, "other": {"id": "cs-2",
                                                           "price": "8.50"}},
        {"woo": {"id": 3, "name": "No id on the listing"},
         "other": {"price": "1.00"}},
        {"woo": {"id": 4, "name": "No price on the website"},
         "other": {"id": "cs-4", "price": "1.00"}},
        {"woo": {"id": 5, "name": "Free on the website"},
         "other": {"id": "cs-5", "price": "1.00"}},
        {"woo": {"id": 1, "name": "Reader without prices"},
         "other": {"id": "cs-6"}},
        {"woo": {"id": 1, "name": "Already the same"}, "other": {
            "id": "cs-7", "price": "CA$12.50"}},
    ]
    plan = cs_record.price_plan(pairs, catalog, PROOFS)
    check("only the card whose price differs is in the plan",
          [(item["id"], item["old"], item["price"]) for item in plan["items"]]
          == [("cs-1", "8.50", "12.50")], str(plan["items"]))
    check("a card with no listing id is counted, not written",
          plan["notes"]["no_id"] == 1, str(plan["notes"]))
    check("a card whose website price is unreadable is counted",
          plan["notes"]["no_site_price"] == 1, str(plan["notes"]))
    check("a listing that reports no price is counted, not guessed",
          plan["notes"]["no_listing_price"] == 1, str(plan["notes"]))
    check("a free card is not pushed to the site as a zero price",
          plan["notes"]["free"] == 1, str(plan["notes"]))
    check("a price that is the same money is not a change",
          all(item["card"] != "Already the same" for item in plan["items"]),
          str(plan["items"]))
    check("the plan knows whether the field is proven", plan["proven"] is True,
          "")
    check("an unproven field is visible in the plan",
          cs_record.price_plan(pairs, catalog, {})["proven"] is False, "")

    check("the summary says how many listings would change",
          "1 listing" in cs_record.plan_summary(plan), cs_record.plan_summary(plan))
    check("nothing to change is said plainly",
          "Nothing to reprice" in
          cs_record.plan_summary({"items": []}), "")
    lines = cs_record.plan_lines({"items": [
        {"card": "Card %d" % number, "old": "1.00", "price": "2.00"}
        for number in range(15)]})
    check("a long plan is cut with the count of what was cut",
          len(lines) == 13 and lines[-1] == "  ... and 3 more", str(lines[-3:]))

    print()
    print("== 9. writing a list, one listing at a time ==")

    class Shelf:
        """Several listings, each at its own record address."""

        def __init__(self, records):
            self.records = {url: dict(record) for url, record in records.items()}
            self.sent = []

        def fetch(self, url, cookie=""):
            if url not in self.records:
                return 404, "<html>no such record</html>"
            return 200, json.dumps(self.records[url])

        def send(self, url, cookie, payload):
            self.sent.append((url, dict(payload)))
            self.records[url].update(payload)
            return 200, '{"ok": true}'

    second_id = "b1234567890abcdef"
    second_url = "https://canadianshopper.ca/api/data/product/" + second_id
    site = Shelf({URL: RECORD,
                  second_url: {"id": second_id, "priceCad": 5, "title": "B"}})
    items = [{"id": LISTING_ID, "card": "Wurmple", "old": "1.00",
              "price": "2.00"},
             {"id": second_id, "card": "Another card", "old": "5.00",
              "price": "6.00"}]
    results = cs_record.write_all(items, "", proofs=PROOFS,
                                  fetch=site.fetch, send=site.send)
    check("every listing in the list is written, in order",
          [result["verdict"] for result in results] == ["written", "written"],
          str([result["verdict"] for result in results]))
    check("and each one sent its own price to its own record",
          site.sent == [(URL, {"priceCad": "2.00"}),
                        (second_url, {"priceCad": "6.00"})], str(site.sent))

    failing = Shelf({URL: RECORD})
    failing.send = lambda url, cookie, payload: (200, '{"ok": true}')
    results = cs_record.write_all(items[:1], "", proofs=PROOFS,
                                  fetch=failing.fetch, send=failing.send)
    check("a run where the site keeps nothing reports it, card by card",
          [result["verdict"] for result in results] == ["ignored"],
          str([result["verdict"] for result in results]))
    check("the tally counts what happened rather than claiming success",
          cs_record.tally(results) == (0, 0, 1), str(cs_record.tally(results)))
    mixed = [{"verdict": "written"}, {"verdict": "same"},
             {"verdict": "ignored"}]
    check("a mixed run is summed up honestly",
          cs_record.tally(mixed) == (1, 1, 1) and
          "1 price set" in cs_record.tally_text(mixed) and
          "1 not changed" in cs_record.tally_text(mixed),
          cs_record.tally_text(mixed))
    steps = []
    cs_record.write_all(items, "", proofs=PROOFS, fetch=site.fetch,
                        send=site.send,
                        on_step=lambda number, total, result:
                        steps.append((number, total, result["verdict"])))
    check("the run says where it has got to", steps[-1][:2] == (2, 2),
          str(steps))

    unproven = cs_record.write_all(items, "", proofs={}, fetch=site.fetch,
                                   send=site.send)
    check("an unproven field writes none of a list",
          [result["verdict"] for result in unproven] ==
          ["unproven", "unproven"], "")



def test_every_proven_field_can_be_written():
    print()
    print("== 10. a form's worth of proven fields ==")
    record = dict(RECORD, title="Wurmple SWSH11", description="Sharp corners.")
    site = Site(record=record)
    proofs = {field: {"proven": True, "verdict": "written", "restored": True,
                      "at": "2026-11-02 15:34:38"} for field in
              ("priceCad", "title", "description", "inventory")}
    result = cs_record.update(
        URL, "", {"priceCad": "2.50", "title": "Wurmple SWSH11 Lost Origin",
                  "inventory": "3"},
        expect_id=LISTING_ID, listing={"id": LISTING_ID, "name": "Wurmple"},
        proofs=proofs, fetch=site.fetch, send=site.send)
    check("every proven field in the form is written in one request",
          result["verdict"] == "written" and len(site.sent) == 1,
          str(result["verdict"]))
    check("and only the fields that changed are in the body",
          sorted(site.sent[0]) == ["inventory", "priceCad", "title"],
          str(site.sent))
    check("each field gets its own answer",
          {entry["field"]: entry["verdict"] for entry in result["fields"]} ==
          {"priceCad": "written", "title": "written", "inventory": "written"},
          str(result["fields"]))
    check("the record really holds all three",
          (site.record["priceCad"], site.record["title"],
           site.record["inventory"]) == ("2.50", "Wurmple SWSH11 Lost Origin",
                                         3), str(site.record))
    check("and the sentence names them",
          "changed on CanadianShopper" in cs_record.sentence(result) and
          "Price" in cs_record.sentence(result), cs_record.sentence(result))

    print()
    print("== 11. what a form may not send ==")
    unlocked = {"priceCad": proofs["priceCad"],
                "title": {"proven": False, "verdict": "ignored"}}
    site = Site(record=record)
    result = cs_record.update(URL, "", {"priceCad": "2.50", "title": "New"},
                              expect_id=LISTING_ID, proofs=unlocked,
                              fetch=site.fetch, send=site.send)
    check("a field with no proof stops the whole write before it is sent",
          result["verdict"] == "unproven" and site.sent == [],
          str(result["verdict"]))
    check("and the answer names the field that is not proven",
          "Title has not been proven" in result["why"], result["why"])
    state = cs_record.refuse_reason("status", "active", proofs)
    check("state is refused outright, with the reason a proof cannot settle it",
          "archiving" in state, state)
    check("a field a form does not know is refused by name",
          "not a field" in cs_record.refuse_reason("colour", "red", proofs), "")
    check("an untouched form is planned as nothing to send",
          cs_record.plan_update({"id": LISTING_ID, "price": "1.00",
                                 "name": "Wurmple"}, {"priceCad": "1.00"},
                                proofs).get("same") is True, "")
    check("a title pasted past a marketplace's limit is refused first",
          "longer than 80" in cs_record.refuse_reason("title", "x" * 81,
                                                      proofs), "")
    check("an empty title is refused",
          "needs a title" in cs_record.refuse_reason("title", "   ", proofs), "")
    check("a negative stock count is refused",
          "whole number" in cs_record.refuse_reason("inventory", "-2", proofs),
          "")
    check("a photo that is not a web address is refused",
          "not a photo" in cs_record.refuse_reason(
              "primaryImageUrl", "x.webp",
              {**proofs, "primaryImageUrl": {"proven": True}}), "")
    check("the evidence sentence names what is open and what is locked",
          "price" in cs_record.evidence_note(unlocked) and
          "title" in cs_record.evidence_note(unlocked), "")
    check("with nothing proven it says the path is closed",
          "will not write" in cs_record.evidence_note({}), "")

    print()
    print("== 12. one field kept, another not ==")
    site = Site(record=record, unkeeps=("title",))
    result = cs_record.update(
        URL, "", {"priceCad": "2.50", "title": "New title"},
        expect_id=LISTING_ID, proofs=proofs, fetch=site.fetch, send=site.send)
    check("a partly-kept write is called partial, not written",
          result["verdict"] == "partial" and result["written"],
          str(result["verdict"]))
    check("the field the site kept says so, and the one it dropped says so",
          {entry["field"]: entry["verdict"] for entry in result["fields"]} ==
          {"priceCad": "written", "title": "ignored"}, str(result["fields"]))
    check("the sentence names both sides",
          "Price now" in cs_record.sentence(result) and
          "Title not kept" in cs_record.sentence(result),
          cs_record.sentence(result))

    print()
    print("== 13. a value that moved since the form was opened ==")
    site = Site(record=dict(record, priceCad=9.99))
    result = cs_record.update(
        URL, "", {"priceCad": "2.50"}, expect_id=LISTING_ID, proofs=proofs,
        expected={"priceCad": "1.00"}, fetch=site.fetch, send=site.send)
    check("a price changed in the dashboard is not overwritten",
          result["verdict"] == "changed" and site.sent == [],
          str(result["verdict"]))
    check("and the answer shows both numbers",
          "9.99" in result["why"] and "1.00" in result["why"], result["why"])
    site = Site(record=record)
    result = cs_record.update(
        URL, "", {"title": "New title"}, expect_id=LISTING_ID, proofs=proofs,
        expected={"title": "Something else entirely"},
        fetch=site.fetch, send=site.send)
    check("a title changed elsewhere is not overwritten either",
          result["verdict"] == "changed" and site.sent == [],
          str(result["verdict"]))
    result = cs_record.update(
        URL, "", {"primaryImageUrl": "https://cs.example/api/file/new.webp"},
        expect_id=LISTING_ID, proofs={**proofs, "primaryImageUrl":
                                      proofs["priceCad"]},
        expected={"primaryImageUrl": "https://shop.example/old.jpg"},
        fetch=Site(record=record).fetch, send=Site().send)
    check("the photo is not blocked by the row's own different URL",
          result["verdict"] != "changed", str(result["verdict"]))

def main():
    test_only_a_proven_field_is_written()
    test_the_price_that_is_sent()
    test_a_price_that_is_written()
    test_what_the_site_answers()
    test_the_address_is_the_records_own()
    test_the_comparison_panel_s_plan()
    test_every_proven_field_can_be_written()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL CS RECORD CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
