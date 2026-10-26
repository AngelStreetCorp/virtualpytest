/**
 * BUG-0950: a live player that falls behind asks for segments the host has already archived away (the playlist lists
 * ~2 min, the hot folder keeps 20-80 s). It used to count those 404s as "FFmpeg appears stuck", and after 10 it destroyed
 * itself and asked for a restart while ffmpeg was writing perfectly well. Now a 404 sends the player to the live edge.
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

  liveSyncPosition: number | null = 120;

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

const frag404 = (instance: any, n = 1) => {
  for (let i = 0; i < n; i++) {
    act(() => {
      instance.handlers.hlsError?.('hlsError', { fatal: false, type: 'networkError', details: 'fragLoadError', response: { code: 404 }, frag: { url: `segment_${i}.ts` } });
    });
  }
};

const renderPlayer = () =>
  render(
    <MemoryRouter>
      <HLSVideoPlayer streamUrl={STREAM_URL} isStreamActive />
    </MemoryRouter>,
  );

describe('HLSVideoPlayer — a segment the host archived away is not a stuck ffmpeg (BUG-0950)', () => {
  let currentTime = 0;
  beforeEach(() => {
    instances.length = 0;
    currentTime = 10;                                     // 110 s behind the live edge
    for (const m of ['play', 'load', 'pause']) {
      Object.defineProperty(window.HTMLMediaElement.prototype, m, {
        configurable: true,
        value: m === 'play' ? vi.fn().mockResolvedValue(undefined) : vi.fn(),
      });
    }
    Object.defineProperty(window.HTMLMediaElement.prototype, 'currentTime', {
      configurable: true,
      get: () => currentTime,
      set: (v: number) => { currentTime = v; },
    });
  });

  it('jumps to the live edge on a 404 instead of counting towards "stuck"', async () => {
    renderPlayer();
    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
    const hls: any = instances[0];
    frag404(hls);
    expect(currentTime).toBe(120);
    expect(hls.startLoad).toHaveBeenCalledWith(120);
    act(() => hls.handlers.hlsFragLoaded?.('hlsFragLoaded', { frag: { url: 'segment_live.ts' } }));
    frag404(hls, 9);                                       // nine more, but the counter was reset by the loaded fragment
    expect(screen.queryByText(/FFmpeg appears stuck/)).toBeNull();
    expect(hls.destroy).not.toHaveBeenCalled();
  });

  it('still says stuck when even the newest segments are missing', async () => {
    renderPlayer();
    await waitFor(() => expect(instances.length).toBeGreaterThan(0));
    frag404(instances[0], 10);
    await waitFor(() => expect(screen.getByText(/FFmpeg appears stuck/)).toBeTruthy());
  });
});
