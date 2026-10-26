"""G2 — the live abstention carries the complete v6 fingerprint.

`attach_unknown_fingerprint` runs only on an abstention (the path that can
register an unknown screen) and never lets a fingerprint failure break localize.
"""
import importlib

import pytest

ne = importlib.import_module('backend_host.src.services.navigation.navigation_executor')

pytestmark = pytest.mark.unit

V6 = {
    'v': 6, 'dhash': 'ab' * 32,
    'regions': {'full': 'ab' * 32, 'center': 'cd' * 32},
    'crop': None, 'focus': {'kind': 'none'}, 'title': 'replay', 'text': [],
}


class Helpers:
    def __init__(self, fingerprint=V6, raises=False):
        self.fingerprint = fingerprint
        self.raises = raises
        self.calls = 0

    def compute_fingerprint(self, img):
        self.calls += 1
        if self.raises:
            raise RuntimeError('ocr failed')
        return self.fingerprint


def test_abstention_attaches_the_full_fingerprint():
    result = {'verdict': {'kind': 'unknown'}}
    helpers = Helpers()
    out = ne.attach_unknown_fingerprint(result, object(), helpers)
    assert out['fingerprint'] == V6
    assert helpers.calls == 1


def test_low_confidence_also_attaches():
    result = {'verdict': {'kind': 'low_confidence'}}
    out = ne.attach_unknown_fingerprint(result, object(), Helpers())
    assert out['fingerprint'] == V6


def test_known_node_does_not_run_the_ocr():
    result = {'verdict': {'kind': 'node'}}
    helpers = Helpers()
    out = ne.attach_unknown_fingerprint(result, object(), helpers)
    assert 'fingerprint' not in out
    assert helpers.calls == 0


def test_fingerprint_failure_is_non_fatal():
    result = {'verdict': {'kind': 'unknown'}}
    out = ne.attach_unknown_fingerprint(result, object(), Helpers(raises=True))
    assert 'fingerprint' not in out
    assert out['verdict'] == {'kind': 'unknown'}
