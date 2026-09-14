// Cloudflare R2 utility functions for URL handling
// Supports both public URLs and private bucket access via pre-signed URLs
//
// MODE DETECTION (automatic based on env var):
// - If VITE_CLOUDFLARE_R2_PUBLIC_URL is set → PUBLIC mode (direct URLs, no auth needed)
// - If VITE_CLOUDFLARE_R2_PUBLIC_URL is NOT set → PRIVATE mode (signed URLs via backend)

import { api } from '../apiClient';
import { buildServerUrl } from '../buildUrlUtils';

/**
 * Get the public URL base from environment variable
 * Returns empty string if not configured (triggers private/signed URL mode)
 */
const getPublicUrlBase = (): string => {
  const envUrl = (import.meta as any).env?.VITE_CLOUDFLARE_R2_PUBLIC_URL ||
                 (import.meta as any).env?.VITE_MINIO_PUBLIC_URL;
  return envUrl && envUrl.trim() !== '' ? envUrl.trim().replace(/\/$/, '') : '';
};

/**
 * Check if public mode is enabled (env var is set)
 */
const isPublicModeEnabled = (): boolean => {
  return getPublicUrlBase() !== '';
};

/**
 * Configuration for signed URL behavior
 * Mode is auto-detected from VITE_CLOUDFLARE_R2_PUBLIC_URL env var
 */
const SIGNED_URL_CONFIG = {
  defaultExpiry: 3600, // 1 hour default
  cacheEnabled: true, // Cache signed URLs in memory
  cacheExpiryBuffer: 300, // Refresh 5 minutes before expiry
};

// Log mode on load
const publicUrlBase = getPublicUrlBase();
if (publicUrlBase) {
  console.log(`[@utils:cloudflareUtils] 🔓 PUBLIC mode - Using direct URLs from: ${publicUrlBase}`);
} else {
  console.log('[@utils:cloudflareUtils] 🔐 PRIVATE mode - Using signed URLs (VITE_CLOUDFLARE_R2_PUBLIC_URL not set)');
}

/**
 * In-memory cache for signed URLs
 * Structure: { path: { url, expiresAt } }
 */
const signedUrlCache: Record<string, { url: string; expiresAt: Date }> = {};

/**
 * SessionStorage key for persisting signed URL cache
 */
const CACHE_STORAGE_KEY = 'vpt_signed_url_cache';

/**
 * Load signed URL cache from sessionStorage
 */
const loadCacheFromStorage = (): void => {
  try {
    const stored = sessionStorage.getItem(CACHE_STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      const now = new Date();
      
      let loadedCount = 0;
      Object.entries(parsed).forEach(([path, entry]: [string, any]) => {
        const expiresAt = new Date(entry.expiresAt);
        
        // Only load if not expired
        if (expiresAt > now) {
          signedUrlCache[path] = {
            url: entry.url,
            expiresAt: expiresAt,
          };
          loadedCount++;
        }
      });
      
      if (loadedCount > 0) {
        console.log(`[@utils:cloudflareUtils] Loaded ${loadedCount} cached signed URLs from sessionStorage`);
      }
    }
  } catch (error) {
    console.warn('[@utils:cloudflareUtils] Failed to load cache from sessionStorage:', error);
  }
};

/**
 * Save signed URL cache to sessionStorage
 */
const saveCacheToStorage = (): void => {
  try {
    // Convert Date objects to ISO strings for JSON serialization
    const serializable: Record<string, { url: string; expiresAt: string }> = {};
    
    Object.entries(signedUrlCache).forEach(([path, entry]) => {
      serializable[path] = {
        url: entry.url,
        expiresAt: entry.expiresAt.toISOString(),
      };
    });
    
    sessionStorage.setItem(CACHE_STORAGE_KEY, JSON.stringify(serializable));
  } catch (error) {
    console.warn('[@utils:cloudflareUtils] Failed to save cache to sessionStorage:', error);
  }
};

