import { ArrowBack, ArrowForward, Delete, Settings } from '@mui/icons-material';
import { Box, IconButton, MenuItem, Select, Tooltip, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useCatalogue } from '../../hooks/customPages/useCustomPages';
import { useI18n } from '../../i18n/useI18n';
import type { BlockState, PageBlock } from '../../types/customPages';
import { dangerIconSx } from '../common/PageChrome';
import { BLOCK_RENDERERS } from './blocks';
import { LockedBlock, UnknownBlock } from './blockParts';

interface Props {
  blocks: PageBlock[];
  states: Record<string, BlockState>;
  editing: boolean;
  onMove: (blockId: string, toIndex: number) => void;
  onWidth: (blockId: string, w: number) => void;
  onRemove: (blockId: string) => void;
  onSettings: (blockId: string) => void;
}

/** The 6-column grid of blocks. In edit mode each block gets move, width, settings and remove controls. */
export const CustomPageBody: React.FC<Props> = ({ blocks, states, editing, onMove, onWidth, onRemove, onSettings }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { data: catalogue } = useCatalogue();
  const titleOf = (type: string) => {
    const entry = catalogue ? [...catalogue.available, ...catalogue.unavailable].find((b) => b.type === type) : undefined;
    return entry ? t(entry.title) : type;
  };
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'repeat(6, minmax(0, 1fr))' },
        gap: 1.5,
        alignItems: 'start',
      }}
    >
      {blocks.map((block, index) => {
        const Renderer = BLOCK_RENDERERS[block.type];
        const state = states[block.id];
        const locked = state && !state.available;
        return (
          <Box
            key={block.id}
            data-testid={`block-${block.type}`}
            sx={{
              gridColumn: { xs: '1 / -1', md: `${block.x + 1} / span ${block.w}` },
              bgcolor: P.surface,
              border: `1px solid ${P.borderColor}`,
              borderRadius: 2,
              p: 1.5,
              minWidth: 0,
            }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 1 }}>
              <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
                {titleOf(block.type)}
              </Typography>
              {editing && (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25 }}>
                  <Tooltip title={t('Move earlier')}>
                    <span>
                      <IconButton size="small" disabled={index === 0} aria-label={t('Move earlier')} onClick={() => onMove(block.id, index - 1)}>
                        <ArrowBack fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                  <Tooltip title={t('Move later')}>
                    <span>
                      <IconButton size="small" disabled={index === blocks.length - 1} aria-label={t('Move later')} onClick={() => onMove(block.id, index + 1)}>
                        <ArrowForward fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                  <Select size="small" value={block.w} onChange={(e) => onWidth(block.id, Number(e.target.value))} inputProps={{ 'aria-label': t('Width') }} sx={{ fontSize: TYPOGRAPHY.caption.size, '& .MuiSelect-select': { py: 0.25 } }}>
                    {[1, 2, 3, 4, 5, 6].map((w) => (
                      <MenuItem key={w} value={w}>
                        {w}/6
                      </MenuItem>
                    ))}
                  </Select>
                  <Tooltip title={t('Settings')}>
                    <IconButton size="small" aria-label={t('Settings')} onClick={() => onSettings(block.id)}>
                      <Settings fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title={t('Remove block')}>
                    <IconButton size="small" aria-label={t('Remove block')} onClick={() => onRemove(block.id)} sx={dangerIconSx(P)}>
                      <Delete fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </Box>
              )}
            </Box>
            {locked ? <LockedBlock missing={state.missing} /> : Renderer ? <Renderer block={block} /> : <UnknownBlock type={block.type} />}
          </Box>
        );
      })}
    </Box>
  );
};
