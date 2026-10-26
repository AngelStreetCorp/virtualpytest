import { Box, Chip } from '@mui/material';
import React, { useMemo } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';

/**
 * The category filter row of the docs pages (Videos, Screenshots): "All N" + one chip per category with
 * its count; the active one is gold, a second press clears it. Wraps on a phone.
 * The categories (key -> English label, display order) come from the page's JSON `categories` object.
 */

/** Returns key -> translated label. Literal t() keys (the i18n extractor needs them); the JSON label is the fallback for a new category. */
export const useCategoryLabel = (categories: Record<string, string> | undefined) => {
  const { t } = useI18n();
  return (key: string): string => {
    const translated: Record<string, string> = {
      Device: t('Device'),
      AI: t('AI'),
      Test: t('Test'),
      Scripts: t('Scripts'),
      Stream: t('Stream'),
    };
    const english = categories?.[key] ?? key;
    return translated[english] ?? english;
  };
};

/** Items per category key (an item counts once in each of its categories). */
export const useCategoryCounts = <T extends { categories: string[] }>(items: T[] | undefined) =>
  useMemo(() => {
    const c: Record<string, number> = {};
    (items ?? []).forEach((v) => v.categories.forEach((k) => (c[k] = (c[k] ?? 0) + 1)));
    return c;
  }, [items]);

interface Props {
  categoryKeys: string[];
  counts: Record<string, number>;
  total: number;
  active: string | null;
  onToggle: (key: string | null) => void;
  labelOf: (key: string) => string;
  /** Bottom gap; 0 when the row sits in a title bar. */
  mb?: number;
}

const CategoryChips: React.FC<Props> = ({ categoryKeys, counts, total, active, onToggle, labelOf, mb = 1.5 }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  return (
    <Box role="group" aria-label={t('Filter by category')} sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mb }}>
      {[null, ...categoryKeys].map((k) => {
        const isActive = k === active;
        return (
          <Chip
            key={k ?? 'all'}
            size="small"
            clickable
            aria-pressed={isActive}
            onClick={() => onToggle(k)}
            label={`${k ? labelOf(k) : t('All')} ${k ? counts[k] ?? 0 : total}`}
            variant={isActive ? 'filled' : 'outlined'}
            sx={{
              fontWeight: 500,
              color: isActive ? 'primary.contrastText' : P.textSecondary,
              bgcolor: isActive ? P.accent : 'transparent',
              borderColor: isActive ? P.accent : P.borderColor,
              '&:hover': { bgcolor: isActive ? P.accentHover : P.hoverBg },
            }}
          />
        );
      })}
    </Box>
  );
};

export default CategoryChips;
