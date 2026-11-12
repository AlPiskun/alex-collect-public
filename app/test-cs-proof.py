#!/usr/bin/env python3
"""Checks for cs_proof - one field, one listing, written and put back.

No site and no network: a fake record answers the reads and a fake site
honours, ignores or refuses the write, which is exactly the three answers a
proof has to tell apart. The one thing a test must never do is let a proof look
successful when the value was not kept - a proof that lies is worse than no
proof at all.
"""
import json
import sys
import tempfile
from datetime import datetime
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


import cs_proof                                        # noqa: E402

RECORD = {
    "id": "94b93f6040f5401daabaa9c936efa5a7",
    "title": "1973-74 O-Pee-Chee Jim Pappin #112 EX 5",
    "priceCad": 1250.0,
    "inventory": 1,
    "description": "Sharp corners.\n\nCondition Report: clean back.",
    "status": "active",
    "primaryImageUrl": "https://canadianshopper.ca/api/file/pappin-square.webp",
}


class Site:
    """A record and the three ways a site answers a write."""

    def __init__(self, record=None, honours=("priceCad", "title", "description",
                                             "inventory", "primaryImageUrl"),
                 ignore=(), refuse=None, normalise=None, fail_read_after=None,
                 gallery=None, gallery_refuse=None, gallery_keeps=True,
                 fail_gallery_after=None):
        self.record = dict(RECORD if record is None else record)
        self.honours = set(honours)
        self.ignore = set(ignore)
        self.refuse = dict(refuse or {})
        self.normalise = dict(normalise or {})
        self.normalised = set()
        self.reads = 0
        self.fail_read_after = fail_read_after
        self.sent = []
        #  The gallery is a collection of its own: productImage rows keyed by
        #  the listing's id, read and written at their own address.
        self.gallery = [dict(row) for row in (gallery or [])]
        self.gallery_refuse = gallery_refuse
        self.gallery_keeps = gallery_keeps
        self.fail_gallery_after = fail_gallery_after
        self.gallery_reads = 0
        self.gallery_sent = []
        self.gallery_removed = []
        self.next_row = len(self.gallery) + 1

    def fetch(self, url, cookie=""):
        if "/api/data/productImage" in str(url):
            self.gallery_reads += 1
            if (self.fail_gallery_after is not None and
                    self.gallery_reads > self.fail_gallery_after):
                return 500, "<html>the gallery could not be read</html>"
            return 200, json.dumps({"data": self.gallery})
        self.reads += 1
        if (self.fail_read_after is not None and
                self.reads > self.fail_read_after):
            return 500, "<html>read failed</html>"
        return 200, json.dumps(self.record)

    def write(self, method, url, cookie, payload):
        """The gallery's own verbs: POST adds a row, DELETE takes one off."""
        if method == "DELETE":
            return self.send(url, cookie, None)
        return self.send(url, cookie, payload)

    def send(self, url, cookie, payload):
        if "/api/data/productImage" in str(url):
            if self.gallery_refuse is not None:
                return self.gallery_refuse, '{"error": "denied"}'
            if payload is None:
                gone = str(url).rsplit("/", 1)[-1]
                self.gallery_removed.append(gone)
                self.gallery = [row for row in self.gallery
                                if str(row.get("id")) != gone]
                return 204, ""
            self.gallery_sent.append(dict(payload))
            if self.gallery_keeps:
                self.gallery.append({"id": "g%d" % self.next_row,
                                     "product": payload.get("product"),
                                     "imageUrl": payload.get("imageUrl"),
                                     "sortOrder": payload.get("sortOrder")})
                self.next_row += 1
            return 201, "{}"
        self.sent.append(dict(payload))
        field, value = next(iter(payload.items()))
        if field in self.refuse:
            return self.refuse[field], "<html>denied</html>"
        if field in self.honours and field not in self.ignore:
            #  A site that stores a value its own way does it to the first
            #  write; the restore is what it is given.
            if field in self.normalise and field not in self.normalised:
                self.record[field] = self.normalise[field]
                self.normalised.add(field)
            else:
                self.record[field] = value
        return 200, json.dumps({"ok": True})


def test_what_a_field_plan_says():
    print()
    print("== 1. what would be written, and what would be put back ==")
    plan = cs_proof.plan("priceCad", RECORD)
    check("a price is proven a cent above the price now",
          (plan["old"], plan["trial"], plan["restore"]) ==
          (1250.0, "1250.01", 1250.0), str(plan))
    check("and the note says why not a bargain price",
          "not offered a bargain" in plan["note"], plan["note"])

    title = cs_proof.plan("title", RECORD)
    check("a title is proven with a marker on the end",
          title["trial"].endswith(" PROOF") and
          title["restore"] == RECORD["title"], str(title))
    long_title = dict(RECORD, title="A" * 80)
    trimmed = cs_proof.plan("title", long_title)
    check("a title near a marketplace's limit is cut, not refused for length",
          trimmed["trial"].endswith(" PROOF") and
          len(trimmed["trial"]) <= cs_proof.TITLE_ROOM, str(trimmed["trial"]))

    stamp = datetime(2026, 11, 2, 14, 30, 5)
    body = cs_proof.plan("description", RECORD, now=stamp)
    check("a description is proven with one dated marker line",
          body["trial"].endswith("Alex Collect write proof 2026-11-02 14:30:05."
                                 ) and
          body["restore"] == RECORD["description"], str(body["trial"][-80:]))
    check("stock is proven one card up, and put back",
          (cs_proof.plan("inventory", RECORD)["trial"],
           cs_proof.plan("inventory", RECORD)["restore"]) == (2, 1), "")

    photo = cs_proof.plan(
        "primaryImageUrl", RECORD,
        staged_url="https://canadianshopper.ca/api/file/pappin-new.webp")
    check("the main photo is proven with a staged photo of the same card",
          photo["trial"].endswith("pappin-new.webp") and
          photo["restore"] == RECORD["primaryImageUrl"], str(photo))
    check("a photo proof with no staged URL is refused, not guessed",
          "image staging step" in cs_proof.plan("primaryImageUrl", RECORD)["why"],
          "")
    check("the listing's own photo is not a proof of anything",
          "already the listing's main photo" in cs_proof.plan(
              "primaryImageUrl", RECORD,
              staged_url=RECORD["primaryImageUrl"])["why"], "")
    check("something that is not a web address is not a photo",
          "not a web address" in cs_proof.plan(
              "primaryImageUrl", RECORD,
              staged_url="/api/file/x.webp")["why"], "")

    state = cs_proof.plan("status", RECORD)
    check("a listing's state is never proven by being hidden",
          "not proven this way" in state["why"] and
          "visibility change" in state["why"], str(state))
    check("an unknown field is refused by name",
          "not a field" in cs_proof.plan("colour", RECORD)["why"], "")
    check("a field the record does not carry is not touched",
          "nothing to put back" in cs_proof.plan(
              "title", {"id": "a", "priceCad": 1})["why"], "")
    check("a field with no value is not touched either",
          "no value" in cs_proof.plan(
              "title", dict(RECORD, title=""))["why"], "")
    check("the vendor's own spelling is matched without case",
          cs_proof.record_value({"Pricecad": 5.0}, "priceCad") == (True, 5.0),
          "")
    check("a price that is not a number cannot be proven",
          "does not read as a price" in cs_proof.plan(
              "priceCad", dict(RECORD, priceCad="ask"))["why"], "")

    print()
    print("== 2. what counts as the same value ==")
    check("12.5, 12.50 and 12.500 are the same price",
          cs_proof.same("priceCad", 12.5, "12.500") and
          cs_proof.same("priceCad", "12.50", 12.5), "")
    check("a cent is a different price",
          not cs_proof.same("priceCad", "12.50", "12.51"), "")
    check("a stock count is a whole number",
          cs_proof.same("inventory", 2, "2") and
          not cs_proof.same("inventory", 2, 3), "")
    check("a description is its words, exactly",
          cs_proof.same("description", "Sharp.", "Sharp. ") and
          not cs_proof.same("description", "Sharp.", "Sharp"), "")
    check("a value is reported as quoted words, not a bare string",
          cs_proof.value_text("title", "A card") == "'A card'" and
          cs_proof.value_text("description", "") == "(empty)", "")


