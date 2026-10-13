import { describe, expect, it } from 'vitest';

import { diffTestcaseVersions, isEmptyDiff } from '../../frontend/src/components/reports/testcaseVersionDiff';
import type { TestcaseVersion } from '../../frontend/src/types/reports';

const version = (n: number, graph: TestcaseVersion['graph_json'], extra: Partial<TestcaseVersion> = {}): TestcaseVersion => ({
  version_number: n,
  testcase_name: 'Login',
  description: 'desc',
  userinterface_name: 'ui-a',
  graph_json: graph,
  ...extra,
});

const base = {
  nodes: [
    { id: 'start', type: 'start', position: { x: 0, y: 0 }, data: { label: 'Start' } },
    { id: 'a1', type: 'action', position: { x: 10, y: 10 }, data: { label: 'Press OK', command: 'press_key', params: { key: 'OK' } } },
    { id: 'v1', type: 'verification', position: { x: 20, y: 20 }, data: { label: 'Check home' } },
  ],
  edges: [
    { id: 'e1', source: 'start', target: 'a1', sourceHandle: 'success' },
    { id: 'e2', source: 'a1', target: 'v1', sourceHandle: 'success' },
  ],
};

describe('diffTestcaseVersions', () => {
  it('reports no differences for identical versions', () => {
    const diff = diffTestcaseVersions(version(1, base), version(2, base));
    expect(isEmptyDiff(diff)).toBe(true);
  });

  it('ignores layout-only node changes', () => {
    const moved = {
      ...base,
      nodes: base.nodes.map((node) => ({ ...node, position: { x: 999, y: 999 }, selected: true, width: 120 })),
    };
    expect(isEmptyDiff(diffTestcaseVersions(version(1, base), version(2, moved)))).toBe(true);
  });

  it('finds added, removed and changed nodes', () => {
    const next = {
      nodes: [
        base.nodes[0],
        { ...base.nodes[1], data: { ...base.nodes[1].data, params: { key: 'BACK' } } },
        { id: 'a2', type: 'action', data: { label: 'Wait' } },
      ],
      edges: base.edges,
    };
    const diff = diffTestcaseVersions(version(1, base), version(2, next));
    expect(diff.nodes.added).toEqual([{ id: 'a2', label: 'Wait' }]);
    expect(diff.nodes.removed).toEqual([{ id: 'v1', label: 'Check home' }]);
    expect(diff.nodes.changed).toEqual([{ id: 'a1', label: 'Press OK', changedKeys: ['data.params'] }]);
  });

  it('finds added, removed and changed edges, keying id-less edges by endpoints', () => {
    const next = {
      nodes: base.nodes,
      edges: [
        { id: 'e1', source: 'start', target: 'a1', sourceHandle: 'failure' },
        { source: 'v1', target: 'start' },
      ],
    };
    const diff = diffTestcaseVersions(version(1, base), version(2, next));
    expect(diff.edges.changed).toEqual([{ key: 'e1', source: 'start', target: 'a1', changedKeys: ['sourceHandle'] }]);
    expect(diff.edges.added).toEqual([{ key: 'v1->start::', source: 'v1', target: 'start' }]);
    expect(diff.edges.removed).toEqual([{ key: 'e2', source: 'a1', target: 'v1' }]);
  });

  it('parses graph_json stored as a JSON string and diffs definition fields', () => {
    const diff = diffTestcaseVersions(
      version(1, JSON.stringify(base)),
      version(2, base, { testcase_name: 'Login v2', description: null }),
    );
    expect(diff.nodes.added).toHaveLength(0);
    expect(diff.nodes.removed).toHaveLength(0);
    expect(diff.fields).toEqual([
      { field: 'testcase_name', before: 'Login', after: 'Login v2' },
      { field: 'description', before: 'desc', after: null },
    ]);
  });

  it('treats object key order as equal', () => {
    const reordered = {
      ...base,
      nodes: base.nodes.map((node) =>
        node.id === 'a1' ? { ...node, data: { params: { key: 'OK' }, command: 'press_key', label: 'Press OK' } } : node,
      ),
    };
    expect(isEmptyDiff(diffTestcaseVersions(version(1, base), version(2, reordered)))).toBe(true);
  });
});
