"""Read a device's live identity for Localize (TASK-107 goal 4; matching is in
shared/src/lib/utils/localize_identity.py).

- android_mobile / android_tablet (adb remote): the resumed activity from `dumpsys activity
  activities`, and with `with_texts` the visible texts of a UI dump (~1-2 s, so localize asks
  for them only when two nodes share the activity).
- web / host_vnc: the URL and title of the page the Playwright controller already holds. A browser
  that is not connected is never launched for this: no identity, pixels decide.

Every read is best effort: any failure returns None and Localize falls back to pixels.
"""
from typing import Any, Dict, Optional

from shared.src.lib.utils.localize_identity import identity_kind, parse_activity, screen_texts

ACTIVITY_TIMEOUT_S = 5


def _run_coroutine(value, timeout: float = 10.0):
    """The Playwright controller's methods are coroutines (they hop onto its own loop). Run one
    to completion from any caller, with or without an event loop of its own, on a short-lived
    thread (the same asyncio.run the web routes use)."""
    import asyncio
    if not asyncio.iscoroutine(value):
        return value
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, value).result(timeout=timeout)


def _android_remote(device):
    remote = device._get_controller('remote')
    if remote is None or not getattr(remote, 'adb_utils', None) or not getattr(remote, 'android_device_id', None):
        return None
    return remote


def android_texts(device) -> Optional[list]:
    remote = _android_remote(device)
    if remote is None:
        return None
    ok, elements, _err = remote.adb_utils.dump_elements(remote.android_device_id, reason='localize identity')
    return screen_texts(elements) if ok else None


def read_identity(device, with_texts: bool = False) -> Optional[Dict[str, Any]]:
    kind = identity_kind(getattr(device, 'device_model', None))
    try:
        if kind == 'android':
            remote = _android_remote(device)
            if remote is None:
                return None
            ok, out, _err, _code = remote.adb_utils.execute_command(
                f"adb -s {remote.android_device_id} shell dumpsys activity activities", timeout=ACTIVITY_TIMEOUT_S)
            found = parse_activity(out) if ok else None
            if not found:
                return None
            ident = {'kind': 'android', 'package': found[0], 'activity': found[1]}
            if with_texts:
                texts = android_texts(device)
                if texts is not None:
                    ident['texts'] = texts
            return ident
        if kind == 'web':
            web = device._get_controller('web')
            if web is None or not getattr(web.__class__, '_browser', None) or not getattr(web.__class__, '_context', None):
                return None
            info = _run_coroutine(web.get_page_info())
            if not (info or {}).get('success') or not info.get('url') or info['url'] == 'about:blank':
                return None
            return {'kind': 'web', 'url': info['url'], 'title': info.get('title') or ''}
    except Exception as e:
        print(f"[@device_identity] {kind} identity not read: {e}")
    return None


def web_viewport_box(device, img_w: int, img_h: int):
    """(x, y, w, h) of the browser page inside the device's captured frame; None for a non-web device, a browser
    that is not connected, or any failure (the whole frame is then used, as before)."""
    try:
        if identity_kind(getattr(device, 'device_model', None)) != 'web':
            return None
        web = device._get_controller('web')
        if web is None or not getattr(web.__class__, '_browser', None) or not getattr(web.__class__, '_context', None):
            return None
        from shared.src.lib.utils.web_viewport import VIEWPORT_JS, viewport_box
        res = _run_coroutine(web.execute_javascript(VIEWPORT_JS))
        if not (res or {}).get('success'):
            return None
        return viewport_box(res.get('result') or res.get('output_data', {}).get('result') or {}, img_w, img_h)
    except Exception as e:
        print(f"[@device_identity] web viewport not read: {e}")
        return None


def fingerprint_frame(img_bgr, device):
    """(frame to fingerprint, box or None): a web device's page area, any other device's whole frame."""
    if img_bgr is None:
        return img_bgr, None
    h, w = img_bgr.shape[:2]
    box = web_viewport_box(device, w, h)
    if not box:
        return img_bgr, None
    from shared.src.lib.utils.web_viewport import crop_to_box
    return crop_to_box(img_bgr, box), box
