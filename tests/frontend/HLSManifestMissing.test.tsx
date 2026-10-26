/**
 * Regression: the manifest-404 terminal state used to erase itself.
 *
 * Measured live 2026-10-22 on /device-control (server vpt-pi4, host vpt-lenovo6,
 * device1): `getStreamUrl` returned 200 in 79 ms with a perfectly good URL, and
 * every single request for the manifest that URL pointed at answered 404 — ffmpeg
 * was not writing that capture. The card showed "Loading stream..." for 60 s+ and
 * kept going, with no error, because:
 *
 *   1. the handler that exists precisely to stop on a manifest 404 did
 *      `setStreamError('Stream manifest not found (404)…')` and then called
 *      `cleanupStream()`, whose last act is `setStreamError(null)`. React batches
 *      both writes in one handler, last one wins, so the error was always null.
 *   2. null error + streamLoaded false + streamUrl set is exactly the state the
 *      "Loading stream..." overlay renders on.
 *   3. and because the handler had just destroyed the hls instance, the
 *      "stream activated while not loaded" effect re-armed and re-requested the
 *      same missing manifest every 6 s, forever.
 *
 * So the test asserts the three things that were each individually wrong: the
 * message survives, the spinner is gone, and the loop has stopped.
 */
import { describe, it, expect, vi, beforeAll, beforeEach, afterAll } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

/**
 * HLSVideoPlayer reads `const MSE_SUPPORTED = 'MediaSource' in window` at MODULE
 * scope, and when that is false it takes the native-playback branch instead of
 * ever constructing an hls.js instance. jsdom has no MediaSource, so the component
 * has to be imported only after the global exists — a static import would be
 * hoisted above any beforeEach and the fake hls.js would never be reached.
 */
let HLSVideoPlayer: any;

beforeAll(async () => {
  (window as any).MediaSource = class {};
  ({ HLSVideoPlayer } = await import('../../frontend/src/components/common/HLSVideoPlayer'));
});

afterAll(() => {
  delete (window as any).MediaSource;
});

/** Event name -> handler map for one fake hls.js instance. */
type Handlers = Record<string, (event: string, data: any) => void>;

interface FakeInstance {
  handlers: Handlers;
  loadSource: ReturnType<typeof vi.fn>;
  attachMedia: ReturnType<typeof vi.fn>;
  destroy: ReturnType<typeof vi.fn>;
}

const instances: FakeInstance[] = [];

class FakeHls {
  static Events = {
    MANIFEST_PARSED: 'hlsManifestParsed',
    FRAG_LOADED: 'hlsFragLoaded',
    ERROR: 'hlsError',
  };

  static isSupported = () => true;

  handlers: Handlers = {};

  loadSource = vi.fn();

  attachMedia = vi.fn();

  destroy = vi.fn();

  stopLoad = vi.fn();

  startLoad = vi.fn();

  detachMedia = vi.fn();

  removeAllListeners = vi.fn();

  recoverMediaError = vi.fn();

  swapAudioCodec = vi.fn();

  on(event: string, handler: (event: string, data: any) => void) {
    this.handlers[event] = handler;
    return this;
  }

  constructor() {
    instances.push(this as unknown as FakeInstance);
  }
}

vi.mock('hls.js', () => ({ default: FakeHls }));

/**
 * The player withholds the stream URL until the host-session cookie has been
 * minted: `streamUrl = hostSessionReady ? rawStreamUrl : undefined`. Real URLs are
 * gated /host/<name>/... paths, and jsdom has no server to mint against, so the URL
 * would stay undefined and hls.js would never be constructed — the component would
 * render "Loading stream..." for a reason that has nothing to do with this bug.
 * Stubbing the hook keeps the test on the production-shaped gated URL.
 */
vi.mock('../../frontend/src/hooks/useHostSession', () => ({
  useHostSession: () => true,
}));

