# Alex Collect

Alex Collect is a local desktop control panel for organizing a small trading-card selling workflow. It brings together the card pipeline, WooCommerce order inputs, a sale checklist, photo utilities, and optional plugins.

## Core features

- Run the card pipeline from a Tkinter desktop window.
- Prepare WooCommerce sale checklists from a typed list or an orders CSV.
- Open the relevant seller pages after a sale; the core does not automatically change eBay or Facebook listings.
- Square card photos for manual uploads.
- Install optional plugins from a local ZIP using the **Plugins** panel.

The core continues to work without any plugins. The CanadianShopper integration is maintained separately and is **not included** in this repository or the core download.

## Install and run

### Windows

1. Install Python 3 from [python.org](https://www.python.org/downloads/); include Tcl/Tk and add Python to PATH.
2. In this folder, install the dependency with `python -m pip install -r requirements.txt`.
3. Double-click `START Alex Collect.bat`.

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
python test-plugin-manager.py
python test-core-sales.py
python test-facebook-feed.py
```

The GUI test needs a working desktop display (or Xvfb on headless Linux).

## Support

Alex Collect is MIT-licensed. Optional donations or support are welcome, but are never required to use, modify, or redistribute the core. The MIT license also permits commercial reuse and redistribution, subject to its notice and warranty terms.

## License

The core program is licensed under the MIT License; see `LICENSE`. Optional plugins may use separate licenses and are not covered by the core license unless their own license says so.
