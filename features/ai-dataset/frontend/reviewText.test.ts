/**
 * The review page's pure helpers (reviewText.ts): the Set default per Show view, labels in
 * words and the triage note (never JSON). Run by the frontend-component-tests job.
 */
import { describe, expect, it } from 'vitest';

import type { ScreenGroup, TrainingFilters, TrainingSample } from './hooks/useTrainingSamples';
import {
  STRIP_ANSWERS, STRIP_DURING_TOLERANCE_MS, acceptButtonText, focusGuessSource, focusLineState, frameChipText,
  framePhase, labelWords, stripAnswerWords, stripDurationText, stripFrames, triageNoteText, withShow,
} from './reviewText';

const FILTERS: TrainingFilters = {
  family: '', split: 'eval', show: 'unchecked', isFailure: '', deviceModel: '', balance: true, confusable: false,
};

const GROUPS: ScreenGroup[] = [
  {
    node_id: 'g-settings',
    label: 'settings',
    members: [
      { node_id: 'g-settings', label: 'settings', focus: null },
      { node_id: 'n-settings-system', label: 'settings_system', focus: 'system' },
    ],
  },
];

const sample = (over: Partial<TrainingSample>): TrainingSample => ({
  id: 's1', family: 'screen-id', object_key: 'k', device_model: 'm', userinterface: 'ui', node_id: null,
  focus_label: null, prompt: null, model_answer: null, ground_truth: null, proposed_label: null, guess_source: 'run',
  label_source: 'run', is_failure: false, label_conflict: false, split: 'train', eval_version: null, source_ref: null,
  created_at: '2026-09-30T00:00:00Z', image_path: null, triage: null, ...over,
});

describe('withShow: the Set follows the Show view', () => {
  it('"Needs you" starts on All sets', () => {
    expect(withShow(FILTERS, 'needs_you', false)).toMatchObject({ show: 'needs_you', split: '' });
  });

  it('the other views go back to Eval', () => {
    const needsYou = withShow(FILTERS, 'needs_you', false);
    expect(withShow(needsYou, 'unchecked', false).split).toBe('eval');
    expect(withShow(needsYou, 'checked', false).split).toBe('eval');
  });

  it('keeps a Set the user picked', () => {
    expect(withShow({ ...FILTERS, split: 'train' }, 'needs_you', true).split).toBe('train');
    expect(withShow({ ...FILTERS, split: 'eval' }, 'needs_you', true).split).toBe('eval');
    expect(withShow({ ...FILTERS, split: '' }, 'unchecked', true).split).toBe('');
  });
});

describe('labelWords', () => {
  it('names a grouped screen with its focus', () => {
    expect(labelWords('screen-id', { node_id: 'g-settings', label: 'settings', node: 'n-settings-system', focus: 'system' }))
      .toBe('settings, system focused');
    expect(labelWords('screen-id', { focus: null, label: 'settings', node: 'g-settings', node_id: 'g-settings' })).toBe('settings');
  });

  it('names a pre-4k node label through the groups, never a uuid', () => {
    expect(labelWords('screen-id', { node_id: 'n-settings-system', label: 'settings_system' }, GROUPS)).toBe('settings, system focused');
    expect(labelWords('screen-id', { node_id: 'x', label: '0f8fad5b-d9cb-469f-a165-70867728950e' })).toBe('');
    expect(labelWords('screen-id', { node_id: null, label: 'popup' })).toBe('popup (a screen not in the tree)');
  });

  it('words the other families', () => {
    expect(labelWords('focus', { focused: null })).toBe('nothing focused');
    expect(labelWords('focus', { focused: 'Apps' })).toBe('Apps');
    expect(labelWords('banner', { channel_number: '101', channel_name: 'BBC One' })).toBe('channel 101 (BBC One)');
    expect(labelWords('banner', { channel_number: null, channel_name: null })).toBe('no channel banner');
    expect(labelWords('av-fault', { incident_type: 'blackscreen' })).toBe('black screen');
    expect(labelWords('av-fault', { incident_type: null, static_screen: true })).toBe('still screen');
    expect(labelWords('av-fault', { incident_type: null, static_screen: false })).toBe('picture was moving');
    expect(labelWords('av-fault', { incident_type: null })).toBe('no fault');
    expect(labelWords('menu', { items: ['Home', 'Guide'], selected: 'Guide' })).toBe('Home, Guide (Guide selected)');
  });

  it('never falls back to JSON', () => {
    expect(labelWords('other', { a: 1, b: [2] })).toBe('');
    expect(labelWords('content-type', { kind: 'live' })).toBe('');
    expect(labelWords('screen-id', null)).toBe('');
  });
});

