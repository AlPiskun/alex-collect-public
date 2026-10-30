#!/usr/bin/env python3
"""Create the pipeline's products on the website itself, instead of a CSV.

The card pipeline ends by writing ``woocommerce_import_<time>.csv`` for a
manual WP All Import. The site's own REST API can take the same rows, one
product at a time, and read every one back - so a batch does not have to stop
at a file.

The rules this module keeps, in the same spirit as the stock writer:

  * a product is created as an **unpublished draft** first, and only published
    by a second, separate call - so a half-finished batch is never live;
  * every product is looked for by SKU before it is created, because running
    the same batch twice must not make two of everything;
  * the answer is read back: an id that does not come back, or a SKU the site
    did not store, is a failure rather than a success;
  * one card failing never stops the rest, and the report says exactly which
    landed and which did not, with the site's own reason.

Photos are uploaded with the WordPress Application Password (the WooCommerce
consumer keys cannot reach the media library), so a product whose photos
could not be uploaded is created as a draft and **not** published - it is left
for the person to see, not published half-dressed.

Nothing here prints, logs or raises with a key or password in the text.
"""
from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import woo_media

PRODUCTS_PATH = "/wp-json/wc/v3/products"
CATEGORIES_PATH = "/wp-json/wc/v3/products/categories"
USER_AGENT = "AlexCollect/2.90"

#  A read is safe to repeat, so a site answering with its own error page gets
#  asked again before a card is called missing: two of the three failures in
#  the run this was written for were single reads of the product list.
SITE_RETRIES = 3
SITE_RETRY_PAUSE = 1.5

#  How many answers in a row may be the site's own error page before the run
#  stops touching it.
SITE_BROKEN_LIMIT = 3

#  The columns the pipeline writes. Anything else in the file is ignored - the
#  CSV is a contract this module reads, not a schema it owns.
COLUMNS = ("SKU", "Name", "Published", "Visibility in catalog",
           "Short description", "Description", "In stock?", "Stock",
           "Regular price", "Categories", "Tags", "Images",
           "Attribute 1 name", "Attribute 1 value(s)", "Attribute 1 visible",
           "Attribute 1 global", "rank_math_title", "rank_math_description",
           "rank_math_focus_keyword")


class ProductError(Exception):
    """A product could not be created, with a sentence saying why.

    ``status`` is the site's HTTP status when it answered at all; ``hint`` is
    what the person can do about it and is empty when there is nothing to do.
    ``state`` says how much is known about the product: "unknown" when the
    website answered with its own error page, so neither "created" nor "not
    created" can be said without guessing.
    """

    def __init__(self, message, hint="", status=0, state=""):
        super().__init__(message)
        self.message = str(message)
        self.hint = str(hint or "")
        self.status = int(status or 0)
        self.state = str(state or "")


# ------------------------------------------------------------------ reading

def read_rows(path):
    """The CSV's rows, as dicts, plus the folder they came from.

    ``utf-8-sig`` because the pipeline writes a BOM for Excel; a file that
    cannot be read is an error with the file named, not an empty batch.
    """
    source = Path(str(path))
    try:
        text = source.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise ProductError("Could not read %s (%s)." % (source.name, exc),
                           "Check the file is still in the batch folder.")
    reader = csv.DictReader(text.splitlines())
    rows = [dict(row) for row in reader if any(
        str(value or "").strip() for value in row.values())]
    if not rows:
        raise ProductError("%s has no product rows." % source.name,
                           "Run the pipeline again, or choose another CSV.")
    return {"path": source, "folder": source.parent, "rows": rows,
            "columns": list(reader.fieldnames or [])}


def _text(row, key):
    return str(row.get(key) or "").strip()


def _number(row, key, default=0):
    raw = _text(row, key)
    if not raw:
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _split(value):
    """A comma-separated cell as a list, empty pieces dropped."""
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def categories_of(value):
    """``"Sports Card > Hockey Card"`` as the names, parent first."""
    return [part.strip() for part in str(value or "").split(">")
            if part.strip()]


