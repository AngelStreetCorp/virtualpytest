/**
 * LifecycleChips — the dev/test/prod renderer shared by the Test Cases list and the
 * Virtual Scripts editor.
 *
 * It is deliberately in core rather than in `features/virtual-scripts/`: a core page cannot
 * import from an optional feature, or a build with DISABLED_FEATURES=virtual-scripts would
 * break the Test Cases page. These tests pin the behaviour both callers rely on.
 */

import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import { LifecycleChips } from '../../frontend/src/components/common/LifecycleChips';

describe('LifecycleChips', () => {
  it('always renders all three env slots, present or not', () => {
    // Missing envs stay visible but greyed, so the three slots line up across rows and
    // the eye can scan a column. Hiding them would make every row a different width.
    render(<LifecycleChips environments={{ dev: true }} />);

    expect(screen.getByText('dev')).toBeInTheDocument();
    expect(screen.getByText('test')).toBeInTheDocument();
    expect(screen.getByText('prod')).toBeInTheDocument();
  });

  it('labels the prod chip with its version when prod exists', () => {
    render(<LifecycleChips environments={{ dev: true, test: true, prod: true }} prodVersion={7} />);
    expect(screen.getByText('prod v7')).toBeInTheDocument();
  });

  it('does not claim a version when prod does not exist', () => {
    // A prod_version left over from a previous promote must not make an absent prod row
    // look present — that would misreport what is deployed.
    render(<LifecycleChips environments={{ dev: true }} prodVersion={7} />);
    expect(screen.queryByText('prod v7')).not.toBeInTheDocument();
    expect(screen.getByText('prod')).toBeInTheDocument();
  });

  it('shows the current version when given one', () => {
    render(<LifecycleChips environments={{ dev: true }} currentVersion={3} />);
    expect(screen.getByText('v3')).toBeInTheDocument();
  });

  it('omits the version entirely when there is none', () => {
    // A disk script has no lifecycle at all; rendering "v" or "v0" would invent one.
    const { container } = render(<LifecycleChips environments={{}} />);
    expect(container.textContent).not.toMatch(/v\d/);
  });

  it('makes prod clickable only when prod exists', () => {
    const onProdClick = vi.fn();
    const { rerender } = render(
      <LifecycleChips environments={{ dev: true }} onProdClick={onProdClick} />,
    );
    screen.getByText('prod').click();
    expect(onProdClick).not.toHaveBeenCalled();

    rerender(<LifecycleChips environments={{ prod: true }} onProdClick={onProdClick} />);
    screen.getByText('prod').click();
    expect(onProdClick).toHaveBeenCalledTimes(1);
  });
});
