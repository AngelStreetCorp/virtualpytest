#!/usr/bin/env python3
"""
TASK-42 gate harness (docs/tasks/TASK-42-test-run-management-parity.md §8).

    python3 scripts/task42_gate.py preflight --manifest <path>
    python3 scripts/task42_gate.py final     --manifest <path> --output-dir <outside-repo-path>

preflight — static bookkeeping only: revision ancestry, clean tree, conflict markers,
            migration/schema pairing and ordering, worker commits merged, stub and
            debug-output scan of changed files, no secrets in the manifest. Runs no tests.

final     — runs once on the frozen, clean candidate:
            1. disposable Postgres (binaries from TASK42_PG_BIN, data dir under the
               output dir, unix socket only): fresh install of every schema file, and an
               upgrade path (schema files present at base_sha + existing-data fixture +
               new migrations). The TASK-42 catalog (columns, constraints, indexes,
               policies, functions) of both databases must be identical. Never points at
               a shared database.
            2. every manifest test command (pytest, tsc, vitest, vite build, Playwright,
               security checks). Commands receive TASK42_PG_DSN for the fresh database.
            3. JSON + Markdown report in --output-dir. Exit code is nonzero unless every
               required gate passed; a required gate that was skipped or blocked fails.

Exit codes: 0 ready · 1 preflight defect · 2 a required final gate failed · 3 environment
missing. The manifest must contain no secrets; the harness never reads a .env file.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCHEMA_DIR = "setup/db/schema"
MIGRATION_DIR = "setup/db/migrations"
SHIM = "scripts/task42/supabase_shim.sql"
UPGRADE_FIXTURE = "scripts/task42/upgrade_fixture.sql"
PG_PORT = 55433

SECRET_RE = re.compile(r"(secret|password|passwd|token|api[_-]?key|jwt|bearer)", re.IGNORECASE)
CONFLICT_RE = re.compile(r"^(<{7} |={7}$|>{7} )", re.MULTILINE)
# Debug output / placeholder code that must not ship in product code paths.
STUB_PATTERNS = {
    ".py": [re.compile(r"\bmcode_diff\b"), re.compile(r"raise NotImplementedError"),
            re.compile(r"#\s*(TODO|FIXME|XXX)\b"), re.compile(r"^\s*print\(.*(DEBUG|debug)")],
    ".ts": [re.compile(r"\bconsole\.log\("), re.compile(r"\bmcode_diff\b"),
            re.compile(r"//\s*(TODO|FIXME|XXX)\b")],
    ".tsx": [re.compile(r"\bconsole\.log\("), re.compile(r"\bmcode_diff\b"),
             re.compile(r"//\s*(TODO|FIXME|XXX)\b")],
}
# A Python function whose whole body is `pass` (optionally after a docstring) is a stub.
PY_STUB_FN = re.compile(r"^\s*def [^\n]+:\n(\s+(\"\"\"|\'\'\')[\s\S]*?\2\n)?\s+pass\s*$", re.MULTILINE)
PRODUCT_PREFIXES = ("backend_server/src/", "backend_host/src/", "shared/src/", "frontend/src/")


@dataclasses.dataclass
class Manifest:
    base_sha: str
    candidate_sha: str
    scope: List[str]
    worker_commits: List[str]
    migration_files: List[str]
    test_commands: List[Dict[str, Any]]
    fixture_ids: List[str]
    required_capabilities: List[str]
    test_environment: str
    stub_allowlist: List[str]
    catalog_tables: List[str]

    @classmethod
    def load(cls, path: str) -> "Manifest":
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return cls(
            base_sha=raw["base_sha"],
            candidate_sha=raw["candidate_sha"],
            scope=list(raw.get("scope", [])),
            worker_commits=list(raw.get("worker_commits", [])),
            migration_files=list(raw.get("migration_files", [])),
            test_commands=list(raw.get("test_commands", [])),
            fixture_ids=list(raw.get("fixture_ids", [])),
            required_capabilities=list(raw.get("required_capabilities", [])),
            test_environment=raw.get("test_environment", "local-disposable"),
            stub_allowlist=list(raw.get("stub_allowlist", [])),
            catalog_tables=list(raw.get("catalog_tables", [])),
        )


@dataclasses.dataclass
class GateResult:
    name: str
    status: str  # passed | failed | blocked | skipped
    required: bool
    duration_sec: float
    details: str
    command: Optional[str] = None
    exit_code: Optional[int] = None
    log: Optional[str] = None
    covers: Optional[List[str]] = None


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _git(*args: str, check: bool = True) -> str:
    out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=check)
    return out.stdout.strip()


def _rev(ref: str) -> Optional[str]:
    try:
        return _git("rev-parse", "--verify", f"{ref}^{{commit}}")
    except subprocess.CalledProcessError:
        return None


def _base_for(base_ref: str, cand: Optional[str]) -> Optional[str]:
    """The delivery base as merged into the candidate: merge-base(base_ref, candidate).

    The delivery branch keeps moving; judging the candidate against its tip would count
    other people's newer commits as missing from the candidate.
    """
    base = _rev(base_ref)
    if not (base and cand):
        return base
    try:
        return _git("merge-base", base, cand)
    except subprocess.CalledProcessError:
        return base


def _is_ancestor(a: str, b: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=REPO).returncode == 0


def _changed_files(base: str, head: str) -> List[str]:
    out = _git("diff", "--name-only", "--diff-filter=ACMR", f"{base}...{head}")
    return [line for line in out.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def preflight(m: Manifest) -> List[GateResult]:
    res: List[GateResult] = []

    def add(name: str, ok: bool, details: str) -> None:
        res.append(GateResult(name, "passed" if ok else "failed", True, 0.0, details))

    cand = _rev(m.candidate_sha)
    base = _base_for(m.base_sha, cand)
    add("revisions_resolve", bool(cand and base), f"base={base} candidate={cand}")
    if not (cand and base):
        return res
    add("candidate_descends_from_base", _is_ancestor(base, cand), f"{base[:10]}..{cand[:10]}")

    missing = [c for c in m.worker_commits
               if not (_rev(c.split(":", 1)[-1]) and _is_ancestor(c.split(":", 1)[-1], cand))]
    add("worker_commits_merged", not missing,
        "all merged" if not missing else "not in candidate: " + ", ".join(missing))

    changed = _changed_files(base, cand)
    conflicts, stubs = [], []
    for path in changed:
        try:
            content = _git("show", f"{cand}:{path}")
        except subprocess.CalledProcessError:
            continue
        if CONFLICT_RE.search(content):
            conflicts.append(path)
        ext = os.path.splitext(path)[1]
        if not (path.startswith(PRODUCT_PREFIXES) and ext in STUB_PATTERNS):
            continue
        # Only lines this candidate added are judged; pre-existing code is not in scope.
        added = [ln[1:] for ln in _git("diff", "-U0", f"{base}...{cand}", "--", path).splitlines()
                 if ln.startswith("+") and not ln.startswith("+++")]
        for line in added:
            if any(p.search(line) for p in STUB_PATTERNS[ext]):
                if not any(path == a or path.startswith(a) for a in m.stub_allowlist):
                    stubs.append(f"{path}: {line.strip()[:80]}")
        if ext == ".py":
            added_text = "\n".join(added)
            for hit in PY_STUB_FN.finditer(added_text):
                stubs.append(f"{path}: stub function {hit.group(0).strip().splitlines()[0][:70]}")
    add("no_conflict_markers", not conflicts, ", ".join(conflicts) or f"{len(changed)} files")
    add("no_stubs_or_debug_output", not stubs,
        "clean" if not stubs else "; ".join(stubs[:25]) + (" …" if len(stubs) > 25 else ""))

    missing_scope = [p for p in m.scope if p not in changed]
    add("scope_files_changed", not missing_scope, ", ".join(missing_scope) or f"{len(m.scope)} files")

    # Migration ordering: every migration in the manifest exists, sorts after every
    # migration present at base, and each new migration has a fresh-install schema file.
    base_migs = set(_git("ls-tree", "--name-only", f"{base}:{MIGRATION_DIR}").splitlines())
    problems = []
    for mig in m.migration_files:
        name = os.path.basename(mig)
        if not _rev(cand) or subprocess.run(["git", "cat-file", "-e", f"{cand}:{mig}"],
                                            cwd=REPO).returncode != 0:
            problems.append(f"missing {mig}")
        newer = [b for b in base_migs if b.endswith(".sql") and not b.endswith("_rollback.sql")
                 and b > name]
        if newer:
            problems.append(f"{name} sorts before existing {sorted(newer)[-1]}")
    new_schema = [p for p in changed if p.startswith(SCHEMA_DIR + "/")]
    numbers = [os.path.basename(p).split("_", 1)[0] for p in
               _git("ls-tree", "--name-only", f"{cand}:{SCHEMA_DIR}").splitlines()]
    for p in new_schema:
        num = os.path.basename(p).split("_", 1)[0]
        if numbers.count(num) > 1 and p not in _git("ls-tree", "-r", "--name-only", base).splitlines():
            problems.append(f"schema number {num} reused by {p}")
    if m.migration_files and not new_schema:
        problems.append("migrations added without a matching fresh-install schema change")
    add("migration_ordering", not problems, "; ".join(problems) or f"{len(m.migration_files)} migrations")

    leaked = [f"{c.get('name')}:{k}" for c in m.test_commands for k, v in (c.get("env") or {}).items()
              if SECRET_RE.search(str(k)) or SECRET_RE.search(str(v))]
    add("no_secrets_in_manifest", not leaked, ", ".join(leaked) or "clean")
    return res


# ---------------------------------------------------------------------------
# Disposable Postgres
# ---------------------------------------------------------------------------


class DisposablePostgres:
    """A throwaway cluster on a unix socket inside the output directory."""

    def __init__(self, bin_dir: str, work_dir: str):
        self.bin = bin_dir
        self.data = os.path.join(work_dir, "pgdata")
        self.sock = os.path.join(work_dir, "pgsock")
        self.log = os.path.join(work_dir, "postgres.log")

    def _cmd(self, name: str) -> str:
        return os.path.join(self.bin, name)

    def start(self) -> None:
        shutil.rmtree(self.data, ignore_errors=True)
        os.makedirs(self.sock, exist_ok=True)
        subprocess.run([self._cmd("initdb"), "-D", self.data, "-U", "postgres", "-A", "trust"],
                       check=True, capture_output=True)
        subprocess.run([self._cmd("pg_ctl"), "-D", self.data, "-l", self.log, "-w", "-o",
                        f"-p {PG_PORT} -k {self.sock} -c listen_addresses='' -c fsync=off "
                        f"-c max_connections=60", "start"], check=True, capture_output=True)

    def stop(self) -> None:
        subprocess.run([self._cmd("pg_ctl"), "-D", self.data, "-m", "fast", "stop"],
                       capture_output=True)

    def dsn(self, db: str) -> str:
        return f"postgresql://postgres@/{db}?host={self.sock}&port={PG_PORT}"

    def psql(self, db: str, *, file: Optional[str] = None, sql: Optional[str] = None,
             text_in: Optional[str] = None) -> Tuple[int, str]:
        cmd = [self._cmd("psql"), "-h", self.sock, "-p", str(PG_PORT), "-U", "postgres", "-d", db,
               "-v", "ON_ERROR_STOP=1", "-q", "-X", "-A", "-t"]
        if file:
            cmd += ["-f", file]
        if sql:
            cmd += ["-c", sql]
        p = subprocess.run(cmd, capture_output=True, text=True, input=text_in)
        return p.returncode, (p.stdout + p.stderr)


CATALOG_SQL = r"""
SELECT 'col '||table_name||'.'||column_name||' '||data_type||' null='||is_nullable||' def='||coalesce(column_default,'')
  FROM information_schema.columns WHERE table_schema='public' AND table_name = ANY(:'tables'::text[])
