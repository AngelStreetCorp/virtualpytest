import { Box, Button, Card, CardContent, Link as MuiLink, Stack, Typography } from '@mui/material';
import { OpenInNew as OpenInNewIcon } from '@mui/icons-material';
import React, { useState } from 'react';
import TestRailConnectionForm, { TestRailFormState } from '../components/integrations/TestRailConnectionForm';

const TestRailIntegration: React.FC = () => {
  const [state, setState] = useState<TestRailFormState | null>(null);
  return (
    <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 900, mx: 'auto' }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
        <Typography variant="h4">TestRail</Typography>
        {state?.projectUrl && (
          <Button component={MuiLink} href={state.projectUrl} target="_blank" rel="noopener noreferrer" endIcon={<OpenInNewIcon />}>
            Open TestRail
          </Button>
        )}
      </Stack>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Connect your TestRail project to publish VirtualPyTest results. Credentials are stored on the backend and never returned to this page.
      </Typography>
      <Card><CardContent>
        <TestRailConnectionForm onState={setState} />
      </CardContent></Card>
    </Box>
  );
};

export default TestRailIntegration;
