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
<<<<<<< HEAD
  "min_core_version": "2.29",
=======
  "min_core_version": "2.28",
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
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
- `batch.photo_cache_repair`
- `batch.pipeline_stage`

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
