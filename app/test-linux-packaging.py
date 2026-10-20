#!/usr/bin/env python3
# ===========================================================================
#  test-linux-packaging.py - the Linux skin: launchers, XDG install, and
#  public plugin-host boundary. Skips itself gracefully on Windows.
#
#  Run:  python3 test-linux-packaging.py
# ===========================================================================
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent          # the repo root
PASS = 0
FAIL = 0
XVFB = None


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s %s" % (name, extra))


def ensure_display():
    """Find a display that actually works: start Xvfb, then PROVE it with
    a trivial Tk call before trusting it (busy/lockless leftovers from
    other runs are common in sandboxes)."""
    global XVFB
    if sys.platform == "win32" or os.environ.get("DISPLAY"):
        try:
            import tkinter as tk
            r = tk.Tk(); r.destroy()
            return
        except Exception:
            os.environ.pop("DISPLAY", None)   # stale DISPLAY - search on
    for d in (":%d" % n for n in range(90, 98)):
        try:
            XVFB = subprocess.Popen(
                ["Xvfb", d, "-screen", "0", "1024x700x24"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            print("  (no Xvfb and no DISPLAY - the boot check may fail)")
            return
        time.sleep(1.2)
        if XVFB.poll() is not None:
            XVFB = None
            continue
        os.environ["DISPLAY"] = d
        try:
            import tkinter as tk
            r = tk.Tk(); r.destroy()
            return                            # proven usable
        except Exception:
            XVFB.terminate()
            XVFB = None
            os.environ.pop("DISPLAY", None)


def sh(script, *args, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(["sh", str(script), *args], capture_output=True,
                          text=True, env=e)


def main():
    if sys.platform == "win32":
        print("Windows detected - the Linux packaging tests do not apply.")
        print("(On Windows, verify with: python app\\test-gui.py and the "
              "Inno Setup compile.)")
        return
    ensure_display()

    print("== 1. the launchers exist and are executable ==")
    for f in ("app/alexcollect.sh", "start-alexcollect.sh",
              "install-linux.sh"):
        p = REPO / f
        check("%s present + executable" % f,
              p.is_file() and os.access(p, os.X_OK))

    print("== 2. shell syntax ==")
    for f in ("app/alexcollect.sh", "start-alexcollect.sh",
              "install-linux.sh"):
        r = subprocess.run(["sh", "-n", str(REPO / f)],
                           capture_output=True, text=True)
        check("%s parses" % f, r.returncode == 0, r.stderr[:80])

    print("== 3. public core/plugin boundary ==")
    check("plugin manager ships in the core",
          (REPO / "app" / "plugin_manager.py").is_file())
    check("plugin API documentation ships",
          (REPO / "docs" / "PLUGIN-API.md").is_file())
    check("private CanadianShopper sources are absent",
          not (REPO / "app" / "addons" / "canadianshopper").exists())
    check("core has no CanadianShopper copy installer",
          not (REPO / "INSTALL CanadianShopper add-on.bat").exists())

    print("== 4. the XDG install into a throwaway HOME ==")
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        r = sh(REPO / "install-linux.sh", env={"HOME": str(home)})
        check("install-linux.sh runs", r.returncode == 0,
              (r.stderr or r.stdout)[-160:])
        dest = home / ".local/share/AlexCollect"
        check("app installed", (dest / "app/gui.py").is_file())
        check("plugin docs installed", (dest / "docs/PLUGIN-API.md").is_file())
        check("private add-on not installed with core",
              not (dest / "app/addons/canadianshopper").exists())
        desk = home / ".local/share/applications/alexcollect.desktop"
        check("desktop entry created", desk.is_file())
        if desk.is_file():
            txt = desk.read_text(encoding="utf-8")
            check("desktop entry: Name/Exec/Icon/Terminal",
                  "Name=Alex Collect" in txt and
                  str(dest / "app/alexcollect.sh") in txt and
                  "Icon=alexcollect" in txt and "Terminal=false" in txt)
        check("icon installed",
              (home / ".local/share/icons/hicolor/256x256/apps/"
                     "alexcollect.png").is_file())
        r = sh(REPO / "install-linux.sh", "--remove",
               env={"HOME": str(home)})
        check("--remove keeps the app + data",
              r.returncode == 0 and dest.is_dir() and not desk.exists())
        r = sh(REPO / "install-linux.sh", "--purge",
               env={"HOME": str(home)})
        check("--purge removes everything", r.returncode == 0 and
              not dest.exists())

    print("== 5. the installed launcher really boots the app ==")
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        sh(REPO / "install-linux.sh", env={"HOME": str(home)})
        launcher = home / ".local/share/AlexCollect/app/alexcollect.sh"
        env = dict(os.environ, HOME=str(home))
        proc = subprocess.Popen([str(launcher)], env=env,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        time.sleep(4.0)
        alive = proc.poll() is None
        proc.terminate()
        out = proc.communicate(timeout=10)[0]
        check("the installed app boots and stays up", alive,
              (out or "")[-200:])
        if not alive and "tkinter" in (out or ""):
            print("        (tkinter missing in this environment - the "
                  "error message shown to the user is correct)")

    print("=" * 62)
    if FAIL:
        print("FAILED %d   PASSED %d" % (FAIL, PASS))
        sys.exit(1)
    print("ALL CHECKS PASSED (%d)" % PASS)
    if XVFB:
        XVFB.terminate()


if __name__ == "__main__":
    main()
