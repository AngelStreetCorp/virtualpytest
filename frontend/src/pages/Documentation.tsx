import { 
  Box, 
  Typography, 
  FormControl,
  Select,
  MenuItem,
  ListSubheader,
  SelectChangeEvent,
} from '@mui/material';
import { ChevronRight } from '@mui/icons-material';
import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';

// Types for docs manifest
interface DocItem {
  title: string;
  path?: string;
  children?: DocItem[];
}

interface DocSection {
  title: string;
  path: string;
  section: string;
  children?: DocItem[];
}

interface DocsManifest {
  docs: DocSection[];
}

// Meta/process H2 sections that are useful for contributors editing the file in-repo
// but are noise for the in-app reader. Keyed by route `section`, stripped before render
// so the page shows only the shipped changelog / the bug index.
const STRIP_SECTIONS: Record<string, string[]> = {
  release_note: ['When to update this file'],
  bugs: ['How to log a bug'],
};

/**
 * Remove the configured H2 sections (heading through to the next H1/H2 heading) from a
 * markdown document. Any horizontal rule / trailing lines that belonged to the stripped
 * section are dropped with it. Unknown sections are left untouched.
 */
const stripMetaSections = (md: string, section?: string): string => {
  const titles = section ? STRIP_SECTIONS[section] : undefined;
  if (!titles || titles.length === 0) return md;
  const wanted = titles.map((t) => t.toLowerCase());

  const out: string[] = [];
  let skipping = false;
  for (const line of md.split('\n')) {
    const heading = line.match(/^(#{1,2})\s+(.*)$/);
    if (heading) {
      const title = heading[2].trim().toLowerCase();
      // Starting a stripped section begins skipping; any other H1/H2 ends it.
      skipping = wanted.includes(title);
      if (skipping) continue;
    }
    if (!skipping) out.push(line);
  }
  return out.join('\n');
};

/**
 * Documentation Navigator Dropdown - Lists all available docs
 */
const DocsNavigator: React.FC<{ currentPath: string }> = ({ currentPath }) => {
  const navigate = useNavigate();
  const [manifest, setManifest] = useState<DocsManifest>({ docs: [] });
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const loadManifest = async () => {
      const candidates = ['/docs/docs-manifest.json', '/docs-manifest.json'];
      for (const url of candidates) {
        try {
          const res = await fetch(url, { cache: 'no-store' });
          if (!res.ok) continue;
          const text = await res.text();
          const parsed = JSON.parse(text) as DocsManifest;
          if (parsed && Array.isArray(parsed.docs)) {
            setManifest(parsed);
            return;
          }
        } catch {
          // Try next candidate URL
        }
      }
      // Avoid endless loading spinner if manifest is unavailable or HTML is returned.
      setManifest({ docs: [] });
      console.error('Failed to load docs manifest from known paths');
    };

    void loadManifest();
  }, []);

  const handleChange = (event: SelectChangeEvent<string>) => {
    const path = event.target.value;
    if (path) {
      navigate(path);
      setOpen(false);
    }
  };

  // Check if a section has any files (direct paths or nested paths)
  const hasFiles = (children?: DocItem[]): boolean => {
    if (!children) return false;
    return children.some(child => 
      child.path || (child.children && hasFiles(child.children))
    );
  };

  // Flatten all doc items for the dropdown
  const renderMenuItems = () => {
    if (!manifest) return null;
    
    const items: React.ReactNode[] = [];
    let visibleSectionIdx = 0;
    
    manifest.docs.forEach((section) => {
      // Skip sections with no children (like Documentation Home which only has a path)
      if (!section.children || !hasFiles(section.children)) return;
      
      // Add section header
      items.push(
        <ListSubheader 
          key={`section-${section.section}`}
          sx={{ 
            bgcolor: 'background.paper',
            color: 'primary.main',
            fontWeight: 600,
            fontSize: '0.8rem',
            lineHeight: '24px',
            py: 0.25,
            borderTop: visibleSectionIdx > 0 ? 1 : 0,
            borderColor: 'divider',
          }}
        >
          {section.title}
        </ListSubheader>
      );
      visibleSectionIdx++;

      // Add section children
      if (section.children) {
        section.children.forEach((child, childIdx) => {
          if (child.path) {
            items.push(
              <MenuItem 
                key={`${section.section}-${childIdx}`} 
                value={child.path}
                sx={{ 
                  pl: 2.5,
                  py: 0.5,
                  minHeight: 28,
                  fontSize: '0.8rem',
                  '&.Mui-selected': {
                    bgcolor: 'primary.dark',
                    '&:hover': { bgcolor: 'primary.dark' }
                  }
                }}
              >
                {child.title}
              </MenuItem>
            );
          } else if (child.children && hasFiles(child.children)) {
            // Nested subsection (like AI, Architecture under Technical)
            items.push(
              <ListSubheader 
                key={`subsection-${section.section}-${childIdx}`}
                sx={{ 
                  bgcolor: 'background.default',
                  color: 'text.secondary',
                  fontWeight: 600,
                  fontSize: '0.75rem',
                  lineHeight: '22px',
                  py: 0,
                  pl: 1.5,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.25,
                }}
              >
                <ChevronRight sx={{ fontSize: 12 }} />
                {child.title}
              </ListSubheader>
            );
            
            child.children.forEach((subChild, subChildIdx) => {
              if (subChild.path) {
                items.push(
                  <MenuItem 
                    key={`${section.section}-${childIdx}-${subChildIdx}`} 
                    value={subChild.path}
                    sx={{ 
                      pl: 4,
                      py: 0.5,
                      minHeight: 26,
                      fontSize: '0.78rem',
                      '&.Mui-selected': {
                        bgcolor: 'primary.dark',
                        '&:hover': { bgcolor: 'primary.dark' }
                      }
                    }}
                  >
                    {subChild.title}
                  </MenuItem>
                );
              }
            });
          }
        });
      }
    });
    
    return items;
  };

  // Get current doc title for display
  const getCurrentTitle = (): string => {
    if (!manifest) return 'Select Documentation';
    
    for (const section of manifest.docs) {
      if (section.path === currentPath) return section.title;
      if (section.children) {
        for (const child of section.children) {
          if (child.path === currentPath) return `${section.title.replace(/^[^\s]+\s/, '')} › ${child.title}`;
          if (child.children) {
            for (const subChild of child.children) {
              if (subChild.path === currentPath) {
                return `${child.title.replace(/^[^\s]+\s/, '')} › ${subChild.title}`;
              }
            }
          }
        }
      }
    }
    return 'Select Documentation';
  };

  // Only feed the Select a value that matches a rendered <MenuItem>; otherwise MUI logs
  // an "out-of-range value" warning (e.g. before the manifest loads, when there are no
  // items). Display still comes from getCurrentTitle(), so an empty value changes nothing.
  const menuItemPaths = new Set<string>();
  const collectPaths = (items?: DocItem[]) =>
    items?.forEach((it) => {
      if (it.path) menuItemPaths.add(it.path);
      if (it.children) collectPaths(it.children);
    });
  manifest.docs.forEach((s) => collectPaths(s.children));
  const selectValue = menuItemPaths.has(currentPath) ? currentPath : '';

  return (
    <Box sx={{ mb: 1.5, display: 'flex', alignItems: 'center', gap: 1.5 }}>
      <FormControl size="small" sx={{ minWidth: 280, maxWidth: 420 }}>
        <Select
          value={selectValue}
          onChange={handleChange}
          open={open}
          onOpen={() => setOpen(true)}
          onClose={() => setOpen(false)}
          displayEmpty
          renderValue={() => (
            <Typography 
              variant="caption" 
              sx={{ 
                fontWeight: 500,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                fontSize: '0.8rem',
              }}
            >
              {getCurrentTitle()}
            </Typography>
          )}
          MenuProps={{
            PaperProps: {
              sx: {
                maxHeight: 400,
                '& .MuiList-root': {
                  py: 0,
                }
              }
            }
          }}
          sx={{
            bgcolor: 'background.paper',
            height: 32,
            '& .MuiSelect-select': {
              py: 0.5,
              display: 'flex',
              alignItems: 'center',
            }
          }}
        >
          {renderMenuItems()}
        </Select>
      </FormControl>
    </Box>
  );
};

