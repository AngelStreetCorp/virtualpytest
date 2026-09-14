/**
 * Coverage Management Hook
 *
 * This hook handles coverage operations including:
 * - Coverage summary across all requirements
 * - Detailed coverage for specific requirements
 * - Uncovered requirements tracking
 * - Coverage statistics and reporting
 */

import { useState, useCallback, useEffect } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { Requirement } from './useRequirements';

export interface RequirementCoverage {
  requirement: Requirement;
  testcases: TestcaseCoverageItem[];
  scripts: ScriptCoverageItem[];
  total_testcases: number;
  total_scripts: number;
  total_coverage: number;
}

export interface TestcaseCoverageItem {
  testcase_id: string;
  testcase_name: string;
  description?: string;
  coverage_type: string;
  execution_count: number;
  pass_count: number;
  last_execution?: {
    success: boolean;
    started_at: string;
  };
}

export interface ScriptCoverageItem {
  script_name: string;
  coverage_type: string;
  execution_count: number;
  pass_count: number;
  last_execution?: {
    success: boolean;
    started_at: string;
  };
}

export interface CategoryCoverageSummary {
  total: number;
  covered: number;
  testcase_count: number;
  script_count: number;
  coverage_percentage: number;
}

export interface CoverageSummary {
  by_category: {
    [category: string]: CategoryCoverageSummary;
  };
  total_requirements: number;
  total_covered: number;
  coverage_percentage: number;
}

export interface CoverageFilters {
  category?: string;
  priority?: string;
}

export interface UseCoverageReturn {
  // Summary
  coverageSummary: CoverageSummary | null;
  isLoadingSummary: boolean;
  summaryError: string | null;
  loadCoverageSummary: (filters?: CoverageFilters) => Promise<void>;
  
  // Detailed Coverage
  requirementCoverage: RequirementCoverage | null;
  isLoadingCoverage: boolean;
  coverageError: string | null;
  loadRequirementCoverage: (requirementId: string) => Promise<void>;
  
  // Uncovered Requirements
  uncoveredRequirements: Requirement[];
  isLoadingUncovered: boolean;
  uncoveredError: string | null;
  loadUncoveredRequirements: () => Promise<void>;
  
  // Filters
  filters: CoverageFilters;
  setFilters: (filters: CoverageFilters) => void;
  
  // Refresh
  refreshAll: () => Promise<void>;
}

export const useCoverage = (): UseCoverageReturn => {
  // Summary State
  const [coverageSummary, setCoverageSummary] = useState<CoverageSummary | null>(null);
  const [isLoadingSummary, setIsLoadingSummary] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  
  // Detailed Coverage State
  const [requirementCoverage, setRequirementCoverage] = useState<RequirementCoverage | null>(null);
  const [isLoadingCoverage, setIsLoadingCoverage] = useState(false);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  
  // Uncovered Requirements State
  const [uncoveredRequirements, setUncoveredRequirements] = useState<Requirement[]>([]);
  const [isLoadingUncovered, setIsLoadingUncovered] = useState(false);
  const [uncoveredError, setUncoveredError] = useState<string | null>(null);
  
  // Filters
  const [filters, setFilters] = useState<CoverageFilters>({});
  
  // Load coverage summary
  const loadCoverageSummary = useCallback(async (customFilters?: CoverageFilters) => {
    setIsLoadingSummary(true);
    setSummaryError(null);
    
    try {
      const activeFilters = customFilters || filters;
      const params = new URLSearchParams();
      
      if (activeFilters.category) params.append('category', activeFilters.category);
      if (activeFilters.priority) params.append('priority', activeFilters.priority);
      
      const url = buildServerUrl(`/server/requirements/coverage/summary${params.toString() ? `?${params.toString()}` : ''}`);
      const data = await api.get(url);
      
      if (data.success) {
        // Ensure by_category exists and is an object
        const summary = data.summary || null;
        if (summary && !summary.by_category) {
          summary.by_category = {};
        }
        setCoverageSummary(summary);
      } else {
        throw new Error(data.error || 'Failed to load coverage summary');
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setSummaryError(errorMsg);
      console.error('[@useCoverage] Error loading coverage summary:', err);
    } finally {
      setIsLoadingSummary(false);
    }
  }, [filters]);
  
  // Load requirement coverage details
  const loadRequirementCoverage = useCallback(async (requirementId: string) => {
    setIsLoadingCoverage(true);
    setCoverageError(null);
    
    try {
      const url = buildServerUrl(`/server/requirements/${requirementId}/coverage`);
      const data = await api.get(url);
      
      if (data.success) {
        setRequirementCoverage(data.coverage || null);
      } else {
        throw new Error(data.error || 'Failed to load requirement coverage');
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setCoverageError(errorMsg);
      console.error('[@useCoverage] Error loading requirement coverage:', err);
    } finally {
      setIsLoadingCoverage(false);
    }
  }, []);
  
  // Load uncovered requirements
  const loadUncoveredRequirements = useCallback(async () => {
    setIsLoadingUncovered(true);
    setUncoveredError(null);
    
    try {
      const url = buildServerUrl('/server/requirements/uncovered');
      const data = await api.get(url);
      
      if (data.success) {
        setUncoveredRequirements(data.requirements || []);
      } else {
        throw new Error(data.error || 'Failed to load uncovered requirements');
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setUncoveredError(errorMsg);
      console.error('[@useCoverage] Error loading uncovered requirements:', err);
    } finally {
      setIsLoadingUncovered(false);
    }
  }, []);
  
  // Refresh all coverage data
  const refreshAll = useCallback(async () => {
    await Promise.all([
      loadCoverageSummary(filters),
      loadUncoveredRequirements(),
    ]);
  }, [loadCoverageSummary, loadUncoveredRequirements, filters]);
  
  // Load coverage summary on mount
  useEffect(() => {
    loadCoverageSummary();
    loadUncoveredRequirements();
  }, [loadCoverageSummary, loadUncoveredRequirements]);
  
  return {
    coverageSummary,
    isLoadingSummary,
    summaryError,
    loadCoverageSummary,
    requirementCoverage,
    isLoadingCoverage,
    coverageError,
    loadRequirementCoverage,
    uncoveredRequirements,
    isLoadingUncovered,
    uncoveredError,
    loadUncoveredRequirements,
    filters,
    setFilters,
    refreshAll,
  };
};

