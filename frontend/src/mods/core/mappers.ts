/**
 * /system `system_update` → mod event. One mapper per update type; null for a type no
 * mod event covers, a payload missing what the event needs, or another team's update.
 */
import { SYSTEM_TYPES } from './constants';
import type { ModEventEnvelope, RunEvent } from './types';

type Payload = Record<string, unknown>;

const num = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined);
const str = (v: unknown): string | undefined => (typeof v === 'string' && v ? v : undefined);
const obj = (v: unknown): Payload => (v && typeof v === 'object' ? (v as Payload) : {});
const stamp = (p: Payload): number => (num(p.timestamp) ? (num(p.timestamp) as number) * 1000 : Date.now());

const mapExecution = (p: Payload): RunEvent | null => {
  const id = str(p.execution_id);
  const status = str(p.status);
  if (!id || !status) return null;
  const result = obj(p.result);
  return {
    id,
    kind: str(p.execution_type) ?? 'run',
    status: status.toLowerCase(),
    progress: num(p.progress),
    message: str(p.message),
    step: str(result.step),
    stepNumber: num(result.step_number),
    totalSteps: num(result.total_steps),
    hostName: str(p.host_name),
    deviceId: str(p.device_id),
    error: str(p.error),
    timestamp: stamp(p),
  };
};

export const mapSystemUpdate = (event: unknown, teamId: string): ModEventEnvelope | null => {
  const p = obj(event);
  const teamOfEvent = str(p.team_id);
  if (teamOfEvent && teamOfEvent !== teamId) return null;

  const hostName = str(p.host_name);
  const deviceId = str(p.device_id);
  const timestamp = stamp(p);

  switch (p.type) {
    case SYSTEM_TYPES.execution: {
      const e = mapExecution(p);
      return e ? { name: 'run.update', e } : null;
    }
    case SYSTEM_TYPES.lock: {
      if (!hostName || !deviceId || typeof p.is_locked !== 'boolean') return null;
      const lock = obj(p.lock_info);
      return {
        name: 'device.lock',
        e: {
          hostName,
          deviceId,
          locked: p.is_locked,
          ownerName: p.is_locked ? str(lock.owner_user_name) : undefined,
          ownerType: p.is_locked ? str(lock.owner_type) : undefined,
          timestamp,
        },
      };
    }
    case SYSTEM_TYPES.hostRegistered:
    case SYSTEM_TYPES.hostUnregistered:
    case SYSTEM_TYPES.hostPing: {
      if (!hostName) return null;
      const status =
        p.type === SYSTEM_TYPES.hostRegistered ? 'online' : p.type === SYSTEM_TYPES.hostUnregistered ? 'offline' : 'alive';
      return { name: 'host.status', e: { hostName, status, timestamp } };
    }
    case SYSTEM_TYPES.controlReady:
    case SYSTEM_TYPES.controlFailed: {
      if (!hostName || !deviceId) return null;
      const ready = p.type === SYSTEM_TYPES.controlReady;
      return { name: 'device.control', e: { hostName, deviceId, ready, error: ready ? undefined : str(p.error), timestamp } };
    }
    case SYSTEM_TYPES.deployment:
    case SYSTEM_TYPES.deploymentExecution:
      return {
        name: 'deployment.change',
        e: {
          action: str(p.action),
          deploymentId: str(p.deployment_id),
          executionId: str(p.execution_id) ?? str(p.task_id),
          status: str(p.status),
          timestamp,
        },
      };
    case SYSTEM_TYPES.agentActivity: {
      const agentId = str(p.agent_id);
      if (!agentId) return null;
      const row = obj(p.row);
      return { name: 'agent.activity', e: { agentId, summary: str(row.summary), level: str(row.level), timestamp } };
    }
    case SYSTEM_TYPES.presence: {
      const users = (Array.isArray(p.users) ? p.users : [])
        .map((u) => obj(u))
        .filter((u) => str(u.user_id))
        .map((u) => ({ userId: str(u.user_id) as string, name: str(u.name) ?? '?' }));
      return {
        name: 'presence.update',
        e: { online: num(p.online) ?? users.length, users, sharedSessions: num(p.shared_sessions) ?? 0, timestamp },
      };
    }
    default:
      return null;
  }
};
