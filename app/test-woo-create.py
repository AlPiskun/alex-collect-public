#!/usr/bin/env python3
"""Checks for woo_create - making the batch's products on the website itself.

No network and no Tk: the site is a fake opener that answers the REST calls
this module makes, records them, and can be told to refuse any one of them.
The point of the module is that a batch cannot end up half-created, twice
created, or live without its photos, so most of these checks are about what
happens when one card goes wrong.
"""
import importlib.util
import json
import os
import sys
import tempfile
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


def load(name):
    path = APP / (name.replace("-", "_") + ".py") if False else APP / name
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_").replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


woo_create = load("woo_create.py")
woo_create.SITE_RETRY_PAUSE = 0        # the tests do not need the waits
pipeline = load("pipeline/card_pipeline.py")

FIELDS = ["SKU", "Name", "Published", "Is featured?", "Visibility in catalog",
          "Short description", "Description", "In stock?", "Stock",
          "Regular price", "Categories", "Tags", "Images",
          "Attribute 1 name", "Attribute 1 value(s)", "Attribute 1 visible",
          "Attribute 1 global", "rank_math_title", "rank_math_description",
          "rank_math_focus_keyword"]


def write_csv(folder, rows):
    import csv
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "woocommerce_import_20260101_120000.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def row(n, **changes):
    base = {
        "SKU": "OPC1971-%03d-PR-2" % n,
        "Name": "1971-72 O-Pee-Chee Test Card #%03d (PR)" % n,
        "Published": 1,
        "Is featured?": 0,
        "Visibility in catalog": "visible",
        "Short description": "A test card.",
        "Description": "A test card, described.",
        "In stock?": 1,
        "Stock": 1,
        "Regular price": 9,
        "Categories": "Sports Card > Hockey Card",
        "Tags": "hockey, o-pee-chee",
        "Images": "test_%03d.webp" % n,
        "Attribute 1 name": "Brand",
        "Attribute 1 value(s)": "O-Pee-Chee",
        "Attribute 1 visible": 1,
        "Attribute 1 global": 1,
        "rank_math_title": "SEO title %d" % n,
        "rank_math_description": "SEO description %d" % n,
        "rank_math_focus_keyword": "hockey card",
    }
    base.update(changes)
    return base


#  What WordPress sends when a PHP fatal ends the request: one sentence, the
#  same for everybody, and no hint of what actually went wrong.
CRITICAL_ERROR_PAGE = (
    b"<p>There has been a critical error on this website.</p>"
    b"<p><a href=\"https://wordpress.org/documentation/article/faq-"
    b"troubleshooting/\">Learn more about troubleshooting WordPress.</a></p>")


