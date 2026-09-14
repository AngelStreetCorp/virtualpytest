/**
 * Requirements Management Hook
 *
 * This hook handles requirements operations including:
 * - CRUD operations for requirements
 * - Linking requirements to testcases and scripts
 * - Filtering and searching requirements
 */

import { useState, useCallback, useEffect } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { getCached, setCached } from '../../utils/pageCache';

export interface Requirement {
  requirement_id: string;
  team_id: string;
  requirement_code: string;
  requirement_name: string;
  category: string;
  priority: string; // P1, P2, P3
  description?: string;
  acceptance_criteria?: string[];
  app_type: string; // streaming, social, news, all
  device_model: string; // android_mobile, android_tv, web, all
  status: string; // active, deprecated, draft
  source_document?: string;
  created_at?: string;
  updated_at?: string;
  created_by?: string;
}

export interface RequirementFilters {
  category?: string;
  priority?: string;
  app_type?: string;
  device_model?: string;
  status?: string;
  coverage?: string; // 'all' | 'covered' | 'partial' | 'none'
}

export interface CoverageCount {
  testcase_count: number;
  script_count: number;
  total_count: number;
}

export interface TestcaseWithLink {
  testcase_id: string;
  testcase_name: string;
  description?: string;
  userinterface_name?: string;
  is_linked: boolean;
  created_at?: string;
}

export interface RequirementCoverage {
  requirement: Requirement;
  testcases_by_ui: {
    [ui: string]: Array<{
      testcase_id: string;
      testcase_name: string;
      description?: string;
      coverage_type: string;
      execution_count: number;
      pass_count: number;
      pass_rate: number;
      last_execution?: any;
    }>;
  };
  scripts: Array<{
    script_name: string;
    coverage_type: string;
    execution_count: number;
    pass_count: number;
    pass_rate: number;
    last_execution?: any;
  }>;
  coverage_summary: {
    total_testcases: number;
    total_scripts: number;
    total_coverage: number;
    pass_rate: number;
    execution_count: number;
  };
}

export interface UseRequirementsReturn {
  // Requirements List
  requirements: Requirement[];
  isLoading: boolean;
  error: string | null;
  
  // CRUD Operations
  createRequirement: (requirement: Omit<Requirement, 'requirement_id' | 'team_id' | 'created_at' | 'updated_at'>) => Promise<{ success: boolean; requirement_id?: string; error?: string }>;
  updateRequirement: (requirementId: string, updates: Partial<Requirement>) => Promise<{ success: boolean; error?: string }>;
  deleteRequirement: (requirementId: string) => Promise<{ success: boolean; error?: string }>;
  getRequirement: (requirementId: string) => Promise<Requirement | null>;
  getRequirementByCode: (requirementCode: string) => Promise<Requirement | null>;
  
  // List & Filter
  loadRequirements: (filters?: RequirementFilters) => Promise<void>;
  refreshRequirements: () => Promise<void>;
  
  // Filters
  filters: RequirementFilters;
  setFilters: (filters: RequirementFilters) => void;
  
  // Categories & Priorities
  categories: string[];
  priorities: string[];
  appTypes: string[];
  deviceModels: string[];
  
  // Linkage
  linkTestcase: (testcaseId: string, requirementId: string, coverageType?: string, notes?: string) => Promise<{ success: boolean; error?: string }>;
  unlinkTestcase: (testcaseId: string, requirementId: string) => Promise<{ success: boolean; error?: string }>;
  linkScript: (scriptName: string, requirementId: string, coverageType?: string, notes?: string) => Promise<{ success: boolean; error?: string }>;
  unlinkScript: (scriptName: string, requirementId: string) => Promise<{ success: boolean; error?: string }>;
  getTestcaseRequirements: (testcaseId: string) => Promise<Requirement[]>;
  getScriptRequirements: (scriptName: string) => Promise<Requirement[]>;
  
