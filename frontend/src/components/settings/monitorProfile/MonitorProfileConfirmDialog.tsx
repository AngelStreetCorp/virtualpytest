import React from 'react';
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Typography } from '@mui/material';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { goldButtonSx } from '../../common/PageChrome';
import { profileTitle, type MonitorProfileInfo, type ProfileChangePlan } from './plan';
import { TYPOGRAPHY } from '../../../constants/typography';

interface Props {
  open: boolean;
  hostName: string;
  plan: ProfileChangePlan;
  profiles: MonitorProfileInfo[];
  saving?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const unitName = (s: string) => `vpt-monitor-${s}`;

export const MonitorProfileConfirmDialog: React.FC<Props> = ({ open, hostName, plan, profiles, saving, onConfirm, onCancel }) => {
  const P = useAgentChatPalette();
  const mono = { fontFamily: 'monospace', fontSize: TYPOGRAPHY.body.size } as const;
  const label = (n: string) => (n ? profileTitle(n, profiles) : 'Default');
  const units = [...plan.restarts.map(unitName), ...plan.restartsHost, ...(plan.restartsStream ? ['vpt-stream'] : [])];
  return (
    <Dialog open={open} onClose={onCancel} maxWidth="sm" fullWidth data-testid="monitor-profile-confirm">
      <DialogTitle>Change the monitoring profile?</DialogTitle>
      <DialogContent>
        <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 1, mb: 2 }}>
          {plan.hostDefault && (
            <Box sx={{ px: 1.5, py: 1, borderBottom: plan.devices.length ? `1px solid ${P.borderColor}` : 0 }}>
              <Typography variant="body2">
                <b>Host default</b>: {label(plan.hostDefault.from)} → <b>{label(plan.hostDefault.to)}</b>
              </Typography>
            </Box>
          )}
          {plan.devices.map((d, i) => (
            <Box key={d.key} sx={{ px: 1.5, py: 1, borderBottom: i < plan.devices.length - 1 ? `1px solid ${P.borderColor}` : 0 }}>
              <Typography variant="body2">
                <span style={mono}>{d.key.toLowerCase()}</span>: {label(d.from)} → <b>{label(d.to)}</b>
              </Typography>
            </Box>
          ))}
        </Box>

        {units.length > 0 ? (
          <>
            <Typography variant="body2" sx={{ mb: 1 }}>
              Restarts on <b>{hostName}</b>: {units.map((u, i) => (
                <React.Fragment key={u}>{i > 0 && ', '}<span style={mono}>{u}</span></React.Fragment>
              ))}
            </Typography>
            <Alert severity="warning" sx={{ mb: 1.5 }}>
              Monitoring of <b>all devices on this host</b> pauses for a few seconds while the services restart. Open incidents may
              resolve and reopen.
              {plan.restartsStream && <> The <b>video of every device on this host</b> also drops for a few seconds (the stream restarts).</>}
            </Alert>
          </>
        ) : (
          <Alert severity="info" sx={{ mb: 1.5 }}>No monitor service needs a restart for this change.</Alert>
        )}

        {plan.notRunning.length > 0 && (
          <Alert severity="info" sx={{ mb: 1.5 }}>
            {plan.notRunning.map((s) => unitName(s)).join(', ')} {plan.notRunning.length > 1 ? 'are' : 'is'} not running on this host
            (a lite host keeps {plan.notRunning.length > 1 ? 'them' : 'it'} off), so {plan.notRunning.length > 1 ? 'they are' : 'it is'} left
            alone and picks the profile up only when started.
          </Alert>
        )}

        {plan.adds.length > 0 && (
          <Box>
            <Typography variant="caption" sx={{ color: P.textMuted }}>What the new profile adds</Typography>
            {plan.adds.map((p) => (
              <Typography key={p.name} variant="body2" sx={{ mt: 0.5 }}>
                <b>{p.title}</b>: {p.cost}
              </Typography>
            ))}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel} disabled={saving}>Cancel</Button>
        <Button variant="contained" sx={goldButtonSx(P)} onClick={onConfirm} disabled={saving}>
          {units.length ? 'Save and restart' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
