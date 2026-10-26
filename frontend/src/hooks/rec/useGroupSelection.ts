import { useCallback, useMemo, useState } from 'react';

import { GROUP_MAX_SIZE, GROUP_MIN_SIZE } from '../../constants/groupControl';
import type { GroupCandidate, GroupSelection } from '../../types/pages/groupControl.types';
import { deviceRemoteProfiles, preferredRemoteProfile } from '../../utils/remoteProfileUtils';

const hasProfile = (c: GroupCandidate, profile: string) => deviceRemoteProfiles(c.device).includes(profile);

const modelOf = (c: GroupCandidate) => c.device.device_model || 'unknown';

// Stream-only models have no controller to drive, so they can never join a group.
const STREAM_ONLY_MODELS = new Set(['rtsp_video', 'local_video']);
const isGroupable = (c: GroupCandidate) =>
  !STREAM_ONLY_MODELS.has(c.device.device_model) && deviceRemoteProfiles(c.device).length > 0;

/**
 * Device-page selection for group control (TASK-76, TASK-80).
 *
 * The group is keyed by `remoteProfile` (the controller the operator picked).
 * Any device that owns that profile can join, regardless of model — STB,
 * Fire TV, Android TV … the operator filters the group via the per-model
 * badges in the bar / modal. The model is no longer a group-defining lock.
 *
 * The *displayed profile* is the visual skin the operator picked; each
 * member picks its own `chosenProfile` later via `chooseDeviceProfile`
 * (TASK-80). If the operator's pick doesn't fit every member, the per-model
 * badge for the misfit model is disabled in the modal so the user knows
 * the toggle is unsafe.
 */
