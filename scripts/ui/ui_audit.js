// In-page colour audit for the VirtualPyTest UI (TASK-56). Evaluated by ui_shots.cjs with AUDIT=1.
// Lists every visible element whose computed colour / background / border / SVG fill is off-palette:
// Tailwind / MUI blues, slate and navy, MUI greys, MUI pink/purple; plus white borders in dark mode
// and #d4a574 gold used as text in light mode (use accentText). '?#1e1e1e' = dark sidebarBg (fine).
// Returns { "<kind>#<hex>": { n, ex: [up to 4 "tag.class prop \"text\""] } }.
(() => {
  const hex = {
    '3b82f6':'blue','2196f3':'blue','1976d2':'blue','1565c0':'blue','2563eb':'blue','60a5fa':'blue','0288d1':'muiInfo','29b6f6':'muiInfoD','42a5f5':'blue','90caf9':'blue','03a9f4':'blue','4fc3f7':'blue','1d4ed8':'blue','93c5fd':'blue','bfdbfe':'blue','dbeafe':'blue','eff6ff':'blue','e3f2fd':'blue','bbdefb':'blue','64b5f6':'blue','0ea5e9':'blue','38bdf8':'blue',
    '1e293b':'slate','0f172a':'slate','111827':'slate','1f2937':'slate','334155':'slate','374151':'slate','64748b':'slate','94a3b8':'slate','cbd5e1':'slate','e2e8f0':'slate','f1f5f9':'slate','f8f9fa':'slate','475569':'slate','6b7280':'slate','9ca3af':'slate','d1d5db':'slate','e5e7eb':'slate','f3f4f6':'slate','f9fafb':'slate','4b5563':'slate',
    'fafafa':'grey','f5f5f5':'grey','e0e0e0':'grey','eeeeee':'grey','bdbdbd':'grey','9e9e9e':'grey','757575':'grey','616161':'grey','424242':'grey','212121':'grey','303030':'grey','121212':'grey','1e1e1e':'?',
    'dc004e':'pink','f48fb1':'pink','9c27b0':'purple','ce93d8':'purple',
  };
  const light = localStorage.getItem('theme-mode') === 'light';
  const toHex = (c) => { const m = c.match(/rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)/); if (!m) return null; if (m[4] !== undefined && +m[4] === 0) return null; return [m[1],m[2],m[3]].map(x => (+x).toString(16).padStart(2,'0')).join(''); };
  const out = {}; const add = (k, el, prop) => { out[k] = out[k] || { n: 0, ex: [] }; out[k].n++; if (out[k].ex.length < 4) { const t = (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 25).replace(/\s+/g,' '); out[k].ex.push(`${el.tagName.toLowerCase()}.${String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className).split(' ').filter(c=>!c.startsWith('css-')).slice(0,2).join('.')} ${prop} "${t}"`); } };
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect(); if (r.width === 0 || r.height === 0) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden') continue;
    const props = [['color', cs.color], ['bg', cs.backgroundColor]];
    if (parseFloat(cs.borderTopWidth) > 0) props.push(['border', cs.borderTopColor]);
    if (parseFloat(cs.borderLeftWidth) > 0) props.push(['borderL', cs.borderLeftColor]);
    if (el instanceof SVGElement && cs.fill) props.push(['fill', cs.fill]);
    for (const [p, v] of props) { const h = toHex(v); if (!h) continue;
      if (hex[h]) add(`${hex[h]}#${h}`, el, p);
      if (light && p === 'color' && h === 'd4a574' && (el.innerText||'').trim()) add('goldTextOnLight#d4a574', el, p);
      if (!light && p.startsWith('border') && (h === 'ffffff' || h === 'e0e0e0')) add('whiteBorderDark#' + h, el, p);
    }
  }
  return out;
})()
