import React, { useMemo, useState } from 'react';
import { MobileHeaderSlotContext } from './MobileHeaderSlotContext';

export const MobileHeaderSlotProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const value = useMemo(() => ({ slot, setSlot }), [slot]);
  return <MobileHeaderSlotContext.Provider value={value}>{children}</MobileHeaderSlotContext.Provider>;
};