UNION ALL
SELECT 'con '||conrelid::regclass||' '||pg_get_constraintdef(oid)
  FROM pg_constraint WHERE connamespace='public'::regnamespace AND conrelid::regclass::text = ANY(:'tables'::text[])
UNION ALL
SELECT 'idx '||tablename||' '||regexp_replace(indexdef, 'INDEX \S+ ON', 'INDEX ON')
  FROM pg_indexes WHERE schemaname='public' AND tablename = ANY(:'tables'::text[])
UNION ALL
SELECT 'pol '||tablename||' '||policyname||' '||cmd||' '||array_to_string(roles,',')||' '||coalesce(qual,'')||' '||coalesce(with_check,'')
  FROM pg_policies WHERE schemaname='public' AND tablename = ANY(:'tables'::text[])
UNION ALL
SELECT 'rls '||relname||' '||relrowsecurity FROM pg_class
  WHERE relnamespace='public'::regnamespace AND relname = ANY(:'tables'::text[])
UNION ALL
SELECT 'trg '||event_object_table||' '||trigger_name||' '||action_timing||' '||event_manipulation
  FROM information_schema.triggers WHERE trigger_schema='public' AND event_object_table = ANY(:'tables'::text[])
UNION ALL
SELECT 'grant '||table_name||' '||grantee||' '||privilege_type FROM information_schema.role_table_grants
  WHERE table_schema='public' AND table_name = ANY(:'tables'::text[]) AND grantee IN ('anon','authenticated','service_role')
