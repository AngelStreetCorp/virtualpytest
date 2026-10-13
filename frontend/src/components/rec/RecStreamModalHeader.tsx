import {
  Close as CloseIcon,
  Tv as TvIcon,
  Language as WebIcon,
  VolumeOff as VolumeOffIcon,
  VolumeUp as VolumeUpIcon,
  Refresh as RefreshIcon,
  RadioButtonChecked as LiveIcon,
  History as ArchiveIcon,
  Visibility as VisibilityIcon,
  VisibilityOff as VisibilityOffIcon,
  Lock as LockIcon,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';

import { AIIcon, CameraIcon, FullscreenIcon } from '../common/icons/CustomIcons';
import { featureDeviceLinks } from '../../config/features';
import { useResponsiveMode } from '../../hooks/useResponsiveMode';
import { Box, IconButton, Typography, Button, CircularProgress, ToggleButtonGroup, ToggleButton, Tooltip } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';

import { Host, Device } from '../../types/common/Host_Types';
import LocalizeButton from '../navigation/Navigation_LocalizeButton';
import { PowerButton } from '../controller/power/PowerButton';

import type { LiveStreamTransport } from '../../types/controller/WebRTC_Types';
import { StreamQualityControl } from './StreamQualityControl';


// Hide the Restart button for the time being — the restart mode UX is being
// reworked and the button has been the source of confusion in the toolbar
// (one more "fixed-width" 144px slot that pushes Control off-screen on narrow
// layouts). Flip this back to `true` to bring it back; the rest of the wiring
// (Restart Mode Toggle Button in the Live/Archive group, onToggleRestart
// prop, restartMode state, useRecModalModes) is unchanged.
const SHOW_RESTART_BUTTON = false;


interface RecStreamModalHeaderProps {
  host: Host;
  device?: Device;

  // Lock label for manual control (mirrors RecHostPreview)
  manualControlLabel?: string | null;
  // Who holds the device: the manual owner, or whoever launched the running script.
  lockOwnerLabel?: string | null;
  // Whether a script/deployment lock is currently active (derived from the live lock
  // state, not device.has_running_deployment — that flag lingers after completion).
  scriptLockActive?: boolean;
  // Optional script/deployment name for the lock tooltip.
  scriptLockLabel?: string | null;
  // Start-time + duration for the lock tooltip (helps spot stale locks)
  lockTiming?: { startedAt: string; duration: string } | null;

  // State
  monitoringMode: boolean;
  restartMode: boolean;
  isLiveMode: boolean;
  currentQuality: 'low' | 'sd' | 'hd' | 'hd_plus';
  streamTransport: LiveStreamTransport;
  isMuted: boolean;
  isControlActive: boolean;
  isControlLoading: boolean;
  aiAgentMode: boolean;
  showWeb: boolean;
  isDesktopDevice: boolean;
  hasPowerControl: boolean;
  // When true, hide the "power user" controls (localize, fullscreen, AI query,
  // live/archive toggle, take control, restart, AI agent) and keep only the
  // basic viewing controls. Used for the mobile device-control page, where
  // the full toolbar doesn't fit a 375px-wide screen. Defaults to false so
  // every other caller (desktop pages reusing this header) is unaffected.
  minimalControls?: boolean;

  // Handlers
  onScreenshot: () => void;
  onOpenFullscreen?: () => void;
  onAIImageQuery?: () => void;
  onToggleLiveMode: () => void;
  onQualityChange: (event: React.MouseEvent<HTMLElement>, newQuality: 'low' | 'sd' | 'hd' | 'hd_plus' | null) => void;
  onToggleStreamTransport: () => void;
  onToggleMute: () => void;
  onToggleControl: () => void;
  onToggleMonitoring: () => void;
  onToggleRestart: () => void;
  onToggleAiAgent: () => void;
  onToggleWeb: () => void;
  // Show/Hide Remote was removed from the toolbar — the panel auto-shows when
  // control is taken and auto-hides when control is released (see
  // useRecModalModes). The `showRemote` state still flows to RecStreamContainer
  // and RecPanelManager; only the toolbar toggle is gone.
  onClose: () => void;
}

export const RecStreamModalHeader: React.FC<RecStreamModalHeaderProps> = ({
  host,
  device,
  manualControlLabel,
  lockOwnerLabel,
  scriptLockActive,
  scriptLockLabel,
  lockTiming,
  monitoringMode,
  restartMode,
  isLiveMode,
  currentQuality,
  streamTransport,
  isMuted,
  isControlActive,
  isControlLoading,
  aiAgentMode,
  showWeb,
  isDesktopDevice,
  hasPowerControl,
  minimalControls = false,
  onScreenshot,
  onOpenFullscreen,
  onAIImageQuery,
  onToggleLiveMode,
  onQualityChange,
  onToggleStreamTransport,
  onToggleMute,
  onToggleControl,
  onToggleMonitoring,
  onToggleRestart,
  onToggleAiAgent,
  onToggleWeb,
  onClose,
}) => {
  const navigate = useNavigate();
  const { isMobile } = useResponsiveMode();
  // host_vnc now has audio too: live via the hidden HLS companion behind the noVNC
  // iframe, archive via the HLS player. So audio is available for all device types.
  const isAudioSupported = true;
  const isArchiveMode = !isLiveMode;
  // ARCHIVE_VIDEO=false on the host: no 24h review buffer to play back.
  const hasReviewBuffer = host.system_stats?.archive_video !== false;
  const P = useAgentChatPalette();

  // Lock indicator — mirror RecHostPreview: show for manual control OR a running
  // script/deployment, with matching colors (manual = info, script = warning).
  const hasManualControl = Boolean(manualControlLabel);
  const hasDeployment = Boolean(scriptLockActive);
  const ownerLabel = lockOwnerLabel || manualControlLabel;
  const showLock = hasManualControl || hasDeployment || Boolean(ownerLabel);

  // Status dot colour — mirrors the logic in DeviceStatusChip: stuck host
  // services outrank both the running script and host.status, so a stuck host
  // shows red even when the host itself is still flagged 'online'.
  const stuckServices = (host.system_stats?.service_health?.services ?? []).filter(
    (s) => s.status === 'stuck',
  );
  const hostStuck = stuckServices.length > 0;
  const stuckServiceNames = stuckServices.map((s) => s.label || s.name).join(', ');

  return (
    <Box
      sx={{
        px: 2,
        py: 1,
        backgroundColor: P.surface,
        color: P.textPrimary,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderRadius: '8px 8px 0 0',
        minHeight: 48,
      }}
    >
      <Typography 
        variant="h6" 
        component="h2" 
        sx={{ 
          display: 'flex', 
          alignItems: 'center', 
          gap: 0.75,
          fontSize: '1rem', // Reduced from h6 default (1.25rem) to ensure single line
          whiteSpace: 'nowrap', // Prevent wrapping
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          // Reserved space for the device name: a long name should ellipsize inside
          // this fixed-width slot instead of pushing the whole toolbar around.
          // 168px fits ~15 characters at 1rem (e.g. "device_vendor_42"), which
          // covers the typical name lengths we see; longer names truncate.
          width: 168,
          flexShrink: 0,
        }}
      >
        <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {(device?.device_name || host.host_name).replace(/_Host$/, '')}
        </Box>
        {showLock && (
          <Tooltip
            arrow
            placement="bottom"
            title={
              <Box sx={{ py: 0.25 }}>
                {ownerLabel && (
                  <Typography variant="caption" sx={{ display: 'block', fontWeight: 'bold' }}>
                    {hasManualControl ? `Controlled by: ${ownerLabel}` : `Run by: ${ownerLabel}`}
                  </Typography>
                )}
                {hasDeployment && (
                  <Typography variant="caption" sx={{ display: 'block', fontWeight: 'bold' }}>
                    {scriptLockLabel ? `Script: ${scriptLockLabel}` : 'Script running'}
                  </Typography>
                )}
                {lockTiming && (
                  <>
                    <Typography variant="caption" sx={{ display: 'block' }}>
                      Started: {lockTiming.startedAt}
                    </Typography>
                    <Typography variant="caption" sx={{ display: 'block' }}>
                      Duration: {lockTiming.duration}
                    </Typography>
                  </>
                )}
              </Box>
            }
          >
            <LockIcon
              sx={{
                fontSize: '1rem',
                color: hasManualControl ? P.accentText : P.warning,
                flexShrink: 0
              }}
            />
          </Tooltip>
        )}
        {/* Status dot — replaces the verbose "online" / "running" / "error" chip in the
            toolbar. Same colour logic as DeviceStatusChip: green when the host is online,
            red when offline or any service is stuck, blue while a script drives the device.
            Tooltip carries the full state text on hover. */}
        <Tooltip
          arrow
          placement="bottom"
          title={
            <Box sx={{ py: 0.25 }}>
              <Typography variant="caption" sx={{ display: 'block', fontWeight: 'bold' }}>
                {hostStuck
                  ? 'Error — host services stuck'
                  : hasDeployment
                    ? `Running — ${scriptLockLabel || 'script in progress'}`
                    : host.status === 'online'
                      ? 'Online'
                      : host.status === 'offline'
                        ? 'Offline'
                        : `Status: ${host.status}`}
              </Typography>
              {stuckServiceNames && (
                <Typography variant="caption" sx={{ display: 'block' }}>
                  Stuck services: {stuckServiceNames}
                </Typography>
              )}
            </Box>
          }
        >
          <Box
            aria-label="Device status"
            sx={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              flexShrink: 0,
              backgroundColor: hostStuck
                ? P.error // red when any host service is stuck
                : hasDeployment
                  ? '#3a8cff' // blue while a script drives the device
                  : host.status === 'online'
                    ? '#2ecc71' // green when the host is up
                    : P.error, // red when offline / unknown
              boxShadow: '0 0 0 2px rgba(255, 255, 255, 0.06)',
            }}
          />
        </Tooltip>
      </Typography>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: '1 1 auto', justifyContent: 'flex-end', flexWrap: 'nowrap', overflowX: 'auto' }}>
        {/* Screenshot Button - disabled in archive/restart mode.
            Icon reduced from MUI default (24px) to 18px so the screenshotter
            (capture) + localize cluster doesn't visually outweigh the other
            icon buttons in the toolbar. */}
        {!restartMode && (
          <IconButton
            size="large"
            onClick={onScreenshot}
            disabled={isArchiveMode}
            sx={{
              color: isArchiveMode ? P.textMuted : P.textSecondary,
              '&:hover': { color: isArchiveMode ? P.textMuted : P.textPrimary },
              '&.Mui-disabled': {
                color: P.textMuted,
              },
              '& .MuiSvgIcon-root': { fontSize: '1.125rem' }, // 18px — lighter than the default 24px
              p: 0.75,
            }}
            aria-label="Take Screenshot"
            title={isArchiveMode ? "Screenshot only available in Live mode" : "Take Screenshot (opens in new tab)"}
          >
            <CameraIcon />
          </IconButton>
        )}

        {/* Localize Button - identify which navigation node the live screen is.
            Uses the device's preferred userinterface/variant; only shown when one
            is configured (otherwise there's no tree to match against).
            Icon reduced to 18px to match the neighbouring Screenshot (capture)
            button — they read as one visual cluster. */}
        {!minimalControls && !restartMode && device?.preferred_userinterface && (
          <LocalizeButton
            hostName={host.host_name}
            deviceId={device.device_id}
            userinterfaceName={device.preferred_userinterface}
            variant={device.preferred_variant ?? null}
            disabled={!isLiveMode}
            disabledTitle="Localize only available in Live mode"
            width={280}
            expandedWidth={380}
            sx={{
              color: isLiveMode ? P.textSecondary : P.textMuted,
              '&:hover': { color: isLiveMode ? P.textPrimary : P.textMuted },
              '&.Mui-disabled': { color: P.textMuted },
              '& .MuiSvgIcon-root': { fontSize: '1.125rem' }, // 18px — overrides LocalizeButton's default 24px
              p: 0.75,
            }}
          />
        )}

        {/* Optional-feature per-device pages (docs/technical/FEATURES.md) */}
        {!minimalControls &&
          device &&
          featureDeviceLinks().map((link) => (
            <IconButton
              key={link.label}
              size="large"
              onClick={() => {
                // replace: takes the modal's Back-to-close history entry, so Back from the
                // feature page returns to the page the modal was opened from.
                navigate(link.path(host.host_name, device.device_id), { replace: true });
                onClose();
              }}
              sx={{ color: P.textSecondary, '&:hover': { color: P.textPrimary } }}
              aria-label={link.label}
              title={link.label}
            >
              {link.icon}
            </IconButton>
          ))}

        {/* Fullscreen Player Button - opens a dedicated quality-focused player in a new tab.
            Disabled in archive/restart mode (live stream only). */}
        {!minimalControls && !restartMode && onOpenFullscreen && (
          <IconButton
            size="large"
            onClick={onOpenFullscreen}
            disabled={!isLiveMode}
            sx={{
              color: isLiveMode ? P.textSecondary : P.textMuted,
              '&:hover': { color: isLiveMode ? P.textPrimary : P.textMuted },
              '&.Mui-disabled': { color: P.textMuted },
            }}
            aria-label="Open fullscreen player"
            title={
              isLiveMode
                ? 'Open fullscreen player in new tab (best quality, buffered)'
                : 'Fullscreen player only available in Live mode'
            }
          >
            <FullscreenIcon fontSize="medium" />
          </IconButton>
        )}

        {/* AI Image Query Button - disabled in archive/restart mode */}
        {!minimalControls && !restartMode && onAIImageQuery && (
          <IconButton
            size="large"
            onClick={onAIImageQuery}
            disabled={!isLiveMode}
            sx={{
              color: isLiveMode ? P.accentText : P.textMuted,
              '&:hover': { color: isLiveMode ? P.accentText : P.textMuted },
              '&.Mui-disabled': {
                color: P.textMuted,
              }
            }}
            aria-label="Ask AI about frame"
            title={isLiveMode ? "Ask AI about current frame" : "AI Query only available in Live mode"}
          >
            <AIIcon fontSize="medium" />
          </IconButton>
        )}

        {/* Live/Archive Mode Toggle Button Group */}
        {!minimalControls && !restartMode && (
          <ToggleButtonGroup
            value={isLiveMode ? 'live' : 'restart'}
            exclusive
            onChange={(_event: React.MouseEvent<HTMLElement>, newMode: 'live' | 'restart' | null) => {
              if (newMode && newMode !== (isLiveMode ? 'live' : 'restart')) {
                onToggleLiveMode();
              }
            }}
            aria-label="Mode selection"
            sx={{
              '& .MuiToggleButton-root': {
                fontSize: '0.8125rem',
                fontWeight: 500,
                minWidth: 68,
                height: 40,
                px: 1.5,
                textTransform: 'none',
                border: '1px solid rgba(255, 255, 255, 0.12)',
                '&.Mui-selected': {
                  backgroundColor: isLiveMode ? P.error : P.accent,
                  color: 'white',
                },
              },
            }}
          >
            <ToggleButton value="live" aria-label="Live mode">
              <LiveIcon sx={{ fontSize: 18, mr: 0.5 }} />
              Live
            </ToggleButton>
            <ToggleButton
              value="restart"
              aria-label="Restart mode"
              disabled={isControlActive || !hasReviewBuffer}
              title={
                !hasReviewBuffer
                  ? "24h review buffer is off on this host (ARCHIVE_VIDEO=false)"
                  : isControlActive ? "Release control to switch to Last 24h mode" : "Last 24h Archive Mode"
              }
            >
              <ArchiveIcon sx={{ fontSize: 18, mr: 0.5 }} />
              Last 24h
            </ToggleButton>
          </ToggleButtonGroup>
        )}

        {!restartMode && !isDesktopDevice && (
          <StreamQualityControl
            quality={currentQuality}
            transport={streamTransport}
            disabled={!isLiveMode}
            compact={minimalControls}
            supportsHdPlus={Boolean(host.system_stats?.hardware_encode)}
            onQualityChange={onQualityChange}
            onToggleTransport={onToggleStreamTransport}
          />
        )}

        {/* Volume Toggle Button — intentionally placed BEFORE Monitoring so the
            toolbar reads Live/Archive → Quality → Mute → Monitoring → Control.
            Visually smaller than the other icon-only buttons (capture, localize,
            fullscreen, AI) so the audio toggle doesn't dominate the toolbar. */}
        {!restartMode && (
          <IconButton
            onClick={onToggleMute}
            disabled={!isAudioSupported}
            sx={{
              color: isAudioSupported ? P.textSecondary : P.textMuted,
              '&:hover': { color: isAudioSupported ? P.textPrimary : P.textMuted },
              '&.Mui-disabled': { color: P.textMuted },
              '& .MuiSvgIcon-root': { fontSize: '1rem' }, // 16px — smaller than the 18px capture/localize icons
              p: 0.5,
            }}
            aria-label={isMuted ? 'Unmute' : 'Mute'}
            title={
              !isAudioSupported
                ? 'Audio not available for host_vnc'
                : isMuted
                  ? 'Unmute Audio'
                  : 'Mute Audio'
            }
          >
            {isMuted ? <VolumeOffIcon /> : <VolumeUpIcon />}
          </IconButton>
        )}

        {/* Monitoring Toggle - icon-only on mobile, no room for the "Monitoring" label */}
        {!restartMode && minimalControls && (
          <IconButton
            size="large"
            onClick={onToggleMonitoring}
            disabled={!isLiveMode}
            sx={{
              color: monitoringMode ? P.accentText : P.textSecondary,
              opacity: !isLiveMode ? 0.5 : 1,
            }}
            aria-label={monitoringMode ? 'Hide Monitoring Overlay' : 'Show Monitoring Overlay'}
            title={
              !isLiveMode
                ? 'Monitoring only available in Live mode'
                : monitoringMode
                  ? 'Hide Monitoring Overlay'
                  : 'Show Monitoring Overlay (Freeze, Blackscreen, Audio, Subtitles, AI)'
            }
          >
            {monitoringMode ? <VisibilityIcon fontSize="large" /> : <VisibilityOffIcon fontSize="large" />}
          </IconButton>
        )}
        {!restartMode && !minimalControls && (
          <Button
            variant={monitoringMode ? 'contained' : 'outlined'}
            onClick={onToggleMonitoring}
            disabled={!isLiveMode}
            startIcon={monitoringMode ? <VisibilityIcon /> : <VisibilityOffIcon />}
            color={monitoringMode ? 'primary' : 'inherit'}
            sx={{
              fontSize: '0.8125rem',
              fontWeight: 500,
              minWidth: 132,
              height: 40,
              px: 1.5,
              textTransform: 'none',
              color: monitoringMode ? 'white' : 'inherit',
              opacity: !isLiveMode ? 0.5 : 1,
            }}
            title={
              !isLiveMode
                ? 'Monitoring only available in Live mode'
                : monitoringMode
                  ? 'Hide Monitoring Overlay'
                  : 'Show Monitoring Overlay (Freeze, Blackscreen, Audio, Subtitles, AI)'
            }
          >
            Monitoring
          </Button>
        )}

        {/* Control Button — fixed width and a fixed-width icon slot so swapping
            TvIcon <-> CircularProgress + Control <-> Release <-> Processing doesn't
            reflow the button (the old minWidth+startIcon combo would jump ~10-20px
            on every state change, which read as a flash in the toolbar). */}
        {!minimalControls && (
          <Button
            variant={isControlActive ? 'contained' : 'outlined'}
            onClick={onToggleControl}
            disabled={isControlLoading || !isLiveMode}
            startIcon={
              // 24px slot — TvIcon renders at 24px (default), CircularProgress at 16px
              // needs the same slot width so the text doesn't shift. Both children sit
              // in the same box, the inactive one is hidden via display.
              <Box
                component="span"
                sx={{
                  width: 24,
                  height: 24,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  mr: '-4px', // MUI adds 8px margin to startIcon — pull the text 4px closer so "Processing..." fits inside the fixed 144px width
                }}
              >
                <Box
                  component="span"
                  sx={{ display: isControlLoading ? 'none' : 'inline-flex' }}
                >
                  <TvIcon sx={{ fontSize: 20 }} />
                </Box>
                <Box
                  component="span"
                  sx={{ display: isControlLoading ? 'inline-flex' : 'none' }}
                >
                  <CircularProgress size={18} thickness={5} />
                </Box>
              </Box>
            }
            color={isControlActive ? 'success' : 'primary'}
            sx={{
              fontSize: '0.8125rem',
              fontWeight: 500,
              width: 144, // fixed — covers "Processing..." (12ch) + 24px icon + 24px padding
              height: 40,
              px: 1.25,
              textTransform: 'none',
              whiteSpace: 'nowrap',
              justifyContent: 'center',
              color: isControlActive ? 'white' : 'inherit',
            }}
            title={
              !isLiveMode
                ? 'Switch to Live mode to take control'
                : isControlLoading
                  ? 'Processing...'
                  : isControlActive
                    ? 'Release Control'
                    : 'Control'
            }
          >
            {isControlLoading
              ? 'Processing…'
              : isControlActive
                ? 'Release'
                : 'Control'}
          </Button>
        )}

        {/* Power Control Button */}
        {hasPowerControl && device && (
          <PowerButton host={host} device={device} disabled={!isControlActive} />
        )}

        {/* Restart Toggle Button — hidden for now (SHOW_RESTART_BUTTON = false). The
            wiring (onToggleRestart prop, restartMode state, useRecModalModes
            `restartMode` flag) is untouched, so flipping the flag at the top
            of the file brings it back without any extra changes. */}
        {SHOW_RESTART_BUTTON && !minimalControls && (
          <Button
            variant={restartMode ? 'contained' : 'outlined'}
            onClick={onToggleRestart}
            disabled={!isControlActive || !isLiveMode}
            startIcon={<RefreshIcon />}
            color={restartMode ? 'secondary' : 'primary'}
            sx={{
              fontSize: '0.8125rem',
              fontWeight: 500,
              width: 144,
              height: 40,
              px: 1.25,
              textTransform: 'none',
              whiteSpace: 'nowrap',
              justifyContent: 'center',
              color: restartMode ? 'white' : 'inherit',
            }}
            title={
              !isLiveMode
                ? 'Only available in Live mode'
                : !isControlActive
                  ? 'Take control first to enable restart mode'
                  : restartMode
                    ? 'Disable Restart Player'
                    : 'Enable Restart Player'
            }
          >
            {restartMode ? 'Stop Restart' : 'Restart'}
          </Button>
        )}

        {/* AI Agent Toggle Button — fixed width so "AI Agent" ↔ "Stop AI Agent" doesn't reflow */}
        {!minimalControls && (
          <Button
            variant={aiAgentMode ? 'contained' : 'outlined'}
            onClick={onToggleAiAgent}
            disabled={!isControlActive || !isLiveMode}
            startIcon={<AIIcon />}
            color={aiAgentMode ? 'info' : 'primary'}
            sx={{
              fontSize: '0.8125rem',
              fontWeight: 500,
              width: 144,
              height: 40,
              px: 1.25,
              textTransform: 'none',
              whiteSpace: 'nowrap',
              justifyContent: 'center',
              color: aiAgentMode ? 'white' : 'inherit',
            }}
            title={
              !isLiveMode
                ? 'Only available in Live mode'
                : !isControlActive
                  ? 'Take control first to enable AI agent'
                  : aiAgentMode
                    ? 'Disable AI Agent'
                    : 'Enable AI Agent'
            }
          >
            {aiAgentMode ? 'Stop AI Agent' : 'AI Agent'}
          </Button>
        )}

        {/* Web Panel Toggle Button. Hidden on a phone-width layout: the web automation
            panel it opens needs the room to sit beside the stream, and the header is already
            fighting for width there. */}
        {isDesktopDevice && !isMobile && (
          <Button
            variant={showWeb ? 'contained' : 'outlined'}
            onClick={onToggleWeb}
            disabled={!isControlActive || !isLiveMode}
            startIcon={<WebIcon />}
            color={showWeb ? 'secondary' : 'primary'}
            sx={{
              fontSize: '0.8125rem',
              fontWeight: 500,
              width: 144,
              height: 40,
              px: 1.25,
              textTransform: 'none',
              whiteSpace: 'nowrap',
              justifyContent: 'center',
              color: showWeb ? 'white' : 'inherit',
            }}
            title={
              !isLiveMode
                ? 'Only available in Live mode'
                : !isControlActive
                  ? 'Take control first to use web automation'
                  : showWeb
                    ? 'Hide Web'
                    : 'Show Web '
            }
          >
            {showWeb ? 'Hide Web' : 'Show Web'}
          </Button>
        )}

        {/* Show Remote / Show Terminal was removed: the remote panel auto-shows when
     control is taken and auto-hides when control is released (see
     useRecModalModes), so the toggle button did nothing meaningful. The
     `showRemote` state still drives the panel itself — it just isn't
     togglable from the toolbar anymore. */}

        {/* Close Button */}
        <IconButton
          size="large"
          onClick={onClose}
          sx={{ color: P.textSecondary, '&:hover': { color: P.textPrimary } }}
          aria-label="Close"
        >
          <CloseIcon fontSize="large" />
        </IconButton>
      </Box>
    </Box>
  );
};