/**
 * Simple Documentation Viewer - Renders markdown files from /docs
 */
const Documentation: React.FC = () => {
  const { section = 'README', subsection, category, page = 'README' } = useParams<{ 
    section?: string; 
    subsection?: string; 
    category?: string;
    page?: string 
  }>();
  const [markdown, setMarkdown] = useState<string>('');
  const [error, setError] = useState<string>('');
  
  // Compute current path for navigator
  const getCurrentDocPath = (): string => {
    if (category && page !== 'README') {
      return `/docs/${section}/${subsection}/${category}/${page}`;
    } else if (category) {
      return `/docs/${section}/${subsection}/${category}`;
    } else if (subsection && page !== 'README') {
      return `/docs/${section}/${subsection}/${page}`;
    } else if (subsection) {
      return `/docs/${section}/${subsection}`;
    } else if (section !== 'README' && page === 'README') {
      return `/docs/${section}`;
    } else if (page !== 'README') {
      return `/docs/${section}/${page}`;
    }
    return `/docs/${section}`;
  };

  useEffect(() => {
    const fetchMarkdown = async () => {
      setError('');

      try {
        // Construct path to markdown file
        let mdPath: string;
        if (section === 'README' && !subsection && !category) {
          // Root docs home (/docs/README) — the file lives at docs/README.md,
          // not docs/README/README.md (there is no "README" section folder).
          mdPath = '/README.md';
        } else if (category && page !== 'README') {
          mdPath = `/${section}/${subsection}/${category}/${page}.md`;
        } else if (category) {
          mdPath = `/${section}/${subsection}/${category}/README.md`;
        } else if (subsection && page !== 'README') {
          mdPath = `/${section}/${subsection}/${page}.md`;
        } else if (subsection) {
          mdPath = `/${section}/${subsection}/README.md`;
        } else if (page === 'README') {
          mdPath = `/${section}/README.md`;
        } else {
          mdPath = `/${section}/${page}.md`;
        }
        
        const fullPath = `/docs${mdPath}`;
        const response = await fetch(fullPath);

        if (!response.ok) {
          throw new Error(`Documentation not found: ${fullPath}`);
        }

        const text = await response.text();
        const lower = text.trimStart().toLowerCase();
        if (lower.startsWith('<!doctype') || lower.startsWith('<html')) {
          throw new Error(`Invalid documentation response (received HTML instead of Markdown): ${fullPath}`);
        }
        setMarkdown(stripMetaSections(text, section));
      } catch (err) {
        console.error('Error loading documentation:', err);
        setError(err instanceof Error ? err.message : 'Failed to load documentation');
      }
    };

    fetchMarkdown();
  }, [section, subsection, category, page]);

  if (error) {
    return (
      <Box sx={{ p: 4 }}>
        <Box sx={{ p: 3, bgcolor: 'error.dark', borderRadius: 1, border: 1, borderColor: 'error.main' }}>
          <Typography variant="h6" color="error.light">
            Error Loading Documentation
          </Typography>
          <Typography variant="body2" sx={{ mt: 1, color: 'error.light' }}>
            {error}
          </Typography>
        </Box>
      </Box>
    );
  }

  return (
    <Box sx={{ pt: 0, px: 3, pb: 3, width: '100%', maxWidth: '1200px', mx: 'auto', minHeight: '80vh' }}>
      {/* Documentation Navigator */}
      <DocsNavigator currentPath={getCurrentDocPath()} />
      
      <Box 
        sx={{ 
          p: 3, 
          minHeight: '70vh', 
          width: '100%',
          backgroundColor: 'background.paper',
          borderRadius: 2,
          border: 1,
          borderColor: 'divider',
        }}
      >
        <Box sx={{ width: '100%', maxWidth: '900px', mx: 'auto' }}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeRaw]}
            // Allow inline base64 images (data:image/...); keep the default XSS guard for everything else.
            urlTransform={(url) => (url.startsWith('data:image/') ? url : defaultUrlTransform(url))}
            components={{
            // Style images
            img: ({ src, alt, loading }) => (
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
            h1: ({ children }) => (
              <Typography variant="h4" component="h1" gutterBottom sx={{ mt: 1.5, mb: 1.5, fontWeight: 600, fontSize: '1.75rem' }}>
                {children}
              </Typography>
            ),
            h2: ({ children }) => (
              <Typography variant="h5" component="h2" gutterBottom sx={{ mt: 2, mb: 1.5, fontWeight: 600, fontSize: '1.35rem' }}>
                {children}
              </Typography>
            ),
            h3: ({ children }) => (
              <Typography variant="h6" component="h3" gutterBottom sx={{ mt: 1.5, mb: 1, fontWeight: 600, fontSize: '1.1rem' }}>
                {children}
              </Typography>
            ),
            h4: ({ children }) => (
              <Typography variant="subtitle1" component="h4" gutterBottom sx={{ mt: 1.5, mb: 0.75, fontWeight: 600, fontSize: '1rem' }}>
                {children}
              </Typography>
            ),
            // Style paragraphs
            p: ({ children }) => (
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
            a: ({ children, href }) => {
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
            ul: ({ children }) => (
              <Box component="ul" sx={{ pl: 2.5, my: 1 }}>
                {children}
              </Box>
            ),
            ol: ({ children }) => (
              <Box component="ol" sx={{ pl: 2.5, my: 1 }}>
                {children}
              </Box>
            ),
            li: ({ children }) => (
              <Typography component="li" variant="body2" sx={{ mb: 0.25, lineHeight: 1.6, fontSize: '0.9rem' }}>
                {children}
              </Typography>
            ),
            // Style blockquotes
            blockquote: ({ children }) => (
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
            table: ({ children }) => (
              <Box sx={{ overflowX: 'auto', my: 1.5 }}>
                <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                  {children}
                </Box>
              </Box>
            ),
            th: ({ children }) => (
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
            td: ({ children }) => (
              <Box component="td" sx={{ border: 1, borderColor: 'divider', p: 1, fontSize: '0.85rem' }}>
                {children}
              </Box>
            ),
            // Style horizontal rules
            hr: () => <Box component="hr" sx={{ my: 2, border: 'none', borderTop: 1, borderColor: 'divider' }} />,
          }}
        >
          {markdown}
        </ReactMarkdown>
        </Box>
      </Box>
    </Box>
  );
};

export default Documentation;
