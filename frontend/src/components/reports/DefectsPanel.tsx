/**
 * Local-first defects for one or more script results: list, create (linked to the given
 * results), link an existing defect, unlink, change status, and the explicit Jira push /
 * refresh. Resolving a defect never touches the run's status, discard flag or evidence.
 */

import {
  Alert,
  Box,
  Button,
  Chip,
  DialogActions,
  DialogContent,
  DialogTitle,
  Link,
  MenuItem,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { useQueries } from '@tanstack/react-query';
import React, { useMemo, useState } from 'react';

import { StyledDialog } from '../common/StyledDialog';
import * as rmApi from '../../hooks/reports/runManagementApi';
import { describeError } from '../../hooks/reports/runManagementApi';
import {
  useDefectMutations,
  useDefects,
  useReportPermissions,
  useReportScope,
} from '../../hooks/reports/useRunManagement';
import { useToast } from '../../hooks/useToast';
import {
  DEFECT_SEVERITIES,
  DEFECT_STATUSES,
  type Defect,
  type DefectSeverity,
  type DefectStatus,
} from '../../types/reports';
import { STATUS } from '../analytics/palette';
import { formatDateTime } from './status';
import { EmptyState, QueryState } from './PageState';
import { dangerButtonSx } from '../common/PageChrome';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

export const DEFECT_TITLE_MAX = 200;
export const MAX_PANEL_RESULTS = 25;

export const RESOLVE_NOTE = "Resolving a defect never changes the run's status, discard flag or evidence.";

const SEVERITY_COLORS: Record<DefectSeverity, string> = {
  critical: STATUS.critical,
  high: STATUS.serious,
  medium: STATUS.warning,
  low: STATUS.good,
};

const STATUS_LABELS: Record<DefectStatus, string> = {
  open: 'Open',
  in_progress: 'In progress',
  resolved: 'Resolved',
  closed: 'Closed',
};

export const SeverityChip: React.FC<{ severity: DefectSeverity }> = ({ severity }) => (
  <Chip
    size="small"
    variant="outlined"
    label={severity}
    sx={{ borderColor: SEVERITY_COLORS[severity], color: SEVERITY_COLORS[severity], textTransform: 'capitalize' }}
  />
);

/**
 * Explicit Jira push. The server keeps one push record per defect, so retrying can never
 * create a second issue; a 504 means the outcome is unknown and the server reconciles on
 * the next attempt once its lease expires.
 */
export const describeJiraPushError = (error: unknown): string => {
  if (rmApi.isApiError(error, 504)) {
    return 'Jira did not confirm the issue in time. Retry in a couple of minutes; no duplicate will be created.';
  }
  if (rmApi.isApiError(error, 409)) return error.message || 'A push for this defect is already in progress.';
  return describeError(error);
};

export const useJiraPush = () => {
  const { pushJira } = useDefectMutations();
  return { push: (defectId: string) => pushJira.mutateAsync(defectId), isPending: pushJira.isPending };
};

export interface DefectTableProps {
  defects: Defect[];
  /** When set, each row offers "Unlink" from this result. */
  unlinkFromResultId?: string;
}

export const DefectTable: React.FC<DefectTableProps> = ({ defects, unlinkFromResultId }) => {
  const P = useAgentChatPalette();
  const { canEditDefects } = useReportPermissions();
  const { update, unlink, refreshJira } = useDefectMutations();
  const jira = useJiraPush();
  const { showError, showSuccess } = useToast();

  const run = async (
    action: () => Promise<unknown>,
    success?: string,
    describe: (error: unknown) => string = describeError,
  ) => {
    try {
      await action();
      if (success) showSuccess(success);
    } catch (error) {
      showError(describe(error));
    }
  };

  return (
    <Box sx={{ overflowX: 'auto' }}>
      <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 720, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col /><col style={{ width: 100 }} /><col style={{ width: 110 }} /><col style={{ width: 130 }} /><col style={{ width: 120 }} />{canEditDefects && <col style={{ width: 110 }} />}</colgroup>
        <TableHead>
          <TableRow>
            <TableCell>Title</TableCell>
            <TableCell>Severity</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Jira</TableCell>
            <TableCell>Updated</TableCell>
            {canEditDefects && <TableCell align="right">Actions</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {defects.map((defect) => (
            <TableRow key={defect.id} data-testid={`defect-${defect.id}`}>
              <TableCell sx={{ maxWidth: 320, wordBreak: 'break-word' }}>{defect.title}</TableCell>
              <TableCell>
                <SeverityChip severity={defect.severity} />
              </TableCell>
              <TableCell>
                {canEditDefects ? (
                  <TextField
                    select
                    size="small"
                    value={defect.status}
                    onChange={(event) =>
                      void run(() =>
                        update.mutateAsync({ id: defect.id, input: { status: event.target.value as DefectStatus } }),
                      )
                    }
                    inputProps={{ 'aria-label': `Status of ${defect.title}` }}
                    sx={{ minWidth: 130 }}
                  >
                    {DEFECT_STATUSES.map((status) => (
                      <MenuItem key={status} value={status}>
                        {STATUS_LABELS[status]}
                      </MenuItem>
                    ))}
                  </TextField>
                ) : (
                  STATUS_LABELS[defect.status]
                )}
              </TableCell>
              <TableCell>
                {defect.external_key ? (
                  defect.external_url ? (
                    <Link href={defect.external_url} target="_blank" rel="noopener noreferrer">
                      {defect.external_key}
                    </Link>
                  ) : (
                    defect.external_key
                  )
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    Local only
                  </Typography>
                )}
              </TableCell>
              <TableCell>{formatDateTime(defect.updated_at)}</TableCell>
              {canEditDefects && (
                <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                  {defect.external_key ? (
                    <Button
                      size="small"
                      onClick={() => void run(() => refreshJira.mutateAsync(defect.id), 'Refreshed from Jira')}
                      disabled={refreshJira.isPending}
                    >
                      Refresh from Jira
                    </Button>
                  ) : (
                    <Button
                      size="small"
                      onClick={() => void run(() => jira.push(defect.id), 'Pushed to Jira', describeJiraPushError)}
                      disabled={jira.isPending}
                    >
                      Push to Jira
                    </Button>
                  )}
                  {unlinkFromResultId && (
                    <Button
                      size="small"
                      onClick={() =>
                        void run(() => unlink.mutateAsync({ id: defect.id, scriptResultId: unlinkFromResultId }))
                      }
                      disabled={unlink.isPending}
                      sx={dangerButtonSx(P)}
                    >
                      Unlink
                    </Button>
                  )}
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
};

export interface CreateDefectDialogProps {
  open: boolean;
  /** Results the new defect is linked to as evidence (may be empty). */
  scriptResultIds: string[];
  onClose: () => void;
}

export const CreateDefectDialog: React.FC<CreateDefectDialogProps> = ({ open, scriptResultIds, onClose }) => {
  const { create } = useDefectMutations();
  const [title, setTitle] = useState('');
  const [severity, setSeverity] = useState<DefectSeverity>('medium');
  const [description, setDescription] = useState('');
  const [error, setError] = useState<string | null>(null);

  const trimmed = title.trim();
  const titleError =
    trimmed.length === 0 ? null : trimmed.length > DEFECT_TITLE_MAX ? `At most ${DEFECT_TITLE_MAX} characters` : null;

  const close = () => {
    setTitle('');
    setDescription('');
    setSeverity('medium');
    setError(null);
    onClose();
  };

  const submit = async () => {
    setError(null);
    try {
      await create.mutateAsync({
        title: trimmed,
        severity,
        description: description.trim() || null,
        script_result_ids: scriptResultIds,
      });
      close();
    } catch (err) {
      setError(describeError(err));
    }
  };

  return (
    <StyledDialog open={open} onClose={close} maxWidth="sm" fullWidth>
      <DialogTitle>New defect</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <TextField
            label="Title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            error={Boolean(titleError)}
            helperText={titleError ?? `1–${DEFECT_TITLE_MAX} characters`}
            autoFocus
            fullWidth
          />
          <TextField
            select
            label="Severity"
            value={severity}
            onChange={(event) => setSeverity(event.target.value as DefectSeverity)}
          >
            {DEFECT_SEVERITIES.map((value) => (
              <MenuItem key={value} value={value} sx={{ textTransform: 'capitalize' }}>
                {value}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            multiline
            minRows={3}
          />
          <Typography variant="body2" color="text.secondary">
            {scriptResultIds.length
              ? `Linked as evidence to ${scriptResultIds.length} result${scriptResultIds.length === 1 ? '' : 's'}.`
              : 'Not linked to any result yet.'}
          </Typography>
          {error && <Alert severity="error">{error}</Alert>}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>Cancel</Button>
        <Button
          variant="contained"
          onClick={() => void submit()}
          disabled={!trimmed || Boolean(titleError) || create.isPending}
        >
          Create
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

interface LinkDefectDialogProps {
  open: boolean;
  scriptResultIds: string[];
  excludeIds: Set<string>;
  onClose: () => void;
}

const LinkDefectDialog: React.FC<LinkDefectDialogProps> = ({ open, scriptResultIds, excludeIds, onClose }) => {
  const all = useDefects({}, open);
  const { link } = useDefectMutations();
  const [defectId, setDefectId] = useState('');
  const [resultId, setResultId] = useState(scriptResultIds[0] ?? '');
  const [error, setError] = useState<string | null>(null);
  const candidates = (all.data?.items ?? []).filter((d) => !excludeIds.has(d.id));

  const close = () => {
    setDefectId('');
    setError(null);
    onClose();
  };

  const submit = async () => {
    setError(null);
    try {
      await link.mutateAsync({ id: defectId, scriptResultId: resultId || scriptResultIds[0] });
      close();
    } catch (err) {
      setError(describeError(err));
    }
  };

  return (
    <StyledDialog open={open} onClose={close} maxWidth="sm" fullWidth>
      <DialogTitle>Link an existing defect</DialogTitle>
      <DialogContent>
        <QueryState loading={all.isLoading} error={all.error}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField select label="Defect" value={defectId} onChange={(e) => setDefectId(e.target.value)}>
              {candidates.length === 0 && (
                <MenuItem value="" disabled>
                  No other defects in this team
                </MenuItem>
              )}
              {candidates.map((defect) => (
                <MenuItem key={defect.id} value={defect.id}>
                  {defect.title}
                </MenuItem>
              ))}
            </TextField>
            {scriptResultIds.length > 1 && (
              <TextField select label="Result" value={resultId} onChange={(e) => setResultId(e.target.value)}>
                {scriptResultIds.map((id) => (
                  <MenuItem key={id} value={id}>
                    {id}
                  </MenuItem>
                ))}
              </TextField>
            )}
            {error && <Alert severity="error">{error}</Alert>}
          </Box>
        </QueryState>
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>Cancel</Button>
        <Button variant="contained" onClick={() => void submit()} disabled={!defectId || link.isPending}>
          Link
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

export interface DefectsPanelProps {
  /** Results whose defects are shown; at most MAX_PANEL_RESULTS are queried. */
  scriptResultIds: string[];
  /** Caption above the list (e.g. "Defects linked to results on this page"). */
  caption?: string;
}

export const DefectsPanel: React.FC<DefectsPanelProps> = ({ scriptResultIds, caption }) => {
  const scope = useReportScope();
  const { canEditDefects } = useReportPermissions();
  const [createOpen, setCreateOpen] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const ids = useMemo(() => Array.from(new Set(scriptResultIds)).slice(0, MAX_PANEL_RESULTS), [scriptResultIds]);

  // Same cache key shape as useDefects so a defect mutation invalidates these too.
  const queries = useQueries({
    queries: ids.map((id) => ({
      queryKey: ['run-management', 'defects', scope.serverKey, scope.deviceFilter?.join(',') ?? '*', { script_result_id: id }],
      queryFn: () => rmApi.fetchDefects({ script_result_id: id }, scope),
    })),
  });

  const loading = queries.some((q) => q.isLoading);
  const error = queries.find((q) => q.error)?.error ?? null;
  const defects = useMemo(() => {
    const byId = new Map<string, Defect>();
    for (const q of queries) for (const defect of q.data?.items ?? []) byId.set(defect.id, defect);
    return Array.from(byId.values()).sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  }, [queries]);

  if (ids.length === 0) {
    return <EmptyState message="No recorded results to attach defects to." />;
  }

  return (
    <Box>
      {caption && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {caption}
        </Typography>
      )}
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        {RESOLVE_NOTE}
      </Typography>
      {canEditDefects && (
        <Box sx={{ display: 'flex', gap: 1, mb: 1, flexWrap: 'wrap' }}>
          <Button size="small" variant="contained" onClick={() => setCreateOpen(true)}>
            New defect
          </Button>
          <Button size="small" variant="outlined" onClick={() => setLinkOpen(true)}>
            Link existing
          </Button>
        </Box>
      )}
      <QueryState loading={loading} error={error}>
        {defects.length === 0 ? (
          <EmptyState message="No defects linked." />
        ) : (
          <DefectTable defects={defects} unlinkFromResultId={ids.length === 1 ? ids[0] : undefined} />
        )}
      </QueryState>
      <CreateDefectDialog open={createOpen} scriptResultIds={ids} onClose={() => setCreateOpen(false)} />
      <LinkDefectDialog
        open={linkOpen}
        scriptResultIds={ids}
        excludeIds={new Set(defects.map((d) => d.id))}
        onClose={() => setLinkOpen(false)}
      />
    </Box>
  );
};

export default DefectsPanel;
