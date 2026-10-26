import React from 'react';

import { useI18n } from '../../../i18n/useI18n';
import { ModeBar, ModeBarActions } from '../ModeBar';
import type { GroupCandidate } from '../../../types/pages/groupControl.types';

import { GroupModelBadgeRow, type GroupModelBadge } from './GroupModelBadgeRow';

interface GroupSelectBarProps {
  count: number;
  /** Size of the pool "Select all" acts on. */
  total: number;
  onSelectAll: () => void;
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
 * Bar above the device grid (same slot as the Edit-tags bar) while group control picks devices (TASK-76).
 *
 * A single chip strip — one chip per model currently in the pool — is the
 * whole operator surface here: clicking a chip adds every candidate of
 * that model, clicking again removes them. The bar's `Control N devices`
 * button still starts the tile once the group hits GROUP_MIN_SIZE.
 */
export const GroupSelectBar: React.FC<GroupSelectBarProps> = ({
  count,
  total,
  onSelectAll,
  canStart,
  selectedByModel,
  poolByModel,
  onToggleByModel,
  onClear,
  onStart,
}) => {
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
    <ModeBar>
      {badges.length > 0 && (
        <GroupModelBadgeRow
          badges={badges}
          onToggle={onToggleByModel}
          label={t('Group model filter')}
          caption={t('Models')}
        />
      )}
      <ModeBarActions
        count={count}
        total={total}
        onSelectAll={onSelectAll}
        selectAllDisabled={total === 0 || count >= total}
        onClear={onClear}
        actionLabel={t('Control {count} devices', { count })}
        onAction={onStart}
        actionDisabled={!canStart}
      />
    </ModeBar>
  );
};
