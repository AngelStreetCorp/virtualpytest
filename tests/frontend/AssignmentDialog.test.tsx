/**
 * Assignment: one result uses the per-result endpoints for changed fields only; a
 * selection uses ONE batch call; the label picker stops at the per-entity maximum.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => {
  const mutation = () => ({ mutateAsync: vi.fn(async () => ({})), isPending: false });
  const labels = Array.from({ length: 11 }, (_, i) => ({ id: `l-${i}`, name: `label-${i}`, color: null }));
  return {
    labels: { data: { items: labels }, isLoading: false, error: null },
    milestones: { data: { items: [{ id: 'm-1', name: 'Release 1' }] }, isLoading: false, error: null },
    groups: { data: { items: [{ id: 'g-1', name: 'Nightly' }] }, isLoading: false, error: null },
    mutations: {
      setResultMilestone: mutation(),
      setResultRunGroup: mutation(),
      setResultLabels: mutation(),
      batchAssign: mutation(),
    },
  };
});

vi.mock('../../frontend/src/hooks/reports/useRunManagement', () => ({
  useLabels: () => h.labels,
  useMilestones: () => h.milestones,
  useRunGroups: () => h.groups,
  useGovernanceMutations: () => h.mutations,
}));

import AssignmentDialog from '../../frontend/src/components/reports/AssignmentDialog';
import { LabelPicker } from '../../frontend/src/components/reports/LabelPicker';

describe('AssignmentDialog', () => {
  beforeEach(() => {
    Object.values(h.mutations).forEach((m) => m.mutateAsync.mockClear());
  });

  it('sends only the changed milestone for a single result', async () => {
    const onDone = vi.fn();
    render(
      <AssignmentDialog
        open
        resultIds={['r-1']}
        initial={{ milestone_id: null, run_group_id: null }}
        onClose={() => {}}
        onDone={onDone}
      />,
    );
    fireEvent.mouseDown(screen.getByRole('combobox', { name: /Milestone/ }));
    fireEvent.click(within(screen.getByRole('listbox')).getByRole('option', { name: 'Release 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(h.mutations.setResultMilestone.mutateAsync).toHaveBeenCalledWith({ resultId: 'r-1', milestoneId: 'm-1' });
    expect(h.mutations.setResultRunGroup.mutateAsync).not.toHaveBeenCalled();
    expect(h.mutations.setResultLabels.mutateAsync).not.toHaveBeenCalled();
    expect(h.mutations.batchAssign.mutateAsync).not.toHaveBeenCalled();
  });

  it('uses one batch call with only the changed fields for a selection', async () => {
    const onDone = vi.fn();
    render(
      <AssignmentDialog
        open
        resultIds={['r-1', 'r-2']}
        initial={{ label_ids: ['l-1'] }}
        onClose={() => {}}
        onDone={onDone}
      />,
    );
    fireEvent.click(screen.getByRole('checkbox', { name: 'Set labels' }));
    expect(screen.getByText(/replace the labels currently on each of the 2 selected results/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(h.mutations.batchAssign.mutateAsync).toHaveBeenCalledTimes(1);
    expect(h.mutations.batchAssign.mutateAsync).toHaveBeenCalledWith({
      script_result_ids: ['r-1', 'r-2'],
      label_ids: ['l-1'],
    });
    expect(h.mutations.setResultLabels.mutateAsync).not.toHaveBeenCalled();
  });

  it('keeps Save disabled when nothing changed', () => {
    render(<AssignmentDialog open resultIds={['r-1']} onClose={() => {}} onDone={() => {}} />);
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });
});

describe('LabelPicker', () => {
  it('disables further labels at the maximum of 10', () => {
    const ten = Array.from({ length: 10 }, (_, i) => `l-${i}`);
    render(<LabelPicker value={ten} onChange={() => {}} />);
    expect(screen.getByText('Maximum of 10 labels reached')).toBeInTheDocument();

    const input = screen.getByRole('combobox');
    fireEvent.mouseDown(input);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    const eleventh = screen.getByRole('option', { name: 'label-10' });
    expect(eleventh).toHaveAttribute('aria-disabled', 'true');
  });
});
