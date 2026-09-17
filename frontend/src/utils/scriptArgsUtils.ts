/**
 * Turning a script's analyzed parameters + the values someone picked into the CLI argument
 * string the executor runs.
 *
 * Extracted from RunTests so the mobile Run Tests page produces a byte-identical command line
 * instead of its own approximation — a phone that quotes differently, or forgets `--host`, is a
 * run that behaves differently from the same test started on a desktop.
 */

export interface ScriptArgParam {
  name: string;
  /** 'positional' args are emitted bare; everything else as `--name value`. */
  type?: string;
}

export interface ScriptArgFrameworkValues {
  hostName?: string;
  deviceId?: string;
  /** Only 'prod' emits anything — `--ui-mode prod`, the dev/prod userinterface target. */
  uiMode?: string;
}

/** Wraps a value in double quotes when the shell would otherwise split or interpret it. */
export const quoteIfNeeded = (value: string): string => {
  if (/[\s"'`$\\()&|;<>]/.test(value)) {
    const escaped = value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    return `"${escaped}"`;
  }
  return value;
};

/**
 * `valueOf` is a lookup rather than a plain map because RunTests resolves each value per
 * (script, device) pair, while simpler callers just read a flat bag.
 *
 * `host` and `device` are skipped in the parameter loop and appended at the end from
 * `framework`: they are framework arguments, so their value comes from the selected target
 * rather than from whatever a script happens to declare.
 */
export function buildScriptArgs(
  parameters: ScriptArgParam[] | undefined,
  valueOf: (paramName: string) => string,
  framework: ScriptArgFrameworkValues = {},
): string {
  const args: string[] = [];

  for (const param of parameters ?? []) {
    if (param.name === 'host' || param.name === 'device') continue;
    const value = (valueOf(param.name) || '').trim();
    if (!value) continue;
    args.push(
      param.type === 'positional' ? quoteIfNeeded(value) : `--${param.name} ${quoteIfNeeded(value)}`,
    );
  }

  if (framework.hostName) args.push(`--host ${quoteIfNeeded(framework.hostName)}`);
  if (framework.deviceId) args.push(`--device ${quoteIfNeeded(framework.deviceId)}`);
  if ((framework.uiMode || '').trim() === 'prod') args.push('--ui-mode prod');

  return args.join(' ');
}
