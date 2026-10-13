import { Alert, Box, Card, CircularProgress, Link, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography, useMediaQuery, useTheme } from '@mui/material';
import React, { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { Usage, fetchUsage } from './api';

export const UsageTab: React.FC<{ days: number }> = ({ days }) => {
  const P = useAgentChatPalette();
  const theme = useTheme();
  const phone = useMediaQuery(theme.breakpoints.down('sm'));
  const [data, setData] = useState<Usage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    setLoading(true); setError(null);
    fetchUsage(days, ctl.signal)
      .then((d) => { setData(d); })
      .catch((e) => { if (!ctl.signal.aborted) setError(e instanceof Error ? e.message : 'Failed to load usage'); })
      .finally(() => { if (!ctl.signal.aborted) setLoading(false); });
    return () => ctl.abort();
  }, [days]);

  if (loading) return <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress /></Box>;
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!data) return null;

  const decisions = [...data.decisions].sort((a, b) => b.ok + b.fail - (a.ok + a.fail));

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      <Card sx={{ p: 1.75, bgcolor: P.surface }}>
        <Typography sx={{ fontSize: '1rem', fontWeight: 600, mb: 0.5 }}>Token use, cost and credit</Typography>
        <Typography sx={{ fontSize: '0.85rem', color: P.textSecondary }}>
          Requests, tokens, speed, errors, cost and the OpenRouter credit per feature, model, team, user or script now live in{' '}
          <Link component={RouterLink} to="/monitoring/ai-usage">Monitoring → AI usage</Link>.
        </Typography>
      </Card>

      {!phone && (
        <Card sx={{ p: 1.75, bgcolor: P.surface }}>
          <Typography sx={{ fontSize: '1rem', fontWeight: 600, mb: 1 }}>Decisions</Typography>
          {decisions.length === 0 ? <Typography sx={{ fontSize: '0.85rem', color: P.textMuted }}>No decisions recorded in this window.</Typography> : (
            <TableContainer>
              <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 420, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col /><col style={{ width: 80 }} /><col style={{ width: 80 }} /><col style={{ width: 130 }} /></colgroup>
                <TableHead><TableRow>
                  <TableCell>Usage key</TableCell><TableCell align="right">ok</TableCell>
                  <TableCell align="right">fail</TableCell><TableCell align="right">outcome known</TableCell>
                </TableRow></TableHead>
                <TableBody>
                  {decisions.map((d) => (
                    <TableRow key={d.usage_key}>
                      <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{d.usage_key}</TableCell>
                      <TableCell align="right" sx={{ color: P.success }}>{d.ok}</TableCell>
                      <TableCell align="right" sx={{ color: d.fail ? P.error : P.textSecondary }}>{d.fail}</TableCell>
                      <TableCell align="right">{d.outcome_known}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Card>
      )}
      {phone && <Typography sx={{ fontSize: '0.75rem', color: P.textMuted }}>The decisions table is shown on wider screens.</Typography>}
    </Box>
  );
};
