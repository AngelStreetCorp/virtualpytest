// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import { extractH2Headings, openAncestorDetails, parseDocsPageOptions, tocHeadingsFor } from './docsPageOptions';

describe('docs page opt-ins', () => {
  it('reads the markers from the leading comments only', () => {
    expect(parseDocsPageOptions('<!-- toc: h2 -->\n<!-- compact -->\n# T')).toEqual({ toc: true, tocOff: false, compact: true });
    expect(parseDocsPageOptions('# T\n\n<!-- toc: h2 -->')).toEqual({ toc: false, tocOff: false, compact: false });
    expect(parseDocsPageOptions('# T')).toEqual({ toc: false, tocOff: false, compact: false });
  });
  it('lists h2 headings with the renderer ids and skips code fences', () => {
    const md = '# T\n\n## 0 Prerequisites\n\n```\n## not a heading\n```\n\n## 1 `Backup`\n\n### sub';
    expect(extractH2Headings(md)).toEqual([
      { id: '0-prerequisites', label: '0 Prerequisites' },
      { id: '1-backup', label: '1 Backup' },
    ]);
  });
  it('shows the panel from 3 h2 headings, honours the opt-out and the old opt-in', () => {
    const three = '# T\n\n## A\n\n## B\n\n## C';
    expect(tocHeadingsFor(three, parseDocsPageOptions(three))).toHaveLength(3);
    const off = '<!-- toc: off -->\n' + three;
    expect(tocHeadingsFor(off, parseDocsPageOptions(off))).toEqual([]);
    const two = '# T\n\n## A\n\n## B';
    expect(tocHeadingsFor(two, parseDocsPageOptions(two))).toEqual([]);
    const forced = '<!-- toc: h2 -->\n' + two;
    expect(tocHeadingsFor(forced, parseDocsPageOptions(forced))).toHaveLength(2);
  });
  it('opens every details around an anchor', () => {
    document.body.innerHTML =
      '<details id="a"><summary>x</summary><details id="b"><summary><a id="t"></a>y</summary></details></details>';
    openAncestorDetails(document.getElementById('t') as Element);
    expect((document.getElementById('a') as HTMLDetailsElement).open).toBe(true);
    expect((document.getElementById('b') as HTMLDetailsElement).open).toBe(true);
  });
});
