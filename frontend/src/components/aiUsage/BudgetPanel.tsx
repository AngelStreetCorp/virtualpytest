/**
 * Monitoring → AI usage Budgets panel (TASK-87 phase 5 / BUG-0559).
 *
 * Renders one card per AI budget bucket that applies to the current team. Each card shows
 * its priced spend this month, the linear month-end forecast, and the bucket's
 * mode (warn / block). Most-specific bucket first (usage > model > endpoint > user > project > team).
 *
 * A super admin gets an "Add bucket" button that opens an editor; a team admin gets a read-only
 * view (the team's own budget row stays editable in Settings → AI). Failures
 * (older server / API down) degrade to the "no budget" empty state.
 */
import { Add as AddIcon, Delete as DeleteIcon } from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  Card,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useCallback, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { useProfile } from '../../hooks/auth/useProfile';

import { BUCKET_TYPES, BudgetBucketsReport, BudgetStatus, deleteBucket, fetchBudget, upsertBucket } from './api';
import { fmtCost, fmtPct } from './format';
import { PanelError } from './PanelError';
import { useAiLoad } from './useAiLoad';
import { TYPOGRAPHY } from '../../constants/typography';

const SPECIFICITY_ORDER: Record<BudgetStatus['bucket_type'], number> = {
  usage: 6, model: 5, endpoint: 4, user: 3, project: 2, team: 1,
};

type Translate = (key: string) => string;

const bucketLabel = (type: BudgetStatus['bucket_type'], t: Translate): string => {
  switch (type) {
    case 'team': return t('Team');
    case 'user': return t('User');
    case 'model': return t('Model');
    case 'endpoint': return t('Endpoint');
    case 'usage': return t('Usage key');
    default: return t('Project');
  }
};

interface EditorState {
  open: boolean;
  bucket_type: BudgetStatus['bucket_type'];
  bucket_id: string;
  label: string;
  month_limit_usd: string;
  mode: 'warn' | 'block';
  warn_at: string;
  saving: boolean;
  error: string | null;
}

const emptyEditor = (endpoint?: string): EditorState => ({
  open: true,
  bucket_type: endpoint ? 'endpoint' : 'team',
  bucket_id: endpoint ?? '',
  label: '',
  month_limit_usd: '50',
  mode: 'warn',
  warn_at: '0.8',
  saving: false,
  error: null,
});

