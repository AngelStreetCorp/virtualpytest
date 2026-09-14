/**
 * Hook to manage tool execution timing and delayed animations
 * 
 * Delays showing executing animations for 5 seconds to avoid
 * flashy effects for fast-executing tools.
 */

import { useRef, useState } from 'react';

export const useToolExecutionTiming = () => {
  // Track tool execution start times to delay showing animations
  const toolExecutionStartTimes = useRef<Record<string, number>>({});
  const [, forceUpdate] = useState({});

  /**
   * Check if tool should show executing animation
   * @param toolKey Unique identifier for the tool execution
   * @param isExecuting Whether the tool is currently executing
   * @returns Whether to show the executing animation
   */
  const shouldShowExecutingAnimation = (toolKey: string, isExecuting: boolean): boolean => {
    if (!isExecuting) {
      // Clean up when tool completes
      delete toolExecutionStartTimes.current[toolKey];
      return false;
    }

    // Track execution start time
    if (!toolExecutionStartTimes.current[toolKey]) {
      toolExecutionStartTimes.current[toolKey] = Date.now();
      // Schedule a re-render after 5 seconds to show the animation
      setTimeout(() => forceUpdate({}), 5000);
    }

    // Calculate duration and determine if we should show animation
    const executionDuration = Date.now() - toolExecutionStartTimes.current[toolKey];
    return executionDuration >= 5000;
  };

  return { shouldShowExecutingAnimation };
};



