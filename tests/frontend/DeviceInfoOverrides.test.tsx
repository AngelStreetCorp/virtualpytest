import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

// DeviceInfoOverrides.tsx depends on `getAllDevices` itself in a callback/effect
// dependency array. A fresh arrow function per mock call makes that dependency
// look changed every render, causing an infinite re-render loop severe enough
// to crash the Vitest worker (hit this exact bug backfilling on 2026-09-06).
// Hoist to a stable reference instead — including the array it returns, which
// now feeds a useMemo and would re-run it on every render if freshly built.
let deviceList: any[] = [];
const getAllDevices = () => deviceList;
// DeviceMaintenanceBadge (rendered inside the Select's MenuItem) calls
// getAllHosts(). The host manager exposes both — stub the second one too so the
// page can render at all. It is unused on the Mock side; returning an empty list
// keeps the badge's device_id lookup as `undefined` (acceptable here, since the
// tests check dropdown labels, not badge text).
const getAllHosts = () => [];
const hostData = {
  getAllDevices,
  getAllHosts,
  selectedServer: 'https://server-a.example',
};
vi.mock('../../frontend/src/hooks/useHostManager', () => ({
  useHostData: () => hostData,
}));

// Workspace scope. `isDeviceAllowed` must be a stable reference for the same
// reason as `getAllDevices` above — it is a useMemo dependency, so a fresh
// function per render re-runs the device memo forever. The mutable
// `allowedTargets` (null = no active workspace) lets a test change the scope
// without changing the function identity.
let allowedTargets: string[] | null = null;
const isDeviceAllowed = (hostName: string, deviceId: string) =>
  allowedTargets === null || allowedTargets.includes(`${hostName}:${deviceId}`);
const workspaceContext = {
  userWorkspaces: [],
  activeWorkspace: null,
  setActiveWorkspace: () => {},
  isLoadingWorkspaces: false,
  isDeviceAllowed,
  isScriptAllowed: () => true,
  isPathHidden: () => false,
};
vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
  WorkspaceProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useWorkspaceContext: () => workspaceContext,
}));

// DeviceInfoOverrides.tsx has `useCallback(loadKeys, [showError, ...])`, and
// loadKeys itself feeds another effect's deps. A fresh showError per mock call
// makes that chain look changed every render, causing an infinite re-render
// loop severe enough to crash the Vitest worker (hit this exact bug backfilling
// on 2026-09-06). Hoist the toast functions to stable references instead.
const toastFns = {
  showSuccess: () => {},
  showError: () => {},
  showWarning: () => {},
  showInfo: () => {},
};
vi.mock('../../frontend/src/contexts/ToastContext', () => ({
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useToastContext: () => toastFns,
  __esModule: true,
}));

// The /keys enrich fetch is irrelevant to scoping — stub it so no test touches
// the network (and so the effect's failure path never fires a toast).
const apiGet = vi.fn(async () => [] as any[]);
vi.mock('../../frontend/src/utils/apiClient', () => ({
  api: {
    get: (...args: any[]) => apiGet(...(args as [])),
    put: async () => ({}),
    delete: async () => ({}),
  },
}));

import DeviceInfoOverrides from '../../frontend/src/pages/DeviceInfoOverrides';

const device = (device_id: string, device_name: string, hostName: string) => ({
  device_id,
  device_name,
  hostName,
  device_info: { model: 'X1' },
  gateway_info: {},
});

const renderAt = (path = '/device-info') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <DeviceInfoOverrides />
    </MemoryRouter>,
  );

const optionLabels = () =>
  Array.from(document.querySelectorAll('[role="option"]')).map((el) => el.textContent);

// MUI's Select opens on mousedown, not click. fireEvent wraps the dispatch in
// act(), which a bare dispatchEvent does not — without it every option render
// logs an "update not wrapped in act(...)" warning.
const openDropdown = () =>
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Device' }));

describe('DeviceInfoOverrides page', () => {
  beforeEach(() => {
    deviceList = [];
    allowedTargets = null;
    apiGet.mockClear();
  });

  it('renders device info heading', () => {
    renderAt();

    expect(screen.getByRole('heading', { name: 'Device Info' })).toBeInTheDocument();
  });

  it('lists every device of the selected server when no workspace is active', async () => {
    deviceList = [device('d1', 'living-room', 'host1'), device('d2', 'kitchen', 'host2')];

    renderAt();
    openDropdown();

    await waitFor(() => expect(optionLabels()).toHaveLength(2));
    expect(optionLabels()).toEqual(
      expect.arrayContaining(['kitchen — host2', 'living-room — host1']),
    );
  });

  it('hides devices the active workspace does not allow', async () => {
    deviceList = [device('d1', 'living-room', 'host1'), device('d2', 'kitchen', 'host2')];
    allowedTargets = ['host1:d1'];

    renderAt();
    openDropdown();

    await waitFor(() => expect(optionLabels()).toHaveLength(1));
    expect(optionLabels()).toEqual(['living-room — host1']);
  });

  it('keeps a deep-linked selection while the host list is still empty', async () => {
    // Cold load: hosts have not arrived yet. The preselect must survive, since
    // an empty list means "nothing to compare against", not "device is gone".
    renderAt('/device-info?device_name=living-room&host_name=host1');

    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(apiGet.mock.calls[0][0]).toContain('device_name=living-room');
    // The Device/Gateway tabs only render while a device is selected.
    expect(screen.getByRole('tab', { name: 'Device' })).toBeInTheDocument();
  });

  it('clears a selection the workspace scope no longer allows', async () => {
    deviceList = [device('d1', 'living-room', 'host1'), device('d2', 'kitchen', 'host2')];
    allowedTargets = ['host2:d2'];

    renderAt('/device-info?device_name=living-room&host_name=host1');

    // Out of scope with a populated host list → selection dropped, so the
    // tabs (rendered only when something is selected) disappear.
    await waitFor(() =>
      expect(screen.queryByRole('tab', { name: 'Device' })).not.toBeInTheDocument(),
    );
  });

  it('clears a selection whose device is absent from the selected server', async () => {
    // Server switch: the new server's hosts are loaded but do not include the
    // previously selected device.
    deviceList = [device('d2', 'kitchen', 'host2')];

    renderAt('/device-info?device_name=living-room&host_name=host1');

    await waitFor(() =>
      expect(screen.queryByRole('tab', { name: 'Device' })).not.toBeInTheDocument(),
    );
  });

  it('auto-selects the first device when the page is opened without a deep link', async () => {
    // Cold load without ?device_name=&host_name= — the user complaint was an
    // empty dropdown with no obvious next step. The page should land directly
    // on the first alphabetical device instead.
    deviceList = [device('d1', 'living-room', 'host1'), device('d2', 'kitchen', 'host2')];

    renderAt();

    // Tabs render only while a device is selected — proves the auto-select fired.
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Device' })).toBeInTheDocument());
    // The first alphabetical device is "kitchen — host2".
    expect(screen.getByRole('combobox', { name: 'Device' })).toHaveTextContent(/kitchen/);
  });

  it('shows the empty-state placeholder when no device carries any info keys', async () => {
    // Devices exist on the server but none have device_info or gateway_info —
    // there is nothing to override, so the dropdown stays empty by design.
    deviceList = [
      { device_id: 'd1', device_name: 'living-room', hostName: 'host1', device_info: {}, gateway_info: {} },
    ];

    renderAt();

    openDropdown();
    await waitFor(() => expect(optionLabels()).toEqual(['No devices with info']));
  });
});