export const useGroupSelection = (selectablePool: GroupCandidate[] = []) => {
  const [isGroupMode, setIsGroupMode] = useState(false);
  const [selected, setSelected] = useState<GroupCandidate[]>([]);
  const [remoteProfile, setRemoteProfileState] = useState<string | null>(null);

  const selectedKeys = useMemo(() => new Set(selected.map((c) => c.key)), [selected]);

  /**
   * Profiles every selected device can *physically* drive — the choices the
   * skin picker offers. Only profiles every selected device owns show up,
   * so switching the skin never strands a member. The per-member
   * `chosenProfile` is resolved later.
   */
  const profileChoices = useMemo(() => {
    if (selected.length === 0) return [];
    return deviceRemoteProfiles(selected[0].device).filter((p) => selected.every((c) => hasProfile(c, p)));
  }, [selected]);

  /**
   * Every device in the workspace, deduplicated and grouped by model. Drives
   * the per-model chip strip in the bar from the moment the operator enters
   * group mode — clicking a chip auto-picks the most common profile of that
   * model and adds the matching candidates, so the operator never has to
   * click a device tile first.
   */
  const poolByModel = useMemo(() => {
    const seen = new Set<string>();
    const map = new Map<string, GroupCandidate[]>();
    for (const c of selectablePool) {
      if (seen.has(c.key) || !isGroupable(c)) continue;
      seen.add(c.key);
      const m = modelOf(c);
      const list = map.get(m);
      if (list) list.push(c);
      else map.set(m, [c]);
    }
    return map;
  }, [selectablePool]);

  /**
   * Within a model, the profile that would be auto-picked on a click. The
   * "most common" profile is the one shared by the most candidates of that
   * model — that's what the group will lock to when the operator clicks the
   * chip. Ties break to the rank already used by `preferredRemoteProfile`
   * (direct > IR > BLE).
   */
  const autoPickProfileForModel = useCallback(
    (model: string): string | null => {
      const candidates = poolByModel.get(model) ?? [];
      if (candidates.length === 0) return null;
      const counts = new Map<string, number>();
      for (const c of candidates) {
        for (const p of deviceRemoteProfiles(c.device)) {
          counts.set(p, (counts.get(p) ?? 0) + 1);
        }
      }
      if (counts.size === 0) return null;
      // Sort by count desc, then by direct > IR > BLE rank.
      const sorted = Array.from(counts.entries()).sort((a, b) => {
        if (b[1] !== a[1]) return b[1] - a[1];
        const rank = (p: string) => (p.startsWith('ble:') ? 2 : p.startsWith('ir:') ? 1 : 0);
        return rank(a[0]) - rank(b[0]);
      });
      return sorted[0]?.[0] ?? null;
    },
    [poolByModel],
  );

  const selectable = useCallback(
    (candidate: GroupCandidate) => {
      if (selectedKeys.has(candidate.key)) return true;
      if (selected.length >= GROUP_MAX_SIZE) return false;
      // Group needs ≥2 devices of the same model — a single-device
      // model (apple_tv on a workspace with one apple_tv device, for
      // instance) can't lead a meaningful group, so refuse direct
      // card-level selection. The chip strip already filters these
      // out as a UI hint, but the card click path needs its own
      // gate so the operator cannot end up with a "group of one".
      // Devices already in the group are unaffected (the
      // selectedKeys branch above lets the operator deselect them).
      const sameModelPool = poolByModel.get(modelOf(candidate))?.length ?? 0;
      if (sameModelPool < 2) return false;
      if (!remoteProfile) return deviceRemoteProfiles(candidate.device).length > 0;
      // Group is the remote profile only — same remote, any device that owns it.
      return hasProfile(candidate, remoteProfile);
    },
    [poolByModel, remoteProfile, selected.length, selectedKeys],
  );

  const toggle = useCallback(
    (candidate: GroupCandidate) => {
      if (selectedKeys.has(candidate.key)) {
        const next = selected.filter((c) => c.key !== candidate.key);
        setSelected(next);
        if (next.length === 0) setRemoteProfileState(null);
        return;
      }
      if (!selectable(candidate)) return;
      if (selected.length === 0) {
        setRemoteProfileState(preferredRemoteProfile(deviceRemoteProfiles(candidate.device)));
      }
      setSelected([...selected, candidate]);
    },
    [selectable, selected, selectedKeys],
  );

  /** Switch the displayed skin; picks without it drop out of the selection. */
  const setRemoteProfile = useCallback((profile: string) => {
    setRemoteProfileState(profile);
    setSelected((prev) => prev.filter((c) => hasProfile(c, profile)));
  }, []);

  const clear = useCallback(() => {
    setSelected([]);
    setRemoteProfileState(null);
  }, []);

  /**
   * `selected` grouped by model — feeds the per-model badge row in the bar.
   * Each model's count is the number of group members of that model.
   */
  const selectedByModel = useMemo(() => {
    const map = new Map<string, GroupCandidate[]>();
    for (const c of selected) {
      const m = modelOf(c);
      const list = map.get(m);
      if (list) list.push(c);
      else map.set(m, [c]);
    }
    return map;
  }, [selected]);

  /**
   * Toggle every candidate of `model` in/out of the group. If no remote
   * profile is set yet, the click auto-picks the model's most common
   * profile (so the chip strip is usable the moment group mode opens).
   * The "all in" check is the candidates-of-model-that-own-the-profile,
   * not the bare pool — a STB with no BLE Arris profile shouldn't count
   * as "in the group" when the chip click already locked BLE Arris.
   *
   * Otherwise: if every in-group candidate of this model is in `selected`,
   * remove them all; else fill the group with every profile-matching
   * candidate, clamped to GROUP_MAX_SIZE.
   */
  const toggleByModel = useCallback(
    (model: string) => {
      const all = poolByModel.get(model) ?? [];
      if (all.length === 0) return;
      const profile = remoteProfile ?? autoPickProfileForModel(model);
      if (!profile) return;
      const candidates = all.filter((c) => hasProfile(c, profile));
      if (candidates.length === 0) return;
      const allIn = candidates.every((c) => selectedKeys.has(c.key));
      setRemoteProfileState(profile);
      if (allIn) {
        setSelected((prev) => {
          const next = prev.filter((c) => !(modelOf(c) === model && hasProfile(c, profile)));
          // When toggling a model off empties the group, drop the
          // controller too so the bar returns to the "no group" state
          // instead of a stale profile pointing at zero devices — same
          // reconciliation as `toggle` does on the last single-device
          // removal. The setter is batched with `setSelected` in
          // React 18 so the next render sees both updates.
          if (next.length === 0) {
            setRemoteProfileState(null);
          }
          return next;
        });
        return;
      }
      const slotsLeft = Math.max(0, GROUP_MAX_SIZE - selected.length);
      if (slotsLeft === 0) return;
      const additions = candidates.filter((c) => !selectedKeys.has(c.key)).slice(0, slotsLeft);
      if (additions.length === 0) return;
      setSelected((prev) => [...prev, ...additions]);
    },
    [autoPickProfileForModel, poolByModel, remoteProfile, selected.length, selectedKeys],
  );

  /** Model "Select all" acts on: the current selection's model, else the first model badge (pool >= 2). */
  const selectAllModel = useMemo(() => {
    if (selected.length > 0) return modelOf(selected[0]);
    const models = Array.from(poolByModel.entries())
      .filter(([, list]) => list.length >= 2)
      .map(([m]) => m)
      .sort((a, b) => a.localeCompare(b));
    return models[0] ?? null;
  }, [poolByModel, selected]);

  const selectAllTotal = selectAllModel ? (poolByModel.get(selectAllModel)?.length ?? 0) : 0;

  const selectAll = useCallback(() => {
    if (!selectAllModel) return;
    const profile = remoteProfile ?? autoPickProfileForModel(selectAllModel);
    if (!profile) return;
    const candidates = (poolByModel.get(selectAllModel) ?? []).filter((c) => hasProfile(c, profile));
    if (candidates.every((c) => selectedKeys.has(c.key))) return;
    toggleByModel(selectAllModel);
  }, [autoPickProfileForModel, poolByModel, remoteProfile, selectAllModel, selectedKeys, toggleByModel]);

  const toggleGroupMode = useCallback(() => {
    setIsGroupMode((prev) => !prev);
    setSelected([]);
    setRemoteProfileState(null);
  }, []);

  const selection: GroupSelection | null =
    remoteProfile ? { candidates: selected, remoteProfile } : null;

  return {
    isGroupMode,
    toggleGroupMode,
    selected,
    selectedKeys,
    remoteProfile,
    profileChoices,
    selectedByModel,
    poolByModel,
    setRemoteProfile,
    isSelectable: selectable,
    toggle,
    toggleByModel,
    selectAll,
    selectAllTotal,
    clear,
    selection,
    canStart: selected.length >= GROUP_MIN_SIZE && !!remoteProfile,
  };
};
