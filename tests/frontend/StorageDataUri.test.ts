/**
 * A capture that arrives inline as a data: URI (BUG-0798).
 *
 * `normalizeStoragePath()` had no data: branch, so a `data:image/jpeg;base64,…`
 * capture was sent to `POST /server/storage/signed-url` like any other path.
 * The server signed the base64 payload as if it were a key, the browser asked
 * for `/virtualpytest/data%3Aimage/jpeg%3Bbase64%2C/…` and got nothing — an
 * empty grey box where the thumbnail should be, with no error.
 */
import { describe, expect, it, vi } from 'vitest';

const post = vi.hoisted(() => vi.fn());

vi.mock('../../frontend/src/utils/apiClient', () => ({
  api: {
    get: vi.fn(),
    post,
  },
  apiClient: vi.fn(),
  apiClientJson: vi.fn(),
  default: vi.fn(),
}));

import { getR2Url } from '../../frontend/src/utils/infrastructure/cloudflareUtils';

const DATA_URI = 'data:image/jpeg;base64,/9j/4AAQSkZJRg==';

describe('a capture that came inline as a data URI', () => {
  it('is used as it is, not signed as a storage path', async () => {
    const url = await getR2Url(DATA_URI);

    expect(url).toBe(DATA_URI);
    // The server was never asked to sign it.
    expect(post).not.toHaveBeenCalled();
  });
});
