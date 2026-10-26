import { fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AnalysedFrameLayer from '../../frontend/src/components/monitoring/AnalysedFrameLayer';
import { MAX_LEAD_S, ProfileOverlay } from '../../frontend/src/components/monitoring/ProfileOverlay';
import type { MonitoringAnalysis, ProfileUi } from '../../frontend/src/types/pages/Monitoring_Types';

afterEach(() => vi.restoreAllMocks());

const EGG_UI: ProfileUi = {
  title: 'Egg quality control',
  headline: { kpi: 'count_total', label: 'eggs inspected' },
  counters: { kpi: 'count_by_condition', items: [{ key: 'good', colour: 'green' }, { key: 'bad', colour: 'red' }] },
  box: { shape: 'ellipse', badge: 'votes', colour_by: 'verdict' },
};

const analysis = (over: Partial<MonitoringAnalysis> = {}): MonitoringAnalysis =>
  ({
    timestamp: 't',
    filename: 'capture_000459168.jpg',
    profile: 'egg_quality',
    frame_size: [1280, 720],
    observations: [
      { label: 'egg', track_id: 765, bbox: [100, 200, 60, 60], votes: '2/3', verdict: null, v: [136, 26], shape: { ellipse: [130, 230, 60, 60, 0] } },
    ],
    kpis: { count_total: 746, count_by_condition: { good: 6, bad: 613 } },
    ui: EGG_UI,
    captured_at: new Date(Date.now() - 400).toISOString(),
    ...over,
  }) as MonitoringAnalysis;

describe('the analysed frame under the overlay (BUG-0836)', () => {
  it('hides the live stream behind a backdrop, with no switch in the corner', () => {
    render(<AnalysedFrameLayer url="http://host/capture_000459168.jpg" active frameLocked />);
    expect(screen.getByTestId('analysed-frame')).toBeTruthy();
    // the picture itself is drawn by the overlay, in the boxes' coordinates (BUG-0913)
    expect(screen.queryByTestId('analysed-frame-img')).toBeNull();
    // owner, 2026-10-26: the "analysed frame / live stream" toggle was not understandable and is gone
    expect(screen.queryByTestId('frame-lock-switch')).toBeNull();
  });

  it('draws nothing at all when no profile overlay is active (tv_app, or a cold monitor)', () => {
    const { container } = render(<AnalysedFrameLayer url="http://host/x.jpg" active={false} frameLocked />);
    expect(container.firstChild).toBeNull();
  });
});

describe('frame-locked means the boxes are NOT carried forward', () => {
  it('ignores the frame age when the picture IS that frame', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 900, height: 400, top: 0, left: 0, right: 900, bottom: 400, x: 0, y: 0, toJSON: () => ({}) });
    render(<ProfileOverlay analysis={analysis()} frameLocked />);
    // v = [136, 26] px/s on a 400 ms-old frame would move the centre by +54 / +10 px. Frame-locked: it must not.
    const e = screen.getAllByTestId('profile-ellipse')[0];
    expect(Number(e.getAttribute('cx'))).toBe(130);
    expect(Number(e.getAttribute('cy'))).toBe(230);
    expect(Number(e.getAttribute('opacity'))).toBe(1);      // nothing faded either
    expect(screen.queryByTestId('profile-sync')).toBeNull();          // no "locked to the analysed frame" label
  });

  it('still carries the boxes forward on the live stream, and fades them once the estimate is old', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 900, height: 400, top: 0, left: 0, right: 900, bottom: 400, x: 0, y: 0, toJSON: () => ({}) });
    const { unmount } = render(<ProfileOverlay analysis={analysis()} frameLocked={false} />);
    const moved = screen.getAllByTestId('profile-ellipse')[0];
    expect(Number(moved.getAttribute('cx'))).toBeGreaterThan(160);   // 130 + 136 px/s x ~0.4 s
    unmount();
    render(<ProfileOverlay analysis={analysis({ captured_at: new Date(Date.now() - MAX_LEAD_S * 4000).toISOString() })} frameLocked={false} />);
    expect(Number(screen.getAllByTestId('profile-ellipse')[0].getAttribute('opacity'))).toBeLessThan(0.3);
  });

  it('toggling frameLocked does not change the number of hooks (a conditional hook would crash here)', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 900, height: 400, top: 0, left: 0, right: 900, bottom: 400, x: 0, y: 0, toJSON: () => ({}) });
    const { rerender } = render(<ProfileOverlay analysis={analysis()} frameLocked={false} />);
    expect(() => rerender(<ProfileOverlay analysis={analysis()} frameLocked />)).not.toThrow();
    expect(screen.getAllByTestId('profile-ellipse')).toHaveLength(1);
  });
});

