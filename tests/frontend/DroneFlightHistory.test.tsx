import { fireEvent, render, screen, within } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';

import { DroneFlightHistory } from '../../frontend/src/components/drone/DroneFlightHistory';
import {
  describeCommand, groupFlights, outcomeOf, pathOf, sentNote, seriesOf, type DroneCommand,
} from '../../frontend/src/components/drone/flightHistory';

let seq = 0;
const cmd = (over: Partial<DroneCommand>): DroneCommand => ({
  ts: '2026-10-14T09:00:00.000Z', seq: ++seq, command: 'move', params: {}, sent: null, success: true, reply: 'ok', blocked: false, landed: false,
  error: null, duration_ms: 1000, airborne: true, bat: 90, h: 80, pose: { x: 100, y: 100 }, flight: 1, ...over,
});
const at = (s: number) => `2026-10-14T09:00:${String(s).padStart(2, '0')}.000Z`;

// two flights and a refused command on the ground: the shape the controller's log has (see shared/src/lib/drone/command_log.py)
const COMMANDS: DroneCommand[] = [
  cmd({ ts: at(0), command: 'takeoff', sent: 'takeoff', flight: 0, success: false, blocked: true, error: 'battery 14% is below the take-off floor', airborne: false, bat: 14, h: 0 }),
  cmd({ ts: at(10), command: 'takeoff', sent: 'takeoff', flight: 1, bat: 92, h: 0, airborne: false, pose: { x: 100, y: 100 } }),
  cmd({ ts: at(14), command: 'move', params: { direction: 'forward', cm: 150 }, sent: 'forward 150', bat: 91, h: 80, pose: { x: 100, y: 250 } }),
  cmd({ ts: at(20), command: 'move', params: { direction: 'up', cm: 400 }, sent: 'up 70', bat: 90, h: 148, pose: { x: 100, y: 250 } }),
  cmd({ ts: at(26), command: 'move', params: { direction: 'right', cm: 900 }, sent: null, success: false, blocked: true, error: 'outside the room', bat: 89, h: 148, pose: { x: 100, y: 250 } }),
  cmd({ ts: at(30), command: 'rotate', params: { direction: 'cw', deg: 90 }, sent: 'cw 90', bat: 88, h: 148, pose: { x: 100, y: 250 } }),
  cmd({ ts: at(34), command: 'land', sent: 'land', bat: 87, h: 8, pose: { x: 100, y: 250 }, landed: true }),
  cmd({ ts: at(50), command: 'takeoff', sent: 'takeoff', flight: 2, bat: 60, h: 0, airborne: false }),
  cmd({ ts: at(55), command: 'land', sent: 'land', flight: 2, bat: 58, h: 5 }),
];

describe('flightHistory helpers', () => {
  it('groups commands into flights, newest first, with the numbers of each', () => {
    const flights = groupFlights(COMMANDS);
    expect(flights.map((f) => f.flight)).toEqual([2, 1, 0]);
    const f1 = flights.find((f) => f.flight === 1)!;
    expect(f1.commands).toHaveLength(6);
    expect(f1.blocked).toBe(1);
    expect(f1.minBattery).toBe(87);
    expect(f1.maxHeightM).toBeCloseTo(1.48);
    expect(flights.find((f) => f.flight === 0)!.blocked).toBe(1);
  });

  it('tells ok, blocked and failed apart', () => {
    expect(outcomeOf(COMMANDS[2])).toBe('ok');
    expect(outcomeOf(COMMANDS[4])).toBe('blocked');
    expect(outcomeOf(cmd({ success: false, blocked: false }))).toBe('failed');
  });

  it('describes commands and notices a command the guard shortened', () => {
    expect(describeCommand(COMMANDS[2])).toBe('move forward 150 cm');
    expect(describeCommand(COMMANDS[5])).toBe('rotate cw 90°');
    expect(describeCommand(cmd({ command: 'rc', params: { lr: 0, fb: 30, ud: 0, yaw: 0 } }))).toBe('stick 0 30 0 0');
    expect(sentNote(COMMANDS[2])).toBeNull();            // sent as asked
    expect(sentNote(COMMANDS[3])).toBe('up 70');         // asked up 400
    expect(sentNote(COMMANDS[4])).toBeNull();            // blocked: nothing was sent
  });

  it('series and path skip commands without a reading or a pose', () => {
    const f1 = groupFlights(COMMANDS).find((f) => f.flight === 1)!;
    expect(seriesOf(f1).battery.map((p) => p.v)).toEqual([92, 91, 90, 89, 88, 87]);
    expect(seriesOf(f1).height.map((p) => p.v)).toEqual([0, 0.8, 1.48, 1.48, 1.48, 0.08]);
    const noPose = { ...f1, commands: [cmd({ pose: null })] };
    expect(pathOf(noPose)).toEqual([]);
    expect(pathOf(f1).filter((p) => p.outcome === 'blocked')).toHaveLength(1);
  });
});

describe('DroneFlightHistory', () => {
  const open = (commands: DroneCommand[]) => render(<DroneFlightHistory open onClose={() => {}} deviceName="Tello-1" commands={commands} />);

  it('lists the flights and opens the newest one', () => {
    open(COMMANDS);
    const items = screen.getAllByTestId('flight-item');
    expect(items.map((i) => i.textContent)).toEqual([
      expect.stringContaining('Flight 2'), expect.stringContaining('Flight 1'), expect.stringContaining('On the ground'),
    ]);
    expect(items[1].textContent).toContain('1 blocked');
    expect(items[0].getAttribute('aria-pressed')).toBe('true');
    expect(screen.getAllByTestId('command-row')).toHaveLength(2);
  });

  it('shows a flight as a timeline with the blocked command highlighted and its reason', () => {
    open(COMMANDS);
    fireEvent.click(screen.getAllByTestId('flight-item')[1]);
    const rows = screen.getAllByTestId('command-row');
    expect(rows.map((r) => r.getAttribute('data-outcome'))).toEqual(['ok', 'ok', 'ok', 'blocked', 'ok', 'ok']);
    const blocked = rows[3];
    expect(within(blocked).getByText('Blocked')).toBeTruthy();
    expect(within(blocked).getByText('outside the room')).toBeTruthy();
    expect(within(rows[2]).getByText('up 70 (shortened)')).toBeTruthy();
    expect(within(rows[0]).getByText('OK')).toBeTruthy();
  });

  it('draws the battery and height charts and the path, with the blocked command marked on each', () => {
    open(COMMANDS);
    fireEvent.click(screen.getAllByTestId('flight-item')[1]);
    expect(screen.getByTestId('chart-battery')).toBeTruthy();
    expect(screen.getByTestId('chart-height')).toBeTruthy();
    expect(screen.getAllByTestId('chart-blocked-tick')).toHaveLength(2);       // one tick per chart
    expect(screen.getByTestId('flight-path')).toBeTruthy();
    expect(screen.getAllByTestId('path-blocked')).toHaveLength(1);
  });

  it('says so when a flight has no position', () => {
    open([cmd({ pose: null, flight: 1 })]);
    expect(screen.getByTestId('path-empty')).toBeTruthy();
  });

  it('has an empty state', () => {
    open([]);
    expect(screen.getByTestId('history-empty').textContent).toContain('No commands recorded yet');
  });
});
