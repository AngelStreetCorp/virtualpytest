#!/usr/bin/env python3
"""Generate Postman-facing OpenAPI inventories from registered Flask routes.

The curated specs remain the human-friendly contracts. These generated inventory
specs add registered Server and Host route/method pairs, including enabled feature
blueprints, to the API reference. Only Server specs are published to the public Postman
workspace. Run this before scripts/sync_postman_openapi.py when routes change.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "docs" / "api" / "specs"
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
CONVERTERS = {"int": "integer", "float": "number", "uuid": "string", "string": "string", "path": "string"}


def dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def registered_blueprints(path: Path, list_names: set[str]) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.List):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(t, ast.Name) and t.id in list_names for t in targets):
            continue
        for entry in node.value.elts:
            if isinstance(entry, ast.Tuple) and entry.elts:
                item = dotted(entry.elts[0])
                if item:
                    found.add(item.rsplit(".", 1)[-1])
    return found


def route_records(path: Path, allowed_blueprints: set[str] | None = None) -> list[dict]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prefixes: dict[str, str] = {}
    function_docs = {
        node.name: ast.get_docstring(node) or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Call):
            continue
        if dotted(node.value.func) != "Blueprint":
            continue
        prefix = ""
        for kw in node.value.keywords:
            if kw.arg == "url_prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                prefix = kw.value.value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                prefixes[target.id] = prefix

    output: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node) or ""
        summary = re.split(r"[.!?]\s|\n", doc.strip(), maxsplit=1)[0] if doc.strip() else node.name.replace("_", " ").capitalize()
        query_names = set()
        for child in ast.walk(node):
            if (isinstance(child, ast.Call) and dotted(child.func) in {"request.args.get", "request.values.get"}
                    and child.args and isinstance(child.args[0], ast.Constant) and isinstance(child.args[0].value, str)):
                query_names.add(child.args[0].value)
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            bp = dotted(decorator.func.value)
            method_name = decorator.func.attr.lower()
            if not bp or bp.rsplit(".", 1)[-1] not in prefixes:
                continue
            bp_name = bp.rsplit(".", 1)[-1]
            if allowed_blueprints is not None and bp_name not in allowed_blueprints:
                continue
            if method_name not in {"route", "get", "post", "put", "patch", "delete"}:
                continue
            rule_node = decorator.args[0] if decorator.args else next((kw.value for kw in decorator.keywords if kw.arg in {"rule", "path"}), None)
            if not isinstance(rule_node, ast.Constant) or not isinstance(rule_node.value, str):
                continue
            methods = {"get": {"GET"}, "post": {"POST"}, "put": {"PUT"}, "patch": {"PATCH"}, "delete": {"DELETE"}}.get(method_name)
            if methods is None:
                methods = {"GET"}
                for kw in decorator.keywords:
                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
                        methods = {el.value.upper() for el in kw.value.elts if isinstance(el, ast.Constant) and isinstance(el.value, str)}
            rule = prefixes.get(bp_name, "").rstrip("/") + "/" + rule_node.value.lstrip("/")
            if rule == "":
                rule = "/"
            for method in methods & HTTP_METHODS:
                output.append({
                    "path": rule,
                    "method": method,
                    "function": node.name,
                    "summary": summary[:180],
                    "module": path.stem,
                    "blueprint": bp_name,
                    "query": sorted(query_names),
                    "source": path.relative_to(ROOT).as_posix(),
                })
    # A few blueprints register compatibility aliases with add_url_rule instead
    # of a decorator; include those rules too (notably Host stream directory lists).
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "add_url_rule":
            continue
        bp = dotted(node.func.value) if isinstance(node.func, ast.Attribute) else None
        bp_name = bp.rsplit(".", 1)[-1] if bp else ""
        if bp_name not in prefixes or (allowed_blueprints is not None and bp_name not in allowed_blueprints):
            continue
        rule_node = node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg == "rule"), None)
        if not isinstance(rule_node, ast.Constant) or not isinstance(rule_node.value, str):
            continue
        view_func_node = next((kw.value for kw in node.keywords if kw.arg == "view_func"), None)
        function_name = view_func_node.id if isinstance(view_func_node, ast.Name) else "registered_route"
        methods_node = next((kw.value for kw in node.keywords if kw.arg == "methods"), None)
        methods = {el.value.upper() for el in methods_node.elts if isinstance(el, ast.Constant) and isinstance(el.value, str)} if isinstance(methods_node, (ast.List, ast.Tuple, ast.Set)) else {"GET"}
        summary = re.split(r"[.!?]\s|\n", function_docs.get(function_name, "").strip(), maxsplit=1)[0] or function_name.replace("_", " ").capitalize()
        query_names = set()
        for child in ast.walk(node):
            if (isinstance(child, ast.Call) and dotted(child.func) in {"request.args.get", "request.values.get"}
                    and child.args and isinstance(child.args[0], ast.Constant) and isinstance(child.args[0].value, str)):
                query_names.add(child.args[0].value)
        rule = prefixes.get(bp_name, "").rstrip("/") + "/" + rule_node.value.lstrip("/")
        for method in methods & HTTP_METHODS:
            output.append({
                "path": rule,
                "method": method,
                "function": function_name,
                "summary": summary[:180],
                "module": path.stem,
                "blueprint": bp_name,
                "query": sorted(query_names),
                "source": path.relative_to(ROOT).as_posix(),
            })
    return output


def server_routes() -> list[dict]:
    app_path = ROOT / "backend_server/src/app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "routes":
            module_names.update(alias.name for alias in node.names)
    allowed = registered_blueprints(app_path, {"blueprints"})
    records = []
    for module in sorted(module_names):
        path = ROOT / "backend_server/src/routes" / f"{module}.py"
        if path.exists():
            records.extend(route_records(path, allowed))
    # Optional features are enabled by a manifest unless DISABLED_FEATURES names them.
    disabled = {value.strip() for value in os.getenv("DISABLED_FEATURES", "").split(",") if value.strip()}
    for feature_dir in sorted((ROOT / "features").iterdir()):
        if feature_dir.name in disabled or not (feature_dir / "manifest.json").exists():
            continue
        part = feature_dir / "backend_server"
        if not part.exists():
            continue
        for path in sorted(part.glob("*.py")):
            if path.name != "__init__.py":
                records.extend(route_records(path))
            else:
                records.extend(route_records(path))
    return records


def host_routes() -> list[dict]:
    registry = ROOT / "backend_host/src/routes/registry.py"
    runner = (os.getenv("HOST_TYPE", "") or "").startswith("runner_")
    allowed = registered_blueprints(registry, {"_runner_registry" if runner else "_full_registry"})
    records = []
    for path in sorted((ROOT / "backend_host/src/routes").glob("*.py")):
        if path.name == "registry.py":
            continue
        records.extend(route_records(path, allowed))
    # Feature host blueprints are enabled by manifest by default. Runner hosts skip
    # AI Test routes; only include those when HOST_TYPE is not runner_*.
    disabled = {value.strip() for value in os.getenv("DISABLED_FEATURES", "").split(",") if value.strip()}
    for feature_dir in sorted((ROOT / "features").iterdir()):
        if feature_dir.name in disabled or not (feature_dir / "manifest.json").exists():
            continue
        part = feature_dir / "backend_host"
        if not part.exists():
            continue
        if runner and feature_dir.name == "ai-test":
            continue
        for path in sorted(part.glob("*.py")):
            records.extend(route_records(path))
    # Host's health alias is registered directly on the Flask app, outside a blueprint.
    records.append({"path": "/health", "method": "GET", "function": "health_alias", "summary": "Backend Host health check", "module": "app", "blueprint": "host_health", "query": [], "source": "backend_host/src/app.py"})
    return records


def normalize_path(path: str) -> str:
    normalized = re.sub(r"<(?:([A-Za-z_][\w]*):)?([A-Za-z_][\w]*)>", r"{\2}", path)
    # Flask routes commonly register both `/resource` and `/resource/` aliases
    # to the same handler. Postman's OpenAPI importer folds those into one request;
    # treat them as one canonical API operation for inventory and verification.
    return normalized.rstrip("/") or "/"


def existing_pairs() -> set[tuple[str, str]]:
    result = set()
    for path in sorted(SPECS.glob("*.yaml")) + sorted(SPECS.glob("*.yml")):
        if path.name in {"server-additional-routes.yaml", "host-backend-host-routes.yaml"}:
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for route, operations in (data.get("paths") or {}).items():
            for method in operations:
                if method.upper() in HTTP_METHODS:
                    result.add((normalize_path(route), method.upper()))
    return result


def make_spec(title: str, server_url: str, records: list[dict], description: str, *, host_service: bool = False) -> dict:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in records:
        grouped[(normalize_path(record["path"]), record["method"])].append(record)
    paths = {}
    for (path, method), sources in sorted(grouped.items()):
        source = sorted(sources, key=lambda r: (r["module"], r["function"]))[0]
        parameters = []
        for match in re.finditer(r"\{([^}]+)\}", path):
            original = re.search(r"<(?:([^:<>]+):)?" + re.escape(match.group(1)) + r">", source["path"])
            converter = original.group(1) if original else "string"
            parameters.append({"name": match.group(1), "in": "path", "required": True, "schema": {"type": CONVERTERS.get(converter, "string")}})
        for name in source["query"]:
            parameters.append({"name": name, "in": "query", "required": False, "schema": {"type": "string"}})
        tag_parts = path.strip("/").split("/")
        tag = "/".join(tag_parts[:2]) if len(tag_parts) > 1 else (tag_parts[0] if tag_parts else title)
        op = {
            "summary": source["summary"],
            "description": f"Route inventory entry from `{source['source']}` ({source['function']}). Check the handler for required payload fields and authorization rules.",
            "operationId": re.sub(
                r"[^A-Za-z0-9_]+", "_",
                f"{source['module']}_{source['function']}_{method.lower()}_{hashlib.sha1(path.encode()).hexdigest()[:8]}",
            ),
            "tags": [tag],
            "parameters": parameters,
            "responses": {"default": {"description": "Endpoint response; see the source route for response schema and status codes."}},
        }
        if method in {"POST", "PUT", "PATCH"}:
            op["requestBody"] = {"required": False, "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}
        paths.setdefault(path, {})[method.lower()] = op
    security = ([{"ApiKeyAuth": []}, {"BearerAuth": []}] if host_service else [{"BearerAuth": []}])
    security_schemes = {
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
    }
    postman_variables = [
        {"key": "server_url", "value": server_url, "description": "Service base URL"},
        {"key": "jwt_token", "value": "your_jwt_token_here", "description": "User Bearer token where required"},
    ]
    if host_service:
        security_schemes["ApiKeyAuth"] = {"type": "apiKey", "in": "header", "name": "X-API-Key"}
        postman_variables.insert(1, {"key": "api_key", "value": "your_api_key_here", "description": "Service credential for trusted host callers"})
    return {
        "openapi": "3.0.3",
        "info": {"title": title, "version": "1.0.0", "description": description},
        "servers": [{"url": "{server_url}", "variables": {"server_url": {"default": server_url}}}],
        "security": security,
        "components": {"securitySchemes": security_schemes},
        "x-postman-variables": postman_variables,
        "paths": paths,
    }


def write_spec(path: Path, spec: dict) -> None:
    path.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")


def main() -> int:
    existing = existing_pairs()
    servers = server_routes()
    hosts = host_routes()
    missing_server = [r for r in servers if (normalize_path(r["path"]), r["method"]) not in existing]
    # All host operations receive a host collection; no HOST specs exist currently.
    server_path = SPECS / "server-additional-routes.yaml"
    host_path = SPECS / "host-backend-host-routes.yaml"
    write_spec(server_path, make_spec("SERVER - Additional Registered Routes", "http://localhost:5109", missing_server,
        "Additional registered Backend Server routes not already represented by the curated SERVER collections. This generated inventory lists route/method coverage; inspect the handler for exact payloads and response schemas."))
    write_spec(host_path, make_spec("HOST - Backend Host Routes", "http://localhost:6109", hosts,
        "Registered Backend Host routes, including enabled feature routes. This generated inventory lists route/method coverage; inspect the handler for exact payloads and response schemas.", host_service=True))
    print(f"Server registered route/method declarations: {len({(normalize_path(r['path']), r['method']) for r in servers})}")
    print(f"Server operations added beyond curated specs: {len({(normalize_path(r['path']), r['method']) for r in missing_server})}")
    print(f"Host registered route/method declarations: {len({(normalize_path(r['path']), r['method']) for r in hosts})}")
    print(f"Wrote {server_path.relative_to(ROOT)} and {host_path.relative_to(ROOT)}")
    all_specs = existing_pairs()
    all_specs.update({(normalize_path(r["path"]), r["method"]) for r in missing_server})
    all_specs.update({(normalize_path(r["path"]), r["method"]) for r in hosts})
    missing = {
        (label, normalize_path(route["path"]), route["method"])
        for label, records in (("SERVER", servers), ("HOST", hosts))
        for route in records
        if (normalize_path(route["path"]), route["method"]) not in all_specs
    }
    if missing:
        print(f"ERROR: {len(missing)} registered route/method pairs remain uncovered")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
