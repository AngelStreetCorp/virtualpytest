// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import { PAGED_LIST_ROW_HEIGHT, PagedList } from './PagedList';

afterEach(cleanup);

const rows = Array.from({ length: 12 }, (_, i) => `row ${i + 1}`);

describe('PagedList', () => {
  it('shows a counter and pager buttons past three rows', () => {
    render(<PagedList rows={rows} getKey={(r) => r} renderRow={(r) => <span>{r}</span>} emptyText="none" />);
    expect(screen.getByTestId('paged-list-counter').textContent).toBe('1–3 of 12');
    expect(screen.getByLabelText('Next rows')).toBeTruthy();
  });
  it('updates the counter when scrolled', () => {
    render(<PagedList rows={rows} getKey={(r) => r} renderRow={(r) => <span>{r}</span>} emptyText="none" />);
    const scroller = screen.getByTestId('paged-list-scroller');
    scroller.scrollTop = PAGED_LIST_ROW_HEIGHT * 3;
    fireEvent.scroll(scroller);
    expect(screen.getByTestId('paged-list-counter').textContent).toBe('4–6 of 12');
  });
  it('has no pager for three rows or fewer', () => {
    render(<PagedList rows={rows.slice(0, 3)} getKey={(r) => r} renderRow={(r) => <span>{r}</span>} emptyText="none" />);
    expect(screen.queryByTestId('paged-list-counter')).toBeNull();
  });
  it('shows the empty text', () => {
    render(<PagedList rows={[]} getKey={(r) => String(r)} renderRow={() => null} emptyText="none" />);
    expect(screen.getByText('none')).toBeTruthy();
  });
});
