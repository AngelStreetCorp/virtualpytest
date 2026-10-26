"""Which live-view transport a device declares — and therefore whether the UI may offer WEB.

BUG-0833: the WEB toggle was rendered unconditionally, so on a host with no MediaMTX every
press was a guaranteed 6 s timeout followed by an error that named nothing. The profile is
now computed from two real facts — a WHEP endpoint on this host, and whether this capture
publishes to it — plus the cloud farm case, which is never streamable at all.
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared.src.lib.utils.stream_capability_utils import (  # noqa: E402
    CLOUD_FARM,
    HLS_NO_PUBLISHER,
    HLS_NO_WEBRTC_HOST,
    WHEP,
    derive_stream_protocol,
    webrtc_supported,
)


V4L2 = {'video': '/dev/video0'}
ADB_SCREENCAP = {'video': ''}
BROWSER_FARM = {'device_farm_provider': 'browserstack'}
SAUCE_FARM = {'device_farm_provider': 'saucelabs', 'video': '/dev/video9'}


def test_a_v4l2_capture_on_a_webrtc_host_is_the_only_whep_case():
    assert derive_stream_protocol(V4L2, webrtc_available=True) == WHEP


def test_no_mediamtx_on_the_host_denies_web_for_every_device():
    # host-clone-1 as it is today: vpt-mediamtx inactive, no mediamtx.yml. Whatever the
    # capture is, there is no endpoint for a browser to negotiate against.
    assert derive_stream_protocol(V4L2, webrtc_available=False) == HLS_NO_WEBRTC_HOST
    assert derive_stream_protocol(ADB_SCREENCAP, webrtc_available=False) == HLS_NO_WEBRTC_HOST


def test_mediamtx_present_but_a_non_grabber_capture_publishes_nothing():
    # Only the v4l2 branch of run_ffmpeg.sh emits the RTSP slave MediaMTX serves.
    assert derive_stream_protocol(ADB_SCREENCAP, webrtc_available=True) == HLS_NO_PUBLISHER
    assert derive_stream_protocol({}, webrtc_available=True) == HLS_NO_PUBLISHER
    assert derive_stream_protocol({'video': ':0'}, webrtc_available=True) == HLS_NO_PUBLISHER


def test_a_cloud_farm_session_gets_its_own_profile_even_when_the_host_is_ready():
    # Checked before the host fact on purpose: telling an operator to install MediaMTX for a
    # device that runs in Sauce Labs' datacentre would send them after the wrong thing.
    assert derive_stream_protocol(BROWSER_FARM, webrtc_available=True) == CLOUD_FARM
    assert derive_stream_protocol(SAUCE_FARM, webrtc_available=True) == CLOUD_FARM
    # …and still when the host has no MediaMTX either.
    assert derive_stream_protocol(BROWSER_FARM, webrtc_available=False) == CLOUD_FARM


def test_only_whep_is_allowed_to_offer_web():
    assert webrtc_supported(WHEP)
    for denied in (CLOUD_FARM, HLS_NO_WEBRTC_HOST, HLS_NO_PUBLISHER):
        assert not webrtc_supported(denied), denied


def test_an_unreported_device_keeps_todays_behaviour():
    # Fail-open. A host whose backend predates the profile field must not silently lose
    # WebRTC on devices that can actually do it (this is a fail-closed bug waiting to happen).
    assert webrtc_supported(None)
    assert webrtc_supported('hls')
    assert webrtc_supported('')
    assert webrtc_supported('something_a_newer_host_says')


def test_a_device_dict_from_to_dict_is_enough_to_derive_the_profile():
    # Mirrors what host_utils stamps: the two fields the derivation reads are both present
    # on a real device dict (device.py to_dict emits them conditionally).
    farm = {'device_id': 'device4', 'device_name': 'BStack_S23', 'device_farm_provider': 'browserstack'}
    assert derive_stream_protocol(farm, webrtc_available=True) == CLOUD_FARM

    grabber = {'device_id': 'capture1', 'device_name': 'STB4', 'video': '/dev/video1'}
    assert derive_stream_protocol(grabber, webrtc_available=True) == WHEP
    assert derive_stream_protocol(grabber, webrtc_available=False) == HLS_NO_WEBRTC_HOST