describe('triageNoteText', () => {
  const conflictRow = sample({
    label_conflict: true,
    conflict_partner: { id: 'p1', ground_truth: { node_id: 'n-settings-system', label: 'settings_system' } },
    triage: {
      status: 'needs_human', reason: 'conflict',
      teacher_label: { focus: null, label: 'settings', node: 'g-settings', node_id: 'g-settings' },
    },
  });

  it('names the conflict partner and the AI answer in words', () => {
    const note = triageNoteText(conflictRow)!;
    expect(note.kind).toBe('conflict');
    expect(note.partner).toBe('settings_system');
    expect(note.aiSaid).toBe('settings');
    expect(Object.values(note).join(' ')).not.toMatch(/node_id|[{}"]/);
  });

  it('uses the screen group of the partner when the groups are known', () => {
    const note = triageNoteText(conflictRow, GROUPS)!;
    expect(note.partner).toBe('settings, system focused');
  });

  it('drops "AI said" when it repeats the partner label', () => {
    const same = sample({
      ...conflictRow,
      triage: { status: 'needs_human', reason: 'conflict', teacher_label: { node_id: 'x', label: 'settings_system' } },
    });
    expect(triageNoteText(same)!.aiSaid).toBe('');
  });

  it('without a partner, says a near-identical screenshot has a different answer', () => {
    const note = triageNoteText(sample({ ...conflictRow, conflict_partner: null }))!;
    expect(note.partner).toBe('');
    expect(note.why).toMatch(/different answer/);
  });

  it('flags an AI-agreed row that became a confusable pair', () => {
    const agreed = sample({ ...conflictRow, triage: { status: 'agreed', reason: null } });
    expect(triageNoteText(agreed)?.kind).toBe('conflict');
    expect(triageNoteText(sample({ triage: { status: 'agreed', reason: null } }))).toBeNull();
  });

  it('words the AI answer for the other reasons', () => {
    const note = triageNoteText(sample({
      family: 'focus',
      triage: { status: 'needs_human', reason: 'disagrees_with_run', teacher_label: { focused: 'Apps' } },
    }))!;
    expect(note.kind).toBe('other');
    expect(note.why).toMatch(/differently from the test run/);
    expect(note.aiSaid).toBe('Apps');
  });

  it('is empty for rows the triage did not send to a human', () => {
    expect(triageNoteText(sample({}))).toBeNull();
    expect(triageNoteText(sample({ triage: { status: 'teacher_only', reason: 'no_independent_label' } }))).toBeNull();
  });
});

describe('the focus line of a grouped screen-id sample (step 4k)', () => {
  it('has three states: not confirmed, confirmed, changed', () => {
    expect(focusLineState(undefined, false)).toBe('unconfirmed');
    expect(focusLineState(undefined, true)).toBe('confirmed');
    expect(focusLineState('Aufnahmen', false)).toBe('changed');
    expect(focusLineState(null, true)).toBe('changed');
  });

  it('the accept button says what it saves', () => {
    expect(acceptButtonText('home', 'Aufnahmen')).toBe('✓ Save: home · focused Aufnahmen (y)');
    expect(acceptButtonText('home', null)).toBe('✓ Save: home · nothing focused (y)');
    expect(acceptButtonText('home')).toBe('✓ Yes, correct (y)');
    expect(acceptButtonText('')).toBe('✓ Yes, correct (y)');
  });

  it('the focus guess comes from the tree node name unless the triage has focus_teacher', () => {
    expect(focusGuessSource(sample({}))).toBe('tree node name');
    expect(focusGuessSource(sample({ triage: { status: 'needs_human', reason: 'low_confidence' } }))).toBe('tree node name');
    const withTeacher = { status: 'agreed', reason: null, focus_teacher: { model: 'claude-sonnet-5', answer: { focused: 'apps' }, confidence: 'high' } };
    expect(focusGuessSource(sample({ triage: withTeacher as TrainingSample['triage'] }))).toBe('AI read the screen');
    const noModel = { status: 'agreed', reason: null, focus_teacher: { answer: { focused: null } } };
    expect(focusGuessSource(sample({ triage: noModel as TrainingSample['triage'] }))).toBe('AI read the screen');
  });
});

describe('freeze strip: frame labels, question and answers', () => {
  // The reviewer's strip: menu, menu, then live video after the freeze ended. frames is stored as
  // plain seconds (incident_manager.py), the shape of every strip row in the lab DB.
  const answer = (over: Record<string, unknown> = {}) => ({
    incident_type: 'freeze', evidence: 'strip', duration_ms: 26000, diffs: [0.1, 0.2],
    frames: [0, 13.2, 52.8],
    ...over,
  });

  it('labels each frame during, after or before the freeze, in strip order', () => {
    expect(stripFrames(answer()).map(frameChipText)).toEqual([
      '+0.0 s · during freeze', '+13.2 s · during freeze', '+52.8 s · after freeze',
    ]);
    const before = stripFrames(answer({ frames: [-1, 0] }));
    expect(before.map(frameChipText)).toEqual(['-1.0 s · before freeze', '+0.0 s · during freeze']);
  });

  it('labels the stored row of the reviewer\'s case (lab sample d1479274)', () => {
    const row = { incident_type: 'freeze', evidence: 'strip', duration_ms: 52728, diffs: [0.35, 0.42, 0.49],
      frames: [0.0, 26.4, 52.8] };
    expect(stripFrames(row).map(frameChipText)).toEqual([
      '+0.0 s · during freeze', '+26.4 s · during freeze', '+52.8 s · after freeze',
    ]);
  });

  it('absorbs only the 0.1 s rounding, so the frame after the freeze reads "after"', () => {
    expect(STRIP_DURING_TOLERANCE_MS).toBe(60);
    expect(framePhase(52.7, 52700)).toBe('during');   // the last frozen frame
    expect(framePhase(52.75, 52700)).toBe('during');  // 0.1 s rounding (<= 50 ms) is absorbed
    expect(framePhase(52.8, 52700)).toBe('after');    // the reviewer's case: live video after a 52.7 s freeze
    expect(framePhase(53.0, 52700)).toBe('after');
    expect(framePhase(-0.1, 52700)).toBe('before');
  });

  it('shows no chips without frames, and times only without a duration', () => {
    expect(stripFrames(answer({ frames: undefined }))).toEqual([]);
    expect(stripFrames(answer({ frames: 'nope' }))).toEqual([]);
    expect(stripFrames(null)).toEqual([]);
    expect(stripFrames(answer({ duration_ms: null })).map(frameChipText)).toEqual(['+0.0 s', '+13.2 s', '+52.8 s']);
  });

  it('says the duration in the question', () => {
    expect(stripDurationText(answer({ duration_ms: 52700 }))).toBe('52.7 s');
    expect(stripDurationText(answer({ duration_ms: 0 }))).toBe('');
    expect(stripDurationText({})).toBe('');
  });

  it('keeps the three buttons and the values they save', () => {
    expect(STRIP_ANSWERS.map(([bold, rest]) => `${bold} ${rest}`)).toEqual([
      'Yes, the video got stuck (real freeze)',
      'No, it was a still screen (menu, guide, radio, pause)',
      'No, the picture was actually moving (detector wrong)',
    ]);
    expect(STRIP_ANSWERS.map(([, , saved]) => saved)).toEqual([
      { incident_type: 'freeze' },
      { incident_type: null, static_screen: true },
      { incident_type: null, static_screen: false },
    ]);
    expect(STRIP_ANSWERS.map(([, , , color]) => color)).toEqual(['error', 'success', 'info']);
  });

  it('words a saved strip answer with the button vocabulary', () => {
    expect(STRIP_ANSWERS.map(([, , saved]) => stripAnswerWords(saved))).toEqual(['real freeze', 'still screen', 'picture was moving']);
    expect(stripAnswerWords({ incident_type: null })).toBe('');
    expect(stripAnswerWords({ incident_type: 'blackscreen' })).toBe('');
  });
});
