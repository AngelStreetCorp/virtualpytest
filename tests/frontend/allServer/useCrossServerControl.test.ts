/**
 * TASK-113 — PR-E tests: useCrossServerControl + useCrossServerStream.
 *
 * socket.io-client is mocked at the module level to avoid opening
 * real WebSockets from the test env. The mocks assert the URL
 * passed to `io()` and that the auth payload is built from the
 * home server (not the currently selected one).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

const ioMock = vi.fn(() => ({
  on: vi.fn(),
  disconnect: vi.fn(),
  emit: vi.fn(),
}));
vi.mock('socket.io-client', () => ({ io: ioMock }));

const buildSocketAuthMock = vi.fn(() => () => ({ token: 'mock-jwt' }));
vi.mock('../../../frontend/src/utils/serverSocket', () => ({
  buildSocketAuth: buildSocketAuthMock,
}));

const ensureHostSessionMock = vi.fn(async () => true);
vi.mock('../../../frontend/src/utils/buildUrlUtils', () => ({
  ensureHostSession: ensureHostSessionMock,
}));

describe('useCrossServerControl', () => {
  beforeEach(() => {
    ioMock.mockClear();
    buildSocketAuthMock.mockClear();
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('opens a socket to the device HOME server, not the currently selected one', async () => {
    const { useCrossServerControl } = await import(
      '../../../frontend/src/hooks/allServer/useCrossServerControl'
    );
    renderHook(() =>
      useCrossServerControl({
        homeServerUrl: 'https://b.example.test',
        namespace: '/agent',
        enabled: true,
      }),
    );
    expect(ioMock).toHaveBeenCalledTimes(1);
    const [url, opts] = ioMock.mock.calls[0];
    expect(url).toBe('https://b.example.test/agent');
    expect(opts.auth).toBeTypeOf('function');
  });

  it('passes the home server URL to buildSocketAuth', async () => {
    const { useCrossServerControl } = await import(
      '../../../frontend/src/hooks/allServer/useCrossServerControl'
    );
    renderHook(() =>
      useCrossServerControl({
        homeServerUrl: 'https://b.example.test',
        enabled: true,
      }),
    );
    expect(buildSocketAuthMock).toHaveBeenCalledWith('https://b.example.test');
  });

  it('does not open a socket when enabled=false', async () => {
    const { useCrossServerControl } = await import(
      '../../../frontend/src/hooks/allServer/useCrossServerControl'
    );
    renderHook(() =>
      useCrossServerControl({
        homeServerUrl: 'https://b.example.test',
        enabled: false,
      }),
    );
    expect(ioMock).not.toHaveBeenCalled();
  });

  it('disconnects on unmount', async () => {
    const { useCrossServerControl } = await import(
      '../../../frontend/src/hooks/allServer/useCrossServerControl'
    );
    const { unmount } = renderHook(() =>
      useCrossServerControl({
        homeServerUrl: 'https://b.example.test',
        enabled: true,
      }),
    );
    unmount();
    const socket = ioMock.mock.results[0]?.value;
    expect(socket?.disconnect).toHaveBeenCalled();
  });
});

describe('useCrossServerStream', () => {
  beforeEach(() => {
    ensureHostSessionMock.mockClear();
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('builds the HLS URL on the device home server', async () => {
    const { useCrossServerStream } = await import(
      '../../../frontend/src/hooks/allServer/useCrossServerStream'
    );
    const { result } = renderHook(() =>
      useCrossServerStream({
        homeServerUrl: 'https://b.example.test',
        hostName: 'host-foo',
      }),
    );
    expect(result.current.url).toBe('https://b.example.test/host/host-foo/stream/stream.m3u8');
  });

  it('prime() calls ensureHostSession on the resolved URL', async () => {
    const { useCrossServerStream } = await import(
      '../../../frontend/src/hooks/allServer/useCrossServerStream'
    );
    const { result } = renderHook(() =>
      useCrossServerStream({
        homeServerUrl: 'https://b.example.test',
        hostName: 'host-foo',
      }),
    );
    await act(async () => {
      const ok = await result.current.prime();
      expect(ok).toBe(true);
    });
    expect(ensureHostSessionMock).toHaveBeenCalledWith(
      'https://b.example.test/host/host-foo/stream/stream.m3u8',
    );
  });

  it('returns null URL when hostName is missing', async () => {
    const { useCrossServerStream } = await import(
      '../../../frontend/src/hooks/allServer/useCrossServerStream'
    );
    const { result } = renderHook(() =>
      useCrossServerStream({
        homeServerUrl: 'https://b.example.test',
        hostName: '',
      }),
    );
    expect(result.current.url).toBeNull();
  });
});
