"""tests/backend_host/test_device_farm.py — TASK-20 tier-A unit tests for
features/device-farm: the provider seam, credential redaction, slot config from
.env, and the session lease (lazy open, reuse, expiry, host cap, single session
shared with verification) plus the frame pump.

No network and no farm account: the Appium client is replaced by a fake module, so
these run anywhere — which is the point. They prove the parts that do not need
credentials. The tier-B gate — a real session against Sauce Labs — passed on
2026-09-17 (TASK-20 §4); it lives in features/device-farm/backend_host/smoke_test.py
and needs an account, so it is deliberately not here.

    PYTHONPATH=. python3 -m pytest tests/backend_host/test_device_farm.py -q

NOTE: CI's merge gate runs `pytest tests/backend_server` only, so nothing in
tests/backend_host runs on a PR today — including this file.
"""
import importlib
import importlib.util
import os
import pathlib
import sys
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_APPIUM_UTILS = 'backend_host.src.lib.utils.appium_utils'


def _load_appium_utils():
    """Import core's appium_utils without executing backend_host/src/__init__.py.

    That package initialiser star-imports every controller, which pulls cv2 and the
    rest of the host's hardware stack — none of which this unit test needs, and none
    of which is installed on a plain dev machine. Loading the one module from its
    file and publishing it under its real dotted name means the feature's own
    runtime import (session.py) finds exactly the module it would find on a host,
    and these tests do not depend on some earlier test having primed sys.modules.
    """
    if _APPIUM_UTILS in sys.modules:
        return sys.modules[_APPIUM_UTILS]
    path = REPO_ROOT / 'backend_host' / 'src' / 'lib' / 'utils' / 'appium_utils.py'
    spec = importlib.util.spec_from_file_location(_APPIUM_UTILS, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_APPIUM_UTILS] = module
    spec.loader.exec_module(module)
    return module


appium_utils = _load_appium_utils()

# The two controller classes subclass core's Appium controllers, so importing them
# pulls the host runtime (cv2, psutil, supabase, the Appium client — all of
# backend_host/requirements.txt). Where that is installed, the controller tests at
# the bottom of this file run against the REAL base classes, which is the only way
# to prove the inherited-method-through-the-lease wiring. Where it is not, they skip
# and the rest of the file still runs.
try:
    remote_mod = importlib.import_module('features.device-farm.backend_host.cloud_appium_remote')
    verification_mod = importlib.import_module(
        'features.device-farm.backend_host.cloud_appium_verification')
    _CONTROLLERS_ERROR = None
except Exception as exc:  # pragma: no cover - depends on the machine, not the code
    remote_mod = verification_mod = None
    _CONTROLLERS_ERROR = exc

requires_host_runtime = pytest.mark.skipif(
    remote_mod is None,
    reason=f'backend_host runtime not installed here ({_CONTROLLERS_ERROR})')


config_mod = importlib.import_module('features.device-farm.lib.config')
constants = importlib.import_module('features.device-farm.lib.constants')
providers_mod = importlib.import_module('features.device-farm.lib.providers')
types_mod = importlib.import_module('features.device-farm.lib.types')
session_mod = importlib.import_module('features.device-farm.backend_host.session')
slots_mod = importlib.import_module('features.device-farm.backend_host.slots')
pump_mod = importlib.import_module('features.device-farm.backend_host.frame_pump')

FarmConfig = types_mod.FarmConfig


def make_cfg(**overrides) -> FarmConfig:
    base = dict(
        device_id='device4',
        device_name='Pixel 8 (Sauce)',
        provider='saucelabs',
        username='acme-user',
        access_key='super-secret-key',
        platform_name='Android',
        device_query='Google Pixel 8',
        platform_version='14',
    )
    base.update(overrides)
    return FarmConfig(**base)


# ---- fake Appium client -----------------------------------------------------
class FakeDriver:
    def __init__(self, endpoint, caps):
        self.endpoint = endpoint
        self.caps = caps
        self.session_id = 'sess-1'
        self.quit_calls = 0
        self.screenshots = 0
        self.keycodes = []

    def get_screenshot_as_png(self):
        self.screenshots += 1
        return b'\x89PNG fake frame'

    def press_keycode(self, keycode):
        self.keycodes.append(keycode)

    def quit(self):
        self.quit_calls += 1


