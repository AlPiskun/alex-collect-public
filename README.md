# Alex Collect 2.47

Alex Collect is a local desktop control panel for organizing a small trading-card selling workflow. It brings together the card pipeline, WooCommerce order inputs, a sale checklist, photo utilities, and optional plugins.

## Core features

- Run the card pipeline from a Tkinter desktop window.
- Prepare WooCommerce sale checklists from a typed list or an orders CSV.
- Configure the store URL, AI page, preferred browser, prompt preferences, custom AI commands, seller links, output/scanner folders, Facebook workbook fields, and eBay Quick List templates/defaults from **User Settings** in the menu bar.
- Copy the built-in **Add grades to titles** and **No grades in titles** prompts, or create, edit, and remove custom AI command buttons in User Settings; hover notes clarify each command’s purpose.
- Review the initial nine-card category plan in compact one-row-per-card output; the larger, screen-adaptive console keeps the confirmation visible without scrolling.
- Use the compact task launcher with fixed-width buttons in clearly separated Sell, After a sale, Photos, and Re-run a marketplace sections; there is no extra headline above the buttons. Plugins and Logs & reports are direct menu items. Hover task buttons for short tips. The output pane always follows new output and entered replies so prompts remain visible.
- Marketplace results are separated into Facebook, WooCommerce, CanadianShopper, and eBay folders. Woo/CS CSVs and eBay Quick List pages roll older batches into history on their next output run. Use Logs & reports to preview/move existing root-level files. See `app/pipeline/OUTPUT-FILES.md` for the accumulation audit.
- See `docs/facebook-feed-settings.md` for the Facebook workbook field templates and placeholder reference.
- Open the configured WordPress media upload page during the listing pipeline, then open the Facebook workbook, its folder, and the configured Facebook review page after export.
- Optionally prepare selected cards for eBay with a local copy/drag-and-drop Quick List page and sport-template tabs. eBay submission stays manual; the core does not change live eBay listings.
- Open the relevant seller pages after a sale; the core does not automatically change eBay or Facebook listings.
- Square card photos for manual uploads.
- Replace one card's photos from **Photos**: type the name or SKU and Alex Collect opens the matching product edit page (with read-only API keys saved) or, when nothing matches, the filtered product list - and the photos you choose are still split, named from the scan and saved, so a card that is not on the website yet can be prepared in advance. It then splits the new sheet scan, ignores the empty (black) slots, asks which image is the **front** and which is the **back** (from that sheet, the folder, or another scan), and saves them in `replacements/` as one pair: the card's current website image name with a `-1`, `-2` counter, so `gretzky-front-2.webp` always sits beside `gretzky-back-2.webp`. With two optional lines in `woo-keys.txt` - your WordPress username and an Application Password - it also uploads both photos and sets them on the product itself: the front becomes the main image, the back follows it, and the old front and back are replaced while any other gallery photo is kept. CanadianShopper plugin 1.0.15 or newer can then replace that one listing's photos - front and, optionally, an additive back - with no staged CSV; older plugin versions are told to update rather than being sent an argument they cannot honour. The eBay and Facebook seller pages open in the same pass, and whole-batch wiring stays a separate action in its own panel.
- Turn a customer's texted list of cards into a website order from **Order from a text list**: paste the list and Alex Collect matches each line to a real product and writes a **pending** order - nothing is charged and no email is sent. One card per line, whether it is written `1970-71 O-Pee-Chee Paul Henderson #217` or `#217 Paul Henderson 1970-71 O-Pee-Chee` - numbering, bullets, bracketed notes and a trailing price are ignored, and a line beginning with a card number is a card, not a comment. A line repeated word for word becomes one row of quantity 2, while the same card listed twice at different grades stays two rows, because those are two different cards. You are asked whether to start a new order or add to an existing one by its number (cards already on it gain quantity rather than appearing twice). Any line that is not a confident match opens a search to pick the card, so nothing is guessed; a line can be skipped or the whole run cancelled. An optional discount applies as one fee line, previewed with the total before anything is written. Without API keys the WooCommerce order list opens and the pasted list is copied to the clipboard.
- The optional CanadianShopper plugin adds draft actions directly to the running pipeline: `v` previews all vendor drafts without changes and returns to the choices, `y` publishes ready drafts after the same `PUBLISH` confirmation used by the app, and `n` (or Enter) skips draft review/publishing. Photo wiring then continues without an extra post-import Enter prompt. The same **Preview drafts** and **Publish ready drafts** buttons remain in the card-pipeline and **Import / publish drafts** panels; the app button also requires its confirmation dialog. No bookmarklet is needed.
- Re-run one marketplace at a time from **Re-run a marketplace**: rebuild just the WooCommerce CSV, the CanadianShopper CSV, the Facebook feed/export, or the eBay Quick List from the AI reply already on disk. Each button rebuilds only its own output and never moves or renames the images again, so a mistyped answer at one step no longer means repeating the whole batch. If no AI text is found the button asks for the file.
- Install optional plugins from a local ZIP using **Plugins** in the menu bar.

