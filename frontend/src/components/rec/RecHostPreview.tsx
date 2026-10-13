import { Error as ErrorIcon, Lock as LockIcon, LocalOffer as TagIcon } from '@mui/icons-material';
import { buildLatestSnapshotUrl, withVncCacheBust } from '../../utils/buildUrlUtils';
import { useHostSession } from '../../hooks/useHostSession';
import { Card, Typography, Box, Chip, CircularProgress, Checkbox, Tooltip, IconButton } from '@mui/material';
import React, { useState, useCallback, useMemo, useEffect, useLayoutEffect, useRef, memo } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { featureDeviceLinks, featurePreviewAction } from '../../config/features';

import { DEFAULT_DEVICE_RESOLUTION } from '../../config/deviceResolutions';
import { isMobileModel } from '../../config/layoutConfig';
import { useStream } from '../../hooks/controller';
import { useVncPassword } from '../../hooks/controller/useVncPassword';
import { useDeviceScriptLabel } from '../../hooks/rec/useDeviceScriptLabel';
import { useDeviceLockLabel } from '../../hooks/rec/useDeviceLockLabel';
import {
  useDroneWifiStatus,
  isDroneDevice,
  droneHintLine,
  DRONE_WIFI_HEADLINE,
  DRONE_WIFI_HINT,
} from '../../hooks/rec/useDroneWifiStatus';
import { useLatestSnapshot } from '../../hooks/rec/useLatestSnapshot';
import { useHostControl } from '../../hooks/useHostManager';
import { useToast } from '../../hooks/useToast';
import { Host, Device } from '../../types/common/Host_Types';
import { calculateVncScaling, vncScaledSize } from '../../utils/vncUtils';
import { getLockTimingLines } from '../../utils/recUtils';
import { HLSVideoPlayer } from '../common/HLSVideoPlayer';
import { LiveStreamSwitch } from '../common/LiveStream/LiveStreamSwitch';
import type { LiveStreamTransport, WhepStatus } from '../../types/controller/WebRTC_Types';
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
    prevProps.shouldPause === nextProps.shouldPause &&
    prevProps.onPlayerReady === nextProps.onPlayerReady &&
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
  onOpenModal?: (poster?: string | null, canReuseStream?: boolean) => void;
  isAnyModalOpen?: boolean;
  isSelectedForModal?: boolean;
  persistentStreamTarget?: HTMLElement | null;
  persistentStreamMuted?: boolean;
  persistentStreamInteractive?: boolean;
  persistentStreamShouldPause?: boolean;
  persistentStreamOnReady?: () => void;
  persistentStreamTransport?: LiveStreamTransport;
  persistentStreamReconnectKey?: string;
  persistentStreamOnWebRTCFailed?: () => void;
  persistentStreamOnWebRTCStatusChange?: (status: WhepStatus) => void;
  /**
   * Group control: the slot of this device's cell in the group modal. While set, the
   * already-playing player moves there (same portal root as the single stream modal),
   * so opening the group does not start a second stream per device.
   */
  groupStreamTarget?: HTMLElement | null;
  /**
   * Snapshot mode (TASK-48): render a 1Hz `latest.jpg` instead of an HLS
   * player or VNC iframe. Hovering for 400 ms swaps to the live branch;
   * leaving unmounts it. The page flips this on when the current page has
   * more than `REC_LIVE_TILE_LIMIT` tiles, so ≤ 16 always play live.
   */
  snapshotMode?: boolean;
  /**
   * Phones only: fill the tile instead of letterboxing (objectFit 'cover'). Some phones stream
   * a 16:9 frame with the portrait screen pillarboxed in the middle; the caller gives the tile a
   * 9:16 box and cover crops the black sides away, like the Take Control panel does.
   */
  fillMobileFrame?: boolean;
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
  persistentStreamTarget = null,
  persistentStreamMuted = true,
  persistentStreamInteractive = false,
  persistentStreamShouldPause = false,
  persistentStreamOnReady,
  persistentStreamTransport = 'hls',
  persistentStreamReconnectKey,
  persistentStreamOnWebRTCFailed,
  persistentStreamOnWebRTCStatusChange,
  groupStreamTarget = null,
  snapshotMode = false,
  fillMobileFrame = false,
}) => {
  const P = useAgentChatPalette();
  const navigate = useNavigate();
  // States
  const [error] = useState<string | null>(null);
  const [isStreamActive, setIsStreamActive] = useState(true);
  // Hover = live (TASK-48): in snapshot mode, onMouseEnter arms a 400 ms timer
  // that flips this to true; the live branch renders for as long as the cursor
  // stays over the tile. onMouseLeave flips it back and unmounts the player.
  const [showLiveOnHover, setShowLiveOnHover] = useState(false);
  // Off-screen tiles cost nothing: IntersectionObserver flips it false when the
  // tile leaves the viewport (with a 200 px margin so tiles just-out-of-frame
  // keep up). Disabled in snapshot mode → no 1 Hz polling; in live mode →
  // isStreamActive=false (HLS pauses, VNC iframe unmounts).
  const [isVisible, setIsVisible] = useState(true);
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

  // A drone has no stream until it flies, and no Wi-Fi until it is powered on.
  // Both are handled here, in the preview, and nowhere else: gating on the tile
  // would make the stream modal and the remote panel unreachable for a drone
  // that is simply switched off.
  const isDrone = useMemo(() => isDroneDevice(device), [device]);

  // Only polls while this preview is mounted (i.e. the device is selected), so
  // browsing /device-control never joins a drone AP behind the user's back.
  const droneWifi = useDroneWifiStatus(host, device, isDrone);

  // Use stream hook for all devices (VNC gets VNC URL, others get HLS URL)
  const { streamUrl, urlError: streamError } = useStream({
    host,
    device_id: device?.device_id || 'device1',
  });

  // Only a host with HOST_VNC_AUTOCONNECT=true returns a password; others stay URL-clean.
  const { vncPasswordReady, withVncPassword } = useVncPassword(isVncDevice ? host : null);

  // BUG-0107 step 2: the proxy's auth_request gate rejects the iframe's navigation to
  // /host/<name>/vnc_lite.html without this cookie. Must be set BEFORE the iframe is
  // given a src, so the preview iframe only renders once the mint call resolves. Not
  // keepAlive: the websocket handshake is the only request the gate ever sees, the
  // connection then persists independent of cookie expiry. (The non-VNC HLS preview
  // below is gated separately, internally, by HLSVideoPlayer itself.)
  const vncSessionReady = useHostSession(isVncDevice ? streamUrl : null, false);

  // Snapshot URL — only computed lazily so buildLatestSnapshotUrl's device-lookup
  // is paid for only by the tiles that actually enter snapshot mode. The hook
  // mints the host-session cookie off this URL via useHostSession above.
  const snapshotUrl = useMemo(() => {
    if (!deviceId) return null;
    try {
      return buildLatestSnapshotUrl(host, deviceId);
    } catch {
      return null;
    }
  }, [host, deviceId]);

  // Snapshot hook runs only when the tile actually wants the img path: snapshot
  // mode is on, the user is not hovering (hover already swapped to live), and
  // the tile is on-screen (off-screen, no content). The hook returns null src
  // while disabled, so the img below renders nothing.
  const showSnapshotImage = snapshotMode && !showLiveOnHover && Boolean(snapshotUrl);
  const { src: snapshotSrc, error: snapshotError } = useLatestSnapshot(
    snapshotUrl,
    showSnapshotImage && isVisible,
  );

  // BUG-0436: the VNC preview used a hardcoded 300×150 box, so the "One full" layout (and any
  // other large layout) left a tiny 255×150 iframe centred in a huge card. Measure the actual
  // stream area (the Box the VNC branch renders into) and scale the iframe to fill it while
  // preserving the remote desktop's 1440×847 aspect ratio. Until ResizeObserver fires the
  // 300×150 fallback keeps the first paint from collapsing to 0×0.
  const vncStreamAreaRef = useRef<HTMLDivElement | null>(null);
  const [vncStreamAreaSize, setVncStreamAreaSize] = useState<{ width: number; height: number } | null>(null);
  useLayoutEffect(() => {
    if (!isVncDevice) return undefined;
    const el = vncStreamAreaRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const update = () => {
      const { width, height } = el.getBoundingClientRect();
      setVncStreamAreaSize((prev) =>
        prev && prev.width === width && prev.height === height ? prev : { width, height },
      );
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [isVncDevice]);
  const vncTargetSize = useMemo(
    () => vncStreamAreaSize ?? { width: 300, height: 150 },
    [vncStreamAreaSize],
  );
  const previewVncScaling = useMemo(
    () => calculateVncScaling(vncTargetSize),
    [vncTargetSize],
  );
  // The size that scaling actually paints. The wrapper below takes it so the render can be
  // centred in the card, which the iframe itself cannot be — its box is the whole remote
  // desktop. Now driven by the measured stream area, not a hardcoded 300×150.
  const previewVncSize = useMemo(() => vncScaledSize(vncTargetSize), [vncTargetSize]);

  const isInGroup = Boolean(groupStreamTarget);
  // Playing in a modal (single stream or group): keep streaming while the page tiles pause.
  const isPlayingInModal = Boolean(isSelectedForModal) || isInGroup;

  // Memoize layout config to prevent unnecessary re-renders
  const layoutConfig = useMemo(() => ({
    minHeight: '150px',
    aspectRatio: `${DEFAULT_DEVICE_RESOLUTION.width}/${DEFAULT_DEVICE_RESOLUTION.height}`,
    // The group cell gives a phone a 9:16 box, like `fillMobileFrame` callers do.
    objectFit: (isMobile && (fillMobileFrame || isInGroup) ? 'cover' : 'contain') as 'fill' | 'contain' | 'cover',
    isMobileModel: isMobile,
  }), [isMobile, fillMobileFrame, isInGroup]);

  // Device flags are now passed as props from parent

  // Hook for notifications
  const { showError } = useToast();

  // Ref to the HLS <video> element so we can capture its current frame as a
  // poster when opening the modal (hides modal's loading overlay).
  const videoRef = useRef<HTMLVideoElement>(null);
  // Keep a stable portal destination for the lifetime of this preview. Moving this
  // plain container between slots does not remount the React-owned player inside it.
  const [persistentStreamRoot] = useState(() => {
    const root = document.createElement('div');
    root.style.width = '100%';
    root.style.height = '100%';
    root.style.position = 'relative';
    root.style.overflow = 'hidden';
    root.style.background = 'black';
    return root;
  });
  const previewStreamSlotRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    if (!isVncDevice || typeof ResizeObserver === 'undefined') return undefined;
    const update = () => {
      const { width, height } = persistentStreamRoot.getBoundingClientRect();
      if (!width || !height) return;
      setVncStreamAreaSize((prev) =>
        prev && prev.width === width && prev.height === height ? prev : { width, height },
      );
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(persistentStreamRoot);
    return () => ro.disconnect();
  }, [isVncDevice, persistentStreamRoot]);

  // Ref to the outer Card — observer target. IntersectionObserver needs a
  // DOM node; refs are stable across renders so we don't churn observers.
  const cardRef = useRef<HTMLDivElement | null>(null);

  // Hover timer: 400 ms after onMouseEnter, flip to live. Cleared on
  // onMouseLeave so a quick cursor pass does not swap modes. Touch devices
  // never fire mouseenter on a real tap, so this path is desktop-only; phones
  // keep the snapshot and tap → modal as before.
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const HOVER_LIVE_DELAY_MS = 400;

  useEffect(() => {
    return () => setIsStreamActive(false);
  }, []);

  // Pause HLS playback + hide VNC iframe whenever the tile should not be
  // streaming: modal is open, OR the tile is off-screen, OR (snapshot mode
  // and the user is not hovering — hover already owns the live branch).
  useEffect(() => {
    const liveRequested = !snapshotMode || showLiveOnHover;
    setIsStreamActive((!isAnyModalOpen || isPlayingInModal) && (isVisible || isPlayingInModal) && liveRequested);
  }, [isAnyModalOpen, isPlayingInModal, isVisible, snapshotMode, showLiveOnHover]);

  // BUG-0465: streamUrl is added to the deps so the effect re-runs when the HLS branch
  // appears. Without it, the effect fires once on mount (previewStreamSlotRef.current is
  // null because useStream starts at null) and never again, leaving persistentStreamRoot
  // detached and every preview tile stuck on a black <video> that hls.js never composits.
  // BUG-0470: same for showSnapshotImage — in snapshot mode the slot only appears when hover
  // swaps the tile to live, so without it the hover player played into a detached root (black).
  useLayoutEffect(() => {
    const target = isSelectedForModal && persistentStreamTarget
      ? persistentStreamTarget
      : groupStreamTarget ?? previewStreamSlotRef.current;
    if (target && persistentStreamRoot.parentElement !== target) {
      target.appendChild(persistentStreamRoot);
    }
  }, [isSelectedForModal, persistentStreamRoot, persistentStreamTarget, groupStreamTarget, streamUrl, showSnapshotImage]);

  useEffect(() => () => persistentStreamRoot.remove(), [persistentStreamRoot]);

  // Off-screen tiles cost nothing (TASK-48 G4). Observe the card with a
  // 200 px rootMargin so tiles just-out-of-frame stay warm — scrolling fast
  // would otherwise pop a flash of black on the way past.
  useEffect(() => {
    const node = cardRef.current;
    if (!node || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry) setIsVisible(entry.isIntersecting);
      },
      { rootMargin: '200px', threshold: 0 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

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

  // Hover handlers — desktop only. cancelHoverLive runs on every unmount-like
  // boundary (mouseleave AND when the effect above re-runs) so a stale timer
  // cannot fire after the cursor has already left.
  const cancelHoverLive = useCallback(() => {
    if (hoverTimerRef.current !== null) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    setShowLiveOnHover(false);
  }, []);

  const handleTileMouseEnter = useCallback(() => {
    if (!snapshotMode) return;
    if (hoverTimerRef.current !== null) clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = setTimeout(() => {
      hoverTimerRef.current = null;
      setShowLiveOnHover(true);
    }, HOVER_LIVE_DELAY_MS);
  }, [snapshotMode]);

  const handleTileMouseLeave = useCallback(() => {
    cancelHoverLive();
  }, [cancelHoverLive]);

  useEffect(() => cancelHoverLive, [cancelHoverLive]);

  // Handle opening/closing with restored state — only block if no stream is available
  const handleOpenStreamModal = useCallback(() => {
    if (previewAction && featureCanHandleClick) {
      setFeatureActionOpen(true);
      return;
    }
    if (isDrone && droneWifi.state !== 'connected') {
      // The drone is the one device whose picture cannot exist before the link
      // does: it is its own access point and only streams once joined. Opening
      // the re-host dialog on a drone we cannot reach just shows an empty modal,
      // so the click explains the real blocker instead. The device modal and the
      // flight panel stay reachable — only this one action is gated.
      //
      // Headline + hint, because the tile splits them across two lines and a
      // bare "AP unavailable" is too terse for a toast that has nowhere else
      // to look.
      const headline = DRONE_WIFI_HEADLINE[droneWifi.state];
      const hint = DRONE_WIFI_HINT[droneWifi.state];
      showError(hint ? `${headline} — ${hint.toLowerCase()}` : headline, {
        id: `rec-preview-drone-wifi-${host.host_name}-${deviceId}`,
      });
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
    // Snapshot-mode poster: when the live <video> is not mounted (snapshotMode
    // on, not hovered), captureVideoPoster returns null — fall back to the
    // current snapshot src so the modal does not flash a black loading frame.
    const liveMounted = !snapshotMode || showLiveOnHover;
    const poster = (liveMounted ? captureVideoPoster() : null) ?? snapshotSrc ?? null;
    // Release hover state after capturing the hand-off frame. A normally-live
    // player stays active and its stable portal root is moved into the modal.
    cancelHoverLive();
    // Snapshot tiles deliberately do not keep a live player resident; even if a
    // hover temporarily mounted one, leaving the tile tears it down by design.
    onOpenModal?.(poster, !snapshotMode);
  }, [
    previewAction,
    featureCanHandleClick,
    streamUrl,
    streamError,
    isDrone,
    droneWifi.state,
    showError,
    onOpenModal,
    captureVideoPoster,
    host.host_name,
    deviceId,
    snapshotMode,
    showLiveOnHover,
    snapshotSrc,
    cancelHoverLive,
  ]);

  // Clean display values - special handling for VNC devices
  const displayName = device
    ? device.device_model === 'host_vnc'
      ? host.host_name // For VNC devices, show just the host name
      : `${device.device_name} - ${host.host_name}`
    : host.host_name;

  const isPausingForModal = Boolean(isAnyModalOpen);
  const pauseMessage = isPlayingInModal ? 'Playing in modal' : 'Preview paused';
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
      ref={cardRef}
      onMouseEnter={handleTileMouseEnter}
      onMouseLeave={handleTileMouseLeave}
      sx={{
        height: 180,
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        p: 0,
        // Card surface so the header reads as a card on the warm-grey page (light) — TASK-56.
        backgroundColor: P.surface,
        backgroundImage: 'none',
        boxShadow: 'none',
        border: isSelected ? `2px solid ${P.accent}` : `1px solid ${P.borderColor}`,
        '&:hover': {
          boxShadow: '0px 4px 20px rgba(0, 0, 0, 0.3)',
          border: isSelected ? `2px solid ${P.accent}` : `1px solid ${P.borderColor}`,
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
                  color: hasManualControl ? P.accentText : P.warning,
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
              width={260}
              expandedWidth={340}
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
                  sx={{ p: 0.25, color: P.textSecondary, '&:hover': { color: P.accentText } }}
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
              {/* Drone wifi state. A Tello is its own access point and only
                  broadcasts while powered on, and only streams while flying, so
                  "no picture" here has three very different causes. This names
                  the one that is actually true instead of letting the generic
                  player call it a stuck stream.

                  Deliberately OUTSIDE the snapshot/live ternary below: inside
                  the snapshot branch it only rendered when `showSnapshotImage`
                  was true, and a drone never takes that path (snapshotMode is
                  off for a small grid, and a landed Tello has no snapshot), so
                  the tile stayed black with no explanation at all. */}
              {isDrone && droneWifi.state !== 'connected' && (
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
                    pointerEvents: 'none',
                    // Above the click-to-open overlay that follows this block,
                    // otherwise the Scan chip is swallowed by it.
                    zIndex: 3,
                  }}
                >
                  <Box
                    sx={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 0.5,
                      width: '100%',
                      height: '100%',
                      px: 1.5,
                      py: 1,
                      // The Tello is white, so a bare card surface would swallow
                      // it in light mode. hoverBg is a warm grey in light and a
                      // raised grey in dark, which separates it in both. It also
                      // covers the whole preview area: the tile's own background
                      // is black in BOTH themes, and dark body text on black is
                      // unreadable in light mode.
                      backgroundColor: P.hoverBg,
                    }}
                  >
                    {/* Placeholder instead of a black frame: it says "this is a
                        drone with no picture yet", not "something failed". Small
                        on purpose — the preview area is only ~120px tall and the
                        text still has to fit under it. */}
                    <Box
                      component="img"
                      src="/tello_placeholder.png"
                      alt=""
                      sx={{
                        maxWidth: 118,
                        height: 'auto',
                        // Dim it a little so the text below stays the loudest
                        // thing in the tile.
                        opacity: 0.9,
                        filter: 'saturate(0.85)',
                      }}
                    />
                    <Typography variant="body2" align="center" sx={{ color: P.textPrimary, fontWeight: 600 }}>
                      {DRONE_WIFI_HEADLINE[droneWifi.state]}
                    </Typography>
                    {/* Hint and action share a row: the preview area is ~110px
                        tall, and stacking the chip under the hint pushed it past
                        the bottom edge where it was clipped. */}
                    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1 }}>
                      {/* droneHintLine owns the "never show a stale error" rule
                          and is unit-tested; keep the logic there, not here. */}
                      {(() => {
                        const hint = droneHintLine(
                          droneWifi.state,
                          droneWifi.busy,
                          droneWifi.ssid,
                          droneWifi.signal
                        );
                        if (!hint) return null;
                        return (
                          <Typography variant="caption" sx={{ color: P.textMuted }}>
                            {hint}
                          </Typography>
                        );
                      })()}
                      {/* Countdown to the next automatic scan. Hidden while busy:
                          the chip already reads "Scanning…", and two indicators
                          saying the same thing is the duplication again. */}
                      {!droneWifi.busy && (
                        <Typography variant="caption" sx={{ color: P.textMuted, fontVariantNumeric: 'tabular-nums' }}>
                          {`${droneWifi.secondsToNextScan}s`}
                        </Typography>
                      )}
                      {droneWifi.state === 'connecting' && <CircularProgress size={14} sx={{ color: P.accent }} />}
                      <Chip
                        label={droneWifi.busy ? 'Scanning…' : 'Scan'}
                        size="small"
                        onClick={(event) => {
                          // The whole card is the click-to-open target, so a plain
                          // onClick here would also raise the "not connected"
                          // gate toast — the one thing this chip exists to fix.
                          event.stopPropagation();
                          droneWifi.rescan();
                        }}
                        sx={{
                          pointerEvents: 'auto',
                          cursor: droneWifi.busy ? 'default' : 'pointer',
                          color: P.accentText,
                          borderColor: P.accent,
                        }}
                      />
                    </Box>
                  </Box>
                </Box>
              )}

          {/* Snapshot tile (TASK-48): when snapshotMode is on AND the user is
              not currently hovering, replace the HLS player / VNC iframe with
              a 1Hz <img> over the device's latest.jpg. Same box, same black
              background, badges and click overlay stay in place. */}
          {showSnapshotImage ? (
            <Box
              sx={{
                position: 'relative',
                width: '100%',
                height: '100%',
                backgroundColor: 'black',
                overflow: 'hidden',
              }}
            >
              {snapshotSrc && (
                <Box
                  component="img"
                  src={snapshotSrc}
                  alt={`${device?.device_name || host.host_name} snapshot`}
                  draggable={false}
                  sx={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: '100%',
                    objectFit: layoutConfig.objectFit,
                    backgroundColor: 'black',
                    userSelect: 'none',
                  }}
                />
              )}
              {/* After 3 consecutive fetch errors the hook keeps polling but
                  the tile now explains why nothing is on screen. No HLS
                  fallback: hosts that haven't shipped latest.jpg simply wait
                  for G1 to roll out (TASK-48 §3). */}
              {snapshotError && (
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
                    pointerEvents: 'none',
                  }}
                >
                  <Typography variant="caption" align="center" sx={{ color: P.textMuted }}>
                    Snapshot unavailable
                  </Typography>
                </Box>
              )}

              {/* Pause overlay when modal is open — mirrors the live branch */}
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
                  <Typography variant="caption" align="center" sx={{ color: P.textMuted }}>
                    {pauseMessage}
                  </Typography>
                </Box>
              )}
              {scriptNameBadge}
              <DeviceFarmBadge provider={device?.device_farm_provider} />
              {/* Click overlay to open full modal — same handler as the live branch */}
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
          ) : streamUrl ? (
            isVncDevice ? (
              <Box
                ref={vncStreamAreaRef}
                sx={{
                  position: 'relative',
                  width: '100%',
                  height: '100%',
                  backgroundColor: 'black',
                  overflow: 'hidden',
                  // NOTE (BUG-0473): the flex centring below no longer reaches the VNC
                  // render. The wrapper is rendered through a portal into
                  // `persistentStreamRoot` and re-parented into `previewStreamSlotRef`,
                  // which is `position: absolute` — so the wrapper is NOT a flex item of
                  // this Box any more, and it lands flush top-left. It now centres itself
                  // (see the wrapper below). The properties are kept because the pause
                  // overlay is still an in-flow flex child and relies on them.
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {/* Only render VNC iframe when stream is active and the VNC session cookie is set */}
                <Box ref={previewStreamSlotRef} sx={{ position: 'absolute', inset: 0 }} />
                {createPortal(isStreamActive && vncSessionReady && vncPasswordReady ? (
                  <Box
                    sx={{
                      width: previewVncSize.width,
                      height: previewVncSize.height,
                      flexShrink: 0,
                      overflow: 'hidden',
                      // BUG-0473: this wrapper is portal-rendered into `persistentStreamRoot`
                      // and re-parented into the absolutely-positioned `previewStreamSlotRef`,
                      // so the stream area's flex centring (BUG-0104) no longer applies to it
                      // and the desktop rendered flush top-left with dead space beside it.
                      // Centre it here instead. `persistentStreamRoot` is `position: relative`,
                      // so these offsets are relative to the render box — which also means the
                      // render stays centred when the root is moved into the modal slot.
                      // The wrapper itself is the fixed painted size, never the 1440x847 iframe
                      // box, so this cannot reintroduce BUG-0104.
                      position: 'absolute',
                      top: '50%',
                      left: '50%',
                      transform: 'translate(-50%, -50%)',
                    }}
                  >
                    <iframe
                      src={withVncCacheBust(withVncPassword(streamUrl))}
                      style={{
                        border: 'none',
                        backgroundColor: '#000',
                        pointerEvents: persistentStreamInteractive ? 'auto' : 'none',
                        ...previewVncScaling, // Preview card target size (memoized)
                      }}
                      title="VNC Desktop Preview"
                    />
                  </Box>
                ) : null, persistentStreamRoot)}
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
                    <Typography variant="caption" align="center" sx={{ color: P.textMuted }}>
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
                <Box ref={previewStreamSlotRef} sx={{ position: 'absolute', inset: 0 }} />
                {createPortal(<LiveStreamSwitch
                  streamUrl={streamUrl}
                  webrtcEnabled={Boolean(isSelectedForModal) && persistentStreamTransport === 'webrtc'}
                  reconnectKey={persistentStreamReconnectKey}
                  onWebRTCFailed={persistentStreamOnWebRTCFailed}
                  onStatusChange={persistentStreamOnWebRTCStatusChange}
                  muted={isSelectedForModal ? persistentStreamMuted : true}
                  layoutConfig={layoutConfig}
                ><MemoizedHLSPlayer
                    streamUrl={streamUrl}
                    isStreamActive={isStreamActive}
                    isCapturing={false}
                    model={device?.device_model || 'unknown'}
                    layoutConfig={layoutConfig}
                    isExpanded={false}
                    muted={isSelectedForModal ? persistentStreamMuted : true}
                    shouldPause={isSelectedForModal && persistentStreamShouldPause}
                    onPlayerReady={isSelectedForModal ? persistentStreamOnReady : undefined}
                    videoElementRef={videoRef}
                  /></LiveStreamSwitch>, persistentStreamRoot)}
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
                    <Typography variant="caption" align="center" sx={{ color: P.textMuted }}>
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
          ) : isDrone ? null : error ? (
            /* A drone renders the wifi overlay above, which is the only status
               a drone should show: "Loading stream…" on top of "Checking…" is
               two answers to one question, and the generic one is always wrong
               for a device that only streams once it is paired and flying. */
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
