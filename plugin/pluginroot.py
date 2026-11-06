"""Shared plugin-root resolver, vendored byte-identical across the plugin family.

resolve(target, name, environ=None) returns name, root, host, via, marketplace,
declared, version, note and reason. root is a directory or None; via is link,
directory-marketplace, install or None. A failed lookup has a reason. A found
copy keeps its root even when its manifest version differs from hunsu.json's
pin; note says hunsu.json declares the pin and names the host (or linked)
copy, its root and version. Unreadable, malformed or non-object JSON/TOML
files count as empty; manifests then give no version. Failed lookups name
files that could not be read, and non-object entries count as absent. Manifests are read in
order: plugin.json, .claude-plugin/plugin.json, .codex-plugin/plugin.json.

All environment reads use environ (default os.environ). AGENT_HOST == 'codex'
selects Codex; anything else selects claude-code. Claude's home is
HUNSU_CLAUDE_DIR, CLAUDE_CONFIG_DIR, then ~/.claude. Codex's is HUNSU_CODEX_DIR,
AGENT_CODEX_HOME, CODEX_HOME, then ~/.codex. ~ uses environ's HOME, falling
back to os.path.expanduser only when HOME is absent.

A hunsu.local.json links[name] wins, relative to target. A missing directory
fails without fallback. Otherwise use in_place's catalog source, then
<link>/<name> if a directory, then the link itself. in_place checks the folder's
own catalog, then its child's; Claude's catalog precedes Codex's local catalog.
A catalog is read only when its realpath lies inside the folder it is read for.
A child <directory>/<name> exists only for a one-component name, and its catalog
is read only when the child's realpath lies inside the folder's. An escaping
child (relative or absolute symlink, parent or chain) is taken as named, its
catalog unread. Catalog sources must be local relative paths resolving by
realpath to directories inside the catalog's folder, with readable plugin
manifests naming no other plugin.

Otherwise hunsu.json plugins[name] supplies marketplace and version;
hunsu.local.json dev[name] overrides marketplace. Only the selected host and
marketplace apply. Claude uses a known_marketplaces.json directory source
in place (catalog, then <path>/<name>), else installed_plugins.json NAME@MARKET:
local for this target, project for this target (real paths), then user scope,
with an existing installPath. Codex requires config.toml plugins.NAME@MARKET
enabled = true and manifest-bearing directories in plugins/cache/MARKET/NAME.
MARKET and NAME must each be one path component. A Claude installPath and a
Codex cache copy are taken as the host records them; no catalog inside is read.
One copy wins; several require a unique manifest version matching the pin,
otherwise fail and list the copies. No declared marketplace: enumerate only
applicable installs with existing copies; exactly one marketplace resolves,
none fails, several fail naming them and asking for a marketplace declaration.
Never fall back to another host or marketplace. This module uses only stdlib
and reads files; it neither installs plugins nor changes the environment.
"""
import json
import os
import re
import tomllib


def object_value(value):
    return value if isinstance(value, dict) else {}


def load(path, errors=None, toml=False):
    try:
        with open(path, "rb" if toml else "r", **({} if toml else {"encoding": "utf-8"})) as fh:
            doc = tomllib.load(fh) if toml else json.load(fh)
        if not isinstance(doc, dict):
            raise ValueError("expected an object")
        return doc
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        if errors is not None:
            errors.append(path)
        return {}


PLUGIN_MANIFESTS = ("plugin.json", os.path.join(".claude-plugin", "plugin.json"), os.path.join(".codex-plugin", "plugin.json"))


def catalog_local(directory, src):
    """`src` as a directory inside the catalog's `directory`, or None. Only a relative path is: no URI scheme (`https:`,
    `file:`, `github:` — a remote source is not a payload here), not absolute or drive- or root-anchored, and resolving —
    by realpath, so neither `..` nor a symlink leads out — to `directory` itself or a directory under it."""
    if not isinstance(src, str) or not src or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", src):
        return None
    if os.path.isabs(src) or os.path.splitdrive(src)[0] or src.startswith(("/", "\\")):
        return None
    root = os.path.normpath(os.path.join(directory, src))
    return root if inside(root, directory) and os.path.isdir(root) else None