  // Coverage
  getCoverageCounts: () => Promise<Record<string, CoverageCount>>;
  getRequirementCoverage: (requirementId: string) => Promise<RequirementCoverage | null>;
  getAvailableTestcases: (requirementId: string, userinterfaceName?: string) => Promise<TestcaseWithLink[]>;
  linkMultipleTestcases: (requirementId: string, testcaseIds: string[], coverageType?: string) => Promise<{ success: boolean; error?: string }>;
  coverageCounts: Record<string, CoverageCount>;
}

export const useRequirements = (): UseRequirementsReturn => {
  const [requirements, setRequirements] = useState<Requirement[]>(() => getCached<Requirement[]>('requirements') ?? []);
  const categories = [...new Set(requirements.map(r => r.category).filter(Boolean))].sort() as string[];
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<RequirementFilters>({});
  const [coverageCounts, setCoverageCounts] = useState<Record<string, CoverageCount>>({});
  
  const priorities = ['P1', 'P2', 'P3'];
  const appTypes = ['streaming', 'social', 'news', 'all'];
  const deviceModels = ['android_mobile', 'android_tv', 'web', 'all'];
  
  // Load requirements with filters
  const loadRequirements = useCallback(async (customFilters?: RequirementFilters) => {
    setIsLoading(true);
    setError(null);
    
    try {
      const activeFilters = customFilters || filters;
      const params = new URLSearchParams();
      
      if (activeFilters.category) params.append('category', activeFilters.category);
      if (activeFilters.priority) params.append('priority', activeFilters.priority);
      if (activeFilters.app_type) params.append('app_type', activeFilters.app_type);
      if (activeFilters.device_model) params.append('device_model', activeFilters.device_model);
      if (activeFilters.status) params.append('status', activeFilters.status);
      
      const url = buildServerUrl(`/server/requirements/list${params.toString() ? `?${params.toString()}` : ''}`);
      const data = await api.get(url);
      
      if (data.success) {
        const reqs = data.requirements || [];
        setRequirements(reqs);
        setCached('requirements', reqs);
      } else {
        throw new Error(data.error || 'Failed to load requirements');
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setError(errorMsg);
      console.error('[@useRequirements] Error loading requirements:', err);
    } finally {
      setIsLoading(false);
    }
  }, [filters]);
  
  // Refresh current requirements
  const refreshRequirements = useCallback(() => {
    return loadRequirements(filters);
  }, [loadRequirements, filters]);
  
  // Create requirement
  const createRequirement = useCallback(async (requirement: Omit<Requirement, 'requirement_id' | 'team_id' | 'created_at' | 'updated_at'>) => {
    try {
      const url = buildServerUrl('/server/requirements/create');
      const data = await api.post(url, requirement);
      
      if (data.success) {
        await refreshRequirements();
        return { success: true, requirement_id: data.requirement_id };
      } else {
        return { success: false, error: data.error || 'Failed to create requirement' };
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      console.error('[@useRequirements] Error creating requirement:', err);
      return { success: false, error: errorMsg };
    }
  }, [refreshRequirements]);
  
  // Update requirement
  const updateRequirement = useCallback(async (requirementId: string, updates: Partial<Requirement>) => {
    try {
      const url = buildServerUrl(`/server/requirements/${requirementId}`);
      const data = await api.put(url, updates);
      
      if (data.success) {
        await refreshRequirements();
        return { success: true };
      } else {
        return { success: false, error: data.error || 'Failed to update requirement' };
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      console.error('[@useRequirements] Error updating requirement:', err);
      return { success: false, error: errorMsg };
    }
  }, [refreshRequirements]);
  
  // Delete requirement (soft delete by setting status to deprecated)
  const deleteRequirement = useCallback(async (requirementId: string) => {
    return updateRequirement(requirementId, { status: 'deprecated' });
  }, [updateRequirement]);
  
  // Get single requirement by ID
  const getRequirement = useCallback(async (requirementId: string): Promise<Requirement | null> => {
    try {
      const url = buildServerUrl(`/server/requirements/${requirementId}`);
      const data = await api.get(url);
      
      if (data.success) {
        return data.requirement;
      } else {
        console.error('[@useRequirements] Error getting requirement:', data.error);
        return null;
      }
    } catch (err) {
      console.error('[@useRequirements] Error getting requirement:', err);
      return null;
    }
  }, []);
  
  // Get requirement by code
  const getRequirementByCode = useCallback(async (requirementCode: string): Promise<Requirement | null> => {
    try {
      const url = buildServerUrl(`/server/requirements/by-code/${requirementCode}`);
      const data = await api.get(url);
      
      if (data.success) {
        return data.requirement;
      } else {
        console.error('[@useRequirements] Error getting requirement by code:', data.error);
        return null;
      }
    } catch (err) {
      console.error('[@useRequirements] Error getting requirement by code:', err);
      return null;
    }
  }, []);
  
  // Link testcase to requirement
  const linkTestcase = useCallback(async (testcaseId: string, requirementId: string, coverageType = 'full', notes?: string) => {
    try {
      const url = buildServerUrl('/server/requirements/link-testcase');
      const data = await api.post(url, {
        testcase_id: testcaseId,
        requirement_id: requirementId,
        coverage_type: coverageType,
        coverage_notes: notes,
      });
      
      if (data.success) {
        return { success: true };
      } else {
        return { success: false, error: data.error || 'Failed to link testcase' };
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      console.error('[@useRequirements] Error linking testcase:', err);
      return { success: false, error: errorMsg };
    }
  }, []);
  
  // Unlink testcase from requirement
  const unlinkTestcase = useCallback(async (testcaseId: string, requirementId: string) => {
    try {
      const url = buildServerUrl('/server/requirements/unlink-testcase');
      const data = await api.post(url, {
        testcase_id: testcaseId,
        requirement_id: requirementId,
      });
      
      if (data.success) {
        return { success: true };
      } else {
        return { success: false, error: data.error || 'Failed to unlink testcase' };
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      console.error('[@useRequirements] Error unlinking testcase:', err);
      return { success: false, error: errorMsg };
    }
  }, []);
  
  // Link script to requirement
  const linkScript = useCallback(async (scriptName: string, requirementId: string, coverageType = 'full', notes?: string) => {
    try {
      const url = buildServerUrl('/server/requirements/link-script');
      const data = await api.post(url, {
        script_name: scriptName,
        requirement_id: requirementId,
        coverage_type: coverageType,
        coverage_notes: notes,
      });
      
      if (data.success) {
        return { success: true };
      } else {
        return { success: false, error: data.error || 'Failed to link script' };
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      console.error('[@useRequirements] Error linking script:', err);
      return { success: false, error: errorMsg };
    }
  }, []);
  
  // Unlink script from requirement
  const unlinkScript = useCallback(async (scriptName: string, requirementId: string) => {
    try {
      const url = buildServerUrl('/server/requirements/unlink-script');
      const data = await api.post(url, {
        script_name: scriptName,
        requirement_id: requirementId,
      });
      
      if (data.success) {
        return { success: true };
      } else {
        return { success: false, error: data.error || 'Failed to unlink script' };
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      console.error('[@useRequirements] Error unlinking script:', err);
      return { success: false, error: errorMsg };
    }
  }, []);
  
  // Get testcase requirements
  const getTestcaseRequirements = useCallback(async (testcaseId: string): Promise<Requirement[]> => {
    try {
      const url = buildServerUrl(`/server/requirements/testcase/${testcaseId}/requirements`);
      const data = await api.get(url);
      
      if (data.success) {
        return data.requirements || [];
      } else {
        console.error('[@useRequirements] Error getting testcase requirements:', data.error);
        return [];
      }
    } catch (err) {
      console.error('[@useRequirements] Error getting testcase requirements:', err);
      return [];
    }
  }, []);
  
  // Get script requirements
  const getScriptRequirements = useCallback(async (scriptName: string): Promise<Requirement[]> => {
    try {
      const url = buildServerUrl(`/server/requirements/script/${scriptName}/requirements`);
      const data = await api.get(url);
      
      if (data.success) {
        return data.requirements || [];
      } else {
        console.error('[@useRequirements] Error getting script requirements:', data.error);
        return [];
      }
    } catch (err) {
      console.error('[@useRequirements] Error getting script requirements:', err);
      return [];
    }
  }, []);
  
  // Get coverage counts for all requirements
  const getCoverageCounts = useCallback(async (): Promise<Record<string, CoverageCount>> => {
    try {
      const url = buildServerUrl('/server/requirements/coverage-counts');
      const data = await api.get(url);
      
      if (data.success) {
        const counts = data.coverage_counts || {};
        setCoverageCounts(counts);
        return counts;
      } else {
        console.error('[@useRequirements] Error getting coverage counts:', data.error);
        return {};
      }
    } catch (err) {
      console.error('[@useRequirements] Error getting coverage counts:', err);
      return {};
    }
  }, []);
  
  // Get detailed coverage for a single requirement
  const getRequirementCoverage = useCallback(async (requirementId: string): Promise<RequirementCoverage | null> => {
    try {
      const url = buildServerUrl(`/server/requirements/${requirementId}/coverage`);
      const data = await api.get(url);
      
      if (data.success) {
        return data.coverage as RequirementCoverage;
      } else {
        console.error('[@useRequirements] Error getting requirement coverage:', data.error);
        return null;
      }
    } catch (err) {
      console.error('[@useRequirements] Error getting requirement coverage:', err);
      return null;
    }
  }, []);
  
  // Get available testcases for linking
  const getAvailableTestcases = useCallback(async (
    requirementId: string, 
    userinterfaceName?: string
  ): Promise<TestcaseWithLink[]> => {
    try {
      const params = new URLSearchParams();
      if (userinterfaceName) {
        params.append('userinterface_name', userinterfaceName);
      }
      
      const url = buildServerUrl(
        `/server/requirements/${requirementId}/available-testcases${params.toString() ? `?${params.toString()}` : ''}`
      );
      const data = await api.get(url);
      
      if (data.success) {
        return data.testcases || [];
      } else {
        console.error('[@useRequirements] Error getting available testcases:', data.error);
        return [];
      }
    } catch (err) {
      console.error('[@useRequirements] Error getting available testcases:', err);
      return [];
    }
  }, []);
  
  // Link multiple testcases at once
  const linkMultipleTestcases = useCallback(async (
    requirementId: string,
    testcaseIds: string[],
    coverageType = 'full'
  ): Promise<{ success: boolean; error?: string }> => {
    try {
      const results = await Promise.all(
        testcaseIds.map(testcaseId => linkTestcase(testcaseId, requirementId, coverageType))
      );
      
      const hasError = results.some(r => !r.success);
      
      if (hasError) {
        return { success: false, error: 'Some testcases failed to link' };
      }
      
      return { success: true };
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      console.error('[@useRequirements] Error linking multiple testcases:', err);
      return { success: false, error: errorMsg };
    }
  }, [linkTestcase]);
  
  // Load requirements on mount and when filters change
  useEffect(() => {
    loadRequirements();
    getCoverageCounts(); // Load coverage counts too
  }, [loadRequirements, getCoverageCounts]);
  
  return {
    requirements,
    isLoading,
    error,
    createRequirement,
    updateRequirement,
    deleteRequirement,
    getRequirement,
    getRequirementByCode,
    loadRequirements,
    refreshRequirements,
    filters,
    setFilters,
    categories,
    priorities,
    appTypes,
    deviceModels,
    linkTestcase,
    unlinkTestcase,
    linkScript,
    unlinkScript,
    getTestcaseRequirements,
    getScriptRequirements,
    getCoverageCounts,
    getRequirementCoverage,
    getAvailableTestcases,
    linkMultipleTestcases,
    coverageCounts,
  };
};

