# Pipeline result-file map and retention audit

The configured pipeline folder now separates marketplace artifacts. Each current batch stays as a normal file until the next output run for that marketplace. At that next run, older files are consolidated into the history shown below; individual older files are removed only after the history has been written successfully. A failed read/write leaves the originals in place.

| Folder | Current outputs | Next-run history / cleanup |
|---|---|---|
| `woocommerce_products/` | `woocommerce_import_*.csv` | `woocommerce_history.csv`, keyed by SKU. Older Woo CSVs are rolled up after a newer Woo CSV is written. The Facebook feed bootstrap reads the current Woo CSV here; it can still read legacy root files during migration. |
| `canadianshopper_products/` | Current `canadianshopper_import_*.csv`, `cs-image-report.csv`, `cs-repoint-report.csv`, and the reusable image cache | `canadianshopper_history.csv`, keyed by title, after a newer CS batch is written. The CanadianShopper **Re-point photos** repair uses cached hosted URLs directly, needs no WooCommerce export, and refreshes its report here. |
| `canadianshopper_products/cs-ready/` | Current import-ready staged CSVs, `back-map.json`, `cs-image-report.csv` in the parent, and the image reuse cache in the parent | `canadianshopper_staged_history.csv` records superseded staged CSV rows after a successful newer stage. Only the current staged batch is sent to the importer. Older `tools/cs-ready` CSVs from previous plugin versions are migrated on the next stage. |
| `ebay_quick_list/` | The current `ebay_quick_list_*.html` handoff page and matching JSON metadata | `ebay_quick_list_history.json` records older pages on the next eBay stage, including the page HTML and listing metadata. Individual old HTML/sidecar files are then removed only after history is safely written. |
| `facebook_merchant_products/` | Current `facebook_delta_*.xlsx`, daily run log, and diagnostic file if a fetch fails | Existing `facebook_history.xlsx` is the consolidated feed history. Older delta/batch exports are cleaned by the next feed run. Dated `facebook_runlog_*.txt` files remain as an audit trail. |

## One-time root-file organization

Use **Logs & reports → Preview old pipeline files** first. If the destinations look right, choose **Move old files into folders** and confirm. The organizer recognizes old Woo, CanadianShopper, eBay Quick List, Facebook, and root-level `cs-ready` outputs. It never deletes or overwrites; a name collision gets a `.migrated-...` suffix. Unrecognized files, input files, credentials, and the image `output/` folder are left alone.

Command-line equivalent from the installed core:

```text
python app/pipeline/organize_pipeline_outputs.py --pipeline-dir "<your pipeline folder>"
python app/pipeline/organize_pipeline_outputs.py --pipeline-dir "<your pipeline folder>" --apply
```

## Other files reviewed

These are outside the marketplace result rollups and may grow or persist by design:

- `output/` contains renamed/split WebP card photos, and `replacements/`
  beside it the fronts and backs cut out of every replacement sheet (tiles live
  under `replacements/_tiles/<sheet>/`). Both are a user-facing image workspace
  and no run deletes from them. They are emptied by the **Older card images go
  to** setting instead: before a new batch writes its first image, the older
  ones are moved into `<setting>/<YYYY-MM-DD HH-MM>/` - straight into that
  folder, in a dated folder of its own per batch,
  after a confirmation. Before that move the tiles that are only background
  are shown as pictures and the ticked ones are **deleted** instead of being
  filed - a blank slot still produces a black tile, and a photograph of
  nothing is not worth keeping. Only images are ever moved or deleted; the
  CSVs and reports in the same folders are records and stay.
- `woo-from-cs/<YYYY-MM-DD HH-MM>/` holds the photos taken off CanadianShopper
  listings when website products are created from them - one folder per run,
  de-squared and saved at 600 px as WebP, named `<card>-front.webp` /
  `<card>-back.webp`. They are what was uploaded, kept so the run can be
  checked; nothing deletes them, and they can be removed like any other image
  workspace.
- `canadianshopper_products/cs-image-cache.json` grows as images are uploaded. It prevents duplicate uploads, so do not delete it casually. The older plugin-side cache is moved here if needed.
- `facebook_runlog_YYYY-MM-DD.txt` accumulates one run log per day; `feed_debug_response.txt` is only written on feed-fetch failure and is overwritten on the next such failure.
- `facebook_merchant_products/helper_last_run.log` holds everything a nested Facebook helper printed on its last failure - the traceback the console used to lose. It is overwritten by the next failing helper and written only when one fails.
- `gui-log.txt` is append-only and can grow over time.
- `output/` and `replacements/` hold WebP files only. A picture named `.jpg`
  whose bytes are WebP (a batch renamed from an image title that carried the
  wrong extension) is renamed to `.webp` in place before the next rename or
  re-run - the bytes are never rewritten and a real JPEG is left alone. This
  is what keeps the eBay Quick List's image links honest.
- `sold-cards-ledger.json` and `sold-cards-checklist.csv` are persistent workflow state, not disposable output. `sold-cards-report.csv` is refreshed by runs.
- `_card_input.txt` is an intermediate file overwritten for each pipeline run.
- `app/quotes/` (or the folder chosen in the quote panel) holds one `<number>.json` per customer quote, with the customer's name, address and the cards, plus the `<number>.pdf` printed from it. It is the user's record of what was promised to whom, so no run cleans it, and it is kept out of Git. `quotes/orders/` holds the order sheets (`order-<number>.pdf`), and `quotes/.images/` keeps the cards' pictures those sheets are drawn with - one file per picture URL, so reprinting an order reads no shop at all.
- `canadianshopper_products/cs-ready/back-map.json` and `cs-image-report.csv` are refreshed during staging. The staged history CSV is preserved separately from the import-ready current batch.

No other core pipeline result file was found that creates a dated, unbounded series in the pipeline root. The GUI log, Facebook daily logs, and image workspace are the main remaining accumulation points.
