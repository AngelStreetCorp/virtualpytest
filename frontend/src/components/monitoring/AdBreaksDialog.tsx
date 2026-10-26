import { Box, Button, CircularProgress, DialogContent, DialogTitle, IconButton, Typography } from '@mui/material';
import React, { useCallback, useEffect, useState } from 'react';

import { AppIcon } from '../../constants/icons';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { api } from '../../utils/apiClient';
import { buildDeviceAdsFileUrl, buildHostServerUrl } from '../../utils/buildUrlUtils';
import { neutralButtonSx } from '../common/PageChrome';
import { StyledDialog } from '../common/StyledDialog';

/**
 * The commercial breaks ad_meter found on one device in the last 24 h, each with the thumbnails it kept while the break ran,
 * so a person can see what the meter called an ad and say "not an ad" (owner, 2026-10-26). The thumbnails are the evidence:
 * a break whose pictures are programme is a detector mistake, and the correction teaches the meter.
 */
export interface AdBreak {
  id: string;
  start: number;
  end: number;
  duration_s: number;
  kind: 'new' | 'confirmed' | 'suspect_overlong' | string;
  confidence?: number;
  opened_by?: string;
  thumbs: string[];
  not_ad: boolean;
}

interface AdBreaksDialogProps {
  open: boolean;
  onClose: () => void;
  host: { host_name: string; server_url?: string } & Record<string, unknown>;
  deviceId: string;
  deviceName?: string;
}

const clock = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
// round first: 299.6 s is 5:00, not 4:60
const span = (s: number) => {
  const r = Math.round(s);
  return `${Math.floor(r / 60)}:${String(r % 60).padStart(2, '0')}`;
};

export const AdBreaksDialog: React.FC<AdBreaksDialogProps> = ({ open, onClose, host, deviceId, deviceName }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [breaks, setBreaks] = useState<AdBreak[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await api.post<{ success?: boolean; breaks?: AdBreak[]; error?: string }>(
        buildHostServerUrl(host, '/server/monitoring/ad-breaks'),
        { host_name: host.host_name, device_id: deviceId, hours: 24 },
      );
      if (res?.success === false) throw new Error(res.error || 'failed');
      setBreaks(res?.breaks ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBreaks([]);
    }
  }, [host, deviceId]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const markNotAd = async (b: AdBreak) => {
    setPending(b.id);
    try {
      await api.post(buildHostServerUrl(host, '/server/monitoring/ad-breaks/not-ad'), {
        host_name: host.host_name,
        device_id: deviceId,
        break_id: b.id,
      });
      setBreaks((list) => (list ?? []).map((x) => (x.id === b.id ? { ...x, not_ad: true } : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  };

  const counted = (breaks ?? []).filter((b) => !b.not_ad && b.kind !== 'suspect_overlong');
  const adSeconds = counted.reduce((sum, b) => sum + (b.duration_s || 0), 0);
  const kindLabel = (k: string) =>
    k === 'confirmed' ? t('seen before') : k === 'new' ? t('new') : k === 'suspect_overlong' ? t('too long, not counted') : k;
  const kindColour = (k: string) => (k === 'confirmed' ? P.error : k === 'new' ? P.warning : P.textMuted);

  return (
    <StyledDialog open={open} onClose={onClose} maxWidth="lg" fullWidth data-testid="ad-breaks-dialog">
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, color: P.textPrimary }}>
        <Box sx={{ flex: 1 }}>
          <Typography sx={{ fontSize: TYPOGRAPHY.pageTitle.size, fontWeight: 700 }}>{t('Ad breaks, last 24 h')}</Typography>
          <Typography variant="caption" sx={{ color: P.textSecondary }}>
            {deviceName ? `${deviceName} · ` : ''}
            {breaks == null
              ? '—'
              : t('{n} breaks · {time} of ads', { n: counted.length, time: span(adSeconds) })}
          </Typography>
        </Box>
        <IconButton onClick={load} aria-label={t('Refresh')} title={t('Refresh')}>
          <AppIcon name="refresh" />
        </IconButton>
        <IconButton onClick={onClose} aria-label={t('Close')} title={t('Close')}>
          <AppIcon name="close" />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        {breaks == null && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={28} />
          </Box>
        )}
        {error && (
          <Typography sx={{ color: P.error, mb: 1 }} data-testid="ad-breaks-error">
            {error}
          </Typography>
        )}
        {breaks != null && breaks.length === 0 && !error && (
          <Typography sx={{ color: P.textSecondary, py: 2 }}>{t('No ad break in the last 24 h.')}</Typography>
        )}
        {(breaks ?? []).map((b) => (
          <Box
            key={b.id}
            data-testid="ad-break-row"
            sx={{
              display: 'flex',
              gap: 2,
              alignItems: 'center',
              py: 1.25,
              borderBottom: `1px solid ${P.borderColor}`,
              opacity: b.not_ad ? 0.5 : 1,
            }}
          >
            <Box sx={{ width: 210, flex: 'none' }}>
              <Typography sx={{ fontWeight: 700, color: P.textPrimary, whiteSpace: 'nowrap' }}>{`${clock(b.start)} – ${clock(b.end)}`}</Typography>
              <Typography variant="caption" sx={{ color: P.textSecondary, display: 'block' }}>
                {span(b.duration_s)}
              </Typography>
              <Typography variant="caption" sx={{ color: b.not_ad ? P.textMuted : kindColour(b.kind), fontWeight: 700 }}>
                {b.not_ad ? t('marked not an ad') : kindLabel(b.kind)}
              </Typography>
            </Box>
            <Box sx={{ flex: 1, display: 'flex', gap: 0.75, overflowX: 'auto', minWidth: 0 }}>
              {b.thumbs.length === 0 && (
                <Typography variant="caption" sx={{ color: P.textMuted }}>
                  {t('No picture kept for this break (recorded before pictures were kept).')}
                </Typography>
              )}
              {b.thumbs.map((name) => (
                <Box
                  key={name}
                  component="img"
                  src={buildDeviceAdsFileUrl(host, deviceId, name)}
                  alt=""
                  loading="lazy"
                  data-testid="ad-break-thumb"
                  sx={{ height: 72, width: 'auto', borderRadius: 0.5, flex: 'none', background: P.surface }}
                />
              ))}
            </Box>
            <Box sx={{ flex: 'none' }}>
              {!b.not_ad && b.kind !== 'suspect_overlong' && (
                <Button
                  size="small"
                  onClick={() => markNotAd(b)}
                  disabled={pending === b.id}
                  sx={neutralButtonSx(P)}
                  data-testid="ad-break-not-ad"
                >
                  {t('Not an ad')}
                </Button>
              )}
            </Box>
          </Box>
        ))}
      </DialogContent>
    </StyledDialog>
  );
};

export default AdBreaksDialog;
