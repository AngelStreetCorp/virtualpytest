/**
 * Assign milestone / run group / labels to one or more completed script results.
 *
 * Only fields the user changed are sent. One result uses the per-result endpoints; a
 * selection uses ONE batch call, which the server applies atomically after scope-checking
 * every member, so a partial assignment cannot happen.
 */

import {
  Alert,
  Button,
  Checkbox,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from '@mui/material';
import React, { useEffect, useState } from 'react';

import { StyledDialog } from '../common/StyledDialog';
import { describeError } from '../../hooks/reports/runManagementApi';
import { useGovernanceMutations, useMilestones, useRunGroups } from '../../hooks/reports/useRunManagement';
import { validateLabelSelection, type BatchAssignmentInput } from '../../types/reports';
import { LabelPicker } from './LabelPicker';

/** Select sentinel values: leave the field as it is, or clear it. */
export const UNCHANGED = '__unchanged__';
export const NONE = '__none__';

export interface AssignmentDialogProps {
  open: boolean;
  resultIds: string[];
  initial?: { milestone_id?: string | null; run_group_id?: string | null; label_ids?: string[] };
  onClose: () => void;
  onDone: () => void;
}

const toSelectValue = (id: string | null | undefined): string =>
  id === undefined ? UNCHANGED : id === null ? NONE : id;

const fromSelectValue = (value: string): string | null | undefined =>
  value === UNCHANGED ? undefined : value === NONE ? null : value;

export const AssignmentDialog: React.FC<AssignmentDialogProps> = ({ open, resultIds, initial, onClose, onDone }) => {
  const milestones = useMilestones(false);
  const groups = useRunGroups(false);
  const mutations = useGovernanceMutations();

  const [milestone, setMilestone] = useState<string>(UNCHANGED);
  const [group, setGroup] = useState<string>(UNCHANGED);
  const [setLabels, setSetLabels] = useState(false);
  const [labelIds, setLabelIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Reset to the caller's current values each time the dialog opens.
  useEffect(() => {
    if (!open) return;
    setMilestone(toSelectValue(initial?.milestone_id));
    setGroup(toSelectValue(initial?.run_group_id));
    setSetLabels(false);
    setLabelIds(initial?.label_ids ?? []);
    setError(null);
  }, [open]);

  const single = resultIds.length === 1;

  const milestoneValue = fromSelectValue(milestone);
  const groupValue = fromSelectValue(group);
  const milestoneChanged = milestoneValue !== undefined && milestoneValue !== initial?.milestone_id;
  const groupChanged = groupValue !== undefined && groupValue !== initial?.run_group_id;
  const nothingToDo = !milestoneChanged && !groupChanged && !setLabels;
  const labelError = setLabels ? validateLabelSelection(labelIds) : null;

  const handleSave = async () => {
    setError(null);
    setSaving(true);
    try {
      if (single) {
        const resultId = resultIds[0];
        if (milestoneChanged) {
          await mutations.setResultMilestone.mutateAsync({ resultId, milestoneId: milestoneValue ?? null });
        }
        if (groupChanged) {
          await mutations.setResultRunGroup.mutateAsync({ resultId, runGroupId: groupValue ?? null });
        }
        if (setLabels) {
          await mutations.setResultLabels.mutateAsync({ resultId, labelIds });
        }
      } else {
        const body: BatchAssignmentInput = { script_result_ids: resultIds };
        if (milestoneChanged) body.milestone_id = milestoneValue ?? null;
        if (groupChanged) body.run_group_id = groupValue ?? null;
        if (setLabels) body.label_ids = labelIds;
        await mutations.batchAssign.mutateAsync(body);
      }
      onDone();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSaving(false);
    }
  };

  const activeMilestones = milestones.data?.items ?? [];
  const activeGroups = groups.data?.items ?? [];

  return (
    <StyledDialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        {single ? 'Assign result' : `Assign ${resultIds.length} results`}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <FormControl size="small" fullWidth>
            <InputLabel id="assign-milestone-label">Milestone</InputLabel>
            <Select
              labelId="assign-milestone-label"
              label="Milestone"
              value={milestone}
              onChange={(event) => setMilestone(event.target.value)}
              inputProps={{ 'data-testid': 'assign-milestone' }}
            >
              <MenuItem value={UNCHANGED}>Leave unchanged</MenuItem>
              <MenuItem value={NONE}>No milestone</MenuItem>
              {activeMilestones.map((item) => (
                <MenuItem key={item.id} value={item.id}>
                  {item.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel id="assign-group-label">Run group</InputLabel>
            <Select
              labelId="assign-group-label"
              label="Run group"
              value={group}
              onChange={(event) => setGroup(event.target.value)}
              inputProps={{ 'data-testid': 'assign-group' }}
            >
              <MenuItem value={UNCHANGED}>Leave unchanged</MenuItem>
              <MenuItem value={NONE}>No group</MenuItem>
              {activeGroups.map((item) => (
                <MenuItem key={item.id} value={item.id}>
                  {item.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControlLabel
            control={<Checkbox checked={setLabels} onChange={(event) => setSetLabels(event.target.checked)} />}
            label="Set labels"
          />
          {setLabels && (
            <>
              <Typography variant="body2" color="text.secondary">
                {single
                  ? 'The labels below replace the labels currently on this result.'
                  : `The labels below replace the labels currently on each of the ${resultIds.length} selected results.`}
              </Typography>
              <LabelPicker value={labelIds} onChange={setLabelIds} />
            </>
          )}
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={() => void handleSave()}
          disabled={saving || nothingToDo || Boolean(labelError) || resultIds.length === 0}
        >
          Save
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

export default AssignmentDialog;
