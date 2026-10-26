import { Box, Button, Collapse, Typography } from '@mui/material';
import { ExpandMore, RocketLaunchOutlined } from '@mui/icons-material';
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { neutralButtonSx } from '../common/PageChrome';
import type { MergedUpgrade } from './releaseNotesParser';
import { TYPOGRAPHY } from '../../constants/typography';

/** One line of the checklist; a long list collapses to a count with a "Show list" link. */
const UpgradeRow: React.FC<{ label: string; items: string[]; plain: boolean }> = ({ label, items, plain }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const [list, setList] = useState(false);
  const long = items.length > 5;
  return (
    <Box sx={{ display: 'flex', gap: 1, py: 0.4, fontSize: TYPOGRAPHY.caption.size, alignItems: 'baseline' }}>
      <Box component="span" sx={{ color: P.textSecondary, minWidth: 110 }}>{label}</Box>
      <Box component="span" sx={{ flex: 1, minWidth: 0, fontFamily: plain ? 'inherit' : 'monospace', overflowWrap: 'anywhere' }}>
        {long && !list ? (
          <Box component="span" sx={{ fontFamily: 'inherit' }}>{tn(items.length, '{count} file', '{count} files')}</Box>
        ) : (
          items.join(plain ? ' · ' : ', ')
        )}
        {long && (
          <Box
            component="button"
            onClick={() => setList((v) => !v)}
            sx={{ ml: 1, border: 0, background: 'none', p: 0, cursor: 'pointer', color: P.accentText, fontSize: TYPOGRAPHY.caption.size, fontFamily: 'inherit' }}
          >
            {list ? t('Hide list') : t('Show list')}
          </Box>
        )}
      </Box>
    </Box>
  );
};

/**
 * The upgrade of one build (or several): only what needs a hand — migrations, new .env keys,
 * services to restart, other manual steps. Nothing needed = one line. The how lives on Platform update.
 */
const ReleaseUpgrade: React.FC<{ upgrade: MergedUpgrade; canRollOut: boolean; to?: string }> = ({ upgrade, canRollOut, to }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const { migrations, envKeys, services, other } = upgrade;
  const parts = [
    migrations.length ? tn(migrations.length, '{count} migration', '{count} migrations') : null,
    envKeys.length ? tn(envKeys.length, '{count} new .env key', '{count} new .env keys') : null,
    services.length ? `${t('restart')} ${services.length}` : null,
    other.length ? tn(other.length, '{count} manual step', '{count} manual steps') : null,
  ].filter(Boolean);
  const needs = parts.length > 0;
  const row = (label: string, items: string[]) =>
    items.length > 0 && <UpgradeRow key={label} label={label} items={items} plain={label === t('Other steps')} />;
  return (
    <Box sx={{ mt: 1.25, border: 1, borderStyle: 'dashed', borderColor: P.borderColor, borderRadius: 1.5, px: 1.5, py: 0.75 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, fontSize: TYPOGRAPHY.body.size, flexWrap: 'wrap' }}>
        <Box
          role={needs ? 'button' : undefined}
          tabIndex={needs ? 0 : undefined}
          aria-expanded={needs ? open : undefined}
          onClick={needs ? () => setOpen((v) => !v) : undefined}
          sx={{ display: 'flex', alignItems: 'center', gap: 1, cursor: needs ? 'pointer' : 'default', flex: 1, minWidth: 0 }}
        >
          <RocketLaunchOutlined sx={{ fontSize: TYPOGRAPHY.cardTitle.size, color: 'text.secondary' }} aria-hidden />
          <b>{t('Upgrade')}</b>
          <Typography component="span" sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.body.size }}>
            {needs ? parts.join(' · ') : t('Nothing to do by hand.')}
          </Typography>
          {needs && <ExpandMore sx={{ fontSize: TYPOGRAPHY.navbarItem.size, color: P.textMuted, transform: open ? 'rotate(180deg)' : 'none' }} />}
        </Box>
        {canRollOut && (
          <Button size="small" sx={neutralButtonSx(P)} onClick={() => navigate(`/configuration/platform-update${to ? `?to=${to}` : ''}`)}>
            {t('Platform update')} →
          </Button>
        )}
      </Box>
      <Collapse in={open} unmountOnExit>
        <Box sx={{ pt: 0.5 }}>
          {row(t('Migrations'), migrations)}
          {row(t('New .env keys'), envKeys)}
          {row(t('Restart'), services)}
          {row(t('Other steps'), other)}
        </Box>
      </Collapse>
    </Box>
  );
};

export default ReleaseUpgrade;