class FakeSite:
    """A site that answers the calls woo_create makes, and remembers them."""

    def __init__(self, exist=(), categories=None, refuse=None,
                 publish_status="publish", existing=None, fail_once=(),
                 save_then_fail=()):
        self.calls = []
        self.products = {}
        self.by_sku = {sku: pid for sku, pid in exist}
        self.next_id = 900
        for sku, pid in self.by_sku.items():
            self.products[pid] = {"id": pid, "sku": sku, "name": sku,
                                  "status": "publish"}
        #  ``existing`` describes a product the site already had: its status
        #  and whether it carries photos. A batch that stopped half way leaves
        #  exactly this behind.
        for sku, detail in (existing or {}).items():
            pid = self.by_sku[sku]
            self.products[pid].update(detail)
        self.categories = dict(categories or {})     # name -> id
        self.next_category = 40
        self.refuse = dict(refuse or {})             # (method, keyword) -> code
        self.publish_status = publish_status
        self.uploads = []
        self.attach_calls = []                       # (attachment, product)
        #  A site that hiccups once and then works, and a site that writes the
        #  product before its own error page - the two shapes of a real HTTP
        #  500 that the app has to tell apart.
        self.fail_once = list(fail_once)
        self.save_then_fail = set(save_then_fail)

    def __call__(self, request, timeout=None):
        method = request.get_method()
        url = request.full_url
        body = None
        if request.data:
            try:
                body = json.loads(request.data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                body = {"_binary": True}      # an image upload, not JSON
        self.calls.append({"method": method, "url": url, "body": body})

        if "wp/v2/media" in url and method == "POST":
            self.uploads.append(url)
            self.next_id += 1
            return 201, json.dumps({"id": self.next_id,
                                    "source_url": "https://shop.example/x.webp"}
                                   ).encode("utf-8")

        for pair in self.fail_once:
            if method == pair[0] and pair[1] in url:
                self.fail_once.remove(pair)
                return 500, CRITICAL_ERROR_PAGE
        for (refuse_method, keyword), code in self.refuse.items():
            if method == refuse_method and keyword in url:
                if code >= 500:
                    return code, CRITICAL_ERROR_PAGE
                return code, json.dumps({"message": "refused by test"}).encode()

        if "/products/categories" in url:
            if method == "GET":
                name = url.split("search=")[1].split("&")[0].replace("+", " ")
                found = self.categories.get(name)
                rows = ([{"id": found, "name": name}] if found else [])
                return 200, json.dumps(rows).encode("utf-8")
            self.next_category += 1
            self.categories[body["name"]] = self.next_category
            return 201, json.dumps({"id": self.next_category,
                                    "name": body["name"]}).encode("utf-8")

        if "/products" in url and "sku=" in url:
            sku = url.split("sku=")[1].split("&")[0]
            sku = sku.replace("%2D", "-").replace("%2d", "-")
            pid = self.by_sku.get(sku)
            rows = ([self.products[pid]] if pid in self.products else [])
            return 200, json.dumps(rows).encode("utf-8")

        if "wp/v2/media" in url and method == "PUT":
            #  The attachment is given its product as its parent, which is
            #  what stops the media library filing the photo as unattached.
            attachment_id = int(url.rstrip("/").rsplit("/", 1)[-1])
            self.attach_calls.append({"id": attachment_id,
                                      "post": (body or {}).get("post")})
            return 200, json.dumps({"id": attachment_id,
                                    "post": (body or {}).get("post")}
                                   ).encode("utf-8")

        if "/products" in url and method == "POST":
            self.next_id += 1
            product = dict(body)
            product.update({"id": self.next_id, "status": body.get("status"),
                            "permalink": "https://shop.example/?p=%d"
                                         % self.next_id})
            self.products[self.next_id] = product
            if body.get("sku"):
                self.by_sku[body["sku"]] = self.next_id
            if body.get("sku") in self.save_then_fail:
                #  The row is written, then the request dies: WordPress's own
                #  "critical error" page is what comes back.
                return 500, CRITICAL_ERROR_PAGE
            return 201, json.dumps(product).encode("utf-8")

        if "/products/" in url and method == "PUT":
            pid = int(url.split("/products/")[1].split("?")[0])
            product = self.products.get(pid, {})
            product["status"] = self.publish_status
            self.products[pid] = product
            return 200, json.dumps(product).encode("utf-8")

        return 404, b"{}"


def build(tmp, rows, exist=(), refuse=None, images=True):
    folder = Path(tmp) / "output"
    folder.mkdir(parents=True, exist_ok=True)
    if images:
        for item in rows:
            name = str(item.get("Images") or "").split(",")[0].strip()
            if name:
                (folder / name).write_bytes(b"not-really-a-webp")
    csv_path = write_csv(Path(tmp) / "woocommerce_products", rows)
    read = woo_create.read_rows(csv_path)
    return read, woo_create.plan(read["rows"], [folder])


def test_reading():
    print()
    print("== 1. the CSV the pipeline writes is what is read ==")
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1), row(2)])
    check("both rows are read", len(read["rows"]) == 2, str(read["rows"]))
    check("the batch folder is remembered",
          read["folder"].name == "woocommerce_products", str(read["folder"]))
    check("the plan holds both products", len(planned["items"]) == 2,
          str(planned["items"]))
    item = planned["items"][0]
    check("the name, SKU and price come across",
          item["name"].startswith("1971-72 O-Pee-Chee") and
          item["sku"].startswith("OPC1971") and item["price"] == "9", str(item))
    check("the category path is split parent first",
          item["categories"] == ["Sports Card", "Hockey Card"],
          str(item["categories"]))
    check("the tags are split", item["tags"] == ["hockey", "o-pee-chee"],
          str(item["tags"]))
    check("the brand becomes one attribute",
          item["attributes"] == [{"name": "Brand",
                                  "options": ["O-Pee-Chee"], "visible": True,
                                  "variation": False}], str(item["attributes"]))
    check("the SEO fields are carried as meta",
          item["meta"]["rank_math_title"] == "SEO title 1", str(item["meta"]))
    check("the photo is found in the output folder",
          item["missing_images"] == [], str(item["missing_images"]))

    empty = Path(tmp) / "empty.csv"
    empty.write_text("SKU,Name\n", encoding="utf-8")
    try:
        woo_create.read_rows(empty)
        check("a file with no product rows is refused", False, "")
    except woo_create.ProductError as exc:
        check("a file with no product rows is refused", "no product rows" in
              exc.message, exc.message)
    try:
        woo_create.read_rows(Path(tmp) / "nope.csv")
        check("a missing file is refused with its name", False, "")
    except woo_create.ProductError as exc:
        check("a missing file is refused with its name",
              "nope.csv" in exc.message, exc.message)


def test_payload():
    print()
    print("== 2. the product body holds only what is known ==")
    tmp = tempfile.mkdtemp()
    _read, planned = build(tmp, [row(1, **{"Regular price": ""})])
    item = planned["items"][0]
    body = woo_create.build_payload(item, image_ids=[3, 4],
                                    category_ids_=[7, 8])
    check("it is always created as a draft",
          body["status"] == "draft", str(body["status"]))
    check("it is a simple, stock-managed product",
          body["type"] == "simple" and body["manage_stock"] is True,
          str(body))
    check("the stock and its state come from the CSV",
          body["stock_quantity"] == 1 and body["stock_status"] == "instock",
          str(body))
    check("a blank price is left out rather than sent as zero",
          "regular_price" not in body, str(body.get("regular_price")))
    check("the photos go in by id, in order",
          body["images"] == [{"id": 3}, {"id": 4}], str(body.get("images")))
    check("the categories go in by id",
          body["categories"] == [{"id": 7}, {"id": 8}],
          str(body.get("categories")))
    check("the tags go in by name",
          body["tags"] == [{"name": "hockey"}, {"name": "o-pee-chee"}],
          str(body.get("tags")))
    check("the SEO fields travel as meta",
          any(entry["key"] == "rank_math_title" for entry in body["meta_data"]),
          str(body.get("meta_data")))

    plan_notes = woo_create.plan([row(2, **{"Regular price": ""})],
                                 [Path(tmp) / "output"])
    check("a product with no price is noted, not refused",
          any("no price" in problem["why"] for problem in plan_notes["problems"]),
          str(plan_notes["problems"]))
    check("and it is still in the plan",
          len(plan_notes["items"]) == 1, str(plan_notes["items"]))
    broken = woo_create.plan([row(3, **{"Name": ""})], [Path(tmp) / "output"])
    check("a row with no name is refused instead of created blank",
          broken["items"] == [] and "no Name" in broken["problems"][0]["why"],
          str(broken))


