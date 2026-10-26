import { render, screen, within } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { BADGE_ALL_UPTO, COMPACT_BELOW_PX, FOCUS_HEX, ProfileOverlay, UI_HEX } from '../../frontend/src/components/monitoring/ProfileOverlay';
import type { MonitoringAnalysis, ProfileTelemetry, ProfileUi } from '../../frontend/src/types/pages/Monitoring_Types';

const EGG_UI: ProfileUi = {
  title: 'Egg quality control',
  headline: { kpi: 'count_total', label: 'eggs inspected' },
  // BUG-0837: the shipped egg profile shows the pair instead of the headline
  stats: [
    { label: 'Eggs', kpi: 'count_total' },
    { label: 'Detections', observations: true },
  ],
  counters: {
    kpi: 'count_by_condition',
    items: [
      { key: 'good', colour: 'green' },
      { key: 'bad', colour: 'red' },
      { key: 'unverified', colour: 'grey' },
    ],
  },
  box: { shape: 'ellipse', badge: 'votes', colour_by: 'verdict' },
  focus_panel: { crop: true, probs: true, title: 'Last checked' },
};

const analysis = (over: Partial<MonitoringAnalysis> = {}): MonitoringAnalysis =>
  ({
    timestamp: 't',
    filename: 'capture_000000001.jpg',
    profile: 'egg_quality',
    frame_size: [1280, 720],
    observations: [
      { label: 'egg', track_id: 7, bbox: [100, 200, 160, 120], votes: '2/3', verdict: null, shape: { ellipse: [180, 260, 160, 120, 20] } },
      { label: 'egg', track_id: 6, bbox: [500, 220, 150, 110], votes: '3/3', verdict: 'good', shape: { ellipse: [575, 275, 150, 110, 0] } },
      { label: 'egg', track_id: 5, bbox: [900, 230, 150, 110], votes: '3/3', verdict: 'bad', shape: { ellipse: [975, 285, 150, 110, 0] } },
    ],
    kpis: { count_total: 173, count_by_condition: { good: 150, bad: 20, unverified: 3 } },
    ui: EGG_UI,
    focus: { track_id: 6, check: 3, checks: 3, verdict: 'good', final: true, probs: { good: 0.91, bad: 0.09 }, crop: 'focus_6_3.jpg' },
    ...over,
  }) as MonitoringAnalysis;

const setWidth = (w: number) =>
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: w, height: 400, top: 0, left: 0, right: w, bottom: 400, x: 0, y: 0, toJSON: () => ({}) });

afterEach(() => vi.restoreAllMocks());

