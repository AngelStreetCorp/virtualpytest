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
  AdminPanelSettings as RolesIcon,
  WorkspacesOutlined as WorkspacesIcon,
  Apartment as TenantIcon,
} from '@mui/icons-material';
import { useAuth } from '../../hooks/auth/useAuth';
import { usePermissions } from '../../hooks/auth/usePermissions';
import { useProfile } from '../../hooks/auth/useProfile';
import { useRoles } from '../../hooks/pages/useRoles';
import { useNavigate } from 'react-router-dom';
import { isAuthEnabled } from '../../lib/supabase';
import { useI18n } from '../../i18n/useI18n';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

export const UserMenu: React.FC = () => {
  const P = useAgentChatPalette();
  const { user, signOut } = useAuth();
  const { profile, isPlatformAdmin } = useProfile();
  const navigate = useNavigate();
  const { t } = useI18n();
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);

  const { canAccess } = usePermissions();
  const { roleLabel } = useRoles();

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

  const handleRoles = () => {
    handleMenuClose();
    navigate('/roles');
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

  const displayName = profile?.full_name || user.email?.split('@')[0] || t('User');
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
            bgcolor: P.accent,
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
              label={roleLabel(profile.role)}
              size="small"
              color={profile.role === 'admin' ? 'error' : profile.role === 'viewer' ? 'default' : 'primary'}
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
            <ListItemText>{t('Tenants')}</ListItemText>
          </MenuItem>
        )}

        {canAccess('org.teams:view') && (
          <MenuItem onClick={handleTeams}>
            <ListItemIcon>
              <TeamsIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>{t('Teams')}</ListItemText>
          </MenuItem>
        )}

        {canAccess('org.users:view') && (
          <MenuItem onClick={handleUsers}>
            <ListItemIcon>
              <UsersIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>{t('Users')}</ListItemText>
          </MenuItem>
        )}

        {canAccess('org.roles:view') && (
          <MenuItem onClick={handleRoles}>
            <ListItemIcon>
              <RolesIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>{t('Roles')}</ListItemText>
          </MenuItem>
        )}

        {canAccess('org.workspaces:view') && (
          <MenuItem onClick={handleWorkspaces}>
            <ListItemIcon>
              <WorkspacesIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>{t('Workspaces')}</ListItemText>
          </MenuItem>
        )}

        <Divider />

        <MenuItem onClick={handleLogout}>
          <ListItemIcon>
            <LogoutIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t('Logout')}</ListItemText>
        </MenuItem>
      </Menu>
    </Box>
  );
};
