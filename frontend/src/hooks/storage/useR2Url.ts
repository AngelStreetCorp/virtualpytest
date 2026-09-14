/**
 * React Hook for R2 URL Management
 * 
 * Provides easy access to R2 files with automatic signed URL generation
 * when private bucket mode is enabled.
 * 
 * Features:
 * - Automatic signed URL fetching (if enabled)
 * - Loading and error states
 * - Auto-refresh before expiry
 * - Public URL fallback
 * - Batch URL loading for multiple files
 * 
 * @example Single URL
 * const { url, loading, error } = useR2Url('captures/device1/capture_123.jpg');
 * 
 * return (
 *   <>
 *     {loading && <Spinner />}
 *     {error && <div>Error: {error}</div>}
 *     {url && <img src={url} alt="Capture" />}
 *   </>
 * );
 * 
 * @example Batch URLs
 * const { urls, loading, error } = useR2UrlsBatch([
 *   'capture1.jpg',
 *   'capture2.jpg',
 *   'capture3.jpg'
 * ]);
 * 
 * return (
 *   <div>
 *     {urls.map((url, i) => <img key={i} src={url} />)}
 *   </div>
 * );
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { getR2Url, getR2UrlsBatch } from '../../utils/infrastructure/cloudflareUtils';

export interface UseR2UrlResult {
  /** The R2 URL (signed or public) */
  url: string | null;
  /** Loading state */
  loading: boolean;
  /** Error message if URL generation failed */
  error: string | null;
  /** Manually refresh the URL */
  refresh: () => Promise<void>;
}

export interface UseR2UrlsBatchResult {
  /** Array of R2 URLs in same order as input paths */
  urls: (string | null)[];
  /** Map of path -> URL for easier lookup */
  urlMap: Record<string, string>;
  /** Loading state */
  loading: boolean;
  /** Error message if URL generation failed */
  error: string | null;
  /** Manually refresh all URLs */
  refresh: () => Promise<void>;
}

/**
 * Hook to get a single R2 URL (with automatic signed URL if needed)
 * 
 * @param path - R2 path or full R2 URL (will extract path automatically)
 * @param expiresIn - Seconds until signed URL expires (default: 3600 = 1 hour)
 * @param autoRefresh - Auto-refresh URL before expiry (default: true)
 * 
 * @returns Object with url, loading, error, and refresh function
 */
export const useR2Url = (
  path: string | null | undefined,
  expiresIn: number = 3600,
  autoRefresh: boolean = true
): UseR2UrlResult => {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchUrl = useCallback(async () => {
    if (!path) {
      setUrl(null);
      setLoading(false);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // getR2Url handles all path formats (full MinIO URLs, full R2 URLs, relative paths)
      const resultUrl = await getR2Url(path, expiresIn);
      setUrl(resultUrl);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to get R2 URL';
      console.error('[@hooks:useR2Url] Error:', errorMsg);
      setError(errorMsg);
      setUrl(null);
    } finally {
      setLoading(false);
    }
  }, [path, expiresIn]);

  useEffect(() => {
    fetchUrl();

    // Setup auto-refresh if enabled
    if (autoRefresh && path) {
      // Refresh 5 minutes before expiry
      const refreshInterval = Math.max((expiresIn - 300) * 1000, 60000); // At least 1 minute
      const intervalId = setInterval(fetchUrl, refreshInterval);

      return () => clearInterval(intervalId);
    }
  }, [fetchUrl, autoRefresh, path, expiresIn]);

  return {
    url,
    loading,
    error,
    refresh: fetchUrl,
  };
};

/**
 * Hook to get multiple R2 URLs in batch (more efficient than multiple useR2Url calls)
 * 
 * @param paths - Array of R2 paths
 * @param expiresIn - Seconds until signed URLs expire (default: 3600)
 * @param autoRefresh - Auto-refresh URLs before expiry (default: true)
 * 
 * @returns Object with urls array, urlMap, loading, error, and refresh function
 */
export const useR2UrlsBatch = (
  paths: (string | null | undefined)[],
  expiresIn: number = 3600,
  autoRefresh: boolean = true
): UseR2UrlsBatchResult => {
  const pathsKey = useMemo(() => JSON.stringify(paths ?? []), [paths]);
  const stablePaths = useMemo(() => paths, [pathsKey]);
  const [urls, setUrls] = useState<(string | null)[]>([]);
  const [urlMap, setUrlMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchUrls = useCallback(async () => {
    // Filter out null/undefined paths
    const validPaths = stablePaths.filter((p): p is string => !!p);

    if (validPaths.length === 0) {
      setUrls([]);
      setUrlMap({});
      setLoading(false);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // getR2UrlsBatch handles all path formats and returns results keyed by original path
      const resultMap = await getR2UrlsBatch(validPaths, expiresIn);

      const resultUrls = stablePaths.map(path => (path ? resultMap[path] || null : null));

      setUrls(resultUrls);
      setUrlMap(resultMap);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to get R2 URLs';
      console.error('[@hooks:useR2UrlsBatch] Error:', errorMsg);
      setError(errorMsg);
      setUrls([]);
      setUrlMap({});
    } finally {
      setLoading(false);
    }
  }, [stablePaths, expiresIn]);

  useEffect(() => {
    fetchUrls();

    // Setup auto-refresh if enabled
    if (autoRefresh && stablePaths.length > 0) {
      const refreshInterval = Math.max((expiresIn - 300) * 1000, 60000);
      const intervalId = setInterval(fetchUrls, refreshInterval);

      return () => clearInterval(intervalId);
    }
  }, [fetchUrls, autoRefresh, stablePaths, expiresIn]);

  return {
    urls,
    urlMap,
    loading,
    error,
    refresh: fetchUrls,
  };
};

/**
 * Hook to convert an existing R2 URL to a potentially signed URL
 * Useful when you already have a public URL stored and want to migrate to signed URLs
 * 
 * @param existingUrl - Existing R2 URL (public or already signed)
 * @param expiresIn - Seconds until signed URL expires
 * 
 * @returns Object with url, loading, error
 */
export const useR2UrlFromExisting = (
  existingUrl: string | null | undefined,
  expiresIn: number = 3600
): UseR2UrlResult => {
  // getR2Url handles all URL formats, no need to pre-extract
  return useR2Url(existingUrl, expiresIn);
};

