import { createStore } from '../../../../../frontend/src/mods/core/data/createStore';
import { initialRunProgressState } from '../actions';
import type { RunProgressState } from '../types';

/** Lives for the page session, so the band survives route changes. */
export const runProgressStore = createStore<RunProgressState>(initialRunProgressState);
