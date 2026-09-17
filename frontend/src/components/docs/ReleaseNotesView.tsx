import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Box,
  Collapse,
  Typography,
} from '@mui/material';
import { ExpandMore } from '@mui/icons-material';
import React, { useMemo, useState } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { createDocsMarkdownComponents, createInlineDocsMarkdownComponents } from './markdownComponents';

interface Subsection {
  heading: string;
  body: string;
}

interface BuildSection {
  title: string;
  subsections: Subsection[];
}

const urlTransform = (url: string) => (url.startsWith('data:image/') ? url : defaultUrlTransform(url));

/** Splits the release notes into the intro (before the first `## `) and one entry per build. */
const parseReleaseNotes = (md: string): { intro: string; sections: BuildSection[] } => {
  const intro: string[] = [];
  const sections: BuildSection[] = [];
  let current: BuildSection | null = null;
  let currentSub: Subsection | null = null;

  const closeSub = () => {
    if (current && currentSub) current.subsections.push(currentSub);
    currentSub = null;
  };
  const closeSection = () => {
    closeSub();
    if (current) sections.push(current);
    current = null;
  };

  for (const line of md.split('\n')) {
    const h2 = line.match(/^##\s+(.*)$/);
    const h3 = line.match(/^###\s+(.*)$/);
    if (h2) {
      closeSection();
      current = { title: h2[1].trim(), subsections: [] };
      continue;
    }
    if (h3) {
      closeSub();
      if (current) currentSub = { heading: h3[1].trim(), body: '' };
      continue;
    }
    if (line.trim() === '---') continue; // section divider, not content
    if (!current) {
      intro.push(line);
    } else if (current) {
      // A section with no `###` of its own (the bug tracker groups bugs straight under the build
      // heading) collects into one unnamed subsection, so both pages take the same path.
      if (!currentSub) currentSub = { heading: '', body: '' };
      currentSub.body += line + '\n';
    }
  }
  closeSection();

  return { intro: intro.join('\n').trim(), sections };
};

/** Pulls top-level `- ` list items out of a subsection body, joining wrapped continuation lines. */
const extractBullets = (body: string): string[] => {
  const bullets: string[] = [];
  let current: string[] | null = null;

  for (const raw of body.split('\n')) {
    const m = raw.match(/^- (.*)$/);
    if (m) {
      if (current) bullets.push(current.join(' ').trim());
      current = [m[1]];
    } else if (raw.trim() !== '') {
      if (current) current.push(raw.trim());
    } else if (current) {
      bullets.push(current.join(' ').trim());
      current = null;
    }
  }
  if (current) bullets.push(current.join(' ').trim());

  return bullets.filter(Boolean);
};

/**
 * A bullet is `- **Title** — body · [BUG-nnnn](…) · `sha` · TASK-nn · 🗄 DB migration `x.sql``.
 * The title is the one-line summary the collapsed row wants; the trailing metadata belongs on
 * that row too, not repeated at the end of the body you opened to read it. Same rule as the
 * customer delivery note (scripts/release/delivery_note.sh), so a fix reads identically in
 * both places — found by its bug number without expanding anything.
 */
interface ParsedBullet {
  bug?: string;
  commit?: string;
  task?: string;
  migration: boolean;
  summary: string;
  details: string;
}

/**
 * Splits raw markdown at the first sentence-ending period outside a `[...]`/`(...)` link or a
 * `` `code` `` span, so a preview never cuts a link or inline code in half. Used only for
 * bullets with no bold title.
 */
const splitAtFirstSentence = (text: string): { summary: string; details: string } => {
  let depth = 0;
  let inCode = false;
  for (let i = 0; i < text.length - 1; i++) {
    const ch = text[i];
    if (ch === '`') {
      inCode = !inCode;
      continue;
    }
    if (inCode) continue;
    if (ch === '[' || ch === '(') depth++;
    else if (ch === ']' || ch === ')') depth = Math.max(0, depth - 1);
    else if (depth === 0 && ch === '.' && text[i + 1] === ' ') {
      return { summary: text.slice(0, i + 1), details: text.slice(i + 1).trim() };
    }
  }
  return { summary: text, details: '' };
};

const parseBullet = (text: string): ParsedBullet => {
  const titled = text.match(/^\*\*(.+?)\*\*\s*[—-]?\s*([\s\S]*)$/);
  const title = titled ? titled[1].trim() : '';
  const rest = titled ? titled[2] : text;

  // Metadata is matched as a whole " · " segment, so a backticked PATH is never read as a commit.
  let bug: string | undefined;
  let commit: string | undefined;
  let task: string | undefined;
  const kept: string[] = [];
  for (const seg of rest.split(' · ')) {
    const t = seg.trim();
    const b = t.match(/^\[(BUG-\d+)\]\([^)]*\)$/);
    if (b) {
      bug = bug ?? b[1];
      continue;
    }
    if (/^`[0-9a-f]{7,40}`$/.test(t) || t === '`this commit`') {
      // "this commit" means the release commit itself — no information here.
      if (t !== '`this commit`') commit = commit ?? t.replace(/`/g, '');
      continue;
    }
    const k = t.match(/^(TASK-\d+)$/);
    if (k) {
      task = task ?? k[1];
      continue;
    }
    kept.push(seg);
  }
  const body = kept.join(' · ').trim();
  const migration = /DB migration/.test(body);

  if (title) return { bug, commit, task, migration, summary: title, details: body };
  const fallback = splitAtFirstSentence(body);
  return { bug, commit, task, migration, ...fallback };
};

/** A new optional feature is a new folder on every host, not one more line in a list of twenty. */
const NewFeatureBadge: React.FC<{ name: string }> = ({ name }) => (
  <Box
    component="span"
    sx={{
      ml: 0.75,
      px: 0.7,
      py: 0.1,
      borderRadius: 0.75,
      border: 1,
      borderColor: 'primary.main',
      color: 'primary.main',
      fontSize: '0.68rem',
      fontWeight: 700,
      whiteSpace: 'nowrap',
      verticalAlign: 'middle',
    }}
  >
    🧩 new feature · {name}
  </Box>
);

const Badge: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Box
    component="span"
    sx={{
      ml: 0.75,
      px: 0.6,
      py: 0.05,
      borderRadius: 0.75,
      border: 1,
      borderColor: 'divider',
      color: 'text.secondary',
      fontSize: '0.68rem',
      fontWeight: 600,
      whiteSpace: 'nowrap',
      verticalAlign: 'middle',
    }}
  >
    {children}
  </Box>
);

const CollapsibleBullet: React.FC<{ text: string; components: Record<string, any> }> = ({ text, components }) => {
  const [expanded, setExpanded] = useState(false);
  const { bug, commit, task, migration, summary, details } = parseBullet(text);
  const newFeature = summary.match(/^New optional feature `([^`]+)`\s*[—-]\s*(.*)$/);

  // The whole row is the control. A "show details" link after every entry repeated the same two
  // words down the page in link blue, and on a summary that filled the line it wrapped onto one
  // of its own — eighteen times in one section. A chevron says the same thing once.
  const toggle = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('a')) return; // a link in the summary still navigates
    setExpanded((v) => !v);
  };

  return (
    <Typography component="li" variant="body2" sx={{ mb: 0.5, lineHeight: 1.6, fontSize: '0.9rem' }}>
      <Box
        component="span"
        onClick={details ? toggle : undefined}
        onKeyDown={
          details
            ? (e: React.KeyboardEvent) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setExpanded((v) => !v);
                }
              }
            : undefined
        }
        role={details ? 'button' : undefined}
        tabIndex={details ? 0 : undefined}
        aria-expanded={details ? expanded : undefined}
        sx={{
          cursor: details ? 'pointer' : 'default',
          '& .rn-chevron': { opacity: 0.45, transition: 'opacity .15s, transform .15s' },
          '&:hover .rn-chevron': { opacity: 1 },
          '&:focus-visible': { outline: '1px solid', outlineColor: 'primary.main', outlineOffset: 2, borderRadius: 0.5 },
        }}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} urlTransform={urlTransform} components={components}>
          {newFeature
            ? newFeature[2].charAt(0).toUpperCase() + newFeature[2].slice(1) // the title led with the feature name
            : bug
              ? `**${bug}** — ${summary}`
              : summary}
        </ReactMarkdown>
        {newFeature && <NewFeatureBadge name={newFeature[1]} />}
        {commit && <Badge>{commit}</Badge>}
        {task && <Badge>{task}</Badge>}
        {migration && <Badge>🗄 migration</Badge>}
        {details && (
          <ExpandMore
            className="rn-chevron"
            sx={{
              fontSize: 16,
              ml: 0.4,
              verticalAlign: 'text-bottom',
              transform: expanded ? 'rotate(180deg)' : 'none',
            }}
          />
        )}
      </Box>
      {details && (
        <Collapse in={expanded}>
          <Box sx={{ mt: 0.25 }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} urlTransform={urlTransform} components={components}>
              {details}
            </ReactMarkdown>
          </Box>
        </Collapse>
      )}
    </Typography>
  );
};