def test_a_field_that_is_written():
    print()
    print("== 3. a field the site keeps ==")
    site = Site()
    url = "https://canadianshopper.ca/api/data/product/" + RECORD["id"]
    result = cs_proof.prove("priceCad", url, "secret-session", fetch=site.fetch,
                            send=site.send, listing={"id": RECORD["id"],
                                                     "name": RECORD["title"]})
    check("the verdict is written", result["verdict"] == "written",
          result.get("why"))
    check("the old price came back after the restore",
          result["restored"] is True and
          site.record["priceCad"] == 1250.0, str(site.record["priceCad"]))
    check("only the one field was ever sent, and only that field",
          [sorted(payload) for payload in site.sent] ==
          [["priceCad"], ["priceCad"]], str(site.sent))
    check("the trial price is the one that went first",
          site.sent[0]["priceCad"] == "1250.01", str(site.sent))
    check("the five steps are all in the report's order",
          [step["step"] for step in result["steps"]] ==
          ["GET the record", "PATCH priceCad", "GET the record",
           "PATCH priceCad (put back)", "GET the record"], str(result["steps"]))
    check("the sentence says the field can be written, and that it is back",
          "can be written at the record's own id" in cs_proof.sentence(result)
          and "old one is back" in cs_proof.sentence(result),
          cs_proof.sentence(result))
    check("the listing and its id travel with the result",
          result["listing"] == RECORD["id"] and
          result["title"] == RECORD["title"], str(result)[:120])

    print()
    print("== 4. a site that says yes and keeps nothing ==")
    site = Site(ignore=("title",))
    result = cs_proof.prove("title", url, "secret-session", fetch=site.fetch,
                            send=site.send)
    check("an accepted write that changes nothing is ignored, not proven",
          result["verdict"] == "ignored" and result["restored"] is True,
          result.get("why"))
    check("and it says a 200 alone is not proof of a field",
          "200 alone is not proof" in result["why"], result["why"])
    check("the old value was sent once more so nothing is left behind",
          site.sent == [{"title": RECORD["title"] + " PROOF"},
                        {"title": RECORD["title"]}], str(site.sent))
    check("the console line says it is not proven",
          "is not proven" in cs_proof.sentence(result), cs_proof.sentence(result))

    print()
    print("== 5. a site that says no ==")
    site = Site(refuse={"priceCad": 403})
    result = cs_proof.prove("priceCad", url, "secret-session", fetch=site.fetch,
                            send=site.send)
    check("the verdict is refused, with the status",
          result["verdict"] == "refused" and result["status"] == 403,
          result.get("why"))
    check("nothing was put back because nothing was taken",
          len(site.sent) == 1 and site.record["priceCad"] == 1250.0, str(site.sent))
    check("the answer the site gave is kept, not swallowed",
          "denied" in result["steps"][1]["body"], str(result["steps"][1]))
    check("and the sentence names the status",
          "HTTP 403" in cs_proof.sentence(result), cs_proof.sentence(result))

    print()
    print("== 6. when the record cannot be read ==")
    site = Site(fail_read_after=0)                     # the first read
    result = cs_proof.prove("priceCad", url, "", fetch=site.fetch,
                            send=site.send)
    check("nothing is written at all",
          result["verdict"] == "unreadable" and site.sent == [],
          str(site.sent))
    check("and the reason says a value that cannot be read cannot be put back",
          "cannot be put back" in result["why"], result["why"])

    site = Site(fail_read_after=1)                     # read, write, then no read
    result = cs_proof.prove("priceCad", url, "", fetch=site.fetch,
                            send=site.send)
    check("a write whose read-back fails is unknown, not proven",
          result["verdict"] == "unknown" and not cs_proof.proven(result),
          result.get("why"))
    check("the old value is still put back when the read-back fails",
          site.sent[-1] == {"priceCad": 1250.0}, str(site.sent))

    print()
    print("== 7. a write that cannot be put back ==")
    site = Site(refuse={})
    original_send = site.send

    def send_that_stops_restoring(url_, cookie_, payload_):
        if site.sent and payload_ == {"priceCad": 1250.0}:
            site.sent.append(dict(payload_))
            return 500, "<html>no</html>"
        return original_send(url_, cookie_, payload_)

    result = cs_proof.prove("priceCad", url, "", fetch=site.fetch,
                            send=send_that_stops_restoring)
    check("the write is proven, but the restore is not",
          result["verdict"] == "written" and result["restored"] is False,
          str(result.get("restored")))
    check("the field is not called proven while the trial value is on it",
          not cs_proof.proven(result), "")
    check("and the console says loudly to put it back by hand",
          "NOT put back" in cs_proof.sentence(result) and
          "by hand" in cs_proof.sentence(result), cs_proof.sentence(result))

    print()
    print("== 8. a site that stores a price its own way ==")
    site = Site(normalise={"priceCad": 1250.01})
    result = cs_proof.prove("priceCad", url, "", fetch=site.fetch,
                            send=site.send)
    check("a normalised-but-changed value is still a write",
          result["verdict"] == "written" and result["restored"] is True,
          result.get("why"))


