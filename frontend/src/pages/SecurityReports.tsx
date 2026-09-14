import { Alert, Box, CircularProgress, IconButton, Tooltip, Typography } from '@mui/material';
import { OpenInNew, Refresh, Security } from '@mui/icons-material';
import React, { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../utils/apiClient';
import { buildPrimaryServerUrl } from '../utils/buildUrlUtils';

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

const SecurityReports: React.FC = () => {
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
    <Box sx={{ height: '80vh', display: 'flex', flexDirection: 'column' }}>
      {/* Header with actions */}
      <Box sx={{ p: 2, borderBottom: '1px solid #e0e0e0', display: 'flex', alignItems: 'center', gap: 2 }}>
        <Security color="primary" sx={{ fontSize: 28 }} />
        <Typography variant="h6" sx={{ flexGrow: 1 }}>
          Security Reports
        </Typography>

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
            srcDoc={html}
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

export default SecurityReports;
