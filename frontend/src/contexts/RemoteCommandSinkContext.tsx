import React, { createContext, useContext } from 'react';

import type { RemoteCommandSink } from '../types/pages/groupControl.types';

const RemoteCommandSinkContext = createContext<RemoteCommandSink | null>(null);

/**
 * TASK-80: keys present on every controlled group member. Buttons outside this
 * set render greyed and the sink returns `ack: 'skipped'` for them. The leaf
 * remote (IR / BLE / ADB / Vega) reads it via `useDisabledRemoteKeys` and
 * decides per-button whether to render the click handler.
 *
 * `null` = no restriction (single-device remote). `[]` = no key is shared
 * (everything is disabled; the group modal shows an empty skin).
 */
const DisabledRemoteKeysContext = createContext<ReadonlySet<string> | null>(null);

/**
 * Routes every remote command sent by `useControllerApi` below it through `sink`
 * (TASK-76 group control). Without a provider the remote sends to its own device.
 */
export const RemoteCommandSinkProvider: React.FC<{
  sink: RemoteCommandSink;
  disabledKeys?: ReadonlyArray<string> | null;
  children: React.ReactNode;
}> = ({ sink, disabledKeys, children }) => (
  <RemoteCommandSinkContext.Provider value={sink}>
    <DisabledRemoteKeysContext.Provider value={disabledKeys ? new Set(disabledKeys) : null}>
      {children}
    </DisabledRemoteKeysContext.Provider>
  </RemoteCommandSinkContext.Provider>
);

export const useRemoteCommandSink = (): RemoteCommandSink | null => useContext(RemoteCommandSinkContext);

/** Read the set of keys disabled in the current group. `null` means "no
 *  restriction" (a single-device remote). */
export const useDisabledRemoteKeys = (): ReadonlySet<string> | null => useContext(DisabledRemoteKeysContext);
