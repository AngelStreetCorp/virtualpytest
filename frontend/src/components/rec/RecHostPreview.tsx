import { Error as ErrorIcon, Lock as LockIcon, LocalOffer as TagIcon } from '@mui/icons-material';
import { withVncCacheBust } from '../../utils/buildUrlUtils';
import { useHostSession } from '../../hooks/useHostSession';
import { Card, Typography, Box, Chip, CircularProgress, Checkbox, Tooltip, IconButton } from '@mui/material';
import React, { useState, useCallback, useMemo, useEffect, useRef, memo } from 'react';
import { useNavigate } from 'react-router-dom';

import { featureDeviceLinks, featurePreviewAction } from '../../config/features';

import { DEFAULT_DEVICE_RESOLUTION } from '../../config/deviceResolutions';
import { isMobileModel } from '../../config/layoutConfig';
import { useStream } from '../../hooks/controller';
import { useDeviceScriptLabel } from '../../hooks/rec/useDeviceScriptLabel';
import { useDeviceLockLabel } from '../../hooks/rec/useDeviceLockLabel';
import { useHostControl } from '../../hooks/useHostManager';
import { useToast } from '../../hooks/useToast';
import { Host, Device } from '../../types/common/Host_Types';
import { calculateVncScaling, vncScaledSize } from '../../utils/vncUtils';
import { getLockTimingLines } from '../../utils/recUtils';
import { HLSVideoPlayer } from '../common/HLSVideoPlayer';
import { DeviceInfoTooltipIcon } from '../common/DeviceInfoTooltipIcon';
import LocalizeButton from '../navigation/Navigation_LocalizeButton';
import { DeviceFarmBadge } from './DeviceFarmBadge';
import { DeviceStatusChip } from './DeviceStatusChip';
import { RunningScriptNameBadge } from './RunningScriptNameBadge';

// Memoized HLS player declared outside the component to retain identity across renders
const MemoizedHLSPlayer = memo(HLSVideoPlayer, (prevProps, nextProps) => {
  // Only re-render if stream URL or essential props change
  return (
    prevProps.streamUrl === nextProps.streamUrl &&
    prevProps.isStreamActive === nextProps.isStreamActive &&
    prevProps.isCapturing === nextProps.isCapturing &&
    prevProps.model === nextProps.model &&
    prevProps.muted === nextProps.muted &&
    JSON.stringify(prevProps.layoutConfig) === JSON.stringify(nextProps.layoutConfig)
  );
});

interface RecHostPreviewProps {
  host: Host;
  device?: Device;
  hideHeader?: boolean;
  isEditMode?: boolean;
  isSelected?: boolean;
  onSelectionChange?: (selected: boolean) => void;
  deviceFlags?: string[]; // Pass flags from parent
  activeFlagFilters?: string[];
  onFlagClick?: (flag: string) => void;
  onOpenModal?: (poster?: string | null) => void;
  isAnyModalOpen?: boolean;
  isSelectedForModal?: boolean;
}

