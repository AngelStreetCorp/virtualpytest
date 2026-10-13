/**
 * Live-TV companion strip (TASK-05): one line under the video saying what is on, expanding on
 * tap to the programme card: the Labox match card for scoreboard sports (MatchCard.tsx), the title
 * card for films and series (TitleCard.tsx), otherwise the genre and whatever facts were looked up.
 *
 * Data: the device's companion result (CompanionOverlay polls /server/companion/latest). On menus,
 * home, settings, loading and error screens it is a single "Content:" verdict line.
 */
import { Box, Link, Typography } from '@mui/material';
import React, { useState } from 'react';

import type { CompanionFacts, CompanionResult } from './types';
import { companionIcon, companionTitle, formatCompanionVerdict, isCompanionStale } from './companionVerdict';

import { scoreStatusLabel } from './MatchCard';
import { MatchPanel } from './MatchPanel';
import { DebateCard, debateLabel } from './DebateCard';
import { digestLabel, SummaryCard } from './SummaryCard';
import { remainingLabel, TitleCard } from './TitleCard';
import { O, OVERLAY_BG } from './overlayPalette';

const PROGRAMME_SCREENS = ['live_tv', 'vod_playback', 'advertisement'];
const FACT_LABELS: Record<string, string> = {
  competition: 'Competition',
  venue: 'Venue',
  kickoff: 'Kickoff',
  home_coach: 'Home coach',
  away_coach: 'Away coach',
  home_lineup: 'Home XI',
  away_lineup: 'Away XI',
  home_starters: 'Home five',
  away_starters: 'Away five',
  tipoff: 'Tip-off',
};

const factText = (value: string | string[] | null) => (Array.isArray(value) ? value.join(', ') : value || '');

const hostname = (url: string) => {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
};

/** The pages the facts came from. */
const Sources: React.FC<{ facts?: CompanionFacts }> = ({ facts }) => {
  if (!facts || facts.sources.length === 0) return null;
  const shown = facts.sources.slice(0, 4);
  return (
    <Typography sx={{ fontSize: 11, color: O.textSecondary, mt: 0.5, width: '100%' }}>
      Sources:{' '}
      {shown.map((s, i) => (
        <Link key={s.url} href={s.url} target="_blank" rel="noopener noreferrer" sx={{ color: O.accentText, mr: 1 }}>
          {s.title || hostname(s.url)}{i < shown.length - 1 ? ',' : ''}
        </Link>
      ))}
    </Typography>
  );
};

/** Fact rows (or, with listFacts=false, only the lookup state and the sources). */
const FactsBlock: React.FC<{ facts?: CompanionFacts; listFacts?: boolean }> = ({ facts, listFacts = true }) => {
  if (!facts) return null;
  if (facts.status === 'pending') {
    return <Typography sx={{ fontSize: 12, color: O.textSecondary }}>Looking up programme facts…</Typography>;
  }
  if (facts.status === 'failed') {
    return <Typography sx={{ fontSize: 12, color: O.warning }}>Facts unavailable{facts.error ? `: ${facts.error}` : ''}</Typography>;
  }
  if (facts.status === 'skipped') {
    // TASK-45 goal 5: Jev's gate decided the title is not a programme / film / series / match
    // worth a web lookup (a strap, a slot, a channel name). Nothing to render.
    return null;
  }
  const rows = listFacts ? Object.entries(facts.facts).filter(([, v]) => factText(v)) : [];
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, minWidth: 0 }}>
      {listFacts && rows.length === 0 && <Typography sx={{ fontSize: 12, color: O.textSecondary }}>No facts found on the web</Typography>}
      {rows.map(([key, value]) => (
        <Typography key={key} sx={{ fontSize: 12, color: O.textPrimary }}>
          <Box component="span" sx={{ color: O.textSecondary, mr: 1 }}>{FACT_LABELS[key] || key.replace(/_/g, ' ')}</Box>
          {factText(value)}
        </Typography>
      ))}
      <Sources facts={facts} />
    </Box>
  );
};