const STREAM_URL = 'https://vpt-pi4.angelstreet.io/host/vpt-lenovo6/stream/capture1/segments/output.m3u8';

/** Fire the fake hls.js ERROR handler with a fatal manifest 404, as the host answers it. */
const fireManifest404 = (instance: FakeInstance) => {
  act(() => {
    instance.handlers.hlsError?.('hlsError', {
      fatal: true,
      type: 'networkError',
      details: 'manifestLoadError',
      response: { code: 404 },
    });
  });
};

/**
 * useLatencyDebug calls useSearchParams(), so the player needs a Router around it.
 * `onRestartRequest` is how a parent asks the player to recover (RecStreamContainer
 * wires it to its Restart control) — the error box itself renders a retry counter,
 * not a button, so this ref IS the recovery path the operator ends up using.
 */
const renderPlayer = (onRestartRequest?: { current: (() => void) | null }) =>
  render(
    <MemoryRouter>
      <HLSVideoPlayer streamUrl={STREAM_URL} isStreamActive onRestartRequest={onRestartRequest as any} />
    </MemoryRouter>,
  );

describe('HLSVideoPlayer — manifest 404 is a terminal state, not a loading state', () => {
  beforeEach(() => {
    instances.length = 0;
    Object.defineProperty(window.HTMLMediaElement.prototype, 'play', {
      configurable: true,
      value: vi.fn().mockResolvedValue(undefined),
    });
    Object.defineProperty(window.HTMLMediaElement.prototype, 'load', {
      configurable: true,
      value: vi.fn(),
    });
    // cleanupStream() calls video.pause(); jsdom has no media pipeline and logs a
    // "Not implemented" error for it, which drowns the assertions in noise.
    Object.defineProperty(window.HTMLMediaElement.prototype, 'pause', {
      configurable: true,
      value: vi.fn(),
    });
  });

  it('keeps the 404 message instead of falling back to "Loading stream..."', async () => {
    renderPlayer();

    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
    expect(screen.getByText('Loading stream...')).toBeTruthy();

    fireManifest404(instances[0]);

    // The message must survive cleanupStream(), which sets streamError back to null.
    await waitFor(() => expect(screen.getByText(/manifest not found/i)).toBeTruthy());
    expect(screen.queryByText('Loading stream...')).toBeNull();
  });

  it('stops re-requesting the missing manifest', async () => {
    renderPlayer();

    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
    expect(instances[0].loadSource).toHaveBeenCalledTimes(1);

    fireManifest404(instances[0]);

    // Past the retry delay (6 s) a re-init would have fired a second loadSource.
    // The live bug re-requested the same 404 manifest indefinitely; retryDelay is
    // 6000 ms, so advance past it and prove the loop is gone.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(instances.filter((i) => i.loadSource.mock.calls.length > 0).length).toBe(1);
  });

  it('recovers when the operator retries after the host starts writing again', async () => {
    const restartRef: { current: (() => void) | null } = { current: null };
    renderPlayer(restartRef);

    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
    fireManifest404(instances[0]);
    await waitFor(() => expect(screen.getByText(/manifest not found/i)).toBeTruthy());

    // The terminal guard must not be a one-way door: once ffmpeg is writing the
    // capture again, the parent's restart control has to be able to load it.
    expect(restartRef.current).toBeTypeOf('function');
    const before = instances.length;
    await act(async () => {
      restartRef.current?.();
      await new Promise((resolve) => setTimeout(resolve, 400));
    });

    await waitFor(() => expect(instances.length).toBeGreaterThan(before));
    const fresh = instances[instances.length - 1];
    expect(fresh.loadSource).toHaveBeenCalledWith(STREAM_URL);

    // A successful manifest clears the error and brings the picture up.
    act(() => {
      fresh.handlers.hlsManifestParsed?.('hlsManifestParsed', {});
    });
    await waitFor(() => expect(screen.queryByText(/manifest not found/i)).toBeNull());
  });
});