/**
 * The live device stream with a LIVE pill, and a strip of the step screenshots below it
 * (click one to see it large; "Live" returns to the stream). The strip is hidden when no
 * step carries a screenshot.
 */
import { Box, Button, Typography } from '@mui/material';
import React, { useEffect, useMemo, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import type { LiveRunStep } from '../../hooks/script/useLiveScriptProgress';
import { DeviceStreamGrid, type DeviceStreamGridProps } from '../common/DeviceStreaming/DeviceStreamGrid';
import { neutralButtonSx } from '../common/PageChrome';
import { stepState } from './runLiveModel';

interface LiveStreamCardProps {
  device: { hostName: string; deviceId: string } | null;
  streamProps: Omit<DeviceStreamGridProps, 'devices'>;
  steps: LiveRunStep[];
  running: boolean;
  /** Step number whose frame is shown large (controlled by the page when a step row is clicked). */
  selected: number | null;
  onSelect: (stepNumber: number | null) => void;
  caption?: string;
}

export const LiveStreamCard: React.FC<LiveStreamCardProps> = ({ device, streamProps, steps, running, selected, onSelect, caption }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const frames = useMemo(() => steps.filter((s) => !!s.screenshot), [steps]);
  const stripRef = useRef<HTMLDivElement>(null);
  const [broken, setBroken] = useState<Set<string>>(new Set());
  useEffect(() => {
    const el = stripRef.current;
    if (el && selected == null) el.scrollLeft = el.scrollWidth;
  }, [frames.length, selected]);
  const shown = selected != null ? frames.find((s) => s.number === selected) : undefined;
  const live = !shown && !!device;

  return (
    <Box data-testid="live-stream-card" sx={{ display: 'flex', flexDirection: 'column', gap: 1.25, minWidth: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        {live && running ? (
          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, px: 1, py: 0.125, borderRadius: 999, fontSize: TYPOGRAPHY.microMeta.size, fontWeight: 600, color: P.error, border: `1px solid ${P.error}` }}>
            <Box component="span" sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: P.error }} />
            {t('LIVE')}
          </Box>
        ) : null}
        <Typography variant="caption" sx={{ color: P.textSecondary, flex: 1, minWidth: 0 }} noWrap>
          {shown ? t('Step {n} frame', { n: shown.number }) : caption}
        </Typography>
        {shown ? (
          <Button size="small" variant="outlined" sx={neutralButtonSx(P)} onClick={() => onSelect(null)}>{t('Back to live')}</Button>
        ) : null}
      </Box>
      <Box sx={{ minHeight: 120, borderRadius: 2, overflow: 'hidden', border: `1px solid ${P.borderColor}`, bgcolor: P.hoverBg }}>
        {shown ? (
          <Box component="img" src={shown.screenshot as string} alt={t('Step {n} frame', { n: shown.number })} sx={{ display: 'block', width: '100%', maxHeight: 420, objectFit: 'contain' }} />
        ) : device ? (
          <DeviceStreamGrid {...streamProps} devices={[device]} maxColumns={1} />
        ) : (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <Typography variant="body2" sx={{ color: P.textSecondary }}>{t('No live stream for this run')}</Typography>
          </Box>
        )}
      </Box>
      {frames.length > 0 ? (
        <Box ref={stripRef} data-testid="frame-strip" sx={{ display: 'flex', gap: 0.75, overflowX: 'auto', pb: 0.5 }}>
          {frames.map((s) => {
            const state = stepState(s);
            const on = s.number === selected;
            return (
              <Box
                key={s.number}
                component="button"
                type="button"
                title={t('Step {n}', { n: s.number })}
                onClick={() => onSelect(on ? null : s.number)}
                sx={{
                  flex: '0 0 auto', p: 0, width: 72, height: 44, borderRadius: 1, overflow: 'hidden', cursor: 'pointer',
                  bgcolor: P.hoverBg, border: `2px solid ${on ? P.selectedBorder : state === 'failed' ? P.error : P.borderColor}`,
                }}
              >
                {broken.has(s.screenshot as string) ? null : (
                  <Box
                    component="img"
                    src={s.screenshot as string}
                    alt=""
                    loading="lazy"
                    onError={() => setBroken((prev) => new Set(prev).add(s.screenshot as string))}
                    sx={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                  />
                )}
              </Box>
            );
          })}
        </Box>
      ) : null}
    </Box>
  );
};
