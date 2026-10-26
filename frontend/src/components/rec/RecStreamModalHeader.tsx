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
  ViewTimeline as TimelineIcon,
  OpenInNew as OpenInNewIcon,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';

import { AppIcon } from '../../constants/icons';
import { AIIcon, CameraIcon, FullscreenIcon } from '../common/icons/CustomIcons';
import { featureDeviceLinks } from '../../config/features';
import { useResponsiveMode } from '../../hooks/useResponsiveMode';
import { ArrowDropDown as ArrowDropDownIcon, Bolt as BoltIcon, Check as CheckIcon, Mic as MicIcon, Route as RouteIcon, PlayCircleOutline as RunScriptIcon } from '@mui/icons-material';
import { Box, ListItemIcon, ListItemText, Menu, MenuItem, IconButton, Typography, Button, CircularProgress, ToggleButtonGroup, ToggleButton, Tooltip, alpha } from '@mui/material';
import React, { useEffect, useState } from 'react';

import { useI18n } from '../../i18n/useI18n';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

import { Host, Device } from '../../types/common/Host_Types';
import LocalizeButton, { LOCALIZE_OFF_TITLE, localizeOff } from '../navigation/Navigation_LocalizeButton';
import { PowerButton } from '../controller/power/PowerButton';

import type { LiveStreamTransport } from '../../types/controller/WebRTC_Types';
import { primaryButtonSx, segmentedSx, toggleSx } from '../common/PageChrome';
import { StreamQualityControl } from './StreamQualityControl';
import { MonitorProfileBadge } from './MonitorProfileBadge';
import { AdBreaksDialog } from '../monitoring/AdBreaksDialog';
import { getDeviceMonitorProfile, deviceTooltipName } from '../../hooks/useDeviceFilters';
import { DeviceInfoNameTooltip } from '../common/DeviceInfoTooltipIcon';
import { DeviceMaintenanceBadge } from '../common/DeviceMaintenanceBadge';
import { api } from '../../utils/apiClient';
import { buildServerUrlWithParams } from '../../utils/buildUrlUtils';
import { TYPOGRAPHY } from '../../constants/typography';


// AVQ feature link (Audio/Video Quality) renders monitor-derived analysis —
// on a tv_lite device (no monitor) the page would load but show empty cards,
// so the link is greys out in the toolbar. Detect by label rather than path
// so this header does not depend on the AVQ feature being enabled at build time.
const isAvqLink = (label: string): boolean => /quality/i.test(label);


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
  /** Device's declared stream profile; hides/disables WEB where it cannot work (BUG-0833). */
  streamProtocol?: string;
  isMuted: boolean;
  isControlActive: boolean;
  isControlLoading: boolean;
  showWeb: boolean;
  isDesktopDevice: boolean;
  hasPowerControl: boolean;
  // Whether this device can be controlled at all — false when it has no remote
  // controller configured (see useRecDeviceChecks.canTakeControl). Disables the
  // Control button and explains why, instead of letting the user lock the device
  // only to land on RemotePanel's "No remote configured" empty state. Required
  // (not defaulted) so a future caller has to decide, rather than silently
  // shipping an enabled Control button on a remote-less device.
  canTakeControl: boolean;
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
  /** LoL zones/inputs overlay toggle; shown only for desktop (host_vnc) devices. */
  lolOverlayAvailable?: boolean;
  lolOverlayOn?: boolean;
  onToggleLolOverlay?: () => void;
  onToggleRestart: () => void;
  /** Panel currently open from the Actions menu; choosing it again closes it. */
  activePanel: 'ai' | 'goto' | 'script' | 'voice' | null;
  onSelectPanel: (panel: 'ai' | 'goto' | 'script' | 'voice') => void;
  onToggleWeb: () => void;
  // Show/Hide Remote was removed from the toolbar — the panel auto-shows when
  // control is taken and auto-hides when control is released (see
  // useRecModalModes). The `showRemote` state still flows to RecStreamContainer
  // and RecPanelManager; only the toolbar toggle is gone.
  onClose: () => void;
}

