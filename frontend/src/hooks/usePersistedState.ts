import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Drop-in replacement for useState that mirrors the value to localStorage so
 * it survives page refresh and route navigation.
 *
 * The stored value is keyed (one localStorage entry per `key`), JSON-encoded,
 * and read back lazily on first mount. A malformed/absent entry falls back to
 * `defaultValue` without throwing.
 */
export function usePersistedState<T>(
  key: string,
  defaultValue: T,
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key);
      return raw !== null ? (JSON.parse(raw) as T) : defaultValue;
    } catch {
      return defaultValue;
    }
  });

  // Avoid re-writing the default back to storage on the very first render.
  const hydrated = useRef(false);

  useEffect(() => {
    if (!hydrated.current) {
      hydrated.current = true;
      return;
    }
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Quota exceeded / storage disabled — keep working in-memory only.
    }
  }, [key, value]);

  // Stable setter identity so callers can keep it out of effect deps.
  const setPersisted = useCallback<React.Dispatch<React.SetStateAction<T>>>(
    (next) => setValue(next),
    [],
  );

  return [value, setPersisted];
}
