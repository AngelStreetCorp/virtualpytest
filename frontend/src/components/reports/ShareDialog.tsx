/**
 * Explicit share action for a run: creates a sanitized, expiring snapshot and lists the
 * run's existing links so they can be revoked. The token is shown once, inside the link
 * fragment (`#t=`), which browsers never send to a server.
 */

import { ContentCopy as CopyIcon } from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  List,
  ListItem,
  ListItemText,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useState } from 'react';

import { StyledDialog } from '../common/StyledDialog';
import { describeError } from '../../hooks/reports/runManagementApi';
import { useShareMutations, useShareSnapshots } from '../../hooks/reports/useRunManagement';
import {
  REPORT_ROUTES,
  SHARE_TTL_DEFAULT_DAYS,
  SHARE_TTL_MAX_DAYS,
  type RunIdentity,
} from '../../types/reports';
import { formatDateTime } from './status';
import { dangerButtonSx } from '../common/PageChrome';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

/** Absolute share URL with the token in the fragment. */
export const buildShareUrl = (snapshotId: string, token: string): string => {
  // Same proxy-path basename rule as App.tsx (e.g. /pi4).
  const proxy = window.location.pathname.match(/^\/(pi\d+|mac)\//);
  const basename = proxy ? proxy[0].slice(0, -1) : '';
  return `${window.location.origin}${basename}${REPORT_ROUTES.share(snapshotId)}#t=${encodeURIComponent(token)}`;
};

export const clampTtlDays = (raw: number): number => {
  if (!Number.isFinite(raw)) return SHARE_TTL_DEFAULT_DAYS;
  return Math.min(SHARE_TTL_MAX_DAYS, Math.max(1, Math.round(raw)));
};

export interface ShareDialogProps {
  open: boolean;
  identity: RunIdentity;
  onClose: () => void;
}

export const ShareDialog: React.FC<ShareDialogProps> = ({ open, identity, onClose }) => {
  const P = useAgentChatPalette();
  const [ttlDays, setTtlDays] = useState<number>(SHARE_TTL_DEFAULT_DAYS);
  const [link, setLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const snapshots = useShareSnapshots(identity, open);
  const { create, revoke } = useShareMutations();

  const handleCreate = async () => {
    setError(null);
    try {
      const response = await create.mutateAsync({
        run_kind: identity.kind,
        run_id: identity.id,
        ttl_days: clampTtlDays(ttlDays),
      });
      setLink(buildShareUrl(response.snapshot.id, response.token));
    } catch (err) {
      setError(describeError(err));
    }
  };

  const handleRevoke = async (id: string) => {
    setError(null);
    try {
      await revoke.mutateAsync(id);
    } catch (err) {
      setError(describeError(err));
    }
  };

  const handleClose = () => {
    setLink(null);
    setError(null);
    onClose();
  };

  const active = (snapshots.data?.items ?? []).filter(
    (s) => !s.revoked_at && new Date(s.expires_at).getTime() > Date.now(),
  );

  return (
    <StyledDialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Share a read-only snapshot</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Anyone with the link can see the run title, status, counts, durations, labels and test names as
          they are now. Logs, reports, hosts, devices, metadata and AI review are never included.
        </Typography>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <TextField
            size="small"
            type="number"
            label="Expires after (days)"
            value={ttlDays}
            onChange={(event) => setTtlDays(Number(event.target.value))}
            onBlur={() => setTtlDays(clampTtlDays(ttlDays))}
            inputProps={{ min: 1, max: SHARE_TTL_MAX_DAYS }}
            helperText={`1–${SHARE_TTL_MAX_DAYS} days`}
            sx={{ width: 180 }}
          />
          <Button variant="contained" onClick={() => void handleCreate()} disabled={create.isPending}>
            Create link
          </Button>
        </Box>
        {link && (
          <Alert severity="success" sx={{ mt: 2, wordBreak: 'break-all' }}>
            <Typography variant="body2" sx={{ mb: 1 }}>
              Copy this link now — it is shown only once.
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="caption" component="code" data-testid="share-link" sx={{ flex: 1 }}>
                {link}
              </Typography>
              <Tooltip title="Copy">
                <IconButton size="small" onClick={() => void navigator.clipboard?.writeText(link)}>
                  <CopyIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>
          </Alert>
        )}
        {error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {error}
          </Alert>
        )}
        <Typography variant="subtitle2" sx={{ mt: 3 }}>
          Active links
        </Typography>
        {snapshots.isLoading ? (
          <Typography variant="body2" color="text.secondary">
            Loading…
          </Typography>
        ) : snapshots.isError ? (
          <Typography variant="body2" color="error">
            {describeError(snapshots.error)}
          </Typography>
        ) : active.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No active links for this run.
          </Typography>
        ) : (
          <List dense>
            {active.map((snapshot) => (
              <ListItem
                key={snapshot.id}
                secondaryAction={
                  <Button
                    size="small"
                    onClick={() => void handleRevoke(snapshot.id)}
                    disabled={revoke.isPending}
                    sx={dangerButtonSx(P)}
                  >
                    Revoke
                  </Button>
                }
              >
                <ListItemText
                  primary={`Created ${formatDateTime(snapshot.created_at)}`}
                  secondary={`Expires ${formatDateTime(snapshot.expires_at)}`}
                />
              </ListItem>
            ))}
          </List>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Close</Button>
      </DialogActions>
    </StyledDialog>
  );
};
