"""tests/backend_host/test_device_model_normalization.py — BUG-0749: the model spellings a
host .env has to survive.

DEVICE{i}_MODEL is typed by hand, and the canonical names are easy to get wrong
(`android_tv` / `androidtv` / `andoridtv`, `apple_tv` / `appletv`, `fire_tv` /
`firetv` / `firetv_vega`). Every consumer looked the raw string up in
DEVICE_CONTROLLER_MAP, so a misspelling was not cosmetic: the factory returned {}, the
device registered with no controllers at all, and Take Control answered "Unsupported
device" with nothing in the log but a model name nobody could spell.

These pin the three resolution passes (exact / separator-free / near miss), the rule
that an AMBIGUOUS value is never guessed at — a device built out of the wrong model is
worse than none, because it looks alive — and that the factory then builds the same
thing for a misspelling as for the canonical name.

No host, no device, no network. The factory is loaded from its file, so the heavy
backend_host controller stack (cv2, psutil, …) is not needed, and its one lazy import
(the optional feature registry) is stubbed. controller_manager's use of the same two
lines is not exercised here: importing it pulls that whole stack.

    PYTHONPATH=. python3 -m pytest tests/backend_host/test_device_model_normalization.py -q

NOTE: CI's merge gate runs `pytest tests/backend_server` only, so nothing in
tests/backend_host runs on a PR today — including this file.
"""

import importlib.util
import pathlib
import subprocess
import sys
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.src.lib.config import device_capabilities as caps  # noqa: E402

FACTORY_PATH = REPO_ROOT / 'backend_host' / 'src' / 'controllers' / 'controller_config_factory.py'
RUN_FFMPEG = REPO_ROOT / 'backend_host' / 'scripts' / 'run_ffmpeg.sh'


def _load_factory():
    """Import the factory from its file, without backend_host/src/__init__.py.

    That package initialiser star-imports every controller, which pulls cv2 and the rest
    of the host's hardware stack — none of it needed here, and none of it installed on a
    plain dev machine. The module's own imports are all `shared.…` absolute imports, so
    they resolve normally from the repo root.
    """
    name = 'backend_host.src.controllers.controller_config_factory'
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, FACTORY_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


factory = _load_factory()


@pytest.fixture
def no_feature_registry(monkeypatch):
    """Stub the optional feature registry that _get_remote_params imports lazily.

    Importing it for real would run backend_host/src/controllers/__init__.py and the
    whole controller stack. A stub that finds nothing is the ordinary path for every
    built-in model: the registry only ever holds implementations a feature plugin
    registered against a model.
    """
    stub = types.ModuleType('backend_host.src.controllers.controller_registry')
    stub.get_remote_implementation = lambda _name: None
    monkeypatch.setitem(sys.modules, 'backend_host.src.controllers.controller_registry', stub)
    return stub


# ---- the shared resolver ----------------------------------------------------
@pytest.mark.parametrize('model', sorted(caps.DEVICE_CONTROLLER_MAP))
def test_every_canonical_model_is_unchanged(model):
    """Adding a model must never let another spelling steal it.

    This is the guard that makes the fuzzy pass safe to keep: every name in the map has
    to be a fixed point of its own spelling resolver.
    """
    assert caps.normalize_device_model(model) == model


@pytest.mark.parametrize('spelling, canonical', [
    # separator-free, which is how people actually write these
    ('androidtv', 'android_tv'),
    ('appletv', 'apple_tv'),
    ('iosmobile', 'ios_mobile'),
    ('rtspvideo', 'rtsp_video'),
    ('localvideo', 'local_video'),
    ('hostvnc', 'host_vnc'),
    ('firetv_vega', 'fire_tv_vega'),
    ('firetv_fireos', 'fire_tv_fireos'),
    ('cloudandroidmobile', 'cloud_android_mobile'),
    # case and the space people type
    ('ANDROID_TV', 'android_tv'),
    ('Android TV', 'android_tv'),
    ('  android_tv  ', 'android_tv'),
    # a dash typed where the underscore belongs
    ('android-mobile', 'android_mobile'),
])
def test_alternative_spellings_resolve(spelling, canonical):
    assert caps.normalize_device_model(spelling) == canonical


