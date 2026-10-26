import { describe, expect, it } from 'vitest';

import {
  hostHasDeviceWithId,
  isTargetKeyCompatibleWithRules,
  NO_DECLARED_RULES,
} from '../../frontend/src/utils/targetCompatibility';
import type { Host } from '../../frontend/src/types/common/Host_Types';

/**
 * QA-OPS-19 — the Run page silently dropped the operator's target when a script
 * with no declared compatibility rules was picked.
 *
 * Two independent things dropped it, and both had to be fixed:
 *
 * 1. The page answered "does this script fit this target" in two places with
 *    two different defaults. The executable LIST treated a rule-less script as
 *    compatible with everything; the target PRUNING treated it as 'device'
 *    only, and a host-level target (the `host` pseudo-device, i.e. the host_vnc
 *    browser device) is not a 'device' as far as that check goes. The list
 *    showed the script, the operator took it, and the target was deleted.
 * 2. The key normalisation dropped every target whose device id reads 'host',
 *    decided on the string alone — so the browser target died with it.
 *
 * The shared default (NO_DECLARED_RULES) is what keeps the two halves in
 * step, and `hostHasDeviceWithId` is what tells a browser device apart from
 * "the host".
 */

const hostWithBrowserDevice = {
  host_name: 'labox-backend',
  devices: [
    { device_id: 'host', device_model: 'host_vnc', device_name: 'labox-backend' },
  ],
} as unknown as Host;

const hostWithStbOnly = {
  host_name: 'vpt-pi1',
  devices: [
    { device_id: 'stb1', device_model: 'stb', device_name: 'stb1' },
  ],
} as unknown as Host;

const hostWithPhone = {
  host_name: 'labox-mobile',
  devices: [
    { device_id: 'device1', device_model: 'android_mobile', device_name: 'Phone slot 1' },
  ],
} as unknown as Host;

describe('a script that declares no rules', () => {
  it('fits a host-level (host_vnc) target', () => {
    expect(
      isTargetKeyCompatibleWithRules('labox-backend:host', [hostWithBrowserDevice], NO_DECLARED_RULES),
    ).toBe(true);
  });

  it('fits a real device target', () => {
    expect(
      isTargetKeyCompatibleWithRules('labox-mobile:device1', [hostWithPhone], NO_DECLARED_RULES),
    ).toBe(true);
  });
});

describe('a script that declares its own rules', () => {
  it('a device-typed script does not fit a host-level target (host vs device)', () => {
    // Unchanged by the fix: `target_type: 'device'` means a real device, and
    // the executable list hides such a script for a host-level target, so the
    // two directions stay consistent.
    expect(
      isTargetKeyCompatibleWithRules(
        'labox-backend:host',
        [hostWithBrowserDevice],
        { target_type: 'device', device_model: 'all' },
      ),
    ).toBe(false);
  });

  it('a device-typed script for another model does not fit a host_vnc device', () => {
    expect(
      isTargetKeyCompatibleWithRules(
        'labox-mobile:device1',
        [hostWithPhone],
        { target_type: 'device', device_model: 'host_vnc' },
      ),
    ).toBe(false);
  });

  it('a host-typed script fits a host-level target on a host that has the browser device', () => {
    expect(
      isTargetKeyCompatibleWithRules(
        'labox-backend:host',
        [hostWithBrowserDevice],
        { target_type: 'host', device_model: 'all' },
      ),
    ).toBe(true);
  });

  it('a host-typed script does not fit a host that has no browser device', () => {
    // The "Host created with 0 devices" case the guard was written for.
    expect(
      isTargetKeyCompatibleWithRules(
        'vpt-pi1:host',
        [hostWithStbOnly],
        { target_type: 'host', device_model: 'all' },
      ),
    ).toBe(false);
  });
});

describe('hostHasDeviceWithId', () => {
  it('is true for the host_vnc pseudo-device, whose id reads "host"', () => {
    expect(hostHasDeviceWithId(hostWithBrowserDevice, 'host')).toBe(true);
  });

  it('is false for a host that has no such device', () => {
    expect(hostHasDeviceWithId(hostWithStbOnly, 'host')).toBe(false);
  });

  it('is true for a real device', () => {
    expect(hostHasDeviceWithId(hostWithPhone, 'device1')).toBe(true);
  });

  it('is false for an unknown device', () => {
    expect(hostHasDeviceWithId(hostWithPhone, 'device9')).toBe(false);
  });

  it('is false for an unknown host', () => {
    expect(hostHasDeviceWithId(undefined, 'host')).toBe(false);
  });
});
