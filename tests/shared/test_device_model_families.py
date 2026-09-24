"""Tests for device model families — which model names describe the same device.

`shared/src/lib/config/device_capabilities.py` carries MODEL_FAMILIES, the one table
every userinterface / host / script-target matcher reads. Before it, matching compared
model strings exactly, so a userinterface built for `android_mobile` was invisible to a
paired phone (`phone_agent`) and to a cloud farm phone (`cloud_android_mobile`) and a
near-duplicate userinterface had to be created per transport.

The TypeScript mirror is `frontend/src/config/deviceModelFamilies.ts`; the two tables
are compared for drift at the bottom of this file.

Run: pytest tests/shared/test_device_model_families.py -v
"""
import json
import os
import re
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.config.device_capabilities import (  # noqa: E402
    CONTROLLER_VERIFICATION_MAP,
    DEVICE_CONTROLLER_MAP,
    MODEL_EXTRA_MATCHES,
    MODEL_FAMILIES,
    expand_models,
    get_compatible_models,
    get_model_family,
    model_matches_any,
    models_are_compatible,
)

_TS_MIRROR = os.path.join(_repo_root, 'frontend', 'src', 'config', 'deviceModelFamilies.ts')

ANDROID_PHONES = ('android_mobile', 'phone_agent', 'cloud_android_mobile', 'runner_android_mobile')


@pytest.mark.unit
class TestAndroidPhoneFamily:
    """The case that prompted the table: three ways to reach one Android phone."""

    @pytest.mark.parametrize('model', ANDROID_PHONES)
    def test_every_android_phone_shares_one_family(self, model):
        assert get_model_family(model) == 'android_phone'

    @pytest.mark.parametrize('model', ANDROID_PHONES)
    def test_a_farm_or_paired_phone_matches_an_android_mobile_userinterface(self, model):
        # `youtube-android-mobile` lists only android_mobile + phone_agent; a farm phone
        # must still find it rather than needing its own `cloud_farm_demo` copy.
        assert model_matches_any(model, ['android_mobile', 'phone_agent'])

    def test_compatibility_is_symmetric(self):
        for a in ANDROID_PHONES:
            for b in ANDROID_PHONES:
                assert models_are_compatible(a, b), f'{a} vs {b}'

    def test_a_tablet_is_not_a_phone(self):
        # Tablet layouts differ, so `youtube-android-tablet` must stay separate.
        assert not models_are_compatible('android_tablet', 'android_mobile')
        assert not model_matches_any('android_tablet', ['android_mobile'])

    def test_a_tv_is_not_a_phone(self):
        assert not models_are_compatible('android_tv', 'android_mobile')

    def test_an_ios_phone_is_not_an_android_one(self):
        assert models_are_compatible('ios_mobile', 'cloud_ios_mobile')
        assert not models_are_compatible('ios_mobile', 'android_mobile')


@pytest.mark.unit
class TestUnknownModels:
    """An unlisted model must degrade to exact matching, never to matching everything."""

    def test_a_model_in_no_family_is_its_own_family(self):
        assert get_compatible_models('stb') == ['stb']
        assert get_model_family('stb') == 'stb'

    def test_a_model_nobody_has_heard_of_still_matches_itself(self):
        assert get_compatible_models('brand_new_thing') == ['brand_new_thing']
        assert model_matches_any('brand_new_thing', ['brand_new_thing'])
        assert not model_matches_any('brand_new_thing', ['android_mobile'])

    def test_empty_inputs_match_nothing(self):
        assert get_compatible_models('') == []
        assert not model_matches_any('', ['android_mobile'])
        assert not model_matches_any('android_mobile', [])
        assert not model_matches_any('android_mobile', None)
        assert not models_are_compatible('android_mobile', '')

    def test_every_model_belongs_to_at_most_one_family(self):
        seen = {}
        for family, models in MODEL_FAMILIES.items():
            for model in models:
                assert model not in seen, f'{model} is in both {seen.get(model)} and {family}'
                seen[model] = family


