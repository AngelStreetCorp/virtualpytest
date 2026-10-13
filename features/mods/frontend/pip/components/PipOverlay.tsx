import { PauseCircleOutline } from '@mui/icons-material';
import { Box, Typography } from '@mui/material';
import React, { useEffect, useRef } from 'react';

import { DeviceControlPanels } from '../../../../../frontend/src/components/common/DeviceControlPanels';
import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useResponsiveMode } from '../../../../../frontend/src/hooks/useResponsiveMode';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import { getZIndex } from '../../../../../frontend/src/utils/zIndexUtils';
import { shouldReleaseOnPause, streamPosition } from '../actions';
import { BOTTOM, EDGE, FOOTER_HEIGHT } from '../constants';
import { pipStore } from '../data/store';
import { usePip } from '../hooks/usePip';
import { usePipControl } from '../hooks/usePipControl';
import type { PipSelection } from '../types';

/**
 * The floating stream (+ remote while PiP holds control), over every page. Also the one
 * place that enforces the rules: pause when a page takes control, release on device change
 * and when the mod goes away.
 */
export const PipOverlay: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { isMobile } = useResponsiveMode();
  const { state, host, device, paused, showRemote } = usePip();
  const { release } = usePipControl();

  // A page took control: release ours (unless it took the same device, then hand over).
  useEffect(() => {
    if (!paused || !state.ownsControl || state.controlBusy) return;
    if (shouldReleaseOnPause(state) && host && state.selection) void release(host, state.selection.deviceId);
    else pipStore.update((s) => ({ ...s, ownsControl: false }));
  }, [paused, state, host, release]);

  // Switching device, or closing PiP, while holding control releases the previous device.
  const heldRef = useRef<{ host: typeof host; selection: PipSelection | null }>({ host: null, selection: null });
  useEffect(() => {
    const held = heldRef.current;
    const switched = held.selection && (held.selection.hostName !== state.selection?.hostName || held.selection.deviceId !== state.selection?.deviceId);
    if (switched && held.host && held.selection) void release(held.host, held.selection.deviceId);
    heldRef.current = state.ownsControl ? { host, selection: state.selection } : { host: null, selection: null };
  }, [state.ownsControl, state.selection, host, release]);

  // Mod switched off (overlay unmounted) while holding control.
  const releaseRef = useRef(release);
  releaseRef.current = release;
  useEffect(
    () => () => {
      const { host: h, selection } = heldRef.current;
      if (h && selection) void releaseRef.current(h, selection.deviceId);
    },
    [],
  );

  if (isMobile || !state.selection || !host || !device) return null;

  if (paused) {
    return (
      <Box
        sx={{
          position: 'fixed',
          right: EDGE,
          bottom: BOTTOM,
          zIndex: getZIndex('HDMI_STREAM'),
          display: 'flex',
          alignItems: 'center',
          gap: 0.75,
          px: 1.5,
          py: 0.75,
          borderRadius: 2,
          bgcolor: P.surface,
          border: `1px solid ${P.borderColor}`,
        }}
      >
        <PauseCircleOutline sx={{ fontSize: 18, color: P.textMuted }} />
        <Typography sx={{ fontSize: '0.75rem', color: P.textSecondary }}>
          {t('Picture-in-picture paused while a page controls a device')}
        </Typography>
      </Box>
    );
  }

  const position = streamPosition(showRemote);

  return (
    // Click-through layer: only the panels themselves take the mouse.
    <Box
      sx={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        zIndex: getZIndex('HDMI_STREAM'),
        '& > *': { pointerEvents: 'auto' },
      }}
    >
      <DeviceControlPanels
        showRemotePanel={showRemote}
        showAVPanel
        selectedHost={host}
        selectedDeviceId={device.device_id}
        isControlActive={state.ownsControl}
        isSidebarOpen={false}
        footerHeight={FOOTER_HEIGHT}
        customPosition={position}
        handleDisconnectComplete={() => void release(host, device.device_id)}
      />
    </Box>
  );
};
