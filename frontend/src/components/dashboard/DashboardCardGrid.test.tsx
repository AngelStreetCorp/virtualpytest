// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CARD_REGISTRY } from './cards/registry';
import { DashboardCardGrid } from './DashboardCardGrid';
import { DASH_CARD_HEIGHT, DASH_KPI_HEIGHT } from './DashCard';
import { summaryFixture, systemFixture } from './dashboard.fixtures';
import { resolveTabCards } from './dashboardLayout';

afterEach(cleanup);

const favs = vi.hoisted(() => ({ items: [] as Array<{ host_name: string; device_id: string }> }));
vi.mock('../../hooks/useDeviceFavorites', () => ({
  useDeviceFavorites: () => ({ isFavorite: () => false, toggle: vi.fn(), count: favs.items.length, items: favs.items }),
}));

type Tab = 'overview' | 'scripts' | 'devices' | 'system';
const renderTab = (tab: Tab, data: Parameters<typeof DashboardCardGrid>[0]['data']) =>
  render(
    <MemoryRouter>
      <DashboardCardGrid cards={resolveTabCards(tab, 'admin', CARD_REGISTRY, undefined)} data={data} range="24h" now={Date.now()} />
    </MemoryRouter>,
  );

const loaded = { summary: summaryFixture, system: null, summaryError: false, systemError: false, loading: false };
const withSystem = { ...loaded, summary: null, system: systemFixture };

