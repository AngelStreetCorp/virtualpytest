/**
 * "This phone" (docs/tasks/TASK-17-mobile-app-phone-agent.md §4) — native only. On the web
 * (isPhoneAgentAvailable() false) it renders a short notice: the route stays harmless so the
 * E2E page sweep (tests/e2e/playwright/specs/ui.pages.spec.js) can visit it on a normal web
 * build. Inside the APK it drives the `phoneAgent` native plugin: first-run (scan / manual
 * server entry) or configured (status, permission checklist, scan/unpair).
 */
import { CheckCircle as OkIcon, Warning as WarnIcon } from '@mui/icons-material';
import {
  Alert,
  Backdrop,
  Box,
  FormControlLabel,
  Switch,
  Button,
  CircularProgress,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  TextField,
  Typography,
} from '@mui/material';
import React, { useCallback, useEffect, useState } from 'react';

import { StyledDialog } from '../../../frontend/src/components/common/StyledDialog';
import { useIsNativeApp } from '../../../frontend/src/hooks/useIsNativeApp';
import { buildServerUrl } from '../../../frontend/src/utils/buildUrlUtils';
import { PAIRING_CODE_RE, PAIRING_CODE_SEP, pairPayloadFromCode } from './hooks/useMobileApp';
import { isPhoneAgentAvailable, phoneAgent, type PhoneAgentStatus } from './native/phoneAgent';

/** What the blocking overlay says, keyed by the `run()` label that set it. */
const BUSY_LABEL: Record<string, string> = {
  scan: 'Pairing this phone…',
  'pairing code': 'Pairing this phone…',
  'server url': 'Saving the server…',
  unpair: 'Unpairing…',
};

const EMPTY_STATUS: PhoneAgentStatus = {
  configured: false,
  paired: false,
  connected: false,
  captureActive: false,
  fps: 0,
  accessibilityEnabled: false,
  projectionGranted: false,
  batteryUnrestricted: false,
  notificationsEnabled: false,
};

/** How long to keep waiting for the bridge before believing it is genuinely not coming. */
const BRIDGE_WAIT_MS = 3000;

/**
 * `isPhoneAgentAvailable()` reads a global the native shell installs by injecting a script
 * into index.html, so asking once during render can catch the APK before the bridge exists
 * and pin this page to its web notice for the whole session — the page-level twin of the
 * bottom-nav bug this hook's `useIsNativeApp()` exists for. On the web `isNativeApp()` is
 * false from the start, so the notice still renders immediately there (the E2E page sweep
 * in tests/e2e/playwright/specs/ui.pages.spec.js depends on that); only inside the app do
 * we wait, and only until the bridge shows up or BRIDGE_WAIT_MS is gone.
 */
function usePhoneAgentReady(): { ready: boolean; waiting: boolean } {
  const isNative = useIsNativeApp();
  const [ready, setReady] = useState(isPhoneAgentAvailable);
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    if (ready || !isNative) return;
    const poll = setInterval(() => {
      if (isPhoneAgentAvailable()) setReady(true);
    }, 100);
    const giveUp = setTimeout(() => {
      setTimedOut(true);
      clearInterval(poll);
    }, BRIDGE_WAIT_MS);
    return () => {
      clearInterval(poll);
      clearTimeout(giveUp);
    };
  }, [ready, isNative]);

  return { ready, waiting: !ready && isNative && !timedOut };
}

export default function ThisPhonePage() {
  const { ready, waiting } = usePhoneAgentReady();

  if (waiting) {
    return (
      <Box sx={{ p: 4, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress />
      </Box>
    );
  }
  if (!ready) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="info">This page is part of the VirtualPyTest mobile app.</Alert>
      </Box>
    );
  }
  return <ThisPhoneNative />;
}

