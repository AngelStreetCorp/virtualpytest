import { Box, Typography } from '@mui/material';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { LolOverlay } from '../components/game/lol/LolOverlay';
import { LolSpellRow } from '../components/game/lol/LolSpellRow';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { pageSurfaceSx } from '../components/common/PageChrome';
import {
  LOL_MARKER_TTL_S,
  LolMarker,
  LolTurnLine,
  LolZonesLine,
} from '../types/game/LolOverlay_Types';

const fmtNum = (n: number) => (Math.abs(n) >= 10 ? n.toFixed(0) : n.toFixed(2));

const parseJsonl = <T,>(text: string): T[] =>
  text.split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l) as T);

/** Index of the last line with t <= `t` (lines sorted by t), or -1. */
const lastAtOrBefore = (lines: { t: number }[], t: number): number => {
  let lo = 0;
  let hi = lines.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lines[mid].t <= t) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return found;
};

const STAT_LABELS: [string, (s: NonNullable<LolTurnLine['state']>) => string | number | undefined][] = [
  ['Health', (s) => (s.hp != null ? `${s.hp} / ${s.hp_max ?? '?'}` : undefined)],
  ['Mana', (s) => (s.mana_max ? `${s.mana} / ${s.mana_max}` : s.mana)],
  ['Attack', (s) => s.ad],
  ['Armor', (s) => s.armor],
  ['Magic resist', (s) => s.mr],
  ['Attack speed', (s) => s.attack_speed],
  ['Move speed', (s) => s.move_speed],
  ['Level', (s) => s.level],
  ['Gold', (s) => s.gold],
  ['CS', (s) => s.cs],
  ['Mode', (s) => s.mode],
];

const fmtClock = (t: number) => `${Math.floor(Math.max(0, t) / 60)}:${String(Math.floor(Math.max(0, t) % 60)).padStart(2, '0')}`;

/**
 * Recorded-run viewer: video + LoL overlay driven by zones.jsonl / turns.jsonl.
 * /lol-replay?video=<url>&zones=<url>&turns=<url>&offset=<video seconds of game 0:00>
 */
