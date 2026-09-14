import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';

import SecurityReports from '../../frontend/src/pages/SecurityReports';

describe('SecurityReports page', () => {
  it('renders the Security Reports heading', () => {
    render(<SecurityReports />);

    expect(screen.getByText('Security Reports')).toBeInTheDocument();
  });
});
