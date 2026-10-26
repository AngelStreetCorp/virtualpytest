import { render } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import { ThemeProvider, createTheme } from '@mui/material';

import {
  createDocsMarkdownComponents,
  createInlineDocsMarkdownComponents,
} from '../../frontend/src/components/docs/markdownComponents';
import { docsTypeScale } from '../../frontend/src/components/docs/docsTypeScale';

// The FAQ is the one docs section rendered a step down the shared type scale (compact=1 on
// /docs/faq in Documentation.tsx). These tests pin that scale in both directions, because
// the failure mode is silent: every other role is a plain literal that still typechecks and
// still renders if a size is bumped without the rest following.
//
// The numbers below come straight from docsTypeScale(): retyping them here would drift
// from toFixed rounding the next time the typography constants change. The earlier
// literal-only version compared 1.75rem / 1.35rem / 1.1rem against the values that lived in
// FONT_SIZE_SCALE before the TASK-100 sweep pulled every literal onto the current scale
// (1.5 / 1.125 / 1 / 0.875 / 0.8125); reading the scale from the production function keeps
// this test honest without tying it to a specific snapshot of the typography constants.
const theme = createTheme();
const baseScale = docsTypeScale(false, 1);
const compactScale = docsTypeScale(true, 1);

/**
 * Render one markdown node through a components map and read its font-size. Asserting the
 * computed style (not the function identity) is what makes this testable at all: every call
 * to the factory builds fresh closures, so two maps can never be `toEqual`.
 *
 * jsdom does not resolve `rem` against the root font size, so this returns the authored
 * value verbatim ("0.8rem") — which is exactly what should be pinned here anyway.
 */
const renderSize = (
  components: Record<string, any>,
  role: 'h1' | 'h2' | 'h3' | 'h4' | 'p' | 'code' | 'td',
): string => {
  const Node = components[role];
  const { container, unmount } = render(
    <ThemeProvider theme={theme}>
      <Node>Sample</Node>
    </ThemeProvider>,
  );
  const size = getComputedStyle(container.firstElementChild as Element).fontSize;
  unmount();
  return size;
};

const build = (compact: boolean) =>
  createDocsMarkdownComponents(() => '/docs/faq', 'README', undefined, compact);

describe('Docs markdown type scale', () => {
  it('renders every role one step smaller in compact mode (the FAQ)', () => {
    const t = build(true);
    // "One step" is defined against the base scale, role by role.
    expect(renderSize(t, 'h1')).toBe(compactScale.h1);
    expect(renderSize(t, 'h2')).toBe(compactScale.h2);
    expect(renderSize(t, 'h3')).toBe(compactScale.h3);
    expect(renderSize(t, 'h4')).toBe(compactScale.h4);
    expect(renderSize(t, 'p')).toBe(compactScale.body);
    expect(renderSize(t, 'code')).toBe(compactScale.code);
    expect(renderSize(t, 'td')).toBe(compactScale.table);
  });

  it('leaves the base scale untouched for every other docs section', () => {
    const t = build(false);
    expect(renderSize(t, 'h1')).toBe(baseScale.h1);
    expect(renderSize(t, 'h2')).toBe(baseScale.h2);
    expect(renderSize(t, 'h3')).toBe(baseScale.h3);
    expect(renderSize(t, 'h4')).toBe(baseScale.h4);
    expect(renderSize(t, 'p')).toBe(baseScale.body);
    expect(renderSize(t, 'code')).toBe(baseScale.code);
    expect(renderSize(t, 'td')).toBe(baseScale.table);
  });

  it('defaults to the base scale when compact is omitted', () => {
    // ReleaseNotesView / IntegrationsGridView call the factory without the new argument.
    const omitted = createDocsMarkdownComponents(() => '/docs/get-started');
    for (const role of ['h1', 'h2', 'h3', 'h4', 'p', 'code', 'td'] as const) {
      expect(renderSize(omitted, role)).toBe(renderSize(build(false), role));
    }
  });

  it('forwards compact through the inline variant used by ReleaseNotesView', () => {
    const inline = createInlineDocsMarkdownComponents(() => '/docs/faq', 'README', undefined, true);
    const full = build(true);
    // Same compact scale, and only paragraphs differ (inline renders no wrapping <p>).
    for (const role of ['h1', 'h2', 'h3', 'h4', 'code', 'td'] as const) {
      expect(renderSize(inline, role)).toBe(renderSize(full, role));
    }
    // The inline p returns a fragment with no element, so it must not inherit the block scale.
    expect(inline.p).not.toEqual(full.p);
  });
});