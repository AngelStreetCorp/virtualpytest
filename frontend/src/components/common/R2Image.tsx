import React from 'react';
import { Box, CircularProgress, Typography, BoxProps } from '@mui/material';
import { ImageNotSupported as NoImageIcon } from '@mui/icons-material';
import { useR2Url } from '../../hooks/storage/useR2Url';

interface R2ImageProps extends Omit<BoxProps, 'component'> {
  /** R2 path or full URL (public or private) */
  src: string | null | undefined;
  /** Alt text for the image */
  alt?: string;
  /** Expiry time in seconds (only used in private mode) */
  expiresIn?: number;
  /** Whether to show loading spinner */
  showLoading?: boolean;
  /** Whether to show error state */
  showError?: boolean;
  /** Custom error message */
  errorMessage?: string;
  /** Image element props */
  imgProps?: React.ImgHTMLAttributes<HTMLImageElement>;
  /** Fallback component when no image */
  fallback?: React.ReactNode;
}

/**
 * R2Image - Auto-handles public/private R2 bucket URLs
 * 
 * Works automatically based on VITE_CLOUDFLARE_R2_PUBLIC_URL env var:
 * - If set: Uses direct public URLs
 * - If not set: Fetches signed URLs from backend
 * 
 * Usage:
 *   <R2Image src="captures/screenshot.jpg" alt="Screenshot" />
 *   <R2Image src={data.screenshot_url} alt="Node" sx={{ maxHeight: 400 }} />
 */
export const R2Image: React.FC<R2ImageProps> = ({
  src,
  alt = 'Image',
  expiresIn = 3600,
  showLoading = true,
  showError = true,
  errorMessage = 'Failed to load image',
  imgProps = {},
  fallback,
  sx,
  ...boxProps
}) => {
  // Use R2 URL hook - handles public/private mode automatically
  const { url, loading, error } = useR2Url(src || null, expiresIn);

  // No source provided
  if (!src) {
    if (fallback) return <>{fallback}</>;
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'action.hover',
          borderRadius: 1,
          p: 2,
          ...sx,
        }}
        {...boxProps}
      >
        <NoImageIcon sx={{ color: 'text.disabled', mr: 1 }} />
        <Typography variant="body2" color="text.disabled">
          No image
        </Typography>
      </Box>
    );
  }

  // Loading state
  if (loading && showLoading) {
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'action.hover',
          borderRadius: 1,
          p: 2,
          minHeight: 100,
          ...sx,
        }}
        {...boxProps}
      >
        <CircularProgress size={24} />
      </Box>
    );
  }

  // Error state
  if (error && showError) {
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'error.dark',
          borderRadius: 1,
          p: 2,
          opacity: 0.7,
          ...sx,
        }}
        {...boxProps}
      >
        <NoImageIcon sx={{ color: 'error.light', mb: 0.5 }} />
        <Typography variant="caption" color="error.light">
          {errorMessage}
        </Typography>
      </Box>
    );
  }

  // Image ready
  if (url) {
    return (
      <Box
        component="img"
        src={url}
        alt={alt}
        sx={{
          objectFit: 'contain',
          ...sx,
        }}
        {...imgProps}
        {...boxProps}
      />
    );
  }

  // Fallback (shouldn't reach here normally)
  if (fallback) return <>{fallback}</>;
  return null;
};

export default R2Image;

