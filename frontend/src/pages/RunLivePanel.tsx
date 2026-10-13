/**
 * /test-results/live/:taskId — the live panel for one task, with an offered (not automatic)
 * hand-off to the run summary once a durable result exists.
 */

import { Alert, Button, Typography } from '@mui/material';
import React, { useCallback, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { ReportPage } from '../components/reports/PageState';
import { RunLivePanel } from '../components/reports/RunLivePanel';
import { REPORT_ROUTES } from '../types/reports';

const RunLive: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [resultId, setResultId] = useState<string | null>(null);

  const handleCompleted = useCallback((scriptResultId: string | null) => setResultId(scriptResultId), []);

  return (
    <ReportPage>
      <Typography variant="h5" component="h1" sx={{ mb: 2 }}>
        Live run
      </Typography>
      {taskId ? (
        <RunLivePanel taskId={taskId} onCompleted={handleCompleted} />
      ) : (
        <Alert severity="info">No task selected.</Alert>
      )}
      {resultId && (
        <Button sx={{ mt: 2 }} variant="contained" onClick={() => navigate(REPORT_ROUTES.summary('script', resultId))}>
          View the recorded result
        </Button>
      )}
    </ReportPage>
  );
};

export default RunLive;
