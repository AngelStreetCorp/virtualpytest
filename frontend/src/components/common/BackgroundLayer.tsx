import { Box } from '@mui/material';
import { alpha } from '@mui/material/styles';
import React, { useEffect, useState } from 'react';

/**
 * A background image (TASK-136): the image with its tint filter, then a scrim in the page colour so
 * text stays readable. `fixed` = the page layer behind the whole app: z-index -1 paints it above
 * <html>'s colour and below every in-flow box (body and #root are transparent while it is on); not
 * `background-attachment: fixed` (repaints on every scroll). Without `fixed` it fills its parent
 * (the theme dialog's preview).
 * A new image is decoded first and swapped in one frame, so the old one stays until the new one can
 * paint: no blank page colour between two images (UI_STYLE S6/S7, no flash).
 */
const BackgroundLayer: React.FC<{ url: string; filter: string; overlay?: string | null; scrimColour: string; scrim: number; fixed?: boolean }> = ({
  url,
  filter,
  overlay = null,
  scrimColour,
  scrim,
  fixed = false,
}) => {
  const [shown, setShown] = useState(url);
  useEffect(() => {
    let live = true;
    const img = new Image();
    img.src = url;
    const done = () => live && setShown(url);
    if (img.decode) img.decode().then(done, done);
    else img.onload = img.onerror = done;
    return () => {
      live = false;
    };
  }, [url]);
  return (
  <Box aria-hidden sx={{ position: fixed ? 'fixed' : 'absolute', inset: 0, zIndex: fixed ? -1 : 0, pointerEvents: 'none' }}>
    <Box
      sx={{
        position: 'absolute',
        inset: 0,
        backgroundImage: `url("${shown}")`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        filter,
      }}
    />
    {overlay && <Box sx={{ position: 'absolute', inset: 0, bgcolor: overlay, mixBlendMode: 'color', opacity: 0.6 }} />}
    <Box sx={{ position: 'absolute', inset: 0, bgcolor: alpha(scrimColour, scrim) }} />
  </Box>
  );
};

export default BackgroundLayer;
