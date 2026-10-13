/**
 * Milestones: team-level release markers that completed script results can be assigned to.
 * Milestones are archived and restored, never deleted; archiving keeps every assignment.
 */

import { Add as AddIcon } from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  Chip,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Link,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import React, { useState } from 'react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';

import { StyledDialog } from '../components/common/StyledDialog';
import { EmptyState, QueryState } from '../components/reports/PageState';
import { formatDateTime } from '../components/reports/status';
import { describeError } from '../hooks/reports/runManagementApi';
import {
  useGovernanceMutations,
  useMilestones,
  useReportPermissions,
} from '../hooks/reports/useRunManagement';
import { useToast } from '../hooks/useToast';
import { GOVERNANCE_NAME_MAX, REPORT_ROUTES, type Milestone, type MilestoneInput } from '../types/reports';
import { useI18n } from '../i18n/useI18n';

/** `YYYY-MM-DD` for a date input from an ISO timestamp. */
export const toDateInput = (iso: string | null | undefined): string => (iso ? iso.slice(0, 10) : '');

/** Date input value to an ISO timestamp at UTC midnight, or null when cleared. */
export const fromDateInput = (value: string): string | null =>
  value ? new Date(`${value}T00:00:00Z`).toISOString() : null;

export const validateGovernanceName = (raw: string): string | null => {
  const name = raw.trim();
  if (!name) return 'Name is required';
  if (name.length > GOVERNANCE_NAME_MAX) return `At most ${GOVERNANCE_NAME_MAX} characters`;
  return null;
};

export interface MilestoneDialogProps {
  open: boolean;
  milestone: Milestone | null;
  onClose: () => void;
}

