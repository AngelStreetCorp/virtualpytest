import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import { Box, Button, IconButton, Typography, CircularProgress } from '@mui/material';
import React, { useState, useCallback, useEffect } from 'react';

import { useAndroidTv } from '../../../hooks/controller/useAndroidTv';
import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { useDisabledRemoteKeys } from '../../../contexts/RemoteCommandSinkContext';
import { Host } from '../../../types/common/Host_Types';
import { TYPOGRAPHY } from '../../../constants/typography';

interface AndroidTvRemoteProps {
  host: Host;
  deviceId?: string;
  isConnected?: boolean;
  // onDisconnectComplete removed - disconnect button was removed
  // Publishes the ADB link + last-send health dot up to RemotePanel
  // (shared with the IR / Vega / Bluetooth remote dots). See
  // backend_host/src/controllers/remote/android_tv.py:get_health().
  onStatusChange?: (color: string, tooltip: string) => void;
  sx?: any;
  isCollapsed: boolean;
  streamContainerDimensions?: {
    width: number;
    height: number;
    x: number;
    y: number;
  };
}

export const AndroidTvRemote = React.memo(
  function AndroidTvRemote({
    host,
    deviceId,
    isConnected,
    // onDisconnectComplete removed
    onStatusChange,
    sx = {},
    isCollapsed,
    streamContainerDimensions,
  }: AndroidTvRemoteProps) {
    const {
      session,
      status,
      isLoading,
      layoutConfig,
      handleConnect,
      // handleDisconnect removed
      handleRemoteCommand,
    } = useAndroidTv(host, deviceId, isConnected);

    const [showOverlays, setShowOverlays] = useState(true);
    const P = useAgentChatPalette();

    // Android TV link + last-send health → status dot (same colour rules
    // as InfraredRemote so operators see one consistent "is this remote
    // working?" indicator across IR / Vega / BLE / Android TV).
    const dotColor: string = (() => {
      if (status === null) return P.textMuted; // grey — status not loaded yet
      if (!status.device_present) return P.error; // red — adb device missing
      if (!status.tx_probe_ok) return P.error; // red — adb shell wedged
      if (status.last_send_ok === false) return P.error; // red — last press failed
      if (status.healthy) return P.success; // green — ready
      return P.error;
    })();
    const dotTooltip: string = status?.detail || 'Android TV status unknown';

    useEffect(() => {
      onStatusChange?.(dotColor, dotTooltip);
    }, [onStatusChange, dotColor, dotTooltip]);

    // Keep showOverlays state persistent when isCollapsed changes
    // This helps with button alignment as overlays remain visible by default

    // Measured pixel height of the image container, used to derive remoteScale.
    // Button overlays are positioned via this same measurement (not the estimate
    // calculateRemoteScale() produces) so they always land on the actual rendered
    // button artwork instead of drifting when the estimate and the CSS-computed
    // aspect-ratio layout disagree.
    //
    // A callback ref (not useRef + useLayoutEffect keyed on isCollapsed/
    // streamContainerDimensions) because the container only mounts once
    // session.connected flips true — a dependency array that doesn't include
    // that transition never re-runs to pick up the newly-attached node, so
    // measuredContainerHeight would stay null and silently fall back to the
    // estimate forever.
    const [remoteContainerEl, setRemoteContainerEl] = useState<HTMLDivElement | null>(null);
    const remoteContainerRef = useCallback((node: HTMLDivElement | null) => {
      setRemoteContainerEl(node);
    }, []);
    const [measuredContainerHeight, setMeasuredContainerHeight] = useState<number | null>(null);

    // TASK-80 multi-profile group: keys outside the shared intersection render
    // greyed; clicks are dropped. Same as IR / BLE leaves.
    const disabledKeys = useDisabledRemoteKeys();
    const isKeyDisabled = (key: string): boolean => disabledKeys != null && !disabledKeys.has(key);

    useEffect(() => {
      if (!remoteContainerEl) return;

      const updateHeight = () =>
        setMeasuredContainerHeight(remoteContainerEl.getBoundingClientRect().height);
      updateHeight();

      const resizeObserver = new ResizeObserver(updateHeight);
      resizeObserver.observe(remoteContainerEl);
      return () => resizeObserver.disconnect();
    }, [remoteContainerEl]);

    // handleDisconnectWithCallback removed - disconnect button was removed

    // Handle button press with visual feedback
    const handleButtonPress = async (buttonKey: string) => {
      if (isLoading || !session.connected) return;

      console.log(`[@component:AndroidTvRemote] Button pressed: ${buttonKey}`);
      await handleRemoteCommand(buttonKey);
    };

    // Calculate responsive remote scale based on available space
    const calculateRemoteScale = () => {
      // Base remote dimensions from config
      const baseHeight = 1800;

      // Determine available height based on context
      let availableHeight: number;

      if (streamContainerDimensions) {
        // Modal context: use the modal's stream container height
        // No disconnect button in modal, just reserve space for header (30px)
        availableHeight = streamContainerDimensions.height - 20;
        console.log(
          `[@component:AndroidTvRemote] Using modal container height: ${streamContainerDimensions.height}, available: ${availableHeight}`,
        );
      } else {
        // Floating panel context: use window height
        availableHeight = window.innerHeight - 120; // Reserve space for disconnect button
        console.log(
          `[@component:AndroidTvRemote] Using window height: ${window.innerHeight}, available: ${availableHeight}`,
        );
      }

      // Calculate the base scale from available height
      const baseScale = availableHeight / baseHeight;

      if (isCollapsed) {
        // For collapsed state, apply panel ratio reduction to the base scale
        const collapsedHeight = parseInt(
          layoutConfig.panel_layout.collapsed.height.replace('px', ''),
          10,
        );
        const expandedHeight = parseInt(
          layoutConfig.panel_layout.expanded.height.replace('px', ''),
          10,
        );
        const collapsedWidth = parseInt(
          layoutConfig.panel_layout.collapsed.width.replace('px', ''),
          10,
        );
        const expandedWidth = parseInt(
          layoutConfig.panel_layout.expanded.width.replace('px', ''),
          10,
        );

        // Account for header height in both states
        const headerHeight = parseInt(layoutConfig.panel_layout.header.padding.replace('px', ''), 10) * 2 + 20; // padding top/bottom + icon space
        const actualCollapsedHeight = collapsedHeight - headerHeight; // 300 - 32 = 268
        const actualExpandedHeight = expandedHeight - headerHeight; // 600 - 32 = 568

        // Calculate scale ratio based on actual container size (excluding header)
        const heightRatio = actualCollapsedHeight / actualExpandedHeight; // 268/568 ≈ 0.47
        const widthRatio = collapsedWidth / expandedWidth; // 160/240 = 0.667

        // Use the smaller ratio to ensure remote fits in collapsed panel
        const panelReductionRatio = Math.min(heightRatio, widthRatio);

        // Apply the reduction ratio to the base scale
        const collapsedScale = baseScale * panelReductionRatio;

        return collapsedScale;
      }

      return baseScale;
    };

    const baseHeight = 1800;
    const remoteScale = measuredContainerHeight
      ? measuredContainerHeight / baseHeight
      : calculateRemoteScale();

    // Render remote interface with clickable buttons
    const renderRemoteInterface = () => {
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
                  <Typography variant="body2">Connecting...</Typography>
                </>
              ) : (
                <>
                  <Typography variant="body2" color="textSecondary">
                    {session.error || 'Android TV Remote'}
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

      return (
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
          {/* Hide/Show Labels Toggle Overlay Button - Panel Top Right */}
          {!isCollapsed && session.connected && (
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
                <VisibilityIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />
              ) : (
                <VisibilityOffIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />
              )}
            </IconButton>
          )}

          {/* Remote container with image background */}
          <Box
            ref={remoteContainerRef}
            data-testid="android-tv-remote-container"
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
            {/* Render clickable button overlays */}
            {Object.entries(
              streamContainerDimensions
                ? layoutConfig.button_layout_recmodal
                : layoutConfig.button_layout,
            ).map(([buttonId, button]) => {
              const keyDisabled = isKeyDisabled(button.key);
              return (
              <Box
                key={buttonId}
                sx={{
                  position: 'absolute',
                  left: `${(button.position.x + layoutConfig.remote_info.global_offset.x) * remoteScale + (isCollapsed ? 1 : 0)}px`,
                  top: `${(button.position.y + layoutConfig.remote_info.global_offset.y) * remoteScale + (isCollapsed ? 1 : 0)}px`,
                  width: `${button.size.width * layoutConfig.remote_info.button_scale_factor * remoteScale}px`,
                  height: `${button.size.height * layoutConfig.remote_info.button_scale_factor * remoteScale}px`,
                  borderRadius: button.shape === 'circle' ? '50%' : '4px',
                  backgroundColor: (() => {
                    if (keyDisabled) return 'rgba(102, 102, 102, 0.06)';
                    if (isCollapsed) return 'rgba(255, 255, 255, 0.1)';
                    if (showOverlays) return 'rgba(255, 255, 255, 0.1)';
                    return 'rgba(255, 255, 255, 0.02)';
                  })(),
                  border: (() => {
                    if (keyDisabled) return '1px solid rgba(102, 102, 102, 0.4)';
                    if (isCollapsed) return '1px solid rgba(255, 255, 255, 0.5)';
                    if (showOverlays) return '1px solid rgba(255, 255, 255, 0.3)';
                    return '1px solid rgba(255, 255, 255, 0.06)';
                  })(),
                  cursor: keyDisabled ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s ease-in-out',
                  '&:hover': keyDisabled
                    ? undefined
                    : {
                        backgroundColor: 'rgba(255, 255, 255, 0.2)',
                        transform: 'scale(1.05)',
                      },
                  '&:active': keyDisabled
                    ? undefined
                    : {
                        backgroundColor: 'rgba(255, 255, 255, 0.3)',
                        transform: 'scale(0.95)',
                      },
                }}
                onClick={() => {
                  if (keyDisabled) return;
                  handleButtonPress(button.key);
                }}
                title={keyDisabled
                  ? `${button.label} - not on every member's transport`
                  : `${button.label} - ${button.comment}`}
              >
                <Typography
                    variant="caption"
                    sx={{
                      // ui-ok: no-literal-font-size — per-remote dynamic sizing: the layout
                      // config gives a base fontSize in px and remoteScale is a per-instance
                      // zoom factor; the result is a real px value, not a role token.
                      fontSize: `${parseInt(layoutConfig.remote_info.text_style.fontSize) * remoteScale}px`, // ui-ok: no-literal-font-size - overlay text scales with the remote image
                      fontWeight: layoutConfig.remote_info.text_style.fontWeight,
                      color: keyDisabled ? 'rgba(160, 160, 160, 0.5)' : layoutConfig.remote_info.text_style.color,
                      textShadow: layoutConfig.remote_info.text_style.textShadow,
                      userSelect: 'none',
                      textDecoration: keyDisabled ? 'line-through' : 'none',
                    }}
                  >
                    {button.label}
                  </Typography>
              </Box>
              );
            })}
          </Box>
        </Box>
      );
    };

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
        {/* Remote Interface - takes most of the space */}
        <Box sx={{ flex: 1, overflow: 'hidden', minHeight: 0 }}>{renderRemoteInterface()}</Box>

        {/* Disconnect Button - REMOVED: Users can close panel or release control */}
      </Box>
    );
  },
  (prevProps, nextProps) => {
    // Memoization to prevent unnecessary re-renders
    return (
      prevProps.host?.host_name === nextProps.host?.host_name &&
      prevProps.deviceId === nextProps.deviceId &&
      prevProps.isConnected === nextProps.isConnected &&
      prevProps.onStatusChange === nextProps.onStatusChange &&
      // onDisconnectComplete comparison removed &&
      JSON.stringify(prevProps.sx) === JSON.stringify(nextProps.sx) &&
      prevProps.isCollapsed === nextProps.isCollapsed &&
      JSON.stringify(prevProps.streamContainerDimensions) ===
        JSON.stringify(nextProps.streamContainerDimensions)
    );
  },
);
