import { Box, Dialog, DialogContent, DialogTitle, FormControl, IconButton, InputLabel, MenuItem, Select, Typography } from '@mui/material';
import type { SelectChangeEvent } from '@mui/material';
import { ChevronLeft, ChevronRight, Close } from '@mui/icons-material';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import CategoryChips, { useCategoryCounts, useCategoryLabel } from './CategoryChips';
import { readHashParam, sortAlphabetical, writeHashParams } from './docsFilter';
import { TYPOGRAPHY } from '../../constants/typography';

/**
 * The Screenshots docs page: category chips, a dropdown that opens one screenshot, and a grid of thumbnails.
 *
 * Data: docs/screenshots/screenshots.json (display order = file order, `categories` = key -> label in chip
 * order). It is the same file scripts/gen_readme_screenshots.py turns into the README; frontend/scripts/copy-docs.sh
 * copies it to /docs/screenshots/screenshots.json at build time. Images: /screenshot/<file>.thumb.webp (640 px,
 * the grid) and /screenshot/<file>.webp (the lightbox).
 *
 * Weight: only the thumbnails of the current filter are in the DOM (lazy-loaded); the full image is fetched
 * when the lightbox opens. Filter and open screenshot live in the URL hash (#c=<cat>&s=<id>).
 */

interface Shot {
  id: string;
  title: string;
  file: string;
  categories: string[];
  alt?: string;
}
interface ShotData {
  categories: Record<string, string>;
  screenshots: Shot[];
}

const DATA_URL = '/docs/screenshots/screenshots.json';
const thumbSrc = (s: Shot) => `/screenshot/${s.file}.thumb.webp`;
const fullSrc = (s: Shot) => `/screenshot/${s.file}.webp`;
const idFromHash = () => readHashParam('s');
const catFromHash = () => readHashParam('c');

