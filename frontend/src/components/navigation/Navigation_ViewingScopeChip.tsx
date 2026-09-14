/**
 * ViewingScopeChip — Canvas viewer chip — selects which variant(s) the canvas renders.
 *
 * Sits on the editor toolbar and lets the author switch between Base, a single
 * variant, or a COMPOSITION of several variants (multi-select). When one or more
 * variants are picked the canvas re-renders through `useResolvedTree` over the
 * composed override maps: disabled rows hidden, per-variant content applied, but
 * no edits are written back. A composition (>1 variant) is a read-only preview.
 * The scope is emitted as a canonical '+'-joined string ('a+b'); single picks
 * emit the bare name and clearing emits null (Base).
 * See docs/agent/navigation/VARIANT.md "Composition".
 */
import { Box, Button, Checkbox, Divider, IconButton, Menu, MenuItem, Tooltip } from '@mui/material';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import React, { useCallback, useState } from 'react';

import { useUserInterfaceVariants } from '../../hooks/userinterface/useUserInterfaceVariants';
import { canonicalVariantName, parseVariantList } from '../../utils/navigation/variantResolver';

interface NavigationViewingScopeChipProps {
  /** Userinterface ID — drives the variant list. Pass null/undefined to disable the dropdown. */
  userInterfaceId?: string | null;
  /** Current scope: null for Base, a single variant name, or a '+'-joined composition. */
  scope: string | null;
  /** Called when the user changes the scope (canonical composite string, or null for Base). */
  onScopeChange: (next: string | null) => void;
  /** Disable the control (e.g. while loading). */
  disabled?: boolean;
  /**
   * Whether rows disabled on the active single variant render ghosted (visible &
   * selectable) instead of being filtered off the canvas. Only meaningful when a
   * single variant is the scope. When `onToggleShowDisabled` is provided, a
   * per-variant eye toggle is rendered on that variant's dropdown row — keeping
   * the toggle out of the toolbar so selecting a variant never shifts button layout.
   */
  showDisabled?: boolean;
  onToggleShowDisabled?: () => void;
}

const BASE_LABEL = 'Base';
const MAX_LABEL_CHARS = 14;
// Single source of truth for the chip width so the closed trigger and the open
// dropdown menu are always the same width (coherent, no jump on open).
const CHIP_WIDTH = 120;

const truncate = (s: string) =>
  s.length > MAX_LABEL_CHARS ? `${s.slice(0, MAX_LABEL_CHARS - 1)}…` : s;

export const NavigationViewingScopeChip: React.FC<NavigationViewingScopeChipProps> = ({
  userInterfaceId,
  scope,
  onScopeChange,
  disabled,
  showDisabled,
  onToggleShowDisabled,
}) => {
  const { variants } = useUserInterfaceVariants(userInterfaceId || null);
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const open = Boolean(anchorEl);

  const hasVariants = variants.length > 0;

  const handleOpen = useCallback((e: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(e.currentTarget);
  }, []);

  const handleClose = useCallback(() => {
    setAnchorEl(null);
  }, []);

  const selected = parseVariantList(scope);
  const selectedSet = new Set(selected);
  // The single variant authoring targets. Only then does "show disabled rows"
  // mean anything (a composition is a read-only preview; Base has nothing to
  // ghost), so the eye toggle is rendered only on that variant's row.
  const editVariant = selected.length === 1 ? selected[0] : null;

  // Base clears the whole selection (and closes the menu).
  const handlePickBase = useCallback(() => {
    onScopeChange(null);
    setAnchorEl(null);
  }, [onScopeChange]);

  // Toggling a variant keeps the menu open so several can be composed.
  const handleToggleVariant = useCallback(
    (name: string) => {
      const next = new Set(parseVariantList(scope));
      if (next.has(name)) next.delete(name);
      else next.add(name);
      onScopeChange(canonicalVariantName([...next]));
    },
    [onScopeChange, scope],
  );

  const fullLabel =
    selected.length === 0
      ? BASE_LABEL
      : selected.length === 1
        ? selected[0]
        : `${selected.length} variants`;
  const currentLabel = truncate(fullLabel);

  return (
    <Box sx={{ display: 'flex', alignItems: 'center' }}>
      <Button
        size="small"
        variant={selected.length === 0 ? 'outlined' : 'contained'}
        color={selected.length === 0 ? 'inherit' : 'primary'}
        endIcon={hasVariants ? <KeyboardArrowDownIcon fontSize="small" /> : null}
        onClick={hasVariants ? handleOpen : undefined}
        disabled={disabled}
        disableRipple={!hasVariants}
        title={fullLabel}
        sx={{
          width: CHIP_WIDTH,
          minWidth: CHIP_WIDTH,
          height: 32,
          justifyContent: 'space-between',
          whiteSpace: 'nowrap',
          fontSize: '0.75rem',
          textTransform: 'none',
          px: 1,
          cursor: hasVariants ? 'pointer' : 'default',
          '& .MuiButton-endIcon': { ml: 0.5 },
          '&:hover': hasVariants ? undefined : { backgroundColor: 'transparent' },
        }}
      >
        <Box
          component="span"
          sx={{ overflow: 'hidden', textOverflow: 'ellipsis', flex: 1, textAlign: 'left' }}
        >
          {currentLabel}
        </Box>
      </Button>
      <Menu
        anchorEl={anchorEl}
        open={open}
        onClose={handleClose}
        MenuListProps={{ dense: true }}
        // Composition multi-select is wider than the trigger so checkboxes +
        // long variant names fit; the trigger stays compact.
        slotProps={{ paper: { sx: { width: 220, minWidth: 220 } } }}
      >
        <MenuItem
          selected={selected.length === 0}
          onClick={handlePickBase}
          sx={{ fontSize: '0.75rem' }}
        >
          {BASE_LABEL}
        </MenuItem>
        <Divider sx={{ my: 0.25 }} />
        {variants.map((v) => (
          <MenuItem
            key={v.name}
            selected={selectedSet.has(v.name)}
            onClick={() => handleToggleVariant(v.name)}
            title={v.name}
            sx={{ fontSize: '0.75rem', py: 0 }}
          >
            <Checkbox
              size="small"
              checked={selectedSet.has(v.name)}
              tabIndex={-1}
              disableRipple
              sx={{ p: 0.5, mr: 0.5 }}
            />
            <Box
              component="span"
              sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}
            >
              {v.name}
            </Box>
            {/* Show/hide rows disabled on THIS variant — only on the active
                single variant. Stop propagation so it toggles visibility
                without flipping the variant selection or closing the menu. */}
            {onToggleShowDisabled && editVariant === v.name && (
              <Tooltip
                title={
                  showDisabled
                    ? 'Hide rows disabled on this variant'
                    : 'Show rows disabled on this variant (greyed — click one to restore)'
                }
              >
                <IconButton
                  size="small"
                  color={showDisabled ? 'primary' : 'default'}
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleShowDisabled();
                  }}
                  sx={{ ml: 0.5, p: 0.25 }}
                >
                  {showDisabled ? (
                    <VisibilityIcon fontSize="small" />
                  ) : (
                    <VisibilityOffIcon fontSize="small" />
                  )}
                </IconButton>
              </Tooltip>
            )}
          </MenuItem>
        ))}
      </Menu>
    </Box>
  );
};

export default NavigationViewingScopeChip;
