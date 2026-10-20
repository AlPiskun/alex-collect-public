#!/usr/bin/env python3
"""Core sale checklist remains usable when no private plugin is installed."""
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent
FAILS = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else " — " + str(detail)))
    if not ok:
        FAILS.append(label)


def main():
    with tempfile.TemporaryDirectory(prefix="alexcollect-core-sales-") as td:
        work = Path(td)
        for name in ("sold-everywhere.py", "sale_inputs.py"):
            shutil.copyfile(APP / name, work / name)
        check("fixture excludes CanadianShopper implementation",
              not (work / "sold-cards.py").exists())
        (work / "typed.txt").write_text(
            "Card Alpha #1, 2\nCard Beta #2 @facebook\n", encoding="utf-8")
        checklist = work / "checklist.csv"
        result = subprocess.run(
            [sys.executable, str(work / "sold-everywhere.py"),
             "--list", str(work / "typed.txt"), "--checklist", str(checklist)],
            cwd=work, capture_output=True, text=True, timeout=30)
        check("typed sale succeeds without the plugin", result.returncode == 0,
              result.stdout + result.stderr)
        with checklist.open(newline="", encoding="utf-8-sig") as fh:
            typed_rows = list(csv.DictReader(fh))
        check("typed sale creates manual rows for the other channels",
              len(typed_rows) == 6 and
              {r["channel"] for r in typed_rows} ==
              {"canadianshopper", "ebay", "facebook", "website"}, typed_rows)

        orders = work / "orders.csv"
        orders.write_text(
            "Order Number,Order Status,Item 1 Name,Item 1 Quantity\n"
            "A-101,completed,Card Gamma #3,1\n"
            "A-102,cancelled,Card Ignored #4,1\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(work / "sold-everywhere.py"),
             "--woo-orders-csv", str(orders), "--checklist", str(checklist)],
            cwd=work, capture_output=True, text=True, timeout=30)
        check("WooCommerce CSV sale succeeds without the plugin",
              result.returncode == 0, result.stdout + result.stderr)
        with checklist.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        new = [row for row in rows if row["card"] == "Card Gamma #3"]
        ignored = [row for row in rows if row["card"] == "Card Ignored #4"]
        check("completed order is added, cancelled order is ignored",
              len(new) == 3 and not ignored,
              {"new": new, "ignored": ignored, "output": result.stdout})
    if FAILS:
        print("FAILED %d: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("ALL CORE SALES CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
