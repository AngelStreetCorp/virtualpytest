/**
 * Blast Radius mod (TASK-77): asks before a device is powered off or rebooted, so one
 * misclick does not stop someone else's run.
 */
import { translate } from '../../../../frontend/src/i18n';
import type { ModDefinition } from '../../../../frontend/src/mods/core/types';

import { needsConfirm, warningFor } from './actions';
import { MOD_ID } from './constants';

export const blastRadiusMod: ModDefinition = {
  id: MOD_ID,
  name: 'Blast Radius',
  description: 'Asks to confirm before a device is powered off or rebooted.',
  defaultEnabled: true,
  register: (on) => {
    on('device.command', async ($, e, next) => {
      if (!needsConfirm(e)) return next(e);
      const w = warningFor(e);
      const ok = await $.ui.confirm({
        title: translate(w.title, w.vars),
        message: translate(w.message, w.vars),
        confirmText: translate(w.confirmText),
        danger: true,
      });
      return ok ? next(e) : { allow: false, reason: 'cancelled' };
    });
  },
};
