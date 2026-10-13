/**
 * Manual runs: a person walks through a testcase snapshot step by step and records the
 * actual outcome of each step. Sessions are resumable, saves use optimistic concurrency
 * (409 = someone else saved first), evidence is optional and its absence is shown, and
 * finalize is idempotent — it produces exactly one recorded result.
 */

import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Link,
  List,
  ListItemButton,
  ListItemText,
  Step,
  StepContent,
  StepLabel,
  Stepper,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import React, { useMemo, useRef, useState } from 'react';
import { Link as RouterLink, useNavigate, useParams } from 'react-router-dom';

import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { useWorkspaceContext } from '../contexts/workspace/WorkspaceContext';
import { useAuth } from '../hooks/auth/useAuth';
import { useHostData } from '../hooks/useHostManager';
import { EmptyState, QueryState, ReportPage } from '../components/reports/PageState';
import { formatDateTime } from '../components/reports/status';
import {
  createManualSession,
  describeError,
  fetchManualSession,
  fetchManualSessions,
  fetchTestcases,
  finalizeManualSession,
  isApiError,
  newIdempotencyKey,
  updateManualSession,
} from '../hooks/reports/runManagementApi';
import { useReportPermissions, useReportScope } from '../hooks/reports/useRunManagement';
import { useI18n } from '../i18n/useI18n';
import {
  MANUAL_STEP_OUTCOMES,
  REPORT_ROUTES,
  type ManualSession,
  type ManualStep,
  type ManualStepOutcome,
} from '../types/reports';

const OUTCOME_LABELS: Record<ManualStepOutcome, string> = {
  passed: 'Passed',
  failed: 'Failed',
  skipped: 'Skipped',
  blocked: 'Blocked',
};

const CONFLICT_MESSAGE = 'Someone else saved this session. The latest version is shown; re-apply your changes.';

/** Optional evidence must be an http(s) URL; empty means "no evidence". */
export const evidenceUrlError = (raw: string): string | null => {
  const value = raw.trim();
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? null : 'Use an http(s) link';
  } catch {
    return 'Use an http(s) link';
  }
};

const sessionKey = (serverKey: string, id: string) => ['run-management', 'manual-session', serverKey, id];

/** The person who ran the session. The server does not resolve names, so say "you" or show the id. */
export const actorLabel = (actorId: string | null, currentUserId: string | null | undefined): string => {
  if (!actorId) return 'Unknown';
  return currentUserId && actorId === currentUserId ? 'You' : actorId;
};

interface DeviceTarget {
  host_name: string;
  device_id: string;
  device_name: string;
}

/**
 * Devices registered on this server and allowed by the active workspace. A manual result
 * is recorded against one of them (host_name + device DISPLAY name, as script results are).
 */
const useManualTargets = (): DeviceTarget[] => {
  const { getAllHosts } = useHostData();
  const { isDeviceAllowed } = useWorkspaceContext();
  return useMemo(() => {
    const targets: DeviceTarget[] = [];
    for (const host of getAllHosts()) {
      for (const device of host.devices || []) {
        if (!device.device_id || !isDeviceAllowed(host.host_name, device.device_id)) continue;
        targets.push({
          host_name: host.host_name,
          device_id: device.device_id,
          device_name: device.device_name || device.device_id,
        });
      }
    }
    return targets;
  }, [getAllHosts, isDeviceAllowed]);
};

/** 409 carries the current session: show it instead of a second request. */
const conflictCurrent = (error: unknown): ManualSession | null => {
  if (!isApiError(error, 409)) return null;
  const body = error.body as { current?: ManualSession } | null;
  return body && typeof body === 'object' && body.current && Array.isArray(body.current.steps) ? body.current : null;
};

// ---------------------------------------------------------------------------
// Start / resume
// ---------------------------------------------------------------------------

