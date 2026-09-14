import type { CampaignConfig } from './Campaign_Types';

/**
 * Full launch-time config for one-click "Last Executions" rerun in RunTests.
 * Captured at launch so the rerun icon never has to refetch or recompute.
 * Mirrored to the deployments.rerun_payload jsonb column for cross-reload reruns.
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
      executionGraph: any;
      scriptInputs: any[];
      scriptVariables: any[];
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
