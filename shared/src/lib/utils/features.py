"""
Optional-feature discovery (see docs/technical/FEATURES.md).

Layout: <project_root>/features/<name>/manifest.json (+ optional sub-folders
backend_server/, backend_host/, frontend/, grafana/, lib/, skills/).

Every app calls into this module at startup; a feature is *enabled* when its folder
holds a manifest.json AND its name is not in the DISABLED_FEATURES env var
(comma-separated). With no features/ folder, or every feature disabled, nothing is
registered and the apps behave exactly as before.
"""
import importlib
import json
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# shared/src/lib/utils -> project root is four levels up
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, '..', '..', '..', '..'))
FEATURES_DIR = os.path.join(PROJECT_ROOT, 'features')


def disabled_features() -> set:
    """Names listed in DISABLED_FEATURES (comma-separated, whitespace tolerant)."""
    raw = os.getenv('DISABLED_FEATURES', '') or ''
    return {tok.strip() for tok in raw.split(',') if tok.strip()}


def enabled_features(features_dir: str = FEATURES_DIR) -> list:
    """Return [{'name', 'path', 'manifest'}] for every enabled feature, sorted by name."""
    if not os.path.isdir(features_dir):
        return []
    disabled = disabled_features()
    found = []
    try:
        names = sorted(os.listdir(features_dir))
    except OSError as e:  # e.g. WinError 5 on a dir rsync created with a Cygwin ACL (BUG-0073)
        print(f"[@features] ⚠️  cannot list {features_dir} ({e}) - no optional feature loaded")
        return []
    for name in names:
        path = os.path.join(features_dir, name)
        manifest_path = os.path.join(path, 'manifest.json')
        if not os.path.isfile(manifest_path):
            continue
        if name in disabled:
            print(f"[@features] ⏭️  {name}: disabled via DISABLED_FEATURES")
            continue
        try:
            with open(manifest_path, encoding='utf-8') as fh:
                manifest = json.load(fh)
        except Exception as e:  # malformed manifest = feature skipped, never a crash
            print(f"[@features] ⚠️  {name}: unreadable manifest.json ({e}) - skipped")
            continue
        found.append({'name': name, 'path': path, 'manifest': manifest})
    return found


def enabled_feature_dirs(subpath: str) -> list:
    """[(name, abs_dir)] for every enabled feature that has `subpath` (e.g. 'skills',
    'backend_server/mcp_tools'). Generic hook so core loaders that scan a fixed folder
    (agent skills, MCP tools) can also pick up what a feature contributes, without
    core ever importing a feature by name.
    """
    out = []
    for feat in enabled_features():
        d = os.path.join(feat['path'], *subpath.split('/'))
        if os.path.isdir(d):
            out.append((feat['name'], d))
    return out


def register_feature_blueprints(app, part: str) -> int:
    """Import features.<name>.<part> and call its register(app) for each enabled feature.

    `part` is 'backend_server' or 'backend_host'. A feature without that sub-package
    is silently skipped. Returns the number of features registered.
    Requires PROJECT_ROOT on sys.path (both apps already put it there).
    """
    count = 0
    for feat in enabled_features():
        name = feat['name']
        if not os.path.isfile(os.path.join(feat['path'], part, '__init__.py')):
            continue
        try:
            module = importlib.import_module(f"features.{name}.{part}")
            module.register(app)
            count += 1
            print(f"[@features] ✅ {name}: {part} registered")
        except Exception as e:
            print(f"[@features] ❌ {name}: {part} failed to register: {e}")
            import traceback
            traceback.print_exc()
    return count


def register_feature_controllers(part: str = 'backend_host') -> int:
    """Import features.<name>.<part> and call its optional register_controllers().

    The no-Flask sibling of register_feature_blueprints. Scripts run as their own
    subprocess (shared/src/lib/executors/script_executor.py), so they build a Host and
    its controllers with no app to register against — a feature that contributes a
    controller has to be given a second chance here or its devices come up with that
    controller missing. A feature without the function is silently skipped, and a
    feature that already registered through register(app) is expected to make its
    register_controllers() a no-op (the app-side registration is the better one: it
    holds live in-process state a subprocess can only reach over the network).
    """
    count = 0
    for feat in enabled_features():
        name = feat['name']
        if not os.path.isfile(os.path.join(feat['path'], part, '__init__.py')):
            continue
        try:
            module = importlib.import_module(f"features.{name}.{part}")
        except Exception as e:
            print(f"[@features] ❌ {name}: {part} failed to import: {e}")
            continue
        hook = getattr(module, 'register_controllers', None)
        if not callable(hook):
            continue
        try:
            hook()
            count += 1
            # "ran", not "registered": a feature that already registered through
            # register(app) is expected to make this a no-op, and only it can tell.
            print(f"[@features] ✅ {name}: {part} register_controllers() ran")
        except Exception as e:
            print(f"[@features] ❌ {name}: {part} controllers failed to register: {e}")
            import traceback
            traceback.print_exc()
    return count
