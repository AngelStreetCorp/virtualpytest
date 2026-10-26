import { Error as ErrorIcon } from '@mui/icons-material';
import { buildLatestSnapshotUrl, withVncCacheBust } from '../../utils/buildUrlUtils';
import { useHostSession } from '../../hooks/useHostSession';
import { Card, Typography, Box, Chip, CircularProgress, Checkbox } from '@mui/material';
import React, { useState, useCallback, useMemo, useEffect, useLayoutEffect, useRef, memo } from 'react';
import { createPortal } from 'react-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { featurePreviewAction } from '../../config/features';

import { DEFAULT_DEVICE_RESOLUTION } from '../../config/deviceResolutions';
import { isMobileModel } from '../../config/layoutConfig';
import { useStream } from '../../hooks/controller';
import VncAudioTrack from '../controller/av/VncAudioTrack';
import { useVncPassword } from '../../hooks/controller/useVncPassword';
import { useDeviceScriptLabel } from '../../hooks/rec/useDeviceScriptLabel';
import { useDeviceLockLabel } from '../../hooks/rec/useDeviceLockLabel';
import {
  useDroneWifiStatus,
  isDroneDevice,
  droneHeadline,
  droneHintLine,
  DRONE_WIFI_HEADLINE,
  DRONE_WIFI_HINT,
} from '../../hooks/rec/useDroneWifiStatus';
import { useLatestSnapshot } from '../../hooks/rec/useLatestSnapshot';
import { useToast } from '../../hooks/useToast';
import { Host, Device } from '../../types/common/Host_Types';
import { withVncViewportScale } from '../../utils/vncUtils';
import { HLSVideoPlayer } from '../common/HLSVideoPlayer';
import { LiveStreamSwitch } from '../common/LiveStream/LiveStreamSwitch';
import type { LiveStreamTransport, WhepStatus } from '../../types/controller/WebRTC_Types';
import { DeviceInfoNameTooltip } from '../common/DeviceInfoTooltipIcon';
import { DeviceFarmBadge } from './DeviceFarmBadge';
import { DeviceLockBadge, lockBadgeShows } from './DeviceLockBadge';
import { DroneTelemetryOverlay } from './DroneBatteryBadge';
import { LocalizeVideoBadge } from './LocalizeVideoBadge';
import { RunningScriptNameBadge } from './RunningScriptNameBadge';
import { MonitorProfileBadge } from './MonitorProfileBadge';
import { getDeviceMonitorProfile, deviceTooltipName } from '../../hooks/useDeviceFilters';
import { DeviceFavoriteStar } from '../common/DeviceFavoriteStar';
import { DeviceMaintenanceBadge } from '../common/DeviceMaintenanceBadge';
import { TYPOGRAPHY } from '../../constants/typography';

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
  persistentStreamOnWebRTCFailed?: (reason: string) => void;
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
  /**
   * "One full" layout: stretch the card to fill the grid cell (no 16:9 dead space).
   * The inner content uses flex:1 to fill the stretched card rather than aspectRatio.
   */
  isPartial?: boolean;
  /** Show the short profile badge in the tile header next to the name (the page turns it off above 5 columns, where it would crowd the title). */
  showProfileBadge?: boolean;
}

