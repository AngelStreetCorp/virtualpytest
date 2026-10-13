/**
 * Redirects from the report pages that became tabs (TASK-42 follow-up) to their tab.
 * Other query parameters (window, archived, status, …) are kept, so old deep links and
 * bookmarks still land on the same view.
 */

import React from 'react';
import { Navigate, useLocation, useParams } from 'react-router-dom';

import { QUALITY_TABS, type QualityTab, type RunManagementTab } from '../../types/reports';

const withTab = (path: string, search: string, tab: string) => {
  const params = new URLSearchParams(search);
  params.set('tab', tab);
  return `${path}?${params.toString()}`;
};

/** /test-results/quality/:tab (flaky | slow | not-executed) → /test-results/quality?tab=… */
export const QualityTabRedirect: React.FC = () => {
  const { tab } = useParams();
  const { search } = useLocation();
  const target: QualityTab = (QUALITY_TABS as readonly string[]).includes(tab ?? '') ? (tab as QualityTab) : 'flaky';
  return <Navigate to={withTab('/test-results/quality', search, target)} replace />;
};

/** /test-results/groups, /milestones, /labels, … → /test-results/run-management?tab=… */
export const RunManagementTabRedirect: React.FC<{ tab: RunManagementTab }> = ({ tab }) => {
  const { search } = useLocation();
  return <Navigate to={withTab('/test-results/run-management', search, tab)} replace />;
};
