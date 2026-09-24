/**
 * Execution Utility Functions
 * 
 * Shared utility functions and components for script and campaign execution.
 * Extracted from RunTests.tsx to be reused across execution interfaces.
 */

import React from 'react';
import { Chip } from '@mui/material';
import {
  loadScriptIdentityMap,
  lookupScriptIdentity,
  IdentityEntry,
} from './identityMapCache';
import type { RerunPayload } from '../types/common/Rerun_Types';

// Convert report URL/path to logs path (strip any signature/domain first)
export const getLogsPath = (reportUrl: string): string => {
  let path = reportUrl;
  try {
    if (path.startsWith('http')) {
      const url = new URL(path);
      path = url.pathname.substring(1); // remove leading /
    }
  } catch { /* use as-is */ }
  // Remove /minio/ prefix from old MinIO browser URLs
  if (path.startsWith('minio/')) {
    path = path.substring('minio/'.length);
  }
  // Remove bucket name prefix (any bucket: virtualpytest, etc.)
  // Bucket is the first segment before known storage prefixes
  const bucketMatch = path.match(/^[^/]+\/(script-|captures\/|verification\/|device-screenshots\/)/);
  if (bucketMatch) {
    path = path.substring(path.indexOf('/') + 1);
  }
  return path.replace('script-reports', 'script-logs').replace('report.html', 'execution.txt');
};

// Keep old name for backward compatibility
export const getLogsUrl = getLogsPath;

// --- Script Identity Map (prefix + display_name from script_identity_map.json) ---
// Storage + lookup live in `identityMapCache` so this module and `useIdentityMap`
// share a single fetch + cache.

/** Fetch & cache the identity map. Safe to call multiple times. */
export const ensureScriptIdentityMap = async (): Promise<void> => {
  await loadScriptIdentityMap();
};

const lookupIdentity = (scriptName: string): IdentityEntry | null => lookupScriptIdentity(scriptName);

/**
 * Return raw {prefix, display_name} for a script (or null if not in the map / map not loaded).
 * Used by useScript / CampaignBuilder to forward identity to the backend so it lands
 * in script_results.metadata without requiring the JSON map on the host VM.
 */
export const getScriptIdentity = (scriptName: string): IdentityEntry | null => {
  return lookupIdentity(scriptName);
};

/** Format script name using identity map: "[TC001] Get System Information" */
export const formatScriptLabel = (scriptName: string): string => {
  const identity = lookupIdentity(scriptName);
  if (identity) {
    const { prefix, display_name } = identity;
    if (prefix && display_name) return `[${prefix}] ${display_name}`;
    if (display_name) return display_name;
    if (prefix) return `[${prefix}] ${scriptName}`;
  }
  return scriptName;
};

// Helper function to get display name for scripts (especially AI test cases and subfolder scripts)
export const getScriptDisplayName = (scriptName: string, aiTestCasesInfo?: any[]): string => {
  // First check identity map (prefix + display_name)
  const identity = lookupIdentity(scriptName);
  if (identity) {
    const { prefix, display_name } = identity;
    if (prefix && display_name) return `[${prefix}] ${display_name}`;
    if (display_name) return display_name;
    if (prefix) return `[${prefix}] ${scriptName}`;
  }
  // AI test cases
  if (scriptName.startsWith('ai_testcase_')) {
    const aiInfo = aiTestCasesInfo?.find(info => info.script_name === scriptName);
    if (aiInfo) {
      const name = aiInfo.name || 'Unnamed Test Case';
      return name.replace(/^AI:\s*/, '');
    }
    return scriptName.replace('ai_testcase_', '').substring(0, 8) + '...';
  }
  return scriptName;
};

// Helper function to check if script is AI generated
export const isAIScript = (scriptName: string): boolean => {
  return scriptName.startsWith('ai_testcase_');
};

// Helper function to determine test result from script output
export const determineTestResult = (result: any): 'success' | 'failure' | undefined => {
  // Use the script_success field provided by the host - this is the authoritative result
  if (result.script_success !== undefined && result.script_success !== null) {
    return result.script_success ? 'success' : 'failure';
  }
  
  // If no script_success field, script execution likely failed at system level
  if (result.exit_code !== undefined && result.exit_code !== 0) {
    return 'failure';
  }
  
  // If script completed but no script_success field, leave undefined
  return undefined;
};

// Helper function to format execution duration
export const formatExecutionDuration = (startTime: string, endTime?: string): string => {
  if (!endTime) return 'Running...';
  
  try {
    const start = new Date(`1970-01-01 ${startTime}`);
    const end = new Date(`1970-01-01 ${endTime}`);
    const diffMs = end.getTime() - start.getTime();
    
    if (diffMs < 0) return 'Invalid';
    
    const seconds = Math.floor(diffMs / 1000);
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    
    if (minutes > 0) {
      return `${minutes}m ${remainingSeconds}s`;
    }
    return `${seconds}s`;
  } catch (error) {
    return 'Invalid';
  }
};

