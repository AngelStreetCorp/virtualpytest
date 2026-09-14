import { ImageOutlined as ImageIcon } from '@mui/icons-material';
import { Box, CircularProgress, IconButton, Popover, Typography } from '@mui/material';
import React, { useState } from 'react';

import { useR2Url } from '../../hooks/storage/useR2Url';
import { getZIndex } from '../../utils/zIndexUtils';

interface ReferenceImagePreviewProps {
  referenceUrl: string;
  disabled?: boolean;
  // When true, render the resolved image inline (constrained to
  // thumbnailMaxWidth/Height) instead of an icon button. Hover/click still
  // opens the full-size popover. Default false keeps the compact
  // icon+popover used inline in the verification editor.
  thumbnail?: boolean;
  thumbnailMaxWidth?: number;
  thumbnailMaxHeight?: number;
}

export const ReferenceImagePreview: React.FC<ReferenceImagePreviewProps> = ({
  referenceUrl,
  disabled = false,
  thumbnail = false,
  thumbnailMaxWidth = 120,
  thumbnailMaxHeight = 68,
}) => {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const { url, loading, error } = useR2Url(referenceUrl);

  const open = Boolean(anchorEl);

  const handleOpen = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const trigger = thumbnail ? (
    <Box
      onMouseEnter={disabled ? undefined : handleOpen}
      onMouseLeave={handleClose}
      onClick={disabled ? undefined : handleOpen}
      sx={{
        width: thumbnailMaxWidth,
        height: thumbnailMaxHeight,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: disabled ? 'default' : 'pointer',
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 0.5,
        overflow: 'hidden',
        bgcolor: 'action.hover',
      }}
    >
      {loading && <CircularProgress size={16} />}
      {!loading && url && !error && (
        <img
          src={url}
          alt=""
          style={{
            maxWidth: thumbnailMaxWidth,
            maxHeight: thumbnailMaxHeight,
            objectFit: 'contain',
            display: 'block',
          }}
        />
      )}
      {!loading && (!url || error) && (
        <Typography variant="caption" color="text.secondary">
          no image
        </Typography>
      )}
    </Box>
  ) : (
    <IconButton
      size="small"
      disabled={disabled}
      onMouseEnter={handleOpen}
      onMouseLeave={handleClose}
      onClick={handleOpen}
      sx={{ p: 0.5, width: 28, height: 28 }}
    >
      <ImageIcon sx={{ fontSize: '1rem' }} />
    </IconButton>
  );

  return (
    <>
      {trigger}
      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={handleClose}
        anchorOrigin={{ vertical: 'center', horizontal: 'right' }}
        transformOrigin={{ vertical: 'center', horizontal: 'left' }}
        disableRestoreFocus
        sx={{ zIndex: getZIndex('NAVIGATION_DIALOGS', 1), pointerEvents: 'none' }}
        slotProps={{
          paper: {
            onMouseEnter: () => setAnchorEl(anchorEl),
            onMouseLeave: handleClose,
            sx: { p: 0.5, pointerEvents: 'auto', bgcolor: 'background.paper' },
          },
        }}
      >
        {loading && (
          <Box sx={{ width: 120, height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <CircularProgress size={20} />
          </Box>
        )}
        {!loading && url && !error && (
          <img
            src={url}
            alt=""
            style={{
              display: 'block',
              maxWidth: 320,
              maxHeight: 240,
              objectFit: 'contain',
            }}
          />
        )}
      </Popover>
    </>
  );
};

export default ReferenceImagePreview;
