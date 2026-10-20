"""Generic WooCommerce sale input readers shared by the core workflow.

This module deliberately contains no CanadianShopper lookup or write code.
"""
import csv
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOT_SOLD_STATUSES = ("cancelled", "refunded", "failed", "pending", "trash", "checkout-draft")

def woo_get(base, path, params, key, secret, timeout=60, retries=3):
    """GET the WooCommerce REST API. Returns (status, parsed-or-text)."""
    q = dict(params or {})
    q["consumer_key"] = key
    q["consumer_secret"] = secret
    url = base.rstrip("/") + path + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; AlexCollectTools/1.0)",
        "Accept": "application/json"}, method="GET")
    last = ""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
                return r.status, json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(body)
            except Exception:
                return exc.code, body[:300]
        except Exception as exc:
            last = str(exc)
    return 0, last


def read_woo_orders_api(args, log):
    """Every order on your site in the window, as simple records."""
    params = {"per_page": 100, "page": 1, "orderby": "date", "order": "desc",
              "status": args.woo_status}
    if args.orders:
        params["include"] = ",".join(args.orders.split(","))
    elif args.woo_since:
        params["after"] = args.woo_since + "T00:00:00"
    elif args.woo_days:
        since = datetime.now(timezone.utc) - timedelta(days=args.woo_days)
        params["after"] = since.strftime("%Y-%m-%dT%H:%M:%S")

    orders, page = [], 1
    while True:
        params["page"] = page
        st, d = woo_get(args.woo_api, "/wp-json/wc/v3/orders", params,
                        args.woo_key, args.woo_secret)
        if st == 401 or st == 403:
            raise SystemExit("! Your website refused the API keys (%s). Check them in\n"
                             "  WooCommerce > Settings > Advanced > REST API - the key\n"
                             "  must be Read access, and its Permissions set to Read." % st)
        if st == 400 and page == 1:
            raise SystemExit("! Your website said: %s\n"
                             "  (\"woocommerce_rest_invalid_param\" on `after` can be\n"
                             "  fixed by using a full date: --woo-since 2026-09-01)"
                             % str(d)[:200])
        if st != 200:
            raise SystemExit("! Could not read orders from your website (HTTP %s): %s"
                             % (st, str(d)[:200]))
        rows = d if isinstance(d, list) else []
        for o in rows:
            items = []
            for li in o.get("line_items") or []:
                items.append({"name": (li.get("name") or "").strip(),
                              "qty": int(li.get("quantity") or 1),
                              "sku": (li.get("sku") or "").strip(),
                              "woo_id": li.get("product_id")})
            orders.append({"number": str(o.get("number") or o.get("id") or ""),
                           "status": (o.get("status") or "").lower(),
                           "date": (o.get("date_created") or "")[:19],
                           "items": items})
        if len(rows) < 100:
            break
        page += 1
        if page > 60:
            break
    log("orders    : %d read from %s" % (len(orders), args.woo_api))
    return orders

NUM_ITEM_NAME = re.compile(r"(?i)^(?:item|line\s*item|product|lineitem)\s*(\d+)\s*"
                           r"(?:name|title|product)$")
NUM_ITEM_QTY = re.compile(r"(?i)^(?:item|line\s*item|product|lineitem)\s*(\d+)\s*"
                          r"(?:qty|quantity)$")
HEADER_ORDER = re.compile(r"(?i)^(?:order\s*(?:number|no|id|#)?|order_?(?:number|id)|number)$")
HEADER_STATUS = re.compile(r"(?i)^(?:order\s*)?status$")
HEADER_NAME = re.compile(r"(?i)^(?:item\s*name|line\s*item\s*name|lineitem\s*name|"
                         r"product\s*name|item|product|item_name|product_name)$")
HEADER_QTY = re.compile(r"(?i)^(?:item\s*quantity|quantity|qty|line\s*item\s*quantity|"
                        r"lineitem\s*quantity|item_qty)$")
HEADER_SKU = re.compile(r"(?i)^(?:item\s*sku|sku|lineitem\s*sku|product\s*sku|item_sku)$")
HEADER_ITEMS_BLOB = re.compile(r"(?i)^(?:items|order\s*items)$")


def _find_header_row(rows):
    for i, row in enumerate(rows[:25]):
        cells = [re.sub(r"\s+", " ", (c or "")).strip() for c in row]
        if any(HEADER_NAME.match(c) or NUM_ITEM_NAME.match(c) or HEADER_ITEMS_BLOB.match(c)
               for c in cells) and any(HEADER_ORDER.match(c) for c in cells):
            return i
    for i, row in enumerate(rows[:25]):
        cells = [re.sub(r"\s+", " ", (c or "")).strip() for c in row]
        if any(HEADER_NAME.match(c) or NUM_ITEM_NAME.match(c) for c in cells):
            return i
    return 0


def _parse_items_blob(text):
    """'2 × Foo, 1 × Bar' -> [(qty, name), ...]"""
    out = []
    for part in re.split(r",(?=\s*\d+\s*[x\u00d7])", text or ""):
        m = re.match(r"\s*(\d+)\s*[x\u00d7]\s*(.+?)\s*$", part)
        if m:
            out.append((int(m.group(1)), m.group(2)))
    return out


