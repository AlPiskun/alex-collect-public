#!/usr/bin/env python3
"""Offline tests for woo_media.py.

Uploading a replacement photo is the one part of the app that changes a live
shop, so its failure behaviour matters more than its happy path: a refused
upload must write nothing and say why, and a failed product update must not
claim success. All of it is checked here with a fake opener, so no network,
no window, and no real credentials are involved.
"""
import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path[:0] = [str(APP)]

import woo_media  # noqa: E402

PASS = 0
FAIL = 0

SITE = "https://shop.example"
USER = "owner"
PASSWORD = "abcd EFGH ijkl MNOP"
KEY = "ck_abc"
SECRET = "cs_def"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s %s" % (name, extra))


class FakeOpener:
    """Stands in for urlopen: records each request, replays canned replies."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, request, timeout=None):
        body = request.data or b""
        self.requests.append({
            "method": request.get_method(),
            "url": request.full_url,
            "headers": dict(request.header_items()),
            "body": body,
            "timeout": timeout,
        })
        reply = self.replies.pop(0) if self.replies else (200, b"{}")
        if isinstance(reply, Exception):
            raise reply
        return reply


def media_reply(attachment_id=901, url="https://shop.example/a.webp"):
    return (201, json.dumps({"id": attachment_id,
                             "source_url": url}).encode("utf-8"))


def product_reply(product_id=42, ids=(901,)):
    return (200, json.dumps({"id": product_id,
                             "images": [{"id": i} for i in ids]}
                            ).encode("utf-8"))


def temp_image(name="gretzky-front-1.webp", data=b"RIFF-webp-bytes"):
    folder = Path(tempfile.mkdtemp())
    path = folder / name
    path.write_bytes(data)
    return path


def test_headers_and_names():
    print("== 1. the request the site actually receives ==")
    image = temp_image()
    opener = FakeOpener(media_reply())
    record = woo_media.upload_media(SITE, USER, PASSWORD, image,
                                    title="Gretzky", opener=opener)
    sent = opener.requests[0]
    check("the media endpoint is posted to",
          sent["url"] == "https://shop.example/wp-json/wp/v2/media",
          sent["url"])
    check("it is a POST with the image bytes",
          sent["method"] == "POST" and sent["body"] == image.read_bytes())
    lower = {k.lower(): v for k, v in sent["headers"].items()}
    check("the Application Password is sent as Basic auth",
          lower.get("authorization") == woo_media.basic_auth(USER, PASSWORD),
          str(lower.get("authorization")))
    check("the type is taken from the extension, not guessed",
          lower.get("content-type") == "image/webp", str(lower.get("content-type")))
    check("the filename is declared, quoted",
          lower.get("content-disposition") ==
          'attachment; filename="gretzky-front-1.webp"',
          str(lower.get("content-disposition")))
    check("the attachment ID comes back as a number",
          record["id"] == 901 and isinstance(record["id"], int), str(record))
    check("the hosted URL comes back", record["source_url"].endswith("a.webp"))

    print()
    print("== 2. awkward filenames and types ==")
    check("a non-ASCII name is made header-safe",
          woo_media.safe_filename("Café card (front)!.webp") ==
          "Caf_card_front.webp",
          woo_media.safe_filename("Café card (front)!.webp"))
    check("a path is not smuggled into the header",
          woo_media.safe_filename("../../etc/passwd.png") == "passwd.png",
          woo_media.safe_filename("../../etc/passwd.png"))
    check("a name with no extension still works",
          woo_media.safe_filename("front") == "front")
    check("a name that cleans away to nothing gets a fallback",
          woo_media.safe_filename("***.webp") == "replacement.webp",
          woo_media.safe_filename("***.webp"))
    check("jpeg is recognised", woo_media.content_type_for("a.JPG") ==
          "image/jpeg")
    check("webp is recognised without mimetypes' help",
          woo_media.content_type_for("a.webp") == "image/webp")


def test_refusals():
    print()
    print("== 3. refusals explain themselves and leak nothing ==")
    image = temp_image()
    cases = [
        (401, "Application Password"),
        (403, "not allowed to upload"),
        (413, "larger than"),
    ]
    for status, phrase in cases:
        opener = FakeOpener((status, json.dumps(
            {"message": "site said no", "code": "x"}).encode("utf-8")))
        try:
            woo_media.upload_media(SITE, USER, PASSWORD, image, opener=opener)
            check("HTTP %d is refused" % status, False, "no error raised")
        except woo_media.MediaError as exc:
            check("HTTP %d is refused with a readable reason" % status,
                  phrase in exc.message and exc.status == status, exc.message)
    html = FakeOpener((500, b"<html><body>Fatal error</body></html>"))
    try:
        woo_media.upload_media(SITE, USER, PASSWORD, image, opener=html)
        check("an unparseable error body is still refused", False)
    except woo_media.MediaError as exc:
        check("an HTML error page does not crash the message",
              "HTTP 500" in exc.message, exc.message)

    unreachable = FakeOpener(urllib.error.URLError("Name or service not known"))
    try:
        woo_media.upload_media(SITE, USER, PASSWORD, image, opener=unreachable)
        check("an unreachable host is refused", False)
    except woo_media.MediaError as exc:
        check("an unreachable host says so",
              "Could not reach the website" in exc.message, exc.message)

    print()
    print("== 4. nothing is attempted without what it needs ==")
    for label, args in (
            ("no site", ("", USER, PASSWORD, image)),
            ("no username", (SITE, "", PASSWORD, image)),
            ("no password", (SITE, USER, "", image)),
            ("missing file", (SITE, USER, PASSWORD, image.parent / "gone.webp")),
    ):
        idle = FakeOpener()
        try:
            woo_media.upload_media(*args, opener=idle)
            check("%s is refused" % label, False, "no error raised")
        except woo_media.MediaError:
            check("%s is refused before any request is made" % label,
                  not idle.requests, str(idle.requests))

    print()
    print("== 5. the password never ends up in a message ==")
    opener = FakeOpener((401, b'{"message":"bad credentials"}'))
    try:
        woo_media.upload_media(SITE, USER, PASSWORD, image, opener=opener)
    except woo_media.MediaError as exc:
        check("the password is not echoed back",
              PASSWORD not in exc.message and "MNOP" not in exc.message,
              exc.message)
        check("neither is the encoded form",
              "YWRtaW4" not in exc.message and "bas" not in exc.message.lower(),
              exc.message)


def test_product_update():
    print()
    print("== 6. the product is pointed at the new image first ==")
    opener = FakeOpener(product_reply())
    product = {"id": 42, "name": "Gretzky", "images": [{"id": 5}, {"id": 6}]}
    woo_media.set_product_images(SITE, KEY, SECRET, 42, [901, 5, 6],
                                 opener=opener)
    sent = opener.requests[0]
    check("a PUT goes to this product's endpoint",
          sent["method"] == "PUT" and
          sent["url"].startswith(
              "https://shop.example/wp-json/wc/v3/products/42?"), sent["url"])
    check("the keys travel as query parameters",
          "consumer_key=ck_abc" in sent["url"] and
          "consumer_secret=cs_def" in sent["url"], sent["url"])
    body = json.loads(sent["body"].decode("utf-8"))
    check("the new image is first, the old ones follow",
          [i["id"] for i in body["images"]] == [901, 5, 6], str(body))

    print()
    print("== 7. keeping or replacing the old gallery ==")
    opener = FakeOpener(media_reply(), product_reply())
    result = woo_media.replace_product_photo(
        SITE, KEY, SECRET, USER, PASSWORD, product, temp_image(),
        keep_existing=True, opener=opener)
    check("by default the existing photos are kept behind the new one",
          result["image_ids"] == [901, 5, 6], str(result["image_ids"]))
    opener = FakeOpener(media_reply(), product_reply(ids=(901,)))
    result = woo_media.replace_product_photo(
        SITE, KEY, SECRET, USER, PASSWORD, product, temp_image(),
        keep_existing=False, opener=opener)
    check("asking to replace the gallery sends only the new image",
          result["image_ids"] == [901], str(result["image_ids"]))
    check("junk in the images array is ignored",
          woo_media.existing_image_ids(
              {"images": [{"id": 5}, {"id": "x"}, {}, {"src": "u"}]}) == [5])
    check("a product with no images still works",
          woo_media.existing_image_ids({"id": 1}) == [])

    print()
    print("== 8. a half-finished replacement is reported as half-finished ==")
    opener = FakeOpener(media_reply(), (500, b'{"message":"boom"}'),
                        (500, b'{"message":"boom"}'))
    try:
        woo_media.replace_product_photo(SITE, KEY, SECRET, USER, PASSWORD,
                                        product, temp_image(), opener=opener)
        check("a failed product update raises", False, "no error raised")
    except woo_media.MediaError as exc:
        check("it says the image reached the library", "media library" in
              exc.message, exc.message)
        check("it says the product was NOT updated",
              "NOT updated" in exc.message, exc.message)
        check("it carries the attachment id so the work is not lost",
              exc.attachment_id == 901 and exc.partial, str(vars(exc)))

    opener = FakeOpener(media_reply(), (401, b'{"message":"bad keys"}'))
    try:
        woo_media.replace_product_photo(SITE, KEY, SECRET, USER, PASSWORD,
                                        product, temp_image(), opener=opener)
    except woo_media.MediaError as exc:
        check("Read-only keys are called out", "Read/Write" in exc.message,
              exc.message)

    print()
    print("== 9. upload refusal means nothing is changed ==")
    opener = FakeOpener((401, b'{"message":"no"}'))
    try:
        woo_media.replace_product_photo(SITE, KEY, SECRET, USER, PASSWORD,
                                        product, temp_image(), opener=opener)
        check("a refused upload raises", False)
    except woo_media.MediaError as exc:
        check("a refused upload is not reported as partial",
              not exc.partial and exc.attachment_id is None, str(vars(exc)))
        check("the product was never touched", len(opener.requests) == 1,
              str([r["url"] for r in opener.requests]))

    opener = FakeOpener(media_reply(), (200, b"{}"))
    try:
        woo_media.replace_product_photo(SITE, KEY, SECRET, USER, PASSWORD,
                                        product, temp_image(), opener=opener)
        check("an empty 200 is not accepted as success", False, "no error raised")
    except woo_media.MediaError as exc:
        check("an empty 200 is not accepted as success",
              "could not be confirmed" in exc.message, exc.message)
    opener = FakeOpener(media_reply(), product_reply(ids=(5,)))
    try:
        woo_media.replace_product_photo(SITE, KEY, SECRET, USER, PASSWORD,
                                        product, temp_image(), opener=opener)
        check("an answer without the new image is not success", False)
    except woo_media.MediaError as exc:
        check("an answer without the new image is not success",
              "not on the product" in exc.message, exc.message)

    print()
    print("== 10. retries only where they are safe ==")
    opener = FakeOpener((503, b"busy"), product_reply())
    woo_media.set_product_images(SITE, KEY, SECRET, 42, [901],
                                 retries=2, opener=opener)
    check("a busy site is retried and the update still lands",
          len(opener.requests) == 2, str(len(opener.requests)))
    opener = FakeOpener((401, b"no"), product_reply())
    try:
        woo_media.set_product_images(SITE, KEY, SECRET, 42, [901],
                                     retries=3, opener=opener)
    except woo_media.MediaError:
        check("a refusal is not retried pointlessly",
              len(opener.requests) == 1, str(len(opener.requests)))
    opener = FakeOpener(media_reply())
    try:
        woo_media.replace_product_photo(SITE, KEY, SECRET, USER, PASSWORD,
                                        {"name": "no id"}, temp_image(),
                                        opener=opener)
    except woo_media.MediaError:
        check("a product with no id uploads nothing", not opener.requests)


def test_parsing_helpers():
    print()
    print("== 11. small helpers ==")
    check("a trailing slash is dropped",
          woo_media.site_root("https://shop.example/") == "https://shop.example")
    check("a bare host is refused", woo_media.site_root("shop.example") == "")
    check("https is recognised", woo_media.is_https("https://a.example"))
    check("http is recognised as not https",
          not woo_media.is_https("http://a.example"))
    check("Basic auth is the standard encoding",
          woo_media.basic_auth("user", "pass") == "Basic dXNlcjpwYXNz",
          woo_media.basic_auth("user", "pass"))
    check("an empty images list is refused",
          _raises(lambda: woo_media.set_product_images(
              SITE, KEY, SECRET, 42, [], opener=FakeOpener())))


def _raises(fn):
    try:
        fn()
    except woo_media.MediaError:
        return True
    return False


def main():
    test_headers_and_names()
    test_refusals()
    test_product_update()
    test_parsing_helpers()
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL WOO MEDIA CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
