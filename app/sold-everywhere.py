#!/usr/bin/env python3
"""
sold-everywhere.py - one card sold, four places to fix
======================================================

WHY
    A vintage card is one unique copy, but it is advertised in up to four
    places at once:

        your website (store.piskun.ca)   <- where the order came from
        CanadianShopper                  <- never reduces stock by itself
        eBay                             <- 250 free listings a month
        Facebook Marketplace             <- personal account: one tap each

    Whichever one sells, the other three keep advertising the card, and the
    customer who gets there first is a double sale. CanadianShopper can be
    changed for you (sold-cards.py). eBay and Facebook have no bulk tools for a
    personal account, so what they need is a checklist that (a) names every card
    still advertised somewhere, (b) links straight to the listing pages, and
    (c) keeps telling you until it is done.

WHAT IT DOES
    * takes sold cards from the same places sold-cards.py does - a list you
      type, an orders CSV exported from your website, or your website's API
    * for each one, writes the rows that are still outstanding:
          CanadianShopper   (or it can do this one for you, with --cs)
          eBay              lower the count, or end it if that was the last copy
          Facebook          mark sold / out of stock
          your website      only when the sale happened somewhere else
    * keeps a tick-off file you edit in Notepad or Excel:
          sold-cards-checklist.csv      put an x in the "done" column
    * shows the outstanding list every time you run ANY of the tools in this
      folder (the reminder you asked for)
    * reminds you to scan replacement photos and can open the scan folder

TYPICAL USE
    python3 sold-everywhere.py --woo-orders-csv orders.csv
    python3 sold-everywhere.py --list sold.txt --sold-on facebook
    python3 sold-everywhere.py --list sold.txt --cs          # let it fix CS too
    python3 sold-everywhere.py --status                      # what is outstanding
    python3 sold-everywhere.py --done 3,5                    # tick rows 3 and 5
    python3 sold-everywhere.py --images-file needs-photos.txt
    python3 sold-everywhere.py --banner                      # one-line nudge (tools)
"""

import argparse
import csv
import re
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

CHECKLIST_COLUMNS = ["num", "done", "card", "channel", "what to do", "link",
                     "added", "ref"]
CHANNEL_ORDER = ["website", "canadianshopper", "ebay", "facebook", "photos"]
CHANNEL_LABEL = {
    "website": "your website",
    "canadianshopper": "CanadianShopper",
    "ebay": "eBay",
    "facebook": "Facebook",
    "photos": "photos",
}
EBAY_LINK = "https://www.ebay.ca/sh/lst/active"
FB_LINK = "https://www.facebook.com/marketplace/you/selling"
SITE_LINK = "https://store.piskun.ca/wp-admin/edit.php?post_type=product"
DEFAULT_SCAN_DIR = r"C:\Users\Owner\Pictures\ControlCenter4\Scan"


# --------------------------------------------------------------------------- helpers
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def card_key(title):
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def read_checklist(path):
    """Returns the rows, whatever state the file is in. A file we cannot read is
    moved aside, never edited in place - it may be the only record."""
    if not Path(path).is_file():
        return []
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    except Exception:
        rows = []
    if not rows:
        return []
    if not set(CHECKLIST_COLUMNS).issubset(set(rows[0].keys())):
        backup = "%s.bak-%s" % (path, datetime.now().strftime("%Y%m%d-%H%M%S"))
        try:
            Path(path).rename(backup)
            print("  note: the checklist had unexpected columns - kept as %s"
                  % Path(backup).name)
        except Exception:
            pass
        return []
    clean = []
    for r in rows:
        if not (r.get("card") or "").strip():
            continue
        r["_key"] = (r.get("ref") or "", card_key(r.get("card")), r.get("channel") or "")
        clean.append(r)
    return clean


def write_checklist(path, rows):
    rows = sorted(rows, key=lambda r: (bool(str(r.get("done") or "").strip()),
                                       0 if r.get("channel") == "photos"
                                       else CHANNEL_ORDER.index(r["channel"]) + 1
                                       if r.get("channel") in CHANNEL_ORDER else 9,
                                       r.get("card") or ""))
    out = []
    for i, r in enumerate(rows, 1):
        out.append({"num": i, "done": r.get("done") or "", "card": r.get("card") or "",
                    "channel": r.get("channel") or "", "what to do": r.get("what to do") or "",
                    "link": r.get("link") or "", "added": r.get("added") or "",
                    "ref": r.get("ref") or ""})
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=CHECKLIST_COLUMNS, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(out)
    return out


