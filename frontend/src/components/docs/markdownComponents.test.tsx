/**
 * BUG-0538: deep links (#step-3, #some-heading) need the ids to reach the DOM.
 * The `a` renderer used to drop id on href-less raw-HTML anchors and headings had no ids.
 */
import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { createDocsMarkdownComponents, hasTechnicalBlock, slugifyHeading } from './markdownComponents';

const render = (md: string) =>
  renderToStaticMarkup(
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={createDocsMarkdownComponents(() => '/docs/x/y')}>
      {md}
    </ReactMarkdown>,
  );

describe('docs markdown anchors', () => {
  it('keeps the id of a raw <a id> anchor', () => {
    expect(render('<a id="step-3"></a>\n\n## Step 3')).toContain('id="step-3"');
  });
  it('keeps the name of a raw <a name> anchor', () => {
    expect(render('<a name="old"></a>\n\ntext')).toContain('id="old"');
  });
  it('gives headings GitHub-style slug ids', () => {
    const html = render('## Some Heading, v2!\n\n### `Code` bit');
    expect(html).toContain('id="some-heading-v2"');
    expect(html).toContain('id="code-bit"');
  });
  it('still renders real links as links', () => {
    expect(render('[x](https://a.b)')).toContain('href="https://a.b"');
  });
  it('slugifies', () => expect(slugifyHeading('Step 3: Backup')).toBe('step-3-backup'));
});

describe('docs <details> blocks', () => {
  const md = '<details>\n<summary><a id="frontend-ssh"></a>Server to frontend VM</summary>\n\nBody with `code` and **bold**.\n\n</details>';
  it('renders details and summary with markdown inside and keeps the anchor id inside the summary', () => {
    const html = render(md);
    expect(html).toContain('<details');
    expect(html).toContain('<summary');
    expect(html).toMatch(/<summary[^>]*><span id="frontend-ssh">/);
    expect(html).toContain('<strong>bold</strong>');
  });
});

describe('docs technical blocks', () => {
  const md = 'Plain words.\n\n<div data-technical>\n\nRun `adb devices`.\n\n</div>\n\n<div class="x">other</div>';
  const renderT = (show: boolean) =>
    renderToStaticMarkup(
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={createDocsMarkdownComponents(() => '/docs/x/y', undefined, undefined, false, 1, show)}>
        {md}
      </ReactMarkdown>,
    );
  it('hides the technical block when the switch is off', () => {
    const html = renderT(false);
    expect(html).not.toContain('adb devices');
    expect(html).toContain('Plain words.');
    expect(html).toContain('other');
  });
  it('shows it, marked, when the switch is on', () => {
    const html = renderT(true);
    expect(html).toContain('adb devices');
    expect(html).toContain('Technical');
  });
  it('detects pages with a technical block', () => {
    expect(hasTechnicalBlock(md)).toBe(true);
    expect(hasTechnicalBlock('no blocks')).toBe(false);
  });
});