const ManualStart: React.FC = () => {
  const { t } = useI18n();
  const navigate = useNavigate();
  const scope = useReportScope();
  const { canRunManual } = useReportPermissions();
  const { user } = useAuth();
  const targets = useManualTargets();
  const sessions = useQuery({
    queryKey: ['run-management', 'manual-sessions', scope.serverKey, scope.deviceFilter],
    queryFn: () => fetchManualSessions(scope),
  });
  const testcases = useQuery({
    queryKey: ['run-management', 'manual-testcases', scope.serverKey],
    queryFn: fetchTestcases,
    enabled: canRunManual,
  });
  const [testcase, setTestcase] = useState<{ testcase_id: string; testcase_name: string } | null>(null);
  const [target, setTarget] = useState<DeviceTarget | null>(null);
  const startKeyRef = useRef<string | null>(null);
  const start = useMutation({
    mutationFn: ({ testcaseId, device }: { testcaseId: string; device: DeviceTarget }) => {
      // One key per start click; a retry after a failure reuses it.
      if (!startKeyRef.current) startKeyRef.current = newIdempotencyKey();
      return createManualSession(
        {
          testcase_id: testcaseId,
          idempotency_key: startKeyRef.current,
          host_name: device.host_name,
          device_name: device.device_name,
        },
        scope,
      );
    },
    onSuccess: (session) => {
      startKeyRef.current = null;
      navigate(REPORT_ROUTES.manualSession(session.id));
    },
  });

  return (
    <>
      <Card variant="outlined" sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="subtitle1" sx={{ mb: 1 }}>
            Start a manual run
          </Typography>
          {!canRunManual ? (
            <Alert severity="info">You do not have permission to run manual tests.</Alert>
          ) : (
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
              <Autocomplete
                size="small"
                sx={{ flex: '1 1 260px', minWidth: 0 }}
                options={testcases.data?.testcases ?? []}
                loading={testcases.isLoading}
                value={testcase}
                isOptionEqualToValue={(a, b) => a.testcase_id === b.testcase_id}
                getOptionLabel={(option) => option.testcase_name}
                onChange={(_e, value) => {
                  startKeyRef.current = null;
                  setTestcase(value);
                }}
                renderInput={(params) => <TextField {...params} label="Test case" />}
              />
              <Autocomplete
                size="small"
                sx={{ flex: '1 1 220px', minWidth: 0 }}
                options={targets}
                value={target}
                isOptionEqualToValue={(a, b) => a.host_name === b.host_name && a.device_id === b.device_id}
                getOptionLabel={(option) => `${option.host_name} · ${option.device_name}`}
                noOptionsText="No device of this server in your workspace"
                onChange={(_e, value) => {
                  startKeyRef.current = null;
                  setTarget(value);
                }}
                renderInput={(params) => (
                  <TextField {...params} label="Device under test" helperText="The result is recorded on this device" />
                )}
              />
              <Button
                variant="contained"
                disabled={!testcase || !target || start.isPending}
                onClick={() => testcase && target && start.mutate({ testcaseId: testcase.testcase_id, device: target })}
              >
                Start
              </Button>
            </Box>
          )}
          {start.isError && (
            <Alert severity="error" sx={{ mt: 1 }}>
              {describeError(start.error)} — pressing Start again retries the same request.
            </Alert>
          )}
        </CardContent>
      </Card>
      <Typography variant="subtitle1" sx={{ mb: 1 }}>
        In-progress sessions
      </Typography>
      <QueryState loading={sessions.isLoading} error={sessions.error}>
        {(sessions.data?.items ?? []).length === 0 ? (
          <EmptyState message={t('No manual session in progress. Pick a test case and a device above, then press Start.')} />
        ) : (
          <List dense>
            {(sessions.data?.items ?? []).map((session) => (
              <ListItemButton key={session.id} component={RouterLink} to={REPORT_ROUTES.manualSession(session.id)}>
                <ListItemText
                  primary={session.testcase_name ?? 'Untitled test case'}
                  secondary={`Started ${formatDateTime(session.started_at)} · ${session.host_name} · ${
                    session.device_name
                  } · tester: ${actorLabel(session.actor_id, user?.id)}`}
                />
              </ListItemButton>
            ))}
          </List>
        )}
      </QueryState>
    </>
  );
};

// ---------------------------------------------------------------------------
// One session
// ---------------------------------------------------------------------------