def normalise(row):
    """One CSV row as this module works with it, and never a guess.

    A product with no name cannot be created; a product with no price can, and
    the pipeline already leaves it blank when the AI gave none, so that is a
    note rather than a stop.
    """
    row = row or {}
    name = _text(row, "Name")
    if not name:
        raise ProductError("A CSV row has no Name, so there is nothing to "
                           "create.", "Check the row in the CSV.")
    item = {
        "name": name,
        "sku": _text(row, "SKU"),
        "published": _text(row, "Published") not in ("", "0", "false", "False"),
        "short": _text(row, "Short description"),
        "description": _text(row, "Description"),
        "price": _text(row, "Regular price"),
        "stock": _number(row, "Stock", 1),
        "in_stock": _text(row, "In stock?") not in ("0", "false", "False"),
        "categories": categories_of(_text(row, "Categories")),
        "tags": _split(_text(row, "Tags")),
        "images": _split(_text(row, "Images")),
        "attributes": [],
        "meta": {},
        "row": row,
    }
    attr_name = _text(row, "Attribute 1 name")
    attr_values = _split(_text(row, "Attribute 1 value(s)"))
    if attr_name and attr_values:
        item["attributes"].append({
            "name": attr_name,
            "options": attr_values,
            "visible": _text(row, "Attribute 1 visible") not in
                       ("", "0", "false", "False"),
            "variation": False,
        })
    for column in ("rank_math_title", "rank_math_description",
                   "rank_math_focus_keyword"):
        value = _text(row, column)
        if value:
            item["meta"][column] = value
    return item


def image_folder(folders):
    """The first folder that actually holds images, or the first one given."""
    folders = [Path(str(folder)) for folder in folders if str(folder or "")]
    for folder in folders:
        if folder.is_dir() and any(folder.glob("*.webp")):
            return folder
    for folder in folders:
        if folder.is_dir():
            return folder
    return folders[0] if folders else Path(".")


def plan(rows, image_folders=()):
    """What would be created, and what is worth knowing first.

    ``missing_images`` is a note, not a refusal: the product can be created
    without its photos and finished in the media library, and the caller says
    so. The one thing that must not happen is a photo silently missing from a
    product that was published anyway - that is decided at publish time.
    """
    folder = image_folder(image_folders) if image_folders else None
    items, problems = [], []
    for index, row in enumerate(rows or [], start=1):
        try:
            item = normalise(row)
        except ProductError as exc:
            problems.append({"row": index, "why": exc.message,
                             "hint": exc.hint})
            continue
        item["missing_images"] = [name for name in item["images"]
                                  if folder is None or not
                                  (Path(folder) / name).is_file()]
        if not item["price"]:
            problems.append({
                "row": index, "why": "%s has no price." % item["name"],
                "hint": "It can be created, but the shop will show no price "
                        "until one is set."})
        items.append(item)
    return {"items": items, "problems": problems, "folder": folder}


def describe(plan_result, limit=12):
    """The confirmation: one line per product, and what is incomplete."""
    items = (plan_result or {}).get("items") or []
    lines = []
    for item in items[:limit]:
        detail = "  %s" % item["name"]
        if item["sku"]:
            detail += "\n      SKU %s" % item["sku"]
        if item["price"]:
            detail += "  |  $%s" % item["price"]
        detail += "  |  stock %d" % item["stock"]
        if item["images"]:
            detail += "  |  %d photo%s" % (
                len(item["images"]), "" if len(item["images"]) == 1 else "s")
        else:
            detail += "  |  no photo"
        lines.append(detail)
    if len(items) > limit:
        lines.append("  ... and %d more" % (len(items) - limit))
    return lines


def summary(plan_result, site=""):
    """One sentence saying what creating this batch would do."""
    items = (plan_result or {}).get("items") or []
    if not items:
        return "Nothing to create."
    photos = sum(1 for item in items if item["images"])
    line = "%d product%s would be created on %s" % (
        len(items), "" if len(items) == 1 else "s", site or "your website")
    if photos:
        line += ", %d with photos uploaded first" % photos
    return line + "."


