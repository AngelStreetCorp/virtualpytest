import React, { createContext, useContext, useState } from 'react';

interface VNCStateContextType {
  isVNCExpanded: boolean;
  setIsVNCExpanded: (expanded: boolean) => void;
}

const VNCStateContext = createContext<VNCStateContextType | null>(null);

export const VNCStateProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isVNCExpanded, setIsVNCExpanded] = useState(false);

  return (
    <VNCStateContext.Provider value={{ isVNCExpanded, setIsVNCExpanded }}>
      {children}
    </VNCStateContext.Provider>
  );
};

export const useVNCState = (): VNCStateContextType => {
  const context = useContext(VNCStateContext);
  if (!context) {
    throw new Error('useVNCState must be used within a VNCStateProvider');
  }
  return context;
};
