import { Box, FormControl, IconButton, InputLabel, MenuItem, Select, SelectChangeEvent, Tooltip, Typography } from '@mui/material';
import { OpenInNew } from '@mui/icons-material';
import React, { useMemo, useState } from 'react';

import { APP_CONFIG, SERVER_CONFIG } from '../config/constants';
import { useBranding } from '../contexts/BrandingContext';

interface ApiDoc {
  title: string;
  filename: string;
  category: 'SERVER';
}

const ApiDocumentation: React.FC = () => {
  const { branding } = useBranding();

  // Available API documentation
  const apiDocs: ApiDoc[] = [
    { title: 'SERVER - Device', filename: 'server-device-management', category: 'SERVER' },
    { title: 'SERVER - Campaign', filename: 'server-campaign-management', category: 'SERVER' },
    { title: 'SERVER - System', filename: 'server-core-system', category: 'SERVER' },
    { title: 'SERVER - Navigation', filename: 'server-navigation-management', category: 'SERVER' },
    { title: 'SERVER - Testcase', filename: 'server-testcase-management', category: 'SERVER' },
    { title: 'SERVER - Script', filename: 'server-script-management', category: 'SERVER' },
    { title: 'SERVER - Requirements', filename: 'server-requirements-management', category: 'SERVER' },
    { title: 'SERVER - AI Analysis', filename: 'server-ai-analysis', category: 'SERVER' },
    { title: 'SERVER - Metrics & Analytics', filename: 'server-metrics-analytics', category: 'SERVER' },
    { title: 'SERVER - Deployment & Scheduling', filename: 'server-deployment-scheduling', category: 'SERVER' },
    { title: 'SERVER - User Interface', filename: 'server-user-interface-management', category: 'SERVER' },
    { title: 'SERVER - Access & Workspace', filename: 'server-access-workspace', category: 'SERVER' },
    { title: 'SERVER - Results & Reporting', filename: 'server-results-reporting', category: 'SERVER' },
  ];

  // Default to an interactive spec so "Try it out" works immediately
  const [selectedDoc, setSelectedDoc] = useState<string>('server-core-system');
  const defaultServerUrl = useMemo(() => SERVER_CONFIG.DEFAULT_URL || window.location.origin, []);

  const handleDocChange = (event: SelectChangeEvent<string>) => {
    setSelectedDoc(event.target.value);
  };

  const selectedDocData = apiDocs.find(d => d.filename === selectedDoc);

  const getSpecUrl = () => `/docs/api/specs/${selectedDoc}.yaml`;
  const getInteractiveUrl = () =>
    `/docs/api/interactive.html?spec=${encodeURIComponent(getSpecUrl())}&server_url=${encodeURIComponent(defaultServerUrl)}&team_id=${encodeURIComponent(APP_CONFIG.DEFAULT_TEAM_ID)}`;
  const frameUrl = getInteractiveUrl();

  return (
    <Box
      sx={{
        height: 'calc(100dvh - 64px)',
        minHeight: 'calc(100dvh - 64px)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        bgcolor: 'background.default'
      }}
    >
      {/* Doc Selector - Sticky Header */}
      <Box sx={{ 
        position: 'sticky',
        top: 0,
        zIndex: 1100,
        bgcolor: 'background.paper',
        p: 1.5, 
        borderBottom: '1px solid #334155', 
        display: 'grid', 
        gridTemplateColumns: '1fr auto 1fr', 
        alignItems: 'center', 
        gap: 2,
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
      }}>
        <Box sx={{ display: 'flex', justifyContent: 'flex-start' }}>
          <FormControl size="small" sx={{ minWidth: 240 }}>
            <InputLabel id="doc-select-label">Select API</InputLabel>
            <Select
              labelId="doc-select-label"
              id="doc-select"
              value={selectedDoc}
              label="Select API"
              onChange={handleDocChange}
              MenuProps={{
                PaperProps: {
                  sx: { fontSize: '13px' }
                }
              }}
            >
              {apiDocs.map((doc) => (
                <MenuItem key={doc.filename} value={doc.filename}>
                  {doc.title}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>
        
        <Typography variant="h6" sx={{ fontWeight: 600, color: 'text.primary', display: 'flex', alignItems: 'center', gap: 1, whiteSpace: 'nowrap' }}>
          🚀 {branding.name} API Documentation
        </Typography>
        
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 0.5 }}>
          <Tooltip title="Open in new tab">
            <IconButton
              onClick={() => window.open(frameUrl, '_blank')}
              color="primary"
              size="small"
            >
              <OpenInNew />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>

      {/* Documentation iframe */}
      <Box sx={{ flex: 1, minHeight: 0, overflow: 'hidden', bgcolor: 'background.default' }}>
        {selectedDocData && (
          <iframe
            key={selectedDoc} // Force reload on doc change
            src={frameUrl}
            width="100%"
            height="100%"
            frameBorder="0"
            title={selectedDocData.title}
            style={{
              border: 'none',
              display: 'block',
              minHeight: '100%',
              overflow: 'hidden'
            }}
          />
        )}
      </Box>
    </Box>
  );
};

export default ApiDocumentation;