def keys_missing_hint(path=None):
    """Exactly what to add to woo-keys.txt, in the words of the file.

    The first three lines are the WooCommerce pair the writes need; lines four
    and five are the WordPress Application Password that only photo upload
    needs. Saying which is which is the difference between a person fixing it
    in one minute and guessing.
    """
    where = str(path) if path else "woo-keys.txt"
    return ("Creating products needs the site's WooCommerce keys with "
            "Read/Write access, in %s:\n"
            "  line 1  the site address, e.g. https://your-store.example\n"
            "  line 2  the consumer key   (ck_...)\n"
            "  line 3  the consumer secret (cs_...)\n"
            "Photos also need the two optional lines:\n"
            "  line 4  your WordPress username\n"
            "  line 5  a WordPress Application Password\n"
            "WooCommerce > Settings > Advanced > REST API > Add key, with "
            "Read/Write permission." % where)


# -------------------------------------------------------------------- HTTP

def site_root(site):
    """The site address without a trailing slash, or "" when unusable."""
    value = str(site or "").strip().rstrip("/")
    if not value.lower().startswith(("http://", "https://")):
        return ""
    return value


def api_url(site, path, key, secret, params=None):
    """A REST address with the keys where hosts keep them.

    Query parameters rather than an Authorization header, for the same reason
    the stock writer and the photo wiring do it: some hosts strip that header
    before PHP sees it.
    """
    root = site_root(site)
    if not root:
        return ""
    query = {"consumer_key": key, "consumer_secret": secret}
    for name, value in (params or {}).items():
        if value not in (None, ""):
            query[name] = value
    return "%s%s?%s" % (root, path, urllib.parse.urlencode(query))


def _http(request, timeout, opener=None):
    if opener is None:
        def opener(req, timeout):
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, response.read()
    try:
        return opener(request, timeout)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        return exc.code, body
    except urllib.error.URLError as exc:
        raise ProductError("Could not reach the website (%s)." %
                           getattr(exc, "reason", exc))
    except ProductError:
        raise
    except Exception as exc:
        raise ProductError("Could not reach the website (%s)." % exc)


def _json(body):
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return {}


def _explain(status, payload, what):
    """The site's refusal, in words the person can act on."""
    said = ""
    if isinstance(payload, dict):
        said = str(payload.get("message") or "").strip()
    said = said[:300]
    if status == 401:
        return ProductError(
            "The website rejected the WooCommerce keys (HTTP 401).",
            "Creating products needs a key pair with Read/Write access; the "
            "pair in woo-keys.txt is read-only or wrong.", status)
    if status == 403:
        return ProductError(
            "Those keys are not allowed to create products (HTTP 403).",
            "Re-create the keys with Read/Write access.", status)
    if status == 400 and "sku" in said.lower():
        return ProductError("The website refused the SKU: %s" % said,
                            "A product with that SKU may already exist; "
                            "compare the batch against the website.", status)
    if status in (500, 502, 503, 504):
        #  WordPress replaces its own fatal error with one sentence and the
        #  same link for everybody, so the answer says nothing about what went
        #  wrong - and a fatal can happen after the product was written. Both
        #  facts are said, because guessing either way is how a batch ends up
        #  duplicated or reported as missing when it is on the site.
        return ProductError(
            "The website answered with its own error page (HTTP %s) instead "
            "of a result." % status,
            "The 'critical error' page is WordPress hiding the real cause; it "
            "is in the site's PHP error log, and on a batch like this it is "
            "usually the PHP memory limit or a request timeout. The keys are "
            "not the problem. This card may or may not have been written, so "
            "run the batch again - it checks each SKU first and never creates "
            "a card twice.", status, state="unknown")
    return ProductError(
        "The website refused to %s (HTTP %s)." % (what, status),
        ("WordPress said: %s" % said) if said else "", status)


