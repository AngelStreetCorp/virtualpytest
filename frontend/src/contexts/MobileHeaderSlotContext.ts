import { createContext } from 'react';

export interface MobileHeaderSlotContextType {
  /** DOM node right of the mobile server picker; null until MobileServerBar mounts. */
  slot: HTMLElement | null;
  setSlot: (node: HTMLElement | null) => void;
}

export const MobileHeaderSlotContext = createContext<MobileHeaderSlotContextType | null>(null);
