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
import { createDocsMarkdownComponents } from '../components/docs/markdownComponents';
import ReleaseNotesView from '../components/docs/ReleaseNotesView';

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
          {(section === 'release_note' || section === 'bugs') && !subsection && !category && page === 'README' ? (
            <ReleaseNotesView markdown={markdown} getCurrentDocPath={getCurrentDocPath} page={page} />
          ) : (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeRaw]}
            // Allow inline base64 images (data:image/...); keep the default XSS guard for everything else.
            urlTransform={(url) => (url.startsWith('data:image/') ? url : defaultUrlTransform(url))}
            components={createDocsMarkdownComponents(getCurrentDocPath, page)}
          >
            {markdown}
          </ReactMarkdown>
          )}
        </Box>
      </Box>
    </Box>
  );
};

export default Documentation;