def _send(url, method, payload=None, timeout=60, opener=None):
    """One call to the site, and a second try when a read came back broken.

    Only a GET is repeated: asking for a product list twice cannot change
    anything, while a POST that answered with a fatal error may already have
    been written - that one is settled by looking the SKU up afterwards, in
    ``create_product``, not by sending it again.
    """
    data = None
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    attempts = SITE_RETRIES if str(method).upper() == "GET" else 1
    for attempt in range(max(1, attempts)):
        request = urllib.request.Request(url, data=data, method=method,
                                         headers=headers)
        status, raw = _http(request, timeout, opener)
        if not 500 <= status < 600 or attempt == attempts - 1:
            return status, _json(raw)
        if SITE_RETRY_PAUSE:
            time.sleep(SITE_RETRY_PAUSE)
    return status, _json(raw)


# ---------------------------------------------------------------- the site

def find_by_sku(site, key, secret, sku, timeout=60, opener=None):
    """The product already carrying this SKU, or ``None``.

    Checked before every creation: a second run of the same batch must find
    its own products rather than make twins of them.
    """
    sku = str(sku or "").strip()
    if not sku:
        return None
    url = api_url(site, PRODUCTS_PATH, key, secret,
                  {"sku": sku, "per_page": 1})
    if not url:
        raise ProductError("No website address or keys are available.")
    status, payload = _send(url, "GET", None, timeout, opener)
    if status in (401, 403):
        raise _explain(status, payload, "read the product list")
    if status != 200:
        raise _explain(status, payload, "read the product list")
    rows = payload if isinstance(payload, list) else []
    for row in rows:
        if str(row.get("sku") or "").strip() == sku:
            return row
    return None


def category_id(site, key, secret, name, parent=0, timeout=60, opener=None,
                create=True):
    """The product category's id, created when the site does not have it."""
    name = str(name or "").strip()
    if not name:
        return 0
    params = {"search": name, "per_page": 100}
    if parent:
        params["parent"] = parent
    url = api_url(site, CATEGORIES_PATH, key, secret, params)
    status, payload = _send(url, "GET", None, timeout, opener)
    if status not in (200,):
        raise _explain(status, payload, "read the categories")
    for row in payload if isinstance(payload, list) else []:
        if str(row.get("name") or "").strip().lower() == name.lower():
            return int(row.get("id") or 0)
    if not create:
        return 0
    body = {"name": name}
    if parent:
        body["parent"] = parent
    url = api_url(site, CATEGORIES_PATH, key, secret)
    status, payload = _send(url, "POST", body, timeout, opener)
    if status not in (200, 201):
        raise _explain(status, payload, "create the category %r" % name)
    return int((payload or {}).get("id") or 0)


def category_ids(site, key, secret, names, timeout=60, opener=None):
    """``[id, ...]`` for a ``["Parent", "Child"]`` path, innermost last.

    The pipeline writes ``"Sports Card > Hockey Card"``, which is a parent and
    its child; creating the child under the parent keeps the shop's own menu
    shape instead of dumping everything at the top level.
    """
    ids, parent = [], 0
    for name in names or []:
        found = category_id(site, key, secret, name, parent=parent,
                            timeout=timeout, opener=opener)
        if not found:
            continue
        ids.append(found)
        parent = found
    return ids


def build_payload(item, image_ids=(), category_ids_=()):
    """The product body for one item, with only the fields we know."""
    payload = {
        "name": item["name"],
        "type": "simple",
        #  Always a draft: publishing is its own step, after the photos are on.
        "status": "draft",
        "short_description": item["short"],
        "description": item["description"],
        "manage_stock": True,
        "stock_quantity": int(item["stock"]),
        "stock_status": "instock" if item["in_stock"] else "outofstock",
    }
    if item["sku"]:
        payload["sku"] = item["sku"]
    if item["price"]:
        payload["regular_price"] = str(item["price"])
    if item["attributes"]:
        payload["attributes"] = [dict(attr) for attr in item["attributes"]]
    if item["tags"]:
        payload["tags"] = [{"name": tag} for tag in item["tags"]]
    if category_ids_:
        payload["categories"] = [{"id": int(value)} for value in category_ids_]
    if image_ids:
        payload["images"] = [{"id": int(value)} for value in image_ids]
    if item.get("meta"):
        payload["meta_data"] = [{"key": key, "value": value}
                                for key, value in item["meta"].items()]
    return payload


