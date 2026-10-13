#!/usr/bin/env python3
"""
report_i18n_check.py — Validate the report i18n catalogs for TASK-52.

Two catalogs are checked:

  1. The **platform** catalog in ``<platform-dir>/<lang>.json`` (default
     ``shared/src/lib/i18n/report``). ``en.json`` is the source of truth. For
     every other language file we list keys missing vs en, extra keys not in
     en, and any placeholder mismatch between the en template and the
     translation of the same key.

  2. Every ``*.i18n.json`` under ``<scripts-dir>`` (default ``test_scripts``,
     walked recursively). Each entry's key is the exact English string
     written by the script; its value is a ``{lang: template}`` map. We list
     the languages (other than en) that are missing from the entry, and we
     verify that every translation keeps the same ``{placeholder}`` set as
     the key.

Invalid JSON files and placeholder mismatches are hard errors. Missing
translations are reported as warnings, unless ``--strict`` is passed, in
which case they also become errors.

Usage:
    python3 scripts/report_i18n_check.py                       # default paths
    python3 scripts/report_i18n_check.py --strict
    python3 scripts/report_i18n_check.py \\
        --platform-dir /tmp/fake_platform \\
        --scripts-dir /tmp/fake_scripts

Repo root defaults to the parent of the ``scripts/`` directory this file
lives in, so ``--platform-dir`` and ``--scripts-dir`` are resolved relative
to it when not absolute. Exit code 0 on success, 1 on any error.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Placeholders are ``{name}`` where ``name`` is a simple identifier. The
# regex matches what's actually used at runtime, so the checker can verify
# a translation keeps the same set as the English template.
PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def placeholders(text):
    """Return the sorted tuple of placeholder names found in ``text``."""
    return tuple(sorted(PLACEHOLDER_RE.findall(text or "")))


def load_json(path):
    """Load JSON from ``path``; return (data, error_message)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except FileNotFoundError:
        return None, "file not found"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"


def resolve(rel_root, value):
    return value if os.path.isabs(value) else os.path.join(rel_root, value)


def check_platform(platform_dir, strict):
    """Yield (severity, where, message) for the platform catalog."""
    if not os.path.isdir(platform_dir):
        yield ("warn", platform_dir,
               f"platform directory not found: {platform_dir} (skipping)")
        return

    en_path = os.path.join(platform_dir, "en.json")
    en_data, en_err = load_json(en_path)
    if en_err == "file not found":
        yield ("warn", en_path, "en.json not found (skipping platform check)")
        return
    if en_err:
        yield ("error", en_path, f"en.json: {en_err}")
        return
    if not isinstance(en_data, dict):
        yield ("error", en_path, "en.json: top-level value is not an object")
        return

    en_keys = set(en_data.keys()) - {"_name"}

    other_files = sorted(
        p for p in Path(platform_dir).glob("*.json")
        if p.name != "en.json"
    )
    if not other_files:
        yield ("info", platform_dir, "no non-en platform languages found")
        return

    for p in other_files:
        lang = p.stem
        data, err = load_json(p)
        if err:
            yield ("error", str(p), f"{lang}.json: {err}")
            continue
        if not isinstance(data, dict):
            yield ("error", str(p), f"{lang}.json: top-level value is not an object")
            continue
        keys = set(data.keys()) - {"_name"}
        missing = sorted(en_keys - keys)
        extra = sorted(keys - en_keys)
        if missing:
            sev = "error" if strict else "warn"
            yield (sev, str(p),
                   f"{lang}.json: missing {len(missing)} key(s) vs en: "
                   + ", ".join(missing[:8])
                   + (f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""))
        if extra:
            yield ("warn", str(p),
                   f"{lang}.json: extra {len(extra)} key(s) not in en: "
                   + ", ".join(extra[:8])
                   + (f" (+{len(extra) - 8} more)" if len(extra) > 8 else ""))
        # Placeholder consistency for keys present in both files
        for k in sorted(en_keys & keys):
            en_val = en_data.get(k, "")
            tr_val = data.get(k, "")
            if not isinstance(tr_val, str):
                yield ("error", str(p),
                       f"{lang}.json: {k!r} value is not a string")
                continue
            en_ph = placeholders(en_val) if isinstance(en_val, str) else ()
            tr_ph = placeholders(tr_val)
            if en_ph != tr_ph:
                yield ("error", str(p),
                       f"{lang}.json: {k!r} placeholder mismatch — en has "
                       f"{list(en_ph) or 'none'}, {lang} has {list(tr_ph) or 'none'}")


