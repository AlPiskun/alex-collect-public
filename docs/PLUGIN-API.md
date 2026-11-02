# Alex Collect plugin interface (host API 1)

Alex Collect plugins are optional ZIP packages installed by the user from the
**Plugins** panel. The public core does not download plugin code or contact a
plugin marketplace. Discovery reads `plugin.json`; it does not import plugin
Python modules automatically.

## Package layout

The ZIP must contain `plugin.json` at its root (or one folder below it), plus
the files declared in its `tools` map:

```text
my-plugin.zip
  plugin.json
  tools/
    my_action.py
```

Example manifest:

```json
{
  "id": "example-plugin",
  "name": "Example plugin",
  "version": "1.0.0",
  "host_api": 1,
  "min_core_version": "2.30",
  "description": "A short description shown in the Plugins panel.",
  "capabilities": ["after_sale.stock_update"],
  "actions": {
    "after_sale.stock_update": "update_stock"
  },
  "tools": {
    "update_stock": "tools/update-stock.py"
  }
}
```

The ID is stable and lowercase. `host_api` must match the version supported by
the running core. `min_core_version`, when supplied, must be a numeric version.
Every action must also appear in `capabilities`, and its value must name a tool
in `tools`. Tool paths must be relative to the package and remain inside it.

## Installed location and lifecycle

- Windows: `%LOCALAPPDATA%\AlexCollect\plugins\<id>` (with `%APPDATA%` as a
  fallback).
- Linux: `~/.local/share/AlexCollect/plugins/<id>`.
- Enable/disable state is kept in `enabled.json` beside the plugin folders.
- Plugin code is removed independently from application settings and data.
- Updating is done by installing a newer ZIP with the same ID.

The first host API exposes declared actions rather than arbitrary Tkinter
screens. The current core recognizes the following action IDs:

- `after_sale.stock_update`
- `catalog.zero_stock`
- `batch.photo_stage`
- `batch.photo_wire`
- `batch.photo_replace`
- `batch.photo_cache_repair`
- `batch.pipeline_stage`
- `marketplace.publish_drafts`
- `marketplace.import_csv`
- `marketplace.listing_update`
- `marketplace.photo_stage`
- `stock.set`

The three photo actions are separate jobs even though one script usually
backs them all, so the core resolves each one by ID rather than by filename:

| Action | When the core calls it | Arguments |
| --- | --- | --- |
| `batch.photo_stage` | Preparing a batch (Square + host the photos) | `--mode prepare ...` |
| `batch.photo_wire` | "Wire the photos", and the whole-batch offer in Replace a card's photos | `--mode wire --cookie-file ... --ready-dir ... --cache ...` |
| `batch.photo_replace` | "Wire this card's photos?" in Replace a card's photos | the same `--mode wire` arguments plus `--title <full product name>` |
| `marketplace.photo_stage` | Stage the photos (from plugin 1.0.40; wraps `batch.photo_stage`) | `--batch-dir ... --stage-out ... [--images-dir ...] [--ready-dir ...] [--cookie-file ...] [--dry-run]` |

**`marketplace.photo_stage` (1.0.40) is the one the core asks for by ID.**
It discovers the batch's direct-child `canadianshopper_import_*.csv` files
rather than being handed each one, stages each front, writes the rewritten CSV
into the ready folder, and answers with one JSON file - the per-row report the
older `batch.photo_stage` never had. The core sends:

```
cs-photo-stage.py --batch-dir "<batch>"
  --stage-out "<batch>/photo-stage.json"
  [--images-dir "<folder>"] [--ready-dir "<batch>/cs-ready"]
  [--cookie-file "<cookie.txt>"] [--dry-run]
```

and reads `items[]` (`csv`, 1-based `row`, `sku`, `title`, `status`,
`staged_url`, `staged_csv`, `back_status`, `back_staged_url`, `error`) and
`files[]` (`input`, `output`). Statuses are `staged`, `already_staged`,
`dry_run` and `error`; exit `0` is a clean batch, `1` a partial one whose
successes are still written, `2` fatal - and a safe `--stage-out` then holds
an error JSON whose `error`/`message` the core quotes. The core reads that
answer rather than guessing from the filename: a partial batch updates the
staged history from the CSVs the plugin says it wrote, and every failed row is
named to the person by card, CSV row and SKU with the plugin's own reason. A
relative `output` is resolved from the batch folder, an absolute one used as
given. The source CSVs are never rewritten - that is the plugin's guarantee,
and the core only reads its answer. `--dry-run` reports what the batch would
do, uploads nothing and changes no CSV, so the panel's **Preview the staging
(no upload)** button never claims a staging. A plugin older than 1.0.40 has no
such action, and the core falls back to the documented `batch.photo_stage
--mode prepare` command, which says only what its exit code said.

`batch.photo_replace` is the narrow one, and since plugin 1.0.15 it needs no
staged CSV at all. When a card's photos are replaced the core splits the new
sheet scan, writes the chosen image into a `replacements` folder, and calls:

```
cs-image-sync.py --mode replace --title "<full listing title>"
  --front "<local front image>" [--back "<local back image>"]
  --cookie-file "<cookie.txt>"
```

A card is photographed as a front and a back, and both are replaced, so the
core sends `--front` and `--back` together whenever a back was chosen; `--back`
is omitted only when the card has no back image. The plugin supplies its own
padding and upload; there is no pipeline run, `cs-ready` folder, or staged
cache involved. The core passes the selected
product's full name exactly as the WooCommerce REST API returned it, with no
stripping of a trailing grade, and matching uses the plugin's exact-first
normalized comparison. Exactly one listing must match: zero or several matches
must exit non-zero before any upload or listing write.

`--back` is optional. Without it, the plugin retargets the listing's **primary**
image and leaves every gallery row alone - it does not add a back.

On the website side the same rule holds, so the core applies it too: the old
pair is taken off the product (never deleted - the files stay in the media
library) before the new one goes on, and when the gallery's filenames say
nothing about which photo is the back, the core asks rather than treating the
first row as the only one to replace.

A listing's main front is not a gallery row. CanadianShopper keeps it in a
separate field from the additional images, so **one gallery row is not a
one-photo listing**: that row may be an old back, a certificate, or packaging.
The core therefore never assumes what a lone row is; the plugin asks (see
"Dialog channel" below) and the user decides.

### Version gates

The action ID cannot tell plugin versions apart, because every version since
1.0.14 declares `batch.photo_replace`. The core therefore checks the declared
version as well as the action:

