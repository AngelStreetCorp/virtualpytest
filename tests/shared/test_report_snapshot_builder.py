"""Unit tests for the report snapshot builder (TASK-49). Storage is faked; runs offline."""

import os
import re
from pathlib import Path

import pytest

from shared.src.lib.utils import report_snapshot_builder as builder

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parent / 'fixtures' / 'synthetic_report.html'
REPORT_KEY = 'script-reports/model_x/run_1/report.html'


class FakeStorage:
    """Just enough of CloudflareUtils for the builder."""

    bucket_name = 'testbucket'

    def __init__(self, report_html=None, sizes=None, default_size=1000):
        self.objects = {}
        if report_html is not None:
            self.objects[REPORT_KEY] = report_html.encode('utf-8')
        self.sizes = sizes or {}
        self.default_size = default_size
        self.copied = []
        self.uploaded = {}
        self.deleted_prefixes = []

    def resolve_remote_path(self, value):
        return value.lstrip('/')

    def download_file(self, remote_path, local_path):
        if remote_path not in self.objects:
            return {'success': False, 'error': f'File not found in R2: {remote_path}'}
        with open(local_path, 'wb') as f:
            f.write(self.objects[remote_path])
        return {'success': True}

    def head_file(self, key):
        if key in self.sizes and self.sizes[key] is None:
            return {'success': False, 'error': 'File not found'}
        return {'success': True, 'content_length': self.sizes.get(key, self.default_size)}

    def copy_file(self, src, dst):
        self.copied.append((src, dst))
        return {'success': True}

    def upload_files(self, mappings, **kwargs):
        for m in mappings:
            with open(m['local_path'], 'rb') as f:
                self.uploaded[m['remote_path']] = (f.read(), m.get('content_type'))
        return {'success': True, 'failed_uploads': []}

    def delete_prefix(self, prefix):
        self.deleted_prefixes.append(prefix)
        return {'success': True, 'deleted': 1}


@pytest.fixture(autouse=True)
def storage_env(monkeypatch):
    monkeypatch.setenv('MINIO_PUBLIC_URL', 'https://public.example.com')
    monkeypatch.setenv('MINIO_ENDPOINT', 'https://storage.example.com')
    for name in ('FRONTEND_URL', 'SERVER_URL', 'BACKEND_SERVER_URL', 'PUBLIC_URL', 'VITE_SERVER_URL',
                 'MINIO_PRESIGN_ENDPOINT', 'CLOUDFLARE_R2_PUBLIC_URL', 'CLOUDFLARE_R2_ENDPOINT'):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fake(monkeypatch):
    storage = FakeStorage(FIXTURE.read_text(encoding='utf-8'))
    monkeypatch.setattr(builder, 'get_cloudflare_utils', lambda: storage)
    return storage


def _build(include_video=True, **kw):
    return builder.build_snapshot(REPORT_KEY, 'snap-1', include_video, 'Snapshot banner <b>x</b>',
                                  platform_hosts=['platform.example.com'], **kw)


def _page(fake):
    return fake.uploaded['shared-snapshots/snap-1/report.html'][0].decode('utf-8')


def test_fixture_report_leaks_nothing(fake):
    result = _build()
    assert result['success'], result
    assert result['storage_prefix'] == 'shared-snapshots/snap-1/'
    page = _page(fake)

    assert page.count('X-Amz-') == 0
    assert page.count('AKIAEXAMPLE') == 0
    assert page.count('/host/') == 0
    assert page.count('script-logs/') == 0
    assert page.count('script-reports/') == 0
    assert 'storage.example.com' not in page
    assert 'platform.example.com' not in page
    assert '/builder/' not in page
    assert 'hls.js' not in page

    # Every reference to a stored object is a relative assets/ link.
    refs = re.findall(r'(?:src|poster)="([^"]+)"', page)
    for ref in refs:
        assert ref.startswith('assets/') or ref.startswith('#'), ref
    assert re.search(r"url\('assets/\d+\.jpg'\)", page)
    for asset in result['assets']:
        assert re.fullmatch(r'\d+\.[a-z0-9]{1,5}', asset['name'])
        assert f'assets/{asset["name"]}' in page

    # Same object referenced several times = one asset.
    sources = [a['source_key'] for a in result['assets']]
    assert len(sources) == len(set(sources))

    # Third-party link kept; removed links keep their text with a label.
    assert 'https://docs.example.org/guide' in page
    assert 'Execution Logs' in page and 'not included in the snapshot' in page
    assert 'View Detailed Comparison Report' in page

    # Banner is escaped and first in the body.
    assert '<body><div id="snapshot-banner"' in page
    assert 'Snapshot banner &lt;b&gt;x&lt;/b&gt;' in page

    # Objects written under the prefix with the right type; manifest present.
    assert fake.uploaded['shared-snapshots/snap-1/report.html'][1] == 'text/html; charset=utf-8'
    assert 'shared-snapshots/snap-1/manifest.json' in fake.uploaded
    for src, dst in fake.copied:
        assert dst.startswith('shared-snapshots/snap-1/assets/')
        assert not src.startswith('script-logs/')
    assert result['size_bytes'] > 0


