import { Add } from '@mui/icons-material';
import { Box, Button, DialogActions, DialogContent, DialogTitle, TextField, Typography } from '@mui/material';
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { StyledDialog } from '../components/common/StyledDialog';
import { PageTitle, neutralButtonSx, pageSurfaceSx, primaryButtonSx } from '../components/common/PageChrome';
import { EmptyState, QueryState } from '../components/reports/PageState';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { TYPOGRAPHY } from '../constants/typography';
import { usePermissions } from '../hooks/auth/usePermissions';
import { useCustomPageMutations, useCustomPages } from '../hooks/customPages/useCustomPages';
import { describeError } from '../hooks/reports/runManagementApi';
import { useToast } from '../hooks/useToast';
import { useI18n } from '../i18n/useI18n';
import type { CustomPageSummary } from '../types/customPages';

const CustomPages: React.FC = () => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const navigate = useNavigate();
  const { showError } = useToast();
  const { hasPermission } = usePermissions();
  const { data, isLoading, error } = useCustomPages();
  const { create } = useCustomPageMutations();
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const canCreate = hasPermission('pages.custom:edit');

  const make = async () => {
    try {
      const page = await create.mutateAsync({ title: title.trim() });
      setCreating(false);
      setTitle('');
      navigate(`/pages/${page.id}?edit=1`);
    } catch (e) {
      showError(describeError(e));
    }
  };

  const items = data ?? [];
  const sections: { label: string; rows: CustomPageSummary[] }[] = [
    { label: t('My pages'), rows: items.filter((p) => p.access === 'owner' && p.status === 'saved') },
    { label: t('Drafts'), rows: items.filter((p) => p.access === 'owner' && p.status === 'draft') },
    { label: t('Shared with me'), rows: items.filter((p) => p.access !== 'owner') },
  ].filter((s) => s.rows.length > 0);

  return (
    <Box sx={[{ width: '100%', minWidth: 0, py: 2 }, ...([pageSurfaceSx(P)] as never[])]}>
      <PageTitle
        title={t('Pages')}
        subtitle={t('Pages built from blocks, by you or by Atlas. Ask Atlas: "make me a page with only my STBs, a node dropdown and the Localize result".')}
        right={
          canCreate && (
            <Button size="small" variant="contained" startIcon={<Add />} onClick={() => setCreating(true)} sx={primaryButtonSx(P)}>
              {t('New page')}
            </Button>
          )
        }
      />
      <QueryState loading={isLoading} error={error}>
        {items.length === 0 ? (
          <EmptyState message={t('No pages yet. Create one, or ask Atlas to build it for you.')} />
        ) : (
          sections.map((section) => (
            <Box key={section.label} sx={{ mb: 2.5 }}>
              <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600, mb: 0.75 }}>
                {section.label}
              </Typography>
              <Box sx={{ bgcolor: P.surface, border: `1px solid ${P.borderColor}`, borderRadius: 2 }}>
                {section.rows.map((p, i) => (
                  <Box
                    key={p.id}
                    component={Link}
                    to={`/pages/${p.id}`}
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1.5,
                      px: 2,
                      py: 1.25,
                      color: P.textPrimary,
                      textDecoration: 'none',
                      borderTop: i === 0 ? 'none' : `1px solid ${P.borderColor}`,
                      '&:hover': { bgcolor: P.hoverBg },
                    }}
                  >
                    <Typography sx={{ flex: 1, minWidth: 0, fontWeight: 600, fontSize: TYPOGRAPHY.body.size }} noWrap>
                      {p.title}
                    </Typography>
                    <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>
                      {tn(p.block_count, '{count} block', '{count} blocks')}
                    </Typography>
                    <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>
                      {p.visibility === 'team' ? t('team') : p.access === 'owner' ? t('private') : p.access === 'edit' ? t('can edit') : t('view only')}
                    </Typography>
                  </Box>
                ))}
              </Box>
            </Box>
          ))
        )}
      </QueryState>
      <StyledDialog open={creating} onClose={() => setCreating(false)} maxWidth="xs" fullWidth>
        <DialogTitle>{t('New page')}</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            size="small"
            sx={{ mt: 1 }}
            label={t('Page title')}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            inputProps={{ maxLength: 120 }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && title.trim()) make();
            }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreating(false)} sx={neutralButtonSx(P)}>
            {t('Cancel')}
          </Button>
          <Button variant="contained" disabled={!title.trim() || create.isPending} onClick={make} sx={primaryButtonSx(P)}>
            {t('Create')}
          </Button>
        </DialogActions>
      </StyledDialog>
    </Box>
  );
};

export default CustomPages;
