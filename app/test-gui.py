#!/usr/bin/env python3
# ===========================================================================
#  test-gui.py - the Control Panel test suite
# ===========================================================================
#  Boots the real window (on Windows: your desktop; on Linux: a virtual
#  display is started automatically), presses the actual buttons, and
#  checks that every one of them shells the exact same command the .bat
#  launchers run - plus the checklist viewer, the typed-list editor, the
#  cookie cleaner and the console streaming.
#
#  Run:  python test-gui.py
# ===========================================================================

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import gui  # noqa: E402

PASS = 0
FAIL = 0
XVFB = None
TMP = Path(tempfile.gettempdir())


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s %s" % (name, extra))


def ensure_display():
    global XVFB
    if sys.platform == "win32" or os.environ.get("DISPLAY"):
        return
    for d in (":99", ":98", ":97"):
        try:
            XVFB = subprocess.Popen(
                ["Xvfb", d, "-screen", "0", "1280x900x24"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            print("  (no Xvfb and no DISPLAY - install xvfb to test on Linux)")
            raise SystemExit(2)
        time.sleep(1.2)
        if XVFB.poll() is None:
            os.environ["DISPLAY"] = d
            return
        XVFB = None
    print("  (could not start a virtual display)")
    raise SystemExit(2)


def tasks_frame(app):
    return app._mode_frame.inner.winfo_children()[0]


def walk(widget):
    yield widget
    for c in widget.winfo_children():
        yield from walk(c)


def find_button(root, text, exact=True):
    for w in walk(root):
        try:
            t = w.cget("text")
        except Exception:
            continue
        if isinstance(t, str) and ((exact and t == text) or
                                   (not exact and t.startswith(text))):
            if hasattr(w, "invoke"):
                return w
    return None


class Capture:
    """Replaces Runner.start: records instead of launching."""

    def __init__(self):
        self.calls = []
        self.proceed = lambda: True

    def __call__(self, script, args, cwd, title, on_done=None, confirm=None):
        if confirm and not self.proceed():
            return False
        self.calls.append({"script": str(script), "args": [str(a) for a in
                                                           args],
                           "cwd": str(cwd), "title": title,
                           "confirm": confirm, "on_done": on_done})
        return True

    @property
    def last(self):
        return self.calls[-1] if self.calls else None


def main():
    ensure_display()
    import tkinter.messagebox as mb
    answers = {"askyesno": True, "shown": []}
    mb.askyesno = lambda *a, **k: answers["askyesno"]
    mb.showinfo = lambda *a, **k: answers["shown"].append(("info", a))
    mb.showwarning = lambda *a, **k: answers["shown"].append(("warn", a))
    mb.showerror = lambda *a, **k: answers["shown"].append(("error", a))
    import tkinter.filedialog as fd
    gui.filedialog.askopenfilename = lambda **k: ""
    gui.filedialog.askdirectory = lambda **k: ""
    gui.filedialog.askopenfilenames = lambda **k: ()

    # Preserve any runtime state already present beside the source tree.
    preserved = {}
    for path in (gui.CHECKLIST, gui.SETTINGS_FILE, gui.LOG_FILE,
                 gui.BASE / "sold-cards.txt", gui.BASE / "needs-photos.txt"):
        preserved[path] = path.read_bytes() if path.is_file() else None

    # Use an isolated test plugin directory. The test must not copy files into
    # or remove tools from the user's actual application installation.
    plugin_test_root = TMP / ("alexcollect-plugin-gui-test-%d" % os.getpid())
    shutil.rmtree(plugin_test_root, ignore_errors=True)
    gui.PLUGIN_MANAGER = gui.PluginManager(root=plugin_test_root)
    cs_package = plugin_test_root.parent / (plugin_test_root.name + "-src")
    shutil.rmtree(cs_package, ignore_errors=True)
    (cs_package / "tools").mkdir(parents=True)
    (cs_package / "tools" / "sold-cards.py").write_text("# test stub\\n")
    (cs_package / "tools" / "cs-image-sync.py").write_text("# test stub\\n")
    (cs_package / "tools" / "pad-and-upload.py").write_text("# test stub\\n")
    (cs_package / "tools" / "cs_stage_hook.py").write_text("# test stub\\n")
    (cs_package / "plugin.json").write_text(json.dumps({
        "id": "canadianshopper", "name": "CanadianShopper test stub",
        "version": "1.0.0", "host_api": 1, "min_core_version": "2.21",
        "description": "GUI test fixture only.",
        "capabilities": ["after_sale.stock_update", "batch.photo_stage",
                         "batch.photo_wire", "batch.photo_cache_repair",
                         "batch.pipeline_stage"],
        "actions": {"after_sale.stock_update": "stock_update",
                    "batch.photo_stage": "photo_sync",
                    "batch.photo_wire": "photo_sync",
                    "batch.photo_cache_repair": "photo_upload",
                    "batch.pipeline_stage": "pipeline_stage"},
        "tools": {"stock_update": "tools/sold-cards.py",
                  "photo_sync": "tools/cs-image-sync.py",
                  "photo_upload": "tools/pad-and-upload.py",
                  "pipeline_stage": "tools/cs_stage_hook.py"}
    }), encoding="utf-8")
    cs_zip = plugin_test_root.parent / (plugin_test_root.name + "-canadianshopper.zip")
    shutil.make_archive(str(cs_zip.with_suffix("")), "zip",
                        root_dir=cs_package)
    gui.PLUGIN_MANAGER.install_zip(cs_zip)

    print("== 1. construction and registry ==")
    app = gui.App()
    app.withdraw()
    app.update()
    check("window builds", app.winfo_exists())
    ids = set(gui.PANEL_ORDER)
    check("titles for every panel", set(gui.TITLES) == ids)
    check("blurbs for every panel", set(gui.BLURBS) == ids)
    check("docs for every panel", ids - {"welcome"} <= set(gui.DOCS),
          str(ids - set(gui.DOCS)))
    check("builders for every panel", set(gui.PANEL_BUILDERS) == ids)

    print("== 2. the three modes ==")
    for mode, name in (("wizard", "wizard"), ("menu", "task menu"),
                       ("tabs", "tabs")):
        app.show_mode(mode)
        app.update()
        check("%s renders" % name, app._mode_frame is not None and
              len(app._mode_frame.winfo_children()) > 0)
    app.show_mode("menu")
    app.update()

    print("== 3. every panel builds from the task menu ==")
    for pid in gui.PANEL_ORDER:
        tasks_frame(app).show_panel(pid)
        app.update()
        check("panel: %s" % pid, app._mode_frame.winfo_children())
    app.show_mode("menu")
    app.update()

    print("== 4. button commands match the .bat launchers ==")
    cap = Capture()
    app.runner.start = cap

    def panel(pid):
        app.show_mode("menu")
        app.update()
        tasks_frame(app).show_panel(pid)
        app.update()

    panel("combine")
    find_button(app, "Preview (--dry-run)").invoke()
    check("combine preview args", cap.last["args"] == ["--dry-run"],
          str(cap.last["args"]))
    find_button(app, "Combine now").invoke()
    check("combine real args", cap.last["args"] == [], str(cap.last["args"]))

    panel("stage")
    find_button(app, "Stage the photos", exact=False).invoke()
    check("stage args", cap.last["args"] == ["--mode", "prepare", "-y",
              "--cookie-file", str(gui.CS_COOKIE_FILE)], str(cap.last["args"]))

    panel("wire")
    find_button(app, "Dry-run (writes nothing)").invoke()
    check("wire dry-run", cap.last["args"] == ["--mode", "wire",
              "--cookie-file", str(gui.CS_COOKIE_FILE), "--dry-run"],
          str(cap.last["args"]))
    find_button(app, "Wire for real").invoke()
    check("wire real", cap.last["args"] == ["--mode", "wire",
              "--cookie-file", str(gui.CS_COOKIE_FILE)], str(cap.last["args"]))
    check("wire real confirms", cap.last["confirm"] and "Dry-run" in
          cap.last["confirm"], str(cap.last["confirm"]))

    panel("rerun")
    expected = ["--mode", "upload", "--images", "front,back",
                "--cookie-file", str(gui.CS_COOKIE_FILE),
                "--cache", str(gui.BASE / "image-cache.json"),
                "--report", str(gui.BASE / "reports" /
                                "image-sync-latest.csv")]
    find_button(app, "Dry-run (writes nothing)").invoke()
    check("rerun dry-run = rerun.bat + --dry-run",
          cap.last["args"] == expected + ["--dry-run"], str(cap.last["args"]))
    find_button(app, "Re-point for real").invoke()
    check("rerun real = rerun.bat", cap.last["args"] == expected,
          str(cap.last["args"]))
    check("rerun runs from the tools folder",
          cap.last["cwd"] == str(gui.BASE), cap.last["cwd"])

    panel("zerostock")
    find_button(app, "Preview: what sits at 0?").invoke()
    check("zero-stock preview", cap.last["args"] == ["--zero-stock"],
          str(cap.last["args"]))
    find_button(app, "Archive them").invoke()
    check("zero-stock apply requests preview-based confirmation",
          cap.last["args"] == ["--zero-stock", "--apply", "--gui-dialogs"] and
          cap.last["confirm"] is None, str(cap.last))

    print("== 5. a card sold - typed list, end to end ==")
    panel("sold")
    find_button(app, "Type the cards...").invoke()
    app.update()
    editor = None
    for w in app.winfo_children():
        if isinstance(w, gui.tk.Toplevel) and "sold" in w.title().lower():
            editor = w
    check("editor opens", editor is not None)
    if editor:
        txt = next(w for w in walk(editor) if isinstance(w, gui.tk.Text))
        txt.insert("1.0", "1992 Skybox Larry Card, 2\n1991 Pro Set Wayne, last")
        find_button(editor, "Save title").invoke()
        app.update()
        check("list file written",
              (gui.BASE / "sold-cards.txt").exists())
        find_button(app, "Add to the checklist", exact=False).invoke()
        a = cap.last
        check("sold uses sold-everywhere.py",
              a["script"] == str(gui.BASE / "sold-everywhere.py"),
              a["script"])
        check("sold typed args", a["args"] == [
            "--list", str(gui.BASE / "sold-cards.txt"),
            "--sold-on", "website", "--checklist", str(gui.CHECKLIST)],
            str(a["args"]))
        cs_radio = find_button(app, "CanadianShopper", exact=True)
        check("CanadianShopper is a sale-source radio choice",
              cs_radio is not None)
        check("plugin-enabled sold panel shows its independent checkbox and controls",
              find_button(app, "Also fix CanadianShopper", exact=False) is not None and
              find_button(app, "CanadianShopper only: preview the stock change",
                          exact=False) is not None and
              find_button(app, "Apply the previewed change", exact=False) is not None)
        cs_box = find_button(app, "Also fix CanadianShopper", exact=False)
        cs_box.invoke()
        find_button(app, "Add to the checklist", exact=False).invoke()
        check("--cs and dialogs forwarded when ticked",
              "--cs" in cap.last["args"] and
              "--gui-dialogs" in cap.last["args"], str(cap.last["args"]))
        cs_box.invoke()
        cs_radio.invoke()
        find_button(app, "Add to the checklist", exact=False).invoke()
        check("CanadianShopper sale source is passed to the checklist tool",
              "--sold-on" in cap.last["args"] and
              cap.last["args"][cap.last["args"].index("--sold-on") + 1] ==
              "canadianshopper", str(cap.last["args"]))
        find_button(app, "my website", exact=True).invoke()
        find_button(app, "CanadianShopper only: preview the stock change"
                    ).invoke()
        a = cap.last
        check("CS-only preview uses sold-cards.py without --apply",
              a["script"] == gui.TOOL("sold-cards.py") and
              a["args"] == ["--list", str(gui.BASE / "sold-cards.txt"),
                            "--cookie-file", str(gui.CS_COOKIE_FILE)],
              str(a["args"]))
        find_button(app, "Apply the previewed change").invoke()
        check("CS-only apply requests preview and dialog",
              cap.last["args"] == ["--list", str(gui.BASE / "sold-cards.txt"),
                                   "--cookie-file", str(gui.CS_COOKIE_FILE),
                                   "--apply", "--gui-dialogs"] and
              cap.last["confirm"] is None, str(cap.last))

    print("== 6. a card needs new photos ==")
    panel("newphotos")
    find_button(app, "Type the cards...").invoke()
    app.update()
    editor = next((w for w in app.winfo_children()
                   if isinstance(w, gui.tk.Toplevel) and "photos" in
                   w.title().lower()), None)
    check("photo editor opens", editor is not None)
    if editor:
        txt = next(w for w in walk(editor) if isinstance(w, gui.tk.Text))
        txt.insert("1.0", "1989 O-Pee-Chee Gretzky")
        find_button(editor, "Save and use this list").invoke()
        app.update()
        a = cap.last
        check("photo reminder args", a["args"] == [
            "--images-file", str(gui.BASE / "needs-photos.txt"),
            "--scan-dir", app.settings["scan_dir"],
            "--checklist", str(gui.CHECKLIST)], str(a["args"]))

    print("== 7. the checklist viewer ==")
    gui.CHECKLIST.write_text(
        'num,done,card,channel,what to do,link,added,ref\n'
        '1,,Test Card A,canadianshopper,reduce the stock by 1,,2026-10-18,o1\n'
        '2,,Test Card B,ebay,lower the quantity by 1,'
        'https://www.ebay.ca/sh/lst/active,2026-10-18,o2\n'
        '3,,Test Card C,facebook,mark it sold,'
        'https://www.facebook.com/marketplace/you/selling,2026-10-18,\n'
        '4,x,Test Card D,canadianshopper,already done,,2026-10-18,o3\n',
        encoding="utf-8")
    viewer = gui.ChecklistViewer(app)
    app.update()
    check("viewer shows 3 outstanding + 1 done",
          len(viewer.vars) == 3 and len(viewer.rows) == 4,
          "%d vars %d rows" % (len(viewer.vars), len(viewer.rows)))
    viewer.vars["2"].set(True)
    viewer.vars["3"].set(True)
    viewer.tick_selected()
    check("tick selected -> --done 2,3",
          cap.last["args"][cap.last["args"].index("--done") + 1] == "2,3",
          str(cap.last["args"]))
    viewer.tick_all()
    check("tick all -> --done all (after confirm)",
          cap.last["args"][cap.last["args"].index("--done") + 1] == "all")
    answers["askyesno"] = False
    n = len(cap.calls)
    viewer.tick_all()
    check("declining 'tick everything' writes nothing", len(cap.calls) == n)
    answers["askyesno"] = True
    opened = []
    old_open_edge_urls = gui.open_edge_urls
    gui.open_edge_urls = lambda urls, **k: (opened.extend(urls) or "Microsoft Edge")
    try:
        viewer.vars["2"].set(True)
        viewer.open_link()
    finally:
        gui.open_edge_urls = old_open_edge_urls
    check("row link opens the eBay page",
          any("ebay.ca" in u for u in opened), str(opened))
    viewer.destroy()
    gui.CHECKLIST.unlink()
    check("viewer cleanup removes the test checklist",
          not gui.CHECKLIST.exists())

    print("== 8. cookie handling ==")
    row = ("__Secure-better-auth.session_token\t"
           "QI9Bk2mdRz7x1PqLmNoP3RsTuVwXyZ0123456789abcd."
           "A4KwPn2xrE-something%3D%3D\t/\t2027-01-01\t\u2713")
    got = gui.clean_cookie_row(row)
    check("devtools table row cleaned",
          got == "__Secure-better-auth.session_token="
                 "QI9Bk2mdRz7x1PqLmNoP3RsTuVwXyZ0123456789abcd."
                 "A4KwPn2xrE-something%3D%3D", repr(got))
    got2 = gui.clean_cookie_row("tok123sig.signaturepart")
    check("bare value is named and kept",
          got2 == "__Secure-better-auth.session_token=tok123sig.signaturepart",
          repr(got2))
    ok, msg = gui.test_connection(None)
    check("no cookie -> friendly message", ok is False and
          "Paste" in msg, msg)
    ok2, msg2 = gui.test_connection("not-a-real-cookie-value-just-testing")
    check("bad cookie -> graceful answer (no crash)",
          ok2 in (True, False) and isinstance(msg2, str), msg2[:60])

    print("== 9. settings ==")
    app.show_mode("menu")
    app.update()
    tasks_frame(app).show_panel("cookie")
    app.update()
    app._pipeline_var.set(str(TMP / "pipeline-test"))
    app._scan_var.set(str(TMP / "scan-test"))
    find_button(app, "Save folders").invoke()
    s = gui.load_settings()
    check("folders saved to settings",
          s["pipeline_dir"] == str(TMP / "pipeline-test") and
          s["scan_dir"] == str(TMP / "scan-test"), str(s))
    app.settings.update(s)
    check("startup mode default is the task menu",
          app.settings.get("startup_mode", "menu") == "menu")

    print("== 10. real streaming through the console ==")
    app.runner = gui.Runner(app)          # back to the real one
    app.update()
    done = {"rc": None}
    app.runner.start("-c", ["print('hello-gui-stream')",
                            "print('second-line')"],
                     cwd=str(gui.BASE), title="stream smoke",
                     on_done=lambda rc: done.update(rc=rc))
    for _ in range(200):
        app.update()
        app.runner.drain()
        if done["rc"] is not None:
            break
        time.sleep(0.05)
    text = app.console.get("1.0", "end")
    check("stream smoke ran", done["rc"] == 0, str(done["rc"]))
    check("console caught the output", "hello-gui-stream" in text and
          "second-line" in text)
    check("console shows the command", "$ " in text and "stream smoke" in text)

    print("== 11. end to end: the GUI runs the real tool ==")
    app.settings["pipeline_dir"] = str(gui.BASE)   # section 9 moved it away
    gui.CHECKLIST.write_text(
        'num,done,card,channel,what to do,link,added,ref\n'
        '1,,1992 Skybox Larry Card,canadianshopper,reduce the stock by 1,,'
        '2026-10-18,o1\n', encoding="utf-8")
    app.show_mode("menu")
    app.update()
    tasks_frame(app).show_panel("checklist")
    app.update()
    find_button(app, "What is outstanding?", exact=False).invoke()
    done2 = {"rc": None}
    app.runner.on_done = lambda rc: done2.update(rc=rc)
    for _ in range(200):
        app.update()
        app.runner.drain()
        if done2["rc"] is not None:
            break
        time.sleep(0.05)
    text2 = app.console.get("1.0", "end")
    check("real sold-everywhere --status ran", done2["rc"] == 0,
          str(done2["rc"]))
    check("the outstanding card is named in the console",
          "1992 Skybox Larry Card" in text2)
    gui.CHECKLIST.unlink()

    print("== 12. the pipeline dialog (mirrors the user's .bat) ==")
    cap2 = Capture()
    app.runner.start = cap2          # section 10 restored the real runner
    cap = cap2
    # 12a  .webp must be offered by the photo picker
    panel("square")
    picked = {}
    gui.filedialog.askopenfilenames = lambda **k: picked.update(k) or ()
    find_button(app, "Pick photo(s)...").invoke()
    check(".webp offered by the photo picker",
          "webp" in str(picked.get("filetypes", "")), str(picked))
    gui.filedialog.askopenfilenames = lambda **k: ()

    # 12b  the two prompts: embedded, distinct, copied to the clipboard
    check("both prompts embedded",
          "SEO Image titles" in gui.PROMPT_FALLBACKS["multi"] and
          "SEO Image titles" in gui.PROMPT_FALLBACKS["single"])
    check("multi-grade prompt puts the grade in the titles",
          "-[grade]" in gui.PROMPT_FALLBACKS["multi"] and
          "-[grade]" not in gui.PROMPT_FALLBACKS["single"])
    tmpdir = TMP / "gui-pipe-test"
    tmpdir.mkdir(exist_ok=True)
    (tmpdir / "card_pipeline.py").write_text("print('pipeline placeholder')\n")
    front_scan = tmpdir / "front-sheet.png"
    back_scan = tmpdir / "back-sheet.png"
    front_scan.write_bytes(b"png"); back_scan.write_bytes(b"png")
    app.settings["pipeline_dir"] = str(tmpdir)
    panel("pipeline")
    find_button(app, "Run the card pipeline", exact=False).invoke()
    app.update()
    dlg = next((w for w in app.winfo_children()
                if isinstance(w, gui.tk.Toplevel) and "pipeline" in
                w.title().lower()), None)
    check("the pipeline dialog appears (prompt reminder included)",
          dlg is not None)
    if dlg:
        find_button(dlg, "Multiple grades", exact=False).invoke()
        try:
            clip = app.clipboard_get()
        except Exception as e:
            clip = "CLIPBOARD-ERROR: %s" % e
        check("multi-grade prompt landed on the clipboard",
              "SEO Image titles" in clip and "-[grade]" in clip,
              clip[:60])
        entries = [w for w in walk(dlg) if isinstance(w, gui.ttk.Entry)]
        check("FRONT and BACK scan rows exist", len(entries) == 2,
              str(len(entries)))
        entries[0].delete(0, "end"); entries[0].insert(0, str(front_scan))
        entries[1].delete(0, "end"); entries[1].insert(0, str(back_scan))
        long_answer = "SEO Image titles:\n" + "x" * 220
        app.clipboard_clear(); app.clipboard_append(long_answer); app.update()
        find_button(dlg, "Split the scans", exact=False).invoke()
        app.update()
        a = cap.last
        check("phase 1 = split --front --back (like the .bat)",
              a["script"] == str(tmpdir / "card_pipeline.py") and
              a["cwd"] == str(tmpdir) and
              a["args"] == ["split", "--front", str(front_scan),
                            "--back", str(back_scan)], str(a["args"]))
        a["on_done"](0)                      # the split finished fine
        a = cap.last
        check("phase 2 = listing --input _card_input.txt --facebook",
              a["args"] == ["listing", "--input",
                            str(tmpdir / "_card_input.txt"), "--facebook"],
              str(a["args"]))
        input_file = tmpdir / "_card_input.txt"
        check("the AI answer was captured for the pipeline",
              input_file.exists() and
              input_file.read_bytes()[:3] == b"\xef\xbb\xbf" and
              "x" * 50 in input_file.read_text(encoding="utf-8-sig"))
        input_file.unlink()

        # a too-short answer must be refused, nothing runs
        n = len(cap.calls)
        n_shown = len(answers["shown"])
        app.clipboard_clear(); app.update()   # no prompt, no answer anywhere
        app.update_idletasks(); app.update()
        panel("pipeline")
        find_button(app, "Run the card pipeline", exact=False).invoke()
        app.update()
        dlg = next((w for w in app.winfo_children()
                    if isinstance(w, gui.tk.Toplevel) and "pipeline" in
                    w.title().lower()), None)
        entries = [w for w in walk(dlg) if isinstance(w, gui.ttk.Entry)]
        entries[0].insert(0, str(front_scan))
        find_button(dlg, "Split the scans", exact=False).invoke()
        app.update()
        check("a short/empty answer is refused (nothing runs)",
              len(cap.calls) == n and len(answers["shown"]) > n_shown,
              "%d calls, shown %d->%d" % (len(cap.calls) - n, n_shown,
                                          len(answers["shown"])))
        dlg.destroy()

    # 12c  the browse flow: only reachable while no pipeline is findable,
    # so the shipped one is hidden for this sub-test and restored after
    shipped = gui.BASE / "pipeline" / "card_pipeline.py"
    shipped_hidden = gui.BASE / "pipeline" / "card_pipeline.py.test-hidden"
    shipped.rename(shipped_hidden)
    try:
        app.settings["pipeline_dir"] = str(gui.BASE)
        answers["askyesno"] = True
        gui.filedialog.askopenfilename = lambda **k: ""
        panel("pipeline")
        n = len(cap.calls)
        find_button(app, "Run the card pipeline", exact=False).invoke()
        app.update()
        check("missing pipeline + cancelled browse = no run, no crash",
              len(cap.calls) == n)
        fake = TMP / "gui-pipe-fake"
        fake.mkdir(exist_ok=True)
        (fake / "card_pipeline.py").write_text("print('fake')\n")
        gui.filedialog.askopenfilename = \
            lambda **k: str(fake / "card_pipeline.py")
        find_button(app, "Run the card pipeline", exact=False).invoke()
        app.update()
        check("browsing for the pipeline saves its folder",
              gui.load_settings()["pipeline_dir"] == str(fake),
              gui.load_settings()["pipeline_dir"])
        dlg = next((w for w in app.winfo_children()
                    if isinstance(w, gui.tk.Toplevel) and "pipeline" in
                    w.title().lower()), None)
        if dlg:
            entries = [w for w in walk(dlg) if isinstance(w, gui.ttk.Entry)]
            entries[0].delete(0, "end")
            entries[0].insert(0, str(front_scan))
            entries[1].delete(0, "end")          # drop any remembered back
            app.clipboard_clear()
            app.clipboard_append("SEO Image titles:\n" + "y" * 220)
            app.update()
            find_button(dlg, "Split the scans", exact=False).invoke()
            app.update()
            check("run proceeds from the browsed folder",
                  cap.last["cwd"] == str(fake), cap.last["cwd"])
        for w in list(app.winfo_children()):
            if isinstance(w, gui.tk.Toplevel) and "pipeline" in                     w.title().lower():
                w.destroy()          # no stale dialogs for section 13
    finally:
        shipped_hidden.rename(shipped)
    app.update()

    # 12d  the wizard continues after the cookie test succeeds
    orig_test = gui.test_connection
    gui.test_connection = lambda cookie=None: (True, "Session OK (test)")
    app.show_mode("wizard")
    app.update()
    w = app._mode_frame.inner.winfo_children()[0]
    w.page = 1
    w.render()
    app.update()
    find_button(app, "Test the connection").invoke()
    cont = None
    for _ in range(60):
        app.update()
        cont = find_button(app, "Connection works", exact=False)
        if cont is not None:
            break
        time.sleep(0.05)
    check("a successful test reveals the continue button", cont is not None)
    if cont:
        cont.invoke()
        app.update()
        check("continue advances to the pipeline step", w.page == 2,
              str(w.page))
    gui.test_connection = orig_test

    print("== 13. real chained run: split then listing ==")
    for w in list(app.winfo_children()):
        if isinstance(w, gui.tk.Toplevel) and "pipeline" in w.title().lower():
            w.destroy()
    stub = TMP / "gui-pipe-stub"
    stub.mkdir(exist_ok=True)
    (stub / "card_pipeline.py").write_text(
        "import sys\n"
        "print('PHASE', sys.argv[1])\n"
        "print('ARGS:', ' '.join(sys.argv[2:]))\n", encoding="utf-8")
    app.settings["pipeline_dir"] = str(stub)
    app.runner = gui.Runner(app)     # a real runner again (12 used a capture)
    done3 = {"n": 0}
    orig_start = app.runner.start

    def counting_start(script, args, cwd, title, on_done=None, confirm=None):
        prev = on_done

        def wrapped(rc):
            if prev:
                prev(rc)
            done3["n"] += 1
        return orig_start(script, args, cwd, title,
                          on_done=wrapped, confirm=confirm)
    app.runner.start = counting_start
    panel("pipeline")
    find_button(app, "Run the card pipeline", exact=False).invoke()
    app.update()
    dlg = next((w for w in app.winfo_children()
                if isinstance(w, gui.tk.Toplevel) and "pipeline" in
                w.title().lower()), None)
    entries = [w for w in walk(dlg) if isinstance(w, gui.ttk.Entry)]
    entries[0].delete(0, "end")
    entries[0].insert(0, str(front_scan))
    entries[1].delete(0, "end")
    entries[1].insert(0, str(back_scan))
    app.clipboard_clear()
    app.clipboard_append("SEO Image titles:\n" + "z" * 220); app.update()
    find_button(dlg, "Split the scans", exact=False).invoke()
    for _ in range(400):
        app.update()
        app.runner.drain()
        if done3["n"] >= 2:
            break
        time.sleep(0.05)
    text3 = app.console.get("1.0", "end")
    check("both phases really ran", done3["n"] == 2, str(done3["n"]))
    check("split output streamed", "PHASE split" in text3)
    check("listing ran after the split succeeded", "PHASE listing" in text3)
    check("the answer file went to the listing phase",
          "_card_input.txt" in text3)
    app.runner.start = orig_start

    print("== 14. click-or-drag: boot scans + live scan feedback ==")
    # 14a  the dialog confirms a chosen scan immediately
    app.settings["pipeline_dir"] = str(stub)
    panel("pipeline")
    find_button(app, "Run the card pipeline", exact=False).invoke()
    app.update()
    dlg = next((w for w in app.winfo_children()
                if isinstance(w, gui.tk.Toplevel) and "pipeline" in
                w.title().lower()), None)
    check("dialog opens with the action button present",
          dlg is not None and
          find_button(dlg, "Split the scans", exact=False) is not None)
    entries = [w for w in walk(dlg) if isinstance(w, gui.ttk.Entry)]
    entries[0].delete(0, "end")
    entries[0].insert(0, str(front_scan))
    dlg.update()
    scan_text = dlg.scan_label.cget("text") if hasattr(dlg, "scan_label") \
        else ""
    check("a chosen FRONT scan is confirmed by name",
          "FRONT scan ready" in scan_text and
          Path(front_scan).name in scan_text, scan_text)
    entries[1].delete(0, "end")
    entries[1].insert(0, str(back_scan))
    dlg.update()
    check("a chosen BACK scan is confirmed too",
          "BACK scan ready" in dlg.scan_label.cget("text"))
    dlg.destroy()

    # 14b  scans passed at boot (drop on the icon) -> pre-filled dialog
    boot_settings = dict(app.settings)
    boot_settings["pipeline_dir"] = str(stub)
    app2 = gui.App(settings=boot_settings, scans=[str(front_scan),
                                                  str(back_scan)])
    app2.withdraw()
    dlg2 = None
    for _ in range(80):
        app2.update()
        dlg2 = next((w for w in app2.winfo_children()
                     if isinstance(w, gui.tk.Toplevel) and "pipeline" in
                     w.title().lower()), None)
        if dlg2 is not None:
            break
        time.sleep(0.02)
    check("dropped scans open the pipeline dialog by themselves",
          dlg2 is not None)
    if dlg2:
        e = [w for w in walk(dlg2) if isinstance(w, gui.ttk.Entry)]
        check("FRONT and BACK prefilled from the drop",
              e[0].get() == str(front_scan) and e[1].get() == str(back_scan),
              "%s | %s" % (e[0].get(), e[1].get()))
        check("the prefill is announced in the dialog",
              "FRONT scan ready" in dlg2.scan_label.cget("text"))
        dlg2.destroy()
    app2.destroy()

    print("== 15. clipboard guard + bare prompts are visible ==")
    # 15a  the clipboard still holding the PROMPT must be refused
    app.settings["pipeline_dir"] = str(stub)
    panel("pipeline")
    n = len(cap.calls)
    n_shown = len(answers["shown"])
    gui.filedialog.askopenfilename = lambda **k: ""
    find_button(app, "Run the card pipeline", exact=False).invoke()
    app.update()
    dlg = next((w for w in app.winfo_children()
                if isinstance(w, gui.tk.Toplevel) and "pipeline" in
                w.title().lower()), None)
    entries = [w for w in walk(dlg) if isinstance(w, gui.ttk.Entry)]
    entries[0].delete(0, "end"); entries[0].insert(0, str(front_scan))
    app.clipboard_clear()
    app.clipboard_append(gui.load_prompt("multi")); app.update()
    find_button(dlg, "Split the scans", exact=False).invoke()
    app.update()
    check("the prompt on the clipboard is refused as 'the question'",
          len(cap.calls) == n and len(answers["shown"]) > n_shown)
    dlg.destroy()

    # 15b  a tool that asks WITHOUT pressing Enter still shows its question
    app.runner = gui.Runner(app)
    app.update()
    app.runner.start("-c",
                     ["import time;print('pick a category [1/2/3]: ', "
                      "end='');time.sleep(1.0);"
                      "a = input(); print('got:' + a)"],
                     cwd=str(gui.BASE), title="bare prompt probe",
                     on_done=lambda rc: None)
    asked = answered = nagged = False
    for _ in range(300):
        app.update()
        app.runner.drain()
        text = app.console.get("1.0", "end")
        if "pick a category" in text:
            asked = True
        if getattr(app, "_saw_dangling_prompt", False):
            nagged = True
        if asked and not answered:
            app.runner.send("2")
            answered = True          # send once; keep polling
        if "got:2" in text:
            break
        time.sleep(0.03)
    check("a bare prompt (no Enter) is visible in the console", asked)
    check("the status bar tells you the tool wants an answer", nagged)
    check("the answer reaches the tool and it finishes",
          "got:2" in app.console.get("1.0", "end"))
    check("known questions explain themselves (the category hint)",
          "NOTE: The pipeline detected categories" in
          app.console.get("1.0", "end"))
    app.runner.stop()

    print("== 16. live clipboard monitor ==")
    cap = Capture()                    # section 15 restored a real runner
    app.runner.start = cap
    check("classifier: the answer",
          gui.classify_clipboard("SEO Image titles:\n" + "a" * 250)[0] ==
          "answer")
    check("classifier: the prompt",
          gui.classify_clipboard(gui.load_prompt("multi"))[0] == "prompt")
    check("classifier: short", gui.classify_clipboard("tiny")[0] == "short")
    check("classifier: other", gui.classify_clipboard("word " * 80)[0] ==
          "other")
    app.settings["pipeline_dir"] = str(stub)
    panel("pipeline")
    gui.filedialog.askopenfilename = lambda **k: ""
    find_button(app, "Run the card pipeline", exact=False).invoke()
    app.update()
    dlg = next((w for w in app.winfo_children()
                if isinstance(w, gui.tk.Toplevel) and "pipeline" in
                w.title().lower()), None)
    check("the dialog shows what the clipboard holds right now",
          dlg is not None and
          "Clipboard right now" in dlg.clip_label.cget("text"),
          dlg.clip_label.cget("text")[:60] if dlg else "no dialog")
    if dlg:
        entries = [w for w in walk(dlg) if isinstance(w, gui.ttk.Entry)]
        entries[0].delete(0, "end"); entries[0].insert(0, str(front_scan))
        # the answer -> green "ready"
        app.clipboard_clear()
        app.clipboard_append("SEO Image titles:\n" + "b" * 240); app.update()
        find_button(dlg, "Split the scans", exact=False).invoke()
        app.update()
        check("pressing the button with the answer on the clipboard runs",
              cap.last["args"] and cap.last["args"][0] == "split")
        panel("pipeline")
        find_button(app, "Run the card pipeline", exact=False).invoke()
        app.update()
        dlg = next((w for w in app.winfo_children()
                    if isinstance(w, gui.tk.Toplevel) and "pipeline" in
                    w.title().lower()), None)
        entries = [w for w in walk(dlg) if isinstance(w, gui.ttk.Entry)]
        entries[0].delete(0, "end"); entries[0].insert(0, str(front_scan))
        # the prompt -> refused again
        app.clipboard_clear()
        app.clipboard_append(gui.load_prompt("single")); app.update()
        n = len(cap.calls)
        n_shown = len(answers["shown"])
        find_button(dlg, "Split the scans", exact=False).invoke()
        app.update()
        check("a stale prompt on the clipboard is still refused",
              len(cap.calls) == n and len(answers["shown"]) > n_shown)
        # long unrelated text -> asked before use; no = nothing runs
        answers["askyesno"] = False
        app.clipboard_clear()
        app.clipboard_append("word " * 80); app.update()
        find_button(dlg, "Split the scans", exact=False).invoke()
        app.update()
        check("unrelated long clipboard text asks first (no = no run)",
              len(cap.calls) == n)
        answers["askyesno"] = True
        find_button(dlg, "Split the scans", exact=False).invoke()
        app.update()
        check("answering yes runs with the unrelated text",
              len(cap.calls) == n + 1)
        dlg.destroy()

    print("== 17. prompt buttons vs the answer + sending Enter ==")
    panel("pipeline")
    gui.filedialog.askopenfilename = lambda **k: ""
    find_button(app, "Run the card pipeline", exact=False).invoke()
    app.update()
    dlg = next((w for w in app.winfo_children()
                if isinstance(w, gui.tk.Toplevel) and "pipeline" in
                w.title().lower()), None)
    answer_text = "SEO Image titles:\n" + "d" * 240
    app.clipboard_clear(); app.clipboard_append(answer_text); app.update()
    dlg.refresh_clip()
    answers["askyesno"] = False          # decline the replace
    find_button(dlg, "Multiple grades", exact=False).invoke()
    app.update()
    try:
        now = app.clipboard_get()
    except Exception:
        now = ""
    check("declining keeps the answer on the clipboard", now == answer_text)
    answers["askyesno"] = True
    find_button(dlg, "Multiple grades", exact=False).invoke()
    app.update()
    now = app.clipboard_get()
    check("accepting puts the prompt on the clipboard",
          gui.classify_clipboard(now)[0] == "prompt")
    check("the live line explains the prompt is waiting to be pasted",
          "PROMPT you copied" in dlg.clip_label.cget("text"),
          dlg.clip_label.cget("text")[:60])
    app.clipboard_clear(); app.clipboard_append(answer_text); app.update()
    dlg.refresh_clip()
    check("copying the answer flips the live line to ready",
          "ready" in dlg.clip_label.cget("text"),
          dlg.clip_label.cget("text")[:60])
    dlg.destroy()

    # an empty answer box sends a bare Enter
    app.runner = gui.Runner(app)         # a real runner again
    app.update()
    app.runner.start("-c",
                     ["a = input(); print('got' + ':[' + repr(a) + ']')"],
                     cwd=str(gui.BASE), title="empty-enter probe",
                     on_done=lambda rc: None)
    sent = False
    for _ in range(300):
        app.update(); app.runner.drain()
        if "got:['']" in app.console.get("1.0", "end"):
            break
        if not sent:
            app.inp.delete(0, "end")     # leave it EMPTY
            app._send_input()            # Send with an empty box = Enter
            sent = True
        time.sleep(0.03)
    app.runner.stop()
    check("Send with an empty box sends a bare Enter",
          "got:['']" in app.console.get("1.0", "end"),
          app.console.get("1.0", "end")[-160:])

    # the Send Enter button sends Enter even with junk in the box
    app.runner = gui.Runner(app)
    app.update()
    app.runner.start("-c",
                     ["a = input(); print('got2' + ':[' + repr(a) + ']')"],
                     cwd=str(gui.BASE), title="enter-button probe",
                     on_done=lambda rc: None)
    sent = False
    for _ in range(300):
        app.update(); app.runner.drain()
        if "got2:['']" in app.console.get("1.0", "end"):
            break
        if not sent:
            app.inp.insert(0, "junk-not-sent")
            find_button(app, "Send Enter").invoke()
            sent = True
        time.sleep(0.03)
    app.runner.stop()
    text = app.console.get("1.0", "end")
    check("the Send Enter button sends Enter by itself",
          "got2:['']" in text and "> junk-not-sent" not in text,
          text[-160:])

    print("== 18. core mode: CanadianShopper treated like Facebook ==")
    app3 = gui.App(settings=dict(app.settings))
    app3.withdraw()
    app3.cs_addon = False               # simulate the add-on removed
    app3.show_mode("menu")
    app3.update()
    tf3 = app3._mode_frame.inner.winfo_children()[0]
    labels = set()
    for w in walk(tf3):
        try:
            labels.add(str(w.cget("text")))
        except Exception:
            pass
    check("no staging/wiring/zero-stock tasks in the core menu",
          not ({"Stage the photos", "Wire the photos",
                "Archive listings at 0", "Re-point photos (repair)"} &
               labels))
    check("the generic Plugins group remains available",
          "Plugins" in labels, str(sorted(labels)))
    tf3.show_panel("sold")
    app3.update()
    sold_widgets = list(walk(app3._mode_frame.inner))
    check("CanadianShopper is still a sale-source choice without the plugin",
          find_button(app3, "CanadianShopper", exact=True) is not None)
    check("the sold panel hides plugin-only checkbox and two controls",
          find_button(app3, "Also fix CanadianShopper", exact=False) is None and
          find_button(app3, "CanadianShopper only: preview the stock change",
                      exact=False) is None and
          find_button(app3, "Apply the previewed change", exact=False) is None)
    def _all_texts(widgets):
        out = []
        for w in widgets:
            try:
                out.append(str(w.cget("text")))
            except Exception:
                pass
        return out
    check("the sold panel explains the manual CanadianShopper task",
          any("manual checklist tasks" in t for t in _all_texts(sold_widgets)))
    tf3.show_panel("cookie")
    app3.update()
    check("core mode: no cookie test button",
          find_button(app3, "Test the connection") is None)
    app3.show_mode("wizard")
    app3.update()
    w3 = app3._mode_frame.inner.winfo_children()[0]
    w3.page = 2
    w3.render()
    app3.update()
    wtext = " ".join(_all_texts(walk(app3._mode_frame.inner)))
    check("the wizard explains the manual CanadianShopper import",
          "CanadianShopper remains a manual import" in wtext, wtext[:240])

    print("== 19. the shipped pipeline is real and found ==")
    cap = Capture()                  # a capture for the new button below
    app.runner.start = cap
    check("hint: the publish gate",
          "PUBLISHED" in gui._prompt_hint_for(
              "Have you finished the WP All Import and media upload?"))
    check("hint: categories",
          gui._prompt_hint_for("pick a category [1/2/3]: ") is not None)
    check("hint: enter for the excel files",
          gui._prompt_hint_for(
              "Press Enter to generate Excel/log files") is not None)
    check("no hint for random text",
          gui._prompt_hint_for("hello world") is None)
    panel("pipeline")
    pipeline_docs = " ".join(
        w.get("1.0", "end") for w in walk(app._mode_frame.inner)
        if isinstance(w, gui.tk.Text))
    check("pipeline help explains scans, AI copy-back, and manual publishing",
          "Choose the FRONT scan" in pipeline_docs and
          "AI chat" in pipeline_docs and
          "Nothing is uploaded or published" in pipeline_docs and
          "card_pipeline.py" not in pipeline_docs, pipeline_docs[:220])
    find_button(app, "Run the Facebook feed updater",
                exact=False).invoke()
    check("the feed-updater button runs the shipped companion",
          cap.last is not None and
          cap.last["script"].endswith(
              "facebook_merchant_products" + os.sep + "facebook_feed.py") and
          cap.last["cwd"].endswith("facebook_merchant_products"),
          str(cap.last))
    check("the pipeline folder ships",
          (gui.BASE / "pipeline" / "README.txt").is_file())
    check("card_pipeline.py ships",
          (gui.BASE / "pipeline" / "card_pipeline.py").is_file())
    check("the pipeline .bat companion ships",
          (gui.BASE / "pipeline" / "card_pipeline.bat").is_file())
    fake_home = TMP / "gui-empty-batch"
    fake_home.mkdir(exist_ok=True)
    got = gui.find_pipeline_script({"pipeline_dir": str(fake_home)})
    check("finder falls back to the shipped pipeline folder",
          got == gui.BASE / "pipeline" / "card_pipeline.py", str(got))
    r = subprocess.run([sys.executable, str(got), "--help"],
                       capture_output=True, text=True)
    check("the shipped pipeline runs (--help)",
          r.returncode == 0 and "split" in (r.stdout + r.stderr))
    r = subprocess.run([sys.executable, str(got), "listing", "--help"],
                       capture_output=True, text=True)
    check("listing --help matches the GUI's invocation",
          r.returncode == 0 and "--input" in (r.stdout + r.stderr) and
          "--facebook" in (r.stdout + r.stderr))
    # the facebook feed companion ships and compiles (never executed here:
    # it is a flat script that fetches the live feed and prompts)
    feed = gui.BASE / "pipeline" / "facebook_merchant_products" / \
        "facebook_feed.py"
    check("the facebook feed companion ships", feed.is_file())
    import py_compile as _pc
    try:
        _pc.compile(str(feed), doraise=True)
        ok = True
    except Exception:
        ok = False
    check("the feed companion compiles", ok)
    feed_src = feed.read_text(encoding="utf-8")
    check("the feed forces UTF-8 for Unicode console output",
          "reconfigure(encoding=\"utf-8\", errors=\"replace\")"
          in feed_src)
    # Reproduce the Windows redirected-stream default and prove the same
    # reconfigure step can print the emoji that crashed on the test PC.
    enc_env = os.environ.copy()
    enc_env["PYTHONIOENCODING"] = "cp1252"
    enc_probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.stdout.reconfigure(encoding='utf-8', "
         "errors='replace'); print('🆕 New products: 1')"],
        capture_output=True, env=enc_env)
    check("UTF-8 console survives a cp1252 redirected stream",
          enc_probe.returncode == 0 and b"New products: 1" in enc_probe.stdout
          and b"UnicodeEncodeError" not in enc_probe.stderr)

    check("the feed ships with no one-off diagnostic IDs",
          "10290" not in feed_src and 'CHECK_IDS = []' in feed_src)
    check("hint: first-run batch bootstrap",
          gui._prompt_hint_for(
              "No facebook_history.xlsx found") is not None)
    check("hint: a failed batch match is safe",
          gui._prompt_hint_for(
              "!! Safe first-run bootstrap stopped: title missing") is
          not None)
    check("one typed sale title strips quantity/channel markers",
          gui.typed_sale_title("Arnie Brown #144, 2 @facebook\n") ==
          "Arnie Brown #144")
    check("Woo follow-up opens the orders list",
          gui.WOO_ORDERS_ADMIN in
          gui.sale_followup_urls("Arnie Brown #144", "facebook") and
          not any("post_type=product" in url
                  for url in gui.sale_followup_urls("Arnie Brown #144", "facebook")))
    followups = gui.sale_followup_urls("Arnie Brown #144", "website")
    check("sold-on channel is excluded from browser follow-ups",
          len(followups) == 2 and gui.WOO_ORDERS_ADMIN not in followups and
          gui.EBAY_ACTIVE in followups and gui.FB_SELLING in followups)
    cs_followups = gui.sale_followup_urls("Arnie Brown #144", "canadianshopper")
    check("CanadianShopper sale opens follow-ups for the other sources",
          len(cs_followups) == 3 and gui.WOO_ORDERS_ADMIN in cs_followups and
          gui.EBAY_ACTIVE in cs_followups and gui.FB_SELLING in cs_followups)
    edge_calls = []
    old_popen = gui.subprocess.Popen
    try:
        gui.subprocess.Popen = lambda command: edge_calls.append(command)
        picked = gui.open_edge_urls(["https://store.example/", "https://ebay.example/"],
                                    edge_path=str(TMP / "msedge.exe"))
    finally:
        gui.subprocess.Popen = old_popen
    check("Edge opens all follow-up pages in one new window",
          picked == "Microsoft Edge" and edge_calls == [[
              str(TMP / "msedge.exe"), "--new-window", "https://store.example/",
              "https://ebay.example/"]])
    # Tool confirmations/match pickers use a private stream protocol so a
    # nested CanadianShopper tool can request a real Tk dialog before writes.
    runner = gui.Runner(app)
    requests, answers_sent = [], []
    old_handler = app.handle_tool_dialog
    old_send = runner.send
    app.handle_tool_dialog = lambda data: (requests.append(data) or
                                           {"answer": "yes"})
    runner.send = answers_sent.append
    marker = gui._TOOL_DIALOG_START
    body = json.dumps({"type": "confirm_cs", "rows": []})
    first = runner._consume_dialog_protocol("before\n" + marker[:9])
    second = runner._consume_dialog_protocol(
        marker[9:] + body + gui._TOOL_DIALOG_END + "\nafter")
    app.handle_tool_dialog = old_handler
    runner.send = old_send
    check("Tk dialog protocol survives split output chunks",
          first + second == "before\n\nafter" and
          requests == [{"type": "confirm_cs", "rows": []}] and
          json.loads(answers_sent[0]) == {"answer": "yes"})
    confirm_prompts = []
    old_askyesno = gui.messagebox.askyesno
    gui.messagebox.askyesno = lambda title, prompt, parent=None: (
        confirm_prompts.append((title, prompt)) or True)
    try:
        approved = app.handle_tool_dialog({"type": "confirm_cs", "rows": [
            {"action": "stock", "title": "Test card", "inventory_before": 3,
             "inventory_after": 2, "sold_qty": 1,
             "status_before": "active", "status_after": "active"}],
            "unmatched": ["Close card title"]})
    finally:
        gui.messagebox.askyesno = old_askyesno
    check("CS confirmation names the listing and exact stock movement",
          approved == {"answer": "yes"} and confirm_prompts and
          "Test card" in confirm_prompts[0][1] and
          "3 -> 2" in confirm_prompts[0][1] and
          "Close card title" in confirm_prompts[0][1])
    check("hint: feed-script failure output is above",
          gui._prompt_hint_for(
              "  !! Facebook feed script exited with code 1.") is not None)

    # == 19b. the CS photo stage is found where the app puts it ============
    print("== 19b. CS photo stage discovery (installed / legacy / none) ==")
    check("hint: the photo-stage skip",
          gui._prompt_hint_for(
              "  ! CanadianShopper photo stage not installed.") is not None)
    shipped_pipe = gui.BASE / "pipeline" / "card_pipeline.py"
    stub_hook = (
        "def run_stage(output_paths, args=None, script_dir=None, "
        "output_dir=None, tools_dir=None, cookie_file=None):\n"
        "    print('STAGE-RAN tools=%s' % tools_dir)\n"
        "    print('STAGE-COOKIE=%s' % cookie_file)\n"
        "    print('STAGE-N=%d' % len(list(output_paths)))\n")
    inp_txt = "SEO Image titles:\n" + "x" * 220

    def sandbox(name, install_root=None, legacy=False, plugin=False,
                plugin_enabled=True):
        d = TMP / name
        shutil.rmtree(d, ignore_errors=True)
        (d / "pipeline" / "canadianshopper" / "tools").mkdir(parents=True)
        shutil.copyfile(shipped_pipe, d / "pipeline" / "card_pipeline.py")
        shutil.copyfile(HERE / "plugin_manager.py", d / "plugin_manager.py")
        isolated_env = os.environ.copy()
        if os.name == "nt":
            isolated_env["LOCALAPPDATA"] = str(d / "local-app-data")
            isolated_env["APPDATA"] = str(d / "app-data")
        else:
            isolated_env["HOME"] = str(d / "home")
        if install_root:
            (d / "cs_stage_hook.py").write_text(stub_hook)
            (d / "addon-canadianshopper.txt").write_text("canadianshopper\\n")
        if legacy:
            (d / "pipeline" / "canadianshopper" / "tools" /
             "cs_stage_hook.py").write_text(stub_hook)
        if plugin:
            if os.name == "nt":
                data_root = Path(isolated_env["LOCALAPPDATA"]) / "AlexCollect"
            else:
                data_root = Path(isolated_env["HOME"]) / ".local" / "share" / "AlexCollect"
            plugin_dir = data_root / "plugins" / "test-stage-plugin"
            (plugin_dir / "tools").mkdir(parents=True)
            (plugin_dir / "tools" / "cs_stage_hook.py").write_text(stub_hook)
            (plugin_dir / "plugin.json").write_text(json.dumps({
                "id": "test-stage-plugin", "name": "Test stage plugin",
                "version": "1.0.0", "host_api": 1,
                "capabilities": ["batch.pipeline_stage"],
                "actions": {"batch.pipeline_stage": "pipeline_stage"},
                "tools": {"pipeline_stage": "tools/cs_stage_hook.py"}}))
            (plugin_dir.parent / "enabled.json").write_text(
                json.dumps({"test-stage-plugin": plugin_enabled}))
        # a real split first: listing needs the split's tile sets, the
        # same way the GUI always runs split before listing
        from PIL import Image as _I
        # digit-bearing stems: listing auto-detects the two sets by the
        # numbers in the names (older = front), like real scanner files
        front = d / "scan-1000000001.png"
        back = d / "scan-1000000002.png"
        _I.new("RGB", (900, 900), "white").save(front)
        _I.new("RGB", (900, 900), "black").save(back)
        subprocess.run(
            [sys.executable, str(d / "pipeline" / "card_pipeline.py"),
             "split", "--front", str(front), "--back", str(back)],
            capture_output=True, text=True, timeout=300, input="",
            env=isolated_env)
        inp = d / "_card_input.txt"
        inp.write_text(inp_txt, encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(d / "pipeline" / "card_pipeline.py"),
             "listing", "--input", str(inp), "--canadianshopper"],
            capture_output=True, text=True, timeout=300,
            input="Y\nY\n", env=isolated_env)

    r = sandbox("gui-v211-installed", install_root=True)
    check("an INSTALLED hook runs with the app-root tools",
          r.returncode == 0 and "STAGE-RAN" in r.stdout and
          ("STAGE-RAN tools=" + str(TMP / "gui-v211-installed"))
          in r.stdout, r.stdout[-200:] + r.stderr[-200:])
    r = sandbox("gui-v211-legacy", legacy=True)
    check("the legacy sibling layout still works",
          r.returncode == 0 and "STAGE-RAN tools=" +
          str(TMP / "gui-v211-legacy" / "pipeline" / "canadianshopper" / "tools")
          in r.stdout, r.stdout[-200:] + r.stderr[-200:])
    r = sandbox("gui-v211-none")
    check("no hook = a clear explanation, still exit 0",
          r.returncode == 0 and
          "photo stage not installed" in r.stdout and
          "Plugins tab" in r.stdout,
          r.stdout[-260:] + r.stderr[-200:])
    r = sandbox("gui-v221-plugin", plugin=True)
    plugin_base = TMP / "gui-v221-plugin"
    if os.name == "nt":
        plugin_tools = (plugin_base / "local-app-data" / "AlexCollect" /
                        "plugins" / "test-stage-plugin" / "tools")
    else:
        plugin_tools = (plugin_base / "home" / ".local" / "share" /
                        "AlexCollect" / "plugins" / "test-stage-plugin" /
                        "tools")
    check("the per-user plugin hook is discovered",
          r.returncode == 0 and "STAGE-RAN tools=" + str(plugin_tools)
          in r.stdout, r.stdout[-260:] + r.stderr[-200:])
    check("the core cookie path is passed to the plugin hook",
          "STAGE-COOKIE=" + str(plugin_base / "cookie.txt") in r.stdout,
          r.stdout[-260:])
    r = sandbox("gui-v221-plugin-disabled", install_root=True,
                plugin=True, plugin_enabled=False)
    check("disabled managed plugin does not fall through to stale legacy tools",
          r.returncode == 0 and "STAGE-RAN" not in r.stdout and
          "photo stage not installed" in r.stdout,
          r.stdout[-260:] + r.stderr[-200:])
    for junk in ("gui-v211-installed", "gui-v211-legacy", "gui-v211-none",
                 "gui-v221-plugin", "gui-v221-plugin-disabled"): 
        shutil.rmtree(TMP / junk, ignore_errors=True)

    # The Plugins panel manages optional plugin packages from local ZIPs.
    print("== 19c. local plugin manager ==")
    panel("plugins")
    check("CanadianShopper test fixture is discovered",
          gui.PLUGIN_MANAGER.is_enabled("canadianshopper"))
    disable = find_button(app, "Disable")
    check("enabled plugin has a Disable control", disable is not None)
    if disable:
        disable.invoke()
        app.update()
    check("Disable control updates plugin state",
          not gui.PLUGIN_MANAGER.is_enabled("canadianshopper"))
    enable = find_button(app, "Enable")
    if enable:
        enable.invoke()
        app.update()
    check("Enable control restores plugin state",
          gui.PLUGIN_MANAGER.is_enabled("canadianshopper"))

    ui_package = plugin_test_root.parent / (plugin_test_root.name + "-ui-src")
    shutil.rmtree(ui_package, ignore_errors=True)
    ui_package.mkdir(parents=True)
    (ui_package / "plugin.json").write_text(json.dumps({
        "id": "ui-test-plugin", "name": "UI test plugin",
        "version": "1.0.0", "host_api": 1,
        "description": "GUI install test.", "capabilities": [], "tools": {}
    }), encoding="utf-8")
    ui_zip = plugin_test_root.parent / (plugin_test_root.name + "-ui.zip")
    shutil.make_archive(str(ui_zip.with_suffix("")), "zip",
                        root_dir=ui_package)
    old_open = gui.filedialog.askopenfilename
    gui.filedialog.askopenfilename = lambda **k: str(ui_zip)
    try:
        panel("plugins")
        install_button = find_button(app, "Install from ZIP...")
        check("Plugins panel offers local ZIP installation",
              install_button is not None)
        if install_button:
            install_button.invoke()
            app.update()
        check("selected plugin ZIP is installed by the panel",
              gui.PLUGIN_MANAGER.get_plugin("ui-test-plugin")["name"] ==
              "UI test plugin")
    finally:
        gui.filedialog.askopenfilename = old_open
    gui.PLUGIN_MANAGER.remove("ui-test-plugin")

    # == 19d. the typed sale editor makes Save obvious ===================
    print("== 19d. typed sale Save and Ctrl+Enter ==")
    edit_path = TMP / "gui-sold-title-editor-test.txt"
    try:
        edit_path.unlink()
    except FileNotFoundError:
        pass
    edit_saved = []
    editor = gui.Editor(
        self_toplevel=app, title="Cards that sold",
        hint="One card per line", initial="Arnie Brown #144",
        save_to=edit_path, save_label="Save title",
        save_hint="Enter adds another card line. Ctrl+Enter saves this title.",
        on_saved=lambda p: edit_saved.append(str(p)))
    app.update()
    save_button = find_button(editor, "Save title")
    txt = next((w for w in editor.winfo_children()
                if isinstance(w, gui.tk.Text)), None)
    check("typed editor has an obvious Save title button",
          save_button is not None)
    check("Save title is above the editor so it stays visible",
          save_button is not None and txt is not None and
          editor.winfo_children().index(save_button.master) <
          editor.winfo_children().index(txt))
    check("Ctrl+Enter is bound in the typing box",
          txt is not None and bool(txt.bind("<Control-Return>")))
    if save_button:
        save_button.invoke()
        app.update()
    check("Save title writes the file and returns to the Sold panel",
          edit_path.is_file() and
          edit_path.read_text(encoding="utf-8").strip() == "Arnie Brown #144"
          and edit_saved == [str(edit_path)] and not editor.winfo_exists(),
          str(edit_saved))
    if edit_path.exists():
        edit_path.unlink()

    # == 20. the drop flow: split-only + remembered scans ==================
    print("== 20. drop flow: split-only + remembered scans ==")
    saved_settings = dict(app.settings)
    cap2 = Capture()
    app.runner.start = cap2
    drop_dir = TMP / "gui-drop-test"
    drop_dir.mkdir(exist_ok=True)
    dfront = drop_dir / "front-sheet.png"
    dback = drop_dir / "back-sheet.png"
    if not dfront.is_file():
        from PIL import Image as _Img
        _Img.new("RGB", (60, 60), "white").save(dfront)
        _Img.new("RGB", (60, 60), "black").save(dback)
    dlg = app.open_pipeline_with_scans([str(dfront), str(dback)])
    check("the drop pre-fills FRONT and BACK",
          dlg.front_var.get() == str(dfront) and
          dlg.back_var.get() == str(dback))
    big = find_button(dlg, "Split the scans", exact=False)
    check("the plain split match is still the FULL button",
          big is not None and
          big.cget("text") == "Split the scans and build the CSV",
          big.cget("text") if big else "none")
    only = find_button(dlg, "Split the scans only")
    check("the split-only button exists", only is not None)
    app.clipboard_clear()
    app.update()
    only.invoke()
    app.update()
    a = cap2.last
    check("split-only runs with NO AI answer",
          a is not None and
          a["args"] == ["split", "--front", str(dfront),
                        "--back", str(dback)] and
          a["title"] == "Card pipeline: split", str(a and a["args"]))
    check("split-only keeps the dialog open for the AI steps",
          bool(dlg.winfo_exists()))
    check("the scans + folder were remembered",
          app.settings.get("scan_dir") == str(drop_dir) and
          app.settings.get("last_front_scan") == str(dfront) and
          app.settings.get("last_back_scan") == str(dback),
          str(app.settings.get("scan_dir")))
    check("the memory reached gui-settings.json",
          "last_front_scan" in
          gui.SETTINGS_FILE.read_text(encoding="utf-8"))
    only.invoke()
    app.update()
    check("split-only twice = two starts, dialog still open",
          len(cap2.calls) == 2 and bool(dlg.winfo_exists()),
          str(len(cap2.calls)))
    # a failed start (runner busy) must NOT close the dialog silently
    app.runner.start = lambda *a, **k: False
    long_answer = "SEO Image titles:\n" + "x" * 220
    app.clipboard_clear()
    app.clipboard_append(long_answer)
    app.update()
    big.invoke()
    app.update()
    check("a failed start keeps the dialog open (no silent close)",
          bool(dlg.winfo_exists()))
    app.runner.start = cap2
    dlg.destroy()
    dlg2 = gui.PipelineDialog(app,
                              gui.BASE / "pipeline" / "card_pipeline.py",
                              lambda *a, **k: True)
    check("a manual run re-fills the remembered scans",
          dlg2.front_var.get() == str(dfront) and
          dlg2.back_var.get() == str(dback))
    dlg2.destroy()
    shutil.rmtree(drop_dir, ignore_errors=True)
    app.settings.clear()
    app.settings.update(saved_settings)
    gui.save_settings(app.settings)
    app.update()

    # Restore test-owned state only. Never delete an existing tool, credential,
    # setting, log, or plugin from the user's app folder.
    for path, original in preserved.items():
        if original is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)
    shutil.rmtree(plugin_test_root, ignore_errors=True)
    shutil.rmtree(cs_package, ignore_errors=True)
    shutil.rmtree(ui_package, ignore_errors=True)
    for archive in (cs_zip, ui_zip):
        try:
            archive.unlink()
        except FileNotFoundError:
            pass
    app.destroy()
    if XVFB:
        XVFB.terminate()

    print("=" * 62)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        sys.exit(1)
    print("ALL CHECKS PASSED (%d)" % PASS)


if __name__ == "__main__":
    main()
