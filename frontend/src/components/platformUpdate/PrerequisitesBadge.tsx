import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Link,
  Tooltip,
  Typography,
} from '@mui/material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutline';
import { Link as RouterLink } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import type { CheckStatus, PrerequisiteCheck, PrerequisitesResult } from '../../hooks/platformUpdate/usePrerequisites';
import { TYPOGRAPHY } from '../../constants/typography';
import { neutralButtonSx } from '../common/PageChrome';
import { CommandBox } from './CommandBox';
import { FreeSpace } from './FreeSpace';
import { FrontendSetup } from './FrontendSetup';
import { UpdateHostOnce } from './UpdateHostOnce';

export const SETUP_GUIDE_PATH = '/docs/user-guide/platform-update';

interface Props {
  result: PrerequisitesResult | null;
  loading: boolean;
  error: string | null;
  onRecheck: () => void;
}

const StatusIcon: React.FC<{ status: CheckStatus; size?: number }> = ({ status, size = 18 }) => {
  const P = useAgentChatPalette();
  if (status === 'ok') return <CheckCircleOutlineIcon sx={{ fontSize: size, color: P.success }} />;
  if (status === 'ko') return <ErrorOutlineIcon sx={{ fontSize: size, color: P.error }} />;
  return <RemoveCircleOutlineIcon sx={{ fontSize: size, color: P.textMuted }} />;
};

const Row: React.FC<{ index: number; check: PrerequisiteCheck; open: boolean; toggle: () => void; onRecheck?: () => void }> = ({
  index, check, open, toggle, onRecheck,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const word = check.status === 'ok' ? 'OK' : check.status === 'ko' ? 'KO' : 'N/A';
  const color = check.status === 'ok' ? P.success : check.status === 'ko' ? P.error : P.textMuted;
  return (
    <Box sx={{ border: `1px solid ${check.status === 'ko' ? P.error : P.borderColor}`, borderRadius: 1.5, mb: 0.75 }}>
      <Box
        onClick={toggle}
        sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.25, py: 0.75, cursor: 'pointer' }}
        role="button"
        aria-expanded={open}
      >
        <Typography sx={{ width: 22, color: P.textMuted, fontSize: TYPOGRAPHY.body.size, fontVariantNumeric: 'tabular-nums' }}>{index}</Typography>
        <StatusIcon status={check.status} />
        <Typography sx={{ flex: 1, minWidth: 0, fontSize: TYPOGRAPHY.body.size, fontWeight: 500 }}>{t(check.title)}</Typography>
        {check.status !== 'na' && !check.required ? (
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{t('warning only')}</Typography>
        ) : null}
        <Typography sx={{ width: 36, textAlign: 'right', fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color }}>{word}</Typography>
        {open ? <ExpandLessIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size, color: P.textMuted }} /> : <ExpandMoreIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size, color: P.textMuted }} />}
      </Box>
      {open ? (
        <Box sx={{ px: 1.25, pb: 1.25, pl: 6.5 }}>
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary, mb: 0.75 }}>{check.detail}</Typography>
          {check.log ? (
            <Box
              component="pre"
              sx={{
                m: 0, mb: 0.75, p: 1, bgcolor: P.hoverBg, borderRadius: 1, fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace',
                whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: P.textSecondary, maxHeight: 160, overflowY: 'auto',
              }}
            >
              {check.log}
            </Box>
          ) : null}
          {check.status === 'ko' && check.fix ? (
            <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textSecondary, mb: 0.5 }}>
              <Box component="span" sx={{ fontWeight: 600 }}>{t('How to fix')}: </Box>
              {check.fix}
            </Typography>
          ) : null}
          {check.status === 'ko' && check.actions && check.actions.length > 0 ? (
            <Box sx={{ mb: 0.75 }}>
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 0.5 }}>
                {t('Run as root on the machine named above each command, then press Re-check.')}
              </Typography>
              {check.actions.map((a) => (
                <CommandBox key={`${a.machine}-${a.command}`} caption={a.machine} hint={a.reason} text={a.command} />
              ))}
              {onRecheck ? (
                <Button size="small" variant="outlined" sx={neutralButtonSx(P)} onClick={onRecheck}>
                  {t('Re-check')}
                </Button>
              ) : null}
            </Box>
          ) : null}
          {check.status === 'ko' && check.update_hosts && check.update_hosts.length > 0 ? (
            <Box sx={{ mb: 0.75 }}>
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 0.5 }}>
                {t('The page can update these hosts once (they need the shared source mounted).')}
              </Typography>
              {check.update_hosts.map((h) => <UpdateHostOnce key={h} host={h} onDone={() => onRecheck?.()} />)}
            </Box>
          ) : null}
          {check.status === 'ko' && check.id === 'frontend_ssh' && onRecheck ? <Box sx={{ mb: 0.75 }}><FrontendSetup onDone={onRecheck} /></Box> : null}
          {check.status === 'ko' && check.id === 'disk' && onRecheck ? <FreeSpace onDone={onRecheck} /> : null}
          <Link component={RouterLink} to={`${SETUP_GUIDE_PATH}#${check.doc_anchor}`} sx={{ fontSize: TYPOGRAPHY.body.size, color: P.accentText }}>
            {t('Setup guide')}
          </Link>
        </Box>
      ) : null}
    </Box>
  );
};

