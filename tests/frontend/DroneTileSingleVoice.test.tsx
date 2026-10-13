/**
 * The drone tile must say exactly one thing at a time.
 *
 * Three regressions, all reported from the same tile on 2026-10-13:
 *
 *  1. "Loading stream…" rendered on top of the drone's own "Checking…", so one
 *     question got two answers and the generic one is always wrong for a drone
 *     (it only streams once paired and flying).
 *  2. The 20s rescan was invisible, so a parked drone looked frozen.
 *  3. A failed poll keeps `error` until the NEXT poll settles, so the tile sat
 *     on "vpt-pi4 cannot be reached" for up to 20s while it was already retrying.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import React from 'react';

import {
  useDroneWifiStatus,
  droneHintLine,
} from '../../frontend/src/hooks/rec/useDroneWifiStatus';

// --- the hook, in isolation -------------------------------------------------

/** Drives the real hook with a stubbed api client. */
function Harness({ enabled = true }: { enabled?: boolean }) {
  const status = useDroneWifiStatus(
    { host_name: 'vpt-pi4' } as never,
    { device_id: 'device3' } as never,
    enabled
  );
  return (
    <div>
      <span data-testid="state">{status.state}</span>
      <span data-testid="countdown">{status.secondsToNextScan}</span>
      <span data-testid="busy">{String(status.busy)}</span>
    </div>
  );
}

const apiGet = vi.fn();
const apiPost = vi.fn();

vi.mock('../../frontend/src/utils/apiClient', () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
}));
vi.mock('../../frontend/src/utils/buildUrlUtils', () => ({
  buildServerUrl: (p: string) => `https://host${p}`,
}));

describe('useDroneWifiStatus countdown', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    apiGet.mockReset().mockResolvedValue({ success: true, linked: false });
    apiPost.mockReset().mockResolvedValue({ success: true, tellos: [] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('counts down from the 20s poll period and never below 1', async () => {
    render(<Harness />);
    // No waitFor() here: it drives its own timers and deadlocks against
    // vi.useFakeTimers(). Flush the initial poll by draining microtasks.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(screen.getByTestId('state')).toHaveTextContent('ap-not-found');

    // The period is 20s, so the countdown starts there.
    expect(screen.getByTestId('countdown')).toHaveTextContent('20');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByTestId('countdown')).toHaveTextContent('17');

    // Well past one full period it must wrap, never render 0 or a negative.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    const n = Number(screen.getByTestId('countdown').textContent);
    expect(n).toBeGreaterThanOrEqual(1);
    expect(n).toBeLessThanOrEqual(20);
  });

  it('resets the countdown to a full period while not enabled', async () => {
    render(<Harness enabled={false} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByTestId('countdown')).toHaveTextContent('20');
  });
});
// --- the hint line, in isolation ------------------------------------------

describe('droneHintLine — never blame a request that is already being retried', () => {
  it('drops the error hint while a scan is in flight', () => {
    // Nothing at all while a retry is running: the chip already reads
    // "Scanning…", so a second line saying something is the duplication again.
    expect(droneHintLine('error', true, null, null)).toBe('');
    expect(droneHintLine('error', true, 'TELLO-F014A0', 60)).toBe('');
  });

  it('still shows the SSID while connecting — that is progress, not a stale complaint', () => {
    expect(droneHintLine('connecting', true, 'TELLO-F014A0', null)).toBe('TELLO-F014A0');
  });

  it('keeps the error hint once the poll has actually failed, and names no host', () => {
    // A failed pair can happen after a successful scan — the host was reachable.
    // Blaming "vpt-pi4" there was wrong, and it sat on screen for 20s.
    const line = droneHintLine('error', false, null, null);
    expect(line).toBe('Could not reach the drone');
    expect(line).not.toMatch(/vpt-pi4|cannot be reached/i);
  });

  it('shows the action hint when the access point is missing', () => {
    expect(droneHintLine('ap-not-found', false, null, null)).toBe('Power on the drone');
  });

  it('prefers the SSID, then the signal, and stays empty when there is nothing', () => {
    expect(droneHintLine('unknown', false, 'TELLO-ABC', 42)).toBe('TELLO-ABC');
    expect(droneHintLine('unknown', false, null, 42)).toBe('signal 42%');
    expect(droneHintLine('unknown', false, null, null)).toBe('');
  });
});
