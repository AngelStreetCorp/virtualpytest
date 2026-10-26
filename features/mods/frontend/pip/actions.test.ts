import { describe, expect, it } from 'vitest';

import type { ControlChangeEvent } from '../../../../frontend/src/mods/core/types';

import {
  applyControlChange,
  clampPosition,
  initialPipState,
  isPaused,
  remoteShown,
  selectDevice,
  setCollapsed,
  setPosition,
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

describe('PiP collapsed state', () => {
  it('starts expanded and flips on toggle', () => {
    expect(initialPipState.collapsed).toBe(false);
    const s1 = setCollapsed(watching, true);
    expect(s1.collapsed).toBe(true);
    const s2 = setCollapsed(s1, true);
    expect(s2).toBe(s1); // idempotent
    expect(setCollapsed(s1, false).collapsed).toBe(false);
  });
});

describe('PiP drag position', () => {
  it('keeps a position inside the viewport unchanged', () => {
    const pos = { x: -120, y: -160 };
    const rect = { left: 620, top: 344, right: 1260, bottom: 744 };
    const out = clampPosition(pos, rect, 1280, 800);
    expect(out).toEqual(pos);
  });

  it('clamps the panel back inside when dragged off the right edge', () => {
    // Panel sits at right=1320 (> viewport.width=1280). dx needed = 1320 - (1280-8) = 48.
    const pos = { x: 0, y: 0 };
    const rect = { left: 680, top: 400, right: 1320, bottom: 800 };
    const out = clampPosition(pos, rect, 1280, 800);
    expect(out.x).toBe(-48);
  });

  it('clamps the panel back inside when dragged off the bottom edge', () => {
    // Panel sits at bottom=850 (> viewport.height=800). dy needed = 850 - (800-8) = 58.
    const pos = { x: 0, y: 0 };
    const rect = { left: 20, top: 450, right: 660, bottom: 850 };
    const out = clampPosition(pos, rect, 1280, 800);
    expect(out.y).toBe(-58);
  });

  it('clamps the panel back inside when dragged off the left edge', () => {
    // Panel sits at left=-12 (< margin=8). dx needed = 8 - (-12) = 20.
    const pos = { x: 0, y: 0 };
    const rect = { left: -12, top: 20, right: 628, bottom: 420 };
    const out = clampPosition(pos, rect, 1280, 800);
    expect(out.x).toBe(20);
  });

  it('centres a panel that is wider than the viewport', () => {
    // 700px HDMI panel in a 600px window: clamp centres it horizontally. targetLeft = (600-700)/2 = -50.
    // Current rect.left = -50, so dx = 0; the panel already centred horizontally.
    const pos = { x: 0, y: 0 };
    const rect = { left: -50, top: 0, right: 650, bottom: 400 };
    const out = clampPosition(pos, rect, 600, 800);
    expect(out.x).toBe(0);
  });

  it('saves a clamped offset and is idempotent when the input already fits', () => {
    const rect = { left: 620, top: 344, right: 1260, bottom: 744 };
    const pos = { x: -120, y: -160 };
    const state = setPosition(watching, pos, rect, 1280, 800);
    expect(state.position).toEqual(pos);
    expect(setPosition(state, pos, rect, 1280, 800)).toBe(state); // no change → same ref
  });
});