/**
 * ProjectSelector — TASK-65 G2
 *
 * Top-bar selector for the active project. Sits after `WorkspaceSwitcher`. Localizes
 * to fr/de via `useI18n`. Looks like the existing top-bar chips (ServerSelector,
 * WorkspaceSwitcher): a small `outlined` MUI Select with a `lucide`-style folder
 * icon (MUI's `Folder`) + the current value + a caret.
 *
 * The "scope-aware" warning (gold border + tooltip when no project is active on
 * a page that should be scoped) is the only extra. Never blocks creation —
 * `Task-65 Q2=1`: a projectless artifact is fine; the warning is information.
 *
 * The dropdown carries four actions:
 *   * All projects (no scope)
 *   * one entry per project
 *   * "Create project…" — opens the inline dialog
 *   * "Manage projects…" — links to /projects (G3)
 *   * "View all projects" — links to /projects (G3)
 *
 * G3 renders `/projects`; until then these links 404, which is fine — the chip
 * still works for the rest of G2.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import {
  Box,
  Button,
  Chip as MuiChip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Tooltip,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import SettingsIcon from '@mui/icons-material/Settings';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import {
  Project,
  useCurrentProject,
} from '../../hooks/common/useCurrentProject';
import { TYPOGRAPHY } from '../../constants/typography';


const ALL_VALUE = '__all__';
const MAX_NAME_LEN = 60;
const PALETTE: ReadonlyArray<string> = [
  '#FFB300', '#43A047', '#1E88E5', '#E53935', '#8E24AA',
  '#00ACC1', '#FB8C00', '#5E35B1', '#3949AB', '#039BE5',
  '#00897B', '#7CB342', '#C0CA33', '#FDD835', '#F4511E',
];


interface ProjectSelectorProps {
  /** The min width of the chip (matches WorkspaceSwitcher's 140 default). */
  minWidth?: number;
  size?: 'small' | 'medium';
}