def inside(path, folder):
    """Whether `path` resolves to `folder` itself or a path under it."""
    base = os.path.realpath(folder)
    try:
        return os.path.commonpath([base, os.path.realpath(path)]) == base
    except ValueError:   # different drives
        return False


def child(directory, name):
    """The child as named, only for a single path component."""
    if (not isinstance(name, str) or not name or name in (".", "..") or
            any(sep in name for sep in ("/", "\\", os.sep, os.altsep) if sep) or
            os.path.splitdrive(name)[0]):
        return None
    return os.path.join(directory, name)


def manifest_names(root, errors=None):
    """The names the plugin manifests at `root` declare (a manifest without one adds none), or None when there is no
    manifest or one cannot be read — a root whose identity cannot be read is not taken."""
    names, found = set(), False
    for m in PLUGIN_MANIFESTS:
        path = os.path.join(root, m)
        if not os.path.isfile(path):
            continue
        found = True
        try:
            unreadable = []
            doc = load(path, unreadable)
            if unreadable:
                if errors is not None:
                    errors.extend(unreadable)
                return None
        except (OSError, ValueError):
            return None
        declared = doc.get("name") if isinstance(doc, dict) else None
        if not isinstance(doc, dict) or (declared is not None and not isinstance(declared, str)):
            return None   # not a manifest, or a name that is not a name (`["probe"]`, `{}`, 5): an identity not read
        if declared is not None:
            names.add(declared)
    return names if found else None


def catalog_source(directory, name, errors=None):
    """The source a marketplace directory's catalog names for plugin `name` (Claude's `.claude-plugin/marketplace.json`, then
    `.agents/plugins/marketplace.json`'s local path), when it is a directory inside the catalog's (catalog_local) whose plugin
    manifests name no other plugin; else None. The catalog's realpath must stay inside `directory` before it is read.
    A source checkout keeps its installed payload in a subdirectory (`./plugin`),
    and only its catalog says which. A URL, an absolute path or a path out of the directory names nothing here (a fresh
    review, 2026-11-05: `../outside` resolved to a sibling and `https://…` to a local `https:/…` directory)."""
    for catalog in (os.path.join(directory, ".claude-plugin", "marketplace.json"), os.path.join(directory, ".agents", "plugins", "marketplace.json")):
        if not inside(catalog, directory):
            continue
        try:
            entries = load(catalog, errors).get("plugins") or []
            if not isinstance(entries, list):
                continue
        except (OSError, ValueError, AttributeError):
            continue   # a catalog this cannot read names nothing; the earlier rule still applies
        for entry in entries:
            src = entry.get("source") if isinstance(entry, dict) and entry.get("name") == name else None
            if isinstance(src, dict) and src.get("source") == "local":
                src = src.get("path")
            root = catalog_local(directory, src)
            names = manifest_names(root, errors) if root else None
            if names is not None and names <= {name}:
                return root
    return None


def in_place(directory, name, errors=None):
    """A plugin's root inside a directory used in place (a hunsu.local.json link, a directory marketplace): what the
    directory's catalog names, else what its one-component child's catalog names when the child stays inside by realpath;
    None when no
    catalog names one — the caller keeps its earlier rule."""
    sub = child(directory, name)
    return catalog_source(directory, name, errors) or (catalog_source(sub, name, errors)
            if sub is not None and inside(sub, directory) and os.path.isdir(sub) else None)


def manifest_version(root, errors=None):
    for manifest in PLUGIN_MANIFESTS:
        path = os.path.join(root, manifest)
        if os.path.isfile(path):
            version = load(path, errors).get("version")
            if version is not None:
                return version
    return None


def resolve(target, name, environ=None):
    errors = []
    result = _resolve(target, name, environ, errors)
    if result["root"] is None and errors:
        result["reason"] += "; could not read: " + ", ".join(dict.fromkeys(errors))
    return result


