import { createContext } from 'react';

/**
 * The right-hand end of the Dashboard tab row. Overview, Scripts, Devices and System put the time-range toggle
 * there; Hosts and devices portals its filter controls (All Targets, More) into it: one slot, never both.
 */
export const DashFilterSlot = createContext<HTMLElement | null>(null);
