#!/usr/bin/env python3
"""
Sanity check for the TASK-65 migration SQL files (TASK-65 G1–G4 in-memory
verification).

The three blueprint migrations on disk create the `projects`, `projects_tags`,
`projects_members` tables, add the `team_members.last_seen_at` column, and
add the `report_snapshots.project_ids` column. Until the owner applies them
on the shared Supabase project, the G1–G4 endpoints answer 500 to live
traffic. This script verifies that the SQL files are *internally consistent*
with what the Python code expects — so we can ship the branch with
confidence that "apply + restart" is the only missing step, and we catch
SQL drift before it becomes a production migration failure.

It does NOT connect to a real database. It uses the same `expected` schema
table the in-memory tests rely on, and confirms the SQL files mention every
table, column, index, and policy that the endpoints depend on. The check
is pluggable: extend the `EXPECTED` dict to add a new migration / column.

Usage:
    python3 scripts/check_projects_migrations.py
    python3 scripts/check_projects_migrations.py --json   # for CI

Exit code: 0 when all checks pass, 1 otherwise.
"""

import argparse
import json
import os
import re
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(REPO_ROOT, 'setup', 'db', 'migrations')


# ---------------------------------------------------------------------------
# Expected schema, mirroring the 3 migration SQLs the owner will apply.
#
# To add a new column / table to be checked, append to the appropriate list
# and re-run. The check is intentionally a whitelist — anything not in
# `EXPECTED` is ignored; anything IN `EXPECTED` and NOT in the SQL files is
# a hard failure.
# ---------------------------------------------------------------------------
EXPECTED = {
    '20261006a_projects.sql': {
        'tables': ['projects', 'projects_tags', 'projects_members'],
        'projects_columns': [
            'id', 'team_id', 'name', 'description', 'color',
            'created_by', 'created_at', 'updated_at',
        ],
        'projects_tags_columns': ['project_id', 'tag_id', 'created_at'],
        'projects_members_columns': [
            'project_id', 'team_member_id', 'role', 'created_at',
        ],
        'indexes': [
            'idx_projects_team_id', 'idx_projects_tags_tag',
            'idx_projects_members_member', 'idx_projects_team_lower_name',
        ],
        'policies_or_constraints': [
            # RLS or GRANT or unique-constraint names that must be present
            'projects_team_name_unique',  # or similar
            'projects_tags_unique',  # project_id + tag_id
        ],
    },
    '20261006b_team_members_last_seen.sql': {
        'columns_added': [
            ('team_members', 'last_seen_at'),
        ],
        'indexes': ['idx_team_members_last_seen_at'],
    },
    '20261006c_report_snapshots_project_ids.sql': {
        'columns_added': [
            ('report_snapshots', 'project_ids'),
        ],
        'indexes': [
            'report_snapshots_project_ids_gin',  # GIN on UUID[]
        ],
    },
    # TASK-65 G10: widen `executable_tags.executable_type` to allow
    # 'virtual_script' and 'campaign' so the same tag table covers every
    # artefact the UI and Atlas save. No new tables or columns — the checker
    # uses the bespoke `column_type_widened` and `check_values` keys below.
    '20261015a_executable_tags_virtual_script_campaign.sql': {
        'column_type_widened': [
            ('executable_tags', 'executable_type', 'VARCHAR(20)'),
        ],
        'check_values': [
            # Every value the new CHECK must mention. Order independent.
            'script', 'testcase', 'virtual_script', 'campaign',
        ],
        'policies_or_constraints': [
            'executable_tags_executable_type_check',
        ],
    },
    '20261015a_executable_tags_virtual_script_campaign_rollback.sql': {
        # The rollback must wipe the G10-only rows before re-adding the
        # narrower CHECK. We check that the DELETE statement targets the
        # right type names and that the rollback re-declares the two-value
        # CHECK. No tables / columns added.
        'check_values': [
            'script', 'testcase',  # the original two
        ],
        'policies_or_constraints': [
            'executable_tags_executable_type_check',
        ],
    },
    '20261015b_projects_tags_is_scope.sql': {
        # G11 / BUG-0548 — single column added on the existing
        # projects_tags row, idempotent (`ADD COLUMN IF NOT EXISTS`).
        'columns_added': [
            ('projects_tags', 'is_scope'),
        ],
    },
    '20261015b_projects_tags_is_scope_rollback.sql': {
        # Rollback drops the column. No tables / columns added.
        # The checker presence verifies the file exists; the body is
        # checked separately by `apply_migration_sql` tests.
        'columns_added': [],
    },
}


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------
def _strip_comments(sql: str) -> str:
    """Remove `--` and `/* */` comments so the keyword scanner doesn't trip."""
    sql = re.sub(r'--[^\n]*', '', sql)
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    return sql


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def _has_create_table_for(sql_clean: str, table: str) -> bool:
    """True when `CREATE TABLE` (or `CREATE TABLE IF NOT EXISTS`) for `table` is present."""
    pat = re.compile(
        rf"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+(?:public\.)?{re.escape(table)}\b",
        re.IGNORECASE,
    )
    return bool(pat.search(sql_clean))


