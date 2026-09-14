import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';

import ApiDocumentation from '../../frontend/src/pages/ApiDocumentation';

describe('ApiDocumentation page', () => {
  it('renders the API documentation heading', () => {
    render(<ApiDocumentation />);

    expect(screen.getByRole('heading', { name: /API Documentation/i })).toBeInTheDocument();
  });
});
