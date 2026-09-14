/**
 * Builder Context
 * 
 * Global context for test case builder data (not device-specific).
 * Stores standard blocks and other builder-related state.
 */

import React, {
  createContext,
  useState,
  useCallback,
  useMemo,
} from 'react';

import { buildServerUrl } from '../../utils/buildUrlUtils';

// ========================================
// TYPES
// ========================================

interface BuilderState {
  // Standard blocks data (global, not device-specific)
  standardBlocks: any[];
  standardBlocksLoading: boolean;
  standardBlocksError: string | null;
}

interface BuilderActions {
  // Data fetching
  fetchStandardBlocks: (hostName: string, force?: boolean) => Promise<void>;
  
  // Data access
  getStandardBlocks: () => any[];
  
  // State management
  clearData: () => void;
}

export type BuilderContextType = BuilderState & BuilderActions;

// ========================================
// CONTEXT
// ========================================

export const BuilderContext = createContext<BuilderContextType | undefined>(undefined);

// ========================================
// PROVIDER
// ========================================

interface BuilderProviderProps {
  children: React.ReactNode;
}

export const BuilderProvider: React.FC<BuilderProviderProps> = ({ children }) => {
  // ========================================
  // STATE
  // ========================================

  const [state, setState] = useState<BuilderState>({
    standardBlocks: [],
    standardBlocksLoading: false,
    standardBlocksError: null,
  });

  // ========================================
  // DATA FETCHING
  // ========================================

  const fetchStandardBlocks = useCallback(async (hostName: string, force: boolean = false) => {
    if (!hostName) {
      console.warn('[BuilderContext] hostName required to fetch standard blocks');
      return;
    }

    // Don't re-fetch if already loaded (unless forced)
    if (!force && state.standardBlocks.length > 0) {
      console.log('[BuilderContext] Standard blocks already loaded');
      return;
    }

    setState((prev) => ({ ...prev, standardBlocksLoading: true, standardBlocksError: null }));

    try {
      console.log('[BuilderContext] Fetching standard blocks from backend for host:', hostName);
      
      // Use /server/ prefix to go through auto-proxy with host_name in query
      const url = buildServerUrl('/server/builder/blocks');
      const response = await fetch(`${url}&host_name=${hostName}`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });

      if (response.ok) {
        const result = await response.json();

        if (result.success && result.blocks && Array.isArray(result.blocks)) {
          console.log(`[BuilderContext] Loaded ${result.blocks.length} standard blocks`);
          setState((prev) => ({
            ...prev,
            standardBlocks: result.blocks,
            standardBlocksLoading: false,
          }));
        } else {
          console.warn('[BuilderContext] Invalid response format');
          setState((prev) => ({ ...prev, standardBlocks: [], standardBlocksLoading: false }));
        }
      } else if (response.status === 404) {
        console.warn('[BuilderContext] Standard blocks endpoint not found (404)');
        setState((prev) => ({ ...prev, standardBlocks: [], standardBlocksLoading: false }));
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (error) {
      console.error('[BuilderContext] Error fetching standard blocks:', error);
      setState((prev) => ({
        ...prev,
        standardBlocksLoading: false,
        standardBlocksError: error instanceof Error ? error.message : 'Unknown error',
      }));
    }
  }, []); // No dependencies - hostName comes as parameter

  // ========================================
  // DATA ACCESS
  // ========================================

  const getStandardBlocks = useCallback((): any[] => {
    return state.standardBlocks;
  }, [state.standardBlocks]);

  // ========================================
  // STATE MANAGEMENT
  // ========================================

  const clearData = useCallback(() => {
    setState({
      standardBlocks: [],
      standardBlocksLoading: false,
      standardBlocksError: null,
    });
  }, []);

  // ========================================
  // EFFECTS
  // ========================================

  // Don't auto-fetch on mount - wait for control to get host_name
  // (triggered from useTestCaseBuilderPage after control)

  // ========================================
  // CONTEXT VALUE
  // ========================================

  const contextValue: BuilderContextType = useMemo(
    () => ({
      // State
      ...state,

      // Actions
      fetchStandardBlocks,
      getStandardBlocks,
      clearData,
    }),
    [state, fetchStandardBlocks, getStandardBlocks, clearData],
  );

  return <BuilderContext.Provider value={contextValue}>{children}</BuilderContext.Provider>;
};

