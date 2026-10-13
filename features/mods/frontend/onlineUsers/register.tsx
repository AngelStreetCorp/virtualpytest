/**
 * Online Users mod (TASK-77): "N online" in the top bar, with who in the tooltip, from the
 * server's presence_changed updates (one per connect / disconnect in this team).
 */
import type { ModDefinition } from '../../../../frontend/src/mods/core/types';

import { OnlineChip } from './components/OnlineChip';
import { MOD_ID } from './constants';
import { onlineStore } from './data/store';

export const onlineUsersMod: ModDefinition = {
  id: MOD_ID,
  name: 'Online Users',
  description: 'Shows how many people of your team are on the platform now, and who.',
  defaultEnabled: true,
  register: (on) => {
    on('presence.update', (_$, e, next) => {
      onlineStore.update(() => e);
      next(e);
    });

    on('app.header', (_$, _props, next) => (
      <>
        <OnlineChip />
        {next()}
      </>
    ));
  },
};
