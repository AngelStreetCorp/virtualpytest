import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { buildArchiveManifestUrl, buildTimelineFileUrl, fetchHostMedia } from '../utils/buildUrlUtils';
import { useHostSession } from './useHostSession';
import { hostTimelineStatus } from './useTimelineSupport';

/** One 10-minute archive chunk (a row of the host's `archive_manifest.json`). */
export interface TimelineChunk {
  hour: number;
  chunkIndex: number;
  /** epoch seconds the chunk was last written (its end) */
  endEpoch: number;
  /** host time of day at the chunk start, seconds (h*3600 + idx*600); no timezone involved */
  todStart: number;
}

export type TimelineLevel = 'day' | 'hour' | 'ten';

/** One 10-minute slot of the 24 h ring (missing chunks are slots too, shown hatched). */
export interface TimelineSlot {
  hour: number;
  chunkIndex: number;
  has: boolean;
  /** what dominates the slot, from its tracks file: 'ok' = nothing flagged, null = tracks not loaded (unknown, NOT ok) */
  flag: 'ad' | 'freeze' | 'blackscreen' | 'ok' | null;
}

export interface TimelineFlags {
  ad: number;
  freeze: number;
  blackscreen: number;
}

export interface TimelineCell {
  key: string;
  /** host time of day (seconds) of the tile start: what the player seeks to */
  tod: number;
  /** seconds the tile stands for */
  spanS: number;
  /** null = no sprite for this tile (chunk missing or not built yet) */
  sprite: { url: string; col: number; row: number; cols: number; rows: number } | null;
  flags: TimelineFlags | null;
  hour: number;
  chunkIndex: number;
  /** width / height of the tile: 16/9 for a landscape video, 9/16 for a phone (the sprite's own tile shape) */
  aspect: number;
}

const SPRITE_GEOMETRY = { 30: { cols: 5, rows: 4, count: 20 }, 6: { cols: 10, rows: 10, count: 100 } } as const;
const KEEP_S = 26 * 3600;

interface TracksFile {
  tiles?: Record<string, TimelineFlags[]>;
  /** the sprite's tile size in px; absent in chunks built before portrait tiles existed (those are 16:9) */
  tile?: { w: number; h: number };
}

export const LANDSCAPE = 16 / 9;

const key = (hour: number, idx: number) => `${hour}_${idx}`;

/**
 * The Timeline grid data for one device: the archive chunk list, and per chunk the tracks file (tile flags).
 * Sprites are plain images, loaded by the browser when a cell shows them. A tile is the frame AT its time.
 */
