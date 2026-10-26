import { fireEvent, render, screen, within } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import { MonitorProfileConfirmDialog } from '../../frontend/src/components/settings/monitorProfile/MonitorProfileConfirmDialog';
import { MonitorProfileSelect } from '../../frontend/src/components/settings/monitorProfile/MonitorProfileSelect';
import { MonitorProfileStatusCard } from '../../frontend/src/components/settings/monitorProfile/MonitorProfileStatusCard';
import {
  effectiveProfile, planProfileChange, type MonitorProfileInfo, type MonitorProfileStatus, type MonitorUnits,
} from '../../frontend/src/components/settings/monitorProfile/plan';

const svc = (img: boolean, audio: boolean, subtitle: boolean) => ({ img, audio, subtitle });
const PROFILES: MonitorProfileInfo[] = [
  { name: 'tv_app', title: 'tv_app', services: svc(true, true, true), models: [], usable: true, reason: null, description: 'TV-app testing', cost: 'Nothing added.' },
  { name: 'ad_meter', title: 'Ad meter', services: svc(true, false, false), models: [], usable: true, reason: null, description: 'Share of ads', cost: 'Image monitor only, +26 MB.' },
  { name: 'counting_cars', title: 'Car counting', services: svc(true, false, false), models: [], usable: false,
    reason: 'model file missing: MONITOR_COCO_MODEL (not set)', description: 'Counts cars', cost: 'Detector.' },
];
const UNITS: MonitorUnits = {
  img: { unit: 'vpt-monitor-img', active: true },
  audio: { unit: 'vpt-monitor-audio', active: true },
  subtitle: { unit: 'vpt-monitor-subtitle', active: false },
};

describe('planProfileChange', () => {
  it('effective profile: device, then host default, then tv_app', () => {
    expect(effectiveProfile('ad_meter', 'counting_cars')).toBe('ad_meter');
    expect(effectiveProfile('', 'counting_cars')).toBe('counting_cars');
    expect(effectiveProfile('', '')).toBe('tv_app');
  });

  it('nothing changed -> no plan, no restart', () => {
    const sel = { host: '', devices: { DEVICE1: '', DEVICE2: 'ad_meter' } };
    const plan = planProfileChange(sel, { ...sel }, PROFILES, UNITS);
    expect(plan.changed).toBe(false);
    expect(plan.restarts).toEqual([]);
  });

  it('one device to ad_meter restarts the three services; the stopped subtitle unit is reported, not restarted', () => {
    const plan = planProfileChange(
      { host: '', devices: { DEVICE1: '', DEVICE2: '' } },
      { host: '', devices: { DEVICE1: 'ad_meter', DEVICE2: '' } }, PROFILES, UNITS);
    expect(plan.devices).toEqual([{ key: 'DEVICE1', from: 'tv_app', to: 'ad_meter' }]);
    expect(plan.restarts).toEqual(['img', 'audio']);
    expect(plan.notRunning).toEqual(['subtitle']);
    expect(plan.adds.map((p) => p.name)).toEqual(['ad_meter']);
  });

  it('a single-device host moving to ad_meter changes the set audio/subtitle serve', () => {
    const plan = planProfileChange({ host: '', devices: { DEVICE1: '' } }, { host: 'ad_meter', devices: { DEVICE1: '' } }, PROFILES, null);
    expect(plan.hostDefault).toEqual({ from: '', to: 'ad_meter' });
    expect(plan.restarts).toEqual(['img', 'audio', 'subtitle']);
  });

  it('writing the same effective profile through another key is not a change', () => {
    const plan = planProfileChange({ host: 'ad_meter', devices: { DEVICE1: '' } }, { host: 'ad_meter', devices: { DEVICE1: 'ad_meter' } }, PROFILES, UNITS);
    expect(plan.devices).toEqual([]);
    expect(plan.restarts).toEqual([]);
  });
});

describe('MonitorProfileSelect', () => {
  it('lists Default first and disables an unusable profile with its reason', () => {
    const onChange = vi.fn();
    render(<MonitorProfileSelect label="Monitoring profile" value="" onChange={onChange} profiles={PROFILES} defaultName="tv_app" />);
    fireEvent.mouseDown(screen.getByRole('combobox'));
    const list = within(screen.getByRole('listbox'));
    expect(list.getAllByRole('option')[0]).toHaveTextContent('Default (tv_app)');
    const cars = list.getByRole('option', { name: /Car counting/ });
    expect(cars).toHaveAttribute('aria-disabled', 'true');
    expect(cars).toHaveTextContent('MONITOR_COCO_MODEL');
    fireEvent.click(list.getByRole('option', { name: /Ad meter/ }));
    expect(onChange).toHaveBeenCalledWith('ad_meter');
  });
});

