/**
 * Hook for making components AI-controllable
 * 
 * Components can register themselves with an element_id and action handlers.
 * The AI can then interact with them via the interact_with_element tool.
 */

import { useEffect, useRef } from 'react';

interface AIInteractEvent {
  element_id: string;
  action: string;
  params?: Record<string, any>;
}

interface AIHighlightEvent {
  element_id: string;
  duration_ms: number;
}

interface AIControllableOptions {
  /** Unique element ID matching the page schema */
  elementId: string;
  
  /** Action handlers for this element */
  onAction?: (action: string, params?: Record<string, any>) => void;
  
  /** Called when AI highlights this element */
  onHighlight?: (duration_ms: number) => void;
  
  /** Reference to the DOM element for default highlight behavior */
  ref?: React.RefObject<HTMLElement>;
}

/**
 * Makes a component controllable by the AI agent
 * 
 * @example
 * ```tsx
 * const MyButton = () => {
 *   const buttonRef = useRef<HTMLButtonElement>(null);
 *   
 *   useAIControllable({
 *     elementId: 'run-btn',
 *     ref: buttonRef,
 *     onAction: (action, params) => {
 *       if (action === 'click') {
 *         handleClick();
 *       }
 *     }
 *   });
 *   
 *   return <button ref={buttonRef}>Run</button>;
 * };
 * ```
 */
export function useAIControllable({
  elementId,
  onAction,
  onHighlight,
  ref,
}: AIControllableOptions) {
  const elementIdRef = useRef(elementId);
  elementIdRef.current = elementId;

  // Handle AI interaction events
  useEffect(() => {
    const handleInteract = (e: CustomEvent<AIInteractEvent>) => {
      if (e.detail.element_id !== elementIdRef.current) return;
      
      console.log(`🤖 [${elementIdRef.current}] Received action: ${e.detail.action}`);
      
      if (onAction) {
        onAction(e.detail.action, e.detail.params);
      }
    };

    window.addEventListener('ai-interact', handleInteract as EventListener);
    return () => window.removeEventListener('ai-interact', handleInteract as EventListener);
  }, [onAction]);

  // Handle AI highlight events
  useEffect(() => {
    const handleHighlight = (e: CustomEvent<AIHighlightEvent>) => {
      if (e.detail.element_id !== elementIdRef.current) return;
      
      console.log(`🤖 [${elementIdRef.current}] Highlighting for ${e.detail.duration_ms}ms`);
      
      if (onHighlight) {
        onHighlight(e.detail.duration_ms);
      } else if (ref?.current) {
        // Default highlight behavior using CSS
        const el = ref.current;
        const originalBoxShadow = el.style.boxShadow;
        const originalTransition = el.style.transition;
        
        el.style.transition = 'box-shadow 0.3s ease';
        el.style.boxShadow = '0 0 0 4px rgba(25, 118, 210, 0.8), 0 0 20px rgba(25, 118, 210, 0.4)';
        
        // Scroll into view
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        
        // Remove highlight after duration
        setTimeout(() => {
          el.style.boxShadow = originalBoxShadow;
          setTimeout(() => {
            el.style.transition = originalTransition;
          }, 300);
        }, e.detail.duration_ms);
      }
    };

    window.addEventListener('ai-highlight', handleHighlight as EventListener);
    return () => window.removeEventListener('ai-highlight', handleHighlight as EventListener);
  }, [onHighlight, ref]);
}

/**
 * Hook to listen for AI toast events
 * Use this in your toast provider component
 */
export function useAIToastListener(showToast: (message: string, severity: 'info' | 'success' | 'warning' | 'error') => void) {
  useEffect(() => {
    const handleToast = (e: CustomEvent<{ message: string; severity: string }>) => {
      showToast(e.detail.message, e.detail.severity as any);
    };

    window.addEventListener('ai-toast', handleToast as EventListener);
    return () => window.removeEventListener('ai-toast', handleToast as EventListener);
  }, [showToast]);
}

/**
 * Utility to get current page path for schema lookups
 */
export function useCurrentPagePath(): string {
  // This could use useLocation but keeping it simple
  return window.location.pathname;
}

