/**
 * BUG-0774 — the navigation editor opened a blank but fully enabled editor
 * for a tree name that does not exist: "0/0 nodes", a live "Add Node" and
 * "Publish", and no message anywhere. A stale bookmark or a typo landed on a
 * working-looking editor, so a developer could add nodes to the wrong place.
 *
 * Two parts are covered here:
 *   - the resolution hook, which reports why the interface could not be opened;
 *   - the screen the page shows instead of the editor.
 */
import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const ui = vi.hoisted(() => ({ getUserInterfaceByName: vi.fn() }));

vi.mock('../../frontend/src/hooks/pages/useUserInterface', async (importActual) => {
  const actual = await importActual<Record<string, unknown>>();
  return {
    ...actual,
    useUserInterface: () => ({ getUserInterfaceByName: ui.getUserInterfaceByName }),
  };
});

import { useUserInterfaceResolution } from '../../frontend/src/hooks/navigation/useUserInterfaceResolution';
import { UserInterfaceNotFoundError } from '../../frontend/src/hooks/pages/useUserInterface';
import { NavigationInterfaceNotFound } from '../../frontend/src/components/navigation/Navigation_InterfaceNotFound';

const resolveWith = (over: Partial<Parameters<typeof useUserInterfaceResolution>[0]> = {}) => {
  const onResolved = vi.fn();
  const view = renderHook(() =>
    useUserInterfaceResolution({
      treeName: 'does-not-exist-xyz',
      mode: 'dev',
      onResolved,
      ...over,
    }),
  );
  return { ...view, onResolved };
};

describe('useUserInterfaceResolution', () => {
  it('says the interface does not exist instead of leaving an empty tree', async () => {
    ui.getUserInterfaceByName.mockRejectedValueOnce(new UserInterfaceNotFoundError('does-not-exist-xyz', 'dev'));

    const { result } = resolveWith();

    await waitFor(() =>
      expect(result.current.error).toBe('User interface "does-not-exist-xyz" not found'),
    );
  });

  it('says when the interface exists in dev only and the prod snapshot is asked for', async () => {
    ui.getUserInterfaceByName.mockRejectedValueOnce(new UserInterfaceNotFoundError('web_tv', 'prod'));

    const { result } = resolveWith({ treeName: 'web_tv', mode: 'prod' });

    await waitFor(() =>
      expect(result.current.error).toBe('No prod snapshot published for "web_tv" — it exists in dev only'),
    );
  });

  it('reports a failed load that is not a missing interface', async () => {
    ui.getUserInterfaceByName.mockRejectedValueOnce(new Error('HTTP 500'));

    const { result } = resolveWith({ treeName: 'stb_tv' });

    await waitFor(() =>
      expect(result.current.error).toBe('Could not load the user interface "stb_tv": HTTP 500'),
    );
  });

  it('hands the interface over when it is found', async () => {
    const found = { id: 'ui-1', name: 'web_tv', models: [], mode: 'dev' };
    ui.getUserInterfaceByName.mockResolvedValueOnce(found);

    const { result, onResolved } = resolveWith({ treeName: 'web_tv' });

    await waitFor(() => expect(onResolved).toHaveBeenCalledWith(found));
    expect(result.current.error).toBeNull();
  });

  it('asks once — a failing lookup is not retried on every render', async () => {
    ui.getUserInterfaceByName.mockRejectedValue(new UserInterfaceNotFoundError('does-not-exist-xyz', 'dev'));

    const { result, rerender } = resolveWith();
    await waitFor(() => expect(result.current.error).toBeTruthy());

    rerender();
    rerender();
    await new Promise((r) => setTimeout(r, 20));

    expect(ui.getUserInterfaceByName).toHaveBeenCalledTimes(1);
  });

  it('keeps the failure when the page re-renders while the lookup is running', async () => {
    // The navigation context is rebuilt on every render, so the callback the
    // page hands over changes identity while the lookup is still running.
    // Dropping the answer of a running lookup left the editor blank and
    // enabled — the BUG-0774 symptom.
    let reject: (reason: unknown) => void = () => {};
    ui.getUserInterfaceByName.mockReturnValueOnce(
      new Promise((_resolve, r) => {
        reject = r;
      }),
    );

    const { result, rerender } = renderHook(
      ({ cb }) =>
        useUserInterfaceResolution({
          treeName: 'does-not-exist-xyz',
          mode: 'dev',
          onResolved: cb,
        }),
      { initialProps: { cb: vi.fn() } },
    );

    rerender({ cb: vi.fn() });

    await act(async () => {
      reject(new UserInterfaceNotFoundError('does-not-exist-xyz', 'dev'));
    });

    await waitFor(() =>
      expect(result.current.error).toBe('User interface "does-not-exist-xyz" not found'),
    );
  });

  it('hands the interface to the latest callback when the page re-rendered', async () => {
    const found = { id: 'ui-1', name: 'web_tv', models: [], mode: 'dev' };
    let resolve: (value: unknown) => void = () => {};
    ui.getUserInterfaceByName.mockReturnValueOnce(
      new Promise((r) => {
        resolve = r;
      }),
    );

    const { rerender } = renderHook(
      ({ cb }) =>
        useUserInterfaceResolution({ treeName: 'web_tv', mode: 'dev', onResolved: cb }),
      { initialProps: { cb: vi.fn() } },
    );

    const latest = vi.fn();
    rerender({ cb: latest });

    await act(async () => {
      resolve(found);
    });

    await waitFor(() => expect(latest).toHaveBeenCalledWith(found));
  });

  it('retry looks the same interface up again', async () => {
    ui.getUserInterfaceByName.mockRejectedValueOnce(new UserInterfaceNotFoundError('does-not-exist-xyz', 'dev'));

    const { result } = resolveWith();
    await waitFor(() => expect(result.current.error).toBeTruthy());

    ui.getUserInterfaceByName.mockResolvedValueOnce({ id: 'ui-1', name: 'does-not-exist-xyz', models: [] });
    act(() => result.current.retry());

    await waitFor(() => expect(result.current.error).toBeNull());
    expect(ui.getUserInterfaceByName).toHaveBeenCalledTimes(2);
  });
});

describe('NavigationInterfaceNotFound', () => {
  it('shows the reason and a way back to the interface list', async () => {
    render(
      <MemoryRouter initialEntries={['/navigation-editor/does-not-exist-xyz']}>
        <Routes>
          <Route
            path="/configuration/interface"
            element={<div>Interface list</div>}
          />
          <Route path="*" element={<NavigationInterfaceNotFound message="User interface &quot;nope&quot; not found" />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('This tree cannot be opened')).toBeInTheDocument();
    expect(screen.getByText('User interface "nope" not found')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Back to Interfaces/i }));

    expect(await screen.findByText('Interface list')).toBeInTheDocument();
  });
});
