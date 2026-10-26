"""
SQL migration listing and runner for step 4 of Platform update (TASK-95).

Pending = a file in ``setup/db/migrations`` (rollback files excluded, filename order — the same order
``apply_schema.sh`` uses) that has no row in ``public.applied_migrations``. The table is platform-global
(created by migration 20261014a_applied_migrations.sql); there is no ``team_id`` because the schema
belongs to the install, not to a team.

Nothing runs without an explicit confirmation: ``apply`` needs ``confirm=True`` and the exact ordered list
of file names the operator saw. A file is executed as a whole (they carry their own BEGIN/COMMIT) and
recorded right after; the first error stops the run.

Database access is injected (``Backend``) so the logic is testable; ``PsycopgBackend`` is the real one and
needs a DSN: the Platform update setting ``db_dsn``, else ``PLATFORM_UPDATE_DB_URI`` | ``SUPABASE_DB_URI`` | ``DATABASE_URL``
(``settings.get``).
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol

from . import settings
from .runs import PlatformUpdateError

TRACKER_FILE = '20261014a_applied_migrations.sql'
DEFAULT_DIR = Path(__file__).resolve().parents[4] / 'setup' / 'db' / 'migrations'


class MigrationError(PlatformUpdateError):
    pass


class Backend(Protocol):
    def read_applied(self) -> Optional[List[str]]:
        """Recorded file names, or None when the tracker table does not exist."""

    def execute_file(self, sql: str) -> None: ...

    def record(self, filename: str, applied_by: str, method: str) -> None: ...

    def unrecord(self, filename: str) -> None: ...

    @property
    def can_execute(self) -> bool: ...


def list_files(directory: Path = DEFAULT_DIR) -> List[str]:
    directory = Path(directory)
    if not directory.is_dir():
        raise MigrationError(f'migration folder not found: {directory}')
    return sorted(p.name for p in directory.glob('*.sql') if not p.name.endswith('_rollback.sql'))


def status(backend: Backend, directory: Path = DEFAULT_DIR) -> Dict:
    files = list_files(directory)
    applied = backend.read_applied()
    if applied is None:
        return {'tracker': 'missing', 'tracker_file': TRACKER_FILE, 'total': len(files), 'applied': 0,
                'pending': [], 'files': files, 'can_apply': backend.can_execute}
    recorded = set(applied)
    return {'tracker': 'ready', 'tracker_file': TRACKER_FILE, 'total': len(files),
            'applied': len([f for f in files if f in recorded]),
            'pending': [f for f in files if f not in recorded],
            'files': files, 'can_apply': backend.can_execute}


def install_tracker(backend: Backend, applied_by: str, directory: Path = DEFAULT_DIR,
                    log: Callable[[str], None] = lambda _m: None) -> None:
    if backend.read_applied() is not None:
        raise MigrationError('the tracker already exists')
    if not backend.can_execute:
        raise MigrationError('no database connection string configured for running migrations')
    sql = (Path(directory) / TRACKER_FILE).read_text(encoding='utf-8')
    log(f'Creating the migration tracker ({TRACKER_FILE})')
    backend.execute_file(sql)
    backend.record(TRACKER_FILE, applied_by, 'page')


def baseline(backend: Backend, up_to: str, applied_by: str, confirm: bool, directory: Path = DEFAULT_DIR,
             log: Callable[[str], None] = lambda _m: None) -> List[str]:
    """Record every file up to and including ``up_to`` as already applied, WITHOUT running it."""
    if not confirm:
        raise MigrationError('confirmation required')
    if not backend.can_execute:
        raise MigrationError('no database connection string configured for running migrations')
    state = status(backend, directory)
    if state['tracker'] != 'ready':
        raise MigrationError('create the tracker first')
    if up_to not in state['files']:
        raise MigrationError(f'unknown migration: {up_to}')
    marked = [f for f in state['pending'] if f <= up_to]
    for name in marked:
        backend.record(name, applied_by, 'baseline')
    log(f'Marked {len(marked)} migrations as already applied (up to {up_to}), none executed')
    return marked


def apply(backend: Backend, filenames: List[str], confirm: bool, applied_by: str,
          directory: Path = DEFAULT_DIR, log: Callable[[str], None] = lambda _m: None) -> List[str]:
    """Run ``filenames`` in order. They must be exactly the first N pending files. Returns the applied names."""
    if confirm is not True:
        raise MigrationError('confirmation required')
    if not filenames:
        raise MigrationError('no migrations selected')
    if not backend.can_execute:
        raise MigrationError('no database connection string configured for running migrations')
    state = status(backend, directory)
    if state['tracker'] != 'ready':
        raise MigrationError('create the tracker first')
    if filenames != state['pending'][:len(filenames)]:
        raise MigrationError('the list does not match the pending migrations (reload the page); '
                             'migrations are applied in order, none can be skipped')
    done: List[str] = []
    for name in filenames:
        sql = (Path(directory) / name).read_text(encoding='utf-8')
        log(f'Applying {name}')
        try:
            backend.execute_file(sql)
        except Exception as exc:  # the file's own transaction rolled back; stop here
            log(f'FAILED {name}: {exc}')
            raise MigrationError(f'{name} failed: {exc}. Applied before it: {len(done)}')
        backend.record(name, applied_by, 'page')
        done.append(name)
    return done


class PsycopgBackend:
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or settings.get('db_dsn')

    @property
    def can_execute(self) -> bool:
        return bool(self.dsn)

    def _connect(self):
        import psycopg2
        return psycopg2.connect(self.dsn, connect_timeout=10)

    def read_applied(self) -> Optional[List[str]]:
        if self.dsn:
            conn = self._connect()
            try:
                with conn, conn.cursor() as cur:
                    cur.execute("SELECT to_regclass('public.applied_migrations')")
                    if cur.fetchone()[0] is None:
                        return None
                    cur.execute('SELECT filename FROM public.applied_migrations')
                    return [r[0] for r in cur.fetchall()]
            finally:
                conn.close()
        from shared.src.lib.utils.supabase_utils import get_supabase_client
        try:
            rows = get_supabase_client().table('applied_migrations').select('filename').execute().data
        except Exception:
            return None
        return [r['filename'] for r in rows]

    def execute_file(self, sql: str) -> None:
        conn = self._connect()
        try:
            conn.autocommit = True  # the file carries its own BEGIN/COMMIT
            with conn.cursor() as cur:
                cur.execute(sql)
        finally:
            conn.close()

    def record(self, filename: str, applied_by: str, method: str) -> None:
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute('INSERT INTO public.applied_migrations (filename, applied_by, method) '
                            'VALUES (%s, %s, %s) ON CONFLICT (filename) DO NOTHING',
                            (filename, applied_by, method))
        finally:
            conn.close()

    def unrecord(self, filename: str) -> None:
        """TASK-128 G12: forget a migration whose ``_rollback.sql`` ran, so it is pending again."""
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute('DELETE FROM public.applied_migrations WHERE filename = %s', (filename,))
        finally:
            conn.close()