def test_creation():
    print()
    print("== 3. creating: drafts first, read back, never twice ==")
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1), row(2)])
    site = FakeSite(categories={"Sports Card": 11, "Hockey Card": 12})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="abcd efgh",
                            publish=False, opener=site)
    check("both products are created", len(report["created"]) == 2, str(report))
    check("nothing failed", report["failed"] == [], str(report["failed"]))
    check("each one is a draft", all(
        entry["status"] == "draft" for entry in report["created"]),
        str(report["created"]))
    check("the photos were uploaded before the product was made",
          len(site.uploads) == 2, str(site.uploads))
    created_calls = [call for call in site.calls
                     if call["method"] == "POST" and "/products" in call["url"]
                     and "categories" not in call["url"]]
    check("the product body carried the uploaded photo ids",
          created_calls and created_calls[0]["body"]["images"],
          str(created_calls[:1]))
    check("and the category ids the site already had",
          created_calls[0]["body"]["categories"] == [{"id": 11}, {"id": 12}],
          str(created_calls[0]["body"].get("categories")))
    check("the SKU is looked for before anything is created",
          site.calls[0]["method"] == "GET" and "sku=" in site.calls[0]["url"],
          str(site.calls[:1]))
    check("nothing was published, because publishing was not asked for",
          not any(call["method"] == "PUT" and "/products/" in call["url"]
                  for call in site.calls), str(site.calls))
    pairs = [(call["id"], call["post"]) for call in site.attach_calls]
    check("each uploaded photo is filed under the product it was made for",
          [post for _attachment, post in pairs] ==
          [entry["id"] for entry in report["created"]], str(pairs))
    check("and the photo it names is the one the product carries",
          [attachment for attachment, _post in pairs] ==
          [call["body"]["images"][0]["id"] for call in created_calls],
          str(pairs))
    lines = woo_create.report_text(report, "https://shop.example")
    check("the report says how many were created",
          "2 products created on https://shop.example." in lines, str(lines))
    check("and that they are drafts, waiting",
          any("left as a draft" in line for line in lines), str(lines))

    # ---- running the same batch again must not make twins
    again = FakeSite(categories={"Sports Card": 11, "Hockey Card": 12},
                     exist=[("OPC1971-001-PR-2", 501),
                            ("OPC1971-002-PR-2", 502)])
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw",
                            publish=False, opener=again)
    check("a product already on the website is skipped, not created twice",
          len(report["skipped"]) == 2 and not report["created"],
          str(report))
    check("and it is not touched at all",
          not any(call["method"] == "POST" for call in again.calls),
          str(again.calls))
    check("the report says it was already there",
          any("Already there" in line for line in
              woo_create.report_text(report)), str(report))


def test_progress_stages():
    """Every part of the work says where it is, not just the card count.

    Creating a batch is four different jobs per card - upload the photos,
    make the draft, read it back, file the photos under it - plus putting it
    on sale afterwards. A bar that only hears "card 3 of 9" cannot say which
    of those is running, which is what the person watching wants to know.
    """
    print()
    print("== 3b. the progress reports name each part of the work ==")
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1)])
    site = FakeSite(categories={"Sports Card": 11, "Hockey Card": 12})
    events = []
    woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                   username="owner", app_password="abcd efgh", publish=True,
                   opener=site, on_item=events.append)
    stages = [event["stage"] for event in events]
    check("the photos, the draft, the filing and the sale are each reported",
          all(stage in stages for stage in
              ("start", "photos", "create", "attach", "done", "publish")),
          str(stages))
    check("every event carries the card, its place, and the total",
          all(event["index"] == 1 and event["total"] == 1 and
              event["item"]["name"] for event in events), str(events[:1]))
    check("the stages arrive in the order they happen",
          stages.index("photos") < stages.index("create") <
          stages.index("attach") < stages.index("done") <
          stages.index("publish"), str(stages))