def read_woo_orders_csv(path, log):
    """Tolerant reader for whatever the WooCommerce admin exported."""
    raw = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            raw = Path(path).read_text(encoding=enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if raw is None:
        raise SystemExit("! Could not read %s" % path)
    rows = list(csv.reader(raw.splitlines()))
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        raise SystemExit("! %s is empty" % path)

    head = _find_header_row(rows)
    header = [re.sub(r"\s+", " ", (c or "")).strip() for c in rows[head]]
    body = rows[head + 1:]

    i_order = i_status = i_name = i_qty = i_sku = i_blob = None
    num_names, num_qtys = {}, {}
    for idx, cell in enumerate(header):
        if i_order is None and HEADER_ORDER.match(cell):
            i_order = idx
        elif i_status is None and HEADER_STATUS.match(cell):
            i_status = idx
        elif m := NUM_ITEM_NAME.match(cell):
            num_names[int(m.group(1))] = idx
        elif m := NUM_ITEM_QTY.match(cell):
            num_qtys[int(m.group(1))] = idx
        elif i_blob is None and HEADER_ITEMS_BLOB.match(cell):
            i_blob = idx
        elif i_name is None and HEADER_NAME.match(cell):
            i_name = idx
        elif i_qty is None and HEADER_QTY.match(cell):
            i_qty = idx
        elif i_sku is None and HEADER_SKU.match(cell):
            i_sku = idx

    if not num_names and i_name is None and i_blob is None:
        raise SystemExit(
            "! I cannot find an item-name column in %s.\n"
            "  Columns seen: %s\n"
            "  Export the orders again (WooCommerce > Orders > Export) or use\n"
            "  --list with one card per line." % (Path(path).name, ", ".join(header[:14])))

    def cell(row, idx):
        if idx is None or idx >= len(row):
            return ""
        return (row[idx] or "").strip()

    orders, seen = {}, []
    last_order, last_status = "", ""
    for row in body:
        num = cell(row, i_order).lstrip("#").strip()
        if num:
            last_order = num
        else:
            num = last_order
        status = (cell(row, i_status) or last_status).lower()
        if status:
            last_status = status
        items = []
        if num_names:
            for n in sorted(num_names):
                name = cell(row, num_names[n])
                if not name:
                    continue
                qtxt = cell(row, num_qtys.get(n)) if num_qtys.get(n) is not None else "1"
                m = re.search(r"\d+", qtxt or "1")
                items.append({"name": name, "qty": int(m.group(0)) if m else 1,
                              "sku": cell(row, i_sku), "woo_id": None})
        elif i_name is not None:
            name = cell(row, i_name)
            if name:
                m = re.search(r"\d+", cell(row, i_qty) or "1")
                items.append({"name": name, "qty": int(m.group(0)) if m else 1,
                              "sku": cell(row, i_sku), "woo_id": None})
        if i_blob is not None and not items:
            for qty, name in _parse_items_blob(cell(row, i_blob)):
                items.append({"name": name, "qty": qty, "sku": "", "woo_id": None})
        if not items:
            continue
        rec = orders.get(num)
        if rec is None:
            rec = {"number": num or "(no order number)", "status": status,
                   "date": "", "items": []}
            orders[num] = rec
            seen.append(rec)
        rec["items"].extend(items)
        if status:
            rec["status"] = status
    log("orders    : %d read from %s (%d item lines)"
        % (len(seen), Path(path).name, sum(len(o["items"]) for o in seen)))
    return seen

def sales_from_orders(orders, log, skip_statuses=True):
    """Flatten orders into sale lines, ignoring orders that are not real sales."""
    sales, notes = [], []
    for o in orders:
        status = (o.get("status") or "").lower()
        if skip_statuses and status in NOT_SOLD_STATUSES:
            notes.append("order %s is %s - ignored" % (o.get("number"), status or "not paid"))
            continue
        for it in o.get("items") or []:
            sales.append({"title": it.get("name") or "", "qty": int(it.get("qty") or 1),
                          "sku": it.get("sku") or "", "woo_id": it.get("woo_id"),
                          "order": o.get("number") or "", "date": o.get("date") or ""})
    return sales, notes

def read_keys_file(path, args):
    """woo-keys.txt: the site address, the consumer key, the secret - one per
    line, in any order. Shopify-style 'ck_... / cs_...' or bare values both work."""
    if not path or not Path(path).is_file():
        return args
    lines = [ln.strip() for ln in Path(path).read_text(encoding="utf-8-sig",
                                                       errors="replace").splitlines()]
    vals = [ln for ln in lines if ln and not ln.startswith("#")]
    rest = []
    for v in vals:
        if v.lower().startswith("http"):
            args.woo_api = args.woo_api or v
        elif re.match(r"(?i)^ck_[0-9a-z]+$", v):
            args.woo_key = args.woo_key or v
        elif re.match(r"(?i)^cs_[0-9a-z]+$", v):
            args.woo_secret = args.woo_secret or v
        else:
            rest.append(v)
    if not (args.woo_key and args.woo_secret) and len(rest) >= 2:
        args.woo_key = args.woo_key or rest[0]
        args.woo_secret = args.woo_secret or rest[1]
    return args