/**
 * Debounced cache save (prevents excessive writes)
 */
let saveCacheTimeout: NodeJS.Timeout | null = null;
const scheduleCacheSave = (): void => {
  if (saveCacheTimeout) {
    clearTimeout(saveCacheTimeout);
  }
  saveCacheTimeout = setTimeout(saveCacheToStorage, 500); // Save 500ms after last update
};

// Load cache from sessionStorage on initialization
loadCacheFromStorage();

/**
 * Checks if a URL is a Cloudflare R2 URL
 * @param url - The URL to check
 * @returns True if the URL is a Cloudflare R2 URL
 */
export const isCloudflareR2Url = (url: string | undefined): boolean => {
  if (!url) return false;
  return url.includes('.r2.cloudflarestorage.com') || url.includes('r2.dev');
};

/**
 * Checks if a URL is a MinIO URL (public or internal)
 * @param url - The URL to check
 * @returns True if the URL is a MinIO URL
 */
export const isMinioUrl = (url: string | undefined): boolean => {
  if (!url) return false;
  // Check for MinIO patterns: /minio/ path or configured MinIO public URL
  const minioPublicUrl = (import.meta as any).env?.VITE_MINIO_PUBLIC_URL || '';
  return url.includes('/minio/') ||
         url.includes(':9000/') ||
         (minioPublicUrl && url.startsWith(minioPublicUrl));
};

/**
 * Checks if a URL is a pre-signed URL (contains AWS signature parameters)
 * @param url - The URL to check
 * @returns True if the URL contains AWS signature parameters
 */
export const isPresignedUrl = (url: string | undefined): boolean => {
  if (!url) return false;
  return url.includes('X-Amz-Signature') && url.includes('X-Amz-Expires');
};

/**
 * Extracts the relative path from a Cloudflare R2 URL
 * @param cloudflareUrl - The full Cloudflare R2 URL
 * @returns The relative path within the R2 bucket
 */
export const extractR2Path = (cloudflareUrl: string): string | null => {
  if (!isCloudflareR2Url(cloudflareUrl)) return null;

  try {
    const url = new URL(cloudflareUrl);
    // Remove leading slash from pathname
    let path = url.pathname.substring(1);

    // If bucket name is in path (e.g., /virtualpytest/file.jpg), remove it
    const r2BucketMatch = path.match(/^[^/]+\/(script-|captures\/|verification\/|device-screenshots\/)/);
    if (r2BucketMatch) {
      path = path.substring(path.indexOf('/') + 1);
    }
    
    return path;
  } catch {
    console.error('[@utils:cloudflareUtils:extractR2Path] Invalid URL:', cloudflareUrl);
    return null;
  }
};

/**
 * Normalize a storage path to a bucket-relative path, handling all input formats:
 * - Full non-R2 URL (e.g. MinIO public URL) → returned as resolvedUrl, use directly
 * - Full Cloudflare R2 URL → extracts the relative path into normalizedPath
 * - Relative bucket path → returned as-is in normalizedPath
 *
 * Single source of truth for path/URL detection used by getR2Url and getR2UrlsBatch.
 */
