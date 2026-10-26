/** Pure rules of the picture-in-picture mod. */
import type { ControlChangeEvent } from '../../../../frontend/src/mods/core/types';

import { BOTTOM, EDGE, PIP_SESSION_ID } from './constants';
import type { PipPosition, PipSelection, PipState, StreamPosition } from './types';

/** Minimum gap between the panel edge and the viewport edge after a drag (px). */
const VIEWPORT_MARGIN = 8;

export const initialPipState: PipState = {
  selection: null,
  remoteVisible: true,
  ownsControl: false,
  controlBusy: false,
  pageControls: {},
  collapsed: false,
  position: null,
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

export const setCollapsed = (state: PipState, collapsed: boolean): PipState =>
  state.collapsed === collapsed ? state : { ...state, collapsed };

/**
 * Clamp a drag offset so the panel never opens off-screen, given the panel's actual
 * rendered rect after the drag and the viewport size in CSS px. Works for either anchor
 * (bottom-right or bottom-left, depending on whether the remote is shown) because we
 * measure the rect, not the anchor offsets.
 *
 * If the panel is wider / taller than the viewport minus twice the margin (a 700 px
 * HDMI panel in a 600 px window, for example), it is centred instead so the user can
 * still see the middle of it.
 */
export const clampPosition = (
  pos: PipPosition,
  rect: { left: number; top: number; right: number; bottom: number },
  viewportW: number,
  viewportH: number,
): PipPosition => {
  const panelW = rect.right - rect.left;
  const panelH = rect.bottom - rect.top;
  let dx = 0;
  let dy = 0;

  if (panelW >= viewportW - 2 * VIEWPORT_MARGIN) {
    // Panel wider than the viewport — centre horizontally.
    const targetLeft = Math.round((viewportW - panelW) / 2);
    dx += targetLeft - rect.left;
  } else if (rect.left < VIEWPORT_MARGIN) {
    dx += VIEWPORT_MARGIN - rect.left;
  } else if (rect.right > viewportW - VIEWPORT_MARGIN) {
    dx -= rect.right - (viewportW - VIEWPORT_MARGIN);
  }

  if (panelH >= viewportH - 2 * VIEWPORT_MARGIN) {
    const targetTop = Math.round((viewportH - panelH) / 2);
    dy += targetTop - rect.top;
  } else if (rect.top < VIEWPORT_MARGIN) {
    dy += VIEWPORT_MARGIN - rect.top;
  } else if (rect.bottom > viewportH - VIEWPORT_MARGIN) {
    dy -= rect.bottom - (viewportH - VIEWPORT_MARGIN);
  }

  return { x: Math.round(pos.x + dx), y: Math.round(pos.y + dy) };
};

/** Save the drag offset, clamped to the viewport so a stale saved position (the user
 * resized their window down after dragging) cannot reopen the panel off-screen.
 *
 * Pure: no DOM access. The overlay calls it with the panel's bounding rect after a
 * pointer-up event.
 */
export const setPosition = (
  state: PipState,
  pos: PipPosition,
  rect: { left: number; top: number; right: number; bottom: number },
  viewportW: number,
  viewportH: number,
): PipState => {
  const clamped = clampPosition(pos, rect, viewportW, viewportH);
  if (state.position?.x === clamped.x && state.position?.y === clamped.y) return state;
  return { ...state, position: clamped };
};