/**
 * MasterchiefConfirmCard
 *
 * Rendered inline in the AgentChat thread when Atlas proposes a masterchief op
 * via the `propose_masterchief_op` MCP tool. The card shows what the op will
 * do, who is asking, and the blast radius. Three actions:
 *
 *  - Confirm  -> POST /server/masterchief/execute with the user's JWT
 *  - Requeue  -> leave the proposal open; the user can come back to it
 *  - Abandon  -> mark the audit row 'refused' (state=refused, summary='abandoned')
 *
 * The privilege holder is always the human browser (the route layer rejects
 * the service key by design), so the model never directly executes an op.
 */
import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material';
import {
  CheckCircleOutline as CheckIcon,
  Close as CloseIcon,
  HourglassEmpty as RequeueIcon,
  SecurityOutlined as SecurityIcon,
  WarningAmber as WarningIcon,
} from '@mui/icons-material';
import { api } from '../../../utils/apiClient';
import { useAgentChatPalette } from '../../../constants/agentChatTheme';

export interface MasterchiefProposal {
  audit_id: string;
  op: string;
  summary: string;
  mutates: boolean;
  required_permission: string;
  platform_admin_only: boolean;
  blast_radius: string;
  params: Record<string, unknown>;
  requester_email?: string;
}

export interface MasterchiefConfirmCardProps {
  proposal: MasterchiefProposal;
  onExecuted?: (result: { state: string; result_summary?: string; duration_ms?: number }) => void;
  onAbandoned?: () => void;
}

type Status = 'proposed' | 'executing' | 'executed' | 'failed' | 'refused';

