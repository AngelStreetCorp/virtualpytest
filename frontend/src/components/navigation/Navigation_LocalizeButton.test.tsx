// @vitest-environment jsdom
/** Localize: the host's verdict.kind 'live' reads "Live video" (TASK-104); motion diagnostics alone never do.
 *  A device whose profile runs no image monitor gets no Localize. */
import { createTheme, ThemeProvider } from '@mui/material/styles';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { LocalizeButton, localizeOff } from './Navigation_LocalizeButton';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const abstain = (motion: Record<string, unknown> | null, kind = 'unknown') => ({
  success: true, candidates: [], ranked: [], total: 12, excluded_count: 0, reason: 'no region matched',
  classifier_diagnostics: motion ? { motion } : null,
  verdict: { kind, node_id: null, label: kind === 'live' ? 'Live video' : 'Unknown', confidence: 0, evidence: {} },
});

const run = async (payload: unknown, mode: 'dark' | 'light') => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: async () => payload }));
  render(
    <ThemeProvider theme={createTheme({ palette: { mode } })}>
      <LocalizeButton hostName="h" deviceId="device1" userinterfaceName="ui" />
    </ThemeProvider>,
  );
  fireEvent.click(screen.getByLabelText('Localize current screen'));
  await waitFor(() => expect(screen.queryByText('Localizing…')).toBeNull());
};

describe.each(['dark', 'light'] as const)('LocalizeButton abstain (%s)', (mode) => {
  it('verdict live → Live video', async () => {
    await run(abstain({ kind: 'full', pct: 62 }, 'live'), mode);
    expect((await screen.findAllByText('Live video')).length).toBeGreaterThan(0);
    expect(screen.queryByText('No match')).toBeNull();
    expect(screen.getByText('The screen is playing video, which is not a saved screen.')).toBeTruthy();
  });
  it('full motion without a live verdict → No match', async () => {
    await run(abstain({ kind: 'full', pct: 62 }), mode);
    expect(await screen.findByText('No match')).toBeTruthy();
  });
  it('static motion → No match', async () => {
    await run(abstain({ kind: 'static', pct: 0 }), mode);
    expect(await screen.findByText('No match')).toBeTruthy();
    expect(screen.queryByText('Live video')).toBeNull();
  });
  it('null diagnostics → No match', async () => {
    await run(abstain(null), mode);
    expect(await screen.findByText('No match')).toBeTruthy();
  });
});

describe('localizeOff (no image monitor, no Localize)', () => {
  const host = { system_stats: { monitoring_off: ['device3'] } };
  it('is off for a device the host lists as monitoring off', () => {
    expect(localizeOff(host, 'device3')).toBe(true);
  });
  it('is on for any other device, or when the host reports nothing', () => {
    expect(localizeOff(host, 'device4')).toBe(false);
    expect(localizeOff({}, 'device3')).toBe(false);
    expect(localizeOff(host, null)).toBe(false);
  });
  it('disables the button with the reason', () => {
    render(<LocalizeButton hostName="h" deviceId="device3" userinterfaceName="ui" disabled disabledTitle="off" />);
    expect((screen.getByLabelText('Localize current screen') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('Wrong screen? corrects the matcher (TASK-104 goal 11)', () => {
  const matched = {
    success: true, total: 3, excluded_count: 2,
    candidates: [{ node_id: 'n-home', label: 'home', confidence: 0.9 }],
    ranked: [{ node_id: 'n-home', label: 'home', confidence: 0.9 }, { node_id: 'n-replay', label: 'replay', confidence: 0.5 }],
    nodes: [{ node_id: 'n-home', label: 'home' }, { node_id: 'n-replay', label: 'replay' }],
    live_fingerprint: { dhash: 'ab', regions: { top: 'cd' } },
    verdict: { kind: 'node', node_id: 'n-home', label: 'home', confidence: 0.9 },
  };

  const openQuestion = async (fetchMock: ReturnType<typeof vi.fn>) => {
    vi.stubGlobal('fetch', fetchMock);
    render(<LocalizeButton hostName="h" deviceId="device1" userinterfaceName="ui" />);
    fireEvent.click(screen.getByLabelText('Localize current screen'));
    await screen.findByText('More');
    fireEvent.click(screen.getByText('More'));
    fireEvent.click(await screen.findByText('Wrong screen?'));
  };

  it('Unknown screen marks a negative on the claimed node, and Undo reverts it', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ json: async () => matched })
      .mockResolvedValueOnce({ json: async () => ({ success: true, id: 'v1', action: 'negative', label: 'home' }) })
      .mockResolvedValueOnce({ json: async () => ({ success: true, id: 'v1' }) });
    await openQuestion(fetchMock);
    fireEvent.click(screen.getByText('Save'));
    expect(await screen.findByText('Marked as an unknown screen')).toBeTruthy();
    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(fetchMock.mock.calls[1][0]).toContain('/server/navigation/localize/verdict');
    expect(body).toMatchObject({ wrong_node_id: 'n-home', true_node_id: null, userinterface_name: 'ui' });
    fireEvent.click(screen.getByText('Undo'));
    expect(await screen.findByText('Undone: the matcher is back as it was')).toBeTruthy();
    expect(fetchMock.mock.calls[2][0]).toContain('/localize/verdict/v1/undo');
  });

  it('an overlay verdict is the headline instead of No match', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({ success: true, candidates: [], ranked: [], total: 2, excluded_count: 2,
        verdict: { kind: 'overlay', node_id: 'n-home', label: 'Popup over home', confidence: 0.8 } }),
    }));
    render(<LocalizeButton hostName="h" deviceId="device1" userinterfaceName="ui" />);
    fireEvent.click(screen.getByLabelText('Localize current screen'));
    expect((await screen.findAllByText('Popup over home')).length).toBeGreaterThan(0);
    expect(screen.queryByText('No match')).toBeNull();
  });
});