def test_logs_and_subreports_never_copied(fake):
    _build()
    copied_sources = [src for src, _ in fake.copied]
    assert all(not s.startswith('script-logs/') for s in copied_sources)
    assert not any(s.endswith('report.html') and s.startswith(('zap-reports/', 'kpi_measurement/'))
                   for s in copied_sources)


def test_video_included_by_default(fake):
    result = _build(include_video=True)
    assert any(a['source_key'].endswith('video.mp4') for a in result['assets'])
    assert re.search(r'<source src="assets/\d+\.mp4"', _page(fake))


def test_video_excluded(fake):
    result = _build(include_video=False)
    assert result['success']
    assert not any(a['source_key'].endswith('video.mp4') for a in result['assets'])
    assert all(not src.endswith('.mp4') for src, _ in fake.copied)
    page = _page(fake)
    assert 'video.mp4' not in page
    assert 'Video not included in this snapshot' in page
    assert 'openVideoModal' not in page
    assert page.count('X-Amz-') == 0


def test_too_large_before_any_copy(monkeypatch):
    storage = FakeStorage(FIXTURE.read_text(encoding='utf-8'), default_size=60 * 1024 * 1024)
    monkeypatch.setattr(builder, 'get_cloudflare_utils', lambda: storage)
    result = _build()
    assert not result['success']
    assert result['error_code'] == 'too_large'
    assert storage.copied == []
    assert storage.uploaded == {}


def test_report_gone(monkeypatch):
    storage = FakeStorage(None)
    monkeypatch.setattr(builder, 'get_cloudflare_utils', lambda: storage)
    result = _build()
    assert not result['success']
    assert result['error_code'] == 'report_gone'


def test_missing_asset_is_neutralised_not_fatal(monkeypatch):
    sizes = {'script-reports/model_x/run_1/step1.jpg': None}
    storage = FakeStorage(FIXTURE.read_text(encoding='utf-8'), sizes=sizes)
    monkeypatch.setattr(builder, 'get_cloudflare_utils', lambda: storage)
    result = _build()
    assert result['success']
    assert 'step1.jpg' not in _page(storage)
    assert all(a['source_key'] != 'script-reports/model_x/run_1/step1.jpg' for a in result['assets'])


def test_copy_failure_cleans_up(monkeypatch):
    storage = FakeStorage(FIXTURE.read_text(encoding='utf-8'))
    storage.copy_file = lambda s, d: {'success': False, 'error': 'boom'}
    monkeypatch.setattr(builder, 'get_cloudflare_utils', lambda: storage)
    result = _build()
    assert result['error_code'] == 'storage_error'
    assert storage.deleted_prefixes == ['shared-snapshots/snap-1/']


def test_purge_snapshot_only_inside_shared_prefix(monkeypatch):
    storage = FakeStorage(None)
    monkeypatch.setattr(builder, 'get_cloudflare_utils', lambda: storage)
    assert builder.purge_snapshot('shared-snapshots/abc/') is True
    assert storage.deleted_prefixes == ['shared-snapshots/abc/']
    for bad in ('', 'script-reports/', 'shared-snapshots/', 'shared-snapshots/../script-reports/'):
        assert builder.purge_snapshot(bad) is False
    assert storage.deleted_prefixes == ['shared-snapshots/abc/']


def test_only_images_and_video_are_copied(monkeypatch):
    """A nested report page (or SVG/JS) is never copied: assets are served from a presigned URL that
    can share the app's origin, outside the report's sandbox."""
    page = (
        '<html><body>'
        '<a href="https://storage.example.com/virtualpytest/script-reports/model_x/run_1/game_report.html">Game report</a>'
        '<img src="https://storage.example.com/virtualpytest/script-reports/model_x/run_1/icon.svg">'
        '<script src="https://storage.example.com/virtualpytest/script-reports/model_x/run_1/x.js"></script>'
        '<img src="https://storage.example.com/virtualpytest/script-reports/model_x/run_1/shot.png">'
        '</body></html>'
    )
    storage = FakeStorage(page)
    monkeypatch.setattr(builder, 'get_cloudflare_utils', lambda: storage)
    result = _build()
    assert result['success'], result
    assert [src.rsplit('/', 1)[-1] for src, _ in storage.copied] == ['shot.png']
    out = _page(storage)
    assert 'game_report.html' not in out and 'icon.svg' not in out and 'x.js' not in out
    assert 'Game report' in out