def pending(rows, channel=None):
    out = []
    for r in rows:
        if str(r.get("done") or "").strip():
            continue
        if channel and r.get("channel") != channel:
            continue
        out.append(r)
    return out


def counts_by_channel(rows):
    tally = {}
    for r in pending(rows):
        tally[r.get("channel")] = tally.get(r.get("channel"), 0) + 1
    return tally


# --------------------------------------------------------------------------- rows
def action_for(channel, qty, last_left, scan_dir):
    n = qty if qty and qty > 0 else 1
    word = "1 copy" if n == 1 else "%d copies" % n
    if channel == "canadianshopper":
        return ("Reduce the stock by %s in the CanadianShopper vendor dashboard; "
                "archive the listing if that reaches 0." % word)
    if channel == "ebay":
        if last_left:
            return ("End the eBay listing (Actions -> End) - the last copy has gone."
                    " It moves to Unsold, photos kept, one click to relist.")
        return ("Lower the eBay quantity by %d (Seller Hub -> Active listings ->"
                " Edit quantity). If that leaves 0, End the listing instead - a"
                " parked listing still eats one of your 250 monthly slots." % n)
    if channel == "facebook":
        if last_left:
            return ("Mark it sold on Facebook (listing -> Mark as sold -> choose the"
                    " buyer) - or Mark out of stock if the listing is an 'in stock'"
                    " one. Do not leave it up: Facebook penalises stale listings.")
        return ("Facebook has no quantity box for these listings any more - put the"
                " remaining count in the description and reply to buyers, then mark"
                " it sold when the last one goes.")
    if channel == "website":
        return ("The order did not come from your website - reduce the stock there"
                " (Products -> search this title) so it cannot be bought twice.")
    if channel == "photos":
        return "Scan the replacement photo(s) into %s" % scan_dir
    if channel == "photos-all":
        return ("Replace the photos everywhere: website product media,"
                " CanadianShopper (run WirePhotos.bat), the eBay listing, and the"
                " Facebook listing.")
    return ""


def make_row(card, channel, action, link, ref):
    return {"done": "", "card": card, "channel": channel, "what to do": action,
            "link": link, "added": now_iso(), "ref": ref}


def channel_rows(card, qty, last_left, sold_on, ref, scan_dir):
    rows = []
    if sold_on != "website":
        rows.append(make_row(card, "website",
                             action_for("website", qty, last_left, scan_dir),
                             SITE_LINK + "&s=" + urllib.parse.quote_plus(card[:60]), ref))
    if sold_on != "canadianshopper":
        rows.append(make_row(
            card, "canadianshopper",
            action_for("canadianshopper", qty, last_left, scan_dir), "", ref))
    if sold_on != "ebay":
        rows.append(make_row(card, "ebay", action_for("ebay", qty, last_left, scan_dir),
                             EBAY_LINK, ref))
    if sold_on != "facebook":
        rows.append(make_row(card, "facebook",
                             action_for("facebook", qty, last_left, scan_dir), FB_LINK, ref))
    return rows


def photo_rows(card, ref, scan_dir):
    return [make_row(card, "photos", action_for("photos", 1, False, scan_dir), "", ref),
            make_row(card, "photos-all", action_for("photos-all", 1, False, scan_dir), "", ref)]


def merge_rows(existing, new_rows):
    """Add the rows that are not already on the checklist.

    An order is only ever recorded once, so re-reading the same orders export
    (or the API window) adds nothing. A card typed into the list has no order
    number to go by, so those are de-duplicated within the same day: type the
    same sale twice in one day and you get one set of rows, but if the card
    sells again next week you get a fresh set."""
    known = {}
    for r in existing:
        known[(r.get("ref") or "", card_key(r.get("card")), r.get("channel"))] = r
    today = now_iso()[:10]
    added = []
    for r in new_rows:
        key = ((r.get("ref") or ""), card_key(r.get("card")), r["channel"])
        seen = known.get(key)
        if seen is not None:
            if seen.get("ref"):
                continue                       # same order: already on the list
            if (seen.get("added") or "")[:10] == today:
                continue                       # same card, typed again today
        existing.append(dict(r, _key=key))
        known[key] = r
        added.append(r)
    return added


