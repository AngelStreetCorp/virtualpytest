"""Which live-view transport a device can ACTUALLY deliver.

WebRTC (WHEP) is not a browser preference: it only exists when **this host runs
MediaMTX** AND **this device's capture publishes to it**. Only the ``v4l2`` branch
of ``backend_host/scripts/run_ffmpeg.sh`` emits the RTSP slave
(``rtsp://127.0.0.1:8554/<captureN>``) that MediaMTX serves — every other source
(ADB screencap, x11grab, imagefile, network feeds) produces HLS and nothing for
MediaMTX. A cloud device farm has no stream of ours at all: ``FarmProvider`` has
no stream method, and its ``video_url`` is a *recording link* the vendor's jobs
API returns once the job has finished.

So each device declares a profile, and the UI offers WEB only for ``whep``.

Every other value is a positive "no" **with a reason**, never an inference:
``hls`` (and an absent profile) mean "this host has not reported yet", which
keeps today's behaviour rather than silently removing WebRTC from a host whose
backend has not been redeployed. BUG-0833: the WEB toggle used to be rendered
unconditionally, so on a host with no MediaMTX at all every click was a
guaranteed 6 s timeout and an error toast naming nothing.
"""

from typing import Any, Dict, Optional

#: WebRTC works: MediaMTX on this host, and this capture feeds it.
WHEP = 'whep'
#: Not reported / unknown. Deliberately permissive — see the module docstring.
HLS = 'hls'
#: An Appium session in the vendor's datacentre (features/device-farm). Never ours to stream.
CLOUD_FARM = 'cloud_farm'
#: HLS only: this host runs no MediaMTX, so there is no WHEP endpoint to negotiate against.
HLS_NO_WEBRTC_HOST = 'hls_no_webrtc_host'
#: HLS only: MediaMTX is here, but this capture publishes nothing to it (not a v4l2 grabber).
HLS_NO_PUBLISHER = 'hls_no_publisher'

#: Profiles that positively deny WebRTC. ``HLS`` is NOT here on purpose — an
#: unreported host must keep today's behaviour rather than lose the feature.
WEBRTC_DENIED = frozenset({CLOUD_FARM, HLS_NO_WEBRTC_HOST, HLS_NO_PUBLISHER})

#: run_ffmpeg.sh detects the source with this prefix; anything else has no RTSP tee.
V4L2_SOURCE_PREFIX = '/dev/video'


def is_cloud_farm_device(device: Optional[Dict[str, Any]]) -> bool:
    """True for a features/device-farm device, whatever its source claims to be.

    Checked first: a farm session is never streamable, and saying "install
    MediaMTX" about one would send an operator after the wrong thing.
    """
    return bool((device or {}).get('device_farm_provider'))


def is_v4l2_device(device: Optional[Dict[str, Any]]) -> bool:
    """True when this capture is a v4l2 grabber, i.e. the one source with an RTSP tee."""
    source = str((device or {}).get('video') or '').strip()
    return source.startswith(V4L2_SOURCE_PREFIX)


def derive_stream_protocol(device: Optional[Dict[str, Any]], webrtc_available: bool) -> str:
    """The profile this device reports to the UI.

    `webrtc_available` is the HOST fact (MediaMTX actually answering on its WHEP
    port), probed on the host and carried in ``system_stats['webrtc']`` — see
    ``system_info_utils.has_webrtc_endpoint()``.
    """
    if is_cloud_farm_device(device):
        return CLOUD_FARM
    if not webrtc_available:
        return HLS_NO_WEBRTC_HOST
    if not is_v4l2_device(device):
        return HLS_NO_PUBLISHER
    return WHEP


def webrtc_supported(profile: Optional[str]) -> bool:
    """Whether the WEB toggle may be offered for a device reporting `profile`.

    Fail-open: only an explicit deny removes the button.
    """
    return profile not in WEBRTC_DENIED