function ThisPhoneNative() {
  const [status, setStatus] = useState<PhoneAgentStatus>(EMPTY_STATUS);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [urlDialogOpen, setUrlDialogOpen] = useState(false);
  const [a11yHelpOpen, setA11yHelpOpen] = useState(false);
  const [codeDialogOpen, setCodeDialogOpen] = useState(false);
  const [pairingCodeInput, setPairingCodeInput] = useState('');
  const [serverUrlInput, setServerUrlInput] = useState('');

  /**
   * Pairing is refused until every permission is green.
   *
   * Pairing first and granting afterwards is what produced most of this feature's confusing
   * states: a slot that reports "connected" while the phone streams nothing (no screen
   * capture), or a device that takes commands and silently ignores every one (no
   * accessibility service). Both look like a broken host from the web side. Getting the
   * permissions first costs one extra step and removes the whole class.
   *
   * Only applies once the phone is configured — the first scan is how the server gets set up,
   * and there is nothing to grant permissions *for* before that.
   */
  /**
   * A paired phone is never simply "disconnected": the agent retries from scratch every 30s
   * (PhoneAgentService's reconnect watchdog) on top of Socket.IO's own backoff. `connecting`
   * comes from the service; the `paired` fallback covers the moment right after a launch,
   * before the first attempt has published anything.
   */
  const linkConnecting = !status.connected && (status.connecting ?? status.paired);

  /**
   * The socket and the video are two different things, and saying "connected · 0 fps" for a
   * phone that is reachable but streaming nothing put the bad news in a unit nobody reads.
   * `idle` is its own state: the link is up, there is simply no screen capture behind it —
   * which is a permission away, not a connection problem.
   */
  const linkState: 'streaming' | 'idle' | 'connecting' | 'down' = status.connected
    ? status.captureActive || status.fps > 0
      ? 'streaming'
      : 'idle'
    : linkConnecting
      ? 'connecting'
      : 'down';
  const LINK_COLOR = { streaming: '#4caf50', idle: '#ffb300', connecting: '#ffb300', down: '#9e9e9e' };
  const LINK_TEXT = {
    streaming: `connected · ${status.fps} fps`,
    idle: 'connected · not streaming',
    connecting: 'connecting…',
    down: 'disconnected',
  };

  const canPair =
    status.accessibilityEnabled &&
    status.projectionGranted &&
    status.batteryUnrestricted &&
    status.notificationsEnabled;

  const refresh = useCallback(async () => {
    try {
      setStatus(await phoneAgent.getStatus());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to read status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    let remove: (() => void) | undefined;
    phoneAgent.addListener('statusChanged', (s) => setStatus(s)).then((h) => {
      remove = h.remove;
    });
    return () => remove?.();
  }, [refresh]);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : `${label} failed`);
    } finally {
      setBusy(null);
    }
  };

  /**
   * Android's screen-capture consent cannot be pre-granted, persisted or silently re-acquired
   * — every projection needs a fresh system dialog. Unpairing stops the agent service, which
   * ends the projection, so coming back from an unpair always means asking again. Ask at the
   * moment of pairing, while the user is still here and expecting dialogs, rather than
   * leaving them paired at 0 fps with only the checklist to explain it.
   */
  const promptForProjection = async () => {
    try {
      await phoneAgent.requestProjection();
    } catch {
      // Non-fatal — the checklist's own "Fix" button covers a decline or a failure here.
    }
  };

  const scanAndApply = () =>
    run('scan', async () => {
      const { value } = await phoneAgent.scanQr();
      // The pairing QR carries the short code now, so it expands here — exactly as a typed
      // code does. Anything else (the "download the app" URL, or an older page's JSON
      // payload) is passed through for the native side to interpret as before.
      const payload = PAIRING_CODE_RE.test(value.trim())
        ? JSON.stringify(pairPayloadFromCode(value, status.serverUrl || ''))
        : value;
      const s = await phoneAgent.applyConfig({ payload });
      if (s.configured) {
        if (s.paired) await promptForProjection();
        await phoneAgent.reloadApp();
      } else {
        setStatus(s);
      }
    });

  const submitServerUrl = () =>
    run('server url', async () => {
      const s = await phoneAgent.setServer({ serverUrl: serverUrlInput.trim() });
      setUrlDialogOpen(false);
      if (s.configured) await phoneAgent.reloadApp();
      else setStatus(s);
    });

  /**
   * Pair from the short code the web page shows instead of its QR — a camera that will not
   * read a dense code, or a phone with no line of sight to the screen, should not be a dead
   * end. The code is `<host>/<device>/<token>`; everything else the QR would have carried is
   * either already here (the configured server) or derived from it, and the native side takes
   * the same payload either way, so this reuses applyConfig rather than adding a second path.
   */
  const submitPairingCode = () =>
    run('pairing code', async () => {
      await phoneAgent.applyConfig({
        payload: JSON.stringify(pairPayloadFromCode(pairingCodeInput, status.serverUrl || '')),
      });
      setCodeDialogOpen(false);
      setPairingCodeInput('');
      await promptForProjection();
      refresh();
    });

  const unpair = () =>
    run('unpair', async () => {
      // Unpairing here used to be purely local: the phone forgot its credentials and stopped
      // its service, but nothing told the other side, so the slot on "Mobile app & phones"
      // kept the phone attached and just went offline — and its Unpair button was still the
      // only way to actually free it. The wire protocol's `unpair` event only runs host →
      // phone, so the phone releases the slot the same way the web page does, through the
      // server. Best-effort: a phone that unpairs while offline must still forget its own
      // credentials, so a failure here is reported but does not stop the local unpair.
      const { hostName, deviceId } = status;
      let releaseError: string | null = null;
      if (hostName && deviceId) {
        try {
          const res = await fetch(
            buildServerUrl(
              `/server/mobile-app/pairings/${encodeURIComponent(hostName)}/${encodeURIComponent(deviceId)}`,
            ),
            { method: 'DELETE' },
          );
          if (!res.ok) releaseError = `the slot may still show as paired (HTTP ${res.status})`;
        } catch {
          releaseError = 'the slot may still show as paired (server unreachable)';
        }
      }
      setStatus(await phoneAgent.unpair());
      if (releaseError) setError(releaseError);
    });

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
      {/* Pairing is a scan, then a system consent dialog, then a WebView reload — from the
          outside that is several seconds of a page that looks idle, and the button labels
          alone are easy to miss on a phone. Block the page and say what is happening. */}
      <Backdrop open={Boolean(busy)} sx={{ zIndex: (t) => t.zIndex.drawer + 1, flexDirection: 'column', gap: 2 }}>
        <CircularProgress color="inherit" />
        <Typography variant="body2">{BUSY_LABEL[busy ?? ''] ?? 'Working…'}</Typography>
      </Backdrop>

      <Typography variant="h6">This phone</Typography>
      {error && (
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      {status.lastError && <Alert severity="warning">{status.lastError}</Alert>}

      {!status.configured ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, alignItems: 'flex-start' }}>
          <Typography variant="body2" color="text.secondary">
            Connect to your server
          </Typography>
          <Button variant="contained" size="small" disabled={!!busy} onClick={scanAndApply}>
            {busy === 'scan' ? 'Scanning…' : 'Scan QR code'}
          </Button>
          <Button variant="outlined" size="small" disabled={!!busy} onClick={() => setUrlDialogOpen(true)}>
            Enter server URL
          </Button>
          <Button variant="text" size="small" disabled={!!busy} onClick={() => setCodeDialogOpen(true)}>
            Enter pairing code
          </Button>
          <Typography variant="caption" color="text.secondary">
            QR from Settings → Mobile app & phones
          </Typography>
        </Box>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {/* The APK actually running, so it can be checked against the version the download
              page advertises without going through Android's app settings. */}
          <StatusRow label="App version" value={status.appVersion ?? '—'} />
          <StatusRow label="Server" value={status.serverUrl ?? '—'} />
          <StatusRow label="Paired" value={status.paired ? `${status.hostName} · ${status.deviceId}` : 'not paired'} />
          <StatusRow
            label="Link"
            value={
              <>
                {/* Amber and pulsing while the agent is retrying, so a link that is working on
                    it does not read the same as one that has given up. A paired phone retries
                    on its own every 30s, which was invisible before. */}
                <Box
                  component="span"
                  sx={{
                    display: 'inline-block',
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    backgroundColor: LINK_COLOR[linkState],
                    mr: 0.75,
                    // Only the retrying state pulses: 'idle' is settled, waiting on a
                    // permission rather than on the network.
                    ...(linkState === 'connecting' && {
                      animation: 'vptLinkPulse 1.2s ease-in-out infinite',
                      '@keyframes vptLinkPulse': {
                        '0%, 100%': { opacity: 1 },
                        '50%': { opacity: 0.25 },
                      },
                    }),
                  }}
                />
                {LINK_TEXT[linkState]}
              </>
            }
          />

          <Typography variant="subtitle2" sx={{ mt: 1 }}>
            Permissions
          </Typography>
          <List dense disablePadding>
            <PermissionRow
              ok={status.accessibilityEnabled}
              label="Accessibility service"
              fix={() => setA11yHelpOpen(true)}
            />
            <PermissionRow
              ok={status.projectionGranted}
              label="Screen capture"
              fix={async () => {
                await phoneAgent.requestProjection();
                refresh();
              }}
            />
            <PermissionRow
              ok={status.batteryUnrestricted}
              label="Battery unrestricted"
              fix={() => phoneAgent.openBatterySettings()}
            />
            {/* Without this there is no way to tell a live agent from a dead one without
                opening the app: Android's screen-capture icon looks identical either way. */}
            <PermissionRow
              ok={status.notificationsEnabled}
              label="Show link status in the status bar"
              fix={async () => {
                await phoneAgent.enableNotifications();
                refresh();
              }}
            />
          </List>

          {!canPair && (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
              Fill all permissions to continue
            </Typography>
          )}

          {/* Not in the Permissions list above: this is a preference, not something the agent
              needs, and pairing must not wait on it. */}
          <FormControlLabel
            sx={{ mt: 0.5 }}
            control={
              <Switch
                size="small"
                checked={status.actionOverlay !== false}
                onChange={async (e) => {
                  setStatus(await phoneAgent.setActionOverlay({ enabled: e.target.checked }));
                }}
              />
            }
            label={
              <Typography variant="body2">
                Execution overlay
              </Typography>
            }
          />

          <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
            <Button
              size="small"
              variant="outlined"
              disabled={!!busy || !canPair}
              onClick={scanAndApply}
            >
              Scan pairing QR
            </Button>
            <Button
              size="small"
              disabled={!!busy || !canPair}
              onClick={() => setCodeDialogOpen(true)}
            >
              Enter code
            </Button>
            {/* Nothing to unpair from when no phone is on a slot — a permanently greyed-out
                button just adds a third thing to read past. */}
            {status.paired && (
              <Button size="small" color="error" disabled={!!busy} onClick={unpair}>
                Unpair
              </Button>
            )}
          </Box>
        </Box>
      )}

      <AccessibilityHelpDialog open={a11yHelpOpen} onClose={() => setA11yHelpOpen(false)} />

      <StyledDialog open={codeDialogOpen} onClose={() => setCodeDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Enter pairing code</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Shown under the QR on Settings → Mobile app &amp; phones.
          </Typography>
          <TextField
            autoFocus
            fullWidth
            size="small"
            placeholder={`host${PAIRING_CODE_SEP}device${PAIRING_CODE_SEP}token`}
            value={pairingCodeInput}
            onChange={(e) => setPairingCodeInput(e.target.value)}
            inputProps={{ autoCapitalize: 'none', autoCorrect: 'off', spellCheck: false }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCodeDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!pairingCodeInput.trim() || busy === 'pairing code'}
            onClick={submitPairingCode}
          >
            {busy === 'pairing code' ? 'Pairing…' : 'Pair'}
          </Button>
        </DialogActions>
      </StyledDialog>

      <StyledDialog open={urlDialogOpen} onClose={() => setUrlDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Enter server URL</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            size="small"
            placeholder="https://vpt.example"
            value={serverUrlInput}
            onChange={(e) => setServerUrlInput(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button size="small" onClick={() => setUrlDialogOpen(false)}>
            Cancel
          </Button>
          <Button
            size="small"
            variant="contained"
            disabled={!serverUrlInput.trim() || busy === 'server url'}
            onClick={submitServerUrl}
          >
            {busy === 'server url' ? 'Saving…' : 'Save'}
          </Button>
        </DialogActions>
      </StyledDialog>
    </Box>
  );
}

function StatusRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Box sx={{ display: 'flex', gap: 1 }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 60 }}>
        {label}
      </Typography>
      <Typography variant="body2">{value}</Typography>
    </Box>
  );
}

