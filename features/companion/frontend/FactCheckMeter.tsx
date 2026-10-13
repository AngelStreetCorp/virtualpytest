/**
 * Live-TV companion fact check meter (TASK-45), laid out like a live debate overlay: a panel per
 * speaker (accent colour, ring gauge, five averaged scores), the live sentence with Jev's scores for
 * it, and the sentences that went to the web check with their verdict.
 *
 * Rendered by DebateCard and SummaryCard when the companion returns `meter`, which it only does with
 * DEVICE{N}_COMPANION_FACTCHECK on. Scores are uncalibrated: every decision is logged server-side for
 * a later evaluation.
 */

import { Box, Typography } from '@mui/material';
import React from 'react';

import { O } from './overlayPalette';
import type { CompanionClaim, CompanionMeter } from './types';

// Palette tokens only (UI_STYLE.md); the strip is on the video, so the dark palette (overlayPalette).
const MUTED = O.textSecondary;
const TEXT = O.textPrimary;
const PANEL_BG = O.surface;
const PANEL_BORDER = `1px solid ${O.borderColor}`;
const TRACK = O.borderColor;
// One series colour per speaker, in the order the payload lists them (most sentences first): gold first.
const ACCENTS = O.series;
const UNKNOWN_ACCENT = O.textMuted;
const UNKNOWN = 'unknown';

type Scores = NonNullable<CompanionMeter['sentences'][number]['scores']>;
type Sentence = CompanionMeter['sentences'][number];

const QUESTIONS: { key: keyof Scores; label: string }[] = [
  { key: 'factual_claim', label: 'Factual claim' },
  { key: 'evasive', label: 'Evasive' },
  { key: 'contradicts_self', label: 'Contradicts self' },
  { key: 'emotional_appeal', label: 'Emotional appeal' },
  { key: 'dodged_question', label: 'Dodged question' },
];

const speakerName = (name: string | null | undefined) => (!name || name === UNKNOWN ? 'Unknown speaker' : name);

const clock = (t: number) =>
  new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

/** Ring gauge 0-100 in the speaker's colour, the number and a small caption inside. */
function Ring({ value, color, size = 84 }: { value: number; color: string; size?: number }): JSX.Element {
  const stroke = 6;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, value));
  return (
    <svg width={size} height={size} role="img" aria-label={`rhetoric index ${Math.round(v)}`}>
      <circle cx={size / 2} cy={size / 2} r={r} stroke={TRACK} strokeWidth={stroke} fill="none" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        stroke={color}
        strokeWidth={stroke}
        fill="none"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - v / 100)}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: 'stroke-dashoffset 0.4s' }}
      />
      <text x="50%" y="46%" dominantBaseline="central" textAnchor="middle" fill={TEXT} fontSize={size * 0.3}
            fontWeight={600} fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace">
        {Math.round(v)}
      </text>
      <text x="50%" y="70%" dominantBaseline="central" textAnchor="middle" fill={MUTED} fontSize={9}>
        rhetoric
      </text>
    </svg>
  );
}

/** Speaker panel bar: label and % on one line, a thin bar in the speaker's colour under it. */
function AverageBar({ label, value, color }: { label: string; value: number | undefined; color: string }): JSX.Element {
  const pct = typeof value === 'number' ? Math.max(0, Math.min(100, value * 100)) : 0;
  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
        <Box component="span" sx={{ color: MUTED }}>{label}</Box>
        <Box component="span" sx={{ color: TEXT, fontVariantNumeric: 'tabular-nums' }}>{Math.round(pct)}%</Box>
      </Box>
      <Box sx={{ height: 3, mt: 0.25, bgcolor: TRACK, borderRadius: 2, overflow: 'hidden' }}>
        <Box sx={{ height: '100%', width: `${pct}%`, bgcolor: color, borderRadius: 2, transition: 'width 0.4s' }} />
      </Box>
    </Box>
  );
}

