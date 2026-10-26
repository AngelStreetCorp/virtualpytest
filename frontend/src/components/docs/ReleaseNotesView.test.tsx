// @vitest-environment jsdom
/**
 * /docs/bugs and /docs/release_note are a stack of build cards — Unreleased open, older builds
 * closed — and the picker FILTERS that stack: the default is every build, picking one narrows to
 * it. A `?list=` naming nothing falls back to every build rather than a blank screen, and `?q=`
 * filters the rows.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import ReleaseNotesView from './ReleaseNotesView';

afterEach(cleanup);

/** Trimmed shape of docs/bugs/README.md as build_bug_index.py writes it. */
const BUGS = `# 🐛 Bug Tracker

What broke and what shipped to fix it, newest first.

## Unreleased

- **The tile stayed black after the drone was switched off** · reported 2026-10-13 · [BUG-0519](BUG-0519.md)
- **A stale pin could be delivered in a customer bundle** · reported 2026-10-13 · [BUG-0518](BUG-0518.md)

## build 9389

- **A report video lost its tail when the archiver rotated** · reported 2026-09-30 · [BUG-0469](BUG-0469.md)

## build 9369 — 2026-09-26

- **The KPI tile content was not centred** · reported 2026-09-26 · [BUG-0471](BUG-0471.md)
`;

const LocationProbe: React.FC = () => {
  const { search } = useLocation();
  return <div data-testid="location">{search}</div>;
};

const renderBugs = (entry = '/docs/bugs') =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <LocationProbe />
      <ReleaseNotesView kind="bugs" title="Bug Tracker" markdown={BUGS} getCurrentDocPath={() => '/docs/bugs'} page="README" />
    </MemoryRouter>,
  );

const pickFrom = (optionText: string) => {
  fireEvent.mouseDown(screen.getByRole('combobox'));
  fireEvent.click(screen.getByRole('option', { name: optionText }));
};

describe('ReleaseNotesView builds', () => {
  it('shows every build card, Unreleased open and older builds closed, with no intro', () => {
    renderBugs();
    expect(screen.getByRole('heading', { name: 'Bug Tracker' })).toBeTruthy();
    expect(screen.queryByText(/What broke and what shipped/)).toBeNull();
    for (const name of ['Unreleased', 'build 9389', 'build 9369']) {
      expect(screen.getByRole('heading', { name })).toBeTruthy();
    }
    expect(screen.getByText('BUG-0519')).toBeTruthy();
    expect(screen.queryByText('BUG-0469')).toBeNull();
    expect(screen.getByTestId('location').textContent).toBe('');
    expect(screen.getByRole('combobox').textContent).toBe('All builds');
  });

  it('opens a closed build on click', () => {
    renderBugs();
    fireEvent.click(screen.getByRole('heading', { name: 'build 9389' }));
    expect(screen.getByText('BUG-0469')).toBeTruthy();
  });

  it('offers All builds plus every build, newest first', () => {
    renderBugs();
    fireEvent.mouseDown(screen.getByRole('combobox'));
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual([
      'All builds',
      'Unreleased',
      'build 9389',
      'build 9369 — 2026-09-26',
    ]);
  });

  it('narrows to the picked build and puts the choice in the URL', () => {
    renderBugs();
    pickFrom('build 9389');
    expect(screen.getByText('BUG-0469')).toBeTruthy();
    expect(screen.queryByText('BUG-0519')).toBeNull();
    expect(screen.getByTestId('location').textContent).toBe('?list=build-9389');
  });

  it('goes back to every build when All builds is picked again', () => {
    renderBugs('/docs/bugs?list=build-9369');
    expect(screen.queryByText('BUG-0519')).toBeNull();
    pickFrom('All builds');
    expect(screen.getByText('BUG-0519')).toBeTruthy();
    expect(screen.getByTestId('location').textContent).toBe('');
  });

  it('falls back to every build when ?list= names nothing', () => {
    renderBugs('/docs/bugs?list=build-9999');
    expect(screen.getByRole('heading', { name: 'build 9369' })).toBeTruthy();
    expect(screen.getByText('BUG-0519')).toBeTruthy();
  });

  it('filters rows by ?q= and hides builds without a match', () => {
    renderBugs('/docs/bugs?q=BUG-0471');
    expect(screen.getByText('BUG-0471')).toBeTruthy();
    expect(screen.queryByText('BUG-0519')).toBeNull();
    expect(screen.queryByRole('heading', { name: 'build 9389' })).toBeNull();
  });

  it('links to the other page in a new tab', () => {
    renderBugs();
    const link = screen.getByRole('link', { name: /Release notes/ });
    expect(link.getAttribute('href')).toBe('/docs/release_note');
    expect(link.getAttribute('target')).toBe('_blank');
  });
});
