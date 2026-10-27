/**
 * TASK-179 P4 — the server scope an Atlas message carries.
 */
import { describe, it, expect } from 'vitest';
import { buildTurnScope } from '../../../frontend/src/lib/allServer/turnScope';
import { ALL_SERVERS_SENTINEL } from '../../../frontend/src/lib/allServer/scope';

const SERVERS: any[] = [
  { server_info: { server_url: 'https://a.test', server_name: 'Awesomation' }, hosts: [{ host_name: 'h1' }, { host_name: 'dup' }] },
  { server_info: { server_url: 'https://b.test', server_name: 'vpt-pi4' }, hosts: [{ host_name: 'h2' }, { host_name: 'dup' }] },
];

describe('buildTurnScope', () => {
  it('All mode sends scope all and the host server when only one server has the host', () => {
    expect(buildTurnScope(ALL_SERVERS_SENTINEL, SERVERS, 'h2')).toEqual({
      server_scope: 'all',
      selected_host_server: 'vpt-pi4',
    });
  });

  it('a host name on two servers names no server (the tool asks which)', () => {
    expect(buildTurnScope(ALL_SERVERS_SENTINEL, SERVERS, 'dup').selected_host_server).toBe('');
  });

  it('a single server sends its name', () => {
    expect(buildTurnScope('https://b.test', SERVERS, '')).toEqual({
      server_scope: 'vpt-pi4',
      selected_host_server: '',
    });
  });

  it('an unknown server url sends an empty scope', () => {
    expect(buildTurnScope('https://nope.test', SERVERS, '').server_scope).toBe('');
  });
});