describe('ProfileOverlay with a ui block', () => {
  it('draws the title, headline, counters and the last-checked panel from the manifest', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={analysis()} metadataUrl={(f) => `http://host/stream/capture1/metadata/${f}`} />);
    expect(screen.getByTestId('profile-title').textContent).toBe('Egg quality control');
    expect(within(screen.getByTestId('profile-headline')).getByText('173')).toBeTruthy();
    expect(screen.getByText('eggs inspected')).toBeTruthy();
    // one row per class, count and its share of the total side by side (BUG-0836)
    const counters = screen.getAllByTestId('profile-counter').map((c) => c.textContent);
    expect(counters).toEqual(['Good15086.7%', 'Bad2011.6%', 'Unverified31.7%']);
    expect(screen.getAllByTestId('profile-counter-pct').map((c) => c.textContent)).toEqual(['86.7%', '11.6%', '1.7%']);
    expect(screen.getAllByTestId('profile-counter-bar').map((b) => b.getAttribute('data-key'))).toEqual(['good', 'bad', 'unverified']);
    expect(screen.getByTestId('profile-focus-verdict').textContent).toBe('Good 91%');
    expect(screen.getByText('check #3 · item #6')).toBeTruthy();
    expect((screen.getByTestId('profile-focus-crop') as HTMLImageElement).src).toBe('http://host/stream/capture1/metadata/focus_6_3.jpg');
    expect(screen.getAllByTestId('profile-prob')).toHaveLength(2);
    expect(screen.getByText('91%')).toBeTruthy();
  });

  it('outlines each egg with its ellipse and a vote badge, coloured by state', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={analysis()} />);
    const ellipses = screen.getAllByTestId('profile-ellipse');
    expect(ellipses).toHaveLength(3);
    expect(screen.queryAllByTestId('profile-rect')).toHaveLength(0);
    expect(ellipses[0].getAttribute('stroke')).toBe('#b388ff');          // still voting: purple
    expect(ellipses[2].getAttribute('stroke')).toBe(UI_HEX.red);          // verdict bad
    // track 6 is the one in the "Last checked" panel, so it is gold however it was judged (BUG-0836)
    expect(ellipses[1].getAttribute('stroke')).toBe(FOCUS_HEX);
    expect(ellipses[1].getAttribute('stroke-width')).toBe(String((1280 / 400) * 1.8));
    expect(ellipses[0].getAttribute('transform')).toBe('rotate(20 180 260)');
    expect(screen.getAllByTestId('profile-badge').map((b) => b.textContent)).toEqual(['2/3', '3/3', '3/3']);
  });

  it('uses rectangles when the manifest says rect', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={analysis({ ui: { ...EGG_UI, box: { shape: 'rect', badge: 'none', colour_by: 'none' } } })} />);
    expect(screen.getAllByTestId('profile-rect')).toHaveLength(3);
    expect(screen.queryAllByTestId('profile-badge')).toHaveLength(0);
  });

  it('collapses the right panel to a narrow strip when the player is small', () => {
    setWidth(COMPACT_BELOW_PX - 100);
    render(<ProfileOverlay analysis={analysis()} />);
    expect(screen.getByTestId('profile-overlay').getAttribute('data-compact')).toBe('true');
    expect(screen.queryByTestId('profile-focus')).toBeNull();
    expect(screen.queryByText('eggs inspected')).toBeNull();
    const counters = screen.getAllByTestId('profile-counter').map((c) => c.textContent);
    expect(counters).toEqual(['15086.7%', '2011.6%', '31.7%']);             // dots, numbers and share, no label
    expect(within(screen.getByTestId('profile-headline')).getByText('173')).toBeTruthy();
  });

  it('shows Eggs and Detections side by side (BUG-0837)', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={analysis()} />);
    const stats = screen.getByTestId('profile-stats');
    // 173 eggs counted, 3 detections in this frame: the pair is the point, the gap is the point
    expect(within(stats).getByTestId('profile-stat-eggs').textContent).toBe('173Eggs');
    expect(within(stats).getByTestId('profile-stat-detections').textContent).toBe('3Detections');
    expect(screen.getAllByTestId('profile-stat-eggs')).toHaveLength(1);   // no duplicate block
  });

  it('counts Detections from the analysed frame, so it follows the frame and not the total', () => {
    setWidth(900);
    const many = analysis({
      observations: new Array(82).fill(analysis().observations[0]) as MonitoringAnalysis['observations'],
    });
    render(<ProfileOverlay analysis={many} />);
    expect(within(screen.getByTestId('profile-stats')).getByTestId('profile-stat-detections').textContent).toBe('82Detections');
    expect(within(screen.getByTestId('profile-stats')).getByTestId('profile-stat-eggs').textContent).toBe('173Eggs');
  });

  it('draws a dash for a stat whose value has not arrived, and keeps the stat row in compact mode', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={analysis({ kpis: {} } as Partial<MonitoringAnalysis>)} />);
    expect(screen.getByTestId('profile-stat-eggs').textContent).toBe('–Eggs');
    expect(screen.getByTestId('profile-stat-detections').textContent).toBe('3Detections');
  });

  it('shows an active incident in the panel', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={analysis({ incidents: { broken_rate: { active: true, value: 11.3 } } })} />);
    expect(screen.getByTestId('profile-incident').textContent).toBe('broken_rate: 11.3');
  });

  it('shows a dash instead of a number before the first KPI arrives and no focus panel without a focus', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={analysis({ kpis: undefined, focus: null })} />);
    expect(within(screen.getByTestId('profile-headline')).getByText('–')).toBeTruthy();
    expect(screen.queryByTestId('profile-focus')).toBeNull();
  });
});

