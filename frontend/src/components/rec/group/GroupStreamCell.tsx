import { Box, Checkbox, Chip, FormControlLabel, Typography, alpha } from '@mui/material';
import React, { useCallback, useEffect, useRef, useState } from 'react';

import { isMobileModel } from '../../../config/layoutConfig';
import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { useI18n } from '../../../i18n/useI18n';
import type { GroupMember } from '../../../types/pages/groupControl.types';
import { formatRemoteProfile } from '../../../utils/remoteProfileUtils';
import { RecHostPreview } from '../RecHostPreview';

import { fetchScreenAspect, screenPointOf } from './groupControl.actions';
import { GroupStatusLed } from './GroupStatusLed';
import { DeviceMaintenanceBadge } from '../../common/DeviceMaintenanceBadge';
import { TYPOGRAPHY } from '../../../constants/typography';

interface GroupStreamCellProps {
  member: GroupMember;
  isFocused: boolean;
  /** Show the transport chip — only when the group drives devices over different transports. */
  showProfile: boolean;
  onToggleFocus: (key: string) => void;
  onIncludedChange: (key: string, included: boolean) => void;
  /** Phones: a click on the stream taps that point (0..1 of the screen) on every targeted phone. */
  onTap?: (key: string, point: { x_pct: number; y_pct: number }) => void;
  /**
   * Set when the page tile of this device already plays live: the cell renders an empty slot
   * and reports it here, and the page tile moves its player into it instead of this cell
   * starting a second stream.
   */
  onStreamSlot?: (key: string, el: HTMLElement | null) => void;
}

