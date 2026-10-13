/**
 * Split view mod (TASK-77): a second page side by side with the current one, like Chrome's
 * split view. The second page is this app in a frame (it hides its own top bar and mods),
 * so each side keeps its own state. Top-bar button or Ctrl + Alt + S.
 */
import type { ModDefinition } from '../../../../frontend/src/mods/core/types';

import { SplitPane } from './components/SplitPane';
import { SplitViewButton } from './components/SplitViewButton';
import { MOD_ID } from './constants';

export const splitViewMod: ModDefinition = {
  id: MOD_ID,
  name: 'Split view',
  description: 'Open a second page side by side, like the Device page next to the Heatmap.',
  defaultEnabled: true,
  register: (on) => {
    on('app.header', (_$, _props, next) => (
      <>
        <SplitViewButton />
        {next()}
      </>
    ));

    on('app.side', (_$, _props, next) => (
      <>
        <SplitPane />
        {next()}
      </>
    ));
  },
};