| Feature | Needs |
| --- | --- |
| `--mode replace` without a staged CSV | plugin **1.0.15** or newer |
| `--back` replacing the gallery row | plugin **1.0.16** or newer |
| the publisher's `PUBLISH` question reaching the console | plugin **1.0.27** or newer |
| writing a stock count on the other site (`stock.set`) | plugin **1.0.21** or newer |
| importing a written CSV into the vendor dashboard (`marketplace.import_csv`) | plugin **1.0.23** or newer |
| editing one listing from the app (`marketplace.listing_update`) | plugin **1.0.28** or newer |
| an address, price and state on every `stock.list` row | plugin **1.0.28** or newer |
| a whole-shop comparison that skips product lookups (`--no-product-lookups`) | plugin **1.0.38** or newer |

`--back` was additive before 1.0.16 - it added the new back beside the old one
- so sending it to 1.0.15 would leave the previous back photo on the listing.
Plugin 1.0.16 replaces the row that matches the pair; plugin 1.0.17 asks the user
when it cannot identify that row instead of stopping. No new gate is needed for
either: the arguments and action IDs are unchanged, so a 1.0.16 copy that can
identify the pair keeps working exactly as it does today.

Plugin 1.0.18 changes nothing in the contract - it hardens the plugin's own
console fallback so a stray `{}` answer from a core without the `pick_back`
handler (2.48 and older) is ignored and re-prompted rather than consumed, and
blank or unrelated lines no longer cancel. Core 2.49 answers `pick_back`
properly, so the fallback is not reached there. No core change is needed for
1.0.18.

Where the pair cannot be identified and the plugin predates 1.0.17, the core
sends the front alone and says why, rather than producing a listing with two
backs. Below 1.0.15 it refuses the path entirely and shows an "update the
plugin" message rather than risking the CSV error.

Whole-batch wiring remains a separate action (`batch.photo_wire`) in its own
panel.

### Nested tools: streaming, and `ALEX_COLLECT_NESTED` (1.0.27)

Everything the core runs is watched: the app streams a tool's stdout into the
console the person is reading and writes their typed answer to its stdin.
A plugin tool that runs **another** tool of its own has to keep that chain
intact, because a question asked by a grandchild is just as invisible as a
question asked by the tool itself.

The rule:

- run children with `stdin=sys.stdin`, `stdout=sys.stdout`, `stderr=sys.stderr`
  and `text=True` - never `capture_output=True`, `stdout=PIPE` or `input=...`;
- print and **flush** a confirmation question before reading the answer, even
  when stdout is a pipe (`print(question, flush=True)` or `sys.stdout.flush()`);
- the core may set **`ALEX_COLLECT_NESTED=1`** in the environment. It does that
  for every tool it launches, and again before `batch.pipeline_stage`, so a
  batch folder run from a terminal gets it too. When it is set, print a line
  before and after each child so the console is never silent for long. A
  plugin that ignores the variable loses nothing; it simply cannot add the
  progress lines.

Why it is a rule: the publisher (`marketplace.publish_drafts`) waits for the
word `PUBLISH` on stdin. Plugin 1.0.26 ran it with its output captured, so the
question never reached the console, the answer was never typed, and the run
looked frozen. 1.0.27 streams it; the core names the version in the console
when the plugin is older, and after 20 s of silence at
*Publishing ready CanadianShopper drafts* it says what to type.

`ALEX_COLLECT_NESTED` is a hint, not a gate: the core makes no decision on it
and no action changes shape.

## Progress channel

A tool that is about to work through many items can put a bar above the app's
console instead of only printing lines. It writes to stdout, once per event:

```
\x1eALEX_COLLECT_PROGRESS:{"index":3,"total":9,"stage":"photos","item":{"name":"Card name"}}\x1f
```

- `index` is the item being worked on (1-based) and `total` is how many there
  are. The bar fills as `index` grows.
- `stage` is free text. The app has clear words for `start`, `photos`,
  `create`, `attach`, `publish` and `done`; any other value is shown as it
  arrives rather than ignored.
- `item.name` is what the person recognises. Keep it short: the bar shows one
  line, and the tool's own printed lines still say everything else.
- The marker is hidden from the console, so a tool must keep printing its
  plain lines too - the marker is for the bar, not for the reader. A run that
  prints markers and nothing else looks like a run that says nothing.
- Progress is optional in both directions: no marker means no bar, and a
  malformed marker is dropped. Nothing a marker does can fail the work.
- **`{"stage": "finish"}` takes the bar down** and means "this step is over";
  `index`/`total`/`item` are not needed with it. Send it when your step ends,
  not when the whole run does: a batch goes on to other tools afterwards, and
  a bar left at the last item through all of that reads as work that has
  stopped. Nothing later in the same run redraws the bar unless a new item
  emits `start`; the bar is also taken down when the process ends, whatever
  it printed.

The card pipeline writes these only when `ALEX_COLLECT_NESTED=1` (the app
sets it), so the same script run in a terminal prints plain lines and never
shows a marker.

## Dialog channel

A tool can ask the app a question and get a structured answer, instead of
printing a prompt and hoping someone types the right thing. The tool writes to
stdout:

```
\x1eALEX_COLLECT_DIALOG:{"type":"<type>", ...}\x1f
```

- `\x1e` (0x1e) starts it, then the literal text `ALEX_COLLECT_DIALOG:`, then one
  JSON object, then `\x1f` (0x1f).
- The app hides the whole marker from the console, shows a real dialog, and
  writes the answer to the **tool's stdin** as one JSON line, which the tool
  reads with `sys.stdin.readline()`.
- If the app does not know the type it answers `{}` - *and still writes it to
  stdin*. A tool that falls back to its own console prompt must therefore skip
  lines that are not an answer it recognises, or it will read that `{}`.

| Type | The app answers |
| --- | --- |
| `confirm_cs` | `{"answer": "yes"}` or `{"answer": "no"}` |
| `match_cs` | `{"matches": {"<index>": "<product id>"}}` |
| `pick_back` | `{"row": "<gallery row id>"}`, `{"row": null}`, or `{"cancel": true}` |

### `pick_back` - which gallery row is the card's old back?

Sent when a listing's existing photos cannot be identified automatically. The
app shows the row filenames with their positions and a picture of what is being
replaced, so this is decided by looking rather than by guessing.

```json
{"type": "pick_back",
 "title": "1972-73 O-Pee-Chee Dave Burrows #133 Rookie Card",
 "front": "133-Dave-Burrows-front-2.webp",
 "back": "133-Dave-Burrows-back-2.webp",
 "rows": [{"id": "13820", "filename": "burrows-133.webp",
           "url": "https://...", "sortOrder": 1}],
 "allow_add": true}
```

