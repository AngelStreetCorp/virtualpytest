/**
 * The drone tile must say exactly one thing at a time.
 *
 * Three regressions, all reported from the same tile on 2026-10-13:
 *
 *  1. "Loading stream…" rendered on top of the drone's own "Checking…", so one
 *     question got two answers and the generic one is always wrong for a drone
 *     (it only streams once paired and flying).
 *  2. A drone that is off was rescanned every 20s forever; now one scan, then the Scan button.
 *  3. A failed poll keeps `error` until the NEXT poll settles, so the tile sat
 *     on "vpt-pi4 cannot be reached" for up to 20s while it was already retrying.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import React from 'react';

import {
  useDroneWifiStatus,
  droneHeadline,
  droneHintLine,
  pinnedSsidFromName,
  SCAN_WINDOW_MS,
} from '../../frontend/src/hooks/rec/useDroneWifiStatus';
import { TelloRemote, TAKEOFF_ARM_MS, droneHorizontalSpeedMs, droneHeightM } from '../../frontend/src/components/controller/remote/TelloRemote';
import { batteryBars } from '../../frontend/src/components/rec/DroneBatteryBadge';

// --- the hook, in isolation -------------------------------------------------

/** Drives the real hook with a stubbed api client. */
function Harness({ enabled = true, name, passive }: { enabled?: boolean; name?: string; passive?: boolean }) {
  const status = useDroneWifiStatus(
    { host_name: 'vpt-pi4' } as never,
    { device_id: 'device3', device_name: name } as never,
    enabled,
    { passive }
  );
  return (
    <div>
      <span data-testid="state">{status.state}</span>
      <span data-testid="bat">{String(status.telemetry.bat ?? '')}</span>
      <span data-testid="paused">{String(status.paused)}</span>
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
  // BUG-0636 switched useDroneWifiStatus from buildServerUrl to buildHostServerUrl.
  // Without this mock entry the hook's import resolves to undefined and the very
  // first api.post builds "TypeError: buildHostServerUrl is not a function", which
  // poll() catches and turns into state='error'. That broke every test that asserts
  // on the link state (busy, ap-not-found, connected, telemetry.bat) and any later
  // assertion in tests that mount <TelloRemote>, since the render itself survives
  // but the link state never reaches 'connected'. When the host passed to the hook
  // does not have a `server_url`, the real implementation falls back to
  // buildServerUrl(endpoint), so the URL is still `https://host${endpoint}` —
  // mirroring that fallback here keeps the existing URL-contains expectations valid.
  buildHostServerUrl: (_host: unknown, p: string) => `https://host${p}`,
}));
const executeRemoteCommand = vi.fn();
vi.mock('../../frontend/src/hooks/controller/useControllerApi', () => ({
  useControllerApi: () => ({ executeRemoteCommand }),
}));
async function settle() {
  // No waitFor(): it drives its own timers and deadlocks against fake timers.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
}

describe('useDroneWifiStatus — no scan loop for a drone that is off', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    apiGet.mockReset().mockResolvedValue({ success: true, linked: false });
    apiPost.mockReset().mockResolvedValue({ success: true, tellos: [] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('scans for the whole window on open, then waits for the Scan button', async () => {
    render(<Harness />);
    // No waitFor(): it drives its own timers and deadlocks against fake timers.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // Still scanning inside the window: no "not found" yet.
    expect(screen.getByTestId('busy')).toHaveTextContent('true');
    expect(screen.getByTestId('state')).not.toHaveTextContent('ap-not-found');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SCAN_WINDOW_MS + 1000);
    });
    expect(screen.getByTestId('state')).toHaveTextContent('ap-not-found');
    expect(screen.getByTestId('busy')).toHaveTextContent('false');
    expect(screen.getByTestId('paused')).toHaveTextContent('true');
    const scans = apiPost.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(120000);
    });
    expect(apiPost.mock.calls.length).toBe(scans);
  });

  it('a refresh opens on the stream of a drone that was live a moment ago', async () => {
    window.localStorage.setItem(
      'virtualpytest:drone-link:vpt-pi4:device3',
      JSON.stringify({ ssid: 'TELLO-C5B142', ts: Date.now() })
    );
    apiGet.mockResolvedValue({ success: true, linked: false, associated: true, video_live: true, ssid: 'TELLO-C5B142' });
    render(<Harness />);
    // Before any poll settles: already connected, no placeholder round trip.
    expect(screen.getByTestId('state')).toHaveTextContent('connected');
    window.localStorage.clear();
  });

  it('one scan press finds a drone that only shows up on the third host scan', async () => {
    let scans = 0;
    apiPost.mockImplementation(async (url: string) => {
      if (url.includes('/tello/scan')) {
        scans += 1;
        return { success: true, tellos: scans >= 3 ? [{ ssid: 'TELLO-C5B142', signal: 60 }] : [] };
      }
      return { success: true }; // pair
    });
    render(<Harness name="Tello-C5B142" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(scans).toBe(3);
    const pairCalls = apiPost.mock.calls.filter((c) => String(c[0]).includes('/tello/pair'));
    expect(pairCalls).toHaveLength(1);
    expect(screen.getByTestId('state')).toHaveTextContent('connected');
  });

  it('a slot named Tello-F014A0 never pairs another Tello in range', async () => {
    apiPost.mockResolvedValue({ success: true, tellos: [{ ssid: 'TELLO-C5B142', signal: 80 }] });
    render(<Harness name="Tello-F014A0" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SCAN_WINDOW_MS + 1000);
    });
    expect(screen.getByTestId('state')).toHaveTextContent('ap-not-found');
    const pairCalls = apiPost.mock.calls.filter((c) => String(c[0]).includes('/tello/pair'));
    expect(pairCalls).toHaveLength(0);
  });

  it('a drone the host is still on is paired — no scan, no second pair', async () => {
    apiGet.mockResolvedValue({ success: true, linked: true, associated: true, ssid: 'TELLO-C5B142', connected: true });
    render(<Harness />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(screen.getByTestId('state')).toHaveTextContent('connected');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(apiPost).not.toHaveBeenCalled();
  });
});

