/**
 * Server picker labels (BUG-0432).
 *
 * The invariant: a name that is unique among the configured servers is shown on its own,
 * exactly as before. Only rows whose name collides get their host appended. Putting a
 * host on every row would make the common case — every server named differently — noisier
 * for no gain.
 */
import { describe, expect, it } from 'vitest';

import { buildServerPickerLabels, serverHostLabel } from '../../frontend/src/utils/serverLabels';

const PRIMARY = 'https://primary.example.com';
const SECONDARY = 'https://secondary.example.com';
const TERTIARY = 'https://tertiary.example.com';

/** Mirrors the component's name resolution: the advertised name, else the host. */
const identity = (names: Record<string, string>) => (url: string) =>
  names[url] ?? url.replace(/^https?:\/\//, '');

describe('serverHostLabel', () => {
  it('drops the protocol and any trailing slash', () => {
    expect(serverHostLabel('https://primary.example.com/')).toBe('primary.example.com');
    expect(serverHostLabel('http://primary.example.com')).toBe('primary.example.com');
  });

  it('keeps a port, which is often what tells two hosts apart', () => {
    expect(serverHostLabel('https://10.0.0.4:5109')).toBe('10.0.0.4:5109');
  });

  it('returns an empty string unchanged', () => {
    expect(serverHostLabel('')).toBe('');
  });
});

describe('buildServerPickerLabels', () => {
  it('leaves unique names untouched (BUG-0432)', () => {
    const labels = buildServerPickerLabels(
      [PRIMARY, SECONDARY],
      identity({ [PRIMARY]: 'Awesomation', [SECONDARY]: 'RPI1-server' }),
    );

    expect(labels).toEqual({ [PRIMARY]: 'Awesomation', [SECONDARY]: 'RPI1-server' });
  });

  it('appends the host to every row whose name collides (BUG-0432)', () => {
    // The real case: a copied .env, so two boxes both answer to the same SERVER_NAME.
    const labels = buildServerPickerLabels(
      [PRIMARY, SECONDARY],
      identity({ [PRIMARY]: 'Awesomation', [SECONDARY]: 'Awesomation' }),
    );

    expect(labels[PRIMARY]).toBe('Awesomation — primary.example.com');
    expect(labels[SECONDARY]).toBe('Awesomation — secondary.example.com');
  });

  it('disambiguates a collision among several rows without touching the unique ones', () => {
    const labels = buildServerPickerLabels(
      [PRIMARY, SECONDARY, TERTIARY],
      identity({ [PRIMARY]: 'Shared', [SECONDARY]: 'Shared', [TERTIARY]: 'RPI1-server' }),
    );

    expect(labels[PRIMARY]).toBe('Shared — primary.example.com');
    expect(labels[SECONDARY]).toBe('Shared — secondary.example.com');
    expect(labels[TERTIARY]).toBe('RPI1-server');
  });

  it('disambiguates two servers on one host by port', () => {
    // Two vpt-host instances behind the same box, both answering with one SERVER_NAME:
    // the port is the only thing left that tells them apart.
    const server = 'https://10.0.0.4:5109';
    const hostSvc = 'https://10.0.0.4:6109';
    const labels = buildServerPickerLabels([server, hostSvc], identity({ [server]: 'Shared', [hostSvc]: 'Shared' }));

    expect(labels[server]).toBe('Shared — 10.0.0.4:5109');
    expect(labels[hostSvc]).toBe('Shared — 10.0.0.4:6109');
  });

  it('needs no disambiguation when the fallback names already differ by port', () => {
    const labels = buildServerPickerLabels(
      ['https://10.0.0.4:5109', 'https://10.0.0.4:6109'],
      identity({}),
    );

    expect(labels['https://10.0.0.4:5109']).toBe('10.0.0.4:5109');
    expect(labels['https://10.0.0.4:6109']).toBe('10.0.0.4:6109');
  });

  it('does not append a host that would just repeat the name', () => {
    // A server whose name already IS its host would otherwise read "host — host".
    const url = 'https://primary.example.com';
    const labels = buildServerPickerLabels([url, SECONDARY], () => 'primary.example.com');

    expect(labels[url]).toBe('primary.example.com');
  });

  it('handles an empty list', () => {
    expect(buildServerPickerLabels([], () => 'unused')).toEqual({});
  });
});
