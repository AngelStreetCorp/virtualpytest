import { createRequestCache } from './requestCache';

/**
 * The testcase list, shared so the several components that show it issue one request
 * between them. A third copy of the logic now in `requestCache.ts`.
 *
 * The old signature took an optional `teamId` that went into the cache key. No caller
 * ever passed it, so every entry keyed as `'default'` and the parameter only made the
 * key look team-scoped when it was not. Dropped rather than kept as a decoration.
 */

const testcaseList = createRequestCache('testcaseList', 30_000);

export const getCachedTestCaseList = (apiUrl: string) => testcaseList.get(apiUrl);
export const invalidateTestCaseListCache = () => testcaseList.invalidate();