// BUG-0836: the overlay is drawn on a LIVE video, so the boxes arrive late and sat next to their objects.
describe('ProfileOverlay keeping the boxes on the objects (BUG-0836)', () => {
  const moving = (over: Partial<MonitoringAnalysis> = {}): MonitoringAnalysis =>
    analysis({
      captured_at: new Date(Date.now() - 200).toISOString(), // 200 ms old, as the monitor really writes it
      observations: [
        { label: 'egg', track_id: 1, bbox: [100, 200, 160, 120], votes: '3/3', verdict: 'bad', v: [300, -60], shape: { ellipse: [180, 260, 160, 120, 0] } },
        { label: 'egg', track_id: 2, bbox: [500, 220, 150, 110], votes: '3/3', verdict: 'good', shape: { ellipse: [575, 275, 150, 110, 0] } },
      ],
      focus: null,
      ...over,
    });

  it('advances each box along its own velocity by the age of the frame', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={moving()} />);
    const [first, second] = screen.getAllByTestId('profile-ellipse');
    // Derive the expectation from the age the overlay itself reports ("sync N ms") rather than
    // from the 200 ms the fixture asked for. useOverlayAge re-reads the clock on a 100 ms tick,
    // so the committed age is anywhere in 200-300 ms — at 300 px/s that is up to 30 px of drift,
    // and no fixed tolerance can be both tight and stable. It failed on a loaded runner
    // (9.6 px off, tolerance 8). The boxes and the label are rendered from the same leadS, so
    // this asserts the same thing exactly, with no wall-clock race.
    const sync = /sync (\d+) ms/.exec(screen.getByTestId('profile-sync').textContent || '');
    expect(sync).not.toBeNull();
    const leadS = Number(sync![1]) / 1000;
    // 300 px/s and -60 px/s on the centre of the first egg (180, 260).
    expect(Math.abs(Number(first.getAttribute('cx')) - (180 + 300 * leadS))).toBeLessThan(1);
    expect(Math.abs(Number(first.getAttribute('cy')) - (260 - 60 * leadS))).toBeLessThan(1);
    // the second egg has no `v` (a tracker with no motion estimate): it stays where it was measured
    expect(Number(second.getAttribute('cx'))).toBe(575);
    expect(Number(second.getAttribute('cy'))).toBe(275);
  });

  it('says how far behind the picture is, and only when the frame JSON carries a capture time', () => {
    setWidth(900);
    const { unmount } = render(<ProfileOverlay analysis={moving()} />);
    expect(screen.getByTestId('profile-sync').textContent).toMatch(/sync \d+ ms/);
    unmount();
    render(<ProfileOverlay analysis={analysis({ captured_at: undefined })} />);
    expect(screen.queryByTestId('profile-sync')).toBeNull();
  });

  it('leaves every box where it was when the frame JSON has no capture time', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={analysis({ observations: moving().observations })} />);
    const first = screen.getAllByTestId('profile-ellipse')[0];
    expect(Number(first.getAttribute('cx'))).toBe(180);
  });

  it('fades the boxes out as the estimate ages, instead of gliding away from the object', () => {
    setWidth(900);
    const fresh = render(<ProfileOverlay analysis={moving({ captured_at: new Date(Date.now() - 50).toISOString() })} />);
    const freshOpacity = Number(screen.getAllByTestId('profile-ellipse')[0].getAttribute('opacity'));
    fresh.unmount();
    render(<ProfileOverlay analysis={moving({ captured_at: new Date(Date.now() - 1200).toISOString() })} />);
    const staleOpacity = Number(screen.getAllByTestId('profile-ellipse')[0].getAttribute('opacity'));
    expect(freshOpacity).toBeGreaterThan(staleOpacity);
    expect(staleOpacity).toBeLessThan(0.3);
  });

  it('drops the vote badges once the scene is too busy to read them, keeping the focused one', () => {
    setWidth(900);
    const many = Array.from({ length: BADGE_ALL_UPTO + 8 }, (_, i) => ({
      label: 'egg',
      track_id: 100 + i,
      bbox: [10 + i * 20, 100, 60, 60] as [number, number, number, number],
      votes: '3/3',
      verdict: 'bad',
      shape: { ellipse: [40 + i * 20, 130, 60, 60, 0] as [number, number, number, number, number] },
    }));
    render(
      <ProfileOverlay
        analysis={analysis({
          observations: many,
          focus: { track_id: 105, check: 3, checks: 3, verdict: 'bad', final: true, probs: { bad: 0.9, good: 0.1 } },
        })}
      />,
    );
    const badges = screen.getAllByTestId('profile-badge');
    expect(badges).toHaveLength(1); // one badge, on the focused egg
    expect(screen.getAllByTestId('profile-box-focus')).toHaveLength(1);
  });

  it('marks the focused item gold in the picture and names that colour in the panel', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={analysis()} />);
    expect(screen.getByTestId('profile-focus-colour').textContent).toContain('gold');
    // the gold outline is the one on the focused track
    const gold = screen.getAllByTestId('profile-ellipse').filter((e) => e.getAttribute('stroke') === FOCUS_HEX);
    expect(gold).toHaveLength(1);
    expect(Number(gold[0].getAttribute('cx'))).toBe(575);
  });
});