describe('droneHintLine — never blame a request that is already being retried', () => {
  it('shows no hint while a scan is in flight — the Scanning chip says it', () => {
    expect(droneHintLine('error', true)).toBe('');
    expect(droneHintLine('ap-not-found', true)).toBe('');
  });

  it('keeps the error hint once the poll has actually failed, and names no host', () => {
    const line = droneHintLine('error', false);
    expect(line).toBe('Power on the drone');
    expect(line).not.toMatch(/vpt-pi4|cannot be reached/i);
  });

  it('shows the action hint when the access point is missing', () => {
    expect(droneHintLine('ap-not-found', false)).toBe('Power on the drone');
  });

  it('never repeats the SSID — the headline already names the drone', () => {
    expect(droneHintLine('connecting', true)).toBe('');
    expect(droneHintLine('unknown', false)).toBe('');
  });
});

describe('droneHeadline — names the drone once its AP is known', () => {
  it('says which drone was found or is missing', () => {
    expect(droneHeadline('connecting', 'Tello-F014A0', 'Tello-C5B142')).toBe('Tello-F014A0 found');
    expect(droneHeadline('ap-not-found', 'Tello-F014A0', 'Tello-C5B142')).toBe('Tello-F014A0 not found');
    expect(droneHeadline('error', 'Tello-F014A0', 'Drone')).toBe('Could not pair Tello-F014A0');
  });

  it('does not repeat the card title', () => {
    expect(droneHeadline('ap-not-found', 'Tello-C5B142', 'Tello-C5B142')).toBe('Drone not found');
    expect(droneHeadline('connecting', 'Tello-C5B142', 'tello-c5b142')).toBe('Drone found');
    expect(droneHeadline('ap-not-found', null, 'Tello-C5B142')).toBe('Drone not found');
  });
});



describe('pinnedSsidFromName — a Tello card name pins its slot to that drone', () => {
  it('maps Tello-XXXXXX to its SSID and ignores any other name', () => {
    expect(pinnedSsidFromName('Tello-F014A0')).toBe('TELLO-F014A0');
    expect(pinnedSsidFromName(' tello-c5b142 ')).toBe('TELLO-C5B142');
    expect(pinnedSsidFromName('Drone')).toBeNull();
    expect(pinnedSsidFromName('Tello-XYZ')).toBeNull();
    expect(pinnedSsidFromName(null)).toBeNull();
  });
});