- `{"row": "<id>"}` - replace exactly that row with the new back. This is the
  row's **ID**, not its display position.
- `{"row": null}` - keep every row and add the new back beside them. Only
  answered when `allow_add` is not `false`.
- `{"cancel": true}` - stop before any upload or listing write. A dialog that is
  closed without being answered answers this, so a stray click changes nothing.

A row with no `id` is refused rather than guessed.

### The pair contract

A card is photographed front and back, so the core always sends both halves
together, and the two local filenames differ only by `-front`/`-back`:

```
gretzky-front-2.webp
gretzky-back-2.webp
```

The counter is shared, so a number taken on either side moves the whole pair
to the next one; a pair is never written as `front-1` beside `back-2`. The
plugin verifies the pair before uploading and identifies the listing's
existing back photo by filename, so core guarantees the naming and does not
send the names separately - the paths are enough.

If the plugin cannot positively identify the existing back, it stops before
uploading or writing anything. The core surfaces that outcome and offers the
recovery path: run the card again and choose no back image, which replaces
the front only.

The core invokes a tool only when a user selects the relevant action. For
`batch.pipeline_stage`, the hook may define `run_stage(output_paths, args,
script_dir, output_dir, tools_dir=..., cookie_file=..., browser_name=...)`.
Optional keyword arguments are passed only when the hook signature accepts
them, preserving compatibility with older plugins. `browser_name` is the
configured browser ID (or an empty string when no preference is set). The
core never executes browser bookmarklets. New capabilities require a
corresponding core integration; merely declaring a new capability does not
add UI controls or run code.

## Writing on the marketplace

Two actions change the other site, and both are called only after the person
has confirmed exactly what will change. The core starts one only when the
plugin declares it; a plugin without it gets a message naming the version
that added it and what to do by hand, never a half-done job.

### `stock.set` - writing a stock count (plugin 1.0.21)

Reading the other site's stock is all the comparison can do on its own. With
`stock.set` declared, the panel can also write one listing's count, and the
direction is fixed and named in every line of the confirmation: **your
website's count goes onto the other site**. Your website is never changed by
it.

```
cs-stock.py --set-file "<plan.json>" [--cookie-file "<cookie.txt>"] --set-out "<result.json>"
```

The plan file is written by the core, one entry per card, and every entry
names the listing three ways because a plugin may know it by id, by SKU or
only by its title:

```json
{"items": [{"id": 13820, "sku": "OPC1971-001-PR-2",
            "title": "1971-72 O-Pee-Chee Test Card #001 (PR)",
            "card": "1971-72 O-Pee-Chee Test Card #001 (PR)",
            "from": 2, "to": 1}]}
```

- `from` is the count the reader last reported; `to` is the website's count.
  The plugin writes `to`.
- Only a listing that is **on sale** is ever in a plan. A draft, hidden or
  archived listing is a row of its own on the panel (`stock.set` cannot fix
  it), and a listing with no stock count is never sent either - there is no
  number to write, and inventing one is how a card that cannot be bought
  starts claiming it can.
- Every id, SKU and title in the plan is a real listing the reader returned.
  Nothing else is being asked for: no titles change, no prices, no listings
  are added, archived or republished.

The result file is the plugin's answer, and it is what the panel reads:

```json
{"updated": [{"id": 13820}],
 "failed":  [{"id": 13821, "why": "that listing is not on sale"}]}
```

- An entry is matched to the plan by `id` (also accepted: `product_id`,
  `listing_id`), then by `sku`, then by `title`, `card` or `name`. The id
  wins when both sides have one, because two cards in one set are exactly
  similar enough for a title match to land on the wrong listing.
- `why`, `reason`, `error` and `message` are all accepted as the failure's
  sentence; it is shown to the person unedited.
- A card the result does not mention is **unknown**, never assumed written:
  it stays on the list and the console says so.
- The core always passes `--set-out`; write the result there. A run that
  writes no result is treated as reporting nothing, so every card stays on
  the list. Pressing **Compare again** is the confirmation the panel offers
  afterwards, so a plugin does not have to read its own write back.

Exit non-zero to mean *nothing was written*: the core takes that at its word,
leaves the list exactly as it was, and names the exit code. A partial write
with a zero exit is the one shape that cannot be reported honestly, so a
plugin that writes several listings should report the ones that failed in
`failed` rather than exiting non-zero after a success.

### `marketplace.import_csv` - importing a written CSV (plugin 1.0.23)

Listing a card on the other site is done by writing the same CSV the batch
pipeline writes and importing it. With `marketplace.import_csv` declared the
core can do the import as well; without it, the file is written, the folder
is opened, and the panel says where the import lives in the vendor dashboard.

```
cs-import.py --csv "<file>" [--csv "<file>" ...] [--cookie-file "<cookie.txt>"] --result "<result.json>"
```

- `--csv` is repeated once per file, in the order they were written. The core
  names them itself (`canadianshopper_import_<stamp>_NN_of_MM.csv`, 500 rows
  per file) and imports **only** the files it passes - a run must not sweep a
  folder for more, because an older batch may be sitting in it.
- `--cookie-file` is passed only when the file exists.
- `--result` is where the answer goes, and it must be written even when
  nothing was imported:

```json
{"imported": [{"file": "canadianshopper_import_20261030_120000_01_of_02.csv",
               "drafts": 3}],
 "failed":   [{"file": "canadianshopper_import_20261030_120000_02_of_02.csv",
               "why": "every listing in this file already exists"}]}
```

- Every listing is created **unpublished**: nothing is published and nothing
  goes live. The panel offers the publisher as the next step.
- A file is named by `file`, `csv` or `path`; the core compares basenames, so
  an absolute path is fine.
- `drafts` may be omitted, then `rows` is used, and then the row count the
  core wrote. A file named in neither list is **unknown** - the core says so
  and tells the person to check the dashboard before importing again, rather
  than assuming the drafts exist.
- "Every listing in this file already exists" is a legitimate, useful answer,
  not a failure to be dressed up: it means the card already has a listing
  that the reader could not see, and the core says exactly that.
- Exit non-zero when the import did not finish. The CSV is still in its
  folder and can be imported by hand.

### `marketplace.listing_update` - changing one listing (since plugin 1.0.28)

The core's **Find and edit a CanadianShopper listing** panel searches the
catalogue `stock.list` returns and can change one listing's title, price, stock
or state from the app. Without this action the panel still reads and searches -
it just says it cannot write, and names the version that can.