const ScreenshotGallery: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [data, setData] = useState<ShotData | null>(null);
  const [failed, setFailed] = useState(false);
  const [category, setCategory] = useState<string | null>(catFromHash);
  const [openId, setOpenId] = useState<string | null>(idFromHash);
  const tiles = useRef<Map<string, HTMLElement>>(new Map());

  useEffect(() => {
    let cancelled = false;
    fetch(DATA_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: ShotData) => !cancelled && setData(d))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onHash = () => {
      setOpenId(idFromHash());
      setCategory(catFromHash());
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const categoryKeys = useMemo(() => Object.keys(data?.categories ?? {}), [data]);
  const activeCategory = category && categoryKeys.includes(category) ? category : null;
  const counts = useCategoryCounts(data?.screenshots);
  const categoryLabel = useCategoryLabel(data?.categories);
  const filtered = useMemo(
    () => (data?.screenshots ?? []).filter((s) => !activeCategory || s.categories.includes(activeCategory)),
    [data, activeCategory],
  );
  const alphabetical = useMemo(() => sortAlphabetical(filtered, (s) => s.title), [filtered]);
  const open = useMemo(() => (data && openId ? data.screenshots.find((s) => s.id === openId) ?? null : null), [data, openId]);
  const openIndex = open ? filtered.findIndex((s) => s.id === open.id) : -1;

  const writeHash = (c: string | null, s: string | null) => writeHashParams([['c', c], ['s', s]]);
  const toggleCategory = (c: string | null) => {
    const next = c === category ? null : c;
    setCategory(next);
    writeHash(next, openId);
  };
  const show = useCallback(
    (id: string | null) => {
      setOpenId(id);
      writeHash(activeCategory, id);
    },
    [activeCategory],
  );
  const pickFromDropdown = (id: string) => {
    tiles.current.get(id)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    show(id);
  };
  const step = useCallback(
    (delta: number) => {
      if (openIndex < 0 || filtered.length < 2) return;
      show(filtered[(openIndex + delta + filtered.length) % filtered.length].id);
    },
    [openIndex, filtered, show],
  );

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') step(-1);
      else if (e.key === 'ArrowRight') step(1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, step]);

  if (failed) {
    return <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>{t('The screenshot list could not be loaded.')}</Typography>;
  }
  if (!data) {
    return <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>{t('Loading…')}</Typography>;
  }

  const navBtnSx = {
    position: 'absolute',
    top: '50%',
    transform: 'translateY(-50%)',
    color: P.textPrimary,
    bgcolor: P.surface,
    border: `1px solid ${P.borderColor}`,
    '&:hover': { bgcolor: P.hoverBg, borderColor: P.accent },
  } as const;

  return (
    <Box sx={{ width: '100%', maxWidth: 900, mx: 'auto' }}>
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1.5 }}>
        <CategoryChips
          categoryKeys={categoryKeys}
          counts={counts}
          total={data.screenshots.length}
          active={activeCategory}
          onToggle={toggleCategory}
          labelOf={categoryLabel}
          mb={0}
        />
      </Box>

      <FormControl size="small" fullWidth sx={{ mb: 2 }}>
        <InputLabel id="screenshot-select-label">{t('Choose a screenshot')}</InputLabel>
        <Select
          labelId="screenshot-select-label"
          id="screenshot-select"
          value=""
          label={t('Choose a screenshot')}
          onChange={(e: SelectChangeEvent) => pickFromDropdown(e.target.value)}
          MenuProps={{ PaperProps: { sx: { maxHeight: 420 } } }}
        >
          {alphabetical.map((s) => (
            <MenuItem key={s.id} value={s.id} sx={{ whiteSpace: 'normal', fontSize: TYPOGRAPHY.body.size }}>
              {s.title}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      <Box
        sx={{
          display: 'grid',
          gap: 1.5,
          gridTemplateColumns: {
            xs: 'minmax(0, 1fr)',
            sm: 'repeat(2, minmax(0, 1fr))',
            md: 'repeat(3, minmax(0, 1fr))',
            lg: 'repeat(4, minmax(0, 1fr))',
          },
        }}
      >
        {filtered.map((s) => (
          <Box
            key={s.id}
            component="button"
            type="button"
            ref={(el: HTMLElement | null) => {
              if (el) tiles.current.set(s.id, el);
              else tiles.current.delete(s.id);
            }}
            onClick={() => show(s.id)}
            aria-label={s.title}
            sx={{
              display: 'block',
              minWidth: 0,
              p: 0,
              textAlign: 'left',
              cursor: 'pointer',
              bgcolor: 'transparent',
              border: 0,
              borderRadius: 1.5,
              '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: 2 },
              '&:hover .shot-frame': { borderColor: P.accent },
            }}
          >
            <Box
              className="shot-frame"
              sx={{
                width: '100%',
                aspectRatio: '640 / 336',
                borderRadius: 1.5,
                overflow: 'hidden',
                border: `1px solid ${P.borderColor}`,
                bgcolor: P.hoverBg,
              }}
            >
              <Box
                component="img"
                src={thumbSrc(s)}
                alt={s.alt ?? s.title}
                width={640}
                loading="lazy"
                sx={{ display: 'block', width: '100%', height: '100%', objectFit: 'contain' }}
              />
            </Box>
            <Typography
              component="span"
              sx={{ display: 'block', mt: 0.5, color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, lineHeight: 1.4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
            >
              {s.title}
            </Typography>
          </Box>
        ))}
      </Box>

      <Dialog open={!!open} onClose={() => show(null)} maxWidth="xl" fullWidth aria-labelledby="screenshot-dialog-title">
        {open && (
          <>
            <DialogTitle id="screenshot-dialog-title" sx={{ pr: 7, fontSize: TYPOGRAPHY.navbarItem.size, fontWeight: 600 }}>
              {open.title}
              <IconButton
                aria-label={t('Close')}
                onClick={() => show(null)}
                size="small"
                sx={{ position: 'absolute', right: 12, top: 12, color: P.textSecondary }}
              >
                <Close fontSize="small" />
              </IconButton>
            </DialogTitle>
            <DialogContent sx={{ position: 'relative', display: 'flex', justifyContent: 'center', px: { xs: 1, sm: 7 }, pb: 2 }}>
              <Box
                component="img"
                src={fullSrc(open)}
                alt={open.alt ?? open.title}
                sx={{ display: 'block', maxWidth: '100%', maxHeight: '75vh', objectFit: 'contain', borderRadius: 1 }}
              />
              {filtered.length > 1 && openIndex >= 0 && (
                <>
                  <IconButton aria-label={t('Previous screenshot')} onClick={() => step(-1)} size="small" sx={{ ...navBtnSx, left: { xs: 4, sm: 12 } }}>
                    <ChevronLeft />
                  </IconButton>
                  <IconButton aria-label={t('Next screenshot')} onClick={() => step(1)} size="small" sx={{ ...navBtnSx, right: { xs: 4, sm: 12 } }}>
                    <ChevronRight />
                  </IconButton>
                </>
              )}
            </DialogContent>
          </>
        )}
      </Dialog>
    </Box>
  );
};

export default ScreenshotGallery;
