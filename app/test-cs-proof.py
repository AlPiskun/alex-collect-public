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
                 ignore=(), refuse=None, normalise=None, fail_read_after=None):
        self.record = dict(RECORD if record is None else record)
        self.honours = set(honours)
        self.ignore = set(ignore)
        self.refuse = dict(refuse or {})
        self.normalise = dict(normalise or {})
        self.normalised = set()
        self.reads = 0
        self.fail_read_after = fail_read_after
        self.sent = []

    def fetch(self, url, cookie=""):
        self.reads += 1
        if (self.fail_read_after is not None and
                self.reads > self.fail_read_after):
            return 500, "<html>read failed</html>"
        return 200, json.dumps(self.record)

    def send(self, url, cookie, payload):
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
                                app_version="3.23")
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


def main():
    test_what_a_field_plan_says()
    test_a_field_that_is_written()
    test_the_photo_comes_from_the_staging_step()
    test_the_report()
    test_what_the_app_remembers()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL CS PROOF CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
