import { useContext } from 'react';
import { BuilderContext, BuilderContextType } from './BuilderContext';

export const useBuilder = (): BuilderContextType => {
  const context = useContext(BuilderContext);
  if (!context) {
    throw new Error('useBuilder must be used within a BuilderProvider');
  }
  return context;
};

/**
 * The builder context, or `undefined` when there is no provider above.
 *
 * See the note on `useOptionalTestCaseBuilder`: this exists so components that render
 * both inside and outside a BuilderProvider can read the context with an unconditional
 * hook call, instead of a `try { useBuilder() } catch {}` that rules-of-hooks cannot
 * verify.
 */
export const useOptionalBuilder = (): BuilderContextType | undefined =>
  useContext(BuilderContext);


