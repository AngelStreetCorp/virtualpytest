import { describe, expect, it } from 'vitest';

import type { ControlChangeEvent } from '../../../../frontend/src/mods/core/types';

import {
  applyControlChange,
  initialPipState,
  isPaused,
  remoteShown,
  selectDevice,
  shouldReleaseOnPause,
  streamPosition,
} from './actions';
import { PIP_SESSION_ID } from './constants';
import type { PipState } from './types';

const change = (over: Partial<ControlChangeEvent> = {}): ControlChangeEvent => ({
  hostName: 'vpt-pi1',
  deviceId: 'device1',
  active: true,
  owner: 'navigation-editor-session',
  timestamp: 0,
  ...over,
});
const watching: PipState = { ...initialPipState, selection: { hostName: 'vpt-pi1', deviceId: 'device2' } };

describe('picture-in-picture', () => {
  it('pauses while a page controls a device, and resumes on release', () => {
    const s = applyControlChange(watching, change());
    expect(isPaused(s)).toBe(true);
    expect(isPaused(applyControlChange(s, change({ active: false })))).toBe(false);
  });

  it('ignores its own control', () => {
    expect(applyControlChange(watching, change({ owner: PIP_SESSION_ID }))).toBe(watching);
  });

  it('releases its own control on pause, except when the page took the same device', () => {
    const owning = { ...watching, ownsControl: true };
    expect(shouldReleaseOnPause(applyControlChange(owning, change()))).toBe(true);
    expect(shouldReleaseOnPause(applyControlChange(owning, change({ deviceId: 'device2' })))).toBe(false);
  });

  it('shows the remote only with control, and moves the stream left beside it', () => {
    expect(remoteShown(watching)).toBe(false);
    const owning = { ...watching, ownsControl: true };
    expect(remoteShown(owning)).toBe(true);
    expect(remoteShown({ ...owning, remoteVisible: false })).toBe(false);
    expect(streamPosition(true).left).toBeDefined();
    expect(streamPosition(false).right).toBeDefined();
  });

  it('drops control ownership when switching device', () => {
    const owning = { ...watching, ownsControl: true };
    expect(selectDevice(owning, { hostName: 'vpt-pi2', deviceId: 'device1' }).ownsControl).toBe(false);
    expect(selectDevice(owning, watching.selection)).toBe(owning);
  });
});
