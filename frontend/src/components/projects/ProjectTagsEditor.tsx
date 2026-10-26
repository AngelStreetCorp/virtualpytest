/**
 * ProjectTagsEditor — the project's tag dialog (opened from the tag count in the page header).
 *
 * Title, the current tags (the scope tag is locked, user tags have a remove cross), one input,
 * Cancel / Add. Uses `POST /server/projects/<id>/tags/names` (array of names) and
 * `DELETE /server/projects/<id>/tags/names/<name>`.
 */
import React, { useState } from 'react';
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';

import { useI18n } from '../../i18n/useI18n';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { neutralButtonSx, primaryButtonSx } from '../common/PageChrome';


export interface ProjectTag {
  tag_id: number;
  name: string;
  color?: string;
  is_scope?: boolean;
}

export interface ProjectTagsEditorProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  canEdit: boolean;
  tags: ProjectTag[];
  onChanged: () => void;
}

const NAME_RE = /^[a-zA-Z0-9_-]+$/;

export const ProjectTagsEditor: React.FC<ProjectTagsEditorProps> = ({
  open,
  onClose,
  projectId,
  canEdit,
  tags,
  onChanged,
}) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();

  const [addValue, setAddValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const scopeTag = tags.find((tag) => tag.is_scope) ?? null;
  const userTags = tags.filter((tag) => !tag.is_scope);

  const close = () => {
    if (pending) return;
    setAddValue('');
    setError(null);
    onClose();
  };

  const submitAdd = async () => {
    if (pending) return;
    const names = addValue.split(/[\s,]+/).map((s) => s.trim()).filter((s) => s.length > 0);
    if (names.length === 0) {
      setError(t('Enter at least one tag name'));
      return;
    }
    if (names.some((n) => !NAME_RE.test(n))) {
      setError(t('Tag names must be alphanumeric (plus \'-\' and \'_\')'));
      return;
    }
    setError(null);
    setPending(true);
    try {
      const res = await apiClient(buildServerUrl(`/server/projects/${projectId}/tags/names`), {
        method: 'POST',
        body: JSON.stringify({ names }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.error || `HTTP ${res.status}`);
      }
      setAddValue('');
      onChanged();
    } catch (e) {
      const msg = e instanceof Error ? e.message : '';
      if (/409|duplicate|already exists/i.test(msg)) setError(t('A tag with that name already exists'));
      else setError(msg || t('Failed to add tag'));
    } finally {
      setPending(false);
    }
  };

  const removeUserTag = async (name: string) => {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const res = await apiClient(
        buildServerUrl(`/server/projects/${projectId}/tags/names/${encodeURIComponent(name)}`),
        { method: 'DELETE' },
      );
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.error || `HTTP ${res.status}`);
      }
      onChanged();
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      setError(/scope tag/i.test(raw) ? t('Cannot remove the project’s scope tag') : `${t('Failed to remove tag')}: ${raw}`);
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onClose={close} maxWidth="xs" fullWidth aria-labelledby="project-tags-dialog-title">
      <DialogTitle id="project-tags-dialog-title">{t('Tags')}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, mt: 0.5 }}>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75 }}>
            {scopeTag && (
              <Chip
                size="small"
                variant="outlined"
                icon={<LockOutlinedIcon />}
                label={scopeTag.name}
                data-testid="project-tag-scope"
              />
            )}
            {userTags.map((tag) => (
              <Chip
                key={tag.tag_id}
                size="small"
                variant="outlined"
                label={tag.name}
                data-testid={`project-tag-user-${tag.name}`}
                onDelete={canEdit ? () => { void removeUserTag(tag.name); } : undefined}
              />
            ))}
          </Box>
          {canEdit && (
            <TextField
              value={addValue}
              onChange={(e) => setAddValue(e.target.value)}
              autoFocus
              fullWidth
              size="small"
              disabled={pending}
              placeholder={t('Add a tag')}
              inputProps={{ 'aria-label': t('Add a tag') }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !pending) {
                  e.preventDefault();
                  void submitAdd();
                }
              }}
            />
          )}
          {error && (
            <Box role="alert" data-testid="project-tag-add-error" sx={{ color: P.error, fontSize: TYPOGRAPHY.body.size }}>
              {error}
            </Box>
          )}
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2, pt: 1, gap: 1 }}>
        <Button onClick={close} disabled={pending} size="small" variant="outlined" sx={neutralButtonSx(P)}>
          {t('Cancel')}
        </Button>
        {canEdit && (
          <Button
            onClick={() => { void submitAdd(); }}
            variant="contained"
            size="small"
            startIcon={<AddIcon />}
            disabled={pending || !addValue.trim()}
            sx={primaryButtonSx(P)}
            data-testid="project-tag-add-submit"
          >
            {t('Add')}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
};