```
cs-listing-update.py --set-file "<plan.json>" --set-out "<result.json>" [--cookie-file "<cookie.txt>"]
```

The plan is one entry per listing: the fields that identify it (`id`, `sku`,
any other id `stock.list` reported, `url`, and `title` as it stands), plus
**only the fields that change**. A field that is absent must be left exactly as
it is on the site:

```json
{"items": [{"id": 13820,
            "sku": "OPC1973-25",
            "title": "1973-74 O-Pee-Chee Walt Tkaczuk #25 EX-MT Rangers",
            "card": "1973-74 O-Pee-Chee Walt Tkaczuk #25 EX-MT",
            "price": "9.50",
            "inventory": 2,
            "status": "active"}]}
```

- `id`, `sku` and the old `title` identify the listing, in that order of
  confidence - the same rule `stock.set` uses, so one listing is never mistaken
  for its neighbour in the set.
- **Any other id `stock.list` reported travels with the plan**, under the name
  the reader gave it: `product_id`, `productId`, `listing_id`, `post_id`,
  `wp_id` and the like. A catalogue's listing and the product its API patches
  are not always the same key, and the writer must get both - with only the
  listing id it can address a resource the site does not know, which is a 404
  and no change at all. `url` (the row's own address) is passed for the same
  reason. **The ids in the plan are exactly what `stock.list` emitted**: the
  core never invents, derives or rewrites one, so a writer that needs the
  product key must emit it.

  A listing's `id` is its catalogue id and is **not** a product id. When the
  vendor supplies a product id, `stock.list` must report it as `product_id`
  (or `productId`) and the update action must build its
  `/api/products/<product_id>/` path from that key alone. A listing with no
  product id is a listing this action cannot patch: report it in `failed` with
  a sentence saying so, before any request is made. It must never be guessed
  from the listing id, a slug or a title - a guess that hits another listing
  edits the wrong card and reports success.
- `title`, when present, is the **new** title. `card` is always the old one, so
  a log line can say what the listing was.
- `price` is a decimal string; `inventory` is an integer (`0` is a real count);
  `status` is `active` or `archived` and means exactly that - nothing else is
  republished or unpublished by it.
- Nothing is ever added, deleted or duplicated by this action, and no other
  field (description, photos, categories, shipping) is sent at all. The
  description and the photos are the vendor dashboard's job, which is what the
  panel's **Open the selected listing** button is for.

The result file is the same shape as `stock.set`, read the same way:

```json
{"updated": [{"id": 13820}],
 "failed":  [{"id": 13821, "why": "that listing is protected"}]}
```

- An entry may be named by `id` (also `product_id`, `productId`, `listing_id`,
  `post_id`), `sku`, `title`, `card` or `name`; the id wins when both sides
  have one, and **any** of the ids the plan was given counts - a writer that
  resolves the page id to the product id and answers with the product id is
  confirming the same listing.
- `why`, `reason`, `error` and `message` are all accepted as the failure's
  sentence, and it is shown unedited.
- A listing the result does not mention is **unknown** - the panel says it
  cannot confirm the change and leaves the row as it was. Exit non-zero to mean
  *nothing was written*: the panel takes that at its word.

A writer that refuses a listing because it has no explicit product id is
answered by the app, not by the person. The panel asks **before** it spends a
write that could only fail: a row with no product id in the list on screen gets
"read the listings again?" rather than a doomed request, because the difference
between an old list and a listing the site gives no product id for is exactly
one read. After the read it **re-plans the same change** from the fresh row -
matched by the id that was being edited - and asks for it once more before
writing. If the fresh row still has no product id, it says so and leaves the
listing for the vendor dashboard. The plugin's own sentence is still printed,
unedited, in the console, and a refusal that arrives anyway is read the same
way.

When any of this fails, the panel prints the failure in the plugin's own words
and then **how the plan named the listing** - `The plan named it: id
14effcaceb8a4b66b6f14e7aded86e2d, product id 4321, SKU OPC70-81` - because
"not found" is a question about which listing was addressed. A 404 is called
what it is: the reader and the endpoint the plugin writes to are naming the
listing by different keys, nothing on the site was changed, and the fix is in
the plugin, not in the app.

### Reading to compare, and reading to edit

`stock.list` is called for two different jobs, and they do not need the same
work done:

| Job | What the core does with the rows |
| --- | --- |
| Compare stock (and list the catalogue) | pairs each listing with a website product by id, then SKU, then title, and writes a count to the listing it matched. **It never reads `product_id`.** |
| Edit a listing | addresses the vendor's own update endpoint with the listing's `product_id`, so every row needs one |

Because a comparison needs no product ids, the core asks the reader to skip
them:

```
cs-stock.py --stock-out "<cs-stock.json>" --no-product-lookups [--cookie-file "<cookie.txt>"]
```

`--no-product-lookups` means: read the catalogue, and do **not** fetch each
listing's own product record. Every other field is unchanged - title, SKU,
inventory, status, price, address, images - and rows simply carry no
`product_id`. The point is cost: a reader that resolves product ids makes one
request per listing, and on a 2,600-listing shop that is the difference between
a read that takes seconds and one that takes half an hour.

It is **optional**, and a reader that does not implement it must keep failing
the way any unknown argument does - Python's argparse exits **2**. The core
treats exit 2 as "this reader does not take that flag", drops it and asks again,
keeping the flags that were not the problem; the person sees one line saying the
read will be the slow one. No version check decides this, so a reader that
implements the flag starts benefiting immediately, whatever version it
declares.

The edit panel never passes it: a listing without a product id cannot be
written from there.

#### Progress while reading

A read may take minutes, and a console that shows one line and then nothing is
indistinguishable from a frozen window. A reader that can say where it is
should emit the progress marker documented under "Dialog channel" - the same
`\x1eALEX_COLLECT_PROGRESS:{...}\x1f` channel every tool uses:

```
\x1eALEX_COLLECT_PROGRESS:{"stage": "read", "index": 850, "total": 2587, "note": "reading listings"}\x1f
```

`stage` is any short word, `index`/`total` drive a real bar (both must be
positive), and `note` is the phrase shown to the person. Emit it during the
catalogue read and during any lookup phase (e.g. `{"stage": "ids", "index":
412, "total": 2587, "note": "resolving product ids"}`), at least every few
seconds. The markers are only read when `ALEX_COLLECT_NESTED` is set, so a
reader run by hand prints nothing odd.

### What a `stock.list` row carries (since plugin 1.0.28)

The listing panel shows a numbered row as **card - state - stock - price -
SKU**, and links to the listing's own page. A row already has `title`/`name`, `sku`,
`inventory` and (since 1.0.25) `status`; from 1.0.28 it also carries:

| key | meaning |
| --- | --- |
| `price` | the listing's price, as the vendor shows it (`"CA$8.50"` and `"8.50"` are both read) |
| `url` | the listing's own page address |
| `product_id` | the id the update action patches, when the vendor supplies one and it differs from `id` - a string, exactly as the vendor gives it (since 1.0.34). Never `0` - a listing whose vendor data carries none has no key at all |
| `images` | since 1.0.32: the listing's pictures, absolute `http(s)` addresses, the primary picture first and then the gallery in the vendor's own order |

Reported since plugin **1.0.33**, when the vendor's product response already
holds them, and worth reporting because they save the core a page read:
`description` (the listing's own words, HTML is fine), `short_description`,
`keywords` or `tags`, and the card's own facts - `condition`, `grade`, `year`,
`set`, `set_name`, `card_number`, `player`, `brand`, `language`, `sport`.
Anything empty is left out rather than sent as an empty string, and nothing is
inferred from other fields: a row without them reads exactly as it did before.
The core ignores capitalisation, underscores and spaces on those keys, so
`cardNumber`, `Card Number` and `card_number` are one key.

"Create website products from CanadianShopper-only listings" copies all of
them onto the new draft: `description` becomes the product's description (its
tags stripped, its paragraphs kept), the keywords and the facts become
WooCommerce tags and attributes, and the pictures are uploaded with the first
one as the product's main image and the rest in its gallery. A reader that
reports none of them costs one read of the listing's own page, where the core
looks for structured data, the page's description meta tags and a block named
like a description. A row that reports the description **and** keywords costs
no page read for them at all; a row with only one picture still costs one,
because the card's back is on its page. Nothing is invented: with no description anywhere the
product's description is left empty and the console says so.

`product_id` is the only key with a write behind it: everything else on a row
is for display. A row without one still lists, searches, prices and opens -
the edit form still opens on it - and the plugin answers the write with the
reason it could not be made. The core counts them after every read and says
so ("`12 listings read; 10 with a product id, so 10 can be edited here`"), and
a plugin that summarises `listings: N, with product id: M` in its own console
line is saying the same thing in its own words - the two numbers agree because
both count the rows the reader emitted.

**`with product id: 0` is a bug report, not a shop.** When no row in a read
carries one, the core stops offering to re-read and says the reader is not
reporting product ids: a second reading of the same catalogue returns the same
nothing, and telling someone to edit 2,541 listings in the dashboard would be
advice that costs them an evening. Nothing on either site is changed by any of
this, and the panel still searches, opens and links each listing. The fix
belongs in the reader: emit `product_id` for each row the vendor's data gives
one for.

**`0` is not an id, and since core 3.09 it is not treated as one.** A row that
says `"product_id": 0` is a row without a product id: no product has id 0 on
any of these sites. So the core counts it as missing rather than as editable,
never puts it in a plan, never sends `PATCH /api/products/0/`, and never
explains a failure with "product id 0" - the sentence would send someone
looking for a product that cannot exist. It also tells the two apart on the
console: *no listing in that read carried a product id* is a reader with the
key missing, while *the plugin reported product_id 0 for all 2,541 listings* is
a reader emitting a placeholder, and the second one is a defect in the reader
even if the first is not.

**Plugin 1.0.34 is the version that reports them properly** - it was released
for exactly this. It emits each listing's real product id as a string
(`4321` becomes `"4321"`, and an opaque id such as `"14effcaceb8a4b66"` is left
alone), omits `product_id` entirely when the vendor's data has none (missing,
null, empty and zero-like references all take that path), never substitutes the
listing id, the slug, the title or the URL, and refuses a zero-product update
before `/api/products/0/` is ever called. Its console reports measured totals -
listings, real ids, absent keys - so a regression is visible in the log.