def create_product(site, key, secret, payload, timeout=60, opener=None):
    """Create one draft product and confirm the site kept it."""
    url = api_url(site, PRODUCTS_PATH, key, secret)
    if not url:
        raise ProductError("No website address or keys are available.",
                           keys_missing_hint())
    status, answer = _send(url, "POST", payload, timeout, opener)
    if 500 <= status < 600:
        #  A fatal error can happen *after* WordPress has written the product -
        #  the row is saved, then the response dies. Sending it again would make
        #  a twin, so the SKU decides: if the product is there, it was created;
        #  if the list reads cleanly and it is not, it was not.
        sku = str(payload.get("sku") or "")
        try:
            found = find_by_sku(site, key, secret, sku, timeout=timeout,
                                opener=opener)
        except ProductError:
            found = None
            known_empty = False
        else:
            known_empty = bool(sku)
        if found is not None:
            recovered = dict(found)
            recovered["_recovered"] = True
            return recovered
        if known_empty:
            raise ProductError(
                "The website answered with its own error page (HTTP %s) when "
                "this card was sent, and no product with that SKU is there "
                "afterwards, so it was not created." % status,
                "The 'critical error' page hides the real cause - it is in "
                "the site's PHP error log, and is usually the PHP memory "
                "limit or a request timeout. The keys are not the problem. "
                "Run the batch again once the site is fixed.", status,
                state="not-created")
    if status not in (200, 201):
        raise _explain(status, answer, "create %r" % payload.get("name"))
    if not isinstance(answer, dict) or not answer.get("id"):
        raise ProductError(
            "The website accepted the product but sent no id back, so it "
            "cannot be confirmed.", "Check Products on the website before "
            "running this batch again.")
    if str(answer.get("sku") or "").strip() != str(payload.get("sku") or ""):
        if payload.get("sku"):
            raise ProductError(
                "The website stored a different SKU (%r) than the one sent "
                "(%r)." % (answer.get("sku"), payload.get("sku")),
                "Check the product on the website.")
    return answer


def publish_product(site, key, secret, product_id, timeout=60, opener=None,
                    retries=2):
    """Put a draft on sale, and confirm the site says it is published."""
    url = api_url(site, "%s/%s" % (PRODUCTS_PATH, product_id), key, secret)
    if not url:
        raise ProductError("No website address or keys are available.")
    last = None
    for _attempt in range(max(1, retries)):
        status, answer = _send(url, "PUT", {"status": "publish"}, timeout,
                               opener)
        if status in (200, 201):
            if str((answer or {}).get("status") or "") != "publish":
                raise ProductError(
                    "The website accepted the change but still reports the "
                    "product as %r." % (answer or {}).get("status"),
                    "Publish it from the website's product list.")
            return answer
        last = _explain(status, answer, "publish the product")
        if status and status < 500:
            break
    raise last or ProductError("The website did not publish the product.")


def upload_photos(site, username, app_password, item, folder, timeout=60,
                  opener=None):
    """Upload the item's photos and return their attachment ids, in order.

    A photo that cannot be uploaded is a ProductError naming the file: the
    product stays a draft, because a live product with a missing front photo
    is worse than an unpublished one.
    """
    ids = []
    for name in item.get("images") or []:
        path = Path(str(folder)) / name
        if not path.is_file():
            raise ProductError("The photo %s is not in %s." % (name, folder),
                               "Re-run the image step, or create this batch "
                               "from the CSV as before.")
        try:
            attachment = woo_media.upload_media(
                site, username, app_password, path,
                title=item["name"], timeout=timeout, opener=opener)
        except woo_media.MediaError as exc:
            raise ProductError("The photo %s could not be uploaded. %s"
                               % (name, exc.message),
                               "Creating products needs the WordPress "
                               "username and Application Password (lines 4 "
                               "and 5 of woo-keys.txt).", exc.status)
        ids.append(int(attachment["id"]))
    return ids


