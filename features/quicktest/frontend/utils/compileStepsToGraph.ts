/**
 * QuickTest compiler
 *
 * Converts the linear QuickTest unit list <-> the testcase graph_json that the
 * backend TestCaseExecutor interprets. A unit is either a plain step or a LOOP
 * holding a contiguous group of child steps.
 *
 * Top-level chain (plain steps + loop nodes):
 *
 *   START --success--> unit0 --success--> unit1 --success--> ... --success--> SUCCESS
 *                        |failure            |failure
 *                        v                   v
 *   (step onFail='stop') FAILURE          FAILURE
 *   (step onFail='continue') routes the failure edge to the NEXT unit instead.
 *   (a loop node's failure edge always routes to FAILURE.)
 *
 * A loop compiles to a `loop` node whose `data.nested_blocks` is a self-contained
 * sub-graph (its own START / SUCCESS / FAILURE [/ break_success] terminals) run
 * once per iteration by the executor. Inside that sub-graph each child step is
 * routed by its `loopBreak`:
 *   - onFailure (default): pass -> next; fail -> sub-FAILURE  (loop aborts, FAIL)
 *   - continue:            pass -> next; fail -> next         (ignore failures)
 *   - onSuccess:           pass -> break_success (loop PASS);  fail -> next (retry)
 * The executor stops a loop early on break_success (pass) or sub-FAILURE (fail,
 * via on_failure:'break'); otherwise it runs all iterations. It treats "exhausted
 * all iterations" as FAIL iff the nested graph has a break_success terminal (a
 * success-break was expected but never hit — retry-until-pass that never passed),
 * else PASS (plain repeat / soak).
 *
 * Node `position` is render-only; the executor follows edges. We lay chains out
 * vertically so a QuickTest opens cleanly in the full visual TestCaseBuilder.
 *
 * Block data shapes match testcase_executor.py + the visual builder's CONTAINER
 * model (a single QuickTest step = a 1-item list):
 *   - goto         -> type 'navigation',   data { target_node_label }
 *   - action       -> type 'action',       data { actions: [{ command, params, action_type? }] }
 *   - verification -> type 'verification', data { verifications: [...], verification_pass_condition: 'all' }
 *   - wait         -> type 'sleep',        data { command: 'sleep', params: { duration } }  // ms
 */

import {
  BlockType,
  ConnectionType,
  LoopBlockData,
  ScriptInput,
  TestCaseBlock,
  TestCaseConnection,
  TestCaseGraph,
} from '../../../../frontend/src/types/testcase/TestCase_Types';
import {
  LoopBreak,
  QuickStepOnFail,
  QuickStepType,
  QuickTestLoop,
  QuickTestStep,
  QuickTestUnit,
  isQuickLoop,
} from '../types/QuickTest_Types';

const X = 250;
const Y_GAP = 120;

const START_ID = 'start';
const SUCCESS_ID = 'success';
const FAILURE_ID = 'failure';

const nodeIdFor = (step: QuickTestStep) => `node-${step.id}`;
const loopNodeIdFor = (loop: QuickTestLoop) => `loop-${loop.id}`;

const successEdge = (source: string, target: string): TestCaseConnection => ({
  id: `e-success-${source}-${target}`,
  source,
  target,
  sourceHandle: 'success',
  type: ConnectionType.SUCCESS,
});

const failureEdge = (source: string, target: string): TestCaseConnection => ({
  id: `e-failure-${source}-${target}`,
  source,
  target,
  sourceHandle: 'failure',
  type: ConnectionType.FAILURE,
});

/** Build the per-step block node `data` for the executor. */
const buildStepNode = (step: QuickTestStep, y: number): TestCaseBlock => {
  const base = { id: nodeIdFor(step), position: { x: X, y } };

  switch (step.type) {
    case 'goto':
      return {
        ...base,
        type: BlockType.NAVIGATION,
        data: { target_node_label: step.targetNodeLabel || '' },
      };
    case 'action':
      // CONTAINER SHAPE: data.actions is the ordered sequence edited inline by
      // InlineActionConfig — identical to what the visual TestCaseBuilder writes.
      return {
        ...base,
        type: BlockType.ACTION,
        data: (step.data as any) || { actions: [] },
      };
    case 'verification':
      return {
        ...base,
        type: BlockType.VERIFICATION,
        data: (step.data as any) || { verifications: [], verification_pass_condition: 'all' },
      };
    case 'wait':
      return {
        ...base,
        // 'sleep' is not a special type -> routed to the standard-block executor.
        type: 'sleep' as BlockType,
        data: { command: 'sleep', params: { duration: step.waitMs ?? 1000 } },
      };
    default:
      return { ...base, type: BlockType.ACTION, data: {} };
  }
};

