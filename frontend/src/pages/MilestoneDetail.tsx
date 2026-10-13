/**
 * One milestone: its metadata and the completed script results assigned to it.
 * Results come from the existing script-results list narrowed server-side by
 * `milestone_id` (and the workspace scope), so nothing is matched by name or time.
 */

import { ArrowBack as BackIcon } from '@mui/icons-material';
import {
  Box,
  Button,
  Chip,
  Link,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import React, { useState } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';

import { EmptyState, QueryState, ReportPage } from '../components/reports/PageState';
import { StatusChip, formatDateTime } from '../components/reports/status';
import { describeError } from '../hooks/reports/runManagementApi';
import {
  useGovernanceMutations,
  useGovernanceResults,
  useMilestones,
  useReportPermissions,
} from '../hooks/reports/useRunManagement';
import { useToast } from '../hooks/useToast';
import { REPORT_ROUTES, scriptResultStatus } from '../types/reports';
import { MilestoneDialog } from './Milestones';

/**
 * Status of a script_results row from its own evidence. `success` is only trusted once
 * the row has completed; an uncompleted row is running (it has started) — never failed.
 */

const MilestoneDetail: React.FC = () => {
  const { milestoneId } = useParams<{ milestoneId: string }>();
  const milestones = useMilestones(true);
  const milestone = (milestones.data?.items ?? []).find((item) => item.id === milestoneId) ?? null;
  const results = useGovernanceResults({ milestone_id: milestoneId }, Boolean(milestoneId));
  const { canEdit } = useReportPermissions();
  const { archiveMilestone, restoreMilestone } = useGovernanceMutations();
  const { showError, showSuccess } = useToast();
  const [editOpen, setEditOpen] = useState(false);

  const run = async (action: () => Promise<unknown>, success: string) => {
    try {
      await action();
      showSuccess(success);
    } catch (err) {
      showError(describeError(err));
    }
  };

  const rows = results.data ?? [];

  return (
    <ReportPage>
      <Button component={RouterLink} to={REPORT_ROUTES.milestones} startIcon={<BackIcon />} size="small" sx={{ mb: 1 }}>
        Milestones
      </Button>
      <QueryState loading={milestones.isLoading} error={milestones.error}>
        {!milestone ? (
          <EmptyState message="This milestone was not found in this team." />
        ) : (
          <>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 1, mb: 2 }}>
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="h5" component="h1" sx={{ wordBreak: 'break-word' }}>
                  {milestone.name}
                </Typography>
                <Stack direction="row" spacing={0.5} sx={{ mt: 0.5 }} flexWrap="wrap">
                  {milestone.archived && <Chip size="small" label="Archived" />}
                  <Chip
                    size="small"
                    variant="outlined"
                    color={milestone.completed_at ? 'success' : 'default'}
                    label={milestone.completed_at ? `Completed ${formatDateTime(milestone.completed_at)}` : 'Open'}
                  />
                  <Chip
                    size="small"
                    variant="outlined"
                    label={milestone.due_at ? `Due ${formatDateTime(milestone.due_at)}` : 'No due date'}
                  />
                </Stack>
                {milestone.description && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    {milestone.description}
                  </Typography>
                )}
              </Box>
              {canEdit && (
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'flex-start' }}>
                  {!milestone.archived && (
                    <>
                      <Button size="small" variant="outlined" onClick={() => setEditOpen(true)}>
                        Edit
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => void run(() => archiveMilestone.mutateAsync(milestone.id), 'Milestone archived')}
                      >
                        Archive
                      </Button>
                    </>
                  )}
                  {milestone.archived && (
                    <Button
                      size="small"
                      variant="outlined"
                      onClick={() => void run(() => restoreMilestone.mutateAsync(milestone.id), 'Milestone restored')}
                    >
                      Restore
                    </Button>
                  )}
                </Box>
              )}
            </Box>

            <Typography variant="subtitle1" sx={{ mb: 1 }}>
              Assigned results
            </Typography>
            <QueryState loading={results.isLoading} error={results.error}>
              {rows.length === 0 ? (
                <EmptyState message="No results are assigned to this milestone in this workspace.">
                  <Typography variant="body2" sx={{ mt: 1 }}>
                    Assign runs from{' '}
                    <Link component={RouterLink} to={REPORT_ROUTES.testReports}>
                      Test Reports
                    </Link>
                    .
                  </Typography>
                </EmptyState>
              ) : (
                <TableContainer component={Paper} variant="outlined" sx={{ overflowX: 'auto' }}>
                  <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 640, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col /><col style={{ width: 110 }} /><col style={{ width: 150 }} /><col style={{ width: 190 }} /></colgroup>
                    <TableHead>
                      <TableRow>
                        <TableCell>Test</TableCell>
                        <TableCell>Status</TableCell>
                        <TableCell>Target</TableCell>
                        <TableCell>Started</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {rows.map((row) => (
                        <TableRow key={row.id}>
                          <TableCell sx={{ wordBreak: 'break-word' }}>
                            <Link component={RouterLink} to={REPORT_ROUTES.summary('script', row.id)}>
                              {row.script_name}
                            </Link>
                          </TableCell>
                          <TableCell>
                            <StatusChip status={scriptResultStatus(row)} />
                          </TableCell>
                          <TableCell>
                            {row.device_name} · {row.host_name}
                          </TableCell>
                          <TableCell>{formatDateTime(row.started_at)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </QueryState>

            {canEdit && <MilestoneDialog open={editOpen} milestone={milestone} onClose={() => setEditOpen(false)} />}
          </>
        )}
      </QueryState>
    </ReportPage>
  );
};

export default MilestoneDetail;
