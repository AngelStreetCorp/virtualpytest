/**
 * Soccer match card for the live-TV companion (TASK-05), ported from Labox's web app:
 * - `ScoreCard`   ← labox-website/src/components/ScoresStrip.tsx (ScoreCard)
 * - `MatchDetail` ← labox-website/src/components/MatchDetailModal.tsx (panel content + MatchEventRow)
 * Same structure, glyphs and tints; plain CSS became MUI `sx`, French labels became English, and
 * the modal became inline content of the companion strip so the video stays visible.
 */
import { Box, Typography } from '@mui/material';
import React from 'react';

import type { CompanionFixture, CompanionMatchEvent } from './types';
import { AGENT_CHAT_PALETTE } from '../../../frontend/src/constants/agentChatTheme';

// Labox theme tokens (index.css :root) — mapped to the static dark palette so the
// companion strip keeps its "dark card on a dark page" look on both themes.
// palette: Labox-derived card tokens — see UI_STYLE.md §3 (categorical scheme).
const SURFACE = AGENT_CHAT_PALETTE.surface;
const BORDER = `${AGENT_CHAT_PALETTE.borderColor}80`;
const ON_MUTED = AGENT_CHAT_PALETTE.textMuted;
const LIVE = AGENT_CHAT_PALETTE.error;
const YELLOW = AGENT_CHAT_PALETTE.gold; // a yellow card must read as yellow
const PENALTY = AGENT_CHAT_PALETTE.series[1];

const Svg: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <svg viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth={1.8}
    strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    {children}
  </svg>
);

const SoccerBallIcon = () => (
  <Svg>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7.5l3.6 2.6-1.4 4.2H9.8l-1.4-4.2Z" />
    <path d="M12 7.5V4M15.6 10.1l3-1.9M13.8 14.3l2 3.3M10.2 14.3l-2 3.3M8.4 10.1l-3-1.9" />
  </Svg>
);

const TargetIcon = () => (
  <Svg>
    <circle cx="12" cy="12" r="9" />
    <circle cx="12" cy="12" r="5" />
    <circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" />
  </Svg>
);

const CardIcon = () => (
  <Svg>
    <rect x="6" y="3" width="12" height="18" rx="1.6" />
  </Svg>
);

export function scoreStatusLabel(fixture: CompanionFixture): string {
  // Countdown sports (basketball) show the clock as read, with its period: "Q4 5:10".
  const clock = fixture.period && fixture.clock ? `${fixture.period} ${fixture.clock}`
    : fixture.minute !== null ? `${fixture.minute}'` : null;
  if (fixture.status === 'live') return clock || 'Live';
  if (fixture.status === 'paused') return clock ? `${clock} · paused` : 'Paused';
  if (fixture.status === 'finished') return 'Full time';
  return 'Upcoming';
}

const EVENT_LABELS: Record<string, string> = {
  goal: 'Goal',
  yellow_card: 'Yellow card',
  red_card: 'Red card',
  try: 'Try',
  conversion: 'Conversion',
  penalty: 'Penalty',
  penalty_try: 'Penalty try',
};

function matchEventLabel(event: CompanionMatchEvent): string {
  if (event.type === 'goal' && event.penalty) return 'Goal (pen.)';
  return EVENT_LABELS[event.type] || event.type.replace(/_/g, ' ');
}

const statusColor = (f: CompanionFixture) => (f.status === 'live' ? LIVE : ON_MUTED);

/** Labox ScoreCard: league caption, one row per team with its score, tinted status. */
export const ScoreCard: React.FC<{ fixture: CompanionFixture }> = ({ fixture }) => (
  <Box
    sx={{
      width: 168,
      flex: '0 0 auto',
      p: '12px 14px',
      borderRadius: '12px',
      background: SURFACE,
      border: `1px solid ${fixture.status === 'live' ? LIVE : BORDER}`,
      display: 'flex',
      flexDirection: 'column',
      gap: '6px',
      color: '#fff',
    }}
  >
    {fixture.league && (
      <Typography sx={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.4, color: ON_MUTED, textTransform: 'uppercase' }}
        noWrap>
        {fixture.league}
      </Typography>
    )}
    {[
      [fixture.homeTeam, fixture.homeScore],
      [fixture.awayTeam, fixture.awayScore],
    ].map(([team, score], i) => (
      <Box key={i} sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1,
        fontSize: 12.5, fontWeight: 600 }}>
        <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{team}</Box>
        <Box component="span" sx={{ fontWeight: 800, flexShrink: 0 }}>{score}</Box>
      </Box>
    ))}
    <Typography sx={{ fontSize: 11, fontWeight: 600, color: statusColor(fixture) }}>{scoreStatusLabel(fixture)}</Typography>
  </Box>
);

const MatchEventRow: React.FC<{ event: CompanionMatchEvent; fixture: CompanionFixture }> = ({ event, fixture }) => {
  const side = event.home ? fixture.homeTeam : fixture.awayTeam;
  const Icon = event.type.endsWith('card') ? CardIcon
    : event.penalty || event.type === 'penalty' || event.type === 'penalty_try' ? TargetIcon : SoccerBallIcon;
  const tint = event.type === 'yellow_card' ? YELLOW : event.type === 'red_card' ? LIVE : event.penalty ? PENALTY : AGENT_CHAT_PALETTE.textPrimary;
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: 12.5 }}>
      <Box component="span" sx={{ width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: tint, flex: 'none' }}>
        <Icon />
      </Box>
      <Box component="span" sx={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {event.minute}' · {matchEventLabel(event)}{event.player ? ` · ${event.player}` : ''}
      </Box>
      <Box component="span" sx={{ color: ON_MUTED, flex: 'none' }}>· {side}</Box>
    </Box>
  );
};

/** Labox MatchDetail panel content: league, "home 1 – 0 away", status, event timeline. */
export const MatchDetail: React.FC<{ fixture: CompanionFixture }> = ({ fixture }) => (
  <Box sx={{ color: '#fff', minWidth: 0 }}>
    {fixture.league && (
      <Typography sx={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.4, color: ON_MUTED, textTransform: 'uppercase' }}>
        {fixture.league}
      </Typography>
    )}
    <Typography component="h3" sx={{ m: '8px 0 4px', fontSize: 20, fontWeight: 700 }}>
      {fixture.homeTeam} {fixture.homeScore} – {fixture.awayScore} {fixture.awayTeam}
    </Typography>
    <Typography sx={{ display: 'inline-block', fontSize: 12, fontWeight: 600, color: statusColor(fixture), mb: 1.5 }}>
      {fixture.status === 'live' ? '● ' : ''}{scoreStatusLabel(fixture)}
    </Typography>
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {fixture.events.length === 0 ? (
        <Typography sx={{ fontSize: 12.5, color: ON_MUTED }}>No events yet</Typography>
      ) : (
        fixture.events.map((event, i) => <MatchEventRow key={i} event={event} fixture={fixture} />)
      )}
    </Box>
  </Box>
);
