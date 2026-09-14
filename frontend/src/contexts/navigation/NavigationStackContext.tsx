import React, { createContext, useContext, useState, useCallback } from 'react';
import { BreadcrumbItem } from './NavigationConfigContext';

interface TreeLevel {
  treeId: string;
  treeName: string;
  parentNodeId: string;
  parentNodeLabel: string;
  parentTreeId?: string;
  depth: number;
}

interface NavigationStackContextType {
  stack: TreeLevel[];
  currentLevel: TreeLevel | null;
  breadcrumb: BreadcrumbItem[];
  pushLevel: (treeId: string, parentNodeId: string, treeName: string, parentNodeLabel: string, depth: number, parentTreeId?: string) => void;
  popLevel: () => void;
  jumpToLevel: (targetIndex: number) => void;
  jumpToRoot: () => void;
  loadBreadcrumb: (treeId: string) => Promise<void>;
  isNested: boolean;
  depth: number;
}

const NavigationStackContext = createContext<NavigationStackContextType | null>(null);

export const NavigationStackProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [stack, setStack] = useState<TreeLevel[]>([]);
  const [breadcrumb, setBreadcrumb] = useState<BreadcrumbItem[]>([]);

  const pushLevel = useCallback(
    (treeId: string, parentNodeId: string, treeName: string, parentNodeLabel: string, depth: number, parentTreeId?: string) => {
      setStack((prev) => [...prev, { treeId, treeName, parentNodeId, parentNodeLabel, depth, parentTreeId }]);
    },
    [],
  );

  const popLevel = useCallback(() => {
    setStack((prev) => prev.slice(0, -1));
  }, []);

  const jumpToLevel = useCallback((targetIndex: number) => {
    setStack((prev) => prev.slice(0, targetIndex + 1));
  }, []);

  const jumpToRoot = useCallback(() => {
    setStack([]);
    setBreadcrumb([]);
  }, []);

  const loadBreadcrumb = useCallback(async (_treeId: string) => {
    try {
      // TODO: Implement breadcrumb loading or remove if not needed
      // const breadcrumbData = await navigationConfig.getTreeBreadcrumb(treeId);
      // setBreadcrumb(breadcrumbData);
      setBreadcrumb([]);
    } catch (error) {
      console.error('Failed to load breadcrumb:', error);
      setBreadcrumb([]);
    }
  }, []);

  const currentLevel = stack[stack.length - 1] || null;
  const isNested = stack.length > 0;
  const depth = currentLevel?.depth || 0;

  return (
    <NavigationStackContext.Provider
      value={{
        stack,
        currentLevel,
        breadcrumb,
        pushLevel,
        popLevel,
        jumpToLevel,
        jumpToRoot,
        loadBreadcrumb,
        isNested,
        depth,
      }}
    >
      {children}
    </NavigationStackContext.Provider>
  );
};

export const useNavigationStack = (): NavigationStackContextType => {
  const context = useContext(NavigationStackContext);
  if (!context) {
    throw new Error('useNavigationStack must be used within a NavigationStackProvider');
  }
  return context;
};
