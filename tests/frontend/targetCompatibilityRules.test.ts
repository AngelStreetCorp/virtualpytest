import { describe, expect, it } from 'vitest';

import {
  effectiveTargetRules,
  isTargetKeyCompatibleWithRules,
  NO_DECLARED_RULES,
} from '../../frontend/src/utils/targetCompatibility';
import type { Host } from '../../frontend/src/types/common/Host_Types';

/**
 * BUG-0789 — the Run page must answer "what are the rules of this executable"
 * the same way the SERVER does, in ONE place.
 *
 * The server only checks the rules a script really declares:
 *
 * - no `_target_rules` at all, or an empty one -> `extract_script_target_rules()`
 *   returns None and nothing is checked, so the script runs on any target;
 * - a partial rule -> `normalize_target_rules()` fills the gaps with
 *   device / all / all.
 *
 * The frontend used to answer "no rules" as 'device' in the pruning step and
 * as 'all' in the list step. Picking a rule-less script then deleted the
 * operator's host-level target without a word.
 */

const hostWithBrowserDevice = {
  host_name: 'labox-backend',
  devices: [
    { device_id: 'host', device_model: 'host_vnc', device_name: 'labox-backend' },
  ],
} as unknown as Host;

describe('effectiveTargetRules', () => {
  it('treats an executable with no rules as compatible with every target', () => {
    expect(effectiveTargetRules(undefined)).toEqual(NO_DECLARED_RULES);
    expect(effectiveTargetRules(null)).toEqual(NO_DECLARED_RULES);
  });

  it('treats an empty rule object as no rules, like the server does', () => {
    // extract_script_target_rules() returns None for an empty dict, so the
    // server checks nothing for it and the script runs anywhere.
    expect(effectiveTargetRules({})).toEqual(NO_DECLARED_RULES);
  });

  it('reads a partial rule the way the backend reads it', () => {
    // normalize_target_rules() / normalizeTargetRules(): a missing target_type
    // means 'device', a missing model means 'all'.
    expect(effectiveTargetRules({ host_os: 'linux' })).toEqual({
      target_type: 'device',
      host_os: 'linux',
      device_model: 'all',
    });
  });

  it('keeps a declared rule as it is', () => {
    expect(effectiveTargetRules({ target_type: 'host' })).toEqual({
      target_type: 'host',
      host_os: 'all',
      device_model: 'all',
    });
    expect(
      effectiveTargetRules({ target_type: 'device', device_model: 'android_mobile' }),
    ).toEqual({
      target_type: 'device',
      host_os: 'all',
      device_model: 'android_mobile',
    });
  });
});

describe('a rule-less executable against a host-level target', () => {
  it('fits the host_vnc pseudo-device', () => {
    expect(
      isTargetKeyCompatibleWithRules(
        'labox-backend:host',
        [hostWithBrowserDevice],
        effectiveTargetRules(undefined),
      ),
    ).toBe(true);
  });

  it('fits it because the rules are the shared no-rules constant', () => {
    // The list and the pruning must read the SAME rules, or the target can
    // vanish between the two (the QA-OPS-19 / BUG-0789 bug).
    expect(effectiveTargetRules(undefined)).toBe(NO_DECLARED_RULES);
  });
});
