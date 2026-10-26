/**
 * Device Stream Grid Component
 * 
 * Extracted from RunTests.tsx to be shared between script runner and campaign interface.
 * This component displays multiple device streams in a responsive grid layout.
 */

import React, { useState, useEffect, useRef } from 'react';
import { Box, Typography, CircularProgress, Button } from '@mui/material';
import { HLSVideoPlayer } from '../HLSVideoPlayer';
import { useStream } from '../../../hooks/controller/useStream';
import { useHostSession } from '../../../hooks/useHostSession';
import { calculateVncScaling } from '../../../utils/vncUtils';
import { TYPOGRAPHY } from '../../../constants/typography';
import VncAudioTrack from '../../controller/av/VncAudioTrack';

// Component interfaces
export interface DeviceStreamGridProps {
  devices: {hostName: string, deviceId: string}[];
  allHosts: any[];
  getDevicesFromHost: (hostName: string) => any[];
  maxColumns?: number;
  isActive?: boolean; // Add prop to control stream lifecycle
  /**
   * Fill the parent container instead of using fixed preview-tile sizes.
   * Defaults to `true` when there is exactly one device, `false` otherwise
   * (RunTests/Campaign-style multi-device grids want the small preview).
   * Pass an explicit value to override the auto-detect.
   */
  expanded?: boolean;
}

interface DeviceStreamItemProps {
  device: {hostName: string, deviceId: string};
  allHosts: any[];
  getDevicesFromHost: (hostName: string) => any[];
  isActive?: boolean; // Add prop to control stream lifecycle
  /** Single-device fill-mode: stretch to the available container. */
  expanded?: boolean;
}

// Move previewHeight to top level
const PREVIEW_HEIGHT = 120; // Consistent preview box height
const PREVIEW_HEIGHT_MOBILE = 200; // Max height on mobile