// Every icon-only toolbar button shares this box (6px padding, 18px glyph) so the gaps between icons are even.
const compactIconSx = { p: 0.75, '& .MuiSvgIcon-root': { fontSize: TYPOGRAPHY.cardTitle.size } } as const;

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
  streamProtocol,
  isMuted,
  isControlActive,
  isControlLoading,
  showWeb,
  isDesktopDevice,
  hasPowerControl,
  canTakeControl,
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
  lolOverlayAvailable = false,
  lolOverlayOn = false,
  onToggleLolOverlay,
  onToggleRestart,
  activePanel,
  onSelectPanel,
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
  // A device whose profile runs no monitor (tv_lite, TASK-95) has no review buffer and no analysis to overlay.
  const monitoringOff = (host.system_stats?.monitoring_off ?? []).includes(device?.device_id ?? '');
  const monitoringOffTitle = 'Monitoring is off for this device (profile tv_lite): stream and control only';
  const hasReviewBuffer = host.system_stats?.archive_video !== false && !monitoringOff;
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [adBreaksOpen, setAdBreaksOpen] = useState(false);
  const [splitAnchor, setSplitAnchor] = React.useState<HTMLElement | null>(null);

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

  // Mirror RecHostPreview's displayName exactly: VNC devices show only host.host_name,
  // every other device shows "<device_name> - <host_name>". The preview tile shows
  // e.g. "stbv1+ - vpt-mf1" and the modal's title should match.
  const displayName = device
    ? device.device_model === 'host_vnc'
      ? host.host_name
      : `${device.device_name} - ${host.host_name}`
    : host.host_name;

  // "Source" is only meaningful for stream-source devices (rtsp_video with a URL,
  // local_video with a file). Pull the current source from /server/av/status so
  // the Actions menu can open it in a new tab — the tv_lite profile has no
  // monitoring, so without this shortcut the only way to verify the source
  // is to open StreamSourceRemote (extra click) and copy the URL out by hand.
  const deviceModel = device?.device_model;
  const isStreamSourceDevice = deviceModel === 'rtsp_video' || deviceModel === 'local_video';
  const [streamSourceUrl, setStreamSourceUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!isStreamSourceDevice || !host?.host_name || !device?.device_id) {
      setStreamSourceUrl(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{ status: { source_url?: string | null; youtube_url?: string | null } }>(
          buildServerUrlWithParams('/server/av/status', {
            host_name: host.host_name,
            device_id: device.device_id,
          }),
        );
        if (cancelled) return;
        setStreamSourceUrl(res.status?.youtube_url || res.status?.source_url || null);
      } catch {
        // Source button stays disabled when the host can't be reached; the
        // StreamSourceRemote panel does a richer read with a retry surface.
        if (!cancelled) setStreamSourceUrl(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [host?.host_name, device?.device_id, isStreamSourceDevice]);

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
          fontSize: TYPOGRAPHY.navbarItem.size, // Reduced from h6 default (1.25rem) to ensure single line
          whiteSpace: 'nowrap', // Prevent wrapping
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          // Reserved space for the device name: a long name should ellipsize inside
          // this fixed-width slot instead of pushing the whole toolbar around.
          // 300px fits ~28 characters at 1rem (e.g. "device_vendor_42"), which
          // covers the typical name lengths we see; longer names truncate.
          width: 300,
          flexShrink: 0,
        }}
      >
        <DeviceInfoNameTooltip
          name={deviceTooltipName(host, device, displayName)}
          info={device?.device_info}
          gatewayInfo={device?.gateway_info}
        >
          <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {displayName}
          </Box>
        </DeviceInfoNameTooltip>
        {device && <MonitorProfileBadge profile={getDeviceMonitorProfile(host, device)} services={host.system_stats?.monitor_profile_services?.[getDeviceMonitorProfile(host, device)]} />}
        <DeviceMaintenanceBadge hostName={host.host_name} deviceId={device?.device_id} />
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
                fontSize: TYPOGRAPHY.navbarItem.size,
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
                  ? P.series[1] // blue while a script drives the device
                  : host.status === 'online'
                    ? '#2ecc71' // green when the host is up
                    : P.error, // red when offline / unknown
              boxShadow: `0 0 0 2px ${alpha(P.textPrimary, 0.06)}`,
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
              ...compactIconSx,
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
            disabled={!isLiveMode || localizeOff(host, device.device_id)}
            disabledTitle={localizeOff(host, device.device_id) ? LOCALIZE_OFF_TITLE : 'Localize only available in Live mode'}
            width={280}
            expandedWidth={380}
            sx={{
              color: isLiveMode ? P.textSecondary : P.textMuted,
              '&:hover': { color: isLiveMode ? P.textPrimary : P.textMuted },
              '&.Mui-disabled': { color: P.textMuted },
              ...compactIconSx,
            }}
          />
        )}

        {/* Timeline (TASK-94): the last 24 h of this device as a thumbnail grid. The selected server is
            already the one that registers this host, so the page finds it from host + device alone.
            Disabled when the device's monitor is off (tv_lite / no-archiver profile): there is no
            24h thumbnail stream to grid — the page would just render an empty state. */}
        {!minimalControls && device?.video_capture_path && (
          <IconButton
            size="large"
            disabled={monitoringOff}
            onClick={() => {
              if (monitoringOff) return;
              // New tab: the stream modal stays where it is.
              window.open(`/monitoring/timeline?host=${encodeURIComponent(host.host_name)}&device=${encodeURIComponent(device.device_id)}`, '_blank', 'noopener');
            }}
            sx={{
              color: monitoringOff ? P.textMuted : P.textSecondary,
              '&:hover': { color: monitoringOff ? P.textMuted : P.textPrimary },
              '&.Mui-disabled': { color: P.textMuted },
              ...compactIconSx,
            }}
            aria-label="Timeline"
            title={monitoringOff ? monitoringOffTitle : 'Timeline (last 24 h)'}
          >
            <TimelineIcon fontSize="medium" />
          </IconButton>
        )}

        {/* Ad breaks (ad_meter only): the last 24 h of breaks with the pictures the meter kept, to check them and mark a
            mistake "not an ad" (owner, 2026-10-26). */}
        {!minimalControls && device && getDeviceMonitorProfile(host, device) === 'ad_meter' && (
          <IconButton
            size="large"
            onClick={() => setAdBreaksOpen(true)}
            sx={{ color: P.textSecondary, '&:hover': { color: P.textPrimary }, ...compactIconSx }}
            aria-label={t('Ad breaks')}
            title={t('Ad breaks, last 24 h')}
            data-testid="ad-breaks-button"
          >
            <AppIcon name="image" size="md" />
          </IconButton>
        )}
        {device && adBreaksOpen && (
          <AdBreaksDialog
            open={adBreaksOpen}
            onClose={() => setAdBreaksOpen(false)}
            host={host as unknown as { host_name: string } & Record<string, unknown>}
            deviceId={device.device_id}
            deviceName={device.device_name}
          />
        )}

        {/* Optional-feature per-device pages (docs/technical/FEATURES.md).
            AVQ (the Audio/Video Quality feature) reads monitor outputs, so on a
            tv_lite device the page loads but its cards come up empty — grey it
            out with the same monitoring-off tooltip the other monitor-dependent
            controls carry. Other feature links are unaffected. */}
        {!minimalControls &&
          device &&
          featureDeviceLinks().map((link) => {
            const linkDisabled = monitoringOff && isAvqLink(link.label);
            return (
              <IconButton
                key={link.label}
                size="large"
                disabled={linkDisabled}
                onClick={() => {
                  if (linkDisabled) return;
                  // replace: takes the modal's Back-to-close history entry, so Back from the
                  // feature page returns to the page the modal was opened from.
                  navigate(link.path(host.host_name, device.device_id), { replace: true });
                  onClose();
                }}
                sx={{
                  color: linkDisabled ? P.textMuted : P.textSecondary,
                  '&:hover': { color: linkDisabled ? P.textMuted : P.textPrimary },
                  '&.Mui-disabled': { color: P.textMuted },
                  ...compactIconSx,
                }}
                aria-label={link.label}
                title={linkDisabled ? monitoringOffTitle : link.label}
              >
                {link.icon}
              </IconButton>
            );
          })}

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
              ...compactIconSx,
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

        {/* AI Image Query Button - disabled in archive/restart mode and on tv_lite devices
            (no monitor means no recent frame context for the AI to reason about; the AI Agent
            panel and the AVQ feature link carry the same monitoring-off tooltip below). */}
        {!minimalControls && !restartMode && onAIImageQuery && (
          <IconButton
            size="large"
            onClick={onAIImageQuery}
            disabled={!isLiveMode || monitoringOff}
            sx={{
              color: isLiveMode && !monitoringOff ? P.accentText : P.textMuted,
              '&:hover': { color: isLiveMode && !monitoringOff ? P.accentText : P.textMuted },
              '&.Mui-disabled': {
                color: P.textMuted,
              },
              ...compactIconSx,
            }}
            aria-label="Ask AI about frame"
            title={
              monitoringOff
                ? monitoringOffTitle
                : isLiveMode
                  ? "Ask AI about current frame"
                  : "AI Query only available in Live mode"
            }
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
            sx={[
              ...(Array.isArray(segmentedSx(P)) ? (segmentedSx(P) as object[]) : [segmentedSx(P)]),
              { '& .MuiToggleButton-root': { fontSize: TYPOGRAPHY.body.size, minWidth: 68, height: 40, px: 1.5 } },
            ]}
          >
            <ToggleButton value="live" aria-label="Live mode">
              <LiveIcon sx={{ fontSize: TYPOGRAPHY.body.size, mr: 0.75, color: P.error }} />
              Live
            </ToggleButton>
            <ToggleButton
              value="restart"
              aria-label="Restart mode"
              disabled={isControlActive || !hasReviewBuffer}
              title={
                monitoringOff
                  ? monitoringOffTitle
                  : !hasReviewBuffer
                  ? "24h review buffer is off on this host (ARCHIVE_VIDEO=false)"
                  : isControlActive ? "Release control to switch to Last 24h mode" : "Last 24h Archive Mode"
              }
            >
              <ArchiveIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size, mr: 0.5 }} />
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
            streamProtocol={streamProtocol}
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
              ...compactIconSx,
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
            {isMuted ? <VolumeOffIcon fontSize="medium" /> : <VolumeUpIcon fontSize="medium" />}
          </IconButton>
        )}

        {lolOverlayAvailable && onToggleLolOverlay && (
          <IconButton
            size="large"
            onClick={onToggleLolOverlay}
            sx={{ color: lolOverlayOn ? P.accentText : P.textSecondary }}
            aria-label={lolOverlayOn ? 'Hide LoL overlay' : 'Show LoL overlay'}
            title={lolOverlayOn ? 'Hide LoL overlay (danger / safe zones, bot inputs)' : 'Show LoL overlay (danger / safe zones, bot inputs)'}
          >
            <AppIcon name="target" size="md" />
          </IconButton>
        )}
        {/* Monitoring Toggle - icon-only on mobile, no room for the "Monitoring" label */}
        {!restartMode && minimalControls && (
          <IconButton
            size="large"
            onClick={onToggleMonitoring}
            disabled={!isLiveMode || monitoringOff}
            sx={{
              color: monitoringMode ? P.accentText : P.textSecondary,
              opacity: !isLiveMode ? 0.5 : 1,
            }}
            aria-label={monitoringMode ? 'Hide Monitoring Overlay' : 'Show Monitoring Overlay'}
            title={
              monitoringOff
                ? monitoringOffTitle
                : !isLiveMode
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
            variant="outlined"
            onClick={onToggleMonitoring}
            disabled={!isLiveMode || monitoringOff}
            startIcon={monitoringMode ? <VisibilityIcon /> : <VisibilityOffIcon />}
            sx={{
              ...(toggleSx(P, monitoringMode) as object),
              fontSize: TYPOGRAPHY.body.size,
              fontWeight: 500,
              minWidth: 132,
              height: 40,
              px: 1.5,
              textTransform: 'none',
              opacity: !isLiveMode ? 0.5 : 1,
            }}
            title={
              monitoringOff
                ? monitoringOffTitle
                : !isLiveMode
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
            variant="contained"
            onClick={onToggleControl}
            disabled={isControlLoading || !isLiveMode || !canTakeControl}
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
                  <TvIcon sx={{ fontSize: TYPOGRAPHY.pageSubtitle.size }} />
                </Box>
                <Box
                  component="span"
                  sx={{ display: isControlLoading ? 'inline-flex' : 'none' }}
                >
                  <CircularProgress size={18} thickness={5} />
                </Box>
              </Box>
            }
            sx={{
              ...(primaryButtonSx(P) as object),
              fontSize: TYPOGRAPHY.body.size,
              fontWeight: 500,
              width: 144, // fixed — covers "Processing..." (12ch) + 24px icon + 24px padding
              height: 40,
              px: 1.25,
              textTransform: 'none',
              whiteSpace: 'nowrap',
              justifyContent: 'center',
            }}
            title={
              !canTakeControl
                ? 'No remote configured for this device'
                : !isLiveMode
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
            variant="outlined"
            onClick={onToggleRestart}
            disabled={!isControlActive || !isLiveMode}
            startIcon={<RefreshIcon />}
            sx={{
              ...(toggleSx(P, restartMode) as object),
              fontSize: TYPOGRAPHY.body.size,
              fontWeight: 500,
              width: 144,
              height: 40,
              px: 1.25,
              textTransform: 'none',
              whiteSpace: 'nowrap',
              justifyContent: 'center',
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

        {/* Actions menu: AI Agent, Source (stream-source devices only, opens the
            current source URL in a new tab), Go to node, Run script. AI Agent
            is greyed out on a monitoring-off device — it relies on the same
            capture / freeze / KPI data the AVQ feature link reads from, so on
            tv_lite it would either fail or hallucinate. Source is the tv_lite
            shortcut for "is the upstream actually reachable right now", which is
            the question you ask first when a stream freezes. */}
        {!minimalControls && (
          <>
            <Button
              variant="outlined"
              color="primary"
              disabled={!isControlActive || !isLiveMode}
              onClick={(e) => setSplitAnchor(e.currentTarget)}
              startIcon={<BoltIcon fontSize="small" />}
              endIcon={<ArrowDropDownIcon />}
              sx={{
                width: 144,
                height: 40,
                flexShrink: 0,
                fontSize: TYPOGRAPHY.body.size,
                fontWeight: 500,
                px: 0.75,
                textTransform: 'none',
                whiteSpace: 'nowrap',
                color: 'inherit',
              }}
              title={
                !isLiveMode
                  ? 'Only available in Live mode'
                  : !isControlActive
                    ? 'Take control first to enable AI agent'
                    : undefined
              }
            >
              {t('Actions')}
            </Button>
            <Menu anchorEl={splitAnchor} open={!!splitAnchor} onClose={() => setSplitAnchor(null)}>
              <MenuItem
                selected={activePanel === 'ai'}
                disabled={monitoringOff}
                onClick={() => {
                  if (monitoringOff) return;
                  setSplitAnchor(null);
                  onSelectPanel('ai');
                }}
                title={monitoringOff ? monitoringOffTitle : undefined}
              >
                <ListItemIcon>
                  <AIIcon />
                </ListItemIcon>
                <ListItemText>{t('AI Agent')}</ListItemText>
                {activePanel === 'ai' && <CheckIcon fontSize="small" sx={{ ml: 1.5 }} />}
              </MenuItem>
              {/* Source — visible only on stream-source devices. The URL is fetched
                  once on mount; the menu item is disabled until /server/av/status
                  resolves. Opens the raw URL in a new tab, which is what an operator
                  wants when they suspect the upstream itself is the failure (the
                  most common cause of a "freeze of image and audio" on a tv_lite
                  host with 47 streams — the box can't keep up, but it's worth
                  confirming the upstream isn't the issue first). */}
              {isStreamSourceDevice && (
                <MenuItem
                  disabled={!streamSourceUrl}
                  onClick={() => {
                    if (!streamSourceUrl) return;
                    window.open(streamSourceUrl, '_blank', 'noopener');
                    setSplitAnchor(null);
                  }}
                  title={
                    streamSourceUrl
                      ? streamSourceUrl
                      : 'Source not yet loaded — close and reopen the modal if it stays empty'
                  }
                >
                  <ListItemIcon>
                    <OpenInNewIcon fontSize="small" />
                  </ListItemIcon>
                  <ListItemText>{t('Source')}</ListItemText>
                </MenuItem>
              )}
              <MenuItem
                selected={activePanel === 'goto'}
                onClick={() => {
                  setSplitAnchor(null);
                  onSelectPanel('goto');
                }}
              >
                <ListItemIcon>
                  <RouteIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>{t('Go to node')}</ListItemText>
                {activePanel === 'goto' && <CheckIcon fontSize="small" sx={{ ml: 1.5 }} />}
              </MenuItem>
              <MenuItem
                selected={activePanel === 'script'}
                onClick={() => {
                  setSplitAnchor(null);
                  onSelectPanel('script');
                }}
              >
                <ListItemIcon>
                  <RunScriptIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>{t('Run script')}</ListItemText>
                {activePanel === 'script' && <CheckIcon fontSize="small" sx={{ ml: 1.5 }} />}
              </MenuItem>
              <MenuItem
                selected={activePanel === 'voice'}
                onClick={() => {
                  setSplitAnchor(null);
                  onSelectPanel('voice');
                }}
              >
                <ListItemIcon>
                  <MicIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>{t('Voice')}</ListItemText>
                {activePanel === 'voice' && <CheckIcon fontSize="small" sx={{ ml: 1.5 }} />}
              </MenuItem>
            </Menu>
          </>
        )}

        {/* Web Panel Toggle Button. Hidden on a phone-width layout: the web automation
            panel it opens needs the room to sit beside the stream, and the header is already
            fighting for width there. */}
        {isDesktopDevice && !isMobile && (
          <Button
            variant="outlined"
            onClick={onToggleWeb}
            disabled={!isControlActive || !isLiveMode}
            startIcon={<WebIcon />}
            sx={{
              ...(toggleSx(P, showWeb) as object),
              fontSize: TYPOGRAPHY.body.size,
              fontWeight: 500,
              width: 144,
              height: 40,
              px: 1.25,
              textTransform: 'none',
              whiteSpace: 'nowrap',
              justifyContent: 'center',
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
