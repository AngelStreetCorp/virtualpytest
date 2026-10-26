import { defineConfig, mergeConfig } from 'vitest/config';

import viteConfig from './vite.config';

// A bare `vitest` run from frontend/ (no --config) used vite.config.ts alone, and vitest 2 then
// forks one worker per CPU: 15 workers at ~330 MB on a 16-core Mac, started by several agents at
// once, filled RAM and swap (2026-10-18). Same cap as tests/frontend/vitest.config.ts, which
// CI and scripts/run-vitest.sh use.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      poolOptions: { forks: { minForks: 1, maxForks: 4 } },
    },
  }),
);
