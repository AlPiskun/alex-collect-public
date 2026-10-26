#!/usr/bin/env python3
"""Headless regression checks for portable user configuration and Woo URLs."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import os
import sys

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "pipeline"))

from user_settings import (feed_urls, has_woo_credentials,
                           has_wordpress_credentials, load_user_settings,
                           marketplace_seller_urls, product_edit_url,
                           product_search_url, read_woo_credentials,
                           read_wordpress_credentials,
                           restrict_file_permissions, site_admin_url,
                           sync_site_url_to_woo_keys)
import card_pipeline as pipeline
import browser_utils


def main():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings_path = root / "gui-settings.json"
        keys_path = root / "woo-keys.txt"
        keys_path.write_text(
            "https://legacy.example\nck_example\ncs_secret\n",
            encoding="utf-8")
        settings = load_user_settings(settings_path)
        assert settings["browser_name"] == ""
        assert settings["custom_ai_commands"] == []
        assert settings["facebook_feed_condition"] == "Used - Good"
        assert "{product_url}" in settings["facebook_feed_description_template"]
        assert settings["ebay_quicklist_enabled"] is True
        assert "templateId=6683629012" in settings["ebay_template_hockey_url"]
        assert settings["ebay_default_condition"] == "Mint"
        assert settings["woo_site_url"] == "https://legacy.example"
        assert site_admin_url("wp-admin/media-new.php", settings) == (
            "https://legacy.example/wp-admin/media-new.php")
        assert feed_urls(settings) == (
            "https://legacy.example/?force_facebook_feed=1",
            "https://legacy.example/feed/facebook.xml")

        settings_path.write_text(
            '{"woo_site_url":"https://new.example",'
            '"woo_feed_url":"https://cdn.example/products.xml",'
            '"woo_feed_refresh_url":"https://new.example/rebuild",'
            '"custom_ai_commands":[{"id":"test","name":"Test button",'
            '"tooltip":"hover","prompt":"Write a test prompt."}]}',
            encoding="utf-8")
        settings = load_user_settings(settings_path)
        assert settings["custom_ai_commands"] == [{
            "id": "test", "name": "Test button", "tooltip": "hover",
            "prompt": "Write a test prompt."}]
        assert feed_urls(settings) == (
            "https://new.example/rebuild", "https://cdn.example/products.xml")
        assert sync_site_url_to_woo_keys(
            "https://new.example", keys_path)
        assert keys_path.read_text(encoding="utf-8").splitlines() == [
            "https://new.example", "ck_example", "cs_secret"]

    events = []
    folder_events = []
    custom_settings = {"woo_site_url": "https://shop.example",
                       "browser_name": "chrome"}
    args = SimpleNamespace(facebook=True, no_browser=False)
    old_settings = pipeline.USER_SETTINGS
    try:
        pipeline.USER_SETTINGS = custom_settings
        with patch.object(pipeline, "launch_urls",
                          side_effect=lambda urls, browser, **k: (
                              events.append(("open", urls[0], browser)) or
                              "Test browser")), \
             patch.object(pipeline, "open_folder",
                          side_effect=lambda path: (
                              folder_events.append(Path(path)) or True)), \
             patch("builtins.input", side_effect=lambda prompt: (
                 events.append(("prompt", prompt)) or "n")):
            with redirect_stdout(StringIO()):
                pipeline.maybe_run_facebook(args)
    finally:
        pipeline.USER_SETTINGS = old_settings
    assert events[0] == (
        "open", "https://shop.example/wp-admin/media-new.php", "chrome")
    assert events[1][0] == "prompt"
    assert "created/published the products" in events[1][1]
    assert folder_events == [pipeline.OUTPUT_DIR]
    launched = []
    with patch.object(browser_utils, "browser_executable",
                      return_value="/fake/chrome"), \
         patch.object(browser_utils.subprocess, "Popen",
                      side_effect=lambda command: launched.append(command)):
        label = browser_utils.open_urls(
            ["https://example.test"], "edge", new_window=True)
    assert label == "Microsoft Edge"
    assert launched == [["/fake/chrome", "--new-window",
                         "https://example.test"]]
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        hook = root / "plugin" / "tools" / "cs_stage_hook.py"
        ready = hook.parent / "cs-ready"
        ready.mkdir(parents=True)
        staged = ready / "canadianshopper_import_batch_01_of_01.csv"
        staged.write_text("header\n", encoding="utf-8")
        original = root / "pipeline" / staged.name
        original.parent.mkdir()
        original.write_text("header\n", encoding="utf-8")
        assert pipeline.canadianshopper_import_folder(
            [original], hook) == ready
        # Without an installed stage hook, always open this run's CSV folder,
        # never a stale cs-ready folder left from an earlier run.
        assert pipeline.canadianshopper_import_folder([original]) == original.parent
    # Replacing one card's photos: the lookup uses the private key file, and
    # every marketplace page comes from the saved settings.
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        keys = root / "woo-keys.txt"
        keys.write_text("https://shop.example\nck_abc\ncs_secret\n",
                        encoding="utf-8")
        assert read_woo_credentials(keys) == ("https://shop.example",
                                             "ck_abc", "cs_secret")
        assert has_woo_credentials(keys)
        # The shipped example must never look like a working key pair.
        keys.write_text("https://your-store.example\n"
                        "ck_replace_with_read_only_consumer_key\n"
                        "cs_replace_with_read_only_consumer_secret\n",
                        encoding="utf-8")
        assert read_woo_credentials(keys) == ("https://your-store.example", "", "")
        assert not has_woo_credentials(keys)
        absent = root / "no-keys-here.txt"
        assert read_woo_credentials(absent) == ("", "", "")
        assert not has_woo_credentials(absent)

    shop = {"woo_site_url": "https://shop.example",
            "canadianshopper_store_url": "https://canadianshopper.ca/store/mine",
            "ebay_selling_url": "https://www.ebay.ca/sh/lst/active",
            "facebook_selling_url":
                "https://www.facebook.com/marketplace/you/selling"}
    assert product_edit_url(42, shop) == \
        "https://shop.example/wp-admin/post.php?post=42&action=edit"
    assert product_edit_url("", shop) == ""
    assert product_search_url("1989 Gretzky", shop) == \
        ("https://shop.example/wp-admin/edit.php?post_type=product"
         "&s=1989+Gretzky")
    assert product_search_url("   ", shop) == ""
    assert marketplace_seller_urls(shop) == [
        "https://canadianshopper.ca/store/mine",
        "https://www.ebay.ca/sh/lst/active",
        "https://www.facebook.com/marketplace/you/selling"]
    # No site URL means no admin URLs at all - never a bare "/wp-admin".
    assert product_edit_url(42, {}) == ""
    assert product_search_url("card", {}) == ""

    # Credentials are a private file, not just a git-ignored one.
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        keys = root / "woo-keys.txt"
        keys.write_text("https://shop.example\nck_abc\ncs_secret\n",
                        encoding="utf-8")
        os.chmod(keys, 0o644)
        assert restrict_file_permissions(keys)
        assert (keys.stat().st_mode & 0o777) == 0o600
        # A missing file is reported, not created.
        assert not restrict_file_permissions(root / "absent.txt")
        # Windows asks icacls to drop inheritance and grant only this user.
        calls = []
        with patch("user_settings.IS_WINDOWS", True), \
                patch("user_settings.os.environ", {"USERNAME": "Owner"}), \
                patch("user_settings.subprocess.run",
                      lambda argv, **kw: (calls.append((argv, kw)) or
                                          SimpleNamespace(returncode=0))):
            assert restrict_file_permissions(keys)
        argv, kw = calls[0]
        assert argv[:2] == ["icacls", str(keys)]
        assert "/inheritance:r" in argv and "Owner:F" in argv
        assert kw.get("capture_output") is True
        # No username means no rule to grant - refuse rather than open it up.
        calls.clear()
        with patch("user_settings.IS_WINDOWS", True), \
                patch("user_settings.os.environ", {}):
            assert not restrict_file_permissions(keys)
        assert not calls

        # -- the optional upload lines, 4 and 5 ----------------------------
        upload_keys = root / "upload-keys.txt"
        upload_keys.write_text(
            "https://shop.example\nck_live\ncs_live\nowner\n"
            "abcd EFGH ijkl MNOP\n", encoding="utf-8")
        assert read_woo_credentials(upload_keys) == (
            "https://shop.example", "ck_live", "cs_live")
        assert read_wordpress_credentials(upload_keys) == (
            "https://shop.example", "owner", "abcd EFGH ijkl MNOP")
        assert has_wordpress_credentials(upload_keys)

        # A WordPress Application Password is handed out in groups; the inner
        # spaces are part of what the user pasted and must survive reading.
        assert " " in read_wordpress_credentials(upload_keys)[2]

        # Only three lines: the WooCommerce keys still work, upload does not.
        three_line = root / "three-line.txt"
        three_line.write_text("https://shop.example\nck_live\ncs_live\n",
                              encoding="utf-8")
        assert read_woo_credentials(three_line)[1:] == ("ck_live", "cs_live")
        assert read_wordpress_credentials(three_line) == (
            "https://shop.example", "", "")
        assert not has_wordpress_credentials(three_line)

        # A username with no password is not half a login.
        half = root / "half.txt"
        half.write_text("https://shop.example\nck_live\ncs_live\nowner\n",
                        encoding="utf-8")
        assert not has_wordpress_credentials(half)

        # The shipped template must never read as working credentials.
        template = APP / "woo-keys.txt.example"
        assert template.is_file()
        assert not has_wordpress_credentials(template)
        assert not has_woo_credentials(template)
        assert read_wordpress_credentials(template)[1:] == ("", "")

        # Comments and blank lines are still ignored around the extra lines.
        noisy = root / "noisy.txt"
        noisy.write_text(
            "# my shop\n\nhttps://shop.example\n# keys\nck_live\ncs_live\n"
            "owner\n# password\nabcd EFGH ijkl MNOP\n", encoding="utf-8")
        assert read_wordpress_credentials(noisy) == (
            "https://shop.example", "owner", "abcd EFGH ijkl MNOP")

        # Rewriting the site URL must not disturb the two upload lines.
        sync_site_url_to_woo_keys("https://new.example", upload_keys)
        assert read_wordpress_credentials(upload_keys) == (
            "https://new.example", "owner", "abcd EFGH ijkl MNOP")
        assert read_woo_credentials(upload_keys)[1:] == ("ck_live", "cs_live")

        # Missing file is not an error, just nothing to upload with.
        assert read_wordpress_credentials(root / "absent.txt") == ("", "", "")

    print("PASS legacy Woo URL migration, media/admin URLs, and feed overrides")
    print("PASS pipeline opens the configured media upload page before asking")
    print("PASS CanadianShopper folder selection prefers staged output, then current CSV")
    print("PASS photo replacement reads the private keys and the saved seller pages")
    print("PASS the credentials file is readable only by this account")
    print("PASS optional WordPress upload lines are read, and never faked")


if __name__ == "__main__":
    main()
