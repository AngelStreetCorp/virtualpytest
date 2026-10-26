import { KeyboardArrowDown, OpenInNew } from '@mui/icons-material';
import { Button, Chip, Menu, MenuItem, Box, Typography, IconButton, Tooltip } from '@mui/material';
import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { getNavVisibility } from '../../config/featureFlags';
import { useTheme } from '../../contexts/ThemeContext';
import { useWorkspaceContext } from '../../contexts/workspace/WorkspaceContext';
import { useI18n } from '../../i18n/useI18n';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { NavigationDropdownProps, NavigationItem } from '../../types/pages/Navigation_Types';
import { navItemSx, NavLabel } from './Navigation_ItemStyle';

const NavigationDropdown: React.FC<NavigationDropdownProps> = ({ label, items, footer, minWidth = 240 }) => {
  const { menuIconColourResolved: menuIconColour } = useTheme();
  const { t } = useI18n();
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const { isPathHidden } = useWorkspaceContext();
  const open = Boolean(anchorEl);
  // Subscribe to palette changes so `navItemSx` re-reads `P.navHover` when the theme switches.
  useAgentChatPalette();

  // One visibility key per item: its full route path. Workspace hides win
  // over env-level flags; beyond that, env HIDDEN > COMING_SOON > DISABLED.
  //
  // Defensive: a malformed feature-contributed nav item (no `path`) would
  // crash `requiredPermissionForPath` on `path.startsWith` and take the whole
  // top bar down with it (page error boundary shows the bare chrome, no nav).
  // Skip the visibility + active-highlight logic for those rows and just
  // surface them as visible — `renderMenuItem` already gates on `path` for
  // the navigation path, so an action-only item with `onSelect` still works.
  const itemVisibility = (item: NavigationItem) => {
    if (item.isVisible && !item.isVisible()) return 'hidden';
    if (!item.path) return 'visible';
    if (isPathHidden(item.path)) return 'hidden';
    return getNavVisibility(item.path);
  };

  // Hide the entire dropdown if all items are hidden and there's no footer
  const hasVisibleItems = items.some((item) => itemVisibility(item) !== 'hidden');
  if (!hasVisibleItems && !footer) return null;

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleExternalClick = (href: string) => {
    window.open(href, '_blank', 'noopener,noreferrer');
    handleClose();
  };

  // Check if any of the dropdown items match the current path (only internal links).
  // Skip items with no `path` — action rows (`onSelect`) and broken entries
  // don't have one, and `pathname.startsWith(undefined)` returns false safely
  // in modern engines but the explicit guard keeps the read intent obvious.
  const isDropdownActive = items.some(
    (item) => !item.external && !item.onSelect && !!item.path && location.pathname.startsWith(item.path),
  );

  const renderMenuItem = (item: NavigationItem) => {
    const visibility = itemVisibility(item);

    if (visibility === 'hidden') return null;

    // A nav row needs SOMETHING to render: an action (onSelect), a destination
    // (path), or an external URL (href / externalHref). Items missing all four
    // would have no key and no target — skip them rather than fall through to
    // `<MenuItem to={undefined}>` which React Router throws on.
    if (!item.onSelect && !item.path && !item.href && !item.externalHref) return null;

    if (visibility === 'coming-soon') {
      return (
        <MenuItem key={item.path} disabled sx={{ py: 1.5, px: 2 }}>
          <Box display="flex" alignItems="center" gap={1} width="100%">
            {item.icon}
            <Typography variant="body2" sx={{ flex: 1 }}>{t(item.label)}</Typography>
            <Chip label={t('Soon')} color="default" size="small" />
          </Box>
        </MenuItem>
      );
    }

    if (visibility === 'disabled') {
      return (
        <MenuItem key={item.path} disabled sx={{ py: 1.5, px: 2 }}>
          <Box display="flex" alignItems="center" gap={1} width="100%">
            {item.icon}
            <Typography variant="body2" sx={{ flex: 1 }}>{t(item.label)}</Typography>
          </Box>
        </MenuItem>
      );
    }

    if (item.onSelect) {
      // Action row (a feature's dialog, say): runs the callback, no navigation.
      const run = item.onSelect;
      return (
        <MenuItem key={item.path} onClick={() => { handleClose(); run(); }} sx={{ py: 1.5, px: 2 }}>
          <Box display="flex" alignItems="center" gap={1}>
            {item.icon}
            <Typography variant="body2">{t(item.label)}</Typography>
          </Box>
        </MenuItem>
      );
    }

    if (item.external && item.href) {
      // External link - opens in new tab
      return (
        <MenuItem
          key={item.href}
          onClick={() => handleExternalClick(item.href!)}
          sx={{ py: 1.5, px: 2 }}
        >
          <Box display="flex" alignItems="center" gap={1} width="100%">
            {item.icon}
            <Typography variant="body2" sx={{ flex: 1 }}>{t(item.label)}</Typography>
            <OpenInNew fontSize="small" sx={{ opacity: 0.5, ml: 1 }} />
          </Box>
        </MenuItem>
      );
    }

    if (item.externalHref) {
      return (
        <MenuItem
          key={item.path}
          onClick={() => { navigate(item.path); handleClose(); }}
          sx={{ py: 1.5, px: 2 }}
        >
          <Box display="flex" alignItems="center" gap={1} width="100%">
            {item.icon}
            <Typography variant="body2" sx={{ flex: 1 }}>{t(item.label)}</Typography>
            <Tooltip title={t('Open {label} instance', { label: t(item.label) })}>
              <IconButton
                size="small"
                aria-label={t('Open {label} instance', { label: t(item.label) })}
                onClick={(event) => {
                  event.stopPropagation();
                  window.open(item.externalHref, '_blank', 'noopener,noreferrer');
                  handleClose();
                }}
                sx={{ p: 0.5, mr: -0.5 }}
              >
                <OpenInNew fontSize="small" sx={{ opacity: 0.6 }} />
              </IconButton>
            </Tooltip>
          </Box>
        </MenuItem>
      );
    }

    // Internal link - uses React Router
    return (
      <MenuItem
        key={item.path}
        component={Link}
        to={item.path}
        onClick={handleClose}
        selected={location.pathname === item.path}
        sx={{
          py: 1.5,
          // Keep large desktop navbar spacing to match design baseline (do not reduce/remove).
          px: 2,
        }}
      >
        <Box display="flex" alignItems="center" gap={1}>
          {item.icon}
          <Typography variant="body2">{t(item.label)}</Typography>
        </Box>
      </MenuItem>
    );
  };

  return (
    <>
      <Button
        onClick={handleClick}
        endIcon={<KeyboardArrowDown />}
        sx={navItemSx(isDropdownActive)}
      >
        <NavLabel text={label} />
      </Button>
      <Menu
        anchorEl={anchorEl}
        open={open}
        onClose={handleClose}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'left',
        }}
        transformOrigin={{
          vertical: 'top',
          horizontal: 'left',
        }}
        PaperProps={{
          sx: {
            mt: 1,
            // `minWidth` so the menu is sized to the widest locale by default
            // (DE "Dokumentation" ~232px, FR "IA" ~228px) — switching language
            // never resizes the menu — but a wider footer (e.g. PreferencesRows
            // with its 292 px minWidth) can still push the menu to grow. The
            // rendered width is max(minWidth, content width).
            minWidth,
            boxShadow: '0 4px 20px rgba(0,0,0,0.1)',
            // Menu icon colour (Edit background → Icons); the item icon is the first svg of the row Box.
            ...(menuIconColour && { '& .MuiMenuItem-root > .MuiBox-root > .MuiSvgIcon-root:first-of-type': { color: menuIconColour } }),
          },
        }}
      >
        {items.map(renderMenuItem)}
        {footer}
      </Menu>
    </>
  );
};

export default NavigationDropdown;
