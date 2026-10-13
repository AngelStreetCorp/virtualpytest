/**
 * Film / series card for the live-TV companion (TASK-05, `title` template): title line, meta line
 * (year · director · duration, or season/episode · network), broadcast-slot progress, synopsis,
 * "previously on", cast chips and similar series. Every fact is web-sourced or absent.
 */
import { Box, Chip, LinearProgress, Typography } from '@mui/material';
import React from 'react';

import type { CompanionResult } from './types';
import { companionTitle } from './companionVerdict';
import { chipSx, O } from './overlayPalette';

const MUTED = O.textSecondary;

type FactValue = string | string[] | null | undefined;

const asList = (v: FactValue): string[] => (Array.isArray(v) ? v : v ? v.split(/,\s*/) : []).filter(Boolean);
const asText = (v: FactValue): string => (Array.isArray(v) ? v.join(', ') : v || '');

export function formatMinutes(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? `${h}h${String(m).padStart(2, '0')}` : `${m} min`;
}

/** "1h12 left" when the slot is known. */
export function remainingLabel(c: CompanionResult): string {
  return c.progress ? `${formatMinutes(c.progress.remaining_min)} left` : '';
}

export const TitleCard: React.FC<{ companion: CompanionResult }> = ({ companion }) => {
  const f = companion.facts?.status === 'ready' ? companion.facts.facts : {};
  const e = companion.entity || {};
  const series = companion.category === 'series';
  const film = companion.category === 'movie';
  const meta = series
    ? [e.season || e.episode ? `S${e.season || '?'} E${e.episode || '?'}` : '', asText(f.episode_title), asText(f.network)]
    : film
      ? [asText(f.year) || e.year || '', asText(f.director), asText(f.duration), asText(f.genre), asText(f.rating)]
      : // game show, documentary, music, kids
        [asText(f.episode_title), asText(f.network), asText(f.year), asText(f.director), f.age ? `age ${asText(f.age)}` : ''];
  const people = asList(f.cast).length ? asList(f.cast) : asList(f.jury).length ? asList(f.jury) : asList(f.performers);
  const p = companion.progress;

  return (
    <Box sx={{ color: O.textPrimary, minWidth: 0, flex: '2 1 320px' }}>
      <Typography sx={{ fontSize: 16, fontWeight: 600 }}>{e.title || companionTitle(companion)}</Typography>
      <Typography sx={{ fontSize: 12, color: MUTED, mb: 1 }}>{meta.filter(Boolean).join(' · ')}</Typography>

      {p && (
        <Box sx={{ mb: 1 }}>
          <LinearProgress variant="determinate" value={(100 * p.elapsed_min) / Math.max(1, p.total_min)}
            sx={{ height: 4, borderRadius: 2, backgroundColor: O.borderColor, '& .MuiLinearProgress-bar': { backgroundColor: O.accent } }} />
          <Typography sx={{ fontSize: 11, color: MUTED, mt: 0.5 }}>
            {p.start} – {p.end} · {formatMinutes(p.elapsed_min)} / {formatMinutes(p.total_min)} · {remainingLabel(companion)}
          </Typography>
        </Box>
      )}

      {asText(f.synopsis) && <Typography sx={{ fontSize: 12.5, mb: 1 }}>{asText(f.synopsis)}</Typography>}
      {series && asText(f.previously_on) && (
        <Typography sx={{ fontSize: 12.5, mb: 1 }}>
          <Box component="span" sx={{ color: MUTED, mr: 1 }}>Previously on</Box>
          {asText(f.previously_on)}
        </Typography>
      )}
      {asText(f.host) && (
        <Typography sx={{ fontSize: 12.5, mb: 0.5 }}>
          <Box component="span" sx={{ color: MUTED, mr: 1 }}>Host</Box>
          {asText(f.host)}
        </Typography>
      )}
      {people.length > 0 && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mb: 1 }}>
          {people.slice(0, 6).map((name) => (
            <Chip key={name} label={name} size="small"
              sx={{ ...chipSx, height: 22 }} />
          ))}
        </Box>
      )}
      {series && asList(f.similar_series).length > 0 && (
        <Typography sx={{ fontSize: 12, color: MUTED }}>Similar: {asList(f.similar_series).join(' · ')}</Typography>
      )}
    </Box>
  );
};
