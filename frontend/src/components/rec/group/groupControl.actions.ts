import type { HostControlContextType } from '../../../contexts/HostControlContext';
import type {
  GroupCandidate,
  GroupCommandResponse,
  GroupMember,
  GroupMemberAfterTake,
  RemoteCommandPayload,
} from '../../../types/pages/groupControl.types';
import { api } from '../../../utils/apiClient';
import { buildServerUrl } from '../../../utils/buildUrlUtils';

/**
 * Takes control of every candidate in parallel; a failure leaves that member listed,
 * not controlled. Uses the browser session like single control: an explicit session
 * id would overwrite the server's cookie session.
 */
export const takeControlAll = async (
  candidates: GroupCandidate[],
  takeControl: HostControlContextType['takeControl'],
): Promise<GroupMemberAfterTake[]> => {
  const results = await Promise.allSettled(
    candidates.map((c) => takeControl(c.host, c.device.device_id)),
  );
  return candidates.map((c, i) => {
    const r = results[i];
    const ok = r.status === 'fulfilled' && r.value.success;
    const error = ok
      ? null
      : r.status === 'fulfilled'
        ? r.value.error || 'Failed to take control'
        : String(r.reason);
    return { ...c, controlled: ok, included: ok, error, ack: null, ackError: null };
  });
};

/** Releases every controlled member; errors are ignored so one dead host never blocks closing. */
export const releaseAll = async (
  members: GroupMemberAfterTake[] | GroupMember[],
  releaseControl: HostControlContextType['releaseControl'],
): Promise<void> => {
  await Promise.allSettled(
    members
      .filter((m) => m.controlled)
      .map((m) => releaseControl(m.host, m.device.device_id)),
  );
};

/**
 * Sends one remote command to every target through the server, which checks the
 * model + each target's remote profile, fans out in parallel and answers one
 * result per device. TASK-80: the per-member `chosenProfile` rides in
 * `targets[].remote_profile`; the top-level `remote_profile` is kept for
 * backward-compat / logging.
 */
export const sendToGroup = async (
  targets: GroupMember[],
  payload: RemoteCommandPayload,
  sessionId: string,
): Promise<GroupCommandResponse> => {
  const seen = new Set<string>();
  const remote_profile = targets
    .map((m) => m.chosenProfile)
    .find((p): p is string => !!p && !seen.has(p) && (seen.add(p), true)) ?? null;
  return api.post<GroupCommandResponse>(buildServerUrl('/server/remote/executeCommandGroup'), {
    targets: targets.map((m) => ({
      host_name: m.host.host_name,
      device_id: m.device.device_id,
      remote_profile: m.chosenProfile,
    })),
    remote_profile,
    command: payload.command,
    params: payload.params ?? {},
    session_id: sessionId,
  });
};

/** A phone's screen aspect (portrait width / height), read live from the device; null if it does not answer. */
export const fetchScreenAspect = async (member: GroupMember): Promise<number | null> => {
  try {
    const r = await api.post<{ success?: boolean; width?: number; height?: number }>(
      buildServerUrl('/server/remote/getOrientation'),
      { host_name: member.host.host_name, device_id: member.device.device_id },
    );
    const w = Number(r?.width);
    const h = Number(r?.height);
    if (!r?.success || !(w > 0) || !(h > 0)) return null;
    return Math.min(w, h) / Math.max(w, h);
  } catch {
    return null;
  }
};

/**
 * Where a click lands on a phone's screen, as 0..1 of that screen, or null outside it.
 * The tile paints the stream with objectFit cover, and the screen sits centred in the
 * frame at its own aspect (some phones stream a 16:9 frame with the screen pillarboxed).
 */
export const screenPointOf = (
  clientX: number,
  clientY: number,
  container: HTMLElement,
  screenAspect: number | null,
): { x_pct: number; y_pct: number } | null => {
  const media = Array.from(container.querySelectorAll<HTMLVideoElement | HTMLImageElement>('video, img')).find(
    (el) => {
      const r = el.getBoundingClientRect();
      const natural = el instanceof HTMLVideoElement ? el.videoWidth : el.naturalWidth;
      return r.width > 0 && r.height > 0 && natural > 0;
    },
  );
  if (!media) return null;
  const vw = media instanceof HTMLVideoElement ? media.videoWidth : media.naturalWidth;
  const vh = media instanceof HTMLVideoElement ? media.videoHeight : media.naturalHeight;
  const rect = media.getBoundingClientRect();
  const scale = Math.max(rect.width / vw, rect.height / vh);
  const fx = (clientX - (rect.left + (rect.width - vw * scale) / 2)) / scale;
  const fy = (clientY - (rect.top + (rect.height - vh * scale) / 2)) / scale;

  const frameAspect = vw / vh;
  const aspect = screenAspect ?? (frameAspect < 1 ? frameAspect : 9 / 16);
  const sw = aspect < frameAspect ? vh * aspect : vw;
  const sh = aspect < frameAspect ? vh : vw / aspect;
  const x = (fx - (vw - sw) / 2) / sw;
  const y = (fy - (vh - sh) / 2) / sh;
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  return { x_pct: Math.round(x * 10000) / 10000, y_pct: Math.round(y * 10000) / 10000 };
};
