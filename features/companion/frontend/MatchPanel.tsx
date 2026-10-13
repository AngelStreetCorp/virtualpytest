/**
 * Expanded match view of the companion strip (TASK-05): the match itself once on the left
 * (MatchDetail), and on the right what the web lookup found — the competition table, ported from
 * Labox's "classement" panel (labox-website/src/pages/AppScores.tsx StandingsPanel), then both
 * line-ups side by side.
 */
import { Box, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../frontend/src/constants/agentChatTheme';

import { MatchDetail } from './MatchCard';
import type { CompanionFacts, CompanionFixture } from './types';

type Row = Record<string, string | number | null | undefined>;

const text = (v: unknown): string => (Array.isArray(v) ? v.join(', ') : v == null ? '' : String(v));
const list = (v: unknown): string[] =>
  (Array.isArray(v) ? v.map(String) : typeof v === 'string' && v ? v.split(/,\s*/) : []).filter(Boolean);

/** Same team? The table spells clubs in full, the score bug uses codes (LIL / Lille OSC). */
function sameTeam(a: string, b: string): boolean {
  const x = a.toLowerCase();
  const y = b.toLowerCase();
  if (!x || !y) return false;
  if (x.includes(y) || y.includes(x)) return true;
  const [short, long] = x.length <= y.length ? [x, y] : [y, x];
  let i = 0;
  for (const ch of long) if (ch === short[i]) i += 1;
  return short.length >= 3 && i === short.length;
}

// Column sets per sport: whichever keys the rows carry decide the columns.
const COLUMNS: [string, string][] = [
  ['played', 'P'],
  ['won', 'W'],
  ['drawn', 'D'],
  ['lost', 'L'],
  ['goals_for', 'GF'],
  ['goals_against', 'GA'],
  ['points_for', 'PF'],
  ['points_against', 'PA'],
  ['win_pct', '%'],
  ['points', 'Pts'],
];

export const StandingsTable: React.FC<{ rows: Row[]; teams: string[] }> = ({ rows, teams }) => {
  const P = useAgentChatPalette();
  const cols = COLUMNS.filter(([key]) => rows.some((r) => r[key] != null && r[key] !== ''));
  const cell = { px: 0.75, py: 0.25, fontSize: 12, textAlign: 'right' as const, whiteSpace: 'nowrap' as const };
  return (
    <Box component="table" sx={{ borderCollapse: 'collapse', width: '100%', color: P.textPrimary }}>
      <thead>
        <tr>
          <Box component="th" sx={{ ...cell, textAlign: 'left', color: P.textMuted, fontWeight: 600 }} />
          {cols.map(([key, label]) => (
            <Box component="th" key={key} sx={{ ...cell, color: P.textMuted, fontWeight: 600 }}>{label}</Box>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => {
          const team = text(row.team);
          const mine = teams.some((t) => sameTeam(team, t));
          return (
            <Box component="tr" key={`${team}-${i}`} sx={{ backgroundColor: mine ? `${P.accent}26` : 'transparent' }}>
              <Box component="td" sx={{ ...cell, textAlign: 'left', fontWeight: mine ? 700 : 400 }}>
                <Box component="span" sx={{ color: P.textMuted, display: 'inline-block', minWidth: 22 }}>{text(row.rank) || i + 1}</Box>
                {team}
              </Box>
              {cols.map(([key]) => (
                <Box component="td" key={key} sx={{ ...cell, fontWeight: key === 'points' ? 800 : 400 }}>{text(row[key])}</Box>
              ))}
            </Box>
          );
        })}
      </tbody>
    </Box>
  );
};

const Lineup: React.FC<{ title: string; players: string[]; coach: string }> = ({ title, players, coach }) => {
  const P = useAgentChatPalette();
  return (
    <Box sx={{ flex: '1 1 160px', minWidth: 0 }}>
      <Typography sx={{ fontSize: 12, fontWeight: 700, mb: 0.5 }}>{title}</Typography>
      {players.map((p, i) => (
        <Typography key={`${p}-${i}`} sx={{ fontSize: 12, lineHeight: 1.45 }} noWrap>{p}</Typography>
      ))}
      {coach && <Typography sx={{ fontSize: 11.5, color: P.textMuted, mt: 0.5 }} noWrap>Coach {coach}</Typography>}
    </Box>
  );
};

export const MatchPanel: React.FC<{ fixture: CompanionFixture; facts?: CompanionFacts }> = ({ fixture, facts }) => {
  const P = useAgentChatPalette();
  const f: Record<string, unknown> = facts?.status === 'ready' ? facts.facts : {};
  const home = text(f.home_team_name) || fixture.homeTeam;
  const away = text(f.away_team_name) || fixture.awayTeam;
  const named = { ...fixture, homeTeam: home, awayTeam: away, league: text(f.competition) || fixture.league };
  const meta = [text(f.venue), text(f.kickoff) || text(f.tipoff), text(f.referee) && `Referee ${text(f.referee)}`]
    .filter(Boolean)
    .join(' · ');
  const standings = (Array.isArray(f.standings) ? f.standings : []).filter(
    (r): r is Row => !!r && typeof r === 'object' && !!(r as Row).team,
  );
  const homeXI = list(f.home_lineup ?? f.home_starters);
  const awayXI = list(f.away_lineup ?? f.away_starters);

  return (
    <Box sx={{ display: 'flex', gap: 3, alignItems: 'flex-start', flexWrap: 'wrap', width: '100%' }}>
      <Box sx={{ flex: '0 1 300px', minWidth: 220 }}>
        <MatchDetail fixture={named} />
        {meta && <Typography sx={{ fontSize: 11.5, color: P.textMuted, mt: 1.5 }}>{meta}</Typography>}
      </Box>
      <Box sx={{ flex: '1 1 420px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        {facts?.status === 'pending' && <Typography sx={{ fontSize: 12, color: P.textMuted }}>Looking up the table and line-ups…</Typography>}
        {facts?.status === 'failed' && (
          <Typography sx={{ fontSize: 12, color: P.warning }}>Facts unavailable{facts.error ? `: ${facts.error}` : ''}</Typography>
        )}
        {standings.length > 0 && <StandingsTable rows={standings} teams={[home, away, fixture.homeTeam, fixture.awayTeam]} />}
        {(homeXI.length > 0 || awayXI.length > 0) && (
          <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
            <Lineup title={home} players={homeXI} coach={text(f.home_coach)} />
            <Lineup title={away} players={awayXI} coach={text(f.away_coach)} />
          </Box>
        )}
      </Box>
    </Box>
  );
};