def test_storage_key_with_a_host_folder_is_copied_but_host_paths_are_dropped(monkeypatch):
    """script-screenshots/host/... is a storage folder, not a gated /host/<name>/ path."""
    page = (
        '<html><body>'
        '<img src="https://storage.example.com/virtualpytest/script-screenshots/host/capture_1.jpg?X-Amz-Signature=f">'
        '<a href="/host/pi9/stream/capture1/report.html">Failure report</a>'
        '<a href="https://platform.example.com/host/pi9/stream/x.jpg">Live</a>'
        '</body></html>'
    )
    storage = FakeStorage(page)
    monkeypatch.setattr(builder, 'get_cloudflare_utils', lambda: storage)
    assert _build()['success']
    assert [src for src, _ in storage.copied] == ['script-screenshots/host/capture_1.jpg']
    out = _page(storage)
    assert '/host/' not in out and 'Failure report' in out and 'Live' in out


def test_storage_link_on_the_platform_host_is_kept_and_copied(monkeypatch):
    """One public domain can serve both the app and presigned storage (MINIO_PRESIGN_ENDPOINT)."""
    monkeypatch.setenv('MINIO_PRESIGN_ENDPOINT', 'https://platform.example.com')
    page = ('<html><body><a href="https://platform.example.com/virtualpytest/script-reports/model_x/run_1/mosaic.jpg'
            '?X-Amz-Signature=f&amp;X-Amz-Credential=AKIAEXAMPLE">Click here</a>'
            '<a href="https://platform.example.com/test-results/reports">Back to VPT</a></body></html>')
    storage = FakeStorage(page)
    monkeypatch.setattr(builder, 'get_cloudflare_utils', lambda: storage)
    assert _build()['success']
    out = _page(storage)
    assert [src for src, _ in storage.copied] == ['script-reports/model_x/run_1/mosaic.jpg']
    assert 'href="assets/1.jpg"' in out
    assert 'snapshot-removed-link">Back to VPT' in out and '/test-results/' not in out


# ---------------------------------------------------------------------------
# Security review (2026-10-04): what may be copied, and what is masked
# ---------------------------------------------------------------------------

def _classifier(include_video=True, folder='script-reports/model_x/run_1/'):
    return builder._Classifier('virtualpytest', ['platform.example.com'], include_video, folder)


def _would_copy(html, **kw):
    _, names = builder.rewrite_report_html(html, _classifier(**kw))
    return list(names)


def test_arbitrary_bucket_objects_named_in_a_report_are_not_copied():
    html = '''<html><body>
<div class="msg">checked navigation/android_mobile/Home.jpg and reference-images/7f0c/logo.png</div>
<div class="msg">https://evil.example/virtualpytest/shared-snapshots/11111111-2222/assets/1.png</div>
<div class="msg">https://evil.example/virtualpytest/captures/other-team-device/capture_1.jpg</div>
<img src="https://evil.example/virtualpytest/captures/other-team-device/capture_2.jpg">
<img src="navigation/android_mobile/Home.jpg">
<img src="https://storage.example.com/virtualpytest/shared-snapshots/1111/assets/2.png">
<img src="https://storage.example.com/virtualpytest/captures/dev/capture_3.jpg?X-Amz-Signature=f">
<img src="https://storage.example.com/virtualpytest/script-reports/other_model/other_run/shot.jpg?X-Amz-Signature=f">
<img src="https://storage.example.com/virtualpytest/script-reports/model_x/run_1/../../other_model/x/shot.jpg">
<img src="script-reports/model_x/run_1/screenshot.jpg">
</body></html>'''
    out, names = builder.rewrite_report_html(html, _classifier())
    assert list(names) == ['script-reports/model_x/run_1/screenshot.jpg']
    # Storage-host and bare references are neutralised; the plain-text mentions on a foreign host
    # are just outside links (nothing of ours), never copied.
    assert 'storage.example.com' not in out and '<img src="navigation/' not in out
    assert 'other_model' not in out and 'X-Amz-' not in out


def test_keys_in_plain_text_or_script_are_not_copied_even_when_allowed():
    html = '''<html><head><style>.a{background:url('script-reports/model_x/run_1/mosaic.jpg')}</style></head><body>
<p>see script-reports/model_x/run_1/typed.jpg and https://storage.example.com/virtualpytest/script-screenshots/h/typed.jpg</p>
<script>var u = "https://storage.example.com/virtualpytest/script-screenshots/h/js.jpg?X-Amz-Signature=f"; if (a<b && c>d) {}</script>
<!-- script-reports/model_x/run_1/comment.jpg -->
<img src="script-reports/model_x/run_1/real.jpg">
</body></html>'''
    assert _would_copy(html) == ['script-reports/model_x/run_1/mosaic.jpg',
                                 'script-reports/model_x/run_1/real.jpg']