// Helper function to generate unique execution ID
export const generateExecutionId = (prefix: string, hostName: string, deviceId: string): string => {
  return `${prefix}_${Date.now()}_${hostName}_${deviceId}`;
};

// Helper function to extract device info from execution ID
export const extractDeviceFromExecutionId = (executionId: string): { hostName?: string; deviceId?: string } => {
  const parts = executionId.split('_');
  if (parts.length >= 4) {
    return {
      hostName: parts[2],
      deviceId: parts[3],
    };
  }
  return {};
};

// Helper function to validate parameter values
export interface ParameterValidationResult {
  valid: boolean;
  errors: string[];
}

export const validateParameterValues = (
  parameters: { name: string; required: boolean }[],
  values: { [name: string]: string }
): ParameterValidationResult => {
  const errors: string[] = [];
  
  parameters.forEach(param => {
    if (param.required && (!values[param.name] || !values[param.name].trim())) {
      errors.push(`${param.name} is required`);
    }
  });
  
  return {
    valid: errors.length === 0,
    errors,
  };
};

// Status types for consistency across components
export type ExecutionStatus = 'running' | 'completed' | 'failed' | 'aborted' | 'preempted' | 'queued';
export type CampaignStatus = 'pending' | 'running' | 'completed' | 'failed' | 'aborted' | 'waiting_for_lock';
export type ScriptStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'waiting_for_lock'
  | 'aborted_by_takeover';

// Centralized status chip helper - extracted from RunTests.tsx to be shared
export const getStatusChip = (status: ExecutionStatus | CampaignStatus | ScriptStatus): React.JSX.Element => {
  switch (status) {
    case 'queued':
      return <Chip label="Queued" color="info" size="small" />;
    case 'pending':
      return <Chip label="Pending" color="default" size="small" />;
    case 'running':
      return <Chip label="Running" color="warning" size="small" />;
    case 'completed':
      return <Chip label="Completed" color="success" size="small" />;
    case 'failed':
      return <Chip label="Failed" color="error" size="small" />;
    case 'aborted':
      return <Chip label="Aborted" color="error" size="small" />;
    case 'preempted':
      return <Chip label="Preempted" color="error" size="small" />;
    case 'skipped':
      return <Chip label="Skipped" color="default" size="small" />;
    case 'waiting_for_lock':
      return <Chip label="Waiting Lock" color="warning" size="small" />;
    case 'aborted_by_takeover':
      return <Chip label="Aborted by Takeover" color="error" size="small" />;
    default:
      return <Chip label="Unknown" color="default" size="small" />;
  }
};

/**
 * Build the rerun config for a stored script result, or null when the run
 * cannot be replayed.
 *
 * Two sources, in priority order:
 *  1. `rerun_payload` — the launching deployment's exact launch config, joined
 *     in by get_script_results. Authoritative, and the only source that covers
 *     runs recorded before the launch fields below were persisted.
 *  2. `metadata` — the launch fields the executor records on every run, which
 *     covers everything that never went through a deployment (campaign steps,
 *     direct API calls).
 *
 * Returns null for runs with neither: an unsaved/ad-hoc testcase graph exists
 * only in the caller that submitted it, and pre-existing rows never recorded
 * their parameters. Callers render no rerun control in that case.
 */
export const buildRerunPayloadFromResult = (result: {
  script_name: string;
  script_type?: string;
  host_name: string;
  device_name: string;
  metadata?: any;
  rerun_payload?: RerunPayload | null;
}): RerunPayload | null => {
  // A campaign payload is deliberately ignored here: these rows are individual
  // script results, and replaying a whole campaign from one of its steps is not
  // what the icon on that row promises. Such a row falls through to metadata and
  // reruns just its own script.
  if (result.rerun_payload && result.rerun_payload.type !== 'campaign') {
    return result.rerun_payload;
  }

  const metadata = result.metadata;
  if (!metadata || typeof metadata !== 'object') return null;

  // device_id is the executor-facing identifier; device_name on the row is the
  // display name, which is not interchangeable with it.
  const deviceId = metadata.device_id || 'host';

  if (result.script_type === 'testcase') {
    // An unsaved graph has no definition to load — nothing to replay.
    if (metadata.unsaved === true || !metadata.testcase_id) return null;
    return {
      type: 'testcase',
      scriptName: result.script_name,
      hostName: result.host_name,
      deviceId,
      deviceModel: metadata.device_model || 'unknown',
      testcaseId: String(metadata.testcase_id),
      testcaseVersionNumber: metadata.testcase_version ?? null,
      inputValues: metadata.testcase_inputs,
    };
  }

  // An empty string is a valid parameter set (a script taking no arguments);
  // only an absent field means the launch config was never recorded.
  if (typeof metadata.parameters !== 'string') return null;

  return {
    type: 'script',
    scriptName: result.script_name,
    hostName: result.host_name,
    deviceId,
    parameters: metadata.parameters,
    // Replays the exact virtual-script row that ran. Without it a virtual
    // script's rerun would look for a disk file of that name and fail.
    virtualScriptId: metadata.virtual_script_id || undefined,
  };
};