const ManualSessionView: React.FC<{ sessionId: string }> = ({ sessionId }) => {
  const scope = useReportScope();
  const client = useQueryClient();
  const { canRunManual } = useReportPermissions();
  const { user } = useAuth();
  const key = sessionKey(scope.serverKey, sessionId);
  const query = useQuery({ queryKey: key, queryFn: () => fetchManualSession(sessionId, scope) });
  const [draft, setDraft] = useState<ManualStep[] | null>(null);
  const [activeStep, setActiveStep] = useState(0);
  const [conflict, setConflict] = useState(false);
  const [message, setMessage] = useState<{ severity: 'success' | 'error'; text: string } | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [finalizedResultId, setFinalizedResultId] = useState<string | null>(null);

  const session = query.data;
  const steps = draft ?? session?.steps ?? [];
  const finalized = session?.status === 'finalized' || finalizedResultId !== null;
  const readOnly = finalized || !canRunManual || session?.status === 'abandoned';
  // The server refuses finalize (422) while a REQUIRED step has no outcome.
  const missingRequired = steps.filter((step) => step.required && !step.outcome).length;
  const allRecorded = steps.length > 0 && missingRequired === 0;
  const urlErrors = steps.map((step) => evidenceUrlError(step.evidence_url ?? ''));
  const hasUrlError = urlErrors.some(Boolean);

  const summary = useMemo(() => {
    const counts: Record<ManualStepOutcome, number> = { passed: 0, failed: 0, skipped: 0, blocked: 0 };
    for (const step of steps) if (step.outcome) counts[step.outcome] += 1;
    return { counts, withoutEvidence: steps.filter((step) => !step.evidence_url).length };
  }, [steps]);

  const handleConflict = async (error: unknown) => {
    setDraft(null);
    setConflict(true);
    const current = conflictCurrent(error);
    if (current) client.setQueryData(key, current);
    else await client.invalidateQueries({ queryKey: key });
  };

  const editStep = (ordinal: number, patch: Partial<ManualStep>) => {
    setConflict(false);
    setDraft((steps).map((step) => (step.ordinal === ordinal ? { ...step, ...patch } : step)));
  };

  /** Save the draft; returns the server session, or null after a handled failure. */
  const save = async (current: ManualSession): Promise<ManualSession | null> => {
    if (!draft) return current;
    try {
      const saved = await updateManualSession(
        sessionId,
        {
        expected_version: current.optimistic_version,
        steps: draft.map(({ ordinal, outcome, note, evidence_url }) => ({
          ordinal,
          outcome,
          note: note?.trim() ? note.trim() : null,
          evidence_url: evidence_url?.trim() ? evidence_url.trim() : null,
        })),
        },
        scope,
      );
      client.setQueryData(key, saved);
      setDraft(null);
      return saved;
    } catch (error) {
      if (isApiError(error, 409)) {
        await handleConflict(error);
      } else {
        setMessage({ severity: 'error', text: describeError(error) });
      }
      return null;
    }
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!session) return null;
      const saved = await save(session);
      if (saved) setMessage({ severity: 'success', text: 'Saved.' });
      return saved;
    },
  });

  const finalizeMutation = useMutation({
    mutationFn: async () => {
      if (!session) return;
      setMessage(null);
      const saved = await save(session);
      if (!saved) return;
      // Finalize is idempotent per session on the server: a retry (or a second tab)
      // gets the result already recorded, never a second one.
      try {
        const response = await finalizeManualSession(sessionId, { expected_version: saved.optimistic_version }, scope);
        client.setQueryData(key, response.session);
        setFinalizedResultId(response.script_result_id);
      } catch (error) {
        if (isApiError(error, 409)) {
          await handleConflict(error);
        } else if (isApiError(error, 422)) {
          setMessage({ severity: 'error', text: `${describeError(error)} — record an outcome for every required step.` });
        } else {
          setMessage({ severity: 'error', text: `${describeError(error)} — finalizing again is safe.` });
        }
      }
    },
  });

  if (!session) {
    return (
      <QueryState loading={query.isLoading} error={query.error ?? new Error('Session not found')}>
        {null}
      </QueryState>
    );
  }

  const resultId = finalizedResultId ?? session.script_result_id;

  return (
    <Box>
      <Typography variant="h5" component="h1" sx={{ wordBreak: 'break-word' }}>
        {session.testcase_name ?? 'Untitled test case'}
      </Typography>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center', my: 1 }}>
        <Chip
          size="small"
          label={session.testcase_version !== null ? `Snapshot of version ${session.testcase_version}` : 'Version not recorded'}
        />
        <Chip size="small" label={`Tester: ${actorLabel(session.actor_id, user?.id)}`} />
        <Chip size="small" label={`${session.host_name} · ${session.device_name}`} />
        <Typography variant="caption" color="text.secondary">
          Started {formatDateTime(session.started_at)} · last saved {formatDateTime(session.updated_at)}
        </Typography>
      </Box>

      {conflict && (
        <Alert severity="warning" sx={{ mb: 2 }} data-testid="manual-conflict">
          {CONFLICT_MESSAGE}
        </Alert>
      )}
      {!canRunManual && !finalized && (
        <Alert severity="info" sx={{ mb: 2 }}>
          You can view this session but not record outcomes.
        </Alert>
      )}
      {finalized && (
        <Alert severity="success" sx={{ mb: 2 }} data-testid="manual-finalized">
          Result recorded.{' '}
          {resultId && (
            <Link component={RouterLink} to={REPORT_ROUTES.summary('script', resultId)}>
              Open the run summary
            </Link>
          )}
        </Alert>
      )}
      {message && (
        <Alert severity={message.severity} sx={{ mb: 2 }}>
          {message.text}
        </Alert>
      )}

      {steps.length === 0 ? (
        <EmptyState message="This test case snapshot has no steps." />
      ) : (
        <Stepper orientation="vertical" activeStep={activeStep} nonLinear>
          {steps.map((step, index) => (
            <Step key={step.ordinal} completed={Boolean(step.outcome)}>
              <StepLabel
                onClick={() => setActiveStep(index)}
                sx={{ cursor: 'pointer' }}
                optional={
                  <Typography variant="caption" color="text.secondary">
                    {step.outcome ? OUTCOME_LABELS[step.outcome] : 'No outcome yet'}
                    {' · '}
                    {step.evidence_url ? 'Evidence attached' : 'No evidence attached'}
                  </Typography>
                }
              >
                {step.label}
                {!step.required && (
                  <Chip size="small" variant="outlined" label="Optional" sx={{ ml: 1, height: 20 }} />
                )}
              </StepLabel>
              <StepContent>
                {step.expected && (
                  <Typography variant="body2" sx={{ mb: 1 }}>
                    Expected: {step.expected}
                  </Typography>
                )}
                <ToggleButtonGroup
                  exclusive
                  size="small"
                  value={step.outcome}
                  disabled={readOnly}
                  onChange={(_e, value: ManualStepOutcome | null) => editStep(step.ordinal, { outcome: value })}
                  aria-label={`Outcome of step ${index + 1}`}
                  sx={{ flexWrap: 'wrap', mb: 1 }}
                >
                  {MANUAL_STEP_OUTCOMES.map((outcome) => (
                    <ToggleButton key={outcome} value={outcome}>
                      {OUTCOME_LABELS[outcome]}
                    </ToggleButton>
                  ))}
                </ToggleButtonGroup>
                <TextField
                  fullWidth
                  size="small"
                  label="Note (optional)"
                  value={step.note ?? ''}
                  disabled={readOnly}
                  onChange={(e) => editStep(step.ordinal, { note: e.target.value })}
                  sx={{ mb: 1 }}
                />
                <TextField
                  fullWidth
                  size="small"
                  label="Evidence link (optional)"
                  value={step.evidence_url ?? ''}
                  disabled={readOnly}
                  error={Boolean(urlErrors[index])}
                  helperText={urlErrors[index] ?? (step.evidence_url ? ' ' : 'No evidence attached')}
                  onChange={(e) => editStep(step.ordinal, { evidence_url: e.target.value })}
                />
              </StepContent>
            </Step>
          ))}
        </Stepper>
      )}

      {!readOnly && (
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 2 }}>
          <Button
            variant="outlined"
            disabled={!draft || hasUrlError || saveMutation.isPending || finalizeMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            Save progress
          </Button>
          <Button
            variant="contained"
            disabled={!allRecorded || hasUrlError || saveMutation.isPending || finalizeMutation.isPending}
            onClick={() => setConfirmOpen(true)}
          >
            Finalize
          </Button>
          {!allRecorded && (
            <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
              Record an outcome for every required step to finalize ({missingRequired} left).
            </Typography>
          )}
        </Box>
      )}

      <ConfirmDialog
        open={confirmOpen}
        title="Finalize this manual run?"
        message={[
          `Passed ${summary.counts.passed} · Failed ${summary.counts.failed} · Skipped ${summary.counts.skipped} · Blocked ${summary.counts.blocked}`,
          `${summary.withoutEvidence} step(s) without evidence.`,
          'This records exactly one result and makes the session read-only.',
        ].join('\n')}
        confirmText="Finalize"
        onConfirm={() => {
          setConfirmOpen(false);
          finalizeMutation.mutate();
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </Box>
  );
};

const ManualRun: React.FC = () => {
  const { sessionId } = useParams<{ sessionId?: string }>();
  // Without a session this is the Manual runs tab of Run Management, which brings the page chrome.
  return sessionId ? (
    <ReportPage>
      <ManualSessionView key={sessionId} sessionId={sessionId} />
    </ReportPage>
  ) : (
    <ManualStart />
  );
};

export default ManualRun;
