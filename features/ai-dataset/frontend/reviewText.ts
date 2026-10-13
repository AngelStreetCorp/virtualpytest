/**
 * Pure helpers of the AI Dataset review page (TASK-27): label shapes, a label in plain
 * words, the triage note under the question, and the Set default per Show view.
 * No React here, so `reviewText.test.ts` covers it without rendering the page.
 */

import type { ReviewShow, ScreenGroup, TrainingFamily, TrainingFilters, TrainingSample } from './hooks/useTrainingSamples';

export type Label = Record<string, unknown>;

export const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
export const asText = (value: unknown) => (value === null || value === undefined ? '' : String(value));

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const AV_FAULTS: [string, string, string][] = [
  // value, correction label, question phrase
  ['freeze', 'Freeze', 'a freeze'],
  ['blackscreen', 'Black screen', 'a black screen'],
  ['macroblocks', 'Macroblocks', 'macroblocks (blocky, broken picture)'],
];

// ─── Freeze strip (step 4g; wording 2026-09-30) ──────────────────────────────

/** A frame of a freeze strip counts as "during freeze" up to this far past the detector duration.
 *  Frame times are rounded to 0.1 s (freeze_strip.py), so the rounding error is <= 50 ms; the
 *  first frame after the freeze sits a full frame gap (>= 100 ms) later and must read "after". */
export const STRIP_DURING_TOLERANCE_MS = 60;

export type FramePhase = 'before' | 'during' | 'after';

/** Where a strip frame sits against the freeze: before its start, during it, or after it ended. */
export const framePhase = (tRelS: number, durationMs: number): FramePhase =>
  tRelS < 0 ? 'before' : tRelS * 1000 <= durationMs + STRIP_DURING_TOLERANCE_MS ? 'during' : 'after';

const finite = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
};

/** The detector's freeze duration in ms from a strip's model_answer; null when missing or not > 0. */
export const stripDurationMs = (modelAnswer: unknown): number | null => {
  const ms = finite(asRecord(modelAnswer).duration_ms);
  return ms !== null && ms > 0 ? ms : null;
};

/**
 * The frames of a strip in strip order, each with its phase. model_answer.frames holds the
 * seconds since the first frame (`[0, 26.4, 52.8]`, written by incident_manager.py), not the
 * {file, t_rel_s} objects of freeze_strip.py's meta. [] when `frames` is missing. phase is null
 * when the duration is unknown (time only).
 */
export const stripFrames = (modelAnswer: unknown): { t: number; phase: FramePhase | null }[] => {
  const a = asRecord(modelAnswer);
  if (!Array.isArray(a.frames)) return [];
  const ms = stripDurationMs(a);
  return a.frames
    .map(finite)
    .filter((t): t is number => t !== null)
    .map((t) => ({ t, phase: t < 0 ? 'before' : ms === null ? null : framePhase(t, ms) }));
};

/** The chip under a strip frame: "+0.0 s · during freeze", "-1.0 s · before freeze". */
export const frameChipText = ({ t, phase }: { t: number; phase: FramePhase | null }): string => {
  const time = `${t < 0 ? '-' : '+'}${Math.abs(t).toFixed(1)} s`;
  return phase ? `${time} · ${phase} freeze` : time;
};

/** The freeze duration as the question says it ("52.7 s"); '' when unknown. */
export const stripDurationText = (modelAnswer: unknown): string => {
  const ms = stripDurationMs(modelAnswer);
  return ms === null ? '' : `${(ms / 1000).toFixed(1)} s`;
};

export const STRIP_HINT = "Look only at the 'during freeze' frames; 'after freeze' shows what came next.";

/** The strip answers: bold text, the rest, the label each one saves, the button colour. */
export const STRIP_ANSWERS: [string, string, Label, 'error' | 'success' | 'info'][] = [
  ['Yes, the video got stuck', '(real freeze)', { incident_type: 'freeze' }, 'error'],
  ['No, it was a still screen', '(menu, guide, radio, pause)', { incident_type: null, static_screen: true }, 'success'],
  ['No, the picture was actually moving', '(detector wrong)', { incident_type: null, static_screen: false }, 'info'],
];