/** One stream in the group tile: live preview filling its layout slot, ack of the last command, include + focus controls. */
export const GroupStreamCell: React.FC<GroupStreamCellProps> = ({
  member,
  isFocused,
  showProfile,
  onToggleFocus,
  onIncludedChange,
  onTap,
  onStreamSlot,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { host, device, controlled } = member;
  const isMobile = isMobileModel(device.device_model);
  const tapsPhone = isMobile && controlled && Boolean(onTap);

  // The phone's screen aspect places a click on its screen inside the streamed frame.
  const [screenAspect, setScreenAspect] = useState<number | null>(null);
  useEffect(() => {
    if (!tapsPhone) return undefined;
    let alive = true;
    void fetchScreenAspect(member).then((a) => alive && setScreenAspect(a));
    return () => {
      alive = false;
    };
  }, [tapsPhone, member.key]);

  // Stable per key: a new callback each render would detach/re-attach the slot every render.
  const streamSlotRef = useCallback(
    (el: HTMLDivElement | null) => onStreamSlot?.(member.key, el),
    [onStreamSlot, member.key],
  );

  const streamRef = useRef<HTMLDivElement | null>(null);
  const [tapMark, setTapMark] = useState<{ x: number; y: number; id: number } | null>(null);
  const handleStreamClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const box = streamRef.current;
    // The click layer is a sibling of the preview; their parent holds the playing <video>/<img>.
    if (!box?.parentElement || !onTap) return;
    const point = screenPointOf(e.clientX, e.clientY, box.parentElement, screenAspect);
    if (!point) return;
    const r = box.getBoundingClientRect();
    setTapMark({ x: e.clientX - r.left, y: e.clientY - r.top, id: Date.now() });
    onTap(member.key, point);
  };

  return (
    <Box
      sx={{
        height: '100%',
        border: `1px solid ${isFocused ? P.accent : P.borderColor}`,
        borderRadius: 1,
        overflow: 'hidden',
        bgcolor: P.surface,
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Box sx={{ position: 'relative', flex: 1, minHeight: 0, bgcolor: P.hoverBg }}>
        {controlled ? (
          // The preview card has a fixed tile height; stretch it to this slot. A phone gets a
          // centred 9:16 box and fills it, so a pillarboxed 16:9 phone stream is not shrunk.
          <Box
            sx={{
              position: 'absolute',
              inset: 0,
              ...(isMobile && { display: 'flex', justifyContent: 'center', bgcolor: 'black' }),
            }}
          >
            <Box
              sx={{
                position: 'relative',
                height: '100%',
                ...(isMobile && { aspectRatio: '9 / 16', maxWidth: '100%' }),
                '& > .MuiCard-root': { height: '100%', border: 0 },
              }}
            >
              {onStreamSlot ? (
                <>
                  <Box ref={streamSlotRef} sx={{ position: 'absolute', inset: 0, bgcolor: 'black' }} />
                  {/* The player is portalled from the page tile, so its clicks bubble there, not here. */}
                  {!tapsPhone && (
                    <Box
                      onClick={() => onToggleFocus(member.key)}
                      sx={{ position: 'absolute', inset: 0, zIndex: 1, cursor: 'pointer' }}
                    />
                  )}
                </>
              ) : (
                <RecHostPreview
                  host={host}
                  device={device}
                  hideHeader
                  fillMobileFrame
                  onOpenModal={tapsPhone ? undefined : () => onToggleFocus(member.key)}
                />
              )}
            </Box>
            {tapsPhone && (
              // Above the preview's own click layer: a click is a tap on the phones, not a focus.
              <Box
                ref={streamRef}
                onClick={handleStreamClick}
                sx={{ position: 'absolute', inset: 0, zIndex: 5, cursor: 'crosshair' }}
              >
                {tapMark && (
                  <Box
                    key={tapMark.id}
                    sx={{
                      position: 'absolute',
                      left: tapMark.x - 14,
                      top: tapMark.y - 14,
                      width: 28,
                      height: 28,
                      borderRadius: '50%',
                      border: `2px solid ${P.accent}`,
                      pointerEvents: 'none',
                      animation: 'groupTapMark 600ms ease-out forwards',
                      '@keyframes groupTapMark': {
                        from: { opacity: 1, transform: 'scale(0.6)' },
                        to: { opacity: 0, transform: 'scale(1.4)' },
                      },
                    }}
                  />
                )}
              </Box>
            )}
          </Box>
        ) : (
          <Box sx={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', p: 2 }}>
            <Typography variant="body2" sx={{ color: P.textMuted, textAlign: 'center' }}>
              {member.error}
            </Typography>
          </Box>
        )}
      </Box>
      {/* Status + device name centred in the footer; Selected / Focus stay at the right edge. */}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) auto minmax(max-content, 1fr)',
          alignItems: 'center',
          gap: 1,
          px: 1,
          py: 0.5,
          minHeight: 36,
        }}
      >
        <Box />
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
          <GroupStatusLed controlled={controlled} ack={member.ack} error={member.ackError} />
          <Typography variant="body2" sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.body.size }} noWrap>
            {device.device_name}
          </Typography>
          <DeviceMaintenanceBadge hostName={host.host_name} deviceId={device.device_id} size={14} />
          <Typography variant="caption" sx={{ color: P.textMuted, fontFamily: 'monospace' }} noWrap>
            {host.host_name}
          </Typography>
          {/* TASK-80: a mixed group shows the transport the backend drives this device on.
              BLE cells use a blue chip, IR / ADB use the gold one. */}
          {controlled && showProfile && member.chosenProfile && (
            <Chip
              size="small"
              label={formatRemoteProfile(member.chosenProfile)}
              sx={{
                height: 18,
                fontSize: TYPOGRAPHY.microMeta.size,
                fontWeight: 600,
                bgcolor: member.chosenProfile.startsWith('ble:') ? alpha(P.series[1], 0.85) : P.accent,
                color: P.onAccent,
              }}
            />
          )}
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, justifyContent: 'flex-end' }}>
          {controlled && (
            <>
              <FormControlLabel
                sx={{ m: 0, '& .MuiFormControlLabel-label': { fontSize: TYPOGRAPHY.caption.size } }}
                control={
                  <Checkbox
                    size="small"
                    sx={{ p: 0.5 }}
                    checked={member.included}
                    onChange={(e) => onIncludedChange(member.key, e.target.checked)}
                  />
                }
                label={t('Selected')}
              />
              <Typography
                component="button"
                onClick={() => onToggleFocus(member.key)}
                sx={{
                  border: 0,
                  bgcolor: 'transparent',
                  cursor: 'pointer',
                  color: P.accentText,
                  fontSize: TYPOGRAPHY.caption.size,
                  p: 0,
                  whiteSpace: 'nowrap',
                }}
              >
                {isFocused ? t('Unfocus') : t('Focus')}
              </Typography>
            </>
          )}
        </Box>
      </Box>
    </Box>
  );
};
