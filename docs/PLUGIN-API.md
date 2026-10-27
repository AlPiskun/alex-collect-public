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

## Security

A Python plugin is **not sandboxed**. When an action runs, its code has the same
permissions as Alex Collect: it can access files and accounts available to the
current user and can use the network. Install only packages from a source you
trust. The ZIP installer rejects path traversal, symbolic links, incompatible
host API versions, and missing declared tools; those checks are package
integrity checks, not a security sandbox or a signature system.