def test_attaching():
    print()
    print("== 3c. the media library is told which product owns each photo ==")
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1)])
    site = FakeSite(categories={"Sports Card": 11, "Hockey Card": 12})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw",
                            publish=False, opener=site)
    entry = report["created"][0]
    check("the upload is given the product as its parent",
          site.attach_calls == [{"id": 901, "post": 902}],
          str(site.attach_calls))
    check("and the run counts it attached", entry.get("attached") == 1 and
          not entry.get("unattached"), str(entry))
    check("nothing is said about unattached photos when there are none",
          not any("unattached" in line
                  for line in woo_create.report_text(report)),
          str(woo_create.report_text(report)))

    #  A site that will not file the photo has still made a finished product.
    #  Saying otherwise would send someone chasing a card that is already on
    #  the website.
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1)])
    site = FakeSite(categories={"Sports Card": 11, "Hockey Card": 12},
                    refuse={("PUT", "wp/v2/media"): 403})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw",
                            publish=False, opener=site)
    entry = report["created"][0]
    check("a refused attachment does not fail the product",
          len(report["created"]) == 1 and report["failed"] == [],
          str(report))
    check("it is counted instead", entry.get("unattached") == 1, str(entry))
    lines = woo_create.report_text(report)
    check("the report says they are still marked unattached",
          any("marked unattached" in line for line in lines), str(lines))
    check("and that the product shows them anyway",
          any("show them anyway" in line for line in lines), str(lines))
    check("with the site's own reason, not a guess",
          "HTTP 403" in str(entry.get("attach_why")), str(entry))

    #  No Application Password means no upload at all, so there is no
    #  attachment to file and no attachment request to make.
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1)])
    site = FakeSite(categories={"Sports Card": 11, "Hockey Card": 12})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            publish=False, opener=site)
    check("with no password nothing is uploaded, so nothing is attached",
          site.attach_calls == [] and not site.uploads,
          str(site.attach_calls))


def test_publishing():
    print()
    print("== 4. publishing is a second step, and only for complete products ==")
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1), row(2)])
    site = FakeSite(categories={"Sports Card": 11, "Hockey Card": 12})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw",
                            publish=True, opener=site)
    check("both are published after they are created",
          len(report["published"]) == 2, str(report))
    puts = [call for call in site.calls
            if call["method"] == "PUT" and "/products/" in call["url"]]
    check("publishing is one PUT per product, with only the status",
          len(puts) == 2 and all(call["body"] == {"status": "publish"}
                                 for call in puts), str(puts))
    check("the report says they are on sale",
          any("put on sale" in line for line in
              woo_create.report_text(report)), str(report))

    # ---- a product whose photos could not be made stays a draft
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1)])
    site = FakeSite(categories={"Sports Card": 11, "Hockey Card": 12})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="", app_password="", publish=True,
                            opener=site)
    check("without the Application Password the product is still created",
          len(report["created"]) == 1, str(report))
    check("but it is never published without its photos",
          report["published"] == [], str(report))
    check("and the report says why it was kept back",
          any("kept as a draft because the photos" in line for line in
              woo_create.report_text(report)), str(report))

    # ---- a site that returns a draft anyway is a failure, not a success
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1)])
    site = FakeSite(categories={"Sports Card": 11, "Hockey Card": 12},
                    publish_status="draft")
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw",
                            publish=True, opener=site)
    check("a product the site kept as a draft is not called published",
          report["published"] == [] and report["failed"], str(report))
    check("and the reason is the site's own answer",
          "still reports the product" in report["failed"][0]["why"],
          str(report["failed"]))


def test_refusals():
    print()
    print("== 5. one card failing never stops the rest, and keys abort ==")
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1), row(2), row(3)])
    site = FakeSite(categories={"Sports Card": 11, "Hockey Card": 12},
                    refuse={("POST", "products?"): 400})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw",
                            opener=site)
    check("every card was attempted", len(report["failed"]) == 3, str(report))
    check("the site's refusal is in the report",
          all(entry["why"] for entry in report["failed"]), str(report))

    #  A photo that is not on disk stops that card only.
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1), row(2)], images=False)
    site = FakeSite(categories={"Sports Card": 11, "Hockey Card": 12})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw", opener=site)
    check("a missing photo fails that card, not the batch",
          len(report["failed"]) == 2 and "not in" in report["failed"][0]["why"],
          str(report["failed"]))
    check("and nothing was created for it",
          report["created"] == [], str(report["created"]))

    #  Wrong keys stop the run at the first card instead of 39 times over.
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1), row(2), row(3)])
    site = FakeSite(categories={"Sports Card": 11, "Hockey Card": 12},
                    refuse={("GET", "products"): 401})
    report = woo_create.run(planned, "https://shop.example", "ck_bad", "cs_bad",
                            username="owner", app_password="pw", opener=site)
    check("a refused key pair stops the run at once", len(report["failed"]) == 3,
          str(report))
    check("the first says what the site said",
          "401" in report["failed"][0]["why"], str(report["failed"][0]))
    check("the rest say they were not attempted",
          "not attempted" in report["failed"][1]["why"],
          str(report["failed"][1]))
    check("and only one request was made for the whole batch",
          len([call for call in site.calls if call["method"] == "GET"]) == 1,
          str(site.calls))


