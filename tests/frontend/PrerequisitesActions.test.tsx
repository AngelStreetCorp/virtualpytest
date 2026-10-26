// @vitest-environment jsdom
/** TASK-128: a KO check may carry `actions`; each shows as a command in a box with Copy, plus Re-check. */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CheckList } from '../../frontend/src/components/platformUpdate/PrerequisitesBadge';
import type { PrerequisiteCheck } from '../../frontend/src/hooks/platformUpdate/usePrerequisites';

afterEach(cleanup);

const CMD = 'sudo bash /srv/vpt/setup/sudoers/install_vpt_update_sudoers.sh --project-root /srv/vpt';
const check = (over: Partial<PrerequisiteCheck>): PrerequisiteCheck => ({
  id: 'host_sudo', title: 'Sudo rights on hosts', required: true, status: 'ko', detail: 'sudo -n is not allowed on: h1.',
  log: '', fix: 'Run the command.', doc_anchor: 'host-sudo', ...over,
});
const renderList = (checks: PrerequisiteCheck[], onRecheck?: () => void) =>
  render(<MemoryRouter><CheckList checks={checks} onRecheck={onRecheck} /></MemoryRouter>);

describe('CheckList actions', () => {
  it('shows each action command in a box with a Copy button and a Re-check button', async () => {
    const writeText = vi.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const onRecheck = vi.fn();
    renderList([check({ actions: [
      { machine: 'h1', command: CMD, reason: 'a password is required' },
      { machine: 'this server', command: 'sudo bash /opt/x --project-root /opt', reason: 'stale' },
    ] })], onRecheck);
    expect(screen.getAllByTestId('command-box').map((n) => n.textContent)).toContain(CMD);
    expect(screen.getByText('h1')).toBeTruthy();
    fireEvent.click(screen.getAllByText('Copy')[0]);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(CMD));
    fireEvent.click(screen.getByText('Re-check'));
    expect(onRecheck).toHaveBeenCalledTimes(1);
  });

  it('shows nothing extra for a row without actions or an OK row', () => {
    renderList([check({}), check({ id: 'tools', status: 'ok', actions: [{ machine: 'h1', command: CMD, reason: 'x' }] })]);
    expect(screen.queryAllByTestId('command-box')).toHaveLength(0);
    expect(screen.queryByText('Re-check')).toBeNull();
  });
});
