/**
 * Atlas Companion (TASK-126): the real app page Atlas and the user look at together.
 * A same-origin iframe of `path?params&embed=1`; the chat reads its URL back so Atlas knows
 * what is shown. The iframe stays mounted while hidden (scroll and open rows survive).
 */
import React, { useEffect, useRef } from 'react';
import { Box, FormControlLabel, IconButton, Switch, Tooltip, Typography, Button, Chip } from '@mui/material';

import { AppIcon } from '../../constants/icons';
import { Palette } from '../../constants/themeEngine';
import { TYPOGRAPHY } from '../../constants/typography';
import useI18n from '../../i18n/useI18n';
import { neutralButtonSx, primaryButtonSx } from '../common/PageChrome';

export interface CompanionTarget {
  page: string;
  name: string;
  path: string;
  params: Record<string, string>;
  title?: string;
  /** Bumps on every update from Atlas so the iframe reloads even for the same URL. */
  rev: number;
}

export type CompanionMode = 'ask' | 'auto';
const MODE_KEY = 'virtualpytest:atlas-companion';

export const loadCompanionMode = (): CompanionMode => {
  try {
    return localStorage.getItem(MODE_KEY) === 'auto' ? 'auto' : 'ask';
  } catch {
    return 'ask';
  }
};

export const saveCompanionMode = (mode: CompanionMode): void => {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch {
    /* storage can be blocked; the choice then lasts for this tab only */
  }
};

const query = (params: Record<string, string>, embed: boolean): string => {
  const q = new URLSearchParams(params);
  if (embed) q.set('embed', '1');
  const s = q.toString();
  return s ? `?${s}` : '';
};

/** Path + filters, with or without embed=1. */
export const companionHref = (c: Pick<CompanionTarget, 'path' | 'params'>, embed = false): string =>
  `${c.path}${query(c.params, embed)}`;

/** `Companion: Test Reports — host=vpt-pi4, device=web_tv` (what the chat sends with each message). */
export const describeCompanion = (name: string, params: Record<string, string>): string => {
  const kv = Object.entries(params).map(([k, v]) => `${k}=${v}`);
  return `Companion: ${name}${kv.length ? ` — ${kv.join(', ')}` : ''}`;
};

const FilterChips: React.FC<{ params: Record<string, string>; P: Palette }> = ({ params, P }) => (
  <>
    {Object.entries(params).map(([k, v]) => (
      <Chip
        key={k}
        size="small"
        label={v}
        title={k}
        sx={{ fontSize: TYPOGRAPHY.microMeta.size, color: P.textSecondary, bgcolor: P.hoverBg }}
      />
    ))}
  </>
);

/** "Open companion" under Atlas's answer: page name, filter chips, one primary button. */
export const CompanionOffer: React.FC<{
  offer: Pick<CompanionTarget, 'name' | 'params'>;
  P: Palette;
  onOpen: () => void;
}> = ({ offer, P, onOpen }) => {
  const { t } = useI18n();
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', px: 2, py: 1 }}>
      <Button size="small" variant="contained" onClick={onOpen} sx={primaryButtonSx(P)}>
        {t('Open companion')}
      </Button>
      <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>{offer.name}</Typography>
      <FilterChips params={offer.params} P={P} />
    </Box>
  );
};

interface PanelProps {
  target: CompanionTarget;
  visible: boolean;
  width: number;
  mode: CompanionMode;
  P: Palette;
  onModeChange: (mode: CompanionMode) => void;
  onClose: () => void;
  onResizeStart: () => void;
  /** Current iframe URL as `{path, params}` (embed=1 removed), on load and on every change. */
  onUrlChange: (path: string, params: Record<string, string>) => void;
}