def test_the_photo_comes_from_the_staging_step():
    print()
    print("== 8b. the staged photo the image step prepared ==")
    import csv as _csv

    def write(folder, name, rows):
        path = folder / name
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = _csv.DictWriter(
                handle, fieldnames=["title", "image_url", "price_cad"])
            writer.writeheader()
            writer.writerows(rows)
        return path

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        old = write(folder, "canadianshopper_import_20260101_01_of_01.csv",
                    [{"title": RECORD["title"],
                      "image_url": "https://cs.example/api/file/old.webp",
                      "price_cad": "1250.00"}])
        import os
        os.utime(old, (1_700_000_000, 1_700_000_000))
        write(folder, "canadianshopper_import_20260201_01_of_01.csv",
              [{"title": "Another card",
                "image_url": "https://cs.example/api/file/other.webp",
                "price_cad": "5.00"}])
        check("the staged photo is found for the card's own title",
              cs_proof.staged_photo(folder, RECORD["title"]) ==
              "https://cs.example/api/file/old.webp",
              cs_proof.staged_photo(folder, RECORD["title"]))
        check("a title that is not the same words is not the same card",
              cs_proof.staged_photo(folder, "Jim Pappin") == "", "")
        check("the newest batch is read first",
              cs_proof.staged_photo(folder, "Another card") ==
              "https://cs.example/api/file/other.webp", "")

        staged = write(folder, "canadianshopper_import_20260301_01_of_01.csv",
                       [{"title": RECORD["title"],
                         "image_url": "https://shop.example/pappin.jpg",
                         "price_cad": "1250.00"}])
        os.utime(staged, (1_800_000_000, 1_800_000_000))
        check("a row the staging step has not rewritten is not a staged photo",
              cs_proof.staged_photo(folder, RECORD["title"]) ==
              "https://cs.example/api/file/old.webp", "")
        check("a folder with no batch in it answers nothing",
              cs_proof.staged_photo(Path(tmp) / "no-batches",
                                    RECORD["title"]) == "", "")
        check("no title is no answer, not the first row",
              cs_proof.staged_photo(folder, "") == "", "")

        #  Plugin 1.0.40 writes the rewritten CSVs into cs-ready beside the
        #  batch, while the batch itself sits one level above - and the panel
        #  is handed the batch, not the folder inside it.
        ready = folder / "cs-ready"
        ready.mkdir()
        write(ready, "canadianshopper_import_20260401_01_of_01.csv",
              [{"title": RECORD["title"],
                "image_url": "https://cs.example/api/file/new.webp",
                "price_cad": "1250.00"}])
        check("a staged CSV in the cs-ready folder is found from the batch",
              cs_proof.staged_photo(folder, RECORD["title"]) ==
              "https://cs.example/api/file/new.webp",
              cs_proof.staged_photo(folder, RECORD["title"]))
        check("and the newest staged row wins across the two folders",
              cs_proof.staged_photo(ready, RECORD["title"]) ==
              "https://cs.example/api/file/new.webp", "")
        check("while a card only the older batch staged keeps its own photo",
              cs_proof.staged_photo(folder, "Another card") ==
              "https://cs.example/api/file/other.webp", "")


def test_the_photos_a_proof_may_write():
    """The squared photos on the site, offered by the app instead of pasted.

    The plugin uploads the squared images, so the safest picture to prove the
    main-photo field with is one of those: the staging step's own upload for
    this card, or a photo the listing already shows. The one photo that must
    never be offered is the one the listing shows *now* - writing it would prove
    nothing, and it is what the proof has to put back.
    """
    print()
    print("== 8b. which photo the proof may write ==")
    row = {"id": "a" * 32,
           "images": ["https://cs.example/api/file/current.webp",
                      "/api/file/back.webp",
                      {"src": "/api/file/detail.webp"}]}
    candidates = cs_proof.photo_candidates(item=row)
    check("the listing's own photos are offered, with their source",
          [entry["url"] for entry in candidates] ==
          ["https://canadianshopper.ca/api/file/back.webp",
           "https://canadianshopper.ca/api/file/detail.webp"],
          str(candidates))
    check("and a bare path is given the site on the front",
          all(entry["url"].startswith("https://canadianshopper.ca/api/file/")
              for entry in candidates), str(candidates))
    check("the photo the listing shows now is never a candidate",
          not any("current.webp" in entry["url"] for entry in candidates), "")

    staged = cs_proof.photo_candidates(item=row, staged="/api/file/staged.webp")
    check("a staged photo comes first: it is the step's own upload",
          staged[0]["url"] ==
          "https://canadianshopper.ca/api/file/staged.webp" and
          "staging" in staged[0]["source"], str(staged[:1]))
    check("and a photo offered twice is offered once",
          len({entry["url"] for entry in staged}) == len(staged), str(staged))
    check("a staged photo the listing already shows is dropped",
          [entry["url"] for entry in
           cs_proof.photo_candidates(
               item={"images": ["https://cs.example/api/file/one.webp"]},
               staged="https://cs.example/api/file/one.webp")] == [],
          "")

    record = {"id": "a" * 32,
              "primaryImageUrl": "https://cs.example/api/file/primary.webp",
              "images": ["https://cs.example/api/file/gallery.webp",
                         "https://cs.example/api/file/primary.webp"]}
    check("a record's own gallery is offered, and its primary is not",
          [entry["url"] for entry in cs_proof.photo_candidates(record=record)]
          == ["https://cs.example/api/file/gallery.webp"], "")
    check("the record is what says which photo is the main one",
          cs_proof.primary_photo(record=record) ==
          "https://cs.example/api/file/primary.webp", "")
    check("with no record, the row's first photo stands in for it",
          cs_proof.primary_photo(item=row) ==
          "https://cs.example/api/file/current.webp", "")
    check("no photos at all is no candidates, not an invented one",
          cs_proof.photo_candidates(item={"id": "a"}) == [], "")
    #  The batch's own staged rows: a card whose CSV title and site title are
    #  not the same words still needs a way in, and the list is it.
    folder = Path(tempfile.mkdtemp())
    ready = folder / "cs-ready"
    ready.mkdir()
    import csv as _csv
    with (ready / "canadianshopper_import_20260301_01_of_01.csv").open(
            "w", newline="", encoding="utf-8") as handle:
        writer = _csv.DictWriter(handle, ["title", "image_url"])
        writer.writeheader()
        writer.writerow({"title": "Card A", "image_url": "/api/file/a.webp"})
        writer.writerow({"title": "Card B", "image_url":
                         "https://shop.example/b.jpg"})
        writer.writerow({"title": "Card A", "image_url": "/api/file/a.webp"})
    rows = cs_proof.staged_photos(folder)
    check("every staged row is offered, with the title it was staged for",
          rows == [{"title": "Card A",
                    "url": "https://canadianshopper.ca/api/file/a.webp"}],
          str(rows))
    check("a row the staging step has not rewritten is not offered",
          not any("shop.example" in row["url"] for row in rows), str(rows))
    offered = cs_proof.photo_candidates(staged_rows=rows)
    check("the batch's rows reach the photo list, named by their titles",
          offered and offered[0]["url"] ==
          "https://canadianshopper.ca/api/file/a.webp" and
          "Card A" in offered[0]["source"], str(offered))

    #  The card's other photo, at the address the plugin names its pairs with.
    #  This is the one route that needs no local file at all: the listing shows
    #  a squared photo the plugin uploaded, so its sibling is the same card.
    check("a front photo names the back beside it",
          cs_proof.sibling_photos(
              "https://canadianshopper.ca/api/file/wurmple-front.webp") ==
          ["https://canadianshopper.ca/api/file/wurmple-back.webp"], "")
    check("and a back photo names the front, keeping the case it was given",
          cs_proof.sibling_photos("https://cs/api/file/006-FRONT.jpg") ==
          ["https://cs/api/file/006-BACK.jpg"], "")
    check("a name with no front or back in it suggests nothing",
          cs_proof.sibling_photos("https://cs/api/file/plain.webp") == [], "")
    check("the folder part never gets swapped, only the file name",
          cs_proof.sibling_photos("https://cs/front/api/file/card.webp") == [],
          str(cs_proof.sibling_photos(
              "https://cs/front/api/file/card.webp")))
    check("only the part after the last slash is a name to change",
          cs_proof.sibling_photos("https://cs/api/file/front-cover.webp") ==
          ["https://cs/api/file/back-cover.webp"], "")

    def answers(status, kind="image/webp"):
        def opener(url):
            return (status == 200, kind if status == 200 else "")
        return opener

    check("a photo the site answers with an image is alive",
          cs_proof.photo_alive("https://cs/api/file/a.webp",
                               opener=answers(200)) == (True, "image/webp"), "")
    check("a photo the site does not have is not offered",
          cs_proof.photo_alive("https://cs/api/file/a.webp",
                               opener=answers(404)) == (False, ""), "")
    check("a photo address that is not a web address is never fetched",
          cs_proof.photo_alive("/api/file/a.webp", opener=answers(200)) ==
          (False, ""), "")
    check("the record's reading is public, so a caller need not reach inside",
          cs_proof.record_from('{"id": "a", "title": "t"}') ==
          {"id": "a", "title": "t"} and
          cs_proof.record_from("not json") is None, "")

    #  The folders searched are part of the answer when nothing is found: the
    #  batch folder, its cs-ready, and wherever a caller says to look.
    empty = Path(tempfile.mkdtemp())
    elsewhere = Path(tempfile.mkdtemp())
    with (elsewhere / "canadianshopper_staged_history.csv").open(
            "w", newline="", encoding="utf-8") as handle:
        writer = _csv.DictWriter(handle, ["title", "image_url"])
        writer.writeheader()
        writer.writerow({"title": "Card C",
                         "image_url": "https://cs.example/api/file/c.webp"})
    check("an extra folder a caller names is searched too",
          cs_proof.staged_photos(empty, extra_folders=[elsewhere]) ==
          [{"title": "Card C",
            "url": "https://cs.example/api/file/c.webp"}],
          str(cs_proof.staged_photos(empty, extra_folders=[elsewhere])))
    check("the consolidated history is read as well as the batch CSVs",
          cs_proof.staged_photo(elsewhere, "Card C") ==
          "https://cs.example/api/file/c.webp", "")
    check("and the folders searched can be said out loud",
          cs_proof.staged_roots(empty, [elsewhere, ""]) ==
          [empty, elsewhere], str(cs_proof.staged_roots(empty,
                                                        [elsewhere, ""])))
    check("a folder that is not there is not claimed to be searched",
          elsewhere not in cs_proof.staged_roots(empty, ["/no/such/folder"]), "")

    check("a photo address is made whole the same way everywhere",
          cs_proof.absolute_photo("/api/file/x.webp") ==
          "https://canadianshopper.ca/api/file/x.webp" and
          cs_proof.absolute_photo("//cdn.example/x.webp") ==
          "https://cdn.example/x.webp" and
          cs_proof.absolute_photo("https://cs.example/x.webp") ==
          "https://cs.example/x.webp" and
          cs_proof.absolute_photo("") == "", "")


