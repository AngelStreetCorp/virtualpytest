/** Display names of group-by dimensions and origins (all through t(), so fr / de apply). */
import type { GroupBy } from './api';

type T = (key: string, vars?: Record<string, string | number>) => string;

export const groupLabel = (g: GroupBy, t: T): string => {
  switch (g) {
    case 'usage': return t('Feature');
    case 'model': return t('Model');
    case 'endpoint': return t('Provider');
    case 'team': return t('Team');
    case 'origin': return t('Origin');
    case 'host': return t('Host');
    case 'device': return t('Host · device');
    case 'script': return t('Script');
    case 'campaign': return t('Campaign');
    case 'user': return t('User');
    case 'server': return t('Server');
    case 'arm': return t('A/B arm');
    case 'error': return t('Error type');
    case 'client': return t('Public Ask visitor');
    case 'category': return t('Category');
    case 'caller': return t('Caller');
    case 'result': return t('Result');
    case 'category_caller': return t('Category and caller');
  }
};

export const originLabel = (origin: string, t: T): string => {
  switch (origin) {
    case 'ui': return t('Web app');
    case 'api': return t('API (service key)');
    case 'script': return t('Script run');
    case 'chat': return t('Agent chat');
    case 'monitoring': return t('Monitoring');
    case 'background': return t('Background job');
    case 'mcp': return t('MCP');
    case 'public': return t('Public Ask');
    case 'settings_test': return t('Settings test');
    case 'eval': return t('Evaluation');
    case 'unknown': return t('Unknown');
    default: return origin;
  }
};

export const errorTypeLabel = (type: string | null, t: T): string => {
  switch (type) {
    case null: return '';
    case 'timeout': return t('Timeout');
    case 'rate_limit': return t('Rate limit (429)');
    case 'no_credit': return t('No credit (402)');
    case 'auth': return t('Authentication');
    case 'bad_request': return t('Bad request');
    case 'server': return t('Provider error (5xx)');
    case 'connection': return t('Connection');
    case 'empty_answer': return t('Empty answer');
    case 'busy': return t('Busy (no free slot)');
    case 'parse': return t('Unparseable JSON');
    case 'refusal': return t('Model refused');
    default: return t('Other error');
  }
};

/** "OpenRouter has no credit left": the cause of a failure as a sentence about its provider. */
export const causeSentence = (reason: string, provider: string, t: T): string => {
  switch (reason) {
    case 'no_credit': return t('{provider} has no credit left', { provider });
    case 'auth': return t('{provider} rejects the API key', { provider });
    case 'connection': return t('{provider} cannot be reached', { provider });
    case 'server': return t('{provider} is failing (server error)', { provider });
    case 'rate_limit': return t('{provider} is limiting requests (rate limit)', { provider });
    case 'timeout': return t('{provider} answers too slowly (timeouts)', { provider });
    case 'empty_answer': return t('{provider} returns empty answers', { provider });
    case 'parse': return t('Answers from {provider} cannot be read as JSON', { provider });
    case 'bad_request': return t('{provider} rejects the request', { provider });
    case 'refusal': return t('{provider} refuses to answer', { provider });
    case 'busy': return t('{provider} is busy (no free slot)', { provider });
    default: return t('Requests to {provider} fail for an unknown reason', { provider });
  }
};

export interface NextStep {
  label: string;
  href: string;
  external?: boolean;
}

const SETTINGS_ENDPOINTS = '/configuration/settings?tab=ai';

/** What to do about a cause: a link with a label, or null when nothing a person can do. */
export const nextStep = (reason: string, preset: string | null | undefined, t: T): NextStep | null => {
  if (reason === 'no_credit') {
    return preset === 'openrouter'
      ? { label: t('Top up credit'), href: 'https://openrouter.ai/settings/credits', external: true }
      : { label: t('Check the account'), href: SETTINGS_ENDPOINTS };
  }
  if (reason === 'auth') return { label: t('Check the API key'), href: SETTINGS_ENDPOINTS };
  if (['connection', 'timeout', 'server', 'rate_limit', 'busy'].includes(reason)) {
    return { label: t('Open provider settings'), href: SETTINGS_ENDPOINTS };
  }
  return null;
};

export const providerTypeLabel = (type: 'cloud' | 'local', t: T): string =>
  type === 'local' ? t('local PC') : t('cloud');

/** Families of usage keys (backend `usages.family_of`): the group header of the feature table. */
export const familyLabel = (family: string, t: T): string => {
  switch (family) {
    case 'sherlock': return t('Sherlock');
    case 'nightwatch': return t('Nightwatch and alert triage');
    case 'screens': return t('Screen recognition');
    case 'manager': return t('Session manager');
    case 'testprompt': return t('Test Prompt');
    case 'atlas': return t('Atlas');
    case 'forge': return t('Forge');
    case 'browser': return t('Browser agent');
    case 'mcp': return t('MCP');
    case 'public': return t('Public Ask');
    case 'vision': return t('Image checks');
    case 'text': return t('Text');
    case 'agent': return t('Agents');
    default: return t('Other');
  }
};

/** Whether a usage key is a decision-model call (closed choice: no meaningful tokens or speed). */
export const isDecision = (key: string): boolean => key.startsWith('text.decision');
export const isChat = (key: string): boolean => key.startsWith('agent.') || key === 'public.ask';

/** The nine categories of backend `usages.category_of`. */
export const categoryLabel = (key: string, t: T): string => {
  switch (key) {
    case 'ask_ai': return t('Ask AI');
    case 'discard_script': return t('Discard script');
    case 'discard_incident': return t('Discard incident');
    case 'script_creation': return t('Script creation');
    case 'screen_recognition': return t('Screen recognition');
    case 'transcripts': return t('Transcripts & translation');
    case 'showcase': return t('Showcase / games');
    case 'web_lookup': return t('Web lookup');
    default: return t('Other');
  }
};

const AGENT_NAMES: Record<string, string> = {
  atlas: 'Atlas', sherlock: 'Sherlock', forge: 'Forge', nightwatch: 'Nightwatch', browser: 'Browser agent', mcp_prompt: 'MCP prompt',
};

/** Caller key of backend `usage_caller.caller_of` (`agent:atlas`, `script:zap.py`, `process:vpt-monitor`, `other:ui`) as words. */
export const callerLabel = (key: string, t: T): string => {
  const [kind, ...rest] = key.split(':');
  const name = rest.join(':');
  if (kind === 'agent') return AGENT_NAMES[name] ?? name.charAt(0).toUpperCase() + name.slice(1);
  if (kind === 'script' || kind === 'process') return name;
  if (kind === 'other') return originLabel(name, t);
  return key;
};

export const resultLabel = (key: string, t: T): string => (key === 'failed' ? t('Failed') : t('Success'));
