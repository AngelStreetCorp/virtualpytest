import { Box, Typography } from '@mui/material';
import { Children } from 'react';
import { AGENT_CHAT_PALETTE } from '../../constants/agentChatTheme';
import { DocsCodeBlock, DocsHeading, DocsTechnicalBlock } from './DocsReaderParts';
import { docsTypeScale } from './docsTypeScale';

/** Plain text of a React children tree (for heading slugs). */
const nodeText = (n: any): string =>
  n == null || typeof n === 'boolean'
    ? ''
    : Array.isArray(n)
      ? n.map(nodeText).join('')
      : typeof n === 'object'
        ? nodeText(n.props?.children)
        : String(n);

/** True when a markdown page holds at least one `<div data-technical>` block. */
export const hasTechnicalBlock = (markdown: string): boolean => /<div\b[^>]*\bdata-technical\b/i.test(markdown);

/** GitHub-style heading slug: lower-case, punctuation dropped, spaces to dashes. */
export const slugifyHeading = (text: string): string =>
  text
    .toLowerCase()
    .trim()
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .replace(/\s/g, '-');

/**
 * Shared react-markdown `components` override used by every docs page. Extracted from
 * Documentation.tsx so ReleaseNotesView can render blocks (In plain words, Upgrade, intro)
 * with the exact same styling and relative-link resolution as the generic doc viewer.
 *
 * `compact` renders every role one step down the scale (docsTypeScale.ts). It is opt-in per section, so
 * the FAQ gets denser without changing the release notes or the technical docs. `scale` multiplies the
 * whole scale (the global Size setting times the reader's S / M / L step).
 */
