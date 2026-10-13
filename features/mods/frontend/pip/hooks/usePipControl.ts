import { useCallback } from 'react';

import { useHostControl } from '../../../../../frontend/src/hooks/useHostManager';
import { useToast } from '../../../../../frontend/src/hooks/useToast';
import { getBrowserSessionId } from '../../../../../frontend/src/hooks/useUserSession';
import { translate } from '../../../../../frontend/src/i18n';
import type { Host } from '../../../../../frontend/src/types/common/Host_Types';
import { pipStore } from '../data/store';

/**
 * Take / release control of the PiP device. Same browser session as the pages (the lock
 * is per browser), but no control.change is sent: PiP's control is not "a page".
 */
export const usePipControl = () => {
  const { takeControl, releaseControl } = useHostControl();
  const { showError } = useToast();

  const take = useCallback(
    async (host: Host, deviceId: string) => {
      pipStore.update((s) => ({ ...s, controlBusy: true }));
      const result = await takeControl(host, deviceId, getBrowserSessionId());
      pipStore.update((s) => ({ ...s, controlBusy: false, ownsControl: result.success }));
      if (!result.success) showError(result.error || translate('Take control failed'));
    },
    [takeControl, showError],
  );

  const release = useCallback(
    async (host: Host, deviceId: string) => {
      pipStore.update((s) => ({ ...s, controlBusy: true }));
      await releaseControl(host, deviceId, getBrowserSessionId()).catch((err) =>
        console.warn('[@mods:pip] release failed', err),
      );
      pipStore.update((s) => ({ ...s, controlBusy: false, ownsControl: false }));
    },
    [releaseControl],
  );

  return { take, release };
};
