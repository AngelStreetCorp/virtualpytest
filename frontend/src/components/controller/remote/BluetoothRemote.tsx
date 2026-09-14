import BluetoothIcon from '@mui/icons-material/Bluetooth';
import BluetoothSearchingIcon from '@mui/icons-material/BluetoothSearching';
import CloseIcon from '@mui/icons-material/Close';
import PowerSettingsNewIcon from '@mui/icons-material/PowerSettingsNew';
import RefreshIcon from '@mui/icons-material/Refresh';
import TerminalIcon from '@mui/icons-material/Terminal';
import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  Tab,
  Tabs,
  Typography,
} from '@mui/material';
import React, { useCallback, useEffect, useRef, useState } from 'react';

import { InfraredRemoteButton } from '../../../config/remote/infraredRemoteBase';
import { ConfirmDialog } from '../../common/ConfirmDialog';
import { StyledDialog } from '../../common/StyledDialog';
import { usePermissionContext } from '../../../contexts/auth/PermissionContext';
import {
  BluetoothLogs,
  useBluetoothRemote,
} from '../../../hooks/controller/useBluetoothRemote';
import { useConfirmDialog } from '../../../hooks/useConfirmDialog';
import { Host } from '../../../types/common/Host_Types';

interface BluetoothRemoteProps {
  host: Host;
  deviceId?: string;
  isConnected?: boolean;
  sx?: any;
  isCollapsed: boolean;
  streamContainerDimensions?: {
    width: number;
    height: number;
    x: number;
    y: number;
  };
  /**
   * Called whenever the BLE dot color should change. RemotePanel uses
   * this to render the dot in its header next to the remote title.
   * Passing `null` would clear the dot; we always pass a color here.
   */
  onStatusChange?: (color: string, tooltip: string) => void;
}

/**
 * BLE HID Remote panel — binary layout:
 *
 *   - FULLY CONNECTED (daemon active + bond + paired + connected):
 *       body = remote image with clickable button overlays
 *   - ANY OTHER STATE:
 *       body = action screen with Start Pairing / Resume / Check Logs
 *
 * Status is shown as a small colored dot in the TOP RIGHT corner of the
 * panel (always visible, hover for full tooltip). No footer. No inline
 * log expander; "Check Logs" opens a modal Dialog over the panel.
 *
 * Green = fully connected, amber = bond exists but disconnected, red =
 * daemon down or no bond, grey = loading.
 */
