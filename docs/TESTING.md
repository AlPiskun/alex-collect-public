# Testing a branch before merging

How to check a change on the Windows machine, in the order that catches the
most problems. Everything here was learned the hard way; the traps at the end
cost real time.

---

## 1. Find the clone and open a terminal in it

The tests live in the **clone**, not in the installed app.

GitHub Desktop, with the repository selected:

- **Repository → Open in Command Prompt** (or *Open in PowerShell*) — starts a
  shell already in the clone root.
- **Repository → Show in Explorer** (`Ctrl+Shift+F`) — then type `powershell`
  in the Explorer address bar and press Enter.

Confirm you are in the right place:

```cmd
git rev-parse --show-toplevel
dir app\test-*.py
```

If `dir app\test-*.py` finds nothing, you are in
`%LOCALAPPDATA%\AlexCollect\app` — the installed copy, which deliberately ships
without tests.

## 2. Trust the folder for command-line git (once per clone)

If git says:

```
fatal: detected dubious ownership in repository at 'C:/Users/Owner/Documents/GitHub/...'
'...' is owned by: 'S-1-5-32-544'
but the current user is: 'S-1-5-21-...'
```

the folder is owned by the Administrators group, not your account (usually
because the clone was made by an elevated process). GitHub Desktop keeps
working because it uses its own bundled git, so this only shows up in a
terminal. Fix once:

```cmd
git config --global --add safe.directory C:/Users/Owner/Documents/GitHub/alex-collect-public
```

For every future clone, re-run that with the new path, or allow all repos with
`git config --global --add safe.directory "*"` (that disables the protection).

## 3. Switch to the branch

GitHub Desktop: **Fetch origin** → **Branch** menu → pick the PR branch.

```cmd
git log --oneline -1
```

The top commit must match the PR page on GitHub.

**"Changes: 0 files" is correct** at this point — that tab shows only
*uncommitted* edits, and the work is already committed.

## 4. Run the suite

`test-gui.py` prints the version and the folder it is testing on its first
line — for example `== 0. Alex Collect 3.23, from
C:\...\alex-collect-public\app ==`. Check that against the PR before reading
any failure: a clone left on an older commit has an older `gui.py` beside an
older test file, and its failures look exactly like the current work's.

From the clone's `app` folder, one command per line:

```cmd
cd C:\Users\Owner\Documents\GitHub\alex-collect-public\app
```

```cmd
python test-gui.py
python test-gui-ergonomics.py
python test-ai-agent-flow.py
python test-custom-ai-commands.py
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
python test-ai-prompts.py
python test-process-utils.py
python test-photo-replace.py
python test-photo-queue.py
python test-photo-assign.py
python test-photo-panel.py
python test-image-store.py
python test-woo-orders.py
python test-sale-preview.py
python test-stock-compare.py
python test-cs-edit.py
python test-cs-proof.py
python test-cs-record.py
python test-ebay-fill.py
python test-market-stock.py
python test-stock-write.py
python test-cs-listing.py
python test-order-panel.py
python test-order-sheet.py
python test-quote.py
python test-order-pdf.py
python test-woo-media.py
python test-woo-create.py
python ..\installer\test-bundled-config.py
```

Notes:

| Test | Needs | Notes |
| --- | --- | --- |
| `test-gui.py` | Tk | Boots a real window; flashes dialogs for a minute or two. ~230 checks. `test-tool-dialog.py` reads this file and fails on a call to an `app.`/`runner.` method that does not exist, so a typo in it is caught without a Windows machine. |
| `test-gui-ergonomics.py` | Tk | Headless-ish layout assertions - the task groups (including the new eBay store panel and the console's follow-the-end rule: new output scrolls into view only while the end is on screen, and leaves the view alone once the reader has scrolled up). |
| `test-ai-agent-flow.py`, `test-custom-ai-commands.py` | Tk | Import `gui.py`, so they need the toolkit. |
| `test-facebook-feed.py` | pandas, openpyxl | Also the nested-helper launcher: the console python, `-u`, the helper's own folder, a helper that explains itself not being retried, a silent failure retried once on the app's own interpreter, and the child's pipes - stdout/stderr owned by the pipeline, stdin never the app's, unbuffered, no console window. Plus the stale-workbook check: a failed export names the older `facebook_delta_*.xlsx` instead of letting it look like this run's. And the workbook-lock check, which reads the shipped `locked_files` out of `facebook_feed.py`: a free workbook is not called locked, a locked one is named with its reason kept, a workbook that does not exist yet is not a lock, and the answer comes before the first feed request. |
| `test-user-settings.py`, `test-ebay-quicklist.py` | Pillow | Prints `Pillow is required` and stops if missing. |
| `test-linux-packaging.py` | Tk, Xvfb | Linux only; skips itself on Windows. |
| `test-market-rerun.py`, `test-pipeline-listing.py` | Pillow | Pipeline regression suite; no GUI. `test-pipeline-listing.py` also reads the plugin version rules: 1.0.27 is the streaming version, an unreadable or missing manifest is never treated as new, and it checks the SKU a card is given: a title naming a dark or light back carries that printing in the SKU (so two printings of one card are two products rather than one SKU), a title naming neither keeps the SKU it always had, and two rows on one SKU are printed with what to do about it while the CSV is being written. |
| `test-ai-prompts.py` | nothing | The shipped AI prompt files, read without Tk. |
| `test-process-utils.py` | nothing | No stray console windows; checks flags only. |
| `test-photo-replace.py` | Pillow | Sheet split, empty-slot detection, replacement naming. |
| `test-photo-queue.py` | nothing | An order's cards, nine at a time: which cards a sale leaves needing a photograph (a card that went to zero is sold out, a card with no stock count has no number that says it is for sale, and both are named with the reason instead of vanishing), one photograph for a card the order carries twice, the first nine and the nine after them, what is remembered between two sittings, the order rearranged to match the sheet, and the sentence that says which nine this run is. |
| `test-photo-assign.py` | Pillow | The worksheet that names the cards: the front images in reading order with the backs left to their tile, the Nth card on the Nth image, a card the search could not find keeping its words as *no match*, an image with no card left as *no card*, the counts under the list, and only a matched row applied without asking. |
| `test-woo-media.py` | none - no network | The upload request, its refusals, and that a half-finished replacement is reported as one; and the media library searched for a photo that may already be there - by the file's own name, by its title when the site re-slugged it, and reporting nothing found rather than crashing when the library refuses or cannot be reached. |
| `test-woo-create.py` | none - no network | Creating the batch's products on the website: the CSV read back, the product body carrying only what is known, drafts first with the photos uploaded before the product exists, SKU lookup so a re-run skips instead of duplicating, publishing as a separate step only after the photos land, a 200 that kept the old status reported as the site's answer, one card's failure not stopping the rest, a refused key pair aborting at the first card, categories made parent-first, the exact key help, the pipeline's own offer (no keys never falling back to the CSV silently, the app's answer obeyed through its flags), and what a second run finds - a live product left alone, a draft named as a draft, a draft with no photos never published, and a batch asked to publish finishing the draft it left behind. Plus the website's own error page: a read repeated before a card is given up on, a card whose existence could not be read called *unconfirmed* rather than missing, a product written before the error page found again by SKU and never sent twice, a card whose SKU really is absent called not created, a card the site would not publish called *not on sale* rather than not created, three error pages in a row stopping the run with the rest *not attempted*, the failed step's line for NOT EVERY STEP FINISHED, and the advice that finishes the batch with one re-run instead of a second CSV import. Plus a slow website: a card's creation tried four times with a longer wait before each, the waits themselves (3s, then 6s, and never more than 20), a card created on its third try with the count of tries recorded, the progress event that says *the website is slow - trying again (2 of 4)* on that card's name while it happens, a 429 and a dropped connection each followed by a second POST, a write that landed before the connection died never sent again, a photo whose upload landed but whose answer was lost found in the media library and not uploaded twice, one second of pause between cards, and four error pages on one card still letting the rest of the batch through. Plus one card per SKU: a dark back and a light back created as two products, a card found under the SKU an older version wrote (and that older SKU refused when it belongs to a different card), a SKU held by a product with a different title reported as not created with both titles, a title that differs only in spacing still the same card, and two rows on one SKU said in the confirmation before anything is written; a title that carries the team where the CSV's does not still the same card, while a corrected and an uncorrected printing are never; and the printing words the create step compares being the pipeline's own list. |
| `test-image-store.py` | Pillow | The rule that keeps the card images from piling up, and the black tiles it deletes on the way: only images count (a CSV or a report in the same folder is a record and is never touched), which images are the sitting's own and therefore never offered, the dated folder a batch's images go to (and `(2)` when that minute is already taken), the move itself (byte for byte, `_tiles/<sheet>` kept, nothing deleted, a name already in the store getting a `(2)` instead of being overwritten, a file that will not move named with its reason and left in place), and the two ways it is asked - the app asking for the folder when the setting is blank and remembering a refusal for the sitting only, the Yes / No / Cancel question when the setting is filled in (Cancel not starting the run), a folder that cannot be used refused with the reason, an empty folder asking nothing - plus the terminal side: a batch the app started not asking a second time, and a run with no setting pointing at the setting instead of waiting for an answer. The black tiles: what counts as only-background (a noisy background yes, a dark card no - its lettering is bright, a grey tile no, an unreadable file never), the window that shows them as pictures with one tick each, deleting exactly the ticked ones and moving the rest, an unticked tile still moving, "Keep them all" and closing the window deleting nothing, nothing ticked saying so, the window only opening after the move was agreed to (no to the move and a cancelled run both delete nothing), a folder of cards opening no window at all, a pile of hundreds measured behind a progress bar, and every button in the window explaining itself. |
| `test-photo-panel.py` | Pillow | Drives the real Photos panel against a stubbed Tk: which image goes where, the arguments the plugin receives, and what each plugin version is allowed to be sent. Also the order queue as the panel draws it - the nine on the table, the cards left out named in the console, Move up and Move down, marking a sitting as photographed so the next one starts at the tenth card, starting an order again, and the nine already filled in when the assignment window opens - that the sheet-reading choice is gone, and that the older card images are offered a home before another sheet is cut, with the sitting's own images held back. |
| `test-woo-orders.py` | none - no network | Reading a pasted card list, which card a line means, when the app refuses to guess, and the exact order body that would be sent. |
| `test-order-panel.py` | Pillow | Drives the real order panel against a stubbed Tk: the pasted list, the picker, new vs existing orders, the discount, the no-keys fallback - and that this panel no longer prints order sheets, which have their own panel. |
| `test-order-sheet.py` | Pillow | Drives the **Print an order** panel against a stubbed Tk and a fake shop: one search box for an order number, a customer's name and a card's name; the number read straight from the shop, the customer answered by the shop's own order search, the card looked up as a product and then asked which orders hold it; every match listed with the reason it is there and a repeated order listed once with every reason kept; the single match pre-selected; the chosen order printed and opened with the order's own number, state and cards; a search that matches nothing; an empty box asked for something to look for; the quotes folder answering when no keys are saved and when the shop will not answer (the sheet then printed from the quote's own record and saying so); pressing the sheet button with nothing chosen; and the dashboard's order list one click away. |
| `test-quote.py` | Pillow | The customer quote, without Tk for the first six sections: the sums (percent and amount discounts, a discount bigger than the subtotal, a blank or nonsense discount, quantities never below one), the cards (added one by one, all the search matches at once, only the ones the shop says are in stock - with the out-of-stock ones counted and left out, and a card that says nothing not guessed at - the same product twice merged into one row, and the four ways of sorting the matches, an unreadable price always last and ties falling back to the name), the saved files (the next number in the same year, a hand-edited quote repaired, broken JSON still listed and still readable as *broken*, saving the same quote twice replacing its file), the address (a four-line box turned into the website's address lines, nothing invented for an empty customer), turning it into an order (the exact order body, the discount as one negative fee, the quote's number and validity in the customer note, a refusal when there is nothing from the shop, and a changed price named as a difference before the order is sent), the PDF (A4 at 200 dpi, the logo plate, a second page when the cards overrun, `Page N of M`), and the real panel driven through a stubbed Tk: search, add all the matches, a typed card, save, print, copy as text, re-price, and turn into an order - the sort chooser re-ordering the matches already on screen without searching again, the chosen order being remembered, and the out-of-stock card named as left out instead of vanishing - the cards' pictures and the links in the printed PDF: a quote row keeping its picture and the card's page through a save and a load, a search result carrying both, the picture actually drawn in the card's column, a card with a picture counted and one without counted as missing, a title that is a link to the product page and a card with no page printing no dead link, the link rectangle sitting over the name and not the price, and forty cards following their links onto the second page - plus the keyless run that still saves and prints but opens the keys file instead of pretending to look anything up. |
| `test-order-pdf.py` | Pillow | The order sheet, no Tk: the order's own number, state in words, paid date, delivery address and cards winning over the quote's, and the quote filling in whatever the order cannot give; the figures adding up to the total the customer was charged (a tax line only when the shop charges tax apart, an unexplained charge named rather than hidden); the pictures - downloaded once, kept in the documents folder, a second print reading the kept copy, and a picture the shop will not give costing that card its photo and nothing else; the paper - the same A4, the same band colour and the same white logo plate in the same place as the quote's, each card's picture actually drawn (its colour on the page), and a "no photo" box where there is none; and a thirty-card order running to more than one page. |
| `test-sale-preview.py` | Pillow | The preview before anything is written: which orders count as sales, what is still to add, the add-these-orders-only arguments, and the key offer when the file is missing. |
| `test-stock-compare.py` | Pillow | Matching two catalogues card by card (SKU first, then title), the action list of disagreements and one-sided cards, the confirmed write plan in both directions, the plugin's result file read conservatively, the refusal when the plugin cannot write, remembered dismissals and their restoration, the listing file written for cards only on the website, its one-click import (including a plugin that cannot import, refuses a file, or reports nothing) and the publish step that follows it (and the read-only look that comes first when nobody knows whether a draft exists - no PUBLISH question and no empty report when there is none), listings that exist but are not on sale (never written to, publish offered for drafts), a reader older than plugin 1.0.25 named by version, the direction stated in both write confirmations, the publisher's own draft tally read from its console line rather than its report file, a listing that carries no count at all being reported by its state instead of vanishing (and never written to), the nearest-title diagnosis that tells a wording problem, a duplicate product holding the listing, and a card that is not listed apart (and the liveness tie-break that keeps a sold-out duplicate from taking the listing), the condition guard that refuses to pair two different grades, the reader's own state tally, a card at zero on the website and nowhere else being left off the list (and named rather than silently dropped, while a zero card that is listed and differs still shows), the catalogue read four pages at a time and reassembled in order (and stopping at the page that ends it), the site's own page count driving a real progress bar where a read without one sweeps, the six ways the result can be sorted (with the panel's chooser re-reading the list without comparing again and remembering the choice), listings the other site holds at zero being called a count job, a plugin older than 1.0.26 being told apart from a real change when archived states come back (and an unreadable version being claimed for in neither direction), plus the on-demand comparison panel; and a failed read explained by what stopped it - one listing's detail lookup told apart from a refused session, a rate limit, a connection that never answered and a line it cannot place (only a refused session pointing at the cookie, the lookup failure saying the cookie was working and quoting the path), ages in words, and the previous read offered with its age - never used on its own, never used when this run wrote the file, and refused when there is nothing readable to offer (a list with no header or a missing file), with a clean exit that writes no new list told apart from a fresh one; and what plugin 1.0.36 says - a catalogue page that could not be read told apart from one listing's lookup (nothing was read, and the site is at fault rather than the cookie), its closing `n lookups failed` read and turned into the row that could not be resolved (compared by SKU or title, not editable by product id), one failed lookup in the singular, and which plugin version carries on past a stopped one (older: update; 1.0.36: a defect; unreadable: neither); and a read the person stopped, which is said to be stopped rather than failed (the banner, the panel line, no reader blamed, the earlier list still offered and named with its age), a reader that ends with an exit code and not one line said to have printed nothing instead of being called unrecognised, the plugin version named in the failure line, an older plugin warned about before a long read and not warned about once it is 1.0.36, a still-running note with the time so far that stays quiet while a tool is talking and after a stop or a finish, and the runner recording a stop before it kills the process, and a run holding at a question saying it is waiting for an answer rather than that it printed nothing; and a comparison that asks the reader to skip the product lookups it never uses, dropping that flag (and then the cookie flag) when a reader answers exit 2 - each drop said out loud, the flags that were not the problem kept - with the slow read named as the slow read, and the finished read's own duration printed with its tally; and comparing the list already on disk from its own button - no tool started, the age said in the console and in the summary beside the counts, a missing or unreadable file refused rather than compared as an empty shop; and plugin 1.0.38's list-only read compared end to end - 2,600 rows with no product ids at all still pairing every card, nothing said against them, and the panel naming the fast read only when the installed plugin takes the flag (an older one still asked, still dropped, and still called the slow read), with the reader's own stages in words; and SKUs that name the printing - a title's tokens, a SKU left alone when it is already right and given its token when it is not, the shop-wide audit that names only the products whose SKU is short a token (never one with no SKU at all), one SKU changed and read back with another product's SKU refused, a variant card created under the SKU its title calls for rather than refused for the plain one, the plain card refused when the dark back holds its SKU - with the SKU that dark back should carry, its product id, and the fact that a re-run changes nothing - the ordinary unrelated-clash advice kept, and the pipeline's tail no longer promising a re-run for a card a SKU is holding back; plus the panel's SKU check: no keys says so and reads nothing, the found products named with the SKU each should have, a No changing nothing, a Yes changing exactly that one field once and saying the answer was read back, a clean shop asking nothing at all; and the bar under that button - nothing on screen before a check starts, a sweeping bar naming the page while the website states no page count, a fraction of the pages when its headers do, a product-by-product fraction naming the product being written while it fixes, and the bar gone both after a finished check and after a read that failed (which can then be started again).; and the reprice gated on the plugin: with it uninstalled the button writes nothing, asks nothing, says the plugin is what talks to the shop and puts the same refusal on the console |
| `test-stock-write.py` | none | Setting one count on a website product: the PUT carries only `stock_quantity`, the answer is read back so a 200 that kept the old number is a failure, a read-only key is explained, and one card failing does not stop the rest. |
| `test-cs-listing.py` | Pillow | Listing a website product on CanadianShopper: the fourteen import columns built from the website product (title, price, its own photo URL, stock count), the notes raised for a missing photo, a blank price or a card at zero, the file itself (utf-8-sig, the importer's filename, 500-row batches), the plugin's import result read conservatively, and the pipeline and this panel sharing one definition of the template. |
| `test-market-stock.py` | Pillow | The eBay/Facebook session and readers: the three ways a cookie gets pasted, eBay rows parsed with their quantities, Facebook states turned into listed/not listed, a login wall told apart from an empty shop, eBay's "Pardon our interruption" page and Facebook's 400 named as the site's check page rather than a stale cookie, the saved page found by the app itself (recognised by its contents, newest first, in the app's folder and in Downloads, too-old ones refused), a refusal falling back to that page with no file picker, a saved page that covers more winning over the live window, eBay read up to 250 listings with every page kept in the app's own copy, and the panel comparing on demand. |
| `test-cs-edit.py` | Pillow | Finding and changing one CanadianShopper listing: a remembered surname, a card number, an exact SKU and a listing id all finding the row while a miss finds nothing, the state filter (archived, on sale, drafts, everything not on sale), the row's words, the change plan carrying only the fields that changed (and nothing at all when nothing did), the confirmation naming old and new, the plugin's answer read conservatively (a listing it does not mention is unknown, never changed, while an answer naming any of the listing's ids - the product id beside the page id - confirms it and another product's id does not), a product id reported beside the listing id reaching the plan while a title-shaped key never does, a 404 printing how the plan named the listing and saying the site was not changed, and the exact row and answer plugin 1.0.30 sends (a catalogue id beside the product id it patches, answered by product id, reported as one changed listing and no UNKNOWN rows), a plugin refusing a listing for having no product id being read as a failure and understood as an old list, the panel counting how much of a read can be edited ("N with a product id, so N can be edited here"), a read in which no listing has one being told apart from a single row without one (its note says what the reading is missing rather than sending 2,541 cards to the dashboard, no pointless second read is offered, and the listing's own page opens instead), asking for a re-read before spending a write on a row with no product id rather than after it, re-planning the same change from the fresh row with the product id in it, and naming a listing the site gives no product id for and leaving it for the dashboard, and a list read by an older plugin being described by the plugin that read it, and the panel: reading the catalogue, searching, narrowing by state, the rows numbered in the list and counting from one again after a filter, the edit form opening filled with the title, price, quantity and state the listing has now, a price, a count and a state changing in one visit (and only those three being sent), a title changing alone (and a state the form was merely showing not being written back), a price that is not a number and a listing with no title both refused without the form closing, a state move from the two state buttons, a declined confirmation writing nothing, a plugin without the action saying so, an unconfirmed or failed write leaving the row alone, the listing's own page, a listing the plugin gave no address for opening the store with the card and its id on the clipboard instead of a dead end, a relative address joined to the site and another plugin's word for it read too, the same key in any spelling (`productUrl`, `PRODUCT_URL`, `Product URL`), every documented address key read, an address that is not the web refused rather than opened (and a bad key not hidden by a good one beside it), the last read on disk being offered when the panel reopens; and a reader that reports `product_id: 0` for every listing being told apart from one that reports none - 0 not counted as an id, never put in a plan, never sent to `/api/products/0/`, never used to explain a failure; a real id accepted in any shape and beside a zero; the console naming the zeros, saying reading again returns them, and pointing at the comparison panel's `stock.set`; and the plugin version that reports real ids - 1.0.34 - named by the panel: an older plugin told updating is the fix, 1.0.34 or newer told a read without ids is a defect, an unreadable version treated as neither, string ids from 1.0.34 editable and carried unchanged into the write, a read with nothing wrong saying nothing at all, and what a read did carry being counted and said - listing ids, SKUs and addresses, with the read's own 2587 in it, a partial SKU column saying how many would be left behind, a read with no SKU on any row saying the product has to come from the vendor's data, a read with no identifier at all said plainly, the line placed between the version and what still works, and the whole read on screen - 2,596 listings read and 2,596 listed, the last card reachable, the summary saying "All 2596 listings shown" (the report was "I'm only shown 200 products": the list capped itself at 200 rows and the read's sentence replaced the count of what was on screen), a card past that old cut found by its SKU, and `search` returning every match unless a caller asks for fewer; and plugin 1.0.35's read - 2,587 rows every one carrying a string product id, all editable with nothing said against them and the exact string carried into the write, an id compared as an id ("4321", 4321, " 4321 " and 4321.0 alike, an opaque id and a leading-zero code kept as given), a writer answering with a number, a string or the listing id all confirming the same change while another product's id does not, and two listings resolving to one product being named after the read with what a write to that id means; and the diagnosis file a plugin's author is handed on request - the run's own output, the progress stages it reported and one row with its detail response, sanitised (a token, a cookie, a session or an e-mail hidden, a long string cut but its real length kept, a long list capped, nesting stopped), a row's `Product-reference keys:` line telling a present id from an empty key and from a `0`, the reader's stages read as *the lookups ran*, *some of them failed*, *they did not run at all* or *no phases at all*, the detail address built as the reader builds it (`/api/data/product/<listing-id>`, not the product id), one detail request answered rather than raised (a DNS failure becomes a status and a body), the button writing one file per press (a second press keeping both) with the read's output, stages and row in it, using the cookie but never writing it, saying where the file went - and with nothing read, asking for a read and writing no file; a 38-key detail record shown key by key with its secret still hidden at key 35, a capped record naming what it did not print, every key mentioning a product found in any spelling with what it holds, a response naming no product anywhere said to name none, an empty SKU on the row noted but not blamed for the missing id, a file that says where its list came from and never claims a reader printed nothing when nothing was kept, the read's output, stages and command written into `cs-stock-meta.json` and used by a diagnosis from a fresh window, the command recovered from the app log for a list read before any of it was kept, and the console pointing at the button when a read has no ids; the reader's own resolution line (plugin 1.0.39) read as five numbers, quoted verbatim, and turned into what it means - every answer 200 and naming no product called the vendor's data rather than a defect in the reader, a mixed read counting its usable ids and its ambiguous SKU, a read that asked for nothing said to have asked for nothing, hard failures named as failures, a 1.0.36-1.0.38 plugin told 1.0.39 prints the counts that settle it and a 1.0.39 one not, the old defect verdict kept when no counts were printed, the resolution line and its sentence in the diagnosis file, and the console quoting it after a read; a shop whose records name no product told that reading again cannot fix its rows (the plugin's updater refuses without an explicit reference) while stock counts still work, a read whose lookups merely failed not given that verdict and offered a re-read instead, and the older `N lookups failed` line kept apart from the resolution line's hard failures, with the diagnosis file carrying the same verdict and what it costs; the shop's real 1.0.39 file reproduced - 250 progress markers cut from the output it shows (counted, and said to be the window's bar rather than the reader's words) while every line the reader said survives, eight failed lookups told apart from 2588 silent answers and carved out of both the verdict and the 'reading again cannot fix these' sentence, `isDemoProduct`/`productOptions` listed as keys that mention a product but hold no id, the record called the closing condition both sides agreed on, and the one question the file cannot answer put plainly: a record that carries `title`, `priceCad`, `inventory` and `status` under the listing's own id, while the update action writes `/api/products/<product_id>/`; and the read-only method probe - one `OPTIONS` request (never a write) whose `Allow` header is read into method names, `PATCH`/`PUT` called the method settled and nothing more - a no-op write named as tolerance rather than proof of a field, with the vendor's documentation, a response schema or a controlled reversible change named as what would settle it, `GET, HEAD` only called read-only and final, and a 405 - or the shop's real answer, a 204 with no header at all - called inconclusive rather than a refusal, with no write attempted on an inconclusive or unanswered probe - with the answer, its meaning and 'nothing was changed' in the diagnosis file and on the console; and the record's own field form - one row per provable field filled with what the row holds, only the field that was typed in sent, the record's own id as the address (never `/api/products/`), the row's old value carried for the guard, the confirmation naming every change and saying the website is not touched, and each unproven field shown greyed with the proof that would open it and the form's sentence naming what is proven and what is never sent; and the plugin rule - with the plugin uninstalled the price button, the field form, the proof and the diagnosis probe each say the plugin is what talks to the shop, ask for nothing and send nothing |
| `test-cs-record.py` | nothing - no network | Writing the fields a proof settled at a listing's own record, and the four things that must hold first: no saved proof means no write (and a proof that stopped being true closes the path again), only a proven field is ever sent - so a proof of the title opens no door to the price - the address is the record's own id and the record must name it, and the values the person confirmed must still be the values there. Then the answers a site gives - written, accepted-and-ignored, refused with its status, unreadable before the write and unknown after it - plus a value already right sending nothing, a zero, a negative or fractional count, an empty or over-80-character title and a photo that is not a web address each refused by name, and a state refused outright because no proof can settle it. A form's worth of fields written in one request carrying only the fields that changed, each field answered on its own, one field kept and another dropped reported as partial rather than written, and a record that moved since the form opened (a price, a title) not overwritten. Then the comparison panel's plan: only the cards whose prices differ, with each reason for leaving one out counted (no listing id, no website price, a reader that sends none, a free card), the confirmed-value guard on a list written one listing at a time, and a tally that never sums a failure into a success. |
| `test-cs-proof.py` | nothing - no network | The proof that settles which fields of a CanadianShopper listing the site really writes: the plan for each field (a cent above the price, ` PROOF` on the title and cut first when the title is near a marketplace's limit, one dated marker line on the description, one more card on the count, and the main photo only from a staged photo of the same card), the fields it refuses to touch and why (a listing's state is never proven by hiding a live listing, a field the record does not carry has nothing to restore, an empty or unreadable value, a URL that is already the photo), what counts as the same value (12.5, 12.50 and 12.500 are one price), and the three answers a site gives: written (and put back), accepted-and-ignored (a 200 that changed nothing is not proof), and refused (with its status) - plus a write whose read-back fails called unknown rather than proven, a restore that fails said twice in the file and loudly on the console, a site that stores a price its own way still counted as a write, and only ever one field per request. The staged photo lookup: the newest batch first, only an `/api/file/` row the staging step has rewritten, only the card's exact title, and nothing at all for a folder with no batch or a title that is not the same words. Then the evidence itself: the file naming the listing, the record's own id and every step, with no cookie in it, two proofs in one second never replacing each other, and the saved record of which fields the last proof left written and put back - replaced, not kept, when a later proof fails. |
| `test-ebay-fill.py` | Pillow | Which cards go on eBay next: prices read from `1,250.00` and `CA$8.50`, an eBay title cut at 80 between words, the card's facts taken from its WooCommerce attributes with the saved defaults filling the gaps, and what cannot be listed named rather than dropped (no price, zero price, none in stock, a draft, no name). The selection itself: the limit minus the active listings is the room, the dearest unlisted cards fill it, a listing is matched by SKU and then by title (two card numbers are two cards, a zero-quantity active listing is still listed), the summary says how full the store is and what stayed behind, and the page it writes is the Quick List page - draggable snippets, the shop's own photo URLs, the template for the card's sport, an ampersand escaped - opened once and kept by the minute. Then the description as it is copied: the product's whole write-up rather than only its summary, the last line of a description longer than 900 characters still on the page, the website's paragraphs kept, scripts, styles and tags gone, the summary shown beside it only when it says something the full text does not, a product with only a summary using it as its description, a card with no description saying so instead of showing an empty box, and no scroll box hiding half of it. Then the criteria: dearest, cheapest, newest and oldest orders (a product with no creation date sorts last in both date orders rather than as the newest or the oldest), the typed list taken first in the order typed with a card that is not there named, a typed SKU and a typed product id finding their card, the category filter (part of a name, any case, a category nothing is filed under, and the count left outside it), every chooser label read back to its key, a hand-edited word meaning the same thing, an unknown order falling back to dearest, and the summary naming the order, the category and any missing typed card. Then the price road and the routing to it: a read whose summary names
the fields a missing product id blocks and the price that is not blocked, a row
with no product id offered the price when Edit is pressed (and the four-field
form not opened), declining that writing nothing and naming the button, and a
read with no listing addresses reported once for the reader. Then the real panel
against a stubbed Tk: no keys says so and writes nothing, the limit typed on the panel is the one the selection uses and is remembered in the settings, the order chosen on the panel is what the selection uses and is remembered too, the category and typed boxes travel with it, the template page for the chosen sport opens (once, not once per card) with the console saying so, no template configured is said rather than silently skipped, a selection with no cards opens no template and writes no page, a refused live read falls back to the saved page and with none says what to do, and the console names the chosen cards and says that nothing was listed. |
| `..\installer\test-bundled-config.py` | nothing | Checks the version/filename/SHA pins agree. |

Every script must end in `PASS` / `OK` / `ALL ... PASSED` and exit 0.

If a script prints nothing and returns instantly, you are in the wrong
directory.

## 5. Smoke-test the GUI by hand (about a minute)

From the clone root:

```cmd
START Alex Collect.bat
```

Open the panel the change touches and press each button.

Safe anywhere:

- **Re-run a marketplace → Facebook feed + xlsx**, then answer `n`. Expect a
  `RE-RUN: FACEBOOK` banner and a clean stop; nothing is written.
- CSV re-run buttons **in the clone** (which has no `_card_input.txt`): expect
  *"No AI listing text found…"* or a file picker. That is the correct
  behaviour, and a useful check itself.

Avoid: the WooCommerce / CanadianShopper / eBay re-run buttons in your **live**
data folder. They write real files and roll the previous CSV into history.

## 6. Merge, then pull

Green everywhere → merge the PR. Then, in GitHub Desktop: switch to `main` →
**Fetch origin** → **Pull origin**.

Pulling `main` does **not** update the installed app. The installer ships a
copy to `%LOCALAPPDATA%\AlexCollect\app`, so rebuilding and reinstalling is a
separate step — see `installer/README.md`.

---

## Traps that cost time

### `#` is not a comment in Command Prompt

```cmd
C:\...># GitHub Desktop: Fetch origin -> Pull origin
'#' is not recognized as an internal or external command
```

PowerShell uses `#`, `cmd.exe` does not. Paste only the command itself.

### A line glued onto the previous one

```cmd
C:\...>python test-gui.pycd C:\Users\Owner\...
python: can't open file '...\test-gui.pycd': [Errno 2] No such file
```

Two lines arrived as one. Run one command per line.

### `>` writes a file

`git pull > app\Pull` creates a file named `app\Pull`. That exact accident
once committed a 0-byte file that would have shipped inside the installer.
Use `>` deliberately or not at all.

### A "not merged" answer that contradicts GitHub

`git merge-base --is-ancestor` can lie in a **shallow clone**, because history
is cut off at a graft point:

```cmd
git fetch --unshallow
git merge-base --is-ancestor origin/<branch> origin/main
echo %ERRORLEVEL%
```

`0` means fully merged and safe to delete; `1` means it has unmerged work.

### Tests need the plugin to be absent — or present

Some checks assert the plugin-*installed* layout and some the plugin-*absent*
one. The suite forces `app.cs_addon` itself where it matters, so it gives the
same answer whether or not CanadianShopper is installed on the machine. If you
ever add a check that depends on it, force the value explicitly.

### Runtime files appearing in `Changes` after testing

`gui-settings.json`, `cookie.txt`, `list*.log` and friends are gitignored.
Leave them alone; do not commit them.

---

## Reading the results

| What you see | Meaning |
| --- | --- |
| `Changes: 0 files` after switching branch | Correct — nothing uncommitted. |
| History top commit = the PR's top commit | You are on the branch. |
| History top commit = an older `Merge pull request #…` | The checkout did not take; pull again with the branch selected. |
| `FAILED 1   PASSED 208` | One assertion failed; the rest are trustworthy. |
| A traceback instead of a summary | The suite aborted early — everything after that point did not run. |
| `ModuleNotFoundError: No module named 'tkinter'` | Install python.org Python with Tcl/Tk. The GUI tests cannot run without it. |
| `Pillow is required. pip install Pillow` | `python -m pip install -r requirements.txt` |

When reporting a failure, paste the traceback **and** the last section header
printed (`== 19b. … ==`), so the failing area is unambiguous.

---

## Why this exists

Until 2.36 the GUI suite had never run to completion on a machine with Tk, so
broken assertions stayed hidden for many versions. The first complete run
found ten defects: one real app bug (image renaming crashed with a `NameError`
in the plain CLI path) and nine stale or broken test assertions, one of which
also exposed a stray tear-off entry in the app menubar. Run the suite before
merging; it is cheaper than finding out in the installer.
