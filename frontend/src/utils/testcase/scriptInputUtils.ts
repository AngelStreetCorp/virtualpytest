/**
 * Script-input helpers for parameterized testcase runs.
 *
 * A testcase is a TEMPLATE: steps store literal `{name}` placeholders and
 * `scriptConfig.inputs[]` declares each variable ({name, type, required,
 * default}). Run-time values are stamped as `inputs[].value` onto a CLONE of
 * the graph just before POST — the backend (TestCaseExecutor) reads
 * `.value || .default` into context.variables and resolves placeholders at
 * block-execution time. `value` is never persisted: Save always strips it.
 */

import { ScriptInput, TestCaseGraph } from '../../types/testcase/TestCase_Types';

/** Whole-value placeholder, same convention as the backend resolver. */
const PLACEHOLDER_REGEX = /^\{(.+)\}$/;

/** Extract the variable name from a `{name}` string, or null. */
export const placeholderName = (value: unknown): string | null => {
  if (typeof value !== 'string') return null;
  const match = value.match(PLACEHOLDER_REGEX);
  return match ? match[1].trim() : null;
};

/** Wrap a variable name as the literal placeholder steps store. */
export const asPlaceholder = (name: string): string => `{${name}}`;

/**
 * Clone the graph and set `.value` on each scriptConfig input present in
 * `values`, coercing by the input's declared type (dialog fields yield
 * strings). Inputs not in `values` — or with an empty value — keep relying
 * on their default (empty means "use default", never "override with ''").
 */
export const stampInputValues = (
  graph: TestCaseGraph,
  values: Record<string, any>,
): TestCaseGraph => {
  const stamped: TestCaseGraph = JSON.parse(JSON.stringify(graph));
  stamped.scriptConfig?.inputs?.forEach((input: ScriptInput & { value?: any }) => {
    if (!(input.name in values)) return;
    const raw = values[input.name];
    if (raw == null || raw === '') return;
    if (input.type === 'number') {
      const num = Number(raw);
      input.value = Number.isNaN(num) ? raw : num;
    } else if (input.type === 'boolean') {
      input.value = raw === true || raw === 'true';
    } else {
      input.value = raw;
    }
  });
  return stamped;
};

/**
 * Map a testcase's scriptConfig to campaign-block I/O: non-protected inputs
 * become editable per-row parameter fields on the CampaignBlock (protected
 * inputs — host_name & co. — are filled from the execution environment).
 * Loosely typed to avoid a hard dependency on CampaignGraph_Types.
 */
export const testcaseScriptConfigToBlockIO = (
  scriptConfig: any,
): { inputs: any[]; outputs: any[] } => ({
  inputs: (scriptConfig?.inputs || [])
    .filter((input: any) => input && !input.protected)
    .map((input: any) => ({
      name: input.name,
      type: input.type,
      required: input.required,
      default: input.default,
    })),
  outputs: (scriptConfig?.outputs || []).map((output: any) => ({
    name: output.name,
    type: output.type,
    description: output.description,
  })),
});

/**
 * Collect every `{name}` referenced by a value tree (step list, block data…).
 * Used to auto-create inputs for unknown names and to gate deleting inputs
 * that are still referenced.
 */
export const collectPlaceholders = (value: unknown, found: Set<string> = new Set()): Set<string> => {
  const name = placeholderName(value);
  if (name) {
    found.add(name);
    return found;
  }
  if (Array.isArray(value)) {
    value.forEach((item) => collectPlaceholders(item, found));
  } else if (value && typeof value === 'object') {
    Object.values(value).forEach((item) => collectPlaceholders(item, found));
  }
  return found;
};
