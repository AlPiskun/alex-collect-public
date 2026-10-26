#!/usr/bin/env python3
"""Offline tests for the local Alex Collect plugin manager."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from plugin_manager import (PluginError, PluginManager, default_plugin_root,
                           parse_version, validate_manifest, version_at_least)


MANIFEST = {
    "id": "sample-addon",
    "name": "Sample Add-on",
    "version": "1.2.0",
    "host_api": 1,
    "description": "Test-only plugin.",
    "capabilities": ["after_sale"],
    "actions": {"after_sale": "after_sale"},
    "tools": {"after_sale": "tools/after_sale.py"}, 
}


def make_zip(path, manifest=None, prefix=""):
    manifest = dict(MANIFEST if manifest is None else manifest)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(prefix + "plugin.json",
                    json.dumps(manifest))
        zf.writestr(prefix + "tools/after_sale.py", "# harmless test stub\n")
    return path


class VersionGateTests(unittest.TestCase):
    """Comparing plugin versions is what keeps a stale plugin from being used.

    batch.photo_replace exists in both 1.0.14 and 1.0.15, but only 1.0.15 can
    work without a staged CSV, so the action ID alone is not enough.
    """

    def test_parse_version_tolerates_real_world_strings(self):
        self.assertEqual(parse_version("1.0.15"), (1, 0, 15))
        self.assertEqual(parse_version("1.0.15-beta"), (1, 0, 15))
        self.assertEqual(parse_version(" 2.40 "), (2, 40))
        self.assertEqual(parse_version(""), ())
        self.assertEqual(parse_version(None), ())
        self.assertEqual(parse_version("v1.0"), ())

    def test_version_at_least_orders_numerically(self):
        self.assertTrue(version_at_least("1.0.15", "1.0.15"))
        self.assertTrue(version_at_least("1.0.16", "1.0.15"))
        self.assertTrue(version_at_least("1.1", "1.0.15"))
        self.assertTrue(version_at_least("2.0", "1.0.15"))
        self.assertFalse(version_at_least("1.0.14", "1.0.15"))
        self.assertFalse(version_at_least("1.0.9", "1.0.15"))

    def test_equal_versions_of_different_length_match(self):
        self.assertTrue(version_at_least("1.0", "1.0.0"))
        self.assertTrue(version_at_least("1.0.0", "1.0"))

    def test_unreadable_versions_are_never_new_enough(self):
        self.assertFalse(version_at_least("", "1.0.15"))
        self.assertFalse(version_at_least("1.0.15", ""))
        self.assertFalse(version_at_least(None, "1.0.15"))


class PluginManagerTests(unittest.TestCase):
    def test_user_data_path_uses_windows_localappdata(self):
        root = default_plugin_root({"LOCALAPPDATA": r"C:\Users\A\Local"},
                                   home=Path("/home/a"), platform="nt")
        self.assertEqual(root, Path(r"C:\Users\A\Local") /
                         "AlexCollect" / "plugins")

    def test_validate_manifest_rejects_incompatible_host_api(self):
        bad = dict(MANIFEST, host_api=2)
        with self.assertRaisesRegex(PluginError, "supports 1"):
            validate_manifest(bad)

    def test_validate_manifest_rejects_path_traversal(self):
        bad = dict(MANIFEST, tools={"after_sale": "../outside.py"})
        with self.assertRaisesRegex(PluginError, "Unsafe tool path"):
            validate_manifest(bad)

    def test_validate_manifest_enforces_minimum_core_version(self):
        bad = dict(MANIFEST, min_core_version="2.22")
        with self.assertRaisesRegex(PluginError, "requires Alex Collect 2.22"):
            validate_manifest(bad, core_version="2.21")

    def test_install_list_resolve_toggle_and_remove(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            zippath = make_zip(base / "sample.zip")
            manager = PluginManager(base / "plugins")
            installed = manager.install_zip(zippath)
            self.assertEqual(installed["id"], "sample-addon")
            self.assertTrue(installed["enabled"])
            self.assertEqual(manager.resolve_tool("sample-addon", "after_sale").name,
                             "after_sale.py")
            self.assertEqual(manager.resolve_action("after_sale").name,
                             "after_sale.py")
            manager.set_enabled("sample-addon", False)
            self.assertFalse(manager.is_enabled("sample-addon"))
            with self.assertRaisesRegex(PluginError, "disabled"):
                manager.resolve_tool("sample-addon", "after_sale")
            manager.set_enabled("sample-addon", True)
            self.assertTrue(manager.is_enabled("sample-addon"))
            manager.remove("sample-addon")
            self.assertEqual(manager.list_plugins(), [])

    def test_install_accepts_single_top_level_folder(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            zippath = make_zip(base / "nested.zip", prefix="sample-addon/")
            manager = PluginManager(base / "plugins")
            self.assertEqual(manager.install_zip(zippath)["id"], "sample-addon")

    def test_install_rejects_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            zippath = base / "bad.zip"
            with zipfile.ZipFile(zippath, "w") as zf:
                zf.writestr("../outside.txt", "nope")
            manager = PluginManager(base / "plugins")
            with self.assertRaisesRegex(PluginError, "Unsafe path"):
                manager.install_zip(zippath)
            self.assertFalse((base / "outside.txt").exists())

    def test_install_rejects_missing_declared_tool(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manifest = dict(MANIFEST, tools={"after_sale": "missing.py"})
            zippath = make_zip(base / "bad-tool.zip", manifest)
            manager = PluginManager(base / "plugins")
            with self.assertRaisesRegex(PluginError, "does not exist"):
                manager.install_zip(zippath)
            self.assertEqual(manager.list_plugins(), [])

    def test_reinstall_preserves_disabled_state(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            zippath = make_zip(base / "sample.zip")
            manager = PluginManager(base / "plugins")
            manager.install_zip(zippath)
            manager.set_enabled("sample-addon", False)
            updated = dict(MANIFEST, version="1.3.0")
            make_zip(zippath, updated)
            installed = manager.install_zip(zippath)
            self.assertEqual(installed["version"], "1.3.0")
            self.assertFalse(installed["enabled"])

    def test_manual_package_without_state_is_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "plugins"
            package = root / MANIFEST["id"]
            (package / "tools").mkdir(parents=True)
            (package / "plugin.json").write_text(json.dumps(MANIFEST),
                                                  encoding="utf-8")
            (package / "tools" / "after_sale.py").write_text("# stub\n")
            manager = PluginManager(root)
            self.assertFalse(manager.is_enabled(MANIFEST["id"]))
            with self.assertRaisesRegex(PluginError, "disabled"):
                manager.resolve_action("after_sale")

    def test_ambiguous_action_provider_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manager = PluginManager(base / "plugins")
            one = make_zip(base / "one.zip")
            manager.install_zip(one)
            second_manifest = dict(MANIFEST, id="second-addon",
                                  name="Second add-on")
            two = make_zip(base / "two.zip", second_manifest)
            manager.install_zip(two)
            with self.assertRaisesRegex(PluginError, "More than one"):
                manager.resolve_action("after_sale")


if __name__ == "__main__":
    unittest.main(verbosity=2)
