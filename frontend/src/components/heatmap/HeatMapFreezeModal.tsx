import { Close as CloseIcon } from '@mui/icons-material';
import { Modal, Box, IconButton, Typography } from '@mui/material';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import React, { useMemo } from 'react';
import { useR2UrlsBatch } from '../../hooks/storage/useR2Url';
import { TYPOGRAPHY } from '../../constants/typography';

interface HeatMapFreezeModalProps {
  freezeModalOpen: boolean;
  hostName: string;
  deviceId: string;
  thumbnailUrls: string[]; // Direct R2 URLs (3 images)
  freezeDiffs: number[]; // Frame differences (3 values)
  timestamp?: string;
  onClose: () => void;
}

export const HeatMapFreezeModal: React.FC<HeatMapFreezeModalProps> = ({
  freezeModalOpen,
  hostName,
  deviceId,
  thumbnailUrls,
  freezeDiffs,
  timestamp,
  onClose,
}) => {
  const P = useAgentChatPalette();
  const httpRegex = /^https?:\/\//i;

  // Determine if any URL needs signing (non-HTTP paths)
  const needsSigning = useMemo(() => thumbnailUrls.some((u) => u && !httpRegex.test(u)), [thumbnailUrls]);

  // Only sign when needed; otherwise use URLs as-is
  const { urls: signedThumbnailUrls, loading } = useR2UrlsBatch(needsSigning ? thumbnailUrls : []);
  const resolvedThumbnailUrls = needsSigning ? signedThumbnailUrls : thumbnailUrls;
  
  if (!freezeModalOpen || thumbnailUrls.length === 0) return null;

  return (
    <Modal
      open={freezeModalOpen}
      onClose={onClose}
      sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}
    >
      <Box
        sx={{
          width: '90vw',
          height: '70vh',
          bgcolor: 'black',
          display: 'flex',
          flexDirection: 'column',
          border: `1px solid ${P.accent}`,
          borderRadius: 2,
          overflow: 'hidden',
          outline: 'none',
        }}
      >
        {/* Header with close button */}
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'flex-end',
            p: 0.5,
            bgcolor: P.surfaceSolid,
          }}
        >
          <IconButton
            onClick={onClose}
            aria-label="Close"
            sx={{
              color: P.textPrimary,
              '&:hover': { bgcolor: P.hoverBg, color: P.accent },
              '& .MuiSvgIcon-root': { fontSize: TYPOGRAPHY.kpiValue.size },
            }}
          >
            <CloseIcon />
          </IconButton>
        </Box>

        {/* Title and Timestamp Metadata */}
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            p: 1,
            bgcolor: P.surfaceSolid,
            borderBottom: `1px solid ${P.borderColor}`,
          }}
        >
          <Typography
            variant="h6"
            sx={{
              color: P.textPrimary,
              fontWeight: 'bold',
              mb: 0.5,
            }}
          >
            Capture
          </Typography>
          {timestamp && (
            <Typography
              variant="body2"
              sx={{
                color: P.textSecondary,
                fontSize: TYPOGRAPHY.body.size,
              }}
            >
              {new Date(timestamp).toLocaleString()}
            </Typography>
          )}
          <Typography
            variant="caption"
            sx={{
              color: P.textMuted,
              fontSize: TYPOGRAPHY.caption.size,
              mt: 0.5,
            }}
          >
            Device: {hostName}-{deviceId}
          </Typography>
        </Box>

        {/* 3 Images side by side */}
        <Box sx={{ display: 'flex', flex: 1, gap: 1, p: 1 }}>
          {loading ? (
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1 }}>
              <Typography sx={{ color: 'white' }}>Loading images...</Typography>
            </Box>
          ) : (
            resolvedThumbnailUrls.map((imageUrl: string | null, index: number) => {
              const diff = freezeDiffs[index];
              const frameLabels = ['Frame -2', 'Frame -1', 'Current'];

              return (
                <Box
                  key={index}
                  sx={{
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                  }}
                >
                  <Typography
                    variant="caption"
                    sx={{
                      color: 'white',
                      textAlign: 'center',
                      p: 0.5,
                      bgcolor: 'rgba(0,0,0,0.7)',
                      fontSize: TYPOGRAPHY.caption.size,
                    }}
                  >
                    {frameLabels[index]} - Diff ({diff !== undefined ? diff.toFixed(1) : 'N/A'})
                  </Typography>
                  {imageUrl ? (
                    <img
                      src={imageUrl}
                      alt={`Frame ${index}`}
                      style={{
                        width: '100%',
                        height: '100%',
                        objectFit: 'contain',
                      }}
                    />
                  ) : (
                    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, bgcolor: 'rgba(255,255,255,0.1)' }}>
                      <Typography sx={{ color: 'rgba(255,255,255,0.5)' }}>Image unavailable</Typography>
                    </Box>
                  )}
                </Box>
              );
            })
          )}
        </Box>
      </Box>
    </Modal>
  );
};
