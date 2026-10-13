import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// BUG-0350: a server down at page load must not leave /ai-agent dead until refresh.
const sock = vi.hoisted(() => {
  const socket = { on: vi.fn(), off: vi.fn(), emit: vi.fn(), connected: false };
  const api: any = {
    socket, connect: vi.fn(), isConnected: false, initSession: vi.fn().mockResolvedValue('s0'), joinSession: vi.fn(),
    registerEventHandler: vi.fn(), unregisterEventHandler: vi.fn(), emitSendMessage: vi.fn(() => true), forceReconnect: vi.fn(),
  };
  return { socket, api };
});

vi.mock('../../frontend/src/contexts/SocketContext', () => ({ useSocket: () => sock.api }));
vi.mock('../../frontend/src/contexts/auth/AuthContext', () => ({ useAuthContext: () => ({ isLoading: false, isAuthenticated: true }) }));
vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({ useWorkspaceContext: () => ({ activeWorkspace: null }) }));
vi.mock('../../frontend/src/hooks/useServerManager', () => ({ useServerManager: () => ({ selectedServer: 'srv', serverHostsData: [] }) }));
vi.mock('../../frontend/src/utils/apiClient', () => ({
  api: { get: vi.fn().mockResolvedValue({}), post: vi.fn().mockResolvedValue({}), delete: vi.fn().mockResolvedValue({}) },
  apiClient: vi.fn(),
}));
vi.mock('../../frontend/src/lib/supabase', () => ({ isAuthEnabled: () => false }));

import { apiClient } from '../../frontend/src/utils/apiClient';
import { useAgentChat } from '../../frontend/src/hooks/aiagent/useAgentChat';

const healthOk = { status: 200, ok: true, json: async () => ({ api_key_configured: true, provider: 'p', model: 'm', endpoint: 'e' }) };

describe('Agent chat health check retry', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
    sock.api.isConnected = false;
    (apiClient as any).mockReset();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: async () => ({ success: true, session: { id: 's1' } }), status: 200 }));
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it('fails twice then succeeds: Reconnecting while down, ready without refresh', async () => {
    (apiClient as any)
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({ status: 502, ok: false, json: async () => ({}) })
      .mockResolvedValue(healthOk);
    const { result } = renderHook(() => useAgentChat());
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(result.current.status).toBe('checking');
    expect(result.current.error).toMatch(/Reconnecting to the server/);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); }); // 1st retry -> 502
    expect(result.current.status).toBe('checking');
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); }); // 2nd retry -> ok
    expect(result.current.status).toBe('ready');
    expect(result.current.error).toBeNull();
    expect((apiClient as any)).toHaveBeenCalledTimes(3);
  });

  it('socket reconnect triggers an immediate retry', async () => {
    (apiClient as any).mockRejectedValueOnce(new TypeError('x')).mockResolvedValue(healthOk);
    const { result, rerender } = renderHook(() => useAgentChat());
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(result.current.status).toBe('checking');
    sock.api.isConnected = true;
    rerender();
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(result.current.status).toBe('ready');
  });

  it('unmount clears the retry timer', async () => {
    (apiClient as any).mockRejectedValue(new TypeError('down'));
    const { unmount } = renderHook(() => useAgentChat());
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect((apiClient as any)).toHaveBeenCalledTimes(1);
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect((apiClient as any)).toHaveBeenCalledTimes(1);
  });

  it('401 is not retried', async () => {
    (apiClient as any).mockResolvedValue({ status: 401, ok: false, json: async () => ({}) });
    const { result } = renderHook(() => useAgentChat());
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(result.current.status).toBe('error');
    expect((apiClient as any)).toHaveBeenCalledTimes(1);
  });
});
