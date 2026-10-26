/**
 * Monitoring → Localize monitoring: one page, two tabs.
 *   Matches  — what Localize decided on live frames (the match_runs log, was /match-runs)
 *   Coverage — how much of each UI tree Localize can name (was /monitoring/localize-coverage)
 * The tab lives in `?tab=`; each tab renders <LocalizeTabs/> at the right of its own page title.
 */
import React from 'react';

import { useLocalizeTab } from '../components/monitoring/LocalizeTabs';

import LocalizeCoverage from './LocalizeCoverage';
import MatchRuns from './MatchRuns';

const LocalizeMonitoring: React.FC = () => (useLocalizeTab() === 'coverage' ? <LocalizeCoverage /> : <MatchRuns />);

export default LocalizeMonitoring;
