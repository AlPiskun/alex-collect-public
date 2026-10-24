#!/usr/bin/env python3
"""Consolidate prior marketplace result files after a newer output exists.

The new result is written first. This module then atomically updates a durable
history and only afterward removes the superseded per-run files. Any read or
write error leaves the source files in place.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path


def _csv_read(path):
    with Path(path).open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("CSV has no header: %s" % path)
        fields = [str(field or "").strip() for field in reader.fieldnames]
        if not any(fields):
            raise ValueError("CSV has an empty header: %s" % path)
        rows = []
        for row in reader:
            rows.append({field: str(row.get(field) or "") for field in fields})
    return fields, rows


def _row_key(row, fields):
    values = [str(row.get(field, "")).strip().casefold() for field in fields]
    if fields and all(values):
        return "key:" + "\x1f".join(values)
    canonical = json.dumps(row, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return "row:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _atomic_csv(path, fieldnames, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                    dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames,
                                    extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fieldnames})
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def consolidate_csv_history(directory, pattern, history_name,
                            exclude_paths=(), key_fields=()):
    """Merge previous CSV result files into a stable history, then remove them.

    `exclude_paths` are the newly written files for this run. When a key is
    supplied, later rows replace earlier snapshots of the same listing. With no
    key, exact duplicate rows are suppressed but distinct historical rows stay.
    """
    directory = Path(directory)
    excluded = {Path(p).resolve() for p in exclude_paths}
    sources = sorted(
        (path for path in directory.glob(pattern)
         if path.is_file() and path.resolve() not in excluded),
        key=lambda path: (path.stat().st_mtime_ns, path.name.casefold()))
    if not sources:
        return {"files": 0, "deleted": 0, "rows": 0,
                "history": str(directory / history_name)}

    history_path = directory / history_name
    ordered_fields = []
    all_rows = []
    if history_path.is_file():
        fields, rows = _csv_read(history_path)
        ordered_fields.extend(fields)
        all_rows.extend(rows)
    for source in sources:
        fields, rows = _csv_read(source)
        for field in fields:
            if field not in ordered_fields:
                ordered_fields.append(field)
        all_rows.extend(rows)

    # Keep one latest record per key (Woo SKU / CanadianShopper title), or all
    # distinct records when a key is not supplied.
    merged = []
    positions = {}
    for row in all_rows:
        key = _row_key(row, key_fields)
        if key in positions:
            # Keep existing non-empty values when a later export omits a
            # column or leaves it blank, while still applying changed values.
            updates = {field: value for field, value in row.items() if value != ""}
            merged[positions[key]] = {**merged[positions[key]], **updates}
        else:
            positions[key] = len(merged)
            merged.append(row)

    _atomic_csv(history_path, ordered_fields, merged)
    deleted = 0
    for source in sources:
        try:
            source.unlink()
            deleted += 1
        except OSError:
            # The history is already safe; leave any undeleted original in place.
            pass
    return {"files": len(sources), "deleted": deleted, "rows": len(merged),
            "history": str(history_path)}


def _atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                    dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_ebay_sidecar(path, data):
    """Atomically write metadata paired with a newly generated Quick List."""
    _atomic_json(path, data)


def consolidate_ebay_history(directory, exclude_paths=()):
    """Roll old Quick List pages and their sidecars into one JSON history."""
    directory = Path(directory)
    excluded = {Path(p).resolve() for p in exclude_paths}
    html_files = {
        p.stem: p for p in directory.glob("ebay_quick_list_*.html")
        if p.is_file() and p.resolve() not in excluded
    }
    json_files = {
        p.stem: p for p in directory.glob("ebay_quick_list_*.json")
        if p.name != "ebay_quick_list_history.json" and p.is_file()
        and p.resolve() not in excluded
    }
    stems = sorted(set(html_files) | set(json_files))
    history_path = directory / "ebay_quick_list_history.json"
    if not stems:
        return {"files": 0, "deleted": 0, "runs": 0,
                "history": str(history_path)}

    if history_path.is_file():
        current = json.loads(history_path.read_text(encoding="utf-8"))
        if not isinstance(current, dict) or not isinstance(current.get("runs"), list):
            raise ValueError("Invalid eBay Quick List history: %s" % history_path)
    else:
        current = {"version": 1, "runs": []}
    runs = current["runs"]
    known = {str(item.get("source_file")) for item in runs
             if isinstance(item, dict)}

    for stem in stems:
        page = html_files.get(stem)
        sidecar = json_files.get(stem)
        source_name = page.name if page else stem + ".json"
        if source_name in known:
            # A prior history write may have succeeded while a file delete did
            # not. The already-recorded source can simply be cleaned up below.
            continue
        if sidecar:
            run = json.loads(sidecar.read_text(encoding="utf-8"))
            if not isinstance(run, dict):
                raise ValueError("Invalid Quick List sidecar: %s" % sidecar)
            run = dict(run)
            run.setdefault("source_file", source_name)
            if page:
                run.setdefault("html", page.read_text(encoding="utf-8",
                                                       errors="replace"))
            if str(run.get("source_file")) in known:
                continue
        elif page:
            # Preserve pre-sidecar pages verbatim so no old drag/copy details
            # are lost when the individual file is removed.
            run = {"version": 1, "source_file": source_name,
                   "created": page.stat().st_mtime, "legacy_html":
                   page.read_text(encoding="utf-8", errors="replace")}
        else:
            continue
        runs.append(run)
        known.add(str(run.get("source_file", source_name)))

    current["version"] = 1
    current["runs"] = runs
    _atomic_json(history_path, current)

    deleted = 0
    for source in list(html_files.values()) + list(json_files.values()):
        try:
            source.unlink()
            deleted += 1
        except OSError:
            pass
    return {"files": len(stems), "deleted": deleted, "runs": len(runs),
            "history": str(history_path)}
