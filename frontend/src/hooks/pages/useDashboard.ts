import { useState, useCallback, useEffect, useRef } from 'react';
import { buildSelectedServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { useServerManager } from '../useServerManager';
import { useAuth } from '../auth/useAuth';
import { isAuthEnabled } from '../../lib/supabase';
import { TestCase, Campaign, Tree } from '../../types';
import { DashboardStats, RecentActivity } from '../../types/pages/Dashboard_Types';

// Cache configuration (30 second TTL for dashboard stats)
const CACHE_TTL_MS = 30000; // 30 seconds
let dashboardCache: {
  data: DashboardStats;
  timestamp: number;
  serverKey: string;
} | null = null;

export interface UseDashboardReturn {
  // Data
  stats: DashboardStats;
  
  // Loading states
  loading: boolean;
  error: string | null;
  isRequestInProgress: boolean;
  
  // Actions
  refreshData: () => Promise<void>;
}

export const useDashboard = (): UseDashboardReturn => {
  const { selectedServer } = useServerManager();
  const { isAuthenticated } = useAuth();
  const canFetch = !isAuthEnabled || isAuthenticated;
  const [stats, setStats] = useState<DashboardStats>({
    testCases: 0,
    campaigns: 0,
    trees: 0,
    recentActivity: [],
  });
  
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRequestInProgress, setIsRequestInProgress] = useState(false);
  
  // Use ref to track the current selectedServer to avoid dependency issues
  const selectedServerRef = useRef(selectedServer);
  selectedServerRef.current = selectedServer;
  
  // Debug: Log when selectedServer changes
  useEffect(() => {
    console.log('[@useDashboard] selectedServer changed to:', selectedServer);
  }, [selectedServer]);

  const fetchDashboardData = useCallback(async () => {
    // Prevent duplicate calls
    if (isRequestInProgress) {
      console.log('[@useDashboard] Request already in progress, skipping duplicate call');
      return;
    }
    
    // Don't proceed if no selected server yet
    if (!selectedServerRef.current) {
      console.log('[@useDashboard] No selected server yet, skipping fetch');
      return;
    }

    // Don't fetch when auth is enabled but user isn't authenticated
    if (!canFetch) {
      return;
    }
    
    // Check cache FIRST (before setting loading state)
    const serverKey = selectedServerRef.current;
    const now = Date.now();
    
    if (dashboardCache && 
        dashboardCache.serverKey === serverKey && 
        (now - dashboardCache.timestamp) < CACHE_TTL_MS) {
      console.log(`[@useDashboard] Cache HIT (age: ${((now - dashboardCache.timestamp) / 1000).toFixed(1)}s)`);
      setStats(dashboardCache.data);
      setLoading(false);
      setError(null);
      return;
    }
    
    try {
      setIsRequestInProgress(true);
      setLoading(true);
      setError(null);
      
      // Fetch campaigns, testcases, trees using selected server
      const [campaignsResponse, testCasesResponse, treesResponse] = await Promise.all([
        api.get(buildSelectedServerUrl('/server/campaigns/getAllCampaigns', selectedServerRef.current)),
        api.get(buildSelectedServerUrl('/server/testcase/list', selectedServerRef.current)),
        api.get(buildSelectedServerUrl('/server/navigationTrees', selectedServerRef.current)), // Automatically includes team_id
      ]);

      let testCases: TestCase[] = [];
      let campaigns: Campaign[] = [];
      let trees: Tree[] = [];

      // api.get returns parsed data directly
      if (testCasesResponse?.success && testCasesResponse?.testcases) {
        testCases = testCasesResponse.testcases;
      }
      if (campaignsResponse?.success && campaignsResponse?.campaigns) {
        campaigns = campaignsResponse.campaigns;
      }
      if (treesResponse?.success && treesResponse?.trees) {
        trees = treesResponse.trees;
      }

      // Generate mock recent activity with proper RecentActivity type
      const recentActivity: RecentActivity[] = [
        ...testCases.slice(0, 3).map(
          (tc): RecentActivity => ({
            id: tc.test_id,
            type: 'test' as const,
            name: tc.name,
            status: 'success' as const,
            timestamp: new Date().toISOString(),
          }),
        ),
        ...campaigns.slice(0, 2).map(
          (c): RecentActivity => ({
            id: c.campaign_id,
            type: 'campaign' as const,
            name: c.campaign_name,
            status: 'pending' as const,
            timestamp: new Date().toISOString(),
          }),
        ),
      ].slice(0, 5);

      const newStats = {
        testCases: testCases.length,
        campaigns: campaigns.length,
        trees: trees.length,
        recentActivity,
      };
      
      setStats(newStats);
      
      // Update cache
      dashboardCache = {
        data: newStats,
        timestamp: Date.now(),
        serverKey,
      };
      console.log('[@useDashboard] Cache updated');
      
    } catch (err) {
      setError('Failed to fetch dashboard data');
      console.error('Failed to fetch dashboard data:', err);
    } finally {
      setLoading(false);
      setIsRequestInProgress(false);
    }
  }, [isRequestInProgress, canFetch]);

  const refreshData = useCallback(async () => {
    // Force refresh - invalidate cache
    console.log('[@useDashboard] Manual refresh - invalidating cache');
    dashboardCache = null;
    await fetchDashboardData();
  }, [fetchDashboardData]);

  // Load data on mount and when selectedServer/auth changes
  useEffect(() => {
    if (selectedServer && canFetch) {
      console.log('[@useDashboard] Selected server changed, refreshing data...');
      fetchDashboardData();
    }
  }, [selectedServer, canFetch]);

  return {
    // Data
    stats,
    
    // Loading states
    loading,
    error,
    isRequestInProgress,
    
    // Actions
    refreshData,
  };
};

