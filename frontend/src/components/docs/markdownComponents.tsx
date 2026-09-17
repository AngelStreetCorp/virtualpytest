import { Box, Typography } from '@mui/material';

/**
 * Shared react-markdown `components` override used by every docs page. Extracted from
 * Documentation.tsx so ReleaseNotesView can render blocks (In plain words, Upgrade, intro)
 * with the exact same styling and relative-link resolution as the generic doc viewer.
 */
export const createDocsMarkdownComponents = (
  getCurrentDocPath: () => string,
  page?: string
): Record<string, any> => ({
  // Style images
  img: ({ src, alt, loading }: any) => (
    <Box
      component="img"
      src={src}
      alt={alt || ''}
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
    <Typography variant="h4" component="h1" gutterBottom sx={{ mt: 1.5, mb: 1.5, fontWeight: 600, fontSize: '1.75rem' }}>
      {children}
    </Typography>
  ),
  h2: ({ children }: any) => (
    <Typography variant="h5" component="h2" gutterBottom sx={{ mt: 2, mb: 1.5, fontWeight: 600, fontSize: '1.35rem' }}>
      {children}
    </Typography>
  ),
  h3: ({ children }: any) => (
    <Typography variant="h6" component="h3" gutterBottom sx={{ mt: 1.5, mb: 1, fontWeight: 600, fontSize: '1.1rem' }}>
      {children}
    </Typography>
  ),
  h4: ({ children }: any) => (
    <Typography variant="subtitle1" component="h4" gutterBottom sx={{ mt: 1.5, mb: 0.75, fontWeight: 600, fontSize: '1rem' }}>
      {children}
    </Typography>
  ),
  // Style paragraphs
  p: ({ children }: any) => (
    <Typography variant="body2" paragraph sx={{ lineHeight: 1.65, fontSize: '0.9rem' }}>
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
            fontSize: '0.8rem',
          }}
          {...props}
        >
          {children}
        </Box>
      );
    }
    return (
      <Box
        component="pre"
        sx={{
          backgroundColor: 'action.hover',
          p: 1.5,
          borderRadius: 1,
          overflow: 'auto',
          my: 1.5,
          border: 1,
          borderColor: 'divider',
        }}
      >
        <code style={{ fontFamily: 'monospace', fontSize: '0.8rem' }} {...props}>
          {children}
        </code>
      </Box>
    );
  },
  // Style links
  a: ({ children, href }: any) => {
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
          color: 'primary.main',
          textDecoration: 'none',
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
    <Typography component="li" variant="body2" sx={{ mb: 0.25, lineHeight: 1.6, fontSize: '0.9rem' }}>
      {children}
    </Typography>
  ),
  // Style blockquotes
  blockquote: ({ children }: any) => (
    <Box
      sx={{
        borderLeft: '3px solid',
        borderColor: 'primary.main',
        pl: 1.5,
        py: 0.25,
        my: 1.5,
        backgroundColor: 'action.hover',
        fontSize: '0.9rem',
      }}
    >
      {children}
    </Box>
  ),
  // Style tables
  table: ({ children }: any) => (
    <Box sx={{ overflowX: 'auto', my: 1.5 }}>
      <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
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
        fontSize: '0.85rem',
      }}
    >
      {children}
    </Box>
  ),
  td: ({ children }: any) => (
    <Box component="td" sx={{ border: 1, borderColor: 'divider', p: 1, fontSize: '0.85rem' }}>
      {children}
    </Box>
  ),
  // Style horizontal rules
  hr: () => <Box component="hr" sx={{ my: 2, border: 'none', borderTop: 1, borderColor: 'divider' }} />,
});

/**
 * Same styling, but paragraphs render inline (no wrapping <p>) — for markdown fragments
 * embedded inside a <li>/<Typography> instead of standing alone as a block.
 */
export const createInlineDocsMarkdownComponents = (
  getCurrentDocPath: () => string,
  page?: string
): Record<string, any> => ({
  ...createDocsMarkdownComponents(getCurrentDocPath, page),
  p: ({ children }: any) => <>{children}</>,
});
