/**
 * Team devices mod (TASK-77): offers the "Team devices" widget — the team's devices with
 * tests running now and errors: failed runs (24 h or 7 days, from the stored script results)
 * or open alerts, per the widget's setting. Running runs come from run.update (live + snapshot).
 */
import type { ModDefinition } from '../../../../frontend/src/mods/core/types';

import { applyRun } from './actions';
import { TeamDevicesWidget } from './components/TeamDevicesWidget';
import { ERRORS_FAILED_24H, ERRORS_FAILED_7D, ERRORS_OPEN_ALERTS, MOD_ID, SHOW_ACTIVE, SHOW_ALL, WIDGET_ID } from './constants';
import { fleetStore } from './data/store';

export const teamDevicesMod: ModDefinition = {
  id: MOD_ID,
  name: 'Team devices widget',
  description: 'A Dashboard widget with your team devices, tests running and failed runs today.',
  defaultEnabled: true,
  register: (on) => {
    on('run.update', (_$, e, next) => {
      fleetStore.update((s) => {
        const running = applyRun(s.running, e);
        return running === s.running ? s : { ...s, running };
      });
      next(e);
    });
  },
  widgets: [
    {
      id: WIDGET_ID,
      name: 'Team devices',
      description: 'Devices, tests running, and failed runs or open alerts.',
      size: 'medium',
      settings: [
        {
          key: 'show',
          label: 'Show',
          type: 'select',
          default: SHOW_ALL,
          options: [
            { value: SHOW_ALL, label: 'All devices' },
            { value: SHOW_ACTIVE, label: 'Only busy, failing or offline devices' },
          ],
        },
        {
          key: 'errors',
          label: 'Count as errors',
          type: 'select',
          default: ERRORS_FAILED_24H,
          options: [
            { value: ERRORS_FAILED_24H, label: 'Failed runs, last 24 h' },
            { value: ERRORS_FAILED_7D, label: 'Failed runs, last 7 days' },
            { value: ERRORS_OPEN_ALERTS, label: 'Open alerts' },
          ],
        },
      ],
      Component: TeamDevicesWidget,
    },
  ],
};