describe('MonitorProfileConfirmDialog', () => {
  const plan = planProfileChange({ host: '', devices: { DEVICE1: '' } }, { host: '', devices: { DEVICE1: 'ad_meter' } }, PROFILES, UNITS);

  it('states the services restarted, that ALL devices pause, and what the profile adds', () => {
    const onConfirm = vi.fn();
    render(<MonitorProfileConfirmDialog open hostName="pi4" plan={plan} profiles={PROFILES} onConfirm={onConfirm} onCancel={() => {}} />);
    expect(screen.getByText(/vpt-monitor-img/)).toBeInTheDocument();
    expect(screen.getByText(/all devices on this host/)).toBeInTheDocument();
    expect(screen.getByText(/may\s+resolve and reopen/)).toBeInTheDocument();
    expect(screen.getByText(/vpt-monitor-subtitle is not running/)).toBeInTheDocument();
    expect(screen.getByText(/Image monitor only, \+26 MB/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save and restart' }));
    expect(onConfirm).toHaveBeenCalled();
  });
});

describe('MonitorProfileStatusCard', () => {
  const status: MonitorProfileStatus = {
    saved: { device1: 'ad_meter', device2: 'tv_app' },
    applied: { device1: 'tv_app', device2: 'tv_app' },
    mismatch: ['device1'],
    units: UNITS,
    result: {
      state: 'done', restarted: ['vpt-monitor-img'], failed: [], not_running: ['vpt-monitor-subtitle'],
      fallbacks: [{ device: 'device2', requested: 'ghost', effective: 'tv_app', kind: 'unknown', reason: "no profile named 'ghost' on this host" }],
    },
  };

  it('flags saved-but-not-running, and shows the restart result and the fallback', () => {
    render(<MonitorProfileStatusCard status={status} profiles={PROFILES} applying={false} />);
    expect(screen.getByText(/Saved, running tv_app/)).toBeInTheDocument();
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText(/Restarted/)).toHaveTextContent('vpt-monitor-img');
    expect(screen.getByText(/not running on this host/)).toBeInTheDocument();
    expect(screen.getByText(/asks for/)).toHaveTextContent('runs as tv_app');
  });

  it('shows progress while applying', () => {
    render(<MonitorProfileStatusCard status={{ ...status, result: { state: 'applying' } }} profiles={PROFILES} applying />);
    expect(screen.getByText(/restarting the monitor services/)).toBeInTheDocument();
  });
});


describe('tv_lite in the plan (stream mode and the host services)', () => {
  const LITE: MonitorProfileInfo = {
    name: 'tv_lite', title: 'TV lite', services: { img: false, audio: false, subtitle: false, archiver: false, kpi: false, avq: false }, stream: 'lean',
    models: [], usable: true, reason: null, description: 'Stream and control only', cost: 'No monitor, archiver, KPI or AVQ; lean ffmpeg.',
  };
  const WITH_LITE = [...PROFILES, LITE];
  const before = { host: '', devices: { DEVICE1: '', DEVICE2: '' } };

  it('switching a device to tv_lite restarts the stream and the host services too, not only the monitors', () => {
    const plan = planProfileChange(before, { host: '', devices: { DEVICE1: 'tv_lite', DEVICE2: '' } }, WITH_LITE, UNITS);
    expect(plan.restartsStream).toBe(true);
    expect(plan.restartsHost).toEqual(['vpt-archiver', 'vpt-kpi', 'vpt-avq']);
    expect(plan.restarts).toEqual(['img', 'audio']);
  });

  it('a change between full-stream profiles does not touch the stream or the host services', () => {
    const plan = planProfileChange(before, { host: '', devices: { DEVICE1: 'ad_meter', DEVICE2: '' } }, WITH_LITE, UNITS);
    expect(plan.restartsStream).toBe(false);
    expect(plan.restartsHost).toEqual([]);
  });

  it('the dialog names vpt-stream and says the video drops', () => {
    const plan = planProfileChange(before, { host: '', devices: { DEVICE1: 'tv_lite', DEVICE2: '' } }, WITH_LITE, UNITS);
    render(<MonitorProfileConfirmDialog open hostName="h1" plan={plan} profiles={WITH_LITE} onConfirm={() => {}} onCancel={() => {}} />);
    const d = screen.getByTestId('monitor-profile-confirm');
    expect(within(d).getByText('vpt-stream')).toBeTruthy();
    expect(within(d).getByText('vpt-archiver')).toBeTruthy();
    expect(d.textContent).toContain('video of every device on this host');
    expect(within(d).getAllByText('TV lite').length).toBeGreaterThan(0);   // the change line and the 'what it adds' line
  });
});
