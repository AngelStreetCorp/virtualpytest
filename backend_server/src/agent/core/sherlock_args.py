"""
The arguments a script run got, as facts for Sherlock's verdict (TASK-38).

A run can fail on its own arguments (``dns_lookuptime --dns <a hostname>`` asks a DNS server that
doesn't exist): without them, the LLM and Jev read that as a product failure. Each declared argument
of the script comes with the value it ran with, whether that was the default, and its meaning from
``_arg_descriptions``. Sources: ``metadata.parameters`` (the command line) and the stored script
source (``metadata.script_source.path``). Never raises; an empty list when nothing is known.
"""

import shlex
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.cloudflare_utils import fetch_text_from_storage
from shared.src.lib.utils.script_params_utils import analyze_script_source

# Framework arguments every run gets; they say where it ran, not what it tested.
FRAMEWORK_ARGS = {"host", "device"}


def parse_command_line(command_line: str) -> Dict[str, Optional[str]]:
    """``--name value`` / ``--flag`` pairs of a stored command line."""
    try:
        tokens = shlex.split(command_line or "")
    except ValueError:
        tokens = (command_line or "").split()
    values: Dict[str, Optional[str]] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--"):
            name = tok[2:]
            if "=" in name:
                name, val = name.split("=", 1)
                values[name] = val
            elif i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                values[name] = tokens[i + 1]
                i += 1
            else:
                values[name] = None
        i += 1
    return values


def describe(command_line: str, source: str) -> List[Dict[str, Any]]:
    """Declared arguments with the value used; arguments not declared by the script are listed too."""
    given = parse_command_line(command_line)
    declared = analyze_script_source(source).get("parameters") or [] if source else []
    out, seen = [], set()
    for p in declared:
        name = p["name"]
        if name in FRAMEWORK_ARGS:
            continue
        seen.add(name)
        used_default = name not in given
        item = {"name": name, "value": p.get("default") if used_default else given[name],
                "default": p.get("default"), "used_default": used_default}
        if p.get("description"):
            item["meaning"] = p["description"]
        out.append(item)
    for name, value in given.items():
        if name not in seen and name not in FRAMEWORK_ARGS:
            out.append({"name": name, "value": value})
    return out


def for_record(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        source_path = (metadata.get("script_source") or {}).get("path")
        source = ""
        if source_path:
            fetched = fetch_text_from_storage(source_path)
            source = (fetched.get("text") or "") if fetched.get("success") else ""
        return describe(metadata.get("parameters") or "", source)
    except Exception as e:
        print(f"[Sherlock] script arguments unavailable for {record.get('id')}: {e}")
        return []