GALLERY = dict(
    RECORD,
    images=["/api/file/pappin-square.webp",
            {"url": "https://canadianshopper.ca/api/file/pappin-back.webp"}])


def test_the_gallery_proof():
    print()
    print("== the gallery, which is a list and not a sentence ==")
    check("the gallery is a field a proof is offered",
          "Gallery photos" in cs_proof.labels() and
          "images" in cs_proof.proof_fields(), str(cs_proof.labels()))
    check("and it is not a field the record-edit form offers",
          "images" not in [field for field, _label in cs_proof.FIELDS],
          str(cs_proof.FIELDS))
    check("a gallery is compared as the photos it holds, not their order",
          cs_proof.same("images", ["/api/file/a.webp", "/api/file/b.webp"],
                        ["https://canadianshopper.ca/api/file/b.webp",
                         "https://canadianshopper.ca/api/file/a.webp"]), "")
    check("a lost photo is a difference, and so is a new one",
          not cs_proof.same("images", ["/api/file/a.webp"],
                            ["/api/file/a.webp", "/api/file/b.webp"]) and
          not cs_proof.same("images", ["/api/file/a.webp"], []), "")
    check("an object in a gallery is read for its address",
          cs_proof.gallery_keys([{"url": "/api/file/a.webp"}]) ==
          ["https://canadianshopper.ca/api/file/a.webp"], "")

    #  The record is never planned to carry a gallery, because it does not.
    refused = cs_proof.plan("images", GALLERY, staged_url="/api/file/new.webp")
    check("the gallery is never planned as a write to the record",
          "not a field of the record" in refused.get("why", "") and
          "productImage" in refused.get("why", ""), refused.get("why", ""))
    check("and a gallery is said as photos, not as a python list",
          cs_proof.value_text("images", GALLERY["images"]).startswith(
              "2 photos:"), cs_proof.value_text("images", GALLERY["images"]))

    url = "https://canadianshopper.ca/api/data/product/" + RECORD["id"]
    site = Site(record=GALLERY, gallery=[
        {"id": "r1", "product": RECORD["id"],
         "imageUrl": "https://cs.example/api/file/old.webp", "sortOrder": 1}])
    result = cs_proof.prove("images", url, "secret-session",
                            staged_url="https://cs.example/api/file/new.webp",
                            fetch=site.fetch, write=site.write)
    check("the gallery is proved by adding a row and removing it again",
          result["verdict"] == "written" and result["restored"] is True,
          str(result.get("why"))[:200])
    check("the row is posted to the gallery's own collection",
          len(site.gallery_sent) == 1 and
          site.gallery_sent[0]["imageUrl"] ==
          "https://cs.example/api/file/new.webp" and
          site.gallery_sent[0]["product"] == RECORD["id"],
          str(site.gallery_sent))
    check("and that same row is the one removed",
          site.gallery_removed == ["g2"], str(site.gallery_removed))
    #  The gallery's writes are POST and DELETE; this module's own sender is a
    #  PATCH. A caller that injects the PATCH sender must not be able to turn a
    #  removal into an edit, so the gallery is always given its own sender.
    other = Site(record=GALLERY)
    patched = []

    def record_sender(*args):
        patched.append(args)
        return 200, "{}"

    second = cs_proof.prove("images", url, "secret-session",
                            staged_url="https://cs.example/api/file/new.webp",
                            fetch=other.fetch, send=record_sender,
                            write=other.write)
    check("the record's own sender is never used for the gallery",
          second["verdict"] == "written" and patched == [] and
          len(other.gallery_sent) == 1 and other.gallery_removed == ["g1"],
          "%s / %s / %s" % (second.get("verdict"), patched,
                            other.gallery_removed))
    check("the gallery is exactly as it was",
          [row["imageUrl"] for row in site.gallery] ==
          ["https://cs.example/api/file/old.webp"], str(site.gallery))
    check("no product record was patched at all", site.sent == [],
          str(site.sent))

    site = Site(record=GALLERY, gallery=[
        {"id": "r1", "imageUrl": "https://cs.example/api/file/new.webp",
         "sortOrder": 1}])
    result = cs_proof.prove("images", url, "secret-session",
                            staged_url="https://cs.example/api/file/new.webp",
                            fetch=site.fetch, write=site.write)
    check("a photo already in the gallery is not added again",
          result["verdict"] == "same" and site.gallery_sent == [],
          str(result.get("verdict")))

    site = Site(record=GALLERY, fail_gallery_after=0)
    result = cs_proof.prove("images", url, "secret-session",
                            staged_url="https://cs.example/api/file/new.webp",
                            fetch=site.fetch, write=site.write)
    check("an unreadable gallery is never written into",
          result["verdict"] == "unreadable" and site.gallery_sent == [],
          str(result.get("verdict")))

    site = Site(record=GALLERY, gallery_keeps=False)
    result = cs_proof.prove("images", url, "secret-session",
                            staged_url="https://cs.example/api/file/new.webp",
                            fetch=site.fetch, write=site.write)
    check("a row the gallery does not show is not settled",
          result["verdict"] == "ignored" and site.gallery_removed == [],
          str(result.get("verdict")))

    site = Site(record=GALLERY)

    def refuse_removal(method, address, cookie, payload):
        if method == "DELETE":
            return 500, "{}"
        return site.write(method, address, cookie, payload)

    result = cs_proof.prove("images", url, "secret-session",
                            staged_url="https://cs.example/api/file/new.webp",
                            fetch=site.fetch, write=refuse_removal)
    check("a row that cannot be removed is not a proof",
          result["verdict"] == "unrestored" and result["restored"] is False,
          str(result.get("verdict")))
    check("and the sentence says the photo is still on the listing",
          "could not be removed" in cs_proof.sentence(result) and
          "take it off on CanadianShopper" in cs_proof.sentence(result),
          cs_proof.sentence(result))
    check("and the advice is to take that row off the listing, not to sign in",
          "Remove that row" in cs_proof.advice(result) and
          "sign in to canadianshopper" not in
          cs_proof.advice(result).casefold(), cs_proof.advice(result))
    text = cs_proof.report_text(result, listing={"id": RECORD["id"]},
                                app_version="3.36")
    check("the proof file says the row and that the photo is still there",
          "As row" in text and "take it off on CanadianShopper" in text)

    print()
    print("== what a person can do about a field that did not settle ==")
    refused = {"field": "priceCad", "label": "Price", "verdict": "refused",
               "status": 401}
    check("a refusal as signed out says to save the cookie again",
          "Sign in to CanadianShopper again" in cs_proof.advice(refused), "")
    check("a refusal the site will not explain points at the proof file",
          "proof file" in cs_proof.advice(
              {"field": "title", "verdict": "refused", "status": 400}), "")
    check("a field the site ignores points at the dashboard and the plugin",
          "dashboard" in cs_proof.advice(
              {"field": "title", "verdict": "ignored"}) and
          "plugin" in cs_proof.advice({"field": "title",
                                       "verdict": "ignored"}), "")
    check("a value that did not come back is an emergency, not a note",
          "by hand now" in cs_proof.advice(
              {"field": "title", "verdict": "written", "restored": False,
               "restore": "A card"}), "")
    check("and a field that did settle needs nothing",
          cs_proof.advice({"field": "title", "verdict": "written",
                           "restored": True}) == "", "")