describe('the picture and its boxes are one drawing (BUG-0913)', () => {
  const rect = () =>
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1900, height: 880, top: 0, left: 0, right: 1900, bottom: 880, x: 0, y: 0, toJSON: () => ({}) });

  it('draws the capture inside the boxes SVG, in frame pixels, once it has loaded', () => {
    rect();
    render(<ProfileOverlay analysis={analysis()} frameLocked frameUrl="http://host/capture_000459168.jpg" />);
    expect(screen.queryByTestId('analysed-frame-img')).toBeNull();          // not before it loaded
    fireEvent.load(screen.getByTestId('analysed-frame-preload'));
    const img = screen.getByTestId('analysed-frame-img');
    expect(img.closest('svg')).toBe(screen.getByTestId('profile-shapes'));   // same coordinate system as the boxes
    expect(img.getAttribute('href')).toBe('http://host/capture_000459168.jpg');
    expect([img.getAttribute('width'), img.getAttribute('height')]).toEqual(['1280', '720']);
    expect(img.getAttribute('preserveAspectRatio')).toBe('none');
  });

  it('keeps the previous picture WITH its own boxes until the next capture has loaded', () => {
    rect();
    const { rerender } = render(<ProfileOverlay analysis={analysis()} frameLocked frameUrl="http://host/a.jpg" />);
    fireEvent.load(screen.getByTestId('analysed-frame-preload'));
    const next = analysis({ filename: 'capture_000459169.jpg', observations: [{ label: 'egg', track_id: 766, bbox: [400, 200, 60, 60], shape: { ellipse: [430, 230, 60, 60, 0] } }] } as Partial<MonitoringAnalysis>);
    rerender(<ProfileOverlay analysis={next} frameLocked frameUrl="http://host/b.jpg" />);
    expect(screen.getByTestId('analysed-frame-img').getAttribute('href')).toBe('http://host/a.jpg');
    expect(Number(screen.getAllByTestId('profile-ellipse')[0].getAttribute('cx'))).toBe(130);
    fireEvent.load(screen.getByTestId('analysed-frame-preload'));
    expect(screen.getByTestId('analysed-frame-img').getAttribute('href')).toBe('http://host/b.jpg');
    expect(Number(screen.getAllByTestId('profile-ellipse')[0].getAttribute('cx'))).toBe(430);
  });
});

describe('a count-only focus panel (owner, 2026-10-26)', () => {
  it('shows no purple "…" and no voting line when the profile has no verdict', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1900, height: 880, top: 0, left: 0, right: 1900, bottom: 880, x: 0, y: 0, toJSON: () => ({}) });
    const ui = { title: 'Egg count', stats: [{ label: 'Eggs', kpi: 'count_total' }], box: { shape: 'ellipse' }, focus_panel: { crop: true, probs: false, title: 'Last egg' } } as unknown as ProfileUi;
    render(<ProfileOverlay analysis={analysis({ ui, focus: { track_id: 261, check: 2, checks: 2, verdict: null, final: false, probs: {}, crop: null } } as Partial<MonitoringAnalysis>)} frameLocked />);
    expect(screen.getByTestId('profile-focus')).toBeTruthy();
    expect(screen.queryByTestId('profile-focus-verdict')).toBeNull();
    expect(screen.queryByText(/check #/)).toBeNull();
  });
});