# --------------------------------------------------------------------------- input
def load_sales(args, log):
    """Read generic sale inputs without requiring the private CS plugin."""
    import sale_inputs

    args = sale_inputs.read_keys_file(args.woo_keys, args)
    if not args.woo_status:
        args.woo_status = "processing,completed"
    if not args.woo_days:
        args.woo_days = 60
    sales, notes = [], []

    if args.woo_api:
        if not (args.woo_key and args.woo_secret):
            raise SystemExit("! WooCommerce API URL and both read-only keys are required.")
        orders = sale_inputs.read_woo_orders_api(args, log)
        more, extra = sale_inputs.sales_from_orders(orders, log)
        for sale in more:
            sale["sold_on"] = "website"
        sales.extend(more)
        notes.extend(extra)
    elif args.woo_orders_csv:
        orders = sale_inputs.read_woo_orders_csv(args.woo_orders_csv, log)
        more, extra = sale_inputs.sales_from_orders(orders, log)
        for sale in more:
            sale["sold_on"] = "website"
        sales.extend(more)
        notes.extend(extra)

    if args.list:
        text = Path(args.list).read_text(encoding="utf-8-sig", errors="replace")
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            qty, last_left = 1, False
            m = re.match(r"^(.*?)[,;\t]\s*(\d+)\s*(?:[,;\t]\s*(last|0|none)\s*)?$",
                         line, re.I)
            if m:
                line = m.group(1).strip()
                qty = int(m.group(2))
                last_left = bool(m.group(3))
            at = re.search(r"\s+@(website|web|site|canadianshopper|cs|ebay|facebook|fb|inperson|person)$",
                           line, re.I)
            sold_on = args.sold_on
            if at:
                line = line[:at.start()].strip()
                token = at.group(1).lower()
                sold_on = {"web": "website", "website": "website", "site": "website",
                           "canadianshopper": "canadianshopper",
                           "cs": "canadianshopper", "ebay": "ebay",
                           "facebook": "facebook", "fb": "facebook",
                           "person": "inperson", "inperson": "inperson"}[token]
            sales.append({"title": line, "qty": qty, "order": "", "sold_on": sold_on,
                          "last_left": last_left, "sku": "", "woo_id": None})
    return sales, notes


