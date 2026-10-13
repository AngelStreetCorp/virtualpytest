/**
 * Mod registry: collects every mod's hooks and runs them as chains.
 * A hook that throws is logged and skipped; the chain goes on without it.
 */
import type { ReactNode } from 'react';

import type {
  EventHook,
  GateHook,
  GateName,
  GateResult,
  ModApi,
  ModEventEnvelope,
  ModGates,
  ModDefinition,
  ModEventName,
  ModEvents,
  ModRegistry,
  On,
  SlotHook,
  SlotName,
  ModSlots,
} from './types';
import { ALLOW, EVENT_NAMES, GATE_NAMES, SLOT_NAMES } from './constants';

interface Entry<H = unknown> {
  modId: string;
  hook: H;
}

const isEvent = (name: string): name is ModEventName => (EVENT_NAMES as readonly string[]).includes(name);
const isSlot = (name: string): name is SlotName => (SLOT_NAMES as readonly string[]).includes(name);
const isGate = (name: string): name is GateName => (GATE_NAMES as readonly string[]).includes(name);

export const createModRegistry = (mods: ModDefinition[]): ModRegistry => {
  // Hooks are stored untyped and narrowed back by name in emit/render.
  const eventHooks = new Map<ModEventName, Entry[]>();
  const slotHooks = new Map<SlotName, Entry[]>();
  const gateHooks = new Map<GateName, Entry[]>();

  for (const mod of mods) {
    const on = ((name: string, hook: unknown) => {
      if (isEvent(name)) {
        eventHooks.set(name, [...(eventHooks.get(name) ?? []), { modId: mod.id, hook }]);
      } else if (isSlot(name)) {
        slotHooks.set(name, [...(slotHooks.get(name) ?? []), { modId: mod.id, hook }]);
      } else if (isGate(name)) {
        gateHooks.set(name, [...(gateHooks.get(name) ?? []), { modId: mod.id, hook }]);
      } else {
        console.warn(`[@mods] ${mod.id}: unknown event or slot "${name}"`);
      }
    }) as On;
    try {
      mod.register(on);
    } catch (err) {
      console.warn(`[@mods] ${mod.id}: register failed`, err);
    }
  }

  const emit = <K extends ModEventName>($: ModApi, event: K, e: ModEvents[K]) => {
    const chain = (eventHooks.get(event) ?? []) as unknown as Entry<EventHook<K>>[];
    const run = (i: number, value: ModEvents[K]): void => {
      const entry = chain[i];
      if (!entry) return;
      let passed = false;
      try {
        entry.hook($, value, (next) => {
          passed = true;
          run(i + 1, next);
        });
      } catch (err) {
        console.warn(`[@mods] ${entry.modId}: ${event} hook failed`, err);
        // A hook that threw after passing on must not run the rest twice.
        if (!passed) run(i + 1, value);
      }
    };
    run(0, e);
  };

  const render = <K extends SlotName>($: ModApi, slot: K, props: ModSlots[K], fallback: ReactNode): ReactNode => {
    const chain = (slotHooks.get(slot) ?? []) as unknown as Entry<SlotHook<K>>[];
    const run = (i: number): ReactNode => {
      const entry = chain[i];
      if (!entry) return fallback;
      try {
        return entry.hook($, props, () => run(i + 1));
      } catch (err) {
        console.warn(`[@mods] ${entry.modId}: ${slot} hook failed`, err);
        return run(i + 1);
      }
    };
    return run(0);
  };

  const dispatch = ($: ModApi, envelope: ModEventEnvelope) => emit($, envelope.name, envelope.e as never);

  // A gate hook that throws or rejects is skipped, like any other hook: a broken mod never
  // blocks the app. Refusing is an explicit `{ allow: false, reason }`.
  const gate = async <K extends GateName>($: ModApi, name: K, e: ModGates[K]): Promise<GateResult> => {
    const chain = (gateHooks.get(name) ?? []) as unknown as Entry<GateHook<K>>[];
    const run = async (i: number, value: ModGates[K]): Promise<GateResult> => {
      const entry = chain[i];
      if (!entry) return ALLOW;
      let passed = false;
      try {
        return await entry.hook($, value, (next) => {
          passed = true;
          return run(i + 1, next);
        });
      } catch (err) {
        console.warn(`[@mods] ${entry.modId}: ${name} gate failed`, err);
        return passed ? ALLOW : run(i + 1, value);
      }
    };
    return run(0, e);
  };

  const widgets = mods.flatMap((m) => m.widgets ?? []);

  return { mods, widgets, emit, dispatch, render, gate };
};
