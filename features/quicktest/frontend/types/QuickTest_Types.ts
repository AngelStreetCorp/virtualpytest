/**
 * QuickTest Builder Types
 *
 * A QuickTest is a *linear* test case — an ordered "shopping list" of steps that
 * run one after another. It is NOT a new storage format: it compiles down to the
 * exact same `testcase_definitions.graph_json` ({nodes, edges, scriptConfig})
 * that the visual TestCaseBuilder produces, and executes through the same
 * TestCaseExecutor / report pipeline. See compileStepsToGraph.ts.
 */

import { ActionBlockData, VerificationBlockData } from '../../../../frontend/src/types/testcase/TestCase_Types';

export type QuickStepType = 'goto' | 'action' | 'verification' | 'wait';

/** What to do when a step fails (top-level steps only). */
export type QuickStepOnFail = 'stop' | 'continue';

/**
 * In-loop behavior — the SAME right-side dropdown a top-level step shows for
 * `onFail`, just with a third option and a different default. Only honored when
 * the step is a loop child; at top level `onFail` is used and this is ignored.
 * The outcome follows the trigger (success-break ⇒ loop passes, failure-break ⇒
 * loop fails), so there are exactly two break triggers + a "don't break" default.
 */
export type LoopBreak =
  | 'onFailure' // default: fail → stop loop, FAIL;   pass → next step
  | 'continue' //           fail → next step (ignore); pass → next step
  | 'onSuccess'; //         pass → stop loop, PASS;    fail → next iteration (retry)

/**
 * One row in the linear list. Only the fields relevant to `type` are populated;
 * the compiler reads the matching subset per type.
 */
export interface QuickTestStep {
  /** Stable local id (used as React key and to build node ids). */
  id: string;
  type: QuickStepType;
  /** Stop the test on failure (default) or carry on to the next step. */
  onFail: QuickStepOnFail;
  /** In-loop break behavior — only used when this step is a loop child. */
  loopBreak?: LoopBreak;
  /** Optional human label shown on the row / in the report. */
  label?: string;

  // type === 'goto'
  targetNodeLabel?: string;

  // type === 'action' | 'verification' — the CONTAINER block data, edited inline
  // by InlineActionConfig / InlineVerificationConfig (same shape the visual
  // TestCaseBuilder block writes: { actions: [...] } / { verifications: [...],
  // verification_pass_condition }). Compiled straight onto the node `data`.
  data?: ActionBlockData | VerificationBlockData;

  // type === 'wait'
  /** Wait duration in MILLISECONDS (compiles to the `sleep` standard block,
   *  whose `duration` param is ms) — or a `{variable}` placeholder resolved
   *  at run time from a number-typed input. */
  waitMs?: number | string;
}

/**
 * A loop wraps a contiguous group of steps and repeats them. Each child step's
 * `loopBreak` decides whether it stops the loop early (pass/fail) or just runs.
 * A loop is one level deep — child steps cannot themselves be loops (v1).
 */
export interface QuickTestLoop {
  kind: 'loop';
  /** Stable local id; the compiled loop node id is `loop-${id}`. */
  id: string;
  /** Fixed iteration count, or a `{variable}` placeholder (number-typed input). */
  iterations: number | string;
  steps: QuickTestStep[];
}

/** A row in the builder is either a plain step or a loop holding child steps. */
export type QuickTestUnit = QuickTestStep | QuickTestLoop;

export const isQuickLoop = (u: QuickTestUnit): u is QuickTestLoop =>
  (u as QuickTestLoop).kind === 'loop';

/** Factory for a fresh empty loop (repeats twice by default). */
export const createLoopUnit = (id: string): QuickTestLoop => ({
  kind: 'loop',
  id,
  iterations: 2,
  steps: [],
});

/** Factory for a fresh step of the given type with sane defaults.
 *  Action/Verification steps are SEEDED with one sensible item (press OK /
 *  wait for image to appear) so the row is never empty — mirroring the visual
 *  builder's toolbox seeds. The command dropdowns resolve these against the
 *  device's available defs once control is active. */
export const createEmptyStep = (id: string, type: QuickStepType): QuickTestStep => ({
  id,
  type,
  onFail: 'stop',
  ...(type === 'wait' ? { waitMs: 1000 } : {}),
  ...(type === 'action'
    ? { data: { actions: [{ command: 'press_key', params: { key: 'OK' }, action_type: 'remote' }] } }
    : {}),
  ...(type === 'verification'
    ? {
        data: {
          verifications: [{ command: 'waitForImageToAppear', verification_type: 'image', params: {} }],
          verification_pass_condition: 'all',
        } as VerificationBlockData,
      }
    : {}),
});

/** Human-readable labels for the step-type dropdown. */
export const QUICK_STEP_TYPE_LABELS: Record<QuickStepType, string> = {
  goto: 'Go to node',
  action: 'Action',
  verification: 'Verification',
  wait: 'Wait',
};

/** Labels for the top-level (not-in-loop) On-fail dropdown. */
export const QUICK_ON_FAIL_LABELS: Record<QuickStepOnFail, string> = {
  stop: 'Stop on fail',
  continue: 'Continue on fail',
};

/** Labels for the in-loop break dropdown (same slot as On-fail). */
export const QUICK_LOOP_BREAK_LABELS: Record<LoopBreak, string> = {
  onFailure: 'Break on fail',
  continue: 'Continue on fail',
  onSuccess: 'Break on success',
};
