// @vitest-environment jsdom
/**
 * The Quality page's window selector carries ONE readable label (BUG-0814).
 *
 * The field had two labels on one control: an `<InputLabel>` next to a `<Select label="Window">`.
 * The label was painted over the select, so only the top row of the letters was visible — and
 * the app paints an opaque background on every outlined field, which covers the lower half of
 * MUI's floating label as well. The label is now plain text next to the select, so nothing can
 * be painted over it, and `labelId` keeps the accessible name.
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../frontend/src/hooks/reports/useRunManagement', () => ({
  useReportScope: () => ({ hostFilter: null }),
}));

import { QualityPageShell } from '../../frontend/src/components/reports/QualityPageShell';

const renderShell = () =>
  render(
    <MemoryRouter>
      <QualityPageShell
        title="Flaky tests"
        description="Which tests are flaky"
        windowDays={14}
        onWindowChange={() => {}}
        loading={false}
        error={null}
      >
        <div>rows</div>
      </QualityPageShell>
    </MemoryRouter>,
  );

describe('the Quality page window selector (BUG-0814)', () => {
  it('shows the label once, not twice', () => {
    renderShell();
    expect(screen.getAllByText('Window')).toHaveLength(1);
  });

  it('shows the label as real text that names the select', () => {
    renderShell();
    const label = screen.getByText('Window');
    expect(label.tagName).toBe('LABEL');

    const select = screen.getByRole('combobox');
    const named = label.getAttribute('for');
    expect(named).toBeTruthy();
    expect(document.getElementById(named as string)).toBe(select);
    expect(select.getAttribute('aria-labelledby')).toContain(label.id);
  });

  it('keeps the label outside the field, so no field background can cover it', () => {
    renderShell();
    const label = screen.getByText('Window');
    const field = screen.getByRole('combobox').closest('.MuiInputBase-root');
    expect(field).toBeTruthy();
    expect(field?.contains(label)).toBe(false);
  });
});
