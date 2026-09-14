import {
  PlayArrow as RunIcon,
  ExpandMore as ExpandMoreIcon,
  CheckCircle as OkIcon,
  Error as ErrorIcon,
} from '@mui/icons-material';
import {
  Box,
  Paper,
  Typography,
  Button,
  TextField,
  FormControl,
  Select,
  MenuItem,
  Checkbox,
  ListItemText,
  Chip,
  CircularProgress,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Alert,
  Stack,
  SelectChangeEvent,
} from '@mui/material';
import React, { useCallback, useMemo, useState } from 'react';

import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { STORAGE_KEYS } from '../config/constants';
import { useServerManager } from '../hooks/useServerManager';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { usePersistedState } from '../hooks/usePersistedState';
import { useToast } from '../hooks/useToast';
import { api } from '../utils/apiClient';
import { buildServerUrl, buildServerUrlForServer } from '../utils/buildUrlUtils';

type HostRunStatus = 'pending' | 'running' | 'ok' | 'error';

interface HostResult {
  status: HostRunStatus;
  success?: boolean;
  exit_code?: number | null;
  stdout?: string;
  stderr?: string;
  stdout_truncated?: boolean;
  stderr_truncated?: boolean;
  duration_ms?: number;
  timed_out?: boolean;
  error?: string | null;
  transport_error?: boolean;
}

const MENU_PROPS = { PaperProps: { sx: { maxHeight: 320 } } };
const DEFAULT_TIMEOUT = 120;

const OutputBlock: React.FC<{ label: string; text: string; truncated?: boolean }> = ({
  label,
  text,
  truncated,
}) => {
  if (!text) return null;
  return (
    <Box sx={{ mb: 1 }}>
      <Typography variant="caption" color="textSecondary" sx={{ fontWeight: 'bold' }}>
        {label}
        {truncated ? ' (truncated)' : ''}
      </Typography>
      <Box
        component="pre"
        sx={{
          m: 0,
          mt: 0.5,
          p: 1,
          backgroundColor: 'grey.900',
          color: 'grey.100',
          borderRadius: 1,
          fontFamily: 'monospace',
          fontSize: '0.75rem',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          maxHeight: 320,
          overflowY: 'auto',
        }}
      >
        {text}
      </Box>
    </Box>
  );
};