describe('DashboardCardGrid', () => {
  it('uses only the two height tokens: KPI for tiles and bands, card for the rest', () => {
    favs.items = [{ host_name: 'vpt-pi1', device_id: 'device3' }];
    renderTab('overview', loaded);
    const cards = document.querySelectorAll('[data-testid^="dash-card-"]');
    expect(cards.length).toBe(7);
    cards.forEach((el) => {
      const id = (el.getAttribute('data-testid') ?? '').replace('dash-card-', '');
      const layout = CARD_REGISTRY.find((c) => c.id === id)!.layout;
      const expected = layout === 'tile' || layout === 'band' ? DASH_KPI_HEIGHT : DASH_CARD_HEIGHT;
      expect(el.ownerDocument.defaultView!.getComputedStyle(el).height, id).toBe(`${expected}px`);
    });
    favs.items = [];
  });

  it('shows four KPI tiles that are deep links', () => {
    renderTab('overview', loaded);
    expect(screen.getByTestId('dash-card-kpi-pass').textContent).toContain('70 %');
    expect(screen.getByTestId('dash-card-kpi-devices').textContent).toContain('17 / 18');
    expect(screen.getByTestId('dash-card-kpi-failures').getAttribute('href')).toBe('/test-results/reports?status=failed&range=24h');
    expect(screen.getByTestId('dash-card-kpi-running').getAttribute('href')).toBe('/run/monitor');
  });

  it('draws the trend with a 0-100 y axis and a last-value label', () => {
    renderTab('overview', loaded);
    const chart = screen.getByTestId('trend-chart');
    ['0 %', '25 %', '50 %', '75 %', '100 %'].forEach((tick) => expect(chart.textContent).toContain(tick));
    expect(screen.getByTestId('trend-last').textContent).toBe('65 %');
  });

  it('shows a centred dash, not axes with a lone dot, when the trend has one point', () => {
    const one = { ...summaryFixture, results: { ...summaryFixture.results, trend: [summaryFixture.results.trend[0]] } };
    renderTab('overview', { ...loaded, summary: one });
    expect(screen.queryByTestId('trend-chart')).toBeNull();
    expect(screen.getByTestId('dash-card-trend').textContent).toContain('—');
  });

  it('merges problems into one list, worst first, each a deep link', () => {
    renderTab('overview', loaded);
    const card = screen.getByTestId('dash-card-attention');
    const rows = Array.from(card.querySelectorAll('a')).slice(1).map((a) => a.textContent ?? '');
    expect(rows[0]).toContain('Pixel · vpt-pi3');
    expect(rows[1]).toContain('failing_0');
    expect(rows[2]).toContain('failing_1');
    expect(card.querySelector('a[href="/test-results/runs/script/fail-0"]')).toBeTruthy();
  });

  it('says All clear when nothing needs attention', () => {
    const clean = { ...summaryFixture, failing: [], devices: { ...summaryFixture.devices, down: 0, down_items: [] } };
    renderTab('overview', { ...loaded, summary: clean });
    expect(screen.getByTestId('dash-card-attention').textContent).toContain('All clear');
  });

  it('shows favourites with a status word, and no card at all without any', () => {
    renderTab('overview', loaded);
    expect(screen.queryByTestId('dash-card-favourites')).toBeNull();
    cleanup();
    favs.items = [{ host_name: 'vpt-pi1', device_id: 'device3' }, { host_name: 'vpt-pi3', device_id: 'device1' }];
    renderTab('overview', loaded);
    const card = screen.getByTestId('dash-card-favourites');
    expect(card.textContent).toContain('device3 · vpt-pi1');
    expect(card.textContent).toContain('locked');
    expect(card.textContent).toContain('down');
    favs.items = [];
  });

  it('lists each failing script once, with fails of runs', () => {
    renderTab('scripts', loaded);
    const card = screen.getByTestId('dash-card-failing');
    expect(card.textContent?.match(/failing_0/g)).toHaveLength(1);
    expect(card.textContent).toContain('4 of 6 failed');
  });

  it('turns numbers and rows into deep links, with no run buttons', () => {
    renderTab('overview', loaded);
    const hrefs = Array.from(document.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('/test-results/reports?status=failed&range=24h');
    expect(screen.queryByText(/new run/i)).toBeNull();
  });

  it('paginates in the card header: three rows and "1-3 of N" next to the title', () => {
    const many = { ...summaryFixture, failing: Array.from({ length: 7 }, (_, i) => ({ ...summaryFixture.failing[0], script_name: `s${i}`, last_result_id: `r${i}` })) };
    renderTab('scripts', { ...loaded, summary: many });
    expect(screen.getByTestId('dash-card-failing').textContent).toContain('1–3 of 7');
  });

  it('shows devices: summary band, down and locked devices, and the per-host rows', () => {
    renderTab('devices', loaded);
    expect(screen.getByTestId('dash-card-devices').textContent).toContain('17 / 18');
    const attention = screen.getByTestId('dash-card-device-attention').textContent ?? '';
    expect(attention).toContain('Pixel · vpt-pi3');
    expect(attention.indexOf('Pixel')).toBeLessThan(attention.indexOf('anna'));
    expect(attention).toContain('anna');
    const hosts = screen.getByTestId('dash-card-hosts-table').textContent ?? '';
    expect(hosts).toContain('vpt-pi1');
    expect(hosts).toContain('12 / 12 up · 4 locked');
    expect(hosts).toContain('5 / 6 up');
  });

  it('shows every VM with status, CPU, load, RAM and disk, and the real database values', () => {
    renderTab('system', withSystem);
    const table = screen.getByTestId('vm-table');
    expect(table.querySelectorAll('[data-testid^="vm-row-"]')).toHaveLength(3);
    expect(screen.getByTestId('vm-row-database').textContent).toContain('80 %');
    expect(screen.getByTestId('vm-row-database').textContent).toContain('high');
    expect(screen.getByTestId('vm-row-storage').textContent).toContain('stale');
    expect(screen.getByTestId('dash-card-sys-services').textContent).toContain('7 / 8');
    expect(screen.getByTestId('dash-card-sys-cpu').textContent).toContain('12 %');
  });

  it('shows an honest no-data state for a null system block', () => {
    renderTab('system', { ...withSystem, system: { ...systemFixture, vms: null, services: null, ai_usage: null, storage: null } });
    expect(screen.getByTestId('dash-card-vms').textContent).toContain('No data');
    expect(screen.getByTestId('dash-card-storage').textContent).toContain('No data');
  });

  it('shows no-data when the source failed and nothing was loaded', () => {
    renderTab('system', { summary: null, system: null, summaryError: false, systemError: true, loading: false });
    expect(screen.getByTestId('dash-card-storage').textContent).toContain('No data');
  });

  describe('structural centring (UI_STYLE 16)', () => {
    const everyTab: Tab[] = ['overview', 'scripts', 'devices', 'system'];
    const style = (el: Element) => el.ownerDocument.defaultView!.getComputedStyle(el);

    it('centres every card block: flex column, justify centre, equal left and right padding', () => {
      favs.items = [{ host_name: 'vpt-pi1', device_id: 'device3' }];
      for (const tab of everyTab) {
        renderTab(tab, tab === 'system' ? withSystem : loaded);
        document.querySelectorAll('[data-testid^="dash-card-"]').forEach((el) => {
          const id = el.getAttribute('data-testid');
          const cs = style(el);
          expect(cs.display, id!).toBe('flex');
          expect(cs.flexDirection, id!).toBe('column');
          expect(cs.justifyContent, id!).toBe('center');
          expect(cs.paddingLeft, id!).toBe(cs.paddingRight);
          expect(cs.paddingTop, id!).toBe(cs.paddingBottom);
        });
        cleanup();
      }
      favs.items = [];
    });

    it('lays a KPI tile out as ONE block centred both ways: label above value, no pushing margins', () => {
      renderTab('overview', loaded);
      const tile = screen.getByTestId('dash-card-kpi-pass');
      expect(style(tile).justifyContent).toBe('center');
      expect(style(tile).alignItems).toBe('center');
      expect(style(tile.children[1] as HTMLElement).justifyContent).toBe('center');
      expect(style(tile).rowGap).not.toBe('0px');
      expect(tile.children).toHaveLength(2);
    });

    it('never uses an auto margin to push content to one edge of a card', () => {
      favs.items = [{ host_name: 'vpt-pi1', device_id: 'device3' }];
      for (const tab of everyTab) {
        renderTab(tab, tab === 'system' ? withSystem : loaded);
        document.querySelectorAll('[data-testid^="dash-card-"] *').forEach((el) => {
          const cs = style(el);
          expect(cs.marginTop, el.outerHTML.slice(0, 80)).not.toBe('auto');
          expect(cs.marginBottom, el.outerHTML.slice(0, 80)).not.toBe('auto');
        });
        cleanup();
      }
      favs.items = [];
    });

    it('centres the body of list cards and of empty states', () => {
      renderTab('scripts', { ...loaded, summary: { ...summaryFixture, running: { count: 0, queued: 0, items: [] } } });
      const running = screen.getByTestId('dash-card-running');
      const body = running.lastElementChild as HTMLElement;
      expect(style(body).justifyContent).toBe('center');
      expect(running.textContent).toContain('—');
    });
  });

  it('opens every link that leaves the dashboard in a new tab', () => {
    favs.items = [{ host_name: 'vpt-pi1', device_id: 'device3' }];
    for (const tab of ['overview', 'scripts', 'devices', 'system'] as Tab[]) {
      renderTab(tab, tab === 'system' ? withSystem : loaded);
      document.querySelectorAll('[data-testid^="dash-card-"] a, [data-testid^="dash-card-"][href]').forEach((a) => {
        expect(a.getAttribute('target'), a.getAttribute('href') ?? '').toBe('_blank');
        expect(a.getAttribute('rel')).toContain('noopener');
      });
      cleanup();
    }
    favs.items = [];
  });

  it('opens the favourites filtered: the card header and each chip carry the Device Control params', () => {
    favs.items = [{ host_name: 'vpt-pi1', device_id: 'device3' }];
    renderTab('overview', loaded);
    const card = screen.getByTestId('dash-card-favourites');
    const hrefs = Array.from(card.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('/device-control?favorites=1');
    expect(hrefs).toContain('/device-control?device=vpt-pi1%2Fdevice3');
    favs.items = [];
  });
});
