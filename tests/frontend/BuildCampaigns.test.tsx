import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../frontend/src/hooks/useResponsiveMode', () => ({
  useResponsiveMode: () => ({
    mode: 'desktop',
    isMobile: false,
    isTablet: false,
    isDesktop: true,
    theme: {},
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useCampaign', () => ({
  useCampaign: () => ({
    campaignConfig: {
      name: '',
      description: '',
      execution_config: { continue_on_failure: true, timeout_minutes: 120, parallel: false },
      script_configurations: [],
    },
    updateCampaignConfig: () => {},
    resetCampaignConfig: () => {},
    aiTestCasesInfo: [],
    addScript: () => {},
    removeScript: () => {},
    reorderScripts: () => {},
    updateScriptConfiguration: () => {},
    scriptAnalysisCache: {},
    loadScriptAnalysis: async () => null,
    error: null,
  }),
}));

vi.mock('../../frontend/src/hooks/useToast', () => ({
  useToast: () => ({
    showSuccess: () => {},
    showError: () => {},
    showWarning: () => {},
    showInfo: () => {},
  }),
}));

vi.mock('../../frontend/src/utils/executionListCache', () => ({
  getCachedCampaignExecutableList: async () => ({ executables: [] }),
  getCachedExecutableList: async () => ({ success: true, folders: [] }),
  invalidateCampaignExecutableListCache: () => {},
  invalidateExecutableListCache: () => {},
}));

vi.mock('../../frontend/src/components/campaigns/ScriptSequenceBuilder', () => ({
  ScriptSequenceBuilder: () => <div data-testid="script-sequence-builder" />,
}));

vi.mock('../../frontend/src/components/common/UnifiedExecutableSelector', () => ({
  UnifiedExecutableSelector: () => <div data-testid="unified-executable-selector" />,
}));

vi.mock('../../frontend/src/components/common/VersionHistoryDialog', () => ({
  VersionHistoryDialog: () => null,
}));

vi.mock('../../frontend/src/components/common/ExecutableTypeToggle', () => ({
  ExecutableTypeToggle: () => <div data-testid="executable-type-toggle" />,
}));

import BuildCampaigns from '../../frontend/src/pages/BuildCampaigns';

describe('BuildCampaigns page', () => {
  it('renders the Build Campaign heading', async () => {
    render(<BuildCampaigns />);

    expect(await screen.findByRole('heading', { name: 'Build Campaign' })).toBeInTheDocument();
    expect(screen.getByTestId('script-sequence-builder')).toBeInTheDocument();
  });
});