def test_unknown_host_with_bucket_in_path_is_not_ours():
    html = '<img src="https://evil.example/virtualpytest/script-screenshots/h/a.jpg">'
    assert _would_copy(html) == []
    html = '<img src="https://storage.example.com/virtualpytest/script-screenshots/h/a.jpg">'
    assert _would_copy(html) == ['script-screenshots/h/a.jpg']


def test_real_report_references_still_copied_including_onclick_json():
    shot = ('https://storage.example.com/virtualpytest/script-screenshots/host/capture_000019514.jpg'
            '?X-Amz-Algorithm=AWS4-HMAC-SHA256&amp;X-Amz-Credential=AKIAEXAMPLE&amp;X-Amz-Signature=f')
    onclick = ("openScreenshotModal('{&quot;label&quot;: &quot;step 1&quot;, &quot;url&quot;: &quot;"
               + shot + "&quot;, &quot;n&quot;: 1}')")
    html = (f'<img src="{shot}" onclick="{onclick}">'
            '<img src="https://storage.example.com/virtualpytest/reference-images/uuid-1/logo.jpg?X-Amz-Signature=f">'
            '<img src="https://storage.example.com/virtualpytest/script-reports/model_x/run_1/mosaic.jpg?X-Amz-Signature=f">'
            '<source src="https://storage.example.com/virtualpytest/script-reports/model_x/run_1/video.mp4?X-Amz-Signature=f">')
    out, names = builder.rewrite_report_html(html, _classifier())
    assert list(names) == [
        'script-screenshots/host/capture_000019514.jpg', 'reference-images/uuid-1/logo.jpg',
        'script-reports/model_x/run_1/mosaic.jpg', 'script-reports/model_x/run_1/video.mp4']
    assert 'X-Amz-' not in out and 'storage.example.com' not in out
    # The onclick JSON stays well formed: the quotes around the rewritten url survive.
    assert '&quot;url&quot;: &quot;assets/1.jpg&quot;, &quot;n&quot;: 1}' in out


def test_masks_typed_values_and_strips_url_query():
    html = '''<div class="action-item">1. input_text(text='my secret', wait_time='1') <b>ok</b></div>
<div class="action-item">2. type(password='hunter2', pin='8713', api_key='sk-abc', key='OK')</div>
<div class="action-item">3. launch(url='https://example.com/login?token=SECRET123#frag', other='keep')</div>
<div class="action-item">4. input_text(text='it's tricky', code='1234')</div>
<span onclick="x(&#x27;a&#x27;)">text=&#x27;escaped pw&#x27;, token=&#x27;abc&#x27;)</span>
<span onclick="modal('{&quot;params&quot;: {&quot;Password&quot;: &quot;p\\&quot;w&quot;, &quot;href&quot;: &quot;https://h.example/p?q=SECRET&quot;, &quot;name&quot;: &quot;ok&quot;}}')">x</span>
<script>var d = {"text": "typed secret", "secret": "s3", "value": "v", "url": "https://a.example/b?c=SECRET"};</script>
<div>element_key='keep-me' monkey='keep' text_color='keep'</div>'''
    out = builder.mask_sensitive_parameters(html)
    for leaked in ('my secret', 'hunter2', '8713', 'sk-abc', 'SECRET123', 'tricky', '1234', 'escaped pw',
                   "token=&#x27;abc", 'p\\&quot;w', 'q=SECRET', 'typed secret', 's3', 'c=SECRET', '#frag'):
        assert leaked not in out, leaked
    assert "text='•••', wait_time='1'" in out
    assert "url='https://example.com/login', other='keep'" in out
    assert 'other=' in out and '&quot;name&quot;: &quot;ok&quot;' in out
    assert '&quot;href&quot;: &quot;https://h.example/p&quot;' in out
    assert "element_key='keep-me'" in out and "monkey='keep'" in out and "text_color='keep'" in out
    assert "key='OK'" in out  # a remote key press is not a secret


def test_rewrite_applies_the_masking_to_the_published_page():
    html = ('<div class="verification-item">1. waitForTextToAppear(text=\'PIN 8713\', timeout=\'20000 ms\') '
            '<a href="https://platform.example.com/x">x</a></div>')
    out, _ = builder.rewrite_report_html(html, _classifier())
    assert '8713' not in out and "text='•••', timeout='20000 ms'" in out
