/**
 * TASK-113 — PR-C extension: the desktop scope picker (ScopePicker)
 * now also surfaces the "All servers" row at the top of the Server
 * column, mirroring the mobile ServerSelector behaviour. These tests
 * pin the wiring: the row is present, picks it, the label chip
 * reflects the sentinel, and disabled state matches the no-eligible-peer
 * gate.
 */
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { ThemeProvider, createTheme } from '@mui/material/styles';

import ScopePickerCmp from '../../../frontend/src/components/common/ScopePicker';
import { ALL_SERVERS_SENTINEL } from '../../../frontend/src/lib/allServer/scope';

// Mock useServerPicker — ScopePicker consumes its return value, we
// drive the sentinel through it. The labelFor mimics buildServerPickerLabels:
// when a name is unique among availableServers, only the host part is rendered.
const labelFor = (url: string): string => {
  if (url === ALL_SERVERS_SENTINEL) return 'All servers';
  return url.replace(/^https?:\/\//, '').replace(/\/+$/, '');
};

const handleChange = vi.fn();
let selectedServer: string = 'https://a.example.test';
let availableServers: string[] = ['https://a.example.test', 'https://b.example.test'];

vi.mock('../../../frontend/src/hooks/useServerPicker', () => ({
  useServerPicker: () => ({
    selectedServer,
    availableServers,
    failedServers: new Set<string>(),
    isServerChanging: false,
    serverAuthStates: {} as Record<string, string>,
    labelFor,
    handleChange: (url: string) => handleChange(url),
    authDialog: null,
  }),
}));

// Mock workspace/project contexts — keep ScopePicker focused on the Server column.
vi.mock('../../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
  useWorkspaceContext: () => ({
    userWorkspaces: [],
    activeWorkspace: null,
    setActiveWorkspace: () => undefined,
  }),
}));

vi.mock('../../../frontend/src/hooks/common/useCurrentProject', () => ({
  useCurrentProject: () => ({
    projects: [],
    currentProject: null,
    setCurrentProject: () => undefined,
    isLoading: false,
    isOnScopeAwarePage: false,
  }),
}));

vi.mock('../../../frontend/src/i18n/useI18n', () => ({
  useI18n: () => ({ t: (s: string) => s }),
}));

const renderPicker = () =>
  render(
    <ThemeProvider theme={createTheme()}>
      <ScopePickerCmp />
    </ThemeProvider>
  );

// Open the picker popover by clicking the chip (the first ButtonBase in the tree).
const openPicker = () => {
  // The chip is the very first button rendered; the next buttons belong to the popover
  // content which is only rendered when the anchor is set.
  const chip = screen.getAllByRole('button')[0];
  fireEvent.click(chip);
};

describe('ScopePicker — All servers row (TASK-113 PR-C extension)', () => {
  beforeEach(() => {
    selectedServer = 'https://a.example.test';
    availableServers = ['https://a.example.test', 'https://b.example.test'];
    handleChange.mockReset();
  });

  it('renders the All servers row at the top of the Server column', () => {
    renderPicker();
    openPicker();
    // After opening the popover, multiple Server column rows are visible.
    const serverColumn = screen.getByText('Server').parentElement as HTMLElement;
    const allServersRow = within(serverColumn).getByText('All servers');
    expect(allServersRow).toBeTruthy();
  });

  it('calls handleChange with the sentinel when the All servers row is clicked', () => {
    renderPicker();
    openPicker();
    const serverColumn = screen.getByText('Server').parentElement as HTMLElement;
    const allServersButton = within(serverColumn)
      .getByText('All servers')
      .closest('button') as HTMLButtonElement;
    expect(allServersButton).toBeTruthy();
    fireEvent.click(allServersButton);
    expect(handleChange).toHaveBeenCalledWith(ALL_SERVERS_SENTINEL);
  });

  it('shows "All servers" as the chip label when the sentinel is selected', () => {
    selectedServer = ALL_SERVERS_SENTINEL;
    renderPicker();
    const chip = screen.getAllByRole('button')[0];
    expect((chip.textContent ?? '').toLowerCase()).toContain('all servers');
  });

  // BUG-0577: any fleet with 0 or 1 configured servers has nothing to
  // federate, so the "All servers" row is hidden. The previous behaviour
  // rendered the row disabled at 0 and at 1; both carried the same
  // user-visible failure (the sentinel would route the system socket to
  // `wss://__all__/...` on every reconnect cycle and Devices rendered
  // "No AV devices found"). The full coverage spans 0 servers
  // (this case) and 1 server (the test below).
  it('hides the All servers row when no eligible peer is available', () => {
    availableServers = [];
    renderPicker();
    openPicker();
    const serverColumn = screen.getByText('Server').parentElement as HTMLElement;
    expect(within(serverColumn).queryByText('All servers')).toBeNull();
  });

  it('hides the All servers row when only one server is configured', () => {
    availableServers = ['https://only.example.test'];
    selectedServer = 'https://only.example.test';
    renderPicker();
    openPicker();
    const serverColumn = screen.getByText('Server').parentElement as HTMLElement;
    expect(within(serverColumn).queryByText('All servers')).toBeNull();
  });
});

// BUG-0799: the scope picker is the first tab stop of the app, and the focus
// was invisible — the button base resets the outline and nothing put one back.
describe('ScopePicker — keyboard focus', () => {
  beforeEach(() => {
    selectedServer = 'https://a.example.test';
    availableServers = ['https://a.example.test', 'https://b.example.test'];
    handleChange.mockReset();
  });

  /** The CSS emotion wrote for the element's classes. */
  const styleSheet = () =>
    Array.from(document.querySelectorAll('style'))
      .map((style) => style.textContent ?? '')
      .join('\n');

  it('draws a focus indicator when the keyboard reaches the chip', () => {
    renderPicker();
    const chip = screen.getAllByRole('button')[0];
    const classes = chip.className.split(' ').filter(Boolean);
    const css = styleSheet();

    const focusRule = classes.some((cls) => css.includes(`.${cls}:focus-visible`));
    expect(focusRule).toBe(true);
  });

  it('draws a focus indicator on the rows of the open picker', () => {
    renderPicker();
    openPicker();
    const row = screen.getByText('All servers').closest('button') as HTMLButtonElement;
    const classes = row.className.split(' ').filter(Boolean);
    const css = styleSheet();

    const focusRule = classes.some((cls) => css.includes(`.${cls}:focus-visible`));
    expect(focusRule).toBe(true);
  });
});