export const AtlasCompanion: React.FC<PanelProps> = ({
  target, visible, width, mode, P, onModeChange, onClose, onResizeStart, onUrlChange,
}) => {
  const { t } = useI18n();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const lastUrl = useRef('');
  const src = companionHref(target, true);
  const [current, setCurrent] = React.useState<{ path: string; params: Record<string, string> }>({
    path: target.path,
    params: target.params,
  });

  // Same-origin: read the page's own URL (filters the user changed inside the page included).
  useEffect(() => {
    lastUrl.current = '';
    setCurrent({ path: target.path, params: target.params });
    const read = () => {
      try {
        const loc = frameRef.current?.contentWindow?.location;
        if (!loc || loc.pathname === 'blank' || loc.href === 'about:blank') return;
        const q = new URLSearchParams(loc.search);
        q.delete('embed');
        const params = Object.fromEntries(q.entries());
        const key = `${loc.pathname}?${q.toString()}`;
        if (key === lastUrl.current) return;
        lastUrl.current = key;
        setCurrent({ path: loc.pathname, params });
        onUrlChange(loc.pathname, params);
      } catch {
        /* cross-origin or not ready yet */
      }
    };
    const frame = frameRef.current;
    let win: Window | null = null;
    const detach = () => {
      win?.removeEventListener('popstate', read);
      win?.removeEventListener('hashchange', read);
      win = null;
    };
    // The app is a SPA: in-page navigation uses pushState/replaceState, which fire no event, so wrap them.
    const attach = () => {
      detach();
      try {
        const w = frame?.contentWindow;
        if (!w) return;
        win = w;
        w.addEventListener('popstate', read);
        w.addEventListener('hashchange', read);
        const h = w.history as History & { __companionPatched?: boolean };
        if (!h.__companionPatched) {
          h.__companionPatched = true;
          (['pushState', 'replaceState'] as const).forEach((fn) => {
            const orig = h[fn].bind(h);
            h[fn] = (...args: Parameters<History['pushState']>) => {
              orig(...args);
              read();
            };
          });
        }
      } catch {
        /* cross-origin */
      }
    };
    const onLoad = () => {
      attach();
      read();
    };
    frame?.addEventListener('load', onLoad);
    return () => {
      detach();
      frame?.removeEventListener('load', onLoad);
    };
  }, [src, target.rev]);

  return (
    <Box sx={{ display: visible ? 'flex' : 'none', height: '100%', flexShrink: 0 }}>
      <Box
        onMouseDown={onResizeStart}
        sx={{
          width: 4,
          cursor: 'ew-resize',
          bgcolor: P.borderColor,
          flexShrink: 0,
          '&:hover, &:active': { bgcolor: P.accent },
        }}
      />
      <Box
        sx={{
          width,
          minWidth: width,
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          bgcolor: P.sidebarBg,
          overflow: 'hidden',
        }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            px: 1.5,
            py: 0.75,
            flexWrap: 'wrap',
            borderBottom: '1px solid',
            borderColor: P.borderColor,
            flexShrink: 0,
          }}
        >
          <Typography sx={{ fontSize: TYPOGRAPHY.cardTitle.size, fontWeight: TYPOGRAPHY.cardTitle.weight, color: P.textPrimary }}>
            {target.name}
          </Typography>
          <FilterChips params={current.params} P={P} />
          <Box sx={{ flex: 1 }} />
          <Tooltip title={t('Open pages without asking')}>
            <FormControlLabel
              sx={{ mx: 0, '& .MuiFormControlLabel-label': { fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary } }}
              control={
                <Switch
                  size="small"
                  checked={mode === 'auto'}
                  onChange={(_e, on) => onModeChange(on ? 'auto' : 'ask')}
                />
              }
              label={t('Auto-open')}
            />
          </Tooltip>
          <Tooltip title={t('Open full page')}>
            <IconButton
              size="small"
              component="a"
              href={companionHref(current)}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={t('Open full page')}
              sx={neutralButtonSx(P)}
            >
              <AppIcon name="link" />
            </IconButton>
          </Tooltip>
          <Tooltip title={t('Hide companion')}>
            <IconButton size="small" onClick={onClose} aria-label={t('Hide companion')} sx={neutralButtonSx(P)}>
              <AppIcon name="close" />
            </IconButton>
          </Tooltip>
        </Box>
        <Box
          component="iframe"
          ref={frameRef}
          key={target.rev}
          src={src}
          title={target.name}
          sx={{ flex: 1, width: '100%', border: 0, bgcolor: P.background }}
        />
      </Box>
    </Box>
  );
};
