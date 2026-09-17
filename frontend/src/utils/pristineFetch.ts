/**
 * The real `fetch`, captured before `installFetchAuth` wraps it.
 *
 * Discovery (`/server/auth/check`) must go out with NO credential: its whole purpose is
 * to learn which Supabase identity a server belongs to, so there is nothing to attach
 * yet, and letting the interceptor fall back to the primary token would send that token
 * to a server we have not yet established shares its Supabase — the exact leak TASK-18
 * closes.
 *
 * Its own module so `installFetchAuth` (which captures it) and `lib/serverIdentity`
 * (which uses it) do not import each other in a cycle.
 */

let pristine: typeof window.fetch | null = null;

/** Called once by installFetchAuth, before it replaces window.fetch. */
export const capturePristineFetch = (fn: typeof window.fetch): void => {
  if (!pristine) pristine = fn;
};

/** Fetch that the auth interceptor never touches. */
export const unauthenticatedFetch: typeof window.fetch = (input, init) =>
  (pristine ?? window.fetch)(input, init);
