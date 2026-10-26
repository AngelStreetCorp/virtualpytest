import { Box, Dialog } from '@mui/material';
import React, { useEffect, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useHostData } from '../../hooks/useHostManager';
import { useI18n } from '../../i18n/useI18n';
import { ensureHostSessionOnce, isGatedHostPath } from '../../utils/buildUrlUtils';
import { matchRunFrameSrc } from '../../utils/matchRunFrame';

/**
 * The frame of one Localize run, shown in-app: a small thumbnail, click for a dialog.
 * Hosts delete old frames, so a failed load shows a plain placeholder instead of a broken image.
 */
export const MatchRunFrame: React.FC<{ frameUrl: string | null; hostName: string }> = ({ frameUrl, hostName }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { getAllHosts } = useHostData();
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const host = getAllHosts().find((h) => h.host_name === hostName);
  const src = frameUrl ? matchRunFrameSrc(host, frameUrl) : '';
  // The host-session cookie must exist BEFORE the image is requested. Without it the proxy
  // gate answers 401, the <img> fires its error handler and the frame is declared "no
  // longer on the host" even when the capture is right there — and the global retry then
  // asks for the same file a second time (BUG-0779).
  // A failed mint (the host did not answer) used to leave the grey placeholder for ever:
  // it now shows the error state and allows ONE retry (BUG-0779 review).
  const gated = !!src && isGatedHostPath(src);
  const [session, setSession] = useState<'pending' | 'ready' | 'failed'>('pending');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setFailed(false);
    setAttempt(0);
  }, [src]);

  useEffect(() => {
    if (!src || !gated) {
      setSession('pending');
      return undefined;
    }
    let cancelled = false;
    setSession('pending');
    ensureHostSessionOnce(src)
      .then((ok) => { if (!cancelled) setSession(ok ? 'ready' : 'failed'); })
      .catch(() => { if (!cancelled) setSession('failed'); });
    return () => { cancelled = true; };
  }, [src, gated, attempt]);

  const ready = !!src && (gated ? session === 'ready' : true);

  if (!frameUrl) return <span style={{ color: P.textMuted }}>—</span>;
  if (gated && session === 'failed') {
    return (
      <Box component="span" sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
        {t('Screenshot no longer on the host')}
        {attempt < 1 && (
          <Box
            component="button"
            type="button"
            onClick={(e: React.MouseEvent) => { e.stopPropagation(); setAttempt(1); }}
            sx={{ ml: 0.75, p: 0, border: 'none', background: 'none', color: P.accent, cursor: 'pointer', font: 'inherit' }}
          >
            {t('Retry')}
          </Box>
        )}
      </Box>
    );
  }
  if (failed) {
    return <Box component="span" sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{t('Screenshot no longer on the host')}</Box>;
  }
  if (!ready) {
    // Same footprint as the thumbnail, so the row does not jump when the frame arrives.
    return <Box sx={{ width: 64, height: 36, flex: 'none', borderRadius: 0.5, border: `1px solid ${P.borderColor}`, bgcolor: P.hoverBg }} />;
  }
  return (
    <>
      <Box
        component="img"
        src={src}
        alt={t('Screenshot')}
        loading="lazy"
        onError={() => setFailed(true)}
        onClick={(e: React.MouseEvent) => {
          e.stopPropagation();
          setOpen(true);
        }}
        sx={{ height: 36, borderRadius: 0.5, border: `1px solid ${P.borderColor}`, cursor: 'zoom-in', display: 'block' }}
      />
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="lg">
        <Box component="img" src={src} alt={t('Screenshot')} onError={() => { setOpen(false); setFailed(true); }} sx={{ maxWidth: '100%', display: 'block' }} />
      </Dialog>
    </>
  );
};