def check_scripts(scripts_dir, platform_dir, strict):
    """Yield (severity, where, message) for every script i18n file."""
    if not os.path.isdir(scripts_dir):
        yield ("warn", scripts_dir,
               f"scripts directory not found: {scripts_dir} (skipping)")
        return

    # Languages the platform offers (other than en). A script entry should
    # cover all of them; missing ones are reported.
    platform_langs = []
    if os.path.isdir(platform_dir):
        platform_langs = sorted(
            p.stem for p in Path(platform_dir).glob("*.json")
            if p.stem != "en"
        )
    if not platform_langs:
        yield ("info", scripts_dir,
               "no non-en platform languages; nothing to cross-check against")

    files = sorted(Path(scripts_dir).glob("**/*.i18n.json"))
    if not files:
        yield ("info", scripts_dir, "no *.i18n.json files found")
        return

    for path in files:
        data, err = load_json(path)
        if err:
            yield ("error", str(path), err)
            continue
        if not isinstance(data, dict):
            yield ("error", str(path), "top-level JSON is not an object")
            continue

        for key, value in data.items():
            key_disp = key if len(key) <= 60 else key[:57] + "..."
            label = f"{path} :: {key_disp!r}"
            if not isinstance(value, dict):
                yield ("error", str(path),
                       f"value for key {key!r} is not an object")
                continue
            expected = placeholders(key)
            # Which platform languages (other than en) should be present?
            wanted = [l for l in platform_langs if l not in value]
            if wanted:
                sev = "error" if strict else "warn"
                yield (sev, label,
                       f"missing translation(s) for: {', '.join(wanted)}")
            # Placeholder consistency per translation
            for lang, template in value.items():
                if not isinstance(template, str):
                    yield ("error", label,
                           f"{lang}: translation is not a string")
                    continue
                got = placeholders(template)
                if got != expected:
                    yield ("error", label,
                           f"{lang}: placeholder mismatch — key has "
                           f"{list(expected) or 'none'}, "
                           f"translation has {list(got) or 'none'}")


def print_group(label, items):
    if not items:
        return
    print(f"\n=== {label} ({len(items)}) ===")
    for sev, where, msg in items:
        print(f"  {sev:5s}  {where}")
        print(f"          {msg}")


def main():
    parser = argparse.ArgumentParser(
        description=("Validate report i18n catalogs "
                     "(platform + per-script *.i18n.json)."))
    parser.add_argument(
        "--platform-dir",
        default="shared/src/lib/i18n/report",
        help="Path to the platform catalog directory (default: %(default)s)")
    parser.add_argument(
        "--scripts-dir",
        default="test_scripts",
        help="Path to the per-script catalog root, walked recursively "
             "(default: %(default)s)")
    parser.add_argument(
        "--strict", action="store_true",
        help="Treat missing translations as errors (default: warnings).")
    args = parser.parse_args()

    # Repo root is the parent of the directory this script lives in
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    platform_dir = resolve(repo_root, args.platform_dir)
    scripts_dir = resolve(repo_root, args.scripts_dir)

    findings = []
    findings.extend(check_platform(platform_dir, args.strict))
    findings.extend(check_scripts(scripts_dir, platform_dir, args.strict))

    errors = [f for f in findings if f[0] == "error"]
    warns = [f for f in findings if f[0] == "warn"]
    infos = [f for f in findings if f[0] == "info"]

    print_group("Errors", errors)
    print_group("Warnings", warns)
    print_group("Info", infos)

    print()
    print(
        f"summary: {len(errors)} error(s), {len(warns)} warning(s), "
        f"{len(infos)} info | platform-dir={platform_dir} | "
        f"scripts-dir={scripts_dir} | strict={args.strict}"
    )
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