const normalizeStoragePath = (path: string): { resolvedUrl: string | null; normalizedPath: string } => {
  // Already-signed URLs must never be re-processed (strips the signature)
  if (isPresignedUrl(path)) {
    return { resolvedUrl: path, normalizedPath: path };
  }
  // Full non-R2 URL (MinIO public, etc.)
  if ((path.startsWith('http://') || path.startsWith('https://')) && !isCloudflareR2Url(path)) {
    // In private mode, old MinIO URLs need path extraction + signing
    if (isMinioUrl(path) && !isPublicModeEnabled()) {
      try {
        const url = new URL(path);
        let extractedPath = url.pathname.substring(1); // remove leading /
        // Remove /minio/ prefix if present
        if (extractedPath.startsWith('minio/')) {
          extractedPath = extractedPath.substring('minio/'.length);
        }
        // Remove bucket name prefix (any bucket: virtualpytest, etc.)
        // Bucket name is the first path segment before script-*, captures/, verification/, etc.
        const bucketMatch = extractedPath.match(/^[^/]+\/(script-|captures\/|verification\/|device-screenshots\/)/);
        if (bucketMatch) {
          extractedPath = extractedPath.substring(extractedPath.indexOf('/') + 1);
        }
        return { resolvedUrl: null, normalizedPath: extractedPath };
      } catch {
        // Fall through to use directly
      }
    }
    return { resolvedUrl: path, normalizedPath: path };
  }
  // Full R2 URL - extract the relative path
  if (isCloudflareR2Url(path)) {
    const extracted = extractR2Path(path);
    return { resolvedUrl: null, normalizedPath: extracted || path };
  }
  // Relative bucket path
  return { resolvedUrl: null, normalizedPath: path };
};

/**
 * Check if private/signed URL mode is active
 * Returns true if VITE_CLOUDFLARE_R2_PUBLIC_URL is NOT set
 */
export const isPrivateMode = (): boolean => !isPublicModeEnabled();

/**
 * Check if public mode is active
 * Returns true if VITE_CLOUDFLARE_R2_PUBLIC_URL IS set
 */
export const isPublicMode = (): boolean => isPublicModeEnabled();

/**
 * Get the current R2 URL mode
 */
export const getR2Mode = (): 'public' | 'private' => isPublicModeEnabled() ? 'public' : 'private';

/**
 * Check if signed URL caching is enabled
 */
export const isSignedUrlCacheEnabled = (): boolean => SIGNED_URL_CONFIG.cacheEnabled;

/**
 * Get a URL for storage path - unified interface for Cloudflare R2 and MinIO
 *
 * Automatically chooses provider based on environment variables:
 * 1. If VITE_CLOUDFLARE_R2_PUBLIC_URL is set → uses Cloudflare R2
 * 2. Else if VITE_MINIO_PUBLIC_URL is set → uses MinIO
 * 3. Else → uses Cloudflare R2 signed URLs (backward compatibility)
 *
 * @param path - Storage path (e.g., 'captures/device1/capture_123.jpg')
 * @param expiresIn - Seconds until expiration for signed URLs (default: 3600 = 1 hour)
 * @returns Promise resolving to the URL
 *
 * @example
 * const url = await getStorageUrl('verification/test.jpg');
 * // Uses Cloudflare if VITE_CLOUDFLARE_R2_PUBLIC_URL is set
 * // Uses MinIO if VITE_MINIO_PUBLIC_URL is set instead
 */
export const getStorageUrl = async (
  path: string,
  expiresIn: number = SIGNED_URL_CONFIG.defaultExpiry
): Promise<string> => {
  // getR2Url → normalizeStoragePath handles all providers and path formats
  return getR2Url(path, expiresIn);
};