def _resolve(target, name, environ, errors):
    env = os.environ if environ is None else environ
    host = "codex" if env.get("AGENT_HOST") == "codex" else "claude-code"
    local = load(os.path.join(target, "hunsu.local.json"), errors)
    declaration = object_value(object_value(load(os.path.join(target, "hunsu.json"), errors).get("plugins")).get(name))
    declared = declaration.get("version")
    market = object_value(local.get("dev")).get(name)
    market = market if isinstance(market, str) and market else declaration.get("marketplace")
    market = market if isinstance(market, str) else None
    result = dict(name=name, root=None, host=host, via=None, marketplace=market,
                  declared=declared, version=None, note=None, reason=None)

    def found(root, via):
        result.update(root=root, via=via, version=manifest_version(root, errors))
        if declared is not None and result["version"] != declared:
            result["note"] = "hunsu.json declares %s %s; the %s copy at %s is %s" % (name, declared, "linked" if via == "link" else host, root, result["version"])
        return result

    links = object_value(local.get("links"))
    if isinstance(links.get(name), str):
        directory = os.path.normpath(os.path.join(target, links[name]))
        if not os.path.isdir(directory):
            result["reason"] = "plugin %s link directory is missing: %s" % (name, directory)
            return result
        sub = child(directory, name)
        return found(in_place(directory, name, errors) or (sub if sub is not None and os.path.isdir(sub) else directory), "link")

    user_home = env.get("HOME") if "HOME" in env else os.path.expanduser("~")
    if host == "codex":
        home = env.get("HUNSU_CODEX_DIR") or env.get("AGENT_CODEX_HOME") or env.get("CODEX_HOME") or os.path.join(user_home, ".codex")
        config = os.path.join(home, "config.toml")
        installs = object_value(load(config, errors, toml=True).get("plugins"))

        def copies(marketplace):
            market_dir = child(os.path.join(home, "plugins", "cache"), marketplace)
            base = child(market_dir, name) if market_dir is not None else None
            if base is None:
                return []
            if object_value(installs.get(name + "@" + marketplace)).get("enabled") is not True:
                return []
            return [os.path.join(base, v) for v in sorted(os.listdir(base))
                    if os.path.isdir(os.path.join(base, v)) and
                    any(os.path.isfile(os.path.join(base, v, m)) for m in PLUGIN_MANIFESTS)] if os.path.isdir(base) else []
    else:
        home = env.get("HUNSU_CLAUDE_DIR") or env.get("CLAUDE_CONFIG_DIR") or os.path.join(user_home, ".claude")
        installs = object_value(load(os.path.join(home, "plugins", "installed_plugins.json"), errors).get("plugins"))

        def copies(marketplace):
            entries = installs.get(name + "@" + marketplace) or []
            if not isinstance(entries, list):
                return []
            want = os.path.realpath(target)
            for scope in ("local", "project", "user"):
                for entry in entries:
                    entry = object_value(entry)
                    path = entry.get("installPath")
                    if entry.get("scope") == scope and isinstance(path, str) and path and os.path.isdir(path) and (scope == "user" or
                            (isinstance(entry.get("projectPath"), str) and os.path.realpath(entry["projectPath"]) == want)):
                        return [path]
            return []

    if not market:
        markets = sorted({key.split("@", 1)[1] for key in installs
                          if key.startswith(name + "@") and copies(key.split("@", 1)[1])})
        if len(markets) != 1:
            result["reason"] = ("plugin %s has installations in several marketplaces on %s: %s; declare the marketplace" %
                                (name, host, ", ".join(markets)) if markets else
                                "plugin %s is not linked or installed here on %s" % (name, host))
            return result
        market = markets[0]
        result["marketplace"] = market

    if host == "claude-code":
        source = object_value(object_value(load(os.path.join(home, "plugins", "known_marketplaces.json"), errors).get(market)).get("source"))
        if source.get("source") == "directory" and isinstance(source.get("path"), str) and source["path"]:
            directory = source["path"]
            sub = child(directory, name)
            root = in_place(directory, name, errors) or (sub if sub is not None and os.path.isdir(sub) else None)
            if root:
                return found(root, "directory-marketplace")
    paths = copies(market)
    if len(paths) > 1:
        matching = [path for path in paths if declared is not None and manifest_version(path, errors) == declared]
        if len(matching) == 1:
            paths = matching
        else:
            result["reason"] = "plugin %s@%s has ambiguous versions on %s: %s" % (name, market, host, ", ".join(paths))
            return result
    if paths:
        return found(paths[0], "install")
    result["reason"] = "plugin %s@%s is declared for this project but not installed for it here on %s — `hunsu install`" % (name, market, host)
    return result
