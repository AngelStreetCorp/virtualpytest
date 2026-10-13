import React from 'react';

import type { ModSlots, SlotName } from '../types';

import { ModErrorBoundary } from './ModErrorBoundary';
import { useMods } from './ModsProvider';

interface Props<K extends SlotName> {
  name: K;
  props: ModSlots[K];
  /** What the app draws when no mod draws here. */
  fallback?: React.ReactNode;
}

/** A place in the app mods can draw into. */
export const ModSlot = <K extends SlotName>({ name, props, fallback = null }: Props<K>) => {
  const { registry, api } = useMods();
  return (
    <ModErrorBoundary slot={name} fallback={fallback}>
      {registry.render(api, name, props, fallback)}
    </ModErrorBoundary>
  );
};
