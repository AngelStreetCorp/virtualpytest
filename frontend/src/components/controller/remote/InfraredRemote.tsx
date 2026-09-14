import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import { Box, Button, IconButton, Typography, CircularProgress } from '@mui/material';
import React, { useState, useEffect, useRef } from 'react';

import { useInfraredRemote } from '../../../hooks/controller';
import { Host } from '../../../types/common/Host_Types';
import { InfraredRemoteButton } from '../../../config/remote/infraredRemoteBase';

interface InfraredRemoteProps {
  host: Host;
  deviceId?: string;
  isConnected?: boolean;
  // onDisconnectComplete removed - disconnect button was removed
  // Publishes the IR transmitter health dot up to RemotePanel (shared with
  // the Bluetooth remote's dot). See docs/agent/devices/INFRARED.md §5.
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

export const InfraredRemote = React.memo(
  function InfraredRemote({
    host,
    deviceId,
    isConnected,
    // onDisconnectComplete removed
    onStatusChange,
    sx = {},
    isCollapsed,
    streamContainerDimensions,
  }: InfraredRemoteProps) {
    const {
      session,
      status,
      layoutConfig,
      handleConnect,
      // handleDisconnect removed
      handleRemoteCommand,
    } = useInfraredRemote(host, deviceId, isConnected);

    const [showOverlays, setShowOverlays] = useState(true);

    // IR transmitter health → status dot (same palette as BluetoothRemote).
    const dotColor: string = (() => {
      if (status === null) return '#888'; // grey — status not loaded yet
      if (!status.device_present) return '#d32f2f'; // red — lirc node missing
      if (!status.tx_probe_ok) return '#d32f2f'; // red — transmitter wedged
      if (status.last_send_ok === false) return '#d32f2f'; // red — last press failed
      if (status.healthy) return '#2e7d32'; // green — ready
      return '#d32f2f';
    })();
    const dotTooltip: string = status?.detail || 'IR status unknown';

    useEffect(() => {
      onStatusChange?.(dotColor, dotTooltip);
    }, [onStatusChange, dotColor, dotTooltip]);

    // Keep showOverlays state persistent when isCollapsed changes
    // This helps with button alignment as overlays remain visible by default

    // handleDisconnectWithCallback removed - disconnect button was removed

    // Handle button press. Deliberately NOT gated on isLoading: a remote must
    // accept rapid successive presses. The old `if (isLoading) return` swallowed
    // a 2nd fast click during the ~500ms server→host round-trip with no request
    // ever sent. Each press fires its own request; the host serialises sends.
    const handleButtonPress = (buttonKey: string) => {
      if (!session.connected) return;

      console.log(`[@component:InfraredRemote] Button pressed: ${buttonKey}`);
      void handleRemoteCommand(buttonKey);
    };

    // Calculate responsive remote scale based on available space
    const calculateRemoteScale = () => {
      // Base remote dimensions from config - match Android TV for consistency
      const baseHeight = 1800;

      // Determine available height based on context
      let availableHeight: number;

      if (streamContainerDimensions) {
        // Modal context: use the modal's stream container height
        // No disconnect button in modal, just reserve space for header (30px)
        availableHeight = streamContainerDimensions.height - 20;
        console.log(
          `[@component:InfraredRemote] Using modal container height: ${streamContainerDimensions.height}, available: ${availableHeight}`,
        );
      } else {
        // Floating panel context: use window height
        availableHeight = window.innerHeight - 120; // Reserve space for disconnect button
        console.log(
          `[@component:InfraredRemote] Using window height: ${window.innerHeight}, available: ${availableHeight}`,
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
        const headerHeight = layoutConfig.panel_layout.header.height 
          ? parseInt(layoutConfig.panel_layout.header.height.replace('px', ''), 10)
          : parseInt(layoutConfig.panel_layout.header.padding.replace('px', ''), 10) * 2 + 20; // fallback to padding calculation
        const actualCollapsedHeight = collapsedHeight - headerHeight;
        const actualExpandedHeight = expandedHeight - headerHeight;

        // Calculate scale ratio based on actual container size (excluding header)
        const heightRatio = actualCollapsedHeight / actualExpandedHeight;
        const widthRatio = collapsedWidth / expandedWidth; // 160/240 = 0.667

        // Use the smaller ratio to ensure remote fits in collapsed panel
        const panelReductionRatio = Math.min(heightRatio, widthRatio);

        // Apply the reduction ratio to the base scale
        const collapsedScale = baseScale * panelReductionRatio;

        return collapsedScale;
      }

      return baseScale;
    };

    // The button overlays are absolutely positioned in pixels (position.* ×
    // remoteScale), so remoteScale MUST equal the *actual* rendered scale of
    // the remote image — boxHeight / 1800. calculateRemoteScale() only
    // *predicts* that height and diverges from reality whenever the box is
    // width-constrained, shifting the overlays off the buttons. So we measure
    // the real image box and drive the scale from it; calculateRemoteScale is
    // only a pre-measurement fallback to avoid a first-frame flash. Mirrors
    // BluetoothRemote.tsx so the shared stb_remote.png overlays align identically.
    const REMOTE_BASE_HEIGHT = 1800;
    const imageBoxRef = useRef<HTMLDivElement | null>(null);
    const [measuredImageHeight, setMeasuredImageHeight] = useState(0);
    useEffect(() => {
      const el = imageBoxRef.current;
      if (!el) return undefined;
      const update = () => setMeasuredImageHeight(el.clientHeight);
      update();
      const ro = new ResizeObserver(update);
      ro.observe(el);
      return () => ro.disconnect();
    }, [session.connected, isCollapsed]);
    const remoteScale =
      measuredImageHeight > 0
        ? measuredImageHeight / REMOTE_BASE_HEIGHT
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
                    {session.error || 'Samsung IR Remote'}
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
                <VisibilityIcon sx={{ fontSize: 18 }} />
              ) : (
                <VisibilityOffIcon sx={{ fontSize: 18 }} />
              )}
            </IconButton>
          )}

          {/* Remote container with image background */}
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
            {/* Render clickable button overlays */}
            {Object.entries(
              streamContainerDimensions
                ? layoutConfig.button_layout_recmodal
                : layoutConfig.button_layout,
            ).map(([buttonId, button]) => {
              const typedButton = button as InfraredRemoteButton;
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
                    if (isCollapsed) {
                      return 'rgba(255, 255, 255, 0.1)'; // Always visible when collapsed for debugging
                    } else if (showOverlays) {
                      return 'rgba(255, 255, 255, 0.1)'; // Normal visibility when expanded
                    } else {
                      return 'rgba(255, 255, 255, 0.02)'; // 20% transparency for debugging when hidden
                    }
                  })(),
                  border: (() => {
                    if (isCollapsed) {
                      return '1px solid rgba(255, 255, 255, 0.5)'; // Always visible when collapsed for debugging
                    } else if (showOverlays) {
                      return '1px solid rgba(255, 255, 255, 0.3)'; // Normal visibility when expanded
                    } else {
                      return '1px solid rgba(255, 255, 255, 0.06)'; // 20% transparency for debugging when hidden
                    }
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
      // onDisconnectComplete comparison removed &&
      JSON.stringify(prevProps.sx) === JSON.stringify(nextProps.sx) &&
      prevProps.isCollapsed === nextProps.isCollapsed &&
      JSON.stringify(prevProps.streamContainerDimensions) ===
        JSON.stringify(nextProps.streamContainerDimensions)
    );
  },
);
