import React, { useContext } from 'react';
import { createPortal } from 'react-dom';
import { MobileHeaderSlotContext } from '../../contexts/MobileHeaderSlotContext';

/**
 * Renders its children on the same line as the mobile server picker (MobileServerBar),
 * so a page's header actions don't cost a row of their own on a phone.
 */
export const MobileHeaderActions: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const slot = useContext(MobileHeaderSlotContext)?.slot;
  return slot ? createPortal(children, slot) : null;
};
