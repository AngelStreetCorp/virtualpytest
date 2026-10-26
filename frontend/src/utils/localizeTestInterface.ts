/** Interfaces made by tests, benches and copies: hidden by default on the Localize coverage page. */
export const isTestInterface = (name: string): boolean =>
  name.startsWith('__') ||
  name.startsWith('acceptance-') ||
  name.includes('-bench-') ||
  name.includes('_bench_') ||
  name.endsWith('_copy') ||
  name.endsWith('-copy');
