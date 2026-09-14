import { useContext } from 'react';
import { BuilderContext, BuilderContextType } from './BuilderContext';

export const useBuilder = (): BuilderContextType => {
  const context = useContext(BuilderContext);
  if (!context) {
    throw new Error('useBuilder must be used within a BuilderProvider');
  }
  return context;
};


