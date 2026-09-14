/**
 * Navigation_VariantToggle (Phase 3 — simplified)
 *
 * Per-row variant scope selector inside Edit Node / Edit Edge dialogs.
 *
 * Layout:
 *   [ <current scope> ▾ ]   single button + dropdown
 *
 * Click → dropdown of `Base` plus every registered variant. Picking an
 * option switches what the dialog body renders/edits; Save routes by the
 * selected scope.
 *
 * Why a dropdown instead of a segmented toggle: variant counts can grow,
 * and a single fixed-width button keeps the dialog header layout stable
 * when scopes are switched (no reflow flash from wrapping segments).
 *
 * No inline create, no kebab — variant creation is restricted to the
 * userinterface settings (§3.1); per-row replicate is the header
 * `Replicate` icon (§3.7).
 *
 * The component is fully controlled via `selectedScope` /
 * `onSelectedScopeChange`. It does not mutate `variant_overrides`.
 *
 * See docs/agent/ENHANCE_VARIANT.md §3.2.
 */

import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import { Box, Button, Menu, MenuItem, Tooltip } from '@mui/material';
import React, { useCallback, useMemo, useState } from 'react';

export type VariantScope = 'base' | string;

interface Navigation_VariantToggleProps {
  /**
   * Registered variants for the current userinterface. The dropdown always
   * shows `Base` plus one item per registered variant. With per-variant
   * overrides on the variant row (not on the node/edge row), this is the
   * sole source of segment names — there is no per-row entry list anymore.
   */
  registeredVariantNames: string[];
  selectedScope: VariantScope;
  onSelectedScopeChange: (next: VariantScope) => void;
  disabled?: boolean;
  /**
   * Grey out the Base menu item — e.g. a variant-only row (hidden_in_base)
   * has no base version to edit, so Base isn't a valid scope for it. The
   * current selection is unaffected.
   */
  baseDisabled?: boolean;
  /** Tooltip shown on the disabled Base item explaining why. */
  baseDisabledReason?: string;
}

const BASE_LABEL = 'Base';

export const Navigation_VariantToggle: React.FC<Navigation_VariantToggleProps> = ({
  registeredVariantNames,
  selectedScope,
  onSelectedScopeChange,
  disabled = false,
  baseDisabled = false,
  baseDisabledReason = '',
}) => {
  // Dedupe defensively. Variant names are user-typed in the registry.
  const segmentNames = useMemo<string[]>(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const name of registeredVariantNames) {
      if (!name || seen.has(name)) continue;
      seen.add(name);
      out.push(name);
    }
    return out;
  }, [registeredVariantNames]);

  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const open = Boolean(anchorEl);

  const handleOpen = useCallback((e: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(e.currentTarget);
  }, []);

  const handleClose = useCallback(() => {
    setAnchorEl(null);
  }, []);

  const handlePick = useCallback(
    (next: VariantScope) => {
      setAnchorEl(null);
      if (next === selectedScope) return;
      onSelectedScopeChange(next);
    },
    [selectedScope, onSelectedScopeChange],
  );

  const currentLabel = selectedScope === 'base' ? BASE_LABEL : selectedScope;

  return (
    <Box sx={{ display: 'flex', alignItems: 'center' }}>
      <Button
        size="small"
        variant={selectedScope === 'base' ? 'outlined' : 'contained'}
        color={selectedScope === 'base' ? 'inherit' : 'primary'}
        endIcon={<KeyboardArrowDownIcon fontSize="small" />}
        onClick={handleOpen}
        disabled={disabled}
        sx={{
          minWidth: 'auto',
          whiteSpace: 'nowrap',
          fontSize: '0.7rem',
          textTransform: 'none',
          py: 0.25,
          px: 1,
          fontFamily:
            'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace',
        }}
      >
        {currentLabel}
      </Button>
      <Menu
        anchorEl={anchorEl}
        open={open}
        onClose={handleClose}
        MenuListProps={{ dense: true }}
        // Anchor the menu *below* the button without resizing the parent.
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        keepMounted
      >
        <Tooltip title={baseDisabled ? baseDisabledReason : ''} placement="left">
          <span>
            <MenuItem
              selected={selectedScope === 'base'}
              disabled={baseDisabled}
              onClick={() => handlePick('base')}
            >
              {BASE_LABEL}
            </MenuItem>
          </span>
        </Tooltip>
        {segmentNames.map((name) => (
          <MenuItem
            key={name}
            selected={selectedScope === name}
            onClick={() => handlePick(name)}
            sx={{
              fontFamily:
                'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace',
            }}
          >
            {name}
          </MenuItem>
        ))}
      </Menu>
    </Box>
  );
};

export default Navigation_VariantToggle;