def run(plan_result, site, key, secret, username="", app_password="",
        publish=False, timeout=60, opener=None, on_item=None):
    """Create every item; then publish the ones that are complete.

    Order matters and is the whole safety story: photos are uploaded first, the
    product is created as a draft, and only a product whose photos all landed
    is published. Anything else stays a draft and is named in the report.
    """
    items = (plan_result or {}).get("items") or []
    folder = (plan_result or {}).get("folder")
    created, skipped, failed, published = [], [], [], []
    #  A site that answers error page after error page is not going to start
    #  working halfway through the batch, and every further request is another
    #  chance of half-written products. Three in a row and the run stops,
    #  naming what it did not attempt.
    streak = [0]

    def site_failing(exc):
        status = int(getattr(exc, "status", 0) or 0)
        streak[0] = streak[0] + 1 if 500 <= status < 600 else 0
        return streak[0] >= SITE_BROKEN_LIMIT

    def not_attempted(start, why):
        for rest in items[start:]:
            failed.append({"name": rest["name"], "sku": rest["sku"],
                           "step": "create", "why": why, "hint": "",
                           "state": "not-attempted"})

    for index, item in enumerate(items, start=1):
        entry = {"name": item["name"], "sku": item["sku"], "step": "create"}
        if callable(on_item):
            try:
                on_item({"index": index, "total": len(items), "item": item,
                         "stage": "start"})
            except Exception:
                pass
        try:
            existing = find_by_sku(site, key, secret, item["sku"],
                                   timeout=timeout, opener=opener)
            if existing is not None:
                entry.update({"id": existing.get("id"),
                              "why": "already on the website",
                              "status": existing.get("status") or "",
                              "images": len(existing.get("images") or []),
                              "link": existing.get("permalink") or ""})
                skipped.append(entry)
                #  A batch that stopped half way leaves products behind as
                #  drafts. Skipping them is right - they are not created
                #  twice - but a batch asked to publish must not leave half
                #  of its cards unpublished and call itself finished, so an
                #  existing draft that already has photos is finished here.
                if publish and entry["status"] == "draft" and entry["images"]:
                    try:
                        publish_product(site, key, secret, entry["id"],
                                        timeout=timeout, opener=opener)
                        entry["status"] = "publish"
                        entry["why"] = "already on the website as a draft"
                        published.append(entry)
                        streak[0] = 0
                    except ProductError as exc:
                        entry["why"] = ("already on the website as a draft, "
                                        "but publishing it failed: %s"
                                        % exc.message)
                        entry["hint"] = exc.hint
                        entry["state"] = "created-not-live"
                        failed.append(entry)
                        if site_failing(exc):
                            not_attempted(index,
                                          "not attempted: the website kept "
                                          "answering with its own error page")
                            break
                else:
                    streak[0] = 0
                continue
            image_ids = []
            if item["images"] and username and app_password:
                image_ids = upload_photos(site, username, app_password, item,
                                          folder, timeout=timeout,
                                          opener=opener)
            elif item["images"]:
                entry["no_photos"] = True
            category_ids_ = category_ids(site, key, secret, item["categories"],
                                         timeout=timeout, opener=opener)
            payload = build_payload(item, image_ids, category_ids_)
            answer = create_product(site, key, secret, payload,
                                    timeout=timeout, opener=opener)
            entry.update({"id": answer.get("id"),
                          "status": answer.get("status") or "draft",
                          "images": len(image_ids),
                          "link": answer.get("permalink") or ""})
            if image_ids and entry.get("id"):
                #  A photo uploaded on its own has no parent, and WordPress
                #  files every parentless image under "Unattached" in the
                #  media library - which reads as "the pictures were lost"
                #  even when the product shows them. The parent is set once
                #  the product exists, and a refusal here changes nothing
                #  about the product that was just made.
                attached = woo_media.attach_media(
                    site, username, app_password, image_ids, entry["id"],
                    timeout=timeout, opener=opener)
                entry["attached"] = len(attached["attached"])
                if attached["failed"]:
                    entry["unattached"] = len(attached["failed"])
                    entry["attach_why"] = (attached["failed"][0].get("why")
                                           or "")
            if answer.get("_recovered"):
                entry["recovered"] = True
            created.append(entry)
            streak[0] = 0
        except ProductError as exc:
            entry.update({"why": exc.message, "hint": exc.hint,
                          "status": exc.status,
                          "state": exc.state or "not-created"})
            failed.append(entry)
            if callable(on_item):
                try:
                    on_item({"index": index, "total": len(items), "item": item,
                             "stage": "done"})
                except Exception:
                    pass
            if exc.status in (401, 403):
                #  The keys are wrong, so the next card would fail the same
                #  way. Stop here and name what was not attempted instead of
                #  repeating one refusal for every card in the batch.
                not_attempted(index, "not attempted: the keys were refused")
                break
            if site_failing(exc):
                not_attempted(index,
                              "not attempted: the website kept answering "
                              "with its own error page")
                break
            continue
        if callable(on_item):
            try:
                on_item({"index": index, "total": len(items), "item": item,
                         "stage": "done"})
            except Exception:
                pass
        #  Publishing is the second step, and only after everything landed.
        if publish and not entry.get("no_photos"):
            try:
                publish_product(site, key, secret, entry["id"],
                                timeout=timeout, opener=opener)
                entry["status"] = "publish"
                published.append(entry)
            except ProductError as exc:
                entry.update({"why": "created, but not published: %s"
                                     % exc.message,
                              "hint": exc.hint, "status": exc.status,
                              "state": "created-not-live"})
                failed.append(entry)
                if site_failing(exc):
                    not_attempted(index,
                                  "not attempted: the website kept answering "
                                  "with its own error page")
                    break
            else:
                streak[0] = 0
    return {"created": created, "skipped": skipped, "failed": failed,
            "published": published,
            "unpublished": [entry for entry in created
                            if entry.get("status") != "publish"]}


