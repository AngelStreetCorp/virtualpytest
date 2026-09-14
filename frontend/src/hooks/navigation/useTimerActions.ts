import { useCallback, useEffect, useRef } from 'react';

import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useNavigationStack } from '../../contexts/navigation/NavigationStackContext';
import type { UINavigationEdge, UINavigationNode } from '../../types/pages/Navigation_Types';

const AUTO_RETURN_COMMAND = 'auto_return';

interface UseTimerActionsProps {
  currentNodeId?: string;
  edges: UINavigationEdge[];
  nodes: UINavigationNode[];
  onNavigateToNode?: (nodeId: string) => void;
}

interface UseTimerActionsReturn {
  checkTimerActions: (nodeId: string) => void;
  clearAllTimers: () => void;
  clearTimer: (timerId: string) => void;
  activeTimerCount: number;
  onNavigateToNode?: (nodeId: string) => void;
}

export const useTimerActions = ({
  currentNodeId,
  edges,
  nodes,
  onNavigateToNode
}: UseTimerActionsProps): UseTimerActionsReturn => {
  const { updateCurrentPosition } = useNavigation();
  const { isNested } = useNavigationStack();
  const activeTimersRef = useRef<Map<string, NodeJS.Timeout>>(new Map());

  // Clear all active timers
  const clearAllTimers = useCallback(() => {
    activeTimersRef.current.forEach((timer) => {
      clearTimeout(timer);
    });
    activeTimersRef.current.clear();
    console.log('[@useTimerActions] Cleared all active timers');
  }, []);

  // Clear specific timer
  const clearTimer = useCallback((timerId: string) => {
    const timer = activeTimersRef.current.get(timerId);
    if (timer) {
      clearTimeout(timer);
      activeTimersRef.current.delete(timerId);
      console.log(`[@useTimerActions] Cleared timer: ${timerId}`);
    }
  }, []);

  // Check for timer actions when reaching a node
  const checkTimerActions = useCallback((nodeId: string) => {
    if (!nodeId) return;

    // Find all edges from this node that have timer actions
    const timerEdges = edges.filter(edge =>
      edge.source === nodeId &&
      edge.data?.action_sets?.some((actionSet: any) =>
        actionSet.actions?.some((action: any) =>
          action.command === AUTO_RETURN_COMMAND && action.params?.timer > 0
        )
      )
    );

    timerEdges.forEach(edge => {
      const timerActions: any[] = [];
      edge.data?.action_sets?.forEach((actionSet: any) => {
        const setTimerActions = actionSet.actions?.filter((action: any) =>
          action.command === AUTO_RETURN_COMMAND && action.params?.timer > 0
        ) || [];
        timerActions.push(...setTimerActions);
      });

      timerActions.forEach((action: any, index: number) => {
        const timerId = `${edge.id}-${index}`;
        const timer = action.params.timer;
        const targetNodeId = action.params.target_node_id || edge.target;

        console.log(`[@useTimerActions] Setting timer for ${timer}ms to return to node: ${targetNodeId}`);

        // Clear existing timer for this edge if any
        clearTimer(timerId);

        // Set new timer
        const timeoutId = setTimeout(() => {
          console.log(`[@useTimerActions] Timer fired! Auto-returning to node: ${targetNodeId}`);
          
          // Execute the auto-return navigation
          if (onNavigateToNode) {
            onNavigateToNode(targetNodeId);
          } else {
            // Fallback: use navigation context to update position
            const targetNode = nodes.find(n => n.id === targetNodeId);
            if (targetNode) {
              updateCurrentPosition(targetNodeId, targetNode.data.label);
            }
          }

          // Clean up the timer reference
          activeTimersRef.current.delete(timerId);
        }, timer);

        // Store timer reference
        activeTimersRef.current.set(timerId, timeoutId);
      });
    });
  }, [edges, nodes, onNavigateToNode, updateCurrentPosition, clearTimer]);

  // Check for timer actions when current node changes
  useEffect(() => {
    if (currentNodeId && !isNested) {
      // Only clear and set timers when NOT in nested navigation mode
      // Clear previous timers when moving to a new node
      clearAllTimers();
      
      // Check for new timer actions
      checkTimerActions(currentNodeId);
    } else if (isNested) {
      // In nested navigation mode, just clear all timers without logging
      activeTimersRef.current.forEach((timer) => {
        clearTimeout(timer);
      });
      activeTimersRef.current.clear();
      // Don't log when clearing for nested navigation
    }

    return () => {
      // Cleanup on unmount
      clearAllTimers();
    };
  }, [currentNodeId, checkTimerActions, clearAllTimers, isNested]);

  return {
    checkTimerActions,
    clearAllTimers,
    clearTimer,
    activeTimerCount: activeTimersRef.current.size,
    onNavigateToNode
  };
};