interface SubGraphIds {
  start: string;
  success: string;
  failure: string;
  breakSuccess: string;
}

/**
 * Build the inner chain (step nodes + their edges) for a loop's child steps,
 * routing each by its `loopBreak`. Terminals are added by the caller.
 */
const buildLoopChain = (
  steps: QuickTestStep[],
  ids: SubGraphIds,
): { nodes: TestCaseBlock[]; edges: TestCaseConnection[] } => {
  const nodes: TestCaseBlock[] = [];
  const edges: TestCaseConnection[] = [];

  // Where a child's "continue to the next child" path goes (the next child, or
  // the sub-SUCCESS terminal when this is the last child = iteration finished).
  const nextOf = (index: number): string =>
    index + 1 < steps.length ? nodeIdFor(steps[index + 1]) : ids.success;

  steps.forEach((step, index) => {
    nodes.push(buildStepNode(step, (index + 1) * Y_GAP));
    const id = nodeIdFor(step);
    const brk: LoopBreak = step.loopBreak ?? 'onFailure';

    if (brk === 'onSuccess') {
      // pass -> stop loop (PASS); fail -> next (and if last, sub-SUCCESS = retry).
      edges.push(successEdge(id, ids.breakSuccess));
      edges.push(failureEdge(id, nextOf(index)));
    } else if (brk === 'continue') {
      // ignore failures: both paths flow to the next child.
      edges.push(successEdge(id, nextOf(index)));
      edges.push(failureEdge(id, nextOf(index)));
    } else {
      // onFailure (default): fail -> sub-FAILURE (loop aborts, FAIL).
      edges.push(successEdge(id, nextOf(index)));
      edges.push(failureEdge(id, ids.failure));
    }
  });

  return { nodes, edges };
};

/** Build a loop node (with its nested_blocks sub-graph) for the parent chain. */
const buildLoopNode = (loop: QuickTestLoop, y: number): TestCaseBlock => {
  const ids: SubGraphIds = {
    start: `loop-${loop.id}-start`,
    success: `loop-${loop.id}-success`,
    failure: `loop-${loop.id}-failure`,
    breakSuccess: `loop-${loop.id}-break_success`,
  };
  const usesBreakSuccess = loop.steps.some((s) => (s.loopBreak ?? 'onFailure') === 'onSuccess');
  const chain = buildLoopChain(loop.steps, ids);
  const terminalY = (loop.steps.length + 1) * Y_GAP;

  const nestedNodes: TestCaseBlock[] = [
    { id: ids.start, type: BlockType.START, position: { x: X, y: 0 }, data: {} },
    ...chain.nodes,
    { id: ids.success, type: BlockType.SUCCESS, position: { x: X, y: terminalY }, data: {} },
    { id: ids.failure, type: BlockType.FAILURE, position: { x: X + 250, y: terminalY }, data: {} },
    ...(usesBreakSuccess
      ? [
          {
            id: ids.breakSuccess,
            type: BlockType.BREAK_SUCCESS,
            position: { x: X - 250, y: terminalY },
            data: {},
          },
        ]
      : []),
  ];
  const nestedEdges: TestCaseConnection[] = [
    successEdge(ids.start, loop.steps.length > 0 ? nodeIdFor(loop.steps[0]) : ids.success),
    ...chain.edges,
  ];

  const data: LoopBlockData = {
    iterations: loop.iterations,
    on_failure: 'break',
    nested_blocks: { nodes: nestedNodes, edges: nestedEdges },
  };
  return { id: loopNodeIdFor(loop), type: BlockType.LOOP, position: { x: X, y }, data };
};

/**
 * Compile an ordered unit list into a testcase graph_json. An empty list (or a
 * list of only empty loops) produces START --success--> SUCCESS (a no-op test).
 *
 * `inputs` are the test's variables ({name} placeholders), emitted as standard
 * scriptConfig.inputs so the saved testcase is a TEMPLATE. Runtime `value` is
 * STRIPPED — values are stamped per run (stampInputValues), never persisted.
 */