export const createDocsMarkdownComponents = (
  getCurrentDocPath: () => string,
  page?: string,
  P?: typeof AGENT_CHAT_PALETTE,
  compact = false,
  scale = 1,
  showTechnical = false,
): Record<string, any> => {
  const T = docsTypeScale(compact, scale);

  return {
    // <div data-technical>: hidden unless the reader's "Show technical details" switch is on. Other divs unchanged.
    div: ({ node, children, ...props }: any) => {
      const technical =
        node?.properties?.dataTechnical !== undefined || props['data-technical'] !== undefined || props.dataTechnical !== undefined;
      if (!technical) return <div {...props}>{children}</div>;
      return showTechnical ? <DocsTechnicalBlock>{children}</DocsTechnicalBlock> : null;
    },
    // Style images
    img: ({ src, alt, loading, width, height }: any) => (
      <Box
        component="img"
        src={src}
        alt={alt || ''}
        width={width}
        height={height}
        loading={loading || 'lazy'}
        sx={{
          maxWidth: '100%',
          height: 'auto',
          borderRadius: 1,
          my: 2,
          display: 'block',
        }}
      />
    ),
    // Style headers
    h1: ({ children }: any) => (
      <DocsHeading id={slugifyHeading(nodeText(children))} variant="h4" component="h1" sx={{ mt: 1.5, mb: 1.5, fontWeight: 600, fontSize: T.h1 }}>
        {children}
      </DocsHeading>
    ),
    h2: ({ children }: any) => (
      <DocsHeading id={slugifyHeading(nodeText(children))} variant="h5" component="h2" sx={{ mt: 2, mb: 1.5, fontWeight: 600, fontSize: T.h2 }}>
        {children}
      </DocsHeading>
    ),
    h3: ({ children }: any) => (
      <DocsHeading id={slugifyHeading(nodeText(children))} variant="h6" component="h3" sx={{ mt: 1.5, mb: 1, fontWeight: 600, fontSize: T.h3 }}>
        {children}
      </DocsHeading>
    ),
    h4: ({ children }: any) => (
      <DocsHeading id={slugifyHeading(nodeText(children))} variant="subtitle1" component="h4" sx={{ mt: 1.5, mb: 0.75, fontWeight: 600, fontSize: T.h4 }}>
        {children}
      </DocsHeading>
    ),
    // Style paragraphs
    p: ({ children }: any) => (
      <Typography variant="body2" paragraph sx={{ lineHeight: 1.65, fontSize: T.body, overflowWrap: 'anywhere' }}>
        {children}
      </Typography>
    ),
    // Style code blocks.
    // react-markdown v10 removed the `inline` prop, so we detect a fenced code
    // block by its `language-*` className instead — everything else is an inline
    // span (otherwise every `code` span rendered as a full-width block box).
    code: ({ className, children, ...props }: any) => {
      const isBlock = /(^|\s)language-/.test(className || '');
      if (!isBlock) {
        return (
          <Box
            component="code"
            className={className}
            sx={{
              backgroundColor: 'action.hover',
              px: 0.5,
              py: 0.15,
              borderRadius: 0.5,
              fontFamily: 'monospace',
              fontSize: T.code,
            }}
            {...props}
          >
            {children}
          </Box>
        );
      }
      // A fenced block: the `pre` override below draws the frame; this is only the monospace text.
      return (
        <code className={className} style={{ fontFamily: 'monospace', fontSize: T.code }} {...props}>
          {children}
        </code>
      );
    },
    // Every fenced block (with or without a language) sits in one scrolling, copyable frame inside the card.
    pre: ({ children }: any) => {
      const child: any = Children.toArray(children)[0];
      const inner = child?.props?.children ?? children;
      const lang = /(^|\s)language-/.test(child?.props?.className || '') ? child.props.className : undefined;
      return (
        <DocsCodeBlock text={nodeText(inner).replace(/\n$/, '')}>
          <code className={lang} style={{ fontFamily: 'monospace', fontSize: T.code }}>{inner}</code>
        </DocsCodeBlock>
      );
    },
    // Style links
    a: ({ children, href, id, name }: any) => {
      // Raw-HTML anchors (<a id="step-3"></a>) have no href: keep the id/name so #deep-links can find them.
      if (!href && (id || name)) return <span id={id || name}>{children}</span>;
      // Check if link is an external link or image
      const isExternal = href?.startsWith('http');
      const isImage = href?.match(/\.(png|jpe?g|gif|svg|webp)$/i);

      // Transform markdown links to React routes
      let transformedHref = href;
      if (href && !href.startsWith('http') && !href.startsWith('#') && !isImage) {
        // Handle relative paths in markdown
        if (href.startsWith('../')) {
          // ../features/unified-controller.md -> /docs/features/unified-controller
          // ../../get-started/quickstart.md -> /docs/get-started/quickstart
          transformedHref = '/docs/' + href.replace(/^\.\.\/+/g, '').replace(/\.md$/, '').replace(/\/README$/i, '');
        } else if (href.startsWith('./')) {
          // ./quickstart.md -> current section + quickstart
          // For nested docs, preserve current path
          const currentPath = window.location.pathname.replace(/\/docs\/?/, '').replace(/\/$/, '');
          const parentPath = currentPath.substring(0, currentPath.lastIndexOf('/')) || currentPath;
          const cleanHref = href.substring(2).replace(/\.md$/, '').replace(/\/README$/i, '');
          transformedHref = `/docs/${parentPath}/${cleanHref}`.replace(/\/+/g, '/');
        } else {
          // Bare relative path (e.g. a sibling file linked as `BUG-0006-….md`
          // from the bugs index). Resolve it against the CURRENT doc's directory,
          // not the site root — otherwise the browser drops the section segment
          // (`/docs/bugs` → `/docs/BUG-0006-…`) and the router fetches a missing
          // `…/README.md`, getting the SPA's HTML back.
          const currentDoc = getCurrentDocPath();
          const currentDir =
            page && page !== 'README'
              ? currentDoc.substring(0, currentDoc.lastIndexOf('/'))
              : currentDoc;
          transformedHref = `${currentDir}/${href.replace(/\.md$/, '')}`
            .replace(/\/+/g, '/')
            .replace(/\/README$/i, '');
        }
      }

      return (
        <Box
          component="a"
          href={transformedHref}
          sx={{
            color: P ? P.accentText : 'primary.main',
            textDecoration: 'none',
            overflowWrap: 'anywhere',
            '&:hover': { textDecoration: 'underline' },
          }}
          target={isExternal || isImage ? '_blank' : undefined}
          rel={isExternal || isImage ? 'noopener noreferrer' : undefined}
        >
          {children}
        </Box>
      );
    },
    // Style lists
    ul: ({ children }: any) => (
      <Box component="ul" sx={{ pl: 2.5, my: 1 }}>
        {children}
      </Box>
    ),
    ol: ({ children }: any) => (
      <Box component="ol" sx={{ pl: 2.5, my: 1 }}>
        {children}
      </Box>
    ),
    li: ({ children }: any) => (
      <Typography component="li" variant="body2" sx={{ mb: 0.25, lineHeight: 1.6, fontSize: T.body, minWidth: 0, overflowWrap: 'anywhere' }}>
        {children}
      </Typography>
    ),
    // Style blockquotes
    blockquote: ({ children }: any) => (
      <Box
        sx={{
          borderLeft: '3px solid',
          borderColor: P ? P.accent : 'primary.main',
          pl: 1.5,
          py: 0.25,
          my: 1.5,
          backgroundColor: 'action.hover',
          fontSize: T.body,
        }}
      >
        {children}
      </Box>
    ),
    // Style tables
    table: ({ children }: any) => (
      <Box sx={{ overflowX: 'auto', maxWidth: '100%', minWidth: 0, my: 1.5 }}>
        <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: T.table }}>
          {children}
        </Box>
      </Box>
    ),
    th: ({ children }: any) => (
      <Box
        component="th"
        sx={{
          border: 1,
          borderColor: 'divider',
          p: 1,
          backgroundColor: 'action.hover',
          fontWeight: 600,
          textAlign: 'left',
          fontSize: T.table,
        }}
      >
        {children}
      </Box>
    ),
    td: ({ children }: any) => (
      <Box component="td" sx={{ border: 1, borderColor: 'divider', p: 1, fontSize: T.table }}>
        {children}
      </Box>
    ),
    // Collapsible blocks (<details><summary>): bordered, palette colours, no layout of their own
    details: ({ children, open }: any) => (
      <Box
        component="details"
        open={open}
        sx={{
          my: 1,
          border: 1,
          borderColor: P ? P.borderColor : 'divider',
          borderRadius: 1,
          px: 1.5,
          py: 0.5,
          '&[open] > summary': { mb: 1 },
        }}
      >
        {children}
      </Box>
    ),
    summary: ({ children }: any) => (
      <Box
        component="summary"
        sx={{
          cursor: 'pointer',
          fontWeight: 600,
          fontSize: T.body,
          color: P ? P.accentText : 'primary.main',
        }}
      >
        {children}
      </Box>
    ),
    // Style horizontal rules
    hr: () => <Box component="hr" sx={{ my: 2, border: 'none', borderTop: 1, borderColor: 'divider' }} />,
  };
};

/**
 * Same styling, but paragraphs render inline (no wrapping <p>) — for markdown fragments
 * embedded inside a <li>/<Typography> instead of standing alone as a block.
 */
export const createInlineDocsMarkdownComponents = (
  getCurrentDocPath: () => string,
  page?: string,
  P?: typeof AGENT_CHAT_PALETTE,
  compact = false,
  scale = 1,
  showTechnical = false,
): Record<string, any> => ({
  ...createDocsMarkdownComponents(getCurrentDocPath, page, P, compact, scale, showTechnical),
  p: ({ children }: any) => <>{children}</>,
});