/** Live sentence bar: label, a bar with a knob at the value, the value as 0.00. */
function ScoreRow({ label, value, color }: { label: string; value: number | undefined; color: string }): JSX.Element {
  const v = typeof value === 'number' ? Math.max(0, Math.min(1, value)) : 0;
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: '120px 1fr 40px', alignItems: 'center', gap: 1, fontSize: 11.5 }}>
      <Box component="span" sx={{ color: MUTED }}>{label}</Box>
      <Box sx={{ position: 'relative', height: 4, bgcolor: TRACK, borderRadius: 2 }}>
        <Box sx={{ height: '100%', width: `${v * 100}%`, bgcolor: color, borderRadius: 2, opacity: 0.85, transition: 'width 0.4s' }} />
        <Box sx={{ position: 'absolute', top: -3, left: `calc(${v * 100}% - 5px)`, width: 10, height: 10,
                   borderRadius: '50%', bgcolor: TEXT, transition: 'left 0.4s' }} />
      </Box>
      <Box component="span" sx={{ color: TEXT, textAlign: 'right', fontFamily: 'ui-monospace, Menlo, monospace' }}>
        {v.toFixed(2)}
      </Box>
    </Box>
  );
}

function SpeakerPanel({ speaker, color }: { speaker: CompanionMeter['speakers'][number]; color: string }): JSX.Element {
  return (
    <Box sx={{ flex: '1 1 200px', maxWidth: { md: 240 }, minWidth: 0, bgcolor: PANEL_BG, border: PANEL_BORDER,
               borderTop: `2px solid ${color}`, borderRadius: 2, p: 1.5 }}>
      <Typography noWrap sx={{ color: TEXT, fontSize: 13, fontWeight: 600, mb: 0.5 }}>{speakerName(speaker.name)}</Typography>
      <Box sx={{ display: 'flex', justifyContent: 'center', mb: 1 }}>
        <Ring value={speaker.index} color={color} />
      </Box>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
        {QUESTIONS.map((q) => <AverageBar key={q.key} label={q.label} value={speaker.avg?.[q.key]} color={color} />)}
      </Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 1, fontSize: 10.5, color: MUTED }}>
        <span>sentences scored</span>
        <Box component="span" sx={{ color: TEXT, fontVariantNumeric: 'tabular-nums' }}>{speaker.n}</Box>
      </Box>
    </Box>
  );
}

