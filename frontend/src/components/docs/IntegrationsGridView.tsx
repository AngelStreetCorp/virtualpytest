import { Box, Chip, Typography, alpha } from '@mui/material';
import { ExtensionOutlined } from '@mui/icons-material';
import React from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { createDocsMarkdownComponents } from './markdownComponents';
import { INTEGRATIONS, STATUS_LABEL, type Integration } from './integrationsData';

const urlTransform = (url: string) => (url.startsWith('data:image/') ? url : defaultUrlTransform(url));

/**
 * Drop the README's own H1 and lede (everything before its first `## `). This view
 * supplies both above the grid, and rendering the file's copy underneath would title
 * the page twice. A README with no H2 at all renders unchanged rather than vanishing.
 */
const bodyAfterIntro = (md: string): string => {
  const firstH2 = md.search(/^##\s+/m);
  return firstH2 === -1 ? md : md.slice(firstH2);
};

/**
 * A chip repeating the same word on every card says nothing, and everything on the grid
 * is `live` today. Chips and their legend appear the moment one entry differs — nothing
 * to remember when a Planned integration is added back.
 */
const SHOWS_STATUS = new Set(INTEGRATIONS.map((i) => i.status)).size > 1;

/**
 * One card: mark, name, one sentence, status chip. The card is the link target, so the
 * whole tile is clickable and focusable rather than just the name.
 *
 * The mark is an <img> off `public/brand/`, not an inline path, so the farm logos here
 * are the very files DeviceFarmBadge already serves. Each file brings its own fill; the
 * brand hex only tints the tile behind it. `alt=""` because the parent tile is aria-hidden
 * and the name is right underneath — a screen reader reading the logo would say it twice.
 */
const IntegrationCard: React.FC<{ item: Integration }> = ({ item }) => {
  const navigate = useNavigate();
  const { brand, logo, name, description, status } = item;

  return (
    <Box
      component="a"
      href={item.href}
      onClick={(e: React.MouseEvent) => {
        // Let ctrl/cmd-click and middle-click open a new tab the way the href promises.
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        navigate(item.href);
      }}
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        textAlign: 'center',
        gap: 1,
        p: 2,
        textDecoration: 'none',
        color: 'inherit',
        border: 1,
        borderColor: 'divider',
        borderRadius: 2,
        bgcolor: 'background.default',
        transition: (t) => t.transitions.create(['border-color', 'background-color']),
        '&:hover': {
          borderColor: alpha(brand, 0.6),
          bgcolor: 'action.hover',
        },
        '&:focus-visible': {
          outline: '2px solid',
          outlineColor: 'primary.main',
          outlineOffset: 2,
        },
      }}
    >
      <Box
        aria-hidden
        sx={{
          width: 46,
          height: 46,
          borderRadius: 2.5,
          display: 'grid',
          placeItems: 'center',
          flex: 'none',
          color: brand,
          bgcolor: alpha(brand, 0.15),
        }}
      >
        {logo ? (
          <Box
            component="img"
            src={logo}
            alt=""
            loading="lazy"
            sx={{ width: 26, height: 26, display: 'block', objectFit: 'contain' }}
          />
        ) : (
          <Typography component="span" sx={{ fontSize: '1.3rem', fontWeight: 700, lineHeight: 1 }}>
            {name.charAt(0)}
          </Typography>
        )}
      </Box>

      <Typography component="span" sx={{ fontSize: '0.95rem', fontWeight: 500 }}>
        {name}
      </Typography>

      <Typography
        component="span"
        sx={{ fontSize: '0.8rem', lineHeight: 1.45, color: 'text.secondary' }}
      >
        {description}
      </Typography>

      {SHOWS_STATUS && (
        <Chip
          label={STATUS_LABEL[status]}
          size="small"
          color={status === 'live' ? 'success' : 'default'}
          variant={status === 'live' ? 'filled' : 'outlined'}
          sx={{
            mt: 'auto',
            height: 20,
            fontSize: '0.65rem',
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
          }}
        />
      )}
    </Box>
  );
};

/**
 * The /docs/integrations overview: the grid of what VirtualPyTest connects to, then the
 * rest of the README (integration patterns, the REST API, how to request one) rendered
 * exactly as any other doc page. The two list sections the grid replaces are stripped
 * upstream in Documentation.tsx, so this component always renders whatever is left.
 */
const IntegrationsGridView: React.FC<{
  markdown: string;
  getCurrentDocPath: () => string;
  page?: string;
}> = ({ markdown, getCurrentDocPath, page }) => (
  <Box>
    <Typography
      variant="h4"
      component="h1"
      sx={{ mt: 1.5, mb: 1, fontWeight: 600, fontSize: '1.75rem', display: 'flex', alignItems: 'center', gap: 1.25 }}
    >
      {/* The same icon the docs navigator draws for this section, so the page and the
          dropdown that reached it agree. An emoji here would be the one glyph left. */}
      <ExtensionOutlined sx={{ fontSize: '1.6rem', color: 'primary.main' }} />
      Integrations
    </Typography>
    <Typography sx={{ mb: 3, color: 'text.secondary' }}>
      VirtualPyTest plugs into the tools your team already runs — for tickets, dashboards, CI,
      storage, and the cloud device farms your phones are leased from.
    </Typography>

    <Box
      sx={{
        display: 'grid',
        gap: 1.75,
        gridTemplateColumns: {
          xs: '1fr',
          sm: 'repeat(2, minmax(0, 1fr))',
          md: 'repeat(3, minmax(0, 1fr))',
        },
      }}
    >
      {INTEGRATIONS.map((item) => (
        <IntegrationCard key={item.name} item={item} />
      ))}
    </Box>

    {SHOWS_STATUS && (
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: '8px 24px', mt: 2.5 }}>
        <Typography sx={{ fontSize: '0.8rem', color: 'text.secondary' }}>
          <b>Live</b> — shipped and documented.
        </Typography>
        <Typography sx={{ fontSize: '0.8rem', color: 'text.secondary' }}>
          <b>Planned</b> — wired behind the seam, not finished.
        </Typography>
      </Box>
    )}

    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw]}
      urlTransform={urlTransform}
      components={createDocsMarkdownComponents(getCurrentDocPath, page)}
    >
      {bodyAfterIntro(markdown)}
    </ReactMarkdown>
  </Box>
);

export default IntegrationsGridView;
