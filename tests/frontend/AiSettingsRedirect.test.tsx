/**
 * The OpenRouter debug page (BUG-0797).
 *
 * The page called `POST /server/ai-tools/debug/openrouter`, a route that was
 * removed with the AI unification (`8b4dce04b`), so Execute always answered
 * 400 and the page looked like a working tool that is broken. The tool now
 * lives in Settings → AI, and the old address redirects there.
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { AiSettingsRedirect } from '../../frontend/src/components/common/AiSettingsRedirect';

describe('the retired OpenRouter debug address', () => {
  it('sends the developer to the AI settings, where the endpoint test lives', async () => {
    render(
      <MemoryRouter initialEntries={['/configuration/openrouter']}>
        <Routes>
          <Route path="/configuration/openrouter" element={<AiSettingsRedirect />} />
          <Route
            path="/configuration/settings"
            element={<div>Settings — AI tab</div>}
          />
        </Routes>
      </MemoryRouter>,
    );

    // The redirect lands on the AI tab of the settings.
    expect(await screen.findByText('Settings — AI tab')).toBeInTheDocument();
  });
});