def test_the_whole_listing_at_once():
    print()
    print("== every field on the listing, in one job ==")
    #  The gallery is a row of its own from the start: the proof must put the
    #  listing back to exactly this, not to an empty gallery.
    front_gallery = {"id": "r1", "product": RECORD["id"],
                     "imageUrl": "https://cs.example/api/file/front-g.webp",
                     "sortOrder": 1}
    site = Site(record=dict(GALLERY), gallery=[front_gallery],
                honours=("priceCad", "title", "description", "inventory",
                         "primaryImageUrl"))
    url = "https://canadianshopper.ca/api/data/product/" + RECORD["id"]
    results = cs_proof.prove_listing(
        url, "secret-session", listing={"id": RECORD["id"],
                                        "name": RECORD["title"]},
        photo="https://cs.example/api/file/front.webp",
        gallery_photo="https://cs.example/api/file/back.webp",
        fetch=site.fetch, send=site.send, write=site.write)
    check("every field the app can prove was proved",
          [result["field"] for result in results] == cs_proof.proof_fields(),
          str([result["field"] for result in results]))
    check("and every one of them settled",
          len(cs_proof.proven_results(results)) == len(results) and
          "All %d fields are settled" % len(results) in
          cs_proof.listing_sentence(results),
          cs_proof.listing_sentence(results))
    main_sent = [payload["primaryImageUrl"] for payload in site.sent
                 if "primaryImageUrl" in payload]
    gallery_sent = [payload["imageUrl"] for payload in site.gallery_sent]
    check("the main photo proof used the front, the gallery the back",
          main_sent and main_sent[0].endswith("front.webp") and
          gallery_sent and
          gallery_sent[0].endswith("back.webp"),
          str((main_sent[:1], gallery_sent[:1])))
    check("nothing was left changed on the listing",
          site.record["priceCad"] == GALLERY["priceCad"] and
          site.record["primaryImageUrl"] == GALLERY["primaryImageUrl"] and
          [row["imageUrl"] for row in site.gallery] ==
          ["https://cs.example/api/file/front-g.webp"],
          str(site.record)[:200])

    print()
    print("== and one field the site will not take ==")
    site = Site(record=dict(GALLERY), refuse={"inventory": 403},
                honours=("priceCad", "title", "description",
                         "primaryImageUrl", "images"))
    results = cs_proof.prove_listing(
        url, "secret-session", photo="https://cs.example/api/file/f.webp",
        gallery_photo="https://cs.example/api/file/b.webp",
        fetch=site.fetch, send=site.send, write=site.write)
    check("the refusal does not stop the other fields being proved",
          len(cs_proof.proven_results(results)) == len(results) - 1,
          cs_proof.listing_sentence(results))
    check("and the listing's sentence names the field that needs attention",
          "Stock needs attention" in cs_proof.listing_sentence(results),
          cs_proof.listing_sentence(results))
    check("a refused field is a problem with a fix beside it",
          [result["field"] for result in cs_proof.problem_results(results)] ==
          ["inventory"] and "not allowed" in cs_proof.advice(
              cs_proof.problem_results(results)[0]), "")

    print()
    print("== a field already settled is not written again ==")
    site = Site(record=dict(GALLERY),
                honours=("priceCad", "title", "description", "inventory",
                         "primaryImageUrl", "images"))
    results = cs_proof.prove_listing(
        url, skip=["priceCad"], photo="https://cs.example/api/file/f.webp",
        gallery_photo="https://cs.example/api/file/b.webp",
        fetch=site.fetch, send=site.send, write=site.write)
    check("a skipped field is reported, not silently dropped",
          results[0]["verdict"] == "skipped" and
          results[0]["settled_earlier"] is True and
          "settled by an earlier proof" in results[0]["why"],
          str(results[0]))
    check("and it is said as done, not as a write that could not be read",
          "was settled by an earlier proof" in cs_proof.sentence(results[0])
          and "readable back" not in cs_proof.sentence(results[0]),
          cs_proof.sentence(results[0]))
    check("and nothing at all was sent for it",
          not any("priceCad" in payload for payload in site.sent),
          str(site.sent[:2]))
    sentence = cs_proof.listing_sentence(results)
    check("a settled field counts as done when the whole is counted",
          "All %d fields are settled" % len(results) in sentence and
          "1 already settled by an earlier proof" in sentence, sentence)
    check("and it is not listed as needing attention",
          "Price" not in ", ".join(result["label"] for result in
                                   cs_proof.problem_results(results)),
          str([result["label"]
               for result in cs_proof.problem_results(results)]))

    print()
    print("== a photo field with no photo is not guessed at ==")
    site = Site(record=dict(GALLERY),
                honours=("priceCad", "title", "description", "inventory",
                         "primaryImageUrl", "images"))
    results = cs_proof.prove_listing(url, fetch=site.fetch, send=site.send, write=site.write)
    photo_results = [result for result in results
                     if result["field"] in cs_proof.photo_fields()]
    check("both photo fields are skipped, with the reason",
          all(result["verdict"] == "skipped" for result in photo_results) and
          all("was not attempted: no photo of this card" in result["why"]
              for result in photo_results), str(photo_results))
    check("and a skip for want of a photo is a problem, unlike a settled one",
          len(cs_proof.problem_results(results)) == 2,
          str([result["field"]
               for result in cs_proof.problem_results(results)]))
    check("and the fields that are not photos are still proved",
          [result["verdict"] for result in results if result["field"] not in
           cs_proof.photo_fields()] == ["written"] * 4,
          str([result["verdict"] for result in results]))
    check("nothing was written for a skipped field",
          not any("primaryImageUrl" in payload or "images" in payload
                  for payload in site.sent), str(site.sent)[:200])

    print()
    print("== the photo to prove with, found rather than asked for ==")
    check("the staged photo is the first choice",
          cs_proof.photo_for_proof(
              record=dict(GALLERY, primaryImageUrl=""),
              staged="https://cs.example/api/file/staged.webp") ==
          "https://cs.example/api/file/staged.webp", "")
    check("a sibling is used only after the site answers for it",
          cs_proof.photo_for_proof(
              record={"primaryImageUrl": "https://cs.example/api/file/a-front.webp"},
              alive=lambda url: (False, "")) == "" and
          cs_proof.photo_for_proof(
              record={"primaryImageUrl": "https://cs.example/api/file/a-front.webp"},
              alive=lambda url: (True, "image/webp")) ==
          "https://cs.example/api/file/a-back.webp", "")
    check("the photo the listing shows now is never the one written",
          cs_proof.photo_for_proof(
              item={"images": ["https://cs.example/api/file/a.webp"]},
              record={"primaryImageUrl": "https://cs.example/api/file/a.webp"}
          ) == "", "")

    print()
    print("== the listing's proof file ==")
    site = Site(record=dict(GALLERY), refuse={"inventory": 403},
                honours=("priceCad", "title", "description",
                         "primaryImageUrl", "images"))
    results = cs_proof.prove_listing(
        url, "secret-session", photo="https://cs.example/api/file/f.webp",
        gallery_photo="https://cs.example/api/file/b.webp",
        fetch=site.fetch, send=site.send, write=site.write)
    text = cs_proof.listing_report_text(
        results, listing={"id": RECORD["id"], "name": RECORD["title"]},
        app_version="3.36")
    check("the file names every field that was tried",
          all(cs_proof.field_label(result["field"]) in text
              for result in results), "")
    check("it says which field needs attention and what to do",
          "Needs attention:" in text and "Stock:" in text and
          "not allowed" in text, text[:400])
    check("it never carries the session cookie",
          "secret-session" not in text, "")


