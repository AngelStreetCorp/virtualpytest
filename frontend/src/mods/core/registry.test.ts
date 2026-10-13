import { describe, expect, it, vi } from 'vitest';

import { enabledMods, mergeChoices, setModChoice } from './actions';
import { mapSystemUpdate } from './mappers';
import { createModRegistry } from './registry';
import type { ModApi, ModDefinition, RunEvent } from './types';

const api: ModApi = {
  ui: { toast: vi.fn(), openPane: vi.fn(), closePane: vi.fn(), confirm: vi.fn(async () => true) },
  clock: { now: () => 0 },
};
const run: RunEvent = { id: 'a', kind: 'script', status: 'running', timestamp: 0 };

describe('mod registry', () => {
  it('runs event hooks in order and lets a hook rewrite or stop the chain', () => {
    const seen: string[] = [];
    const mods: ModDefinition[] = [
      { id: 'one', name: '', description: '', defaultEnabled: true, register: (on) => on('run.update', (_$, e, next) => next({ ...e, status: 'x' })) },
      { id: 'two', name: '', description: '', defaultEnabled: true, register: (on) => on('run.update', (_$, e) => seen.push(e.status)) },
      { id: 'three', name: '', description: '', defaultEnabled: true, register: (on) => on('run.update', (_$, e) => seen.push(`never ${e.id}`)) },
    ];
    createModRegistry(mods).emit(api, 'run.update', run);
    expect(seen).toEqual(['x']);
  });

  it('skips a throwing hook and falls back to the default draw', () => {
    const mods: ModDefinition[] = [
      { id: 'bad', name: '', description: '', defaultEnabled: true, register: (on) => on('app.band', () => { throw new Error('x'); }) },
    ];
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    expect(createModRegistry(mods).render(api, 'app.band', {}, 'default')).toBe('default');
    warn.mockRestore();
  });

  it('lets a slot hook draw or pass to next()', () => {
    const mods: ModDefinition[] = [
      { id: 'pane', name: '', description: '', defaultEnabled: true, register: (on) => on('app.pane', (_$, p, next) => (p.paneId === 'mine' ? 'mine' : next())) },
    ];
    const registry = createModRegistry(mods);
    expect(registry.render(api, 'app.pane', { paneId: 'mine' }, null)).toBe('mine');
    expect(registry.render(api, 'app.pane', { paneId: 'other' }, 'default')).toBe('default');
  });
});

describe('mapSystemUpdate', () => {
  it('maps an execution_update to run.update and filters other teams', () => {
    const env = mapSystemUpdate(
      {
        type: 'execution_update',
        execution_type: 'script',
        execution_id: 't1',
        status: 'running',
        team_id: 'team',
        result: { step: 'zap', step_number: 1, total_steps: 3 },
        timestamp: 2,
      },
      'team',
    );
    expect(env?.name).toBe('run.update');
    expect(env?.e).toMatchObject({ id: 't1', kind: 'script', step: 'zap', stepNumber: 1, totalSteps: 3, timestamp: 2000 });
    expect(mapSystemUpdate({ type: 'execution_update', execution_id: 't1', status: 'running', team_id: 'other' }, 'team')).toBeNull();
  });

  it('maps locks, hosts, control, deployments and agent activity', () => {
    expect(
      mapSystemUpdate(
        { type: 'lock_changed', host_name: 'h', device_id: 'd', is_locked: true, lock_info: { owner_user_name: 'Paul', owner_type: 'manual_control' } },
        'team',
      ),
    ).toMatchObject({ name: 'device.lock', e: { hostName: 'h', deviceId: 'd', locked: true, ownerName: 'Paul', ownerType: 'manual_control' } });
    expect(mapSystemUpdate({ type: 'host_unregistered', host_name: 'h' }, 'team')).toMatchObject({ name: 'host.status', e: { status: 'offline' } });
    expect(mapSystemUpdate({ type: 'host_ping', host_name: 'h' }, 'team')).toMatchObject({ e: { status: 'alive' } });
    expect(mapSystemUpdate({ type: 'control_failed', host_name: 'h', device_id: 'd', error: 'busy' }, 'team')).toMatchObject({
      name: 'device.control',
      e: { ready: false, error: 'busy' },
    });
    expect(mapSystemUpdate({ type: 'deployment_execution_changed', task_id: 'x', status: 'completed' }, 'team')).toMatchObject({
      name: 'deployment.change',
      e: { executionId: 'x', status: 'completed' },
    });
    expect(mapSystemUpdate({ type: 'agent_activity', agent_id: 'assistant', team_id: 'team', row: { summary: 'Chat turn' } }, 'team')).toMatchObject({
      name: 'agent.activity',
      e: { agentId: 'assistant', summary: 'Chat turn' },
    });
  });

  it('maps presence, counting people and shared sessions apart', () => {
    expect(
      mapSystemUpdate(
        { type: 'presence_changed', team_id: 'team', online: 2, shared_sessions: 1, users: [{ user_id: 'u1', name: 'Ann' }, { user_id: 'u2', name: 'Bo' }] },
        'team',
      ),
    ).toMatchObject({ name: 'presence.update', e: { online: 2, sharedSessions: 1, users: [{ userId: 'u1', name: 'Ann' }, { userId: 'u2', name: 'Bo' }] } });
    expect(mapSystemUpdate({ type: 'presence_changed', team_id: 'other', online: 5, users: [] }, 'team')).toBeNull();
  });

  it('ignores unknown types and incomplete payloads', () => {
    expect(mapSystemUpdate({ type: 'something_else' }, 'team')).toBeNull();
    expect(mapSystemUpdate({ type: 'lock_changed', host_name: 'h' }, 'team')).toBeNull();
    expect(mapSystemUpdate(null, 'team')).toBeNull();
  });
});

