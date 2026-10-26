import { describe, expect, it } from 'vitest';
import type { Host } from '../../frontend/src/types/common/Host_Types';
import type { ServerHostData } from '../../frontend/src/types/common/Server_Types';
import { dedupeHostsByName } from '../../frontend/src/components/status/hostCatalog';

const host = (host_name: string, over: Partial<Host> = {}): Host =>
  ({
    host_name,
    host_url: `/host/${host_name}`,
    host_api_url: `http://10.0.0.5:6109`,
    host_port: 6109,
    devices: [],
    device_count: 0,
    status: 'online',
    last_seen: 0,
    registered_at: '2026-10-22T00:00:00Z',
    system_stats: { cpu_percent: 10, memory_percent: 20, disk_percent: 30 },
    ...over,
  }) as Host;

const server = (server_url: string, hosts: Host[]): ServerHostData =>
  ({
    server_info: { server_url },
    hosts,
  }) as unknown as ServerHostData;

/**
 * The live layout (2026-10-22): the primary server and the QualiAI server both
 * register host-clone-1 and host-clone-2 — the same two machines, same
 * host_api_url — so the Status page showed them twice and counted their
 * services twice (BUG-0771).
 */
const PRIMARY = server('https://primary', [
  host('host-clone-1'),
  host('labox-backend'),
  host('labox-mobile'),
  host('host-clone-2'),
]);

const QUALIAI = server('https://qualiai', [
  host('host-clone-2'),
  host('host-clone-3'),
  host('host-android-mobile'),
  host('host-android-tv'),
  host('host-clone-1'),
]);

describe('dedupeHostsByName', () => {
  it('lists a host registered on two servers once', () => {
    const names = dedupeHostsByName([PRIMARY, QUALIAI]).map((h) => h.host_name);
    expect(names.filter((n) => n === 'host-clone-1')).toHaveLength(1);
    expect(names.filter((n) => n === 'host-clone-2')).toHaveLength(1);
  });

  it('keeps every distinct host and the order of the servers', () => {
    const names = dedupeHostsByName([PRIMARY, QUALIAI]).map((h) => h.host_name);
    expect(names).toEqual([
      'host-clone-1',
      'labox-backend',
      'labox-mobile',
      'host-clone-2',
      'host-clone-3',
      'host-android-mobile',
      'host-android-tv',
    ]);
  });

  it('lets a later catalog fill in the system stats the first one did not carry', () => {
    const bare = host('host-clone-1', { system_stats: undefined as unknown as Host['system_stats'] });
    const withStats = host('host-clone-1', { system_stats: { cpu_percent: 42 } as unknown as Host['system_stats'] });
    const [merged] = dedupeHostsByName([server('https://primary', [bare]), server('https://qualiai', [withStats])]);
    expect(merged.system_stats).toEqual({ cpu_percent: 42 });
  });

  it('does not invent a second row when a server repeats a host inside its own catalog', () => {
    const names = dedupeHostsByName([server('https://primary', [host('host-clone-1'), host('host-clone-1')])]).map((h) => h.host_name);
    expect(names).toEqual(['host-clone-1']);
  });

  it('survives a server with no hosts at all', () => {
    expect(dedupeHostsByName([server('https://empty', [])])).toEqual([]);
    expect(dedupeHostsByName([])).toEqual([]);
  });
});