**Plugin 1.0.35 is the version that fills the gap.** When a listing's own
payload carries no product reference, 1.0.35 resolves one through the
single-listing endpoint, reusing `stock.set`'s exact SKU matching: an
unambiguous SKU becomes a product id, an ambiguous one stays without one, and
only the resolved id is copied from the detail data - every other field still
comes from the stock read. The lookups are cached per listing for the run. Its
own line for the 2,587-row fixture is
`2587 listings, 2587 with a real product id, 0 without the key, 0 reported as 0`.

Two consequences the core handles, and a reader should know about:

- **An id is an id however it is written.** `"4321"`, `4321`, `" 4321 "` and
  `4321.0` are compared as one id, so a result file that answers with a number
  after a plan that carried a string still confirms the change instead of
  reading as *unknown*. An opaque id (`14effcaceb8a4b66`) and a number-shaped
  code with a leading zero (`0012`) are compared exactly as given.
- **Two listings can now resolve to one product.** A duplicate listing, or two
  SKUs the vendor maps onto the same product, gives the same `product_id` to
  more than one row - and an edit addressed by that id changes what every
  listing sharing it shows. The core counts this after every read and prints
  one line naming the product and the listings, rather than letting a
  single-row confirmation stand for both.

The core names the version. A read with no usable product id is told apart by
which plugin produced it: from anything older than **1.0.34** the console says
updating the plugin is the fix, and from **1.0.34 or newer** it says the read is
a defect in the reader worth reporting, because by then it is one. Nothing about
a listing is changed either way.

**The reader's own line is quoted.** A reader that summarises a read in the
shape `stock.list: 2596 listings, 0 with a real product id, 2596 without the
key, 0 reported as 0` has those four numbers repeated in the core's sentence,
because they are what a defect report is built from - and because `without the
key` and `reported as 0` are different bugs. The core also says which read it
was: the comparison asks for `--no-product-lookups` (and its rows having no
`product_id` is the flag working), while the edit panel never passes it and
expects ids - so a read there with none means the lookups did not run or every
one came back empty. A reader that prints no such line costs only the generic
sentence; one that prints it makes the next report a one-liner.

**The reader prints its own resolution counts.** From plugin **1.0.39** every
successful ordinary read ends with a line like:

```
Stock resolution: 2596 detail requests, 0 usable references, 2596 HTTP 200s without a usable reference, 0 ambiguous SKUs, 0 hard failures
```

Detail requests include failed attempts; usable references come from detail
responses (direct ids and cache hits do not inflate the HTTP counts); the older
`Stock read: … lookups failed` line still comes last when anything failed; and
the `ids` stage is still emitted even when nothing resolves. Its scope is
confirmed and deliberately narrow:

