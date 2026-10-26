import React, { useState, useEffect, useRef } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Box, CircularProgress, Typography } from '@mui/material';
import { useAuth } from '../../hooks/auth/useAuth';
import { usePermissions } from '../../hooks/auth/usePermissions';
import { useProfile } from '../../hooks/auth/useProfile';
import { Permission, Role, requiredPermissionForPath } from '../../types/auth';
import { isAuthEnabled } from '../../lib/supabase';
import PageSkeleton from '../common/PageSkeleton';

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
 * The gate itself. Only mounted when auth is enabled, so every hook below runs
 * unconditionally.
 *
 * This is split out rather than guarded by an early return inside one component:
 * `isAuthEnabled` is a module constant, so an early return above the hooks is
 * stable in practice, but it is still a conditional hook call as far as
 * react-hooks/rules-of-hooks can tell — and that one pattern is why the rule was
 * switched off repo-wide. Moving the branch to a wrapper that renders either this
 * or its children keeps the behaviour identical and the hooks checkable.
 */
const AuthGate: React.FC<ProtectedRouteProps> = ({
  children,
  requiredRole,
  requiredPermission,
  requiredPlatformAdmin,
  fallbackPath = '/login',
}) => {
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { hasRole, canAccess, isLoading: permissionsLoading } = usePermissions();
  const isLoading = authLoading || permissionsLoading;
  const { isPlatformAdmin } = useProfile();
  const location = useLocation();
  const [showLoading, setShowLoading] = useState(false);
  // The skeleton is only for the FIRST resolution, i.e. the app boot. `permissionsLoading` can
  // flip back to true on a later navigation (useRoles refetching role defaults), and a skeleton
  // then would replace content the user is already reading. Once we have rendered real content
  // for this mount, later waits go back to rendering nothing rather than erasing the page.
  const awaitingFirstContent = useRef(true);

  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (isLoading) {
      // Delay showing the loading spinner to prevent flashing on fast loads.
      // 1500ms, not 500ms: AuthContext only clears its flag after a PROFILE round trip, so
      // a remote load routinely sits in the 600ms–1s range. At 500ms this message fired just
      // before the real content landed, replacing one loading screen with another. Hold it
      // back until the wait is long enough that silence would look like a hang.
      timer = setTimeout(() => setShowLoading(true), 1500);
    } else {
      setShowLoading(false);
    }
    return () => clearTimeout(timer);
  }, [isLoading]);

  useEffect(() => {
    if (!isLoading) awaitingFirstContent.current = false;
  }, [isLoading]);

  // Show loading spinner while checking auth
  if (isLoading) {
    // Hold the area with a neutral placeholder instead of nothing, so the first paint is
    // "app frame + page-shaped placeholder" -> "app frame + content" rather than
    // "app frame + void" -> "app frame + content".
    if (!showLoading) return awaitingFirstContent.current ? <PageSkeleton /> : null;

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

  // Check permission requirement: the route's own, else the page's entry in PAGE_PERMISSIONS
  // (the same table the nav uses to hide the page).
  const neededPermission = requiredPermission ?? requiredPermissionForPath(location.pathname);
  if (neededPermission && !canAccess(neededPermission)) {
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
          {Array.isArray(neededPermission)
            ? neededPermission.join(' or ')
            : neededPermission}
        </Typography>
      </Box>
    );
  }

  // Render children or Outlet
  return children ? <>{children}</> : <Outlet />;
};

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
export const ProtectedRoute: React.FC<ProtectedRouteProps> = (props) => {
  // Auth disabled: everything is public, and none of the auth hooks should run.
  if (!isAuthEnabled) {
    return props.children ? <>{props.children}</> : <Outlet />;
  }
  return <AuthGate {...props} />;
};