const isListSubsection = (heading: string, body = '') =>
  /features|bug fixes|security/i.test(heading) || (!heading && /^\s*-\s/m.test(body));

const countBullets = (body: string) => extractBullets(body).length;

/**
 * Release notes get their own layout: one collapsible section per build (newest 2 open by
 * default) and, within Features/Bug fixes/Security, one collapsible bullet per entry (first
 * sentence shown, full write-up on click) — otherwise the changelog is an unreadable wall of text.
 */
const ReleaseNotesView: React.FC<{ markdown: string; getCurrentDocPath: () => string; page?: string }> = ({
  markdown,
  getCurrentDocPath,
  page,
}) => {
  const { intro, sections } = useMemo(() => parseReleaseNotes(markdown), [markdown]);
  const blockComponents = useMemo(() => createDocsMarkdownComponents(getCurrentDocPath, page), [getCurrentDocPath, page]);
  const inlineComponents = useMemo(() => createInlineDocsMarkdownComponents(getCurrentDocPath, page), [getCurrentDocPath, page]);
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set([0]));

  const toggleSection = (idx: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <Box>
      {intro && (
        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} urlTransform={urlTransform} components={blockComponents}>
          {intro}
        </ReactMarkdown>
      )}

      {sections.map((section, idx) => (
        <Accordion
          key={section.title}
          expanded={expanded.has(idx)}
          onChange={() => toggleSection(idx)}
          disableGutters
          elevation={0}
          square
          sx={{
            background: 'transparent',
            '&:before': { display: 'none' },
            borderBottom: 1,
            borderColor: 'divider',
            '&:last-of-type': { borderBottom: 0 },
          }}
        >
          <AccordionSummary expandIcon={<ExpandMore />} sx={{ px: 0 }}>
            <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1.5, flexWrap: 'wrap' }}>
              <Typography variant="h5" component="h2" sx={{ fontWeight: 600, fontSize: '1.35rem' }}>
                {section.title}
              </Typography>
              {/* How much is in this build, without opening it. */}
              <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.78rem' }}>
                {section.subsections
                  .filter((sub) => isListSubsection(sub.heading, sub.body))
                  .map((sub) => {
                    const label = sub.heading.replace(/[A-Za-z ]+/g, '').trim() || sub.heading;
                    return label ? `${countBullets(sub.body)} ${label}` : `${countBullets(sub.body)}`;
                  })
                  .join(' · ')}
              </Typography>
            </Box>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 0, pt: 0, pb: 2 }}>
            {section.subsections.map((sub, subIdx) => (
              <Box key={subIdx} sx={{ mb: 2 }}>
                {sub.heading && (
                <Typography variant="h6" component="h3" sx={{ fontWeight: 600, fontSize: '1.1rem', mb: 1 }}>
                  {sub.heading}
                  {isListSubsection(sub.heading, sub.body) && (
                    <Box component="span" sx={{ ml: 1, color: 'text.secondary', fontWeight: 500, fontSize: '0.95rem' }}>
                      ({countBullets(sub.body)})
                    </Box>
                  )}
                </Typography>
                )}
                {isListSubsection(sub.heading, sub.body) ? (
                  <Box component="ul" sx={{ pl: 2.5, my: 1 }}>
                    {extractBullets(sub.body).map((bullet, bIdx) => (
                      <CollapsibleBullet key={bIdx} text={bullet} components={inlineComponents} />
                    ))}
                  </Box>
                ) : (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeRaw]}
                    urlTransform={urlTransform}
                    components={blockComponents}
                  >
                    {sub.body}
                  </ReactMarkdown>
                )}
              </Box>
            ))}
          </AccordionDetails>
        </Accordion>
      ))}
    </Box>
  );
};

export default ReleaseNotesView;
