#!/usr/bin/env python3
"""Checks for cs_gallery - a listing's photos as rows of their own.

No site and no network: a fake gallery answers the reads, keeps, ignores or
refuses the writes, and removes a row when it is told to.

Every check is about one of the three things that make this module worth
having. A failed read is never an empty gallery - because writing a proof on
top of a gallery nobody could see is how a listing loses a photo. A proof is
add, read, delete, read - so the listing is left as it was. And the only row
this module ever removes is the one its own read-back named.
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


import cs_gallery                                      # noqa: E402

LISTING = "94b93f6040f5401daabaa9c936efa5a7"
PHOTO = "https://canadianshopper.ca/api/file/back_9fcdf283.jpg"
FRONT = "https://canadianshopper.ca/api/file/front.jpg"


class Site:
    """A gallery of rows, and the four ways a site answers a write."""

    def __init__(self, rows=None, post_status=201, delete_status=204,
                 keep=True, fail_reads=(), fail_later_reads=(), ids=True):
        self.rows = [dict(row) for row in (rows or [])]
        self.post_status = post_status
        self.delete_status = delete_status
        self.keep = keep
        self.fail_reads = set(fail_reads)          # read numbers that fail
        self.fail_later_reads = set(fail_later_reads)
        self.ids = ids
        self.reads = 0
        self.sent = []

    def fetch(self, url, cookie=""):
        self.reads += 1
        if self.reads in self.fail_reads or self.reads in self.fail_later_reads:
            return 500, "<html>read failed</html>"
        return 200, json.dumps({"data": self.rows})

    def send(self, method, url, cookie, payload=None):
        self.sent.append((method, url, payload))
        if method == "POST":
            if self.post_status >= 300:
                return self.post_status, '{"error": "not allowed"}'
            if self.keep:
                self.rows.append({
                    "id": ("new-%d" % (len(self.rows) + 1)) if self.ids else "",
                    "product": (payload or {}).get("product"),
                    "imageUrl": (payload or {}).get("imageUrl"),
                    "sortOrder": (payload or {}).get("sortOrder")})
            return self.post_status, "{}"
        if method == "DELETE":
            if self.delete_status >= 300:
                return self.delete_status, "{}"
            gone = url.rsplit("/", 1)[-1]
            self.rows = [row for row in self.rows
                         if str(row.get("id")) != gone]
            return self.delete_status, ""
        return 405, ""


def test_the_address_of_a_gallery():
    print()
    print("== 1. where a listing's gallery is asked for ==")
    url = cs_gallery.read_url(LISTING)
    check("the gallery is its own collection, not a field on the record",
          "/api/data/productImage" in url and "/api/data/product/" not in url,
          url)
    check("the filter names the record's own id",
          "%22value%22%3A%22" + LISTING in url, url)
    check("and it asks for the field, the operator and the value",
          all(part in url for part in ("field", "operator", "eq", "product")),
          url)
    check("the answer is asked for in one read", "limit=1000" in url, url)
    check("no listing id, no address", cs_gallery.read_url("") == "", "")
    check("one row's own address is the collection plus its id",
          cs_gallery.row_url("row-1") ==
          "https://canadianshopper.ca/api/data/productImage/row-1", "")
    check("no row id, no address", cs_gallery.row_url("") == "", "")


def test_what_a_gallery_answer_holds():
    print()
    print("== 2. the rows, and a read that failed ==")
    payload = {"data": [{"id": "r1", "product": LISTING, "imageUrl": FRONT,
                         "sortOrder": 1},
                        {"id": "r2", "product": LISTING, "imageUrl": PHOTO,
                         "sortOrder": 2}]}
    found = cs_gallery.rows(payload)
    check("every row is read with its own id and photo",
          [row["id"] for row in found] == ["r1", "r2"] and
          [row["imageUrl"] for row in found] == [FRONT, PHOTO], str(found))
    check("a bare data list is read too",
          len(cs_gallery.rows(payload["data"])) == 2, "")
    check("a row with no photo address is dropped rather than guessed at",
          cs_gallery.rows({"data": [{"id": "r3"}, {"id": "r4",
                                                  "imageUrl": "x"}]}) ==
          [{"id": "r4", "product": "", "imageUrl": "x", "sortOrder": None}],
          str(cs_gallery.rows({"data": [{"id": "r3"},
                                        {"id": "r4", "imageUrl": "x"}]})))
    check("an empty gallery is an empty list",
          cs_gallery.rows({"data": []}) == [], "")
    check("a body that is not JSON is no rows, not an exception",
          cs_gallery.rows("<html>nope</html>") == [], "")

    site = Site(rows=payload["data"])
    looked = cs_gallery.read(cs_gallery.read_url(LISTING), "", fetch=site.fetch)
    check("a read that answers holds the rows",
          looked["rows"] is not None and len(looked["rows"]) == 2, str(looked))
    site = Site(fail_reads=(1,))
    looked = cs_gallery.read(cs_gallery.read_url(LISTING), "", fetch=site.fetch)
    check("a read that fails is None, never an empty gallery",
          looked["rows"] is None and looked["status"] == 500, str(looked))
    check("and it says why, with the status",
          "500" in looked["why"], looked["why"])


def test_a_photo_added_to_a_gallery():
    print()
    print("== 3. adding one photo ==")
    site = Site(rows=[{"id": "r1", "product": LISTING, "imageUrl": FRONT,
                       "sortOrder": 1}])
    result = cs_gallery.add(LISTING, "c", PHOTO, fetch=site.fetch,
                            send=site.send)
    posted = [payload for method, _url, payload in site.sent
              if method == "POST"]
    check("the row is posted to the gallery collection",
          site.sent and site.sent[0][0] == "POST" and
          site.sent[0][1].endswith("/api/data/productImage"), str(site.sent))
    check("and it carries the record's own id, the photo and a position",
          posted and posted[0] == {"product": LISTING, "imageUrl": PHOTO,
                                   "sortOrder": 2}, str(posted))
    check("the read-back is what says it is there",
          result["verdict"] == "added" and result["written"], str(result))
    check("and the row's own id is kept, so it can be removed again",
          result["row"] == "new-2", str(result.get("row")))
    check("the gallery is read once before and once after",
          site.reads == 2, str(site.reads))

    site = Site(rows=[{"id": "r1", "product": LISTING,
                       "imageUrl": PHOTO.replace("canadianshopper.ca", "cs.example"),
                       "sortOrder": 1}])
    result = cs_gallery.add(LISTING, "c", PHOTO, fetch=site.fetch,
                            send=site.send)
    check("a photo already there is not posted again",
          result["verdict"] == "same" and site.sent == [], str(result))
    check("and the same file under another host is the same photo",
          result["verdict"] == "same", result["verdict"])

    site = Site(keep=False)
    result = cs_gallery.add(LISTING, "c", PHOTO, fetch=site.fetch,
                            send=site.send)
    check("a site that accepts and does not show it is ignored, not added",
          result["verdict"] == "ignored" and not result["after"],
          str(result))
    check("and it says nothing was left behind", "left behind" in result["why"],
          result["why"])

    site = Site(post_status=403)
    result = cs_gallery.add(LISTING, "c", PHOTO, fetch=site.fetch,
                            send=site.send)
    check("a refused post is refused, with the status",
          result["verdict"] == "refused" and "403" in result["why"],
          result["why"])

    site = Site(fail_reads=(1,))
    result = cs_gallery.add(LISTING, "c", PHOTO, fetch=site.fetch,
                            send=site.send)
    check("an unreadable gallery writes nothing at all",
          result["verdict"] == "unreadable" and site.sent == [], str(result))
    check("and the reason is the read, not the photo", "could not be read" in
          result["why"], result["why"])

    site = Site(fail_later_reads=(2,))
    result = cs_gallery.add(LISTING, "c", PHOTO, fetch=site.fetch,
                            send=site.send)
    check("a post with an unreadable read-back is unknown, never added",
          result["verdict"] == "unknown" and result["written"], str(result))
    check("and no row id is invented for it", result["row"] == "",
          str(result.get("row")))

    site = Site()
    result = cs_gallery.add(LISTING, "c", "back.jpg", fetch=site.fetch,
                            send=site.send)
    check("a file on this computer is not a photo a gallery can hold",
          result["verdict"] == "refused" and site.reads == 0 and
          not site.sent, result["why"])
    result = cs_gallery.add("", "c", PHOTO, fetch=site.fetch, send=site.send)
    check("no listing id, no write", result["verdict"] == "unreadable",
          result["why"])

    site = Site(rows=[])
    cs_gallery.add(LISTING, "c", PHOTO, fetch=site.fetch, send=site.send)
    check("the first photo of an empty gallery goes at position 1",
          site.sent[0][2]["sortOrder"] == 1, str(site.sent))
    site = Site(rows=[{"id": "a", "imageUrl": FRONT, "sortOrder": 4},
                      {"id": "b", "imageUrl": PHOTO, "sortOrder": 9}])
    cs_gallery.add(LISTING, "c",
                   "https://canadianshopper.ca/api/file/third.jpg",
                   fetch=site.fetch, send=site.send)
    check("a new photo goes after every row the site already has",
          site.sent[0][2]["sortOrder"] == 10, str(site.sent))


def test_removing_one_row():
    print()
    print("== 4. removing the row this app added ==")
    site = Site(rows=[{"id": "r1", "imageUrl": FRONT, "sortOrder": 1},
                      {"id": "r2", "imageUrl": PHOTO, "sortOrder": 2}])
    result = cs_gallery.remove(LISTING, "c", "r2", fetch=site.fetch,
                               send=site.send)
    check("the row is removed by its own id",
          site.sent[0][0] == "DELETE" and
          site.sent[0][1].endswith("/api/data/productImage/r2"),
          str(site.sent))
    check("and the gallery read back shows it gone",
          result["verdict"] == "removed" and result["restored"], str(result))
    check("the photos that were not this row are still there",
          [row["id"] for row in site.rows] == ["r1"], str(site.rows))

    site = Site(rows=[{"id": "r1", "imageUrl": FRONT, "sortOrder": 1}],
                delete_status=500)
    result = cs_gallery.remove(LISTING, "c", "r1", fetch=site.fetch,
                               send=site.send)
    check("a refused removal is refused, and says the row is still there",
          result["verdict"] == "refused" and "500" in result["why"],
          result["why"])

    site = Site(rows=[{"id": "r1", "imageUrl": FRONT, "sortOrder": 1}])
    site.delete_status = 204
    site.send = lambda method, url, cookie, payload=None: (
        site.sent.append((method, url, payload)) or (204, ""))
    result = cs_gallery.remove(LISTING, "c", "r1", fetch=site.fetch,
                               send=site.send)
    check("a removal the site accepts twice is still wrong",
          result["verdict"] == "unrestored" and
          "still lists row" in result["why"], result["why"])

    site = Site(fail_later_reads=(1,))
    result = cs_gallery.remove(LISTING, "c", "r1", fetch=site.fetch,
                               send=site.send)
    check("a removal with an unreadable read-back is unknown", result["verdict"]
          == "unknown", str(result))
    check("no row id, nothing sent",
          cs_gallery.remove(LISTING, "c", "", fetch=site.fetch,
                            send=site.send)["verdict"] == "refused", "")


def test_the_gallery_proof():
    print()
    print("== 5. add, read, delete, read ==")
    site = Site(rows=[{"id": "r1", "imageUrl": FRONT, "sortOrder": 1}])
    result = cs_gallery.prove(LISTING, "c", PHOTO, fetch=site.fetch,
                              send=site.send)
    check("the proof adds a row, reads it, removes it and reads again",
          [step["step"] for step in result["steps"]] ==
          ["GET the gallery", "POST the gallery row", "GET the gallery back",
           "DELETE the gallery row", "GET the gallery back"],
          str([step["step"] for step in result["steps"]]))
    check("and it calls the field settled, with the listing as it was",
          result["verdict"] == "written" and result["restored"] is True,
          str(result["verdict"]))
    check("the row it removed is the row its own read-back named",
          result["row"] == "new-2", str(result.get("row")))
    check("the photo that was there before is untouched",
          [row["imageUrl"] for row in site.rows] == [FRONT], str(site.rows))
    check("and the counts say what the gallery held",
          result["before"] == 1 and result["after"] == 1, str(result))
    check("the sentence says settled, and how many rows",
          "settled" in cs_gallery.sentence(result) and "1 row" in
          cs_gallery.sentence(result), cs_gallery.sentence(result))
    check("the advice says what can now be done",
          "writable" in cs_gallery.advice(result),
          cs_gallery.advice(result))

    #  A proof of an empty gallery: one row added, read, removed.
    site = Site(rows=[])
    result = cs_gallery.prove(LISTING, "c", PHOTO, fetch=site.fetch,
                              send=site.send)
    check("an empty gallery is proved the same way",
          result["verdict"] == "written" and result["before"] == 0
          and result["after"] == 0 and site.rows == [], str(result))

    #  The photo is there and its row cannot be removed: the listing has
    #  changed, and that must be said loudly rather than called a proof.
    site = Site(rows=[], delete_status=500)
    result = cs_gallery.prove(LISTING, "c", PHOTO, fetch=site.fetch,
                              send=site.send)
    check("a row that cannot be removed is not a proof",
          result["verdict"] == "unrestored" and result["restored"] is False,
          str(result["verdict"]))
    check("and the sentence sends the person to take it off by hand",
          "Take it off" in result["why"], result["why"])
    check("the photo really is still in the gallery",
          [row["imageUrl"] for row in site.rows] == [PHOTO], str(site.rows))

    #  The site keeps the row and gives it no id: nothing may be guessed at.
    site = Site(rows=[], ids=False)
    result = cs_gallery.prove(LISTING, "c", PHOTO, fetch=site.fetch,
                              send=site.send)
    check("a row with no id from the read-back is never removed by guesswork",
          result["verdict"] == "added" and not
          [sent for sent in site.sent if sent[0] == "DELETE"],
          str(site.sent))
    check("and the person is told where the photo is",
          "left in place" in result["why"], result["why"])

    site = Site(keep=False)
    result = cs_gallery.prove(LISTING, "c", PHOTO, fetch=site.fetch,
                              send=site.send)
    check("a gallery that ignores the row is not proved",
          result["verdict"] == "ignored" and not
          [sent for sent in site.sent if sent[0] == "DELETE"], str(result))

    site = Site(post_status=400)
    result = cs_gallery.prove(LISTING, "c", PHOTO, fetch=site.fetch,
                              send=site.send)
    check("a refused add stops the proof before anything is removed",
          result["verdict"] == "refused" and not
          [sent for sent in site.sent if sent[0] == "DELETE"], str(result))

    site = Site(fail_reads=(1,))
    result = cs_gallery.prove(LISTING, "c", PHOTO, fetch=site.fetch,
                              send=site.send)
    check("an unreadable gallery is not proved and not written",
          result["verdict"] == "unreadable" and site.sent == [], str(result))


def main():
    test_the_address_of_a_gallery()
    test_what_a_gallery_answer_holds()
    test_a_photo_added_to_a_gallery()
    test_removing_one_row()
    test_the_gallery_proof()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL CS GALLERY CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
