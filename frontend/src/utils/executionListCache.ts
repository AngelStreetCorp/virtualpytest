import { createRequestCache } from './requestCache';

/**
 * The two executable lists behind the Run Tests / Build Campaigns pickers.
 *
 * Both were written out longhand here — the same value + in-flight + TTL + peek +
 * invalidate logic twice, with `campaign` spliced into every identifier. See
 * `requestCache.ts` for the shared implementation and for why it keeps one entry and
 * why `peek` exists.
 */

const TTL_MS = 30_000;

const executableList = createRequestCache('executableList', TTL_MS);
const campaignExecutableList = createRequestCache('campaignExecutableList', TTL_MS);

export const getCachedExecutableList = (apiUrl: string) => executableList.get(apiUrl);
export const invalidateExecutableListCache = () => executableList.invalidate();

export const getCachedCampaignExecutableList = (apiUrl: string) =>
  campaignExecutableList.get(apiUrl);
export const peekCachedCampaignExecutableList = (apiUrl: string) =>
  campaignExecutableList.peek(apiUrl);
export const invalidateCampaignExecutableListCache = () => campaignExecutableList.invalidate();
