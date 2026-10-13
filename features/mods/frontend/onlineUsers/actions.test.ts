import { describe, expect, it } from 'vitest';

import { listedNames } from './actions';
import { MAX_NAMES } from './constants';

describe('online users', () => {
  it('lists names up to the cap and counts the rest', () => {
    const users = Array.from({ length: MAX_NAMES + 3 }, (_, i) => ({ userId: `u${i}`, name: `User ${i}` }));
    const r = listedNames({ online: users.length, users, sharedSessions: 0, timestamp: 0 });
    expect(r.names).toHaveLength(MAX_NAMES);
    expect(r.more).toBe(3);
  });
});
