"""call_host must say a connect timeout is a connect timeout, not a 120s read timeout."""
from unittest import mock

import requests

from shared.src.lib.utils import build_url_utils as b

HOST = {'host_name': 'h', 'host_api_url': 'http://127.0.0.1:1'}


def _call(exc):
    with mock.patch.object(b, 'buildHostUrl', return_value='http://127.0.0.1:1/x'), \
         mock.patch.object(b.requests, 'request', side_effect=exc):
        return b.call_host(HOST, '/host/x', timeout=120)


def test_connect_timeout_is_labelled():
    data, status = _call(requests.exceptions.ConnectTimeout())
    assert status == 504 and 'connect timeout=3s' in data['error'] and '120' not in data['error']


def test_read_timeout_keeps_read_label():
    data, status = _call(requests.exceptions.ReadTimeout())
    assert status == 504 and 'timeout=120s' in data['error']
