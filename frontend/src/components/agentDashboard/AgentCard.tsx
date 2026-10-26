import { Box, Button, Card, Typography } from '@mui/material';
import React from 'react';
import { useNavigate } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AgentOverview, Health, fmtAgo, fmtTokens } from './api';
import { TYPOGRAPHY } from '../../constants/typography';

export const useHealthColor = () => {
  const P = useAgentChatPalette();
  return (h: Health) => ({ ok: P.success, warn: P.warning, error: P.error, idle: P.textMuted })[h];
};
const HEALTH_WORD: Record<Health, string> = { ok: 'healthy', warn: 'some errors', error: 'failing', idle: 'idle' };

export const AgentCard: React.FC<{ agent: AgentOverview; onLogs: () => void }> = ({ agent, onLogs }) => {
  const P = useAgentChatPalette();
  const navigate = useNavigate();
  const healthColor = useHealthColor();
  const c = healthColor(agent.health);
  const s = agent.stats;
  return (
    <Card sx={{ p: 1.75, bgcolor: P.surface, display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 1 }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography noWrap sx={{ fontSize: TYPOGRAPHY.navbarItem.size, fontWeight: 600 }}>{agent.name}</Typography>
          {agent.role && <Typography noWrap sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{agent.role}</Typography>}
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexShrink: 0 }}>
          <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: c }} />
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: c }}>{HEALTH_WORD[agent.health]}</Typography>
        </Box>
      </Box>

      <Box sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textSecondary, minHeight: 20 }}>
        {agent.now.length > 0 ? (
          agent.now.slice(0, 3).map((n, i) => (
            <Typography key={i} noWrap sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary }} title={n.summary}>
              <Box component="span" sx={{ color: P.accentText, fontWeight: 600 }}>Now: </Box>{n.summary}
            </Typography>
          ))
        ) : (
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>
            Now: idle (last {agent.last_activity ? fmtAgo(agent.last_activity) : 'activity: none in window'})
          </Typography>
        )}
      </Box>

      <Typography sx={{ fontSize: TYPOGRAPHY.body.size }}>
        {s.calls} calls ·{' '}
        <Box component="span" sx={{ color: s.errors ? P.error : P.textSecondary }}>{s.errors} errors</Box>
        {s.fallbacks > 0 && <Box component="span" sx={{ color: P.textSecondary }}> · {s.fallbacks} fallbacks</Box>}
      </Typography>
      <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textSecondary }}>
        tokens {fmtTokens(s.tokens_in)} in / {fmtTokens(s.tokens_out)} out
      </Typography>
      {agent.model && (
        <Typography noWrap sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }} title={agent.model}>
          model: <Box component="span" sx={{ fontFamily: 'monospace' }}>{agent.model}</Box>
        </Typography>
      )}

      {agent.parts.length > 0 && (
        <Box sx={{ borderTop: `1px solid ${P.borderColor}`, pt: 0.75 }}>
          {agent.parts.map((p) => (
            <Box key={p.key} sx={{ display: 'flex', justifyContent: 'space-between', gap: 1, fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
              <Box component="span" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.label}</Box>
              <Box component="span" sx={{ flexShrink: 0, color: p.errors ? P.error : P.textMuted }}>
                {p.calls}{p.errors ? ` · ${p.errors} err` : ''}
              </Box>
            </Box>
          ))}
        </Box>
      )}

      {agent.feedback && (agent.feedback.count || agent.feedback.up || agent.feedback.down || agent.feedback.rating != null) ? (
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
          feedback:{' '}
          {agent.feedback.rating != null && `${Number(agent.feedback.rating).toFixed(1)}/5`}
          {agent.feedback.count ? ` (${agent.feedback.count})` : ''}
          {agent.feedback.up != null || agent.feedback.down != null ? ` ${agent.feedback.up ?? 0} up / ${agent.feedback.down ?? 0} down` : ''}
        </Typography>
      ) : null}

      <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mt: 'auto', pt: 0.5 }}>
        <Button size="small" variant="outlined" onClick={onLogs}>Logs</Button>
        {agent.links.map((l) => (
          <Button key={l.to + l.label} size="small" variant="text" onClick={() => navigate(l.to)}>{l.label}</Button>
        ))}
      </Box>
    </Card>
  );
};
