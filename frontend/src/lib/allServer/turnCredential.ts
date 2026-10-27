/**
 * What the Atlas chat sends with each message so the server can act as the signed-in user on any server
 * (TASK-179 P4): the same login the app's normal API calls use (the Supabase access token, or the auto-sign
 * token of an agent/E2E session). The picker's scope is in turnScope.ts.
 *
 * The credential is read fresh for every send (tokens refresh), goes into one `send_message` and nowhere else:
 * it is not kept in state, storage or logs.
 */
import { getAutoSignHeaderToken } from '../autoSign';
import { getAccessTokenForServer } from '../serverIdentity';
import { getServerBaseUrl } from '../../utils/buildUrlUtils';

export interface TurnAuth {
  token?: string;
  auto_sign?: string;
}

export const buildTurnAuth = async (): Promise<TurnAuth> => {
  const auth: TurnAuth = {};
  try {
    const token = await getAccessTokenForServer(getServerBaseUrl());
    if (token) auth.token = token;
  } catch {
    // No session: the auto-sign token (if any) or nothing; the server then keeps the service key for local calls.
  }
  const autoSign = getAutoSignHeaderToken();
  if (autoSign) auth.auto_sign = autoSign;
  return auth;
};
