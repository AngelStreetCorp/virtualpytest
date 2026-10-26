import { describe, expect, it } from 'vitest';

import { localizeBadgeText } from './LocalizeVideoBadge';

describe('localizeBadgeText (TASK-115)', () => {
  it('names a node with no confidence', () => {
    expect(localizeBadgeText({ kind: 'node', label: 'home', confidence: 0.957 })).toBe('home');
  });
  it('keeps live as the label', () => {
    expect(localizeBadgeText({ kind: 'live', label: 'Live video', confidence: 1 })).toBe('Live video');
  });
  it('names a signal with no confidence', () => {
    expect(localizeBadgeText({ kind: 'signal', label: 'Black Screen', confidence: 1 })).toBe('Black Screen');
    expect(localizeBadgeText({ kind: 'signal', label: 'No Signal' })).toBe('No Signal');
  });
  it('shows nothing on unknown or no verdict', () => {
    expect(localizeBadgeText({ kind: 'unknown', label: 'unknown' })).toBeNull();
    expect(localizeBadgeText({ kind: 'known_screen', label: '', evidence: { named: false } })).toBeNull();
    expect(localizeBadgeText({ kind: 'known_screen', label: 'Splash' })).toBe('Splash');
    expect(localizeBadgeText({ kind: 'known_screen', label: 'Splash (poster)' })).toBe('Splash');
    expect(localizeBadgeText(null)).toBeNull();
  });
});
