// @vitest-environment jsdom
/**
 * A capture that came back as an inline `data:` URI has to be shown as it is (BUG-0798).
 *
 * The Unknown screens page stores the thumbnail of a capture as a `data:image/jpeg;base64,…`
 * string. That string was handed to the R2 signing helper like any other storage path, so the
 * backend signed the payload as if it were a file name and the browser asked for
 * "/virtualpytest/data%3Aimage/jpeg%3Bbase64%2C…" — a 404, and an empty thumbnail.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const post = vi.hoisted(() => vi.fn());

vi.mock('../../frontend/src/utils/apiClient', () => ({
  api: { post },
}));

import { getR2Url } from '../../frontend/src/utils/infrastructure/cloudflareUtils';

const DATA_URI = 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQ==';

describe('an inline data: capture (BUG-0798)', () => {
  beforeEach(() => {
    post.mockReset();
  });

  it('returns the data: URI itself', async () => {
    await expect(getR2Url(DATA_URI)).resolves.toBe(DATA_URI);
  });

  it('never asks the backend to sign it', async () => {
    await getR2Url(DATA_URI);
    expect(post).not.toHaveBeenCalled();
  });
});
