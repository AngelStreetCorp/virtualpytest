/**
 * Pure helpers behind the live run views (page and dialog): step state, chips,
 * percent and the log built from the step events. No React, no network.
 */

import type { LiveRunStep } from '../../hooks/script/useLiveScriptProgress';

export type ChipState = 'done' | 'now' | 'failed' | 'skipped' | 'pending';

export interface StepChip {
  key: string;
  label: string;
  state: ChipState;
}

const MAX_PENDING_CHIPS = 12;

export const formatElapsed = (ms: number): string => {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
};

/** "step 4: tap - Battle menu is open…" -> action tag + text; other labels stay as they are. */
export const splitLabel = (label: string): { tag?: string; text: string } => {
  const m = /^(?:step\s+\d+:\s*)?([a-z_]{2,12})\s+[-–—]\s+(.*)$/is.exec(label);
  return m ? { tag: m[1].toLowerCase(), text: m[2] } : { text: label };
};

export const stepState = (step: LiveRunStep): Exclude<ChipState, 'now' | 'pending'> =>
  step.skipped ? 'skipped' : step.success ? 'done' : 'failed';

/** Percent done, or null when the script does not report a total. */
export const percentDone = (doneCount: number, totalSteps: number | null, finished: boolean): number | null => {
  if (finished && doneCount > 0) return 100;
  if (!totalSteps || totalSteps <= 0) return null;
  return Math.min(100, Math.round((doneCount / totalSteps) * 100));
};

/**
 * Chips for the header. When steps carry a `stage`, one chip per consecutive stage; otherwise one
 * chip per step, followed by a "now" chip for the step being worked on and a few pending ones.
 */
export const buildChips = (
  steps: LiveRunStep[],
  totalSteps: number | null,
  running: boolean,
  nextLabel: (n: number) => string,
): StepChip[] => {
  if (steps.some((s) => s.stage)) {
    const groups: { stage: string; steps: LiveRunStep[] }[] = [];
    steps.forEach((s) => {
      const stage = s.stage || splitLabel(s.label).text;
      const last = groups[groups.length - 1];
      if (last && last.stage === stage) last.steps.push(s);
      else groups.push({ stage, steps: [s] });
    });
    return groups.map((g, i) => {
      const failed = g.steps.some((s) => stepState(s) === 'failed');
      const allSkipped = g.steps.every((s) => s.skipped);
      const state: ChipState = failed ? 'failed' : allSkipped ? 'skipped' : running && i === groups.length - 1 ? 'now' : 'done';
      return { key: `g${i}`, label: g.stage, state };
    });
  }
  const chips: StepChip[] = steps.map((s) => ({
    key: `s${s.number}`,
    label: splitLabel(s.label).text,
    state: stepState(s),
  }));
  if (running) {
    const first = steps.length + 1;
    chips.push({ key: `s${first}`, label: nextLabel(first), state: 'now' });
    if (totalSteps && totalSteps > first) {
      const last = Math.min(totalSteps, first + MAX_PENDING_CHIPS);
      for (let n = first + 1; n <= last; n += 1) chips.push({ key: `s${n}`, label: nextLabel(n), state: 'pending' });
    }
  }
  return chips;
};

export type LogKind = 'step' | 'warn' | 'error';

export interface LogLine {
  id: string;
  at: number | null;
  kind: LogKind;
  text: string;
}

export const buildLogLines = (steps: LiveRunStep[]): LogLine[] => {
  const lines: LogLine[] = [];
  steps.forEach((s) => {
    const state = stepState(s);
    const dur = s.durationMs != null ? ` (${formatElapsed(s.durationMs)})` : '';
    lines.push({
      id: `l${s.number}`,
      at: s.at ?? null,
      kind: state === 'failed' ? 'error' : state === 'skipped' ? 'warn' : 'step',
      text: `[step ${s.number}] ${splitLabel(s.label).text}${dur}`,
    });
    if (s.error && state === 'failed') {
      lines.push({ id: `l${s.number}e`, at: s.at ?? null, kind: 'error', text: `  ${s.error}` });
    }
  });
  return lines;
};

export const formatClock = (ms: number | null): string => {
  if (ms == null) return '--:--:--';
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};

export const logToText = (lines: LogLine[]): string =>
  lines.map((l) => `[${formatClock(l.at)}] ${l.text}`).join('\n');
