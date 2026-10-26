/**
 * Pure logic of the drone "Flight history" view: the controller's command log (POST /server/drone/tello/command_history) grouped into
 * flights, and the series the charts draw. Mirrors shared/src/lib/drone/command_log.py: `flight` counts successful take-offs since the
 * controller started (0 = commands before the first take-off), `blocked` = the safety guard refused it, `clipped_from` = the guard
 * shortened it (what was asked is in `params`, what was sent in `sent`).
 */
export interface DroneCommand {
  ts: string;
  seq: number;
  command: string;
  params: Record<string, unknown>;
  sent: string | null;
  success: boolean;
  reply: string | null;
  blocked: boolean;
  landed: boolean;
  error: string | null;
  duration_ms: number;
  airborne: boolean;
  bat: number | null;
  h: number | null; // cm
  pose: { x: number; y: number; z?: number; yaw?: number } | null; // cm, dead-reckoned
  flight: number;
  clipped_from?: unknown;
}

export interface DroneFlight {
  flight: number;
  start: number; // ms
  end: number; // ms
  commands: DroneCommand[];
  blocked: number;
  failed: number;
  minBattery: number | null;
  maxHeightM: number | null;
}

export type CommandOutcome = 'ok' | 'blocked' | 'failed';

export const outcomeOf = (c: DroneCommand): CommandOutcome => (c.blocked ? 'blocked' : c.success ? 'ok' : 'failed');

const ms = (ts: string): number => {
  const t = Date.parse(ts);
  return Number.isFinite(t) ? t : 0;
};

/** Flights, newest first. */
export function groupFlights(commands: DroneCommand[]): DroneFlight[] {
  const by = new Map<number, DroneCommand[]>();
  for (const c of commands) {
    const list = by.get(c.flight) ?? [];
    list.push(c);
    by.set(c.flight, list);
  }
  return Array.from(by.entries())
    .map(([flight, list]) => {
      const sorted = [...list].sort((a, b) => a.seq - b.seq);
      const bats = sorted.map((c) => c.bat).filter((v): v is number => typeof v === 'number');
      const hs = sorted.map((c) => c.h).filter((v): v is number => typeof v === 'number');
      return {
        flight,
        start: ms(sorted[0].ts),
        end: ms(sorted[sorted.length - 1].ts) + (sorted[sorted.length - 1].duration_ms || 0),
        commands: sorted,
        blocked: sorted.filter((c) => c.blocked).length,
        failed: sorted.filter((c) => !c.success && !c.blocked).length,
        minBattery: bats.length ? Math.min(...bats) : null,
        maxHeightM: hs.length ? Math.max(...hs) / 100 : null,
      };
    })
    .sort((a, b) => b.flight - a.flight);
}

export const flightLabel = (f: DroneFlight): string => (f.flight === 0 ? 'On the ground' : `Flight ${f.flight}`);

/** "move forward 50 cm", "takeoff", "rc 0 0 40 0" */
export function describeCommand(c: DroneCommand): string {
  const p = c.params ?? {};
  if (c.command === 'move') return `move ${String(p.direction ?? '')} ${String(p.cm ?? '')} cm`.replace(/\s+/g, ' ').trim();
  if (c.command === 'rotate') return `rotate ${String(p.direction ?? '')} ${String(p.deg ?? '')}°`.replace(/\s+/g, ' ').trim();
  if (c.command === 'rc') return `stick ${[p.lr, p.fb, p.ud, p.yaw].map((v) => (typeof v === 'number' ? v : 0)).join(' ')}`;
  if (c.command === 'sdk') return `sdk ${String(p.cmd ?? '')}`.trim();
  return c.command;
}

/** The SDK text a command asks for ("forward 50", "cw 45", "takeoff"), or null for commands without a fixed text (stick, raw sdk). */
const askedSdk = (c: DroneCommand): string | null => {
  const p = c.params ?? {};
  if (c.command === 'move') return `${String(p.direction ?? '')} ${String(p.cm ?? '')}`.trim();
  if (c.command === 'rotate') return `${String(p.direction ?? '')} ${String(p.deg ?? '')}`.trim();
  if (c.command === 'takeoff' || c.command === 'land' || c.command === 'emergency') return c.command;
  return null;
};

/** What was really sent when it differs from what was asked (the guard shortened it, e.g. up 400 -> up 70), else null. */
export function sentNote(c: DroneCommand): string | null {
  if (!c.sent || c.blocked) return null;
  const asked = askedSdk(c);
  if (asked === null) return null;
  return c.sent.replace(/\s+/g, ' ').trim() === asked.replace(/\s+/g, ' ').trim() ? null : c.sent;
}

export interface SeriesPoint {
  t: number; // ms
  v: number;
}

/** Battery percent and height in metres at each command that reports them. */
export function seriesOf(f: DroneFlight): { battery: SeriesPoint[]; height: SeriesPoint[] } {
  const battery: SeriesPoint[] = [];
  const height: SeriesPoint[] = [];
  for (const c of f.commands) {
    const t = ms(c.ts);
    if (typeof c.bat === 'number') battery.push({ t, v: c.bat });
    if (typeof c.h === 'number') height.push({ t, v: c.h / 100 });
  }
  return { battery, height };
}

export interface PathPoint {
  x: number;
  y: number;
  seq: number;
  outcome: CommandOutcome;
}

export const pathOf = (f: DroneFlight): PathPoint[] =>
  f.commands.filter((c) => c.pose && Number.isFinite(c.pose.x) && Number.isFinite(c.pose.y)).map((c) => ({ x: c.pose!.x, y: c.pose!.y, seq: c.seq, outcome: outcomeOf(c) }));

/** Lengths like "2 m 10 s". */
export const formatDuration = (msec: number): string => {
  const s = Math.max(0, Math.round(msec / 1000));
  return s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`;
};
