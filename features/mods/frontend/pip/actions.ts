/** Pure rules of the picture-in-picture mod. */
import type { ControlChangeEvent } from '../../../../frontend/src/mods/core/types';

import { BOTTOM, EDGE, PIP_SESSION_ID } from './constants';
import type { PipSelection, PipState, StreamPosition } from './types';

export const initialPipState: PipState = {
  selection: null,
  remoteVisible: true,
  ownsControl: false,
  controlBusy: false,
  pageControls: {},
};

export const deviceKey = (s: PipSelection) => `${s.hostName}:${s.deviceId}`;

export const sameDevice = (a: PipSelection | null, b: PipSelection | null) =>
  !!a && !!b && a.hostName === b.hostName && a.deviceId === b.deviceId;

/** Track what pages control; PiP's own takes and releases are ignored. */
export const applyControlChange = (state: PipState, e: ControlChangeEvent): PipState => {
  if (e.owner === PIP_SESSION_ID) return state;
  const key = deviceKey(e);
  const has = key in state.pageControls;
  if (e.active === has) return state;
  const pageControls = { ...state.pageControls };
  if (e.active) pageControls[key] = { hostName: e.hostName, deviceId: e.deviceId };
  else delete pageControls[key];
  return { ...state, pageControls };
};

/** A page controls a device: PiP steps aside so two streams never show at once. */
export const isPaused = (state: PipState) => Object.keys(state.pageControls).length > 0;

/**
 * On pause, PiP releases its own control, unless a page took that same device: the lock
 * is then shared by this browser session and releasing it would cut the page off.
 */
export const shouldReleaseOnPause = (state: PipState) =>
  state.ownsControl && !!state.selection && !(deviceKey(state.selection) in state.pageControls);

export const remoteShown = (state: PipState) => state.ownsControl && state.remoteVisible && !isPaused(state);

export const streamPosition = (withRemote: boolean): StreamPosition =>
  withRemote ? { left: EDGE, bottom: BOTTOM } : { right: EDGE, bottom: BOTTOM };

export const selectDevice = (state: PipState, selection: PipSelection | null): PipState =>
  sameDevice(state.selection, selection) ? state : { ...state, selection, ownsControl: false };

export const toggleRemote = (state: PipState): PipState => ({ ...state, remoteVisible: !state.remoteVisible });
