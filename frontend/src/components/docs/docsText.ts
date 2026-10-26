import { Children, cloneElement, isValidElement, type ReactNode } from 'react';

/**
 * No emoji in the docs chrome or the reader outline (UI_STYLE.md "Docs reader"). The markdown
 * headings still carry them for GitHub readers ("🚀 Get Started"); everything the app draws from a
 * heading (nav, "On this page", search, the rendered heading) goes through these helpers.
 * Keycaps (1️⃣), pictographs, flags, ZWJ joiners and variation selectors go; ©, ® and ™ stay.
 * scripts/gen-docs-search-index.mjs carries the same pattern for the build-time index.
 */
const EMOJI = /(?:[0-9#*]\uFE0F?\u20E3|(?![\u00A9\u00AE\u2122])\p{Extended_Pictographic}|\p{Regional_Indicator}|\uFE0F|\u200D|\u20E3)+/gu;

export const stripEmoji = (text: string): string => text.replace(EMOJI, '').replace(/\s{2,}/g, ' ').trim();

export const hasEmoji = (text: string): boolean => {
  EMOJI.lastIndex = 0;
  return EMOJI.test(text);
};

/** Same as stripEmoji on a React children tree (text nodes only); the leading space an emoji leaves is trimmed. */
export const stripEmojiNode = (node: ReactNode): ReactNode => {
  const mapped = Children.map(node, (child) => {
    if (typeof child === 'string') return child.replace(EMOJI, '');
    if (isValidElement<{ children?: ReactNode }>(child) && child.props.children !== undefined) {
      return cloneElement(child, undefined, stripEmojiNode(child.props.children));
    }
    return child;
  });
  if (Array.isArray(mapped) && typeof mapped[0] === 'string') mapped[0] = mapped[0].replace(/^\s+/, '');
  return mapped;
};
