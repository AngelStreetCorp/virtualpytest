"""
The published API contracts must be usable.

Two defects hid here (BUG-0800): ``server-dashboard.yaml`` was not valid YAML
(a plain scalar with a colon in it), so the reference viewer, Postman and every
client generator refused it — and the API reference dropdown offered 14 of the
19 published specs, so the dashboard, log-review and masterchief routes had no
contract a developer would find.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit  # no live server: the specs are files on disk

ROOT = Path(__file__).resolve().parents[2]
SPECS_DIR = ROOT / "docs" / "api" / "specs"


def _load_generator():
    """The script that writes the list the API reference offers."""
    path = ROOT / "scripts" / "generate_api_spec_manifest.py"
    spec = importlib.util.spec_from_file_location("generate_api_spec_manifest", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_published_spec_parses_as_yaml():
    """One unquoted colon was enough to make a whole contract unusable."""
    broken = []
    for path in sorted(SPECS_DIR.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            broken.append(f"{path.name}: {str(e).splitlines()[0]}")
            continue
        assert isinstance(document, dict), f"{path.name} is not a mapping"
        assert document.get("openapi"), f"{path.name} declares no openapi version"
        assert (document.get("info") or {}).get("title"), f"{path.name} has no info.title"
    assert not broken, "invalid YAML: " + "; ".join(broken)


def test_the_api_reference_offers_every_published_spec():
    """The dropdown is built from the files, so a new spec cannot be forgotten."""
    generator = _load_generator()
    offered = {entry["filename"] for entry in generator.entries()}
    on_disk = {path.stem for path in SPECS_DIR.glob("*.yaml")}
    missing = on_disk - offered - set(generator.BULK_DUMPS)
    assert not missing, f"not offered by the API reference: {sorted(missing)}"


def test_the_offered_list_is_the_generated_one():
    """The list in the frontend is the one the script writes."""
    generator = _load_generator()
    target = ROOT / "frontend" / "src" / "config" / "apiSpecs.ts"
    assert target.read_text(encoding="utf-8") == generator.render(generator.entries()), (
        "frontend/src/config/apiSpecs.ts is stale — run: python3 scripts/generate_api_spec_manifest.py"
    )


@pytest.mark.parametrize("name", ["server-dashboard", "server-log-review", "server-masterchief"])
def test_the_specs_that_were_missing_are_offered(name):
    """The three named categories that the dropdown never offered."""
    generator = _load_generator()
    assert name in {entry["filename"] for entry in generator.entries()}
