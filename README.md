# Alex Collect 2.71

Alex Collect is a local desktop control panel for organizing a small trading-card selling workflow. It brings together the card pipeline, WooCommerce order inputs, a sale checklist, photo utilities, and optional plugins.

## Core features

- Run the card pipeline from a Tkinter desktop window.
- Preview the orders that sold since the last check, then add only those to the sale checklist.
- Compare stock between the website and CanadianShopper, eBay or Facebook on demand, and do something about what you find. The list holds only what needs attention - a count that differs, or a card that exists on one side only - and it is where the fixing happens: the website is right far more often than not, so one button sets every differing CanadianShopper count to the website's count, always showing the exact card, the old count and the new one and asking first. Select rows to fix or ignore just those, and when the website is the one that is wrong, **Set the website to the selected cards' counts...** writes the other site's count onto the website product - one field, `stock_quantity`, one product at a time, with its own confirmation naming each card and both counts, and the website's answer read back so a 200 that quietly kept the old number is reported as a failure. That direction needs WooCommerce keys with Read/Write access (the same pair the photo wiring uses); a read-only pair is told apart from a broken one, and the cards stay on the list because nothing was written. **Open the selected cards on the website** is still there for a count a plugin owns or a variable product, where a number is not the whole story. A card that is on the website and no longer on CanadianShopper is the one that can be put *back*: select it and **List the selected cards on CanadianShopper...** writes the same import file the batch pipeline writes - the same fourteen columns, the same filename, the same folder - built from the website product itself (its title, its price, the photo URL the shop already serves, its stock count), with the confirmation naming each card and anything missing from it (no photo, no price, or a card at zero that would be listed out of stock). The file is written first, then Alex Collect offers to import it for you: with plugin **1.0.23 or newer** (`marketplace.import_csv`) the draft listings appear without leaving the app, while a plugin without it says so and opens the folder, because the file is the same one a batch produces either way. Imported listings always arrive as unpublished drafts, and the run then offers the step that actually puts the card back on sale: **publish the new drafts**, which is the existing publisher with `--apply`, so the readiness checks still decide what may go live and PUBLISH still has to be typed. That publisher scans every draft on CanadianShopper - the dialog says so - so drafts from earlier runs are considered too and anything not ready is left alone; declining it falls back to the read-only *Preview drafts* report. The cards stay on the list until the next comparison finds them live on CanadianShopper. **List every website-only card...** does the same for the whole list at once. A card that is no longer sold on the other site is ignored rather than asked about forever: the dismissal is remembered in `stock-ignored.json` and a dismissed card comes back if its title is edited or when you restore it. Comparing changes nothing on any site, and only the counts are ever written - nothing is added, removed or repriced. Writing the CanadianShopper count is plugin 1.0.21 or newer (`stock.set`); the count is sent as `{"inventory": n}` and nothing else, matched by listing id, then SKU, then title, and a card the plugin could not match or found ambiguous comes back as failed with its reason - the row stays on the list, because a count the plugin did not confirm is not a count that was fixed. An older plugin is told apart from a failure: the dialog names 1.0.21 and the exact changes go to the clipboard and the console.
- Read eBay and Facebook without being lied to about what came back. Both sites check whether a request comes from a browser: eBay answers with its "Pardon our interruption" page under HTTP 200 and Facebook with an HTTP 400 script shell. The panel names that page, says your cookie is not the problem and that nothing was read or changed, and offers the way round it - save the page from your own signed-in browser with Ctrl+S (HTML only) and use **Read a saved eBay/Facebook page...**, which runs the same reader. A page that loads but yields no listing is reported as "no listing on it could be read" with the saved copy named, never as an empty shop, and a page that is really a sign-in page is reported as an expired session so you know which fix to reach for.
- Prepare WooCommerce sale checklists from a typed list or an orders CSV.
- Configure the store URL, AI page, preferred browser, prompt preferences, custom AI commands, seller links, output/scanner folders, Facebook workbook fields, and eBay Quick List templates/defaults from **User Settings** in the menu bar. Its **Save user settings** button sits beside the title, in a strip above the form that does not scroll - the settings page is the longest in the app, and saving used to mean scrolling past every field first. The page is split into ten groups - when the app opens, the store and AI, the store pages, custom AI commands, marketplace pages, the eBay handoff, the Facebook fields, the CanadianShopper CSV, the folders, and the CanadianShopper login - and each group has its own heading and its own **What this panel does** button covering just that group, instead of one explanation trying to describe the whole page. Each page now fills the window rather than stopping at the height of its own widgets, and the output console takes fewer lines on a small screen, so a long form has the room to be scrolled through.
- Copy the built-in **Add grades to titles** and **No grades in titles** prompts, or create, edit, and remove custom AI command buttons in User Settings; hover notes clarify each command’s purpose.
- Review the initial nine-card category plan in compact one-row-per-card output; the larger, screen-adaptive console keeps the confirmation visible without scrolling.
- Use the compact task launcher with fixed-width buttons in clearly separated Sell, After a sale, Photos, and Re-run a marketplace sections; there is no extra headline above the buttons. Plugins and Logs & reports are direct menu items. Hover task buttons for short tips. The output pane always follows new output and entered replies so prompts remain visible.
- Every panel leads with its work: buttons and input fields sit together at the top, and the explanation is folded behind a **What this panel does** button beside the title - it opens directly under that row, so the answer appears where the click was, and it starts folded. A panel is opened to do something with it, not to read eight lines first - and at 800x600 the prose used to push the buttons off the bottom of the window. Long steps now say so while they run instead of leaving the window blank, and no window opens bigger than the screen it opens on. In the tabs view each panel sits in its own bordered, titled section with a gap between boxes, so a group holding five panels no longer reads as one long page. Every button in the app explains itself on hover - what it does and what it leaves unchanged - not only the ones on the task page, and a check fails the build if a new button ships without its sentence. Closing the panel help takes its frame out of the layout rather than leaving a gap where the words were, and the scrolling page area is painted in the window's own colour instead of Tk's default white, so a short panel ends where its content ends instead of trailing a white band.
- Marketplace results are separated into Facebook, WooCommerce, CanadianShopper, and eBay folders. Woo/CS CSVs and eBay Quick List pages roll older batches into history on their next output run. Use Logs & reports to preview/move existing root-level files. See `app/pipeline/OUTPUT-FILES.md` for the accumulation audit.
- See `docs/facebook-feed-settings.md` for the Facebook workbook field templates and placeholder reference.
- Open the configured WordPress media upload page during the listing pipeline, then open the Facebook workbook, its folder, and the configured Facebook review page after export.
- Optionally prepare selected cards for eBay with a local copy/drag-and-drop Quick List page and sport-template tabs. eBay submission stays manual; the core does not change live eBay listings.
- Open the relevant seller pages after a sale; the core does not automatically change eBay or Facebook listings.
- Square card photos for manual uploads.
- Replace card photos from **Photos**, starting from the sheets you scanned rather than from a card name. **Add sheets...** takes the front sheet and the back one (any order, more than one at a time); each is split into its nine positions behind a **Reading your scans** window that names the sheet it is on and moves a bar as each one finishes - a 600 dpi scan takes seconds, and a window that shows nothing looks hung - the empty (black) slots are ignored and counted, and the sheets stay loaded for the whole sitting, so the next card does not mean splitting them again. The small pictures are kept for the sitting too, so the second card's picker opens at once instead of decoding them again. Images already used are no longer offered. Choosing an image means looking at it: the picker shows the card pictures captioned with nothing but the slot they came from - nine of them on an 800x600 screen, in a grid that scrolls if the window is smaller - with the buttons above the grid so they never scroll out of reach, and the back is proposed from the same slot on the back sheet because both sheets were filled in the same order. Then type the card name or SKU and Alex Collect opens the matching product edit page (with read-only API keys saved) or, when nothing matches, the filtered product list - and the photos you choose are still split, named from the scan and saved, so a card that is not on the website yet can be prepared in advance. The chosen pair is saved in `replacements/` as one pair: the card's current website image name with a `-1`, `-2` counter, so `gretzky-front-2.webp` always sits beside `gretzky-back-2.webp`. With two optional lines in `woo-keys.txt` - your WordPress username and an Application Password - it also uploads both photos and sets them on the product itself: the front becomes the main image, the back follows it, and the old front and back come off the product before the new pair goes on - taken off the product only, never deleted, so the image files stay in your media library - while any other gallery photo is kept. When a product's photos predate the `-front`/`-back` naming there is nothing to read the old back from, so Alex Collect asks which photo it is instead of guessing and leaving it beside the new one; that question also offers keeping every existing photo, and the confirmation then lists exactly what comes off and what stays. CanadianShopper plugin 1.0.15 or newer can then replace that one listing's photos with no staged CSV. From plugin 1.0.16 the new back replaces the old one, so a listing ends up with one front and one back; 1.0.15 is sent the front alone and told why, because its back would be added beside the old photo instead of replacing it, and anything older is told to update rather than being sent an argument it cannot honour. A listing's main photo is kept apart from its gallery, so one gallery row is not a one-photo listing - it can be an old back, a certificate, or packaging. Alex Collect never guesses which: from plugin 1.0.17 it asks, showing the row filenames and the images being sent, so you pick the row to replace, keep every row and add the new back beside them, or cancel. Closing that window without answering cancels, so a stray click changes nothing. The eBay and Facebook seller pages open in the same pass, and the `replacements/` folder opens with them so the same two files can be dragged straight into a marketplace listing; whole-batch wiring stays a separate action in its own panel.
- Assign a whole sheet at once from **Assign photos to cards...**: each card image becomes a row, and the rows can be filled three ways - paste the AI's read of the sheet (one title per line), paste your cards in the order they were scanned, or pick one image and search its card. Every row shows the picture, the slot it came from and the card it matched; a card that is only a near-tie for another is offered rather than chosen, because replacing the wrong card's photos is not undone with a click. Applying works one card at a time and a failure stops that card only.
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