/** A strip answer in the words of its button ("still screen"); '' for any other label. */
export const stripAnswerWords = (value: unknown): string => {
  const r = asRecord(value);
  if (r.incident_type === 'freeze') return 'real freeze';
  if (r.incident_type !== null && r.incident_type !== undefined) return '';
  return r.static_screen === true ? 'still screen' : r.static_screen === false ? 'picture was moving' : '';
};

export const isNoBanner =(value: unknown) => {
  const r = asRecord(value);
  return 'channel_number' in r && 'channel_name' in r && r.channel_number === null && r.channel_name === null;
};

/** A screen-id label for a screen not in the tree: {node_id: null, label}. */
export const isOffTree = (value: unknown) => {
  const r = asRecord(value);
  return 'node_id' in r && r.node_id === null && asText(r.label).trim() !== '';
};

/** A screen-id label in the step-4k group form (it names the original node). */
const isGrouped = (value: unknown) => 'node' in asRecord(value);

/**
 * The group form of a screen-id label: as is when already grouped, else (a pre-4k label
 * naming a node) the group holding that node with the node's focus. null for a screen not in
 * the tree or a node the groups do not know.
 */
export const toGroupLabel = (value: unknown, groups: ScreenGroup[]): Label | null => {
  const r = asRecord(value);
  if (!('node_id' in r) || r.node_id === null || r.node_id === undefined) return null;
  if (isGrouped(r)) return r;
  const nodeId = asText(r.node_id);
  for (const g of groups) {
    const m = g.members.find((x) => x.node_id === nodeId);
    if (m) return { node_id: g.node_id, label: g.label, node: m.node_id, node_label: m.label, focus: m.focus };
  }
  return null;
};

/** The screen name of a screen-id label: the group, else the node's label, never a uuid. */
export const screenName = (value: unknown, groups: ScreenGroup[]): string => {
  const grouped = toGroupLabel(value, groups);
  if (grouped) return asText(grouped.label);
  const raw = asText(asRecord(value).label);
  return UUID_RE.test(raw) ? '' : raw;
};

/**
 * A label in plain words ("settings, apps focused", "channel 101 (BBC One)", "no fault").
 * '' when the label is empty or has no readable shape: callers never fall back to JSON.
 */
export const labelWords = (family: TrainingFamily, value: unknown, groups: ScreenGroup[] = []): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  const r = asRecord(value);
  switch (family) {
    case 'screen-id': {
      if (isOffTree(value)) return `${asText(r.label)} (a screen not in the tree)`;
      const name = screenName(value, groups);
      const grouped = toGroupLabel(value, groups);
      const focus = grouped ? asText(grouped.focus) : '';
      if (!name) return '';
      return focus ? `${name}, ${focus} focused` : name;
    }
    case 'focus':
      if (!('focused' in r)) return '';
      return r.focused === null ? 'nothing focused' : asText(r.focused);
    case 'banner': {
      if (isNoBanner(value)) return 'no channel banner';
      const num = asText(r.channel_number);
      const name = asText(r.channel_name);
      if (num && name) return `channel ${num} (${name})`;
      if (num) return `channel ${num}`;
      return name;
    }
    case 'av-fault': {
      if (!('incident_type' in r)) return '';
      if (r.incident_type === null || r.incident_type === undefined) return stripAnswerWords(r) || 'no fault';
      const fault = AV_FAULTS.find(([v]) => v === r.incident_type);
      return fault ? fault[1].toLowerCase() : asText(r.incident_type);
    }
    case 'menu': {
      const items = Array.isArray(r.items) ? r.items.map(asText).filter(Boolean) : [];
      if (!items.length) return '';
      return `${items.join(', ')} (${asText(r.selected) || 'nothing'} selected)`;
    }
    default: {
      if (typeof r.content === 'string') return r.content;
      if (typeof r.label === 'string') return r.label;
      return '';
    }
  }
};

/**
 * The note under the question when the AI triage sent a sample to a human (or when an
 * AI-agreed sample turned out to be half of a confusable pair). Words only, never JSON.
 * `partner` is the other sample's label (conflict only; '' = unknown), `aiSaid` the AI's
 * answer when worth showing ('' = not shown).
 */
