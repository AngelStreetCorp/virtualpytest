/**
 * Is a phone slot usable as a run target right now?
 *
 * A `phone_agent` slot is a device line in a host's `.env`, so core sees it — and offers it in
 * Run Tests — whether or not a phone is paired to it, connected, or actually streaming. Picking
 * one that is not fails on the run's first action, which is a slow and confusing way to find out
 * that a phone is asleep in someone's pocket.
 *
 * Ready means **connected and sending frames**. Connected alone is not enough: a phone whose
 * screen-capture consent was dropped (every app upgrade drops it) stays connected and answers
 * commands while producing no frames at all, so every image, OCR and video verification in the
 * tree fails against a frozen placeholder. That is the "connected · not streaming" state the
 * phone's own page shows.
 *
 * Registered through `targetReadiness` in routes.tsx — core asks, the feature answers, and with
 * the feature disabled core never learns the concept exists.
 */
import { useEffect, useMemo } from 'react';

import { useMobileApp, type PhoneSlot } from './hooks/useMobileApp';

/** How often slot states are re-read while the picker is on screen. */
const POLL_MS = 10_000;

function describe(slot: PhoneSlot): { ready: boolean; reason?: string } {
  if (slot.state !== 'connected') {
    // 'free' (nothing paired), 'pending' (a code was issued, not yet scanned) or 'offline'
    // (paired, phone not reachable) — all the same answer for a run.
    const detail =
      slot.state === 'free'
        ? 'no phone paired'
        : slot.state === 'pending'
          ? 'pairing not finished'
          : 'phone not connected';
    return { ready: false, reason: `${slot.device_name}: ${detail}` };
  }
  // `fps` is the rate the host asked for, not evidence that anything is arriving — it stays
  // at its configured value on a phone that has stopped sending. `streaming` is the real
  // signal. A host too old to report it says nothing, and we do not invent a verdict.
  if (slot.streaming === false) {
    return {
      ready: false,
      reason: `${slot.device_name}: connected but not streaming — grant screen capture on the phone`,
    };
  }
  return { ready: true };
}

export function usePhoneTargetReadiness() {
  const { hosts, refresh } = useMobileApp();

  useEffect(() => {
    const timer = setInterval(() => {
      void refresh();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const byKey = useMemo(() => {
    const map = new Map<string, { ready: boolean; reason?: string }>();
    for (const host of hosts) {
      // A host we could not reach reports slots_error and unknown states. Staying silent there
      // is deliberate: core then shows the slot as it always did, rather than hiding a phone
      // because the server had a bad five seconds.
      if (host.slots_error) continue;
      for (const slot of host.slots || []) {
        map.set(`${host.host_name}:${slot.device_id}`, describe(slot));
      }
    }
    return map;
  }, [hosts]);

  return useMemo(
    () => (hostName: string, deviceId: string) => byKey.get(`${hostName}:${deviceId}`),
    [byKey],
  );
}
