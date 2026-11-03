#!/usr/bin/env python3
"""Read the photo staging step's own answer - per card, not just an exit code.

CanadianShopper 1.0.40 added ``marketplace.photo_stage`` (``tools/cs-photo-
stage.py``), which stages a batch's photos and writes one JSON file saying what
happened to every row: the front that was uploaded and its URL, the front the
cache already knew, the dry-run row that was only checked, and the row that
failed with the plugin's own reason. The older ``batch.photo_stage``
(``tools/cs-image-sync.py --mode prepare``) answers with an exit code alone, so
the panel could say *staged* or *did not stage* and nothing about which card.

This module is the reading of that file - no plugin code, no network, no Tk -
so the panel can name the cards that failed, count what was already staged, and
write the staged history from the CSVs the plugin says it wrote rather than
from a filename pattern. It is deliberately forgiving: a plugin that reports a
key this module has not met yet, or a file cut short by a full disk, must make
the panel say less, never crash it.

The contract it reads (CanadianShopper 1.0.40):

``{"items": [{"csv", "row", "sku", "title", "status", "back_status",
"back_staged_url", "staged_url", "staged_csv", "source_image_url", "error"}],
"files": [{"input", "output"}]}``

with ``status`` one of :data:`STATUSES`. Exit codes are the plugin's own: ``0``
no row errors, ``1`` a partial batch whose successes are still reported, ``2``
a fatal invocation, input, authentication or output failure - and a safe
``--stage-out`` then holds an error JSON.
"""

import json
from pathlib import Path

#: The action that stages a batch's photos and reports every row. The older
#: ``batch.photo_stage`` still exists and still works; it is the fallback for a
#: plugin older than 1.0.40, and it says nothing per row.
ACTION = "marketplace.photo_stage"

#: The plugin version that first declares :data:`ACTION`.
VERSION = "1.0.40"

#: The action this one wraps, kept for a plugin that predates it.
LEGACY_ACTION = "batch.photo_stage"

#: Every status the plugin documents for a front. ``dry_run`` means the row was
#: only checked and carries no new URL; ``error`` covers a front that failed and
#: a back that failed after its front was staged.
STATUSES = ("staged", "already_staged", "dry_run", "error")

#: How many failed rows the console names before it says "and N more". A batch
#: with two hundred failures is a batch with one cause; the first rows say what
#: it is, and the whole list is in the JSON beside the batch.
SHOWN_FAILURES = 20


def args(batch_dir, stage_out, ready_dir="", cookie_file=None, images_dir="",
         dry_run=False):
    """The command line the plugin documents for ``marketplace.photo_stage``.

    Only what the caller has is passed: ``--images-dir`` defaults to the batch
    folder and ``--ready-dir`` to ``<batch>/cs-ready`` inside the plugin, so
    naming those paths here would be the core guessing at folders the plugin
    already knows. ``--dry-run`` uploads nothing (it may still fetch a remote
    source image when no local file exists).
    """
    argv = ["--batch-dir", str(batch_dir), "--stage-out", str(stage_out)]
    if images_dir:
        argv += ["--images-dir", str(images_dir)]
    if ready_dir:
        argv += ["--ready-dir", str(ready_dir)]
    if cookie_file:
        argv += ["--cookie-file", str(cookie_file)]
    if dry_run:
        argv += ["--dry-run"]
    return argv


def read_stage(path):
    """The staging answer, or ``None`` when there is nothing readable there."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def items(stage):
    """Every row the plugin reported, in its own order, as dictionaries."""
    rows = (stage or {}).get("items")
    return [row for row in rows if isinstance(row, dict)] if \
        isinstance(rows, list) else []


def files(stage):
    """The CSV mappings the plugin wrote: ``{"input": ..., "output": ...}``."""
    found = []
    for entry in (stage or {}).get("files") or []:
        if not isinstance(entry, dict):
            continue
        source, staged = str(entry.get("input") or "").strip(), \
            str(entry.get("output") or "").strip()
        if source or staged:
            found.append({"input": source, "output": staged})
    return found


def status_of(item):
    """A row's status, lower-cased, or ``"unknown"`` when it sent none."""
    status = str((item or {}).get("status") or "").strip().lower()
    return status if status else "unknown"


def tally(stage):
    """How many rows ended in each status, including one this module has not
    met before (counted under its own name rather than thrown away)."""
    counts = {status: 0 for status in STATUSES}
    for item in items(stage):
        status = status_of(item)
        counts[status] = counts.get(status, 0) + 1
    return counts


def staged(stage):
    """The rows whose front is on the site now - new or out of the cache."""
    return [item for item in items(stage)
            if status_of(item) in ("staged", "already_staged")
            and str(item.get("staged_url") or "").strip()]


def failures(stage):
    """The rows the plugin called an error, front or back, in its own order."""
    return [item for item in items(stage) if status_of(item) == "error"]


def _title_of(item):
    return str(item.get("title") or "").strip() or "(no title)"