const AD_UI: ProfileUi = {
  title: 'Ad meter',
  headline: { kpi: 'ads_pct_today', label: 'ads', unit: '%' },
  counters: { kpi: 'breaks_by_kind', items: [{ key: 'confirmed', colour: 'red', label: 'seen before' }, { key: 'new', colour: 'amber', label: 'new' }] },
  state_badge: { event: 'ad_break', label: 'AD', colour: 'red' },
};

const adAnalysis = (over: Partial<MonitoringAnalysis> = {}): MonitoringAnalysis =>
  ({
    timestamp: 't',
    filename: 'capture_000000001.jpg',
    profile: 'ad_meter',
    frame_size: [1280, 720],
    observations: [],
    events: { ad_break: { start: 1000, duration_ms: 155000 } },
    kpis: { ads_pct_today: 11.6, breaks_by_kind: { confirmed: 2, new: 1 } },
    ui: AD_UI,
    ...over,
  }) as MonitoringAnalysis;

describe('ProfileOverlay ad_meter (state badge, percent headline)', () => {
  it('shows the AD badge with its running time while a break is in progress, and the headline with a percent sign', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={adAnalysis()} />);
    const badge = screen.getByTestId('profile-state-badge');
    expect(badge.textContent).toBe('AD 2:35');
    expect(within(screen.getByTestId('profile-headline')).getByText('11.6%')).toBeTruthy();
    expect(screen.getAllByTestId('profile-counter').map((c) => c.textContent)).toEqual(['seen before266.7%', 'new133.3%']);
    expect(screen.queryAllByTestId('profile-rect')).toHaveLength(0);
    expect(screen.queryAllByTestId('profile-ellipse')).toHaveLength(0);
  });

  it('has no badge outside a break and keeps it short in the small player', () => {
    setWidth(900);
    const { unmount } = render(<ProfileOverlay analysis={adAnalysis({ events: {} })} />);
    expect(screen.queryByTestId('profile-state-badge')).toBeNull();
    unmount();
    vi.restoreAllMocks();
    setWidth(COMPACT_BELOW_PX - 100);
    render(<ProfileOverlay analysis={adAnalysis()} />);
    expect(screen.getByTestId('profile-state-badge').textContent).toBe('AD');
  });

  it('writes minutes after the number and a dash while the KPI is not there yet', () => {
    setWidth(900);
    const ui: ProfileUi = { ...AD_UI, headline: { kpi: 'minutes_to_first_break', label: 'first break after', unit: 'min' } };
    const { unmount } = render(<ProfileOverlay analysis={adAnalysis({ ui, kpis: { minutes_to_first_break: 7.5 } })} />);
    expect(screen.getByTestId('profile-headline').textContent).toContain('7.5min');
    unmount();
    render(<ProfileOverlay analysis={adAnalysis({ ui, kpis: { minutes_to_first_break: null as unknown as number } })} />);
    expect(screen.getByTestId('profile-headline').textContent).toContain('–');
  });
});

describe('ProfileOverlay without a ui block', () => {
  it('keeps the generic boxes-and-KPIs overlay', () => {
    render(<ProfileOverlay analysis={analysis({ ui: undefined, observations: [{ label: 'car', track_id: 1, bbox: [10, 10, 100, 60] }] })} />);
    expect(screen.getAllByTestId('profile-box')).toHaveLength(1);
    expect(screen.queryByTestId('profile-panel')).toBeNull();
    expect(screen.getByText('Objects:')).toBeTruthy();
  });
});

// ---- the drone profile's HUD (TASK-90 goal 12) ----------------------------------------------------
const DRONE_UI: ProfileUi = {
  title: 'Drone',
  state_badge: { event: 'flying', label: 'FLYING', colour: 'green' },
  hud: [
    { key: 'bat', label: 'Battery', short: 'BAT', format: 'battery', unit: '%', warn_below: 20 },
    { key: 'temp', label: 'Temp', short: 'TMP', unit: '°C', warn_above: 80 },
    { key: 'alt', label: 'Alt', short: 'ALT', unit: 'm', decimals: 1 },
    { key: 'spd', label: 'Speed', short: 'SPD', unit: 'm/s', decimals: 1 },
    { key: 'ft', label: 'Flight', short: 'FLT', format: 'duration' },
    { key: 'lat', key2: 'lon', label: 'GPS', format: 'latlon' },
  ],
};

