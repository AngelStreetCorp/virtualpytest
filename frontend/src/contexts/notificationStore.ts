import { useSyncExternalStore } from 'react';

import { APP_CONFIG } from '../config/constants';

export type NotificationSeverity = 'error' | 'warning' | 'info' | 'success';

export type NotificationCategory =
  | 'device' | 'host' | 'script' | 'capture' | 'ai_spend' | 'storage' | 'deploy' | 'security' | 'support' | 'action';

export const NOTIFICATION_CATEGORIES: NotificationCategory[] = [
  'device', 'host', 'script', 'capture', 'ai_spend', 'storage', 'deploy', 'security', 'support', 'action',
];

export interface NotificationItem {
  id: string;
  /** Missing on entries stored before TASK-145: they count as `action`. */
  category?: NotificationCategory;
  severity: NotificationSeverity;
  /** Already translated text, as shown in the toast. */
  message: string;
  /** In-app path the item opens (e.g. `/status?host=pi1`). */
  to?: string;
  /** What it is about (device, host, ...): lets the viewer mute one device. */
  scope?: NotificationScope;
  ts: number;
  read: boolean;
  /** TASK-100: epoch ms when the platform saw the underlying condition clear. The row stays in the bell
   *  for `RESOLVED_GRACE_MS` after this so the operator can read "X was full 14:00, you cleared it 14:17". */
  resolved_at?: number | null;
}

/** True when the underlying condition has been seen clear (auto-resolve). */
export const isResolved = (n: NotificationItem): boolean => typeof n.resolved_at === 'number';

// ---- Preferences (TASK-145, contract #43): user+device > user > device > project > workspace > team > platform default ----

export type PrefScopeType = 'team' | 'workspace' | 'project' | 'device' | 'user';
export type MinSeverity = 'info' | 'warning' | 'error';

export interface NotificationPrefRow {
  scope_type: PrefScopeType;
  /** workspace / project / device id; the user id for a user row; the team id for a team row. */
  scope_id: string;
  user_id?: string | null;
  category: NotificationCategory;
  bell: boolean;
  toast: boolean;
  email: boolean;
  min_severity: MinSeverity;
  /** ISO date; the row's channels are off until then. */
  muted_until?: string | null;
  locked?: boolean;
}

export interface NotificationScope {
  team_id?: string;
  workspace_id?: string;
  project_id?: string;
  device_id?: string;
  host_name?: string;
}

export interface ResolvedChannels {
  bell: boolean;
  toast: boolean;
  email: boolean;
}

type Channels = ResolvedChannels & { min_severity: MinSeverity };

/** Platform defaults (NOTIFICATIONS.md table). `toast` is on/off, `toastMin` the lowest severity that toasts. */
export const PLATFORM_DEFAULTS: Record<NotificationCategory, { toast: boolean; toastMin: MinSeverity }> = {
  device: { toast: true, toastMin: 'error' },
  host: { toast: true, toastMin: 'error' },
  script: { toast: false, toastMin: 'error' },
  capture: { toast: true, toastMin: 'warning' },
  ai_spend: { toast: true, toastMin: 'warning' },
  storage: { toast: true, toastMin: 'warning' },
  deploy: { toast: false, toastMin: 'error' },
  security: { toast: true, toastMin: 'error' },
  support: { toast: false, toastMin: 'info' },
  action: { toast: true, toastMin: 'info' },
};

const RANK: Record<NotificationSeverity, number> = { info: 0, success: 0, warning: 1, error: 2 };
const MIN_RANK: Record<MinSeverity, number> = { info: 0, warning: 1, error: 2 };
const SPECIFICITY: PrefScopeType[] = ['team', 'workspace', 'project', 'device', 'user'];
/** Position of a row in the walk. A device row with a user_id is "this user + this device": the most specific of all. */
const rowRank = (r: Pick<NotificationPrefRow, 'scope_type' | 'user_id'>): number =>
  r.scope_type === 'device' && r.user_id ? SPECIFICITY.length : SPECIFICITY.indexOf(r.scope_type);

