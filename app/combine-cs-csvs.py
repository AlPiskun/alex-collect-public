#!/usr/bin/env python3
"""
Combine accumulated CanadianShopper import CSVs into import-sized batches
=========================================================================

You will build up one CSV per scanning session (card_pipeline.py writes
`canadianshopper_import_<timestamp>_01_of_01.csv`). The importer takes at most
**500 rows and 2 MB per file**, so when the Import-from-CSV button comes back
you can merge several sessions into a few full batches instead of uploading
nine-card files one at a time.

    py -3 combine-cs-csvs.py                      # every canadianshopper_import_*.csv here
    py -3 combine-cs-csvs.py --csv "Scan*.csv"    # a pattern or folder, repeatable
    py -3 combine-cs-csvs.py --dry-run            # show the plan, write nothing

What it does
------------
* reads every input with utf-8-sig, the encoding the pipeline writes
* normalises the 14 import columns (missing ones are added empty, extras dropped)
* SKIPS duplicate titles and tells you about them - the importer only INSERTs,
  so the same card twice would become two listings
* splits the result into batches of at most 500 rows AND at most 2 MB
* writes them as canadianshopper_combined_<timestamp>_NN_of_MM.csv

About duplicates, in plain words
--------------------------------
The importer never updates an existing listing - it always creates a new one.
So:
  * combine only the batches you have NOT imported yet, and
  * if a card of that title is already on your store, the import will create a
    second copy of it (delete the extra afterwards, or don't import that row).

This tool cannot know what is on the site, so it only compares the CSVs you
give it. The photo stage (`cs-image-sync.py --mode wire`) is the part that
matches against your live listings.

Two things it refuses to guess at
---------------------------------
* Rows whose image_url already points at canadianshopper.ca/api/file/ are
  already-staged rows: combining and re-staging those would upload them a second
  time. Combine the ORIGINAL CSVs from the scan folder instead; pass
  --allow-staged to override.
* A row missing title / price_cad / category is listed as a warning - the
  importer needs all three.
"""

import argparse
import csv
import glob
import io
import os
import re
import sys
from datetime import datetime
from pathlib import Path

CANONICAL_FIELDS = [
    "title", "price_cad", "category", "description", "image_url",
    "inventory", "is_made_to_order", "ship_from_province",
    "shipping_flat_cad", "free_shipping", "handling_days", "transit_days",
    "sizes", "colors",
]
REQUIRED = ("title", "price_cad", "category")
PER_FILE = 500
MAX_MB = 2.0


def clean_title(text):
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def expand_csv_args(values):
    """Each value may be a file, a glob or a folder."""
    out = []
    for value in values:
        if os.path.isdir(value):
            out.extend(sorted(glob.glob(os.path.join(value, "*.csv"))))
        else:
            out.extend(sorted(glob.glob(value)) or [value])
    seen, uniq = set(), []
    for path in out:
        if os.path.abspath(path) not in seen:
            seen.add(os.path.abspath(path))
            uniq.append(path)
    return uniq


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        return fields, [dict(r) for r in reader]


def normalise(row):
    return {f: (row.get(f) or "").strip() for f in CANONICAL_FIELDS}


