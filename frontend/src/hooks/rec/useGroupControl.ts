import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { releaseAll, sendToGroup, takeControlAll } from '../../components/rec/group/groupControl.actions';
import { GROUP_LOG_SIZE } from '../../constants/groupControl';
import type {
  GroupCommandResponse,
  GroupLogEntry,
  GroupMember,
  GroupSelection,
  RemoteCommandPayload,
} from '../../types/pages/groupControl.types';
import { chooseDeviceProfile, sharedKeyIntersection } from '../../utils/remoteProfileUtils';
import { useHostControl } from '../useHostManager';
import { useUserSession } from '../useUserSession';

/**
 * Group tile state (TASK-76, TASK-80): takes control of every candidate, sends
 * each remote command to the included members through
 * `/server/remote/executeCommandGroup` (one model, one displayed profile), and
 * keeps a per-member ack. TASK-80 adds:
 *  - each `GroupMember.chosenProfile` — the per-target transport the backend
 *    will drive (IR on one device, BLE on the other, both visible as chips).
 *  - the `sharedKeys` set — the keys present on every member's transport; the
 *    remote panel disables the buttons outside this set.
 *  - the sink now posts `targets[].remote_profile` so each member's controller
 *    receives the key through the right transport.
 */
export const useGroupControl = ({ candidates, remoteProfile }: GroupSelection) => {
  const { takeControl, releaseControl } = useHostControl();
  const { sessionId } = useUserSession();
  const [members, setMembers] = useState<GroupMember[]>([]);
  const [isTaking, setIsTaking] = useState(true);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [log, setLog] = useState<GroupLogEntry[]>([]);

  // Sends and the unmount release read the latest members without re-creating the sink.
  const membersRef = useRef<GroupMember[]>([]);
  const focusRef = useRef<string | null>(null);
  const releasedRef = useRef(false);
  membersRef.current = members;
  focusRef.current = focusKey;

  const modelOf = (m: GroupMember) => m.device.device_model || 'unknown';

  const startedRef = useRef(false);
  const mountedRef = useRef(false);
  // A new releaseControl identity must not run the close cleanup, so it is read through a ref.
  const releaseControlRef = useRef(releaseControl);
  releaseControlRef.current = releaseControl;

  // Mount flag + release on close. Refs survive React StrictMode's remount, so the
  // take below runs once and a tile closed mid-take still releases what it got.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (!releasedRef.current) releaseAll(membersRef.current, releaseControlRef.current);
    };
  }, []);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    takeControlAll(candidates, takeControl).then((taken) => {
      if (!mountedRef.current) {
        releaseAll(taken, releaseControlRef.current);
        return;
      }
      // Resolve each member's chosen transport AFTER take-control so the device
      // list (and its `key_capabilities`) is final.
      const withChosen: GroupMember[] = taken.map((m) => {
        // First pass: try the displayed profile as-is (operator's first pick).
        const chosen = chooseDeviceProfile(
          m.device,
          remoteProfile,
          sharedKeyIntersection(m.device, [remoteProfile]),
        );
        return { ...m, chosenProfile: chosen ?? m.device.remote_profiles?.[0] ?? remoteProfile };
      });
      setMembers(withChosen);
      setIsTaking(false);
    });
    // Taken once per opened tile; the candidate list is fixed while it is open.
  }, [remoteProfile]);

  /**
   * The keys present on every controlled member's `chosenProfile`. Computed
   * once per `members` change. Drives the `disabledKeys` prop on the remote
   * panel — anything outside this set is greyed and clicks are skipped.
   */
  const sharedKeys = useMemo<string[]>(() => {
    const controlled = members.filter((m) => m.controlled && m.chosenProfile);
    if (controlled.length === 0) return [];
    return sharedKeyIntersection(controlled[0].device, controlled.map((m) => m.chosenProfile));
  }, [members]);

  const patch = useCallback((update: (m: GroupMember) => GroupMember) => {
    setMembers((prev) => prev.map(update));
  }, []);

  const setIncluded = useCallback(
    (key: string, included: boolean) => patch((m) => (m.key === key ? { ...m, included } : m)),
    [patch],
  );

  /**
   * Every member's `included` flag, keyed by model. Drives the per-model
   * badges in the modal header — count is the number of included members
   * of each model.
   */
  const includedByModel = useMemo(() => {
    const map = new Map<string, { included: GroupMember[]; total: GroupMember[] }>();
    for (const m of members) {
      const model = modelOf(m);
      const bucket = map.get(model) ?? { included: [], total: [] };
      bucket.total.push(m);
      if (m.included) bucket.included.push(m);
      map.set(model, bucket);
    }
    return map;
  }, [members]);

  /**
   * Per-model backward-compat with the badge row: the count we show on the
   * chip. Counts only controlled & non-erroring members — an excluded
   * member with an error chip would still drive the count.
   */
  const modelCounts = useMemo(() => {
    const out = new Map<string, { included: number; total: number }>();
    for (const [model, bucket] of includedByModel.entries()) {
      const controlled = bucket.total.filter((m) => m.controlled);
      out.set(model, {
        included: bucket.included.length,
        total: controlled.length,
      });
    }
    return out;
  }, [includedByModel]);

  /**
   * Toggle every member of `model` between included/excluded. If every
   * member of the model is already included, exclude them all; otherwise
   * include them all. The badge is disabled when at least one member of
   * the model has `chosenProfile !== remoteProfile` (a "non-compatible
   * target" — the backend fell back to a different transport) and is
   * surfaced by the caller via `isModelCompatible`.
   */
  const toggleIncludedByModel = useCallback(
    (model: string) => {
      const bucket = includedByModel.get(model);
      if (!bucket) return;
      const allIncluded = bucket.total.length > 0 && bucket.included.length === bucket.total.length;
      const next = !allIncluded;
      patch((m) => (modelOf(m) === model ? { ...m, included: next } : m));
    },
    [includedByModel, patch],
  );

  /**
   * True when every member of `model` is reachable through the displayed
   * remote. A member with `chosenProfile !== remoteProfile` (the backend
   * had to fall back because the operator's remote isn't on it) makes
   * the badge disabled so the operator knows the toggle is unsafe for
   * that model.
   */
  const isModelCompatible = useCallback(
    (model: string) => {
      const bucket = includedByModel.get(model);
      if (!bucket) return true;
      return bucket.total.every((m) => m.chosenProfile === remoteProfile);
    },
    [includedByModel, remoteProfile],
  );

  const toggleFocus = useCallback((key: string) => setFocusKey((prev) => (prev === key ? null : key)), []);

  /** Members the next command goes to: an excluded member in focus is driven alone. */
  const targetsOf = (list: GroupMember[], focus: string | null): GroupMember[] => {
    const focused = list.find((m) => m.key === focus && m.controlled);
    if (focused && !focused.included) return [focused];
    return list.filter((m) => m.controlled && m.included);
  };

  const sink = useCallback(
    async (payload: RemoteCommandPayload) => {
      const targets = targetsOf(membersRef.current, focusRef.current);
      if (targets.length === 0) throw new Error('No device included in the group');
      const targetKeys = new Set(targets.map((m) => m.key));
      // Targets keep their last result until this send answers (no flash).
      patch((m) => (m.controlled && !targetKeys.has(m.key) ? { ...m, ack: 'skipped', ackError: null } : m));

      let response: GroupCommandResponse;
      try {
        response = await sendToGroup(targets, payload, sessionId);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        patch((m) => (targetKeys.has(m.key) ? { ...m, ack: 'error', ackError: message } : m));
        throw err;
      }
      const deviceRef = (host: string, device: string) => `${host}/${device}`;
      const byDevice = new Map((response.results ?? []).map((r) => [deviceRef(r.host_name, r.device_id), r]));
      const outcome = new Map(
        targets.map((m) => {
          const r = byDevice.get(deviceRef(m.host.host_name, m.device.device_id));
          return [m.key, r?.success ? null : r?.error || 'No answer for this device'];
        }),
      );
      patch((m) =>
        outcome.has(m.key)
          ? { ...m, ack: outcome.get(m.key) ? 'error' : 'ok', ackError: outcome.get(m.key) ?? null }
          : m,
      );
      const ok = [...outcome.values()].filter((e) => e === null).length;
      setLog((prev) =>
        [
          { at: Date.now(), command: payload.command, sent: targets.length, ok, skewMs: response.skew_ms ?? 0 },
          ...prev,
        ].slice(0, GROUP_LOG_SIZE),
      );

      // The remote reads the first device's answer like a single-device send.
      const first = (response.results ?? []).find((r) => r.success);
      if (!first) throw new Error(outcome.get(targets[0].key) ?? 'Command failed');
      return first.response;
    },
    [patch, sessionId],
  );

  const release = useCallback(async () => {
    releasedRef.current = true;
    await releaseAll(membersRef.current, releaseControlRef.current);
  }, []);

  const controlled = members.filter((m) => m.controlled);
  const primary = controlled[0] ?? null;

  return {
    members,
    controlled,
    primary,
    isTaking,
    focusKey,
    toggleFocus,
    setIncluded,
    toggleIncludedByModel,
    includedByModel,
    modelCounts,
    isModelCompatible,
    targets: targetsOf(members, focusKey),
    sharedKeys,
    sink,
    log,
    release,
  };
};
