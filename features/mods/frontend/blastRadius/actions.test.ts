import { describe, expect, it } from 'vitest';

import type { DeviceCommandEvent } from '../../../../frontend/src/mods/core/types';

import { needsConfirm, warningFor } from './actions';

const cmd = (command: string): DeviceCommandEvent => ({ hostName: 'vpt-pi1', deviceId: 'device1', command, source: 'power' });

describe('blast radius', () => {
  it('asks only for power off and reboot', () => {
    expect(needsConfirm(cmd('power_off'))).toBe(true);
    expect(needsConfirm(cmd('reboot'))).toBe(true);
    expect(needsConfirm(cmd('power_on'))).toBe(false);
  });

  it('names the device and host in the warning', () => {
    const w = warningFor(cmd('reboot'));
    expect(w.confirmText).toBe('Reboot');
    expect(w.vars).toEqual({ device: 'device1', host: 'vpt-pi1' });
  });
});