@pytest.mark.parametrize('typo, canonical', [
    ('andoridtv', 'android_tv'),      # r and o transposed
    ('stbb', 'stb'),                  # doubled letter
    ('android_ta', 'android_tv'),     # truncated, but only one android_tv completion
    ('firetv_ios', 'fire_tv_fireos'),  # fire_tv_fireos half-remembered
])
def test_near_misses_resolve(typo, canonical):
    assert caps.normalize_device_model(typo) == canonical


@pytest.mark.parametrize('spelling', ['fire_tv', 'firetv', 'Fire TV', 'FIRETV'])
def test_bare_fire_tv_resolves_to_fire_os(spelling):
    """A family name, not a typo: the common Fire TV, logged at every entry point.

    Vega has its own model and is the rarer case, so the ambiguous spelling resolves to
    Fire OS and says so — a Vega-only fleet changes MODEL_ALIASES, not its .env files.
    """
    assert caps.normalize_device_model(spelling) == 'fire_tv_fireos'


@pytest.mark.parametrize('value', [
    'android',            # four possible android_* completions
    'runner',             # four possible runner_* completions
    'ios',                # ios_mobile or cloud_ios_mobile
    'tv',                 # not a model, and close to none
    'fire',               # not a model
    'rtsp-video-2',       # a numbered variant, not a spelling
    'samsung_tv',         # a real device type this project has no controllers for
    'foobar',
    'ips',
])
def test_ambiguous_values_are_never_guessed_at(value):
    """Unknown in, unknown out — the caller still reports it and lists the real names.

    Everything here either has several plausible models or is not a model at all. Note
    what is NOT here: `android_ta`, which has only one android_tv completion and is
    resolved by the near-miss pass above.
    """
    assert caps.normalize_device_model(value) == value


def test_blank_is_reported_as_unknown():
    assert caps.normalize_device_model('') == 'unknown'
    assert caps.normalize_device_model('   ') == 'unknown'


def test_non_string_is_passed_through():
    assert caps.normalize_device_model(None) is None


# ---- the platform suffix ----------------------------------------------------
@pytest.mark.parametrize('value, expected', [
    ('stb', ('stb', None)),
    ('stb-example-v2', ('stb', 'example-v2')),      # already exact: nothing changes
    ('android_tv-example-v2', ('android_tv', 'example-v2')),
    ('firetv_vega-v2', ('fire_tv_vega', 'v2')),      # misspelled model, real tag
    ('unknown', ('unknown', None)),
    ('', ('unknown', None)),
])
def test_parse_keeps_the_platform_tag(value, expected):
    assert caps.parse_device_model(value) == expected


def test_a_separator_spelling_is_read_as_a_model_not_as_a_tag():
    """`android-mobile` is the model android_mobile, not the model `android` + tag `mobile`.

    The dash is the platform-tag separator, so the whole value is tried as a model first —
    without the fuzzy pass, which would otherwise swallow the tag (`android_tv-v2`).
    """
    assert caps.parse_device_model('android-mobile') == ('android_mobile', None)


# ---- the log line -----------------------------------------------------------
@pytest.mark.parametrize('raw, canonical', [
    ('android_tv', 'android_tv'),
    ('stb-example-v2', 'stb'),      # the tag is not a misspelling
    ('unknown', 'unknown'),
])
def test_spelling_note_is_quiet_when_nothing_changed(raw, canonical):
    assert caps.model_spelling_note(raw, canonical) is None


def test_spelling_note_names_the_correction():
    assert caps.model_spelling_note('androidtv', 'android_tv') == "'androidtv' read as 'android_tv'"
    assert caps.model_spelling_note('fire_tv', 'fire_tv_fireos') == "'fire_tv' read as 'fire_tv_fireos'"


