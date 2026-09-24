/**
 * Device model families on the frontend side.
 *
 * `frontend/src/config/deviceModelFamilies.ts` is the mirror of MODEL_FAMILIES in
 * `shared/src/lib/config/device_capabilities.py`. The backend filters
 * `getCompatibleInterfaces` with the Python copy; the page filters hosts, campaign
 * targets and script `_target_rules` with this one. A drift between them shows up as a
 * userinterface the server offers and the page hides — so the table itself is compared
 * for drift in `tests/shared/test_device_model_families.py`, and what is pinned here is
 * the behaviour the three frontend matchers get from it.
 *
 * The bug this replaced: matching was exact-string `includes`, so a userinterface built
 * for `android_mobile` was invisible to a paired phone (`phone_agent`) and to a cloud
 * farm phone (`cloud_android_mobile`), and near-duplicate userinterfaces had to be
 * created per transport.
 */
import { describe, expect, it } from 'vitest';

import {
  expandModels,
  getCompatibleModels,
  getModelFamily,
  modelMatchesAny,
  modelsAreCompatible,
} from '../../frontend/src/config/deviceModelFamilies';
import { isDeviceCompatibleWithInterface } from '../../frontend/src/utils/userinterface/deviceCompatibilityUtils';
import { isHostCompatibleWithRules } from '../../frontend/src/utils/targetCompatibility';

const ANDROID_PHONES = [
  'android_mobile',
  'phone_agent',
  'cloud_android_mobile',
  'runner_android_mobile',
];

const device = (model: string) => ({ device_model: model }) as any;
const ui = (models: string[]) => ({ id: 'ui', name: 'ui', models }) as any;
const host = (models: string[]) =>
  ({
    host_name: 'host1',
    devices: models.map((m, i) => ({ device_id: `device${i + 1}`, device_model: m })),
  }) as any;

describe('model families', () => {
  it.each(ANDROID_PHONES)('%s is an android phone', (model) => {
    expect(getModelFamily(model)).toBe('android_phone');
  });

  it('a model in no family is its own family', () => {
    expect(getCompatibleModels('stb')).toEqual(['stb']);
    expect(getCompatibleModels('brand_new_thing')).toEqual(['brand_new_thing']);
  });

  it('empty input matches nothing', () => {
    expect(getCompatibleModels('')).toEqual([]);
    expect(modelMatchesAny('android_mobile', [])).toBe(false);
    expect(modelMatchesAny('android_mobile', null)).toBe(false);
    expect(modelsAreCompatible('android_mobile', '')).toBe(false);
  });

  it('a tablet is not a phone, and a TV is neither', () => {
    expect(modelsAreCompatible('android_tablet', 'android_mobile')).toBe(false);
    expect(modelsAreCompatible('android_tv', 'android_mobile')).toBe(false);
  });

  it('keeps the host_vnc rule one-directional', () => {
    // A VNC host has a browser and a desktop on it, so it can run a web interface.
    expect(modelMatchesAny('host_vnc', ['web'])).toBe(true);
    // A web device is Playwright only — a host_vnc tree is full of desktop actions.
    expect(modelMatchesAny('web', ['host_vnc'])).toBe(false);
  });

  it('expands a web interface back to the hosts that can run it', () => {
    expect(expandModels(['web'])).toContain('host_vnc');
  });
});

describe('userinterface matching', () => {
  it.each(ANDROID_PHONES)(
    '%s can use a userinterface built for android_mobile',
    (model) => {
      // `youtube-android-mobile` lists only android_mobile + phone_agent; a farm phone
      // must find it rather than needing its own `cloud_farm_demo` copy.
      expect(
        isDeviceCompatibleWithInterface(device(model), ui(['android_mobile', 'phone_agent'])),
      ).toBe(true);
    },
  );

  it('does not offer a tablet interface to a phone', () => {
    expect(isDeviceCompatibleWithInterface(device('android_mobile'), ui(['android_tablet']))).toBe(
      false,
    );
  });

  it('an interface with no models matches nothing', () => {
    expect(isDeviceCompatibleWithInterface(device('android_mobile'), ui([]))).toBe(false);
  });
});

describe('script target rules', () => {
  const rules = { target_type: 'device' as const, host_os: 'all' as const };

  it.each(ANDROID_PHONES)('a script declaring android_mobile is offered for %s', (model) => {
    expect(isHostCompatibleWithRules(host([model]), { ...rules, device_model: 'android_mobile' })).toBe(
      true,
    );
  });

  it('still honours a pipe-separated model list', () => {
    expect(
      isHostCompatibleWithRules(host(['android_tablet']), {
        ...rules,
        device_model: 'android_mobile|android_tablet',
      }),
    ).toBe(true);
  });

  it('still excludes a host with nothing matching', () => {
    expect(isHostCompatibleWithRules(host(['stb']), { ...rules, device_model: 'android_mobile' })).toBe(
      false,
    );
  });

  it('device_model "all" is unchanged', () => {
    expect(isHostCompatibleWithRules(host(['stb']), { ...rules, device_model: 'all' })).toBe(true);
  });
});
