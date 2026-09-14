/**
 * useTestCaseSave Hook
 * 
 * Handles test case save, load, list, and delete operations.
 * Follows Navigation architecture pattern with buildServerUrl + fetch directly.
 */

import { useCallback } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { invalidateExecutableListCache } from '../../utils/executionListCache';
import { getCachedTestCaseList, invalidateTestCaseListCache } from '../../utils/testcaseCache';
import { TestCaseGraph } from '../../types/testcase/TestCase_Types';
import { getErrorMessage } from '../../utils/testcase/testCaseHelpers';

export const useTestCaseSave = () => {
  
  /**
   * Save or update a test case
   */
  const saveTestCase = useCallback(async (
    testcaseName: string,
    graphJson: TestCaseGraph,
    description: string,
    userinterfaceName: string,
    createdBy: string,
    environment: string = 'dev',
    overwrite: boolean = false,
    folder?: string,  // NEW: Folder name (user-selected or typed)
    tags?: string[]   // NEW: List of tag names
  ): Promise<{ success: boolean; action?: string; error?: string; testcase?: any }> => {
    try {
      const result = await api.post(buildServerUrl('/server/testcase/save'), {
        testcase_name: testcaseName,
        graph_json: graphJson,
        description,
        userinterface_name: userinterfaceName,
        created_by: createdBy,
        environment,
        overwrite,
        folder,
        tags,
      });
      
      // Invalidate cache after successful save
      if (result.success) {
        invalidateTestCaseListCache();
        invalidateExecutableListCache();
      }
      
      return result;
    } catch (error) {
      console.error('[useTestCaseSave] Error saving test case:', getErrorMessage(error));
      return {
        success: false,
        error: getErrorMessage(error),
      };
    }
  }, []);

  /**
   * List all test cases
   */
  const listTestCases = useCallback(async (): Promise<{ success: boolean; testcases: any[] }> => {
    try {
      return await getCachedTestCaseList(buildServerUrl('/server/testcase/list'));
    } catch (error) {
      console.error('[useTestCaseSave] Error listing test cases:', error);
      return { success: false, testcases: [] };
    }
  }, []);

  /**
   * Get a specific test case by ID
   */
  const getTestCase = useCallback(async (testcaseId: string): Promise<{ success: boolean; testcase?: any; error?: string }> => {
    try {
      return await api.get(buildServerUrl(`/server/testcase/${testcaseId}`));
    } catch (error) {
      console.error('[useTestCaseSave] Error getting test case:', getErrorMessage(error));
      return {
        success: false,
        error: getErrorMessage(error),
      };
    }
  }, []);

  /**
   * Delete a test case
   */
  const deleteTestCase = useCallback(async (testcaseId: string): Promise<{ success: boolean; error?: string }> => {
    try {
      const result = await api.delete(buildServerUrl(`/server/testcase/${testcaseId}`));
      if (result.success) {
        invalidateTestCaseListCache();
        invalidateExecutableListCache();
      }
      return result;
    } catch (error) {
      console.error('[useTestCaseSave] Error deleting test case:', getErrorMessage(error));
      return {
        success: false,
        error: getErrorMessage(error),
      };
    }
  }, []);

  return {
    saveTestCase,
    listTestCases,
    getTestCase,
    deleteTestCase,
  };
};
