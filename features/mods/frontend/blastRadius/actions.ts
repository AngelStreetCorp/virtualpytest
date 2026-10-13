/** Pure rules of the Blast Radius mod. */
import type { DeviceCommandEvent } from '../../../../frontend/src/mods/core/types';

import { DANGEROUS_COMMANDS } from './constants';
import type { CommandWarning } from './types';

export const needsConfirm = (e: DeviceCommandEvent): boolean => DANGEROUS_COMMANDS.has(e.command);

/** The dialog for a dangerous command; English text is the i18n key. */
export const warningFor = (e: DeviceCommandEvent): CommandWarning => {
  const vars = { device: e.deviceId, host: e.hostName };
  if (e.command === 'reboot') {
    return {
      title: 'Reboot {device}?',
      message: 'This cuts power to {device} on {host} and starts it again. A run or a live session on it stops.',
      confirmText: 'Reboot',
      vars,
    };
  }
  return {
    title: 'Power off {device}?',
    message: 'This cuts power to {device} on {host}. A run or a live session on it stops, and it stays off until someone powers it on.',
    confirmText: 'Power off',
    vars,
  };
};
