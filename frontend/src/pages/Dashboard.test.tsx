// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { summaryFixture, systemFixture } from '../components/dashboard/dashboard.fixtures';

const mocks = vi.hoisted(() => ({ role: 'tester' as string, refresh: vi.fn() }));

vi.mock('../contexts/auth/PermissionContext', () => ({
  usePermissionContext: () => ({ role: mocks.role, hasRole: (r: string | string[]) => (Array.isArray(r) ? r : [r]).includes(mocks.role) }),
}));
vi.mock('../contexts/auth/AuthContext', () => ({ useAuthContext: () => ({ profile: { id: 'user-1' } }) }));
vi.mock('../hooks/useToast', () => ({ useToast: () => ({ showError: vi.fn(), showWarning: vi.fn() }) }));
vi.mock('../hooks/useDeviceFavorites', () => ({ useDeviceFavorites: () => ({ isFavorite: () => false, toggle: vi.fn(), count: 0, items: [] }) }));
vi.mock('../hooks/useResponsiveMode', () => ({ useResponsiveMode: () => ({ isMobile: false }) }));
vi.mock('../components/dashboard/HostsDevicesView', () => ({ default: () => <div data-testid="hosts-view" /> }));
vi.mock('../components/dashboard/useDashboardData', () => ({
  useDashboardData: () => ({
    data: { summary: summaryFixture, system: systemFixture, summaryError: false, systemError: false, loading: false },
    generatedAt: Date.now() - 12_000,
    refresh: mocks.refresh,
  }),
}));

import Dashboard from './Dashboard';

const renderPage = (url = '/') =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <Dashboard />
    </MemoryRouter>,
  );

beforeEach(() => {
  window.localStorage.clear();
  mocks.role = 'tester';
  mocks.refresh.mockClear();
});
afterEach(cleanup);

const tabNames = () => screen.getAllByRole('tab').map((t) => t.textContent);

describe('Dashboard page', () => {
  it('opens on Overview, with Hosts and devices one click away', () => {
    renderPage();
    expect(screen.getByTestId('dash-card-trend')).toBeTruthy();
    expect(screen.queryByTestId('hosts-view')).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: /Hosts and devices/ }));
    expect(screen.getByTestId('hosts-view')).toBeTruthy();
  });

  it('shares one slot in the tab row: filters on Hosts, the range toggle elsewhere, never both', () => {
    renderPage();
    const slot = screen.getByTestId('dash-filter-slot');
    expect(getComputedStyle(slot).display).toBe('none');
    fireEvent.click(screen.getByRole('tab', { name: /Hosts and devices/ }));
    expect(getComputedStyle(screen.getByTestId('dash-filter-slot')).display).toBe('flex');
    expect(getComputedStyle(document.querySelector('[aria-label="Time range"]') as HTMLElement).display).toBe('none');
  });

  it('shows tabs per role', () => {
    renderPage();
    expect(tabNames()).toEqual(['Overview', 'Hosts and devices', 'Scripts', 'Devices']);
    cleanup();
    mocks.role = 'viewer';
    renderPage();
    expect(tabNames()).toEqual(['Overview', 'Hosts and devices', 'Devices']);
    cleanup();
    mocks.role = 'admin';
    renderPage();
    expect(tabNames()).toContain('System');
  });

  it('remembers the favourite tab and falls back when the role loses it', () => {
    mocks.role = 'admin';
    renderPage();
    fireEvent.click(screen.getByTestId('dash-fav-system'));
    cleanup();
    renderPage();
    expect(screen.getByTestId('dash-card-storage')).toBeTruthy();
    cleanup();
    mocks.role = 'viewer';
    renderPage();
    expect(screen.getByTestId('dash-card-trend')).toBeTruthy();
  });

  it('is view only: no run or start control anywhere', () => {
    mocks.role = 'admin';
    renderPage();
    expect(screen.queryByRole('button', { name: /new run|start|run/i })).toBeNull();
  });

  it('customize drawer toggles a card and resets the tab', () => {
    renderPage();
    expect(screen.getByTestId('dash-card-trend')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Customize' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Trend' }));
    expect(screen.queryByTestId('dash-card-trend')).toBeNull();
    fireEvent.click(screen.getByText('Reset this tab to default'));
    expect(screen.getByTestId('dash-card-trend')).toBeTruthy();
  });

  it('kiosk hides the header, rotates every 30 s and refreshes, Esc leaves', () => {
    vi.useFakeTimers();
    try {
      renderPage('/?kiosk=1');
      expect(screen.getByTestId('dash-kiosk')).toBeTruthy();
      expect(screen.queryByRole('tab')).toBeNull();
      expect(screen.getByTestId('dash-card-trend')).toBeTruthy();
      act(() => {
        vi.advanceTimersByTime(30_000);
      });
      expect(mocks.refresh).toHaveBeenCalled();
      expect(screen.queryByTestId('dash-card-trend')).toBeNull();
      expect(screen.getByTestId('hosts-view')).toBeTruthy();
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(screen.queryByTestId('dash-kiosk')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
