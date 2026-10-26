import { useCallback, useState } from 'react';

import { ConfirmDialog } from '../../components/common/ConfirmDialog';
import { useI18n } from '../../i18n/useI18n';
import { useDeviceMaintenanceLookup } from './useDeviceMaintenance';

/**
 * Confirm before taking control of / running on a device that is under maintenance (TASK-97 G6).
 * `guard(host, device, proceed)` calls `proceed` right away for a device that is not covered, otherwise after
 * the operator confirms "Device under maintenance - continue?". Render `guardDialog` once in the component.
 */
export const useMaintenanceGuard = () => {
  const { t, formatDate } = useI18n();
  const lookup = useDeviceMaintenanceLookup();
  const [pending, setPending] = useState<{ message: string; proceed: () => void } | null>(null);

  /** Proceeds at once unless one of `devices` is covered; then asks first (the earliest-ending window is quoted). */
  const guardAny = useCallback(
    (devices: Array<{ hostName: string | undefined | null; deviceId: string | undefined | null }>, proceed: () => void) => {
      const wins = devices.map((d) => lookup(d.hostName, d.deviceId)).filter((w): w is NonNullable<typeof w> => !!w);
      if (wins.length === 0) {
        proceed();
        return;
      }
      const win = wins.sort((x, y) => Date.parse(x.window_end) - Date.parse(y.window_end))[0];
      const until = formatDate(new Date(win.window_end), { timeStyle: 'short' });
      const reason = win.reason || win.note || '';
      setPending({
        message: reason
          ? t('Under maintenance until {time} — {reason}', { time: until, reason })
          : t('Under maintenance until {time}', { time: until }),
        proceed,
      });
    },
    [lookup, t, formatDate],
  );

  const guard = useCallback(
    (hostName: string | undefined | null, deviceId: string | undefined | null, proceed: () => void) =>
      guardAny([{ hostName, deviceId }], proceed),
    [guardAny],
  );

  const guardDialog = (
    <ConfirmDialog
      open={pending !== null}
      title={t('Device under maintenance')}
      message={pending ? `${pending.message}\n${t('Continue anyway?')}` : ''}
      confirmText={t('Continue')}
      cancelText={t('Cancel')}
      confirmColor="warning"
      onConfirm={() => {
        const run = pending?.proceed;
        setPending(null);
        run?.();
      }}
      onCancel={() => setPending(null)}
    />
  );

  return { guard, guardAny, guardDialog };
};
