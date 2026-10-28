"""Local plugin registry for Alex Collect.

Plugins are installed from user-selected ZIP files into the user's data
folder, not into the core application's source/install directory. Discovery
only reads manifests: plugin Python code is not imported automatically.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

PLUGIN_API_VERSION = 1
PLUGIN_DIR_NAME = "plugins"
PLUGIN_MANIFEST = "plugin.json"
_PLUGIN_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
_MAX_ARCHIVE_FILES = 500


class PluginError(ValueError):
    """An invalid, incompatible, or unsafe plugin package."""


def user_data_dir(environ=None, home=None, platform=None):
    """Return Alex Collect's per-user data directory on Windows/Linux."""
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    platform = os.name if platform is None else platform
    if platform == "nt":
        root = environ.get("LOCALAPPDATA") or environ.get("APPDATA")
        if root:
            return Path(root) / "AlexCollect"
    return home / ".local" / "share" / "AlexCollect"


def default_plugin_root(environ=None, home=None, platform=None):
    return user_data_dir(environ=environ, home=home, platform=platform) / PLUGIN_DIR_NAME


def _safe_relative(value, label):
    if not isinstance(value, str) or not value.strip():
        raise PluginError("%s must be a non-empty relative path." % label)
    path = PurePosixPath(value.replace("\\", "/"))
    if (path.is_absolute() or ":" in value or
            any(part in ("", ".", "..") for part in path.parts)):
        raise PluginError("Unsafe %s path: %s" % (label, value))
    return path


def parse_version(value):
    """A dotted version as a tuple of ints, or () when it is not one.

    Lenient on purpose: plugin versions are author-supplied strings, and a
    caller comparing versions must not blow up on "1.0.15-beta" or "". Extra
    parts are kept, so 1.2.3.4 compares sensibly against 1.2.3.
    """
    if not isinstance(value, str):
        return ()
    parts = []
    for piece in value.strip().split("."):
        digits = re.match(r"\d+", piece)
        if not digits:
            break
        parts.append(int(digits.group()))
    return tuple(parts)


def version_at_least(have, want, _pad=4):
    """True when ``have`` is the same as or newer than ``want``.

    Missing trailing parts count as zero, so 1.0 and 1.0.0 are equal, and an
    unreadable version is never treated as new enough.
    """
    have_parts, want_parts = parse_version(have), parse_version(want)
    if not have_parts or not want_parts:
        return False
    width = max(len(have_parts), len(want_parts), _pad)
    return (have_parts + (0,) * (width - len(have_parts)) >=
            want_parts + (0,) * (width - len(want_parts)))


def _version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+){1,2}", value):
        raise PluginError("min_core_version must use a numeric version such as 2.21.")
    return tuple(int(part) for part in value.split("."))


def validate_manifest(raw, package_dir=None, host_api=PLUGIN_API_VERSION,
                      core_version=None):
    """Validate the public metadata contract; never execute plugin code."""
    if not isinstance(raw, dict):
        raise PluginError("plugin.json must contain a JSON object.")
    plugin_id = raw.get("id")
    if not isinstance(plugin_id, str) or not _PLUGIN_ID.fullmatch(plugin_id):
        raise PluginError("Plugin id must use lowercase letters, digits, '-' or '_'.")
    name = raw.get("name")
    version = raw.get("version")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise PluginError("Plugin name must be a non-empty string (max 100 characters).")
    if not isinstance(version, str) or not version.strip() or len(version) > 40:
        raise PluginError("Plugin version must be a non-empty string (max 40 characters).")
    api = raw.get("host_api")
    if not isinstance(api, int) or isinstance(api, bool):
        raise PluginError("host_api must be an integer.")
    if api != host_api:
        raise PluginError("Plugin requires host API %s; this app supports %s." %
                          (api, host_api))
    minimum = raw.get("min_core_version")
    if minimum is not None:
        min_tuple = _version_tuple(minimum)
        if core_version is not None:
            current_tuple = _version_tuple(core_version)
            width = max(len(min_tuple), len(current_tuple))
            if min_tuple + (0,) * (width - len(min_tuple)) > current_tuple + (0,) * (width - len(current_tuple)):
                raise PluginError("Plugin requires Alex Collect %s or newer; this app is %s." %
                                  (minimum, core_version))
    capabilities = raw.get("capabilities", [])
    if (not isinstance(capabilities, list) or
            any(not isinstance(x, str) or not x.strip() for x in capabilities)):
        raise PluginError("capabilities must be a list of non-empty strings.")
    if len(set(capabilities)) != len(capabilities):
        raise PluginError("capabilities contains duplicate entries.")
    tools = raw.get("tools", {})
    if not isinstance(tools, dict):
        raise PluginError("tools must be an object mapping action names to files.")
    clean_tools = {}
    for key, rel in tools.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,63}", key):
            raise PluginError("Tool keys must use lowercase letters, digits, '.', '_' or '-'.")
        rel_path = _safe_relative(rel, "tool")
        if package_dir is not None:
            file_path = Path(package_dir).joinpath(*rel_path.parts)
            try:
                file_path.resolve().relative_to(Path(package_dir).resolve())
            except ValueError:
                raise PluginError("Tool path escapes the plugin directory.")
            if not file_path.is_file():
                raise PluginError("Declared tool does not exist: %s" % rel)
        clean_tools[key] = rel_path.as_posix()
    actions = raw.get("actions", {})
    if not isinstance(actions, dict):
        raise PluginError("actions must map host action IDs to tool keys.")
    clean_actions = {}
    for action, tool_key in actions.items():
        if (not isinstance(action, str) or
                not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,99}", action)):
            raise PluginError("Action IDs must use lowercase letters, digits, '.', '_' or '-'.")
        if action not in capabilities:
            raise PluginError("Action '%s' must also be declared as a capability." % action)
        if tool_key not in clean_tools:
            raise PluginError("Action '%s' refers to an undeclared tool." % action)
        clean_actions[action] = tool_key
    clean = dict(raw)
    clean["tools"] = clean_tools
    clean["actions"] = clean_actions
    clean["capabilities"] = list(capabilities)
    return clean


