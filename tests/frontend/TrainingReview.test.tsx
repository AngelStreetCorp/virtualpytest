/**
 * AI Dataset review page (features/ai-dataset): the filter selects show "All" (not a blank
 * field), "Needs you" starts on All sets, and an empty "Needs you" in one set points at the
 * other sets. The data hook is mocked; the pure helpers are covered by reviewText.test.ts.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';

const hook = vi.hoisted(() => ({
  samples: [],
  total: 0,
  isLoading: false,
  error: null,
  evalCounts: {},
  evalThreshold: 200,
  agreedCounts: {},
  aiThreshold: 50,
  load: vi.fn(),
  countSamples: vi.fn(),
  loadEvalCounts: vi.fn(),
  loadOfftreeLabels: vi.fn(),
  loadCoverage: vi.fn(),
  label: vi.fn(),
  freeze: vi.fn(),
  clearError: vi.fn(),
}));
const noGroups = vi.hoisted(() => ({ groups: [], loading: false }));

vi.mock('../../features/ai-dataset/frontend/hooks/useTrainingSamples', async (importActual) => ({
  ...(await importActual<object>()),
  useTrainingSamples: () => hook,
  useScreenGroups: () => noGroups,
}));

import TrainingReview from '../../features/ai-dataset/frontend/TrainingReview';

/** The visible value of a labelled MUI select. */
const selectValue = (label: string) => {
  const control = screen.getByText(label, { selector: 'label' }).parentElement as HTMLElement;
  return within(control).getByRole('combobox');
};

const pick = async (label: string, option: string) => {
  fireEvent.mouseDown(selectValue(label));
  fireEvent.click(await screen.findByRole('option', { name: option }));
};

const lastSplit = () => hook.load.mock.calls[hook.load.mock.calls.length - 1][0].split;

beforeEach(() => {
  hook.load.mockResolvedValue({ returned: 0, added: 0 });
  hook.countSamples.mockResolvedValue(48);
  hook.loadEvalCounts.mockResolvedValue(undefined);
  hook.loadOfftreeLabels.mockResolvedValue([]);
  hook.loadCoverage.mockResolvedValue(null);
});

describe('TrainingReview filters', () => {
  it('shows "All" in the Family and "AI got it" selects, not a blank field', async () => {
    render(<TrainingReview />);
    await waitFor(() => expect(hook.load).toHaveBeenCalled());
    expect(selectValue('Family')).toHaveTextContent('All');
    expect(selectValue('AI got it')).toHaveTextContent('All');
    expect(selectValue('Set')).toHaveTextContent('Eval');
  });

  it('"Needs you" starts on All sets and the Set select says so', async () => {
    render(<TrainingReview />);
    await pick('Show', 'Needs you');
    await waitFor(() => expect(selectValue('Set')).toHaveTextContent('All'));
    expect(lastSplit()).toBe('');
    // Back to "Not checked yet": Eval again.
    await pick('Show', 'Not checked yet');
    await waitFor(() => expect(selectValue('Set')).toHaveTextContent('Eval'));
  });

  it('keeps a Set the user picked, and an empty set offers "Show all sets"', async () => {
    render(<TrainingReview />);
    await pick('Set', 'Train');
    await pick('Show', 'Needs you');
    await waitFor(() => expect(hook.load.mock.calls.at(-1)?.[0]).toMatchObject({ show: 'needs_you', split: 'train' }));
    expect(await screen.findByText('Nothing the AI triage sent to you in the Train set.')).toBeInTheDocument();
    expect(await screen.findByText('48 screenshots are waiting for you in the other sets.')).toBeInTheDocument();
    expect(hook.countSamples).toHaveBeenCalledWith(expect.objectContaining({ show: 'needs_you', split: '' }));
    fireEvent.click(screen.getByRole('button', { name: 'Show all sets' }));
    await waitFor(() => expect(lastSplit()).toBe(''));
    expect(selectValue('Set')).toHaveTextContent('All');
  });
});

// Step 4k: a grouped screen-id sample, "Is this the home screen?" + "Focused: recordings?".
const HOME = { node_id: 'g-home', label: 'home', node: 'n-home-rec', node_label: 'home_recordings', focus: 'recordings' };
const screenSample = (over: Record<string, unknown> = {}) => ({
  id: 's1', family: 'screen-id', object_key: 'k', device_model: 'm', userinterface: 'ui', node_id: 'n-home-rec',
  focus_label: null, prompt: null, model_answer: null, ground_truth: null, proposed_label: HOME, guess_source: 'run',
  label_source: 'run', is_failure: false, label_conflict: false, split: 'eval', eval_version: null, source_ref: null,
  created_at: '2026-09-30T00:00:00Z', image_url: null, triage: null, ...over,
});