/** The checks as expandable rows (KO rows open by default): the badge dialog and Platform update step 0 show the same list. */
export const CheckList: React.FC<{ checks: PrerequisiteCheck[]; onRecheck?: () => void }> = ({ checks, onRecheck }) => {
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  return (
    <>
      {checks.map((check, i) => (
        <Row
          key={check.id}
          index={i + 1}
          check={check}
          onRecheck={onRecheck}
          open={toggled[check.id] ?? check.status === 'ko'}
          toggle={() => setToggled((prev) => ({ ...prev, [check.id]: !(prev[check.id] ?? check.status === 'ko') }))}
        />
      ))}
    </>
  );
};

/**
 * Badge next to the Platform update title (TASK-101 G5): `Prerequisites n/m · OK|KO`, an info icon that says what it is,
 * and a dialog that lists every check. KO rows are expanded by default; the dialog has a Re-check button.
 */
export const PrerequisitesBadge: React.FC<Props> = ({ result, loading, error, onRecheck }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [listKey, setListKey] = useState(0);

  const state: 'checking' | 'ok' | 'ko' | 'error' = !result ? (error ? 'error' : 'checking') : result.ok ? 'ok' : 'ko';
  const color = state === 'ok' ? P.success : state === 'ko' || state === 'error' ? P.error : P.textMuted;
  const word = state === 'ok' ? 'OK' : state === 'ko' ? 'KO' : state === 'error' ? '?' : '...';
  const counts = result ? `${result.passed}/${result.total}` : '-';

  return (
    <>
      <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, ml: 1.5, verticalAlign: 'middle' }}>
        <Box
          component="button"
          type="button"
          onClick={() => setOpen(true)}
          sx={{
            display: 'inline-flex', alignItems: 'center', gap: 0.75, px: 1.25, py: 0.25, minWidth: 190, cursor: 'pointer',
            font: 'inherit', fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color, bgcolor: 'transparent',
            border: `1px solid ${color}`, borderRadius: 4, justifyContent: 'center',
          }}
        >
          {loading && !result ? <CircularProgress size={12} color="inherit" /> : <StatusIcon status={state === 'ok' ? 'ok' : state === 'checking' ? 'na' : 'ko'} size={14} />}
          <Box component="span" sx={{ fontVariantNumeric: 'tabular-nums' }}>{t('Prerequisites')} {counts}</Box>
          <Box component="span">· {word}</Box>
        </Box>
        <Tooltip
          title={t('The machines must be ready for this update. Click for every check.')}
        >
          <IconButton size="small" aria-label={t('What are the prerequisites?')} onClick={() => setOpen(true)}>
            <InfoOutlinedIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size, color: P.textMuted }} />
          </IconButton>
        </Tooltip>
      </Box>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>{t('Prerequisites')}</DialogTitle>
        <DialogContent sx={{ minHeight: 320 }}>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 1.5 }}>
            {t('A required KO check blocks deploys. "Warning only" never does.')}
          </Typography>
          {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
          {!result && loading ? <Typography sx={{ color: P.textMuted }}>{t('Checking...')}</Typography> : null}
          <CheckList key={listKey} checks={result?.checks ?? []} onRecheck={() => { setListKey((k) => k + 1); onRecheck(); }} />
        </DialogContent>
        <DialogActions sx={{ justifyContent: 'space-between', px: 3 }}>
          <Link component={RouterLink} to={`${SETUP_GUIDE_PATH}#step-0`} sx={{ fontSize: TYPOGRAPHY.body.size, color: P.accentText }}>
            {t('Setup guide')}
          </Link>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button variant="outlined" size="small" onClick={() => { setListKey((k) => k + 1); onRecheck(); }} disabled={loading}>
              {loading ? <CircularProgress size={16} color="inherit" /> : t('Re-check')}
            </Button>
            <Button size="small" onClick={() => setOpen(false)}>{t('Close')}</Button>
          </Box>
        </DialogActions>
      </Dialog>
    </>
  );
};
