/**
 * Settings -> Mobile app & phones (docs/tasks/TASK-17-mobile-app-phone-agent.md §4).
 *
 * "Get the app" card: a `kind: 'config'` QR that configures a fresh install (server +
 * Supabase), plus the APK link when VITE_MOBILE_APP_URL is set. Below it, a host picker and
 * the phone-slot table for that host (Slot / Phone / State / action). A pairable slot offers
 * "Show QR code", which opens the pairing dialog: one big code, self-renewing before it
 * expires, plus the same pairing as text to type in.
 *
 * The QR lived inline in the row for a while (560c73a4ec onwards) so pairing needed no click.
 * A table row is not enough space for a code a phone camera will actually read — the reporter
 * had to enlarge it every time, which is the click the inline version existed to save — so the
 * button is back and the row stays legible.
 *
 * While the dialog is open the page polls the slot, so a successful scan closes it and flips
 * the row to Unpair without anyone touching anything.
 */
import { Refresh as RefreshIcon } from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControl,
  IconButton,
  MenuItem,
  Paper,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import { useEffect, useMemo, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';

import PairQrDialog from './PairQrDialog';

import { getEnv } from '../../../frontend/src/config/constants';
import { useProfile } from '../../../frontend/src/hooks/auth/useProfile';
import {
  buildAppDownloadQrValue,
  useMobileApp,
  type MobileAppHost,
  type PhoneSlot,
  type PhoneSlotState,
} from './hooks/useMobileApp';

const EMPTY_STATE_TEXT =
  'No host has phone slots. Add DEVICEn_MODEL=phone_agent to a host .env — see docs.';

const STATE_DOT_COLOR: Record<PhoneSlotState, string> = {
  connected: '#4caf50',
  pending: '#ff9800',
  free: '#9e9e9e',
  offline: '#9e9e9e',
  unknown: '#9e9e9e',
};

const STATE_LABEL: Record<PhoneSlotState, string> = {
  connected: 'online',
  pending: 'pairing…',
  free: 'free',
  offline: 'offline',
  unknown: 'unknown',
};

const PAIRABLE_STATES: PhoneSlotState[] = ['free', 'pending', 'unknown'];

const formatLastSeen = (iso: string | null): string => {
  if (!iso) return '';
  const ms = Date.now() - Date.parse(iso);
  if (!Number.isFinite(ms) || ms < 0) return '';
  const mins = Math.round(ms / 60000);
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
};

const phoneLabel = (slot: PhoneSlot): string => {
  if (slot.phone) {
    return `${slot.phone.manufacturer} ${slot.phone.model} · ${slot.phone.screen.w}×${slot.phone.screen.h}`;
  }
  if (slot.device_name && slot.state === 'offline') {
    const seen = formatLastSeen(slot.last_seen);
    return seen ? `${slot.device_name} (last seen ${seen})` : slot.device_name;
  }
  return '—';
};

export default function MobileAppPage() {
  const { isAdmin } = useProfile();
  const { hosts, loading, error, refresh, createPairing, deletePairing } = useMobileApp();
  const [hostName, setHostName] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const [pairingHelpExpanded, setPairingHelpExpanded] = useState(false);

  // Preselect the first host once the list arrives; keep the user's choice afterwards.
  useEffect(() => {
    if (!hostName && hosts.length > 0) setHostName(hosts[0].host_name);
  }, [hosts, hostName]);

  const selectedHost: MobileAppHost | null = useMemo(
    () => hosts.find((h) => h.host_name === hostName) ?? null,
    [hosts, hostName],
  );
  const anyHostHasSlots = useMemo(() => hosts.some((h) => h.slots.length > 0), [hosts]);

  const apkUrl = getEnv('VITE_MOBILE_APP_URL');
  // Sidecar published next to the APK (`<apk>.json`: version, version_code, built, size_bytes,
  // commit) so the page can say what it hands out. Missing sidecar = link without details.
  const [apkInfo, setApkInfo] = useState<{
    version?: string;
    version_code?: number;
    built?: string;
    size_bytes?: number;
    commit?: string;
  } | null>(null);
  useEffect(() => {
    if (!apkUrl) return;
    let cancelled = false;
    fetch(`${apkUrl}.json`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((info) => {
        if (!cancelled && info && typeof info === 'object') setApkInfo(info);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [apkUrl]);
  // Cache-bust with the build's own version_code: this file gets overwritten in place under
  // the SAME name on every release, and Cloudflare's default edge cache served a stale build
  // for hours after an upload (TASK-17 BUG) because the plain URL never changed. A URL that
  // changes with every release can never go stale, independent of any cache-control header.
  const bustedApkUrl = apkUrl && apkInfo?.version_code ? `${apkUrl}?v=${apkInfo.version_code}` : apkUrl;
  const configQr = useMemo(() => buildAppDownloadQrValue(bustedApkUrl), [bustedApkUrl]);
  const apkDetails = apkInfo
    ? [
        apkInfo.version ? `v${apkInfo.version}` : null,
        apkInfo.size_bytes ? `${(apkInfo.size_bytes / 1048576).toFixed(0)} MB` : null,
        apkInfo.built ? `built ${apkInfo.built}` : null,
        apkInfo.commit ? apkInfo.commit : null,
      ]
        .filter(Boolean)
        .join(' · ')
    : '';

  const anyPairable = selectedHost?.slots.some((s) => PAIRABLE_STATES.includes(s.state)) ?? false;

  // The slot whose pairing dialog is open, if any. Held here rather than in the row so the
  // page can both poll for the scan and close the dialog when it lands.
  const [qrSlotId, setQrSlotId] = useState<string | null>(null);
  const qrSlot = selectedHost?.slots.find((s) => s.device_id === qrSlotId) ?? null;

  // Poll only while a code is on screen — that is the only moment a scan can arrive. At 1s
  // rather than the old 3s: the phone pairs in well under a second, so a slower poll was the
  // whole of the lag between scanning and the code going away.
  useEffect(() => {
    if (!qrSlotId) return;
    const timer = setInterval(() => refresh(), 1000);
    return () => clearInterval(timer);
  }, [qrSlotId, refresh]);

  // The scan landed (or the slot was taken by another phone): the code on screen is spent, so
  // take it away instead of leaving a dead QR up.
  useEffect(() => {
    if (!qrSlotId) return;
    if (qrSlot && PAIRABLE_STATES.includes(qrSlot.state)) return;
    setQrSlotId(null);
  }, [qrSlotId, qrSlot]);

  const handleUnpair = async (deviceId: string) => {
    if (!selectedHost) return;
    setActionError(null);
    try {
      await deletePairing(selectedHost.host_name, deviceId);
      refresh();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'failed to remove pairing');
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Typography variant="h6">Mobile app & phones</Typography>

      {error && <Alert severity="error">{error}</Alert>}
      {actionError && (
        <Alert severity="error" onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      <Paper variant="outlined" sx={{ p: 1.5, textAlign: 'center' }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Download the app
        </Typography>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap' }}>
          <QRCodeSVG value={configQr} size={160} level="L" />
          <Box component="ol" sx={{ m: 0, pl: 2.5, display: 'flex', flexDirection: 'column', gap: 0.5, textAlign: 'left' }}>
            <li>
              <Typography variant="body2">
                {apkUrl ? (
                  <>
                    <a href={bustedApkUrl} target="_blank" rel="noreferrer">
                      Install the VirtualPyTest app
                    </a>
                    {apkDetails && (
                      <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                        {apkDetails}
                      </Typography>
                    )}
                  </>
                ) : (
                  'Ask your admin for the APK'
                )}
              </Typography>
            </li>
            <li>
              <Typography variant="body2">
                Or scan this code with your camera — it downloads the app directly
              </Typography>
            </li>
            <li>
              <Typography variant="body2">
                Open it → Phone tab → Scan QR code → scan it again to finish setup
              </Typography>
            </li>
          </Box>
        </Box>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
          Android will block the install until you allow it: on the warning, tap Settings, enable
          "Allow from this source", then go back and install.
        </Typography>
      </Paper>

      {isAdmin && (
        <>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
            <Typography variant="subtitle2">Phone slots</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ flexBasis: '100%', order: 9 }}>
              A slot reserves one device entry for a phone on a host.
            </Typography>
            {hosts.length > 0 && (
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <Select value={hostName} onChange={(e) => setHostName(e.target.value)}>
                  {hosts.map((h) => (
                    <MenuItem key={h.host_name} value={h.host_name}>
                      {h.host_name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            )}
            <Box sx={{ flex: 1 }} />
            <Tooltip title="Refresh">
              <IconButton size="small" onClick={() => refresh()}>
                <RefreshIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>

          {!anyHostHasSlots ? (
            <Typography variant="body2" color="text.secondary">
              {EMPTY_STATE_TEXT}
            </Typography>
          ) : (
            selectedHost && (
              <Paper variant="outlined">
                <Table
                  size="small"
                  sx={{ '& .MuiTableRow-root:hover': { backgroundColor: 'transparent !important' } }}
                >
                  <TableHead>
                    <TableRow>
                      <TableCell>Slot</TableCell>
                      <TableCell>Phone</TableCell>
                      <TableCell>State</TableCell>
                      <TableCell align="right">Pair / Action</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {selectedHost.slots.map((slot) => (
                      <TableRow key={slot.device_id}>
                        <TableCell>{slot.device_id}</TableCell>
                        <TableCell>{phoneLabel(slot)}</TableCell>
                        <TableCell>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                            <Box
                              sx={{
                                width: 8,
                                height: 8,
                                borderRadius: '50%',
                                backgroundColor: STATE_DOT_COLOR[slot.state],
                                flexShrink: 0,
                              }}
                            />
                            {STATE_LABEL[slot.state]}
                          </Box>
                        </TableCell>
                        <TableCell align="right">
                          {PAIRABLE_STATES.includes(slot.state) ? (
                            <Button size="small" onClick={() => setQrSlotId(slot.device_id)}>
                              Show QR code
                            </Button>
                          ) : (
                            <Tooltip title="Disconnects this phone and frees the slot for another one.">
                              <Button size="small" onClick={() => handleUnpair(slot.device_id)}>
                                Unpair
                              </Button>
                            </Tooltip>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Paper>
            )
          )}
          {selectedHost?.slots_error && <Alert severity="warning">{selectedHost.slots_error}</Alert>}
          {anyPairable && (
            <Box>
              <Typography variant="caption" color="text.secondary">
                Press "Show QR code" on a free slot and scan it from the app's Phone tab, then share
                the "Entire screen" when asked.{' '}
                <Box
                  component="span"
                  onClick={() => setPairingHelpExpanded((v) => !v)}
                  sx={{ color: 'primary.main', cursor: 'pointer', textDecoration: 'underline' }}
                >
                  {pairingHelpExpanded ? 'Less info' : 'More info'}
                </Box>
              </Typography>
              {pairingHelpExpanded && (
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                  Without "Entire screen", the phone pairs but never streams a picture. The app also
                  needs the Accessibility service enabled for taps (Phone tab → Permissions → Fix).
                  Each code is one-time and renews itself before it expires — the row switches to
                  Unpair the moment the phone connects.
                </Typography>
              )}
            </Box>
          )}

          {selectedHost && qrSlotId && (
            <PairQrDialog
              hostName={selectedHost.host_name}
              deviceId={qrSlotId}
              createPairing={createPairing}
              onClose={() => setQrSlotId(null)}
            />
          )}
        </>
      )}
    </Box>
  );
}
