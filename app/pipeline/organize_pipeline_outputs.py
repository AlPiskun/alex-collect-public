#!/usr/bin/env python3
"""Move recognized legacy result files from the pipeline root into folders.

Preview is the default. Pass --apply to move files. This organizer never
rewrites, deletes, or overwrites content; name collisions get a safe suffix.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

DESTINATIONS = {
    "canadianshopper_products": (
        "canadianshopper_import*.csv", "canadianshopper_history.csv",
        "canadianshopper_staged_history.csv", "cs-image-report.csv",
        "cs-image-cache.json",
    ),
    "ebay_quick_list": ("ebay_quick_list_*.html", "ebay_quick_list_*.json"),
    "woocommerce_products": ("woocommerce_import_*.csv", "woocommerce_history.csv"),
    "facebook_merchant_products": (
        "facebook_history.xlsx", "facebook_batch_*.xlsx",
        "facebook_delta_*.xlsx", "facebook_runlog_*.txt",
        "feed_debug_response.txt",
    ),
}


def _destination_name(destination: Path, source: Path):
    target = destination / source.name
    if not target.exists():
        return target
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = destination / (source.stem + ".migrated-" + stamp + source.suffix)
    number = 2
    while candidate.exists():
        candidate = destination / (
            source.stem + ".migrated-" + stamp + "-" + str(number) + source.suffix)
        number += 1
    return candidate


def plan_moves(pipeline_dir):
    root = Path(pipeline_dir).expanduser().resolve()
    moves = []
    for folder, patterns in DESTINATIONS.items():
        destination = root / folder
        seen = set()
        for pattern in patterns:
            for source in sorted(root.glob(pattern), key=lambda p: p.name.casefold()):
                if not source.is_file() or source in seen:
                    continue
                seen.add(source)
                moves.append((source, _destination_name(destination, source)))
    # The older manual stage wrote its prepared CSVs into a root cs-ready/ folder.
    legacy_ready = root / "cs-ready"
    ready_destination = root / "canadianshopper_products" / "cs-ready"
    if legacy_ready.is_dir():
        for source in sorted(legacy_ready.iterdir(), key=lambda p: p.name.casefold()):
            if source.is_file() and (
                    (source.name.startswith("canadianshopper_import") and
                     source.suffix.lower() == ".csv") or
                    source.name in {"back-map.json",
                                    "canadianshopper_staged_history.csv"}):
                moves.append((source, _destination_name(ready_destination, source)))
    return root, moves


def organize(pipeline_dir, apply=False, output=print):
    root, moves = plan_moves(pipeline_dir)
    output("Pipeline folder: %s" % root)
    if not moves:
        output("No recognized legacy result files are in the pipeline root.")
        return {"moved": 0, "planned": 0}
    for source, destination in moves:
        output("%s  ->  %s" %
               ("MOVE" if apply else "WOULD MOVE", destination.relative_to(root)))
    if not apply:
        output("Preview only. Re-run with --apply to move these files.")
        return {"moved": 0, "planned": len(moves)}

    moved = 0
    for source, destination in moves:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = _destination_name(destination.parent, source) if destination.exists() else destination
        source.replace(destination)
        moved += 1
        output("Moved: %s" % source.name)
    try:
        (root / "cs-ready").rmdir()
    except OSError:
        pass
    output("Moved %d file(s). No files were deleted or overwritten." % moved)
    return {"moved": moved, "planned": len(moves)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipeline-dir", default=str(Path(__file__).resolve().parent),
                        help="pipeline folder (defaults to this script's folder)")
    parser.add_argument("--apply", action="store_true",
                        help="perform the planned moves; default is preview only")
    args = parser.parse_args(argv)
    try:
        organize(args.pipeline_dir, apply=args.apply)
    except Exception as exc:
        print("ERROR: could not organize pipeline results: %s: %s" %
              (type(exc).__name__, exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
