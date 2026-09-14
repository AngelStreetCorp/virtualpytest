import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

import LangfuseDashboard from '../../frontend/src/pages/LangfuseDashboard';

describe('LangfuseDashboard page', () => {
  it('renders the not-enabled state when VITE_LANGFUSE_URL is unset', () => {
    // In the test env VITE_LANGFUSE_URL is not defined, so the page renders
    // its "not enabled" instructional state rather than the iframe.
    render(
      <BrowserRouter>
        <LangfuseDashboard />
      </BrowserRouter>,
    );

    expect(screen.getByText('Langfuse LLM Observability')).toBeInTheDocument();
    expect(screen.getByText(/Langfuse is not enabled/i)).toBeInTheDocument();
  });
});
