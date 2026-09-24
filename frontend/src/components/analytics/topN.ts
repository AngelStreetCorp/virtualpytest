/**
 * Truncate a ranking to N bars plus one "others" row.
 *
 * With 12 devices this is a no-op. On a customer install with 200 it is the
 * difference between a readable card and a 200-bar chart that is both unreadable and
 * slow, and it keeps every ranking card the same height whatever the fleet size.
 *
 * The tail is SUMMED rather than dropped, so the bars still add up to the total shown
 * elsewhere on the tab. A chart that quietly loses 190 devices is worse than one that
 * says "others (190)".
 *
 * The backend already applies the same rule to the sections it computes (see
 * `_top_n` in shared/src/lib/database/analytics_db.py); this is for rankings the
 * frontend derives itself, and for re-truncating after a client-side filter.
 */

import { Ranked } from '../../types/pages/Analytics_Types';

/** The API's row shape, reused rather than redeclared. */
export type RankedItem = Ranked;

export const topN = (items: RankedItem[], n = 10): RankedItem[] => {
  if (items.length <= n) {
    return [...items].sort((a, b) => b.value - a.value);
  }
  const ordered = [...items].sort((a, b) => b.value - a.value);
  const head = ordered.slice(0, n);
  const tail = ordered.slice(n);
  return [
    ...head,
    {
      name: `others (${tail.length})`,
      value: tail.reduce((sum, item) => sum + item.value, 0),
      is_others: true,
    },
  ];
};

/** Same, but worst-first — for "lowest availability" style cards. */
export const bottomN = (items: RankedItem[], n = 10): RankedItem[] =>
  [...items].sort((a, b) => a.value - b.value).slice(0, n);

export default topN;
