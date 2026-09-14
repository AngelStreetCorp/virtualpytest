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

export function invalidateExecutableListCache(): void {
  executableListCache = null;
  executableListInflight = null;
}

export function invalidateCampaignExecutableListCache(): void {
  campaignExecutableListCache = null;
  campaignExecutableListInflight = null;
}
