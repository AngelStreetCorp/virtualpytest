import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// BUG-0340: a send during a server restart must never vanish silently.
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
  apiClient: vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => ({ api_key_configured: true, provider: 'p', model: 'm', endpoint: 'e' }) }),
}));
vi.mock('../../frontend/src/lib/supabase', () => ({ isAuthEnabled: () => false }));

import { apiClient } from '../../frontend/src/utils/apiClient';
import { useAgentChat } from '../../frontend/src/hooks/aiagent/useAgentChat';

const sessionOk = () => ({ json: async () => ({ success: true, session: { id: 's1' } }), status: 200 });

describe('Agent chat send during server restart', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
    (apiClient as any).mockResolvedValue({ status: 200, ok: true, json: async () => ({ api_key_configured: true, provider: 'p', model: 'm', endpoint: 'e' }) });
    sock.api.initSession.mockResolvedValue('s0');
    sock.api.emitSendMessage.mockReturnValue(true);
    sock.socket.connected = false; sock.api.isConnected = false;
    sock.api.emitSendMessage.mockClear(); sock.api.connect.mockClear();
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it('socket down at send: shows Reconnecting, keeps the text, delivers after reconnect', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sessionOk()));
    const { result, rerender } = renderHook(() => useAgentChat());
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    act(() => { result.current.setInput('show the failing test cases as a table'); });
    await act(async () => { await result.current.sendMessage(); });
    expect(result.current.error).toMatch(/Reconnecting/);
    expect(result.current.input).toBe('show the failing test cases as a table');
    expect(sock.api.emitSendMessage).not.toHaveBeenCalled();
    sock.socket.connected = true; sock.api.isConnected = true;
    rerender();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(sock.api.emitSendMessage).toHaveBeenCalledTimes(1);
    expect(sock.api.emitSendMessage.mock.calls[0][0]).toBe('show the failing test cases as a table');
    expect(result.current.input).toBe('');
  });

  it('never reconnects: ends in a visible error and the text is kept', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sessionOk()));
    const { result } = renderHook(() => useAgentChat());
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    act(() => { result.current.setInput('hello'); });
    await act(async () => { await result.current.sendMessage(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(65000); });
    expect(result.current.error).toMatch(/not sent/);
    expect(result.current.input).toBe('hello');
    expect(sock.api.emitSendMessage).not.toHaveBeenCalled();
  });

  it('session create failing during restart: visible error, text kept, no bubble', async () => {
    sock.socket.connected = true; sock.api.isConnected = true;
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const { result } = renderHook(() => useAgentChat());
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    act(() => { result.current.setInput('hello'); });
    const p = act(async () => { const q = result.current.sendMessage(); await vi.advanceTimersByTimeAsync(65000); await q; });
    await p;
    expect(result.current.error).toMatch(/Unable to reach the server.*not sent/);
    expect(result.current.input).toBe('hello');
    expect(sock.api.emitSendMessage).not.toHaveBeenCalled();
    expect(result.current.conversations.flatMap((c: any) => c.messages)).toHaveLength(0);
  });

  // BUG-0401: the server accepts the connection but never answers.
  it('session create hangs: Reconnecting within 3s, error after the budget, text kept, no bubble', async () => {
    sock.socket.connected = true; sock.api.isConnected = true;
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    const { result } = renderHook(() => useAgentChat());
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    act(() => { result.current.setInput('build a canvas'); });
    let q: Promise<void>;
    await act(async () => { q = result.current.sendMessage(); await vi.advanceTimersByTimeAsync(3500); });
    expect(result.current.error).toMatch(/Reconnecting/);
    expect(result.current.input).toBe('build a canvas');
    await act(async () => { await vi.advanceTimersByTimeAsync(70000); await q; });
    expect(result.current.error).toMatch(/Unable to reach the server.*not sent/);
    expect(result.current.input).toBe('build a canvas');
    expect(sock.api.emitSendMessage).not.toHaveBeenCalled();
    expect(result.current.conversations.flatMap((c: any) => c.messages)).toHaveLength(0);
  });

  it('session create hangs then recovers: delivered exactly once, a second Enter during the hang is ignored', async () => {
    sock.socket.connected = true; sock.api.isConnected = true;
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(() => { calls++; return calls <= 2 ? new Promise(() => {}) : Promise.resolve(sessionOk()); }));
    const { result } = renderHook(() => useAgentChat());
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    act(() => { result.current.setInput('build a canvas'); });
    await act(async () => { void result.current.sendMessage(); await vi.advanceTimersByTimeAsync(5000); });
    await act(async () => { void result.current.sendMessage(); await vi.advanceTimersByTimeAsync(100); });
    expect(calls).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(40000); });
    // one user send; any ack-watchdog resend (no ack in this mock) carries the same client_msg_id
    const ids = new Set(sock.api.emitSendMessage.mock.calls.map((c: any) => c[2].client_msg_id));
    expect(ids.size).toBe(1);
    expect(sock.api.emitSendMessage.mock.calls[0][0]).toBe('build a canvas');
    expect(calls).toBe(3);
    expect(result.current.input).toBe('');
  });

  it('socket connected but silent: watchdog shows Waiting, resends with the SAME client_msg_id', async () => {
    sock.socket.connected = true; sock.api.isConnected = true;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sessionOk()));
    const { result } = renderHook(() => useAgentChat());
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    act(() => { result.current.setInput('hello'); });
    await act(async () => { await result.current.sendMessage(); });
    expect(sock.api.emitSendMessage).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(4500); });
    expect(result.current.error).toMatch(/Waiting for the server/);
    expect(sock.api.forceReconnect).toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(sock.api.emitSendMessage).toHaveBeenCalledTimes(2);
    const id1 = sock.api.emitSendMessage.mock.calls[0][2].client_msg_id;
    expect(id1).toBeTruthy();
    expect(sock.api.emitSendMessage.mock.calls[1][2].client_msg_id).toBe(id1);
  });
});