export const useTimeline = (host: any, deviceId: string | undefined) => {
  // The sprites are plain <img> / CSS images, which cannot mint the host-session cookie (600 s TTL) the proxy gate
  // wants; keep it fresh for as long as the page is open, or a page left open turns into hatched tiles.
  const sessionUrl = useMemo(() => {
    try {
      return host && deviceId ? buildArchiveManifestUrl(host, deviceId) : null;
    } catch {
      return null;
    }
  }, [host, deviceId]);
  useHostSession(sessionUrl, true);

  const [chunks, setChunks] = useState<TimelineChunk[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tracks, setTracks] = useState<Record<string, TracksFile | null>>({});
  const requested = useRef<Set<string>>(new Set());
  const chunksRef = useRef<TimelineChunk[]>([]);
  chunksRef.current = chunks;
  // The 24 h ring reuses hour folders, so every file URL carries its chunk's end time: a cache (browser, proxy) can keep it forever.
  const version = useCallback(
    (hour: number, idx: number) => Math.floor(chunksRef.current.find((c) => c.hour === hour && c.chunkIndex === idx)?.endEpoch ?? 0),
    [],
  );
  // null = not known yet; false = the host's vpt-timeline service has built nothing for this device
  const [built, setBuilt] = useState<boolean | null>(null);
  // The host's answer for this device, asked once: the probe below re-runs whenever `chunks`
  // changes (and `load` is rebuilt whenever the host object is a new instance), and used to repeat the status call each time (BUG-0778 review).
  const statusRef = useRef<{ key: string; answer: ReturnType<typeof hostTimelineStatus> } | null>(null);

  const load = useCallback(async () => {
    if (!host || !deviceId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetchHostMedia(`${buildArchiveManifestUrl(host, deviceId)}?_t=${Date.now()}`, { cache: 'no-store' });
      if (!res.ok) {
        setChunks([]);
        setError(res.status === 404 ? 'no_archive' : 'load_failed');
        return;
      }
      const data = await res.json();
      const now = Date.now() / 1000;
      const newest = new Map<string, TimelineChunk>();
      for (const c of data.chunks || []) {
        if (typeof c.created !== 'number' || now - c.created > KEEP_S) continue;
        const item: TimelineChunk = {
          hour: c.hour,
          chunkIndex: c.chunk_index,
          endEpoch: c.created,
          todStart: c.hour * 3600 + c.chunk_index * 600,
        };
        const k = key(item.hour, item.chunkIndex);
        if (!newest.has(k) || newest.get(k)!.endEpoch < item.endEpoch) newest.set(k, item);
      }
      setChunks([...newest.values()].sort((a, b) => a.endEpoch - b.endEpoch));
    } catch {
      setChunks([]);
      setError('load_failed');
    } finally {
      setLoading(false);
    }
  }, [host, deviceId]);

  useEffect(() => {
    setTracks({});
    requested.current = new Set();
    setBuilt(null);
    void load();
  }, [load]);

  /** The user asked for a fresh look: ask the host about its service again too. */
  const reload = useCallback(() => {
    statusRef.current = null;
    return load();
  }, [load]);

  /** Fetch the tracks file of the given chunks once (a missing file is remembered as null). */
  const ensureTracks = useCallback(
    (wanted: { hour: number; chunkIndex: number }[]) => {
      if (!host || !deviceId) return;
      wanted.forEach(({ hour, chunkIndex }) => {
        const k = key(hour, chunkIndex);
        if (requested.current.has(k)) return;
        requested.current.add(k);
        void (async () => {
          try {
            const res = await fetchHostMedia(`${buildTimelineFileUrl(host, deviceId, hour, `timeline_${chunkIndex}_tracks.json`)}?v=${version(hour, chunkIndex)}`);
            if (res.ok) {
              const json = (await res.json()) as TracksFile;
              setTracks((prev) => ({ ...prev, [k]: json }));
            }
          } catch {
            /* flags are optional */
          }
        })();
      });
    },
    [host, deviceId, version],
  );

  // Is the service building anything for this device? Probe a few finished chunks (not the newest, still growing).
  useEffect(() => {
    if (!host || !deviceId || !chunks.length) return;
    let cancelled = false;
    void (async () => {
      // The host knows whether its Timeline service is on for this device: one call
      // instead of probing files that cannot exist for a device the service was never
      // enabled for (BUG-0778).
      const statusKey = `${host.host_name}|${deviceId}`;
      if (statusRef.current?.key !== statusKey) {
        statusRef.current = { key: statusKey, answer: hostTimelineStatus(host, deviceId) };
      }
      const status = await statusRef.current.answer;
      if (cancelled) return;
      if (status && !status.enabled) {
        setBuilt(false);
        return;
      }
      const probe = chunks.slice(-4, -1).length ? chunks.slice(-4, -1) : chunks.slice(-1);
      for (const c of probe) {
        try {
          const res = await fetchHostMedia(`${buildTimelineFileUrl(host, deviceId, c.hour, `timeline_${c.chunkIndex}_30s.json`)}?v=${Math.floor(c.endEpoch)}`);
          if (res.ok) {
            if (!cancelled) setBuilt(true);
            return;
          }
        } catch {
          /* try the next one */
        }
      }
      if (!cancelled) setBuilt(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [host, deviceId, chunks]);

  const hours = useMemo(() => {
    const seen: number[] = [];
    chunks.forEach((c) => {
      if (!seen.includes(c.hour)) seen.push(c.hour);
    });
    return seen;
  }, [chunks]);

  const has = useCallback((hour: number, idx: number) => chunks.some((c) => c.hour === hour && c.chunkIndex === idx), [chunks]);
  // The device's tile shape, from the first tracks file that says: it shapes the hatched "not built" tiles and chunks whose tracks are not loaded yet.
  const deviceAspect = useMemo(() => {
    for (const t of Object.values(tracks)) if (t?.tile?.w && t.tile.h) return t.tile.w / t.tile.h;
    return LANDSCAPE;
  }, [tracks]);
  const cell = useCallback(
    (hour: number, chunkIndex: number, step: 30 | 6, tile: number, spanS: number): TimelineCell => {
      const trk = tracks[key(hour, chunkIndex)];
      const aspect = trk ? (trk.tile?.w && trk.tile.h ? trk.tile.w / trk.tile.h : LANDSCAPE) : deviceAspect;
      const g = SPRITE_GEOMETRY[step];
      const built = host && deviceId && has(hour, chunkIndex);
      const flags = tracks[key(hour, chunkIndex)]?.tiles?.[String(step)]?.[tile] ?? null;
      return {
        key: `${hour}_${chunkIndex}_${step}_${tile}`,
        tod: hour * 3600 + chunkIndex * 600 + tile * step,
        spanS,
        sprite: built
          ? {
              url: `${buildTimelineFileUrl(host, deviceId as string, hour, `timeline_${chunkIndex}_${step}s.jpg`)}?v=${version(hour, chunkIndex)}`,
              col: tile % g.cols,
              row: Math.floor(tile / g.cols),
              cols: g.cols,
              rows: g.rows,
            }
          : null,
        flags,
        hour,
        chunkIndex,
        aspect,
      };
    },
    [host, deviceId, has, version, tracks, deviceAspect],
  );

  /** Share of a 15-min span (from `sec` into the hour) in each state, from the 30 s tile flags; null when none loaded. */
  const quarterFlags = useCallback(
    (hour: number, sec: number): TimelineFlags | null => {
      const sum: TimelineFlags = { ad: 0, freeze: 0, blackscreen: 0 };
      let seen = 0;
      for (let t = sec; t < sec + 900; t += 30) {
        const f = tracks[key(hour, Math.floor(t / 600))]?.tiles?.['30']?.[(t % 600) / 30];
        if (!f) continue;
        seen += 1;
        sum.ad += f.ad;
        sum.freeze += f.freeze;
        sum.blackscreen += f.blackscreen;
      }
      if (!seen) return null;
      return { ad: sum.ad / 30, freeze: sum.freeze / 30, blackscreen: sum.blackscreen / 30 };
    },
    [tracks],
  );

  /** Day: one tile per 15 min of every hour that has chunks, oldest first (the 30 s sprite tile at the start). */
  const dayCells = useCallback((): TimelineCell[] => {
    const out: TimelineCell[] = [];
    hours.forEach((h) => {
      for (let q = 0; q < 4; q++) {
        const sec = q * 900;
        out.push({ ...cell(h, Math.floor(sec / 600), 30, (sec % 600) / 30, 900), flags: quarterFlags(h, sec) });
      }
    });
    return out;
  }, [hours, cell, quarterFlags]);

  /** Hour: 120 tiles of 30 s. */
  const hourCells = useCallback(
    (hour: number): TimelineCell[] => Array.from({ length: 120 }, (_, i) => cell(hour, Math.floor(i / 20), 30, i % 20, 30)),
    [cell],
  );

  /** 10 min: 100 tiles of 6 s. */
  const tenCells = useCallback(
    (hour: number, chunkIndex: number): TimelineCell[] => Array.from({ length: 100 }, (_, i) => cell(hour, chunkIndex, 6, i, 6)),
    [cell],
  );

  /** Every 10-min slot from the oldest to the newest chunk, in time order (the ring wraps at 144). */
  const slots = useMemo((): TimelineSlot[] => {
    if (!chunks.length) return [];
    const first = chunks[0];
    const last = chunks[chunks.length - 1];
    const lastId = last.hour * 6 + last.chunkIndex;
    const out: TimelineSlot[] = [];
    let id = first.hour * 6 + first.chunkIndex;
    for (let n = 0; n < 144; n++) {
      const hour = Math.floor(id / 6);
      const chunkIndex = id % 6;
      const tiles = tracks[key(hour, chunkIndex)]?.tiles?.['30'];
      let flag: TimelineSlot['flag'] = null;
      if (tiles?.length) {
        const mean = (k: keyof TimelineFlags) => tiles.reduce((a, f) => a + f[k], 0) / tiles.length;
        flag = mean('freeze') > 0.4 ? 'freeze' : mean('blackscreen') > 0.4 ? 'blackscreen' : mean('ad') > 0.4 ? 'ad' : 'ok';
      }
      out.push({ hour, chunkIndex, has: chunks.some((c) => c.hour === hour && c.chunkIndex === chunkIndex), flag });
      if (id === lastId) break;
      id = (id + 1) % 144;
    }
    return out;
  }, [chunks, tracks]);

  return { chunks, slots, hours, built, loading, error, reload, ensureTracks, dayCells, hourCells, tenCells, has };
};

export type UseTimeline = ReturnType<typeof useTimeline>;
