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
line — for example `== 0. Alex Collect 2.97, from
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
python test-woo-orders.py
python test-sale-preview.py
python test-stock-compare.py
python test-cs-edit.py
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
| `test-gui.py` | Tk | Boots a real window; flashes dialogs for a minute or two. ~209 checks. |
| `test-gui-ergonomics.py` | Tk | Headless-ish layout assertions. |
| `test-ai-agent-flow.py`, `test-custom-ai-commands.py` | Tk | Import `gui.py`, so they need the toolkit. |
| `test-facebook-feed.py` | pandas, openpyxl | Also the nested-helper launcher: the console python, `-u`, the helper's own folder, a helper that explains itself not being retried, a silent failure retried once on the app's own interpreter, and the child's pipes - stdout/stderr owned by the pipeline, stdin never the app's, unbuffered, no console window. Plus the stale-workbook check: a failed export names the older `facebook_delta_*.xlsx` instead of letting it look like this run's. And the workbook-lock check, which reads the shipped `locked_files` out of `facebook_feed.py`: a free workbook is not called locked, a locked one is named with its reason kept, a workbook that does not exist yet is not a lock, and the answer comes before the first feed request. |
| `test-user-settings.py`, `test-ebay-quicklist.py` | Pillow | Prints `Pillow is required` and stops if missing. |
| `test-linux-packaging.py` | Tk, Xvfb | Linux only; skips itself on Windows. |
| `test-market-rerun.py`, `test-pipeline-listing.py` | Pillow | Pipeline regression suite; no GUI. `test-pipeline-listing.py` also reads the plugin version rules: 1.0.27 is the streaming version, an unreadable or missing manifest is never treated as new. |
| `test-ai-prompts.py` | nothing | The shipped AI prompt files, read without Tk. |
| `test-process-utils.py` | nothing | No stray console windows; checks flags only. |
| `test-photo-replace.py` | Pillow | Sheet split, empty-slot detection, replacement naming. |
| `test-photo-queue.py` | nothing | An order's cards, nine at a time: which cards a sale leaves needing a photograph (a card that went to zero is sold out, a card with no stock count has no number that says it is for sale, and both are named with the reason instead of vanishing), one photograph for a card the order carries twice, the first nine and the nine after them, what is remembered between two sittings, the order rearranged to match the sheet, and the sentence that says which nine this run is. |
| `test-photo-assign.py` | Pillow | The worksheet that names the cards: the front images in reading order with the backs left to their tile, the Nth card on the Nth image, a card the search could not find keeping its words as *no match*, an image with no card left as *no card*, the counts under the list, and only a matched row applied without asking. |
| `test-woo-media.py` | none - no network | The upload request, its refusals, and that a half-finished replacement is reported as one. |
| `test-woo-create.py` | none - no network | Creating the batch's products on the website: the CSV read back, the product body carrying only what is known, drafts first with the photos uploaded before the product exists, SKU lookup so a re-run skips instead of duplicating, publishing as a separate step only after the photos land, a 200 that kept the old status reported as the site's answer, one card's failure not stopping the rest, a refused key pair aborting at the first card, categories made parent-first, the exact key help, the pipeline's own offer (no keys never falling back to the CSV silently, the app's answer obeyed through its flags), and what a second run finds - a live product left alone, a draft named as a draft, a draft with no photos never published, and a batch asked to publish finishing the draft it left behind. Plus the website's own error page: a read repeated before a card is given up on, a card whose existence could not be read called *unconfirmed* rather than missing, a product written before the error page found again by SKU and never sent twice, a card whose SKU really is absent called not created, a card the site would not publish called *not on sale* rather than not created, three error pages in a row stopping the run with the rest *not attempted*, the failed step's line for NOT EVERY STEP FINISHED, and the advice that finishes the batch with one re-run instead of a second CSV import. |
| `test-photo-panel.py` | Pillow | Drives the real Photos panel against a stubbed Tk: which image goes where, the arguments the plugin receives, and what each plugin version is allowed to be sent. Also the order queue as the panel draws it - the nine on the table, the cards left out named in the console, Move up and Move down, marking a sitting as photographed so the next one starts at the tenth card, starting an order again, and the nine already filled in when the assignment window opens - and that the sheet-reading choice is gone. |
| `test-woo-orders.py` | none - no network | Reading a pasted card list, which card a line means, when the app refuses to guess, and the exact order body that would be sent. |
| `test-order-panel.py` | Pillow | Drives the real order panel against a stubbed Tk: the pasted list, the picker, new vs existing orders, the discount, the no-keys fallback - and that this panel no longer prints order sheets, which have their own panel. |
| `test-order-sheet.py` | Pillow | Drives the **Print an order** panel against a stubbed Tk and a fake shop: one search box for an order number, a customer's name and a card's name; the number read straight from the shop, the customer answered by the shop's own order search, the card looked up as a product and then asked which orders hold it; every match listed with the reason it is there and a repeated order listed once with every reason kept; the single match pre-selected; the chosen order printed and opened with the order's own number, state and cards; a search that matches nothing; an empty box asked for something to look for; the quotes folder answering when no keys are saved and when the shop will not answer (the sheet then printed from the quote's own record and saying so); pressing the sheet button with nothing chosen; and the dashboard's order list one click away. |
| `test-quote.py` | Pillow | The customer quote, without Tk for the first six sections: the sums (percent and amount discounts, a discount bigger than the subtotal, a blank or nonsense discount, quantities never below one), the cards (added one by one, all the search matches at once, only the ones the shop says are in stock - with the out-of-stock ones counted and left out, and a card that says nothing not guessed at - the same product twice merged into one row, and the four ways of sorting the matches, an unreadable price always last and ties falling back to the name), the saved files (the next number in the same year, a hand-edited quote repaired, broken JSON still listed and still readable as *broken*, saving the same quote twice replacing its file), the address (a four-line box turned into the website's address lines, nothing invented for an empty customer), turning it into an order (the exact order body, the discount as one negative fee, the quote's number and validity in the customer note, a refusal when there is nothing from the shop, and a changed price named as a difference before the order is sent), the PDF (A4 at 200 dpi, the logo plate, a second page when the cards overrun, `Page N of M`), and the real panel driven through a stubbed Tk: search, add all the matches, a typed card, save, print, copy as text, re-price, and turn into an order - the sort chooser re-ordering the matches already on screen without searching again, the chosen order being remembered, and the out-of-stock card named as left out instead of vanishing - the cards' pictures and the links in the printed PDF: a quote row keeping its picture and the card's page through a save and a load, a search result carrying both, the picture actually drawn in the card's column, a card with a picture counted and one without counted as missing, a title that is a link to the product page and a card with no page printing no dead link, the link rectangle sitting over the name and not the price, and forty cards following their links onto the second page - plus the keyless run that still saves and prints but opens the keys file instead of pretending to look anything up. |
| `test-order-pdf.py` | Pillow | The order sheet, no Tk: the order's own number, state in words, paid date, delivery address and cards winning over the quote's, and the quote filling in whatever the order cannot give; the figures adding up to the total the customer was charged (a tax line only when the shop charges tax apart, an unexplained charge named rather than hidden); the pictures - downloaded once, kept in the documents folder, a second print reading the kept copy, and a picture the shop will not give costing that card its photo and nothing else; the paper - the same A4, the same band colour and the same white logo plate in the same place as the quote's, each card's picture actually drawn (its colour on the page), and a "no photo" box where there is none; and a thirty-card order running to more than one page. |
| `test-sale-preview.py` | Pillow | The preview before anything is written: which orders count as sales, what is still to add, the add-these-orders-only arguments, and the key offer when the file is missing. |
| `test-stock-compare.py` | Pillow | Matching two catalogues card by card (SKU first, then title), the action list of disagreements and one-sided cards, the confirmed write plan in both directions, the plugin's result file read conservatively, the refusal when the plugin cannot write, remembered dismissals and their restoration, the listing file written for cards only on the website, its one-click import (including a plugin that cannot import, refuses a file, or reports nothing) and the publish step that follows it (and the read-only look that comes first when nobody knows whether a draft exists - no PUBLISH question and no empty report when there is none), listings that exist but are not on sale (never written to, publish offered for drafts), a reader older than plugin 1.0.25 named by version, the direction stated in both write confirmations, the publisher's own draft tally read from its console line rather than its report file, a listing that carries no count at all being reported by its state instead of vanishing (and never written to), the nearest-title diagnosis that tells a wording problem, a duplicate product holding the listing, and a card that is not listed apart (and the liveness tie-break that keeps a sold-out duplicate from taking the listing), the condition guard that refuses to pair two different grades, the reader's own state tally, a card at zero on the website and nowhere else being left off the list (and named rather than silently dropped, while a zero card that is listed and differs still shows), the catalogue read four pages at a time and reassembled in order (and stopping at the page that ends it), the site's own page count driving a real progress bar where a read without one sweeps, the six ways the result can be sorted (with the panel's chooser re-reading the list without comparing again and remembering the choice), listings the other site holds at zero being called a count job, a plugin older than 1.0.26 being told apart from a real change when archived states come back (and an unreadable version being claimed for in neither direction), plus the on-demand comparison panel. |
| `test-stock-write.py` | none | Setting one count on a website product: the PUT carries only `stock_quantity`, the answer is read back so a 200 that kept the old number is a failure, a read-only key is explained, and one card failing does not stop the rest. |
| `test-cs-listing.py` | Pillow | Listing a website product on CanadianShopper: the fourteen import columns built from the website product (title, price, its own photo URL, stock count), the notes raised for a missing photo, a blank price or a card at zero, the file itself (utf-8-sig, the importer's filename, 500-row batches), the plugin's import result read conservatively, and the pipeline and this panel sharing one definition of the template. |
| `test-market-stock.py` | Pillow | The eBay/Facebook session and readers: the three ways a cookie gets pasted, eBay rows parsed with their quantities, Facebook states turned into listed/not listed, a login wall told apart from an empty shop, eBay's "Pardon our interruption" page and Facebook's 400 named as the site's check page rather than a stale cookie, the saved page found by the app itself (recognised by its contents, newest first, in the app's folder and in Downloads, too-old ones refused), a refusal falling back to that page with no file picker, a saved page that covers more winning over the live window, eBay read up to 250 listings with every page kept in the app's own copy, and the panel comparing on demand. |
| `test-cs-edit.py` | Pillow | Finding and changing one CanadianShopper listing: a remembered surname, a card number, an exact SKU and a listing id all finding the row while a miss finds nothing, the state filter (archived, on sale, drafts, everything not on sale), the row's words, the change plan carrying only the fields that changed (and nothing at all when nothing did), the confirmation naming old and new, the plugin's answer read conservatively (a listing it does not mention is unknown, never changed, while an answer naming any of the listing's ids - the product id beside the page id - confirms it and another product's id does not), a product id reported beside the listing id reaching the plan while a title-shaped key never does, a 404 printing how the plan named the listing and saying the site was not changed, and the exact row and answer plugin 1.0.30 sends (a catalogue id beside the product id it patches, answered by product id, reported as one changed listing and no UNKNOWN rows), a plugin refusing a listing for having no product id being read as a failure and understood as an old list, the panel counting how much of a read can be edited ("N with a product id, so N can be edited here"), a read in which no listing has one being told apart from a single row without one (its note says what the reading is missing rather than sending 2,541 cards to the dashboard, no pointless second read is offered, and the listing's own page opens instead), asking for a re-read before spending a write on a row with no product id rather than after it, re-planning the same change from the fresh row with the product id in it, and naming a listing the site gives no product id for and leaving it for the dashboard, and a list read by an older plugin being described by the plugin that read it, and the panel: reading the catalogue, searching, narrowing by state, the rows numbered in the list and counting from one again after a filter, the edit form opening filled with the title, price, quantity and state the listing has now, a price, a count and a state changing in one visit (and only those three being sent), a title changing alone (and a state the form was merely showing not being written back), a price that is not a number and a listing with no title both refused without the form closing, a state move from the two state buttons, a declined confirmation writing nothing, a plugin without the action saying so, an unconfirmed or failed write leaving the row alone, the listing's own page, a listing the plugin gave no address for opening the store with the card and its id on the clipboard instead of a dead end, a relative address joined to the site and another plugin's word for it read too, the same key in any spelling (`productUrl`, `PRODUCT_URL`, `Product URL`), every documented address key read, an address that is not the web refused rather than opened (and a bad key not hidden by a good one beside it), and the last read on disk being offered when the panel reopens. |
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