/**
 * Which channels a notification uses for this viewer. Pure.
 * Rows apply from the least to the most specific scope (team, workspace, project, device, user, user+device);
 * a row that does not match the notification's scope (or another user's row) is skipped. A locked row ends the walk: nothing more
 * specific can change that category. A muted row switches bell, toast and email off until `muted_until`.
 * `min_severity` of the winning row gates the interruptive channels (toast, email); the bell keeps everything.
 * Without a row the platform default decides the toast and the bell shows everything. An `action` error always toasts (the user just did it).
 */
export const resolvePrefs = (
  rows: NotificationPrefRow[],
  n: { category: NotificationCategory; severity: NotificationSeverity; scope?: NotificationScope },
  userId: string | undefined,
  now: number = Date.now(),
): ResolvedChannels => {
  const def = PLATFORM_DEFAULTS[n.category];
  const rank = RANK[n.severity];
  let ch: Channels | null = null;
  let muted = false;
  const applicable = rows
    .filter((r) => {
      if (r.category !== n.category) return false;
      if (r.scope_type === 'workspace') return !!n.scope?.workspace_id && r.scope_id === n.scope.workspace_id;
      if (r.scope_type === 'project') return !!n.scope?.project_id && r.scope_id === n.scope.project_id;
      if (r.scope_type === 'device') return !!n.scope?.device_id && r.scope_id === n.scope.device_id && (!r.user_id || (!!userId && r.user_id === userId));
      if (r.scope_type === 'user') return !!userId && (r.user_id || r.scope_id) === userId;
      return true;
    })
    .sort((a, b) => rowRank(a) - rowRank(b));
  for (const r of applicable) {
    ch = { bell: r.bell, toast: r.toast, email: r.email, min_severity: r.min_severity };
    muted = !!r.muted_until && Date.parse(r.muted_until) > now;
    if (r.locked) break;
  }
  let out: ResolvedChannels;
  if (!ch) {
    out = { bell: true, toast: def.toast && rank >= MIN_RANK[def.toastMin], email: false };
  } else if (muted) {
    out = { bell: false, toast: false, email: false };
  } else {
    const loud = rank >= MIN_RANK[ch.min_severity];
    out = { bell: ch.bell, toast: ch.toast && loud, email: ch.email && loud };
  }
  if (n.category === 'action' && n.severity === 'error') out.toast = true;
  return out;
};

export const NOTIFICATIONS_KEY = 'virtualpytest:notifications';
export const NOTIFICATIONS_MAX = 200;
export const NOTIFICATIONS_OWNER_KEY = 'virtualpytest:notifications:owner';
export const NOTIFICATIONS_DISMISSED_KEY = 'virtualpytest:notifications:dismissed';
export const NOTIFICATIONS_TOASTED_KEY = 'virtualpytest:notifications:toasted';
/** A producer that re-fires the same id toasts it at most this many times. */
export const TOAST_MAX_SHOWS = 2;
const MUTE_MAX = 500;

/** TASK-100: resolved rows stay in the bell this long before being auto-purged. */
export const RESOLVED_GRACE_MS = 2 * 60 * 60 * 1000;
/** TASK-100: anything this old (by `ts`) is purged regardless of state, so the bell has a rolling window. */
export const MAX_AGE_MS = 48 * 60 * 60 * 1000;

/** Newest first, one entry per id (a repeat replaces the old entry and is unread again), capped at 200.
 *  A re-add of an item that had been resolved clears `resolved_at` (the problem is back). */
export const addToList = (list: NotificationItem[], item: Omit<NotificationItem, 'read'>): NotificationItem[] =>
  [{ ...item, read: false, resolved_at: null }, ...list.filter((n) => n.id !== item.id)].slice(0, NOTIFICATIONS_MAX);

/** What to remove at this moment: items resolved longer ago than the grace period, and anything
 *  older than the rolling window. Pure; called once per poll and on app start. */
export const purgeOlderThan = (
  list: NotificationItem[],
  now: number = Date.now(),
  graceMs: number = RESOLVED_GRACE_MS,
  maxAgeMs: number = MAX_AGE_MS,
): NotificationItem[] => {
  let dirty = false;
  const kept = list.filter((n) => {
    const stale = typeof n.resolved_at === 'number' && now - n.resolved_at >= graceMs;
    const aged = now - n.ts >= maxAgeMs;
    if (stale || aged) { dirty = true; return false; }
    return true;
  });
  return dirty ? kept : list;
};

