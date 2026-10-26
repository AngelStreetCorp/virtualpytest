"""The nav-tab check must survive the executor's verification filter.

`_filter_valid_verifications` drops an image verification that has no
`params.image_path` — the reference image it would match against. The
nav-tab check matches nothing: it reads the focus underline off the live
frame. Without an explicit branch it was silently dropped, and the node was
"verified" by nothing.
"""
import importlib

import pytest


@pytest.fixture
def executor():
    mod = importlib.import_module('backend_host.src.services.verifications.verification_executor')
    return mod.VerificationExecutor.__new__(mod.VerificationExecutor)


def _nav(params):
    return {"verification_type": "image", "command": "waitForNavTabIndex", "params": params}


def test_nav_tab_check_is_kept(executor):
    kept = executor._filter_valid_verifications([_nav({"tab_index": 3, "tab_count": 9, "timeout": 3000})])
    assert len(kept) == 1
    assert kept[0]["params"]["tab_index"] == 3


def test_nav_tab_check_without_an_index_is_dropped(executor):
    kept = executor._filter_valid_verifications([_nav({"tab_count": 9})])
    assert kept == []


def test_a_plain_image_check_still_needs_its_reference(executor):
    kept = executor._filter_valid_verifications([
        {"verification_type": "image", "command": "waitForImageToAppear", "params": {}}])
    assert kept == []