function summaryLine(c: CompanionResult): React.ReactNode {
  if (!c.screen || !PROGRAMME_SCREENS.includes(c.screen)) {
    const verdict = formatCompanionVerdict(c);
    return <>Content: <Box component="span" sx={{ color: verdict.color, fontWeight: 600 }}>{verdict.text}</Box></>;
  }
  const live = c.live;
  if (c.screen === 'advertisement') {
    return live ? `Ad break · tracking paused · last: ${live.homeScore} – ${live.awayScore} (${scoreStatusLabel(live)})`
      : 'Ad break';
  }
  if (c.template === 'match' && live) {
    return (
      <>
        {live.homeTeam} <b>{live.homeScore} – {live.awayScore}</b> {live.awayTeam}
        <Box component="span" sx={{ color: live.status === 'live' ? O.error : O.textSecondary, ml: 1 }}>
          · {scoreStatusLabel(live)}{live.status === 'live' ? ' ●' : ''}
        </Box>
      </>
    );
  }
  const kind = [c.category, c.subcategory].filter(Boolean).join(' / ');
  const title = companionTitle(c);
  if (c.template === 'debate') {
    return `${title || 'Debate'} · ${debateLabel(c)}`;
  }
  if (c.template === 'summary') {
    return `${title || kind || 'News'} · ${digestLabel(c)}${c.digest?.sensitive?.flag ? ' · ⚠' : ''}`;
  }
  if (c.template === 'title' && title) {
    const left = remainingLabel(c);
    return `${title}${left ? ` · ${left}` : ''}`;
  }
  return title ? `${title}${kind ? ` · ${kind}` : ''}` : kind || 'Identifying…';
}

export const CompanionStrip: React.FC<{ companion?: CompanionResult; show: boolean }> = ({ companion, show }) => {
  const [expanded, setExpanded] = useState(false);
  if (!show || !companion || (!companion.screen && !companion.error)) return null;
  const stale = isCompanionStale(companion);
  const canExpand = !!companion.screen && PROGRAMME_SCREENS.includes(companion.screen)
    && companion.screen !== 'advertisement'
    && (!!companion.live || !!companion.facts || !!companion.progress || companion.template === 'summary' || companion.template === 'debate');

  return (
    <Box
      onClick={() => canExpand && setExpanded((e) => !e)}
      sx={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 1200,
        pointerEvents: 'auto',
        cursor: canExpand ? 'pointer' : 'default',
        backgroundColor: OVERLAY_BG,
        borderTop: `1px solid ${O.borderColor}`,
        color: O.textPrimary,
        opacity: stale ? 0.6 : 1,
        px: 1.5,
        py: 0.75,
      }}
      data-testid="companion-strip"
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Box component="span" sx={{ fontSize: 16 }}>{companionIcon(companion)}</Box>
        <Typography sx={{ fontSize: 13, flex: 1, minWidth: 0 }} noWrap>{summaryLine(companion)}</Typography>
        {companion.backoff && (
          <Typography sx={{ fontSize: 11, color: O.warning }} noWrap>
            AI {companion.backoff.reason === 'busy' ? 'busy' : 'error'} · retry in {companion.backoff.retry_in_s}s
          </Typography>
        )}
        {companion.facts?.status === 'pending' && (
          <Typography sx={{ fontSize: 11, color: O.textSecondary }} noWrap>looking up…</Typography>
        )}
        {canExpand && <Typography sx={{ fontSize: 12, color: O.textSecondary }}>{expanded ? '▾' : '▴'}</Typography>}
      </Box>

      {expanded && canExpand && (
        <Box sx={{ display: 'flex', gap: 2, mt: 1, pb: 0.5, alignItems: 'flex-start', flexWrap: 'wrap' }}
          onClick={(e) => e.stopPropagation()}>
          {companion.live ? (
            <>
              {/* The match once (left), the table and line-ups in the full width (right). */}
              <MatchPanel fixture={companion.live} facts={companion.facts} />
              <Sources facts={companion.facts} />
            </>
          ) : (
            <>
              {companion.template === 'debate' ? (
                <DebateCard companion={companion} />
              ) : companion.template === 'summary' ? (
                <SummaryCard companion={companion} />
              ) : companion.template === 'title' ? (
                <TitleCard companion={companion} />
              ) : (
                <Typography sx={{ fontSize: 15, fontWeight: 600 }}>{companionTitle(companion)}</Typography>
              )}
              <Box sx={{ flex: '1 1 240px', minWidth: 0 }}>
                <FactsBlock facts={companion.facts} listFacts={companion.template !== 'title'} />
              </Box>
            </>
          )}
        </Box>
      )}
    </Box>
  );
};