export const RecHostPreview: React.FC<RecHostPreviewProps> = ({
  host,
  device,
  hideHeader = false,
  isEditMode = false,
  isSelected = false,
  onSelectionChange,
  // The flag chip / Localize / AVQ / lock / status toolbar entries were removed
  // from the header (BUG-0552) but the props stay on the interface — Rec.tsx's
  // memo comparator still references them, and a future use of the same
  // `deviceFlags` data on a Settings / Monitor overlay is plausible. Marking
  // them as ignored at this site keeps the call site and the comparator in
  // sync without leaving dead UI in the header.
  deviceFlags: _deviceFlags = [],
  activeFlagFilters: _activeFlagFilters,
  onFlagClick: _onFlagClick,
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
  isPartial = false,
  showProfileBadge = false,
}) => {
  const P = useAgentChatPalette();
  // States
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
  const deviceId = device?.device_id || 'device1';

  const {
    scriptLabel: deploymentScriptLabel,
    hasNamedScript: hasNamedDeployment,
    scriptOwnerName,
  } = useDeviceScriptLabel(host, device);

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
  // A drone's player mounts only once it is paired AND the host writes fresh video.
  const droneVideoReady = droneWifi.state === 'connected' && droneWifi.videoLive;

  // Use stream hook for all devices (VNC gets VNC URL, others get HLS URL)
  const {
    streamUrl,
    audioStreamUrl,
    urlError: streamError,
    isLoadingUrl: isStreamUrlLoading,
  } = useStream({
    host,
    device_id: device?.device_id || 'device1',
  });

  // Only a host with HOST_VNC_AUTOCONNECT=true returns a password; others stay URL-clean.
  const { vncPasswordReady, withVncPassword } = useVncPassword(isVncDevice ? host : null);

  // The card's terminal error state. It replaces an `error` useState that had no
  // setter, so it was permanently null and the branch guarding it below could never
  // render — every non-player state fell through to "Loading stream..." instead.
  const previewError = streamError;

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
  // droneVideoReady: same again for a drone — its slot only appears once the drone is paired
  // and its video is live, long after streamUrl resolved; the video played off-screen (black).
  useLayoutEffect(() => {
    const target = isSelectedForModal && persistentStreamTarget
      ? persistentStreamTarget
      : groupStreamTarget ?? previewStreamSlotRef.current;
    if (target && persistentStreamRoot.parentElement !== target) {
      target.appendChild(persistentStreamRoot);
    }
  }, [isSelectedForModal, persistentStreamRoot, persistentStreamTarget, groupStreamTarget, streamUrl, showSnapshotImage, droneVideoReady]);

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

  // Clean display values - special handling for VNC devices. RECENTLY
  // the preview tile dropped the host suffix (TASK-116): the tile was already
  // cramped once the title row only has room for one identifier, and the host
  // is one click away (open the stream modal, the rec page header, or hover
  // the device for the tooltip). The modal title still keeps the " - host"
  // format in RecStreamModalHeader so the wider surface stays unambiguous.
  const displayName = device
    ? device.device_model === 'host_vnc'
      ? host.host_name // For VNC devices, show just the host name
      : device.device_name
    : host.host_name;

  // The tile label dropped the host suffix (TASK-116 above), but the host is
  // still part of the device's identity — the hover tooltip puts it back so the
  // operator can tell two same-named devices on different hosts apart without
  // opening the stream modal. VNC devices already show only the host, so they
  // get no suffix.
  const tooltipName = deviceTooltipName(
    host,
    device,
    device && device.device_model !== 'host_vnc' ? `${displayName} - ${host.host_name}` : displayName,
  );

  const isPausingForModal = Boolean(isAnyModalOpen);
  const pauseMessage = isPlayingInModal ? 'Playing in modal' : 'Preview paused';
  // Who is on the device (manual lock owner, else whoever launched the run) —
  // shown next to the script name, not instead of it.
  const lockOwnerLabel = manualControlLabel || scriptOwnerName;
  // The blue lock names the OPERATOR only, so a run whose lock carries no owner name
  // leaves that corner empty rather than repeating the script name from the right one.
  const lockBadgeShown = lockBadgeShows(lockOwnerLabel);
  // Bottom-right is the SCRIPT only. It used to print the owner too, and once
  // DeviceLockBadge took the operator name to bottom-left the same words showed up in
  // both corners — verified live on a manual-control tile, where the name appeared once
  // in the blue lock and again in this black pill. One corner, one fact: WHO is on the
  // device (left, blue lock), WHAT is running (right, here).
  const scriptNameBadge = hasNamedDeployment ? (
    <RunningScriptNameBadge
      scriptName={deploymentScriptLabel as string}
      maxChars={30}
      // Two absolutely-positioned badges on one tile only stay apart if they each keep
      // to their own share. RunningScriptNameBadge defaults to 85% of the width, which
      // on a narrow tile ran its black pill over the lock at bottom-left and hid it —
      // verified live on host-clone-2, where both badges printed the same script name
      // and the right one covered the left.
      sx={lockBadgeShown ? { maxWidth: '52%' } : undefined}
    />
  ) : null;

  // Bottom-left badges, as ONE row (owner 2026-10-22).
  //
  // Both facts belong to the DEVICE, not to the stream, so they render outside the
  // snapshot/live ternary below — the same reason DroneTelemetryOverlay sits above it.
  // Inside the ternary each one was only reachable from one branch, which is exactly how a
  // lock indicator ends up invisible on half the tiles that are locked.
  //
  // They also share one row rather than each being absolutely positioned on the same
  // corner: a farm device that was locked rendered two badges on top of each other, and
  // which one won depended on nothing the operator could see.
  const farmProvider = device?.device_farm_provider;
  const bottomLeftBadges =
    lockBadgeShown || farmProvider ? (
      <Box
        sx={{
          position: 'absolute',
          left: 8,
          bottom: 8,
          zIndex: 3,
          display: 'flex',
          alignItems: 'center',
          gap: 0.5,
          // Matches the share the script badge above was trimmed to, so the two corners
          // cannot meet in the middle however long the operator's name is.
          maxWidth: '46%',
          // Only the badges themselves take the pointer; the gaps between them must not
          // steal the click that opens the device.
          pointerEvents: 'none',
        }}
      >
        <DeviceLockBadge
          ownerName={lockOwnerLabel}
          scriptLockActive={hasNamedDeployment}
          maxChars={22}
          sx={{ position: 'relative', left: 'auto', bottom: 'auto', zIndex: 'auto', maxWidth: '100%', pointerEvents: 'auto' }}
        />
        <DeviceFarmBadge
          provider={farmProvider}
          sx={{ position: 'relative', left: 'auto', bottom: 'auto', zIndex: 'auto', pointerEvents: 'auto' }}
        />
      </Box>
    ) : null;

  return (
    <Card
      ref={cardRef}
      onMouseEnter={handleTileMouseEnter}
      onMouseLeave={handleTileMouseLeave}
      sx={{
        // TASK-116: the stream content area drives its own 16:9 (or 9:16 for
        // a phone) aspect ratio below, so the Card no longer needs a fixed
        // height. Letting the Card size to its header + 16:9 stream area means
        // a 16:9 stream fills the content area end-to-end with no horizontal
        // letterboxing, which the old `height: 180` produced because the
        // header strip pushed the content area wider than 16:9. The row above
        // (Rec.tsx Grid item) used to override `height: 100%` here to defeat
        // BUG-0452; that override is removed in Rec.tsx because the Card now
        // drives the row height itself.
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
              available on hover. Toolbar was slimmed down (BUG-0552) to make
              room: the device flags chip, the lock indicator, the Localize
              button, the AVQ feature link and the status dot are gone, leaving
              only the name and the favorite star (plus the edit-mode checkbox
              when relevant). The full lock / script state still appears in the
              running-script badge in the card body. */}
          <Box sx={{ flex: 1, mr: 0.5, minWidth: 0, display: 'flex', alignItems: 'center' }}>
            <DeviceInfoNameTooltip
              name={tooltipName}
              info={device?.device_info}
              gatewayInfo={device?.gateway_info}
            >
              <Typography variant="subtitle2" noWrap sx={{ minWidth: 0 }}>
                {displayName}
              </Typography>
            </DeviceInfoNameTooltip>
            <DeviceMaintenanceBadge hostName={host.host_name} deviceId={device?.device_id} />
          </Box>

          {/* Profile tag, right-aligned just left of the favourite star */}
          {showProfileBadge && device && <MonitorProfileBadge profile={getDeviceMonitorProfile(host, device)} services={host.system_stats?.monitor_profile_services?.[getDeviceMonitorProfile(host, device)]} />}

          {/* Selection checkbox in edit mode - positioned next to the favorite star */}
          {isEditMode && (
            <Checkbox
              size="small"
              checked={isSelected}
              onChange={(e) => onSelectionChange?.(e.target.checked)}
              sx={{
                p: 0.5,
                '& .MuiSvgIcon-root': {
                  fontSize: TYPOGRAPHY.navbarItem.size
                }
              }}
            />
          )}

          {/* Favorite star, top-right of the tile (TASK-99) */}
          {device && <DeviceFavoriteStar hostName={host.host_name} deviceId={device.device_id} />}
        </Box>
      )}

      {/* Content area - Stream preview or Runner badge. The aspectRatio
          below is what kills the black side-bars (TASK-116): the previous
          version was `flex: 1` which filled the post-header remainder of a
          fixed-height Card, leaving a content area wider than 16:9 and
          letterboxing every stream. Forcing the area to 16:9 (or 9:16 for a
          phone in fillMobileFrame / group slot) means the stream, the snapshot
          img and the VNC iframe each size to fill the box end-to-end, and the
          Card grows in height to make room — the row above no longer needs
          `height: 100%` overrides to keep the tile inside its grid item. */}
      <Box
        sx={{
          width: '100%',
          // "One full": stretch to fill the card (no 16:9 dead space below video).
          // All other layouts use fixed aspectRatio so the card sizes to the content.
          ...(isPartial
            ? { flex: 1, minHeight: 0 }
            : { aspectRatio: (isMobile && (fillMobileFrame || isInGroup)) ? '9 / 16' : '16 / 9' }),
          position: 'relative',
          overflow: 'hidden',
          backgroundColor: 'black',
        }}
      >
              {/* Drone battery + temperature, top-right on the video */}
              {isDrone && <DroneTelemetryOverlay host={host} device={device} status={droneWifi} />}
              {/* Monitor's Localize verdict, top-right on the video (tv_app profile, TASK-115) */}
              {!isDrone && <LocalizeVideoBadge host={host} device={device} />}
              {/* Blue lock + who holds the device, bottom-left. OUTSIDE the snapshot/live
                  ternary below, for the same reason the drone wifi overlay is: a lock is a
                  property of the device and must not depend on which branch the tile happens
                  to be in (a snapshot-mode tile took the snapshot branch, so a lock indicator
                  inside the ternary would have been missing on exactly the grids that are
                  too big to stream live). */}
              {bottomLeftBadges}
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
              {isDrone && !droneVideoReady && (
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
                    // Lets the text below hide itself when the tile is too small
                    // to fit it (container queries read this box's size).
                    containerType: 'size',
                  }}
                >
                  <Box
                    sx={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 0.25,
                      width: '100%',
                      height: '100%',
                      px: 1.5,
                      py: 0.5,
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
                        // Shrinks to the room the two text lines leave, so a short preview
                        // never crops the headline or the Scan row (the column is centred).
                        minHeight: 0,
                        flex: '0 1 auto',
                        maxHeight: 'calc(100% - 48px)',
                        width: 'auto',
                        objectFit: 'contain',
                        // Dim it a little so the text below stays the loudest
                        // thing in the tile.
                        opacity: 0.9,
                        filter: 'saturate(0.85)',
                      }}
                    />
                    {/* Headline and action row are one line each, whatever the card
                        width: a wrapping line changed the tile's height on every
                        state change, which read as flashing. */}
                    {/* Hidden when the tile has no room for it: only the drone
                        image and the Rescan/Scan chip remain. */}
                    <Typography
                      variant="body2"
                      align="center"
                      noWrap
                      sx={{
                        color: P.textPrimary,
                        fontWeight: 600,
                        maxWidth: '100%',
                        flexShrink: 0,
                        '@container (max-width: 240px) or (max-height: 150px)': { display: 'none' },
                      }}
                    >
                      {droneHeadline(droneWifi.state, droneWifi.droneName, device?.device_name)}
                    </Typography>
                    {/* Hint and action share a row: the preview area is ~110px
                        tall, and stacking the chip under the hint pushed it past
                        the bottom edge where it was clipped. */}
                    <Box sx={{ display: 'flex', flexWrap: 'nowrap', alignItems: 'center', justifyContent: 'center', gap: 1, whiteSpace: 'nowrap', maxWidth: '100%', minHeight: 24, flexShrink: 0 }}>
                      {/* droneHintLine owns the "never show a stale error" rule
                          and is unit-tested; keep the logic there, not here. */}
                      {(() => {
                        const hint = droneHintLine(droneWifi.state, droneWifi.busy);
                        if (!hint) return null;
                        return (
                          <Typography
                            variant="caption"
                            noWrap
                            sx={{
                              color: P.textMuted,
                              minWidth: 0,
                              '@container (max-width: 240px) or (max-height: 150px)': { display: 'none' },
                            }}
                          >
                            {hint}
                          </Typography>
                        );
                      })()}
                      {/* One indicator: the spinner sits inside the chip, after the word.
                          No chip while "Starting video…": the drone is paired, there is
                          nothing to scan for. The row keeps its height (minHeight). */}
                      {droneWifi.state !== 'connected' && (
                      <Chip
                        label={
                          droneWifi.busy ? (
                            <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
                              Scanning
                              <CircularProgress size={11} thickness={5} sx={{ color: 'inherit' }} />
                            </Box>
                          ) : droneWifi.state === 'error' ? (
                            'Rescan'
                          ) : (
                            'Scan'
                          )
                        }
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
                          flexShrink: 0,
                          cursor: droneWifi.busy ? 'default' : 'pointer',
                          color: P.accentText,
                          borderColor: P.accent,
                        }}
                      />
                      )}
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
          ) : streamUrl && !(isDrone && !droneVideoReady) ? (
            /* A drone's stream mounts only once it is paired AND the host writes
               fresh segments: before that the live playlist is missing (or a stale
               one is served) and the player sits on a black tile or its own
               "Stream connection issues" overlay over the drone placeholder. */
            isVncDevice ? (
              <Box
                sx={{
                  position: 'relative',
                  width: '100%',
                  height: '100%',
                  backgroundColor: 'black',
                  overflow: 'hidden',
                  // The pause overlay is an in-flow flex child; the VNC iframe
                  // fills the portal root and noVNC fits the framebuffer itself.
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
                      position: 'absolute',
                      inset: 0,
                      overflow: 'hidden',
                    }}
                  >
                    <iframe
                      src={withVncViewportScale(withVncCacheBust(withVncPassword(streamUrl)))}
                      style={{
                        border: 'none',
                        backgroundColor: '#000',
                        pointerEvents: persistentStreamInteractive ? 'auto' : 'none',
                        width: '100%',
                        height: '100%',
                      }}
                      title="VNC Desktop Preview"
                    />
                    {audioStreamUrl && isPlayingInModal ? <VncAudioTrack audioStreamUrl={audioStreamUrl} /> : null}
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
          ) : isDrone ? null : previewError ? (
            /* The request for this device's stream URL failed or timed out.
               (A drone never reaches this branch — it renders the wifi overlay
               above, which is the only status a drone should show: "Loading
               stream…" on top of "Checking…" is two answers to one question,
               and the generic one is always wrong for a device that only streams
               once it is paired and flying.)
               Until this branch existed the card ignored `streamError` entirely
               and fell through to "Loading stream..." below — so a host that
               could not be reached produced a transient toast and then a card
               that spun forever, which is the same trap as the HLS manifest 404:
               a terminal state dressed as progress. */
            <Box
              sx={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 1,
                color: 'error.main',
                px: 2,
              }}
            >
              <ErrorIcon sx={{ fontSize: TYPOGRAPHY.caption.size }} />
              <Typography variant="caption" align="center">
                {previewError}
              </Typography>
            </Box>
          ) : isStreamUrlLoading || !streamUrl ? (
            /* Still resolving. Bounded by useStream's 15 s deadline: past that the
               request lands in `previewError` above and this branch is left behind. */
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
          ) : (
            /* Resolved, no error, and still nothing to play — say so instead of
               claiming to be busy. */
            <Box
              sx={{
                height: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'text.secondary',
              }}
            >
              <Typography variant="caption" align="center">
                No stream available
              </Typography>
            </Box>
          )}
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
