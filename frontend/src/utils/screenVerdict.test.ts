/**
 * The Screen row of the monitoring overlay must let an operator read WHAT was decided,
 * HOW confidently, WHICH tier answered, and WHY it abstained. These tests pin the
 * formatting of that diagnosis, and — deliberately — that an abstain stays calm grey
 * (an abstain is normal behaviour, not an error).
 *
 * `tier`/`reason`/`door` are additive and optional: archived frames written before the
 * backend reported them must keep rendering the plain verdict, so the diagnosis must
 * degrade to null rather than throw or invent a door.
 */
import { describe, expect, it } from 'vitest';

import {
  formatScreenDiagnosis,
  formatScreenVerdict,
  SCREEN_CONF_GREEN,
  type ScreenVerdict,
} from './screenVerdict';

const matched = (over: Partial<ScreenVerdict> = {}): ScreenVerdict => ({
  node: 'apps_netflix',
  confidence: 0.9,
  excluded: 40,
  total: 41,
  ...over,
});

describe('formatScreenDiagnosis', () => {
  it('reports the answering tier on a confident match', () => {
    const d = formatScreenDiagnosis(matched({ tier: 'rule' }));

    expect(d).not.toBeNull();
    expect(d!.tier).toBe('rule');
    expect(d!.door).toBeNull();
  });

  it('maps every abstain door to a human phrase', () => {
    const phrases = ['1', '2', '3', '4', '5', '6'].map(
      (door) => formatScreenDiagnosis({ node: null, door, reason: 'x' })!.door,
    );

    // Every door has its own phrase — none falls back to the generic unknown text.
    expect(new Set(phrases).size).toBe(6);
    phrases.forEach((p) => expect(p).toBeTruthy());
  });

  it('renders an unrecognised door as the generic unknown phrase, still calm grey', () => {
    const d = formatScreenDiagnosis({ node: null, door: '7', reason: 'brand new door' });

    expect(d!.door).toBe('no recognizable screen');
    // An abstain must never read as an error: grey, same family as 'unknown screen'.
    expect(d!.color).toBe(formatScreenVerdict({ node: null }).color);
    expect(d!.reason).toBe('brand new door');
  });

  it('keeps the door grey and the tier dim, so neither looks like an error', () => {
    const abstain = formatScreenDiagnosis({ node: null, tier: 'rule', door: '1' })!;
    const match = formatScreenDiagnosis(matched({ tier: 'rule' }))!;

    expect(abstain.color).toBe('#9e9e9e');
    expect(match.color).toBe('#888888');
    expect(match.color).not.toBe('#ff4444');
  });

  it('normalises tier case and passes an unknown tier through instead of dropping it', () => {
    expect(formatScreenDiagnosis(matched({ tier: 'RULE' }))!.tier).toBe('rule');
    // 'cv' / 'model' are reserved by the backend, so the label exists even though this
    // path never emits them — an unknown value must still surface rather than vanish.
    expect(formatScreenDiagnosis(matched({ tier: 'model' }))!.tier).toBe('model');
    expect(formatScreenDiagnosis(matched({ tier: 'something_new' }))!.tier).toBe('something_new');
  });

  it('returns null when the payload carries no diagnosis (older frame, clean match)', () => {
    expect(formatScreenDiagnosis(null)).toBeNull();
    expect(formatScreenDiagnosis(undefined)).toBeNull();
    expect(formatScreenDiagnosis(matched())).toBeNull(); // no tier, no door
    expect(formatScreenDiagnosis({ node: null, tier: '', door: '' })).toBeNull();
  });
});

describe('formatScreenVerdict (unchanged behaviour)', () => {
  it('still colours a confident single match green and a weak match amber', () => {
    expect(formatScreenVerdict(matched()).text).toBe('apps_netflix (90%)');
    expect(formatScreenVerdict(matched()).color).toBe(formatScreenVerdict({
      ...matched(),
      confidence: SCREEN_CONF_GREEN,
    }).color);
  });

  it('still shows a named capture state and a plain unknown screen', () => {
    expect(formatScreenVerdict({ state: 'blackscreen', state_label: 'Black Screen' }).text).toBe(
      'Black Screen',
    );
    expect(formatScreenVerdict({ node: null, door: '1' }).text).toBe('unknown screen');
  });
});

describe('formatScreenVerdict Tier-2 priority (2026-10-11 fix)', () => {
  // The bug: a healthy frame with {node, error:'none', overlay:'none', loaded:'yes'} used
  // to render as 'Error: none' in the primary slot and bury the matched node behind a
  // badge. After the fix, 'none' is the absence of an error and must NOT claim primary;
  // 'yes' is the normal settled state and must not shadow the node either. Only the
  // genuinely-noteworthy Tier-2 values (error=='visible', overlay!=none, playback
  // playing/paused, loaded=='no') own the primary.
  const healthy = (over: Partial<ScreenVerdict> = {}): ScreenVerdict => ({
    node: 'home',
    confidence: 0.95,
    excluded: 0,
    total: 1,
    error: 'none',
    overlay: 'none',
    playback: 'not_applicable',
    loaded: 'yes',
    ...over,
  });

  it("does not let 'Error: none' shadow the matched node", () => {
    const r = formatScreenVerdict(healthy());
    expect(r.text).toBe('home (95%)');
    // 'Error: none' must not even be a badge — 'none' is the absence of an error.
    expect((r.badges ?? []).find((b) => b.text.startsWith('error:'))).toBeUndefined();
  });

  it("does not let 'Overlay: none' shadow the matched node", () => {
    const r = formatScreenVerdict(healthy({ overlay: 'none' }));
    expect(r.text).toBe('home (95%)');
  });

  it("does not let 'loaded: yes' shadow the matched node (the normal settled state)", () => {
    // 'yes' must drop to a dim badge, never to the primary slot.
    const r = formatScreenVerdict(healthy({ loaded: 'yes' }));
    expect(r.text).toBe('home (95%)');
    const loadedBadge = (r.badges ?? []).find((b) => b.text === 'loaded');
    expect(loadedBadge).toBeDefined();
  });

  it("does let 'loaded: no' claim the primary — it is the transient 'still loading' state", () => {
    const r = formatScreenVerdict(healthy({ loaded: 'no' }));
    expect(r.text).toBe('loading…');
  });

  it("does let 'error: visible' claim the primary", () => {
    const r = formatScreenVerdict(healthy({ error: 'visible' }));
    expect(r.text).toBe('Error: visible');
  });

  it("does let 'overlay: popup' claim the primary", () => {
    const r = formatScreenVerdict(healthy({ overlay: 'popup' }));
    expect(r.text).toBe('Overlay: popup');
  });

  it("does let 'playback: playing' claim the primary", () => {
    const r = formatScreenVerdict(healthy({ playback: 'playing' }));
    expect(r.text).toBe('playing');
  });

  it("does not let 'playback: not_applicable' or 'stopped' claim the primary", () => {
    expect(formatScreenVerdict(healthy({ playback: 'not_applicable' })).text).toBe('home (95%)');
    expect(formatScreenVerdict(healthy({ playback: 'stopped' })).text).toBe('home (95%)');
  });

  it("state still wins over a node (capture-side state is the highest-priority signal)", () => {
    const r = formatScreenVerdict(healthy({ state: 'blackscreen', state_label: 'Black Screen' }));
    expect(r.text).toBe('Black Screen');
  });
});