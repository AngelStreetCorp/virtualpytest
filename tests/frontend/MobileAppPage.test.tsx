import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import MobileAppPage from '../../features/mobile-app/frontend/MobileAppPage';

// MobileAppPage reads the signed-in profile through useProfile() -> useAuthContext(), which
// throws outside an AuthProvider — the page is a render test, not an auth test.
vi.mock('../../frontend/src/hooks/auth/useProfile', () => ({
  useProfile: () => ({
    profile: { id: 'test-user', role: 'admin' },
    refreshProfile: vi.fn(),
    isAdmin: true,
    isTester: false,
    isViewer: false,
  }),
}));

import {
  buildAppDownloadQrValue,
  buildPairingCode,
  pairPayloadFromCode,
  PAIRING_CODE_RE,
  type PairingResponse,
} from '../../features/mobile-app/frontend/hooks/useMobileApp';

describe('buildAppDownloadQrValue', () => {
  it('is the APK URL when one is configured — scanning it must download the app directly', () => {
    expect(buildAppDownloadQrValue('https://vpt.example/downloads/app.apk')).toBe(
      'https://vpt.example/downloads/app.apk',
    );
  });

  it('falls back to this page\'s origin when no APK is published', () => {
    expect(buildAppDownloadQrValue('')).toBe(window.location.origin);
  });

  it('ignores a non-absolute value (misconfigured env) and falls back to the origin', () => {
    expect(buildAppDownloadQrValue('/downloads/app.apk')).toBe(window.location.origin);
  });
});

describe('pairing code', () => {
  const pairing: PairingResponse = {
    success: true,
    host_name: 'vpt-host1',
    device_id: 'device3',
    token: 'tok-123',
    expires_at: '2026-09-15T10:12:00Z',
    host_url: 'https://vpt.example/host/vpt-host1',
    host_api_url: 'http://192.168.0.50:6109',
  };

  it('is the three parts that identify the slot, and nothing else', () => {
    expect(buildPairingCode(pairing)).toBe('vpt-host1/device3/tok-123');
  });

  it('expands back into the payload the native side accepts', () => {
    const payload = pairPayloadFromCode(buildPairingCode(pairing), 'https://vpt.example/') as Record<string, unknown>;
    expect(payload).toMatchObject({
      v: 1,
      kind: 'pair',
      server_url: 'https://vpt.example',
      host_name: 'vpt-host1',
      device_id: 'device3',
      token: 'tok-123',
      // Derived, not carried: a code cannot know the host's LAN address.
      host_url: 'https://vpt.example/host/vpt-host1',
      host_api_url: 'https://vpt.example/host/vpt-host1',
    });
    expect(typeof payload.expires_at).toBe('string');
  });

  it('rejects anything that is not a code, so a scanned download URL is never mistaken for one', () => {
    expect(PAIRING_CODE_RE.test('https://vpt.example/downloads/app.apk')).toBe(false);
    expect(PAIRING_CODE_RE.test('vpt-host1/device3/tok-123')).toBe(true);
    expect(() => pairPayloadFromCode('vpt-host1/device3', 'https://vpt.example')).toThrow();
    expect(() => pairPayloadFromCode('a/b/c', '')).toThrow();
  });
});

const HOSTS_WITH_SLOTS = {
  success: true,
  hosts: [
    {
      host_name: 'vpt-host1',
      host_url: 'https://vpt.example/host/vpt-host1',
      host_api_url: 'http://192.168.0.50:6109',
      status: 'online',
      slots: [
        {
          device_id: 'device2',
          device_name: 'Google Pixel 8',
          state: 'connected',
          phone: { manufacturer: 'Google', model: 'Pixel 8', android: '15', screen: { w: 1080, h: 2400, density: 420 } },
          last_seen: new Date().toISOString(),
          fps: 3,
        },
        {
          device_id: 'device3',
          device_name: '',
          state: 'free',
          phone: null,
          last_seen: null,
          fps: 0,
        },
      ],
    },
  ],
};

const EMPTY_HOSTS = { success: true, hosts: [] };

describe('MobileAppPage', () => {
  it('renders the heading, both slots, and the right action per slot state', async () => {
    // Opening a free slot's pairing dialog mints a token — the mock must tell a GET /hosts
    // apart from a POST /pairings, unlike a single blanket response.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (init?.method === 'POST' && String(url).includes('/pairings')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              success: true,
              host_name: 'vpt-host1',
              device_id: 'device3',
              token: 'tok-abc',
              expires_at: new Date(Date.now() + 600_000).toISOString(),
              host_url: 'https://vpt.example/host/vpt-host1',
              host_api_url: 'http://192.168.0.50:6109',
            }),
          });
        }
        return Promise.resolve({ ok: true, json: async () => HOSTS_WITH_SLOTS });
      }),
    );

    render(<MobileAppPage />);

    expect(await screen.findByRole('heading', { name: 'Mobile app & phones' })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('device2')).toBeInTheDocument();
      expect(screen.getByText('device3')).toBeInTheDocument();
    });

    const connectedRow = screen.getByText('device2').closest('tr')!;
    expect(connectedRow).toHaveTextContent('Unpair');

    // The free row offers "Show QR code" (the QR went back behind a button so a page with
    // several free slots is not a wall of codes). Clicking it opens the pairing dialog: the
    // code as an SVG, with a live mm:ss countdown to the token's expiry.
    const freeRow = screen.getByText('device3').closest('tr')!;
    expect(freeRow.querySelector('svg')).not.toBeInTheDocument();
    fireEvent.click(within(freeRow).getByRole('button', { name: 'Show QR code' }));

    const dialog = await screen.findByRole('dialog');
    await waitFor(() => {
      expect(dialog.querySelector('svg')).toBeInTheDocument();
    });
    expect(dialog).toHaveTextContent(/expires in \d+:\d{2}/);
    expect(dialog).toHaveTextContent('Pairing device3 on vpt-host1');
  });

  it('shows the exact empty-state text when no host has phone slots', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => EMPTY_HOSTS,
      }),
    );

    render(<MobileAppPage />);

    expect(await screen.findByRole('heading', { name: 'Mobile app & phones' })).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getByText('No host has phone slots. Add DEVICEn_MODEL=phone_agent to a host .env — see docs.'),
      ).toBeInTheDocument();
    });
  });
});