def _caps_of(options) -> dict:
    """Capabilities out of either the real AppiumOptions or the stand-in below."""
    if hasattr(options, 'to_capabilities'):
        return dict(options.to_capabilities())
    return dict(getattr(options, 'caps', {}))


class FakeOptions:
    """Stand-in for AppiumOptions when the Appium client is not installed."""

    def __init__(self):
        self.caps = {}

    def load_capabilities(self, caps):
        self.caps.update(caps)


@pytest.fixture
def fake_appium(monkeypatch):
    """Stop WebDriver sessions at the door and record every one that was opened.

    When the real Appium client is installed (it is in backend_host/requirements.txt)
    only `webdriver.Remote` is replaced, so the genuine AppiumOptions and the genuine
    AppiumUtils code paths still run — the fake is the farm, not the client. Without
    the client, the whole package is stood in for, so these tests also run on a
    machine that has never installed it.
    """
    opened = []
    failure = {'raise': None}

    def remote(command_executor=None, options=None, **_kwargs):
        if failure['raise'] is not None:
            raise failure['raise']
        driver = FakeDriver(command_executor, _caps_of(options))
        driver.session_id = f'sess-{len(opened) + 1}'
        opened.append(driver)
        return driver

    try:
        import appium.options.common as real_options  # noqa: F401
        import appium.webdriver as real_webdriver
        monkeypatch.setattr(real_webdriver, 'Remote', remote)
    except ImportError:
        appium = types.ModuleType('appium')
        webdriver = types.ModuleType('appium.webdriver')
        webdriver.Remote = remote
        appium.webdriver = webdriver
        options_common = types.ModuleType('appium.options.common')
        options_common.AppiumOptions = FakeOptions
        options_pkg = types.ModuleType('appium.options')
        options_pkg.common = options_common
        for name, module in (('appium', appium), ('appium.webdriver', webdriver),
                             ('appium.options', options_pkg),
                             ('appium.options.common', options_common)):
            monkeypatch.setitem(sys.modules, name, module)

    yield types.SimpleNamespace(opened=opened, failure=failure)


@pytest.fixture(autouse=True)
def clean_sessions():
    """The lease registry is module-global; no test may inherit another's session."""
    session_mod.release_all()
    yield
    session_mod.release_all()


# ---- the provider seam ------------------------------------------------------
@pytest.mark.unit
def test_every_provider_puts_credentials_in_its_own_options_block():
    cfg = make_cfg()
    expected = {
        'saucelabs': (constants.SAUCE_OPTIONS_KEY, 'username', 'accessKey'),
        'browserstack': (constants.BROWSERSTACK_OPTIONS_KEY, 'userName', 'accessKey'),
        'lambdatest': (constants.LAMBDATEST_OPTIONS_KEY, 'user', 'accessKey'),
    }
    for name, (block_key, user_key, key_key) in expected.items():
        provider = providers_mod.get_provider(name)
        caps = provider.session_caps(cfg._replace() if hasattr(cfg, '_replace') else cfg)
        assert block_key in caps, f'{name}: missing its vendor options block'
        block = caps[block_key]
        assert block[user_key] == 'acme-user'
        assert block[key_key] == 'super-secret-key'
        # The credential lives in the capabilities, never in the URL.
        assert 'super-secret-key' not in provider.endpoint_url(cfg)
        assert 'acme-user' not in provider.endpoint_url(cfg)


@pytest.mark.unit
def test_cloud_caps_drop_the_local_only_keys():
    """The local controller's udid/WDA keys are exactly what a farm rejects."""
    caps = providers_mod.get_provider('saucelabs').session_caps(make_cfg())
    for local_only in ('udid', 'appium:udid', 'usePrebuiltWDA', 'useNewWDA',
                       'shouldUseSingletonTestManager'):
        assert local_only not in caps


@pytest.mark.unit
@pytest.mark.parametrize('platform,automation,normalized', [
    ('Android', 'UiAutomator2', 'Android'),
    ('android', 'UiAutomator2', 'Android'),
    ('iOS', 'XCUITest', 'iOS'),
    ('ios', 'XCUITest', 'iOS'),
])
def test_platform_and_automation_are_normalized(platform, automation, normalized):
    caps = providers_mod.get_provider('saucelabs').session_caps(
        make_cfg(platform_name=platform))
    assert caps[constants.CAP_PLATFORM_NAME] == normalized
    assert caps[constants.CAP_AUTOMATION_NAME] == automation


