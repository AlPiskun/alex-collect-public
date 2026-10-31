#!/usr/bin/env python3
"""Headless checks for the Facebook workbook handoff stage."""
import builtins
import importlib.util
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("card_pipeline", APP / "pipeline" / "card_pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def main():
    old_script_dir = pipeline.SCRIPT_DIR
    old_settings = pipeline.USER_SETTINGS
    old_open_path = pipeline.open_path
    old_open_folder = pipeline.open_folder
    old_open_browser = pipeline.open_in_browser
    calls = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export_dir = root / "facebook_merchant_products"
            export_dir.mkdir()
            older = export_dir / "facebook_delta_20261020.xlsx"
            latest = export_dir / "facebook_delta_20261021.xlsx"
            history = export_dir / "facebook_history.xlsx"
            for index, path in enumerate((older, latest, history), start=1):
                path.write_bytes(b"test")
                os.utime(path, (index, index))
            pipeline.SCRIPT_DIR = root
            #  Both pages are set on purpose: the handoff must open the
            #  bulk-create page the CSVs are uploaded through, never the
            #  selling list the stock comparison reads.
            pipeline.USER_SETTINGS = {
                "facebook_selling_url": "https://www.facebook.com/marketplace/you/selling",
                "facebook_bulk_create_url":
                    "https://www.facebook.com/marketplace/create/bulk",
            }
            pipeline.open_path = lambda path: calls.append(("file", Path(path))) or True
            pipeline.open_folder = lambda path: calls.append(("folder", Path(path))) or True
            pipeline.open_in_browser = lambda url: calls.append(("browser", url)) or "Test browser"
            with patch.object(builtins, "input", return_value=""):
                pipeline.open_facebook_delivery()
            assert ("file", latest) in calls
            assert ("folder", export_dir) in calls
            assert ("browser", "https://www.facebook.com/marketplace/create/bulk") in calls
            assert ("browser", "https://www.facebook.com/marketplace/you/selling") not in calls
            print("PASS Facebook handoff opens latest workbook, export folder, the bulk-create page, and waits for review")
            #  A settings file saved before this page was its own setting has
            #  no key for it. The handoff must still open the bulk-create page
            #  rather than falling back to the selling list.
            calls.clear()
            pipeline.USER_SETTINGS = {
                "facebook_selling_url": "https://www.facebook.com/marketplace/you/selling"
            }
            with patch.object(builtins, "input", return_value=""):
                pipeline.open_facebook_delivery()
            assert ("browser", pipeline.FACEBOOK_BULK_CREATE_URL) in calls, calls
            assert ("browser", "https://www.facebook.com/marketplace/you/selling") not in calls
            print("PASS an older settings file still opens the bulk-create page")
    finally:
        pipeline.SCRIPT_DIR = old_script_dir
        pipeline.USER_SETTINGS = old_settings
        pipeline.open_path = old_open_path
        pipeline.open_folder = old_open_folder
        pipeline.open_in_browser = old_open_browser


if __name__ == "__main__":
    main()
