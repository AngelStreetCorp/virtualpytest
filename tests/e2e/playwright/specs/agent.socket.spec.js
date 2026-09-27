/**
 * /agent Socket.IO handshake + chat round-trip.
 *
 * Regression for the "Atlas ..." forever bubble: several client code paths called
 * socket.connect() while the authenticated handshake was still pending, socket.io-client
 * re-sent the CONNECT packet each time, python-socketio refused the duplicates on the same
 * engine connection with `44/agent "Unable to connect"`, and the client tore the whole
 * manager down on that CONNECT_ERROR — leaving a socket that still read `connected` but
 * delivered nothing. The agent's reply went to a room nobody was listening in.
 *
 * Both Engine.IO transports are captured: the very first packets travel over long-polling
 * before the websocket upgrade, so the websocket frames alone miss the CONNECT.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('./_navigate');

const SIO_PATH = '/socket.io/';
const RS = '\x1e'; // Engine.IO polling packet separator

function attachSocketCapture(page) {
  const cap = { sent: [], received: [], sockets: 0, closed: 0, consoleErrors: [] };
  page.on('websocket', (ws) => {
    if (!ws.url().includes(SIO_PATH)) return;
    const idx = cap.sockets++;
    ws.on('framesent', (f) => cap.sent.push({ via: `ws${idx}`, data: String(f.payload) }));
    ws.on('framereceived', (f) => cap.received.push({ via: `ws${idx}`, data: String(f.payload) }));
    ws.on('close', () => { cap.closed++; });
  });
  page.on('request', (req) => {
    if (req.method() !== 'POST' || !req.url().includes(SIO_PATH)) return;
    (req.postData() || '').split(RS).forEach((p) => p && cap.sent.push({ via: 'poll', data: p }));
  });
  page.on('response', async (res) => {
    const req = res.request();
    if (req.method() !== 'GET' || !req.url().includes(SIO_PATH) || res.status() !== 200) return;
    try {
      (await res.text()).split(RS).forEach((p) => p && cap.received.push({ via: 'poll', data: p }));
    } catch {
      // websocket upgrade responses have no body
    }
  });
  page.on('console', (msg) => {
    if (msg.type() === 'error') cap.consoleErrors.push(msg.text());
  });
  return cap;
}

const startsWith = (list, prefix) => list.filter((f) => f.data.startsWith(prefix));

function summary(cap) {
  return {
    sockets: cap.sockets,
    closed: cap.closed,
    connectSent: startsWith(cap.sent, '40/agent').length,
    connectAck: startsWith(cap.received, '40/agent').length,
    connectError: startsWith(cap.received, '44/agent').map((f) => f.data),
    joinSent: startsWith(cap.sent, '42/agent,["join_session"').length,
    joined: startsWith(cap.received, '42/agent,["joined"').length,
    socketContextErrors: cap.consoleErrors.filter((t) => t.includes('SocketContext')),
  };
}

function agentEvents(cap) {
  return startsWith(cap.received, '42/agent,["agent_event"')
    .map((f) => {
      try { return JSON.parse(f.data.slice(f.data.indexOf(',') + 1))[1]; } catch { return null; }
    })
    .filter(Boolean);
}

test.describe('AI agent socket', () => {
  test('one authenticated /agent connection per engine connection, no CONNECT_ERROR', async ({ page }) => {
    const cap = attachSocketCapture(page);
    await gotoWithAutoSign(page, '/ai-agent', { waitUntil: 'domcontentloaded' });
    // Long enough for the async auth callback, the polling→websocket upgrade and every
    // consumer's connect() call to have happened.
    await page.waitForTimeout(12_000);

    const s = summary(cap);
    console.log('[agent.socket] handshake summary', JSON.stringify(s));

    expect(s.connectAck, 'the /agent namespace was never acknowledged').toBeGreaterThanOrEqual(1);
    expect(s.connectError, 'server refused a duplicate CONNECT on the same engine connection').toEqual([]);
    expect(s.connectSent, 'more CONNECT packets than engine connections').toBe(s.connectAck);
    expect(s.socketContextErrors).toEqual([]);
    expect(s.closed, 'the websocket was torn down during page load').toBe(0);
  });

  test('a prompt gets its reply rendered', async ({ page }) => {
    // One agent conversation runs at a time per server worker; a message sent while
    // another conversation is being answered waits for it (the server says so with a
    // 'Waiting for another conversation to finish...' event). Budget for that.
    test.setTimeout(360_000);
    const cap = attachSocketCapture(page);
    await gotoWithAutoSign(page, '/ai-agent', { waitUntil: 'domcontentloaded' });

    const input = page.getByPlaceholder(/How can I help you|Ask AI Agent/);
    await expect(input).toBeVisible({ timeout: 20_000 });
    await page.waitForFunction(() => Boolean(window.__vptSocket && window.__vptSocket.connected), null, { timeout: 30_000 });
    await expect(input).toBeEnabled({ timeout: 20_000 });

    const marker = `PONG-${Date.now().toString(36)}`;
    await input.fill(`Reply with exactly the text "${marker}" and nothing else. Do not call any tool.`);
    await input.press('Enter');

    // The backend acks with 'thinking' within ~1s, then streams message/session_ended.
    try {
      await expect
        .poll(() => agentEvents(cap).some((e) => e.type === 'message' || e.type === 'session_ended'), {
          timeout: 300_000,
          message: 'no agent message reached the page — is the client still in the room the message was sent in?',
        })
        .toBe(true);
    } finally {
      const sends = startsWith(cap.sent, '42/agent,["send_message"');
      console.log('[agent.socket] send_message frames:', sends.length, sends.map((f) => f.data.slice(0, 160)));
      console.log('[agent.socket] agent_event types so far:', JSON.stringify(agentEvents(cap).map((e) => `${e.type}${e.session_id ? '@' + e.session_id.slice(0, 8) : ''}`)));
      console.log('[agent.socket] rooms joined:', JSON.stringify(startsWith(cap.received, '42/agent,["joined"').map((f) => f.data.slice(0, 120))));
      console.log('[agent.socket] socket errors:', JSON.stringify(startsWith(cap.received, '42/agent,["error"').map((f) => f.data.slice(0, 200))));
    }

    const reply = agentEvents(cap).find((e) => e.type === 'message' && e.content && e.content.includes(marker));
    expect(reply, `agent never answered with ${marker}: ${JSON.stringify(agentEvents(cap).map((e) => e.type))}`).toBeTruthy();
    await expect(page.getByText(marker).last()).toBeVisible({ timeout: 15_000 });

    // The typing indicator must clear once the session ended.
    await expect.poll(() => agentEvents(cap).some((e) => e.type === 'session_ended'), { timeout: 30_000 }).toBe(true);

    const s = summary(cap);
    console.log('[agent.socket] round-trip summary', JSON.stringify(s));
    expect(s.connectError).toEqual([]);
  });
});
