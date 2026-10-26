import { useCallback, useState } from 'react';

/**
 * Categories the QuickfilterBadgeArea row can show. Each value also names the
 * shared filter-store key the chip row writes to:
 *   - profiles → profileFilter (DeviceProfileChips already uses this)
 *   - models   → deviceModelFilter
 *   - targets  → targetFilter
 *   - favorites → a derived toggle on the target filter (favorite targets only)
 *
 * Order in the array = display order on the row. Presence = visible.
 * Stored in localStorage under `vpt_quickfilter_config_v1`.
 */
export type CategoryId = 'profiles' | 'models' | 'tags' | 'favorites';

/** Ordered list of all category ids — the default order in the configure popover. */
export const ALL_CATEGORIES: CategoryId[] = ['profiles', 'models', 'tags', 'favorites'];

/** What the row shows on a fresh install. Matches today's behavior (profiles only). */
export const DEFAULT_CATEGORIES: CategoryId[] = ['profiles'];

const STORAGE_KEY = 'vpt_quickfilter_config_v1';

/**
 * Validate the localStorage payload. Old configs from before a schema bump
 * may carry unknown ids — drop them. An empty array is a valid user choice
 * ("show no quickfilters") and stays empty; the bolt remains visible so the
 * user can re-enable categories via the configure popover.
 */
const sanitize = (raw: unknown): CategoryId[] => {
  if (!Array.isArray(raw)) return DEFAULT_CATEGORIES;
  const valid = new Set<string>(ALL_CATEGORIES);
  const seen = new Set<CategoryId>();
  const next: CategoryId[] = [];
  for (const entry of raw) {
    if (typeof entry !== 'string') continue;
    if (!valid.has(entry)) continue;
    // Type-narrowing: we just checked `entry` is a member of ALL_CATEGORIES.
    const id = entry as CategoryId;
    if (seen.has(id)) continue;
    seen.add(id);
    next.push(id);
  }
  return next;
};

/**
 * Read the persisted config once at mount, sanitized. Kept out of
 * `usePersistedState` so the body of the hook stays declarative.
 */
const useSanitizedPersistedCategories = (): [CategoryId[], React.Dispatch<React.SetStateAction<CategoryId[]>>] => {
  const [value, setValue] = useState<CategoryId[]>(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      return raw === null ? DEFAULT_CATEGORIES : sanitize(JSON.parse(raw));
    } catch {
      return DEFAULT_CATEGORIES;
    }
  });
  // Mirror to localStorage on every change.
  const write = useCallback<React.Dispatch<React.SetStateAction<CategoryId[]>>>(
    (next) => {
      setValue((prev) => {
        const resolved = typeof next === 'function' ? (next as (p: CategoryId[]) => CategoryId[])(prev) : next;
        try {
          window.localStorage.setItem(STORAGE_KEY, JSON.stringify(resolved));
        } catch {
          // Quota exceeded / storage disabled — keep working in-memory only.
        }
        return resolved;
      });
    },
    [],
  );
  return [value, write];
};

export interface UseQuickfilterConfigReturn {
  /** Ordered, visible list. The row renders chips in this order. */
  categories: CategoryId[];
  /** Add a category if missing, remove if present. Reordering is its own op. */
  toggleCategory: (id: CategoryId) => void;
  /** Drag-to-reorder — moves `from` to position `to` (after splice). */
  reorder: (from: number, to: number) => void;
  /** Empty the selection. The bolt stays visible so the user can re-enable. */
  clear: () => void;
}

/**
 * Per-user config for which categories the QuickfilterBadgeArea row shows, and
 * in which order. Backed by localStorage; lifting to a server-side preferences
 * API is a follow-up so the choice syncs across browsers / devices.
 */
export const useQuickfilterConfig = (): UseQuickfilterConfigReturn => {
  const [categories, setCategories] = useSanitizedPersistedCategories();

  const toggleCategory = useCallback(
    (id: CategoryId) => {
      setCategories((prev) => {
        if (prev.includes(id)) {
          // Empty selection is a valid user choice — the bolt stays visible
          // so the user can re-enable a category from the configure popover.
          return prev.filter((c) => c !== id);
        }
        // Insert at the end so the operator's existing order is preserved on
        // first enable. Drag-to-reorder from the configure popover can re-shuffle.
        return [...prev, id];
      });
    },
    [setCategories],
  );

  const reorder = useCallback(
    (from: number, to: number) => {
      setCategories((prev) => {
        if (from === to) return prev;
        if (from < 0 || from >= prev.length) return prev;
        if (to < 0 || to >= prev.length) return prev;
        const next = [...prev];
        const [moved] = next.splice(from, 1);
        next.splice(to, 0, moved);
        return next;
      });
    },
    [setCategories],
  );

  const clear = useCallback(() => setCategories([]), [setCategories]);

  return { categories, toggleCategory, reorder, clear };
};