@pytest.mark.unit
class TestHostVncStaysAsymmetric:
    """The pre-existing host_vnc rule, which is deliberately *not* a family.

    A host_vnc device can run a web or desktop userinterface; a web device cannot run a
    host_vnc one, because that tree is full of desktop actions Playwright cannot execute.
    """

    def test_a_vnc_host_still_matches_web_and_desktop_interfaces(self):
        compatible = get_compatible_models('host_vnc')
        assert 'web' in compatible and 'desktop' in compatible

    def test_a_web_device_does_not_match_a_vnc_interface(self):
        assert get_compatible_models('web') == ['web']
        assert not model_matches_any('web', ['host_vnc'])

    def test_extras_are_declared_one_way_only(self):
        for device_model, extras in MODEL_EXTRA_MATCHES.items():
            for extra in extras:
                assert device_model not in MODEL_EXTRA_MATCHES.get(extra, []), (
                    f'{device_model} <-> {extra} is symmetric; make it a family instead')


@pytest.mark.unit
class TestExpandModels:
    """The reverse direction: which devices can run this userinterface."""

    def test_an_android_mobile_interface_accepts_every_android_phone(self):
        assert set(expand_models(['android_mobile'])) == set(ANDROID_PHONES)

    def test_a_web_interface_is_runnable_by_a_vnc_host(self):
        # Reverse of MODEL_EXTRA_MATCHES — the direction host_vnc's rule does allow.
        expanded = expand_models(['web'])
        assert 'web' in expanded and 'host_vnc' in expanded

    def test_several_models_expand_without_duplicates(self):
        expanded = expand_models(['android_mobile', 'phone_agent'])
        assert sorted(expanded) == sorted(set(expanded))
        assert set(expanded) == set(ANDROID_PHONES)

    def test_empty_expands_to_empty(self):
        assert expand_models([]) == []
        assert expand_models(None) == []


@pytest.mark.unit
class TestFamiliesAreHonest:
    """A family is a promise that the same navigation tree runs on every member.

    These guard the promise at the controller level, so the table cannot claim a
    compatibility the host could not actually deliver.
    """

    def test_every_family_member_is_a_known_device_model(self):
        for family, models in MODEL_FAMILIES.items():
            for model in models:
                assert model in DEVICE_CONTROLLER_MAP, (
                    f'{model} ({family}) has no entry in DEVICE_CONTROLLER_MAP')

    def test_every_android_phone_can_serve_adb_verifications(self):
        # An android_mobile navigation tree writes its screen checks as
        # `verification_type: 'adb'`. If a family member's remote cannot back 'adb', that
        # tree would be offered for it and then fail at run time.
        for model in ANDROID_PHONES:
            remotes = DEVICE_CONTROLLER_MAP[model]['remote']
            backed = any('adb' in CONTROLLER_VERIFICATION_MAP.get(r, []) for r in remotes)
            assert backed, f"{model}'s remote {remotes} does not back the 'adb' verification type"


@pytest.mark.unit
class TestTypeScriptMirrorMatches:
    """frontend/src/config/deviceModelFamilies.ts must carry the same table.

    The backend filters `getCompatibleInterfaces` with the Python copy and the frontend
    filters hosts, campaigns and script targets with the TypeScript one; a drift between
    them shows up as a userinterface the server offers and the page hides.
    """

    @staticmethod
    def _parse_ts_object(name: str) -> dict:
        source = open(_TS_MIRROR).read()
        match = re.search(rf'export const {name}: Record<string, string\[\]> = {{(.*?)\n}};',
                          source, re.S)
        assert match, f'{name} not found in {_TS_MIRROR}'
        body = match.group(1)
        # Strip comments, quote the bare keys, swap TS single quotes for JSON double ones
        # and drop the trailing comma — then it is JSON.
        body = re.sub(r'//[^\n]*', '', body)
        body = re.sub(r'^(\s*)([A-Za-z_][A-Za-z0-9_]*):', r'\1"\2":', body, flags=re.M)
        body = body.replace("'", '"')
        body = re.sub(r',(\s*)$', r'\1', body.strip())
        return json.loads('{' + body + '}')

    def test_families_match(self):
        assert self._parse_ts_object('MODEL_FAMILIES') == MODEL_FAMILIES

    def test_extras_match(self):
        assert self._parse_ts_object('MODEL_EXTRA_MATCHES') == MODEL_EXTRA_MATCHES
