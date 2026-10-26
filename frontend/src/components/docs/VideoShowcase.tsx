import { Box, FormControl, InputLabel, MenuItem, Select, Typography } from '@mui/material';
import { visuallyHidden } from '@mui/utils';
import type { SelectChangeEvent } from '@mui/material';
import { PlayArrow } from '@mui/icons-material';
import React, { useEffect, useMemo, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import CategoryChips, { useCategoryCounts, useCategoryLabel } from './CategoryChips';
import { readHashParam, sortAlphabetical, writeHashParams } from './docsFilter';
import { TYPOGRAPHY } from '../../constants/typography';

/**
 * The Videos docs page: one top video, a dropdown that picks it, and the 3 newest as thumbnails.
 *
 * Data: docs/videos/videos.json (newest first, `default` = the best-of shown first). It is the same
 * file scripts/gen_readme_videos.py turns into the README blocks; frontend/scripts/copy-docs.sh
 * copies it to /docs/videos/videos.json at build time.
 *
 * Weight: the page loads 4 images and NO iframe. The top video is a poster (its thumbnail + a play
 * button) that becomes the YouTube iframe on click, so the ~1 MB YouTube player is only fetched by
 * someone who presses play. Once playing, picking another video starts it right away.
 * Dropdown options are text only (alphabetical, publication number right-aligned after the title). The chosen video lives in the URL hash (#v=<id>).
 */

interface Video {
  id: string;
  title: string | null;
  summary: string;
  thumb: string | null;
  added: string | null;
  categories: string[];
}
interface VideoData {
  default: string;
  /** key -> display label, in display order; edited in docs/videos/videos.json. */
  categories: Record<string, string>;
  videos: Video[];
}

const NEWEST = 3;
const DATA_URL = '/docs/videos/videos.json';

// "... | VirtualPyTest" is a YouTube SEO suffix, noise on this page.
const cleanTitle = (v: Video) => (v.title || v.id).replace(/\s*\|\s*VirtualPyTest\s*$/, '');
// Repo thumbnails live in frontend/public (served from /); videos without one use YouTube's image.
const thumbSrc = (v: Video) =>
  v.thumb ? v.thumb.replace(/^frontend\/public/, '') : `https://img.youtube.com/vi/${v.id}/hqdefault.jpg`;

// Layout: main video + 3 stacked 16:9 thumbnails on the right. With gap G the thumbnail column is
// W/4 - 41*G/36 wide, which makes 3 thumbnails + 2 gaps exactly as tall as the 16:9 main video.
const GAP_PX = 12;
const THUMB_COL = `calc(25% - ${(41 * GAP_PX) / 36}px)`;
const BLOCK_MAX_WIDTH = 900;

const idFromHash = (): string | null => readHashParam('v', '[\\w-]{11}');
const catFromHash = (): string | null => readHashParam('c');

const VideoShowcase: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [data, setData] = useState<VideoData | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<string | null>(idFromHash);
  const [category, setCategory] = useState<string | null>(catFromHash);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(DATA_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: VideoData) => !cancelled && setData(d))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onHash = () => {
      setSelected(idFromHash());
      setCategory(catFromHash());
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // replaceState: the choice is shareable but does not pile up history entries.
  const writeHash = (c: string | null, v: string | null) => writeHashParams([['c', c], ['v', v]]);
  const pick = (id: string) => {
    setSelected(id);
    writeHash(category, id);
  };
  const toggleCategory = (c: string | null) => {
    const next = c === category ? null : c;
    setCategory(next);
    writeHash(next, selected);
  };

  const byId = useMemo(() => new Map((data?.videos ?? []).map((v) => [v.id, v])), [data]);
  const top = data ? byId.get(selected ?? '') ?? byId.get(data.default) : undefined;
  // Publication number: oldest = 1, newest = N. Derived from the position (newest-first array), never stored.
  const numberOf = useMemo(() => {
    const n = data?.videos.length ?? 0;
    return new Map((data?.videos ?? []).map((v, i) => [v.id, n - i]));
  }, [data]);
  const categoryKeys = useMemo(() => Object.keys(data?.categories ?? {}), [data]);
  const activeCategory = category && categoryKeys.includes(category) ? category : null;
  const counts = useCategoryCounts(data?.videos);
  const categoryLabel = useCategoryLabel(data?.categories);
  const alphabetical = useMemo(
    () => sortAlphabetical((data?.videos ?? []).filter((v) => !activeCategory || v.categories.includes(activeCategory)), cleanTitle),
    [data, activeCategory],
  );
  const newest = useMemo(
    () => (data ? data.videos.filter((v) => v.id !== data.default).slice(0, NEWEST) : []),
    [data],
  );

  if (failed) {
    return <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>{t('The video list could not be loaded.')}</Typography>;
  }
  if (!data || !top) {
    return <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>{t('Loading…')}</Typography>;
  }

  const badgeSx = {
    position: 'absolute',
    top: 6,
    left: 6,
    px: 0.75,
    py: 0.125,
    borderRadius: 1,
    fontSize: TYPOGRAPHY.caption.size,
    fontWeight: 600,
    lineHeight: 1.4,
    color: 'common.white',
    bgcolor: 'rgba(0, 0, 0, 0.65)',
    pointerEvents: 'none',
  } as const;
  const numTag = (v: Video) => `#${numberOf.get(v.id)}`;

  return (
    <Box sx={{ width: '100%', maxWidth: BLOCK_MAX_WIDTH, mx: 'auto' }}>
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1.5 }}>
        <CategoryChips
          categoryKeys={categoryKeys}
          counts={counts}
          total={data.videos.length}
          active={activeCategory}
          onToggle={toggleCategory}
          labelOf={categoryLabel}
          mb={0}
        />
      </Box>

      <FormControl size="small" fullWidth sx={{ mb: 1.5 }}>
        <InputLabel id="video-select-label">{t('Choose a video')}</InputLabel>
        <Select
          labelId="video-select-label"
          id="video-select"
          value={top.id}
          label={t('Choose a video')}
          onChange={(e: SelectChangeEvent) => pick(e.target.value)}
          renderValue={() => `${cleanTitle(top)}  ·  ${numTag(top)}`}
          MenuProps={{ PaperProps: { sx: { maxHeight: 420 } } }}
          sx={{ '& .MuiSelect-select': { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }}
        >
          {alphabetical.map((v) => (
            <MenuItem key={v.id} value={v.id} sx={{ whiteSpace: 'normal', fontSize: TYPOGRAPHY.body.size, display: 'flex', gap: 2 }}>
              <Box component="span" sx={{ flex: 1, minWidth: 0 }}>{cleanTitle(v)}</Box>
              <Box component="span" sx={{ flexShrink: 0, color: P.textMuted, fontVariantNumeric: 'tabular-nums' }}>{numTag(v)}</Box>
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      <Box
        sx={{
          display: 'grid',
          gap: `${GAP_PX}px`,
          gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: `minmax(0, 1fr) ${THUMB_COL}` },
          alignItems: 'start',
        }}
      >
        <Box
          sx={{
            position: 'relative',
            width: '100%',
            aspectRatio: '16 / 9',
            borderRadius: 1.5,
            overflow: 'hidden',
            border: `1px solid ${P.borderColor}`,
            bgcolor: P.hoverBg,
          }}
        >
          {playing ? (
            <iframe
              key={top.id}
              src={`https://www.youtube.com/embed/${top.id}?autoplay=1&rel=0`}
              title={cleanTitle(top)}
              loading="lazy"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', border: 0 }}
            />
          ) : (
            <Box
              component="button"
              type="button"
              onClick={() => setPlaying(true)}
              aria-label={`${t('Play')}: ${cleanTitle(top)} (${numTag(top)})`}
              sx={{
                position: 'absolute',
                inset: 0,
                width: '100%',
                height: '100%',
                p: 0,
                border: 0,
                cursor: 'pointer',
                bgcolor: 'transparent',
                '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: -2 },
                '&:hover .play-btn': { bgcolor: P.accentHover },
              }}
            >
              <Box
                component="img"
                src={thumbSrc(top)}
                alt={cleanTitle(top)}
                sx={{ display: 'block', width: '100%', height: '100%', objectFit: 'cover' }}
              />
              <Box
                className="play-btn"
                sx={{
                  position: 'absolute',
                  top: '50%',
                  left: '50%',
                  transform: 'translate(-50%, -50%)',
                  width: 64,
                  height: 64,
                  borderRadius: '50%',
                  bgcolor: P.accent,
                  color: 'primary.contrastText',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <PlayArrow sx={{ fontSize: TYPOGRAPHY.displayKpi.size }} />
              </Box>
              <Box component="span" sx={badgeSx}>{numTag(top)}</Box>
            </Box>
          )}
        </Box>

        <Box
          component="section"
          aria-label={t('Latest videos')}
          sx={{
            display: 'grid',
            gap: `${GAP_PX}px`,
            gridTemplateColumns: { xs: 'repeat(3, minmax(0, 1fr))', md: 'minmax(0, 1fr)' },
          }}
        >
          {newest.map((v) => {
            const active = v.id === top.id;
            return (
              <Box
                key={v.id}
                component="button"
                type="button"
                onClick={() => pick(v.id)}
                aria-pressed={active}
                aria-label={`${cleanTitle(v)} (${numTag(v)})`}
                sx={{
                  position: 'relative',
                  display: 'block',
                  width: '100%',
                  aspectRatio: '16 / 9',
                  p: 0,
                  cursor: 'pointer',
                  bgcolor: P.surface,
                  border: `1px solid ${active ? P.accent : P.borderColor}`,
                  borderRadius: 1.5,
                  overflow: 'hidden',
                  '&:hover': { borderColor: P.accent },
                  '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: 2 },
                }}
              >
                <Box
                  component="img"
                  src={thumbSrc(v)}
                  alt={cleanTitle(v)}
                  loading="lazy"
                  sx={{ display: 'block', width: '100%', height: '100%', objectFit: 'cover' }}
                />
                <Box component="span" sx={badgeSx}>{numTag(v)}</Box>
                <Box component="span" sx={visuallyHidden}>{cleanTitle(v)}</Box>
              </Box>
            );
          })}
        </Box>
      </Box>
    </Box>
  );
};

export default VideoShowcase;