# --------------------------------------------------------------------------- canadian shopper
def run_cs(args, log, checklist_rows_created):
    """Hand the optional CanadianShopper leg to its installed plugin tool."""
    tool = Path(args.cs_tool) if getattr(args, "cs_tool", "") else HERE / "sold-cards.py"
    if not tool.is_file():
        log("  ! CanadianShopper plugin tool is not installed; open the Plugins tab.")
        return None
    cmd = [sys.executable, "-u", str(tool)]
    if args.woo_orders_csv:
        cmd += ["--woo-orders-csv", args.woo_orders_csv]
    if args.woo_api and args.woo_key and args.woo_secret:
        cmd += ["--woo-api", args.woo_api, "--woo-key", args.woo_key,
                "--woo-secret", args.woo_secret]
    elif args.woo_keys:
        cmd += ["--woo-keys", args.woo_keys]
    if args.list:
        cmd += ["--list", args.list]
    if args.orders:
        cmd += ["--orders", args.orders]
    if args.woo_status:
        cmd += ["--woo-status", args.woo_status]
    if getattr(args, "woo_days", None):
        cmd += ["--woo-days", str(args.woo_days)]
    if getattr(args, "woo_since", ""):
        cmd += ["--woo-since", args.woo_since]
    if args.cookie:
        cmd += ["--cookie", args.cookie]
    if args.cookie_file:
        cmd += ["--cookie-file", args.cookie_file]
    cmd += ["--ledger", str(args.ledger), "--report", str(args.report), "--apply"]
    if getattr(args, "gui_dialogs", False):
        cmd.append("--gui-dialogs")
    log("")
    log("  CanadianShopper leg - running: %s" % " ".join(
        ('"%s"' % c if " " in c else c) for c in cmd[1:]))
    try:
        if getattr(args, "gui_dialogs", False):
            # In GUI mode the child must share stdin/stdout so its structured
            # match and approval requests reach Tk and its answers reach it.
            proc = subprocess.Popen(cmd, stdin=sys.stdin, stdout=sys.stdout,
                                    stderr=subprocess.STDOUT)
            rc = proc.wait(timeout=900)
            output = ""
        else:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            rc, output = res.returncode, res.stdout or ""
    except Exception as exc:
        log("  ! could not run sold-cards.py: %s" % exc)
        return None
    if output:
        tail = [ln for ln in output.splitlines() if ln.strip()][-14:]
        for ln in tail:
            log("    %s" % ln)
    if rc != 0:
        log("  ! the CanadianShopper run did not finish (exit %s) - the rows below"
            " stay unticked, run SoldCards.bat" % rc)
        return None
    failed = set()
    try:
        if Path(args.report).is_file():
            with open(args.report, newline="", encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    if (row.get("action") or "") in ("error", "not-found"):
                        failed.add(card_key(row.get("title")))
    except Exception:
        pass
    return failed


# --------------------------------------------------------------------------- status
def print_status(rows, checklist_path, verbose=True):
    todo = pending(rows)
    if not todo:
        if verbose:
            print("  Nothing outstanding - every card that sold has been dealt with"
                  " everywhere.")
        return 0
    tally = counts_by_channel(rows)
    summary = ", ".join("%s %d" % (CHANNEL_LABEL.get(k, k), v)
                        for k, v in sorted(tally.items(),
                                           key=lambda kv: CHANNEL_ORDER.index(kv[0])
                                           if kv[0] in CHANNEL_ORDER else 9))
    print("  %d thing(s) still to do:  %s" % (len(todo), summary))
    if verbose:
        for r in todo:
            print("   #%-3s %-16s %-44s %s" % (r.get("num") or "?", 
                                               r.get("channel") or "",
                                               (r.get("card") or "")[:44],
                                               (r.get("link") or "")))
    print("  tick them off: put x in the 'done' column of %s" % checklist_path)
    return len(todo)


def print_banner(rows, checklist_path):
    """One short block. Silent when there is nothing to nag about."""
    todo = pending(rows)
    if not todo:
        return
    tally = counts_by_channel(rows)
    photos = tally.pop("photos", 0) + tally.pop("photos-all", 0)
    parts = []
    for key in ("ebay", "facebook", "canadianshopper", "website"):
        if tally.get(key):
            parts.append("%s %d" % (CHANNEL_LABEL[key], tally[key]))
    print("")
    print("  ===== STILL ADVERTISED ELSEWHERE ============================")
    print("   %d sold card item(s) waiting:  %s" % (len(todo), ", ".join(parts)))
    if photos:
        print("   %d card(s) need new photos scanned" % photos)
    print("   checklist : %s" % checklist_path)
    print("   show it   : SoldEverywhere.bat  (menu 3)")


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description="One card sold -> fix your website, CanadianShopper, eBay and"
                    " Facebook. Keeps a tick-off checklist and reminds you until it"
                    " is done.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
the checklist file
------------------
  sold-cards-checklist.csv, one row per thing to do. Put an x in the "done"
  column (Notepad or Excel) and the row stops being reported. Rows ticked off
  come back only if a NEW sale needs them again.

examples
--------
  python3 sold-everywhere.py --list sold.txt                  website sale
  python3 sold-everywhere.py --list sold.txt --sold-on facebook
  python3 sold-everywhere.py --woo-orders-csv orders.csv --cs  let CS be done for me
  python3 sold-everywhere.py --status
  python3 sold-everywhere.py --done 3,5
  python3 sold-everywhere.py --images-file newphotos.txt
  python3 sold-everywhere.py --banner
""")
    ap.add_argument("--list", default="", help="text file: one card per line,"
                    " optionally 'title, qty' or 'title, qty, last', and"
                    " '@ebay' / '@facebook' / '@inperson' to name where it sold")
    ap.add_argument("--sold-on", default="website",
                    choices=["website", "canadianshopper", "facebook", "ebay",
                             "inperson", "other"],
                    help="where these sales came from (default website)")
    ap.add_argument("--woo-orders-csv", default="", help="orders CSV from your website")
    ap.add_argument("--woo-api", default="")
    ap.add_argument("--woo-key", default="")
    ap.add_argument("--woo-secret", default="")
    ap.add_argument("--woo-keys", default="")
    ap.add_argument("--woo-status", default="")
    ap.add_argument("--woo-days", type=int, default=0)
    ap.add_argument("--woo-since", default="")
    ap.add_argument("--orders", default="")
    ap.add_argument("--cs", action="store_true",
                    help="also do the CanadianShopper leg now")
    ap.add_argument("--cs-tool", default="",
                    help="path to the optional plugin's stock-update tool")
    ap.add_argument("--gui-dialogs", action="store_true",
                    help="use Tk dialogs for CanadianShopper matching and write confirmation")
    ap.add_argument("--images-file", default="",
                    help="cards that need new photos: one title per line")
    ap.add_argument("--scan-dir", default=DEFAULT_SCAN_DIR,
                    help="where your scanner drops the files")
    ap.add_argument("--done", default="", help="tick these checklist numbers (or 'all')")
    ap.add_argument("--status", action="store_true", help="show what is outstanding")
    ap.add_argument("--banner", action="store_true",
                    help="one-line nudge, for the other tools to call")
    ap.add_argument("--prune-done", action="store_true",
                    help="delete rows that are already ticked off")
    ap.add_argument("--checklist", default=str(HERE / "sold-cards-checklist.csv"))
    ap.add_argument("--cookie", default="")
    ap.add_argument("--cookie-file", default="")
    ap.add_argument("--ledger", default=str(HERE / "sold-cards-ledger.json"))
    ap.add_argument("--report", default=str(HERE / "sold-cards-report.csv"))
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    rows = read_checklist(args.checklist)

    if args.banner:
        print_banner(rows, args.checklist)
        return 0

    if args.status or args.done:
        if args.done:
            todo = pending(rows)
            if args.done.strip().lower() in ("all", "*"):
                chosen = list(todo)
            else:
                wanted = {int(x) for x in re.findall(r"\d+", args.done)}
                chosen = [r for r in todo if int(r.get("num") or 0) in wanted]
                missing = wanted - {int(r.get("num") or 0) for r in chosen}
                if missing:
                    print("  ! no outstanding row numbered %s"
                          % ", ".join(str(m) for m in sorted(missing)))
            for r in chosen:
                r["done"] = "x"
            rows = write_checklist(args.checklist, rows)
            print("  ticked off %d row(s)." % len(chosen))
            if not chosen:
                print_status(rows, args.checklist)
                return 0
        print_status(rows, args.checklist)
        return 0

    if args.prune_done:
        before = len(rows)
        rows = [r for r in rows if not str(r.get("done") or "").strip()]
        write_checklist(args.checklist, rows)
        print("  removed %d ticked-off row(s); %d left." % (before - len(rows), len(rows)))
        return 0

    # ------------------------------------------------------------------ new work
    print("=" * 74)
    print(" Alex Collect - a card sold: clear it from everywhere")
    print("=" * 74)

    created = []
    sales = []
    if args.list or args.woo_orders_csv or args.woo_keys or args.woo_api:
        sales, notes = load_sales(args, print)
        for s in sales:
            s.setdefault("sold_on", args.sold_on)
            s.setdefault("last_left", False)
        if sales:
            print("sales     : %d line(s)" % len(sales))
        if notes:
            for n in notes[:10]:
                print("   note: %s" % n)
        for s in sales:
            new = channel_rows(s["title"], s.get("qty") or 1, s.get("last_left"),
                               s.get("sold_on") or args.sold_on, s.get("order") or "",
                               args.scan_dir)
            created += merge_rows(rows, new)

    if args.images_file:
        if not Path(args.images_file).is_file():
            raise SystemExit("! no photo list at %s - make the file first (one card"
                             " title per line)." % args.images_file)
        text = Path(args.images_file).read_text(encoding="utf-8-sig", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            created += merge_rows(rows, photo_rows(line, "photos", args.scan_dir))
        print("photos    : rows for the cards in %s" % Path(args.images_file).name)

    # ---- CanadianShopper leg -------------------------------------------------
    if args.cs and (args.list or args.woo_orders_csv or args.woo_keys or args.woo_api):
        failed = run_cs(args, print, created)
        if failed is not None:
            done_keys = {card_key(r["card"]) for r in created
                         if r["channel"] == "canadianshopper"} - failed
            for r in rows:
                if r.get("channel") == "canadianshopper" and \
                        card_key(r.get("card")) in done_keys and \
                        not str(r.get("done") or "").strip():
                    r["done"] = "x"
                    r["what to do"] = ("Updated on CanadianShopper by this run"
                                       " (%s)" % now_iso())
            print("  CanadianShopper rows ticked off: %d"
                  % len(done_keys))

    if created:
        print("")
        print("  %d new row(s) added to the checklist:" % len(created))
        for r in created:
            print("   %-16s %-40s %s" % (r["channel"], (r["card"] or "")[:40],
                                         r["what to do"][:64]))
    elif sales or args.images_file:
        print("")
        print("  Nothing new - those cards are already on the checklist.")

    rows = write_checklist(args.checklist, rows)

    print("")
    print("-" * 74)
    print_status(rows, args.checklist)
    print("-" * 74)
    print("  checklist : %s" % args.checklist)
    print("  tick off  : SoldEverywhere.bat -> 4, or put x in the done column")
    if any(r.get("channel", "").startswith("photos") for r in created):
        print("  photos    : scan into %s" % args.scan_dir)
    print("")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:                      # never blow up a tool that called us
        print("  sold-everywhere: %s" % exc)
        sys.exit(1)