export const BudgetPanel: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { isPlatformAdmin } = useProfile();
  const { data, failed, reload } = useAiLoad('budget-buckets', () => fetchBudget() as Promise<BudgetBucketsReport>, []);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [busyDelete, setBusyDelete] = useState<string | null>(null);

  const openEditor = useCallback((endpoint?: string) => setEditor(emptyEditor(endpoint)), []);
  const closeEditor = useCallback(() => setEditor(null), []);

  const submit = useCallback(async () => {
    if (!editor) return;
    const team_scope = data?.team_id;
    if (!team_scope) {
      setEditor({ ...editor, error: t('No team scope to attach the bucket to') });
      return;
    }
    if (!editor.bucket_id) {
      setEditor({ ...editor, error: t('Bucket id is required') });
      return;
    }
    const limit = Number(editor.month_limit_usd);
    const warn = Number(editor.warn_at);
    if (!Number.isFinite(limit) || limit <= 0) {
      setEditor({ ...editor, error: t('Limit must be a number above 0') });
      return;
    }
    if (!Number.isFinite(warn) || warn <= 0 || warn > 1) {
      setEditor({ ...editor, error: t('Warn threshold must be in (0, 1]') });
      return;
    }
    setEditor({ ...editor, saving: true, error: null });
    try {
      await upsertBucket({
        bucket_type: editor.bucket_type,
        bucket_id: editor.bucket_id.trim(),
        team_scope,
        month_limit_usd: limit,
        mode: editor.mode,
        warn_at: warn,
        label: editor.label.trim() || null,
      });
      setEditor(null);
      reload();
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      setEditor({ ...editor, saving: false, error: message });
    }
  }, [editor, data?.team_id, reload, t]);

  const remove = useCallback(async (bucket: BudgetStatus) => {
    const key = `${bucket.bucket_type}:${bucket.bucket_id}`;
    setBusyDelete(key);
    try {
      await deleteBucket(bucket.bucket_type, bucket.bucket_id, bucket.team_scope);
      reload();
    } finally {
      setBusyDelete(null);
    }
  }, [reload]);

  if (failed) return <PanelError what={t('the budget')} onRetry={reload} />;
  if (!data) return null;
  // New shape (BucketsReport) has `buckets: []`. Legacy single-team shape has `budget: ...`
  const buckets: BudgetStatus[] = Array.isArray((data as { buckets?: BudgetStatus[] }).buckets)
    ? (data as { buckets: BudgetStatus[] }).buckets
    : ((data as unknown as { budget: BudgetStatus | null }).budget
        ? [((data as unknown as { budget: BudgetStatus | null }).budget as BudgetStatus)]
        : []);

  return (
    <Card sx={{ p: 1.5, bgcolor: P.surface }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1, gap: 1, flexWrap: 'wrap' }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{t('AI budgets (this month)')}</Typography>
        {isPlatformAdmin && (
          <Button size="small" startIcon={<AddIcon />} onClick={() => openEditor()} sx={{ textTransform: 'none' }}>
            {t('Add bucket')}
          </Button>
        )}
      </Box>

      {data.month && (
        <Box sx={{ mb: 1.5 }}>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{t('This month')}</Typography>
          <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, flexWrap: 'wrap' }}>
            <Typography sx={{ fontSize: TYPOGRAPHY.cardTitle.size, fontWeight: 600, fontVariantNumeric: 'tabular-nums', color: P.textPrimary }}>
              {fmtCost(data.month.spent) ?? '$0.00'}
            </Typography>
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
              {t('forecast: {amount}', { amount: fmtCost(data.month.forecast) ?? '–' })}
            </Typography>
          </Box>
          {(data.unbudgeted ?? []).map((u) => (
            <Box key={u.endpoint} sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5, flexWrap: 'wrap' }}>
              <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.warning }}>
                {u.name} {fmtCost(u.spent) ?? '$0.00'} {t('this month')} · {t('no budget')}
              </Typography>
              {isPlatformAdmin && (
                <Button size="small" onClick={() => openEditor(u.endpoint)} sx={{ textTransform: 'none' }}>
                  {t('Add bucket')}
                </Button>
              )}
            </Box>
          ))}
        </Box>
      )}

      {buckets.length === 0 && (
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>
          {t('No AI budget set for this team. Spend keeps flowing without a cap.')}
        </Typography>
      )}

      <Stack spacing={1}>
        {buckets
          .slice()
          .sort((a, b) => SPECIFICITY_ORDER[b.bucket_type] - SPECIFICITY_ORDER[a.bucket_type])
          .map((b) => {
            const color = b.state === 'over' ? P.error : b.state === 'warn' ? P.warning : P.success;
            const isDeleting = busyDelete === `${b.bucket_type}:${b.bucket_id}`;
            return (
              <Box key={`${b.bucket_type}:${b.bucket_id}`} sx={{ p: 1, borderRadius: 1, bgcolor: P.hoverBg }}>
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5, gap: 1, flexWrap: 'wrap' }}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Chip
                      label={bucketLabel(b.bucket_type, t)}
                      size="small"
                      sx={{ fontSize: TYPOGRAPHY.caption.size, height: 20, bgcolor: P.surface, color: P.textSecondary }}
                    />
                    <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 500, color: P.textPrimary }}>
                      {b.label || b.bucket_id}
                    </Typography>
                    <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
                      ({b.bucket_id})
                    </Typography>
                  </Stack>
                  {isPlatformAdmin && (
                    <Tooltip title={t('Delete this bucket')}>
                      <span>
                        <IconButton
                          size="small"
                          onClick={() => remove(b)}
                          disabled={isDeleting}
                        >
                          {isDeleting ? <CircularProgress size={14} /> : <DeleteIcon fontSize="small" />}
                        </IconButton>
                      </span>
                    </Tooltip>
                  )}
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, mb: 0.5 }}>
                  <Typography sx={{ fontSize: TYPOGRAPHY.cardTitle.size, fontWeight: 600, fontVariantNumeric: 'tabular-nums', color }}>
                    {fmtCost(b.spent) ?? '$0.00'}
                  </Typography>
                  <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
                    {t('{share} of {limit}', { share: fmtPct(b.share), limit: fmtCost(b.limit) ?? '$0.00' })}
                    {' · '}
                    {b.mode === 'block' ? t('blocks when used up') : t('warning only')}
                    {' · '}
                    {t('forecast: {amount}', { amount: fmtCost(b.forecast) ?? '–' })}
                  </Typography>
                </Box>
                <Box sx={{ height: 6, borderRadius: 1, bgcolor: P.surface }}>
                  <Box sx={{ height: '100%', width: `${Math.min(100, Math.max(1, b.share * 100))}%`, borderRadius: 1, bgcolor: color }} />
                </Box>
              </Box>
            );
          })}
      </Stack>

      {editor && (
        <Dialog open onClose={closeEditor} fullWidth maxWidth="sm">
          <DialogTitle>{t('Add AI budget bucket')}</DialogTitle>
          <DialogContent>
            <Stack spacing={2} sx={{ mt: 1 }}>
              <TextField
                select
                label={t('Bucket type')}
                value={editor.bucket_type}
                onChange={(e) => setEditor({ ...editor, bucket_type: e.target.value as BudgetStatus['bucket_type'] })}
                fullWidth
              >
                {BUCKET_TYPES.map((bt) => (
                  <MenuItem key={bt} value={bt}>{bucketLabel(bt, t)}</MenuItem>
                ))}
              </TextField>
              <TextField
                label={t('Bucket id (UUID for team / user / project; model name; endpoint name; usage key)')}
                value={editor.bucket_id}
                onChange={(e) => setEditor({ ...editor, bucket_id: e.target.value })}
                fullWidth
              />
              <TextField
                label={t('Label (optional)')}
                value={editor.label}
                onChange={(e) => setEditor({ ...editor, label: e.target.value })}
                fullWidth
              />
              <TextField
                label={t('Monthly limit (USD)')}
                type="number"
                inputProps={{ min: 0.01, step: 0.01 }}
                value={editor.month_limit_usd}
                onChange={(e) => setEditor({ ...editor, month_limit_usd: e.target.value })}
                fullWidth
              />
              <TextField
                select
                label={t('Mode')}
                value={editor.mode}
                onChange={(e) => setEditor({ ...editor, mode: e.target.value as 'warn' | 'block' })}
                fullWidth
              >
                <MenuItem value="warn">{t('Warning only (banner)')}</MenuItem>
                <MenuItem value="block">{t('Block when over (refuse the call)')}</MenuItem>
              </TextField>
              <TextField
                label={t('Warn threshold (0-1)')}
                type="number"
                inputProps={{ min: 0.01, max: 1, step: 0.05 }}
                value={editor.warn_at}
                onChange={(e) => setEditor({ ...editor, warn_at: e.target.value })}
                fullWidth
              />
              {editor.error && <Alert severity="error">{editor.error}</Alert>}
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={closeEditor} disabled={editor.saving}>{t('Cancel')}</Button>
            <Button onClick={submit} disabled={editor.saving} variant="contained">
              {editor.saving ? <CircularProgress size={16} /> : t('Save')}
            </Button>
          </DialogActions>
        </Dialog>
      )}
    </Card>
  );
};