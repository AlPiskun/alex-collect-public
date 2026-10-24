"""Find and launch a user's preferred installed browser."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

_BROWSER_CANDIDATES = (
    ("edge", "Microsoft Edge", "msedge.exe", "msedge", (
        ("PROGRAMFILES(X86)", "Microsoft/Edge/Application/msedge.exe"),
        ("PROGRAMFILES", "Microsoft/Edge/Application/msedge.exe"),
        ("LOCALAPPDATA", "Microsoft/Edge/Application/msedge.exe"),
    )),
    ("chrome", "Google Chrome", "chrome.exe", "google-chrome", (
        ("PROGRAMFILES", "Google/Chrome/Application/chrome.exe"),
        ("PROGRAMFILES(X86)", "Google/Chrome/Application/chrome.exe"),
        ("LOCALAPPDATA", "Google/Chrome/Application/chrome.exe"),
    )),
    ("firefox", "Mozilla Firefox", "firefox.exe", "firefox", (
        ("PROGRAMFILES", "Mozilla Firefox/firefox.exe"),
        ("PROGRAMFILES(X86)", "Mozilla Firefox/firefox.exe"),
        ("LOCALAPPDATA", "Mozilla Firefox/firefox.exe"),
    )),
    ("brave", "Brave", "brave.exe", "brave-browser", (
        ("PROGRAMFILES", "BraveSoftware/Brave-Browser/Application/brave.exe"),
        ("PROGRAMFILES(X86)", "BraveSoftware/Brave-Browser/Application/brave.exe"),
        ("LOCALAPPDATA", "BraveSoftware/Brave-Browser/Application/brave.exe"),
    )),
)


def browser_executable(browser_id: str) -> str:
    """Return the executable for a supported installed browser, if found."""
    for key, _label, win_cmd, unix_cmd, candidates in _BROWSER_CANDIDATES:
        if key != browser_id:
            continue
        for command in (win_cmd, unix_cmd):
            found = shutil.which(command)
            if found:
                return found
        for env_key, relative in candidates:
            root = os.environ.get(env_key, "")
            if root:
                path = Path(root) / Path(relative)
                if path.is_file():
                    return str(path)
        if sys.platform == "darwin":
            mac_apps = {
                "edge": "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "chrome": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "firefox": "/Applications/Firefox.app/Contents/MacOS/firefox",
                "brave": "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            }
            path = Path(mac_apps[key])
            if path.is_file():
                return str(path)
        return ""
    return ""


def available_browsers() -> list[tuple[str, str]]:
    """Return (setting value, display name) for available choices."""
    choices = [("system", "System default browser")]
    for key, label, *_rest in _BROWSER_CANDIDATES:
        if browser_executable(key):
            choices.append((key, label))
    return choices


def browser_label(browser_id: str) -> str:
    for key, label in available_browsers():
        if key == (browser_id or "system"):
            return label
    return "System default browser"


def open_urls(urls, browser_id="system", new_window=False) -> str:
    """Open URLs in the requested browser; fall back to the OS default."""
    urls = [str(url).strip() for url in urls if str(url).strip()]
    if not urls:
        return ""
    browser_id = browser_id or "system"
    if browser_id != "system":
        exe = browser_executable(browser_id)
        if exe:
            args = [exe]
            if new_window:
                args.append("--new-window")
            args.extend(urls)
            try:
                subprocess.Popen(args)
                return browser_label(browser_id)
            except (OSError, subprocess.SubprocessError):
                pass
    for url in urls:
        try:
            webbrowser.open_new_tab(url)
        except Exception:
            pass
    return "the system default browser"
