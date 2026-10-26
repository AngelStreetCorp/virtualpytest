/**
 * Label catalog for the team. Labels are assigned by id, so a rename is canonical:
 * every result carrying the label shows the new name. Deleting a label removes its
 * assignments only; the results themselves are untouched.
 */

import { Add as AddIcon } from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  DialogActions,
  DialogContent,
  DialogTitle,
  Link,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import React, { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { StyledDialog } from '../components/common/StyledDialog';
import { EmptyState, QueryState } from '../components/reports/PageState';
import { describeError } from '../hooks/reports/runManagementApi';
import { useGovernanceMutations, useLabels, useReportPermissions } from '../hooks/reports/useRunManagement';
import { useToast } from '../hooks/useToast';
import { LABEL_NAME_MAX, REPORT_ROUTES, validateLabelName, type RunLabel } from '../types/reports';
import { useI18n } from '../i18n/useI18n';
import { dangerButtonSx } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';

const HEX_COLOR = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
const DEFAULT_COLOR = '#2a78d6';

/** Text of the delete confirmation; states exactly what is and is not removed. */
export const deleteLabelMessage = (label: Pick<RunLabel, 'name'>): string =>
  `Removes the label "${label.name}" from every result and test case that carries it. ` +
  'The results and test cases themselves are not changed.';

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

interface LabelDialogProps {
  open: boolean;
  label: RunLabel | null;
  existing: RunLabel[];
  onClose: () => void;
}

const LabelDialog: React.FC<LabelDialogProps> = ({ open, label, existing, onClose }) => {
  const { createLabel, updateLabel } = useGovernanceMutations();
  const [name, setName] = useState('');
  const [color, setColor] = useState(DEFAULT_COLOR);
  const [touched, setTouched] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(label?.name ?? '');
    setColor(label?.color ?? DEFAULT_COLOR);
    setTouched(false);
    setServerError(null);
  }, [open, label]);

  const nameError = validateLabelName(name, existing, label?.id);
  const colorError = color && !HEX_COLOR.test(color) ? 'Use a hex colour like #2a78d6' : null;
  const pending = createLabel.isPending || updateLabel.isPending;

  const handleSave = async () => {
    setTouched(true);
    if (nameError || colorError) return;
    setServerError(null);
    const input = { name: name.trim(), color: color || null };
    try {
      if (label) await updateLabel.mutateAsync({ id: label.id, input });
      else await createLabel.mutateAsync(input);
      onClose();
    } catch (err) {
      setServerError(describeError(err));
    }
  };

  return (
    <StyledDialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{label ? 'Rename label' : 'New label'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField
            size="small"
            label="Name"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setTouched(true);
            }}
            error={touched && Boolean(nameError)}
            helperText={touched && nameError ? nameError : `1–${LABEL_NAME_MAX} characters, unique in the team`}
            inputProps={{ 'data-testid': 'label-name' }}
          />
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <TextField
              size="small"
              label="Colour"
              value={color}
              onChange={(event) => setColor(event.target.value)}
              error={Boolean(colorError)}
              helperText={colorError ?? ' '}
              sx={{ flex: 1 }}
            />
            <Box
              component="input"
              type="color"
              aria-label="Pick colour"
              value={HEX_COLOR.test(color) && color.length === 7 ? color : DEFAULT_COLOR}
              onChange={(event: React.ChangeEvent<HTMLInputElement>) => setColor(event.target.value)}
              sx={{ width: 40, height: 32, border: 0, p: 0, background: 'none', mb: 2.5 }}
            />
          </Box>
          {label && (
            <Typography variant="body2" color="text.secondary">
              Renaming changes the label everywhere it is used.
            </Typography>
          )}
          {serverError && (
            <Alert severity="error" data-testid="label-server-error">
              {serverError}
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={() => void handleSave()}
          disabled={pending || (touched && (Boolean(nameError) || Boolean(colorError)))}
        >
          Save
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

const RunLabels: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const labels = useLabels();
  const { canEdit } = useReportPermissions();
  const { deleteLabel } = useGovernanceMutations();
  const { showError, showSuccess } = useToast();
  const [dialog, setDialog] = useState<{ open: boolean; label: RunLabel | null }>({ open: false, label: null });
  const [toDelete, setToDelete] = useState<RunLabel | null>(null);

  const items = labels.data?.items ?? [];

  const confirmDelete = async () => {
    if (!toDelete) return;
    const target = toDelete;
    setToDelete(null);
    try {
      const removed = await deleteLabel.mutateAsync(target.id);
      showSuccess(
        `Label "${target.name}" removed from ${plural(removed.removed_script_result_assignments, 'result')} ` +
          `and ${plural(removed.removed_testcase_assignments, 'test case')}`,
      );
    } catch (err) {
      showError(describeError(err));
    }
  };

  return (
    <Box sx={{ minWidth: 0 }}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'flex-end', gap: 1, mb: 2 }}>
        {canEdit && (
          <Button
            variant="contained"
            size="small"
            startIcon={<AddIcon />}
            onClick={() => setDialog({ open: true, label: null })}
          >
            New label
          </Button>
        )}
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Team labels for script results and test cases. Up to 10 labels per item.
      </Typography>

      <QueryState loading={labels.isLoading} error={labels.error}>
        {items.length === 0 ? (
          <EmptyState message={t('No labels yet.')}>
            {canEdit && (
              <Button variant="outlined" size="small" sx={{ mt: 1 }} onClick={() => setDialog({ open: true, label: null })}>
                {t('Create the first label')}
              </Button>
            )}
          </EmptyState>
        ) : (
          <TableContainer component={Paper} variant="outlined" sx={{ overflowX: 'auto' }}>
            <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 420, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col /><col style={{ width: 130 }} /></colgroup>
              <TableHead>
                <TableRow>
                  <TableCell>Label</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((label) => (
                  <TableRow key={label.id}>
                    <TableCell>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
                        <Box
                          sx={{
                            width: 12,
                            height: 12,
                            borderRadius: '2px',
                            flexShrink: 0,
                            bgcolor: label.color || 'action.disabled',
                          }}
                        />
                        <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>
                          {label.name}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell align="right">
                      <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                        <Link
                          component={RouterLink}
                          to={`${REPORT_ROUTES.testReports}?label=${encodeURIComponent(label.id)}`}
                          variant="body2"
                          sx={{ alignSelf: 'center', mr: 1 }}
                        >
                          View results
                        </Link>
                        {canEdit && (
                          <>
                            <Button size="small" onClick={() => setDialog({ open: true, label })}>
                              Rename
                            </Button>
                            <Button size="small" onClick={() => setToDelete(label)} sx={dangerButtonSx(P)}>
                              Remove
                            </Button>
                          </>
                        )}
                      </Box>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </QueryState>

      {canEdit && (
        <LabelDialog
          open={dialog.open}
          label={dialog.label}
          existing={items}
          onClose={() => setDialog({ open: false, label: null })}
        />
      )}
      <ConfirmDialog
        open={Boolean(toDelete)}
        title="Remove label"
        message={toDelete ? deleteLabelMessage(toDelete) : ''}
        confirmText="Remove label"
        confirmColor="error"
        onConfirm={() => void confirmDelete()}
        onCancel={() => setToDelete(null)}
      />
    </Box>
  );
};

export default RunLabels;
