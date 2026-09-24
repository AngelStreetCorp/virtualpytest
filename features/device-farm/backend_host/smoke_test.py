"""Tier-B smoke test: prove one real farm session end to end.

This is the gate TASK-20 §4 records as `Gate: none` — everything unit tests cannot
reach because it needs a real account: that the endpoint host is right, that the
farm accepts these capabilities, that a device is allocated, that screenshots and
the element tree come back, and that the session is released instead of running
until the farm reaps it (which is billed either way).

Run it on a host whose .env has a cloud slot configured:

    PYTHONPATH=. python3 features/device-farm/backend_host/smoke_test.py --device device4

It prints PASS/FAIL per step and exits non-zero on the first failure, so the output
can be pasted back as evidence. The access key is never printed: the capabilities
go through redact(), and only the first line of a WebDriver error is shown, because
the rest of it is the request — and the request carries the key.
"""
import argparse
import os
import sys
import time


def _bootstrap_path() -> None:
    """Allow running as a plain script from the repo root."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, '..', '..', '..'))
    if root not in sys.path:
        sys.path.insert(0, root)


_bootstrap_path()

import importlib  # noqa: E402  (after the path bootstrap)

config = importlib.import_module('features.device-farm.lib.config')
providers = importlib.import_module('features.device-farm.lib.providers')
session_mod = importlib.import_module('features.device-farm.backend_host.session')
slots = importlib.import_module('features.device-farm.backend_host.slots')

_failures = []


def step(name: str, ok: bool, detail: str = '') -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{f' — {detail}' if detail else ''}")
    if not ok:
        _failures.append(name)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default=None,
                        help='slot id, e.g. device4 (default: the first cloud slot in .env)')
    parser.add_argument('--key', default='HOME', help='key to press (default: HOME)')
    parser.add_argument('--keep-open', action='store_true',
                        help='do NOT release the session at the end (it stays billed)')
    args = parser.parse_args()

    device_id = args.device
    if not device_id:
        found = slots.farm_slot_ids()
        if not found:
            print('No cloud slot in this .env: set DEVICE{i}_MODEL=cloud_android_mobile '
                  '(or cloud_ios_mobile). See features/device-farm/README.md.')
            return 2
        device_id = found[0]
    print(f'Device slot: {device_id}\n')

    cfg, missing = slots.farm_config_for(device_id)
    if not step('slot is configured', cfg is not None,
                '' if cfg else f"missing {', '.join(missing)}"):
        return 1
    print(f'       {cfg}')   # FarmConfig.__str__ is already redacted

    provider = providers.get_provider(cfg.provider)
    step('provider resolved', True, f'{provider.name} at {provider.endpoint_url(cfg)}')
    if cfg.provider not in providers.FULLY_IMPLEMENTED:
        print(f'       note: {cfg.provider} has no REST half yet — the app upload, device '
              f'listing and artifact steps below will be skipped')

    # --- the session ---------------------------------------------------------
    session = session_mod.get_session(cfg)
    started = time.time()
    utils = session.utils()
    if not step('session opened', utils is not None,
                session.last_error or f'{session.session_id} in {time.time() - started:.1f}s'):
        return 1

    try:
        artifacts = None
        if cfg.provider in providers.FULLY_IMPLEMENTED:
            try:
                artifacts = provider.session_artifacts(cfg, session.session_id)
                step('session page', bool(artifacts and artifacts.session_url),
                     (artifacts.session_url if artifacts else ''))
            except NotImplementedError as e:
                step('session page', False, str(e))

        resolution = utils.get_device_resolution(device_id)
        step('device resolution', bool(resolution), str(resolution))

        ok, elements, error = utils.dump_elements(device_id)
        step('element dump', ok and bool(elements),
             f'{len(elements)} elements' if ok else error)

        ok, screenshot, error = utils.take_screenshot(device_id)
        step('screenshot', ok and bool(screenshot),
             f'{len(screenshot)} base64 chars' if ok else error)

        frame_path = slots.frame_path_for(device_id)
        if frame_path:
            driver = session.driver_if_open()
            png = driver.get_screenshot_as_png() if driver else b''
            tmp = f'{frame_path}.tmp'
            os.makedirs(os.path.dirname(frame_path) or '.', exist_ok=True)
            with open(tmp, 'wb') as fh:
                fh.write(png)
            os.replace(tmp, frame_path)
            step('frame written where ffmpeg reads it', bool(png), frame_path)
        else:
            print('[SKIP] frame write — this slot has no DEVICE*_VIDEO image path')

        ok = utils.execute_key_command(device_id, args.key)
        step(f'key {args.key}', ok)

    finally:
        if args.keep_open:
            print('\nSession left OPEN (--keep-open): it is billed until the farm reaps it.')
        else:
            session_mod.release_session(device_id)
            step('session released', session_mod.peek_session(device_id) is None)

    print()
    if _failures:
        print(f'FAILED: {", ".join(_failures)}')
        return 1
    print('All steps passed — the farm path works end to end.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
