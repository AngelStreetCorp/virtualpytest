/**
 * Debate / talk-show card of the companion strip (TASK-05 L4b, `debate` template): the topic now
 * (the channel's strap), the people its captions named, positions and claims from the transcript
 * digest, and the earlier topics. Speakers are only attributed when a caption named them. With fact
 * checking on for the device, each checkable claim shows its verdict and a source.
 *
 * TASK-45: when the companion returns a ``meter``, the Claims block is replaced by the live
 * FactCheckMeter. ClaimCheck lives there and is shared with the claims list.
 */
import { Box, Chip, Typography } from '@mui/material';
import React from 'react';

import type { CompanionResult } from './types';
import FactCheckMeter, { ClaimCheck } from './FactCheckMeter';
import { chipSx, O } from './overlayPalette';

const MUTED = O.textSecondary;
const chip = { ...chipSx, height: 22 };

const clock = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

export function debateLabel(c: CompanionResult): string {
  const topic = c.topics?.[0]?.text || c.digest?.topic;
  const n = c.roster?.length ?? 0;
  return [topic, n ? `${n} ${n === 1 ? 'speaker' : 'speakers'}` : ''].filter(Boolean).join(' · ') || 'listening…';
}

export const DebateCard: React.FC<{ companion: CompanionResult }> = ({ companion }) => {
  const d = companion.digest;
  const topics = companion.topics ?? [];
  const roster = companion.roster ?? [];
  const meter = companion.meter;
  return (
    <Box sx={{ color: O.textPrimary, minWidth: 0, flex: '1 1 100%', display: 'flex', gap: 3, flexWrap: 'wrap' }}>
      <Box sx={{ flex: '2 1 360px', minWidth: 0 }}>
        <Typography sx={{ fontSize: 11, fontWeight: 600, color: MUTED }}>
          Now discussing
        </Typography>
        <Typography sx={{ fontSize: 15, fontWeight: 600, mb: 1 }}>{topics[0]?.text || d?.topic || '—'}</Typography>
        {d?.topic && topics[0] && <Typography sx={{ fontSize: 12.5, color: MUTED, mb: 1 }}>{d.topic}</Typography>}

        {(d?.positions?.length ?? 0) > 0 && (
          <Box sx={{ mb: 1 }}>
            {d!.positions!.map((p, i) => (
              <Typography key={i} sx={{ fontSize: 12.5 }}>
                <b>{p.speaker || 'Someone'}</b>: {p.stance}
              </Typography>
            ))}
          </Box>
        )}
        {meter ? (
          <Box sx={{ mb: 1 }}>
            <FactCheckMeter meter={meter} />
          </Box>
        ) : (d?.claims?.length ?? 0) > 0 ? (
          <Box sx={{ mb: 1 }}>
            <Typography sx={{ fontSize: 11, color: MUTED, mb: 0.25 }}>Claims</Typography>
            {d!.claims!.map((c, i) => (
              <Box key={i} sx={{ mb: 0.5 }}>
                <Typography sx={{ fontSize: 12.5 }}>
                  “{c.text}” <Box component="span" sx={{ color: MUTED }}>— {c.speaker || '?'}{c.checkable && !c.check ? ' · checkable' : ''}</Box>
                </Typography>
                {c.check && (
                  <Typography sx={{ fontSize: 11.5, pl: 1.5 }}>
                    <ClaimCheck check={c.check} />
                  </Typography>
                )}
              </Box>
            ))}
          </Box>
        ) : null}
        {!d && <Typography sx={{ fontSize: 12, color: MUTED }}>Listening… the first digest comes after a couple of minutes.</Typography>}
        {d && (
          <Typography sx={{ fontSize: 11, color: MUTED }}>
            From the last {d.window_min} min of speech ({d.lines} lines, automatic transcript) and the channel's captions.
          </Typography>
        )}
      </Box>

      <Box sx={{ flex: '1 1 240px', minWidth: 0 }}>
        <Typography sx={{ fontSize: 11, color: MUTED, mb: 0.5 }}>Speakers (from captions)</Typography>
        {roster.length === 0 ? (
          <Typography sx={{ fontSize: 12, color: MUTED, mb: 1 }}>None named on screen yet</Typography>
        ) : (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mb: 1 }}>
            {roster.map((s) => <Chip key={s.name} size="small" sx={chip} label={s.role ? `${s.name} · ${s.role}` : s.name} />)}
          </Box>
        )}
        {topics.length > 1 && (
          <>
            <Typography sx={{ fontSize: 11, color: MUTED, mb: 0.25 }}>Earlier topics</Typography>
            {topics.slice(1, 6).map((t) => (
              <Typography key={t.text} sx={{ fontSize: 12 }} noWrap>
                <Box component="span" sx={{ color: MUTED, mr: 1 }}>{clock(t.first_seen)}</Box>{t.text}
              </Typography>
            ))}
          </>
        )}
      </Box>
    </Box>
  );
};