export const compileStepsToGraph = (
  units: QuickTestUnit[],
  inputs: ScriptInput[] = [],
): TestCaseGraph => {
  const nodes: TestCaseBlock[] = [
    { id: START_ID, type: BlockType.START, position: { x: X, y: 0 }, data: {} },
  ];
  const edges: TestCaseConnection[] = [];

  // Empty loops don't compile to anything (a loop node with no nested blocks
  // would fail validation) — skip them so an in-progress empty container is a no-op.
  const visible = units.filter((u) => !(isQuickLoop(u) && u.steps.length === 0));

  const unitNodeId = (u: QuickTestUnit) => (isQuickLoop(u) ? loopNodeIdFor(u) : nodeIdFor(u));
  const nextOf = (index: number): string =>
    index + 1 < visible.length ? unitNodeId(visible[index + 1]) : SUCCESS_ID;

  visible.forEach((unit, index) => {
    const y = (index + 1) * Y_GAP;
    if (isQuickLoop(unit)) {
      const id = loopNodeIdFor(unit);
      nodes.push(buildLoopNode(unit, y));
      // A loop's success edge -> next unit; its failure edge -> FAILURE terminal.
      edges.push(successEdge(id, nextOf(index)));
      edges.push(failureEdge(id, FAILURE_ID));
    } else {
      const id = nodeIdFor(unit);
      nodes.push(buildStepNode(unit, y));
      edges.push(successEdge(id, nextOf(index)));
      const failTarget = unit.onFail === 'continue' ? nextOf(index) : FAILURE_ID;
      edges.push(failureEdge(id, failTarget));
    }
  });

  edges.push(successEdge(START_ID, visible.length > 0 ? unitNodeId(visible[0]) : SUCCESS_ID));

  const lastY = (visible.length + 1) * Y_GAP;
  nodes.push({ id: SUCCESS_ID, type: BlockType.SUCCESS, position: { x: X, y: lastY }, data: {} });
  nodes.push({ id: FAILURE_ID, type: BlockType.FAILURE, position: { x: X + 250, y: lastY }, data: {} });

  return {
    nodes,
    edges,
    scriptConfig: {
      inputs: inputs.map(({ ...input }) => {
        delete (input as any).value; // runtime-only, never saved
        return input;
      }),
      outputs: [],
      variables: [],
      metadata: { mode: 'append', fields: [] },
    },
  };
};

/** Map a graph node type back to the QuickTest step type. */
const stepTypeFromNode = (node: TestCaseBlock): QuickStepType | null => {
  switch (node.type) {
    case BlockType.NAVIGATION:
      return 'goto';
    case BlockType.ACTION:
      return 'action';
    case BlockType.VERIFICATION:
      return 'verification';
    case 'sleep' as BlockType:
      return 'wait';
    default:
      if ((node.data as any)?.command === 'sleep') return 'wait';
      return null;
  }
};

/** Reconstruct a QuickTestStep (type + data, no onFail/loopBreak) from a node. */
const stepFromNode = (node: TestCaseBlock): QuickTestStep | null => {
  const stepType = stepTypeFromNode(node);
  if (!stepType) return null;
  const data = (node.data || {}) as any;

  const actionData =
    stepType === 'action'
      ? Array.isArray(data.actions)
        ? data
        : {
            actions: data.command
              ? [{ command: data.command, action_type: data.action_type, params: data.params || {} }]
              : [],
          }
      : undefined;
  const verificationData =
    stepType === 'verification'
      ? Array.isArray(data.verifications)
        ? data
        : {
            verifications: data.command
              ? [
                  {
                    command: data.command,
                    verification_type: data.verification_type,
                    threshold: data.threshold,
                    reference: data.reference,
                    params: data.params || {},
                  },
                ]
              : [],
            verification_pass_condition: data.verification_pass_condition || 'all',
          }
      : undefined;

  return {
    id: node.id.replace(/^node-/, ''),
    type: stepType,
    onFail: 'stop',
    ...(stepType === 'goto' ? { targetNodeLabel: data.target_node_label } : {}),
    ...(stepType === 'action' ? { data: actionData } : {}),
    ...(stepType === 'verification' ? { data: verificationData } : {}),
    ...(stepType === 'wait' ? { waitMs: data.params?.duration ?? 1000 } : {}),
  };
};

/**
 * Reconstruct a loop's child steps from its nested_blocks sub-graph. Walks the
 * chain following each child's "next sibling" edge (success for most, failure for
 * onSuccess steps), reconstructing `loopBreak` from where the edges point.
 * Returns null if the sub-graph is not a clean linear loop chain (branching,
 * cycle, or a nested loop).
 */
