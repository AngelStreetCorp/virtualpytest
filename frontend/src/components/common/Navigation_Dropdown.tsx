import { KeyboardArrowDown, OpenInNew } from '@mui/icons-material';
import { Button, Chip, Menu, MenuItem, Box, Typography } from '@mui/material';
import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

import { getNavVisibility } from '../../config/featureFlags';
import { useWorkspaceContext } from '../../contexts/workspace/WorkspaceContext';
import { NavigationDropdownProps, NavigationItem } from '../../types/pages/Navigation_Types';

const NavigationDropdown: React.FC<NavigationDropdownProps> = ({ label, items, footer }) => {
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const location = useLocation();
  const { isPathHidden } = useWorkspaceContext();
  const open = Boolean(anchorEl);
  const navItemWidth = 108;

  // One visibility key per item: its full route path. Workspace hides win
  // over env-level flags; beyond that, env HIDDEN > COMING_SOON > DISABLED.
  const itemVisibility = (item: NavigationItem) =>
    isPathHidden(item.path) ? 'hidden' : getNavVisibility(item.path);

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

  // Check if any of the dropdown items match the current path (only internal links)
  const isDropdownActive = items.some((item) => !item.external && location.pathname.startsWith(item.path));

  const renderMenuItem = (item: NavigationItem) => {
    const visibility = itemVisibility(item);

    if (visibility === 'hidden') return null;

    if (visibility === 'coming-soon') {
      return (
        <MenuItem key={item.path} disabled sx={{ py: 1.5, px: 2 }}>
          <Box display="flex" alignItems="center" gap={1} width="100%">
            {item.icon}
            <Typography variant="body2" sx={{ flex: 1 }}>{item.label}</Typography>
            <Chip label="Soon" color="default" size="small" />
          </Box>
        </MenuItem>
      );
    }

    if (visibility === 'disabled') {
      return (
        <MenuItem key={item.path} disabled sx={{ py: 1.5, px: 2 }}>
          <Box display="flex" alignItems="center" gap={1} width="100%">
            {item.icon}
            <Typography variant="body2" sx={{ flex: 1 }}>{item.label}</Typography>
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
          sx={{
            py: 1.5,
            px: 2,
            '&:hover': {
              backgroundColor: 'action.hover',
            },
          }}
        >
          <Box display="flex" alignItems="center" gap={1} width="100%">
            {item.icon}
            <Typography variant="body2" sx={{ flex: 1 }}>{item.label}</Typography>
            <OpenInNew fontSize="small" sx={{ opacity: 0.5, ml: 1 }} />
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
        sx={{
          py: 1.5,
          // Keep large desktop navbar spacing to match design baseline (do not reduce/remove).
          px: 2,
          backgroundColor: location.pathname === item.path ? 'action.selected' : 'transparent',
          '&:hover': {
            backgroundColor: 'action.hover',
          },
        }}
      >
        <Box display="flex" alignItems="center" gap={1}>
          {item.icon}
          <Typography variant="body2">{item.label}</Typography>
        </Box>
      </MenuItem>
    );
  };

  return (
    <>
      <Button
        onClick={handleClick}
        endIcon={<KeyboardArrowDown />}
        sx={{
          color: isDropdownActive ? 'secondary.main' : 'inherit',
          fontWeight: isDropdownActive ? 600 : 400,
          minWidth: navItemWidth,
          flexShrink: 0,
          justifyContent: 'center',
          textTransform: 'none',
          px: 1,
          py: 0.875,
          textAlign: 'center',
          whiteSpace: 'nowrap',
          '&:hover': {
            backgroundColor: 'rgba(255, 255, 255, 0.1)',
          },
        }}
      >
        {label}
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
            minWidth: 200,
            boxShadow: '0 4px 20px rgba(0,0,0,0.1)',
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
