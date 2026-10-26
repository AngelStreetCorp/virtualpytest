/**
 * TASK-113 — migration helper tests: useRowServerUrl + lookupHostServerUrl.
 */
import { describe, it, expect } from 'vitest';
import { lookupHostServerUrl } from '../../../frontend/src/hooks/allServer/useRowServerUrl';

const hostsA = [
  { host_name: 'host-1', server_url: 'https://a.example.test' },
  { host_name: 'host-2' },
];
const hostsB = [{ host_name: 'host-3', server_url: 'https://b.example.test' }];

const SERVER_HOSTS = [
  {
    server_info: { server_url: 'https://a.example.test', server_name: 'A' },
    hosts: hostsA,
  },
  {
    server_info: { server_url: 'https://b.example.test', server_name: 'B' },
    hosts: hostsB,
  },
];

describe('lookupHostServerUrl', () => {
  it('returns the host.server_url when stamped', () => {
    expect(lookupHostServerUrl(SERVER_HOSTS, 'host-1')).toBe('https://a.example.test');
    expect(lookupHostServerUrl(SERVER_HOSTS, 'host-3')).toBe('https://b.example.test');
  });

  it('falls back to the server_info.server_url when the host is unstamped', () => {
    expect(lookupHostServerUrl(SERVER_HOSTS, 'host-2')).toBe('https://a.example.test');
  });

  it('returns null when the host is not in any server', () => {
    expect(lookupHostServerUrl(SERVER_HOSTS, 'host-missing')).toBeNull();
  });

  it('returns null for empty input', () => {
    expect(lookupHostServerUrl(SERVER_HOSTS, '')).toBeNull();
  });
});
