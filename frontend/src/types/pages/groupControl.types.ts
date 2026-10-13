import type { Device, Host } from '../common/Host_Types';

/** Result of the last command for one group member (TASK-76). */
export type GroupAck = 'ok' | 'error' | 'skipped';

/** One device picked for group control. */
export interface GroupCandidate {
  key: string;
  host: Host;
  device: Device;
}

/** A group member after take-control: controlled or listed as unavailable. */
export interface GroupMember extends GroupCandidate {
  controlled: boolean;
  included: boolean;
  error: string | null;
  ack: GroupAck | null;
  ackError: string | null;
  /**
   * TASK-80: the per-member transport profile (BLE on one device, IR on the
   * other). Picked by `chooseDeviceProfile` from the displayed skin and the
   * device's own `remote_profiles`. Drives the cell chip and the per-target
   * send to `/server/remote/executeCommandGroup`.
   */
  chosenProfile: string;
}

/**
 * `takeControlAll` returns each member with the take-control outcome and the
 * `included` default but without `chosenProfile` (the latter is resolved once
 * every member is known — the `useGroupControl` hook stamps it).
 */
export type GroupMemberAfterTake = Omit<GroupMember, 'chosenProfile'>;

/** Body of `/server/remote/executeCommand`, as built by `useControllerApi`. */
export type RemoteCommandPayload = Record<string, unknown> & {
  host_name: string;
  command: string;
};

/** Replaces the single-device send while a remote drives a group. */
export type RemoteCommandSink = (payload: RemoteCommandPayload) => Promise<unknown>;

export interface GroupLogEntry {
  at: number;
  command: string;
  sent: number;
  ok: number;
  skewMs: number;
}

/**
 * What the device page hands to the group tile (TASK-76, TASK-80).
 * `remoteProfile` is the *visual* skin the operator picked (the controller
 * that defines the group); each `GroupMember.chosenProfile` is the *actual*
 * transport that drives that device and may fall back to a different
 * transport when the operator's pick isn't on a member.
 *
 * The group is keyed by the remote profile only — same remote, any device
 * that supports it. The model breakdown is communicated via per-model
 * badges in the bar and the modal header.
 */
export interface GroupSelection {
  candidates: GroupCandidate[];
  remoteProfile: string;
}

/**
 * One device's line in a `/server/remote/executeCommandGroup` answer.
 * `remote_profile` is the per-target profile the host drove the device on
 * (TASK-80), echoed back so the frontend can label the per-cell chip and the
 * audit log can name the transport.
 */
export interface GroupCommandResult {
  host_name: string;
  device_id: string;
  success: boolean;
  skipped?: boolean;
  error: string | null;
  ms: number;
  remote_profile?: string | null;
  response?: unknown;
}

export interface GroupCommandResponse {
  success: boolean;
  error?: string;
  results?: GroupCommandResult[];
  skew_ms?: number;
  remote_profiles?: string[];
  mismatches?: { host_name: string; device_id: string; reason: string }[];
}
