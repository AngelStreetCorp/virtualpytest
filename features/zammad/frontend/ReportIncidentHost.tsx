import React, { useEffect } from 'react';

import { useAuthContext } from '../../../frontend/src/contexts/auth/AuthContext';
import { ReportIncidentDialog } from './ReportIncidentDialog';
import {
  closeReportIncident,
  refreshReportEnabled,
  setReportEnabled,
  useReportIncidentState,
} from './reportIncident';

/**
 * Mounted once by core (FeatureDefinition.appOverlays). Owns the one "Open a ticket" dialog and
 * keeps the Enabled flag fresh: read after sign-in and again when the server picker moves, because the
 * switch is stored per server.
 */
export const ReportIncidentHost: React.FC = () => {
  const { isAuthenticated } = useAuthContext();
  const { isOpen, options, reportEnabled } = useReportIncidentState();
  const signedIn = isAuthenticated;

  useEffect(() => {
    if (!signedIn) {
      setReportEnabled(false);
      return undefined;
    }
    refreshReportEnabled();
    window.addEventListener('vpt:server-changed', refreshReportEnabled);
    return () => window.removeEventListener('vpt:server-changed', refreshReportEnabled);
  }, [signedIn]);

  if (!reportEnabled) return null;
  return <ReportIncidentDialog open={isOpen} options={options} onClose={closeReportIncident} />;
};

export default ReportIncidentHost;
