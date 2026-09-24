import React, { useState } from 'react';
import {
  Box,
  IconButton,
  Menu,
  MenuItem,
  Avatar,
  Typography,
  Divider,
  ListItemIcon,
  ListItemText,
  Chip,
} from '@mui/material';
import {
  Logout as LogoutIcon,
  Groups as TeamsIcon,
  People as UsersIcon,
  WorkspacesOutlined as WorkspacesIcon,
  Apartment as TenantIcon,
} from '@mui/icons-material';
import { useAuth } from '../../hooks/auth/useAuth';
import { useProfile } from '../../hooks/auth/useProfile';
import { useNavigate } from 'react-router-dom';
import { isAuthEnabled } from '../../lib/supabase';

export const UserMenu: React.FC = () => {
  const { user, signOut } = useAuth();
  const { profile, isPlatformAdmin } = useProfile();
  const navigate = useNavigate();
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);

  const isAdmin = profile?.role === 'admin';

  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleMenuClose = () => {
    setAnchorEl(null);
  };

  const handleTenants = () => {
    handleMenuClose();
    navigate('/tenants');
  };

  const handleTeams = () => {
    handleMenuClose();
    navigate('/teams');
  };

  const handleUsers = () => {
    handleMenuClose();
    navigate('/users');
  };

  const handleWorkspaces = () => {
    handleMenuClose();
    navigate('/workspaces');
  };

  const handleLogout = async () => {
    handleMenuClose();
    try {
      await signOut();
      navigate('/login');
    } catch (error) {
      console.error('Logout error:', error);
    }
  };

  if (!isAuthEnabled || !user) {
    return null;
  }

  const displayName = profile?.full_name || user.email?.split('@')[0] || 'User';
  const avatarUrl = profile?.avatar_url || user.user_metadata?.avatar_url;

  return (
    <Box>
      <IconButton onClick={handleMenuOpen} size="small">
        <Avatar
          src={avatarUrl}
          alt={displayName}
          sx={{
            width: 32,
            height: 32,
            bgcolor: 'primary.main',
          }}
        >
          {displayName.charAt(0).toUpperCase()}
        </Avatar>
      </IconButton>

      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={handleMenuClose}
        onClick={handleMenuClose}
        transformOrigin={{ horizontal: 'right', vertical: 'top' }}
        anchorOrigin={{ horizontal: 'right', vertical: 'bottom' }}
        PaperProps={{
          sx: { minWidth: 240, mt: 1 },
        }}
      >
        <Box sx={{ px: 2, py: 1.5 }}>
          <Typography variant="subtitle2" fontWeight="bold">
            {displayName}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {user.email}
          </Typography>
          {profile?.role && (
            <Chip
              label={profile.role.toUpperCase()}
              size="small"
              color={profile.role === 'admin' ? 'error' : profile.role === 'tester' ? 'primary' : 'default'}
              sx={{ mt: 1 }}
            />
          )}
        </Box>

        <Divider />

        {/* TASK-23: Tenants entry is super-admin only, sits above Teams
            in the dropdown so the platform-owner surface is grouped together. */}
        {isPlatformAdmin && (
          <MenuItem onClick={handleTenants}>
            <ListItemIcon>
              <TenantIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Tenants</ListItemText>
          </MenuItem>
        )}

        {isAdmin && (
          <MenuItem onClick={handleTeams}>
            <ListItemIcon>
              <TeamsIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Teams</ListItemText>
          </MenuItem>
        )}

        {isAdmin && (
          <MenuItem onClick={handleUsers}>
            <ListItemIcon>
              <UsersIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Users</ListItemText>
          </MenuItem>
        )}

        {isAdmin && (
          <MenuItem onClick={handleWorkspaces}>
            <ListItemIcon>
              <WorkspacesIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Workspaces</ListItemText>
          </MenuItem>
        )}

        <Divider />

        <MenuItem onClick={handleLogout}>
          <ListItemIcon>
            <LogoutIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Logout</ListItemText>
        </MenuItem>
      </Menu>
    </Box>
  );
};
