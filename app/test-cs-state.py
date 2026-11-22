#!/usr/bin/env python3
"""Checks for cs_state - putting a listing back on sale at its own record.

``marketplace.listing_update`` patches ``/api/products/<product_id>/`` and
refuses a listing whose record names no product, which on the shop this was
written for is every listing (2,704 of 2,704). A listing's state is also on its
own record, at ``/api/data/product/<listing-id>``, and that address is the one
the app already writes proven fields to - so this is where "put this card back
on sale" is answered.

No site and no network: a fake record answers the reads and a fake site keeps,
ignores or refuses the write. Every check is about one of the three things that
matter - that only the state is ever sent, at the listing that was chosen, and
that what the site did afterwards is reported rather than assumed.
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


import cs_state                                        # noqa: E402

LISTING_ID = "a2304e72dbca4e678e7111d011ade22d"
URL = "https://canadianshopper.ca/api/data/product/" + LISTING_ID

#: The record as the shop answered it - the same shape cs_record's own fixture
#: uses, because both write to the same address. This one is archived.
RECORD = {"id": LISTING_ID,
          "title": "#319 Val Fonteyne 1972-73 O-Pee-Chee",
          "priceCad": 4, "inventory": 1, "status": "Archived"}


class Site:
    """A record, and the ways a site answers a state write."""

    def __init__(self, record=None, keep=True, refuse=False, fail_reads=(),
                 unkeeps=False, after=None, id_in_record=True):
        self.record = dict(RECORD if record is None else record)
        if not id_in_record:
            self.record.pop("id", None)
        self.keep = keep
        self.refuse = refuse
        self.fail_reads = set(fail_reads)      # which read number fails
        self.unkeeps = unkeeps                 # accepted, not kept
        self.after = after                     # what the record says after
        self.reads = 0
        self.sent = []

    def fetch(self, url="", cookie=""):
        self.reads += 1
        if self.reads in self.fail_reads:
            return 500, "<html>read failed</html>"
        record = dict(self.record)
        if self.reads > 1 and self.after is not None:
            record = dict(self.record, **self.after)
        return 200, json.dumps(record)

    def send(self, url, cookie, payload):
        self.sent.append(dict(payload))
        if self.refuse:
            return 403, "<html>denied</html>"
        if self.keep and not self.unkeeps:
            for field, value in payload.items():
                self.record[field] = value
        return 200, "{}"


def runner(site, **changes):
    options = dict(url=URL, cookie="session=1", to="active",
                   expect="archived", listing_id=LISTING_ID,
                   listing={"name": "#319 Val Fonteyne 1972-73 O-Pee-Chee"},
                   fetch=site.fetch, send=site.send)
    options.update(changes)
    return cs_state.change(**options)


# ---------------------------------------------------------------- the words
def test_the_words():
    print()
    print("== 1. the two states, and the vendor's spelling of them ==")
    check("the two states a listing can be moved to", 
          cs_state.word_for("active") == "active" and
          cs_state.word_for("archived") == "archived", "")
    check("and the words a person reads for them",
          cs_state.label_for("active") == "on sale" and
          cs_state.label_for("archived") == "archived", "")
    check("anything else is not a state this module writes",
          cs_state.word_for("draft") == "" and
          cs_state.word_for("") == "" and cs_state.word_for(None) == "", "")
    check("a state the vendor spells in its own case is the same state",
          cs_state.same_state("Archived", "archived") and
          cs_state.same_state("ARCHIVED", "archived") and
          cs_state.same_state("Active", "active"), "")
    check("and a different state is not",
          not cs_state.same_state("Archived", "active") and
          not cs_state.same_state("draft", "active"), "")
    check("a draft is neither of the two states, and is not pretended to be",
          cs_state.state_of("draft") == "draft" and
          cs_state.state_of("") == "", "")

    #  The gate the panel uses: a plan that asks for a state and nothing else
    #  is the record road's business; anything else is the plugin's.
    only = {"id": 102, "sku": "OPC73-91", "title": "Joe Watson",
            "card": "Joe Watson", "status": "active"}
    check("a plan that asks for the state alone is the record road's",
          cs_state.changes_only_state(only), str(only))
    check("a price in it is not",
          not cs_state.changes_only_state(dict(only, price="6.00")), "")
    check("nor a count, a description or a photo",
          not cs_state.changes_only_state(dict(only, inventory=2)) and
          not cs_state.changes_only_state(dict(only, description="x")) and
          not cs_state.changes_only_state(
              dict(only, primaryImageUrl="https://cs.example/a.jpg")), "")
    check("nor a renamed title",
          not cs_state.changes_only_state(dict(only, title="Joe Watson EX")),
          "")
    check("and a plan with no state at all is not one either",
          not cs_state.changes_only_state(dict(only, status="")), "")


# ---------------------------------------------------------------- the write
def test_putting_a_listing_back_on_sale():
    print()
    print("== 2. archived to on sale, at the listing's own record ==")
    site = Site()
    result = runner(site)
    check("the state is written", result["verdict"] == "written" and
          result["written"], str(result))
    check("one field, one request", site.sent == [{"status": "active"}],
          str(site.sent))
    check("the record was read before and after it", site.reads == 2,
          str(site.reads))
    check("and the answer says what it was and what it is now",
          result["was"] == "archived" and result["now"] == "active",
          (result["was"], result["now"]))
    check("the sentence says it was read back, and what was not touched",
          "read back after the write" in cs_state.sentence(result) and
          "your website was not touched" in cs_state.sentence(result),
          cs_state.sentence(result))

    #  The other direction is the same request with the other word.
    site = Site(record=dict(RECORD, status="active"))
    put_away = runner(site, to="archived", expect="active")
    check("putting a listing away is the same write the other way",
          put_away["verdict"] == "written" and
          site.sent == [{"status": "archived"}], str(site.sent))


def test_a_site_that_does_not_keep_it():
    print()
    print("== 3. accepted is not changed: what the record says afterwards ==")
    site = Site(unkeeps=True)
    result = runner(site)
    check("a write the site tolerated but did not keep is not called written",
          result["verdict"] == "ignored" and not result["written"],
          str(result))
    check("it says the record still shows the old state",
          "still says it is archived" in result["why"], result["why"])
    check("and says where the change has to be made instead",
          "vendor dashboard" in result["why"], result["why"])
    check("the sentence never claims the state changed",
          "shows it as on sale" not in cs_state.sentence(result),
          cs_state.sentence(result))

    site = Site(refuse=True)
    result = runner(site)
    check("a refusal keeps the site's own status", result["verdict"] ==
          "refused" and result["status"] == 403, str(result))
    check("and says the listing is unchanged",
          "still archived" in result["why"], result["why"])

    site = Site(after={"status": "draft"})
    result = runner(site)
    check("a state neither asked for nor held is named, not accepted",
          result["verdict"] == "other" and "draft" in result["why"],
          result["why"])
    check("and the sentence sends nobody on without checking it",
          "Check that listing" in cs_state.sentence(result),
          cs_state.sentence(result))

    site = Site(fail_reads=(2,))
    result = runner(site)
    check("a write that cannot be read back is unconfirmed, not written",
          result["verdict"] == "unknown" and not result["written"],
          str(result))


def test_what_is_never_sent():
    print()
    print("== 4. nothing is written on a guess ==")
    site = Site(record=dict(RECORD, status="active"))
    result = runner(site)
    check("a listing already in that state is not written",
          result["verdict"] == "same" and site.sent == [], str(site.sent))
    check("and the sentence says so plainly",
          "already on sale" in cs_state.sentence(result),
          cs_state.sentence(result))

    #  The row was read a while ago and the site has moved on since: the state
    #  the person was looking at is not the state there now.
    site = Site()
    result = runner(site, expect="active")
    check("a listing that moved since the list was read is not written",
          result["verdict"] == "changed" and site.sent == [], str(site.sent))
    check("and the answer names both states",
          "archived" in result["why"] and "on sale" in result["why"],
          result["why"])

    site = Site(id_in_record=False)
    result = runner(site)
    check("a record that does not name the listing is not written",
          result["verdict"] == "refused" and site.sent == [], str(site.sent))
    site = Site(record=dict(RECORD, id="someone-else"))
    result = runner(site)
    check("nor is a record that names a different one",
          result["verdict"] == "refused" and site.sent == [] and
          "someone-else" in result["why"], str(site.sent))
    site = Site(record={key: value for key, value in RECORD.items()
                        if key != "status"})
    result = runner(site)
    check("a record with no state on it cannot be read back, so is not written",
          result["verdict"] == "refused" and site.sent == [], str(site.sent))
    site = Site(fail_reads=(1,))
    result = runner(site)
    check("a record that cannot be read at all is not written",
          result["verdict"] == "unreadable" and site.sent == [], str(site.sent))
    site = Site()
    result = runner(site, listing_id="")
    check("no record id, no request", result["verdict"] == "unreadable" and
          not site.sent and site.reads == 0, str(site.reads))
    result = runner(Site(), to="draft")
    check("a state this module does not write is refused, not guessed",
          result["verdict"] == "refused" and result["sent"] == {}, "")

    check("the identity of the listing, not just its state, is checked first",
          "changing the wrong listing" in runner(Site(id_in_record=False))["why"],
          "")


class Deleting:
    """A record, and the ways a site answers a DELETE.

    Deleting a listing is the one request in this app that cannot be undone
    from it, so the shapes it has to get right are all here: the record that
    goes, the record the site keeps in its bin, the record it leaves exactly as
    it was, the refusal, and a read the app cannot make at all.
    """

    def __init__(self, record=None, gone=True, bin_word="", keep=False,
                 refuse=0, fail_reads=(), id_in_record=True,
                 before_gone=False, new_id=""):
        self.record = dict(RECORD if record is None else record)
        if not id_in_record:
            self.record.pop("id", None)
        self.gone = gone
        self.bin_word = bin_word
        self.keep = keep
        self.refuse = refuse
        self.fail_reads = set(fail_reads)
        self.before_gone = before_gone
        self.new_id = new_id
        self.reads = 0
        self.deleted = []

    def fetch(self, url="", cookie=""):
        self.reads += 1
        if self.reads in self.fail_reads:
            return 500, "<html>read failed</html>"
        if self.before_gone:
            return 404, '{"message": "Not found"}'
        if self.deleted and self.gone and not self.keep:
            return 404, '{"message": "Not found"}'
        record = dict(self.record)
        if self.deleted and self.new_id:
            record["id"] = self.new_id
        return 200, json.dumps(record)

    def send(self, url, cookie):
        self.deleted.append(url)
        if self.refuse:
            return self.refuse, "<html>denied</html>"
        if self.keep:
            return 204, ""
        if self.bin_word:
            self.record["status"] = self.bin_word
        return 204, ""


def remover(site, **changes):
    options = dict(url=URL, cookie="session=1", listing_id=LISTING_ID,
                   listing={"name": "#319 Val Fonteyne 1972-73 O-Pee-Chee"},
                   fetch=site.fetch, send=site.send)
    options.update(changes)
    return cs_state.remove(**options)


def test_deleting_a_listing():
    print()
    print("== 5. deleting a listing, and reading the record afterwards ==")
    site = Deleting()
    result = remover(site)
    check("a record that goes is reported as deleted",
          result["verdict"] == "deleted" and cs_state.removed(result),
          str(result))
    check("one delete, at the listing's own record",
          site.deleted == [URL], str(site.deleted))
    check("the record was read before and after it", site.reads == 2,
          str(site.reads))
    check("and the sentence says the record is gone, read back after it",
          "record is gone" in cs_state.remove_sentence(result),
          cs_state.remove_sentence(result))
    check("and that the website was not touched",
          "your website was not touched" in cs_state.remove_sentence(result),
          cs_state.remove_sentence(result))

    site = Deleting(gone=False, bin_word="Trash")
    result = remover(site)
    check("a site that keeps the record in its bin says so",
          result["verdict"] == "trashed" and cs_state.removed(result),
          str(result))
    check("and the sentence names the bin and the dashboard",
          "bin" in cs_state.remove_sentence(result) and
          "vendor dashboard" in cs_state.remove_sentence(result),
          cs_state.remove_sentence(result))

    site = Deleting(gone=False, keep=True)
    result = remover(site)
    check("accepted and unchanged is not a deletion",
          result["verdict"] == "left" and not cs_state.removed(result),
          str(result))
    check("and it says the listing is still there, and where to delete it",
          "still there" in cs_state.remove_sentence(result) and
          "vendor dashboard" in cs_state.remove_sentence(result),
          cs_state.remove_sentence(result))

    site = Deleting(refuse=405)
    result = remover(site)
    check("a refused delete keeps the site's own status",
          result["verdict"] == "refused" and result["status"] == 405,
          str(result))
    check("and a 405 says this address does not take a delete",
          "does not take a delete" in result["why"] and
          "vendor dashboard" in result["why"], result["why"])


def test_a_delete_is_never_sent_on_a_guess():
    print()
    print("== 6. what a delete will not do ==")
    site = Deleting(id_in_record=False)
    result = remover(site)
    check("a record that names no listing is not deleted",
          result["verdict"] == "refused" and not site.deleted, str(result))
    site = Deleting(record=dict(RECORD, id="someone-else"))
    result = remover(site)
    check("nor is a record that names a different one",
          result["verdict"] == "refused" and not site.deleted and
          "someone-else" in result["why"], str(result))
    check("and it says deleting the wrong listing is the mistake it must "
          "never make",
          "deleting the wrong listing" in result["why"], result["why"])
    site = Deleting(fail_reads=(1,))
    result = remover(site)
    check("a record that cannot be read is not deleted",
          result["verdict"] == "unreadable" and not site.deleted,
          str(result))
    check("and nothing at all is asked of the site",
          site.reads == 1 and not site.deleted, str(site.reads))
    site = Deleting(before_gone=True)
    result = remover(site)
    check("a record that is already gone sends no delete",
          result["verdict"] == "deleted" and not site.deleted, str(result))
    check("and says there is nothing to delete", "nothing was sent" in
          result["why"], result["why"])
    site = Deleting()
    result = remover(site, listing_id="")
    check("no record id, no request at all",
          result["verdict"] == "unreadable" and site.reads == 0 and
          not site.deleted, str(site.reads))
    result = remover(Deleting(), url="")
    check("no address, no request at all",
          result["verdict"] == "unreadable" and result["steps"] == [],
          str(result))

    site = Deleting(fail_reads=(2,))
    result = remover(site)
    check("a delete that cannot be read back is unconfirmed, not deleted",
          result["verdict"] == "unknown" and not cs_state.removed(result),
          str(result))
    check("and says to check that listing before anything else",
          "Check it on CanadianShopper" in result["why"], result["why"])
    site = Deleting(gone=False, new_id="another-listing")
    result = remover(site)
    check("an address that answers as another listing is named, not assumed",
          result["verdict"] == "other" and "another-listing" in result["why"],
          str(result))

    check("the words that mean a record is in the bin are known",
          cs_state.in_bin("Trash") and cs_state.in_bin("deleted") and
          cs_state.in_bin("recycled"), "")
    check("and a state that is not one of them is not a deletion",
          not cs_state.in_bin("archived") and not cs_state.in_bin("active") and
          not cs_state.in_bin(""), "")


def main():
    test_the_words()
    test_putting_a_listing_back_on_sale()
    test_a_site_that_does_not_keep_it()
    test_what_is_never_sent()
    test_deleting_a_listing()
    test_a_delete_is_never_sent_on_a_guess()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL CS STATE CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