def report_text(report, site=""):
    """Console lines for a finished run, in the order a person reads them."""
    lines = []
    created = (report or {}).get("created") or []
    skipped = (report or {}).get("skipped") or []
    failed = (report or {}).get("failed") or []
    published = (report or {}).get("published") or []
    if created:
        lines.append("%d product%s created on %s." %
                     (len(created), "" if len(created) == 1 else "s",
                      site or "your website"))
    fresh = [entry for entry in published if entry in created]
    older = [entry for entry in published if entry not in created]
    if fresh:
        lines.append("%d of them put on sale." % len(fresh))
    if older:
        lines.append("%d already on the website as a draft %s put on sale "
                     "too." % (len(older), "was" if len(older) == 1 else
                               "were"))
    refused = {entry.get("sku") for entry in failed
               if str(entry.get("state") or "") == "created-not-live"}
    waiting = [entry for entry in created
               if str(entry.get("status") or "") != "publish"
               and entry.get("sku") not in refused]
    if waiting:
        #  Said whether or not publishing was asked for: a batch that ends in
        #  drafts must never read like a batch that ended live. A card the
        #  site refused to publish is not "waiting to be published when it is
        #  ready" - it is named below, with the site's answer.
        lines.append("%d left as a draft - publish them when they are ready."
                     % len(waiting))
    recovered = [entry for entry in created if entry.get("recovered")]
    if recovered:
        lines.append("%d product%s was written even though the website "
                     "answered with its own error page: %s found by SKU "
                     "afterwards, so %s created once."
                     % (len(recovered), "" if len(recovered) == 1 else "s",
                        "it was" if len(recovered) == 1 else "they were",
                        "it is" if len(recovered) == 1 else "they are"))
    loose = [entry for entry in created if entry.get("unattached")]
    if loose:
        #  Said once, and said calmly: the product is finished and shows every
        #  photo. What is wrong is only the label the media library puts on
        #  the files, which is what makes a finished batch look unfinished.
        why = next((entry.get("attach_why") for entry in loose
                    if entry.get("attach_why")), "")
        lines.append(
            "The photos on %d of them are in the media library but are still "
            "marked unattached there - the products show them anyway.%s"
            % (len(loose), " " + why if why else ""))
    for entry in skipped:
        #  The state is the point: an existing product that is still a draft
        #  is a card nobody can buy, and it must never be listed as though it
        #  were live.
        status = str(entry.get("status") or "")
        if entry.get("why") != "already on the website":
            detail = entry.get("why") or status or "state unknown"
        elif status == "publish":
            detail = "live, so nothing was changed"
        elif status == "draft":
            if not entry.get("images"):
                detail = ("a draft with no photos - new photos are added "
                          "on the website, then publish it")
            else:
                detail = ("a draft, and publishing this batch was not asked "
                          "for")
        else:
            detail = "state %r, left alone" % (status or "unknown")
        lines.append("Already there: %s (product %s) - %s."
                     % (entry.get("name"), entry.get("id"), detail))
    for entry in failed:
        why = str(entry.get("why") or "")
        hint = str(entry.get("hint") or "")
        state = str(entry.get("state") or "")
        if entry.get("why", "").startswith("already on the website"):
            lines.append("Not published: %s (product %s) - %s %s"
                         % (entry.get("name"), entry.get("id"), why, hint))
            continue
        if state == "created-not-live":
            #  The product is on the site; only the second step failed. Saying
            #  "not created" over a product that exists is how a batch gets
            #  imported twice, so the heading says what actually happened.
            detail = why[len("created, but not published: "):] \
                if why.startswith("created, but not published: ") else why
            lines.append("Not on sale: %s (product %s) - it was created, but "
                         "the website would not publish it: %s %s"
                         % (entry.get("name"), entry.get("id"), detail, hint))
            continue
        if state == "not-attempted":
            lines.append("Not attempted: %s - %s."
                         % (entry.get("name"), why))
            continue
        if state == "unknown":
            lines.append("Could not be confirmed: %s - %s %s"
                         % (entry.get("name"), why, hint))
            continue
        lines.append("Not created: %s - %s %s" % (entry.get("name"), why,
                                                  hint))
    no_photos = [entry for entry in created if entry.get("no_photos")]
    if no_photos:
        lines.append("%d product%s kept as a draft because the photos were "
                     "not uploaded - add the WordPress username and "
                     "Application Password (lines 4 and 5 of woo-keys.txt) "
                     "and run the batch again." %
                     (len(no_photos), "" if len(no_photos) == 1 else "s"))
    if not created and not skipped and not failed:
        lines.append("Nothing was created.")
    lines.extend(recovery_text(report))
    return lines