Uploading a photo needs a WordPress **Application Password** (Users > Profile > Application Passwords): the WooCommerce consumer keys cannot reach the media library, and setting a product photo needs Read/Write keys rather than Read-only. Application Passwords need HTTPS. Without those two lines the app still names and saves the image; you attach it in the media library.

The core continues to work without any plugins. The CanadianShopper integration is maintained separately and is **not included** in this repository or the core download.

## Install and run

### Windows

You can install from source or build an Inno Setup installer:

- **Run from source:** Install Python 3 with Tcl/Tk, run `python -m pip install -r requirements.txt`, then double-click `START Alex Collect.bat`.
- **Inno Setup:** See [`installer/README.md`](installer/README.md). It documents a small setup for PCs with Python and a separate setup that installs a private Python runtime. The bundled setup still needs internet during installation to download Python packages.

Both installers package only the public core. CanadianShopper remains a separate plugin ZIP and is installed from the Plugins menu item.

### Linux

Install Python 3, Tkinter, and the requirements. On Debian/Ubuntu:

```sh
sudo apt install python3 python3-tk python3-pip
python3 -m pip install --user -r requirements.txt
./install-linux.sh
./start-alexcollect.sh
```

## Plugins

Choose **Plugins** from the menu bar to install a trusted plugin ZIP, enable or disable it, or remove it. Plugin code is not sandboxed and runs with your account's permissions; install only packages from sources you trust. Alex Collect does not download plugins automatically.

The CanadianShopper plugin is a separate, privately maintained package and is not part of the public core. Plugin developers can start with [the plugin API](docs/PLUGIN-API.md).

## Development checks

Step-by-step instructions for checking a branch on Windows - including the one-time git setup and the common traps - are in [docs/TESTING.md](docs/TESTING.md).

From the `app` directory:

```sh
python test-gui.py
python test-gui-ergonomics.py
python test-linux-packaging.py
python test-ai-agent-flow.py
python test-user-settings.py
python test-plugin-manager.py
python test-core-sales.py
python test-facebook-feed.py
python test-facebook-delivery.py
python test-ebay-quicklist.py
python test-pipeline-output-organization.py
python test-category-plan.py
python test-market-rerun.py
python test-pipeline-listing.py
python test-custom-ai-commands.py
python ../installer/test-bundled-config.py
```

The GUI test needs a working desktop display (or Xvfb on headless Linux).

## Support

Alex Collect is MIT-licensed. Optional donations or support are welcome, but are never required to use, modify, or redistribute the core. The MIT license also permits commercial reuse and redistribution, subject to its notice and warranty terms.

## License

The core program is licensed under the MIT License; see `LICENSE`. Optional plugins may use separate licenses and are not covered by the core license unless their own license says so.