export const BluetoothRemote = React.memo(
  function BluetoothRemote({
    host,
    deviceId,
    isConnected,
    sx = {},
    isCollapsed,
    streamContainerDimensions,
    onStatusChange,
  }: BluetoothRemoteProps) {
    const {
      session,
      isLoading,
      isPairing,
      isWaking,
      pairPhase,
      pairError,
      layoutConfig,
      status,
      resumeFailed,
      handleConnect,
      handleRemoteCommand,
      startPairing,
      resume,
      coldWake,
      getLogs,
      logsSince,
      clearLogsSince,
    } = useBluetoothRemote(host, deviceId, isConnected);

    const { canAccess } = usePermissionContext();
    const canManagePairing = canAccess('device_control:reboot');

    const {
      dialogState: confirmDialogState,
      confirm: openConfirm,
      handleConfirm: handleConfirmOk,
      handleCancel: handleConfirmCancel,
    } = useConfirmDialog();

    const [showOverlays, setShowOverlays] = useState(true);
    const [logsOpen, setLogsOpen] = useState(false);
    const [logs, setLogs] = useState<BluetoothLogs | null>(null);
    const [logsLoading, setLogsLoading] = useState(false);
    const [logsTab, setLogsTab] = useState(0);
    // User-intent flag: set synchronously the instant the user confirms
    // a re-pair, cleared only once the full success state is visible
    // (fullyConnected) or the hook reports a non-success terminal phase.
    //
    // Forces the "Waiting for STB to pair…" screen immediately, so the
    // body doesn't flash through intermediate status snapshots before
    // pairPhase propagates.
    //
    // Critically, we do NOT clear on pairPhase==='success' alone: a 2s
    // status poll that was in flight when the hook's pair loop finishes
    // can land AFTER the loop's setStatus(success) and stomp it with
    // the transient "connected but !hid_ready" snapshot that happens
    // between the SMP handshake and the STB's HID CCCD subscribe — that
    // snapshot briefly flashes the amber "Remote connected but not
    // responding" state. Waiting for fullyConnected hides it.
    const [pairingIntent, setPairingIntent] = useState(false);

    // Safety net: independent of the hook's pair-poll loop, force-clear
    // pairingIntent 60 s after the user clicked pair. Guards against any
    // missed pairPhase transition (dual-click early-returning the hook,
    // component re-mount wiping the loop, etc.) — without this the
    // "Waiting for STB to pair…" screen could stick forever. Matches the
    // hook's 60 s pair loop ceiling.
    const PAIR_WAIT_MS = 60000;
    useEffect(() => {
      if (!pairingIntent) return undefined;
      const t = window.setTimeout(() => setPairingIntent(false), PAIR_WAIT_MS);
      return () => window.clearTimeout(t);
    }, [pairingIntent]);

    const triggerRepair = useCallback(() => {
      setPairingIntent(true);
      startPairing();
    }, [startPairing]);

    // Countdown during pairing. Matches PAIR_WAIT_MS / the hook's pair loop.
    const [pairRemaining, setPairRemaining] = useState<number>(0);
    const pairStartRef = useRef<number | null>(null);
    useEffect(() => {
      if (pairPhase === 'pairing' || pairingIntent) {
        if (pairStartRef.current === null) {
          pairStartRef.current = Date.now();
          setPairRemaining(60);
        }
        const t = window.setInterval(() => {
          if (pairStartRef.current === null) return;
          const elapsed = (Date.now() - pairStartRef.current) / 1000;
          setPairRemaining(Math.max(0, Math.round(60 - elapsed)));
        }, 250);
        return () => window.clearInterval(t);
      }
      pairStartRef.current = null;
      setPairRemaining(0);
      return undefined;
    }, [pairPhase, pairingIntent]);

    const handleButtonPress = async (buttonKey: string) => {
      if (isLoading || !session.connected) return;
      await handleRemoteCommand(buttonKey);
    };

    // Fetch logs when the modal opens; auto-refresh every 5s while open.
    const refreshLogs = useCallback(async () => {
      setLogsLoading(true);
      try {
        const result = await getLogs(300);
        if (result) setLogs(result);
      } finally {
        setLogsLoading(false);
      }
    }, [getLogs]);

    useEffect(() => {
      if (!logsOpen) return undefined;
      refreshLogs();
      const t = window.setInterval(refreshLogs, 5000);
      return () => window.clearInterval(t);
    }, [logsOpen, refreshLogs]);

    // Responsive remote scale (same as InfraredRemote).
    const calculateRemoteScale = () => {
      const baseHeight = 1800;
      let availableHeight: number;
      if (streamContainerDimensions) {
        availableHeight = streamContainerDimensions.height - 20;
      } else {
        availableHeight = window.innerHeight - 120;
      }
      const baseScale = availableHeight / baseHeight;
      if (isCollapsed) {
        const collapsedHeight = parseInt(layoutConfig.panel_layout.collapsed.height.replace('px', ''), 10);
        const expandedHeight = parseInt(layoutConfig.panel_layout.expanded.height.replace('px', ''), 10);
        const collapsedWidth = parseInt(layoutConfig.panel_layout.collapsed.width.replace('px', ''), 10);
        const expandedWidth = parseInt(layoutConfig.panel_layout.expanded.width.replace('px', ''), 10);
        const headerHeight = layoutConfig.panel_layout.header.height
          ? parseInt(layoutConfig.panel_layout.header.height.replace('px', ''), 10)
          : parseInt(layoutConfig.panel_layout.header.padding.replace('px', ''), 10) * 2 + 20;
        const actualCollapsedHeight = collapsedHeight - headerHeight;
        const actualExpandedHeight = expandedHeight - headerHeight;
        const heightRatio = actualCollapsedHeight / actualExpandedHeight;
        const widthRatio = collapsedWidth / expandedWidth;
        const panelReductionRatio = Math.min(heightRatio, widthRatio);
        return baseScale * panelReductionRatio;
      }
      return baseScale;
    };

    // ---- Derived state -------------------------------------------------
    // Show the remote only when HID is actually working — not just
    // "connected". The battery-only trap (§ 6.7.9) produces connected=true
    // + hid_ready=false, which silently drops every key press.
    const fullyConnected =
      status !== null &&
      status.daemon_active &&
      status.bond_present &&
      status.paired &&
      status.hid_ready;

    // Degraded: the STB is connected and paired but HID didn't subscribe.
    // This is the battery-only trap — keys are silently dropped.
    const degraded =
      status !== null &&
      status.daemon_active &&
      status.bond_present &&
      status.paired &&
      status.connected &&
      !status.hid_ready;

    // The button overlays are absolutely positioned in pixels (position.* ×
    // remoteScale), so remoteScale MUST equal the *actual* rendered scale of
    // the remote image — boxHeight / 1800. calculateRemoteScale() only
    // *predicts* that height from window.innerHeight / stream dims, which
    // diverges from reality whenever the viewport is shorter than the
    // heuristic assumes (e.g. a Windows RDP session whose taskbar eats
    // vertical space), shifting the overlays off the buttons. So we measure
    // the real image box and drive the scale from it; calculateRemoteScale
    // is only a pre-measurement fallback to avoid a first-frame flash.
    const REMOTE_BASE_HEIGHT = 1800;
    const imageBoxRef = useRef<HTMLDivElement | null>(null);
    const [measuredImageHeight, setMeasuredImageHeight] = useState(0);
    useEffect(() => {
      const el = imageBoxRef.current;
      if (!el) return undefined;
      const update = () => {
        const h = el.clientHeight;
        setMeasuredImageHeight(h);
      };
      update();
      const ro = new ResizeObserver(update);
      ro.observe(el);
      return () => ro.disconnect();
    }, [fullyConnected, isCollapsed]);
    const remoteScale =
      measuredImageHeight > 0
        ? measuredImageHeight / REMOTE_BASE_HEIGHT
        : calculateRemoteScale();

    // "Actively pairing" = user clicked pair OR hook is in 60s pair-poll.
    // Plain "adapter advertising, no bond" (e.g. post-timeout state on the
    // daemon) is NOT the same as actively pairing — it's a recoverable
    // state where the user should see Start Pairing / Retry actions.
    const activelyPairing = pairingIntent || pairPhase === 'pairing';
    const isAdvertising = status !== null && status.advertising && !status.bond_present;

    // Clear pairingIntent when the hook's pair loop confirms success AND
    // status has caught up (fullyConnected), or when the pair loop errors
    // out. Do NOT trust fullyConnected alone: at the instant the user
    // clicks re-pair, fullyConnected is still true for the OLD bond —
    // start.sh hasn't had time to wipe it. Clearing on fullyConnected
    // would immediately drop the waiting screen and flip back to the
    // remote image before the re-pair even starts.
    useEffect(() => {
      if (!pairingIntent) return;
      if (pairPhase === 'success' && fullyConnected) {
        setPairingIntent(false);
        return;
      }
      if (pairPhase === 'timeout' || pairPhase === 'failed') {
        setPairingIntent(false);
      }
    }, [pairingIntent, fullyConnected, pairPhase]);

    // Dot color: green=ok, amber=connected-but-broken, blue=pairing,
    // red=down, grey=loading.
    const dotColor: string = (() => {
      if (status === null) return '#888';
      if (activelyPairing) return '#1976d2';  // blue — pairing in progress
      if (!status.daemon_active) return '#d32f2f';
      if (!status.bond_present) return '#d32f2f';
      if (degraded) return '#ed6c02';  // amber — connected but keys won't work
      if (fullyConnected && status.connected) return '#2e7d32';
      return '#d32f2f'; // bonded but STB disconnected
    })();
    const dotTooltip: string =
      status === null
        ? 'BLE status loading…'
        : `adapter=${status.adapter_mac ?? '?'} stb=${status.stb_mac ?? '?'} ` +
          `daemon=${status.daemon_active} bond=${status.bond_present} ` +
          `paired=${status.paired} connected=${status.connected} ` +
          `trusted=${status.trusted} services=${status.services_resolved} ` +
          `hid_ready=${status.hid_ready}`;

    // Publish dot color + tooltip upward to RemotePanel's header whenever
    // either changes. useEffect with primitive deps so we don't thrash on
    // every render.
    useEffect(() => {
      if (onStatusChange) {
        onStatusChange(dotColor, dotTooltip);
      }
    }, [dotColor, dotTooltip, onStatusChange]);

    // ---- Headline for the action screen --------------------------------
    const actionHeadline = (() => {
      if (activelyPairing) return 'Waiting for STB to pair…';
      if (status === null) return 'Loading BLE status…';
      if (!status.bond_present) return 'No Bluetooth pairing found';
      if (!status.daemon_active) return 'BLE daemon is not running';
      if (degraded) return 'Remote connected but not responding';
      if (isWaking) return 'Waking STB…';
      if (resumeFailed && !status.connected)
        return 'Resume didn’t recover the link';
      if (!status.paired || !status.connected) return 'STB disconnected';
      return 'BLE ready';
    })();
    const actionSubtext = (() => {
      // Do not embed the live adapter_mac here. start.sh cycles through
      // power-off / MAC-rotate / power-on, and hciconfig reports
      // 00:00:00:00:00:00 mid-cycle, so the 2s poll would briefly render
      // that in the subtext — visible as a flicker between the headline
      // and the settled pairing state.
      if (activelyPairing)
        return 'Put the STB into "Add new remote" mode. This will take up to 60 seconds.';
      if (!status) return '';
      if (!status.bond_present) {
        const mac = status.adapter_mac && !status.adapter_mac.startsWith('00:00:00')
          ? status.adapter_mac
          : null;
        return (
          "Put the STB into pair-new-remote mode, then click Start Pairing. " +
          (mac ? `We'll run start.sh on the host using adapter ${mac}.` : "We'll run start.sh on the host.")
        );
      }
      if (!status.daemon_active)
        return 'The hid-remote service is down. Click Resume to bring it back up.';
      if (degraded)
        // Battery-only trap (§ 6.7.9). Resume rarely fixes this on Arris
        // STBs because the STB reconnects via cached bond and re-subscribes
        // to Battery only. The reliable path out is to remove the bond on
        // the STB side first, THEN re-pair. We tell the operator both
        // steps explicitly because "Re-pair as last resort" turned out to
        // be misleading guidance — they'd click Re-pair without forgetting
        // on the STB and end up in the same trap.
        return 'STB reconnected but HID subscription is missing. ' +
          'Open the STB remote-settings menu, FORGET this remote, then click Re-pair.';
      if (isWaking)
        return `Sending ADV_DIRECT_IND to ${status.stb_mac ?? 'bonded STB'} — should reconnect within 8 s.`;
      if (resumeFailed && !status.connected)
        return 'The daemon is up but the STB hasn’t reconnected. ' +
          'Power-cycle the STB or click Re-pair to start over.';
      if (!status.paired || !status.connected)
        return 'The STB lost its BLE link. If it is in standby, press Power to wake it. ' +
          'Otherwise click Resume to re-launch the daemon, or wait for auto-reconnect.';
      return '';
    })();

    // ---- Action screen (not fully connected) ---------------------------
    const renderActionScreen = () => {
      // While pairing, suppress all status-derived action buttons so the
      // intermediate states bond.sh walks through (bond wiped → daemon
      // restart → advertising) don't flash Start/Resume/Re-pair in and
      // out behind the pairing spinner. Only the pairing spinner renders.
      const pairingLocked = activelyPairing || isPairing;
      // Show Start Pairing whenever there's no bond and no active pair
      // request — including the post-timeout state where the daemon is
      // still advertising (isAdvertising=true) but the hook has long
      // since stopped polling.
      const showStart =
        !pairingLocked && status !== null && !status.bond_present;
      // Resume is valid in degraded too: resume.sh can recover the
      // missing HID CCCD subscription without wiping the bond.
      const showResume =
        !pairingLocked &&
        status !== null &&
        status.bond_present &&
        !isWaking &&
        (!status.daemon_active || !status.connected || degraded);
      // Re-pair is offered whenever the device has a bond but isn't fully
      // healthy — i.e. ANY case where Resume might not fix things. The
      // previous narrow condition (only `degraded` OR `resumeFailed +
      // disconnected`) locked the operator out of Re-pair in mixed
      // states (e.g. bond loaded + daemon up + connected + hid_ready=false
      // briefly during a reconnect handshake). Always offering Re-pair
      // alongside Resume gives an escape hatch regardless of the exact
      // partial-state combination — and Re-pair plus an STB-side forget
      // is the only reliable fix for the §6.7.9 trap (see degraded
      // subtext above). Pairing in progress still suppresses it.
      const showRepair =
        !pairingLocked &&
        status !== null &&
        status.bond_present &&
        !fullyConnected;
      // POWER on demand: the deep/cold-standby wake path. When the STB is
      // bonded but disconnected we can't tell whether it's asleep, so we
      // always offer a POWER key the user can press to try to wake it. It
      // maps to a normal press_key('POWER') — on the daemon side a key
      // written while no peer is connected triggers the wake advertisement
      // (BLUETOOTH.md §6.7.10). Unlike Resume/Re-pair this is a plain
      // remote key, so it is NOT gated behind canManagePairing. Requires
      // the daemon to be up (FIFO) and excludes the degraded battery-only
      // trap where HID keys are silently dropped.
      const showPower =
        !pairingLocked &&
        status !== null &&
        status.daemon_active &&
        status.bond_present &&
        !status.connected;
      return (
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            px: 3,
            py: 2,
            gap: 2,
            textAlign: 'center',
          }}
        >
          {activelyPairing || isWaking ? (
            <BluetoothSearchingIcon sx={{ fontSize: 56, color: '#1976d2' }} />
          ) : !status ? (
            <CircularProgress size={28} />
          ) : !status.daemon_active ? (
            <BluetoothIcon sx={{ fontSize: 56, color: '#d32f2f' }} />
          ) : degraded ? (
            <BluetoothIcon sx={{ fontSize: 56, color: '#ed6c02' }} />
          ) : (
            <BluetoothSearchingIcon sx={{ fontSize: 56, color: '#888' }} />
          )}

          <Typography variant="subtitle1" sx={{ color: '#eee' }}>
            {actionHeadline}
          </Typography>
          {actionSubtext && (
            <Typography variant="body2" sx={{ color: '#aaa', maxWidth: 340 }}>
              {actionSubtext}
            </Typography>
          )}

          {(pairPhase === 'timeout' || pairPhase === 'failed') && pairError && (
            <Alert severity="error" sx={{ maxWidth: 380, fontSize: '0.8rem' }}>
              {pairError}
            </Alert>
          )}

          <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap', justifyContent: 'center', rowGap: 1.5 }}>
            {activelyPairing && (
              <Stack direction="row" alignItems="center" spacing={1} sx={{ height: 30.75 }}>
                <CircularProgress size={18} />
                <Typography variant="body2" sx={{ color: '#eee' }}>
                  {pairRemaining > 0
                    ? `Pairing… ${pairRemaining}s remaining`
                    : 'Waiting for STB…'}
                </Typography>
              </Stack>
            )}
            {isWaking && !isPairing && !isAdvertising && (
              <Stack direction="row" alignItems="center" spacing={1} sx={{ height: 30.75 }}>
                <CircularProgress size={18} />
                <Typography variant="body2" sx={{ color: '#eee' }}>
                  Waking STB…
                </Typography>
              </Stack>
            )}
            {showStart && canManagePairing && (
              <Button
                variant="contained"
                color="primary"
                size="small"
                startIcon={<BluetoothIcon />}
                onClick={triggerRepair}
                disabled={isPairing}
              >
                {pairPhase === 'timeout' || pairPhase === 'failed' ? 'Retry Pairing' : 'Start Pairing'}
              </Button>
            )}
            {showResume && canManagePairing && (
              <Button
                variant="contained"
                color="warning"
                size="small"
                startIcon={isLoading ? <CircularProgress size={14} color="inherit" /> : <RefreshIcon />}
                onClick={resume}
                disabled={isLoading}
              >
                {isLoading ? 'Resuming…' : 'Resume'}
              </Button>
            )}
            {showRepair && canManagePairing && (
              <Button
                variant="contained"
                color="warning"
                size="small"
                startIcon={isPairing ? <CircularProgress size={14} color="inherit" /> : <BluetoothIcon />}
                onClick={triggerRepair}
                disabled={isPairing}
              >
                {isPairing ? 'Re-pairing…' : 'Re-pair'}
              </Button>
            )}
            {showPower && (
              <Button
                variant="contained"
                color="error"
                size="small"
                startIcon={
                  isWaking ? <CircularProgress size={14} color="inherit" /> : <PowerSettingsNewIcon />
                }
                onClick={coldWake}
                disabled={isWaking}
                title="Press POWER to wake the STB from deep standby (Broadcom WoBLE)"
              >
                {isWaking ? 'Waking…' : 'Power'}
              </Button>
            )}
            <Button
              variant="outlined"
              color="inherit"
              size="small"
              startIcon={<TerminalIcon />}
              onClick={() => setLogsOpen(true)}
            >
              Check Logs
            </Button>
          </Stack>

          {!canManagePairing && (showStart || showResume || showRepair) && (
            <Typography variant="caption" sx={{ color: '#888' }}>
              Only an administrator can pair or resume the BLE remote.
            </Typography>
          )}
        </Box>
      );
    };

    // ---- Remote image (fully connected) --------------------------------
    const renderRemoteImage = () => (
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100%',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        {!isCollapsed && (
          <IconButton
            size="small"
            onClick={() => setShowOverlays(!showOverlays)}
            title={showOverlays ? 'Hide button overlays' : 'Show button overlays'}
            sx={{
              position: 'absolute',
              top: 8,
              right: 8,
              zIndex: 10,
              color: 'rgba(255, 255, 255, 0.7)',
              backgroundColor: 'rgba(0, 0, 0, 0.4)',
              p: 0.5,
              '&:hover': {
                backgroundColor: 'rgba(0, 0, 0, 0.6)',
                color: '#fff',
              },
            }}
          >
            {showOverlays ? (
              <VisibilityIcon sx={{ fontSize: 18 }} />
            ) : (
              <VisibilityOffIcon sx={{ fontSize: 18 }} />
            )}
          </IconButton>
        )}
        {!isCollapsed && canManagePairing && (
          <IconButton
            size="small"
            onClick={() => {
              const currentMac = status?.stb_mac ?? 'unknown';
              openConfirm({
                title: 'Re-pair BLE remote?',
                // Two-step instruction: forget on STB first, THEN re-pair.
                // Skipping the STB-side forget is the #1 cause of the
                // pair-completes-but-keys-don't-work failure (§ 6.7.9
                // battery-only trap). Spelling it out here too.
                message:
                  `This will WIPE the current bond (${currentMac}) on our side.\n\n` +
                  `Before continuing:\n` +
                  `  1. Open the STB remote-settings menu and FORGET this remote.\n` +
                  `  2. Put the STB into "Add new remote" mode.\n` +
                  `  3. Confirm — re-pairing without step 1 usually leaves the STB ` +
                  `subscribed to Battery only and keys won't reach it.`,
                confirmText: 'Re-pair',
                confirmColor: 'warning',
                onConfirm: triggerRepair,
              });
            }}
            disabled={isPairing || pairingIntent}
            title={
              isPairing || pairingIntent
                ? 'Re-pairing in progress…'
                : 'Re-pair — wipes the current bond and runs start.sh'
            }
            sx={{
              position: 'absolute',
              top: 8,
              left: 8,
              zIndex: 10,
              backgroundColor: 'rgba(25, 118, 210, 0.85)',
              color: '#fff',
              p: 0.5,
              '&:hover': { backgroundColor: 'rgba(25, 118, 210, 1)' },
              '&.Mui-disabled': { backgroundColor: 'rgba(25, 118, 210, 0.35)', color: '#fff' },
            }}
          >
            {isPairing || pairingIntent ? (
              <CircularProgress size={16} color="inherit" />
            ) : (
              <BluetoothSearchingIcon sx={{ fontSize: 18 }} />
            )}
          </IconButton>
        )}
        <Box
          ref={imageBoxRef}
          sx={{
            position: 'relative',
            width: 'auto',
            height: '100%',
            aspectRatio: '640/1800',
            backgroundImage: `url(${layoutConfig.remote_info.image_url})`,
            backgroundSize: 'contain',
            backgroundRepeat: 'no-repeat',
            backgroundPosition: 'center',
          }}
        >
          {Object.entries(
            streamContainerDimensions
              ? layoutConfig.button_layout_recmodal
              : layoutConfig.button_layout,
          ).map(([buttonId, button]) => {
            const typedButton = button as unknown as InfraredRemoteButton;
            return (
              <Box
                key={buttonId}
                sx={{
                  position: 'absolute',
                  left: `${(typedButton.position.x + layoutConfig.remote_info.global_offset.x) * remoteScale + (isCollapsed ? 1 : 0)}px`,
                  top: `${(typedButton.position.y + layoutConfig.remote_info.global_offset.y) * remoteScale + (isCollapsed ? 1 : 0)}px`,
                  width: `${typedButton.size.width * layoutConfig.remote_info.button_scale_factor * remoteScale}px`,
                  height: `${typedButton.size.height * layoutConfig.remote_info.button_scale_factor * remoteScale}px`,
                  borderRadius: typedButton.shape === 'circle' ? '50%' : '4px',
                  backgroundColor: (() => {
                    if (isCollapsed) return 'rgba(255, 255, 255, 0.1)';
                    if (showOverlays) return 'rgba(255, 255, 255, 0.1)';
                    return 'rgba(255, 255, 255, 0.02)';
                  })(),
                  border: (() => {
                    if (isCollapsed) return '1px solid rgba(255, 255, 255, 0.5)';
                    if (showOverlays) return '1px solid rgba(255, 255, 255, 0.3)';
                    return '1px solid rgba(255, 255, 255, 0.06)';
                  })(),
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s ease-in-out',
                  '&:hover': {
                    backgroundColor: 'rgba(255, 255, 255, 0.2)',
                    transform: 'scale(1.05)',
                  },
                  '&:active': {
                    backgroundColor: 'rgba(255, 255, 255, 0.3)',
                    transform: 'scale(0.95)',
                  },
                }}
                onClick={() => handleButtonPress(typedButton.key)}
                title={`${typedButton.label} - ${typedButton.comment}`}
              >
                <Typography
                  variant="caption"
                  sx={{
                    fontSize: `${parseInt(layoutConfig.remote_info.text_style.fontSize) * remoteScale}px`,
                    fontWeight: layoutConfig.remote_info.text_style.fontWeight,
                    color: layoutConfig.remote_info.text_style.color,
                    textShadow: layoutConfig.remote_info.text_style.textShadow,
                    userSelect: 'none',
                  }}
                >
                  {typedButton.label}
                </Typography>
              </Box>
            );
          })}
        </Box>
      </Box>
    );

    // ---- Top-level body dispatch ---------------------------------------
    const renderBody = () => {
      if (!session.connected) {
        return (
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              p: 2,
            }}
          >
            <Box sx={{ textAlign: 'center' }}>
              {session.connecting ? (
                <>
                  <CircularProgress size={24} sx={{ mb: 1 }} />
                  <Typography variant="body2">Connecting…</Typography>
                </>
              ) : (
                <>
                  <Typography variant="body2" color="textSecondary">
                    {session.error || 'BLE Remote'}
                  </Typography>
                  <Button variant="outlined" size="small" onClick={handleConnect} sx={{ mt: 1 }}>
                    Connect
                  </Button>
                </>
              )}
            </Box>
          </Box>
        );
      }
      // Lock to action screen the instant the user confirms a re-pair
      // (pairingIntent) and stay there through the whole pair operation.
      // pairingIntent is set synchronously in triggerRepair so no
      // intermediate render can flash the remote image or Start/Resume
      // buttons between click and the hook's pairPhase transitioning.
      // isPairing is included as a backstop: the 60s safety timeout can
      // clear pairingIntent while the hook's pair loop is still running —
      // without `|| isPairing` the old bond's fullyConnected snapshot would
      // briefly re-show the remote (with a live Re-pair button) mid-pair.
      if (pairingIntent || isPairing || pairPhase === 'pairing') return renderActionScreen();
      if (fullyConnected) return renderRemoteImage();
      return renderActionScreen();
    };

    // ---- Logs modal ----------------------------------------------------
    // Unit names are PER-ADAPTER now (multi-instance: hid-remote-hci1.service,
    // hid-remote-hci2.service, vpt-ble-remote@hci1.service, ...). We don't
    // hardcode them — discover them from the `logs` response (every key
    // except `pairing_status` is a unit name). We sort to a stable display
    // order regardless of dict iteration order: hid-remote, hid-agent, ble-remote.
    const LOG_UNITS = React.useMemo<string[]>(() => {
      const keys = logs
        ? Object.keys(logs).filter((k) => k !== 'pairing_status')
        : [];
      const order = (name: string): number =>
        name.startsWith('hid-remote') ? 0 :
        name.startsWith('hid-agent') ? 1 :
        name.startsWith('vpt-ble-remote') ? 2 : 3;
      return keys.sort((a, b) => order(a) - order(b));
    }, [logs]);

    // Short display label = unit name minus `.service` suffix and the
    // `-hciN` / `@hciN` adapter suffix. So `hid-remote-hci1.service`
    // becomes `hid-remote`; `vpt-ble-remote@hci2.service` becomes
    // `vpt-ble-remote`. Operators don't need the adapter suffix repeated
    // in every tab — they already know which device this panel belongs
    // to from the parent RemotePanel header.
    const LOG_LABELS = React.useMemo<string[]>(
      () => LOG_UNITS.map((u) =>
        u.replace(/\.service$/, '').replace(/[@-]hci\d+$/, '')
      ),
      [LOG_UNITS],
    );

    // Clamp logsTab if LOG_UNITS shrinks (e.g. one of the three units
    // is missing from the response — happens transiently during start.sh
    // before the systemd-run for that unit lands). Without this, the
    // selected tab can index past the array and MUI Tabs throws a
    // warning about an out-of-range value.
    useEffect(() => {
      if (LOG_UNITS.length > 0 && logsTab >= LOG_UNITS.length) {
        setLogsTab(LOG_UNITS.length - 1);
      }
    }, [LOG_UNITS, logsTab]);

    const renderLogsDialog = () => (
      <StyledDialog
        open={logsOpen}
        onClose={() => setLogsOpen(false)}
        maxWidth="lg"
        fullWidth
        PaperProps={{ sx: { bgcolor: '#111', color: '#ddd' } }}
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', py: 1 }}>
          <Stack direction="row" alignItems="center" spacing={1}>
            <TerminalIcon fontSize="small" />
            <Typography variant="subtitle1">BLE debug logs</Typography>
            {logsSince && (
              <Typography variant="caption" sx={{ color: '#6a6' }}>
                since {new Date(logsSince).toLocaleTimeString()}
              </Typography>
            )}
            <Typography variant="caption" sx={{ color: '#888' }}>
              (auto-refresh 5s)
            </Typography>
          </Stack>
          <Stack direction="row" alignItems="center" spacing={0.5}>
            {logsSince && (
              <Button size="small" onClick={clearLogsSince} sx={{ color: '#aaa', fontSize: '0.65rem', minWidth: 0 }}>
                Show all
              </Button>
            )}
            <IconButton size="small" onClick={refreshLogs} disabled={logsLoading} sx={{ color: '#aaa' }}>
              {logsLoading ? <CircularProgress size={14} color="inherit" /> : <RefreshIcon fontSize="small" />}
            </IconButton>
            <IconButton size="small" onClick={() => setLogsOpen(false)} sx={{ color: '#aaa' }}>
              <CloseIcon fontSize="small" />
            </IconButton>
          </Stack>
        </DialogTitle>
        <Tabs
          value={logsTab}
          onChange={(_, v) => setLogsTab(v)}
          sx={{
            minHeight: 28,
            px: 2,
            '& .MuiTab-root': { minHeight: 28, py: 0.5, fontSize: '0.7rem', color: '#999' },
            '& .Mui-selected': { color: '#7aa !important' },
            '& .MuiTabs-indicator': { backgroundColor: '#7aa' },
          }}
        >
          {LOG_LABELS.map((label) => (
            <Tab key={label} label={label} />
          ))}
        </Tabs>
        <DialogContent
          sx={{
            fontFamily: 'monospace',
            fontSize: '0.7rem',
            py: 1,
            height: '60vh',
            overflow: 'hidden',
          }}
        >
          <Box sx={{ height: '100%', overflowY: 'auto' }}>
            {logs ? (
              <pre
                style={{
                  margin: 0,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                  fontSize: '0.7rem',
                  lineHeight: 1.25,
                  color: '#ddd',
                }}
              >
                {(() => {
                  const value = logs[LOG_UNITS[logsTab]];
                  // BluetoothLogs is keyed-by-string with mixed value
                  // types (string | BluetoothPairingStatus), but LOG_UNITS
                  // excludes 'pairing_status', so the value here is always
                  // a string in practice. Cast to satisfy the union check.
                  return typeof value === 'string' ? value : '(empty)';
                })()}
              </pre>
            ) : (
              <Typography variant="caption" sx={{ color: '#888' }}>
                Loading logs…
              </Typography>
            )}
          </Box>
        </DialogContent>
      </StyledDialog>
    );

    return (
      <Box
        sx={{
          ...sx,
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        {/* The BLE status dot lives in RemotePanel's header (next to the
             BLUETOOTH title), published via onStatusChange. Not rendered
             here — keeps the body clean. */}
        <Box sx={{ flex: 1, overflow: 'hidden', minHeight: 0 }}>{renderBody()}</Box>
        {renderLogsDialog()}
        <ConfirmDialog
          open={confirmDialogState.open}
          title={confirmDialogState.title}
          message={confirmDialogState.message}
          confirmText={confirmDialogState.confirmText}
          cancelText={confirmDialogState.cancelText}
          confirmColor={confirmDialogState.confirmColor}
          onConfirm={handleConfirmOk}
          onCancel={handleConfirmCancel}
        />
      </Box>
    );
  },
  (prevProps, nextProps) => {
    return (
      prevProps.host?.host_name === nextProps.host?.host_name &&
      prevProps.deviceId === nextProps.deviceId &&
      prevProps.isConnected === nextProps.isConnected &&
      JSON.stringify(prevProps.sx) === JSON.stringify(nextProps.sx) &&
      prevProps.isCollapsed === nextProps.isCollapsed &&
      JSON.stringify(prevProps.streamContainerDimensions) ===
        JSON.stringify(nextProps.streamContainerDimensions)
    );
  },
);
