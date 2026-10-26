/**
 * /test-results/live/:taskId — the live page for one task, with an offered (not automatic)
 * hand-off to the run summary once a durable result exists.
 */

import { Alert, Box, Button } from '@mui/material';
import React, { useCallback, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { PageTitle, pageSurfaceSx, primaryButtonSx } from '../components/common/PageChrome';
import { ReportPage } from '../components/reports/PageState';
import { RunLivePanel } from '../components/reports/RunLivePanel';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { useI18n } from '../i18n/useI18n';
import { REPORT_ROUTES } from '../types/reports';

const RunLive: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [resultId, setResultId] = useState<string | null>(null);

  const handleCompleted = useCallback((scriptResultId: string | null) => setResultId(scriptResultId), []);

  return (
    <ReportPage>
      <Box sx={pageSurfaceSx(P)}>
        <PageTitle title={t('Live run')} />
        {taskId ? (
          <RunLivePanel taskId={taskId} onCompleted={handleCompleted} />
        ) : (
          <Alert severity="info">{t('No task selected.')}</Alert>
        )}
        {resultId && (
          <Button sx={{ mt: 2, ...(primaryButtonSx(P) as object) }} variant="contained" onClick={() => navigate(REPORT_ROUTES.summary('script', resultId))}>
            {t('View the recorded result')}
          </Button>
        )}
      </Box>
    </ReportPage>
  );
};

export default RunLive;