def _manifest_at(directory, host_api=PLUGIN_API_VERSION, core_version=None):
    path = Path(directory) / PLUGIN_MANIFEST
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PluginError("The ZIP must contain a %s file." % PLUGIN_MANIFEST)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PluginError("Could not read plugin.json: %s" % exc)
    return validate_manifest(raw, package_dir=directory, host_api=host_api,
                             core_version=core_version), path


class PluginManager:
    """Install, list, enable, disable, and remove local plugin ZIPs."""

    def __init__(self, root=None, host_api=PLUGIN_API_VERSION,
                 core_version="2.54"):
        self.root = Path(root) if root is not None else default_plugin_root()
        self.root = self.root.expanduser()
        self.host_api = host_api
        self.core_version = core_version
        self.state_file = self.root / "enabled.json"

    def _read_enabled(self):
        try:
            value = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return {k: (v is True) for k, v in value.items()
                        if isinstance(k, str)}
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
        return {}

    def _write_enabled(self, enabled):
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(enabled, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        os.replace(tmp, self.state_file)

    def list_plugins(self):
        """Return metadata for installed plugins; invalid packages are reported."""
        enabled = self._read_enabled()
        if not self.root.is_dir():
            return []
        result = []
        for folder in sorted(self.root.iterdir(), key=lambda p: p.name.casefold()):
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            try:
                manifest, _ = _manifest_at(folder, self.host_api,
                                           self.core_version)
                if folder.name != manifest["id"]:
                    raise PluginError("Folder name does not match plugin id '%s'." %
                                      manifest["id"])
                result.append({**manifest, "path": folder,
                               "enabled": enabled.get(manifest["id"], False),
                               "compatible": True, "error": ""})
            except PluginError as exc:
                result.append({"id": folder.name, "name": folder.name,
                               "version": "", "path": folder,
                               "enabled": False, "compatible": False,
                               "capabilities": [], "tools": {},
                               "error": str(exc)})
        return result

    def get_plugin(self, plugin_id):
        for plugin in self.list_plugins():
            if plugin["id"] == plugin_id:
                if not plugin["compatible"]:
                    raise PluginError(plugin["error"])
                return plugin
        raise PluginError("Plugin is not installed: %s" % plugin_id)

    def is_enabled(self, plugin_id):
        try:
            return bool(self.get_plugin(plugin_id)["enabled"])
        except PluginError:
            return False

    def set_enabled(self, plugin_id, value):
        plugin = self.get_plugin(plugin_id)
        enabled = self._read_enabled()
        enabled[plugin_id] = bool(value)
        self._write_enabled(enabled)
        return {**plugin, "enabled": bool(value)}

    def resolve_tool(self, plugin_id, tool_key, require_enabled=True):
        plugin = self.get_plugin(plugin_id)
        if require_enabled and not plugin["enabled"]:
            raise PluginError("Plugin is disabled: %s" % plugin_id)
        rel = plugin["tools"].get(tool_key)
        if not rel:
            raise PluginError("Plugin '%s' does not provide tool '%s'." %
                              (plugin_id, tool_key))
        path = (Path(plugin["path"]) / rel).resolve()
        try:
            path.relative_to(Path(plugin["path"]).resolve())
        except ValueError:
            raise PluginError("Tool path escapes the plugin directory.")
        if not path.is_file():
            raise PluginError("Plugin tool is missing: %s" % rel)
        return path

    def resolve_action(self, action_id):
        """Resolve a declared host action to its enabled plugin tool."""
        providers = []
        disabled = []
        for plugin in self.list_plugins():
            if (plugin["compatible"] and
                    action_id in plugin.get("actions", {})):
                if not plugin["enabled"]:
                    disabled.append(plugin["id"])
                    continue
                tool_key = plugin["actions"][action_id]
                providers.append(self.resolve_tool(plugin["id"], tool_key))
        if not providers:
            if disabled:
                raise PluginError("Plugin is disabled: %s" % ", ".join(disabled))
            raise PluginError("No enabled plugin provides action: %s" % action_id)
        if len(providers) > 1:
            raise PluginError("More than one enabled plugin provides action: %s" % action_id)
        return providers[0]

    def install_zip(self, archive):
        """Safely install a user-selected ZIP; reject traversal and symlinks."""
        archive = Path(archive)
        if not zipfile.is_zipfile(archive):
            raise PluginError("Choose a valid plugin .zip file.")
        self.root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            if len(infos) > _MAX_ARCHIVE_FILES:
                raise PluginError("Plugin ZIP contains too many files.")
            total = sum(info.file_size for info in infos)
            if total > _MAX_ARCHIVE_BYTES:
                raise PluginError("Plugin ZIP is larger than 100 MB when expanded.")
            for info in infos:
                path = PurePosixPath(info.filename.replace("\\", "/"))
                if (path.is_absolute() or ":" in info.filename or
                        any(p in ("", ".", "..") for p in path.parts)):
                    raise PluginError("Unsafe path in plugin ZIP: %s" % info.filename)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise PluginError("Symbolic links are not allowed in plugin ZIPs.")
            with tempfile.TemporaryDirectory(prefix=".install-", dir=self.root) as td:
                stage = Path(td) / "package"
                stage.mkdir()
                for info in infos:
                    target = stage.joinpath(*PurePosixPath(
                        info.filename.replace("\\", "/")).parts)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as source, target.open("wb") as dest:
                            shutil.copyfileobj(source, dest)
                package = stage
                if not (package / PLUGIN_MANIFEST).is_file():
                    children = [p for p in stage.iterdir() if p.is_dir()]
                    if len(children) == 1 and (children[0] / PLUGIN_MANIFEST).is_file():
                        package = children[0]
                    else:
                        raise PluginError("The ZIP must contain plugin.json at its root or one folder below.")
                manifest, _ = _manifest_at(package, self.host_api,
                                           self.core_version)
                plugin_id = manifest["id"]
                # Re-validate paths against the fully extracted package.
                manifest = validate_manifest(manifest, package_dir=package,
                                             host_api=self.host_api,
                                             core_version=self.core_version)
                destination = self.root / plugin_id
                backup = self.root / (".%s-replaced" % plugin_id)
                if backup.exists():
                    shutil.rmtree(backup)
                had_old = destination.exists()
                if had_old:
                    os.replace(destination, backup)
                try:
                    os.replace(package, destination)
                except Exception:
                    if had_old and backup.exists():
                        os.replace(backup, destination)
                    raise
                if backup.exists():
                    shutil.rmtree(backup)
                # New plugins are enabled by default; retain an existing choice.
                enabled = self._read_enabled()
                enabled.setdefault(plugin_id, True)
                self._write_enabled(enabled)
        return self.get_plugin(plugin_id)

    def remove(self, plugin_id):
        if not isinstance(plugin_id, str) or not _PLUGIN_ID.fullmatch(plugin_id):
            raise PluginError("Invalid plugin id.")
        path = self.root / plugin_id
        if not path.is_dir():
            raise PluginError("Plugin is not installed: %s" % plugin_id)
        shutil.rmtree(path)
        enabled = self._read_enabled()
        enabled.pop(plugin_id, None)
        self._write_enabled(enabled)
        return {"id": plugin_id, "path": path}
