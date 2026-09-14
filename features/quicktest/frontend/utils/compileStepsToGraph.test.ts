/**
 * compileStepsToGraph / parseGraphToSteps — round-trip tests.
 *
 * These two functions are the whole of QuickTest's persistence: the builder's linear
 * step list is compiled to a core testcase graph on save, and parsed back on load.
 * Everything else (create / edit / delete / run through `/server/testcase/*`) sits on
 * top, so a compiler bug shows up as all of those "succeeding" while storing a graph
 * that no longer means what the user built.
 *
 * The property under test is therefore round-tripping: parse(compile(units)) === units.
 * It needs no server, no device and no DOM.
 */

import { describe, expect, it } from 'vitest';

import type { QuickTestLoop, QuickTestStep, QuickTestUnit } from '../types/QuickTest_Types';

import { compileStepsToGraph, parseGraphToSteps } from './compileStepsToGraph';

const step = (over: Partial<QuickTestStep> & Pick<QuickTestStep, 'id' | 'type'>): QuickTestStep => ({
  onFail: 'stop',
  ...over,
});

/** compile → parse, asserting the graph was representable at all. */
const roundTrip = (units: QuickTestUnit[], inputs: any[] = []) => {
  const parsed = parseGraphToSteps(compileStepsToGraph(units, inputs));
  expect(parsed, 'graph was not parseable back into QuickTest units').not.toBeNull();
  return parsed!;
};

describe('compileStepsToGraph / parseGraphToSteps round-trip', () => {
  it('round-trips an empty list', () => {
    expect(roundTrip([]).units).toEqual([]);
  });

  it('round-trips each step type', () => {
    const units: QuickTestUnit[] = [
      step({ id: '1', type: 'goto', targetNodeLabel: 'home' }),
      step({ id: '2', type: 'wait', waitMs: 2500 }),
      step({
        id: '3',
        type: 'action',
        data: { actions: [{ command: 'press_key', params: { key: 'OK' } }] } as any,
      }),
      step({
        id: '4',
        type: 'verification',
        data: {
          verifications: [{ command: 'waitForTextToAppear', params: { text: 'Live' } }],
          verification_pass_condition: 'all',
        } as any,
      }),
    ];
    expect(roundTrip(units).units).toEqual(units);
  });

  it('preserves onFail on top-level steps', () => {
    const units: QuickTestUnit[] = [
      step({ id: '1', type: 'goto', targetNodeLabel: 'home', onFail: 'continue' }),
      step({ id: '2', type: 'goto', targetNodeLabel: 'guide', onFail: 'stop' }),
    ];
    const out = roundTrip(units).units as QuickTestStep[];
    expect(out.map((u) => u.onFail)).toEqual(['continue', 'stop']);
  });

  it('preserves script inputs', () => {
    const inputs = [{ name: 'channel', type: 'number', default: 3 }];
    expect(roundTrip([step({ id: '1', type: 'wait', waitMs: 100 })], inputs).inputs).toEqual(inputs);
  });

  it('round-trips a {variable} wait rather than coercing it to a number', () => {
    const units: QuickTestUnit[] = [step({ id: '1', type: 'wait', waitMs: '{delay}' })];
    expect((roundTrip(units).units[0] as QuickTestStep).waitMs).toBe('{delay}');
  });

  describe('loops', () => {
    const loop = (over: Partial<QuickTestLoop> = {}): QuickTestLoop => ({
      kind: 'loop',
      id: 'L1',
      iterations: 3,
      steps: [step({ id: 'c1', type: 'goto', targetNodeLabel: 'home', loopBreak: 'onFailure' })],
      ...over,
    });

    it('round-trips a loop with its children', () => {
      const units: QuickTestUnit[] = [loop()];
      expect(roundTrip(units).units).toEqual(units);
    });

    it('preserves each loopBreak variant on loop children', () => {
      const units: QuickTestUnit[] = [
        loop({
          steps: [
            step({ id: 'c1', type: 'goto', targetNodeLabel: 'a', loopBreak: 'onFailure' }),
            step({ id: 'c2', type: 'goto', targetNodeLabel: 'b', loopBreak: 'continue' }),
            step({ id: 'c3', type: 'goto', targetNodeLabel: 'c', loopBreak: 'onSuccess' }),
          ],
        }),
      ];
      const out = (roundTrip(units).units[0] as QuickTestLoop).steps;
      expect(out.map((s) => s.loopBreak)).toEqual(['onFailure', 'continue', 'onSuccess']);
    });

    it('round-trips a {variable} iteration count', () => {
      const units: QuickTestUnit[] = [loop({ iterations: '{count}' })];
      expect((roundTrip(units).units[0] as QuickTestLoop).iterations).toBe('{count}');
    });

    it('skips an empty loop — an in-progress container must not break the graph', () => {
      // Documented behaviour in compileStepsToGraph: a loop node with no nested blocks
      // would fail validation, so an empty one compiles to nothing.
      const units: QuickTestUnit[] = [
        loop({ id: 'empty', steps: [] }),
        step({ id: '1', type: 'goto', targetNodeLabel: 'home' }),
      ];
      const out = roundTrip(units).units;
      expect(out).toHaveLength(1);
      expect((out[0] as QuickTestStep).id).toBe('1');
    });

    it('keeps a loop ordered between the steps around it', () => {
      const units: QuickTestUnit[] = [
        step({ id: 'before', type: 'goto', targetNodeLabel: 'home' }),
        loop(),
        step({ id: 'after', type: 'wait', waitMs: 500 }),
      ];
      const out = roundTrip(units).units;
      expect(out.map((u) => ('kind' in u ? `loop:${u.id}` : u.id))).toEqual([
        'before',
        'loop:L1',
        'after',
      ]);
    });
  });

  describe('graph shape', () => {
    it('always emits a START node', () => {
      const g = compileStepsToGraph([], []);
      expect(g.nodes.some((n) => String(n.type).toLowerCase().includes('start'))).toBe(true);
    });

    it('gives every non-terminal node an outgoing edge', () => {
      const g = compileStepsToGraph(
        [
          step({ id: '1', type: 'goto', targetNodeLabel: 'home' }),
          step({ id: '2', type: 'wait', waitMs: 100 }),
        ],
        [],
      );
      const withOutgoing = new Set(g.edges.map((e) => e.source));
      const terminal = (t: unknown) => /success|failure|end/i.test(String(t));
      for (const n of g.nodes) {
        if (!terminal(n.type) && !terminal(n.id)) {
          expect(withOutgoing.has(n.id), `node ${n.id} (${n.type}) has no outgoing edge`).toBe(true);
        }
      }
    });

    it('returns null for a graph QuickTest cannot represent', () => {
      const g = compileStepsToGraph([step({ id: '1', type: 'wait', waitMs: 100 })], []);
      // scriptConfig outputs/variables/metadata are visual-builder-only data flow.
      const enriched = { ...g, scriptConfig: { ...(g as any).scriptConfig, outputs: [{ name: 'x' }] } };
      expect(parseGraphToSteps(enriched as any)).toBeNull();
    });
  });
});