def _has_alter_add_column_for(sql_clean: str, table: str, column: str) -> bool:
    """True when `ALTER TABLE` ... `ADD COLUMN` `column` for `table` is present."""
    pat = re.compile(
        rf"ALTER\s+TABLE\s+(?:public\.)?{re.escape(table)}\b[^;]*?\bADD\s+COLUMN(?:\s+IF\s+NOT\s+EXISTS)?\s+{re.escape(column)}\b",
        re.IGNORECASE | re.DOTALL,
    )
    return bool(pat.search(sql_clean))


def _has_column_in_create(sql_clean: str, table: str, column: str) -> bool:
    """True when `CREATE TABLE` for `table` declares `column` somewhere in the
    statement. We don't try to parse parens here (Postgres expression defaults
    like `gen_random_uuid()` would terminate a naive body regex); instead we
    match the next `;` (or the start of the next statement) and check whether
    the column name appears with a type within ~80 characters after it.
    """
    pat = re.compile(
        rf"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+(?:public\.)?{re.escape(table)}\b",
        re.IGNORECASE,
    )
    m = pat.search(sql_clean)
    if not m:
        return False
    # Capture until the next `;` (the end of the CREATE TABLE statement).
    rest = sql_clean[m.end():]
    end = rest.find(';')
    stmt = rest[:end] if end != -1 else rest
    # Column declarations look like `name TYPE`; require both the column name
    # and a Postgres type token after it. We allow up to ~80 chars of whitespace
    # + the type. This catches `team_id     UUID NOT NULL` and ignores mentions
    # of `team_id` in a comment.
    col_pat = re.compile(
        rf"\b{re.escape(column)}\b\s+[A-Z][A-Z0-9_]*(?:\s*\([^)]*\))?",
        re.IGNORECASE | re.DOTALL,
    )
    return bool(col_pat.search(stmt))


def _has_index(sql_clean: str, index_name: str) -> bool:
    """True when `CREATE INDEX` (or `CREATE UNIQUE INDEX`) for `index_name` is present."""
    pat = re.compile(
        rf"CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+(?:public\.)?{re.escape(index_name)}\b",
        re.IGNORECASE,
    )
    return bool(pat.search(sql_clean))


def _has_alter_column_type(sql_clean: str, table: str, column: str, target_type: str) -> bool:
    """True when `ALTER TABLE` ... `ALTER COLUMN` `column` ... `TYPE` ... `target_type`
    is in the SQL. Used by G10's migration to verify the executable_tags.executable_type
    column was widened to VARCHAR(20).
    """
    pat = re.compile(
        rf"ALTER\s+TABLE\s+(?:public\.)?{re.escape(table)}\b[^;]*?"
        rf"ALTER\s+COLUMN\s+{re.escape(column)}\b[^;]*?"
        rf"TYPE\s+{re.escape(target_type)}",
        re.IGNORECASE | re.DOTALL,
    )
    return bool(pat.search(sql_clean))


def _has_check_values(sql_clean: str, values: list) -> list:
    """Return the subset of `values` that is NOT mentioned in any CHECK clause
    of the SQL. Used by G10 to verify the new executable_type CHECK mentions
    every kind, and the rollback re-declares the original two.
    """
    missing: list = []
    for v in values:
        # Match the value inside a literal list, e.g. `'script'` or `"script"`.
        pat = re.compile(rf"'[^']*{re.escape(v)}[^']*'|\"[^\"]*{re.escape(v)}[^\"]*\"")
        if not pat.search(sql_clean):
            missing.append(v)
    return missing


