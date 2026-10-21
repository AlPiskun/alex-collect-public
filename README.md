# Alex Collect 2.28

Alex Collect is a local desktop control panel for organizing a small trading-card selling workflow. It brings together the card pipeline, WooCommerce order inputs, a sale checklist, photo utilities, and optional plugins.

## Core features

- Run the card pipeline from a Tkinter desktop window.
- Prepare WooCommerce sale checklists from a typed list or an orders CSV.
- Configure the store URL, AI page, preferred browser, prompt preferences, seller links, output/scanner folders, Facebook workbook fields, and eBay Quick List templates/defaults in **User Settings** (also available between **View** and **Help**).
- See `docs/facebook-feed-settings.md` for the Facebook workbook field templates and placeholder reference.
- Open the configured WordPress media upload page during the listing pipeline, then open the Facebook workbook, its folder, and the configured Facebook review page after export.
- Optionally prepare selected cards for eBay with a local copy/drag-and-drop Quick List page and sport-template tabs. eBay submission stays manual; the core does not change live eBay listings.
- Open the relevant seller pages after a sale; the core does not automatically change eBay or Facebook listings.
- Square card photos for manual uploads.
- Install optional plugins from a local ZIP using the **Plugins** panel.

The core continues to work without any plugins. The CanadianShopper integration is maintained separately and is **not included** in this repository or the core download.

## Install and run

### Windows

You can install from source or build an Inno Setup installer:

- **Run from source:** Install Python 3 with Tcl/Tk, run `python -m pip install -r requirements.txt`, then double-click `START Alex Collect.bat`.
- **Inno Setup:** See [`installer/README.md`](installer/README.md). It documents a small setup for PCs with Python and a separate setup that installs a private Python runtime. The bundled setup still needs internet during installation to download Python packages.

Both installers package only the public core. CanadianShopper remains a separate plugin ZIP and is installed from the Plugins panel.

### Linux

Install Python 3, Tkinter, and the requirements. On Debian/Ubuntu:

```sh
sudo apt install python3 python3-tk python3-pip
python3 -m pip install --user -r requirements.txt
./install-linux.sh
./start-alexcollect.sh
```

## Plugins

Use the **Plugins** panel to install a trusted plugin ZIP, enable or disable it, or remove it. Plugin code is not sandboxed and runs with your account's permissions; install only packages from sources you trust. Alex Collect does not download plugins automatically.

The CanadianShopper plugin is a separate, privately maintained package and is not part of the public core. Plugin developers can start with [the plugin API](docs/PLUGIN-API.md).

## Development checks

From the `app` directory:

```sh
python test-gui.py
python test-ai-agent-flow.py
python test-user-settings.py
python test-plugin-manager.py
python test-core-sales.py
python test-facebook-feed.py
python test-ebay-quicklist.py
```

The GUI test needs a working desktop display (or Xvfb on headless Linux).

## Support

Alex Collect is MIT-licensed. Optional donations or support are welcome, but are never required to use, modify, or redistribute the core. The MIT license also permits commercial reuse and redistribution, subject to its notice and warranty terms.

## License

The core program is licensed under the MIT License; see `LICENSE`. Optional plugins may use separate licenses and are not covered by the core license unless their own license says so.