/** A history row as the server stores it; `dismissed` rows are tombstones. `resolved_at`/`dismissed_at`
 *  are optional columns added by TASK-100. */
export type ServerNotification = NotificationItem & { dismissed?: boolean };

/**
 * Local cache + server history, merged by id. Pure.
 * The newer `ts` wins; a tombstone beats an older local copy (so a dismissal made in another browser sticks);
 * `push` is what the server lacks or has older and must be sent up.
 * TASK-100: when both sides have the same id, the richer side wins — server wins by default, but if
 * the local copy has `resolved_at` and the server copy does not, we keep the local timestamp and push it up.
 */
export const mergeHistory = (
  local: NotificationItem[],
  server: ServerNotification[],
): { merged: NotificationItem[]; push: NotificationItem[] } => {
  const byId = new Map<string, NotificationItem>();
  const push: NotificationItem[] = [];
  const serverById = new Map(server.map((s) => [s.id, s]));
  for (const s of server) if (!s.dismissed) byId.set(s.id, { ...s, dismissed: undefined } as NotificationItem);
  for (const l of local) {
    const s = serverById.get(l.id);
    if (!s) {
      byId.set(l.id, l);
      push.push(l);
    } else if (l.ts > s.ts) {
      byId.set(l.id, l);
      push.push(l);
    } else if (!s.dismissed && l.ts === s.ts) {
      // Same ts: union fields. A read flag on either side wins; a resolve on either side wins.
      const merged: NotificationItem = {
        ...s,
        read: !!(s.read || l.read),
        resolved_at: s.resolved_at ?? l.resolved_at ?? null,
      };
      byId.set(l.id, merged);
      if (l.read && !s.read) push.push(merged);
    }
  }
  const merged = Array.from(byId.values()).sort((a, b) => b.ts - a.ts).slice(0, NOTIFICATIONS_MAX);
  return { merged, push };
};

/** Live + resolved items, live first (newest ts), then resolved (newest resolved_at first). Pure. */
export const sortForBell = (list: NotificationItem[]): NotificationItem[] => {
  const live = list.filter((n) => !isResolved(n)).sort((a, b) => b.ts - a.ts);
  const fixed = list.filter((n) => isResolved(n)).sort((a, b) => (b.resolved_at ?? 0) - (a.resolved_at ?? 0));
  return [...live, ...fixed];
};

/** How the store tells the server (registered by useNotificationHistory once the user is known). Never awaited. */
export interface NotificationSync {
  upsert: (items: NotificationItem[]) => void;
  markRead: (id?: string) => void;
  dismiss: (id?: string) => void;
  /** TASK-100: drop the id from server-side history (used by `purgeOlderThan`). */
  purge: (ids: string[]) => void;
}
let sync: NotificationSync | null = null;
export const registerNotificationSync = (s: NotificationSync | null) => {
  sync = s;
};

const readOwner = (): string | null => {
  try {
    return localStorage.getItem(NOTIFICATIONS_OWNER_KEY);
  } catch {
    return null;
  }
};

const read = (): NotificationItem[] => {
  try {
    const parsed = JSON.parse(localStorage.getItem(NOTIFICATIONS_KEY) ?? '[]');
    return Array.isArray(parsed) ? parsed.filter((n) => n && typeof n.id === 'string').slice(0, NOTIFICATIONS_MAX) : [];
  } catch {
    return [];
  }
};

const readJson = <T,>(key: string, fallback: T): T => {
  try {
    const v = JSON.parse(localStorage.getItem(key) ?? 'null');
    return v ?? fallback;
  } catch {
    return fallback;
  }
};
const writeJson = (key: string, v: unknown) => {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* storage blocked: the mute lasts for this tab only */
  }
};

/** Ids the user dismissed or skipped: never recorded or toasted again, even when the producer re-fires them. */
let dismissedIds: string[] = readJson<string[]>(NOTIFICATIONS_DISMISSED_KEY, []);
let toastCounts: Record<string, number> = readJson<Record<string, number>>(NOTIFICATIONS_TOASTED_KEY, {});