// Individual device stream component
const DeviceStreamItem: React.FC<DeviceStreamItemProps> = ({ device, allHosts, getDevicesFromHost, isActive = true, expanded = false }) => {
  const hostObject = allHosts.find((host) => host.host_name === device.hostName);

  // Stream lifecycle management
  const [isStreamActive, setIsStreamActive] = useState(isActive);
  const [isVisible, setIsVisible] = useState(true);
  const effectiveDeviceId = device.deviceId || 'host';

  // Use stream hook to get device stream
  const { streamUrl, audioStreamUrl, isLoadingUrl, urlError } = useStream({
    host: hostObject!,
    device_id: effectiveDeviceId,
  });

  // Update stream active state when parent isActive prop changes
  useEffect(() => {
    setIsStreamActive(isActive && isVisible);
  }, [isActive, isVisible]);

  // Cleanup stream when component unmounts
  useEffect(() => {
    return () => {
      console.log(`[@component:DeviceStreamItem] Component unmounting, stopping stream for ${device.hostName}:${device.deviceId}`);
      setIsStreamActive(false);
    };
  }, [device.hostName, device.deviceId]);

  // Get device model
  const deviceObject = getDevicesFromHost(device.hostName).find(
    (d) => d.device_id === effectiveDeviceId
  );
  const deviceModel = deviceObject?.device_model || '';
  const isVnc = deviceModel === 'host_vnc';

  // The stream proxy's auth_request gate 401s /host/<name>/vnc_lite.html without the
  // host-session cookie, so the iframe is only mounted once the mint resolves (same
  // pattern as DevicePanel / VNCStream). Not keepAlive: only the handshake is gated.
  const vncSessionReady = useHostSession(isVnc ? streamUrl : null, false);
  const displayLabel = device.deviceId ? `${device.hostName}:${device.deviceId}` : device.hostName;
  const modelLabel = deviceModel && deviceModel !== 'unknown' ? ` (${deviceModel})` : '';
  
  // Check if mobile model for content adaptation
  const isMobileModel = !!(deviceModel && deviceModel.toLowerCase().includes('mobile'));

  // For VNC fill-mode, the iframe keeps its native 1440x847 layout box and is scaled with
  // a CSS transform; we need the actual stream-container size to recompute the scale, not
  // a hardcoded preview size.
  const streamBoxRef = useRef<HTMLDivElement | null>(null);
  const [vncBoxSize, setVncBoxSize] = useState<{ width: number; height: number }>({
    width: 300,
    height: PREVIEW_HEIGHT - 24,
  });
  useEffect(() => {
    if (!expanded || !isVnc) return;
    const el = streamBoxRef.current;
    if (!el) return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      // Subtract the label-bar height so the scaled render centres inside the stream box
      const labelBar = el.firstElementChild as HTMLElement | null;
      const labelH = labelBar?.getBoundingClientRect().height ?? 0;
      setVncBoxSize({
        width: Math.max(64, Math.floor(rect.width)),
        height: Math.max(48, Math.floor(rect.height - labelH)),
      });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [expanded, isVnc]);

  return (
    <Box
      sx={{
        backgroundColor: 'black',
        borderRadius: 1,
        overflow: 'hidden',
        width: '100%', // Let grid control width, content adapts inside
        height: expanded ? '100%' : 'auto',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        minHeight: 0,
      }}
    >
      {/* Device label */}
      <Box sx={{ px: 1, py: 0.5, backgroundColor: 'rgba(0,0,0,0.8)', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 0.5, flexShrink: 0 }}>
        <Typography variant="caption" noWrap>
          {displayLabel}{modelLabel}
        </Typography>
        <Button
          size="small"
          variant="text"
          color="inherit"
          onClick={() => setIsVisible((prev) => !prev)}
          sx={{ minWidth: 56, px: 0.5, py: 0, fontSize: TYPOGRAPHY.microMeta.size }}
        >
          {isVisible ? 'Hide' : 'Show'}
        </Button>
      </Box>
      
      {/* Stream content */}
      <Box
        ref={streamBoxRef}
        sx={{
          height: expanded ? { xs: '60vh', sm: '100%' } : { xs: PREVIEW_HEIGHT_MOBILE, sm: PREVIEW_HEIGHT },
          flex: expanded ? '1 1 auto' : '0 0 auto',
          position: 'relative',
          backgroundColor: 'black',
          overflow: 'hidden', // Ensure content doesn't overflow
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: 0,
        }}
      >
        {!isVisible ? (
          <Typography variant="caption" color="text.secondary">
            Stream hidden
          </Typography>
        ) : streamUrl && hostObject && (!isVnc || vncSessionReady) ? (
          // VNC devices: Show iframe, Others: Use HLSVideoPlayer
          isVnc ? (
            <Box
              sx={{
                position: 'relative',
                width: '100%',
                height: '100%',
                backgroundColor: 'black',
                overflow: 'hidden',
              }}
            >
              <iframe
                src={streamUrl}
                style={{
                  border: 'none',
                  backgroundColor: '#000',
                  pointerEvents: 'none',
                  display: 'block',
                  margin: '0 auto',
                  ...calculateVncScaling(expanded ? vncBoxSize : { width: 300, height: PREVIEW_HEIGHT - 24 }), // In fill-mode the stream box is measured, not a hard-coded preview size
                }}
                title={`VNC Desktop - ${device.hostName}:${device.deviceId}`}
                allow="fullscreen"
              />
              {audioStreamUrl ? <VncAudioTrack audioStreamUrl={audioStreamUrl} /> : null}
            </Box>
          ) : (
            // Absolute fill inside fixed-height container to strictly clamp size
            <Box sx={{ position: 'absolute', inset: 0 }}>
              <HLSVideoPlayer
                streamUrl={streamUrl}
                isStreamActive={isStreamActive}
                isCapturing={false}
                model={deviceModel}
                layoutConfig={{
                  minHeight: '0px',
                  aspectRatio: isMobileModel ? '9/16' : '16/9',
                  objectFit: 'contain',
                  isMobileModel,
                }}
                isExpanded={false}
                muted={true}
                sx={{
                  width: '100%',
                  height: '100%',
                  '& video': {
                    width: '100% !important',
                    height: '100% !important',
                    objectFit: 'contain !important',
                  },
                }}
              />
            </Box>
          )
        ) : (
          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'white',
              textAlign: 'center',
              height: '100%',
            }}
          >
            {/* Error is checked BEFORE the VNC-loading case. A VNC device keeps a stream URL
                for 24 h (useStream's cache), so `isVnc && streamUrl` stayed true
                after the fetch failed — and because this branch came first, the
                error underneath was unreachable: a broken VNC device showed
                "Loading..." forever with its real cause sitting in `urlError`.
                The VNC case means "waiting for the iframe to paint", which is only
                true while there is no error. */}
            {urlError ? (
              <>
                <Typography color="error" variant="caption" sx={{ mb: 1 }}>
                  Stream Error
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ fontSize: TYPOGRAPHY.microMeta.size }}>
                  {urlError}
                </Typography>
              </>
            ) : isLoadingUrl || (isVnc && streamUrl && hostObject) ? (
              <>
                <CircularProgress sx={{ color: 'white', mb: 1 }} size={20} />
                <Typography variant="caption">Loading...</Typography>
              </>
            ) : (
              <Typography variant="caption">No stream available</Typography>
            )}
          </Box>
        )}
      </Box>
    </Box>
  );
};

// Main grid component
export const DeviceStreamGrid: React.FC<DeviceStreamGridProps> = ({
  devices,
  allHosts,
  getDevicesFromHost,
  maxColumns = 3,
  isActive = true,
  expanded,
}) => {
  // Auto-fill-mode when there is exactly one device: the tile should grow to use the full
  // container instead of staying at the fixed preview-tile height (RunTests/Campaign style).
  // Multi-device grids keep the small-tile layout. Callers can override with an explicit value.
  const fill = expanded ?? devices.length === 1;
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: `repeat(${Math.min(devices.length, maxColumns)}, 1fr)`,
        gridTemplateRows: fill ? 'minmax(0, 1fr)' : undefined,
        gap: 2,
        width: '100%',
        height: fill ? '100%' : 'auto',
        alignSelf: fill ? 'stretch' : undefined,
        gridAutoRows: fill ? undefined : { xs: `${PREVIEW_HEIGHT_MOBILE}px`, sm: `${PREVIEW_HEIGHT}px` },
      }}
    >
      {devices.map((device, index) => (
        <DeviceStreamItem
          key={`${device.hostName}-${device.deviceId}-${index}`}
          device={device}
          allHosts={allHosts}
          getDevicesFromHost={getDevicesFromHost}
          isActive={isActive}
          expanded={fill}
        />
      ))}
    </Box>
  );
};
