import { isResolved, type NotificationItem } from '../../contexts/notificationStore';

/**
 * The 24 h digest (TASK-166): once per session, the platform looks at the notification history
 * of the last 24 hours and surfaces the problems that matter.
 *
 * The rule the owner asked for: if there are errors, the three most recent errors win; if there
 * are no errors, the three most recent warnings do. Errors always beat warnings — a warning is
 * never more urgent than an error.
 *
 * The digest reads the *history*, not the live dashboard poll: a problem that started yesterday
 * is still worth showing, and a category whose toast is switched off (`script`) is still worth
 * counting. Pure: the timing lives in the component.
 */

/** How far back the digest looks. */
export const DIGEST_WINDOW_MS = 24 * 60 * 60 * 1000;
/** How many problems the digest shows. */
export const DIGEST_TOP_N = 3;
/** The toast id: one digest at a time. */
export const DIGEST_TOAST_ID = 'vpt-notification-digest';

export interface DigestSelection {
  severity: 'error' | 'warning';
  /** Every problem of that severity inside the window (the number in the pill). */
  total: number;
  /** The top ones to show, newest first. */
  items: NotificationItem[];
}

/**
 * The problems the digest shows, or null when there is nothing to say.
 *
 * Only live problems count: a problem the platform has already seen clear (`resolved_at`) is in
 * the bell with its "Fixed X ago" note, not in the digest.
 */
export const selectDigest = (
  items: ReadonlyArray<NotificationItem>,
  now: number,
  windowMs: number = DIGEST_WINDOW_MS,
  topN: number = DIGEST_TOP_N,
): DigestSelection | null => {
  const inWindow = items.filter(
    (n) =>
      (n.severity === 'error' || n.severity === 'warning') &&
      !isResolved(n) &&
      now - n.ts < windowMs,
  );
  const errors = inWindow.filter((n) => n.severity === 'error').sort((a, b) => b.ts - a.ts);
  const warnings = inWindow.filter((n) => n.severity === 'warning').sort((a, b) => b.ts - a.ts);
  const chosen = errors.length ? errors : warnings;
  if (!chosen.length) return null;
  return {
    severity: errors.length ? 'error' : 'warning',
    total: chosen.length,
    items: chosen.slice(0, topN),
  };
};
