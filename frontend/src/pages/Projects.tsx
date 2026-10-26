/**
 * Projects — list page (TASK-65 G3)
 *
 * Landing `/projects`. Renders every project the caller can see as a card on
 * the gold-palette page chrome. Click the card -> `/projects/<id>`. The "Create
 * project" gold action reuses the same dialog as the top-bar selector (open via
 * a local state mirror).
 *
 * Visual contract: `pageSurfaceSx(P)` + `PageTitle` + cards. One gold filled
 * action per view (UI_STYLE contract #28). Dark + light + 390 px.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import {
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import FolderIcon from '@mui/icons-material/Folder';

import { PageTitle, dangerButtonSx, neutralButtonSx, pageSurfaceSx } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { PROJECT_COLOR_PALETTE } from '../constants/projectPalette';
import { useI18n } from '../i18n/useI18n';
import { usePermissions } from '../hooks/auth/usePermissions';
import { api } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';
import {
  Project,
  useCurrentProject,
} from '../hooks/common/useCurrentProject';
import { TYPOGRAPHY } from '../constants/typography';


const MAX_NAME_LEN = 60;


interface CreateDialogState {
  open: boolean;
  name: string;
  color: string;
  submitting: boolean;
  error: string | null;
}


const Projects: React.FC = () => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const navigate = useNavigate();
  const { hasPermission } = usePermissions();
  const canCreate = hasPermission('team:projects:create');

  const { refresh } = useCurrentProject();
  const { data, isLoading } = useQuery<Project[]>({
    queryKey: ['projects', 'list'],
    queryFn: async () => {
      const list = await api.get<Project[]>(buildServerUrl('/server/projects'));
      return Array.isArray(list) ? list : [];
    },
  });
  const projects = data ?? [];
  const queryClient = useQueryClient();

  // Bulk delete: select mode shows a checkbox per card; the backend still enforces admin/owner per project.
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const exitSelect = () => { setSelectMode(false); setSelected(new Set()); setDeleteError(null); };
  const toggleSelected = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  const allSelected = projects.length > 0 && selected.size === projects.length;

  const deleteSelected = async () => {
    setDeleting(true);
    const ids = Array.from(selected);
    const results = await Promise.allSettled(
      ids.map((id) => api.delete(buildServerUrl(`/server/projects/${id}`))),
    );
    const failed = ids.filter((_, i) => results[i].status === 'rejected');
    await queryClient.invalidateQueries({ queryKey: ['projects', 'list'] });
    await refresh();
    setDeleting(false);
    setConfirmDelete(false);
    if (failed.length === 0) {
      exitSelect();
    } else {
      setSelected(new Set(failed));
      setDeleteError(t('{count} could not be deleted (admins and project owners only)', { count: failed.length }));
    }
  };

  const [dialog, setDialog] = useState<CreateDialogState>({
    open: false, name: '', color: PROJECT_COLOR_PALETTE[0], submitting: false, error: null,
  });

  useEffect(() => {
    document.title = `${t('Projects')} | VirtualPyTest`;
  }, [t]);

  const openCreate = () => setDialog((d) => ({ ...d, open: true }));
  const closeCreate = () =>
    setDialog((d) => ({ ...d, open: false, name: '', color: PROJECT_COLOR_PALETTE[0], error: null, submitting: false }));

  const submitCreate = async () => {
    const trimmed = dialog.name.trim();
    if (!trimmed || trimmed.length > MAX_NAME_LEN) return;
    setDialog((d) => ({ ...d, submitting: true, error: null }));
    try {
      await api.post<Project>(buildServerUrl('/server/projects'),
        { name: trimmed, color: dialog.color });
      closeCreate();
      await refresh();
    } catch (e) {
      const msg = (e && typeof e === 'object' && 'message' in e)
        ? String((e as { message?: unknown }).message || '') : '';
      if (/409|duplicate|already exists/i.test(msg)) {
        setDialog((d) => ({ ...d, error: t('A project with that name already exists in this team'), submitting: false }));
      } else {
        setDialog((d) => ({ ...d, error: t('Failed to create project'), submitting: false }));
      }
    }
  };

  return (
    <Box sx={{ ...(pageSurfaceSx(P) as object), py: 2, px: { xs: 1, sm: 0 }, minWidth: 0 }}>
      <PageTitle
        title={t('Projects')}
        subtitle={t('Create, own, and scope the team\'s work')}
        right={
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {selectMode && (
              <>
                {deleteError && (
                  <Typography sx={{ color: P.error, fontSize: TYPOGRAPHY.body.size, alignSelf: 'center' }}>{deleteError}</Typography>
                )}
                <Button
                  sx={neutralButtonSx(P)}
                  onClick={() => setSelected(allSelected ? new Set() : new Set(projects.map((p) => p.id)))}
                >
                  {t('Select all')}
                </Button>
                <Button
                  sx={dangerButtonSx(P)}
                  disabled={selected.size === 0 || deleting}
                  onClick={() => setConfirmDelete(true)}
                  data-testid="projects-bulk-delete"
                >
                  {t('Delete selected ({count})', { count: selected.size })}
                </Button>
              </>
            )}
            {projects.length > 0 && (
              <Button
                sx={neutralButtonSx(P)}
                onClick={selectMode ? exitSelect : () => setSelectMode(true)}
                data-testid="projects-select-toggle"
              >
                {selectMode ? t('Done') : t('Select')}
              </Button>
            )}
            {canCreate && (
            <Button
              variant="contained"
              color="primary"
              startIcon={<AddIcon />}
              onClick={openCreate}
              disabled={dialog.submitting}
              data-testid="projects-create-cta"
            >
              {t('Create')}
            </Button>
            )}
          </Stack>
        }
      />

      {isLoading && projects.length === 0 && (
        <Typography sx={{ color: P.textSecondary, py: 4, textAlign: 'center' }}>
          {t('Loading…')}
        </Typography>
      )}

      {!isLoading && projects.length === 0 && (
        <Card sx={{ borderRadius: 3, mt: 2, border: `1px solid ${P.borderColor}`, boxShadow: 'none' }}>
          <CardContent sx={{ textAlign: 'center', py: 6 }}>
            <FolderIcon sx={{ fontSize: TYPOGRAPHY.displayKpi.size, color: P.textSecondary, mb: 1 }} />
            <Typography sx={{ fontWeight: 600, mb: 1 }}>{t('No projects yet')}</Typography>
            <Typography sx={{ color: P.textSecondary, mb: 2, fontSize: TYPOGRAPHY.body.size }}>
              {t('Create your first project to scope scripts, testcases and campaigns.')}
            </Typography>
            {canCreate && (
              <Button
                variant="contained"
                color="primary"
                startIcon={<AddIcon />}
                onClick={openCreate}
                disabled={dialog.submitting}
              >
                {t('Create')}
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {projects.length > 0 && (
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          {projects.map((p) => (
            <Grid item xs={12} sm={6} md={4} lg={3} key={p.id}>
              <Card
                sx={{
                  borderRadius: 3,
                  border: `1px solid ${P.borderColor}`,
                  boxShadow: 'none',
                  height: '100%',
                  transition: 'border-color 120ms ease',
                  '&:hover': { borderColor: P.accent },
                }}
                data-testid={`project-card-${p.id}`}
              >
                <CardActionArea
                  onClick={() => (selectMode ? toggleSelected(p.id) : navigate(`/projects/${p.id}`))}
                  sx={{ height: '100%', alignItems: 'flex-start' }}
                >
                  <CardContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.25, alignItems: 'flex-start' }}>
                    <Stack direction="row" spacing={1} alignItems="center">
                      {selectMode && (
                        <Checkbox
                          size="small"
                          checked={selected.has(p.id)}
                          tabIndex={-1}
                          disableRipple
                          sx={{ p: 0 }}
                        />
                      )}
                      <FolderIcon sx={{ color: p.color ?? P.accent }} />
                      <Typography
                        sx={{
                          fontWeight: 600,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          maxWidth: 220,
                        }}
                      >
                        {p.name}
                      </Typography>
                    </Stack>
                    {p.description && (
                      <Typography
                        sx={{
                          color: P.textSecondary,
                          fontSize: TYPOGRAPHY.body.size,
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                        }}
                      >
                        {p.description}
                      </Typography>
                    )}
                    <Stack direction="row" spacing={0.75} flexWrap="wrap" sx={{ pt: 0.5 }}>
                      <Chip
                        size="small"
                        label={t('{count} members', { count: p.member_count })}
                        sx={{ height: 20, fontSize: TYPOGRAPHY.microMeta.size }}
                      />
                      {p.owner_count > 0 && (
                        <Chip
                          size="small"
                          label={t('{count} owners', { count: p.owner_count })}
                          sx={{ height: 20, fontSize: TYPOGRAPHY.microMeta.size }}
                          color="primary"
                          variant="outlined"
                        />
                      )}
                      {(() => {
                        // G11 / BUG-0548 — only count user-attached tags, not
                        // the auto-created scope tag. Fall back to the legacy
                        // `tag_ids.length` for backends that don't yet expose
                        // `user_tag_count` (pre-migration 20261015b). After the
                        // migration is applied, the value is exact; before,
                        // the legacy count over-reports by 1.
                        const visibleTagCount = typeof p.user_tag_count === 'number'
                          ? p.user_tag_count
                          : p.tag_ids.length;
                        return visibleTagCount > 0 ? (
                          <Chip
                            size="small"
                            label={t('{count} tags', { count: visibleTagCount })}
                            sx={{ height: 20, fontSize: TYPOGRAPHY.microMeta.size }}
                            variant="outlined"
                          />
                        ) : null;
                      })()}
                    </Stack>
                  </CardContent>
                </CardActionArea>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      <Dialog open={confirmDelete} onClose={deleting ? undefined : () => setConfirmDelete(false)} maxWidth="xs" fullWidth>
        <DialogTitle>{t('Delete {count} projects?', { count: selected.size })}</DialogTitle>
        <DialogContent>
          <Typography sx={{ color: P.textSecondary }}>
            {t('This permanently removes the selected projects.')}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDelete(false)} disabled={deleting}>{t('Cancel')}</Button>
          <Button sx={dangerButtonSx(P)} onClick={deleteSelected} disabled={deleting} data-testid="projects-bulk-delete-confirm">
            {deleting ? t('Deleting…') : t('Delete')}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={dialog.open}
        onClose={dialog.submitting ? undefined : closeCreate}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>{t('Create project')}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
            <Tooltip
              title={t('Use 60 characters or fewer')}
              open={dialog.name.trim().length > MAX_NAME_LEN}
              placement="top"
              arrow
            >
              <TextField
                label={t('Project name')}
                value={dialog.name}
                onChange={(e) => setDialog((d) => ({ ...d, name: e.target.value }))}
                autoFocus
                fullWidth
                size="small"
                error={dialog.name.trim().length > MAX_NAME_LEN}
                helperText={
                  dialog.name.trim().length > MAX_NAME_LEN ? t('Project name is too long') : ' '
                }
                disabled={dialog.submitting}
              />
            </Tooltip>
            <Box>
              <Box sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textSecondary, mb: 0.75 }}>
                {t('Project color')}
              </Box>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                {PROJECT_COLOR_PALETTE.map((c) => (
                  <Box
                    key={c}
                    role="button"
                    aria-label={c}
                    onClick={() => setDialog((d) => ({ ...d, color: c }))}
                    sx={{
                      width: 24, height: 24, borderRadius: '50%',
                      backgroundColor: c,
                      cursor: dialog.submitting ? 'not-allowed' : 'pointer',
                      outline: dialog.color === c ? `2px solid ${P.accent}` : '1px solid transparent',
                      outlineOffset: 2,
                    }}
                  />
                ))}
              </Box>
            </Box>
            {dialog.error && (
              <Box sx={{ color: P.error, fontSize: TYPOGRAPHY.body.size }}>{dialog.error}</Box>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeCreate} disabled={dialog.submitting}>{t('Cancel')}</Button>
          <Button
            onClick={submitCreate}
            disabled={!dialog.name.trim() || dialog.name.trim().length > MAX_NAME_LEN || dialog.submitting}
            variant="contained"
          >
            {dialog.submitting ? t('Creating…') : t('Create project')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default Projects;