- a read whose **every** detail request failed at the transport level still
  prints the line (`… 0 usable references, 0 HTTP 200s without a usable
  reference, 0 ambiguous SKUs, N hard failures`), followed by the older failure
  line - the catalogue read completed, only the lookups did not;
- a read of an **empty catalogue** prints it too, all five numbers zero;
- a **fatal** session or catalogue failure is a different path: the read ends
  with its error, no resolution happened, and no line is printed;
- a `--no-product-lookups` read is the comparison's own read: it performs no
  detail lookup, its rows are expected to carry no ids, and the core never
  prints the gap sentence for it. Whether that read also prints the resolution
  line is the reader's business - the core only uses one when it is there.

The core reads all five numbers, quotes the line verbatim in the console and in
a diagnosis file, and - this is the part that matters - lets them decide who is
being reported. A read whose every answer came back HTTP 200 and named no
product is **the vendor's data, not a defect in the reader**: the core says so,
names the counts it is relying on, and stops short of the "report this to the
plugin's author" verdict it gives when the counts are absent. Before 1.0.39
that verdict could only be a guess, so a current-but-older plugin (1.0.34 to
1.0.38) is told that 1.0.39 prints the counts that settle it. An ambiguous SKU
is named as one - more than one product matched, so no id was invented - and a
hard failure is still a failure. A read that mixes both is said to be two
things: the answers that came back 200 and named nothing are the vendor's data,
while the ones whose request failed were never read at all and a re-read may
still resolve them - so the "reading again cannot fix these" sentence carves
them out rather than writing them off.

**No server-side resolver behind the write.** `marketplace.listing_update`
matches the listing by id, SKU or old title - and refuses a multi-match - but
it will not write without an **explicit** product reference in that listing's
own record: it PATCHes `/api/products/<product_id>/` and, if the matched
record names none, it fails before any request rather than guessing. There is
no listing-to-product resolution on the write path in 1.0.39, and the generic
`/api/data/product/<listing-id>` record is not written to. Two consequences the
core states rather than leaves to be discovered:

- A read whose resolution line says every answer came back 200 and named no
  product is **settled**, not pending: those listings cannot have their title,
  price or state changed from the app, and reading again cannot change that.
  The console says so in those words and points at the vendor dashboard.
- **Stock counts are unaffected.** `stock.set` addresses the listing itself, so
  the comparison panel still writes counts for exactly those listings.
- If a vendor ever confirms that the write route accepts the listing id - or
  that the reader may resolve it server-side and refuse a non-unique answer -
  that is a new, verifiable contract and a change on both sides, not something
  to infer from a GET response.

**Asking the route instead of guessing.** One `OPTIONS` request to the same
`/api/data/product/<listing-id>` address answers most of that question without
writing anything, so **Save a read diagnosis...** makes it and records the
answer:

- `Allow: … PATCH …` (or `PUT`) - the vendor's own route states it accepts a
  write, at the address the listing id already names. That is evidence the
  product id is not needed *to address* the record; which fields it accepts is
  still unproven, and the core says so rather than acting on it.
- `Allow: GET, HEAD` only - the route is read-only and "not editable on
  CanadianShopper" is final for title, price and state.
- `405`, `501`, or `204`/`200` with no `Allow` header - inconclusive. Many
  servers answer `OPTIONS` that way without meaning the route is read-only
  (`204 No Content` is a common "handled, nothing to say"), so the core reports
  it as unanswered, never as a refusal - and never as permission. No write is
  attempted on such an answer and none is designed from it; the question stays
  open.
- No answer at all (offline, refused) - said to say nothing either way.

`OPTIONS` carries no body: it cannot change a listing, and the file says so
beside the answer. The probe is one extra request per diagnosis, never part of
a read.

**What each answer licenses, agreed with the plugin's author.** The method
answer is a gate, not a decision to edit:

- **`GET, HEAD` only** - no listing-record write path is added; "not editable on
  CanadianShopper" is final for those fields.
- **`405`, `501`, no `Allow`** - inconclusive; no write is attempted and none is
  designed.
- **`PATCH` or `PUT` advertised** - the method is established and the field
  behaviour is not. The next step is a controlled proof, not an implementation.

A no-op `PATCH` (carrying the values a listing already has) is **not** that
proof on its own: a server can accept a request and silently ignore a field, so
a 200 shows only that the route tolerated it. Field behaviour needs the vendor's
documentation, a response schema that establishes it, or a controlled,
reversible change on a listing set aside for the purpose - read back before and
after and compared over the whole record, timestamps and unrelated fields
included, since even a no-op request may have side effects.

If that proof arrives, the work is a **listing-record write path**, kept
distinct from the dual-ID one: it addresses `/api/data/product/<listing-id>`
with the record's own id, never calls that id `product_id`, matches exactly and
refuses an ambiguous match, sends only fields proven accepted, and leaves the
existing `/api/products/<product_id>/` behaviour untouched for records that do
carry an explicit product reference. Until then the updater does not change.

**Proving a field, one listing at a time.** A `PATCH` that advertises itself,
or a vendor's own tool seen writing a field, settles the method and that one
field; every other field still needs the controlled, reversible change above.
**Prove a field can be written** - beside **Save a read diagnosis...** in the
edit panel - runs exactly that proof:

- one listing, chosen in the list, addressed at
  `/api/data/product/<listing-id>`: the record's own id, never called
  `product_id`, and never the product id from `/api/products/<product_id>/`;
- exactly one field per run: `priceCad`, `title`, `description`, `inventory`, or
  `primaryImageUrl`;
- the trial value is marked and reversible - a cent above the price, ` PROOF`
  on the title (cut first when the title is near a marketplace's limit), one
  dated marker line on the description, one more card on the count, and for the
  main photo a URL from the image staging step that shows the same card, since
  a proof must not show a shopper a different picture. That URL is found in the
  pipeline folder's staged `canadianshopper_import_*.csv` (the newest batch
  first, by the card's exact title, and only an `/api/file/` row the staging
  step has already rewritten), or pasted by hand when no staged row exists;
- the record is read first and the plan is made from **that** read, so a value
  changed in the dashboard while the panel was open is never "restored" to an
  older one;
- `status` is never proven: archiving a live listing and putting it back is not
  the same record it was, and a visibility change is not something a proof
  should do to a live listing to find out;
- the old value is written back and the record is read a third time, so the
  verdict separates the three answers a site gives: **written** (the record
  shows the trial value), **ignored** (the site answered 200 and the record did
  not change - a 200 is never proof on its own), and **refused** (not a 2xx),
  plus unreadable/unknown when a read fails. A write that cannot be read back
  is not called proven, and the old value is put back anyway.

