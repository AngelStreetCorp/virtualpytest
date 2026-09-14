import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../frontend/src/components/campaign/CampaignSelector', () => ({
  CampaignSelector: React.forwardRef(function CampaignSelectorMock(_props: any, _ref: any) {
    return <div data-testid="campaign-selector" />;
  }),
}));

import CampaignEditor from '../../frontend/src/pages/CampaignEditor';

describe('CampaignEditor page', () => {
  it('renders the Campaign heading', () => {
    render(<CampaignEditor />);

    expect(screen.getByRole('heading', { name: 'Campaign' })).toBeInTheDocument();
    expect(screen.getByTestId('campaign-selector')).toBeInTheDocument();
  });
});
