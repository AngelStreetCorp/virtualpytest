import React, { createContext, useContext, useMemo, useState } from 'react';

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

/**
 * Provides the VNC state when no ancestor does.
 *
 * The player (`VNCStream`) and the browser terminal (`PlaywrightWebTerminal`) read the same
 * "is the panel expanded" flag, so they have to sit under one provider. The pages that host
 * them usually wrap themselves (the navigation editor, the Rec stream modal, AgentChat, the
 * Quick Test builder), but the panels that render a player on their own — the
 * picture-in-picture overlay, the test case builder, the virtual scripts page — used to
 * crash with "useVNCState must be used within a VNCStateProvider" the moment a `host_vnc`
 * device was picked (BUG-0192, BUG-0777).
 *
 * This boundary gives such a page its own provider instead of throwing. An ancestor's
 * provider still wins, so where the state is meant to be shared it stays shared, and the
 * rendered tree keeps the same shape (the provider is always there), so nothing remounts
 * when the state changes.
 */
export const VNCStateBoundary: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const outer = useContext(VNCStateContext);
  const [ownExpanded, setOwnExpanded] = useState(false);
  const own = useMemo(
    () => ({ isVNCExpanded: ownExpanded, setIsVNCExpanded: setOwnExpanded }),
    [ownExpanded],
  );
  const value = outer ?? own;

  return <VNCStateContext.Provider value={value}>{children}</VNCStateContext.Provider>;
};

export const useVNCState = (): VNCStateContextType => {
  const context = useContext(VNCStateContext);
  if (!context) {
    throw new Error('useVNCState must be used within a VNCStateProvider');
  }
  return context;
};
