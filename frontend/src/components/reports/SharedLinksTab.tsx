import { Lock as LockIcon } from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Link,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import React, { useCallback, useEffect, useMemo, useState } from 'react';

import {
  useReportSnapshots,
  type TeamSnapshot,
  type TeamSnapshotList,
  type TeamSnapshotStatus,
} from '../../hooks/useReportSnapshots';
import { openR2Url } from '../../utils/infrastructure/cloudflareUtils';
import { dangerButtonSx } from '../common/PageChrome';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';

const STATUS_CHIPS: Array<{ value: TeamSnapshotStatus; label: string }> = [
  { value: 'active', label: 'Active' },
  { value: 'expired', label: 'Expired' },
  { value: 'revoked', label: 'Revoked' },
  { value: 'all', label: 'All' },
];

const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '-');

const fmtSize = (bytes: number) => {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
};

const fmtSpan = (ms: number) => {
  const min = Math.round(ms / 60000);
  if (min < 60) return `${Math.max(min, 1)} min`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} h`;
  return `${Math.round(h / 24)} d`;
};

type RowStatus = 'active' | 'expired' | 'revoked' | 'purged';

const rowStatus = (s: TeamSnapshot, now: number): RowStatus => {
  if (s.revoked_at) return 'revoked';
  if (new Date(s.expires_at).getTime() <= now) return s.purged_at ? 'purged' : 'expired';
  return 'active';
};

const expiryText = (s: TeamSnapshot, status: RowStatus, now: number) => {
  if (status === 'revoked') return 'revoked';
  const diff = new Date(s.expires_at).getTime() - now;
  return diff > 0 ? `in ${fmtSpan(diff)}` : `expired ${fmtSpan(-diff)} ago`;
};

const STATUS_COLOR: Record<RowStatus, 'success' | 'default' | 'error' | 'warning'> = {
  active: 'success',
  expired: 'warning',
  revoked: 'error',
  purged: 'default',
};

export const SharedLinksTab: React.FC = () => {
  const P = useAgentChatPalette();
  const { listTeamSnapshots, revokeSnapshot } = useReportSnapshots();
  const [status, setStatus] = useState<TeamSnapshotStatus>('active');
  const [filter, setFilter] = useState('');
  const [data, setData] = useState<TeamSnapshotList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await listTeamSnapshots(status));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load shared links');
    } finally {
      setLoading(false);
    }
  }, [listTeamSnapshots, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleRevoke = async (id: string) => {
    setRevokingId(id);
    try {
      await revokeSnapshot(id);
      setConfirmId(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to revoke the link');
    } finally {
      setRevokingId(null);
    }
  };

  const now = Date.now();
  const rows = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const all = data?.snapshots ?? [];
    if (!q) return all;
    return all.filter((s) =>
      `${s.script_name ?? ''} ${s.created_by_name ?? 'service'}`.toLowerCase().includes(q),
    );
  }, [data, filter]);

  const activeCount = useMemo(
    () => (data?.snapshots ?? []).filter((s) => rowStatus(s, now) === 'active').length,
    [data, now],
  );

  const openReport = async (url: string) => {
    try {
      await openR2Url(url);
    } catch {
      setError('Failed to open the report. It may have expired.');
    }
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
        {STATUS_CHIPS.map((c) => (
          <Chip
            key={c.value}
            label={c.label}
            clickable
            size="small"
            color={status === c.value ? 'primary' : 'default'}
            variant={status === c.value ? 'filled' : 'outlined'}
            onClick={() => setStatus(c.value)}
          />
        ))}
        <TextField
          size="small"
          placeholder="Filter by report or creator"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          sx={{ minWidth: 260 }}
        />
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        Links are shown once at creation; this list cannot reopen them. Revoking deletes the copy
        immediately.
      </Typography>
      {error && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      <TableContainer component={Paper} variant="outlined">
        <Table
          size="small"
          sx={{
            tableLayout: 'fixed',
            minWidth: 1120,
            '& .MuiTableCell-root': { px: 1, py: 0.25, fontSize: TYPOGRAPHY.body.size, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' },
          }}
        >
          <colgroup>
            <col /><col style={{ width: 110 }} /><col style={{ width: 175 }} /><col style={{ width: 105 }} /><col style={{ width: 80 }} />
            <col style={{ width: 75 }} /><col style={{ width: 55 }} /><col style={{ width: 65 }} /><col style={{ width: 55 }} />
            <col style={{ width: 175 }} /><col style={{ width: 95 }} />
          </colgroup>
          <TableHead>
            <TableRow>
              {[
                'Report', 'Device', 'Created', 'By', 'Expires', 'Password', 'Video', 'Size', 'Views',
                'Last viewed', 'Status',
              ].map((h) => (
                <TableCell key={h} sx={{ py: 0.5 }}>
                  <strong>{h}</strong>
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                <TableCell colSpan={11}>
                  <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                    <CircularProgress />
                  </Box>
                </TableCell>
              </TableRow>
            ) : rows.length === 0 ? (
              <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                <TableCell colSpan={11} sx={{ textAlign: 'center', py: 4 }}>
                  <Typography variant="body2" color="textSecondary">
                    No shared links
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              rows.map((s) => {
                const st = rowStatus(s, now);
                return (
                  <TableRow key={s.id} sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                    <TableCell>
                      {s.report_url ? (
                        <Link component="button" variant="body2" onClick={() => openReport(s.report_url!)}>
                          {s.script_name || 'Report'}
                        </Link>
                      ) : (
                        s.script_name || '-'
                      )}
                    </TableCell>
                    <TableCell>{s.device_name || '-'}</TableCell>
                    <TableCell>{fmtDate(s.created_at)}</TableCell>
                    <TableCell>{s.created_by ? s.created_by_name || '-' : 'Service'}</TableCell>
                    <TableCell>{expiryText(s, st, now)}</TableCell>
                    <TableCell>
                      {s.has_password ? (
                        <IconButton size="small" disabled sx={{ p: 0.25 }} aria-label="Password protected">
                          <LockIcon fontSize="small" />
                        </IconButton>
                      ) : (
                        '–'
                      )}
                    </TableCell>
                    <TableCell>{s.include_video ? 'yes' : 'no'}</TableCell>
                    <TableCell>{fmtSize(s.size_bytes)}</TableCell>
                    <TableCell>{s.view_count}</TableCell>
                    <TableCell>{fmtDate(s.last_viewed_at)}</TableCell>
                    <TableCell>
                      {s.can_revoke ? (
                        confirmId === s.id ? (
                          <>
                            <Button
                              size="small"
                              variant="contained"
                              disabled={revokingId === s.id}
                              onClick={() => handleRevoke(s.id)}
                              sx={dangerButtonSx(P)}
                            >
                              Confirm revoke
                            </Button>
                            <Button size="small" onClick={() => setConfirmId(null)}>
                              Cancel
                            </Button>
                          </>
                        ) : (
                          <Button size="small" onClick={() => setConfirmId(s.id)} sx={dangerButtonSx(P)}>
                            Revoke
                          </Button>
                        )
                      ) : (
                        <Chip
                          size="small"
                          color={STATUS_COLOR[st]}
                          label={st.charAt(0).toUpperCase() + st.slice(1)}
                          sx={{ height: 20, fontSize: TYPOGRAPHY.caption.size }}
                        />
                      )}
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </TableContainer>
      {data && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
          Active: {activeCount} · {fmtSize(data.quota.used_bytes)} of {fmtSize(data.quota.limit_bytes)} team
          quota
        </Typography>
      )}
    </Box>
  );
};

export default SharedLinksTab;
