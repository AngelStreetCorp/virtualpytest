/**
 * Wraps the router's <Suspense><Routes>...</Routes></Suspense>. Nothing in the app previously
 * caught a render-time error, so any uncaught throw in one page (including a lazy-loaded
 * optional-feature page) unmounted the ENTIRE React tree — a fully blank screen (just the
 * body's background colour) with no header, no bottom nav, no way back short of a manual
 * reload. This keeps the persistent app chrome (AppHeader, MobileBottomNav — both siblings of
 * this boundary in App.tsx, not descendants) alive and gives the user a way out.
 *
 * The functional wrapper exists only to read the route via `useLocation()` (the class
 * component itself can't use hooks) and key the class instance by pathname, so navigating
 * away — even via the surviving bottom nav — remounts a clean boundary instead of leaving a
 * stale error screen glued to the next page.
 */
import { Box, Button, Typography } from '@mui/material';
import React from 'react';
import { useLocation } from 'react-router-dom';

interface State {
  error: Error | null;
}

class RouteErrorBoundaryImpl extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[RouteErrorBoundary] page crashed:', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (error) {
      return (
        <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 1.5, alignItems: 'flex-start' }}>
          <Typography variant="h6">This page hit an error</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-word' }}>
            {error.message || 'Unknown error'}
          </Typography>
          <Button variant="contained" size="small" onClick={() => this.setState({ error: null })}>
            Try again
          </Button>
        </Box>
      );
    }
    return this.props.children;
  }
}

export function RouteErrorBoundary({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();
  return <RouteErrorBoundaryImpl key={pathname}>{children}</RouteErrorBoundaryImpl>;
}
