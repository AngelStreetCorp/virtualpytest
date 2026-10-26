import { DragIndicator, OpenInFull, PictureInPictureAlt, Restore } from '@mui/icons-material';
import { Box, IconButton, Tooltip, Typography } from '@mui/material';
import React, { useCallback, useEffect, useRef, useState } from 'react';

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
import type { PipPosition, PipSelection } from '../types';

/**
 * The floating stream (+ remote while PiP holds control), over every page. Also the one
 * place that enforces the rules: pause when a page takes control, release on device change
 * and when the mod goes away.
 *
 * The whole panel shell is draggable from its header (except clicks on the header buttons
 * themselves, which still take control, minimize, expand / collapse or hide the remote).
 * Drag offset persists in localStorage so the placement survives reloads and is re-clamped
 * on resize so the panel can never reopen off-screen.
 */
export const PipOverlay: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { isMobile } = useResponsiveMode();
  const {
    state,
    host,
    device,
    paused,
    showRemote,
    setCollapsed,
    setPosition: setPos,
    reclampPosition,
  } = usePip();
  const { release } = usePipControl();
  const position = state.position;

  // Live drag offset: pos.x / pos.y mirror the saved offset, but updating them on every
  // pointer-move (instead of writing to the store) keeps the drag at 60 fps. The store
  // is only written on pointer-up.
  const [liveOffset, setLiveOffset] = useState<PipPosition>(position ?? { x: 0, y: 0 });
  const dragStateRef = useRef<{
    pointerId: number;
    startClientX: number;
    startClientY: number;
    startOffset: PipPosition;
  } | null>(null);
  const shellRef = useRef<HTMLDivElement | null>(null);

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
    const switched =
      held.selection &&
      (held.selection.hostName !== state.selection?.hostName ||
        held.selection.deviceId !== state.selection?.deviceId);
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

  // Follow the saved offset when it changes from outside the drag (e.g. localStorage load).
  useEffect(() => {
    if (!dragStateRef.current) setLiveOffset(position ?? { x: 0, y: 0 });
  }, [position?.x, position?.y]);

  // Re-clamp on viewport resize so a smaller window cannot reopen the panel off-screen.
  useEffect(() => {
    const handleResize = () => {
      const el = shellRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      reclampPosition(rect, window.innerWidth, window.innerHeight);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [reclampPosition]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      // The drag handle is the header strip; ignore clicks on its buttons so they still
      // fire (minimize / expand / collapse / take-control / release-control / hide-remote).
      const handle = e.currentTarget;
      const interactive = (e.target as HTMLElement).closest(
        'button, [role="button"], a, input, textarea, select, [data-no-drag="true"]',
      );
      if (interactive) return;
      e.preventDefault();
      handle.setPointerCapture(e.pointerId);
      dragStateRef.current = {
        pointerId: e.pointerId,
        startClientX: e.clientX,
        startClientY: e.clientY,
        startOffset: liveOffset,
      };
      handle.style.cursor = 'grabbing';
    },
    [liveOffset],
  );

  const onPointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragStateRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const dx = e.clientX - drag.startClientX;
    const dy = e.clientY - drag.startClientY;
    setLiveOffset({ x: drag.startOffset.x + dx, y: drag.startOffset.y + dy });
  }, []);

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const drag = dragStateRef.current;
      if (!drag || drag.pointerId !== e.pointerId) return;
      const el = shellRef.current;
      if (el && el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
      if (el) el.style.cursor = 'grab';
      dragStateRef.current = null;
      if (el) {
        const rect = el.getBoundingClientRect();
        setPos(liveOffset, rect, window.innerWidth, window.innerHeight);
      }
    },
    [liveOffset, setPos],
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
          bgcolor: P.surfaceSolid,
          border: `1px solid ${P.borderColor}`,
        }}
      >
        <Typography sx={{ fontSize: '0.75rem', color: P.textSecondary }}>
          {t('Picture-in-picture paused while a page controls a device')}
        </Typography>
      </Box>
    );
  }

  // The user collapsed PiP from the top-bar menu: show a small chip with a Show button.
  if (state.collapsed) {
    return (
      <Box
        sx={{
          position: 'fixed',
          inset: 0,
          pointerEvents: 'none',
          zIndex: getZIndex('HDMI_STREAM'),
        }}
      >
        <Box
          ref={shellRef}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          sx={{
            position: 'absolute',
            right: EDGE,
            bottom: BOTTOM,
            transform: `translate(${position?.x ?? 0}px, ${position?.y ?? 0}px)`,
            display: 'flex',
            alignItems: 'center',
            gap: 0.75,
            px: 1.5,
            py: 0.75,
            borderRadius: 2,
            bgcolor: P.surfaceSolid,
            border: `1px solid ${P.borderColor}`,
            cursor: 'grab',
            touchAction: 'none',
            pointerEvents: 'auto',
            boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
            '&:hover': { borderColor: P.accent },
          }}
        >
          <DragIndicator sx={{ fontSize: 14, color: P.textMuted }} />
          <PictureInPictureAlt sx={{ fontSize: 16, color: P.textSecondary }} />
          <Typography sx={{ fontSize: '0.75rem', color: P.textSecondary }}>
            {device.device_name || device.device_id}
          </Typography>
          <Tooltip title={t('Show')}>
            <IconButton
              size="small"
              onClick={() => setCollapsed(false)}
              sx={{ color: P.textSecondary, '&:hover': { color: P.accent } }}
            >
              <OpenInFull sx={{ fontSize: 16 }} />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>
    );
  }

  const anchor = streamPosition(showRemote);
  // The shell is the anchor point in the viewport (bottom-right, or bottom-left when the
  // remote is shown). The panels inside it are positioned absolutely, so their offsets are
  // read against the shell, not against the viewport: passing the viewport offsets again
  // would place the panel twice as far from the corner as it should be (BUG-0777).
  const panelAnchor = showRemote ? { left: '0px', bottom: '0px' } : { right: '0px', bottom: '0px' };
  // Live offset is what the user is currently dragging; saved position is the resting spot.
  // While dragging, show the live offset; otherwise show the saved one so the saved value
  // matches what is rendered (no jitter on reload).
  const displayOffset = dragStateRef.current ? liveOffset : position ?? { x: 0, y: 0 };

  return (
    // Click-through layer: only the panels themselves take the mouse.
    <Box
      sx={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        zIndex: getZIndex('HDMI_STREAM'),
      }}
    >
      <Box
        ref={shellRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        sx={{
          position: 'absolute',
          ...anchor,
          transform: `translate(${displayOffset.x}px, ${displayOffset.y}px)`,
          cursor: 'grab',
          touchAction: 'none',
          pointerEvents: 'auto',
          // Visual cue that the panel is draggable: a small grip at the top of the panel.
          '&::before': {
            content: '""',
            position: 'absolute',
            top: 0,
            left: '50%',
            transform: 'translateX(-50%)',
            width: 36,
            height: 4,
            borderRadius: '0 0 4px 4px',
            bgcolor: P.accent,
            opacity: 0.6,
          },
        }}
      >
        {/* Collapse-to-chip control — pinned to the panel so it is always reachable,
            independent of the panel's internal minimize / expand-collapse buttons. */}
        <Tooltip title={t('Collapse picture-in-picture')}>
          <IconButton
            size="small"
            onClick={() => setCollapsed(true)}
            data-no-drag="true"
            sx={{
              position: 'absolute',
              top: -10,
              right: -10,
              zIndex: 1,
              bgcolor: P.surfaceSolid,
              border: `1px solid ${P.borderColor}`,
              color: P.textSecondary,
              '&:hover': { color: P.accent, borderColor: P.accent },
              width: 24,
              height: 24,
            }}
          >
            <Restore sx={{ fontSize: 14 }} />
          </IconButton>
        </Tooltip>
        <DeviceControlPanels
          showRemotePanel={showRemote}
          showAVPanel
          selectedHost={host}
          selectedDeviceId={device.device_id}
          isControlActive={state.ownsControl}
          isSidebarOpen={false}
          footerHeight={FOOTER_HEIGHT}
          customPosition={panelAnchor}
          handleDisconnectComplete={() => void release(host, device.device_id)}
        />
      </Box>
    </Box>
  );
};