const RunCommand: React.FC = () => {
  const { serverHostsData } = useServerManager();
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();
  const { showSuccess, showError, showWarning } = useToast();

  // All known host names across every connected server (sorted, unique) —
  // same derivation as the Dashboard target filter.
  const hostOptions = useMemo(() => {
    const names = new Set<string>();
    serverHostsData.forEach((sd) => sd.hosts.forEach((h) => names.add(h.host_name)));
    return Array.from(names).sort();
  }, [serverHostsData]);

  // Map every host -> the server that actually owns it, so the request goes
  // to the right backend regardless of which server is selected in the UI
  // (no manual re-selection; "Host X not found" can't happen for a listed
  // host). serverHostsData already carries this mapping.
  const hostServerUrl = useMemo(() => {
    const map = new Map<string, string>();
    serverHostsData.forEach((sd) => {
      const url = sd.server_info?.server_url;
      if (url) sd.hosts.forEach((h) => map.set(h.host_name, url));
    });
    return map;
  }, [serverHostsData]);

  // Persist only the host selection (never the command body).
  const [selectedHosts, setSelectedHosts] = usePersistedState<string[]>(
    STORAGE_KEYS.RUN_COMMAND_HOSTS,
    [],
  );
  const [command, setCommand] = useState('');
  const [timeoutSec, setTimeoutSec] = useState<number>(DEFAULT_TIMEOUT);
  const [isRunning, setIsRunning] = useState(false);
  const [results, setResults] = useState<Record<string, HostResult>>({});

  // Only run on hosts that still exist in the registry.
  const hostsToRun = useMemo(
    () => selectedHosts.filter((h) => hostOptions.includes(h)),
    [selectedHosts, hostOptions],
  );

  const setHostResult = useCallback((host: string, patch: HostResult) => {
    setResults((prev) => ({ ...prev, [host]: patch }));
  }, []);

  const runAll = useCallback(async () => {
    const clampedTimeout = Math.max(1, Math.min(600, Math.floor(timeoutSec) || DEFAULT_TIMEOUT));
    setIsRunning(true);
    setResults(Object.fromEntries(hostsToRun.map((h) => [h, { status: 'pending' as const }])));

    let okCount = 0;
    // Sequential — one host at a time. A failure (command or transport) never
    // breaks the loop; we record it and move on to the next host.
    for (const host of hostsToRun) {
      setHostResult(host, { status: 'running' });
      try {
        const srv = hostServerUrl.get(host);
        const url = srv
          ? buildServerUrlForServer(srv, '/server/system/runCommandOnHost')
          : buildServerUrl('/server/system/runCommandOnHost');
        const res = await api.post<HostResult>(url, {
          host_name: host,
          command,
          timeout: clampedTimeout,
        });
        const ok = res.success === true;
        if (ok) okCount += 1;
        setHostResult(host, { ...res, status: ok ? 'ok' : 'error' });
      } catch (e) {
        // api.post throws on non-2xx (host unreachable / timeout / proxy error).
        setHostResult(host, {
          status: 'error',
          transport_error: true,
          error: e instanceof Error ? e.message : String(e),
        });
      }
    }

    setIsRunning(false);
    const failed = hostsToRun.length - okCount;
    if (failed === 0) {
      showSuccess(`All ${hostsToRun.length} host(s) succeeded`);
    } else {
      showError(`${failed} of ${hostsToRun.length} host(s) failed`);
    }
  }, [hostsToRun, command, timeoutSec, hostServerUrl, setHostResult, showSuccess, showError]);

  const handleRunClick = useCallback(() => {
    if (!command.trim()) {
      showWarning('Enter a command to run');
      return;
    }
    if (hostsToRun.length === 0) {
      showWarning('Select at least one host');
      return;
    }
    confirm({
      title: `Run command on ${hostsToRun.length} host(s)?`,
      message:
        `You are about to run an arbitrary shell command AS ROOT (sudo) on ` +
        `${hostsToRun.length} host(s):\n\n${hostsToRun.join(', ')}\n\n` +
        `This can permanently change or break these machines. Commands run ` +
        `sequentially; a failure on one host does not stop the others.`,
      confirmText: 'Run',
      confirmColor: 'warning',
      onConfirm: () => {
        void runAll();
      },
    });
  }, [command, hostsToRun, confirm, runAll, showWarning]);

  const statusChip = (r: HostResult | undefined) => {
    const st = r?.status ?? 'pending';
    if (st === 'pending') return <Chip size="small" label="Pending" variant="outlined" />;
    if (st === 'running')
      return (
        <Chip
          size="small"
          icon={<CircularProgress size={12} />}
          label="Running"
          variant="outlined"
        />
      );
    if (st === 'ok')
      return (
        <Chip
          size="small"
          color="success"
          icon={<OkIcon />}
          label={`OK · exit ${r?.exit_code ?? 0} · ${r?.duration_ms ?? 0} ms`}
        />
      );
    return (
      <Chip
        size="small"
        color="error"
        icon={<ErrorIcon />}
        label={
          r?.transport_error
            ? 'Error · unreachable'
            : r?.timed_out
              ? 'Error · timed out'
              : `Error · exit ${r?.exit_code ?? '?'}`
        }
      />
    );
  };

  return (
    <Box>
      <Typography variant="h4" component="h1" gutterBottom>
        Run Command on Hosts
      </Typography>

      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} sx={{ mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
          <FormControl size="small" sx={{ width: 280 }}>
            <Select
              multiple
              displayEmpty
              value={selectedHosts}
              disabled={isRunning}
              onChange={(e: SelectChangeEvent<string[]>) =>
                setSelectedHosts(e.target.value as string[])
              }
              renderValue={(sel) =>
                (sel as string[]).length === 0
                  ? 'Select hosts'
                  : `${(sel as string[]).length} host(s) selected`
              }
              MenuProps={MENU_PROPS}
            >
              {hostOptions.map((h) => (
                <MenuItem key={h} value={h} dense>
                  <Checkbox size="small" checked={selectedHosts.includes(h)} />
                  <ListItemText primary={h} primaryTypographyProps={{ variant: 'body2' }} />
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Chip
            label={`Select all (${hostOptions.length})`}
            size="small"
            variant="outlined"
            onClick={() => setSelectedHosts(hostOptions)}
            disabled={isRunning}
          />
          <Chip
            label="Clear"
            size="small"
            variant="outlined"
            onClick={() => setSelectedHosts([])}
            disabled={isRunning}
          />
          <TextField
            label="Timeout (s)"
            type="number"
            size="small"
            value={timeoutSec}
            disabled={isRunning}
            onChange={(e) => setTimeoutSec(Number(e.target.value))}
            inputProps={{ min: 1, max: 600 }}
            sx={{ width: 120 }}
          />
        </Stack>

        <TextField
          label="Command / script"
          placeholder={'e.g.\necho "host: $(hostname)"\nsudo systemctl is-active vpt-host'}
          multiline
          minRows={8}
          fullWidth
          value={command}
          disabled={isRunning}
          onChange={(e) => setCommand(e.target.value)}
          InputProps={{ sx: { fontFamily: 'monospace', fontSize: '0.85rem' } }}
          sx={{ mb: 2 }}
        />

        <Button
          variant="contained"
          color="warning"
          startIcon={isRunning ? <CircularProgress size={16} color="inherit" /> : <RunIcon />}
          onClick={handleRunClick}
          disabled={isRunning}
        >
          {isRunning ? 'Running…' : `Run on ${hostsToRun.length} host(s)`}
        </Button>
      </Paper>

      {hostsToRun.length > 0 && Object.keys(results).length > 0 && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Results
          </Typography>
          {hostsToRun.map((host) => {
            const r = results[host];
            return (
              <Accordion
                // Remount on status change so errored hosts auto-expand while
                // the user can still toggle any panel afterwards.
                key={`${host}:${r?.status ?? 'pending'}`}
                defaultExpanded={r?.status === 'error'}
                sx={{
                  boxShadow: 'none',
                  border: '1px solid #e0e0e0',
                  mb: 1,
                  '&:before': { display: 'none' },
                }}
              >
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1.5,
                      width: '100%',
                    }}
                  >
                    <Typography variant="subtitle2" sx={{ fontWeight: 'bold', minWidth: 160 }}>
                      {host}
                    </Typography>
                    {statusChip(r)}
                  </Box>
                </AccordionSummary>
                <AccordionDetails>
                  {!r || r.status === 'pending' ? (
                    <Typography variant="body2" color="textSecondary">
                      Waiting…
                    </Typography>
                  ) : r.status === 'running' ? (
                    <Typography variant="body2" color="textSecondary">
                      Running…
                    </Typography>
                  ) : (
                    <>
                      {r.error && (
                        <Alert severity="error" sx={{ mb: 1 }}>
                          {r.error}
                        </Alert>
                      )}
                      <OutputBlock label="stdout" text={r.stdout || ''} truncated={r.stdout_truncated} />
                      <OutputBlock label="stderr" text={r.stderr || ''} truncated={r.stderr_truncated} />
                      {!r.stdout && !r.stderr && !r.error && (
                        <Typography variant="body2" color="textSecondary">
                          (no output)
                        </Typography>
                      )}
                      <Typography variant="caption" color="textSecondary">
                        exit {String(r.exit_code)} · {r.duration_ms ?? 0} ms
                      </Typography>
                    </>
                  )}
                </AccordionDetails>
              </Accordion>
            );
          })}
        </Paper>
      )}

      <ConfirmDialog
        open={dialogState.open}
        title={dialogState.title}
        message={dialogState.message}
        confirmText={dialogState.confirmText}
        cancelText={dialogState.cancelText}
        confirmColor={dialogState.confirmColor}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </Box>
  );
};

export default RunCommand;
