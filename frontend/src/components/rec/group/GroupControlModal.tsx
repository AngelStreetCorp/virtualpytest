import { Box, Button, Chip, CircularProgress, Typography } from '@mui/material';
import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { useAIContext } from '../../../contexts/AIContext';
import { useBackToClose } from '../../../hooks/useBackToClose';
import { useGroupControl } from '../../../hooks/rec/useGroupControl';
import { useI18n } from '../../../i18n/useI18n';
import type { GroupSelection } from '../../../types/pages/groupControl.types';
import { formatRemoteProfile, profileRemoteType } from '../../../utils/remoteProfileUtils';
import { getZIndex } from '../../../utils/zIndexUtils';

import { GroupModelBadgeRow, type GroupModelBadge } from './GroupModelBadgeRow';
import { GroupRemoteSide } from './GroupRemoteSide';
import { GroupStreamGrid } from './GroupStreamGrid';

interface GroupControlModalProps {
  selection: GroupSelection;
  onClose: () => void;
  /**
   * Exit group mode on the parent page (TASK-76). Called after `onClose` so
   * the user lands back on the normal Edit / Group control + filters row, with
   * the in-progress selection cleared. Hooked to `Release all` and to the
   * back-to-close gesture, so both paths leave the page in a clean state.
   */
  onExitGroup: () => void;
  /** Devices whose page tile plays live: their cell reuses that player (see GroupStreamCell). */
  reusableStreamKeys?: ReadonlySet<string>;
  onStreamSlot?: (key: string, el: HTMLElement | null) => void;
}

