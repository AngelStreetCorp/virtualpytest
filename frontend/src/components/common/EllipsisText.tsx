/**
 * Text that ellipsises, and shows its full value on hover — but only when it is actually
 * clipped. A tooltip on every cell is noise; a cell you cannot read and cannot interrogate is
 * worse. Truncation is measured (scrollWidth vs clientWidth) rather than guessed from length,
 * since the same string clips or not depending on the column width and the font.
 *
 * Re-measured on window resize and whenever the text changes, so a column that narrows starts
 * offering the tooltip without a remount.
 */
import { Tooltip, Typography, type TypographyProps } from '@mui/material';
import React, { useCallback, useEffect, useRef, useState } from 'react';

export interface EllipsisTextProps extends Omit<TypographyProps, 'children'> {
  children: string;
  /** Shown instead of `children` in the tooltip, when the full value is longer than the label. */
  tooltip?: string;
}

export const EllipsisText: React.FC<EllipsisTextProps> = ({
  children,
  tooltip,
  sx,
  ...typographyProps
}) => {
  const ref = useRef<HTMLElement | null>(null);
  const [clipped, setClipped] = useState(false);

  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setClipped(el.scrollWidth > el.clientWidth + 1);
  }, []);

  useEffect(() => {
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [measure, children]);

  const text = (
    <Typography
      {...typographyProps}
      ref={ref}
      sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', ...sx }}
    >
      {children}
    </Typography>
  );

  if (!clipped) return text;

  return (
    <Tooltip title={tooltip || children} arrow enterDelay={300}>
      {text}
    </Tooltip>
  );
};

export default EllipsisText;
