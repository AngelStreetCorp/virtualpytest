/**
 * Navigation Screenshot Context
 * 
 * Provides batched screenshot URL loading for navigation nodes.
 * This drastically reduces API calls by fetching all signed URLs at once
 * instead of individually per node.
 * 
 * Features:
 * - Batch loading: 1 API call instead of N calls
 * - Visibility detection: Skip re-fetch when tab becomes visible if URLs still valid
 * - Persistent cache: Survives tab switches via sessionStorage
 * - Auto-refresh: Updates URLs before expiry
 */

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { useR2UrlsBatch } from '../../hooks/storage/useR2Url';
import type { UINavigationNode } from '../../types/pages/Navigation_Types';

const SCREENSHOT_URL_EXPIRY_SECONDS = 3600;
const MIN_REFETCH_INTERVAL_MS = 60000;

interface NavigationScreenshotContextType {
  /** Get screenshot URL for a node (returns null if not loaded yet) */
  getScreenshotUrl: (nodeId: string) => string | null;
  /** Loading state */
  loading: boolean;
  /** Error message if batch load failed */
  error: string | null;
  /** Manually refresh all screenshot URLs */
  refresh: () => Promise<void>;
  /** Number of screenshots loaded */
  loadedCount: number;
}

const NavigationScreenshotContext = createContext<NavigationScreenshotContextType | null>(null);

interface NavigationScreenshotProviderProps {
  children: React.ReactNode;
  nodes: UINavigationNode[];
}

export const NavigationScreenshotProvider: React.FC<NavigationScreenshotProviderProps> = ({
  children,
  nodes,
}) => {
  const [urlMap, setUrlMap] = useState<Record<string, string>>({});
  const [lastFetchTime, setLastFetchTime] = useState<number>(0);
  const isTabVisibleRef = useRef<boolean>(!document.hidden);
  const isMountedRef = useRef<boolean>(true);

  // Extract all screenshot paths from nodes
  const screenshotPaths = React.useMemo(() => {
    const paths: string[] = [];
    const pathToNodeId: Record<string, string> = {};

    nodes.forEach(node => {
      if (node.data.screenshot) {
        paths.push(node.data.screenshot);
        pathToNodeId[node.data.screenshot] = node.id;
      }
    });

    return { paths, pathToNodeId };
  }, [nodes]);

  // Use batch hook to fetch all URLs at once
  const { loading, error, refresh: batchRefresh, urlMap: batchUrlMap } = useR2UrlsBatch(
    screenshotPaths.paths,
    SCREENSHOT_URL_EXPIRY_SECONDS,
    true
  );

  // Update our URL map when batch hook updates
  useEffect(() => {
    if (!loading && Object.keys(batchUrlMap).length > 0) {
      const nodeUrlMap: Record<string, string> = {};
      
      // Convert path-based map to node ID-based map
      Object.entries(batchUrlMap).forEach(([path, url]) => {
        const nodeId = screenshotPaths.pathToNodeId[path];
        if (nodeId) {
          nodeUrlMap[nodeId] = url;
        }
      });

      setUrlMap(nodeUrlMap);
      setLastFetchTime(Date.now());
      
      console.log(
        `[@context:NavigationScreenshot] Loaded ${Object.keys(nodeUrlMap).length} screenshot URLs (batch mode)`
      );
    }
  }, [batchUrlMap, loading, screenshotPaths.pathToNodeId]);

  // Re-sign the overwritten object key when a node screenshot is replaced.
  // Same key gets new bytes; the cached signed URL is bound to the previous
  // image in the browser cache, so we discard it by re-running the batch.
  useEffect(() => {
    const handleScreenshotUpdated = () => {
      console.log('[@context:NavigationScreenshot] nodeScreenshotUpdated - re-signing URLs');
      batchRefresh();
    };

    window.addEventListener('nodeScreenshotUpdated', handleScreenshotUpdated as EventListener);
    return () => {
      window.removeEventListener('nodeScreenshotUpdated', handleScreenshotUpdated as EventListener);
    };
  }, [batchRefresh]);

  // Track tab visibility to prevent unnecessary re-fetches
  useEffect(() => {
    const handleVisibilityChange = () => {
      const isVisible = !document.hidden;
      const wasHidden = !isTabVisibleRef.current;
      isTabVisibleRef.current = isVisible;

      if (isVisible && wasHidden) {
        const timeSinceLastFetch = Date.now() - lastFetchTime;
        if (timeSinceLastFetch < MIN_REFETCH_INTERVAL_MS) {
          console.log(
            `[@context:NavigationScreenshot] Tab visible but URLs still fresh (fetched ${Math.floor(timeSinceLastFetch / 1000)}s ago) - skipping re-fetch`
          );
          return;
        }

        // URLs might be expired, refresh
        console.log(
          `[@context:NavigationScreenshot] Tab visible and URLs may be stale (fetched ${Math.floor(timeSinceLastFetch / 1000)}s ago) - refreshing`
        );
        batchRefresh();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [lastFetchTime, batchRefresh]);

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const getScreenshotUrl = useCallback((nodeId: string): string | null => {
    return urlMap[nodeId] || null;
  }, [urlMap]);

  const refresh = useCallback(async () => {
    await batchRefresh();
  }, [batchRefresh]);

  const value: NavigationScreenshotContextType = {
    getScreenshotUrl,
    loading,
    error,
    refresh,
    loadedCount: Object.keys(urlMap).length,
  };

  return (
    <NavigationScreenshotContext.Provider value={value}>
      {children}
    </NavigationScreenshotContext.Provider>
  );
};

/**
 * Hook to access batched screenshot URLs
 */
export const useNavigationScreenshots = (): NavigationScreenshotContextType => {
  const context = useContext(NavigationScreenshotContext);
  if (!context) {
    throw new Error('useNavigationScreenshots must be used within NavigationScreenshotProvider');
  }
  return context;
};

/**
 * Hook to get a single screenshot URL for a node (convenience wrapper)
 */
export const useNodeScreenshot = (nodeId: string): string | null => {
  const { getScreenshotUrl } = useNavigationScreenshots();
  return getScreenshotUrl(nodeId);
};

