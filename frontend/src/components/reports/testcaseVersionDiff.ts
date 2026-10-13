/**
 * Structured, read-only diff between two stored testcase versions.
 *
 * Compares the definition fields and the graph (nodes by id, edges by id or by their
 * endpoints). Layout-only node properties (position, selection, measured size) are
 * ignored so moving a block on the canvas is not reported as a change.
 */

import type { TestcaseGraph, TestcaseGraphEdge, TestcaseGraphNode, TestcaseVersion } from '../../types/reports';

const LAYOUT_KEYS = new Set(['position', 'positionAbsolute', 'selected', 'dragging', 'width', 'height']);
const FIELD_KEYS = ['testcase_name', 'description', 'userinterface_name'] as const;
export type VersionDiffField = (typeof FIELD_KEYS)[number];

export interface FieldChange {
  field: VersionDiffField;
  before: string | null;
  after: string | null;
}

export interface NodeRef {
  id: string;
  label: string;
}

export interface NodeChange extends NodeRef {
  changedKeys: string[];
}

export interface EdgeRef {
  key: string;
  source: string;
  target: string;
}

export interface EdgeChange extends EdgeRef {
  changedKeys: string[];
}

export interface TestcaseVersionDiff {
  fields: FieldChange[];
  nodes: { added: NodeRef[]; removed: NodeRef[]; changed: NodeChange[] };
  edges: { added: EdgeRef[]; removed: EdgeRef[]; changed: EdgeChange[] };
}

/** JSON with object keys sorted, so key order never reads as a change. */
export const stableStringify = (value: unknown): string => {
  if (value === undefined) return 'undefined';
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .filter((key) => record[key] !== undefined)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`)
    .join(',')}}`;
};

const parseGraph = (raw: TestcaseVersion['graph_json']): TestcaseGraph => {
  if (!raw) return {};
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw) as unknown;
      return parsed && typeof parsed === 'object' ? (parsed as TestcaseGraph) : {};
    } catch {
      return {};
    }
  }
  return raw;
};

const nodeLabel = (node: TestcaseGraphNode): string => {
  const data = node.data ?? {};
  const label = data.label ?? data.name;
  return typeof label === 'string' && label.trim() ? label : node.id;
};

export const edgeKey = (edge: TestcaseGraphEdge): string =>
  edge.id ? String(edge.id) : `${edge.source}->${edge.target}:${edge.sourceHandle ?? ''}:${edge.targetHandle ?? ''}`;

const differingKeys = (a: Record<string, unknown>, b: Record<string, unknown>, skip: Set<string>): string[] => {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return Array.from(keys)
    .filter((key) => !skip.has(key) && stableStringify(a[key]) !== stableStringify(b[key]))
    .sort();
};

const nodeChangedKeys = (before: TestcaseGraphNode, after: TestcaseGraphNode): string[] => {
  const skip = new Set([...LAYOUT_KEYS, 'data']);
  const top = differingKeys(before, after, skip);
  const data = differingKeys(before.data ?? {}, after.data ?? {}, new Set()).map((key) => `data.${key}`);
  return [...top, ...data];
};

const EDGE_COMPARED = ['source', 'target', 'type', 'sourceHandle', 'targetHandle', 'data'] as const;

const edgeChangedKeys = (before: TestcaseGraphEdge, after: TestcaseGraphEdge): string[] =>
  EDGE_COMPARED.filter((key) => stableStringify(before[key] ?? null) !== stableStringify(after[key] ?? null));

const asText = (value: unknown): string | null =>
  value === null || value === undefined || value === '' ? null : String(value);

export const diffTestcaseVersions = (older: TestcaseVersion, newer: TestcaseVersion): TestcaseVersionDiff => {
  const fields: FieldChange[] = FIELD_KEYS.flatMap((field) => {
    const before = asText(older[field]);
    const after = asText(newer[field]);
    return before === after ? [] : [{ field, before, after }];
  });

  const oldGraph = parseGraph(older.graph_json);
  const newGraph = parseGraph(newer.graph_json);

  const oldNodes = new Map((oldGraph.nodes ?? []).map((node) => [node.id, node]));
  const newNodes = new Map((newGraph.nodes ?? []).map((node) => [node.id, node]));
  const nodes: TestcaseVersionDiff['nodes'] = { added: [], removed: [], changed: [] };
  newNodes.forEach((node, id) => {
    const previous = oldNodes.get(id);
    if (!previous) {
      nodes.added.push({ id, label: nodeLabel(node) });
      return;
    }
    const changedKeys = nodeChangedKeys(previous, node);
    if (changedKeys.length) nodes.changed.push({ id, label: nodeLabel(node), changedKeys });
  });
  oldNodes.forEach((node, id) => {
    if (!newNodes.has(id)) nodes.removed.push({ id, label: nodeLabel(node) });
  });

  const oldEdges = new Map((oldGraph.edges ?? []).map((edge) => [edgeKey(edge), edge]));
  const newEdges = new Map((newGraph.edges ?? []).map((edge) => [edgeKey(edge), edge]));
  const edges: TestcaseVersionDiff['edges'] = { added: [], removed: [], changed: [] };
  newEdges.forEach((edge, key) => {
    const previous = oldEdges.get(key);
    const ref = { key, source: edge.source, target: edge.target };
    if (!previous) {
      edges.added.push(ref);
      return;
    }
    const changedKeys = edgeChangedKeys(previous, edge);
    if (changedKeys.length) edges.changed.push({ ...ref, changedKeys });
  });
  oldEdges.forEach((edge, key) => {
    if (!newEdges.has(key)) edges.removed.push({ key, source: edge.source, target: edge.target });
  });

  return { fields, nodes, edges };
};

export const isEmptyDiff = (diff: TestcaseVersionDiff): boolean =>
  diff.fields.length === 0 &&
  diff.nodes.added.length + diff.nodes.removed.length + diff.nodes.changed.length === 0 &&
  diff.edges.added.length + diff.edges.removed.length + diff.edges.changed.length === 0;