def _where(item):
    """``row 12, SKU "PKM-006"`` - enough to find the row in the CSV."""
    said = []
    row = item.get("row")
    if row not in (None, ""):
        said.append("row %s" % row)
    sku = str(item.get("sku") or "").strip()
    if sku:
        said.append('SKU "%s"' % sku)
    csv_name = Path(str(item.get("csv") or "")).name
    if csv_name:
        said.append(csv_name)
    return ", ".join(said)


def failure_line(item):
    """One failed row, in the words a person can act on.

    The reason is the plugin's own sentence, quoted rather than paraphrased: it
    is the one thing the app does not know, and the one thing the person
    needs to fix the row.
    """
    where = _where(item or {})
    reason = str((item or {}).get("error") or "").strip() or \
        "no reason was reported"
    return ("%s%s: %s" % (_title_of(item or {}),
                          " (%s)" % where if where else "", reason))


def failure_lines(stage, limit=SHOWN_FAILURES):
    """The failed rows, at most ``limit`` of them, and the size of the rest."""
    rows = failures(stage)
    return [failure_line(row) for row in rows[:limit]], \
        max(0, len(rows) - int(limit or 0))


def ready_csvs(stage):
    """The staged CSVs the plugin says it wrote, as strings (not yet checked)."""
    return [entry["output"] for entry in files(stage) if entry["output"]]


def output_paths(stage, batch_dir=""):
    """The staged CSVs as paths, with a relative answer taken from the batch.

    The plugin is told the batch folder, so a relative ``output`` belongs to
    it; an absolute one is used as given. Nothing is checked for existence
    here - the caller says so when a path the plugin reported is missing.
    """
    found = []
    base = Path(batch_dir) if str(batch_dir or "").strip() else None
    for path in ready_csvs(stage):
        candidate = Path(path)
        if not candidate.is_absolute() and base is not None:
            candidate = base / candidate
        found.append(candidate)
    return found


def fatal_message(stage):
    """The plugin's own reason from an error JSON, or ``""`` when it sent one."""
    for key in ("error", "message", "reason", "detail"):
        value = (stage or {}).get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            inner = value.get("message") or value.get("reason")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return ""


def summary(stage, dry_run=False):
    """One sentence for the panel: what the batch did, in counts.

    It counts what the plugin counted, and it says *dry run* when it was one -
    ``dry_run`` rows have no URL and must never be reported as staged.
    """
    counts = tally(stage)
    total = sum(counts.values())
    if not total:
        return "The staging step reported no rows."
    parts = []
    if counts.get("staged"):
        parts.append("%d staged" % counts["staged"])
    if counts.get("already_staged"):
        parts.append("%d already staged" % counts["already_staged"])
    if counts.get("dry_run"):
        parts.append("%d checked" % counts["dry_run"])
    for status, count in sorted(counts.items()):
        if status in STATUSES or not count:
            continue
        parts.append("%d %s" % (count, status))
    if counts.get("error"):
        parts.append("%d failed" % counts["error"])
    said = ", ".join(parts) or "nothing to stage"
    if dry_run:
        return ("Preview only (nothing was uploaded): %s across %d row%s."
                % (said, total, "" if total == 1 else "s"))
    return "Photos: %s across %d row%s." % (said, total,
                                            "" if total == 1 else "s")


def report(stage, exit_code=0, dry_run=False):
    """Everything the panel says about one staging run.

    ``lines`` are ``(tag, text)`` for the console, ``summary`` is the one
    sentence for the panel's own line, and ``failed`` is the number of rows the
    plugin called errors - which is not the same as the exit code: a batch can
    exit 0 with an ignored back-photo warning, and a partial batch (exit 1) is
    still a batch whose successes were written.
    """
    lines = []
    failed = len(failures(stage))
    if stage is None:
        return {"lines": [], "summary": "", "failed": 0, "known": False}
    if exit_code == 2:
        reason = fatal_message(stage) or "the plugin gave no reason"
        lines.append(("err", "The staging step could not run: %s" % reason))
        return {"lines": lines, "summary": "The staging step could not run.",
                "failed": 0, "known": True}
    text = summary(stage, dry_run=dry_run)
    lines.append(("ok" if not failed else "warn", text))
    shown, more = failure_lines(stage)
    for line in shown:
        lines.append(("err", line))
    if more:
        lines.append(("dim", "  ... and %d more failed row%s. The whole list "
                      "is in the staging answer beside the batch."
                      % (more, "" if more == 1 else "s")))
    written = [Path(path).name for path in ready_csvs(stage)]
    if written:
        lines.append(("dim", "Staged CSV%s written: %s."
                      % ("" if len(written) == 1 else "s",
                         ", ".join(written[:6]) +
                         (" ..." if len(written) > 6 else ""))))
    return {"lines": lines, "summary": text, "failed": failed, "known": True}


def exit_is_ok(exit_code):
    """Whether the batch is worth going on from: 0 clean, 1 partial."""
    return int(exit_code or 0) in (0, 1)
