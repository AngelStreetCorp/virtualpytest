/**
 * Run Progress mod (TASK-77): a band under the top bar while scripts, campaigns and
 * test cases run, a side pane with one row per run, and a toast when a run ends.
 */
import { translate } from '../../../../frontend/src/i18n';
import type { ModDefinition } from '../../../../frontend/src/mods/core/types';

import { applyRunEvent, endsRun } from './actions';
import { RunProgressBand } from './components/RunProgressBand';
import { RunProgressPane } from './components/RunProgressPane';
import { MOD_ID, PANE_ID } from './constants';
import { runProgressStore } from './data/store';

export const runProgressMod: ModDefinition = {
  id: MOD_ID,
  name: 'Run Progress',
  description: 'Live progress of running scripts, campaigns and test cases.',
  defaultEnabled: true,
  register: (on) => {
    on('run.update', ($, e, next) => {
      const ended = endsRun(runProgressStore.get(), e);
      runProgressStore.update((s) => applyRunEvent(s, e));
      if (ended) {
        const vars = { kind: e.kind, id: e.id.slice(0, 8) };
        if (e.status === 'completed') $.ui.toast(translate('{kind} {id} passed', vars), 'success');
        else $.ui.toast(translate('{kind} {id} failed', vars), 'error');
      }
      next(e);
    });

    on('app.band', ($, _props, next) => (
      <>
        <RunProgressBand $={$} />
        {next()}
      </>
    ));

    on('app.pane', ($, props, next) => (props.paneId === PANE_ID ? <RunProgressPane $={$} /> : next()));
  },
};
