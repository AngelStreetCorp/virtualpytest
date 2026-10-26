// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ActionsMenu } from './ActionsMenu';

afterEach(cleanup);

describe('ActionsMenu', () => {
  it('is one button; the actions live in the menu and keep their handlers', () => {
    const restart = vi.fn();
    const reboot = vi.fn();
    render(
      <ActionsMenu
        label="More actions"
        items={[
          { key: 'a', label: 'Restart service', icon: <i />, onClick: restart },
          { key: 'b', label: 'Reboot', icon: <i />, onClick: reboot, danger: true },
        ]}
      />,
    );
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.queryByText('Reboot')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }));
    expect(screen.getByRole('menuitem', { name: 'Restart service' })).toBeTruthy();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Reboot' }));
    expect(reboot).toHaveBeenCalledTimes(1);
    expect(restart).not.toHaveBeenCalled();
  });
  it('renders nothing without items', () => {
    const { container } = render(<ActionsMenu label="More actions" items={[]} />);
    expect(container.firstChild).toBeNull();
  });
  it('groups items under subheaders with a divider between the groups', () => {
    render(
      <ActionsMenu
        label="More actions"
        items={[
          { key: 'a', group: 'Server', label: 'Restart server', icon: <i />, onClick: vi.fn() },
          { key: 'b', group: 'Server', label: 'Reboot server', icon: <i />, onClick: vi.fn(), danger: true },
          { key: 'c', group: 'All hosts', label: 'Reboot all hosts', icon: <i />, onClick: vi.fn(), danger: true },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }));
    const menu = screen.getByRole('menu');
    expect(Array.from(menu.querySelectorAll('li')).map((li) => li.textContent)).toEqual(['Server', 'Restart server', 'Reboot server', 'All hosts', 'Reboot all hosts']);
    expect(menu.querySelectorAll('hr')).toHaveLength(1);
  });
});
