import type { CampaignConfig } from '../pages/Campaign_Types';

/**
 * Full launch-time config for a one-click rerun.
 *
 * Two pages produce it from different sources:
 *  - RunTests builds it in memory at launch and mirrors it to the
 *    `deployments.rerun_payload` jsonb column, so its "Last Executions" rows
 *    survive a reload.
 *  - TestReports derives it from a stored `script_results` row — either the
 *    deployment payload joined in by get_script_results, or, for runs that had
 *    no deployment behind them, the launch fields recorded on `metadata`.
 *
 * Because of that second source, the testcase variant carries EITHER a
 * preloaded graph (RunTests, which already holds one) OR a `testcaseId` to load
 * it from (TestReports — a graph is far too large to store per result row).
 */
export type RerunPayload =
  | {
      type: 'script';
      scriptName: string;
      hostName: string;
      deviceId: string;
      parameters: string;
      /** For virtual scripts: the DB row id (dev/test/prod) that actually ran, so
       *  a rerun replays the exact same version. Absent for disk scripts. */
      virtualScriptId?: string;
    }
  | {
      type: 'testcase';
      scriptName: string;
      hostName: string;
      deviceId: string;
      deviceModel: string;
      /** Preloaded graph — present when the launcher already had one in memory.
       *  Absent for a payload derived from a stored result, where `testcaseId`
       *  is used to fetch the graph instead. */
      executionGraph?: any;
      scriptInputs?: any[];
      scriptVariables?: any[];
      /** Saved-testcase id, used to load the graph when none is embedded.
       *  Absent for unsaved/ad-hoc graphs, which cannot be rerun at all. */
      testcaseId?: string;
      testcaseVersionNumber: number | null;
      /** User-supplied input values from the Run-with-inputs dialog, replayed
       *  verbatim on rerun (no dialog re-prompt). */
      inputValues?: Record<string, any>;
    }
  | {
      type: 'campaign';
      campaignName: string;
      hostName: string;
      deviceId: string;
      campaignSource: 'db' | 'file';
      campaignConfig: CampaignConfig;
    };