/** TASK-76 group tile: every selected stream side by side, one remote driving them all. */
export const GroupControlModal: React.FC<GroupControlModalProps> = ({
  selection,
  onClose,
  onExitGroup,
  reusableStreamKeys,
  onStreamSlot,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const group = useGroupControl(selection);
  const { candidates, remoteProfile } = selection;

  const { pushFloatingButtonSuppress, popFloatingButtonSuppress } = useAIContext();
  useEffect(() => {
    pushFloatingButtonSuppress();
    return () => popFloatingButtonSuppress();
  }, [pushFloatingButtonSuppress, popFloatingButtonSuppress]);

  const { release } = group;
  const handleRelease = useCallback(async () => {
    await release();
    onClose();
    onExitGroup();
  }, [release, onClose, onExitGroup]);

  useBackToClose(true, handleRelease);

  // The grid's View menu renders on the Models row, at its right end.
  const [viewMenuTarget, setViewMenuTarget] = useState<HTMLElement | null>(null);

  // A click on a phone stream taps that point of the screen on every targeted phone.
  const { sink, members } = group;
  const handleTap = useCallback(
    (key: string, point: { x_pct: number; y_pct: number }) => {
      const member = members.find((m) => m.key === key);
      if (!member) return;
      // Per-device acks show a failure; nothing else to do here.
      sink({ host_name: member.host.host_name, command: 'tap_coordinates', params: point }).catch(() => undefined);
    },
    [sink, members],
  );

  const unavailable = group.members.filter((m) => !m.controlled);

  /**
   * Per-model badge row in the header. The chip's number is the included
   * count of that model — click toggles every member's `included` flag
   * so the operator can quickly narrow the group to, e.g., only STBs.
   * The chip is disabled when at least one member of the model has
   * `chosenProfile !== remoteProfile` (the backend fell back because
   * the operator's remote isn't on it).
   */
  const modelBadges = useMemo<GroupModelBadge[]>(() => {
    const out: GroupModelBadge[] = [];
    for (const [model, bucket] of group.includedByModel.entries()) {
      const total = bucket.total.length;
      const included = bucket.included.length;
      if (total === 0) continue;
      const enabled = group.isModelCompatible(model);
      out.push({ model, count: included, enabled });
    }
    return out.sort((a, b) => a.model.localeCompare(b.model));
  }, [group.includedByModel, group.isModelCompatible]);

  return (
    <Box
      sx={{
        position: 'fixed',
        inset: 0,
        zIndex: getZIndex('MODAL_CONTENT'),
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0, 0, 0, 0.9)',
      }}
    >
      <Box
        sx={{
          width: '95vw',
          height: '90vh',
          bgcolor: P.surface,
          borderRadius: 2,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
            px: 2,
            py: 1,
            borderBottom: `1px solid ${P.borderColor}`,
            flexWrap: 'wrap',
          }}
        >
          <Typography sx={{ fontWeight: 600 }}>
            {t('Group control')} ·{' '}
            <Box component="span" sx={{ fontFamily: 'monospace', color: P.accentText }}>
              {formatRemoteProfile(remoteProfile)}
            </Box>
          </Typography>
          {!group.isTaking && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
              <Box
                sx={{
                  width: 9,
                  height: 9,
                  borderRadius: '50%',
                  bgcolor: unavailable.length ? P.warning : P.success,
                }}
              />
              <Typography variant="body2">
                {t('{count}/{total} controlled', { count: group.controlled.length, total: group.members.length })}
              </Typography>
            </Box>
          )}
          {unavailable.map((m) => (
            <Chip
              key={m.key}
              size="small"
              label={`${m.device.device_name}: ${m.error}`}
              sx={{ color: P.error, border: `1px solid ${P.error}66`, bgcolor: `${P.error}1f` }}
            />
          ))}
          <Box sx={{ flex: 1 }} />
          <Button variant="outlined" size="small" onClick={handleRelease} sx={{ textTransform: 'none' }}>
            {t('Release all')}
          </Button>
        </Box>
        {/* Per-model badge row — lets the operator drop every member of a
            model (or include the whole model again) in one click without
            scrolling through the stream grid. A chip is greyed when at least
            one member of the model has `chosenProfile !== remoteProfile`
            (the backend fell back to a different transport) and the toggle
            is therefore unsafe. */}
        {(modelBadges.length > 0 || !group.isTaking) && (
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              px: 2,
              py: 0.75,
              borderBottom: `1px solid ${P.borderColor}`,
              flexWrap: 'wrap',
            }}
          >
            {modelBadges.length > 0 && (
              <GroupModelBadgeRow
                badges={modelBadges}
                onToggle={group.toggleIncludedByModel}
                label={t('Group model filter')}
                caption={t('Models')}
              />
            )}
            {/* Right edge lines up with the stream grid's: past the 320px remote side, minus the grid's 12px padding vs the row's 16px. */}
            <Box ref={setViewMenuTarget} sx={{ ml: 'auto', mr: { md: '316px' }, display: 'flex' }} />
          </Box>
        )}

        {group.isTaking ? (
          <Box sx={{ flex: 1, display: 'grid', placeItems: 'center' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <CircularProgress size={20} />
              <Typography variant="body2" sx={{ color: P.textSecondary }}>
                {t('Taking control of {count} devices…', { count: candidates.length })}
              </Typography>
            </Box>
          </Box>
        ) : (
          <Box sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: { xs: 'column', md: 'row' } }}>
            <GroupStreamGrid
              members={group.members}
              focusKey={group.focusKey}
              onToggleFocus={group.toggleFocus}
              onIncludedChange={group.setIncluded}
              onTap={handleTap}
              viewMenuTarget={viewMenuTarget}
              reusableStreamKeys={reusableStreamKeys}
              onStreamSlot={onStreamSlot}
            />
            {group.primary ? (
              <GroupRemoteSide
                primary={group.primary}
                remoteType={profileRemoteType(remoteProfile)}
                targets={group.targets}
                sink={group.sink}
                log={group.log}
                onRelease={handleRelease}
              />
            ) : (
              <Box sx={{ width: { md: 320 }, p: 2, borderLeft: { md: `1px solid ${P.borderColor}` } }}>
                <Typography variant="body2" sx={{ color: P.error }}>
                  {t('No device of the group could be controlled.')}
                </Typography>
              </Box>
            )}
          </Box>
        )}
      </Box>
    </Box>
  );
};
