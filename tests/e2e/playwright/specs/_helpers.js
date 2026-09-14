function apiHeaders() {
  const headers = {
    'Content-Type': 'application/json',
  };

  const apiKey = process.env.API_KEY || '';
  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
    headers['X-API-Key'] = apiKey;
  }

  const autoSignToken = process.env.E2E_AUTO_SIGN_TOKEN || '';
  if (autoSignToken) {
    headers['X-Auto-Sign'] = autoSignToken;
  }
  return headers;
}

async function readJson(response) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    return { _raw: text };
  }
}

async function getHosts(request, teamId) {
  const response = await request.get(`/server/system/getAllHosts?include_system_stats=true&team_id=${encodeURIComponent(teamId)}`, {
    headers: apiHeaders(),
  });
  const body = await readJson(response);
  return { response, body };
}

async function getScripts(request, teamId) {
  const response = await request.get(`/server/script/list?team_id=${encodeURIComponent(teamId)}`, {
    headers: apiHeaders(),
  });
  const body = await readJson(response);
  return { response, body };
}

function pickDnsLookupScript(scripts) {
  if (!Array.isArray(scripts)) return null;
  const dns = scripts.find((s) => String(s).includes('dns_lookuptime.py'));
  return dns || scripts[0] || null;
}

module.exports = {
  apiHeaders,
  readJson,
  getHosts,
  getScripts,
  pickDnsLookupScript,
};