describe('gates', () => {
  const cmd = { hostName: 'h', deviceId: 'd', command: 'reboot', source: 'power' as const };
  const gateMod = (id: string, hook: Parameters<Parameters<ModDefinition['register']>[0]>[1]): ModDefinition => ({
    id,
    name: id,
    description: '',
    defaultEnabled: true,
    register: (on) => on('device.command', hook as never),
  });

  it('allows when no mod refuses', async () => {
    expect(await createModRegistry([]).gate(api, 'device.command', cmd)).toEqual({ allow: true });
    const pass = gateMod('pass', ((_$: ModApi, e: typeof cmd, next: (e: typeof cmd) => Promise<unknown>) => next(e)) as never);
    expect(await createModRegistry([pass]).gate(api, 'device.command', cmd)).toEqual({ allow: true });
  });

  it('stops at the first refusal', async () => {
    const later = vi.fn();
    const refuse = gateMod('refuse', (async () => ({ allow: false, reason: 'no' })) as never);
    const after = gateMod('after', ((...args: unknown[]) => { later(...args); return { allow: true }; }) as never);
    expect(await createModRegistry([refuse, after]).gate(api, 'device.command', cmd)).toEqual({ allow: false, reason: 'no' });
    expect(later).not.toHaveBeenCalled();
  });

  it('skips a gate that throws', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const broken = gateMod('broken', (async () => { throw new Error('x'); }) as never);
    expect(await createModRegistry([broken]).gate(api, 'device.command', cmd)).toEqual({ allow: true });
    warn.mockRestore();
  });
});

describe('mod choices', () => {
  const mod = (id: string, defaultEnabled: boolean): ModDefinition => ({ id, name: id, description: '', defaultEnabled, register: () => undefined });

  it('follows the default until the user chooses', () => {
    const mods = [mod('on', true), mod('off', false)];
    expect(enabledMods(mods, {}).map((m) => m.id)).toEqual(['on']);
    expect(enabledMods(mods, { on: false, off: true }).map((m) => m.id)).toEqual(['off']);
  });

  it('lets server choices win and copies browser-only ones up', () => {
    const { merged, toUpload } = mergeChoices({ a: false, b: true }, { a: true });
    expect(merged).toEqual({ a: true, b: true });
    expect(toUpload).toEqual([['b', true]]);
  });

  it('keeps the same object when the choice does not change', () => {
    const choices = { a: true };
    expect(setModChoice(choices, 'a', true)).toBe(choices);
    expect(setModChoice(choices, 'a', false)).toEqual({ a: false });
  });
});
