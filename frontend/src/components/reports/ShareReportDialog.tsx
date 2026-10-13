import { ContentCopy as CopyIcon } from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  IconButton,
  InputAdornment,
  InputLabel,
  MenuItem,
  Select,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useCallback, useEffect, useRef, useState } from 'react';

import {
  useReportSnapshots,
  type CreatedSnapshot,
  type ReportSnapshot,
} from '../../hooks/useReportSnapshots';
import { getServerBaseUrl } from '../../utils/buildUrlUtils';
import { StyledDialog } from '../common/StyledDialog';

interface ShareReportDialogProps {
  open: boolean;
  onClose: () => void;
  scriptResultId: string;
  scriptName: string;
}

const EXPIRY_LABELS: Record<number, string> = {
  3600: '1 hour',
  86400: '1 day',
  604800: '7 days',
  2592000: '30 days',
};
const DEFAULT_CHOICES = [3600, 86400, 604800, 2592000];
const MIN_PASSWORD = 8;

const expiryLabel = (s: number) => EXPIRY_LABELS[s] ?? `${Math.round(s / 3600)} hours`;
const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '-');

const copyText = async (text: string): Promise<boolean> => {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the textarea fallback */
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
};

export const ShareReportDialog: React.FC<ShareReportDialogProps> = ({
  open,
  onClose,
  scriptResultId,
  scriptName,
}) => {
  const { getConfig, createSnapshot, listSnapshots, revokeSnapshot } = useReportSnapshots();

  const [configLoading, setConfigLoading] = useState(true);
  const [choices, setChoices] = useState<number[]>(DEFAULT_CHOICES);
  const [expiresIn, setExpiresIn] = useState<number>(604800);
  const [usePassword, setUsePassword] = useState(false);
  const [password, setPassword] = useState('');
  const [includeVideo, setIncludeVideo] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedSnapshot | null>(null);
  const [copied, setCopied] = useState('');
  const [snapshotsLoading, setSnapshotsLoading] = useState(false);
  const [snapshots, setSnapshots] = useState<ReportSnapshot[]>([]);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  // Async deps live in refs so the reset-on-open effect only re-runs on open/id changes.
  const hooksRef = useRef({ getConfig, listSnapshots });
  hooksRef.current = { getConfig, listSnapshots };

  const refreshList = useCallback(async (id: string) => {
    setSnapshotsLoading(true);
    try {
      setSnapshots(await hooksRef.current.listSnapshots(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load links');
    } finally {
      setSnapshotsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setCreated(null);
    setError(null);
    setUsePassword(false);
    setPassword('');
    setIncludeVideo(true);
    setConfirmId(null);
    setCopied('');
    setSnapshots([]);
    setConfigLoading(true);
    hooksRef.current
      .getConfig()
      .then((cfg) => {
        if (cancelled) return;
        if (cfg.expiry_choices?.length) setChoices(cfg.expiry_choices);
        setExpiresIn(cfg.default_expires_in);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load sharing settings');
      })
      .finally(() => {
        if (!cancelled) setConfigLoading(false);
      });
    refreshList(scriptResultId);
    return () => {
      cancelled = true;
    };
  }, [open, scriptResultId, refreshList]);

  const passwordInvalid = usePassword && password.length < MIN_PASSWORD;

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      const res = await createSnapshot({
        script_result_id: scriptResultId,
        expires_in: expiresIn,
        include_video: includeVideo,
        ...(usePassword ? { password } : {}),
      });
      setCreated(res);
      refreshList(scriptResultId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create link');
    } finally {
      setCreating(false);
    }
  };

  const handleCopy = async (key: string, text: string) => {
    const ok = await copyText(text);
    setCopied(ok ? key : '');
    if (!ok) setError('Could not copy automatically. Select the text and copy it manually.');
  };

  const handleRevoke = async (id: string) => {
    setRevokingId(id);
    setError(null);
    try {
      await revokeSnapshot(id);
      setConfirmId(null);
      await refreshList(scriptResultId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to revoke link');
    } finally {
      setRevokingId(null);
    }
  };

  // The link must reach the server that built the snapshot (only its storage holds the copy),
  // which is the selected server, not necessarily the page's own origin.
  const serverBase = getServerBaseUrl();
  const origin = /^https?:\/\//.test(serverBase) ? serverBase.replace(/\/+$/, '') : window.location.origin;
  const link = created ? origin + created.path : '';
  const deleteLink = created ? origin + created.delete_path : '';

  const readOnlyField = (key: string, label: string, value: string) => (
    <TextField
      label={label}
      value={value}
      fullWidth
      size="small"
      InputProps={{
        readOnly: true,
        endAdornment: (
          <InputAdornment position="end">
            <Tooltip title={copied === key ? 'Copied' : 'Copy'}>
              <IconButton size="small" onClick={() => handleCopy(key, value)}>
                <CopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </InputAdornment>
        ),
      }}
      onFocus={(e) => e.target.select()}
    />
  );

  return (
    <StyledDialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Share report: {scriptName}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" sx={{ mb: 2 }}>
          Anyone with the link can view this report (screenshots, verification images, video)
          without an account until it expires. Typed values (text, PIN, passwords) are masked; check
          the report before sharing.
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {configLoading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
            <CircularProgress size={24} />
          </Box>
        ) : created ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {readOnlyField('link', 'Share link', link)}
            <Typography variant="body2" color="text.secondary">
              Expires {fmt(created.expires_at)}
            </Typography>
            {readOnlyField('delete', 'Delete link', deleteLink)}
            <Typography variant="caption" color="text.secondary">
              Keep this to revoke the link without logging in. It is shown only once.
            </Typography>
          </Box>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            <FormControl size="small" fullWidth>
              <InputLabel id="share-expiry-label">Expires after</InputLabel>
              <Select
                labelId="share-expiry-label"
                label="Expires after"
                value={expiresIn}
                onChange={(e) => setExpiresIn(Number(e.target.value))}
              >
                {choices.map((s) => (
                  <MenuItem key={s} value={s}>
                    {expiryLabel(s)}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControlLabel
              control={
                <Switch checked={usePassword} onChange={(e) => setUsePassword(e.target.checked)} />
              }
              label="Protect with a password"
            />
            {usePassword && (
              <TextField
                label="Password"
                type="password"
                size="small"
                fullWidth
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                error={passwordInvalid && password.length > 0}
                helperText={`At least ${MIN_PASSWORD} characters`}
                autoComplete="new-password"
              />
            )}
            <FormControlLabel
              control={
                <Switch checked={includeVideo} onChange={(e) => setIncludeVideo(e.target.checked)} />
              }
              label="Include video"
            />
          </Box>
        )}

        <Typography variant="subtitle2" sx={{ mt: 3, mb: 1 }}>
          Active links for this report
        </Typography>
        {snapshotsLoading ? (
          <CircularProgress size={20} />
        ) : snapshots.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No active links.
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {snapshots.map((s) => (
              <Box
                key={s.id}
                sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}
              >
                <Typography variant="body2" sx={{ flex: 1, minWidth: 220 }}>
                  Created {fmt(s.created_at)}, expires {fmt(s.expires_at)}, password{' '}
                  {s.has_password ? 'yes' : 'no'}, {s.view_count} view{s.view_count === 1 ? '' : 's'}
                </Typography>
                {confirmId === s.id ? (
                  <>
                    <Button
                      size="small"
                      color="error"
                      variant="contained"
                      disabled={revokingId === s.id}
                      onClick={() => handleRevoke(s.id)}
                    >
                      Confirm revoke
                    </Button>
                    <Button size="small" onClick={() => setConfirmId(null)}>
                      Cancel
                    </Button>
                  </>
                ) : (
                  <Button size="small" color="error" onClick={() => setConfirmId(s.id)}>
                    Revoke
                  </Button>
                )}
              </Box>
            ))}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
        {!created && (
          <Button
            variant="contained"
            onClick={handleCreate}
            disabled={configLoading || creating || passwordInvalid}
            startIcon={creating ? <CircularProgress size={16} /> : undefined}
          >
            {creating ? 'Creating...' : 'Create link'}
          </Button>
        )}
        {created && (
          <Button variant="outlined" onClick={() => setCreated(null)}>
            Create another
          </Button>
        )}
      </DialogActions>
    </StyledDialog>
  );
};

export default ShareReportDialog;
