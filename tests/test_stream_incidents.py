"""BUG-0960: a stuck stream keeps ONE open incident across host restarts, and recovery resolves it."""
from shared.src.lib.database import system_metrics_db as smd


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, op=None, payload=None):
        self.db, self.op, self.payload, self.filters = db, op, payload, {}

    def select(self, *a, **k):
        return _Query(self.db, 'select')

    def insert(self, payload):
        return _Query(self.db, 'insert', payload)

    def update(self, payload):
        return _Query(self.db, 'update', payload)

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def in_(self, col, vals):
        self.filters[col] = tuple(vals)
        return self

    def execute(self):
        rows = self.db.rows
        if self.op == 'insert':
            rows.append({**self.payload, 'incident_id': len(rows) + 1})
            return _Result([rows[-1]])
        match = [r for r in rows if all(r.get(c) in v if isinstance(v, tuple) else r.get(c) == v
                                        for c, v in self.filters.items())]
        if self.op == 'update':
            for r in match:
                r.update(self.payload)
        return _Result(match)


class _DB:
    def __init__(self):
        self.rows = []

    def table(self, name):
        assert name == 'system_incident'
        return _Query(self)


def _run(db, monkeypatch, ffmpeg, monitor='off'):
    monkeypatch.setattr(smd, 'get_supabase', lambda: db)
    return smd.process_device_incidents('Tello', 'capture2', ffmpeg, monitor, 'vpt-pi4')


def test_restart_does_not_duplicate_and_recovery_resolves(monkeypatch):
    db = _DB()
    monkeypatch.setattr(smd, '_open_incidents', {})
    assert _run(db, monkeypatch, 'stuck')['incidents_created'] == 1
    assert _run(db, monkeypatch, 'stuck')['incidents_created'] == 0

    monkeypatch.setattr(smd, '_open_incidents', {})  # host process restarted
    assert _run(db, monkeypatch, 'stuck')['incidents_created'] == 0
    assert len(db.rows) == 1

    monkeypatch.setattr(smd, '_open_incidents', {})  # restarted again, stream recovered
    assert _run(db, monkeypatch, 'active')['incidents_resolved'] == 1
    assert db.rows[0]['status'] == 'resolved'


def test_same_capture_folder_on_another_host_is_separate(monkeypatch):
    db = _DB()
    monkeypatch.setattr(smd, '_open_incidents', {})
    _run(db, monkeypatch, 'stopped')
    monkeypatch.setattr(smd, 'get_supabase', lambda: db)
    smd.process_device_incidents('Other', 'capture2', 'active', 'off', 'host-clone-1')
    assert db.rows[0]['status'] == 'open'


def test_tello_opens_no_incident(monkeypatch):
    db = _DB()
    monkeypatch.setattr(smd, '_open_incidents', {})
    monkeypatch.setattr(smd, 'get_supabase', lambda: db)
    smd.process_device_incidents('Tello-F014A0', 'capture6', 'stuck', 'stuck', 'vpt-pi4', 'tello')
    assert db.rows == []


def test_tool_counts_tello_as_idle_and_tables_failures(monkeypatch):
    from backend_server.src.mcp.tools.analysis_tools import AnalysisTools
    rows = [
        {'host_name': 'vpt-pi4', 'device_name': 'Tello-F014A0', 'device_model': 'tello', 'capture_folder': 'capture6',
         'ffmpeg_status': 'stuck', 'monitor_status': 'stuck', 'state': 'idle', 'failing_since': None},
        {'host_name': 'vpt-wise1', 'device_name': 'vpt-wise1_Host', 'device_model': 'host_vnc',
         'capture_folder': 'capture1', 'ffmpeg_status': 'stopped', 'monitor_status': 'off', 'state': 'failing',
         'failing_since': '2026-10-21T16:57:23+00:00'},
        {'host_name': 'vpt-pi1', 'device_name': 'stb3', 'device_model': 'stb', 'capture_folder': 'capture3',
         'ffmpeg_status': 'active', 'monitor_status': 'active', 'state': 'running', 'failing_since': None},
    ]
    monkeypatch.setattr(smd, 'get_stream_status', lambda host_name=None: rows)
    out = AnalysisTools().get_stream_status({'only_failing': True})
    text = out['content'][0]['text']
    assert text.startswith('**Streams:** 1 running · 1 failing · 1 idle (need pairing)')
    assert '| vpt-wise1_Host | vpt-wise1 | video stopped | ' in text and 'days |' in text
    assert 'Idle, not counted (video only while paired): Tello-F014A0 (vpt-pi4)' in text
    assert 'stb3' not in text and [s['device_name'] for s in out['streams']] == ['vpt-wise1_Host', 'Tello-F014A0']
