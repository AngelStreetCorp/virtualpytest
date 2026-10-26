import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';

import type { Device, Host } from '../../types/common/Host_Types';

/** A device chosen by a device_picker block, as the blocks that read it need it. */
export interface DeviceRef {
  host: Host;
  device: Device;
}

interface PageRuntimeValue {
  pageId: string;
  /** Chosen device per device_picker block id. */
  picks: Record<string, DeviceRef | null>;
  setPick: (blockId: string, ref: DeviceRef | null) => void;
}

const PageRuntimeContext = createContext<PageRuntimeValue | null>(null);

/** Per-view state shared by the blocks of one custom page (which device each picker holds). */
export const PageRuntimeProvider: React.FC<{ pageId: string; children: React.ReactNode }> = ({ pageId, children }) => {
  const [picks, setPicks] = useState<Record<string, DeviceRef | null>>({});
  const setPick = useCallback((blockId: string, ref: DeviceRef | null) => {
    setPicks((prev) => (prev[blockId]?.device === ref?.device && prev[blockId]?.host === ref?.host ? prev : { ...prev, [blockId]: ref }));
  }, []);
  const value = useMemo(() => ({ pageId, picks, setPick }), [pageId, picks, setPick]);
  return <PageRuntimeContext.Provider value={value}>{children}</PageRuntimeContext.Provider>;
};

export const usePageRuntime = (): PageRuntimeValue => {
  const ctx = useContext(PageRuntimeContext);
  if (!ctx) throw new Error('usePageRuntime must be used inside PageRuntimeProvider');
  return ctx;
};

/** The device chosen by the picker a block reads from (`device_from`), or null. */
export const useBlockDevice = (deviceFrom: unknown): DeviceRef | null => {
  const { picks } = usePageRuntime();
  return typeof deviceFrom === 'string' ? (picks[deviceFrom] ?? null) : null;
};
