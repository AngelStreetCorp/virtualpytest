import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// A failed tool call emits an `error` event but the agent carries on. The banner (hook `error`)
// must go away once the turn recovers, yet stay when the turn fails with no later success.
const sock = vi.hoisted(() => {
  const state: { handler: ((event: any) => void) | null } = { handler: null };
  const socket = { on: vi.fn(), off: vi.fn(), emit: vi.fn(), connected: true };
  const api = {
    socket, connect: vi.fn(), isConnected: true, initSession: vi.fn(), joinSession: vi.fn(),
    registerEventHandler: (_name: string, handler: (event: any) => void) => { state.handler = handler; },
    unregisterEventHandler: vi.fn(), emitSendMessage: vi.fn(), forceReconnect: vi.fn(),
  };
  return { state, api };
});

vi.mock('../../frontend/src/contexts/SocketContext', () => ({ useSocket: () => sock.api }));
vi.mock('../../frontend/src/contexts/auth/AuthContext', () => ({ useAuthContext: () => ({ isLoading: false, isAuthenticated: true }) }));
vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({ useWorkspaceContext: () => ({ activeWorkspace: null }) }));
vi.mock('../../frontend/src/hooks/useServerManager', () => ({ useServerManager: () => ({ selectedServer: 'srv', serverHostsData: [] }) }));
vi.mock('../../frontend/src/utils/apiClient', () => ({
  api: { get: vi.fn().mockResolvedValue({}), post: vi.fn().mockResolvedValue({}), delete: vi.fn().mockResolvedValue({}) },
  apiClient: { get: vi.fn().mockResolvedValue({}), post: vi.fn().mockResolvedValue({}) },
}));
vi.mock('../../frontend/src/lib/supabase', () => ({ isAuthEnabled: () => false }));

import { useAgentChat } from '../../frontend/src/hooks/aiagent/useAgentChat';

const ev = (type: string, extra: Record<string, unknown> = {}) => ({ type, agent: 'Atlas', content: '', timestamp: new Date().toISOString(), ...extra });
const emit = (event: any) => act(() => { sock.state.handler?.(event); });

describe('Agent chat stale tool-error banner', () => {
  beforeEach(() => { sock.state.handler = null; vi.spyOn(console, 'log').mockImplementation(() => {}); vi.spyOn(console, 'error').mockImplementation(() => {}); });

  it('shows a tool error at once and clears it when a later tool call succeeds', () => {
    const { result } = renderHook(() => useAgentChat());
    expect(sock.state.handler).toBeTruthy();
    emit(ev('tool_result', { tool_name: 'query', success: false }));
    emit(ev('error', { content: 'Tool query failed' }));
    expect(result.current.error).toBe('Tool query failed');
    emit(ev('tool_result', { tool_name: 'query', success: true }));
    expect(result.current.error).toBeNull();
  });

  it('clears the banner when the agent answers after the failure', () => {
    const { result } = renderHook(() => useAgentChat());
    emit(ev('error', { content: 'Tool query failed' }));
    emit(ev('message', { content: 'Here is the answer' }));
    expect(result.current.error).toBeNull();
  });

  it('keeps the error when the turn fails with no later success', () => {
    const { result } = renderHook(() => useAgentChat());
    emit(ev('tool_result', { tool_name: 'query', success: true }));
    emit(ev('error', { content: 'Turn failed' }));
    emit(ev('session_ended'));
    expect(result.current.error).toBe('Turn failed');
  });

  it('does not clear an unrelated error (e.g. a socket or send error) on a later success', () => {
    const { result } = renderHook(() => useAgentChat());
    emit(ev('error', { content: 'Tool query failed' }));
    emit(ev('tool_result', { success: true }));
    act(() => { sock.api.socket.on.mock.calls.find((c) => c[0] === 'error')?.[1]({ error: 'boom' }); });
    expect(result.current.error).toBe('boom');
    emit(ev('tool_result', { success: true }));
    expect(result.current.error).toBe('boom');
  });
});