# ---- the factory ------------------------------------------------------------
@pytest.mark.parametrize('canonical, misspelled', [
    ('android_tv', 'androidtv'),
    ('android_tv', 'andoridtv'),
    ('apple_tv', 'appletv'),
    ('fire_tv_vega', 'firetv_vega'),
    ('fire_tv_fireos', 'firetv_ios'),
    ('stb', 'stbb'),
    ('rtsp_video', 'rtspvideo'),
    ('host_vnc', 'hostvnc'),
])
def test_factory_builds_the_same_thing_for_a_misspelling(canonical, misspelled, no_feature_registry):
    """The whole point: a misspelled .env builds the device the canonical name builds."""
    def build(model):
        return factory.create_controller_configs_from_device_info({
            'device_id': 'device1', 'device_name': 'Test', 'device_model': model,
        })

    expected = build(canonical)
    assert expected, f"{canonical} should build controllers"
    assert build(misspelled) == expected


def test_factory_also_accepts_the_legacy_model_key(no_feature_registry):
    """device_config['model'] is the other key the factory reads; it gets the same tolerance."""
    built = factory.create_controller_configs_from_device_info({
        'device_id': 'device1', 'device_name': 'Test', 'model': 'appletv',
    })
    assert built == factory.create_controller_configs_from_device_info({
        'device_id': 'device1', 'device_name': 'Test', 'model': 'apple_tv',
    })
    assert built


@pytest.mark.parametrize('model', ['samsung_tv', 'android', 'foobar'])
def test_factory_still_refuses_an_unknown_model(model, no_feature_registry):
    """No silent fallback: an unknown model yields no controllers, as it always did."""
    assert factory.create_controller_configs_from_device_info({
        'device_id': 'device1', 'device_name': 'Test', 'device_model': model,
    }) == {}


@pytest.mark.parametrize('action_type', ['remote', 'web', 'desktop', 'verification', 'av', 'power', 'ai'])
def test_controller_type_lookup_survives_a_misspelling(action_type):
    assert (factory.get_controller_type_for_device('andoridtv', action_type)
            == factory.get_controller_type_for_device('android_tv', action_type))


def test_controller_type_lookup_still_routes_unknown_models_by_default():
    """Unchanged default routing for a model that is not in the map at all."""
    assert factory.get_controller_type_for_device('samsung_tv', 'remote') == 'remote'
    assert factory.get_controller_type_for_device('samsung_tv', 'web') == 'web'


# ---- run_ffmpeg.sh keeps the same folding -----------------------------------
def _slice_override_kind(dest: pathlib.Path) -> pathlib.Path:
    """Copy override_kind_for_model() out of run_ffmpeg.sh.

    Sourcing the whole script would boot the capture service, so the function is lifted out
    by its `name() {` … `}` block. Reading it from the REAL file rather than a copy kept in
    the test is the point: editing the logic breaks these tests.
    """
    lines = RUN_FFMPEG.read_text(encoding='utf-8').splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith('override_kind_for_model() {'))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].rstrip() == '}')
    script = dest / 'override_kind.sh'
    script.write_text(''.join(lines[start:end + 1]), encoding='utf-8')
    return script


@pytest.mark.parametrize('spelling, expected', [
    ('rtsp_video', 'url'),
    ('rtspvideo', 'url'),
    ('RTSP_Video', 'url'),
    ('rtsp-video', 'url'),
    ('tello', 'url'),
    ('Tello', 'url'),
    ('local_video', 'path'),
    ('localvideo', 'path'),
    ('Local_Video', 'path'),
    # a model that takes no runtime source override still takes none, spelled any way
    ('stb', ''),
    ('android_tv', ''),
    ('', ''),
])
def test_shell_override_folds_the_model_the_same_way(spelling, expected, tmp_path):
    """A host spelled differently must not get a correct device and a dead source switch.

    Without this the ffmpeg side read the .env model literally, so `rtspvideo` built a
    right device in Python and silently ignored its runtime URL override here.
    """
    script = _slice_override_kind(tmp_path)
    result = subprocess.run(
        ['bash', '-c', f'source "{script}"; override_kind_for_model "$1"', '_', spelling],
        capture_output=True, text=True, check=True)
    assert result.stdout.strip() == expected