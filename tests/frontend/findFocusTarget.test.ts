import { describe, expect, it } from 'vitest';

import { findFocusTarget } from '../../frontend/src/utils/navigation/findFocusTarget';

const nodes = [
  { value: 't1::home', nodeId: 'home', treeId: 't1' },
  { value: 't2::apps_player', nodeId: 'apps_player', treeId: 't2' },
];

describe('findFocusTarget', () => {
  it('finds a root node', () => {
    expect(findFocusTarget(nodes, 'home')?.treeId).toBe('t1');
  });
  it('finds a subtree node and returns its owning tree', () => {
    expect(findFocusTarget(nodes, 'apps_player')?.value).toBe('t2::apps_player');
  });
  it('returns null for unknown or empty ids', () => {
    expect(findFocusTarget(nodes, 'nope')).toBeNull();
    expect(findFocusTarget(nodes, '')).toBeNull();
    expect(findFocusTarget(nodes, null)).toBeNull();
  });
});
