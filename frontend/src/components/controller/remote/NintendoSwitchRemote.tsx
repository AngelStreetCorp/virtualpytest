import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import { Alert, Box, Button, IconButton, Tooltip, Typography } from '@mui/material';
import React, { useCallback, useEffect, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import {
  nintendoSwitchRemoteConfig,
  SwitchHotspot,
} from '../../../config/remote/nintendoSwitchRemote';
import { useControllerApi } from '../../../hooks/controller/useControllerApi';
import { Host } from '../../../types/common/Host_Types';

interface NintendoSwitchRemoteProps {
  host: Host;
  deviceId?: string;
  isCollapsed: boolean;
  sx?: any;
}

interface ProconStatus {
  success: boolean;
  state?: 'connected' | 'reconnecting' | 'pairing' | 'disconnected' | 'daemon_down' | string;
  switch_address?: string | null;
  last_error?: string | null;
  error?: string;
  warning?: string;
  pair_window_remaining_s?: number;
}

const STATUS_POLL_MS = 3000;

const { remote_info: info, hotspots } = nintendoSwitchRemoteConfig;
const CANVAS_W = info.image_size.width;
const CANVAS_H = info.image_size.height + info.top_strip_height;

export const NintendoSwitchRemote = React.memo(function NintendoSwitchRemote({
  host,
  deviceId,
  isCollapsed,
  sx = {},
}: NintendoSwitchRemoteProps) {
  const P = useAgentChatPalette();
  // STATE_STYLE depends on the palette, so build it inside the component.
  const STATE_STYLE: Record<string, { color: string; label: string }> = {
    connected: { color: P.success, label: 'Connected' },
    reconnecting: { color: P.warning, label: 'Reconnecting…' },
    pairing: { color: P.accentText, label: 'Pairing' },
    disconnected: { color: P.error, label: 'Disconnected' },
    daemon_down: { color: P.error, label: 'Controller daemon down' },
  };
  const { postToHost } = useControllerApi(host, deviceId);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<ProconStatus | null>(null);
  const [showOverlays, setShowOverlays] = useState(true);

  // Fit the photo (+ trigger strip) into the available area and drive the
  // hotspot scale from the real rendered width.
  const areaRef = useRef<HTMLDivElement | null>(null);
  const [area, setArea] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = areaRef.current;
    if (!el) return undefined;
    const update = () => setArea({ width: el.clientWidth, height: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const canvasWidth = Math.max(0, Math.min(area.width, (area.height * CANVAS_W) / CANVAS_H));
  const scale = canvasWidth / CANVAS_W;

  const refreshStatus = useCallback(async () => {
    try {
      const result = await postToHost<ProconStatus>(
        '/server/av/switch/status',
        {},
        { includeDeviceId: true },
      );
      setStatus(result);
    } catch (requestError: any) {
      setStatus({ success: false, state: 'disconnected', error: requestError?.message });
    }
  }, [postToHost]);

  useEffect(() => {
    void refreshStatus();
    const timer = setInterval(() => void refreshStatus(), STATUS_POLL_MS);
    return () => clearInterval(timer);
  }, [refreshStatus]);

  // Not gated on a pending flag: a remote must accept rapid successive
  // presses; the daemon serialises them.
  const sendCommand = useCallback(
    async (command: string) => {
      setError(null);
      try {
        const result = await postToHost<{ success: boolean; error?: string }>(
          '/server/av/switch/command',
          { command },
          { includeDeviceId: true },
        );
        if (!result.success) setError(result.error || `${command} failed`);
      } catch (requestError: any) {
        setError(requestError?.message || `${command} failed`);
      }
      if (command === 'pair') void refreshStatus();
    },
    [postToHost, refreshStatus],
  );

  const state = status?.state || 'unknown';
  const stateStyle = STATE_STYLE[state] || { color: '#888', label: 'Status unknown' };
  const statusDetail =
    state === 'pairing'
      ? `Open Controllers → Change Grip/Order on the Switch${
          status?.pair_window_remaining_s !== undefined
            ? ` (${status.pair_window_remaining_s}s left)`
            : ''
        }`
      : state === 'connected'
        ? status?.switch_address || ''
        : status?.last_error || status?.error || '';

  const renderHotspot = (id: string, spot: SwitchHotspot) => {
    const width = spot.width * scale;
    const height = spot.height * scale;
    return (
      <Box
        key={id}
        onClick={() => void sendCommand(spot.command)}
        title={`${spot.label || spot.comment} - ${spot.command}`}
        sx={{
          position: 'absolute',
          left: `${spot.x * scale - width / 2}px`,
          top: `${(spot.y + info.top_strip_height) * scale - height / 2}px`,
          width: `${width}px`,
          height: `${height}px`,
          borderRadius: spot.shape === 'circle' ? '50%' : '4px',
          backgroundColor: showOverlays ? 'rgba(255, 255, 255, 0.1)' : 'rgba(255, 255, 255, 0.02)',
          border: showOverlays
            ? '1px solid rgba(255, 255, 255, 0.3)'
            : '1px solid rgba(255, 255, 255, 0.06)',
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
      >
        {showOverlays && spot.label && (
          <Typography
            variant="caption"
            sx={{
              fontSize: `${Math.max(8, parseInt(info.text_style.fontSize, 10) * scale)}px`,
              fontWeight: info.text_style.fontWeight,
              color: info.text_style.color,
              textShadow: info.text_style.textShadow,
              userSelect: 'none',
              lineHeight: 1,
            }}
          >
            {spot.label}
          </Typography>
        )}
      </Box>
    );
  };

  return (
    <Box
      sx={{
        ...sx,
        display: 'flex',
        flexDirection: 'column',
        gap: 0.75,
        p: isCollapsed ? 0.75 : 1,
        overflow: 'hidden',
        minHeight: 0,
      }}
    >
      {/* Connection status + Pair */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minHeight: 28 }}>
        <Tooltip title={statusDetail || stateStyle.label}>
          <Box
            sx={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              backgroundColor: stateStyle.color,
              flexShrink: 0,
            }}
          />
        </Tooltip>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="caption" sx={{ fontWeight: 'bold', display: 'block', lineHeight: 1.2 }}>
            {stateStyle.label}
          </Typography>
          {!isCollapsed && statusDetail && (
            <Typography
              variant="caption"
              color="textSecondary"
              sx={{ display: 'block', lineHeight: 1.2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
            >
              {statusDetail}
            </Typography>
          )}
        </Box>
        <Tooltip title="Pair: then open Controllers → Change Grip/Order on the Switch">
          <span>
            <Button
              size="small"
              variant="outlined"
              disabled={state === 'pairing' || state === 'daemon_down'}
              onClick={() => void sendCommand('pair')}
              sx={{ minWidth: 0, px: 1, py: 0.25, fontSize: '0.7rem' }}
            >
              Pair
            </Button>
          </span>
        </Tooltip>
        {!isCollapsed && (
          <IconButton
            size="small"
            onClick={() => setShowOverlays(!showOverlays)}
            title={showOverlays ? 'Hide button overlays' : 'Show button overlays'}
            sx={{ p: 0.5 }}
          >
            {showOverlays ? (
              <VisibilityIcon sx={{ fontSize: 18 }} />
            ) : (
              <VisibilityOffIcon sx={{ fontSize: 18 }} />
            )}
          </IconButton>
        )}
      </Box>

      {state === 'pairing' && !isCollapsed && (
        <Alert severity="info" sx={{ py: 0 }}>
          On the Switch: Controllers → Change Grip/Order. The Pro Controller pairs by itself.
        </Alert>
      )}
      {status?.warning && <Alert severity="warning" sx={{ py: 0 }}>{status.warning}</Alert>}
      {error && (
        <Alert severity="error" sx={{ py: 0 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Controller photo with clickable hotspots; ZL/ZR in the strip above */}
      <Box
        ref={areaRef}
        sx={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      >
        <Box
          sx={{
            position: 'relative',
            width: `${canvasWidth}px`,
            height: `${canvasWidth * (CANVAS_H / CANVAS_W)}px`,
          }}
        >
          <Box
            component="img"
            src={info.image_url}
            alt={info.name}
            draggable={false}
            sx={{
              position: 'absolute',
              left: 0,
              top: `${info.top_strip_height * scale}px`,
              width: '100%',
              height: `${info.image_size.height * scale}px`,
              userSelect: 'none',
              pointerEvents: 'none',
            }}
          />
          {scale > 0 && Object.entries(hotspots).map(([id, spot]) => renderHotspot(id, spot))}
        </Box>
      </Box>
    </Box>
  );
});
