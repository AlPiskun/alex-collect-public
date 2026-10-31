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
- `stock.set`

The three photo actions are separate jobs even though one script usually
backs them all, so the core resolves each one by ID rather than by filename:

| Action | When the core calls it | Arguments |
| --- | --- | --- |
| `batch.photo_stage` | Preparing a batch (Square + host the photos) | `--mode prepare ...` |
| `batch.photo_wire` | "Wire the photos", and the whole-batch offer in Replace a card's photos | `--mode wire --cookie-file ... --ready-dir ... --cache ...` |
| `batch.photo_replace` | "Wire this card's photos?" in Replace a card's photos | the same `--mode wire` arguments plus `--title <full product name>` |

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

The plan is one entry per listing, and **only the fields that change are
present**. A field that is absent must be left exactly as it is on the site:

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

- An entry may be named by `id` (also `product_id`, `listing_id`), `sku`,
  `title`, `card` or `name`; the id wins when both sides have one.
- `why`, `reason`, `error` and `message` are all accepted as the failure's
  sentence, and it is shown unedited.
- A listing the result does not mention is **unknown** - the panel says it
  cannot confirm the change and leaves the row as it was. Exit non-zero to mean
  *nothing was written*: the panel takes that at its word.

### What a `stock.list` row carries (since plugin 1.0.28)

The listing panel shows a row as **card - state - stock - price - SKU**, and
links to the listing's own page. A row already has `title`/`name`, `sku`,
`inventory` and (since 1.0.25) `status`; from 1.0.28 it also carries:

| key | meaning |
| --- | --- |
| `price` | the listing's price, as the vendor shows it (`"CA$8.50"` and `"8.50"` are both read) |
| `url` | the listing's own page address |

Both are display-only and are used by the **Find and edit a CanadianShopper
listing** panel, which shows the price in its row and opens the address behind
its **Open the selected listing** button. An older reader that omits them still
lists, searches and edits; the row simply has no price in it and the button
says the link is missing rather than opening something guessed.

## Security

A Python plugin is **not sandboxed**. When an action runs, its code has the same
permissions as Alex Collect: it can access files and accounts available to the
current user and can use the network. Install only packages from a source you
trust. The ZIP installer rejects path traversal, symbolic links, incompatible
host API versions, and missing declared tools; those checks are package
integrity checks, not a security sandbox or a signature system.