def test_a_photo_of_the_wrong_card_is_never_chosen():
    """The report: a Wurmple listing was proved with a 1978 baseball card.

    Five fields were settled, so the run only had the gallery to prove - but it
    still picked the photos, and the best-scoring row in the batch was a
    different card entirely. The chooser shows a person the titles; the
    automatic run has nobody looking, so a photo may only be written when the
    app is sure it is this card.
    """
    print()
    print("== never a photo of a different card ==")
    wurmple = "#006/196 Wurmple SWSH11: Lost Origin - Pokémon TCG"
    check("a baseball card from the same batch is not this card",
          not cs_proof.same_card(
              wurmple, "56 Syl Apps 1978-79 O-Pee-Chee Baseball Card"), "")
    check("and neither is another Pokemon card from another set",
          not cs_proof.same_card(wurmple, "Pikachu Base Set 58/102"), "")
    check("the same card with a grade on the end is this card",
          cs_proof.same_card(
              wurmple, "#006/196 Wurmple SWSH11 Lost Origin Pokemon TCG EX-MT"),
          "")
    check("an empty title is never this card",
          not cs_proof.same_card(wurmple, "") and
          not cs_proof.same_card("", "anything"), "")

    record = {"id": "a", "primaryImageUrl":
              "https://canadianshopper.ca/api/file/wurmple-front.jpg",
              "images": ["https://canadianshopper.ca/api/file/wurmple-front.jpg"]}
    rows = [{"title": "56 Syl Apps 1978-79 O-Pee-Chee Baseball Card",
             "url": "https://canadianshopper.ca/api/file/apps-front.jpg"},
            {"title": "73 Pit Martin 1973-74 O-Pee-Chee",
             "url": "https://canadianshopper.ca/api/file/pit-front.jpg"}]
    photos = cs_proof.auto_photos(item={"name": wurmple}, record=record,
                                  staged_rows=rows, siblings=[], card=wurmple)
    check("with nothing of this card, no photo is chosen at all",
          photos["main"] == "" and photos["gallery"] == "", str(photos))
    check("and the reason names the closest row and how close it was",
          "Syl Apps" in photos["why_main"] and "%" in photos["why_main"] and
          "not this card" in photos["why_main"], photos["why_main"])
    check("the reason says the photo chooser is the way through",
          "photo chooser" in photos["why_main"], photos["why_main"])

    #  A staged row that really is this card is used, and the same photo is
    #  never chosen for both fields.
    rows2 = [{"title": wurmple, "url":
              "https://canadianshopper.ca/api/file/wurmple-back.jpg"},
             {"title": "56 Syl Apps 1978-79 O-Pee-Chee Baseball Card",
              "url": "https://canadianshopper.ca/api/file/apps-front.jpg"}]
    photos = cs_proof.auto_photos(item={"name": wurmple},
                                  record={"primaryImageUrl":
                                          "https://cs/api/file/front.jpg"},
                                  staged_rows=rows2, siblings=[], card=wurmple)
    check("a staged row whose title is this card is used",
          photos["main"].endswith("wurmple-back.jpg"), str(photos))
    check("and a second photo of this card goes to the gallery",
          cs_proof.auto_photos(
              item={"name": wurmple},
              record={"primaryImageUrl": "https://cs/api/file/front.jpg"},
              gallery_rows=[{"id": "r1",
                             "imageUrl": "https://cs/api/file/front.jpg"}],
              staged_rows=rows2 + [{"title": wurmple + " back",
                                    "url": "https://cs/api/file/back2.jpg"}],
              siblings=[], card=wurmple)["gallery"].endswith("back2.jpg"), "")
    check("a photo already in the gallery is not added twice",
          cs_proof.auto_photos(
              item={"name": wurmple},
              record={"primaryImageUrl": "https://cs/api/file/front.jpg"},
              gallery_rows=[
                  {"id": "r1", "imageUrl": "https://cs/api/file/front.jpg"},
                  {"id": "r2",
                   "imageUrl":
                       "https://cs/api/file/wurmple-back.jpg"}],
              staged_rows=rows2, siblings=[], card=wurmple)["gallery"] == "",
          "")
    #  A record with no gallery field says nothing about the gallery: without
    #  the rows, nothing is claimed and no "carries no gallery" is invented.
    photos = cs_proof.auto_photos(item={"name": wurmple},
                                  record={"primaryImageUrl":
                                          "https://cs/api/file/front.jpg"},
                                  staged_rows=rows2, siblings=[], card=wurmple)
    check("a record with no gallery is not a listing with no gallery",
          photos["why_gallery"] == "" or "carries no gallery"
          not in photos["why_gallery"], photos["why_gallery"])
    #  No photo of this card at all, and a gallery holding somebody else's:
    #  "every photo of this card is already in the gallery" is vacuously true
    #  over an empty list, and it is the wrong sentence twice over - there is
    #  no photo of this card, and the gallery is not the thing at fault.
    photos = cs_proof.auto_photos(
        item={"name": wurmple},
        record={"primaryImageUrl": "https://cs/api/file/front.jpg"},
        gallery_rows=[{"id": "r1",
                       "imageUrl": "https://cs/api/file/apps-front.jpg"}],
        staged_rows=[], siblings=[], alive=lambda url: (False, ""),
        card=wurmple)
    check("no photo of this card is never said as a gallery that holds them "
          "all",
          photos["gallery"] == "" and
          "already in the listing's gallery" not in photos["why_gallery"] and
          bool(photos["why_main"]), str(photos))

    #  A listing whose every photo of the card is already in its gallery, and
    #  a proof of it: the proof adds a second row for one of those photos and
    #  takes that row off again, so the gallery ends as it started. Without
    #  that, this listing's gallery could never be proved at all.
    settled_gallery = [{"id": "r1", "imageUrl": "https://cs/api/file/front.jpg"},
                       {"id": "r2", "imageUrl": "https://cs/api/file/back.jpg"}]
    plain = cs_proof.auto_photos(
        item={"name": wurmple},
        record={"primaryImageUrl": "https://cs/api/file/front.jpg"},
        gallery_rows=settled_gallery,
        staged_rows=[], siblings=["https://cs/api/file/back.jpg"],
        alive=lambda url: (True, ""), card=wurmple)
    check("an add with every photo already there says there is nothing new",
          plain["gallery"] == "" and "nothing new to add" in
          plain["why_gallery"], str(plain))
    proved = cs_proof.auto_photos(
        item={"name": wurmple},
        record={"primaryImageUrl": "https://cs/api/file/front.jpg"},
        gallery_rows=settled_gallery,
        staged_rows=[], siblings=["https://cs/api/file/back.jpg"],
        alive=lambda url: (True, ""), card=wurmple, proof_copy=True)
    check("a proof of that listing uses a copy of a photo the gallery shows",
          proved["gallery"] in ("https://cs/api/file/front.jpg",
                                "https://cs/api/file/back.jpg"),
          str(proved))
    check("and says it is a second row that comes off again",
          "second row" in proved["why_gallery"] and
          "keeps exactly the rows" in proved["why_gallery"],
          proved["why_gallery"])

    print()
    print("== the gallery is not a key on the record, whatever it is called ==")
    url = "https://canadianshopper.ca/api/data/product/" + RECORD["id"]
    for key in ("images", "galleryImages", "imageUrls", "gallery", "photos"):
        found = dict(RECORD, **{key: ["https://cs/api/file/a.webp",
                                      "https://cs/api/file/b.webp"]})
        planned = cs_proof.plan("images", found,
                                staged_url="https://cs/api/file/new.webp")
        check("a record carrying %r is still not planned as a gallery write"
              % key, "not a field of the record" in planned.get("why", ""),
              str(planned)[:160])
        site = Site(record=found)
        result = cs_proof.prove("images", url, "secret-session",
                                staged_url="https://cs/api/file/new.webp",
                                fetch=site.fetch, write=site.write)
        check("and %r is never patched on the record, and never read for it"
              % key,
              result["verdict"] == "written" and site.sent == [] and
              site.record.get(key) == found[key], str(site.sent))