// Keep the old getR2Url function for backward compatibility
export const getR2Url = async (
  path: string,
  expiresIn: number = SIGNED_URL_CONFIG.defaultExpiry
): Promise<string> => {
  const { resolvedUrl, normalizedPath } = normalizeStoragePath(path);

  // Full non-R2 URL (MinIO public etc.) - use directly
  if (resolvedUrl) return resolvedUrl;

  const publicBase = getPublicUrlBase();

  if (publicBase) {
    // PUBLIC MODE: Return direct URL (no API call needed)
    return `${publicBase}/${normalizedPath}`;
  }

  // PRIVATE MODE: Need to get signed URL from backend
  // Check cache first
  if (SIGNED_URL_CONFIG.cacheEnabled && signedUrlCache[normalizedPath]) {
    const cached = signedUrlCache[normalizedPath];
    const now = new Date();
    const timeUntilExpiry = (cached.expiresAt.getTime() - now.getTime()) / 1000;

    if (timeUntilExpiry > SIGNED_URL_CONFIG.cacheExpiryBuffer) {
      console.log(`[@utils:cloudflareUtils] Using cached signed URL for ${normalizedPath} (expires in ${Math.floor(timeUntilExpiry)}s)`);
      return cached.url;
    } else {
      delete signedUrlCache[normalizedPath];
    }
  }

  // Request new signed URL from backend
  try {
    const response = await api.post<{
      success: boolean;
      url?: string;
      expires_at?: string;
      error?: string;
    }>(buildServerUrl('/server/storage/signed-url'), {
      path: normalizedPath,
      expires_in: expiresIn,
    });

    if (response.success && response.url && response.expires_at) {
      const { url, expires_at } = response;

      if (SIGNED_URL_CONFIG.cacheEnabled) {
        signedUrlCache[normalizedPath] = {
          url,
          expiresAt: new Date(expires_at),
        };
        scheduleCacheSave();
      }

      console.log(`[@utils:cloudflareUtils] Generated signed URL for ${normalizedPath} (expires: ${expires_at})`);
      return url;
    } else {
      throw new Error(response.error || 'Failed to generate signed URL');
    }
  } catch (error) {
    console.error(`[@utils:cloudflareUtils] Error generating signed URL for ${normalizedPath}:`, error);
    throw new Error(`Failed to get signed URL for ${normalizedPath}: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
};

/**
 * Get multiple URLs in a batch (more efficient than individual calls)
 * 
 * Mode is AUTO-DETECTED based on VITE_CLOUDFLARE_R2_PUBLIC_URL env var.
 * 
 * @param paths - Array of R2 paths
 * @param expiresIn - Seconds until expiration for signed URLs (default: 3600)
 * @returns Promise resolving to map of path -> URL
 * 
 * @example
 * const urls = await getR2UrlsBatch([
 *   'capture1.jpg',
 *   'capture2.jpg',
 *   'capture3.jpg'
 * ]);
 * console.log(urls['capture1.jpg']); // Public or signed URL based on env config
 */
export const getR2UrlsBatch = async (
  paths: string[],
  expiresIn: number = SIGNED_URL_CONFIG.defaultExpiry
): Promise<Record<string, string>> => {
  if (paths.length === 0) return {};

  const publicBase = getPublicUrlBase();

  if (publicBase) {
    // PUBLIC MODE: Return direct URLs (no API call needed)
    // Use normalizeStoragePath so already-full URLs (MinIO public) are returned as-is
    return paths.reduce((acc, path) => {
      const { resolvedUrl, normalizedPath } = normalizeStoragePath(path);
      acc[path] = resolvedUrl ?? `${publicBase}/${normalizedPath}`;
      return acc;
    }, {} as Record<string, string>);
  }

  // PRIVATE MODE: Need to get signed URLs from backend
  // Result is keyed by the original input path throughout, so callers never need to remap.
  const result: Record<string, string> = {};
  const pathsToFetch: string[] = [];           // normalized paths sent to API
  const normalizedToOriginal: Record<string, string> = {}; // normalized → original path
  const now = new Date();

  for (const path of paths) {
    const { resolvedUrl, normalizedPath } = normalizeStoragePath(path);

    if (resolvedUrl) {
      // Already a full public URL (MinIO etc.) - no signing needed
      result[path] = resolvedUrl;
      continue;
    }

    if (SIGNED_URL_CONFIG.cacheEnabled && signedUrlCache[normalizedPath]) {
      const cached = signedUrlCache[normalizedPath];
      const timeUntilExpiry = (cached.expiresAt.getTime() - now.getTime()) / 1000;

      if (timeUntilExpiry > SIGNED_URL_CONFIG.cacheExpiryBuffer) {
        result[path] = cached.url;
        continue;
      } else {
        delete signedUrlCache[normalizedPath];
      }
    }

    pathsToFetch.push(normalizedPath);
    normalizedToOriginal[normalizedPath] = path;
  }

  if (pathsToFetch.length > 0) {
    try {
      const response = await api.post<{
        success: boolean;
        urls?: Array<{ path: string; url: string; expires_at: string; expires_in: number }>;
        failed?: Array<{ path: string; error: string }>;
        generated_count?: number;
        failed_count?: number;
      }>(buildServerUrl('/server/storage/signed-urls-batch'), {
        paths: pathsToFetch,
        expires_in: expiresIn,
      });

      if (response.success && response.urls) {
        for (const item of response.urls) {
          const originalPath = normalizedToOriginal[item.path] ?? item.path;
          result[originalPath] = item.url;

          if (SIGNED_URL_CONFIG.cacheEnabled) {
            signedUrlCache[item.path] = {
              url: item.url,
              expiresAt: new Date(item.expires_at),
            };
          }
        }

        if (SIGNED_URL_CONFIG.cacheEnabled && response.urls.length > 0) {
          scheduleCacheSave();
        }

        if (response.failed && response.failed.length > 0) {
          for (const failedItem of response.failed) {
            console.error(`[@utils:cloudflareUtils] Failed to get signed URL for ${failedItem.path}: ${failedItem.error}`);
            const originalPath = normalizedToOriginal[failedItem.path] ?? failedItem.path;
            result[originalPath] = '';
          }
        }

        console.log(`[@utils:cloudflareUtils] Generated ${response.generated_count} signed URLs (batch)`);
      }
    } catch (error) {
      console.error('[@utils:cloudflareUtils] Error generating batch signed URLs:', error);
      for (const normalizedPath of pathsToFetch) {
        const originalPath = normalizedToOriginal[normalizedPath] ?? normalizedPath;
        if (!result[originalPath]) result[originalPath] = '';
      }
    }
  }

  return result;
};

/**
 * Invalidate the signed-URL cache entry for a single path.
 * Use when the underlying object has been overwritten and the cached signed
 * URL would otherwise still resolve to the previous bytes.
 */
export const invalidateSignedUrl = (path: string | null | undefined): void => {
  if (!path) return;
  const { normalizedPath } = normalizeStoragePath(path);
  if (signedUrlCache[normalizedPath]) {
    delete signedUrlCache[normalizedPath];
    scheduleCacheSave();
  }
};

/**
 * Clear the signed URL cache (useful when user logs out)
 */
export const clearSignedUrlCache = (): void => {
  Object.keys(signedUrlCache).forEach(key => delete signedUrlCache[key]);
  try {
    sessionStorage.removeItem(CACHE_STORAGE_KEY);
  } catch (error) {
    console.warn('[@utils:cloudflareUtils] Failed to clear sessionStorage cache:', error);
  }
  console.log('[@utils:cloudflareUtils] Signed URL cache cleared (memory + sessionStorage)');
};

/**
 * Open a storage URL in a new tab, handling pre-signed URLs and generating signed URLs as needed.
 *
 * This function centralizes the logic for opening R2/MinIO URLs:
 * 1. If URL is already pre-signed (has X-Amz-Signature), opens directly
 * 2. If public mode is enabled, constructs direct URL
 * 3. Otherwise, fetches signed URL from backend
 *
 * @param url - The storage URL or path to open
 * @param expiresIn - Seconds until signed URL expires (default: 3600)
 * @returns Promise that resolves when URL is opened, or rejects on error
 *
 * @example
 * try {
 *   await openR2Url(result.html_report_r2_url);
 * } catch (error) {
 *   showError('Failed to open file');
 * }
 */
export const openR2Url = async (
  url: string,
  expiresIn: number = SIGNED_URL_CONFIG.defaultExpiry
): Promise<void> => {
  // getR2Url → normalizeStoragePath handles all formats:
  // presigned URLs, full MinIO URLs, full R2 URLs, and relative paths
  const resolvedUrl = await getR2Url(url, expiresIn);
  window.open(resolvedUrl, '_blank');
};
