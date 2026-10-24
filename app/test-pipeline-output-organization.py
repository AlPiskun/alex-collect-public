#!/usr/bin/env python3
"""Offline tests for output histories and legacy result-file organization."""
import csv
import importlib.util
import json
import os
import tempfile
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent / "pipeline"
spec = importlib.util.spec_from_file_location("output_history", PIPELINE / "output_history.py")
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)
spec = importlib.util.spec_from_file_location(
    "organize_pipeline_outputs", PIPELINE / "organize_pipeline_outputs.py")
organizer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(organizer)


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_csv_history(root):
    folder = root / "woocommerce_products"
    older = folder / "woocommerce_import_old.csv"
    newer = folder / "woocommerce_import_new.csv"
    current = folder / "woocommerce_import_current.csv"
    write_csv(older, ["SKU", "Name", "Description"], [
        {"SKU": "A", "Name": "Old name", "Description": "Prior details"},
        {"SKU": "B", "Name": "Card B", "Description": "Card B details"}])
    write_csv(newer, ["SKU", "Name", "Description"], [
        {"SKU": "A", "Name": "Revised A", "Description": ""}])
    os.utime(older, (10, 10))
    os.utime(newer, (20, 20))
    write_csv(current, ["SKU", "Name"], [{"SKU": "C", "Name": "Current C"}])
    result = history.consolidate_csv_history(
        folder, "woocommerce_import_*.csv", "woocommerce_history.csv",
        exclude_paths=[current], key_fields=("SKU",))
    with (folder / "woocommerce_history.csv").open(
            newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    by_sku = {row["SKU"]: row for row in rows}
    assert result["files"] == 2 and result["deleted"] == 2
    assert not older.exists() and not newer.exists() and current.exists()
    assert {sku: row["Name"] for sku, row in by_sku.items()} == {
        "A": "Revised A", "B": "Card B"}
    assert by_sku["A"]["Description"] == "Prior details"

    broken = folder / "woocommerce_import_broken.csv"
    broken.write_text("", encoding="utf-8")
    try:
        history.consolidate_csv_history(
            folder, "woocommerce_import_*.csv", "woocommerce_history.csv",
            exclude_paths=[current], key_fields=("SKU",))
        raise AssertionError("empty source CSV should fail closed")
    except ValueError:
        assert broken.exists()
    print("PASS CSV history is written before old batches are removed; current batch is kept")
    print("PASS unreadable CSV stays in place")


def test_ebay_history(root):
    folder = root / "ebay_quick_list"
    folder.mkdir(parents=True)
    legacy = folder / "ebay_quick_list_20261020_100000.html"
    legacy.write_text("<html><h2>Legacy Gretzky</h2></html>", encoding="utf-8")
    old_page = folder / "ebay_quick_list_20261021_100000.html"
    sidecar = folder / "ebay_quick_list_20261021_100000.json"
    old_page.write_text("<html>older page</html>", encoding="utf-8")
    sidecar.write_text(json.dumps({
        "version": 1, "source_file": old_page.name,
        "cards": [{"title": "Current-era record"}],
    }), encoding="utf-8")
    current = folder / "ebay_quick_list_20261022_100000.html"
    current_sidecar = current.with_suffix(".json")
    current.write_text("<html>new page</html>", encoding="utf-8")
    current_sidecar.write_text(json.dumps({"source_file": current.name}),
                               encoding="utf-8")
    result = history.consolidate_ebay_history(
        folder, exclude_paths=[current, current_sidecar])
    saved = json.loads((folder / "ebay_quick_list_history.json").read_text(
        encoding="utf-8"))
    assert result["deleted"] == 3 and len(saved["runs"]) == 2
    assert legacy.name not in [p.name for p in folder.glob("*.html")]
    assert current.exists() and current_sidecar.exists()
    old_sidecar_run = next(run for run in saved["runs"]
                           if run["source_file"] == old_page.name)
    assert "older page" in old_sidecar_run["html"]
    legacy_run = next(run for run in saved["runs"]
                      if run["source_file"] == legacy.name)
    assert "Legacy Gretzky" in legacy_run["legacy_html"]
    print("PASS eBay Quick List history preserves legacy page data and keeps the current page")


def test_legacy_organizer(root):
    root.mkdir(parents=True, exist_ok=True)
    cs = root / "canadianshopper_import_20261022.csv"
    ebay = root / "ebay_quick_list_20261022_100000.html"
    woo = root / "woocommerce_import_20261022.csv"
    facebook = root / "facebook_delta_20261022.xlsx"
    unknown = root / "notes.txt"
    legacy_ready_dir = root / "cs-ready"
    legacy_ready = legacy_ready_dir / "canadianshopper_import_staged.csv"
    for path in (cs, ebay, woo, facebook, unknown):
        path.write_text("test", encoding="utf-8")
    legacy_ready_dir.mkdir()
    legacy_ready.write_text("staged", encoding="utf-8")
    dest = root / "woocommerce_products"
    dest.mkdir()
    (dest / woo.name).write_text("keep destination", encoding="utf-8")
    preview = organizer.organize(root, apply=False, output=lambda _line: None)
    assert preview["planned"] == 5 and all(path.exists() for path in
                                           (cs, ebay, woo, facebook, legacy_ready))
    result = organizer.organize(root, apply=True, output=lambda _line: None)
    assert result["moved"] == 5
    assert (root / "canadianshopper_products" / cs.name).exists()
    assert (root / "ebay_quick_list" / ebay.name).exists()
    assert (dest / woo.name).read_text(encoding="utf-8") == "keep destination"
    assert len(list(dest.glob("woocommerce_import_20261022.migrated-*"))) == 1
    assert (root / "facebook_merchant_products" / facebook.name).exists()
    assert (root / "canadianshopper_products" / "cs-ready" / legacy_ready.name).exists()
    assert not legacy_ready_dir.exists()
    assert unknown.exists()
    print("PASS root-level outputs move by marketplace, with collision protection and unknown files untouched")


def main():
    with tempfile.TemporaryDirectory(prefix="alexcollect-output-test-") as temp:
        root = Path(temp)
        test_csv_history(root / "csv")
        test_ebay_history(root / "ebay")
        test_legacy_organizer(root / "legacy")


if __name__ == "__main__":
    main()
