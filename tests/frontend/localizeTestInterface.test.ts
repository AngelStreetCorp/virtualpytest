import { describe, expect, it } from 'vitest';

import { isTestInterface } from '../../frontend/src/utils/localizeTestInterface';

describe('isTestInterface', () => {
  it.each([
    'acceptance-stb4-tv-20261004-0437',
    '__smoke_test_ui_x',
    '__ci_fixture_interface__',
    'vpttv-ch-bench-1',
    'x_bench_2',
    'stb_tv_autobuild_copy',
    'web-copy',
  ])('%s is a test interface', (n) => expect(isTestInterface(n)).toBe(true));

  it.each(['stb_tv', 'stb_android_tv', 'web_tv', 'copyright_ui'])('%s is real', (n) =>
    expect(isTestInterface(n)).toBe(false),
  );
});