export const isDismissed = (id: string): boolean => dismissedIds.includes(id);
const muteIds = (ids: string[]) => {
  dismissedIds = Array.from(new Set([...dismissedIds, ...ids])).slice(-MUTE_MAX);
  writeJson(NOTIFICATIONS_DISMISSED_KEY, dismissedIds);
};
/** Counts one toast of this id; false once it has been shown `TOAST_MAX_SHOWS` times. */
const takeToastSlot = (id: string): boolean => {
  const n = toastCounts[id] ?? 0;
  if (n >= TOAST_MAX_SHOWS) return false;
  toastCounts = { ...toastCounts, [id]: n + 1 };
  const keys = Object.keys(toastCounts);
  if (keys.length > MUTE_MAX) delete toastCounts[keys[0]];
  writeJson(NOTIFICATIONS_TOASTED_KEY, toastCounts);
  return true;
};

let items: NotificationItem[] = read();
const listeners = new Set<() => void>();

const commit = (next: NotificationItem[]) => {
  items = next;
  try {
    localStorage.setItem(NOTIFICATIONS_KEY, JSON.stringify(next));
  } catch {
    /* storage blocked: the list stays in memory for this tab */
  }
  listeners.forEach((l) => l());
};

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};

export const notificationStore = {
  add: (item: Omit<NotificationItem, 'read'>) => {
    commit(addToList(items, item));
    sync?.upsert([items[0]]);
  },
  markRead: (id: string) => {
    commit(items.map((n) => (n.id === id ? { ...n, read: true } : n)));
    sync?.markRead(id);
  },
  markAllRead: () => {
    commit(items.map((n) => ({ ...n, read: true })));
    sync?.markRead();
  },
  /** TASK-100: drop from the bell now, ask the server for the same (existing tombstone path). */
  dismiss: (id: string) => {
    muteIds([id]);
    const next = items.map((n) => (n.id === id ? { ...n, resolved_at: null } : n));
    commit(next.filter((n) => n.id !== id));
    sync?.dismiss(id);
    sync?.upsert(next.filter((n) => n.id === id));
  },
  clear: () => {
    muteIds(items.map((n) => n.id));
    const stamped = items.map((n) => ({ ...n, resolved_at: null }));
    commit([]);
    sync?.dismiss();
    sync?.upsert(stamped);
  },
  /**
   * TASK-100: mark the underlying condition as cleared. First resolution wins: a later recurrence
   * (notify() with the same id) clears the flag.
   */
  resolve: (id: string, now: number = Date.now()) => {
    let changed = false;
    const next = items.map((n) => {
      if (n.id !== id) return n;
      if (typeof n.resolved_at === 'number') return n;
      changed = true;
      return { ...n, resolved_at: now, read: true };
    });
    if (!changed) return;
    const resolved = next.find((n) => n.id === id);
    commit(next);
    if (resolved) sync?.upsert([resolved]);
  },
  /**
   * TASK-100: drop resolved items past the grace period and items of any other category past the rolling
   * 48 h cap. Pure helper exposed for tests; the store runs it implicitly via `commit()` in the
   * dashboard auto-resolve pass.
   */
  purgeOlderThan: (now: number = Date.now()) => {
    const idsToForget: string[] = [];
    const kept = purgeOlderThan(items, now);
    if (kept.length !== items.length) {
      const keptIds = new Set(kept.map((n) => n.id));
      for (const n of items) if (!keptIds.has(n.id)) idsToForget.push(n.id);
    }
    commit(kept);
    if (idsToForget.length) sync?.purge(idsToForget);
  },
  /**
   * The signed-in user's server history arrived: merge it with the local cache. A cache that belonged to another
   * account is dropped first, so one account's history never lands in another's.
   */
  loadServer: (userId: string, server: ServerNotification[]) => {
    const owner = readOwner();
    const local = owner && owner !== userId ? [] : items;
    try {
      localStorage.setItem(NOTIFICATIONS_OWNER_KEY, userId);
    } catch {
      /* storage blocked */
    }
    const { merged, push } = mergeHistory(local, server);
    commit(purgeOlderThan(merged).filter((n) => !isDismissed(n.id)));
    if (push.length) sync?.upsert(push.slice(0, 200));
  },
};

let prefRows: NotificationPrefRow[] = [];
let prefUserId: string | undefined;
export const setNotificationPrefs = (rows: NotificationPrefRow[], userId?: string) => {
  prefRows = rows;
  prefUserId = userId;
};

