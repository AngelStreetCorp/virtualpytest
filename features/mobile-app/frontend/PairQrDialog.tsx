/**
 * The pairing dialog for one slot (features/mobile-app, docs/tasks/TASK-17): a code big enough
 * for a phone camera, renewed before it expires, and the same pairing as text for a camera that
 * will not cooperate.
 *
 * Its own file because two places open it: the "Mobile app & phones" page, and a phone slot's
 * card on the REC page, where a slot with no phone on it offers pairing instead of an empty
 * player.
 *
 * Mounted only while it is open, so a token is minted on opening rather than held (and
 * continuously renewed) for every free slot on a page. The caller unmounts it as soon as the
 * slot stops being pairable — a scan, or another phone taking the slot — so a spent code is
 * never left on screen.
 */
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  IconButton,
  LinearProgress,
  InputAdornment,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import { ContentCopy as CopyIcon } from '@mui/icons-material';
import React, { useEffect, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';

import { buildPairingCode, type PairingResponse } from './hooks/useMobileApp';

export function PairQrDialog({
  hostName,
  deviceId,
  createPairing,
  onClose,
}: {
  hostName: string;
  deviceId: string;
  createPairing: (hostName: string, deviceId: string) => Promise<PairingResponse>;
  onClose: () => void;
}) {
  const [pairing, setPairing] = useState<PairingResponse | null>(null);
  const [codeCopied, setCodeCopied] = useState(false);
  const [qrError, setQrError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());

  const copyCode = async () => {
    try {
      if (!pairing) return;
      await navigator.clipboard.writeText(buildPairingCode(pairing));
      setCodeCopied(true);
      window.setTimeout(() => setCodeCopied(false), 1500);
    } catch {
      /* clipboard blocked (http origin, denied permission) — the field is selectable anyway */
    }
  };

  const expiresAtMs = pairing ? Date.parse(pairing.expires_at) : null;

  // Mint a token on open, and again once the current one is within 10s of expiring, so the
  // code on screen is always one that still works.
  useEffect(() => {
    let cancelled = false;
    const remaining = expiresAtMs ? expiresAtMs - Date.now() : 0;
    if (expiresAtMs && remaining > 10_000) return;
    createPairing(hostName, deviceId)
      .then((p) => {
        if (!cancelled) setPairing(p);
      })
      .catch((e) => {
        if (!cancelled) setQrError(e instanceof Error ? e.message : 'failed to create pairing');
      });
    return () => {
      cancelled = true;
    };
    // createPairing is stable (useCallback in the hook); `now` is what re-triggers the renewal check.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostName, deviceId, expiresAtMs, now]);

  // Ticks both the visible countdown and the renewal check above.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const remainingS = pairing
    ? Math.max(0, Math.floor((Date.parse(pairing.expires_at) - now) / 1000))
    : 0;
  const countdown = `${Math.floor(remainingS / 60)}:${String(remainingS % 60).padStart(2, '0')}`;
  // The QR carries the pairing CODE, not the payload. The payload made this a 65-module
  // symbol — twice the modules of the download QR — which is why it needed roughly double the
  // size to scan. The code is 29 modules, so 288px is ~10 screen pixels per module.
  const pairingCode = pairing ? buildPairingCode(pairing) : '';

  return (
    <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
        {qrError ? (
          <Alert severity="error" sx={{ width: '100%' }}>
            {qrError}
          </Alert>
        ) : !pairing ? (
          <CircularProgress size={28} sx={{ my: 4 }} />
        ) : (
          <>
            {/* Level M is affordable now the symbol is small: the extra redundancy helps
                against glare and moiré off a screen without costing meaningful density. */}
            <QRCodeSVG value={pairingCode} size={288} level="M" />
            <Typography variant="body2" color="text.secondary" textAlign="center">
              Pairing {deviceId} on {hostName} · scan it with the app&apos;s &quot;Scan pairing
              QR&quot; button · expires in {countdown}
            </Typography>

            {/* The dialog is watching the slot once a second and closes itself the moment the
                phone is on it. Saying so — and showing something moving — is the difference
                between "nothing happened" and "it is working on it" in the second after a
                scan. */}
            <Box sx={{ width: '100%' }}>
              <LinearProgress sx={{ borderRadius: 1 }} />
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: 'block', mt: 0.5, textAlign: 'center' }}
              >
                Waiting for the phone to connect…
              </Typography>
            </Box>

            {/* Same pairing, by hand — for a camera that will not read the code, or a phone
                being set up with no line of sight to this screen. The app derives everything
                else from the server it is already configured with. */}
            <Box sx={{ width: '100%', mt: 1 }}>
              <Typography variant="caption" color="text.secondary">
                Or type this into the app — &quot;Enter pairing code&quot;
              </Typography>
              <TextField
                fullWidth
                size="small"
                value={pairingCode}
                InputProps={{
                  readOnly: true,
                  sx: { fontFamily: 'monospace', fontSize: '0.75rem' },
                  endAdornment: (
                    <InputAdornment position="end">
                      <Tooltip title={codeCopied ? 'Copied' : 'Copy'}>
                        <IconButton size="small" onClick={copyCode}>
                          <CopyIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </InputAdornment>
                  ),
                }}
                onFocus={(e: React.FocusEvent<HTMLInputElement>) => e.target.select()}
              />
            </Box>
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

export default PairQrDialog;
