import { api } from './apiClient';

interface RequestCacheEntry<T> {
  data: T;
  timestamp: number;
  apiUrl: string;
}

const CACHE_TTL_MS = 30000;

let executableListCache: RequestCacheEntry<any> | null = null;
let executableListInflight: Promise<any> | null = null;

let campaignExecutableListCache: RequestCacheEntry<any> | null = null;
let campaignExecutableListInflight: Promise<any> | null = null;

const isFresh = (timestamp: number) => (Date.now() - timestamp) < CACHE_TTL_MS;

export async function getCachedExecutableList(apiUrl: string): Promise<any> {
  if (executableListCache && executableListCache.apiUrl === apiUrl && isFresh(executableListCache.timestamp)) {
    return executableListCache.data;
  }

  if (executableListInflight) {
    return executableListInflight;
  }

  executableListInflight = api.get(apiUrl)
    .then((data) => {
      executableListCache = {
        data,
        timestamp: Date.now(),
        apiUrl,
      };
      return data;
    })
    .finally(() => {
      executableListInflight = null;
    });

  return executableListInflight;
}

export async function getCachedCampaignExecutableList(apiUrl: string): Promise<any> {
  if (campaignExecutableListCache && campaignExecutableListCache.apiUrl === apiUrl && isFresh(campaignExecutableListCache.timestamp)) {
    return campaignExecutableListCache.data;
  }

  if (campaignExecutableListInflight) {
    return campaignExecutableListInflight;
  }

  campaignExecutableListInflight = api.get(apiUrl)
    .then((data) => {
      campaignExecutableListCache = {
        data,
        timestamp: Date.now(),
        apiUrl,
      };
      return data;
    })
    .finally(() => {
      campaignExecutableListInflight = null;
    });

  return campaignExecutableListInflight;
}

/**
 * What is cached right now, without fetching — or null when there is nothing fresh.
 *
 * The async getters above already avoid the request on a cache hit, but a caller still has to
 * `await` them, and a page that flips a loading flag before awaiting shows its loading state
 * for a frame on every mount. Peeking first lets it seed from the cache synchronously and skip
 * the flag entirely, which is the difference between a list that is simply there and one that
 * visibly rebuilds each time you come back to the page.
 */
export function peekCachedExecutableList(apiUrl: string): any | null {
  return executableListCache && executableListCache.apiUrl === apiUrl
    && isFresh(executableListCache.timestamp)
    ? executableListCache.data
    : null;
}

export function peekCachedCampaignExecutableList(apiUrl: string): any | null {
  return campaignExecutableListCache && campaignExecutableListCache.apiUrl === apiUrl
    && isFresh(campaignExecutableListCache.timestamp)
    ? campaignExecutableListCache.data
    : null;
}

export function invalidateExecutableListCache(): void {
  executableListCache = null;
  executableListInflight = null;
}

export function invalidateCampaignExecutableListCache(): void {
  campaignExecutableListCache = null;
  campaignExecutableListInflight = null;
}
