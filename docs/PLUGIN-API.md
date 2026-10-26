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
must exit non-zero before any upload or listing write. `--back` is optional and
additive - without it the existing gallery is left untouched.

The action ID alone cannot tell 1.0.14 from 1.0.15, because both declare
`batch.photo_replace`; only 1.0.15 accepts `--mode replace` without a CSV. The
core therefore gates this path on the declared plugin **version** as well as
the action, and shows an "update the plugin" message rather than risking the
CSV error on an older copy. Whole-batch wiring remains a separate action
(`batch.photo_wire`) in its own panel.

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