def recovery_text(report):
    """What to do next, said once, without inviting a second copy.

    A failed batch always offers the same way out - run it again - because the
    SKU check makes that safe and makes it finish what stopped. The old advice
    (import the CSV through WP All Import) is only mentioned when the website
    holds none of the batch, since importing a CSV over cards that are already
    there is how duplicates appear.
    """
    report = report or {}
    failed = report.get("failed") or []
    if not failed:
        if report.get("created"):
            return ["The CSV import step is not needed for the products "
                    "listed as created above."]
        return []
    on_site = len(report.get("created") or []) + len(report.get("skipped")
                                                    or [])
    waiting = [entry for entry in (report.get("created") or [])
               if str(entry.get("status") or "") != "publish"]
    lines = []
    if waiting:
        lines.append("%d of this batch %s on the website as a draft and only "
                     "%s publishing."
                     % (len(waiting), "is" if len(waiting) == 1 else "are",
                        "needs" if len(waiting) == 1 else "need"))
    if on_site:
        lines.append("Run the same batch again once the website is "
                     "answering: it finds every card by its SKU first, "
                     "publishes the drafts whose photos landed, and creates "
                     "only the ones that are missing. Nothing is created "
                     "twice, so do not import the CSV as well.")
    else:
        lines.append("Nothing was written to the website, so the CSV is "
                     "unchanged and can still be imported the old way - or "
                     "run the same batch again once the site is answering.")
    return lines


def write_report(path, report, site=""):
    """Save what happened beside the CSV, and return the path."""
    target = Path(str(path))
    payload = {"site": site, "when": __import__("datetime").datetime.now()
               .isoformat(timespec="seconds"), "report": report}
    target.write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                      encoding="utf-8")
    return target
