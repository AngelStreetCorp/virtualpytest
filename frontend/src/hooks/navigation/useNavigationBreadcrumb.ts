import { useCallback } from 'react';

import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useNavigationConfig } from '../../contexts/navigation/NavigationConfigContext';
import { useNavigationStack } from '../../contexts/navigation/NavigationStackContext';
import { useNavigationEditor } from './useNavigationEditor';

const LOG_PREFIX_AUTO_SAVE = 'Auto-saving before navigating';

/**
 * Shared hook for navigation breadcrumb functionality
 * Used by both NavigationEditor and NavigationTreeViewer to avoid code duplication
 */
export const useNavigationBreadcrumb = () => {
  const navigation = useNavigation();
  const { setActualTreeId, actualTreeId } = useNavigationConfig();
  const { popLevel, jumpToLevel, jumpToRoot } = useNavigationStack();
  const { saveTreeWithStateUpdate, hasUnsavedChanges } = useNavigationEditor();

  const handleNavigateBack = useCallback(async () => {
    if (navigation.parentChain.length <= 1) {
      console.log('Already at root, cannot go back');
      return;
    }

    if (hasUnsavedChanges && actualTreeId) {
      console.log(`${LOG_PREFIX_AUTO_SAVE} back to parent tree`);
      try {
        await saveTreeWithStateUpdate(actualTreeId);
        console.log('Auto-save successful');
      } catch (error) {
        console.error('Auto-save failed:', error);
        // Continue navigation even if save fails
      }
    }

    navigation.popFromParentChain();
    popLevel();

    const parent = navigation.parentChain[navigation.parentChain.length - 2];
    if (parent) {
      setActualTreeId(parent.treeId);
    }
  }, [navigation, popLevel, setActualTreeId, hasUnsavedChanges, saveTreeWithStateUpdate, actualTreeId]);

  const handleNavigateToLevel = useCallback(
    async (levelIndex: number) => {
      // `levelIndex` is an index into the breadcrumb `stack`, which excludes the
      // root tree. `parentChain` includes the root tree at index 0, so the matching
      // parentChain entry is `levelIndex + 1`. Without this offset, clicking the
      // first intermediate crumb (e.g. "apps") lands on parentChain[0] = root.
      const chainIndex = levelIndex + 1;
      if (chainIndex >= navigation.parentChain.length) {
        console.log('Invalid level index');
        return;
      }

      if (hasUnsavedChanges && actualTreeId) {
        console.log(`${LOG_PREFIX_AUTO_SAVE} to level`, levelIndex);
        try {
          await saveTreeWithStateUpdate(actualTreeId);
          console.log('Auto-save successful');
        } catch (error) {
          console.error('Auto-save failed:', error);
          // Continue navigation even if save fails
        }
      }

      const newChain = navigation.parentChain.slice(0, chainIndex + 1);
      const target = newChain[newChain.length - 1];

      navigation.setNodes(target.nodes);
      navigation.setEdges(target.edges);
      navigation.setParentChain(newChain);

      jumpToLevel(levelIndex);
      setActualTreeId(target.treeId);
    },
    [navigation, jumpToLevel, setActualTreeId, hasUnsavedChanges, saveTreeWithStateUpdate, actualTreeId],
  );

  const handleNavigateToRoot = useCallback(async () => {
    if (navigation.parentChain.length === 0) {
      console.log('No root tree in parent chain');
      return;
    }

    if (hasUnsavedChanges && actualTreeId) {
      console.log(`${LOG_PREFIX_AUTO_SAVE} to root`);
      try {
        await saveTreeWithStateUpdate(actualTreeId);
        console.log('Auto-save successful');
      } catch (error) {
        console.error('Auto-save failed:', error);
        // Continue navigation even if save fails
      }
    }

    navigation.resetToRoot();
    jumpToRoot();

    const root = navigation.parentChain[0];
    setActualTreeId(root.treeId);
  }, [navigation, jumpToRoot, setActualTreeId, hasUnsavedChanges, saveTreeWithStateUpdate, actualTreeId]);

  return {
    handleNavigateBack,
    handleNavigateToLevel,
    handleNavigateToRoot,
  };
};