Each proof writes a small `cs-proof-<date>.txt` beside the app - the listing,
the record's address, the field, before / wrote / read back / put back / final,
every status and what it settles, with no cookie, token or password - and
`cs-field-proofs.json` remembers which fields the last proof left written **and
put back**. A refusal, an ignored write or a failed restore replaces that entry:
a proof that stopped being true is worse than none.

**What a proof licenses: the record write path.** `priceCad` has that evidence
on this shop - a proof written to `/api/data/product/a2304e72…`, read back as
`1.01`, restored to `1`, and read back again as `1` - so the price is the one
field confirmed written on the listing-record road (`cs_record.py`) today. The
road itself is not the price's: every field the proof module can settle -
`priceCad`, `title`, `description`, `inventory` and `primaryImageUrl` - travels
it, and each one opens only when its own proof is saved, so the list of
writable fields is whatever `cs-field-proofs.json` says it is. `status` never
travels it (`cs_proof.UNPROVABLE`), for the reason the proof module gives.
Every write on it is gated on the proof file, not on a version number:

- **no saved proof, no write.** `cs-field-proofs.json` is read before every
  write; a field whose last proof was refused, ignored or failed to restore is
  not written. Delete the file and the path closes again.
- **the record's own id is the address**, and the record must name that same
  id. A record at that address naming a different id - or no id at all - is
  never written, however sure the panel is about the listing.
- **the values the person confirmed must still be there.** The record is read
  before the write; if it now shows another price, title, description or stock
  count, nothing is sent and the panel says what it found. A confirmation
  about `8.50` can never become a write of something else. (The main photo is
  exempt from that comparison, not from the read: a catalogue row carries the
  shop's own URL while the record carries the site's hosted file, so a
  difference there is normal - the read-back still proves what happened.)
- **only the changed fields are sent, in one request.** A form saved untouched
  sends nothing; a form that changed the price and the title sends
  `{"priceCad": "12.50", "title": "..."}` and nothing else, so no field can
  move with another.
- **read back after the write, field by field.** `written` means the record
  shows the new value for that field; a 2xx whose read-back still shows the old
  one is reported as *ignored* for that field and the edit as *partial* if
  another field was kept; a write whose read-back cannot be read is *unknown*,
  and says so rather than claiming success.
- **a zero price is refused** (a marketplace zero is almost always a mistake),
  and so is a negative or non-whole stock count, an empty or over-80-character
  title, a description emptied by accident, and a main photo that is not an
  `http(s)` address. The website is never touched.

A row the plugin cannot address is routed, not dead-ended: with at least one
proven field, **Edit the selected listing...** says that the plugin's edit form
cannot send a title, stock count or state and offers the record road instead -
the price dialog when the price is all that is proven, the field form when more
is - and the read's summary names the fields that are blocked rather than
saying "none can be edited here".
A read in which no listing carries its own address is reported once as a reader
gap - the same way a read with no product ids is - so the vendor's author gets
the version and count line that explains it.

The price is offered in two places - the CanadianShopper edit panel for one
listing (the road that works when the vendor reports no product id), and the
stock comparison panel for every compared card whose price differs (each
written and read back on its own, one listing at a time, so a wrong id cannot
take a run with it). The edit panel's **Edit the record's fields...** is the
form for all five: every provable field on one screen, filled with what the row
says it holds, a proven field typeable, an unproven one greyed with **Prove
this field...** beside it. The edit panel still writes title, stock and state
through `marketplace.listing_update` and `/api/products/<product_id>/` for rows
that have a product id - two roads to the same listing, and the record road
needs no id at all. No unattended or scheduled write is added for any field.

