import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

// HLSDebugPage dynamically imports hls.js and drives <video>/HLS internals
// that jsdom doesn't implement — mock the module so mount doesn't explode.
vi.mock('hls.js', () => {
  class HlsMock {
    static isSupported() {
      return false;
    }
    static Events = {
      MANIFEST_PARSED: 'hlsManifestParsed',
      LEVEL_LOADED: 'hlsLevelLoaded',
      FRAG_LOADED: 'hlsFragLoaded',
      FRAG_PARSING_USERDATA: 'hlsFragParsingUserdata',
      ERROR: 'hlsError',
    };
    on() {}
    loadSource() {}
    attachMedia() {}
    destroy() {}
    startLoad() {}
  }
  return { default: HlsMock };
});

import HLSDebugPage from '../../frontend/src/pages/HLSDebugPage';

describe('HLSDebugPage', () => {
  it('renders the debug page heading and stream controls', () => {
    render(
      <BrowserRouter>
        <HLSDebugPage />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'HLS Debug Page' })).toBeInTheDocument();
    expect(screen.getByText('Video Player')).toBeInTheDocument();
    expect(screen.getByText('Stream Stats')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Play/i })).toBeInTheDocument();
  });
});