function LivePanel({ sentence, color }: { sentence: Sentence; color: string }): JSX.Element {
  return (
    <Box sx={{ flex: '2 1 340px', minWidth: 0, bgcolor: PANEL_BG, border: PANEL_BORDER, borderRadius: 2, p: 1.5,
               display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Typography sx={{ color: TEXT, fontSize: 15, lineHeight: 1.4 }}>{sentence.text}</Typography>
      <Typography sx={{ color: MUTED, fontSize: 11.5 }}>
        <Box component="span" sx={{ color }}>●</Box> {speakerName(sentence.speaker)}
        {typeof sentence.t === 'number' ? ` · ${clock(sentence.t)}` : ''}
      </Typography>
      <Typography sx={{ fontSize: 10.5, color: MUTED, mt: 0.5 }}>
        <Box component="span" sx={{ color: O.accentText, fontWeight: 600 }}>Jev</Box>
        {' '}scored this sentence in {sentence.ms ?? '…'} ms
      </Typography>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
        {QUESTIONS.map((q) => <ScoreRow key={q.key} label={q.label} value={sentence.scores?.[q.key]} color={color} />)}
      </Box>
    </Box>
  );
}

const VERDICT: Record<string, { icon: string; label: string; color: string }> = {
  supported: { icon: '✅', label: 'Supported', color: O.success },
  contradicted: { icon: '❌', label: 'Contradicted', color: O.error },
  unverified: { icon: '❔', label: 'Unverified', color: MUTED },
};

const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
};

/** The fact check of a claim: verdict, what the sources say, the first source as a link. */
export const ClaimCheck: React.FC<{ check: NonNullable<CompanionClaim['check']> }> = ({ check }) => {
  if (check.status === 'pending') return <Box component="span" sx={{ color: MUTED }}>checking…</Box>;
  if (check.status === 'capped') return <Box component="span" sx={{ color: MUTED }}>not checked (hourly limit)</Box>;
  if (check.status === 'failed') return <Box component="span" sx={{ color: MUTED }}>check failed</Box>;
  if (check.status === 'skipped') {
    // TASK-45 goal 5: Jev's gate said no to the web check. The fact-check list filters
    // skipped sentences out (see below), so this branch is for the rare case where the
    // payload still carries a check entry (e.g. the sentence is also shown in the live
    // panel). Mirror the gate's reason so it is at least legible.
    const why = check.reason === 'repeat' ? 'already checked' : 'too vague to check';
    return <Box component="span" sx={{ color: MUTED }}>skipped ({why})</Box>;
  }
  const v = VERDICT[check.verdict || 'unverified'];
  const source = check.sources?.[0];
  return (
    <Box component="span">
      <Box component="span" sx={{ color: v.color, fontWeight: 600 }}>{v.icon} {v.label}</Box>
      {check.note && <Box component="span" sx={{ color: MUTED }}> — {check.note}</Box>}
      {source && (
        <>
          {' · '}
          <Box component="a" href={source.url} target="_blank" rel="noopener noreferrer" sx={{ color: O.accentText }}>
            {host(source.url)}
          </Box>
        </>
      )}
    </Box>
  );
};

/** Speaker panels around the live sentence, then the fact-checked sentences. */
export default function FactCheckMeter({ meter }: { meter: CompanionMeter }): JSX.Element {
  const speakers = meter.speakers || [];
  const accent: Record<string, string> = {};
  speakers.filter((s) => s.name !== UNKNOWN).forEach((s, i) => { accent[s.name] = ACCENTS[i % ACCENTS.length]; });
  const colorOf = (name: string | null | undefined) => (name && accent[name]) || UNKNOWN_ACCENT;
  const [left, right, ...rest] = speakers;
  const live = meter.sentences?.[0];
  // TASK-45 goal 5: a skipped check means Jev's gate said no to the web call; do not show it
  // in the "Fact check" list at all (only the bar on the live panel may still carry it).
  const checked = (meter.sentences || []).filter((s) => s.check && s.check.status !== 'skipped');

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      {live || left ? (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5, alignItems: 'stretch' }}>
          {left && <SpeakerPanel speaker={left} color={colorOf(left.name)} />}
          {live && <LivePanel sentence={live} color={colorOf(live.speaker)} />}
          {right && <SpeakerPanel speaker={right} color={colorOf(right.name)} />}
          {rest.map((s) => <SpeakerPanel key={s.name} speaker={s} color={colorOf(s.name)} />)}
        </Box>
      ) : (
        <Typography sx={{ color: MUTED, fontSize: 12 }}>Listening… sentences are scored as the subtitles come in.</Typography>
      )}
      {checked.length > 0 && (
        <Box>
          <Typography sx={{ color: TEXT, fontSize: 13, fontWeight: 600, mb: 0.75 }}>
            Fact check
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
            {checked.map((s, i) => (
              <Box key={`${s.t ?? i}-${s.text}`} sx={{ bgcolor: PANEL_BG, border: PANEL_BORDER,
                         borderLeft: `2px solid ${colorOf(s.speaker)}`, borderRadius: 1.5, px: 1.25, py: 0.75 }}>
                <Typography sx={{ color: TEXT, fontSize: 13 }}>“{s.text}”</Typography>
                <Typography sx={{ fontSize: 11.5, mt: 0.25 }}>
                  <Box component="span" sx={{ color: MUTED }}>
                    {speakerName(s.speaker)}{typeof s.t === 'number' ? ` · ${clock(s.t)}` : ''} ·{' '}
                  </Box>
                  {s.check && <ClaimCheck check={s.check} />}
                </Typography>
              </Box>
            ))}
          </Box>
        </Box>
      )}
    </Box>
  );
}