**The core's own calls are gated on the plugin being installed.** Four
features in this core talk to the site's API directly rather than through an
action: the field proof (`cs_proof.py`), the record write path
(`cs_record.py`), its bulk use in the comparison panel's *Set CanadianShopper
to the website's prices...*, and the read-only diagnosis probe
(`GET`/`OPTIONS` on a listing's record). The plugin is what owns that
conversation - it holds the session cookie and the actions the vendor
documents - so all four are offered **only while the plugin is installed**
(`gui.cs_plugin_installed`): without it each button says the plugin is what
talks to the shop and sends nothing, instead of reaching past the plugin to
an API nobody installed. That is the rule for anything new here that would
touch the vendor's API: it belongs in the plugin as an action, not in the
core. The plugin's author agreed to take those four behind versioned
actions - a proposed `marketplace.record_update` (opaque `listing_id` and
the fields to change, answering `before`, `after`, `applied_fields` and an
error) and `marketplace.record_proof` (the same identity input, answering
the before/after records and `proven_fields`). Neither is implemented or
claimed in 1.0.40, so the gated direct calls above are the interim: the
core moves to the actions when a plugin declares them, and until then the
proof file is still the only thing that lets a field be written.

**A hard-failure report, if the failures turn out to be deterministic.** The
counts do not say which listings failed, and a read caches no failures, so a
re-read repeats every unresolved detail request. If the same listings fail
again, the additive shape agreed on is an optional report with one entry per
failed listing - `listing_id`, `kind` (`http` / `transport` / `json` / `empty`),
`http_status` where there is one, and a short sanitized reason - leaving the
`Stock resolution` line byte-identical and changing neither the resolver nor
caching. It is not written before a re-read shows the failures repeat: a
2,596-row read that reported 8 hard failures and then, read again, reported
2,596 HTTP 200s and 0 failures is exactly the transient case this rule is for,
and no report was added for it.

**The console can say whether the lookups ran.** The reader's phases are
evidence, not decoration: a read whose `ids` stage was reported and came back
with no usable product id is a different report from one whose stage never
appeared at all, and only the reader can tell the two apart. The core records
the `stage` names a read emits (from the progress markers above) and prints one
of three sentences beside the count line:

- the product-id stage appeared - *the lookups ran* (and, when the reader also
  reported failed lookups, *some of them failed*);
- stages appeared, none of them the product-id stage - *its lookups did not
  run at all*;
- no stages at all - *the console cannot say whether its lookups ran*.

Recognised spellings are `ids`, `id`, `product-ids`, `product_ids`,
`productids`, `resolving ids` and `lookups`, compared case-insensitively; `ids`
is the one the shipped reader uses. A reader that stops emitting its stage
makes the first question in a defect report unanswerable, so keep it.

**One file, for the plugin's author.** When a read with no usable product ids
has to be reported, the listing panel's **Save a read diagnosis...** button
writes a single text file (`cs-read-diagnosis-<date>-<time>.txt` in the app's
folder, with a number added rather than an earlier file replaced) that holds the
three things a reader's author asks for: the run's
complete console output, the progress stages it reported, the reader's own
`Stock resolution:` line with the sentence it means, and one catalogue row
together with the response from `GET <site>/api/data/product/<listing-id>` -
the same endpoint the reader's own lookup reads, fetched once with the
person's own cookie when the button is pressed. It is meant to be pasted into a
conversation, so it is sanitised before it is written: any key naming a token,
cookie, secret, password, session, credential, API key, e-mail, phone or
address has its value replaced with *(hidden - it is not part of the question)*,
strings are cut at 40 characters (their real length is kept), and lists and
nesting stop early. A `Product-reference keys:` line says, for the row, which
id-shaped keys are present, empty, or holding `0` - which is the first thing to
check when a read has no ids.

The detail record is shown **key by key** (sixty with their values, the rest by
name) rather than counted, because the question it answers is *does this record
name a product anywhere* - and a reference sitting at key 30 of 38 is exactly
what a key count throws away. One line then lists the keys that *mention* a
product (`product`, `productId`, `productData`, any spelling) and - separately -
whether any of them actually holds an id, because `isDemoProduct: null` mentions
a product and answers nothing. When none of them holds one, the file says the
reader cannot resolve the listing from this endpoint, and, if the record also
carries the fields an edit changes (`title`, `priceCad`, `inventory`, `status`,
`description`, `primaryImageUrl`, `category`, `sku`) under the listing's own id,
says so: that record being writable directly is the one question a diagnosis
cannot answer, and it is worth asking before a shop is written off as uneditable.

The file's copy of the console **leaves out the progress markers**, with a line
saying how many were omitted. A 2,596-row read emits ~250
`ALEX_COLLECT_PROGRESS:` lines; left in, they are the whole file and the five
lines that matter are lost inside them. The markers are still parsed - the
phases and counts come from them - they are simply not printed as if they were
the reader's words. An empty `sku` on the row is noted but not blamed: a reader
that has the listing id asks for that listing's detail, and the record's keys
are what decide the answer.

**A read's account is kept beside the list.** The app records the run's output
(up to 200,000 characters), the progress stages and the exact command in
`cs-stock-meta.json` next to `cs-stock.json`. A diagnosis written after the
window that made the read has closed therefore still quotes the run, and a
command recovered from the app's own log fills in for lists read before this
was kept. When the read's account really is missing, the file says so instead
of claiming the reader printed nothing.

**When the vendor's data carries no product reference at all.** The reader can
be perfectly correct and still deliver no product ids: 1.0.34's own console
line reported *2,587 listings, 0 with a real product id, 2,587 without the key,
0 reported as 0* - so those listings are being read from somewhere that does
not name the product. That is not a row the core can write, and it will not
guess one, but it is also not a dead end, because the reader is reading the
listings themselves:

- **The core now counts what the read did carry** and prints it once, after the
  version sentence: *What the read did carry: 2587 listing ids, 2587 SKUs,
  2587 listing addresses (of 2587 listings), so the reader has what resolving a
  listing to its product takes; it is only the product id itself that never
  arrived.* If a read has no SKU on any row it says that instead, because then
  the product has to come from the vendor's own data rather than from a lookup.
- **Resolving the listing is the reader's job, and it has the material.**
  `stock.set` already addresses a listing by `id`, then `sku`, then `title`, so
  the same catalogue entry can be turned into the product it belongs to. The
  update action may do that - find the product from the listing it was given,
  and refuse rather than guess when the answer is not unique.
- **The core will accept an answer keyed by the listing's own id.** A result
  entry naming `id`, `sku`, `title`, `card` or `name` confirms the change just
  as a product id does, so a writer that resolves internally and reports what
  it resolved needs no change here.
- **Editing is blocked by it, and said to be.** With no product reference in
  any detail record, `marketplace.listing_update` refuses each of those
  listings before writing, so the edit panel says reading again cannot fix
  them and leaves title, price and state to the vendor dashboard. Stock counts
  are the exception:
- **Stock counts are not blocked by any of this.** The comparison panel's
  **Set CanadianShopper to the website's counts...** writes through `stock.set`,
  which addresses the listing rather than a product, so a shop whose reader
  reports no product ids can still have its stock corrected - only title, price
  and state need the listing panel.

Two rules follow for a reader:

- **Never emit `0`, `"0"`, `"0.0"` or any other empty stand-in for a missing
  product id.** Omit the key. The core's whole handling of "this listing cannot
  be written from here" is built on the key being absent, and a placeholder
  breaks the count it prints and the promise it makes about the rows it can
  edit.
- **Emit the real id the write endpoint patches**, exactly as the vendor gives
  it, as a number or a string - the core never renumbers it. If the vendor's
  listing data has no product id at all, the listing has no product id: leave
  the key out and let the core say so once, rather than filling the gap with a
  zero that reads as if every listing were editable.

Both are display-only and are used by the **Find and edit a CanadianShopper
listing** panel, which shows the price in its row and opens the address behind
its **Open the selected listing** button. An older reader that omits them still
lists, searches and edits; the row simply has no price in it.

Since plugin **1.0.29** every row's `url` is an absolute `http(s)` address
taken from the vendor's own data, which is what the core opens directly. The
core also accepts a path from the site (`/listing/12345`) and joins it onto
`https://canadianshopper.ca`, and it reads the same address under `link`,
`permalink`, `href`, `product_url`, `productUrl`, `listing_url`, `web_url`,
`view_url`, `address` and `page` - in that order, with capitals, underscores
and spaces ignored, so `productUrl`, `product_url` and `Product URL` are one
key. A key holding something that is not the web (`javascript:`, `mailto:`, a
Windows path) is skipped, not opened, and a bad key never hides a good one
beside it.

A row with no usable address is not a dead end: the button opens the seller's
own store and puts the card's title and listing id on the clipboard to search
for. That is the fallback, though, not the plan - 1.0.29 emits the address for
every listing whose vendor data has one, so `url` is what makes the button open
the listing itself.

## Security

A Python plugin is **not sandboxed**. When an action runs, its code has the same
permissions as Alex Collect: it can access files and accounts available to the
current user and can use the network. Install only packages from a source you
trust. The ZIP installer rejects path traversal, symbolic links, incompatible
host API versions, and missing declared tools; those checks are package
integrity checks, not a security sandbox or a signature system.