def test_categories_and_help():
    print()
    print("== 6. categories are made when missing, and the help is exact ==")
    site = FakeSite()
    ids = woo_create.category_ids("https://shop.example", "ck_a", "cs_b",
                                  ["Sports Card", "Hockey Card"], opener=site)
    check("a missing category is created, child under parent",
          ids == [41, 42], str(ids))
    posts = [call for call in site.calls if call["method"] == "POST"]
    check("the parent is created first",
          posts[0]["body"] == {"name": "Sports Card"}, str(posts[0]["body"]))
    check("the child is created under it",
          posts[1]["body"] == {"name": "Hockey Card", "parent": 41},
          str(posts[1]["body"]))
    already = FakeSite(categories={"Sports Card": 11})
    ids = woo_create.category_ids("https://shop.example", "ck_a", "cs_b",
                                  ["Sports Card"], opener=already)
    check("a category the site already has is reused",
          ids == [11] and not any(call["method"] == "POST"
                                  for call in already.calls), str(already.calls))

    hint = woo_create.keys_missing_hint("C:/app/woo-keys.txt")
    check("the key help names the file", "C:/app/woo-keys.txt" in hint, hint)
    check("and says which line is which",
          all(word in hint for word in ("line 1", "line 2", "line 3",
                                        "line 4", "line 5")), hint)
    check("and says the keys need Read/Write", "Read/Write" in hint, hint)
    check("and that photos need the Application Password",
          "Application Password" in hint, hint)

    check("a batch with nothing in it says so",
          woo_create.summary({"items": []}) == "Nothing to create.", "")
    planned = {"items": [{"name": "A card", "sku": "S1", "price": "9",
                          "stock": 1, "images": ["a.webp"],
                          "categories": [], "tags": [], "attributes": [],
                          "meta": {}, "missing_images": []}]}
    check("the confirmation names the site and the photos",
          woo_create.summary(planned, "shop.example") ==
          "1 product would be created on shop.example, 1 with photos "
          "uploaded first.", woo_create.summary(planned, "shop.example"))
    lines = woo_create.describe(planned)
    check("the confirmation names the card, its SKU and its photo count",
          "A card" in lines[0] and "SKU S1" in lines[0] and "1 photo" in
          lines[0], str(lines))


def test_existing_products():
    """What a second run finds: live products, and the drafts it left behind."""
    print()
    print("== 3b. a product already there is reported by its state ==")
    rows = [row(1), row(2)]
    exist = [("OPC1971-001-PR-2", 701), ("OPC1971-002-PR-2", 702)]

    with tempfile.TemporaryDirectory() as td:
        site = FakeSite(exist=exist, existing={
            "OPC1971-001-PR-2": {"status": "publish",
                                 "images": [{"id": 1}, {"id": 2}]},
            "OPC1971-002-PR-2": {"status": "draft",
                                 "images": [{"id": 3}, {"id": 4}]}})
        read, planned = build(Path(td), rows)
        report = woo_create.run(planned, "https://shop.example", "ck_a",
                                "cs_b", publish=False, opener=site)
    puts = [c for c in site.calls if c["method"] == "PUT"]
    text = "\n".join(woo_create.report_text(report, "https://shop.example"))
    check("a live product is left completely alone", puts == [], str(puts))
    check("the report says it is live",
          "Already there: 1971-72 O-Pee-Chee Test Card #001 (PR) "
          "(product 701) - live, so nothing was changed." in text, text)
    check("and a draft is named as a draft",
          "a draft, and publishing this batch was not asked for" in text, text)
    check("nothing is called created when nothing was", "created on" not in
          text, text)

    with tempfile.TemporaryDirectory() as td:
        site = FakeSite(exist=exist, existing={
            "OPC1971-001-PR-2": {"status": "publish",
                                 "images": [{"id": 1}, {"id": 2}]},
            "OPC1971-002-PR-2": {"status": "draft",
                                 "images": [{"id": 3}, {"id": 4}]}})
        read, planned = build(Path(td), rows)
        report = woo_create.run(planned, "https://shop.example", "ck_a",
                                "cs_b", publish=True, opener=site)
    puts = [c for c in site.calls if c["method"] == "PUT"]
    text = "\n".join(woo_create.report_text(report, "https://shop.example"))
    check("a batch asked to publish finishes the draft it left behind",
          len(puts) == 1 and "/products/702" in puts[0]["url"], str(puts))
    check("and says so, apart from the new products",
          "1 already on the website as a draft was put on sale too." in text,
          text)
    check("the live one is still not touched", all("701" not in c["url"]
                                                   for c in puts), str(puts))
    check("it is not counted as a product created",
          "created on" not in text, text)

    with tempfile.TemporaryDirectory() as td:
        #  A draft with no photos is a product nobody finished: publishing it
        #  would put a card on sale with an empty gallery.
        site = FakeSite(exist=[("OPC1971-001-PR-2", 701)], existing={
            "OPC1971-001-PR-2": {"status": "draft", "images": []}})
        read, planned = build(Path(td), [row(1)])
        report = woo_create.run(planned, "https://shop.example", "ck_a",
                                "cs_b", publish=True, opener=site)
    puts = [c for c in site.calls if c["method"] == "PUT"]
    text = "\n".join(woo_create.report_text(report, "https://shop.example"))
    check("a draft with no photos is never published", puts == [], str(puts))
    check("and the report says what to do about it",
          "a draft with no photos - new photos are added on the website, "
          "then publish it" in text, text)


