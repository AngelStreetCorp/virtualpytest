import { useEffect, useRef, useState } from 'react';

import { api } from '../utils/apiClient';
import {
  buildArchiveManifestUrl,
  buildServerUrlWithParams,
  buildTimelineFileUrl,
  fetchHostMedia,
} from '../utils/buildUrlUtils';

/** The newest chunks looked at per device: the service builds newest first, so a built device has one of these. */
const NEWEST = 4;
/** Devices checked at once (each check is a manifest and up to NEWEST small files). */
const PARALLEL = 4;
const KEEP_S = 26 * 3600;

export interface TimelineCandidate {
  host: any;
  device: { device_id: string };
}

export const supportKey = (hostName: string, deviceId: string): string => `${hostName}|${deviceId}`;

/** What the host says about its Timeline service for one device. */
export interface TimelineServiceStatus {
  /** the service is opted in for this device */
  enabled: boolean;
  /** archive chunks the device has */
  chunks: number;
}

/**
 * The host's own answer about the Timeline service for one device: is it enabled for that
 * device at all, and how many archive chunks it knows.
 *
 * BUG-0778: the page used to answer this by probing up to four sprite files per device
 * with HEAD. The service is opted in per device, so for every device it was never enabled
 * for all four probes 404ed — 14 to 17 failing requests on every load of the page, and the
 * same again on every navigation. The host knows the answer in one call.
 *
 * null = the host did not answer (an older host without the route, or a network error):
 * the caller then falls back to the file probe.
 */
export async function hostTimelineStatus(host: any, deviceId: string): Promise<TimelineServiceStatus | null> {
  if (!host?.host_name || !deviceId) return null;
  try {
    const url = buildServerUrlWithParams('/server/timeline/status', {
      host_name: host.host_name,
      device_id: deviceId,
    });
    const body = await api.get<{ enabled?: boolean; chunks?: number }>(url);
    if (typeof body?.enabled !== 'boolean') return null;
    return { enabled: body.enabled, chunks: Number(body.chunks) || 0 };
  } catch (err) {
    // Not silent: an older host without the route answers 404 and lands here, and so does a
    // network error. The caller falls back to the file probe, but the reason is on record.
    console.warn('[timeline] host status unavailable, falling back to the file probe:', err);
    return null;
  }
}

/** True when the host has built a Timeline for this device: its archive lists chunks and one of the newest has a sprite map. */
export async function deviceHasTimeline(host: any, deviceId: string): Promise<boolean> {
  try {
    // The service is off for this device: no sprite will ever exist for it, so do not
    // look for one (BUG-0778).
    const status = await hostTimelineStatus(host, deviceId);
    if (status && !status.enabled) return false;
    const res = await fetchHostMedia(`${buildArchiveManifestUrl(host, deviceId)}?_t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) return false;
    const now = Date.now() / 1000;
    const chunks = ((await res.json()).chunks || []) as Array<{ hour: number; chunk_index: number; created: number }>;
    const newest = chunks
      .filter((c) => typeof c.created === 'number' && now - c.created <= KEEP_S)
      .sort((a, b) => b.created - a.created)
      .slice(0, NEWEST);
    for (const c of newest) {
      const r = await fetchHostMedia(buildTimelineFileUrl(host, deviceId, c.hour, `timeline_${c.chunk_index}_6s.json`), { method: 'HEAD' });
      if (r.ok) return true;
    }
    return false;
  } catch {
    return false;
  }
}

/**
 * Which of the candidate devices have a Timeline (the page lists only those). The check runs once per set of candidates, a few at a
 * time; `checking` is true until every device has been looked at.
 */
export function useTimelineSupport(candidates: TimelineCandidate[]): { supported: Set<string>; checking: boolean } {
  const [supported, setSupported] = useState<Set<string>>(new Set());
  const [checking, setChecking] = useState(false);
  const signature = candidates.map((c) => supportKey(c.host.host_name, c.device.device_id)).join(',');
  const run = useRef(0);

  useEffect(() => {
    const mine = ++run.current;
    if (!candidates.length) {
      setSupported(new Set());
      setChecking(false);
      return undefined;
    }
    setChecking(true);
    const queue = [...candidates];
    const found = new Set<string>();
    const worker = async () => {
      for (let next = queue.shift(); next && run.current === mine; next = queue.shift()) {
        if (await deviceHasTimeline(next.host, next.device.device_id)) {
          found.add(supportKey(next.host.host_name, next.device.device_id));
          if (run.current === mine) setSupported(new Set(found));
        }
      }
    };
    void Promise.all(Array.from({ length: Math.min(PARALLEL, queue.length) }, worker)).then(() => {
      if (run.current === mine) {
        setSupported(new Set(found));
        setChecking(false);
      }
    });
    return () => {
      run.current += 1;
    };
    // the signature stands for the candidate list: a new array with the same devices must not restart the checks
  }, [signature]);

  return { supported, checking };
}
