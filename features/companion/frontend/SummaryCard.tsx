/**
 * News card of the companion strip (TASK-05 L4a, `summary` template): the stories of the last
 * minutes, newest first, each with its people / places / organisations, plus who is on screen
 * (lower thirds) and a sensitive-content warning. Built from the live transcript + on-screen text.
 */
import { Box, Chip, Typography } from '@mui/material';
import React from 'react';

import FactCheckMeter from './FactCheckMeter';
import type { CompanionResult, CompanionStory } from './types';
import { chipSx, O } from './overlayPalette';

const MUTED = O.textSecondary;

export function digestLabel(c: CompanionResult, nowMs: number = Date.now()): string {
  const d = c.digest;
  if (!d) return 'listening…';
  const ago = Math.max(0, Math.round((nowMs / 1000 - d.at) / 60));
  const n = d.stories?.length ?? 0;
  return `${n} ${n === 1 ? 'story' : 'stories'} · updated ${ago ? `${ago} min ago` : 'now'}`;
}

const chip = { ...chipSx, height: 20, fontSize: 10.5 };

const Story: React.FC<{ story: CompanionStory }> = ({ story }) => {
  const tags = [...story.people, ...story.places, ...story.orgs];
  return (
    <Box sx={{ mb: 1 }}>
      <Typography sx={{ fontSize: 13, fontWeight: 600 }}>▸ {story.headline}</Typography>
      {story.summary && <Typography sx={{ fontSize: 12.5, ml: 1.5 }}>{story.summary}</Typography>}
      {tags.length > 0 && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, ml: 1.5, mt: 0.25 }}>
          {tags.slice(0, 8).map((t) => <Chip key={t} label={t} size="small" sx={chip} />)}
        </Box>
      )}
    </Box>
  );
};

export const SummaryCard: React.FC<{ companion: CompanionResult }> = ({ companion }) => {
  const d = companion.digest;
  const third = companion.on_screen?.lower_third;
  return (
    <Box sx={{ color: O.textPrimary, minWidth: 0, flex: '1 1 100%' }}>
      {d?.sensitive?.flag && (
        <Typography sx={{ fontSize: 12, color: O.warning, mb: 1 }}>⚠ {d.sensitive.reason || 'sensitive images'}</Typography>
      )}
      {third && (
        <Typography sx={{ fontSize: 12, color: MUTED, mb: 1 }}>
          On screen: <b style={{ color: O.textPrimary, fontWeight: 600 }}>{third.name}</b>{third.role ? `, ${third.role}` : ''}
        </Typography>
      )}
      {!d && <Typography sx={{ fontSize: 12, color: MUTED }}>Listening… the first digest comes after a couple of minutes.</Typography>}
      {d && (d.stories?.length ?? 0) === 0 && (
        <Typography sx={{ fontSize: 12, color: MUTED }}>Nothing clear enough to summarise in the last {d.window_min} min.</Typography>
      )}
      {companion.meter && (
        <Box sx={{ mb: 1 }}>
          <FactCheckMeter meter={companion.meter} />
        </Box>
      )}
      {d?.stories?.map((s) => <Story key={s.headline} story={s} />)}
      {d && (
        <Typography sx={{ fontSize: 11, color: MUTED, mt: 0.5 }}>
          From the last {d.window_min} min of speech ({d.lines} lines, automatic transcript) and on-screen text.
        </Typography>
      )}
    </Box>
  );
};
