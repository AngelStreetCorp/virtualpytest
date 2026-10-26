import { Box, Button, DialogActions, DialogContent, DialogTitle, MenuItem, Select, Typography } from '@mui/material';
import React, { useEffect, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useCustomPageMutations, useSharing } from '../../hooks/customPages/useCustomPages';
import { describeError } from '../../hooks/reports/runManagementApi';
import { useToast } from '../../hooks/useToast';
import { useI18n } from '../../i18n/useI18n';
import { StyledDialog } from '../common/StyledDialog';
import { neutralButtonSx, primaryButtonSx } from '../common/PageChrome';

type Level = 'none' | 'view' | 'edit';

interface Props {
  pageId: string;
  title: string;
  open: boolean;
  onClose: () => void;
}

/**
 * Share a saved page with named team members (view or edit) or the whole team (view). Sharing grants no
 * right: the dialog shows, per person, how many blocks they would see locked before the owner saves.
 */
export const ShareDialog: React.FC<Props> = ({ pageId, title, open, onClose }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const { showSuccess, showError } = useToast();
  const { data, isLoading, error } = useSharing(pageId, open);
  const { saveSharing } = useCustomPageMutations();
  const [team, setTeam] = useState<Level>('none');
  const [levels, setLevels] = useState<Record<string, Level>>({});

  useEffect(() => {
    if (!data) return;
    setTeam(data.visibility === 'team' ? 'view' : 'none');
    setLevels(Object.fromEntries(data.members.map((m) => [m.user_id, m.shared ? (m.can_edit ? 'edit' : 'view') : 'none'])));
  }, [data]);

  const lockedText = (n: number | null) =>
    n === null ? t('Access unknown') : n === 0 ? t('Sees every block') : tn(n, 'Sees {count} block locked', 'Sees {count} blocks locked');

  const save = async () => {
    try {
      await saveSharing.mutateAsync({
        id: pageId,
        visibility: team === 'view' ? 'team' : 'private',
        shares: Object.entries(levels)
          .filter(([, level]) => level !== 'none')
          .map(([user_id, level]) => ({ user_id, can_edit: level === 'edit' })),
      });
      showSuccess(t('Sharing saved'));
      onClose();
    } catch (e) {
      showError(describeError(e));
    }
  };

  const picker = (value: Level, onChange: (l: Level) => void, label: string, withEdit: boolean) => (
    <Select size="small" value={value} onChange={(e) => onChange(e.target.value as Level)} inputProps={{ 'aria-label': label }} sx={{ minWidth: 130, fontSize: TYPOGRAPHY.body.size }}>
      <MenuItem value="none">{t('Not shared')}</MenuItem>
      <MenuItem value="view">{t('Can view')}</MenuItem>
      {withEdit && <MenuItem value="edit">{t('Can edit')}</MenuItem>}
    </Select>
  );

  return (
    <StyledDialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('Share "{title}"', { title })}</DialogTitle>
      <DialogContent>
        {isLoading && <Typography sx={{ color: P.textMuted }}>{t('Loading...')}</Typography>}
        {error && <Typography sx={{ color: P.error }}>{describeError(error)}</Typography>}
        {data && (
          <Box sx={{ display: 'flex', flexDirection: 'column' }}>
            <Row
              name={t('Whole team')}
              sub={tn(data.members.length, '{count} person', '{count} people')}
              locked={data.team_locked_max > 0 ? tn(data.team_locked_max, 'Up to {count} block locked', 'Up to {count} blocks locked') : t('Sees every block')}
              control={picker(team, setTeam, t('Whole team'), false)}
            />
            {data.members.map((m) => (
              <Row
                key={m.user_id}
                name={m.name}
                sub={m.role || ''}
                locked={lockedText(m.locked_blocks)}
                warn={(m.locked_blocks ?? 0) > 0}
                control={picker(levels[m.user_id] ?? 'none', (l) => setLevels((prev) => ({ ...prev, [m.user_id]: l })), m.name, true)}
              />
            ))}
            {data.members.length === 0 && <Typography sx={{ color: P.textMuted, py: 1 }}>{t('No other member in this team.')}</Typography>}
            <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, mt: 1.5 }}>
              {t('Sharing grants no right. Each person sees a block with their own permissions; a block they may not use shows as locked.')}
            </Typography>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} sx={neutralButtonSx(P)}>
          {t('Cancel')}
        </Button>
        <Button variant="contained" disabled={!data || saveSharing.isPending} onClick={save} sx={primaryButtonSx(P)}>
          {t('Save sharing')}
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

const Row: React.FC<{ name: string; sub: string; locked: string; warn?: boolean; control: React.ReactNode }> = ({ name, sub, locked, warn, control }) => {
  const P = useAgentChatPalette();
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 1, borderTop: `1px solid ${P.borderColor}` }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600 }} noWrap>
          {name}
        </Typography>
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: warn ? P.warning : P.textMuted }}>
          {sub ? `${sub} · ${locked}` : locked}
        </Typography>
      </Box>
      {control}
    </Box>
  );
};
