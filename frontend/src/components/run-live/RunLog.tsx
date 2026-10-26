/** Log of a live run, built from its step events: All / Steps / Warnings & errors, search, Follow, Wrap, Copy, Download. */
import { Box, Button, InputAdornment, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import React, { useEffect, useMemo, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AppIcon } from '../../constants/icons';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import type { LiveRunStep } from '../../hooks/script/useLiveScriptProgress';
import { segmentedSx, toggleSx } from '../common/PageChrome';
import { buildLogLines, formatClock, logToText, type LogLine } from './runLiveModel';

type Filter = 'all' | 'steps' | 'problems';

interface RunLogProps {
  steps: LiveRunStep[];
  fileName: string;
}

export const RunLog: React.FC<RunLogProps> = ({ steps, fileName }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [follow, setFollow] = useState(true);
  const [wrap, setWrap] = useState(true);
  const [copied, setCopied] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  const all = useMemo(() => buildLogLines(steps), [steps]);
  const problems = all.filter((l) => l.kind !== 'step').length;
  const lines = useMemo(() => {
    const q = query.trim().toLowerCase();
    return all.filter((l) => {
      if (filter === 'steps' && !l.id.match(/^l\d+$/)) return false;
      if (filter === 'problems' && l.kind === 'step') return false;
      return !q || l.text.toLowerCase().includes(q);
    });
  }, [all, filter, query]);

  useEffect(() => {
    const el = bodyRef.current;
    if (follow && el) el.scrollTop = el.scrollHeight;
  }, [lines.length, follow]);

  const colorOf = (l: LogLine) => (l.kind === 'error' ? P.error : l.kind === 'warn' ? P.warning : P.textPrimary);
  const text = () => logToText(lines);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text());
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([text()], { type: 'text/plain;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${fileName.replace(/[^\w.-]+/g, '_') || 'run'}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Box data-testid="run-log" sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <ToggleButtonGroup exclusive size="small" value={filter} onChange={(_e, v: Filter | null) => v && setFilter(v)} sx={segmentedSx(P, 'sm')}>
          <ToggleButton value="all">{t('All')}</ToggleButton>
          <ToggleButton value="steps">{t('Steps')}</ToggleButton>
          <ToggleButton value="problems">{t('Warnings & errors')}{problems > 0 ? ` ${problems}` : ''}</ToggleButton>
        </ToggleButtonGroup>
        <TextField
          size="small"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('Search the log')}
          sx={{ flex: '1 1 200px', minWidth: 160 }}
          InputProps={{ startAdornment: <InputAdornment position="start"><AppIcon name="search" /></InputAdornment> }}
        />
      </Box>
      <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2, overflow: 'hidden' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, px: 1.25, py: 0.5, bgcolor: P.hoverBg, borderBottom: `1px solid ${P.borderColor}` }}>
          <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.caption.size, flex: 1 }}>{t('Live log')}</Typography>
          <Button size="small" variant="outlined" sx={toggleSx(P, follow)} onClick={() => setFollow((v) => !v)}>{t('Follow')}</Button>
          <Button size="small" variant="outlined" sx={toggleSx(P, wrap)} onClick={() => setWrap((v) => !v)}>{t('Wrap')}</Button>
          <Button size="small" variant="outlined" sx={toggleSx(P, false)} startIcon={<AppIcon name="copy" />} onClick={() => void copy()}>{copied ? t('Copied') : t('Copy')}</Button>
          <Button size="small" variant="outlined" sx={toggleSx(P, false)} startIcon={<AppIcon name="download" />} onClick={download}>{t('Download')}</Button>
        </Box>
        <Box
          ref={bodyRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            if (follow && el.scrollHeight - el.scrollTop - el.clientHeight > 40) setFollow(false);
          }}
          sx={{ maxHeight: 260, minHeight: 80, overflow: 'auto', p: 1.25, fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, lineHeight: 1.6 }}
        >
          {lines.length === 0 ? (
            <Typography variant="caption" sx={{ color: P.textMuted }}>{all.length === 0 ? t('Waiting for the first step…') : t('No log line matches')}</Typography>
          ) : lines.map((l) => (
            <Box key={l.id} sx={{ whiteSpace: wrap ? 'pre-wrap' : 'pre', overflowWrap: wrap ? 'anywhere' : 'normal', color: colorOf(l) }}>
              <Box component="span" sx={{ color: P.textMuted }}>[{formatClock(l.at)}]</Box> {l.text}
            </Box>
          ))}
        </Box>
      </Box>
    </Box>
  );
};
