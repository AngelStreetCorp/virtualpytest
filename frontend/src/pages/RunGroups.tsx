/**
 * Run groups: organise completed script results. Groups are archived and restored,
 * never deleted — an archived group keeps its results and links.
 */

import { PushPin as PinIcon, PushPinOutlined as UnpinIcon } from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  Chip,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  Link,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useMemo, useState } from 'react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';

import { StyledDialog } from '../components/common/StyledDialog';
import { EmptyState, QueryState } from '../components/reports/PageState';
import { formatDateTime } from '../components/reports/status';
import { describeError } from '../hooks/reports/runManagementApi';
import { useGovernanceMutations, useReportPermissions, useRunGroups } from '../hooks/reports/useRunManagement';
import { useToast } from '../hooks/useToast';
import { GOVERNANCE_NAME_MAX, REPORT_ROUTES, type RunGroup } from '../types/reports';
import { useI18n } from '../i18n/useI18n';

export const ARCHIVE_HINT = 'Archived groups keep their results and links; restore any time.';

const HEX_COLOR = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

const CreateGroupDialog: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const { createGroup } = useGovernanceMutations();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState('');
  const [error, setError] = useState<string | null>(null);

  const trimmed = name.trim();
  const nameError = trimmed.length > GOVERNANCE_NAME_MAX ? `At most ${GOVERNANCE_NAME_MAX} characters` : null;
  const colorError = color && !HEX_COLOR.test(color.trim()) ? 'Use a hex colour such as #2a78d6' : null;

  const close = () => {
    setName('');
    setDescription('');
    setColor('');
    setError(null);
    onClose();
  };

  const submit = async () => {
    setError(null);
    try {
      await createGroup.mutateAsync({
        name: trimmed,
        description: description.trim() || null,
        color: color.trim() || null,
      });
      close();
    } catch (err) {
      setError(describeError(err));
    }
  };

  return (
    <StyledDialog open={open} onClose={close} maxWidth="sm" fullWidth>
      <DialogTitle>New run group</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <TextField
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            error={Boolean(nameError)}
            helperText={nameError ?? `1–${GOVERNANCE_NAME_MAX} characters`}
            autoFocus
          />
          <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} multiline minRows={2} />
          <TextField
            label="Colour (optional)"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            error={Boolean(colorError)}
            helperText={colorError ?? 'Hex, e.g. #2a78d6'}
          />
          {error && <Alert severity="error">{error}</Alert>}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>Cancel</Button>
        <Button
          variant="contained"
          onClick={() => void submit()}
          disabled={!trimmed || Boolean(nameError) || Boolean(colorError) || createGroup.isPending}
        >
          Create
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

const RunGroups: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const includeArchived = searchParams.get('archived') === '1';
  const groups = useRunGroups(includeArchived);
  const { canEdit } = useReportPermissions();
  const { updateGroup, archiveGroup, restoreGroup } = useGovernanceMutations();
  const { showError, showSuccess } = useToast();
  const [createOpen, setCreateOpen] = useState(false);
  const { t } = useI18n();

  const items = useMemo(() => {
    const list = [...(groups.data?.items ?? [])];
    return list.sort(
      (a, b) => Number(b.pinned) - Number(a.pinned) || Number(a.archived) - Number(b.archived) || a.name.localeCompare(b.name),
    );
  }, [groups.data]);

  const run = async (action: () => Promise<unknown>, success: string) => {
    try {
      await action();
      showSuccess(success);
    } catch (error) {
      showError(describeError(error));
    }
  };

  const toggleArchived = (checked: boolean) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (checked) next.set('archived', '1');
        else next.delete('archived');
        return next;
      },
      { replace: true },
    );

  return (
    <Box sx={{ minWidth: 0 }}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Box>
          <Typography variant="caption" color="text.secondary">
            {ARCHIVE_HINT}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <FormControlLabel
            control={<Switch checked={includeArchived} onChange={(e) => toggleArchived(e.target.checked)} />}
            label="Show archived"
          />
          {canEdit && (
            <Button variant="contained" size="small" onClick={() => setCreateOpen(true)}>
              New group
            </Button>
          )}
        </Box>
      </Box>
      <QueryState loading={groups.isLoading} error={groups.error}>
        {items.length === 0 ? (
          <EmptyState message={includeArchived ? t('No run groups yet.') : t('No active run groups.')}>
            {canEdit && (
              <Button variant="outlined" size="small" sx={{ mt: 1 }} onClick={() => setCreateOpen(true)}>
                {t('Create the first group')}
              </Button>
            )}
          </EmptyState>
        ) : (
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 520, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col /><col style={{ width: 190 }} />{canEdit && <col style={{ width: 110 }} />}</colgroup>
              <TableHead>
                <TableRow>
                  <TableCell>Name</TableCell>
                  <TableCell>Updated</TableCell>
                  {canEdit && <TableCell align="right">Actions</TableCell>}
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((group: RunGroup) => (
                  <TableRow key={group.id} data-testid={`group-${group.id}`} sx={{ opacity: group.archived ? 0.6 : 1 }}>
                    <TableCell sx={{ maxWidth: 320, wordBreak: 'break-word' }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                        {group.color && (
                          <Box sx={{ width: 10, height: 10, borderRadius: '2px', bgcolor: group.color, flexShrink: 0 }} />
                        )}
                        <Link component={RouterLink} to={REPORT_ROUTES.group(group.id)}>
                          {group.name}
                        </Link>
                        {group.pinned && <Chip size="small" label="Pinned" />}
                        {group.archived && <Chip size="small" label="Archived" variant="outlined" />}
                      </Box>
                      {group.description && (
                        <Typography variant="caption" color="text.secondary">
                          {group.description}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>{formatDateTime(group.updated_at)}</TableCell>
                    {canEdit && (
                      <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                        <Tooltip title={group.pinned ? 'Unpin' : 'Pin'}>
                          <IconButton
                            size="small"
                            aria-label={group.pinned ? `Unpin ${group.name}` : `Pin ${group.name}`}
                            onClick={() =>
                              void run(
                                () => updateGroup.mutateAsync({ id: group.id, input: { pinned: !group.pinned } }),
                                group.pinned ? 'Unpinned' : 'Pinned',
                              )
                            }
                          >
                            {group.pinned ? <PinIcon fontSize="small" /> : <UnpinIcon fontSize="small" />}
                          </IconButton>
                        </Tooltip>
                        {group.archived ? (
                          <Button
                            size="small"
                            onClick={() => void run(() => restoreGroup.mutateAsync(group.id), `Restored "${group.name}"`)}
                          >
                            Restore
                          </Button>
                        ) : (
                          <Tooltip title={ARCHIVE_HINT} describeChild>
                            <Button
                              size="small"
                              onClick={() => void run(() => archiveGroup.mutateAsync(group.id), `Archived "${group.name}"`)}
                            >
                              Archive
                            </Button>
                          </Tooltip>
                        )}
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        )}
      </QueryState>
      <CreateGroupDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </Box>
  );
};

export default RunGroups;
