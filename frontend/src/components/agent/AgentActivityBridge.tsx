/**
 * Agent Activity Bridge
 * 
 * Connects AIContext (chat events) to AgentActivityContext (badges).
 * Listens for chat events and triggers badge updates.
 */

import { useEffect, useRef } from 'react';
import { useAIContext } from '../../contexts/AIContext';
import { useAgentActivity } from '../../contexts/AgentActivityContext';

export const AgentActivityBridge: React.FC = () => {
  const { isProcessing, activeTask, executionSteps, selectedAgentId } = useAIContext();
  const { startTask, updateTaskStep, completeTask, failTask } = useAgentActivity();
  
  const currentTaskIdRef = useRef<string | null>(null);
  const lastAgentIdRef = useRef<string>(selectedAgentId || 'assistant');
  const wasProcessingRef = useRef(false);
  const capturedStepsRef = useRef<typeof executionSteps>([]);
  
  // Update last agent ID when selectedAgentId changes
  useEffect(() => {
    if (selectedAgentId) {
      lastAgentIdRef.current = selectedAgentId;
    }
  }, [selectedAgentId]);
  
  // Capture steps continuously while processing to avoid losing them
  useEffect(() => {
    if (isProcessing && executionSteps.length > 0) {
      capturedStepsRef.current = [...executionSteps];
      console.log('🎯 Bridge: Captured steps', executionSteps.length);
    }
  }, [isProcessing, executionSteps]);

  // Track processing state changes
  useEffect(() => {
    console.log('🎯 Bridge: State change', { 
      isProcessing, 
      wasProcessing: wasProcessingRef.current, 
      activeTask, 
      hasCurrentTask: !!currentTaskIdRef.current,
      agentId: lastAgentIdRef.current,
    });
    
    // Detect when processing starts
    if (isProcessing && !wasProcessingRef.current && activeTask) {
      // Extract agent ID from task context if available
      const agentId = lastAgentIdRef.current || 'assistant';
      
      // Start a new task in the badge system
      const taskId = startTask(agentId, activeTask, 'manual');
      currentTaskIdRef.current = taskId;
      console.log(`🎯 Bridge: Started badge task ${taskId} for ${agentId}`, { activeTask });
    }
    
    // Detect when processing stops
    if (!isProcessing && wasProcessingRef.current && currentTaskIdRef.current) {
      const agentId = lastAgentIdRef.current || 'assistant';
      
      // Use captured steps (they might have been cleared from AIContext already)
      const stepsToUse = capturedStepsRef.current.length > 0 ? capturedStepsRef.current : executionSteps;
      const lastStep = stepsToUse[stepsToUse.length - 1];
      
      console.log(`🎯 Bridge: Processing stopped, completing task ${currentTaskIdRef.current}`, { 
        lastStep,
        stepsCount: stepsToUse.length,
        usedCaptured: capturedStepsRef.current.length > 0
      });
      
      if (lastStep?.status === 'error') {
        failTask(agentId, currentTaskIdRef.current, lastStep.detail || 'Task failed');
      } else {
        // Build summary from captured execution steps
        const toolCalls = stepsToUse.filter(s => 
          s.label !== 'Parse Command' && 
          s.label !== 'Thinking' && 
          s.label !== 'AI Response'
        );
        
        // Extract AI response — only the LAST one (shortcut shows latest, full history in Agent Chat)
        let response = '';
        const aiResponseSteps = stepsToUse.filter(s => s.label === 'AI Response');
        if (aiResponseSteps.length > 0) {
          const lastStep = aiResponseSteps[aiResponseSteps.length - 1];
          response = lastStep?.detail || '';
        }
        
        // Fallback: try to extract from tool results if no AI response
        if (!response) {
          const lastToolResult = [...stepsToUse].reverse().find(s => 
            s.detail && 
            s.label !== 'Thinking' && 
            s.label !== 'Parse Command' &&
            s.label !== 'AI Response'
          );
          if (lastToolResult?.detail) {
            try {
              const parsed = JSON.parse(lastToolResult.detail);
              if (parsed.content && Array.isArray(parsed.content)) {
                const textContent = parsed.content.find((c: any) => c.type === 'text');
                if (textContent?.text) {
                  response = textContent.text;
                }
              }
            } catch {
              // Not JSON - don't use raw tool output
            }
          }
        }
        
        // If there's no AI response AND no real tool activity (only Thinking/Parse
        // steps), this is a timeout or connection failure — show an error instead
        // of a fake "Task completed successfully" message.
        if (!response && toolCalls.length === 0) {
          failTask(agentId, currentTaskIdRef.current, 'No response from agent. Please try again.');
        } else {
          if (!response) {
            response = 'Task completed successfully';
          }

          const summary = toolCalls.length > 0 ? {
            title: 'Task Complete',
            data: {
              'Tools used': toolCalls.length,
              'Last tool': toolCalls[toolCalls.length - 1]?.label || 'Processing',
            }
          } : undefined;

          completeTask(agentId, currentTaskIdRef.current, response, summary);
        }
      }
      
      console.log(`🎯 Bridge: Completed badge task ${currentTaskIdRef.current}`);
      
      // Clear captured steps after completion
      capturedStepsRef.current = [];
      currentTaskIdRef.current = null;
    }
    
    wasProcessingRef.current = isProcessing;
  }, [isProcessing, activeTask, executionSteps, startTask, completeTask, failTask]);

  // Update steps as they progress
  useEffect(() => {
    if (!currentTaskIdRef.current || !isProcessing) return;
    
    const lastStep = executionSteps[executionSteps.length - 1];
    if (lastStep && lastStep.label !== 'Parse Command') {
      const agentId = lastAgentIdRef.current || 'assistant';
      console.log('🎯 Bridge: Updating step', lastStep.label);
      updateTaskStep(agentId, currentTaskIdRef.current, {
        id: lastStep.id,
        label: lastStep.label,
        status: lastStep.status,
        detail: lastStep.detail,
        timestamp: new Date().toISOString(),
      });
    }
  }, [executionSteps, isProcessing, updateTaskStep]);

  // Listen for navigation events from AI agent
  useEffect(() => {
    const handleNavigation = (event: any) => {
      if (!currentTaskIdRef.current) return;
      
      const { to } = event.detail;
      const agentId = lastAgentIdRef.current || 'assistant';
      
      console.log(`🎯 Bridge: Navigation detected - updating task with redirectedTo: ${to}`);
      
      // Update the current task with the navigation destination
      updateTaskStep(agentId, currentTaskIdRef.current, {
        id: `nav-${Date.now()}`,
        label: `Navigated to ${to}`,
        status: 'done',
        detail: `Redirected to ${to}`,
        timestamp: new Date().toISOString(),
      });
    };

    window.addEventListener('ai-navigation', handleNavigation);
    return () => window.removeEventListener('ai-navigation', handleNavigation);
  }, [updateTaskStep]);

  // This component doesn't render anything
  return null;
};

export default AgentActivityBridge;