const droneAnalysis = (telemetry: ProfileTelemetry | undefined, over: Partial<MonitoringAnalysis> = {}): MonitoringAnalysis =>
  ({
    timestamp: 't',
    filename: 'capture_000000001.jpg',
    profile: 'drone',
    observations: [],
    events: { flying: { start: 1, duration_ms: 65000 } },
    kpis: {},
    ui: DRONE_UI,
    telemetry,
    ...over,
  }) as MonitoringAnalysis;

const FLYING: ProfileTelemetry = { ok: true, age: 0.2, bat: 87, temp: 62, alt: 1.2, spd: 0.5, ft: 95, fly: true };

describe('ProfileOverlay HUD (drone profile)', () => {
  it('draws battery, temperature, altitude, speed and flight time top right, and no right panel', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={droneAnalysis(FLYING)} />);
    const rows = screen.getAllByTestId('hud-row');
    expect(rows.map((r) => r.getAttribute('data-key'))).toEqual(['bat', 'temp', 'alt', 'spd', 'ft']);   // no GPS row: no fix
    const values = screen.getAllByTestId('hud-value').map((v) => v.textContent);
    expect(values).toEqual(['87%', '62 °C', '1.2 m', '0.5 m/s', '1:35']);
    expect(screen.getByTestId('hud-battery-icon').getAttribute('data-bars')).toBe('4');
    expect(screen.queryByTestId('profile-panel')).toBeNull();
    expect(screen.getByTestId('profile-state-badge').textContent).toBe('FLYING 1:05');
  });

  it('adds the GPS row when a fix comes', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={droneAnalysis({ ...FLYING, lat: 47.37691, lon: 8.54169, fix: 3 })} />);
    const gps = screen.getAllByTestId('hud-row').find((r) => r.getAttribute('data-key') === 'lat')!;
    expect(within(gps).getByTestId('hud-value').textContent).toBe('47.37691, 8.54169');
  });

  it('colours a low battery and a hot drone red, and lists the active incidents', () => {
    setWidth(900);
    render(
      <ProfileOverlay
        analysis={droneAnalysis({ ...FLYING, bat: 15, temp: 85 }, { incidents: { battery_low: { active: true, value: 9 }, temp_high: { active: false, value: 0 } } })}
      />,
    );
    const [bat, temp, alt] = screen.getAllByTestId('hud-value').map((e) => getComputedStyle(e).color);
    expect(bat).toBe(temp);                 // both the error colour
    expect(alt).not.toBe(bat);
    expect(screen.getByTestId('hud-battery-icon').getAttribute('data-bars')).toBe('1');
    expect(screen.getAllByTestId('hud-incident').map((e) => e.textContent)).toEqual(['battery low']);
  });

  it('says NO TELEMETRY instead of old numbers when the reading is stale', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={droneAnalysis({ ok: false, age: 12 })} />);
    expect(screen.getByTestId('hud-no-telemetry').textContent).toBe('NO TELEMETRY');
    expect(screen.queryAllByTestId('hud-row')).toHaveLength(0);
  });

  it('draws nothing for a frame that has no telemetry key at all', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={droneAnalysis(undefined)} />);
    expect(screen.queryByTestId('profile-hud')).toBeNull();
  });

  it('shortens the labels to three letters in the small player', () => {
    setWidth(COMPACT_BELOW_PX - 100);
    render(<ProfileOverlay analysis={droneAnalysis(FLYING)} />);
    expect(screen.getByTestId('profile-hud').getAttribute('data-compact')).toBe('true');
    expect(screen.queryByText('Battery')).toBeNull();
    expect(screen.getAllByTestId('hud-label').map((e) => e.textContent)).toEqual(['BAT', 'TMP', 'ALT', 'SPD', 'FLT']);
    expect(screen.getAllByTestId('hud-value')).toHaveLength(5);
  });

  it('keeps the right panel of profiles that have no HUD', () => {
    setWidth(900);
    render(<ProfileOverlay analysis={analysis()} metadataUrl={(f) => f} />);
    expect(screen.getByTestId('profile-panel')).toBeTruthy();
    expect(screen.queryByTestId('profile-hud')).toBeNull();
  });
});
