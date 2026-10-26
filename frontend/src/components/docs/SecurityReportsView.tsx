import { Alert, Box, CircularProgress, IconButton, Tooltip, Typography } from '@mui/material';
import { OpenInNew, Refresh } from '@mui/icons-material';
import React, { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../../utils/apiClient';
import { buildPrimaryServerUrl } from '../../utils/buildUrlUtils';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

// The dashboard's own "JSON ↗" quick-links point at relative file paths that only existed when
// this report was served as a static file (public/docs/security/*.json). Now that it's fetched
// through an authenticated API call and rendered via srcDoc, those relative links have nothing to
// resolve against — neutralize them rather than ship dead links. The raw JSON is still reachable
// (authenticated) at GET /server/security/reports/<name>.
const neutralizeJsonLinks = (html: string): string =>
  html.replace(
    /<a class="json-link" href="[\w-]+\.json" target="_blank"[^>]*>JSON ↗<\/a>/g,
    '<span class="json-link" style="opacity:0.4" title="Raw JSON: GET /server/security/reports/&lt;name&gt; (authenticated)">JSON</span>'
  );

// The report HTML is generated with its own dark look; restyle it with the app palette so it
// follows the theme (class names from scripts/parse-security-to-html.py).
const paletteCss = (P: ReturnType<typeof useAgentChatPalette>): string => `<style>
  body { background: ${P.surface}; color: ${P.textPrimary}; }
  .header h1 { color: ${P.textPrimary}; }
  .timestamp, .metric-label, .summary-info, .section-arrow, .issue-loc, .no-issues { color: ${P.textMuted}; }
  .summary, .section { background: ${P.background}; border-color: ${P.borderColor}; }
  .section-header:hover, .json-link:hover, .filter-btn.active { background: ${P.hoverBg}; }
  .section-title, .issue-id { color: ${P.textSecondary}; }
  .issue-text, .section-counts .ignored { color: ${P.textSecondary}; }
  .filter-btn { border-color: ${P.borderColor}; color: ${P.textSecondary}; }
  .filter-btn:hover, .filter-btn.active { border-color: ${P.textMuted}; color: ${P.textPrimary}; }
  .issues { border-top-color: ${P.borderColor}; }
  .issue { border-left-color: ${P.borderColor}; }
  .issue:nth-child(odd) { background: ${P.hoverBg}; }
  .json-link { color: ${P.accentText}; }
  .high, .filter-btn.active.high { color: ${P.error}; }
  .medium, .filter-btn.active.medium { color: ${P.warning}; }
  .low, .issue-fix, .filter-btn.active.low { color: ${P.success}; }
  .filter-btn.active.high { border-color: ${P.error}; }
  .filter-btn.active.medium { border-color: ${P.warning}; }
  .filter-btn.active.low { border-color: ${P.success}; }
  .issue.high { border-left-color: ${P.error}; }
  .issue.medium { border-left-color: ${P.warning}; }
  .issue.low { border-left-color: ${P.success}; }
  .issues::-webkit-scrollbar-track { background: ${P.background}; }
  .issues::-webkit-scrollbar-thumb { background: ${P.borderColor}; }
</style>`;

const SecurityReportsView: React.FC = () => {
  const P = useAgentChatPalette();
  const [html, setHtml] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await apiClient(buildPrimaryServerUrl('/server/security/dashboard'));
      if (response.status === 403) {
        setError('Security reports are admin-only.');
        return;
      }
      if (response.status === 404) {
        setError('Security dashboard has not been generated yet (run scripts/generate-security-docs.sh).');
        return;
      }
      if (!response.ok) {
        setError(`Failed to load security dashboard (HTTP ${response.status}).`);
        return;
      }
      setHtml(neutralizeJsonLinks(await response.text()));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load security dashboard.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openInNewTab = () => {
    if (!html) return;
    const blobUrl = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
    window.open(blobUrl, '_blank');
    // Give the new tab time to load the blob before revoking it.
    setTimeout(() => URL.revokeObjectURL(blobUrl), 30_000);
  };

  return (
    <Box sx={{ height: 'max(560px, calc(100dvh - 190px))', display: 'flex', flexDirection: 'column' }}>
      {/* The page title lives in the docs header bar; this row only carries the view's actions. */}
      <Box sx={{ pb: 1, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="body2" color="textSecondary">
            Bandit + Safety + npm audit
          </Typography>
          <Tooltip title="Refresh report">
            <IconButton onClick={() => void load()} color="primary" size="medium">
              <Refresh />
            </IconButton>
          </Tooltip>
          <Tooltip title="Open in new tab">
            <IconButton onClick={openInNewTab} color="primary" size="medium" disabled={!html}>
              <OpenInNew />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>

      {/* Security Report */}
      <Box sx={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
            <CircularProgress />
          </Box>
        )}
        {!loading && error && (
          <Box sx={{ p: 3 }}>
            <Alert severity="warning">{error}</Alert>
          </Box>
        )}
        {!loading && !error && (
          <iframe
            srcDoc={html.replace('</head>', `${paletteCss(P)}</head>`)}
            width="100%"
            height="100%"
            frameBorder="0"
            title="Security Reports"
            style={{
              border: 'none',
              display: 'block',
            }}
          />
        )}
      </Box>
    </Box>
  );
};

export default SecurityReportsView;
