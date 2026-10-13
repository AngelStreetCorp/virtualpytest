/**
 * Picture-in-picture mod (TASK-77): a chosen device's stream floats bottom-right over every
 * page; with Take control the remote appears bottom-right and the stream moves bottom-left.
 * It pauses while a page in this browser controls a device, so two streams never show.
 */
import type { ModDefinition } from '../../../../frontend/src/mods/core/types';

import { applyControlChange } from './actions';
import { PipMenuButton } from './components/PipMenuButton';
import { PipOverlay } from './components/PipOverlay';
import { MOD_ID } from './constants';
import { pipStore } from './data/store';

export const pipMod: ModDefinition = {
  id: MOD_ID,
  name: 'Picture-in-picture',
  description: "Keeps a device's stream in a corner on every page, with its remote once you take control.",
  defaultEnabled: true,
  register: (on) => {
    on('control.change', (_$, e, next) => {
      pipStore.update((s) => applyControlChange(s, e));
      next(e);
    });

    on('app.header', (_$, _props, next) => (
      <>
        <PipMenuButton />
        {next()}
      </>
    ));

    on('app.overlay', (_$, _props, next) => (
      <>
        <PipOverlay />
        {next()}
      </>
    ));
  },
};