/** Create (milestone = null) or edit dialog. */
export const MilestoneDialog: React.FC<MilestoneDialogProps> = ({ open, milestone, onClose }) => {
  const { createMilestone, updateMilestone } = useGovernanceMutations();
  const [name, setName] = useState(milestone?.name ?? '');
  const [description, setDescription] = useState(milestone?.description ?? '');
  const [dueAt, setDueAt] = useState(toDateInput(milestone?.due_at));
  const [error, setError] = useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setName(milestone?.name ?? '');
    setDescription(milestone?.description ?? '');
    setDueAt(toDateInput(milestone?.due_at));
    setError(null);
  }, [open, milestone]);

  const nameError = validateGovernanceName(name);
  const pending = createMilestone.isPending || updateMilestone.isPending;

  const handleSave = async () => {
    if (nameError) return;
    const input: MilestoneInput = {
      name: name.trim(),
      description: description.trim() || null,
      due_at: fromDateInput(dueAt),
    };
    try {
      if (milestone) await updateMilestone.mutateAsync({ id: milestone.id, input });
      else await createMilestone.mutateAsync(input);
      onClose();
    } catch (err) {
      setError(describeError(err));
    }
  };

  return (
    <StyledDialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{milestone ? 'Edit milestone' : 'New milestone'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField
            size="small"
            label="Name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            error={Boolean(name) && Boolean(nameError)}
            helperText={name ? nameError ?? ' ' : ' '}
            inputProps={{ maxLength: GOVERNANCE_NAME_MAX + 20 }}
            required
          />
          <TextField
            size="small"
            label="Description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            multiline
            minRows={2}
          />
          <TextField
            size="small"
            type="date"
            label="Due date"
            value={dueAt}
            onChange={(event) => setDueAt(event.target.value)}
            InputLabelProps={{ shrink: true }}
          />
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={() => void handleSave()} disabled={Boolean(nameError) || pending}>
          Save
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

const Milestones: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const includeArchived = searchParams.get('archived') === '1';
  const milestones = useMilestones(includeArchived);
  const { canEdit } = useReportPermissions();
  const { archiveMilestone, restoreMilestone, updateMilestone } = useGovernanceMutations();
  const { showError, showSuccess } = useToast();
  const { t } = useI18n();
  const [dialog, setDialog] = useState<{ open: boolean; milestone: Milestone | null }>({
    open: false,
    milestone: null,
  });

  const setIncludeArchived = (value: boolean) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set('archived', '1');
        else next.delete('archived');
        return next;
      },
      { replace: true },
    );

  const run = async (action: () => Promise<unknown>, success: string) => {
    try {
      await action();
      showSuccess(success);
    } catch (err) {
      showError(describeError(err));
    }
  };

  const items = milestones.data?.items ?? [];

  return (
    <Box sx={{ minWidth: 0 }}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'flex-end', gap: 1, mb: 2 }}>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <FormControlLabel
            control={
              <Switch checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} />
            }
            label="Show archived"
          />
          {canEdit && (
            <Button
              variant="contained"
              size="small"
              startIcon={<AddIcon />}
              onClick={() => setDialog({ open: true, milestone: null })}
            >
              New milestone
            </Button>
          )}
        </Box>
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Assign completed runs to a milestone from Test Reports or a run summary. Archiving a milestone hides it
        from pickers; its assignments stay and it can be restored at any time.
      </Typography>

      <QueryState loading={milestones.isLoading} error={milestones.error}>
        {items.length === 0 ? (
          <EmptyState message={includeArchived ? t('No milestones yet.') : t('No active milestones.')}>
            {canEdit && (
              <Button
                variant="outlined"
                size="small"
                sx={{ mt: 1 }}
                onClick={() => setDialog({ open: true, milestone: null })}
              >
                {t('Create the first milestone')}
              </Button>
            )}
          </EmptyState>
        ) : (
          <TableContainer component={Paper} variant="outlined" sx={{ overflowX: 'auto' }}>
            <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 560, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col /><col style={{ width: 130 }} /><col style={{ width: 110 }} />{canEdit && <col style={{ width: 110 }} />}</colgroup>
              <TableHead>
                <TableRow>
                  <TableCell>Name</TableCell>
                  <TableCell>Due</TableCell>
                  <TableCell>State</TableCell>
                  {canEdit && <TableCell align="right">Actions</TableCell>}
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((milestone) => (
                  <TableRow key={milestone.id} sx={{ opacity: milestone.archived ? 0.6 : 1 }}>
                    <TableCell sx={{ wordBreak: 'break-word' }}>
                      <Link component={RouterLink} to={REPORT_ROUTES.milestone(milestone.id)}>
                        {milestone.name}
                      </Link>
                      {milestone.description && (
                        <Typography variant="caption" color="text.secondary" display="block">
                          {milestone.description}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>{milestone.due_at ? formatDateTime(milestone.due_at) : '—'}</TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.5} flexWrap="wrap">
                        {milestone.archived && <Chip size="small" label="Archived" />}
                        {milestone.completed_at ? (
                          <Chip size="small" color="success" variant="outlined" label="Completed" />
                        ) : (
                          <Chip size="small" variant="outlined" label="Open" />
                        )}
                      </Stack>
                    </TableCell>
                    {canEdit && (
                      <TableCell align="right">
                        <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                          {!milestone.archived && (
                            <>
                              <Button size="small" onClick={() => setDialog({ open: true, milestone })}>
                                Edit
                              </Button>
                              <Button
                                size="small"
                                onClick={() =>
                                  void run(
                                    () =>
                                      updateMilestone.mutateAsync({
                                        id: milestone.id,
                                        input: {
                                          completed_at: milestone.completed_at ? null : new Date().toISOString(),
                                        },
                                      }),
                                    milestone.completed_at ? 'Milestone reopened' : 'Milestone completed',
                                  )
                                }
                              >
                                {milestone.completed_at ? 'Reopen' : 'Mark completed'}
                              </Button>
                              <Button
                                size="small"
                                onClick={() =>
                                  void run(() => archiveMilestone.mutateAsync(milestone.id), 'Milestone archived')
                                }
                              >
                                Archive
                              </Button>
                            </>
                          )}
                          {milestone.archived && (
                            <Button
                              size="small"
                              onClick={() =>
                                void run(() => restoreMilestone.mutateAsync(milestone.id), 'Milestone restored')
                              }
                            >
                              Restore
                            </Button>
                          )}
                        </Box>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </QueryState>

      {canEdit && (
        <MilestoneDialog
          open={dialog.open}
          milestone={dialog.milestone}
          onClose={() => setDialog({ open: false, milestone: null })}
        />
      )}
    </Box>
  );
};

export default Milestones;