const parseLoopSteps = (nested: TestCaseGraph): QuickTestStep[] | null => {
  if (!nested?.nodes?.length) return null;
  const byId = new Map(nested.nodes.map((n) => [n.id, n]));
  const successTarget = (src: string) =>
    nested.edges.find((e) => e.source === src && e.sourceHandle === 'success')?.target;
  const failureTarget = (src: string) =>
    nested.edges.find((e) => e.source === src && e.sourceHandle === 'failure')?.target;

  const start = nested.nodes.find((n) => n.type === BlockType.START);
  if (!start) return null;
  const failureNode = nested.nodes.find((n) => n.type === BlockType.FAILURE);
  const breakNode = nested.nodes.find((n) => n.type === BlockType.BREAK_SUCCESS);

  const isTerminal = (n?: TestCaseBlock) =>
    !n ||
    n.type === BlockType.SUCCESS ||
    n.type === BlockType.FAILURE ||
    n.type === BlockType.BREAK_SUCCESS;

  const steps: QuickTestStep[] = [];
  const seen = new Set<string>();
  let currentId = successTarget(start.id);

  while (currentId) {
    const node = byId.get(currentId);
    if (!node) return null;
    if (isTerminal(node)) break;
    if (node.type === BlockType.LOOP) return null; // no nested loops in v1
    if (seen.has(currentId)) return null; // cycle
    seen.add(currentId);

    const base = stepFromNode(node);
    if (!base) return null;

    const sTarget = successTarget(currentId);
    const fTarget = failureTarget(currentId);
    let loopBreak: LoopBreak;
    if (breakNode && sTarget === breakNode.id) loopBreak = 'onSuccess';
    else if (failureNode && fTarget === failureNode.id) loopBreak = 'onFailure';
    else loopBreak = 'continue';

    steps.push({ ...base, loopBreak });

    // The next child is reached via the success edge, except for onSuccess steps
    // (whose success exits the loop) — their failure edge carries the retry/next path.
    currentId = loopBreak === 'onSuccess' ? fTarget : sTarget;
    const nextNode = currentId ? byId.get(currentId) : undefined;
    if (isTerminal(nextNode)) break;
  }

  return steps;
};

/**
 * Parse a testcase graph back into a QuickTest unit list. Walks the success chain
 * from START; a plain step infers `onFail` from its failure-edge target, a LOOP
 * node is unwrapped into a QuickTestLoop (with child steps + reconstructed
 * loopBreak).
 *
 * Returns null (caller falls back to the full visual builder) if the graph is not
 * a clean linear chain: branching/cycles, a non-linear loop body, a nested loop,
 * a loop using the legacy `nested_graph` key, or scriptConfig carrying
 * outputs/variables/metadata QuickTest can't author.
 */
export interface ParsedQuickTest {
  units: QuickTestUnit[];
  inputs: ScriptInput[];
}

export const parseGraphToSteps = (graph: TestCaseGraph): ParsedQuickTest | null => {
  if (!graph?.nodes?.length) return { units: [], inputs: [] };

  const scriptConfig = graph.scriptConfig;
  if (
    scriptConfig &&
    ((scriptConfig.outputs?.length ?? 0) > 0 ||
      (scriptConfig.variables?.length ?? 0) > 0 ||
      (scriptConfig.metadata?.fields?.length ?? 0) > 0)
  ) {
    return null; // visual-builder data-flow QuickTest can't represent
  }
  const inputs: ScriptInput[] = scriptConfig?.inputs ?? [];

  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const successTarget = (source: string) =>
    graph.edges.find((e) => e.source === source && e.sourceHandle === 'success')?.target;
  const failureTarget = (source: string) =>
    graph.edges.find((e) => e.source === source && e.sourceHandle === 'failure')?.target;

  const start = graph.nodes.find((n) => n.type === BlockType.START);
  if (!start) return null;

  const units: QuickTestUnit[] = [];
  const seen = new Set<string>();
  let currentId = successTarget(start.id);

  while (currentId) {
    const node = byId.get(currentId);
    if (!node) return null;
    if (node.type === BlockType.SUCCESS) break;
    if (node.type === BlockType.FAILURE || node.type === BlockType.BREAK_SUCCESS) return null;
    if (seen.has(currentId)) return null; // cycle -> not linear
    seen.add(currentId);

    if (node.type === BlockType.LOOP) {
      const data = (node.data || {}) as LoopBlockData;
      const nested = data.nested_blocks;
      if (!nested) return null; // legacy nested_graph / malformed -> visual builder
      const childSteps = parseLoopSteps(nested);
      if (!childSteps) return null;
      units.push({
        kind: 'loop',
        id: node.id.replace(/^loop-/, ''),
        iterations: data.iterations,
        steps: childSteps,
      });
      currentId = successTarget(currentId);
      continue;
    }

    const base = stepFromNode(node);
    if (!base) return null;
    const failTo = failureTarget(currentId);
    const failNode = failTo ? byId.get(failTo) : undefined;
    const onFail: QuickStepOnFail =
      !failNode || failNode.type === BlockType.FAILURE ? 'stop' : 'continue';
    units.push({ ...base, onFail });

    currentId = successTarget(currentId);
  }

  return { units, inputs };
};
