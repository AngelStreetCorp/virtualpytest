/**
 * Shared UI constants/helpers for TestCaseBuilder page/components.
 */

import { ExecutionState } from '../../types/testcase/TestCase_Types';

export const TESTCASE_BUILDER_ATTRIBUTION_CSS = `
  .react-flow__panel.react-flow__attribution {
    display: none !important;
  }
`;

export const STANDARD_BLOCK_TYPES = [
  'evaluate_condition',
  'custom_code',
  'common_operation',
  'set_variable',
  'set_variable_io',
  'get_current_time',
  'sleep',
];

export const FIT_VIEW_INITIAL_DELAY_MS = 100;
export const FIT_VIEW_ON_LOAD_DELAY_MS = 150;
export const FIT_VIEW_ON_NEW_DELAY_MS = 200;

export const isEditableTarget = (target: EventTarget | null): boolean => {
  const element = target as HTMLElement | null;
  if (!element) {
    return false;
  }
  return (
    element.tagName === 'INPUT' ||
    element.tagName === 'TEXTAREA' ||
    element.isContentEditable ||
    element.closest('input') !== null ||
    element.closest('textarea') !== null
  );
};

export const getExecutionFooterSummary = (executionState: ExecutionState): string => {
  if (executionState.isExecuting) {
    return 'Executing...';
  }
  if (!executionState.result) {
    return '';
  }

  const result = executionState.result;
  const resultType = result.result_type || (result.success ? 'success' : 'error');
  if (resultType === 'success') {
    return `✓ Last run: SUCCESS (${result.execution_time_ms}ms)`;
  }
  if (resultType === 'failure') {
    return `✗ Last run: FAILURE (${result.execution_time_ms}ms)`;
  }
  return `⚠ Last run: ERROR - ${result.error || 'Unknown error'}`;
};
