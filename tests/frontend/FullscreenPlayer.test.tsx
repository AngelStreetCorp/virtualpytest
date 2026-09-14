import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

// FullscreenPlayer dynamically imports hls.js and drives <video>/HLS internals
// that jsdom doesn't implement — mock the module so mount doesn't explode.
vi.mock('hls.js', () => {
  class HlsMock {
    static isSupported() {
      return false; // exercise the "no src" / native-fallback-safe path deterministically
    }
    static Events = { MANIFEST_PARSED: 'hlsManifestParsed', ERROR: 'hlsError' };
    static ErrorTypes = { NETWORK_ERROR: 'networkError', MEDIA_ERROR: 'mediaError' };
    on() {}
    loadSource() {}
    attachMedia() {}
    destroy() {}
    startLoad() {}
    recoverMediaError() {}
  }
  return { default: HlsMock };
});

import FullscreenPlayer from '../../frontend/src/pages/FullscreenPlayer';

describe('FullscreenPlayer page', () => {
  it('shows a message when no stream URL is provided', () => {
    render(
      <MemoryRouter initialEntries={['/fullscreen']}>
        <FullscreenPlayer />
      </MemoryRouter>,
    );

    expect(screen.getByText('No stream URL provided')).toBeInTheDocument();
  });

  it('renders the video element and label when a src is provided', () => {
    render(
      <MemoryRouter initialEntries={['/fullscreen?src=%2Fstream%2Foutput.m3u8&name=Device1']}>
        <FullscreenPlayer />
      </MemoryRouter>,
    );

    expect(screen.getByText('Device1')).toBeInTheDocument();
    expect(document.querySelector('video')).toBeInTheDocument();
  });
});