export interface TriageNoteText {
  kind: 'conflict' | 'other';
  why: string;
  partner: string;
  aiSaid: string;
}

export const triageNoteText = (sample: TrainingSample, groups: ScreenGroup[] = []): TriageNoteText | null => {
  const t = sample.triage;
  if (!t) return null;
  const conflict = (t.status === 'needs_human' && t.reason === 'conflict') || (t.status === 'agreed' && sample.label_conflict);
  if (t.status !== 'needs_human' && !conflict) return null;
  const aiWords = labelWords(sample.family, t.teacher_label, groups);
  if (conflict) {
    const partner = sample.conflict_partner ? labelWords(sample.family, sample.conflict_partner.ground_truth, groups) : '';
    return {
      kind: 'conflict',
      why: partner
        ? 'A near-identical screenshot is labelled'
        : 'A near-identical screenshot has a different answer: check this one carefully.',
      partner,
      // The AI's answer only adds something when it is not the partner's label.
      aiSaid: aiWords && aiWords !== partner ? aiWords : '',
    };
  }
  const why = t.reason === 'disagrees_with_run' ? 'The AI answered differently from the test run: which one is right?'
    : t.reason === 'low_confidence' ? `The AI was not sure${t.teacher_note ? ` (${t.teacher_note})` : ''}.`
    : t.reason === 'spot_check' ? 'Random check of an AI answer: is it right?'
    : 'Sent to you by the AI triage.';
  return { kind: 'other', why, partner: '', aiSaid: aiWords };
};

// ─── Step 4k: the "Focused: X?" line of a grouped screen-id sample ───────────

/**
 * The state the focus line shows: `unconfirmed` (the default, nobody looked yet), `confirmed`
 * (its Yes, or `f`) or `changed` (a Fix). `edited` is the human's focus (undefined = not
 * changed, null = nothing focused).
 */
export type FocusLineState = 'unconfirmed' | 'confirmed' | 'changed';

export const focusLineState = (edited: string | null | undefined, confirmed: boolean): FocusLineState =>
  edited !== undefined ? 'changed' : confirmed ? 'confirmed' : 'unconfirmed';

/** The focus in words, as the line and the accept button say it. */
export const focusWords = (focus: string | null) => (focus === null ? 'nothing focused' : `focused ${focus}`);

/**
 * The main accept button: exactly what it saves. `focus` is the focus the line shows (null =
 * nothing focused); undefined when the sample has no focus line (today's wording).
 */
export const acceptButtonText = (screen: string, focus?: string | null): string =>
  focus === undefined ? '✓ Yes, correct (y)' : `✓ Save: ${screen || 'this screen'} · ${focusWords(focus)} (y)`;

/**
 * Where the focus guess comes from: the AI when the triage has a `focus_teacher` record
 * ({model, answer: {focused}, confidence}), else the tree node name (a missing field too).
 */
export const focusGuessSource = (sample: TrainingSample): string => {
  const teacher = asRecord(asRecord(sample.triage).focus_teacher);
  if (Object.keys(teacher).length === 0) return 'tree node name';
  return 'AI read the screen';
};

// ─── Set filter default per Show view ─────────────────────────────────────────

/**
 * The Set a Show view starts on. "Needs you" lists what the AI triage sent to a human, in
 * any split (most rows are in train), so it starts on All; the other views on Eval.
 */
export const DEFAULT_SPLIT: Record<ReviewShow, TrainingFilters['split']> = {
  needs_you: '',
  unchecked: 'eval',
  checked: 'eval',
  all: 'eval',
};

/** Filters after a Show change: the Set follows the view unless the user picked one. */
export const withShow = (prev: TrainingFilters, show: ReviewShow, splitPinned: boolean): TrainingFilters => ({
  ...prev,
  show,
  split: splitPinned ? prev.split : DEFAULT_SPLIT[show],
});

export const SPLIT_OPTIONS: [TrainingFilters['split'], string][] = [
  ['', 'All'],
  ['eval', 'Eval'],
  ['train', 'Train'],
  ['holdout', 'Holdout'],
];

export const splitName = (split: TrainingFilters['split']) =>
  SPLIT_OPTIONS.find(([v]) => v === split)?.[1] ?? split;