const LolReplay: React.FC = () => {
  const P = useAgentChatPalette();
  const [params] = useSearchParams();
  const video = params.get('video') ?? '';
  const offset = Number(params.get('offset') ?? 0) || 0;
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [zonesLines, setZonesLines] = useState<LolZonesLine[]>([]);
  const [turns, setTurns] = useState<LolTurnLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [gameT, setGameT] = useState(0);

  useEffect(() => {
    const load = async () => {
      try {
        const [z, t] = await Promise.all(
          (['zones', 'turns'] as const).map(async (k) => {
            const url = params.get(k);
            if (!url) throw new Error(`missing ?${k}=`);
            const r = await fetch(url);
            if (!r.ok) throw new Error(`${k}: HTTP ${r.status}`);
            return r.text();
          }),
        );
        setZonesLines(parseJsonl<LolZonesLine>(z));
        setTurns(parseJsonl<LolTurnLine>(t));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    };
    load();
  }, [params]);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = videoRef.current;
      if (v) setGameT(v.currentTime - offset);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [offset]);

  const zoneIdx = lastAtOrBefore(zonesLines, gameT);
  const turnIdx = lastAtOrBefore(turns, gameT);
  const turn = turnIdx >= 0 ? turns[turnIdx] : null;

  const markers = useMemo<LolMarker[]>(() => {
    const out: LolMarker[] = [];
    for (let i = turnIdx; i >= 0 && gameT - turns[i].t < LOL_MARKER_TTL_S; i--) {
      for (const inp of turns[i].inputs ?? []) out.push({ ...inp, age: gameT - turns[i].t });
    }
    return out;
  }, [turns, turnIdx, gameT]);

  /** Outcomes caused by the turns of the last 3 s of game time. */
  const recentOutcomes = useMemo(() => {
    const out: NonNullable<LolTurnLine['outcomes']> = [];
    for (let i = turnIdx; i >= 0 && gameT - turns[i].t < 3; i--) out.push(...(turns[i].outcomes ?? []));
    return out.slice(0, 8);
  }, [turns, turnIdx, gameT]);

  return (
    <Box sx={pageSurfaceSx(P)}>
    <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, gap: 2, p: 2 }}>
      <Box sx={{ position: 'relative', flex: 1, minWidth: 0, bgcolor: 'black', borderRadius: 1, overflow: 'hidden', aspectRatio: '16 / 10', alignSelf: 'flex-start', width: '100%' }}>
        <video ref={videoRef} src={video} controls playsInline style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
        {zoneIdx >= 0 && <LolOverlay zones={zonesLines[zoneIdx].zones} frame={zonesLines[zoneIdx].frame} markers={markers} units={turn?.world?.units} />}
      </Box>
      <Box sx={{ width: { xs: '100%', md: 320 }, color: P.textPrimary }} data-testid="lol-replay-panel">
        <Typography variant="h6" sx={{ mb: 1 }}>Game {fmtClock(gameT)}{turn?.turn != null ? ` · turn ${turn.turn}` : ''}</Typography>
        {error && <Typography sx={{ color: P.error, mb: 1 }}>{error}</Typography>}
        {turn?.state && (
          <Box sx={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 2, rowGap: 0.5, mb: 2 }}>
            {STAT_LABELS.map(([label, get]) => {
              const v = get(turn.state!);
              return v == null ? null : (
                <React.Fragment key={label}>
                  <Typography variant="body2" sx={{ color: P.textSecondary }}>{label}</Typography>
                  <Typography variant="body2">{v}</Typography>
                </React.Fragment>
              );
            })}
            {turn.state.spells && (
              <>
                <Typography variant="body2" sx={{ color: P.textSecondary }}>Spells</Typography>
                <LolSpellRow spells={turn.state.spells} />
              </>
            )}
            {turn.state.items?.length ? (
              <>
                <Typography variant="body2" sx={{ color: P.textSecondary }}>Items</Typography>
                <Typography variant="body2">{turn.state.items.join(', ')}</Typography>
              </>
            ) : null}
          </Box>
        )}
        {turn && (turn.reward != null || recentOutcomes.length > 0) && (
          <Box sx={{ mb: 2 }} data-testid="lol-replay-outcomes">
            {turn.reward != null && (
              <Typography variant="body2" sx={{ color: P.textSecondary }}>
                Reward <Box component="span" sx={{ color: turn.reward < 0 ? P.error : turn.reward > 0 ? P.success : P.textMuted }}>{fmtNum(turn.reward)}</Box>
                {turn.return_8s != null ? ` · next 8 s ${fmtNum(turn.return_8s)}` : ''}
              </Typography>
            )}
            {recentOutcomes.map((o, i) => (
              <Typography key={i} variant="caption" sx={{ display: 'block', color: o.value < 0 ? P.error : o.value > 0 ? P.success : P.textMuted }}>
                {o.event.replace(/_/g, ' ')} {fmtNum(o.value)}{o.cause_action ? ` · from ${o.cause_action}` : ''}
              </Typography>
            ))}
          </Box>
        )}
        {turn?.decision && (
          <Box sx={{ p: 1.5, borderRadius: 1, border: `1px solid ${P.borderColor}`, bgcolor: P.sidebarBg }}>
            <Typography variant="subtitle2">Decision: {turn.decision.choice}</Typography>
            <Typography variant="body2" sx={{ color: P.textSecondary }}>{turn.decision.reason}</Typography>
            {turn.decision.options?.map((o) => (
              <Typography key={o.id} variant="caption" sx={{ display: 'block', color: P.textMuted }}>{o.id}: {Math.round(o.p * 100)}%</Typography>
            ))}
          </Box>
        )}
        {!turn && !error && <Typography sx={{ color: P.textMuted }}>Press play: details appear from game 0:00.</Typography>}
      </Box>
    </Box>
    </Box>
  );
};

export default LolReplay;