def test_error_pages():
    """A website that answers with its own error page is not an answer.

    The run this was written for: nine cards, six created, four put on sale,
    and five named "Not created" - two of which were on the site as drafts
    with their photos. A batch told that has to import the CSV to fix it would
    have made five duplicates.
    """
    print()
    print("== 8. the website's own error page is not an answer ==")
    categories = {"Sports Card": 11, "Hockey Card": 12}

    # ---- a read that hiccups once costs nothing
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1)])
    site = FakeSite(categories=categories,
                    fail_once=[("GET", "sku=OPC1971-001-PR-2")])
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw", opener=site)
    reads = [call for call in site.calls if call["method"] == "GET"
             and "sku=" in call["url"]]
    check("a read answered with an error page is simply asked again",
          len(reads) == 2 and len(report["created"]) == 1,
          "%s %s" % (len(reads), report))
    check("and the batch does not have to apologise for it",
          report["failed"] == [], str(report["failed"]))

    # ---- every read failing: the card is unconfirmed, never called missing
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1)])
    site = FakeSite(categories=categories,
                    refuse={("GET", "sku="): 500})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw", opener=site)
    reads = [call for call in site.calls if call["method"] == "GET"
             and "sku=" in call["url"]]
    text = "\n".join(woo_create.report_text(report, "https://shop.example"))
    check("a failing read is asked three times before the card is given up on",
          len(reads) == woo_create.SITE_RETRIES, str(len(reads)))
    check("the card is called unconfirmed, not missing",
          "Could not be confirmed" in text and "Not created" not in text,
          text)
    check("and the answer says where the real cause is",
          "PHP error log" in text and "memory limit" in text, text)
    check("and says outright that the keys are not the problem",
          "keys are not the problem" in text, text)
    check("and nothing was sent to be created", not any(
          call["method"] == "POST" for call in site.calls), str(site.calls))

    # ---- the product was written, then the site died: not a second send
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1)])
    site = FakeSite(categories=categories,
                    save_then_fail=["OPC1971-001-PR-2"])
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw", opener=site)
    posts = [call for call in site.calls if call["method"] == "POST"
             and "wp/v2/media" not in call["url"]]
    text = "\n".join(woo_create.report_text(report, "https://shop.example"))
    check("a product written before the error page is not sent twice",
          len(posts) == 1, str(len(posts)))
    check("and it is reported as created, because it is there",
          len(report["created"]) == 1 and not report["failed"],
          str(report))
    check("with the lost answer named rather than hidden",
          "answered with its own error page" in text
          and "created once" in text, text)

    # ---- a create that really did nothing says so, and says where to look
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1)])
    site = FakeSite(categories=categories, refuse={("POST", "products?"): 500})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw", opener=site)
    text = "\n".join(woo_create.report_text(report, "https://shop.example"))
    check("a card whose product is not there afterwards is called not created",
          "Not created" in text and "no product with that SKU is there" in text,
          text)
    check("and the reason is the site's error page, in plain words",
          "HTTP 500" in text, text)

    # ---- a card refused at the second step is not "not created"
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1)])
    site = FakeSite(categories=categories, refuse={("PUT", "/products/"): 500})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw", publish=True,
                            opener=site)
    text = "\n".join(woo_create.report_text(report, "https://shop.example"))
    check("a product the site would not publish is not called not created",
          "Not created" not in text and "Not on sale" in text, text)
    check("and it is named with its product id",
          "product 9" in text, text)
    check("and it is not counted among the drafts waiting to be published",
          "left as a draft" not in text, text)

    # ---- a site that keeps failing stops being asked
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(n) for n in range(1, 6)])
    site = FakeSite(categories=categories, refuse={("GET", "sku="): 500})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw", opener=site)
    attempted = [entry for entry in report["failed"]
                 if entry.get("state") != "not-attempted"]
    rest = [entry for entry in report["failed"]
            if entry.get("state") == "not-attempted"]
    check("three error pages in a row stop the run touching the site",
          len(attempted) == woo_create.SITE_BROKEN_LIMIT and len(rest) == 2,
          "%s / %s" % (len(attempted), len(rest)))
    check("the rest are named as not attempted, not as failures",
          all("not attempted" in entry["why"] for entry in rest),
          str(rest))
    text = "\n".join(woo_create.report_text(report, "https://shop.example"))
    check("and the console says Not attempted for them", "Not attempted" in
          text, text)

    # ---- the way out is one re-run, never a second copy
    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1), row(2)])
    site = FakeSite(categories=categories, refuse={("PUT", "/products/"): 500})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw", publish=True,
                            opener=site)
    pipeline_note = pipeline.creation_failure_note(report)
    text = "\n".join(woo_create.report_text(report, "https://shop.example"))
    check("a batch that half worked is finished by running it again",
          "Run the same batch again" in text, text)
    check("and it says the SKU check is what makes that safe",
          "by its SKU" in text and "Nothing is created twice" in text, text)
    check("and it warns against importing the CSV as well",
          "do not import the CSV" in text, text)

    tmp = tempfile.mkdtemp()
    read, planned = build(tmp, [row(1)])
    site = FakeSite(categories=categories, refuse={("GET", "sku="): 500})
    report = woo_create.run(planned, "https://shop.example", "ck_a", "cs_b",
                            username="owner", app_password="pw", opener=site)
    text = "\n".join(woo_create.report_text(report, "https://shop.example"))
    check("a batch that wrote nothing keeps the old CSV road open",
          "imported the old way" in text
          and "do not import the CSV" not in text, text)

    check("a broken batch is a failed step, not a finished run",
          "WooCommerce (" in (pipeline_note or ""), str(pipeline_note))
    check("and that line counts what is missing out of the batch",
          "of 2 cards" in (pipeline_note or ""), str(pipeline_note))
    check("a batch that worked has no failed step to report",
          pipeline.creation_failure_note(
              {"created": [{"sku": "S1"}], "skipped": [], "failed": []}) == "",
          "")

    check("a finished batch is told the CSV import is not needed",
          "CSV import step is not needed" in "\n".join(
              woo_create.recovery_text({"created": [{"sku": "S"}],
                                        "failed": []})), "")
    check("and nothing is said at all when there was nothing to do",
          woo_create.recovery_text({"created": [], "skipped": [],
                                    "failed": []}) == [], "")


