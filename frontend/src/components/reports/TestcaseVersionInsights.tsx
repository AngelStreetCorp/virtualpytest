/**
 * Extra content for the existing testcase Versions dialog: a read-only diff between two
 * stored versions, the testcase's labels, and links to its recent results. Restore stays
 * in the dialog itself and is not touched here.
 */

import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  Divider,
  FormControl,
  InputLabel,
  Link,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import React, { useEffect, useMemo, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';

import {
  describeError,
  fetchScriptResults,
  fetchTestcaseLabels,
  isApiError,
  setTestcaseLabels,
} from '../../hooks/reports/runManagementApi';
import { useLabels, useReportPermissions, useReportScope } from '../../hooks/reports/useRunManagement';
import {
  REPORT_ROUTES,
  scriptResultStatus,
  validateLabelSelection,
  type RunLabel,
  type TestcaseVersion,
} from '../../types/reports';
import { StatusChip, formatDateTime } from './status';
import { diffTestcaseVersions } from './testcaseVersionDiff';
import { VersionDiff } from './VersionDiff';

export interface TestcaseVersionInsightsProps {
  testcaseId: string;
  testcaseName: string | null;
  versions: TestcaseVersion[];
}


const VersionCompare: React.FC<{ versions: TestcaseVersion[] }> = ({ versions }) => {
  const [newer, setNewer] = useState<number | ''>(versions[0]?.version_number ?? '');
  const [older, setOlder] = useState<number | ''>(versions[1]?.version_number ?? '');

  useEffect(() => {
    setNewer(versions[0]?.version_number ?? '');
    setOlder(versions[1]?.version_number ?? '');
  }, [versions]);

  if (versions.length < 2) {
    return (
      <Typography variant="body2" color="text.secondary">
        Only one version exists; there is nothing to compare yet.
      </Typography>
    );
  }

  const olderRow = versions.find((v) => v.version_number === older);
  const newerRow = versions.find((v) => v.version_number === newer);

  return (
    <Box>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
        {(
          [
            ['From', older, setOlder],
            ['To', newer, setNewer],
          ] as const
        ).map(([label, value, set]) => (
          <FormControl key={label} size="small" sx={{ minWidth: 140 }}>
            <InputLabel>{label}</InputLabel>
            <Select
              label={label}
              value={value}
              onChange={(event) => set(Number(event.target.value))}
              inputProps={{ 'aria-label': `${label} version` }}
            >
              {versions.map((v) => (
                <MenuItem key={v.version_number} value={v.version_number}>
                  Version {v.version_number}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        ))}
      </Box>
      {olderRow && newerRow ? (
        <VersionDiff diff={diffTestcaseVersions(olderRow, newerRow)} />
      ) : (
        <Typography variant="body2" color="text.secondary">
          Select two versions.
        </Typography>
      )}
    </Box>
  );
};

const TestcaseLabels: React.FC<{ testcaseId: string }> = ({ testcaseId }) => {
  const { canEdit } = useReportPermissions();
  const client = useQueryClient();
  const catalog = useLabels();
  const assigned = useQuery({
    queryKey: ['run-management', 'testcase-labels', testcaseId],
    queryFn: () => fetchTestcaseLabels(testcaseId),
    retry: false,
  });
  const [selection, setSelection] = useState<RunLabel[] | null>(null);
  const save = useMutation({
    mutationFn: (ids: string[]) => setTestcaseLabels(testcaseId, ids),
    onSuccess: () => {
      setSelection(null);
      void client.invalidateQueries({ queryKey: ['run-management', 'testcase-labels', testcaseId] });
    },
  });

  if (assigned.isLoading) {
    return (
      <Typography variant="body2" color="text.secondary">
        Loading labels…
      </Typography>
    );
  }
  if (assigned.isError) {
    return (
      <Typography variant="body2" color="text.secondary">
        {isApiError(assigned.error, 404) ? 'Labels unavailable' : describeError(assigned.error)}
      </Typography>
    );
  }

  const current = assigned.data?.labels ?? [];
  const value = selection ?? current;
  const selectionError = validateLabelSelection(value.map((label) => label.id));

  if (!canEdit) {
    return current.length ? (
      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
        {current.map((label) => (
          <Chip key={label.id} size="small" label={label.name} />
        ))}
      </Box>
    ) : (
      <Typography variant="body2" color="text.secondary">
        No labels.
      </Typography>
    );
  }

  return (
    <Box>
      <Autocomplete
        multiple
        size="small"
        options={catalog.data?.items ?? []}
        loading={catalog.isLoading}
        value={value}
        isOptionEqualToValue={(option, item) => option.id === item.id}
        getOptionLabel={(option) => option.name}
        onChange={(_event, next) => setSelection(next)}
        renderInput={(params) => (
          <TextField {...params} label="Labels" error={Boolean(selectionError)} helperText={selectionError ?? ' '} />
        )}
      />
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
        <Button
          size="small"
          variant="contained"
          disabled={selection === null || Boolean(selectionError) || save.isPending}
          onClick={() => save.mutate(value.map((label) => label.id))}
        >
          Save labels
        </Button>
        {save.isError && (
          <Typography variant="body2" color="error">
            {describeError(save.error)}
          </Typography>
        )}
      </Box>
    </Box>
  );
};

const RecentResults: React.FC<{ testcaseId: string; testcaseName: string | null }> = ({ testcaseId, testcaseName }) => {
  const scope = useReportScope();
  const results = useQuery({
    queryKey: ['run-management', 'testcase-results', scope.serverKey, scope.hostFilter, testcaseId, testcaseName],
    queryFn: () => fetchScriptResults({ script_name: testcaseName as string, limit: 10 }, scope),
    enabled: Boolean(testcaseName),
  });

  const rows = useMemo(
    () =>
      (results.data ?? []).filter((row) => {
        if (row.script_type !== 'testcase') return false;
        const linked = row.metadata?.testcase_id;
        return linked === undefined || linked === null || String(linked) === testcaseId;
      }),
    [results.data, testcaseId],
  );

  if (!testcaseName) {
    return (
      <Typography variant="body2" color="text.secondary">
        Results are matched by testcase name, which this version does not record.
      </Typography>
    );
  }
  if (results.isLoading) {
    return (
      <Typography variant="body2" color="text.secondary">
        Loading results…
      </Typography>
    );
  }
  if (results.isError) return <Alert severity="error">{describeError(results.error)}</Alert>;
  if (rows.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No recorded executions in this workspace.
      </Typography>
    );
  }
  return (
    <Box component="ul" sx={{ listStyle: 'none', p: 0, m: 0 }}>
      {rows.map((row) => (
        <Box component="li" key={row.id} sx={{ display: 'flex', gap: 1, alignItems: 'center', py: 0.25, flexWrap: 'wrap' }}>
          <StatusChip status={scriptResultStatus(row)} />
          <Link component={RouterLink} to={REPORT_ROUTES.summary('script', row.id)}>
            {formatDateTime(row.started_at)}
          </Link>
          <Typography variant="caption" color="text.secondary">
            {row.host_name} / {row.device_name}
          </Typography>
        </Box>
      ))}
    </Box>
  );
};

export const TestcaseVersionInsights: React.FC<TestcaseVersionInsightsProps> = ({
  testcaseId,
  testcaseName,
  versions,
}) => (
  <Box data-testid="testcase-version-insights">
    <Divider sx={{ mb: 2 }} />
    <Typography variant="subtitle1" sx={{ mb: 1 }}>
      Compare versions
    </Typography>
    <VersionCompare versions={versions} />
    <Divider sx={{ my: 2 }} />
    <Typography variant="subtitle1" sx={{ mb: 1 }}>
      Labels
    </Typography>
    <TestcaseLabels testcaseId={testcaseId} />
    <Divider sx={{ my: 2 }} />
    <Typography variant="subtitle1" sx={{ mb: 1 }}>
      Recent results
    </Typography>
    <RecentResults testcaseId={testcaseId} testcaseName={testcaseName} />
  </Box>
);
