import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { AGENT_CHAT_PALETTE_LIGHT } from '../../constants/agentChatTheme';

/**
 * Doc links in the repo are relative `.md` paths; in a PDF they must be absolute app URLs or
 * they point nowhere. Only README pages use this (`/docs/release_note` is `release_note/README.md`),
 * so links resolve against the route as a folder — `../bugs/X.md` → `/docs/bugs/X`.
 */
const toAbsoluteUrl = (url: string): string => {
  if (url.startsWith('data:image/')) return url;
  const safe = defaultUrlTransform(url);
  if (!safe || /^(https?:|mailto:|#)/.test(safe)) return safe;
  const cleaned = safe.replace(/\/README\.md$/i, '').replace(/\.md$/i, '');
  try {
    return new URL(cleaned, window.location.origin + window.location.pathname.replace(/\/?$/, '/')).href;
  } catch {
    return safe;
  }
};

// Print stylesheet for a PDF on white paper. Palette colors are interpolated from the light
// theme (gold accent for links, hoverBg for code blocks) so the printed page agrees with the
// in-app gold palette rather than rendering browser-blue.
const PRINT_CSS = `
  @page { size: A4; margin: 16mm 14mm; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #111;
         background: #fff; font-size: 10.5pt; line-height: 1.5; margin: 0; }
  h1 { font-size: 20pt; margin: 0 0 6pt; }
  h2 { font-size: 15pt; margin: 18pt 0 6pt; padding-bottom: 3pt; border-bottom: 1px solid #ccc;
       break-after: avoid; }
  h3 { font-size: 12pt; margin: 12pt 0 4pt; break-after: avoid; }
  ul, ol { padding-left: 16pt; margin: 4pt 0; }
  li { margin: 2pt 0; break-inside: avoid; }
  p { margin: 4pt 0; }
  a { color: ${AGENT_CHAT_PALETTE_LIGHT.accentText}; text-decoration: none; }
  code { font-family: Consolas, 'Courier New', monospace; font-size: 9pt; background: #f2f2f2;
         padding: 0 3pt; border-radius: 3pt; }
  pre { background: ${AGENT_CHAT_PALETTE_LIGHT.hoverBg}; padding: 6pt; border-radius: 4pt; white-space: pre-wrap;
        break-inside: avoid; }
  pre code { background: none; padding: 0; }
  table { border-collapse: collapse; margin: 6pt 0; }
  th, td { border: 1px solid #ccc; padding: 3pt 6pt; text-align: left; }
  hr { border: 0; border-top: 1px solid #ddd; margin: 10pt 0; }
  img { max-width: 100%; }
`;

/**
 * Prints the whole markdown document — every section and entry expanded, light theme — from a
 * hidden iframe, so the browser's print dialog offers "Save as PDF" without the app chrome.
 * `title` becomes the default PDF file name.
 */
export const exportMarkdownPdf = (markdown: string, title: string): void => {
  const body = renderToStaticMarkup(
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} urlTransform={toAbsoluteUrl}>
      {markdown}
    </ReactMarkdown>,
  );

  const iframe = document.createElement('iframe');
  iframe.setAttribute('aria-hidden', 'true');
  Object.assign(iframe.style, { position: 'fixed', right: '0', bottom: '0', width: '0', height: '0', border: '0' });
  document.body.appendChild(iframe);

  const doc = iframe.contentDocument;
  const win = iframe.contentWindow;
  if (!doc || !win) {
    iframe.remove();
    return;
  }
  doc.open();
  doc.write(`<!doctype html><html><head><meta charset="utf-8"><title>${title.replace(/</g, '&lt;')}</title>` +
    `<style>${PRINT_CSS}</style></head><body>${body}</body></html>`);
  doc.close();

  const cleanup = () => setTimeout(() => iframe.remove(), 1000);
  win.addEventListener('afterprint', cleanup, { once: true });
  // Let images (inline base64 screenshots) lay out before the dialog snapshots the page.
  setTimeout(() => {
    win.focus();
    win.print();
  }, 250);
};