describe('drone readings and the remote panel (owner requests 2026-10-13)', () => {
  const host = { host_name: 'vpt-pi4', devices: [{ device_id: 'device3', device_name: 'Tello-C5B142' }] } as never;

  beforeEach(() => {
    vi.useFakeTimers();
    window.localStorage.clear();
    apiGet.mockReset();
    apiPost.mockReset().mockResolvedValue({ success: true, tellos: [] });
    executeRemoteCommand.mockReset().mockResolvedValue({
      success: true, airborne: false, telemetry: { bat: 76, vgx: 0, vgy: 0, vgz: 0, h: 0 },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('a paired drone reports its battery from the status route', async () => {
    apiGet.mockResolvedValue({
      success: true, linked: true, associated: true, ssid: 'TELLO-C5B142', connected: true, telemetry: { bat: 76, temph: 48 },
    });
    render(<Harness name="Tello-C5B142" />);
    await settle();
    expect(screen.getByTestId('bat')).toHaveTextContent('76');
  });

  it('a passive reader (stream modal header) never scans or pairs', async () => {
    apiGet.mockResolvedValue({ success: true, linked: false });
    render(<Harness passive />);
    await settle();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(apiPost).not.toHaveBeenCalled();
  });

  it('a lost drone greys every control and offers Scan', async () => {
    apiGet.mockResolvedValue({ success: true, linked: false });
    render(<TelloRemote host={host} deviceId="device3" isCollapsed={false} />);
    await settle();
    expect(screen.getByText('Not paired')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Scanning…' })).toBeDisabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SCAN_WINDOW_MS + 1000);
    });
    expect(screen.getByRole('button', { name: 'Scan' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Take off' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Emergency stop' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Up' })).toBeDisabled();
    expect(screen.getByLabelText('Not linked')).toBeInTheDocument();
    expect(screen.queryByText(/Pair Tello/)).toBeNull();
  });

  it('take off needs a second tap within a few seconds', async () => {
    apiGet.mockResolvedValue({ success: true, linked: true, associated: true, ssid: 'TELLO-C5B142', connected: true });
    render(<TelloRemote host={host} deviceId="device3" isCollapsed={false} />);
    await settle();
    const takeoffCalls = () => executeRemoteCommand.mock.calls.filter((c) => c[0] === 'takeoff');

    fireEvent.click(screen.getByRole('button', { name: 'Take off' }));
    expect(takeoffCalls()).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Tap again to take off' })).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TAKEOFF_ARM_MS + 10);
    });
    expect(screen.getByRole('button', { name: 'Take off' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Take off' }));
    fireEvent.click(screen.getByRole('button', { name: 'Tap again to take off' }));
    await settle();
    expect(takeoffCalls()).toHaveLength(1);
  });

  it('controls enable while the take-off runs, and roll back when it fails', async () => {
    apiGet.mockResolvedValue({ success: true, linked: true, associated: true, ssid: 'TELLO-C5B142', connected: true });
    let finish: (v: unknown) => void = () => undefined;
    executeRemoteCommand.mockImplementation((cmd: string) =>
      cmd === 'takeoff'
        ? new Promise((r) => { finish = r; })
        : Promise.resolve({ success: true, airborne: false, telemetry: { bat: 76 } }));
    render(<TelloRemote host={host} deviceId="device3" isCollapsed={false} />);
    await settle();
    expect(screen.getByRole('slider', { name: 'Move pad' })).toHaveAttribute('aria-disabled', 'true');

    fireEvent.click(screen.getByRole('button', { name: 'Take off' }));
    fireEvent.click(screen.getByRole('button', { name: 'Tap again to take off' }));
    await settle();
    expect(screen.getByRole('button', { name: 'Taking off…' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Move pad' })).toHaveAttribute('aria-disabled', 'false');
    expect(screen.getByRole('button', { name: 'Emergency stop' })).toBeInTheDocument();
    // A telemetry poll saying "landed" mid take-off does not grey the controls again.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.getByRole('slider', { name: 'Move pad' })).toHaveAttribute('aria-disabled', 'false');

    await act(async () => {
      finish({ success: false, error: 'blocked: battery 15% below takeoff floor 40%' });
    });
    await settle();
    expect(screen.getByRole('button', { name: 'Take off' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Move pad' })).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText(/below takeoff floor/)).toBeInTheDocument();
  });

  it('shows HS in m/s and H in m, 0 when landed, everything greyed below the main button', async () => {
    apiGet.mockResolvedValue({ success: true, linked: true, associated: true, ssid: 'TELLO-C5B142', connected: true });
    render(<TelloRemote host={host} deviceId="device3" isCollapsed={false} />);
    await settle();
    expect(screen.getByText('0.0 m/s')).toBeInTheDocument();
    expect(screen.getByText('0.0 m')).toBeInTheDocument();
    expect(screen.getByLabelText('Linked')).toBeInTheDocument();
    expect(screen.queryByText(/room fence|no GPS —|Click Find|km\/h|Take off to fly/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Emergency stop' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Flip forward' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Rotate left' })).toBeDisabled();
    expect(screen.getByRole('slider', { name: 'Move pad' })).toHaveAttribute('aria-disabled', 'true');
  });

  it('never puts a tooltip over the move pad, not even while it is held (owner report 2026-10-22)', async () => {
    apiGet.mockResolvedValue({ success: true, linked: true, associated: true, ssid: 'TELLO-C5B142', connected: true });
    executeRemoteCommand.mockResolvedValue({ success: true, airborne: true, telemetry: { bat: 76, h: 80 } });
    render(<TelloRemote host={host} deviceId="device3" isCollapsed={false} />);
    await settle();
    const pad = screen.getByRole('slider', { name: 'Move pad' });
    // Hover, then press and keep the pointer down — the whole flight the pointer rests here, so a
    // hover tooltip parks itself over the pad and the operator cannot see the stick they steer with.
    fireEvent.pointerEnter(pad);
    fireEvent.mouseEnter(pad);
    fireEvent.pointerDown(pad, { pointerId: 1 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.queryByText('Move: forward, back, left, right')).toBeNull();
    expect(document.querySelector('[role="tooltip"]')).toBeNull();
    fireEvent.pointerUp(pad, { pointerId: 1 });
    await settle();
  });

  it('never puts a tooltip over the round hold buttons either (owner report 2026-10-22)', async () => {
    apiGet.mockResolvedValue({ success: true, linked: true, associated: true, ssid: 'TELLO-C5B142', connected: true });
    executeRemoteCommand.mockResolvedValue({ success: true, airborne: true, telemetry: { bat: 76, h: 80 } });
    render(<TelloRemote host={host} deviceId="device3" isCollapsed={false} />);
    await settle();
    // Up, Down, Rotate left and Rotate right are press-and-hold for the whole flight, so the
    // pointer never leaves them and a hover tooltip parks itself over the panel the operator reads.
    for (const name of ['Rotate left', 'Rotate right', 'Up', 'Down']) {
      const button = screen.getByRole('button', { name });
      fireEvent.pointerEnter(button);
      fireEvent.mouseEnter(button);
      fireEvent.pointerDown(button, { pointerId: 1 });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1200);
      });
      expect(screen.queryByText(name)).toBeNull();
      expect(document.querySelector('[role="tooltip"]')).toBeNull();
      fireEvent.pointerUp(button, { pointerId: 1 });
      await settle();
    }
  });

  it('a held pad or button streams rc and the release sends the stop', async () => {
    apiGet.mockResolvedValue({ success: true, linked: true, associated: true, ssid: 'TELLO-C5B142', connected: true });
    executeRemoteCommand.mockResolvedValue({ success: true, airborne: true, telemetry: { bat: 76, h: 80 } });
    render(<TelloRemote host={host} deviceId="device3" isCollapsed={false} />);
    await settle();
    // jsdom has no PointerEvent: without one fireEvent drops clientX/clientY.
    if (!(window as any).PointerEvent) (window as any).PointerEvent = class extends MouseEvent {
      pointerId: number;
      constructor(type: string, init: any = {}) { super(type, init); this.pointerId = init.pointerId ?? 0; }
    };
    const pad = screen.getByRole('slider', { name: 'Move pad' });
    pad.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100, right: 100, bottom: 100, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.pointerDown(pad, { clientX: 50, clientY: 0, pointerId: 1 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });
    const rc = () => executeRemoteCommand.mock.calls.filter((c) => c[0] === 'rc').map((c) => c[1]);
    expect(rc().length).toBeGreaterThanOrEqual(3);
    expect(rc()[0]).toEqual({ lr: 0, fb: 100, ud: 0, yaw: 0 });
    fireEvent.pointerUp(pad, { pointerId: 1 });
    await settle();
    expect(rc()[rc().length - 1]).toEqual({ lr: 0, fb: 0, ud: 0, yaw: 0 });

    fireEvent.pointerDown(screen.getByRole('button', { name: 'Up' }), { pointerId: 2 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150);
    });
    expect(rc()[rc().length - 1]).toEqual({ lr: 0, fb: 0, ud: 100, yaw: 0 });
    fireEvent.pointerUp(screen.getByRole('button', { name: 'Up' }), { pointerId: 2 });
    await settle();
    expect(rc()[rc().length - 1]).toEqual({ lr: 0, fb: 0, ud: 0, yaw: 0 });
    const count = rc().length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(rc().length).toBe(count);
  });
});

describe('speed and battery maths', () => {
  it('HS from vgx/vgy (dm/s) in m/s and H from h (cm) in m, 0 on the ground', () => {
    expect(droneHorizontalSpeedMs({ vgx: 10, vgy: 0, vgz: 30 }, true)).toBe(1);
    expect(droneHorizontalSpeedMs({ vgx: 3, vgy: 4 }, true)).toBe(0.5);
    expect(droneHorizontalSpeedMs({ vgx: 10 }, false)).toBe(0);
    expect(droneHeightM({ h: 85 }, true)).toBe(0.9);
    expect(droneHeightM({ h: 85 }, false)).toBe(0);
  });

  it('fills 0-4 bars', () => {
    expect(batteryBars(0)).toBe(0);
    expect(batteryBars(20)).toBe(1);
    expect(batteryBars(76)).toBe(4);
    expect(batteryBars(100)).toBe(4);
  });
});
