/**
 * Data hook for the "Mobile app & phones" page (docs/tasks/TASK-17-mobile-app-phone-agent.md
 * §1.2, §4). Talks to /server/mobile-app/* (implemented in parallel under
 * features/mobile-app/backend_server) and builds the QR payload the page renders, which is
 * the server's pairing response merged with this web app's OWN runtime env — the same QR
 * both configures a fresh install (kind 'config') and pairs it to a slot (kind 'pair').
 */
import { useCallback, useEffect, useState } from 'react';

import { buildServerUrl } from '../../../../frontend/src/utils/buildUrlUtils';

export type PhoneSlotState = 'free' | 'pending' | 'connected' | 'offline' | 'unknown';

export interface PhoneInfo {
  manufacturer: string;
  model: string;
  android: string;
  screen: { w: number; h: number; density: number };
}

export interface PhoneSlot {
  device_id: string;
  device_name: string;
  state: PhoneSlotState;
  phone: PhoneInfo | null;
  last_seen: string | null;
  /** The rate the host ASKED for, not evidence of frames. See `streaming`. */
  fps: number;
  /** Frames are actually arriving. Absent from a host older than this field. */
  streaming?: boolean;
}

export interface MobileAppHost {
  host_name: string;
  host_url: string;
  host_api_url: string;
  status: string;
  slots: PhoneSlot[];
  slots_error?: string;
}

export interface PairingResponse {
  success: boolean;
  host_name: string;
  device_id: string;
  token: string;
  expires_at: string;
  host_url: string;
  host_api_url: string;
}



/** Separator for the pairing code. Absent from host names, device ids and the base64url
 *  token alike, so a plain split is unambiguous. */
export const PAIRING_CODE_SEP = '/';

/**
 * Short, scannable-and-typeable stand-in for a pairing payload: `<host>/<device>/<token>`.
 *
 * This is what the pairing QR encodes. Carrying the whole payload made it a 65-module symbol —
 * twice the modules of the "download the app" QR beside it, which is just a URL — so at any
 * size that fits a table row its modules were finer than a phone camera reads off a monitor,
 * and it only decoded once blown up. This is 64 characters and encodes to 29 modules, smaller
 * than the download QR, because everything else is already on the phone (`server_url`, from
 * when it was configured) or derived from it.
 */
export const buildPairingCode = (pairing: PairingResponse): string =>
  [pairing.host_name, pairing.device_id, pairing.token].join(PAIRING_CODE_SEP);

/** A pairing code and nothing else: three non-empty parts, no scheme, no spaces. Deliberately
 *  strict so a scanned download URL is never mistaken for one. */
export const PAIRING_CODE_RE = /^[^\s/:]+\/[^\s/:]+\/[^\s/:]+$/;

/** The app assumes the host's one-time token outlives this; the host enforces the real TTL. */
const PAIRING_CODE_TTL_MS = 10 * 60 * 1000;

/**
 * Expand a pairing code into the payload the native side accepts. Shared by the scanner and
 * the typed-code dialog so both produce byte-identical payloads.
 */
export const pairPayloadFromCode = (code: string, serverUrl: string): Record<string, unknown> => {
  const trimmed = code.trim();
  if (!PAIRING_CODE_RE.test(trimmed)) {
    throw new Error(`expected <host>${PAIRING_CODE_SEP}<device>${PAIRING_CODE_SEP}<token>`);
  }
  const base = (serverUrl || '').replace(/\/+$/, '');
  if (!base) throw new Error('set the server URL first');
  const [hostName, deviceId, token] = trimmed.split(PAIRING_CODE_SEP);
  const hostUrl = `${base}/host/${hostName}`;
  return {
    v: 1,
    kind: 'pair',
    server_url: base,
    host_name: hostName,
    device_id: deviceId,
    // A code cannot carry the host's LAN address; the agent already falls back to the proxied
    // host_url when it cannot reach host_api_url, so both point there.
    host_api_url: hostUrl,
    host_url: hostUrl,
    token,
    expires_at: new Date(Date.now() + PAIRING_CODE_TTL_MS).toISOString(),
  };
};

/**
 * "Get the app" QR value. This code is scanned with the phone's own camera, before the app
 * exists to read a structured payload — a JSON `config` payload used to sit here, which every
 * ordinary camera app can only show as inert text (or, at best, the URLs buried inside it,
 * which is what actually happened: two unrelated-looking links instead of one useful action).
 * A plain URL is something every scanner offers to open, so this points straight at the APK —
 * scanning it downloads the app directly. The app's own "Scan QR code" button can scan this
 * same code again after install: PayloadApplier.kt recognises a bare URL and configures itself
 * from its origin, so nothing else about the flow changes.
 */
export const buildAppDownloadQrValue = (apkUrl: string): string =>
  apkUrl && /^https?:\/\//i.test(apkUrl) ? apkUrl : window.location.origin;

export function useMobileApp() {
  const [hosts, setHosts] = useState<MobileAppHost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(buildServerUrl('/server/mobile-app/hosts'));
      const data = await res.json();
      if (!res.ok || data.success === false) {
        setError(data.error ?? 'failed to load hosts');
        setHosts([]);
        return;
      }
      setError(null);
      setHosts(data.hosts ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load hosts');
      setHosts([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const createPairing = useCallback(async (hostName: string, deviceId: string): Promise<PairingResponse> => {
    const res = await fetch(buildServerUrl('/server/mobile-app/pairings'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host_name: hostName, device_id: deviceId }),
    });
    const data = await res.json();
    if (!res.ok || data.success === false) {
      throw new Error(data.error ?? 'failed to create pairing');
    }
    return data as PairingResponse;
  }, []);

  const deletePairing = useCallback(async (hostName: string, deviceId: string): Promise<void> => {
    const res = await fetch(
      buildServerUrl(`/server/mobile-app/pairings/${encodeURIComponent(hostName)}/${encodeURIComponent(deviceId)}`),
      { method: 'DELETE' },
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.success === false) {
      throw new Error(data.error ?? 'failed to remove pairing');
    }
  }, []);

  return { hosts, loading, error, refresh, createPairing, deletePairing };
}