export const MasterchiefConfirmCard: React.FC<MasterchiefConfirmCardProps> = ({
  proposal,
  onExecuted,
  onAbandoned,
}) => {
  const P = useAgentChatPalette();
  const [status, setStatus] = useState<Status>('proposed');
  const [summary, setSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const callExecute = async (action: 'execute' | 'abandon') => {
    setStatus(action === 'execute' ? 'executing' : 'refused');
    setError(null);
    if (action === 'abandon') {
      // Soft abandon in Part 7: the row stays 'proposed' in the audit table.
      // A dedicated abandon endpoint ships in a follow-up; the user-facing
      // effect is the same (the card is dismissed and the proposal will
      // surface as stale the next time the user opens the chat).
      setSummary('abandoned by user (audit row left as proposed)');
      onAbandoned?.();
      return;
    }
    try {
      const res = await api.post('/server/masterchief/execute', {
        audit_id: proposal.audit_id,
      });
      if (!res.data?.success) {
        const msg = res.data?.error || `HTTP ${res.status}`;
        setStatus('failed');
        setError(msg);
        onExecuted?.({ state: 'failed', result_summary: msg });
        return;
      }
      const d = res.data;
      setStatus(d.state || 'executed');
      setSummary(d.result_summary || null);
      onExecuted?.({
        state: d.state,
        result_summary: d.result_summary,
        duration_ms: d.duration_ms,
      });
    } catch (e: any) {
      setStatus('failed');
      setError(String(e?.response?.data?.error || e?.message || e));
    }
  };

  const statusColor: Record<Status, string> = {
    proposed: P.accent,
    executing: P.accent,
    executed: '#22c55e',
    failed: '#ef4444',
    refused: P.textMuted,
  };

  const statusLabel: Record<Status, string> = {
    proposed: 'awaiting confirmation',
    executing: 'executing...',
    executed: 'executed',
    failed: 'failed',
    refused: 'abandoned',
  };

  const isTerminal = status === 'executed' || status === 'failed' || status === 'refused';

  return (
    <Box
      sx={{
        my: 1.5,
        p: 2,
        borderRadius: 2,
        bgcolor: P.surface,
        border: `1px solid ${proposal.mutates ? '#f59e0b' : P.borderColor}`,
        boxShadow: proposal.mutates ? '0 0 0 1px rgba(245,158,11,0.2)' : 'none',
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <SecurityIcon sx={{ color: P.accent, fontSize: 18 }} />
        <Typography variant="subtitle2" sx={{ color: P.textPrimary, fontWeight: 600, flex: 1 }}>
          Masterchief · {proposal.op}
        </Typography>
        {proposal.mutates && (
          <Chip
            icon={<WarningIcon sx={{ fontSize: 14 }} />}
            label="mutates"
            size="small"
            sx={{
              bgcolor: 'rgba(245,158,11,0.15)',
              color: '#b45309',
              fontWeight: 600,
              fontSize: '0.7rem',
            }}
          />
        )}
        {proposal.platform_admin_only && (
          <Chip
            label="admin-only on prod"
            size="small"
            sx={{
              bgcolor: 'rgba(212,165,116,0.15)',
              color: P.accent,
              fontWeight: 600,
              fontSize: '0.7rem',
            }}
          />
        )}
        <Tooltip title="close (audit row stays proposed)">
          <IconButton
            size="small"
            onClick={() => callExecute('abandon')}
            disabled={isTerminal}
            sx={{ color: P.textMuted }}
          >
            <CloseIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>
      </Stack>

      <Typography variant="body2" sx={{ color: P.textPrimary, mb: 0.5 }}>
        {proposal.summary}
      </Typography>
      <Typography variant="caption" sx={{ color: P.textMuted, display: 'block', mb: 1 }}>
        permission: <code>{proposal.required_permission}</code>
        {proposal.requester_email ? <> · requested by {proposal.requester_email}</> : null}
      </Typography>

      <Box
        sx={{
          p: 1,
          mb: 1.5,
          borderRadius: 1.5,
          bgcolor: proposal.mutates ? 'rgba(245,158,11,0.08)' : P.sidebarBg,
          border: `1px solid ${P.borderColor}`,
        }}
      >
        <Typography variant="caption" sx={{ color: P.textMuted, fontWeight: 600, display: 'block', mb: 0.25 }}>
          Blast radius
        </Typography>
        <Typography variant="caption" sx={{ color: P.textPrimary }}>
          {proposal.blast_radius}
        </Typography>
      </Box>

      {Object.keys(proposal.params || {}).length > 0 && (
        <Box
          component="pre"
          sx={{
            m: 0,
            mb: 1.5,
            p: 1,
            fontSize: '0.7rem',
            color: P.textPrimary,
            bgcolor: P.inputBg,
            border: `1px solid ${P.borderColor}`,
            borderRadius: 1,
            overflow: 'auto',
            maxHeight: 120,
          }}
        >
          {JSON.stringify(proposal.params, null, 2)}
        </Box>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 1, fontSize: '0.75rem' }}>
          {error}
        </Alert>
      )}
      {summary && !error && (
        <Alert
          severity={status === 'executed' ? 'success' : status === 'failed' ? 'error' : 'info'}
          sx={{ mb: 1, fontSize: '0.75rem' }}
        >
          {summary}
        </Alert>
      )}

      <Stack direction="row" alignItems="center" spacing={1}>
        <Box
          sx={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            bgcolor: statusColor[status],
            transition: 'all 0.2s',
          }}
        />
        <Typography variant="caption" sx={{ color: P.textMuted, flex: 1 }}>
          {statusLabel[status]}
        </Typography>
        <Button
          variant="text"
          size="small"
          startIcon={<RequeueIcon sx={{ fontSize: 14 }} />}
          onClick={() => callExecute('abandon')}
          disabled={isTerminal}
          sx={{ color: P.textMuted }}
        >
          Abandon
        </Button>
        <Button
          variant="contained"
          size="small"
          startIcon={
            status === 'executing' ? (
              <CircularProgress size={12} sx={{ color: 'inherit' }} />
            ) : (
              <CheckIcon sx={{ fontSize: 14 }} />
            )
          }
          onClick={() => callExecute('execute')}
          disabled={isTerminal || status === 'executing'}
          sx={{
            bgcolor: P.accent,
            color: '#0a0a0a',
            fontWeight: 600,
            '&:hover': { bgcolor: P.accentHover },
            '&.Mui-disabled': { bgcolor: P.hoverBg, color: P.textMuted },
          }}
        >
          {status === 'executing' ? 'Executing' : 'Confirm'}
        </Button>
      </Stack>
    </Box>
  );
};