def test_a_record_with_no_gallery_stops_being_a_problem():
    """The report: a record with 39 keys and no gallery among them.

    The record's shape is still worth keeping - it is the evidence a plugin
    author needs - but it is evidence about the *record*, not a verdict on the
    gallery: the gallery is productImage rows, and a listing whose record shows
    no gallery can have a full one. So the shape is reported and the field is
    still offered.
    """
    print()
    print("== the record's keys are evidence, not a verdict ==")
    record = {"id": "a", "createdAt": "2026-10-01", "vendor": "pokemon",
              "title": "Wurmple", "slug": "wurmple", "description": "A card.",
              "primaryImageUrl": "https://cs/api/file/wurmple-front.jpg",
              "priceCad": 1.0, "inventory": 1, "status": "active",
              "category": "pokemon", "shipFromProvince": "ON",
              "shippingFlatCad": 3.0, "specs": ["set: Lost Origin"],
              "tags": ["vintage", "pokemon"]}
    report = cs_proof.photo_field_report(record)
    check("the fields that could hold photos are named, with what is in them",
          any(line.startswith("primaryImageUrl is text") for line in report) and
          any(line.startswith("tags is a list of 2") for line in report),
          str(report))
    #  gallery_keys is a reader for a value that already *is* a gallery: the
    #  filtering of what counts as a photo lives in photo_field_report, which
    #  is what the proof file shows. A list of words is named as a list of
    #  words there, not as photos.
    check("a list of words is named as words, not as photos",
          any(line.startswith("tags is a list of 2") for line in report),
          str(report))
    check("the gallery is offered whatever the record's keys say",
          "images" in cs_proof.proof_fields() and
          "Gallery photos" in cs_proof.labels(), str(cs_proof.labels()))
    check("and the record's shape is never the reason a gallery is refused",
          "not a field of the record" in cs_proof.plan(
              "images", record, staged_url="https://cs/api/file/back.jpg"
          ).get("why", ""), "")