@pytest.mark.unit
def test_device_request_lands_where_each_provider_reads_it():
    """Sauce reads the device from appium:, BrowserStack from its own block."""
    cfg = make_cfg()
    sauce = providers_mod.get_provider('saucelabs').session_caps(cfg)
    assert sauce[constants.CAP_DEVICE_NAME] == 'Google Pixel 8'
    assert sauce[constants.CAP_PLATFORM_VERSION] == '14'

    bstack = providers_mod.get_provider('browserstack').session_caps(cfg)
    assert bstack[constants.BROWSERSTACK_OPTIONS_KEY]['deviceName'] == 'Google Pixel 8'
    assert bstack[constants.BROWSERSTACK_OPTIONS_KEY]['osVersion'] == '14'


@pytest.mark.unit
def test_app_reference_is_passed_through_untouched():
    caps = providers_mod.get_provider('saucelabs').session_caps(
        make_cfg(app_ref='storage:abc-123'))
    assert caps[constants.CAP_APP] == 'storage:abc-123'


@pytest.mark.unit
def test_unimplemented_providers_say_so_instead_of_pretending():
    cfg = make_cfg(provider='browserstack')
    provider = providers_mod.get_provider('browserstack')
    with pytest.raises(NotImplementedError):
        provider.available_devices(cfg)
    with pytest.raises(NotImplementedError):
        provider.upload_app(cfg, '/tmp/app.apk')
    assert providers_mod.FULLY_IMPLEMENTED == ('saucelabs',)


@pytest.mark.unit
def test_unknown_provider_names_what_exists():
    with pytest.raises(ValueError) as excinfo:
        providers_mod.get_provider('perfecto')
    assert 'saucelabs' in str(excinfo.value)


# ---- redaction --------------------------------------------------------------
@pytest.mark.unit
def test_redaction_masks_the_key_inside_the_vendor_block():
    caps = providers_mod.get_provider('saucelabs').session_caps(make_cfg())
    printed = str(config_mod.redact(caps))
    assert 'super-secret-key' not in printed
    assert '***' in printed
    # The original is untouched — redaction is for printing, not for sending.
    assert caps[constants.SAUCE_OPTIONS_KEY]['accessKey'] == 'super-secret-key'


@pytest.mark.unit
def test_core_redaction_twin_covers_the_same_shape():
    caps = providers_mod.get_provider('lambdatest').session_caps(make_cfg())
    assert 'super-secret-key' not in str(appium_utils.redact_capabilities(caps))


@pytest.mark.unit
def test_farm_config_str_does_not_carry_the_key():
    assert 'super-secret-key' not in str(make_cfg())
    assert make_cfg().redacted().access_key == '***'


# ---- config from .env -------------------------------------------------------
@pytest.mark.unit
def test_missing_credentials_are_reported_in_env_spelling():
    cfg, missing = config_mod.from_device_config({
        'device_id': 'device4', 'appium_platform_name': 'Android'})
    assert cfg is None
    assert missing == ['DEVICE4_FARM_USER', 'DEVICE4_FARM_KEY']


@pytest.mark.unit
def test_screenshot_fps_is_clamped_because_frames_are_billed():
    cfg, _ = config_mod.from_device_config({
        'device_id': 'device1', 'appium_platform_name': 'Android',
        'farm_user': 'u', 'farm_key': 'k', 'farm_screenshot_fps': '99'})
    assert cfg.screenshot_fps == constants.MAX_SCREENSHOT_FPS

    cfg, _ = config_mod.from_device_config({
        'device_id': 'device1', 'appium_platform_name': 'Android',
        'farm_user': 'u', 'farm_key': 'k', 'farm_screenshot_fps': 'nonsense'})
    assert cfg.screenshot_fps == constants.DEFAULT_SCREENSHOT_FPS


