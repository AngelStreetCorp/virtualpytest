/**
 * TASK-113 — migration-3 tests: AllServersSettingsLanding.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const handleChangeMock = vi.fn();
vi.mock('../../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    serverHostsData: [
      {
        server_info: { server_url: 'https://a.example.test', server_name: 'Alpha' },
        hosts: [{ host_name: 'h-1' }, { host_name: 'h-2' }],
      },
      {
        server_info: { server_url: 'https://b.example.test', server_name: 'Beta' },
        hosts: [{ host_name: 'h-3' }],
      },
    ],
    serverAuthStates: {
      'https://a.example.test': 'authenticated',
      'https://b.example.test': 'authenticated',
    },
    selectedServer: '__all__',
  }),
}));
vi.mock('../../../frontend/src/hooks/useServerPicker', () => ({
  useServerPicker: () => ({
    handleChange: handleChangeMock,
  }),
}));

import { AllServersSettingsLanding } from '../../../frontend/src/components/settings/AllServersSettingsLanding';

describe('AllServersSettingsLanding', () => {
  beforeEach(() => {
    handleChangeMock.mockClear();
  });

  it('renders one card per eligible server', () => {
    render(<AllServersSettingsLanding />);
    expect(screen.getByTestId('settings-server-card-https://a.example.test')).toBeTruthy();
    expect(screen.getByTestId('settings-server-card-https://b.example.test')).toBeTruthy();
  });

  it('shows the host count for each server', () => {
    render(<AllServersSettingsLanding />);
    expect(screen.getByText('2 hosts')).toBeTruthy();
    expect(screen.getByText('1 host')).toBeTruthy();
  });

  it('switching the picker to a server fires handleChange with that URL', () => {
    render(<AllServersSettingsLanding />);
    const card = screen.getByTestId('settings-server-card-https://b.example.test');
    const button = card.querySelector('button');
    if (button) fireEvent.click(button);
    else fireEvent.click(card);
    expect(handleChangeMock).toHaveBeenCalledWith('https://b.example.test');
  });
});
