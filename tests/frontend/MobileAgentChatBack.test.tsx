// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react-dom/test-utils';
import { createRoot, Root } from 'react-dom/client';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';

import { MobileAgentChat } from '../../frontend/src/components/ai/MobileAgentChat';

const { navigateMock } = vi.hoisted(() => ({ navigateMock: vi.fn() }));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigateMock };
});

vi.mock('../../frontend/src/i18n/useI18n', () => ({
  useI18n: () => ({ t: (s: string) => s, tn: (_one: string, other: string) => other }),
}));

vi.mock('../../frontend/src/contexts/AgentChatContext', () => ({
  useAgentChatContext: () => ({
    status: 'ready',
    messages: [],
    input: '',
    setInput: vi.fn(),
    sendMessage: vi.fn(),
    isProcessing: false,
    error: null,
    session: null,
  }),
}));

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  navigateMock.mockClear();
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  document.body.innerHTML = '';
  window.history.replaceState(null, '');
});

const render = () => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(<MemoryRouter initialEntries={['/ai-agent']}><MobileAgentChat /></MemoryRouter>));
};

const backButton = () =>
  container!.querySelector('button[aria-label="Back"]') as HTMLButtonElement | null;

describe('the mobile Agent Chat (BUG-0776)', () => {
  it('has a way out of the chat', () => {
    render();
    // The chat is the whole page on a phone and the bottom navigation is hidden on
    // /ai-agent, so the page itself has to offer the way back.
    expect(backButton()).not.toBeNull();
  });

  it('goes back to the dashboard when the app was opened straight onto the chat', () => {
    window.history.replaceState({ idx: 0 }, '');
    render();
    act(() => backButton()!.click());
    expect(navigateMock).toHaveBeenCalledWith('/');
  });

  it('goes back to the page the chat was opened from when there is one', () => {
    window.history.replaceState({ idx: 3 }, '');
    render();
    act(() => backButton()!.click());
    expect(navigateMock).toHaveBeenCalledWith(-1);
  });
});