// ---------------------------------------------------------------------------
// CreateProjectDialog (inline; selector-specific)
// ---------------------------------------------------------------------------
export const CreateProjectDialog: React.FC<{
  open: boolean;
  onClose: () => void;
  onCreated: (project: Project) => void;
}> = ({ open, onClose, onCreated }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const [name, setName] = useState('');
  const [color, setColor] = useState<string>(PALETTE[0]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset state every time the dialog reopens.
  useEffect(() => {
    if (!open) return;
    setName('');
    setColor(PALETTE[0]);
    setError(null);
    setSubmitting(false);
  }, [open]);

  const trimmedName = name.trim();
  const tooLong = trimmedName.length > MAX_NAME_LEN;
  const nameOk = trimmedName.length > 0 && !tooLong;

  const submit = async () => {
    if (!nameOk) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.post<Project>(
        buildServerUrl('/server/projects'),
        { name: trimmedName, color },
      );
      onCreated(created);
      onClose();
    } catch (e) {
      // The server returns 409 for a duplicate name (UNIQUE(team_id, LOWER(name))).
      const msg = (e && typeof e === 'object' && 'message' in e) ? String((e as { message?: unknown }).message || '') : '';
      if (/409|duplicate|already exists/i.test(msg)) {
        setError(t('A project with that name already exists in this team'));
      } else {
        setError(t('Failed to create project'));
      }
      // Keep the dialog open so they can fix and retry.
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={submitting ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{t('Create project')}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
          <Tooltip
            title={t('Use 60 characters or fewer')}
            open={tooLong}
            placement="top"
            arrow
          >
            <TextField
              label={t('Project name')}
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              fullWidth
              size="small"
              error={tooLong}
              helperText={tooLong ? t('Project name is too long') : `${trimmedName.length} / ${MAX_NAME_LEN}`}
              disabled={submitting}
            />
          </Tooltip>
          <Box>
            <Box sx={{ fontSize: TYPOGRAPHY.body.size, color: 'text.secondary', mb: 0.75 }}>
              {t('Project color')}
            </Box>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              {PALETTE.map((c) => (
                <Box
                  key={c}
                  role="button"
                  aria-label={c}
                  onClick={() => setColor(c)}
                  sx={{
                    width: 24,
                    height: 24,
                    borderRadius: '50%',
                    backgroundColor: c,
                    cursor: submitting ? 'not-allowed' : 'pointer',
                    outline: color === c
                      ? `2px solid ${P.accent}`
                      : '1px solid transparent',
                    outlineOffset: 2,
                    opacity: submitting ? 0.5 : 1,
                  }}
                />
              ))}
            </Box>
          </Box>
          {error && (
            <Box sx={{ color: P.error, fontSize: TYPOGRAPHY.body.size }}>{error}</Box>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>{t('Cancel')}</Button>
        <Button onClick={submit} disabled={!nameOk || submitting} variant="contained">
          {submitting ? t('Creating…') : t('Create project')}
        </Button>
      </DialogActions>
    </Dialog>
  );
};


// ---------------------------------------------------------------------------
// ProjectSelector
// ---------------------------------------------------------------------------
const ProjectSelector: React.FC<ProjectSelectorProps> = ({
  minWidth = 160,
  size = 'small',
}) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const navigate = useNavigate();
  const {
    projects,
    currentProject,
    setCurrentProject,
    isLoading,
    isOnScopeAwarePage,
    refresh,
  } = useCurrentProject();

  const [createOpen, setCreateOpen] = useState(false);

  const value = currentProject?.id ?? ALL_VALUE;
  const showScopeWarning = isOnScopeAwarePage && !currentProject;

  const renderSelected = (v: unknown): React.ReactNode => {
    if (v === ALL_VALUE) return t('All');
    const proj = projects.find((p) => p.id === v);
    if (!proj) return '';
    return proj.name;
  };

  const select = (
    <FormControl
      size={size}
      sx={{
        minWidth,
        // Gold border + glow when no project on a scope-aware page (TASK-65 §2 G2).
        // Never blocks creation; it's an informational reminder.
        '& .MuiOutlinedInput-root': showScopeWarning
          ? {
              borderColor: P.accent,
              boxShadow: `0 0 0 1px ${P.accent}`,
              '& fieldset': { borderColor: P.accent },
              '&:hover fieldset': { borderColor: P.accent },
              '&.Mui-focused fieldset': { borderColor: P.accent },
            }
          : undefined,
      }}
      variant="outlined"
    >
      <InputLabel sx={{ fontSize: TYPOGRAPHY.body.size }}>{t('Project')}</InputLabel>
      <Select
        value={value}
        label={t('Project')}
        onChange={(e) => {
          const v = e.target.value;
          setCurrentProject(v === ALL_VALUE ? null : v);
        }}
        renderValue={renderSelected}
        MenuProps={{
          PaperProps: {
            sx: {
              '& .MuiList-root': { py: 0.25 },
              '& .MuiMenuItem-root': {
                minHeight: 28,
                py: 0.25,
                px: 1,
                fontSize: TYPOGRAPHY.body.size,
                lineHeight: 1.2,
              },
            },
          },
        }}
        sx={{
          '& .MuiSelect-select': {
            display: 'flex',
            alignItems: 'center',
            fontSize: TYPOGRAPHY.body.size,
            py: 0.5,
          },
        }}
      >
        {/* Header: section label */}
        <MenuItem disabled sx={{ opacity: '1 !important', fontWeight: 600 }}>
          {t('Projects')}
        </MenuItem>

        <MenuItem value={ALL_VALUE}>
          <Box component="em" sx={{ opacity: 0.8 }}>{t('All')}</Box>
        </MenuItem>

        {isLoading && projects.length === 0 && (
          <MenuItem disabled>{t('Loading…')}</MenuItem>
        )}

        {projects.map((p) => (
          <MenuItem
            key={p.id}
            value={p.id}
            sx={{
              gap: 1,
            }}
          >
            <Box sx={{ minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {p.name}
            </Box>
            {p.owner_count > 0 && (
              <MuiChip
                size="small"
                label={t('{count} owners', { count: p.owner_count })}
                sx={{ height: 18, fontSize: TYPOGRAPHY.microMeta.size }}
              />
            )}
          </MenuItem>
        ))}

        {/* Divider + actions */}
        <Box sx={{ borderTop: `1px solid ${P.borderColor}`, my: 0.5 }} />

        <MenuItem onClick={(e) => { e.stopPropagation(); setCreateOpen(true); }}>
          <AddIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size, mr: 1 }} />
          {t('Create project…')}
        </MenuItem>
        <MenuItem onClick={(e) => { e.stopPropagation(); navigate('/projects'); }}>
          <SettingsIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size, mr: 1 }} />
          {t('Manage projects…')}
        </MenuItem>
        <MenuItem onClick={(e) => { e.stopPropagation(); navigate('/projects'); }}>
          <OpenInNewIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size, mr: 1 }} />
          {t('View all projects')}
        </MenuItem>
      </Select>
    </FormControl>
  );

  const wrapped = showScopeWarning ? (
    <Tooltip
      title={t('Pick a project to scope this page')}
      placement="bottom"
      arrow
    >
      <span>{select}</span>
    </Tooltip>
  ) : select;

  return (
    <>
      {wrapped}
      <CreateProjectDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={async () => {
          await refresh();
        }}
      />
    </>
  );
};

export default ProjectSelector;