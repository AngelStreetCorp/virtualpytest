/**
 * Labels catalog: client validation mirrors the server (trim, 1–20 chars,
 * case-insensitive uniqueness), server refusals are displayed, delete says what it removes.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../../frontend/src/hooks/reports/runManagementApi';
import { validateLabelName, validateLabelSelection } from '../../frontend/src/types/reports';

const h = vi.hoisted(() => ({
  labels: {
    data: {
      items: [
        // GET /server/run-labels rows: no usage count is sent.
        { id: 'l-1', name: 'smoke', color: '#2a78d6', created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z' },
        { id: 'l-2', name: 'nightly', color: null, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z' },
      ],
    },
    isLoading: false,
    error: null,
  },
  mutations: {
    createLabel: { mutateAsync: vi.fn(), isPending: false },
    updateLabel: { mutateAsync: vi.fn(), isPending: false },
    deleteLabel: { mutateAsync: vi.fn(), isPending: false },
  },
}));

vi.mock('../../frontend/src/hooks/useToast', () => ({
  useToast: () => ({ showSuccess: () => {}, showError: () => {}, showInfo: () => {}, showWarning: () => {} }),
}));
vi.mock('../../frontend/src/hooks/reports/useRunManagement', () => ({
  useLabels: () => h.labels,
  useReportPermissions: () => ({ canEdit: true }),
  useGovernanceMutations: () => h.mutations,
}));

import RunLabels from '../../frontend/src/pages/RunLabels';

const renderPage = () =>
  render(
    <MemoryRouter>
      <RunLabels />
    </MemoryRouter>,
  );

const openCreate = () => {
  fireEvent.click(screen.getByRole('button', { name: 'New label' }));
  return screen.getByTestId('label-name') as HTMLInputElement;
};

describe('label validation helpers', () => {
  const existing = [{ id: 'l-1', name: 'Smoke' }];
  it('trims and bounds the name', () => {
    expect(validateLabelName('   ', existing)).toBe('Name is required');
    expect(validateLabelName('x'.repeat(21), existing)).toBe('At most 20 characters');
    expect(validateLabelName(`  ${'x'.repeat(20)}  `, existing)).toBeNull();
  });
  it('is case-insensitively unique, except for the label being renamed', () => {
    expect(validateLabelName(' SMOKE ', existing)).toBe('A label with this name already exists');
    expect(validateLabelName('smoke', existing, 'l-1')).toBeNull();
  });
  it('caps a selection at 10 labels', () => {
    expect(validateLabelSelection(Array.from({ length: 10 }, (_, i) => `l${i}`))).toBeNull();
    expect(validateLabelSelection(Array.from({ length: 11 }, (_, i) => `l${i}`))).toMatch(/At most 10/);
  });
});

describe('RunLabels page', () => {
  beforeEach(() => {
    Object.values(h.mutations).forEach((m) => m.mutateAsync.mockReset());
  });

  it('lists labels with a link to their results (the catalog carries no usage count)', () => {
    renderPage();
    expect(screen.getByText('smoke')).toBeInTheDocument();
    expect(screen.queryByText(/\d+ results?$/)).not.toBeInTheDocument();
    const links = screen.getAllByRole('link', { name: 'View results' });
    expect(links[0]).toHaveAttribute('href', '/test-results/reports?label=l-1');
  });

  it('rejects empty, too long and duplicate names before calling the server', () => {
    renderPage();
    const input = openCreate();
    fireEvent.change(input, { target: { value: '   ' } });
    expect(screen.getByText('Name is required')).toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'x'.repeat(21) } });
    expect(screen.getByText('At most 20 characters')).toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'SMOKE' } });
    expect(screen.getByText('A label with this name already exists')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(h.mutations.createLabel.mutateAsync).not.toHaveBeenCalled();
  });

  it('creates with a trimmed name', async () => {
    h.mutations.createLabel.mutateAsync.mockResolvedValue({ id: 'l-3', name: 'regression' });
    renderPage();
    const input = openCreate();
    fireEvent.change(input, { target: { value: '  regression  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(h.mutations.createLabel.mutateAsync).toHaveBeenCalledWith({ name: 'regression', color: '#2a78d6' }),
    );
  });

  it('shows the server refusal', async () => {
    h.mutations.createLabel.mutateAsync.mockRejectedValue(new ApiError(409, 'label refused (name conflict)', {}));
    renderPage();
    const input = openCreate();
    fireEvent.change(input, { target: { value: 'fresh' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByTestId('label-server-error')).toHaveTextContent('label refused (name conflict)');
  });

  it('explains that removing a label keeps the results', async () => {
    h.mutations.deleteLabel.mutateAsync.mockResolvedValue({
      removed_script_result_assignments: 3,
      removed_testcase_assignments: 0,
    });
    renderPage();
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[0]);
    expect(
      screen.getByText(
        'Removes the label "smoke" from every result and test case that carries it. ' +
          'The results and test cases themselves are not changed.',
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Remove label' }));
    await waitFor(() => expect(h.mutations.deleteLabel.mutateAsync).toHaveBeenCalledWith('l-1'));
  });
});