/**
 * Android has no API for an app to switch its own accessibility service on — unlike screen
 * capture, which gets a real consent dialog — and the per-service deep link
 * (ACTION_ACCESSIBILITY_DETAILS_SETTINGS) is gated behind a privileged permission, so tapping
 * "Fix" can only ever land on the Accessibility list. That list says nothing about which row
 * to touch, which is the actual complaint. Naming the taps here is the most direct thing we
 * are allowed to do.
 */
function AccessibilityHelpDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <StyledDialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Turn on the accessibility service</DialogTitle>
      <DialogContent>
        <Typography variant="body2" sx={{ mb: 1 }}>
          Android only lets you switch this on yourself. In the screen that opens:
        </Typography>
        <List dense disablePadding>
          <ListItem disableGutters>
            <ListItemText primary="1. Tap Installed apps (or Downloaded apps)" />
          </ListItem>
          <ListItem disableGutters>
            <ListItemText primary="2. Tap VirtualPyTest" />
          </ListItem>
          <ListItem disableGutters>
            <ListItemText primary="3. Turn the switch on and confirm" />
          </ListItem>
        </List>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={() => {
            onClose();
            phoneAgent.openAccessibilitySettings();
          }}
        >
          Open settings
        </Button>
      </DialogActions>
    </StyledDialog>
  );
}

function PermissionRow({ ok, label, fix }: { ok: boolean; label: string; fix: () => void | Promise<void> }) {
  return (
    <ListItem disableGutters secondaryAction={!ok ? <Button size="small" onClick={() => fix()}>Fix</Button> : undefined}>
      <ListItemIcon sx={{ minWidth: 32 }}>
        {ok ? <OkIcon fontSize="small" color="success" /> : <WarnIcon fontSize="small" color="warning" />}
      </ListItemIcon>
      <ListItemText primary={label} />
    </ListItem>
  );
}
