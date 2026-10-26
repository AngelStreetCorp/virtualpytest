import { Box, Button, DialogActions, DialogContent, DialogTitle, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useCatalogue } from '../../hooks/customPages/useCustomPages';
import { useI18n } from '../../i18n/useI18n';
import type { BlockType, CatalogueBlock } from '../../types/customPages';
import { StyledDialog } from '../common/StyledDialog';
import { neutralButtonSx, primaryButtonSx } from '../common/PageChrome';

interface Props {
  open: boolean;
  onClose: () => void;
  onAdd: (type: BlockType) => void;
}

/** The block palette: blocks the user may add first, locked ones below with the reason. */
export const AddBlockDialog: React.FC<Props> = ({ open, onClose, onAdd }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { data, isLoading, error } = useCatalogue();

  const row = (block: CatalogueBlock, locked: boolean) => (
    <Box
      key={block.type}
      data-testid={`palette-${block.type}`}
      data-locked={locked ? 'true' : 'false'}
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1.5,
        py: 1,
        borderTop: `1px solid ${P.borderColor}`,
        opacity: locked ? 0.65 : 1,
      }}
    >
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.body.size }}>{t(block.title)}</Typography>
        <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>{t(block.description)}</Typography>
        {locked && (
          <Typography sx={{ color: P.warning, fontSize: TYPOGRAPHY.caption.size, mt: 0.25 }}>
            {t('Needs {permission}. Ask a team admin.', { permission: (block.missing ?? []).join(', ') })}
          </Typography>
        )}
      </Box>
      <Button size="small" variant="contained" disabled={locked} onClick={() => onAdd(block.type)} sx={primaryButtonSx(P)}>
        {t('Add')}
      </Button>
    </Box>
  );

  return (
    <StyledDialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('Add a block')}</DialogTitle>
      <DialogContent>
        {isLoading && <Typography sx={{ color: P.textMuted }}>{t('Loading...')}</Typography>}
        {error && <Typography sx={{ color: P.error }}>{(error as Error).message}</Typography>}
        {data && (
          <>
            {data.available.map((b) => row(b, false))}
            {data.unavailable.length > 0 && (
              <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, textTransform: 'uppercase', letterSpacing: '0.06em', mt: 2 }}>
                {t('Not available to you')}
              </Typography>
            )}
            {data.unavailable.map((b) => row(b, true))}
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} sx={neutralButtonSx(P)}>
          {t('Close')}
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};