# ---- slots ------------------------------------------------------------------
@pytest.fixture
def farm_env(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith('DEVICE'):
            monkeypatch.delenv(key, raising=False)
    frame = tmp_path / 'device4' / 'latest.jpg'
    monkeypatch.setenv('DEVICE4_NAME', 'Pixel 8 (Sauce)')
    monkeypatch.setenv('DEVICE4_MODEL', 'cloud_android_mobile')
    monkeypatch.setenv('DEVICE4_APPIUM_PLATFORM_NAME', 'Android')
    monkeypatch.setenv('DEVICE4_VIDEO', str(frame))
    monkeypatch.setenv('DEVICE4_FARM_USER', 'acme-user')
    monkeypatch.setenv('DEVICE4_FARM_KEY', 'super-secret-key')
    monkeypatch.setenv('DEVICE4_FARM_DEVICE', 'Google Pixel 8')
    monkeypatch.setenv('DEVICE4_FARM_OS_VERSION', '14')
    return str(frame)


@pytest.mark.unit
def test_farm_slots_are_found_by_model(farm_env, monkeypatch):
    monkeypatch.setenv('DEVICE1_NAME', 'STB')
    monkeypatch.setenv('DEVICE1_MODEL', 'stb')
    assert slots_mod.farm_slot_ids() == ['device4']


@pytest.mark.unit
def test_slot_config_is_read_without_core_passing_farm_keys(farm_env):
    """The verification controller only gets device_id — it must still find the slot."""
    cfg, missing = slots_mod.farm_config_for('device4')
    assert missing == []
    assert cfg.provider == constants.DEFAULT_PROVIDER
    assert cfg.device_query == 'Google Pixel 8'
    assert cfg.device_name == 'Pixel 8 (Sauce)'


@pytest.mark.unit
def test_device_config_overrides_the_env_name(farm_env):
    cfg, _ = slots_mod.farm_config_for('device4', {'device_name': 'renamed in core'})
    assert cfg.device_name == 'renamed in core'


@pytest.mark.unit
def test_non_image_video_path_means_no_pump(farm_env, monkeypatch):
    monkeypatch.setenv('DEVICE4_VIDEO', '/dev/video0')
    assert slots_mod.frame_path_for('device4') == ''


# ---- the lease --------------------------------------------------------------
@pytest.mark.unit
def test_no_session_is_opened_until_a_command_needs_one(fake_appium):
    session = session_mod.get_session(make_cfg())
    assert session.is_open is False
    assert fake_appium.opened == []

    utils = session.utils()
    assert utils is not None
    assert len(fake_appium.opened) == 1
    assert session.is_open is True
    # The driver is reachable under the host slot id, which is what every inherited
    # Appium method passes as its device id.
    assert utils.get_driver('device4') is fake_appium.opened[0]


@pytest.mark.unit
def test_a_second_command_reuses_the_same_session(fake_appium):
    session = session_mod.get_session(make_cfg())
    session.utils()
    session.utils()
    assert len(fake_appium.opened) == 1


@pytest.mark.unit
def test_an_expired_session_is_replaced_before_the_farm_reaps_it(fake_appium, monkeypatch):
    clock = {'now': 1000.0}
    monkeypatch.setattr(session_mod.time, 'time', lambda: clock['now'])

    session = session_mod.get_session(make_cfg(idle_timeout=60))
    session.utils()
    assert len(fake_appium.opened) == 1

    # Idle past (idle_timeout - SESSION_EXPIRY_MARGIN): the farm is about to reap it.
    clock['now'] += 60 - constants.SESSION_EXPIRY_MARGIN
    session.utils()
    assert len(fake_appium.opened) == 2
    assert fake_appium.opened[0].quit_calls == 1


@pytest.mark.unit
def test_the_host_cap_refuses_the_extra_session_with_a_reason(fake_appium, monkeypatch):
    monkeypatch.setenv(constants.ENV_HOST_MAX_SESSIONS, '1')
    first = session_mod.get_session(make_cfg(device_id='device4'))
    second = session_mod.get_session(make_cfg(device_id='device5'))

    assert first.utils() is not None
    assert second.utils() is None
    assert 'cap' in (second.last_error or '')
    assert len(fake_appium.opened) == 1


@pytest.mark.unit
def test_a_refused_session_is_an_error_not_a_traceback(fake_appium):
    fake_appium.failure['raise'] = RuntimeError('Misconfigured -- Unsupported device\nfull payload')
    session = session_mod.get_session(make_cfg())
    assert session.utils() is None
    assert 'RuntimeError' in session.last_error
    # Only the first line: a WebDriver error pastes the whole request, caps included.
    assert 'full payload' not in session.last_error


@pytest.mark.unit
def test_release_quits_the_driver_and_forgets_the_session(fake_appium):
    session = session_mod.get_session(make_cfg())
    session.utils()
    session_mod.release_session('device4')
    assert fake_appium.opened[0].quit_calls == 1
    assert session_mod.peek_session('device4') is None


# ---- the frame pump ---------------------------------------------------------
class _StubSession:
    def __init__(self, driver=None):
        self.driver = driver
        self.opens_requested = 0

    def driver_if_open(self):
        return self.driver

    def utils(self):  # the pump must never call this
        self.opens_requested += 1
        raise AssertionError('the frame pump must not open a session')


@pytest.mark.unit
def test_pump_writes_a_frame_atomically(tmp_path):
    driver = FakeDriver('endpoint', {})
    frame_path = tmp_path / 'latest.jpg'
    pump = pump_mod.FramePump(make_cfg(), _StubSession(driver), str(frame_path))

    pump._capture_once(driver)

    assert frame_path.read_bytes() == b'\x89PNG fake frame'
    assert not (tmp_path / 'latest.jpg.tmp').exists()
    assert pump.frames_written == 1


@pytest.mark.unit
def test_pump_writes_nothing_while_no_session_is_open(tmp_path):
    frame_path = tmp_path / 'latest.jpg'
    session = _StubSession(driver=None)
    pump = pump_mod.FramePump(make_cfg(), session, str(frame_path))

    # One loop turn's worth of work, without starting the thread.
    assert session.driver_if_open() is None
    assert not frame_path.exists()
    assert session.opens_requested == 0
    assert pump.frames_written == 0


@pytest.mark.unit
def test_pump_survives_a_farm_that_stops_answering(tmp_path):
    class Broken(FakeDriver):
        def get_screenshot_as_png(self):
            raise RuntimeError('session terminated')

    driver = Broken('endpoint', {})
    pump = pump_mod.FramePump(make_cfg(), _StubSession(driver), str(tmp_path / 'latest.jpg'))
    pump._stop.set()  # keep the failure back-off from actually sleeping
    pump._capture_once(driver)

    assert pump.frames_written == 0
    assert 'session terminated' in pump.last_error


# ---- the controllers, against the real core base classes --------------------
@requires_host_runtime
@pytest.mark.unit
def test_building_the_controller_opens_no_session(fake_appium):
    controller = remote_mod.CloudAppiumRemoteController(make_cfg())
    assert fake_appium.opened == []
    # 'Connected' means leasable: the inherited guards read this flag, and a command
    # has to get through them to be able to take the lease.
    assert controller.is_connected is True
    assert controller.appium_device_id == 'device4'


@requires_host_runtime
@pytest.mark.unit
def test_an_inherited_command_takes_the_lease_and_reaches_the_device(fake_appium):
    """press_key is core's, untouched: it proves the whole inherited surface works."""
    controller = remote_mod.CloudAppiumRemoteController(make_cfg())

    assert controller.press_key('HOME') is True

    assert len(fake_appium.opened) == 1
    assert fake_appium.opened[0].keycodes == [3]          # Android HOME
    assert fake_appium.opened[0].endpoint == 'https://ondemand.us-west-1.saucelabs.com/wd/hub'


@requires_host_runtime
@pytest.mark.unit
def test_verification_shares_the_one_session_instead_of_allocating_a_second_device(fake_appium):
    cfg = make_cfg()
    remote = remote_mod.CloudAppiumRemoteController(cfg)
    verification = verification_mod.CloudAppiumVerificationController(cfg=cfg)

    assert remote.press_key('BACK') is True
    assert verification._connect_device() is True

    assert len(fake_appium.opened) == 1, 'a farm device was allocated twice'
    assert verification.session is remote.session


@requires_host_runtime
@pytest.mark.unit
def test_a_farm_outage_is_a_failed_command_not_a_traceback(fake_appium):
    fake_appium.failure['raise'] = RuntimeError('all devices busy')
    controller = remote_mod.CloudAppiumRemoteController(make_cfg())

    assert controller.press_key('HOME') is False
    assert 'all devices busy' in controller.last_session_error


@requires_host_runtime
@pytest.mark.unit
def test_disconnect_releases_the_lease(fake_appium):
    controller = remote_mod.CloudAppiumRemoteController(make_cfg())
    controller.press_key('HOME')

    assert controller.disconnect() is True
    assert fake_appium.opened[0].quit_calls == 1
    assert session_mod.peek_session('device4') is None


@requires_host_runtime
@pytest.mark.unit
def test_status_does_not_probe_the_farm_endpoint(fake_appium, monkeypatch):
    """Core curls <endpoint>/status, which a farm hub answers only to an authenticated
    caller — it would report a healthy slot as unreachable."""
    import subprocess

    def explode(*args, **kwargs):
        raise AssertionError('get_status must not shell out to the farm endpoint')

    monkeypatch.setattr(subprocess, 'run', explode)
    controller = remote_mod.CloudAppiumRemoteController(make_cfg())

    status = controller.get_status()
    assert status['success'] is True
    assert status['farm']['open'] is False


@requires_host_runtime
@pytest.mark.unit
def test_the_lease_cannot_be_reassigned_from_outside(fake_appium):
    controller = remote_mod.CloudAppiumRemoteController(make_cfg())
    with pytest.raises(AttributeError):
        controller.appium_utils = object()


@requires_host_runtime
@pytest.mark.unit
def test_a_slot_with_a_frame_path_starts_a_pump_that_waits_for_a_session(fake_appium, tmp_path):
    frame_path = tmp_path / 'latest.jpg'
    controller = remote_mod.CloudAppiumRemoteController(
        make_cfg(), frame_path=str(frame_path))
    try:
        assert controller.frame_pump is not None
        # The invariant that matters is NO SESSION. The pump does write exactly one
        # frame before any session exists — a placeholder, so the host's ffmpeg grabber
        # has something to open (it refuses to start otherwise, and blocks the other
        # devices' grabbers behind it). That write is local and costs nothing; leasing a
        # device to produce a frame would cost money on every configured slot.
        assert fake_appium.opened == []
        assert frame_path.exists(), 'the grabber needs a source image to start'
        assert frame_path.stat().st_size < 4096, 'placeholder only — not a real capture'
    finally:
        controller.disconnect()


@requires_host_runtime
@pytest.mark.unit
def test_core_builds_the_expected_controller_set_for_a_cloud_model():
    """The core hook in device_capabilities is what makes the feature reachable at all."""
    from backend_host.src.controllers.controller_config_factory import (
        create_controller_configs_from_device_info,
    )

    configs = create_controller_configs_from_device_info({
        'device_id': 'device4',
        'device_name': 'Pixel 8 (Sauce)',
        'model': 'cloud_android_mobile',
        'video_capture_path': '/var/www/html/stream/capture4',
        'video_stream_path': '/host/stream/capture4',
    })

    # The AV controller is core's ffmpeg one: the pump feeds the captures folder, so
    # nothing downstream of it knows the device is in a farm.
    assert configs['av']['implementation'] == 'hdmi_stream'
    assert configs['remote']['implementation'] == 'appium_cloud'
    assert configs['verification_appium']['implementation'] == 'appium'
    # 'adb' as well: a cloud Android phone is in the android_phone family
    # (MODEL_FAMILIES), and an android_mobile navigation tree writes its screen checks
    # as `verification_type: 'adb'`. Without this the tree is offered for a farm phone
    # and then finds no implementation.
    assert configs['verification_adb']['implementation'] == 'adb'
    for verification in ('image', 'text', 'color', 'video'):
        assert f'verification_{verification}' in configs


@requires_host_runtime
@pytest.mark.unit
def test_adb_verification_is_backed_by_the_same_farm_session(fake_appium):
    """Registering 'adb' must not open a second (billed) device."""
    cfg = make_cfg()
    remote = remote_mod.CloudAppiumRemoteController(cfg)
    adb_verification = verification_mod.CloudAppiumVerificationController(
        cfg=cfg, verification_type='adb')

    assert remote.press_key('BACK') is True
    assert adb_verification._connect_device() is True

    assert adb_verification.verification_type == 'adb'
    assert adb_verification.session is remote.session
    assert len(fake_appium.opened) == 1, 'a farm device was allocated twice'


@pytest.mark.unit
def test_a_trial_account_is_told_what_to_do_instead(monkeypatch):
    """Some plans answer 403 'Access API is not available for free trial accounts' to the
    real-device endpoints. It is a plan limit, not a credential problem, and it applies to
    the *listing* only — a session against a device named directly still opens.

    Note what this test no longer claims. It used to say a trial account has no real
    devices and must fall back to an emulator; on 2026-09-17 the trial account in hand
    listed the full pool (HTTP 200) and validation ran on a real Samsung Galaxy S23 FE.
    So the message must not send the reader to an emulator — that was advice built on a
    belief that turned out to be wrong."""
    import requests

    class Response:
        status_code = 403
        text = ('Access API is not available for free trial accounts\\n'
                'The Access API requires private devices, which are not included')

    monkeypatch.setattr(requests, 'get', lambda *a, **kw: Response())
    provider = providers_mod.get_provider('saucelabs')

    with pytest.raises(providers_mod.UnsupportedOperation) as excinfo:
        provider.available_devices(make_cfg())

    message = str(excinfo.value)
    assert 'free trial' in message.lower()        # quotes what the farm actually said
    assert 'plan' in message.lower()              # names it as a plan limit, not a credential one
    assert 'sessions are' in message.lower()      # and that this does not block a run
    assert 'DEVICE{i}_FARM_DEVICE' in message     # says exactly what to do instead
    assert 'Emulator' not in message              # and does not repeat the disproven advice


# ---- the placeholder seed ---------------------------------------------------
@pytest.mark.unit
def test_the_pump_seeds_a_frame_so_the_grabber_can_start(tmp_path):
    """The host's ffmpeg grabber will not start until its source image exists, and it
    waits ~2 minutes before giving up. Grabbers are started in sequence, so a farm slot
    with no image yet held up every other device on the host — found on a real host
    2026-09-17, where a new browserstack slot stopped device2, device3 and host from
    streaming at all."""
    frame = tmp_path / 'device9' / 'latest.jpg'
    pump = pump_mod.FramePump(make_cfg(device_id='device9'), _NeverOpens(), str(frame))
    assert pump.start() is True
    try:
        assert frame.exists(), 'grabber would block: no source image'
        assert frame.read_bytes()[:3] == b'\xff\xd8\xff', 'seed must be a valid JPEG'
        # The grabber reads orientation straight off this image's aspect
        # (run_ffmpeg.sh: portrait iff height > width) and locks the ffmpeg pipeline to
        # it. A square or wide seed silently rotates every capture for the device: a
        # 16x16 seed gave "Detected orientation: landscape (source: 16x16)" and 2340x1080
        # captures of a phone that reported itself PORTRAIT.
        from PIL import Image
        import io as _io
        width, height = Image.open(_io.BytesIO(frame.read_bytes())).size
        assert height > width, f'seed must be portrait, got {width}x{height}'
    finally:
        pump.stop()


@pytest.mark.unit
def test_seeding_never_opens_a_session(tmp_path):
    """Seeding is the pump touching the filesystem, not the farm. A pump that leased a
    device just to have something to write would bill every configured slot forever."""
    session = _NeverOpens()
    pump = pump_mod.FramePump(make_cfg(device_id='device9'), session, str(tmp_path / 'f.jpg'))
    pump.start()
    try:
        assert session.utils_calls == 0, 'the pump must never call utils()'
    finally:
        pump.stop()


@pytest.mark.unit
def test_a_real_frame_is_never_replaced_by_the_placeholder(tmp_path):
    """A frame left by an earlier session is better evidence than a black square, and a
    host restart must not throw it away."""
    frame = tmp_path / 'latest.jpg'
    frame.write_bytes(b'\xff\xd8\xff-a-real-screenshot')
    pump = pump_mod.FramePump(make_cfg(device_id='device9'), _NeverOpens(), str(frame))
    pump.start()
    try:
        assert frame.read_bytes() == b'\xff\xd8\xff-a-real-screenshot'
    finally:
        pump.stop()


class _NeverOpens:
    """A session that is configured but has never been leased — the idle-host case."""

    def __init__(self):
        self.utils_calls = 0

    def driver_if_open(self):
        return None

    def utils(self):
        self.utils_calls += 1
        raise AssertionError('the pump opened a session')
