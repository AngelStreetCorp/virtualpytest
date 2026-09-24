import React, { useState, useEffect } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Box, CircularProgress, Typography } from '@mui/material';
import { useAuth } from '../../hooks/auth/useAuth';
import { usePermissions } from '../../hooks/auth/usePermissions';
import { useProfile } from '../../hooks/auth/useProfile';
import { Permission, Role } from '../../types/auth';
import { isAuthEnabled } from '../../lib/supabase';

interface ProtectedRouteProps {
  children?: React.ReactNode;
  requiredRole?: Role | Role[];
  requiredPermission?: Permission | Permission[];
  // TASK-23: super-admin gate. When true, only users with
    // profile.is_platform_admin === true get through — even role='admin' is not
    // enough. Use for tenant-related routes that regular admins must not see.
  requiredPlatformAdmin?: boolean;
  fallbackPath?: string;
}

/**
 * Protected Route Component
 * Wraps routes that require authentication and/or specific permissions
 * 
 * @example
 * // Require authentication only
 * <Route element={<ProtectedRoute />}>
 *   <Route path="/dashboard" element={<Dashboard />} />
 * </Route>
 * 
 * @example
 * // Require specific role
 * <Route element={<ProtectedRoute requiredRole="admin" />}>
 *   <Route path="/settings" element={<Settings />} />
 * </Route>
 * 
 * @example
 * // Require specific permission
 * <Route element={<ProtectedRoute requiredPermission="api_testing" />}>
 *   <Route path="/api/workspaces" element={<ApiWorkspaces />} />
 * </Route>
 */
export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  requiredRole,
  requiredPermission,
  requiredPlatformAdmin,
  fallbackPath = '/login',
}) => {
  // If auth is disabled, allow access to everything - skip auth hooks entirely
  if (!isAuthEnabled) {
    return children ? <>{children}</> : <Outlet />;
  }

  // Auth is enabled - now we need to check authentication state
  const { isAuthenticated, isLoading } = useAuth();
  const { hasRole, canAccess } = usePermissions();
  const { isPlatformAdmin } = useProfile();
  const location = useLocation();
  const [showLoading, setShowLoading] = useState(false);

  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (isLoading) {
      // Delay showing the loading spinner to prevent flashing on fast loads
      timer = setTimeout(() => setShowLoading(true), 500);
    } else {
      setShowLoading(false);
    }
    return () => clearTimeout(timer);
  }, [isLoading]);

  // Show loading spinner while checking auth
  if (isLoading) {
    // Return null (blank) until the delay passes, then show spinner
    if (!showLoading) return null;
    
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '60vh',
          gap: 2,
        }}
      >
        <CircularProgress />
        <Typography variant="body2" color="text.secondary">
          Checking authentication...
        </Typography>
      </Box>
    );
  }

  // Redirect to login if not authenticated
  if (!isAuthenticated) {
    return <Navigate to={fallbackPath} state={{ from: location }} replace />;
  }

  // Check role requirement
  if (requiredRole && !hasRole(requiredRole)) {
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '60vh',
          gap: 2,
          textAlign: 'center',
        }}
      >
        <Typography variant="h4" color="error.main">
          Access Denied
        </Typography>
        <Typography variant="body1" color="text.secondary">
          You don't have the required role to access this page.
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Required role: {Array.isArray(requiredRole) ? requiredRole.join(' or ') : requiredRole}
        </Typography>
      </Box>
    );
  }

  // TASK-23: platform-admin gate. Refuses role='admin' too — Q3 says regular
  // admins must not even see this route exists.
  if (requiredPlatformAdmin && !isPlatformAdmin) {
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '60vh',
          gap: 2,
          textAlign: 'center',
        }}
      >
        <Typography variant="h4" color="error.main">
          Access Denied
        </Typography>
        <Typography variant="body1" color="text.secondary">
          This page requires platform-admin (super admin) access.
        </Typography>
      </Box>
    );
  }

  // Check permission requirement
  if (requiredPermission && !canAccess(requiredPermission)) {
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '60vh',
          gap: 2,
          textAlign: 'center',
        }}
      >
        <Typography variant="h4" color="error.main">
          Access Denied
        </Typography>
        <Typography variant="body1" color="text.secondary">
          You don't have permission to access this page.
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Required permission:{' '}
          {Array.isArray(requiredPermission)
            ? requiredPermission.join(' or ')
            : requiredPermission}
        </Typography>
      </Box>
    );
  }

  // Render children or Outlet
  return children ? <>{children}</> : <Outlet />;
};

