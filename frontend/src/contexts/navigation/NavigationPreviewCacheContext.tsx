import React, { createContext, useContext, useCallback, useRef, useEffect } from 'react';
import { NavigationStep } from '../../types/pages/Navigation_Types';
import { CACHE_CONFIG } from '../../config/constants';

interface NavigationPreviewCacheContextType {
  getCachedPreview: (treeId: string, currentNodeId: string | null, targetNodeId: string) => NavigationStep[] | null;
  cachePreview: (treeId: string, currentNodeId: string | null, targetNodeId: string, steps: NavigationStep[]) => void;
  invalidateTree: (treeId: string) => void;
}

interface CacheEntry {
  steps: NavigationStep[];
  timestamp: number;
}

const NavigationPreviewCacheContext = createContext<NavigationPreviewCacheContextType | null>(null);

/** localStorage key for preview step cache */
const CACHE_STORAGE_KEY = 'nav_preview_cache';

// Load cache from localStorage
const loadCacheFromStorage = (): Map<string, CacheEntry> => {
  try {
    const stored = localStorage.getItem(CACHE_STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      const now = Date.now();
      const cache = new Map<string, CacheEntry>();
      
      // Filter out expired entries
      let validCount = 0;
      let expiredCount = 0;
      
      Object.entries(parsed).forEach(([key, entry]: [string, any]) => {
        const age = now - entry.timestamp;
        if (age < CACHE_CONFIG.VERY_SHORT_TTL) {
          cache.set(key, entry as CacheEntry);
          validCount++;
        } else {
          expiredCount++;
        }
      });
      
      console.log(`[@PreviewCache] Loaded ${validCount} valid entries from localStorage (${expiredCount} expired entries removed)`);
      return cache;
    }
  } catch (error) {
    console.warn('[@PreviewCache] Failed to load cache from localStorage:', error);
  }
  return new Map();
};

// Save cache to localStorage
const saveCacheToStorage = (cache: Map<string, CacheEntry>): void => {
  try {
    const obj: Record<string, CacheEntry> = {};
    cache.forEach((value, key) => {
      obj[key] = value;
    });
    localStorage.setItem(CACHE_STORAGE_KEY, JSON.stringify(obj));
  } catch (error) {
    console.warn('[@PreviewCache] Failed to save cache to localStorage:', error);
  }
};

export const NavigationPreviewCacheProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Initialize cache from localStorage
  const cache = useRef<Map<string, CacheEntry>>(loadCacheFromStorage());
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Debounced save to localStorage
  const scheduleSave = useCallback(() => {
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }
    saveTimeoutRef.current = setTimeout(() => {
      saveCacheToStorage(cache.current);
    }, 500); // Save 500ms after last update
  }, []);

  // Clean up timeout on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
        saveCacheToStorage(cache.current); // Save immediately on unmount
      }
    };
  }, []);

  const getCachedPreview = useCallback((treeId: string, currentNodeId: string | null, targetNodeId: string) => {
    const key = `${treeId}|${currentNodeId || 'root'}|${targetNodeId}`;
    const cached = cache.current.get(key);
    
    if (cached) {
      const age = Date.now() - cached.timestamp;
      if (age < CACHE_CONFIG.VERY_SHORT_TTL) {
        const ageSeconds = Math.floor(age / 1000);
        console.log(`[@PreviewCache] ✅ HIT: ${targetNodeId} (age: ${ageSeconds}s)`);
        return cached.steps;
      } else {
        // Entry expired, remove it
        cache.current.delete(key);
        scheduleSave();
        console.log(`[@PreviewCache] ⏰ EXPIRED: ${targetNodeId} (removing)`);
      }
    }
    
    return null;
  }, [scheduleSave]);

  const cachePreview = useCallback((treeId: string, currentNodeId: string | null, targetNodeId: string, steps: NavigationStep[]) => {
    const key = `${treeId}|${currentNodeId || 'root'}|${targetNodeId}`;
    cache.current.set(key, {
      steps,
      timestamp: Date.now(),
    });
    scheduleSave();
    console.log(`[@PreviewCache] 💾 Cached ${targetNodeId} (total: ${cache.current.size}, TTL: 30s)`);
  }, [scheduleSave]);

  const invalidateTree = useCallback((treeId: string) => {
    const keys = Array.from(cache.current.keys()).filter(k => k.startsWith(`${treeId}|`));
    keys.forEach(k => cache.current.delete(k));
    scheduleSave();
    console.log(`[@PreviewCache] 🗑️ Invalidated ${keys.length} entries for tree ${treeId}`);
  }, [scheduleSave]);

  return (
    <NavigationPreviewCacheContext.Provider value={{ getCachedPreview, cachePreview, invalidateTree }}>
      {children}
    </NavigationPreviewCacheContext.Provider>
  );
};

export const useNavigationPreviewCache = () => {
  const context = useContext(NavigationPreviewCacheContext);
  if (!context) throw new Error('useNavigationPreviewCache must be used within NavigationPreviewCacheProvider');
  return context;
};
