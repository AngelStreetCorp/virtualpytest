const { test, expect } = require('@playwright/test');
const { apiHeaders, readJson, getHosts, getScripts, pickDnsLookupScript } = require('./_helpers');

const TEAM_ID = process.env.TEAM_ID || 'team_123';

test.describe('API Smoke - Core Workflows', () => {
  test('8. Health endpoint reports healthy', async ({ request }) => {
    const response = await request.get('/server/system/health', { headers: apiHeaders() });
    expect(response.ok()).toBeTruthy();
    const body = await readJson(response);
    expect(body.status).toBe('healthy');
  });

  test('9. Can fetch hosts and script list for team', async ({ request }) => {
    const hostsRes = await getHosts(request, TEAM_ID);
    expect(hostsRes.response.ok()).toBeTruthy();
    expect(hostsRes.body.success).toBeTruthy();
    expect(Array.isArray(hostsRes.body.hosts)).toBeTruthy();

    const scriptsRes = await getScripts(request, TEAM_ID);
    expect(scriptsRes.response.ok()).toBeTruthy();
    expect(scriptsRes.body.success).toBeTruthy();
    expect(Array.isArray(scriptsRes.body.scripts)).toBeTruthy();
  });

  test('10. Fast script execution + deployment create/run/delete flow', async ({ request }) => {
    const hostsRes = await getHosts(request, TEAM_ID);
    expect(hostsRes.response.ok()).toBeTruthy();
    const firstHost = hostsRes.body.hosts?.[0];
    expect(firstHost, 'No hosts registered — CI environment must have at least one host').toBeTruthy();
    const firstDevice = firstHost.devices?.[0];
    expect(firstDevice, 'Host has no devices registered — CI environment must have at least one device').toBeTruthy();

    const scriptsRes = await getScripts(request, TEAM_ID);
    expect(scriptsRes.response.ok()).toBeTruthy();
    const scriptName = pickDnsLookupScript(scriptsRes.body.scripts);
    expect(scriptName).toBeTruthy();

    const executeResponse = await request.post(`/server/script/execute?team_id=${encodeURIComponent(TEAM_ID)}`, {
      headers: apiHeaders(),
      data: {
        host_name: firstHost.host_name,
        device_id: firstDevice.device_id,
        script_name: scriptName,
        parameters: '',
      },
    });
    if (executeResponse.status() === 423) {
      const lockedBody = await readJson(executeResponse);
      test.skip(true, `Device already locked: ${lockedBody.message || lockedBody.error || 'device is in use by another session'}`);
      return;
    }
    expect([200, 202]).toContain(executeResponse.status());
    const executeBody = await readJson(executeResponse);
    expect(executeBody.success).toBeTruthy();

    const deploymentPayload = {
      name: `e2e_dns_lookup_${Date.now()}`,
      host_name: firstHost.host_name,
      device_id: firstDevice.device_id,
      script_name: scriptName,
      userinterface_name: process.env.UI_NAME || 'example_mobile',
      parameters: '',
      cron_expression: '*/30 * * * *',
    };

    const createResponse = await request.post(`/server/deployment/create?team_id=${encodeURIComponent(TEAM_ID)}`, {
      headers: apiHeaders(),
      data: deploymentPayload,
    });
    const createBody = await readJson(createResponse);
    expect(createResponse.ok(), `Deployment create failed: HTTP ${createResponse.status()} ${JSON.stringify(createBody)}`).toBeTruthy();
    expect(createBody.success).toBeTruthy();
    const deploymentId = createBody.deployment?.id;
    expect(deploymentId).toBeTruthy();

    const runResponse = await request.post(`/server/deployment/run/${deploymentId}?team_id=${encodeURIComponent(TEAM_ID)}`, {
      headers: apiHeaders(),
    });
    expect(runResponse.ok()).toBeTruthy();
    const runBody = await readJson(runResponse);
    expect(runBody.success).toBeTruthy();

    const deleteResponse = await request.delete(`/server/deployment/delete/${deploymentId}?team_id=${encodeURIComponent(TEAM_ID)}`, {
      headers: apiHeaders(),
    });
    expect(deleteResponse.ok()).toBeTruthy();
    const deleteBody = await readJson(deleteResponse);
    expect(deleteBody.success).toBeTruthy();
  });
});