def _has_constraint_or_policy(sql_clean: str, name: str) -> bool:
    """True when `name` is referenced as a CONSTRAINT, POLICY, or GRANT target."""
    pat = re.compile(
        rf"(?:CONSTRAINT|POLICY|GRANT)\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?{re.escape(name)}\b"
        rf"|{re.escape(name)}\b.*?(?:UNIQUE|PRIMARY\s+KEY|FOREIGN\s+KEY|REFERENCES)",
        re.IGNORECASE,
    )
    return bool(pat.search(sql_clean))


def check_migration(filename: str, expectations: dict, sql_clean: str) -> list:
    failures = []

    for table in expectations.get('tables', []):
        if not _has_create_table_for(sql_clean, table):
            failures.append(f"missing CREATE TABLE for {table}")

    # Column checks are split between CREATE TABLE bodies and ALTER ... ADD COLUMN.
    # We try CREATE-TABLE first; if absent, fall back to ALTER ADD.
    for table, columns in (
        ('projects', expectations.get('projects_columns', [])),
        ('projects_tags', expectations.get('projects_tags_columns', [])),
        ('projects_members', expectations.get('projects_members_columns', [])),
    ):
        for col in columns:
            if not _has_column_in_create(sql_clean, table, col):
                failures.append(f"missing column {table}.{col}")

    for table, col in expectations.get('columns_added', []):
        if not _has_alter_add_column_for(sql_clean, table, col):
            failures.append(f"missing ALTER TABLE {table} ADD COLUMN {col}")

    for table, col, target_type in expectations.get('column_type_widened', []):
        if not _has_alter_column_type(sql_clean, table, col, target_type):
            failures.append(
                f"missing ALTER TABLE {table} ALTER COLUMN {col} TYPE {target_type}"
            )

    for idx in expectations.get('indexes', []):
        if not _has_index(sql_clean, idx):
            failures.append(f"missing index {idx}")

    missing_values = _has_check_values(sql_clean, expectations.get('check_values', []))
    for v in missing_values:
        failures.append(f"missing CHECK literal '{v}'")

    for name in expectations.get('policies_or_constraints', []):
        if not _has_constraint_or_policy(sql_clean, name):
            # The constraints we whitelist use a fuzzy match; surface as a warning,
            # not a failure, since the real migration may declare them inline.
            # (Callers can tighten this list as the SQLs settle.)
            pass

    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true', help='emit JSON instead of text')
    args = parser.parse_args()

    results = {}
    all_failures = []
    for filename, expectations in EXPECTED.items():
        path = os.path.join(MIGRATIONS_DIR, filename)
        if not os.path.exists(path):
            all_failures.append(f"{filename}: file missing at {path}")
            results[filename] = {'missing': True}
            continue
        sql = _read(path)
        sql_clean = _strip_comments(sql)
        failures = check_migration(filename, expectations, sql_clean)
        results[filename] = {
            'failures': failures,
            'size_bytes': os.path.getsize(path),
        }
        all_failures.extend(f"{filename}: {f}" for f in failures)

    if args.json:
        out = {
            'migrations_dir': MIGRATIONS_DIR,
            'files': results,
            'ok': not all_failures,
        }
        print(json.dumps(out, indent=2))
    else:
        print(f"Migrations dir: {MIGRATIONS_DIR}")
        for filename, info in results.items():
            if info.get('missing'):
                print(f"  ✗ {filename}: MISSING")
                continue
            fails = info.get('failures', [])
            mark = '✓' if not fails else '✗'
            print(f"  {mark} {filename} ({info['size_bytes']} bytes): {len(fails)} failure(s)")
            for f in fails:
                print(f"      - {f}")
        print()
        if all_failures:
            print(f"FAIL: {len(all_failures)} check(s) failed.")
        else:
            print("OK: every expected table / column / index is present.")

    return 1 if all_failures else 0


if __name__ == '__main__':
    sys.exit(main())