UNION ALL
SELECT 'fn '||p.proname||'('||pg_get_function_identity_arguments(p.oid)||') secdef='||p.prosecdef
  FROM pg_proc p WHERE p.pronamespace='public'::regnamespace AND p.oid > (SELECT max(oid) FROM pg_proc WHERE pronamespace='pg_catalog'::regnamespace)
ORDER BY 1;
"""


def _schema_files_at(rev: str) -> List[str]:
    names = _git("ls-tree", "--name-only", f"{rev}:{SCHEMA_DIR}").splitlines()
    return sorted(n for n in names if n.endswith(".sql"))


def database_gates(m: Manifest, pg: DisposablePostgres, out_dir: str, cand: str, base: str) -> List[GateResult]:
    res: List[GateResult] = []
    shim = os.path.join(REPO, SHIM)
    log_path = os.path.join(out_dir, "db_apply.log")
    log = open(log_path, "w", encoding="utf-8")

    def apply(db: str, files: List[Tuple[str, str]]) -> Optional[str]:
        """files: (label, sql_text). Returns an error string or None."""
        for label, sql in files:
            rc, out = pg.psql(db, file="-", text_in=sql)
            log.write(f"--- {db}: {label} rc={rc}\n{out}\n")
            if rc != 0:
                errs = [ln for ln in out.splitlines() if "ERROR" in ln][:3]
                return f"{label}: {' | '.join(errs) or out[-300:]}"
        return None

    def read(path: str) -> str:
        with open(os.path.join(REPO, path), encoding="utf-8") as fh:
            return fh.read()

    # Fresh install: shim + every schema file of the candidate, in order.
    t0 = time.time()
    pg.psql("postgres", sql="CREATE DATABASE t42_fresh")
    err = apply("t42_fresh", [("shim", read(SHIM))] +
                [(n, read(f"{SCHEMA_DIR}/{n}")) for n in _schema_files_at(cand)])
    res.append(GateResult("db_fresh_install", "failed" if err else "passed", True, time.time() - t0,
                          err or f"{len(_schema_files_at(cand))} schema files applied", log=log_path,
                          covers=["schema"]))

    # Upgrade: schema as of base + existing-data fixture + new migrations in order.
    t0 = time.time()
    pg.psql("postgres", sql="CREATE DATABASE t42_upgrade")
    base_files = [(f"base:{n}", _git("show", f"{base}:{SCHEMA_DIR}/{n}")) for n in _schema_files_at(base)]
    steps = [("shim", read(SHIM))] + base_files
    if os.path.isfile(os.path.join(REPO, UPGRADE_FIXTURE)):
        steps.append(("existing-data fixture", read(UPGRADE_FIXTURE)))
    steps += [(mig, read(mig)) for mig in sorted(m.migration_files)]
    err = apply("t42_upgrade", steps)
    res.append(GateResult("db_upgrade_migration", "failed" if err else "passed", True, time.time() - t0,
                          err or f"base schema + fixture + {len(m.migration_files)} migrations",
                          log=log_path, covers=["schema", "migration"]))

    # Rollback files must apply cleanly after the upgrade, then re-upgrade must work.
    if not err:
        t0 = time.time()
        rollbacks = [p.replace(".sql", "_rollback.sql") for p in sorted(m.migration_files, reverse=True)]
        rollbacks = [p for p in rollbacks if os.path.isfile(os.path.join(REPO, p))]
        pg.psql("postgres", sql="CREATE DATABASE t42_rollback TEMPLATE t42_upgrade")
        rerr = apply("t42_rollback", [(p, read(p)) for p in rollbacks] +
                     [(f"reapply {mig}", read(mig)) for mig in sorted(m.migration_files)])
        res.append(GateResult("db_rollback_then_reapply", "failed" if rerr else "passed", True,
                              time.time() - t0, rerr or f"{len(rollbacks)} rollback files", log=log_path,
                              covers=["migration"]))

    # Catalog parity between fresh install and upgraded database.
    if all(r.status == "passed" for r in res) and m.catalog_tables:
        t0 = time.time()
        tables = "{" + ",".join(m.catalog_tables) + "}"
        dumps = {}
        for db in ("t42_fresh", "t42_upgrade"):
            sql = CATALOG_SQL.replace(":'tables'", "'" + tables + "'")
            if "role_permissions" in m.catalog_tables:
                # Role grants are data, not DDL: compare them too (sorted, so order is irrelevant).
                sql += ("SELECT 'grant-data '||role||' '||(SELECT string_agg(p, ',' ORDER BY p) "
                        "FROM jsonb_array_elements_text(permissions) p) FROM public.role_permissions;\n")
            rc, out = pg.psql(db, file="-", text_in=sql)
            dumps[db] = out.splitlines() if rc == 0 else [f"ERROR {out}"]
        fresh, upg = set(dumps["t42_fresh"]), set(dumps["t42_upgrade"])
        diff = sorted([f"fresh-only {x}" for x in fresh - upg] + [f"upgrade-only {x}" for x in upg - fresh])
        with open(os.path.join(out_dir, "catalog_diff.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(diff) + "\n")
        missing_tables = [t for t in m.catalog_tables if not any(l.startswith(f"rls {t} ") for l in fresh)]
        rls_off = [l for l in fresh if l.startswith("rls ") and l.endswith(" false")]
        ok = not diff and not missing_tables and not rls_off
        detail = (f"{len(fresh)} catalog entries identical; RLS on for {len(m.catalog_tables)} tables" if ok else
                  f"diff={len(diff)} missing_tables={missing_tables} rls_off={rls_off} (see catalog_diff.txt)")
        res.append(GateResult("db_catalog_parity_and_rls", "passed" if ok else "failed", True,
                              time.time() - t0, detail, covers=["schema", "rls"]))
    log.close()
    return res


# ---------------------------------------------------------------------------
# Final
# ---------------------------------------------------------------------------


def _run_command(spec: Dict[str, Any], out_dir: str, extra_env: Dict[str, str]) -> GateResult:
    name = spec["name"]
    required = bool(spec.get("required", True))
    cmd = spec.get("cmd")
    if not (isinstance(cmd, list) and all(isinstance(c, str) for c in cmd)):
        return GateResult(name, "failed", required, 0.0, "cmd must be a list of strings")
    cmd = [os.path.expandvars(os.path.expanduser(c)) for c in cmd]
    cwd = os.path.join(REPO, spec.get("cwd", "."))
    env = {**os.environ, **extra_env,
           **{k: os.path.expandvars(os.path.expanduser(str(v))) for k, v in (spec.get("env") or {}).items()}}
    log_path = os.path.join(out_dir, f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.log")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                           timeout=int(spec.get("timeout_sec", 1800)))
        rc, output = p.returncode, p.stdout + "\n" + p.stderr
    except FileNotFoundError as exc:
        return GateResult(name, "blocked", required, time.time() - t0, f"missing executable: {exc}",
                          command=" ".join(cmd), covers=spec.get("covers"))
    except subprocess.TimeoutExpired as exc:
        rc, output = -1, f"timeout after {exc.timeout}s\n{exc.stdout or ''}{exc.stderr or ''}"
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(output if isinstance(output, str) else output.decode("utf-8", "replace"))
    tail = [ln for ln in str(output).strip().splitlines() if ln.strip()][-3:]
    status = "passed" if rc == 0 else "failed"
    # A required test that did not run fails readiness: pytest exit 5 = nothing collected,
    # and with fail_on_skip any "N skipped" in the summary is a failure.
    skipped = re.search(r"\b(\d+) skipped\b", str(output))
    if status == "passed" and spec.get("fail_on_skip") and skipped and int(skipped.group(1)) > 0:
        status = "failed"
        tail.append(f"{skipped.group(1)} tests skipped (fail_on_skip)")
    return GateResult(name, status, required, time.time() - t0, " | ".join(tail)[:600],
                      command=" ".join(cmd), exit_code=rc, log=log_path, covers=spec.get("covers"))


VITEST_FAIL_RE = re.compile(r"^\s*FAIL\s+(\S+\.test\.tsx?)\b", re.MULTILINE)


def _judge_against_baseline(r: GateResult, spec: Dict[str, Any], out_dir: str, base: str) -> GateResult:
    """Accept a failed suite only when every failing file is a listed, proven baseline failure.

    A listed file must also fail when run at the base revision, in a throwaway sparse worktree
    the gate creates itself, so "pre-existing" is evidence rather than a claim. Anything else
    (a new failing file, or a listed file that passes at base) keeps the gate failed.
    """
    with open(r.log, encoding="utf-8", errors="replace") as fh:
        failed = {os.path.normpath(os.path.join(spec.get("cwd", "."), f)) for f in VITEST_FAIL_RE.findall(fh.read())}
    allowed = set(spec["baseline_failures"])
    unexpected = sorted(failed - allowed)
    if not failed or unexpected:
        r.details += f" | failing files not in baseline: {unexpected or 'unparsed output'}"
        return r
    wt = os.path.join(out_dir, "base_worktree")
    subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=REPO, capture_output=True)
    try:
        _git("worktree", "add", "--detach", "--no-checkout", wt, base)
        subprocess.run(["git", "sparse-checkout", "set", "--no-cone", *spec.get("baseline_sparse", ["/frontend/", "/tests/frontend/", "/features/"])],
                       cwd=wt, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-q"], cwd=wt, check=True, capture_output=True)
        for link in spec.get("baseline_links", []):
            dst = os.path.join(wt, link)
            if os.path.lexists(dst):
                os.remove(dst) if os.path.islink(dst) or os.path.isfile(dst) else shutil.rmtree(dst)
            os.symlink(os.path.join(REPO, spec.get("baseline_link_target", link)), dst)
        still_failing = []
        for f in sorted(failed):
            rel = os.path.relpath(f, spec.get("cwd", "."))
            p = subprocess.run([*[os.path.expandvars(c) for c in spec["baseline_cmd"]], rel],
                               cwd=os.path.join(wt, spec.get("cwd", ".")), capture_output=True, text=True,
                               timeout=900)
            if p.returncode != 0:
                still_failing.append(f)
        if sorted(still_failing) == sorted(failed):
            r.status = "passed"
            r.details = (f"only pre-existing failures, each re-proven failing at base {base[:10]}: "
                         f"{', '.join(sorted(failed))} | {r.details}")
        else:
            r.details += f" | listed baseline files that PASS at base: {sorted(set(failed) - set(still_failing))}"
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=REPO, capture_output=True)
    return r


def final(m: Manifest, out_dir: str) -> List[GateResult]:
    res: List[GateResult] = []
    cand = _rev(m.candidate_sha)
    base = _base_for(m.base_sha, cand)
    head = _rev("HEAD")
    dirty = _git("status", "--porcelain", "--untracked-files=no")
    ok = bool(cand) and cand == head and not dirty
    res.append(GateResult("candidate_frozen_and_clean", "passed" if ok else "failed", True, 0.0,
                          f"candidate={cand} HEAD={head} dirty={bool(dirty)}"))
    if not ok or not base:
        return res

    pg_bin = os.environ.get("TASK42_PG_BIN", "")
    if not os.path.isfile(os.path.join(pg_bin, "initdb")):
        res.append(GateResult("disposable_postgres", "blocked", True, 0.0,
                              "TASK42_PG_BIN must point at a directory containing initdb/pg_ctl/psql"))
        return res
    pg = DisposablePostgres(pg_bin, out_dir)
    try:
        pg.start()
        res.extend(database_gates(m, pg, out_dir, cand, base))
        env = {"TASK42_PG_DSN": pg.dsn("t42_fresh"), "TASK42_CANDIDATE_SHA": cand}
        for spec in m.test_commands:
            r = _run_command(spec, out_dir, env)
            if r.status == "failed" and spec.get("baseline_failures"):
                r = _judge_against_baseline(r, spec, out_dir, base)
            res.append(r)
            print(f"[gate] {r.status:7} {r.name} ({r.duration_sec:.0f}s)", flush=True)
    finally:
        pg.stop()
    return res


def write_report(results: List[GateResult], out_dir: str, mode: str, m: Manifest) -> int:
    os.makedirs(out_dir, exist_ok=True)
    required_bad = [r for r in results if r.required and r.status != "passed"]
    ready = not required_bad
    env = {
        "python": sys.version.split()[0],
        "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()
        if shutil.which("node") else None,
        "test_environment": m.test_environment,
    }
    payload = {
        "mode": mode, "generated_at": _now(), "ready": ready,
        "base_sha": _base_for(m.base_sha, _rev(m.candidate_sha)), "candidate_sha": _rev(m.candidate_sha),
        "environment": env, "results": [dataclasses.asdict(r) for r in results],
    }
    with open(os.path.join(out_dir, f"task42_gate_{mode}.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    lines = [f"# TASK-42 gate — {mode}", "",
             f"- candidate: `{payload['candidate_sha']}`  base: `{payload['base_sha']}`",
             f"- generated: {payload['generated_at']}  env: python {env['python']}, node {env['node']}",
             f"- **verdict: {'READY' if ready else 'NOT READY'}**", "",
             "| gate | status | required | seconds | exit | details |", "|---|---|---|---|---|---|"]
    for r in results:
        details = r.details.replace("|", "\\|").replace("\n", " ")[:300]
        lines.append(f"| {r.name} | {r.status} | {'yes' if r.required else 'no'} | "
                     f"{r.duration_sec:.0f} | {'' if r.exit_code is None else r.exit_code} | {details} |")
    with open(os.path.join(out_dir, f"task42_gate_{mode}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    if ready:
        return 0
    return 1 if mode == "preflight" else (3 if any(r.status == "blocked" for r in required_bad) else 2)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    p1 = sub.add_parser("preflight")
    p1.add_argument("--manifest", required=True)
    p1.add_argument("--output-dir", default=None)
    p2 = sub.add_parser("final")
    p2.add_argument("--manifest", required=True)
    p2.add_argument("--output-dir", required=True)
    args = ap.parse_args(argv)
    m = Manifest.load(args.manifest)
    out_dir = os.path.abspath(args.output_dir or os.path.join("/tmp", "task42_preflight"))
    if out_dir == REPO or out_dir.startswith(REPO + os.sep):
        print("output dir must be outside the repository (CONTRACTS §23)", file=sys.stderr)
        return 3
    os.makedirs(out_dir, exist_ok=True)
    results = preflight(m) if args.mode == "preflight" else final(m, out_dir)
    return write_report(results, out_dir, args.mode, m)


if __name__ == "__main__":
    sys.exit(main())
