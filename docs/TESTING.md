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
python test-photo-panel.py
python test-woo-orders.py
python test-sale-preview.py
python test-stock-compare.py
python test-market-stock.py
python test-stock-write.py
python test-cs-listing.py
python test-order-panel.py
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
| `test-facebook-feed.py` | pandas, openpyxl | |
| `test-user-settings.py`, `test-ebay-quicklist.py` | Pillow | Prints `Pillow is required` and stops if missing. |
| `test-linux-packaging.py` | Tk, Xvfb | Linux only; skips itself on Windows. |
| `test-market-rerun.py`, `test-pipeline-listing.py` | Pillow | Pipeline regression suite; no GUI. |
| `test-ai-prompts.py` | nothing | The shipped AI prompt files, read without Tk. |
| `test-process-utils.py` | nothing | No stray console windows; checks flags only. |
| `test-photo-replace.py` | Pillow | Sheet split, empty-slot detection, replacement naming. |
| `test-woo-media.py` | none - no network | The upload request, its refusals, and that a half-finished replacement is reported as one. |
| `test-woo-create.py` | none - no network | Creating the batch's products on the website: the CSV read back, the product body carrying only what is known, drafts first with the photos uploaded before the product exists, SKU lookup so a re-run skips instead of duplicating, publishing as a separate step only after the photos land, a 200 that kept the old status reported as the site's answer, one card's failure not stopping the rest, a refused key pair aborting at the first card, categories made parent-first, the exact key help, and the pipeline's own offer (no keys never falling back to the CSV silently, the app's answer obeyed through its flags). |
| `test-photo-panel.py` | Pillow | Drives the real Photos panel against a stubbed Tk: which image goes where, the arguments the plugin receives, and what each plugin version is allowed to be sent. |
| `test-woo-orders.py` | none - no network | Reading a pasted card list, which card a line means, when the app refuses to guess, and the exact order body that would be sent. |
| `test-order-panel.py` | Pillow | Drives the real order panel against a stubbed Tk: the pasted list, the picker, new vs existing orders, the discount, and the no-keys fallback. |
| `test-sale-preview.py` | Pillow | The preview before anything is written: which orders count as sales, what is still to add, the add-these-orders-only arguments, and the key offer when the file is missing. |
| `test-stock-compare.py` | Pillow | Matching two catalogues card by card (SKU first, then title), the action list of disagreements and one-sided cards, the confirmed write plan in both directions, the plugin's result file read conservatively, the refusal when the plugin cannot write, remembered dismissals and their restoration, the listing file written for cards only on the website, its one-click import (including a plugin that cannot import, refuses a file, or reports nothing) and the publish step that follows it (and the read-only look that comes first when nobody knows whether a draft exists - no PUBLISH question and no empty report when there is none), listings that exist but are not on sale (never written to, publish offered for drafts), a reader older than plugin 1.0.25 named by version, the direction stated in both write confirmations, the publisher's own draft tally read from its console line rather than its report file, a listing that carries no count at all being reported by its state instead of vanishing (and never written to), the nearest-title diagnosis that tells a wording problem, a duplicate product holding the listing, and a card that is not listed apart (and the liveness tie-break that keeps a sold-out duplicate from taking the listing), the condition guard that refuses to pair two different grades, the reader's own state tally, listings the other site holds at zero being called a count job, a plugin older than 1.0.26 being told apart from a real change when archived states come back (and an unreadable version being claimed for in neither direction), plus the on-demand comparison panel. |
| `test-stock-write.py` | none | Setting one count on a website product: the PUT carries only `stock_quantity`, the answer is read back so a 200 that kept the old number is a failure, a read-only key is explained, and one card failing does not stop the rest. |
| `test-cs-listing.py` | Pillow | Listing a website product on CanadianShopper: the fourteen import columns built from the website product (title, price, its own photo URL, stock count), the notes raised for a missing photo, a blank price or a card at zero, the file itself (utf-8-sig, the importer's filename, 500-row batches), the plugin's import result read conservatively, and the pipeline and this panel sharing one definition of the template. |
| `test-market-stock.py` | Pillow | The eBay/Facebook session and readers: the three ways a cookie gets pasted, eBay rows parsed with their quantities, Facebook states turned into listed/not listed, a login wall told apart from an empty shop, eBay's "Pardon our interruption" page and Facebook's 400 named as the site's check page rather than a stale cookie, the saved-page route, and the panel comparing on demand. |
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
