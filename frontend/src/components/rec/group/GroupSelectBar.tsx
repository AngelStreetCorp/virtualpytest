import { Box, Button } from '@mui/material';
import React from 'react';

import { goldButtonSx } from '../../common/PageChrome';
import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { useI18n } from '../../../i18n/useI18n';
import type { GroupCandidate } from '../../../types/pages/groupControl.types';

import { GroupModelBadgeRow, type GroupModelBadge } from './GroupModelBadgeRow';

interface GroupSelectBarProps {
  count: number;
  canStart: boolean;
  /** Per-model membership of the current group selection, sorted by
   *  model name. Drives the chip strip that lets the operator add /
   *  remove every candidate of a model in one click. */
  selectedByModel: Map<string, GroupCandidate[]>;
  /** Per-model pool (every selectable candidate for the chosen remote
   *  profile), used to decide whether a chip is fully selected already. */
  poolByModel: Map<string, GroupCandidate[]>;
  /** Click a chip → toggle every candidate of that model in / out of
   *  the group, up to the per-group cap. */
  onToggleByModel: (model: string) => void;
  onClear: () => void;
  onStart: () => void;
}

/**
 * Sticky bar under the device grid while group control picks devices (TASK-76).
 *
 * A single chip strip — one chip per model currently in the pool — is the
 * whole operator surface here: clicking a chip adds every candidate of
 * that model, clicking again removes them. The bar's `Control N devices`
 * button still starts the tile once the group hits GROUP_MIN_SIZE.
 */
export const GroupSelectBar: React.FC<GroupSelectBarProps> = ({
  count,
  canStart,
  selectedByModel,
  poolByModel,
  onToggleByModel,
  onClear,
  onStart,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();

  // One chip per model currently in the pool — "in the group" is the
  // count, the tooltip explains the click action. The pool is now the
  // whole workspace, so the chips are visible the moment group mode opens
  // and clicking one auto-picks the model's most common remote profile.
  // Grouping needs ≥2 devices of a model, so chips with fewer than two
  // pool candidates are hidden — apple_tv with a single device would be a
  // useless "group of one" and don't belong in the filter strip.
  const badges: GroupModelBadge[] = React.useMemo(() => {
    const models = new Set<string>();
    poolByModel.forEach((_, model) => models.add(model));
    selectedByModel.forEach((_, model) => models.add(model));
    return Array.from(models)
      .sort((a, b) => a.localeCompare(b))
      .map((model) => {
        const inGroup = (selectedByModel.get(model) ?? []).length;
        const poolTotal = (poolByModel.get(model) ?? []).length;
        return { model, count: inGroup, enabled: poolTotal > 0 };
      })
      .filter(({ model }) => (poolByModel.get(model)?.length ?? 0) >= 2);
  }, [poolByModel, selectedByModel]);

  return (
    <Box
      sx={{
        position: 'sticky',
        bottom: 8,
        zIndex: 2,
        mt: 2,
        display: 'flex',
        alignItems: 'center',
        gap: 1.5,
        // Bar is one line, no matter what — the operator asked for
        // that explicitly. When the chip strip overflows, the strip
        // itself becomes a horizontal scroller (set inside
        // GroupModelBadgeRow); the action buttons stay pinned to the
        // right of the row.
        flexWrap: 'nowrap',
        px: 1.5,
        py: 1,
        bgcolor: P.surface,
        border: `1px solid ${P.borderColor}`,
        borderRadius: 1,
        overflow: 'hidden',
        // iOS / Android long-press triggers a system text-selection
        // overlay on any selectable text inside the bar (the "flash
        // effect" the operator complained about). The bar only carries
        // labels and counts that nobody needs to copy, so suppress
        // selection across the whole row.
        userSelect: 'none',
        WebkitUserSelect: 'none',
        WebkitTouchCallout: 'none',
      }}
    >
      {badges.length > 0 && (
        <GroupModelBadgeRow
          badges={badges}
          onToggle={onToggleByModel}
          label={t('Group model filter')}
          caption={t('Models')}
        />
      )}
      <Button size="small" onClick={onClear} disabled={count === 0} sx={{ textTransform: 'none', color: P.accentText, flexShrink: 0 }}>
        {t('Clear')}
      </Button>
      <Button size="small" variant="contained" onClick={onStart} disabled={!canStart} sx={{ ...goldButtonSx(P), flexShrink: 0 }}>
        {t('Control {count} devices', { count })}
      </Button>
    </Box>
  );
};
