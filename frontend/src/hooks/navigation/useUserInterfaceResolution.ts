/**
 * useUserInterfaceResolution — find the interface the navigation editor was
 * opened for, and say so when there is none.
 *
 * The editor is opened by name and mode: /navigation-editor/<name>?mode=prod.
 * A name that does not exist — or an interface that exists in dev only while
 * the prod snapshot is asked for — used to leave the editor blank and fully
 * enabled ("0/0 nodes", a live "Add Node" and "Publish"), so a typo read as an
 * empty tree and a developer could publish nodes into the wrong place
 * (BUG-0774). This hook reports the failure so the page can show it.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { useUserInterface, UserInterfaceNotFoundError } from '../pages/useUserInterface';

export interface SeededUserInterface {
  id: string;
  name: string;
  models: string[];
  mode?: 'dev' | 'prod';
}

export interface ResolvedUserInterfaceLike {
  name?: string;
  mode?: string;
}

/** The words shown when the interface cannot be opened. */
export const describeInterfaceResolveError = (error: unknown, treeName: string): string =>
  error instanceof UserInterfaceNotFoundError
    ? error.message
    : `Could not load the user interface "${treeName}": ${
        error instanceof Error ? error.message : 'unknown error'
      }`;

export interface UserInterfaceResolution {
  /** Why the interface could not be opened. Null while it loads, and once it is open. */
  error: string | null;
  /** Look the same interface up again after a failure. */
  retry: () => void;
}

/**
 * @param treeName       the interface name from the URL
 * @param mode           'dev' or 'prod' — the same name exists in both
 * @param seededInterface the interface the caller already had, if any
 * @param currentUserInterface the interface the editor is showing now, if any
 * @param onResolved     called with the interface that was found
 */
export const useUserInterfaceResolution = ({
  treeName,
  mode,
  seededInterface,
  currentUserInterface,
  onResolved,
}: {
  treeName: string;
  mode: 'dev' | 'prod';
  seededInterface?: SeededUserInterface | null;
  currentUserInterface?: ResolvedUserInterfaceLike | null;
  onResolved: (userInterface: any) => void;
}): UserInterfaceResolution => {
  const { getUserInterfaceByName } = useUserInterface();
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  // The key of the attempt already made. One attempt per tree+mode+retry, so a
  // failing lookup is not retried in a loop by every re-render.
  const attemptedRef = useRef<string | null>(null);
  // The attempt whose answer is still accepted. A lookup started for another
  // tree, mode or retry supersedes it.
  const activeRef = useRef<string | null>(null);
  // The caller's callback is rebuilt on every provider render (it closes over
  // the navigation context). The answer must not depend on that identity, so
  // the latest one is kept here instead of being an effect dependency.
  const onResolvedRef = useRef(onResolved);

  useEffect(() => {
    onResolvedRef.current = onResolved;
  }, [onResolved]);

  useEffect(() => {
    if (!treeName) return;

    const attemptKey = `${treeName}::${mode}#${attempt}`;
    if (attemptedRef.current === attemptKey) return;
    attemptedRef.current = attemptKey;
    activeRef.current = attemptKey;

    // The same name exists in dev and prod; the mode says which row is asked
    // for. A different tree or mode is a different lookup.
    if (currentUserInterface?.name === treeName && (currentUserInterface.mode || 'dev') === mode) {
      return;
    }

    // The caller already handed us the interface — no round-trip needed.
    if (seededInterface && seededInterface.name === treeName && (seededInterface.mode || 'dev') === mode) {
      onResolvedRef.current(seededInterface);
      return;
    }

    setError(null);

    // No cleanup cancels this lookup: the page re-renders for many unrelated
    // reasons, and dropping the answer of a lookup that is still running hid
    // the failure the page has to show (BUG-0774). A newer attempt supersedes
    // an older one through activeRef.
    const resolve = async () => {
      try {
        const resolved = await getUserInterfaceByName(treeName, mode);
        if (activeRef.current !== attemptKey) return;
        onResolvedRef.current(resolved);
      } catch (err) {
        if (activeRef.current !== attemptKey) return;
        setError(describeInterfaceResolveError(err, treeName));
      }
    };

    void resolve();
  }, [treeName, mode, attempt, seededInterface, currentUserInterface, getUserInterfaceByName]);

  const retry = useCallback(() => {
    setError(null);
    setAttempt((n) => n + 1);
  }, []);

  return { error, retry };
};

export default useUserInterfaceResolution;
