/**
 * AI usage, level 3 (TASK-147): one call. One line (feature · model · provider · host · time), four tiles
 * (result, latency, tokens, cost), the repeat count when the list folded a run of identical failures, the trace.
 */
import { Box, Button, Link, Typography } from '@mui/material';
import React, { useState } from 'react';

import { neutralButtonSx, primaryButtonSx } from '../common/PageChrome';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';

import { UsageQuery, UsageReport, fetchAiCall } from './api';
import { fmtCost, fmtCount, fmtDateTime, fmtSeconds, fmtTimeRange, fmtTokens } from './format';
import { callerLabel, categoryLabel, causeSentence, errorTypeLabel, nextStep, originLabel } from './labels';
import { PanelError } from './PanelError';
import { TraceDialog } from './TraceDialog';
import { TileRow, UsageTile } from './usageParts';
import { useAiLoad } from './useAiLoad';

interface Props {
  requestId: string;
  query: UsageQuery;
  base: UsageReport;
  /** Size and first time of the folded run this call stands for (1 = a single call). */
  repeat: number;
  first: string;
  onBack: () => void;
}

export const UsageCall: React.FC<Props> = ({ requestId, query, base, repeat, first, onBack }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [trace, setTrace] = useState(false);
  const load = useAiLoad('call', () => fetchAiCall(query, requestId), [requestId, query.hours, query.team]);
  if (load.failed) return <PanelError what={t('the call')} onRetry={load.reload} />;
  if (!load.data) return <Box sx={{ minHeight: 240 }} />;
  const c = load.data.calls[0];
  if (!c) return <Typography sx={{ color: P.textMuted }}>{t('No call with this id in the period.')}</Typography>;

  const provider = (base.providers ?? []).find((p) => p.endpoint === c.endpoint)?.name ?? c.endpoint;
  const feature = c.category ? categoryLabel(c.category, t, base.overview?.category_labels) : c.usage_label || c.usage_key;
  const avoided = c.outcome === 'avoided';
  const noPrice = c.cost == null && c.ok && !avoided;
  const bad = !c.ok && !avoided;
  const step = bad ? nextStep(c.error_type ?? '', (base.providers ?? []).find((p) => p.endpoint === c.endpoint)?.preset, t) : null;
  const who = [
    c.caller ? callerLabel(c.caller, t) : '',
    c.origin ? originLabel(c.origin, t) : '',
    c.script_name,
    c.device_id,
    c.images ? (c.images === 1 ? t('1 image') : t('{n} images', { n: fmtCount(c.images) })) : '',
    c.fallback_used ? t('fallback') : '',
    c.attempt_index ? t('attempt {n}', { n: c.attempt_index + 1 }) : '',
  ].filter(Boolean).join(' · ');
  const where = [feature, c.model, provider, c.host_name].filter(Boolean).join(' · ');

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, mb: 2, flexWrap: 'wrap' }}>
        {repeat > 1 && (
          <Box component="span" sx={{ px: 1, borderRadius: 2, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, bgcolor: `${P.error}24`, color: P.error }}>
            {fmtCount(repeat)}× · {fmtTimeRange(first, c.ts)}
          </Box>
        )}
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size }}>
          {where} <Box component="span" sx={{ color: P.textMuted }}>· {fmtDateTime(c.ts)}</Box>
        </Typography>
      </Box>
      <TileRow>
        <UsageTile label={t('Result')} value={avoided ? t('Avoided') : c.ok ? t('OK') : errorTypeLabel(c.error_type, t) || t('Failed')} color={bad ? P.error : undefined} />
        <UsageTile label={t('Latency')} value={fmtSeconds(c.latency_ms)} />
        <UsageTile label={t('Tokens')} value={fmtTokens(c.tokens_in + c.tokens_out)} caption={`${fmtTokens(c.tokens_in)} ${t('in')} · ${fmtTokens(c.tokens_out)} ${t('out')}`} />
        <UsageTile label={t('Cost')} value={noPrice ? t('no price') : fmtCost(c.cost) ?? '—'} hint={noPrice ? t('This model has no price') : undefined} />
      </TileRow>
      {bad && (
        <Typography sx={{ mb: 1.5, fontSize: TYPOGRAPHY.body.size }}>
          {causeSentence(c.error_type ?? '', provider, t)}
          {step && (
            <>
              {' · '}
              <Link href={step.href} {...(step.external ? { target: '_blank', rel: 'noopener noreferrer' } : {})} underline="hover">{step.label}</Link>
            </>
          )}
        </Typography>
      )}
      {who && <Typography sx={{ mb: 1.5, fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{who}</Typography>}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        {c.ok && c.trace_url && c.request_id && <Button size="small" sx={primaryButtonSx(P)} onClick={() => setTrace(true)}>{t('Trace')}</Button>}
        <Button size="small" sx={neutralButtonSx(P)} onClick={onBack}>{t('Back')}</Button>
        <Typography sx={{ ml: 'auto', fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, fontFamily: 'monospace' }}>{c.request_id}</Typography>
      </Box>
      {trace && c.request_id && <TraceDialog traceId={c.request_id} onClose={() => setTrace(false)} />}
    </Box>
  );
};