def test_the_report():
    print()
    print("== 9. the file the author is handed ==")
    site = Site()
    url = "https://canadianshopper.ca/api/data/product/" + RECORD["id"]
    result = cs_proof.prove("priceCad", url, "secret-session", fetch=site.fetch,
                            send=site.send, listing={"id": RECORD["id"],
                                                     "name": RECORD["title"]})
    text = cs_proof.report_text(result, listing={"id": RECORD["id"],
                                                 "name": RECORD["title"]},
                                when=datetime(2026, 11, 2, 14, 30, 5),
                                app_version="3.36")
    check("it names the listing and the record's own id",
          RECORD["title"] in text and RECORD["id"] in text and
          "not a product id" in text, text[:400])
    check("it names the address the vendor has to look at", url in text, "")
    check("before, wrote, read back, put back and final are all there",
          all(word in text for word in
              ("Before:", "Wrote:", "Read back:", "Put back:", "Final:")), "")
    check("the result is the sentence, not a bare status",
          "can be written at the record's own id" in text, text[-600:])
    check("every step and its status is listed",
          "GET the record" in text and "PATCH priceCad" in text and
          "HTTP 200" in text, "")
    check("the session cookie is never in it", "secret-session" not in text, "")
    check("and it says so at the end",
          "No cookie, token or password is in this file." in text, "")

    refused = dict(result, verdict="refused", status=403,
                   why="The site refused the write (HTTP 403).")
    refused_text = cs_proof.report_text(refused, listing={"id": "a"})
    check("a refusal is reported with its status, not as a success",
          "HTTP 403" in refused_text and "Result:" in refused_text, "")
    stuck = dict(result, restored=False, final="1250.01")
    stuck_text = cs_proof.report_text(stuck, listing={"id": "a"})
    check("a restore that did not happen is in the file twice",
          "! The old value was not read back" in stuck_text and
          "still shows" in stuck_text, stuck_text[-400:])

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        first = cs_proof.proof_path(folder, now=datetime(2026, 11, 2, 14, 30, 5))
        check("a proof file is dated to the second, in the app's folder",
              first.name.startswith("cs-proof-20261102-143005") and
              first.parent == folder, str(first))
        first.write_text("x", encoding="utf-8")
        second = cs_proof.proof_path(folder, now=datetime(2026, 11, 2, 14, 30, 5))
        check("a second proof in the same second is its own file",
              second != first and second.name.endswith("-2.txt"), str(second))


def test_what_the_app_remembers():
    print()
    print("== 10. what is remembered between proofs ==")
    site = Site()
    url = "https://canadianshopper.ca/api/data/product/" + RECORD["id"]
    written = cs_proof.prove("priceCad", url, "", fetch=site.fetch,
                             send=site.send)
    ignored = cs_proof.prove("title", url, "", fetch=Site(ignore=("title",)).fetch,
                             send=Site(ignore=("title",)).send)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        data = cs_proof.remember(folder, written, now=datetime(2026, 11, 2, 9))
        check("a written-and-restored field is remembered as proven",
              cs_proof.settled("priceCad", data) and
              data["priceCad"]["verdict"] == "written", str(data))
        data = cs_proof.remember(folder, ignored, now=datetime(2026, 11, 2, 10))
        check("an ignored field is remembered as not proven",
              not cs_proof.settled("title", data) and
              data["title"]["restored"] is True, str(data["title"]))
        check("the file on disk is the same answer",
              cs_proof.settled("priceCad", cs_proof.load_proofs(folder)) and
              not cs_proof.settled("title", cs_proof.load_proofs(folder)), "")
        broken = dict(written, restored=False)
        data = cs_proof.remember(folder, broken, now=datetime(2026, 11, 2, 11))
        check("a proof that stopped being true replaces the earlier one",
              not cs_proof.settled("priceCad", data), str(data["priceCad"]))
        check("a folder with no proofs answers without a file",
              cs_proof.load_proofs(Path(tmp) / "nothing-here") == {}, "")


def test_a_field_this_record_does_not_have_is_remembered():
    print()
    print("== 14. \"no such field here\" is remembered, so it is not asked again ==")
    import tempfile
    folder = Path(tempfile.mkdtemp(prefix="alex-absent-"))
    try:
        absent = cs_proof.missing_result("title", record={"id": "abc",
                                                           "priceCad": 1})
        cs_proof.remember(folder, absent, listing={"id": "abc"})
        proofs = cs_proof.load_proofs(folder)
        check("a field the record does not carry is saved as that",
              proofs["title"]["field_missing"] is True, str(proofs))
        check("and it is not saved as proven",
              proofs["title"]["proven"] is False and
              not cs_proof.settled("title", proofs), str(proofs))
        check("the same listing is not asked again",
              cs_proof.known_absent("title", proofs, "abc"), "")
        check("another listing may carry the field, so it is asked there",
              not cs_proof.known_absent("title", proofs, "def"), "")
        check("a field with no mark is not treated as absent",
              not cs_proof.known_absent("description", proofs, "abc"), "")

        #  The gallery is the exception, and it is the whole point: it is not
        #  a record field, so "the record has no such field" says nothing about
        #  it. A mark left by an older version must not keep it unproved.
        gallery = cs_proof.missing_result("images", record={"id": "abc",
                                                            "priceCad": 1})
        cs_proof.remember(folder, dict(gallery, field_missing=True),
                          listing={"id": "abc"})
        proofs = cs_proof.load_proofs(folder)
        check("the gallery is never remembered as a missing field",
              proofs["images"]["field_missing"] is False, str(proofs["images"]))
        check("and an older mark on it is not believed",
              not cs_proof.known_absent("images", proofs, "abc"), "")

        #  A later run that finds the field clears the mark, because the
        #  record grew it - that is what adding a gallery photo does.
        written = cs_proof.plan("images", {"id": "abc", "images": ["a"]},
                                staged_url="/api/file/b.jpg")
        cs_proof.remember(folder, dict(written, verdict="written",
                                       restored=True, field_missing=False),
                          listing={"id": "abc"})
        proofs = cs_proof.load_proofs(folder)
        check("a proof that finds the field clears the mark",
              proofs["images"]["field_missing"] is False, str(proofs))
        check("and the field is settled from then on",
              cs_proof.settled("images", proofs), str(proofs))
        check("so it is no longer skipped as absent",
              not cs_proof.known_absent("images", proofs, "abc"), "")
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def main():
    test_what_a_field_plan_says()
    test_a_field_that_is_written()
    test_the_photo_comes_from_the_staging_step()
    test_the_photos_a_proof_may_write()
    test_the_gallery_proof()
    test_the_whole_listing_at_once()
    test_a_photo_of_the_wrong_card_is_never_chosen()
    test_a_record_with_no_gallery_stops_being_a_problem()
    test_the_report()
    test_what_the_app_remembers()
    test_a_field_this_record_does_not_have_is_remembered()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL CS PROOF CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
