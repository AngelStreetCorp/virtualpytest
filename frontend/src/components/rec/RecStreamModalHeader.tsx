import {
  Close as CloseIcon,
  Tv as TvIcon,
  SmartToy as AIIcon,
  Language as WebIcon,
  VolumeOff as VolumeOffIcon,
  VolumeUp as VolumeUpIcon,
  Refresh as RefreshIcon,
  RadioButtonChecked as LiveIcon,
  History as ArchiveIcon,
  CameraAlt as CameraIcon,
  OpenInFull as FullscreenIcon,
  Visibility as VisibilityIcon,
  VisibilityOff as VisibilityOffIcon,
  Lock as LockIcon,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';

import { featureDeviceLinks } from '../../config/features';
import { useResponsiveMode } from '../../hooks/useResponsiveMode';
import { Box, IconButton, Typography, Button, CircularProgress, ToggleButtonGroup, ToggleButton, Tooltip } from '@mui/material';
import React from 'react';

import { Host, Device } from '../../types/common/Host_Types';
import LocalizeButton from '../navigation/Navigation_LocalizeButton';
import { PowerButton } from '../controller/power/PowerButton';

import { DeviceStatusChip } from './DeviceStatusChip';

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
  isQualitySwitching: boolean;
  isMuted: boolean;
  isControlActive: boolean;
  isControlLoading: boolean;
  aiAgentMode: boolean;
  showWeb: boolean;
  showRemote: boolean;
  isDesktopDevice: boolean;
  hasPowerControl: boolean;
  // When true, hide the "power user" controls (localize, fullscreen, AI query,
  // live/archive toggle, take control, restart, AI agent, show remote) and keep
  // only the basic viewing controls. Used for the mobile device-control page,
  // where the full toolbar doesn't fit a 375px-wide screen. Defaults to false so
  // every other caller (desktop pages reusing this header) is unaffected.
  minimalControls?: boolean;

  // Handlers
  onScreenshot: () => void;
  onOpenFullscreen?: () => void;
  onAIImageQuery?: () => void;
  onToggleLiveMode: () => void;
  onQualityChange: (event: React.MouseEvent<HTMLElement>, newQuality: 'low' | 'sd' | 'hd' | 'hd_plus' | null) => void;
  onToggleMute: () => void;
  onToggleControl: () => void;
  onToggleMonitoring: () => void;
  onToggleRestart: () => void;
  onToggleAiAgent: () => void;
  onToggleWeb: () => void;
  onToggleRemote: () => void;
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
  isQualitySwitching,
  isMuted,
  isControlActive,
  isControlLoading,
  aiAgentMode,
  showWeb,
  showRemote,
  isDesktopDevice,
  hasPowerControl,
  minimalControls = false,
  onScreenshot,
  onOpenFullscreen,
  onAIImageQuery,
  onToggleLiveMode,
  onQualityChange,
  onToggleMute,
  onToggleControl,
  onToggleMonitoring,
  onToggleRestart,
  onToggleAiAgent,
  onToggleWeb,
  onToggleRemote,
  onClose,
}) => {
  const navigate = useNavigate();
  const { isMobile } = useResponsiveMode();
  // host_vnc now has audio too: live via the hidden HLS companion behind the noVNC
  // iframe, archive via the HLS player. So audio is available for all device types.
  const isAudioSupported = true;
  const isArchiveMode = !isLiveMode;

  // HD+ is a VAAPI-only stream tier — only offer it on hosts that advertise hardware
  // H.264 encode (server falls hd_plus→hd elsewhere, but we hide the button to avoid
  // a no-op toggle on software-only hosts like Pi 5).
  const supportsHdPlus = Boolean(host.system_stats?.hardware_encode);

  // Lock indicator — mirror RecHostPreview: show for manual control OR a running
  // script/deployment, with matching colors (manual = info, script = warning).
  const hasManualControl = Boolean(manualControlLabel);
  const hasDeployment = Boolean(scriptLockActive);
  const ownerLabel = lockOwnerLabel || manualControlLabel;
  const showLock = hasManualControl || hasDeployment || Boolean(ownerLabel);

  return (
    <Box
      sx={{
        px: 2,
        py: 1,
        backgroundColor: 'grey.800',
        color: 'white',
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
          gap: 0.5,
          fontSize: '1rem', // Reduced from h6 default (1.25rem) to ensure single line
          whiteSpace: 'nowrap', // Prevent wrapping
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          maxWidth: '300px', // Constrain title area to prevent button wrapping
          flex: '0 0 auto', // Don't grow, allow shrink if needed
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
                color: hasManualControl ? 'info.main' : 'warning.main',
                flexShrink: 0
              }}
            />
          </Tooltip>
        )}
        {/* Same status chip as the preview card: "running" (blue) while a script drives
            the device, else online/offline — or error when host services are stuck. */}
        <DeviceStatusChip host={host} isRunning={hasDeployment} sx={{ ml: 0.5 }} />
      </Typography>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: '1 1 auto', justifyContent: 'flex-end', flexWrap: 'nowrap' }}>
        {/* Screenshot Button - disabled in archive/restart mode */}
        {!restartMode && (
          <IconButton
            onClick={onScreenshot}
            disabled={isArchiveMode}
            sx={{
              color: isArchiveMode ? 'grey.600' : 'grey.300',
              '&:hover': { color: isArchiveMode ? 'grey.600' : 'white' },
              '&.Mui-disabled': {
                color: 'grey.600',
              }
            }}
            aria-label="Take Screenshot"
            title={isArchiveMode ? "Screenshot only available in Live mode" : "Take Screenshot (opens in new tab)"}
          >
            <CameraIcon />
          </IconButton>
        )}

        {/* Localize Button - identify which navigation node the live screen is.
            Uses the device's preferred userinterface/variant; only shown when one
            is configured (otherwise there's no tree to match against). */}
        {!minimalControls && !restartMode && device?.preferred_userinterface && (
          <LocalizeButton
            hostName={host.host_name}
            deviceId={device.device_id}
            userinterfaceName={device.preferred_userinterface}
            variant={device.preferred_variant ?? null}
            disabled={!isLiveMode}
            disabledTitle="Localize only available in Live mode"
            sx={{
              color: isLiveMode ? 'grey.300' : 'grey.600',
              '&:hover': { color: isLiveMode ? 'white' : 'grey.600' },
              '&.Mui-disabled': { color: 'grey.600' },
            }}
          />
        )}

        {/* Optional-feature per-device pages (docs/technical/FEATURES.md) */}
        {!minimalControls &&
          device &&
          featureDeviceLinks().map((link) => (
            <IconButton
              key={link.label}
              onClick={() => {
                onClose();
                navigate(link.path(host.host_name, device.device_id));
              }}
              sx={{ color: 'grey.300', '&:hover': { color: 'white' } }}
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
            onClick={onOpenFullscreen}
            disabled={!isLiveMode}
            sx={{
              color: isLiveMode ? 'grey.300' : 'grey.600',
              '&:hover': { color: isLiveMode ? 'white' : 'grey.600' },
              '&.Mui-disabled': { color: 'grey.600' },
            }}
            aria-label="Open fullscreen player"
            title={
              isLiveMode
                ? 'Open fullscreen player in new tab (best quality, buffered)'
                : 'Fullscreen player only available in Live mode'
            }
          >
            <FullscreenIcon />
          </IconButton>
        )}

        {/* AI Image Query Button - disabled in archive/restart mode */}
        {!minimalControls && !restartMode && onAIImageQuery && (
          <IconButton
            onClick={onAIImageQuery}
            disabled={!isLiveMode}
            sx={{ 
              color: isLiveMode ? 'rgba(0,150,255,0.8)' : 'grey.600',
              '&:hover': { color: isLiveMode ? 'rgba(0,150,255,1)' : 'grey.600' },
              '&.Mui-disabled': {
                color: 'grey.600',
              }
            }}
            aria-label="Ask AI about frame"
            title={isLiveMode ? "Ask AI about current frame" : "AI Query only available in Live mode"}
          >
            <AIIcon />
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
            size="small"
            aria-label="Mode selection"
            sx={{
              '& .MuiToggleButton-root': {
                fontSize: '0.75rem',
                minWidth: 50,
                px: 1,
                border: '1px solid rgba(255, 255, 255, 0.12)',
                '&.Mui-selected': {
                  backgroundColor: isLiveMode ? 'error.main' : 'primary.main',
                  color: 'white',
                },
              },
            }}
          >
            <ToggleButton value="live" aria-label="Live mode">
              <LiveIcon sx={{ fontSize: 16, mr: 0.5 }} />
              Live
            </ToggleButton>
            <ToggleButton 
              value="restart" 
              aria-label="Restart mode"
              disabled={isControlActive}
              title={isControlActive ? "Release control to switch to Last 24h mode" : "Last 24h Archive Mode"}
            >
              <ArchiveIcon sx={{ fontSize: 16, mr: 0.5 }} />
              Last 24h
            </ToggleButton>
          </ToggleButtonGroup>
        )}

        {/* Quality control, mobile: the full LOW/SD/HD/HD+ group doesn't fit a narrow
            toolbar, so a single button shows the current level and cycles to the next
            one on tap (low -> sd -> hd -> hd+ -> low), instead of showing every option
            at once. */}
        {!restartMode && !isDesktopDevice && minimalControls && (
          <Button
            variant="contained"
            size="small"
            disabled={!isLiveMode}
            onClick={(e) => {
              const order: Array<'low' | 'sd' | 'hd' | 'hd_plus'> = supportsHdPlus
                ? ['low', 'sd', 'hd', 'hd_plus']
                : ['low', 'sd', 'hd'];
              const next = order[(order.indexOf(currentQuality) + 1) % order.length];
              onQualityChange(e, next);
            }}
            sx={{
              fontSize: '0.75rem',
              minWidth: 44,
              px: 1,
              opacity: !isLiveMode ? 0.5 : 1,
              backgroundColor: isQualitySwitching
                ? 'warning.main'
                : currentQuality === 'low'
                  ? 'success.main'
                  : currentQuality === 'sd'
                    ? 'primary.main'
                    : currentQuality === 'hd'
                      ? 'secondary.main'
                      : 'error.main',
              color: 'white',
            }}
            title="Tap to switch quality"
          >
            {currentQuality === 'hd_plus' ? 'HD+' : currentQuality.toUpperCase()}
          </Button>
        )}

        {/* Quality Toggle Button Group - Hidden for VNC/Desktop devices */}
        {!restartMode && !isDesktopDevice && !minimalControls && (
          <ToggleButtonGroup
            value={currentQuality}
            exclusive
            onChange={onQualityChange}
            size="small"
            aria-label="Quality selection"
            disabled={!isLiveMode} // Disable quality buttons in archive mode
            sx={{
              backgroundColor: isQualitySwitching ? 'warning.main' : undefined, // Orange during transition
              '& .MuiToggleButton-root': {
                fontSize: '0.75rem',
                minWidth: 38, // Reduced from 45 to save space
                px: 0.5, // Reduced from 1 to save space
                py: 0.5, // Reduce vertical padding too
                border: '1px solid rgba(255, 255, 255, 0.12)',
                opacity: !isLiveMode ? 0.5 : 1, // Dim when disabled in archive mode
                '&.Mui-selected': {
                  backgroundColor: 'primary.main',
                  color: 'white',
                  '&:hover': {
                    backgroundColor: 'primary.dark',
                  },
                },
                '&:disabled': {
                  color: 'rgba(255, 255, 255, 0.3)',
                  borderColor: 'rgba(255, 255, 255, 0.12)',
                },
              },
            }}
          >
            <ToggleButton
              value="low"
              aria-label="Low quality"
              title="Switch to LOW Quality (320x180) - Fastest loading"
              sx={{
                '&.Mui-selected': {
                  backgroundColor: 'success.main',
                  '&:hover': {
                    backgroundColor: 'success.dark',
                  },
                },
              }}
            >
              LOW
            </ToggleButton>
            <ToggleButton
              value="sd"
              aria-label="Standard definition"
              title="Switch to SD Quality (640x360) - Balanced"
              sx={{
                '&.Mui-selected': {
                  backgroundColor: 'primary.main',
                  '&:hover': {
                    backgroundColor: 'primary.dark',
                  },
                },
              }}
            >
              SD
            </ToggleButton>
            <ToggleButton
              value="hd"
              aria-label="High definition"
              title="Switch to HD Quality (1280x720) - Best quality"
              sx={{
                '&.Mui-selected': {
                  backgroundColor: 'secondary.main',
                  '&:hover': {
                    backgroundColor: 'secondary.dark',
                  },
                },
              }}
            >
              HD
            </ToggleButton>
            {/* HD+ : VAAPI-only tier (2s segments, 30fps, 12Mbps). Only shown on hosts
                that advertise hardware H.264 encode — best viewed in the fullscreen player. */}
            {supportsHdPlus && (
              <ToggleButton
                value="hd_plus"
                aria-label="HD plus"
                title="Switch to HD+ Quality (1280x720 @ 30fps) - Smoothest, best for fullscreen viewing"
                sx={{
                  '&.Mui-selected': {
                    backgroundColor: 'error.main',
                    '&:hover': {
                      backgroundColor: 'error.dark',
                    },
                  },
                }}
              >
                HD+
              </ToggleButton>
            )}
          </ToggleButtonGroup>
        )}

        {/* Monitoring Toggle - icon-only on mobile, no room for the "Monitoring" label */}
        {!restartMode && minimalControls && (
          <IconButton
            onClick={onToggleMonitoring}
            disabled={!isLiveMode}
            sx={{
              color: monitoringMode ? 'primary.main' : 'grey.300',
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
            {monitoringMode ? <VisibilityIcon /> : <VisibilityOffIcon />}
          </IconButton>
        )}
        {!restartMode && !minimalControls && (
          <Button
            variant={monitoringMode ? 'contained' : 'outlined'}
            size="small"
            onClick={onToggleMonitoring}
            disabled={!isLiveMode}
            startIcon={monitoringMode ? <VisibilityIcon /> : <VisibilityOffIcon />}
            color={monitoringMode ? 'primary' : 'inherit'}
            sx={{
              fontSize: '0.75rem',
              minWidth: 120,
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

        {/* Volume Toggle Button */}
        {!restartMode && (
          <IconButton
            onClick={onToggleMute}
            disabled={!isAudioSupported}
            sx={{
              color: isAudioSupported ? 'grey.300' : 'grey.600',
              '&:hover': { color: isAudioSupported ? 'white' : 'grey.600' },
              '&.Mui-disabled': { color: 'grey.600' },
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

        {/* Take Control Button */}
        {!minimalControls && (
          <Button
            variant={isControlActive ? 'contained' : 'outlined'}
            size="small"
            onClick={onToggleControl}
            disabled={isControlLoading || !isLiveMode}
            startIcon={isControlLoading ? <CircularProgress size={16} /> : <TvIcon />}
            color={isControlActive ? 'success' : 'primary'}
            sx={{
              fontSize: '0.75rem',
              minWidth: 120,
              color: isControlActive ? 'white' : 'inherit',
            }}
            title={
              !isLiveMode
                ? 'Switch to Live mode to take control'
                : isControlLoading
                  ? 'Processing...'
                  : isControlActive
                    ? 'Release Control'
                    : 'Take Control'
            }
          >
            {isControlLoading
              ? 'Processing...'
              : isControlActive
                ? 'Release'
                : 'Take Control'}
          </Button>
        )}

        {/* Power Control Button */}
        {hasPowerControl && device && (
          <PowerButton host={host} device={device} disabled={!isControlActive} />
        )}

        {/* Restart Toggle Button */}
        {!minimalControls && (
          <Button
            variant={restartMode ? 'contained' : 'outlined'}
            size="small"
            onClick={onToggleRestart}
            disabled={!isControlActive || !isLiveMode}
            startIcon={<RefreshIcon />}
            color={restartMode ? 'secondary' : 'primary'}
            sx={{
              fontSize: '0.75rem',
              minWidth: 120,
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

        {/* AI Agent Toggle Button */}
        {!minimalControls && (
          <Button
            variant={aiAgentMode ? 'contained' : 'outlined'}
            size="small"
            onClick={onToggleAiAgent}
            disabled={!isControlActive || !isLiveMode}
            startIcon={<AIIcon />}
            color={aiAgentMode ? 'info' : 'primary'}
            sx={{
              fontSize: '0.75rem',
              minWidth: 120,
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
            size="small"
            onClick={onToggleWeb}
            disabled={!isControlActive || !isLiveMode}
            startIcon={<WebIcon />}
            color={showWeb ? 'secondary' : 'primary'}
            sx={{
              fontSize: '0.75rem',
              minWidth: 100,
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

        {/* Remote/Terminal Toggle Button */}
        {!minimalControls && (
          <Button
            variant="outlined"
            size="small"
            onClick={onToggleRemote}
            disabled={!isControlActive || !isLiveMode}
            sx={{
              fontSize: '0.75rem',
              minWidth: 100,
              color: 'inherit',
            }}
            title={
              !isLiveMode
                ? 'Only available in Live mode'
                : !isControlActive
                  ? `Take control first to use ${isDesktopDevice ? 'terminal' : 'remote'}`
                  : showRemote
                    ? `Hide ${isDesktopDevice ? 'Terminal' : 'Remote'}`
                    : `Show ${isDesktopDevice ? 'Terminal' : 'Remote'}`
            }
          >
            {showRemote
              ? `Hide ${isDesktopDevice ? 'Terminal' : 'Remote'}`
              : `Show ${isDesktopDevice ? 'Terminal' : 'Remote'}`}
          </Button>
        )}

        {/* Close Button */}
        <IconButton
          onClick={onClose}
          sx={{ color: 'grey.300', '&:hover': { color: 'white' } }}
          aria-label="Close"
        >
          <CloseIcon />
        </IconButton>
      </Box>
    </Box>
  );
};