def batch_bytes(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CANONICAL_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return len(buf.getvalue().encode("utf-8-sig"))


def split_batches(rows, per_file=PER_FILE, max_mb=MAX_MB):
    """Greedy packing: no batch over per_file rows and none over max_mb."""
    limit = max_mb * 1_000_000
    batches, current = [], []
    for row in rows:
        trial = current + [row]
        if len(trial) > per_file or batch_bytes(trial) > limit:
            if not current:                     # a single huge row
                batches.append(trial)
                current = []
                continue
            batches.append(current)
            current = [row]
        else:
            current = trial
    if current:
        batches.append(current)
    return batches


def write_batch(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=CANONICAL_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(
        description="Combine CanadianShopper import CSVs into 500-row batches.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples
--------
  py -3 combine-cs-csvs.py
  py -3 combine-cs-csvs.py --csv "canadianshopper_import_*.csv" --out combined
  py -3 combine-cs-csvs.py --dry-run
""")
    ap.add_argument("--csv", action="append", default=None,
                    help="input CSV, glob or folder (default: canadianshopper_import_*.csv)")
    ap.add_argument("--out", default="combined", help="folder for the batches")
    ap.add_argument("--per-file", type=int, default=PER_FILE,
                    help="max rows per batch (the importer's limit is 500)")
    ap.add_argument("--max-mb", type=float, default=MAX_MB,
                    help="max MB per batch (the importer's limit is 2)")
    ap.add_argument("--keep-duplicates", action="store_true",
                    help="keep rows whose title already appeared (default: skip)")
    ap.add_argument("--allow-staged", action="store_true",
                    help="allow inputs whose image_url is already a hosted square file")
    ap.add_argument("--dry-run", action="store_true", help="show the plan only")
    args = ap.parse_args()

    inputs = expand_csv_args(args.csv or ["canadianshopper_import_*.csv"])
    inputs = [p for p in inputs if os.path.isfile(p)]
    if not inputs:
        raise SystemExit("! No input CSVs found. Pass --csv <file|pattern|folder>.")

    print("=" * 70)
    print(" Combine CanadianShopper import CSVs")
    print("=" * 70)

    rows, seen, dupes, warnings = [], {}, [], []
    staged = []
    for path in inputs:
        fields, file_rows = read_rows(path)
        missing = [f for f in REQUIRED if f not in fields]
        if missing:
            warnings.append("%s: no %s column at all" % (Path(path).name, ", ".join(missing)))
        kept_here = 0
        for row in file_rows:
            row = normalise(row)
            title = clean_title(row["title"])
            if not title:
                warnings.append("%s: a row with a blank title was skipped" % Path(path).name)
                continue
            if "/api/file/" in row["image_url"]:
                staged.append("%s: %s" % (Path(path).name, row["title"][:48]))
            for field in REQUIRED:
                if not row[field]:
                    warnings.append("%s: %r has a blank %s" % (Path(path).name, row["title"][:40], field))
            if title in seen and not args.keep_duplicates:
                dupes.append("%s  (first seen in %s)" % (row["title"][:60], seen[title]))
                continue
            seen.setdefault(title, Path(path).name)
            rows.append(row)
            kept_here += 1
        print("  read  %-52s %4d row(s)" % (Path(path).name[:52], len(file_rows)))

    if staged and not args.allow_staged:
        print("\n  ! %d row(s) already point at a hosted square file (/api/file/)." % len(staged))
        print("    Those CSVs have already been staged. Combine the ORIGINAL CSVs from")
        print("    the scan folder instead - re-staging a staged file uploads it again.")
        print("    (Re-run with --allow-staged if you really mean to.)")
        for line in staged[:5]:
            print("      - %s" % line)
        raise SystemExit("! Stopped so you do not double-upload.")

    batches = split_batches(rows, args.per_file, args.max_mb)
    out_dir = Path(args.out)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("-" * 70)
    print("  rows read            : %d" % (len(rows) + (0 if args.keep_duplicates else len(dupes))))
    print("  duplicates skipped   : %d%s" % (len(dupes), "" if args.keep_duplicates else "  (--keep-duplicates keeps them)"))
    print("  rows to import       : %d in %d file(s)" % (len(rows), len(batches)))
    for line in dupes[:8]:
        print("      dup: %s" % line)
    if len(dupes) > 8:
        print("      ... and %d more" % (len(dupes) - 8))
    if warnings:
        print("  warnings (%d):" % len(warnings))
        for line in warnings[:10]:
            print("      ! %s" % line)
        if len(warnings) > 10:
            print("      ... and %d more" % (len(warnings) - 10))

    written = []
    for index, batch in enumerate(batches, start=1):
        name = "canadianshopper_combined_%s_%02d_of_%02d.csv" % (stamp, index, len(batches))
        path = out_dir / name
        size_mb = batch_bytes(batch) / 1e6
        note = "%d row(s), %.2f MB" % (len(batch), size_mb)
        if len(batch) > args.per_file or size_mb > args.max_mb:
            note += "   <-- OVER THE IMPORTER LIMIT"
        if args.dry_run:
            print("  would write %s  (%s)" % (path, note))
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            write_batch(path, batch)
            print("  wrote %s  (%s)" % (path, note))
            written.append(str(path))

    print("-" * 70)
    if args.dry_run:
        print("  Dry run - nothing was written.")
    else:
        print("  %d file(s) ready in %s" % (len(written), out_dir))
        print("")
        print("  NEXT: stage these so image_url becomes the square hosted photo:")
        print("        stage-cards.bat  (or cs-image-sync.py --mode prepare --csv "
              "\"%s\\*.csv\")" % out_dir)
        print("        then import the copies in canadianshopper\\tools\\cs-ready\\")
    return 0


if __name__ == "__main__":
    sys.exit(main())
