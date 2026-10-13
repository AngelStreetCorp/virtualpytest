import { KeyboardArrowDown } from '@mui/icons-material';
import { Button, Menu, MenuItem, Box, Typography, Chip } from '@mui/material';
import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

import { getNavVisibility } from '../../config/featureFlags';
import { useWorkspaceContext } from '../../contexts/workspace/WorkspaceContext';
import { useI18n } from '../../i18n/useI18n';
import type { NavigationItem } from '../../types/pages/Navigation_Types';

import { NavigationGroupedDropdownProps } from '../../types/pages/Navigation_Types';
import { navItemSx } from './Navigation_ItemStyle';

const NavigationGroupedDropdown: React.FC<NavigationGroupedDropdownProps> = ({ label, groups }) => {
  const { t } = useI18n();
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const location = useLocation();
  const { isPathHidden } = useWorkspaceContext();
  const open = Boolean(anchorEl);

  // Workspace hidden_pages take precedence over env-level flags.
  const itemVisibility = (item: NavigationItem) =>
    isPathHidden(item.path) ? 'hidden' : getNavVisibility(item.path);

  // Filter out sections where all children are hidden
  const visibleGroups = groups.filter((group) =>
    group.items.some((item) => itemVisibility(item) !== 'hidden'),
  );

  // Hide the entire dropdown if no sections have visible items
  if (visibleGroups.length === 0) return null;

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  // Check if any of the grouped items match the current path
  const isDropdownActive = visibleGroups.some((group) =>
    group.items.some((item) => location.pathname.startsWith(item.path))
  );

  return (
    <>
      <Button
        onClick={handleClick}
        endIcon={<KeyboardArrowDown />}
        sx={navItemSx(isDropdownActive)}
      >
        {label}
      </Button>
      <Menu
        anchorEl={anchorEl}
        open={open}
        onClose={handleClose}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'center',
        }}
        transformOrigin={{
          vertical: 'top',
          horizontal: 'center',
        }}
        PaperProps={{
          sx: {
            mt: 1,
            minWidth: Math.min(800, visibleGroups.length * 200),
            maxWidth: 960,
            boxShadow: '0 4px 20px rgba(0,0,0,0.1)',
          },
        }}
      >
        {/* Four-column grid layout */}
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: `repeat(${visibleGroups.length}, 1fr)`,
            gap: 0,
            p: 0,
          }}
        >
          {visibleGroups.map((group, groupIndex) => (
            <Box
              key={t(group.sectionLabel)}
              sx={{
                borderRight: groupIndex < visibleGroups.length - 1 ? '1px solid rgba(0, 0, 0, 0.08)' : 'none',
              }}
            >
              {/* Section Header */}
              <Box
                sx={{
                  px: 2,
                  py: 0.75,
                  backgroundColor: 'rgba(0, 0, 0, 0.03)',
                  borderBottom: '1px solid rgba(0, 0, 0, 0.08)',
                }}
              >
                <Typography
                  variant="caption"
                  sx={{
                    fontWeight: 700,
                    fontSize: '0.7rem',
                    letterSpacing: '0.5px',
                    color: 'text.secondary',
                    textTransform: 'uppercase',
                  }}
                >
                  {t(group.sectionLabel)}
                </Typography>
              </Box>

              {/* Section Items */}
              {group.items.map((item) => {
                const visibility = itemVisibility(item);
                if (visibility === 'hidden') return null;
                const isDisabled = visibility === 'disabled' || visibility === 'coming-soon';
                return (
                  <MenuItem
                    key={item.path}
                    component={isDisabled ? 'div' : Link}
                    to={isDisabled ? undefined : item.path}
                    onClick={isDisabled ? undefined : handleClose}
                    disabled={isDisabled}
                    selected={location.pathname === item.path}
                    sx={{
                      py: 0.75,
                      px: 2,
                      fontSize: '0.875rem',
                      opacity: isDisabled ? 0.5 : 1,
                      cursor: isDisabled ? 'default' : 'pointer',
                    }}
                  >
                    <Box display="flex" alignItems="center" gap={1} width="100%">
                      {item.icon}
                      <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>
                        {t(item.label)}
                      </Typography>
                      {visibility === 'coming-soon' && (
                        <Chip label={t('Soon')} size="small" sx={{ ml: 'auto', height: 16, fontSize: '0.6rem' }} />
                      )}
                    </Box>
                  </MenuItem>
                );
              })}
            </Box>
          ))}
        </Box>
      </Menu>
    </>
  );
};

export default NavigationGroupedDropdown;
