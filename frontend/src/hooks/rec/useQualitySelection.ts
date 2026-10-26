import { useCallback, useRef, useState } from 'react';

import type { Device, Host } from '../../types/common/Host_Types';
import { api } from '../../utils/apiClient';
import { buildHostServerUrl } from '../../utils/buildUrlUtils';

import { isDroneDevice } from './useDroneWifiStatus';
import type { QualityLevel } from './useRecQualitySwitch';

export interface QualityTarget {
  key: string;
  host: Host;
  device: Device;
}

export type QualityPhase = 'idle' | 'applying' | 'done';

/** The applying phase has no verification: after the last command is sent we wait this long, then report ok. */
export const QUALITY_APPLY_WAIT_MS = 10_000;

/** Single place that decides whether a device can run a quality. Drones and devices without an AV
 *  controller can't; no per-device HD+ limit is recorded anywhere yet, so every video device can. */
export const deviceSupportsQuality = (device: Device, _quality: QualityLevel): boolean =>
  !isDroneDevice(device) && Boolean(device.device_capabilities?.av);

/**
 * Device-page selection for bulk stream quality (TASK-97): pick the quality, pick the devices that
 * support it, apply. All requests go out in parallel and are not verified.
 */
export const useQualitySelection = () => {
  const [isQualityMode, setIsQualityMode] = useState(false);
  const [quality, setQualityState] = useState<QualityLevel>('hd');
  const [selected, setSelected] = useState<Map<string, QualityTarget>>(new Map());
  const [phase, setPhase] = useState<QualityPhase>('idle');
  const [failed, setFailed] = useState<QualityTarget[]>([]);
  const [okCount, setOkCount] = useState(0);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const previous = useRef<Map<string, { target: QualityTarget; quality: QualityLevel }>>(new Map());
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const reset = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    setPhase('idle');
    setFailed([]);
    setOkCount(0);
  }, []);

  const toggleQualityMode = useCallback(() => {
    setIsQualityMode((on) => !on);
    setSelected(new Map());
    reset();
  }, [reset]);

  const setQuality = useCallback((next: QualityLevel) => {
    setQualityState(next);
    setSelected((prev) => new Map([...prev].filter(([, t]) => deviceSupportsQuality(t.device, next))));
    reset();
  }, [reset]);

  const toggle = useCallback((target: QualityTarget) => {
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(target.key)) next.delete(target.key);
      else if (deviceSupportsQuality(target.device, quality)) next.set(target.key, target);
      return next;
    });
  }, [quality]);

  const selectAll = useCallback((pool: QualityTarget[]) => {
    setSelected(new Map(pool.filter((t) => deviceSupportsQuality(t.device, quality)).map((t) => [t.key, t])));
  }, [quality]);

  const clear = useCallback(() => setSelected(new Map()), []);

  const send = useCallback(async (targets: QualityTarget[], level: QualityLevel) => {
    if (timer.current) clearInterval(timer.current);
    setPhase('applying');
    setSecondsLeft(Math.round(QUALITY_APPLY_WAIT_MS / 1000));
    const results = await Promise.all(targets.map(async (t) => {
      try {
        await api.post(buildHostServerUrl(t.host, '/server/system/setStreamQuality'), {
          host_name: t.host.host_name,
          device_id: t.device.device_id,
          quality: level,
        });
        return { t, ok: true };
      } catch {
        return { t, ok: false };
      }
    }));
    setFailed(results.filter((r) => !r.ok).map((r) => r.t));
    setOkCount(results.filter((r) => r.ok).length);
    const end = Date.now() + QUALITY_APPLY_WAIT_MS;
    timer.current = setInterval(() => {
      const left = Math.ceil((end - Date.now()) / 1000);
      if (left <= 0) {
        if (timer.current) clearInterval(timer.current);
        setPhase('done');
      } else {
        setSecondsLeft(left);
      }
    }, 500);
  }, []);

  /** Remember each device's current quality first so Undo can put it back. */
  const apply = useCallback(async () => {
    const targets = [...selected.values()];
    const before = await Promise.all(targets.map(async (t) => {
      try {
        const res = await api.get<{ quality?: QualityLevel }>(buildHostServerUrl(t.host,
          `/server/system/getStreamQuality?host_name=${encodeURIComponent(t.host.host_name)}&device_id=${encodeURIComponent(t.device.device_id)}`));
        return { target: t, quality: res.quality ?? 'low' };
      } catch {
        return { target: t, quality: 'low' as QualityLevel };
      }
    }));
    previous.current = new Map(before.map((b) => [b.target.key, b]));
    await send(targets, quality);
  }, [selected, quality, send]);

  const retryFailed = useCallback(() => send(failed, quality), [failed, quality, send]);

  const undo = useCallback(async () => {
    const entries = [...previous.current.values()];
    // Group by previous quality so each device returns to its own value.
    const levels = new Set(entries.map((e) => e.quality));
    reset();
    await Promise.all([...levels].map((lvl) => send(entries.filter((e) => e.quality === lvl).map((e) => e.target), lvl)));
  }, [reset, send]);

  return {
    isQualityMode, quality, selected, phase, failed, okCount, secondsLeft,
    toggleQualityMode, setQuality, toggle, selectAll, clear, apply, retryFailed, undo, reset,
  };
};
