import ClosedCaptionIcon from '@mui/icons-material/ClosedCaption';
import { Box, MenuItem, Select, ToggleButton, Typography } from '@mui/material';
import React, { useEffect, useMemo, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useCaptionPlayback } from '../../hooks/useCaptionPlayback';
import { LANGUAGES, Language } from '../../i18n';
import { useI18n } from '../../i18n/useI18n';
import { ensureHostSession } from '../../utils/buildUrlUtils';
import { CHUNK_SECONDS, formatBehind, hostSecondOfDay, targetPosition } from '../../utils/captionPlayback';
import { TYPOGRAPHY } from '../../constants/typography';

interface Props {
  host: any;
  deviceId: string;
  delayS: number;
}

/**
 * Delayed player for a caption_playback device (TASK-103): plays `delayS` behind live from the archive's
 * growing 10-minute chunk, with machine captions (never held back by them) and a viewer language.
 */
export const CaptionPlaybackPlayer: React.FC<Props> = ({ host, deviceId, delayS }) => {
  const P = useAgentChatPalette();
  const { t, lang: appLang } = useI18n();
  const cp = useCaptionPlayback(host, deviceId, delayS);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [src, setSrc] = useState<{ hour: number; idx: number; v: number } | null>(null);
  const [ccOn, setCcOn] = useState(true);
  const [behind, setBehind] = useState<number | null>(null);
  const [waiting, setWaiting] = useState(false);
  const pendingSeek = useRef<number | null>(null);
  const srcRef = useRef(src);
  srcRef.current = src;
  const limitRef = useRef(cp.limit);
  limitRef.current = cp.limit;
  const hostOffsetRef = useRef(cp.hostOffset);
  hostOffsetRef.current = cp.hostOffset;

  // Pick where to be. Runs every second: starts playback, follows chunk changes, resyncs after a stall.
  useEffect(() => {
    const id = window.setInterval(() => {
      const v = videoRef.current;
      const hostOffset = hostOffsetRef.current;
      if (hostOffset == null) return; // the archive's hours are the host's: wait until its clock is known
      const want = targetPosition(Date.now(), delayS, hostOffset);
      const cur = srcRef.current;
      const wantFile = cp.findChunk(want.hour, want.chunkIndex);
      if (!cur) {
        if (!wantFile) return; // the archive has no chunk for the delayed position yet
        pendingSeek.current = want.offset; // captions never gate the picture: they catch up when ready
        void ensureHostSession(cp.chunkUrl(want.hour, want.chunkIndex)).then(() =>
          setSrc({ hour: want.hour, idx: want.chunkIndex, v: Date.now() }));
        return;
      }
      if (!v) return;
      const sameChunk = cur.hour === want.hour && cur.idx === want.chunkIndex;
      const atEnd = v.duration > 0 && v.currentTime >= v.duration - 0.8;
      if (!sameChunk && atEnd && wantFile) {
        pendingSeek.current = 0;
        setSrc({ hour: want.hour, idx: want.chunkIndex, v: Date.now() });
      } else if (sameChunk && atEnd) {
        pendingSeek.current = v.currentTime; // growing file: reload to pick up the newly appended minutes
        setSrc({ ...cur, v: Date.now() });
      }
      // The picture always plays; the badge only says the captions of this minute are not ready yet.
      setWaiting(sameChunk && v.currentTime >= limitRef.current - 0.2);
      if (v.paused && !v.ended && v.readyState >= 2) void v.play().catch(() => undefined);
      // Real offset behind live.
      const nowSec = hostSecondOfDay(Date.now(), hostOffset);
      const pos = cur.hour * 3600 + cur.idx * CHUNK_SECONDS + v.currentTime;
      const off = (((nowSec - pos) % 86400) + 86400) % 86400;
      setBehind(off);
      // Stalled far behind the profile delay: jump back to it.
      if (sameChunk && off > delayS + 60) {
        v.currentTime = want.offset;
      }
    }, 1000);
    return () => window.clearInterval(id);
  }, [delayS, cp.chunks, cp.chunkUrl]);

  const url = src ? `${cp.chunkUrl(src.hour, src.idx)}?t=${src.v}` : undefined;
  const vtt = useMemo(() => (cp.vtt ? URL.createObjectURL(new Blob([cp.vtt], { type: 'text/vtt' })) : null), [cp.vtt]);
  useEffect(() => () => { if (vtt) URL.revokeObjectURL(vtt); }, [vtt]);
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    for (const tr of Array.from(v.textTracks)) tr.mode = ccOn ? 'showing' : 'disabled';
  }, [ccOn, vtt, url]);

  const picked = cp.lang;
  const sourceShown = cp.shownLang != null && cp.shownLang !== picked;
  const langName = (code: string) => LANGUAGES.find((l) => l.code === code)?.name ?? code;
  const behindLabel = behind == null ? t('Starting…') : t('{time} behind live', { time: formatBehind(behind) });

  return (
    <Box sx={{ position: 'relative', flex: 1, display: 'flex', flexDirection: 'column', bgcolor: 'black', minWidth: 0 }}>
      <video
        key={url}
        ref={videoRef}
        src={url}
        autoPlay
        muted={false}
        playsInline
        crossOrigin="use-credentials"
        onLoadedMetadata={(e) => {
          if (pendingSeek.current != null) {
            e.currentTarget.currentTime = pendingSeek.current;
            pendingSeek.current = null;
          }
        }}
        style={{ flex: 1, minHeight: 0, width: '100%', objectFit: 'contain', background: 'black' }}
      >
        {vtt && <track key={vtt} kind="captions" src={vtt} srcLang={cp.shownLang ?? appLang} label={t('Machine captions')} default={ccOn} />}
      </video>

      {!url && (
        <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>
            {cp.manifestError ? t('The archive is not available yet.') : t('Waiting for the archive…')}
          </Typography>
        </Box>
      )}

      <Box sx={{ position: 'absolute', top: 10, left: 10, display: 'flex', gap: 1, alignItems: 'center' }}>
        <Box sx={{ px: 1.25, py: 0.4, borderRadius: 1.5, bgcolor: P.surfaceSolid, border: `1px solid ${P.borderColor}` }}>
          <Typography sx={{ color: P.textPrimary, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600 }}>{behindLabel}</Typography>
        </Box>
        {waiting && (
          <Box sx={{ px: 1.25, py: 0.4, borderRadius: 1.5, bgcolor: P.surfaceSolid, border: `1px solid ${P.borderColor}` }}>
            <Typography sx={{ color: P.warning, fontSize: TYPOGRAPHY.caption.size }}>{t('Waiting for captions…')}</Typography>
          </Box>
        )}
      </Box>

      <Box
        sx={{
          position: 'absolute', top: 10, right: 10, display: 'flex', gap: 1, alignItems: 'center',
          px: 1, py: 0.5, borderRadius: 1.5, bgcolor: P.surfaceSolid, border: `1px solid ${P.borderColor}`,
        }}
      >
        <ToggleButton
          value="cc"
          size="small"
          selected={ccOn}
          onChange={() => setCcOn((v) => !v)}
          aria-label={t('Captions')}
          sx={{ border: 'none', py: 0.25, px: 0.75, color: P.neutralText, '&.Mui-selected': { bgcolor: P.selectedBg, color: P.selectedText } }}
        >
          <ClosedCaptionIcon fontSize="small" />
        </ToggleButton>
        <Select
          size="small"
          value={picked}
          onChange={(e) => cp.setLang(e.target.value as Language)}
          aria-label={t('Caption language')}
          sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textPrimary, '& .MuiSelect-select': { py: 0.25 } }}
        >
          {LANGUAGES.map((l) => (
            <MenuItem key={l.code} value={l.code}>{l.name}</MenuItem>
          ))}
        </Select>
      </Box>

      <Box sx={{ position: 'absolute', left: 10, bottom: 10, right: 10, display: 'flex', justifyContent: 'space-between', pointerEvents: 'none' }}>
        <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.microMeta.size, bgcolor: P.surfaceSolid, px: 1, borderRadius: 1 }}>
          {t('Machine captions')}
          {sourceShown ? ` · ${t('shown in {language}, not translated yet', { language: langName(cp.shownLang as string) })}` : ''}
        </Typography>
      </Box>
    </Box>
  );
};

export default CaptionPlaybackPlayer;