type ToastRenderer = (n: { id: string; severity: NotificationSeverity; message: string; action?: { label: string; to?: string; onClick?: () => void }; duration?: number }) => void;
let renderToast: ToastRenderer | null = null;
/** Registered by ToastProvider: how a notification that passes the preferences becomes a toast. */
export const registerToastRenderer = (r: ToastRenderer | null) => {
  renderToast = r;
};

export interface NotifyInput {
  /** Stable per problem episode. */
  id: string;
  category: NotificationCategory;
  severity: NotificationSeverity;
  /** Already translated. */
  message: string;
  /** Page that shows the cause. */
  to?: string;
  scope?: NotificationScope;
  /** The toast's button; omit for a record-only entry. */
  action?: { label: string; to?: string; onClick?: () => void };
  duration?: number;
}

/** Records the item for the bell and toasts it, each only when the viewer's preferences say so. */
export const notify = (n: NotifyInput): ResolvedChannels => {
  if (isDismissed(n.id)) return { bell: false, toast: false, email: false };
  const ch = resolvePrefs(prefRows, n, prefUserId);
  const scope = { team_id: APP_CONFIG.DEFAULT_TEAM_ID, ...n.scope };
  if (ch.bell) notificationStore.add({ id: n.id, category: n.category, severity: n.severity, message: n.message, to: n.to, scope, ts: Date.now() });
  if (ch.toast && renderToast && takeToastSlot(n.id)) renderToast({ id: n.id, severity: n.severity, message: n.message, action: n.action, duration: n.duration });
  return ch;
};

export const useNotifications = (): NotificationItem[] => useSyncExternalStore(subscribe, () => items);

// ---- The 24 h digest waits for the account's history before it counts anything (TASK-166) ----

/** True once the server history has been merged (or the load failed and the local cache is all there is). */
let historyLoaded = false;
const historyListeners = new Set<() => void>();

/** Called by useNotificationHistory once the merge is done (or has failed). */
export const markHistoryLoaded = () => {
  if (historyLoaded) return;
  historyLoaded = true;
  historyListeners.forEach((l) => l());
};

export const useHistoryLoaded = (): boolean =>
  useSyncExternalStore(
    (l) => {
      historyListeners.add(l);
      return () => {
        historyListeners.delete(l);
      };
    },
    () => historyLoaded,
  );

/** A platform problem that is open right now (drives the persistent Dashboard chip). Not persisted. */
export interface ActiveProblem {
  id: string;
  message: string;
  to: string;
}

let active: ActiveProblem[] = [];
const activeListeners = new Set<() => void>();

export const setActiveProblems = (next: ActiveProblem[]) => {
  if (JSON.stringify(next) === JSON.stringify(active)) return;
  active = next;
  activeListeners.forEach((l) => l());
};

export const useActiveProblems = (): ActiveProblem[] =>
  useSyncExternalStore(
    (l) => {
      activeListeners.add(l);
      return () => {
        activeListeners.delete(l);
      };
    },
    () => active,
  );


/** What a category does at `scopeType` when that level has no row of its own: the next less specific row, else the platform default. */
export const inheritedRow = (
  rows: NotificationPrefRow[],
  category: NotificationCategory,
  scopeType: PrefScopeType,
  scopeId: string,
): Pick<NotificationPrefRow, 'bell' | 'toast' | 'email' | 'min_severity' | 'locked'> => {
  const below = SPECIFICITY.indexOf(scopeType);
  let found: NotificationPrefRow | null = null;
  for (const r of rows) {
    if (r.category !== category) continue;
    if (r.scope_type === 'device') continue; // Settings never edits a device row as a level
    const level = SPECIFICITY.indexOf(r.scope_type);
    if (level >= below) continue;
    if ((r.scope_type === 'workspace' || r.scope_type === 'project') && r.scope_id !== scopeId) continue;
    if (!found || level > SPECIFICITY.indexOf(found.scope_type)) found = r;
  }
  if (found) return { bell: found.bell, toast: found.toast, email: found.email, min_severity: found.min_severity, locked: found.locked };
  const def = PLATFORM_DEFAULTS[category];
  return { bell: true, toast: def.toast, email: false, min_severity: def.toastMin, locked: false };
};
