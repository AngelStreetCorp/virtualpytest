"""Host disk cleanup ("Fix now" on a disk problem): the file rules, and the server route's refusals."""
import os
import time
from unittest.mock import patch

import pytest
from flask import Flask

from shared.src.lib.utils import host_disk_cleanup as hdc

pytestmark = pytest.mark.unit

NOW = time.time()


def _file(path, age_s, size=100):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'x' * size)
    os.utime(path, (NOW - age_s, NOW - age_s))
    return path


@pytest.fixture
def cap(tmp_path):
    base = tmp_path / 'capture1'
    keep = [
        _file(f'{base}/captures/capture_new.jpg', 60),                         # live
        _file(f'{base}/captures/capture_inuse.jpg', 300),                      # < min age
        _file(f'{base}/segments/20/chunk_10min_1.mp4', 10 * 3600),             # inside the 24 h buffer
        _file(f'{base}/temp/1min_slot_3.mp4', 90 * 86400),                     # rotating slot: never matched
        _file(f'{base}/active_captures.conf', 90 * 86400),
        _file(f'{base}/.env', 90 * 86400),
        _file(f'{base}/reports/new.html', 86400),
    ]
    old = [
        _file(f'{base}/captures/capture_old.jpg', 2 * 3600, 1000),
        _file(f'{base}/thumbnails/capture_old_thumbnail.jpg', 2 * 3600, 10),
        _file(f'{base}/captures/05/capture_x.jpg', 30 * 3600, 500),
        _file(f'{base}/segments/05/chunk_10min_2.mp4', 30 * 3600, 5000),
        _file(f'{base}/reports/run1/a.html', 5 * 86400, 200),
        _file(f'{base}/original_with_crop_1.png', 5 * 86400, 300),
    ]
    return base, keep, old


def test_dry_run_reports_figure_and_deletes_nothing(cap):
    base, keep, old = cap
    res = hdc.run_cleanup([str(base)], dry_run=True, now=NOW)
    assert res['dry_run'] and res['disk_after'] is None
    assert res['files'] == len(old) and res['freed_bytes'] == 1000 + 10 + 500 + 5000 + 200 + 300
    assert all(os.path.exists(p) for p in keep + old)


def test_real_run_deletes_only_expired(cap):
    base, keep, old = cap
    res = hdc.run_cleanup([str(base)], dry_run=False, now=NOW)
    assert res['files'] == len(old) and res['disk_after'] is not None
    assert not any(os.path.exists(p) for p in old)
    assert all(os.path.exists(p) for p in keep)


def test_symlink_is_never_followed(cap, tmp_path):
    base, _, _ = cap
    outside = _file(str(tmp_path / 'outside.jpg'), 99 * 86400)
    os.symlink(outside, base / 'captures' / 'capture_link.jpg')
    hdc.run_cleanup([str(base)], dry_run=False, now=NOW)
    assert os.path.exists(outside)


# --- server route ---------------------------------------------------------------------------

def _route():
    try:
        from backend_server.src.routes import server_system_routes as r
    except Exception as e:  # backend deps missing here
        pytest.skip(f'routes not importable: {e}')
    fn = r.host_disk_cleanup_proxy
    while hasattr(fn, '__wrapped__'):
        fn = fn.__wrapped__
    return r, fn


def _call(body, locks=None, host=None, team='t1'):
    r, fn = _route()
    host = {'host_name': 'h1', 'team_id': 'team-a'} if host is None else host
    app = Flask(__name__)
    with app.test_request_context('/server/system/hostDiskCleanup', method='POST', json=body, headers={'X-Team-ID': team}):
        from flask import request
        request.user_id = 'user-1'
        with patch.object(r, 'get_host_manager') as hm, \
                patch('backend_server.src.lib.utils.lock_utils.get_all_locked_devices', return_value=locks or {}), \
                patch('shared.src.lib.utils.build_url_utils.call_host', return_value=({'success': True, 'freed_bytes': 7}, 200)) as ch:
            hm.return_value.get_host.return_value = host
            resp = fn()
            resp, code = resp if isinstance(resp, tuple) else (resp, 200)
            return code, resp.get_json(), ch


def test_route_requires_host_name():
    assert _call({})[0] == 400


def test_route_dry_run_is_default_and_ignores_locks():
    code, body, ch = _call({'host_name': 'h1'}, locks={'h1:d': {'host_name': 'h1', 'owner_user_id': 'other'}}, team='team-a')
    assert code == 200 and ch.call_args.kwargs['data'] == {'dry_run': True}


def test_route_refuses_real_run_on_host_held_by_someone_else():
    code, body, ch = _call({'host_name': 'h1', 'dry_run': False}, locks={'h1:d': {'host_name': 'h1', 'owner_user_id': 'other'}}, team='team-a')
    assert code == 409 and body['errorType'] == 'host_busy' and not ch.called


def test_route_lets_the_holder_clean_its_own_host():
    code, _, ch = _call({'host_name': 'h1', 'dry_run': False}, locks={'h1:d': {'host_name': 'h1', 'owner_user_id': 'user-1'}}, team='team-a')
    assert code == 200 and ch.call_args.kwargs['data'] == {'dry_run': False}


def test_route_hides_a_host_of_another_team():
    assert _call({'host_name': 'h1'}, team='team-b')[0] == 404
