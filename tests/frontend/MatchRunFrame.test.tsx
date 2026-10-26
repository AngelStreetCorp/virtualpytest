import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MatchRunFrame } from '../../frontend/src/components/monitoring/MatchRunFrame';

/**
 * BUG-0779: the frame was requested once without the host-session cookie (401) and once
 * again with `?_hs=<ts>` (404). The 401 alone decided the outcome: the <img> error handler
 * fired and the frame was declared "no longer on the host" even when the capture was there.
 *
 * The fix mints the session before the image is requested, so the only error left is a real
 * 404 — and the file is asked for once.
 */

const { ensureHostSessionOnceMock } = vi.hoisted(() => ({ ensureHostSessionOnceMock: vi.fn(async () => true) }));
vi.mock('../../frontend/src/utils/buildUrlUtils', () => ({
  ensureHostSessionOnce: ensureHostSessionOnceMock,
  ensureHostSession: vi.fn(async () => true),
  isGatedHostPath: (url: string) => !!url && url.includes('/host/'),
}));

vi.mock('../../frontend/src/hooks/useHostManager', () => ({
  useHostData: () => ({ getAllHosts: () => [{ host_name: 'h1' }] }),
}));

vi.mock('../../frontend/src/utils/matchRunFrame', () => ({
  matchRunFrameSrc: (_host: unknown, frameUrl: string) =>
    `http://h1/host/h1/stream/capture/captures/${frameUrl}`,
}));

beforeEach(() => {
  ensureHostSessionOnceMock.mockClear();
  ensureHostSessionOnceMock.mockImplementation(async () => true);
});

describe('a Localize frame', () => {
  it('mints the host session before the image is requested', async () => {
    render(<MatchRunFrame frameUrl="capture_1.jpg" hostName="h1" />);

    await waitFor(() => expect(screen.getByAltText('Screenshot')).toBeTruthy());
    expect(ensureHostSessionOnceMock).toHaveBeenCalled();
    // The image is only in the DOM once the session is there.
    expect(ensureHostSessionOnceMock.mock.calls[0][0]).toContain('/host/h1/stream/');
  });

  it('does not ask for the file while the session is being minted', async () => {
    let release: (ok: boolean) => void = () => {};
    ensureHostSessionOnceMock.mockImplementation(() => new Promise<boolean>((resolve) => { release = resolve; }));

    render(<MatchRunFrame frameUrl="capture_1.jpg" hostName="h1" />);

    expect(screen.queryByAltText('Screenshot')).toBeNull();
    release(true);
    await waitFor(() => expect(screen.getByAltText('Screenshot')).toBeTruthy());
  });

  it('says the capture is gone only when the file itself is gone', async () => {
    render(<MatchRunFrame frameUrl="capture_1.jpg" hostName="h1" />);
    await waitFor(() => expect(screen.getByAltText('Screenshot')).toBeTruthy());

    const img = screen.getByAltText('Screenshot') as HTMLImageElement;
    act(() => {
      img.dispatchEvent(new Event('error'));
    });

    await waitFor(() => expect(screen.getByText('Screenshot no longer on the host')).toBeTruthy());
  });
});

describe('a Localize frame whose host session cannot be minted (BUG-0779 review)', () => {
  it('shows the error state, not the grey placeholder for ever, and allows one retry', async () => {
    ensureHostSessionOnceMock.mockImplementation(async () => false);
    render(<MatchRunFrame frameUrl="capture_1.jpg" hostName="h1" />);

    await waitFor(() => expect(screen.getByText('Screenshot no longer on the host')).toBeTruthy());
    expect(screen.queryByAltText('Screenshot')).toBeNull();

    // the retry mints again, and the image appears once the host answers
    ensureHostSessionOnceMock.mockImplementation(async () => true);
    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => expect(screen.getByAltText('Screenshot')).toBeTruthy());
    expect(ensureHostSessionOnceMock).toHaveBeenCalledTimes(2);
  });

  it('offers the retry only once', async () => {
    ensureHostSessionOnceMock.mockImplementation(async () => false);
    render(<MatchRunFrame frameUrl="capture_1.jpg" hostName="h1" />);
    await waitFor(() => expect(screen.getByText('Retry')).toBeTruthy());
    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => expect(ensureHostSessionOnceMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText('Screenshot no longer on the host')).toBeTruthy());
    expect(screen.queryByText('Retry')).toBeNull();
  });
});