const acceptButton = () => screen.getByRole('button', { name: /^✓/ });

describe('TrainingReview focus line (one Yes, one Fix)', () => {
  beforeEach(() => {
    hook.label.mockReset();
    hook.label.mockResolvedValue(undefined);
  });
  afterEach(() => {
    (hook as { samples: unknown[] }).samples = [];
  });
  const show = async (over: Record<string, unknown> = {}) => {
    (hook as { samples: unknown[] }).samples = [screenSample(over)];
    render(<TrainingReview />);
    await screen.findByText('focus guess from: tree node name');
  };

  it('shows the focus as text, with no Yes or Fix of its own', async () => {
    await show();
    expect(screen.getByText('Focused:')).toHaveTextContent('Focused: recordings');
    expect(screen.queryByRole('button', { name: 'Yes (f)' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Fix' })).not.toBeInTheDocument();
    expect(acceptButton()).toHaveTextContent('✓ Save: home · focused recordings (y)');
    expect(screen.getByRole('button', { name: '✗ No, fix it (n)' })).toBeInTheDocument();
  });

  it('keeps today\'s wording without a focus', async () => {
    (hook as { samples: unknown[] }).samples = [screenSample({ proposed_label: { ...HOME, focus: null } })];
    render(<TrainingReview />);
    expect(await screen.findByRole('button', { name: '✓ Yes, correct (y)' })).toBeInTheDocument();
    expect(screen.queryByText('Focused:')).not.toBeInTheDocument();
  });

  it('y saves the screen and its focus together', async () => {
    await show();
    fireEvent.keyDown(window, { key: 'y' });
    await waitFor(() => expect(hook.label).toHaveBeenCalledTimes(1));
    expect(hook.label.mock.calls[0][1]).toEqual(HOME);
  });

  it('f does nothing any more', async () => {
    await show();
    fireEvent.keyDown(window, { key: 'f' });
    expect(hook.label).not.toHaveBeenCalled();
  });

  it('"No, fix it" changes screen and focus in one form', async () => {
    (noGroups as { groups: unknown[] }).groups = [{ node_id: 'g-home', label: 'home', members: [
      { node_id: 'g-home', label: 'home', focus: null },
      { node_id: 'n-home-rec', label: 'home_recordings', focus: 'recordings' },
    ] }];
    onTestFinished(() => { (noGroups as { groups: unknown[] }).groups = []; });
    await show();
    fireEvent.click(screen.getByRole('button', { name: '✗ No, fix it (n)' }));
    const focus = await screen.findByLabelText('Focused item');  // shown once the screen groups load
    expect(focus).toHaveValue('recordings');
    fireEvent.change(focus, { target: { value: 'Aufnahmen' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save answer (Ctrl+Enter)' }));
    await waitFor(() => expect(hook.label).toHaveBeenCalledTimes(1));
    expect(hook.label.mock.calls[0][1]).toMatchObject({ label: 'home', focus: 'Aufnahmen' });
  });

  it('an already-checked sample: y only moves on', async () => {
    await show({ label_source: 'human' });
    expect(acceptButton()).toHaveTextContent('✓ Yes, correct (y)');
    fireEvent.keyDown(window, { key: 'y' });
    expect(hook.label).not.toHaveBeenCalled();
  });

  it('says where the focus guess comes from', async () => {
    await show();
    expect(screen.getByText('focus guess from: tree node name')).toBeInTheDocument();
    cleanup();
    (hook as { samples: unknown[] }).samples = [screenSample({
      triage: { status: 'agreed', reason: null, focus_teacher: { model: 'claude-sonnet-5', answer: { focused: 'recordings' }, confidence: 'high' } },
    })];
    render(<TrainingReview />);
    expect(await screen.findByText('focus guess from: AI read the screen')).toBeInTheDocument();
  });
});

describe('TrainingReview review flow', () => {
  beforeEach(() => {
    hook.label.mockReset();
  });
  afterEach(() => {
    (hook as { samples: unknown[] }).samples = [];
  });

  it('shows the question only once the image has loaded', async () => {
    (hook as { samples: unknown[] }).samples = [screenSample({ image_url: 'https://example.test/a.jpg' })];
    render(<TrainingReview />);
    const img = await screen.findByAltText('Screenshot 1');
    // Hidden until the image is there: no question or answer of a sample before its image.
    expect(screen.queryByRole('button', { name: /^✓/ })).not.toBeInTheDocument();
    fireEvent.load(img);
    expect(acceptButton()).toBeEnabled();
  });

  it('a pending save never blocks the answers (the next sample comes from the list at once)', async () => {
    hook.label.mockReturnValue(new Promise(() => {}));  // the server never answers
    (hook as { samples: unknown[] }).samples = [screenSample()];
    render(<TrainingReview />);
    fireEvent.click(await screen.findByRole('button', { name: /^✓ Save/ }));
    expect(hook.label).toHaveBeenCalledTimes(1);
    expect(acceptButton()).toBeEnabled();
    expect(screen.getByRole('button', { name: '✗ No, fix it (n)' })).toBeEnabled();
  });

  it('a failed save brings the sample back with the error', async () => {
    hook.label.mockRejectedValue(new Error('HTTP 502'));
    (hook as { samples: unknown[] }).samples = [screenSample({ id: 'one' }), screenSample({ id: 'two', proposed_label: { ...HOME, focus: null } })];
    render(<TrainingReview />);
    fireEvent.click(await screen.findByRole('button', { name: /^✓ Save/ }));
    expect(await screen.findByText(/Your answer for screenshot 1 was not saved: HTTP 502/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^✓ Save: home · focused recordings/ })).toBeInTheDocument();
  });
});

// A freeze strip: frames labelled during/after the freeze, one question, three answers.
const STRIP_ANSWER = {
  incident_type: 'freeze', evidence: 'strip', duration_ms: 26000, diffs: [],
  frames: [0, 13.2, 52.8],  // stored as plain seconds (BUG-0209)
};
const stripSample = (over: Record<string, unknown> = {}) => screenSample({
  family: 'av-fault', node_id: null, model_answer: STRIP_ANSWER, proposed_label: { incident_type: 'freeze' },
  image_url: 'https://example.test/strip.jpg', ...over,
});

describe('TrainingReview freeze strip', () => {
  beforeEach(() => {
    hook.label.mockReset();
    hook.label.mockResolvedValue(undefined);
  });
  afterEach(() => {
    (hook as { samples: unknown[] }).samples = [];
  });
  const showStrip = async (over: Record<string, unknown> = {}) => {
    (hook as { samples: unknown[] }).samples = [stripSample(over)];
    render(<TrainingReview />);
    fireEvent.load(await screen.findByAltText('Screenshot 1'));  // the answers wait for the image
    await screen.findByText(/Was that a problem\?|Still correct\?/);
  };

  it('labels the frames and asks one question with the duration', async () => {
    await showStrip();
    expect(screen.getByText('+0.0 s · during freeze')).toBeInTheDocument();
    expect(screen.getByText('+13.2 s · during freeze')).toBeInTheDocument();
    expect(screen.getByText('+52.8 s · after freeze')).toBeInTheDocument();
    expect(screen.getByText(/Was that a problem\?/)).toHaveTextContent(
      "The picture didn't change for 26.0 s (frames marked 'during freeze'). Was that a problem?",
    );
    expect(screen.getByText("Look only at the 'during freeze' frames; 'after freeze' shows what came next.")).toBeInTheDocument();
    expect(screen.queryByText(/really frozen/)).not.toBeInTheDocument();
  });

  it('shows no frame chips when the strip has no frames', async () => {
    await showStrip({ model_answer: { ...STRIP_ANSWER, frames: undefined } });
    expect(screen.queryByText(/during freeze$/)).not.toBeInTheDocument();
  });

  it.each([
    ['Yes, the video got stuck (real freeze)', { incident_type: 'freeze' }],
    ['No, it was a still screen (menu, guide, radio, pause)', { incident_type: null, static_screen: true }],
    ['No, the picture was actually moving (detector wrong)', { incident_type: null, static_screen: false }],
  ])('"%s" saves the same value as before', async (name, saved) => {
    await showStrip();
    fireEvent.click(screen.getByRole('button', { name }));
    await waitFor(() => expect(hook.label).toHaveBeenCalledTimes(1));
    expect(hook.label.mock.calls[0][1]).toEqual(saved);
    expect(screen.getByRole('button', { name: "Can't tell" })).toBeInTheDocument();
  });

  it('an already-checked strip says the answer in the same words', async () => {
    await showStrip({ label_source: 'human', proposed_label: { incident_type: null, static_screen: true } });
    expect(screen.getByText(/Still correct\?/)).toHaveTextContent('You said: still screen. Still correct?');
  });
});