export const RecHostPreview: React.FC<RecHostPreviewProps> = ({
  host,
  device,
  hideHeader = false,
  isEditMode = false,
  isSelected = false,
  onSelectionChange,
  deviceFlags = [], // Default to empty array
  activeFlagFilters,
  onFlagClick,
  onOpenModal,
  isAnyModalOpen,
  isSelectedForModal,
}) => {
  const navigate = useNavigate();
  // States
  const [error] = useState<string | null>(null);
  const [isStreamActive, setIsStreamActive] = useState(true);
  const manualControlLabel = useDeviceLockLabel(host, device);
  const { getDeviceLockInfo } = useHostControl();
  const deviceId = device?.device_id || 'device1';
  const lockInfo = getDeviceLockInfo(host, deviceId);

  const {
    scriptLabel: deploymentScriptLabel,
    hasNamedScript: hasNamedDeployment,
    scriptOwnerName,
  } = useDeviceScriptLabel(host, device);
  const hasManualControl = Boolean(manualControlLabel);

  // Start-time + live duration for the lock tooltip — a multi-hour duration makes
  // a stale/zombie script lock obvious at a glance.
  const lockTiming = useMemo(() => getLockTimingLines(lockInfo), [lockInfo]);

  const isMobile = useMemo(
    () => isMobileModel(device?.device_model),
    [device?.device_model]
  );

  // Check if this is a VNC device
  const isVncDevice = useMemo(() => {
    return device?.device_model === 'host_vnc';
  }, [device?.device_model]);

  // Use stream hook for all devices (VNC gets VNC URL, others get HLS URL)
  const { streamUrl, urlError: streamError } = useStream({
    host,
    device_id: device?.device_id || 'device1',
  });

  // BUG-0107 step 2: the proxy's auth_request gate rejects the iframe's navigation to
  // /host/<name>/vnc_lite.html without this cookie. Must be set BEFORE the iframe is
  // given a src, so the preview iframe only renders once the mint call resolves. Not
  // keepAlive: the websocket handshake is the only request the gate ever sees, the
  // connection then persists independent of cookie expiry. (The non-VNC HLS preview
  // below is gated separately, internally, by HLSVideoPlayer itself.)
  const vncSessionReady = useHostSession(isVncDevice ? streamUrl : null, false);

  const previewVncScaling = useMemo(
    () => calculateVncScaling({ width: 300, height: 150 }),
    [],
  );
  // The size that scaling actually paints. The wrapper below takes it so the render can be
  // centred in the card, which the iframe itself cannot be — its box is the whole remote
  // desktop.
  const previewVncSize = useMemo(() => vncScaledSize({ width: 300, height: 150 }), []);

  // Memoize layout config to prevent unnecessary re-renders
  const layoutConfig = useMemo(() => ({
    minHeight: '150px',
    aspectRatio: `${DEFAULT_DEVICE_RESOLUTION.width}/${DEFAULT_DEVICE_RESOLUTION.height}`,
    objectFit: 'contain' as 'fill' | 'contain' | 'cover',
    isMobileModel: isMobile,
  }), [isMobile]);

  // Device flags are now passed as props from parent

  // Hook for notifications
  const { showError } = useToast();

  // Ref to the HLS <video> element so we can capture its current frame as a
  // poster when opening the modal (hides modal's loading overlay).
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    return () => setIsStreamActive(false);
  }, []);

  useEffect(() => {
    setIsStreamActive(!isAnyModalOpen);
  }, [isAnyModalOpen]);

  const captureVideoPoster = useCallback((): string | null => {
    const video = videoRef.current;
    if (!video || !video.videoWidth || !video.videoHeight) return null;
    try {
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext('2d');
      if (!ctx) return null;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL('image/jpeg', 0.6);
    } catch {
      // Tainted canvas (CORS) or other draw failure — skip poster, loading overlay will show.
      return null;
    }
  }, []);

  // An optional feature can claim this device model's click (config/features.ts). It is
  // mounted below and tells us whether it wants it — a phone slot does while it has no phone
  // on it, since the "stream" behind the card is only the offline placeholder.
  const previewAction = featurePreviewAction(device?.device_model);
  const [featureCanHandleClick, setFeatureCanHandleClick] = useState(false);
  const [featureActionOpen, setFeatureActionOpen] = useState(false);

  // Handle opening/closing with restored state — only block if no stream is available
  const handleOpenStreamModal = useCallback(() => {
    if (previewAction && featureCanHandleClick) {
      setFeatureActionOpen(true);
      return;
    }
    if (!streamUrl || streamError) {
      // Stable per-device id so repeated clicks on a dead-stream card replace
      // the single popup instead of stacking one per click.
      showError(streamError || 'No active stream available', {
        id: `rec-preview-stream-error-${host.host_name}-${deviceId}`,
      });
      return;
    }
    const poster = captureVideoPoster();
    setIsStreamActive(false);
    onOpenModal?.(poster);
  }, [
    previewAction,
    featureCanHandleClick,
    streamUrl,
    streamError,
    showError,
    onOpenModal,
    captureVideoPoster,
    host.host_name,
    deviceId,
  ]);

  // Clean display values - special handling for VNC devices
  const displayName = device
    ? device.device_model === 'host_vnc'
      ? host.host_name // For VNC devices, show just the host name
      : `${device.device_name} - ${host.host_name}`
    : host.host_name;

  const isPausingForModal = Boolean(isAnyModalOpen);
  const pauseMessage = isSelectedForModal ? 'Playing in modal' : 'Preview paused';
  // Who is on the device (manual lock owner, else whoever launched the run) —
  // shown next to the script name, not instead of it.
  const lockOwnerLabel = manualControlLabel || scriptOwnerName;
  const scriptNameBadge =
    hasNamedDeployment || lockOwnerLabel ? (
      <RunningScriptNameBadge
        scriptName={hasNamedDeployment ? (deploymentScriptLabel as string) : null}
        ownerName={lockOwnerLabel}
        maxChars={30}
      />
    ) : null;

  return (
    <Card
      sx={{
        height: 180,
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        p: 0,
        backgroundColor: 'transparent',
        backgroundImage: 'none',
        boxShadow: 'none',
        border: isSelected ? '2px solid #1976d2' : '1px solid rgba(255, 255, 255, 0.1)',
        '&:hover': {
          boxShadow: '0px 4px 20px rgba(0, 0, 0, 0.3)',
          border: isSelected ? '2px solid #1976d2' : '1px solid rgba(255, 255, 255, 0.2)',
        },
        '& .MuiCard-root': {
          padding: 0,
        },
      }}
    >
      {/* Header */}
      {!hideHeader && (
        <Box
          sx={{
            px: 1,
            py: 0.5,
            minHeight: 32,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 0.5,
            position: 'relative',
          }}
        >
          {/* Device name — must stay fully readable. The full name is always
              available on hover; tags are collapsed (below) so they never
              squeeze it. */}
          <Tooltip title={displayName} arrow placement="top">
            <Typography variant="subtitle2" noWrap sx={{ flex: 1, mr: 0.5, minWidth: 0 }}>
              {displayName}
            </Typography>
          </Tooltip>

          {/* Device flags. One tag → show it as a chip. Two or more → collapse
              into a single compact "tags" badge whose tooltip lists them all,
              so the device name is never cropped by a row of chips. */}
          {deviceFlags.length === 1 && (() => {
            const flag = deviceFlags[0];
            const isActive = activeFlagFilters?.includes(flag) ?? false;
            return (
              <Chip
                label={flag}
                size="small"
                variant={isActive ? 'filled' : 'outlined'}
                color={isActive ? 'primary' : 'default'}
                clickable={!!onFlagClick}
                onClick={onFlagClick ? (e) => { e.stopPropagation(); onFlagClick(flag); } : undefined}
                sx={{ fontSize: '0.65rem', height: 18, maxWidth: 80, flexShrink: 0 }}
              />
            );
          })()}
          {deviceFlags.length > 1 && (
            <Tooltip
              arrow
              placement="top"
              title={
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, py: 0.25, maxWidth: 220 }}>
                  {deviceFlags.map((flag) => {
                    const isActive = activeFlagFilters?.includes(flag) ?? false;
                    return (
                      <Chip
                        key={flag}
                        label={flag}
                        size="small"
                        variant={isActive ? 'filled' : 'outlined'}
                        color={isActive ? 'primary' : 'default'}
                        clickable={!!onFlagClick}
                        onClick={onFlagClick ? (e) => { e.stopPropagation(); onFlagClick(flag); } : undefined}
                        sx={{ fontSize: '0.65rem', height: 18 }}
                      />
                    );
                  })}
                </Box>
              }
            >
              <Chip
                icon={<TagIcon sx={{ fontSize: '0.75rem !important', ml: '4px' }} />}
                label={deviceFlags.length}
                size="small"
                variant={deviceFlags.some((f) => activeFlagFilters?.includes(f)) ? 'filled' : 'outlined'}
                color={deviceFlags.some((f) => activeFlagFilters?.includes(f)) ? 'primary' : 'default'}
                sx={{ fontSize: '0.65rem', height: 18, flexShrink: 0, '& .MuiChip-label': { px: 0.5 } }}
              />
            </Tooltip>
          )}
          
          {/* Deployment running or manual control indicator */}
          {(hasNamedDeployment || hasManualControl || lockOwnerLabel) && (
            <Tooltip
              arrow
              placement="top"
              title={
                <Box sx={{ py: 0.25 }}>
                  {lockOwnerLabel && (
                    <Typography variant="caption" sx={{ display: 'block', fontWeight: 'bold' }}>
                      {hasManualControl
                        ? `Controlled by: ${lockOwnerLabel}`
                        : `Run by: ${lockOwnerLabel}`}
                    </Typography>
                  )}
                  {hasNamedDeployment && (
                    <Typography variant="caption" sx={{ display: 'block', fontWeight: 'bold' }}>
                      Script: {deploymentScriptLabel}
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
                  fontSize: '0.9rem',
                  color: hasManualControl ? 'info.main' : 'warning.main',
                  ml: 0.5,
                }}
              />
            </Tooltip>
          )}
          
          {/* Selection checkbox in edit mode - positioned before status chip */}
          {isEditMode && (
            <Checkbox
              size="small"
              checked={isSelected}
              onChange={(e) => onSelectionChange?.(e.target.checked)}
              sx={{ 
                p: 0.5,
                '& .MuiSvgIcon-root': {
                  fontSize: '1rem'
                }
              }}
            />
          )}
          
          {/* Device info — last metadata on hover; click opens the editor */}
          <DeviceInfoTooltipIcon
            info={device?.device_info}
            gatewayInfo={device?.gateway_info}
            deviceName={device?.device_name}
            hostName={host.host_name}
          />

          {/* Localize Button - identify which navigation node the live screen is.
              Preview is always live, so no disabled/live-mode gating needed.
              Only shown when a preferred userinterface is configured. */}
          {device?.preferred_userinterface && (
            <LocalizeButton
              hostName={host.host_name}
              deviceId={device.device_id}
              userinterfaceName={device.preferred_userinterface}
              variant={device.preferred_variant ?? null}
              sx={{
                p: 0.25,
                '& .MuiSvgIcon-root': { fontSize: '1rem' },
              }}
            />
          )}

          {/* Optional-feature per-device pages (docs/technical/FEATURES.md) */}
          {device &&
            featureDeviceLinks().map((link) => (
              <Tooltip key={link.label} title={link.label}>
                <IconButton
                  size="small"
                  sx={{ p: 0.25, color: 'grey.400', '&:hover': { color: 'primary.main' } }}
                  onClick={(e) => {
                    e.stopPropagation();
                    navigate(link.path(host.host_name, device.device_id));
                  }}
                >
                  {link.icon}
                </IconButton>
              </Tooltip>
            ))}

          <DeviceStatusChip host={host} isRunning={hasNamedDeployment} />
        </Box>
      )}

      {/* Content area - Stream preview or Runner badge */}
      <Box sx={{ flex: 1, position: 'relative', minHeight: 0, overflow: 'hidden' }}>
        <Box
          sx={{
            height: '100%',
            position: 'relative',
            overflow: 'hidden',
            backgroundColor: 'black',
          }}
        >
          {streamUrl ? (
            isVncDevice ? (
              <Box
                sx={{
                  position: 'relative',
                  width: '100%',
                  height: '100%',
                  backgroundColor: 'black',
                  overflow: 'hidden',
                  // Centring is safe here ONLY because the flex item is the fixed-size
                  // wrapper below, never the iframe. calculateVncScaling gives the iframe a
                  // 1440x847 layout box that it shrinks with a transform about 'top left';
                  // as a flex item that box gets shrunk to ~300px wide and centred, putting
                  // its top-left ~350px ABOVE the card, and the transform then scales about
                  // that off-card corner — which overflow hidden clips to a black card
                  // (BUG-0104). The wrapper is already the painted size, so centring it
                  // moves the render and nothing else.
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {/* Only render VNC iframe when stream is active and the VNC session cookie is set */}
                {isStreamActive && vncSessionReady && (
                  <Box
                    sx={{
                      width: previewVncSize.width,
                      height: previewVncSize.height,
                      flexShrink: 0,
                      overflow: 'hidden',
                    }}
                  >
                    <iframe
                      src={withVncCacheBust(streamUrl)}
                      style={{
                        border: 'none',
                        backgroundColor: '#000',
                        pointerEvents: 'none',
                        ...previewVncScaling, // Preview card target size (memoized)
                      }}
                      title="VNC Desktop Preview"
                    />
                  </Box>
                )}
                {/* Pause overlay when modal is open */}
                {isPausingForModal && (
                  <Box
                    sx={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      right: 0,
                      bottom: 0,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      backgroundColor: 'rgba(0, 0, 0, 0.85)',
                      zIndex: 2,
                    }}
                  >
                    <Typography variant="caption" align="center" sx={{ color: 'grey.500' }}>
                      {pauseMessage}
                    </Typography>
                  </Box>
                )}
                {scriptNameBadge}
                <DeviceFarmBadge provider={device?.device_farm_provider} />
                {/* Click overlay to open full modal */}
                <Box
                  onClick={handleOpenStreamModal}
                  sx={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    cursor: 'pointer',
                    backgroundColor: 'transparent',
                    zIndex: 1,
                    '&:hover': {
                      backgroundColor: 'rgba(0, 0, 0, 0.1)',
                    },
                  }}
                />
              </Box>
            ) : (
              <Box
                sx={{
                  position: 'relative',
                  width: '100%',
                  height: '100%',
                  backgroundColor: 'black',
                  overflow: 'hidden',
                }}
              >
                {/* Keep HLS player mounted, control via isStreamActive prop */}
                <MemoizedHLSPlayer
                    streamUrl={streamUrl}
                    isStreamActive={isStreamActive}
                    isCapturing={false}
                    model={device?.device_model || 'unknown'}
                    layoutConfig={layoutConfig}
                    isExpanded={false}
                    muted={true} // Always muted in preview
                    videoElementRef={videoRef}
                  />
                {/* Pause overlay when modal is open */}
                {isPausingForModal && (
                  <Box
                    sx={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      right: 0,
                      bottom: 0,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      backgroundColor: 'rgba(0, 0, 0, 0.85)',
                      zIndex: 2,
                    }}
                  >
                    <Typography variant="caption" align="center" sx={{ color: 'grey.500' }}>
                      {pauseMessage}
                    </Typography>
                  </Box>
                )}
                {scriptNameBadge}
                <DeviceFarmBadge provider={device?.device_farm_provider} />
                {/* Click overlay to open full modal */}
                <Box
                  onClick={handleOpenStreamModal}
                  sx={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    cursor: 'pointer',
                    backgroundColor: 'transparent',
                    zIndex: 1,
                    '&:hover': {
                      backgroundColor: 'rgba(0, 0, 0, 0.05)',
                    },
                  }}
                />
              </Box>
            )
          ) : error ? (
            <Box
              sx={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'error.main',
              }}
            >
              <ErrorIcon sx={{ mb: 1 }} />
              <Typography variant="caption" align="center">
                {error}
              </Typography>
            </Box>
          ) : (
            <Box
              sx={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 2,
              }}
            >
              <CircularProgress size={24} />
              <Typography variant="caption" color="text.secondary">
                Loading stream...
              </Typography>
            </Box>
          )}
        </Box>
      </Box>

      {/* Stream Modal */}
      {/* The RecHostStreamModal component is no longer rendered here */}

      {/* A feature's stand-in for this card's click (config/features.ts). Always mounted so it
          can tell us whether it wants the click before anyone clicks; it renders nothing until
          `open`. */}
      {previewAction && (
        <previewAction.Component
          hostName={host.host_name}
          deviceId={deviceId}
          open={featureActionOpen}
          onClose={() => setFeatureActionOpen(false)}
          onCanHandleChange={setFeatureCanHandleClick}
        />
      )}
    </Card>
  );
};
