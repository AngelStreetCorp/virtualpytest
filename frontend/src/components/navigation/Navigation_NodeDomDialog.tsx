import { Close as CloseIcon } from '@mui/icons-material';
import {
  Box,
  Button,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import React, { useState } from 'react';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { getZIndex } from '../../utils/zIndexUtils';
import { StyledDialog } from '../common/StyledDialog';
import { neutralButtonSx } from '../common/PageChrome';

interface DomElement {
  index?: number;
  id?: string;
  type?: string;
  label?: string;
  bbox?: number[];
  focused?: boolean;
  ok_action?: string;
}

interface NodeDomDialogProps {
  open: boolean;
  onClose: () => void;
  nodeLabel?: string;
  dom: any;
  screenshotUrl?: string | null;
  /** The <stem>_dom.jpg overlay, opened in a new tab from the footer. */
  overlayUrl?: string | null;
}

const MONO = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace';

/** A node's DOM (focusable elements from the screenshot): the screenshot with the
 *  element boxes drawn on top, and the element list. Hovering a row highlights its box. */
export const NodeDomDialog: React.FC<NodeDomDialogProps> = ({
  open,
  onClose,
  nodeLabel,
  dom,
  screenshotUrl,
  overlayUrl,
}) => {
  const P = useAgentChatPalette();
  const [hover, setHover] = useState<number | null>(null);
  const elements: DomElement[] = Array.isArray(dom?.focusable_elements) ? dom.focusable_elements : [];
  const version = dom?._dom_meta?.v;

  return (
    <StyledDialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      sx={{ zIndex: getZIndex('NAVIGATION_DIALOGS', 1) }}
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Box sx={{ flex: 1 }}>DOM · {nodeLabel}</Box>
        <Typography sx={{ fontFamily: MONO, fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
          {elements.length} elements{version ? ` · v${version}` : ''}
          {dom?.screen_type ? ` · ${dom.screen_type}` : ''}
        </Typography>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        {dom?.screen_summary && (
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 1 }}>
            {dom.screen_summary}
          </Typography>
        )}
        <Box sx={{ position: 'relative', borderRadius: 1, overflow: 'hidden', bgcolor: P.hoverBg, lineHeight: 0 }}>
          {screenshotUrl && (
            <Box component="img" src={screenshotUrl} alt="Screenshot" sx={{ width: '100%', display: 'block' }} />
          )}
          {elements.map((e, i) => {
            if (!Array.isArray(e.bbox) || e.bbox.length !== 4) return null;
            const [x, y, w, h] = e.bbox;
            const on = hover === i;
            const colour = e.focused || on ? P.accent : P.series[1];
            return (
              <Box
                key={i}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                sx={{
                  position: 'absolute',
                  left: `${x * 100}%`,
                  top: `${y * 100}%`,
                  width: `${w * 100}%`,
                  height: `${h * 100}%`,
                  border: `2px solid ${colour}`,
                  borderRadius: 0.5,
                  bgcolor: on ? `${P.accent}40` : 'transparent',
                  opacity: hover === null || on ? 1 : 0.35,
                }}
              />
            );
          })}
        </Box>
        <Table size="small" sx={{ mt: 1, tableLayout: 'fixed' }}>
          <colgroup>
            <col style={{ width: 48 }} />
            <col />
            <col style={{ width: 140 }} />
            <col style={{ width: 110 }} />
          </colgroup>
          <TableHead>
            <TableRow>
              <TableCell>#</TableCell>
              <TableCell>Element</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>OK does</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {elements.map((e, i) => (
              <TableRow
                key={i}
                hover
                selected={hover === i}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              >
                <TableCell sx={{ fontFamily: MONO, color: P.textSecondary }}>{e.index ?? i}</TableCell>
                <TableCell sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={e.id}>
                  {e.label || e.id}
                  {e.focused && (
                    <Typography component="span" sx={{ ml: 1, fontSize: TYPOGRAPHY.caption.size, color: P.accent }}>
                      focused
                    </Typography>
                  )}
                </TableCell>
                <TableCell sx={{ fontFamily: MONO, color: P.textSecondary }}>{e.type}</TableCell>
                <TableCell sx={{ fontFamily: MONO, color: P.textSecondary }}>{e.ok_action}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DialogContent>
      <DialogActions>
        <Button
          variant="outlined"
          sx={neutralButtonSx(P)}
          disabled={!overlayUrl}
          onClick={() => overlayUrl && window.open(overlayUrl, '_blank')}
        >
          Open image in new tab
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

export default NodeDomDialog;