def test_pipeline_glue(tmp):
    """The pipeline offers this instead of quietly writing a CSV.

    The batch is the only place that knows the renamed photos, so the
    creation has to happen inside the run - which means the flags have to
    carry the answers the app already collected.
    """
    print()
    print("== 7. the pipeline asks, and never falls back to the CSV silently ==")
    import argparse
    from contextlib import redirect_stdout
    from io import StringIO
    from unittest.mock import patch

    import card_pipeline

    site = "https://shop.example"
    _, planned = build(tmp, [row(1)], images=True)
    csv_path = str(Path(tmp) / "woocommerce_products"
                   / "woocommerce_import_20260101_120000.csv")

    def run_help():
        import subprocess
        return subprocess.run(
            [sys.executable, str(APP / "pipeline" / "card_pipeline.py"),
             "listing", "--help"], capture_output=True, text=True,
            timeout=120).stdout

    def args(**changes):
        base = dict(create_products=False, no_create_products=False,
                    publish_products=False, draft_products=False,
                    confirmed=False, yes=False)
        base.update(changes)
        return argparse.Namespace(**base)

    def glue(argv, keys=("", "", ""), typed="", failure=False):
        """Run the pipeline's offer; return (created?, output, run calls)."""
        calls = []

        def fake_run(plan_result, site_url, key, secret, username="",
                     app_password="", publish=False, timeout=60, opener=None,
                     on_item=None):
            calls.append({"publish": publish, "username": username,
                          "app_password": app_password, "items":
                          len(plan_result["items"])})
            #  The real run reports every part of every card. Two events are
            #  enough: the start (which is also the console line a person
            #  reads) and a stage after it.
            if callable(on_item):
                for stage in ("start", "photos"):
                    on_item({"index": 1, "total": len(plan_result["items"]),
                             "item": plan_result["items"][0],
                             "stage": stage})
            entry = {"name": plan_result["items"][0]["name"],
                     "sku": plan_result["items"][0]["sku"], "step": "create",
                     "id": 900, "status": "draft", "images": 1}
            if publish:
                entry["status"] = "publish"
            failed = []
            if failure:
                #  The site wrote the product, then answered with its own
                #  error page on the second step: exactly the run this section
                #  was added for.
                failed = [{"name": entry["name"], "sku": entry["sku"],
                           "step": "create", "id": 900, "status": 500,
                           "state": "created-not-live",
                           "why": "created, but not published: The website "
                                  "answered with its own error page (HTTP "
                                  "500) instead of a result.",
                           "hint": "Run the batch again once the site is "
                                   "fixed."}]
            return {"created": [entry], "skipped": [], "failed": failed,
                    "published": [entry] if publish and not failure else [],
                    "unpublished": [] if publish and not failure else [entry]}

        answers = iter((typed or "n\n").splitlines() or [""])
        prompts = []

        def fake_input(prompt="", *a, **k):
            prompts.append(prompt)
            return next(answers, "")
        out = StringIO()
        with patch.object(card_pipeline, "read_woo_credentials",
                          lambda *a, **k: keys), \
                patch.object(card_pipeline, "read_wordpress_credentials",
                             lambda *a, **k: (site, "owner", "app pass")), \
                patch.object(card_pipeline.woo_create, "run", fake_run), \
                patch("builtins.input", fake_input), \
                redirect_stdout(out):
            created, _note = card_pipeline.maybe_create_woocommerce_products(
                argv, csv_path)
        return created, out.getvalue(), calls, prompts

    check("every column it reads is a column the pipeline writes",
          [name for name in woo_create.COLUMNS
           if name not in card_pipeline.FIELDNAMES] == [],
          str([name for name in woo_create.COLUMNS
               if name not in card_pipeline.FIELDNAMES]))
    prompt = run_help()
    check("the pipeline's own help offers creating the products",
          "--create-products" in prompt and "--publish-products" in prompt
          and "--confirmed" in prompt, prompt[:200])

    created, output, calls, prompts = glue(args())
    check("with no keys the pipeline says so, and names the file to fill",
          created is False and "not created" in output and
          "woo-keys.txt" in output, output[-300:])
    check("and points at the CSV that is still ready", csv_path in output,
          output[-300:])
    check("and nothing was written to the website", not calls, str(calls))

    created, output, calls, prompts = glue(args(no_create_products=True))
    check("--no-create-products is silent and creates nothing",
          created is False and not calls and "woo-keys" not in output,
          output[-200:])

    created, output, calls, prompts = glue(
        args(create_products=True, draft_products=True, confirmed=True),
        keys=(site, "ck_a", "cs_b"))
    check("the app's answer is obeyed: drafts only", created is True and
          calls and calls[0]["publish"] is False, str(calls))
    check("the WordPress username reaches the photo upload",
          calls and calls[0]["username"] == "owner", str(calls))
    check("the console shows the finished report", "created on" in output,
          output[-300:])
    check("and says the CSV is not needed for those products",
          "CSV import step is not needed" in output, output[-300:])
    check("the report was saved beside the CSV",
          "woo-create-result.json" in output, output[-300:])

    created, output, calls, prompts = glue(
        args(create_products=True, publish_products=True, confirmed=True),
        keys=(site, "ck_a", "cs_b"))
    check("publishing was chosen for the whole batch", created is True and
          calls and calls[0]["publish"] is True, str(calls))

    created, output, calls, prompts = glue(args(), keys=(site, "ck_a", "cs_b"),
                                  typed="n")
    check("without --confirmed the console still asks, and 'n' stops it",
          created is False and not calls and "Nothing was created" in output,
          output[-300:] + str(calls))

    created, output, calls, prompts = glue(args(), keys=(site, "ck_a", "cs_b"),
                                  typed="y\nn")
    check("and 'y' creates them, then asks about putting them on sale",
          created is True and calls and calls[0]["publish"] is False,
          str(calls))
    check("the publish question was the second one asked",
          len(prompts) == 2 and "on sale" in prompts[1], str(prompts))

    created, output, calls, prompts = glue(args(), keys=(site, "ck_a", "cs_b"),
                                  typed="y\ny")
    check("answering yes there publishes the complete products",
          created is True and calls and calls[0]["publish"] is True,
          str(calls))

    #  The bar above the app's console is fed by a marker the pipeline writes
    #  only when the app started the run. A person running card_pipeline.py in
    #  a terminal reads the plain "[1/1] Card" line and never sees a marker.
    with patch.dict(os.environ, {"ALEX_COLLECT_NESTED": "1"}):
        created, output, calls, prompts = glue(
            args(create_products=True, publish_products=True, confirmed=True),
            keys=(site, "ck_a", "cs_b"))
    marker = "\x1eALEX_COLLECT_PROGRESS:"
    events = []
    for piece in output.split(marker)[1:]:
        body = piece.split("\x1f", 1)[0]
        events.append(json.loads(body))
    check("the app is told how far the creation has got",
          [event["stage"] for event in events] ==
          ["start", "photos", "finish"] and
          all(event["index"] == 1 and event["total"] == 1
              for event in events), str(events))
    check("a marker carries the card's name, not its whole plan",
          events[0]["item"] == {"name": planned["items"][0]["name"]} and
          events[1]["item"] == {"name": planned["items"][0]["name"]},
          str(events[:2]))

    #  The creation step is over when the products are, and the batch runs on
    #  into CanadianShopper, eBay and Facebook afterwards. The last statement
    #  the pipeline makes about this step is that it is finished; without it
    #  the app's bar sat at the last card for the rest of the run.
    check("the creation step says when it is over",
          events and events[-1]["stage"] == "finish", str(events[-3:]))
    check("and the console still reads as sentences and counts",
          "  [1/1] " in output, output[:200])
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ALEX_COLLECT_NESTED", None)
        created, plain_output, calls, prompts = glue(
            args(create_products=True, publish_products=True, confirmed=True),
            keys=(site, "ck_a", "cs_b"))
    check("a run started by hand gets no markers at all",
          marker not in plain_output and "[1/1]" in plain_output,
          plain_output[-300:])

    created, output, calls, prompts = glue(
        args(create_products=True, publish_products=True, confirmed=True),
        keys=(site, "ck_a", "cs_b"), failure=True)
    #  "1 of 9 cards is not on the website" only says a card is missing. The
    #  note now names it and gives the site's own short reason, because the
    #  alternative is scanning hundreds of console lines for which one.
    note = card_pipeline.creation_failure_note({
        "created": [{"name": "A card", "sku": "A1"}],
        "skipped": [], "published": [], "unpublished": [],
        "failed": [{"name": "1972-73 O-Pee-Chee Mike Corrigan #48 Dark Back",
                    "sku": "S9", "state": "not-created",
                    "why": "The website answered with its own error page "
                           "(HTTP 500) instead of a result."}]})
    check("the failed card is named, with the site's reason",
          "Mike Corrigan" in note and "HTTP 500" in note, note)
    check("and the count is still there", "1 of 2" in note, note)
    many = card_pipeline.creation_failure_note({
        "created": [], "skipped": [], "published": [], "unpublished": [],
        "failed": [{"name": "Card %d" % index, "sku": "S%d" % index,
                    "state": "not-created", "why": "refused"}
                   for index in range(1, 5)]})
    check("a long list says how many were left out",
          "Card 1" in many and "Card 2" in many and "Card 3" not in many and
          "and 2 more" in many, many)

    check("a batch the site broke names the button that finishes it",
          "Re-run a marketplace" in output and "WooCommerce CSV" in output,
          output[-500:])
    check("and never offers the CSV import over cards that already exist",
          "imported the old way" not in output and
          "do not import the CSV" in output, output[-500:])


def main():
    test_reading()
    test_payload()
    test_creation()
    test_progress_stages()
    test_attaching()
    test_publishing()
    test_existing_products()
    test_refusals()
    test_categories_and_help()
    test_error_pages()
    with tempfile.TemporaryDirectory() as td:
        test_pipeline_glue(Path(td))
    print()
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        return 1
    print("ALL WOO CREATE CHECKS PASSED (%d)" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
