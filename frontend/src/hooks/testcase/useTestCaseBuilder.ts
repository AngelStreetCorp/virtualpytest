/**
 * useTestCaseBuilder Hook
 * 
 * Handles fetching available interfaces, navigation nodes, actions, and verifications
 * for TestCase Builder dropdowns and configuration.
 * Follows Navigation architecture pattern with buildServerUrl + fetch directly.
 */

import { useCallback } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { getErrorMessage } from '../../utils/testcase/testCaseHelpers';

export interface NavigationNode {
  id: string;
  label: string;
  type?: string;
}

export interface UserInterface {
  id: string;
  userinterface_name: string;
  display_name?: string;
}

export interface ActionCommand {
  command: string;
  description: string;
  params?: Record<string, any>;
}

const EMPTY_USER_INTERFACES_RESULT = { success: false, userinterfaces: [] as UserInterface[] };
const EMPTY_TREES_RESULT = { success: false, trees: [] as any[] };
const EMPTY_NODES_RESULT = { success: false, nodes: [] as NavigationNode[] };

const DEFAULT_ACTIONS: ActionCommand[] = [
  { command: 'press_ok', description: 'Press OK button' },
  { command: 'press_back', description: 'Press Back button' },
  { command: 'press_home', description: 'Press Home button' },
  { command: 'press_up', description: 'Press Up button' },
  { command: 'press_down', description: 'Press Down button' },
  { command: 'press_left', description: 'Press Left button' },
  { command: 'press_right', description: 'Press Right button' },
  { command: 'press_menu', description: 'Press Menu button' },
  { command: 'press_power', description: 'Press Power button' },
  { command: 'press_mute', description: 'Press Mute button' },
  { command: 'press_volume_up', description: 'Volume Up' },
  { command: 'press_volume_down', description: 'Volume Down' },
  { command: 'press_channel_up', description: 'Channel Up' },
  { command: 'press_channel_down', description: 'Channel Down' },
  { command: 'press_play', description: 'Press Play button' },
  { command: 'press_pause', description: 'Press Pause button' },
  { command: 'press_stop', description: 'Press Stop button' },
  { command: 'press_rewind', description: 'Press Rewind button' },
  { command: 'press_fast_forward', description: 'Press Fast Forward button' },
  { command: 'click_element', description: 'Click UI element', params: { element_id: 'string' } },
  { command: 'send_text', description: 'Send text input', params: { text: 'string' } },
  { command: 'wait', description: 'Wait for duration', params: { seconds: 'number' } },
];

const DEFAULT_VERIFICATIONS = [
  { type: 'text', description: 'Verify text on screen', params: ['text', 'threshold'] },
  { type: 'image', description: 'Verify image reference', params: ['reference', 'threshold'] },
  { type: 'audio', description: 'Verify audio playing', params: ['threshold'] },
  { type: 'black_screen', description: 'Verify black screen', params: ['threshold'] },
  { type: 'freeze_screen', description: 'Verify not frozen', params: ['threshold'] },
];

export const useTestCaseBuilder = () => {
  
  /**
   * Fetch all user interfaces for a team
   */
  const getUserInterfaces = useCallback(async (): Promise<{ success: boolean; userinterfaces: UserInterface[] }> => {
    try {
      return await api.get(buildServerUrl('/server/userinterface/getAllUserInterfaces'));
    } catch (error) {
      console.error('[useTestCaseBuilder] Error fetching user interfaces:', error);
      return EMPTY_USER_INTERFACES_RESULT;
    }
  }, []);

  /**
   * Fetch full navigation tree with nodes
   */
  const getNavigationTree = useCallback(async (treeId: string): Promise<{ success: boolean; tree?: any }> => {
    try {
      const tree = await api.get(buildServerUrl(`/server/navigationTrees/${treeId}/full`));
      return { success: true, tree };
    } catch (error) {
      console.error('[useTestCaseBuilder] Error fetching navigation tree:', error);
      return { success: false };
    }
  }, []);

  /**
   * Fetch all navigation trees for a team
   */
  const getAllNavigationTrees = useCallback(async (): Promise<{ success: boolean; trees: any[] }> => {
    try {
      return await api.get(buildServerUrl('/server/navigationTrees'));
    } catch (error) {
      console.error('[useTestCaseBuilder] Error fetching navigation trees:', error);
      return EMPTY_TREES_RESULT;
    }
  }, []);

  /**
   * Get navigation nodes for a specific userinterface
   * Fetches the root tree for the interface and returns its nodes
   */
  const getNavigationNodesForInterface = useCallback(async (
    userinterfaceName: string
  ): Promise<{ success: boolean; nodes: NavigationNode[] }> => {
    try {
      // First, get all trees for the team
      const treesResponse = await getAllNavigationTrees();
      
      if (!treesResponse.success || !treesResponse.trees) {
        return EMPTY_NODES_RESULT;
      }
      
      // Find tree matching the userinterface_name
      const matchingTree = treesResponse.trees.find(
        (tree: any) => tree.userinterface_name === userinterfaceName
      );
      
      if (!matchingTree) {
        console.warn(`[useTestCaseBuilder] No tree found for userinterface: ${userinterfaceName}`);
        return EMPTY_NODES_RESULT;
      }
      
      // Fetch full tree data with nodes
      const treeResponse = await getNavigationTree(matchingTree.tree_id);
      
      if (!treeResponse.success || !treeResponse.tree) {
        return EMPTY_NODES_RESULT;
      }
      
      const nodes = treeResponse.tree.nodes || [];
      return {
        success: true,
        nodes: nodes.map((node: any) => ({
          id: node.id,
          label: node.label || node.id,
          type: node.type,
        })),
      };
    } catch (error) {
      console.error('[useTestCaseBuilder] Error fetching navigation nodes:', getErrorMessage(error));
      return EMPTY_NODES_RESULT;
    }
  }, [getAllNavigationTrees, getNavigationTree]);

  /**
   * Get available action commands
   * These are device commands that can be executed
   */
  const getAvailableActions = useCallback(async (): Promise<{ success: boolean; actions: ActionCommand[] }> => {
    return { success: true, actions: DEFAULT_ACTIONS };
  }, []);

  /**
   * Get available verification types
   */
  const getAvailableVerifications = useCallback(async (): Promise<{ success: boolean; verifications: any[] }> => {
    return { success: true, verifications: DEFAULT_VERIFICATIONS };
  }, []);

  return {
    getUserInterfaces,
    getNavigationTree,
    getAllNavigationTrees,
    getNavigationNodesForInterface,
    getAvailableActions,
    getAvailableVerifications,
  };
};

