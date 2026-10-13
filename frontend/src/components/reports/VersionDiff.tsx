/**
 * Read-only renderer for a testcase version diff (definition fields, graph nodes, edges).
 */

import { Box, Chip, Typography } from '@mui/material';
import React from 'react';

import { isEmptyDiff, type TestcaseVersionDiff } from './testcaseVersionDiff';

const FIELD_LABELS: Record<string, string> = {
  testcase_name: 'Name',
  description: 'Description',
  userinterface_name: 'User interface',
};

const Section: React.FC<{ title: string; count: number; children: React.ReactNode }> = ({ title, count, children }) => (
  <Box sx={{ mb: 2 }}>
    <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
      {title} ({count})
    </Typography>
    {count === 0 ? (
      <Typography variant="body2" color="text.secondary">
        No changes
      </Typography>
    ) : (
      children
    )}
  </Box>
);

const Line: React.FC<{ kind: 'added' | 'removed' | 'changed'; children: React.ReactNode }> = ({ kind, children }) => (
  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 0.25, minWidth: 0, flexWrap: 'wrap' }}>
    <Chip
      size="small"
      label={kind}
      color={kind === 'added' ? 'success' : kind === 'removed' ? 'error' : 'warning'}
      variant="outlined"
      sx={{ height: 20 }}
    />
    <Typography variant="body2" sx={{ minWidth: 0, wordBreak: 'break-word' }}>
      {children}
    </Typography>
  </Box>
);

export interface VersionDiffProps {
  diff: TestcaseVersionDiff;
}

export const VersionDiff: React.FC<VersionDiffProps> = ({ diff }) => {
  if (isEmptyDiff(diff)) {
    return (
      <Typography variant="body2" color="text.secondary" data-testid="version-diff-empty">
        No differences between these versions.
      </Typography>
    );
  }
  const nodeCount = diff.nodes.added.length + diff.nodes.removed.length + diff.nodes.changed.length;
  const edgeCount = diff.edges.added.length + diff.edges.removed.length + diff.edges.changed.length;
  return (
    <Box data-testid="version-diff">
      <Section title="Definition" count={diff.fields.length}>
        {diff.fields.map((change) => (
          <Line key={change.field} kind="changed">
            {FIELD_LABELS[change.field] ?? change.field}: “{change.before ?? '—'}” → “{change.after ?? '—'}”
          </Line>
        ))}
      </Section>
      <Section title="Steps (nodes)" count={nodeCount}>
        {diff.nodes.added.map((node) => (
          <Line key={`a-${node.id}`} kind="added">
            {node.label}
          </Line>
        ))}
        {diff.nodes.removed.map((node) => (
          <Line key={`r-${node.id}`} kind="removed">
            {node.label}
          </Line>
        ))}
        {diff.nodes.changed.map((node) => (
          <Line key={`c-${node.id}`} kind="changed">
            {node.label} — {node.changedKeys.join(', ')}
          </Line>
        ))}
      </Section>
      <Section title="Transitions (edges)" count={edgeCount}>
        {diff.edges.added.map((edge) => (
          <Line key={`a-${edge.key}`} kind="added">
            {edge.source} → {edge.target}
          </Line>
        ))}
        {diff.edges.removed.map((edge) => (
          <Line key={`r-${edge.key}`} kind="removed">
            {edge.source} → {edge.target}
          </Line>
        ))}
        {diff.edges.changed.map((edge) => (
          <Line key={`c-${edge.key}`} kind="changed">
            {edge.source} → {edge.target} — {edge.changedKeys.join(', ')}
          </Line>
        ))}
      </Section>
    </Box>
  );
};
