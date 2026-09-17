import { useEffect, useState } from 'react';

import { isNativeApp } from '../config/runtimeConfig';

/**
 * Reactive `isNativeApp()`, for components that decide their layout from it.
 *
 * `isNativeApp()` is a plain function read during render, and one of the two signals it
 * looks at (`window.Capacitor`) is installed by a script the native shell injects into
 * index.html rather than being there from the start. A component that only ever asks once,
 * while rendering, can therefore latch onto the web answer and never recover — which is
 * exactly how the app came to show its web bottom nav, with no "This phone" tab, inside the
 * APK. The native `/config.js` flag makes the answer deterministic for current builds; this
 * re-check after mount is the belt to that pair of braces, so a late bridge still flips the
 * UI over instead of leaving it wrong for the whole session.
 */
export const useIsNativeApp = (): boolean => {
  const [native, setNative] = useState(isNativeApp);

  useEffect(() => {
    if (native) return;
    setNative(isNativeApp());
  }, [native]);

  return native;
};
