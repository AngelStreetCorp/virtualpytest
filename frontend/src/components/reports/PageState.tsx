/**
 * Loading / forbidden / not-found / error states shared by the run-management pages.
 * `loading` is a boolean gate, never "the list is empty" (an empty list is an answer).
 */

import { Alert, Box, CircularProgress, Typography } from '@mui/material';
import React from 'react';

import { describeError, isApiError } from '../../hooks/reports/runManagementApi';

export interface QueryStateProps {
  loading: boolean;
  error: unknown;
  children: React.ReactNode;
}

export const QueryState: React.FC<QueryStateProps> = ({ loading, error, children }) => {
  if (loading) {
    return (
      <Box role="status" aria-label="Loading" sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress size={28} />
      </Box>
    );
  }
  if (error) {
    if (isApiError(error, 403)) {
      return (
        <Alert severity="warning" data-testid="state-forbidden">
          You do not have permission to view this.
        </Alert>
      );
    }
    if (isApiError(error, 404)) {
      return (
        <Alert severity="info" data-testid="state-not-found">
          Not found, or not visible in this team and workspace.
        </Alert>
      );
    }
    return (
      <Alert severity="error" data-testid="state-error">
        {describeError(error)}
      </Alert>
    );
  }
  return <>{children}</>;
};

export const EmptyState: React.FC<{ message: string; children?: React.ReactNode }> = ({ message, children }) => (
  <Box sx={{ textAlign: 'center', py: 5 }} data-testid="state-empty">
    <Typography variant="body2" color="text.secondary">
      {message}
    </Typography>
    {children}
  </Box>
);

/** Page shell: padded column that never scrolls horizontally on a phone. */
export const ReportPage: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Box sx={{ width: '100%', maxWidth: '100%', minWidth: 0, overflowX: 'hidden', py: 2, px: { xs: 1, sm: 0 } }}>
    {children}
  </Box>
);
