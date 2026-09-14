import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../frontend/src/hooks/pages/useAIQueue', () => ({
  useAIQueue: () => ({
    getQueueStatus: async () => ({
      status: 'ok',
      service: 'ai-queue',
      timestamp: new Date().toISOString(),
      stats: {},
      analysis_24h: {
        window_hours: 24,
        since: new Date().toISOString(),
        until: new Date().toISOString(),
        scripts: { analyzed: 0, discarded: 0, kept: 0, items: [] },
        incidents: { analyzed: 0, discarded: 0, kept: 0, items: [] },
      },
      queues: {
        incidents: { name: 'incidents', length: 0, processed: 0, discarded: 0, validated: 0, items: [] },
        scripts: { name: 'scripts', length: 0, processed: 0, discarded: 0, validated: 0, items: [] },
      },
    }),
    clearQueues: async () => {},
  }),
}));

import AIQueueMonitor from '../../frontend/src/pages/AIQueueMonitor';

describe('AIQueueMonitor page', () => {
  it('renders the AI Queue Monitor heading', async () => {
    render(<AIQueueMonitor />);

    expect(await screen.findByRole('heading', { name: 'AI Queue Monitor' })).toBeInTheDocument();
  });
});
