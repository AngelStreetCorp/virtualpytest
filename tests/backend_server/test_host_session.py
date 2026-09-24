"""Host session gate (BUG-0107 step 2) — backend_server/src/routes/server_host_session_routes.py.

The gate that closed BUG-0107 had no automated coverage at all: `/server/host-session/authorize`
is declared `internal;` in the proxy config, so the CI route sweep gets nginx's own 404 for it and
skipped it — and a skipped row proves nothing. What matters is not that the authorize route
answers, but that the proxy still consults it, so these tests drive the gate the way a browser
does: through a real gated `/host/<name>/stream/...` URL.

  anonymous        -> 401   (no cookie, no key)
  forged cookie    -> 401
  service API key  -> through (server-to-server callers: MCP screenshot, heatmap processor)
  minted cookie    -> through on the host it was minted for, 403 on any other

Minting (`POST /server/host-session/session`) is `@require_user_auth`; the shared service key
satisfies it through the global guard's principal, so nothing here needs a user JWT and nothing
here is conditionally skipped except when the suite is pointed at a server with no proxy
in front of it (a local run) — where the gate does not exist to be tested.

The last two tests cover the cross-origin client the gate broke on arrival: the mobile app is a
Capacitor shell serving the bundled frontend from its own `https://localhost` origin, so every
request it makes to a deployment is cross-SITE. A `SameSite=Strict` cookie is neither stored nor
replayed there, and a credentialed request rejects a wildcard `Access-Control-Allow-Origin` — so
the APK minted a session, got a 200, and then 401'd on every manifest and segment. Both
properties are invisible from a browser on the deployment's own domain, which is why the gate
shipped looking healthy.
"""

import pytest

COOKIE_NAME = "vpt_host_session"
GATED_SUFFIX = "/stream/output.m3u8"
MINT_PATH = "/server/host-session/session"


@pytest.fixture
def gated_url(device_host: str) -> str:
    return f"/host/{device_host}{GATED_SUFFIX}"


@pytest.fixture
def gate_status(get, gated_url: str) -> int:
    """Status of an anonymous GET on a gated path — and the guard for this whole module.

    The gate lives in the proxy, so it only exists when the suite runs against a deployed
    URL. 404 means nothing fronts `/host/...` here (a bare local server has no such path),
    which is a skip. 200 means the proxy IS there and is no longer consulting the gate —
    the exact regression this module exists to catch, so that fails rather than skips.
    """
    status = get(gated_url).status_code
    if status == 404:
        pytest.skip(f"no proxy fronts {gated_url} — point SERVER_URL at the deployed server")
    return status


def test_gated_path_denies_anonymous(gate_status: int, gated_url: str):
    assert gate_status == 401, (
        f"{gated_url} answered {gate_status} to an anonymous request; the host-session gate "
        "either is not applied to this location or is allowing unauthenticated traffic"
    )


def test_gated_path_rejects_a_forged_cookie(gate_status, get, gated_url: str):
    response = get(gated_url, headers={"Cookie": f"{COOKIE_NAME}=not.a.real.token"})
    assert response.status_code == 401


def test_service_api_key_passes_the_gate(gate_status, get, gated_url: str, api_headers: dict):
    """Server-to-server callers hold the shared key, never a browser session.

    They must get past the gate; whether the file itself exists on that host is not this
    test's business (a host with no live stream answers 404 from behind the gate).
    """
    response = get(gated_url, headers=api_headers)
    assert response.status_code not in (401, 403), (
        f"the service API key was refused by the gate ({response.status_code}) — the MCP "
        "screenshot tool and the heatmap processor fetch these URLs with exactly this key"
    )


def test_mint_requires_authentication(post):
    response = post(MINT_PATH, json={"host_name": "anything"})
    assert response.status_code == 401


def test_mint_requires_a_host_name(post, api_headers: dict):
    response = post(MINT_PATH, json={}, headers=api_headers)
    assert response.status_code == 400


def test_mint_rejects_an_unknown_host(post, api_headers: dict):
    response = post(MINT_PATH, json={"host_name": "vpt-not-a-registered-host"}, headers=api_headers)
    assert response.status_code == 404


def test_minted_cookie_opens_its_own_host_and_no_other(
    gate_status, post, get, api_headers: dict, device_host: str, gated_url: str
):
    minted = post(MINT_PATH, json={"host_name": device_host}, headers=api_headers)
    assert minted.status_code == 200, f"could not mint a session for {device_host}: {minted.text[:200]}"
    token = minted.cookies.get(COOKIE_NAME)
    assert token, f"{MINT_PATH} returned no {COOKIE_NAME} cookie"

    cookie = {"Cookie": f"{COOKIE_NAME}={token}"}

    own_host = get(gated_url, headers=cookie)
    assert own_host.status_code not in (401, 403), (
        f"a freshly minted session was refused on its own host ({own_host.status_code})"
    )

    # Same cookie, different host in the path: the claim no longer matches, so the gate
    # must refuse it. This is what makes the cookie host-scoped rather than a skeleton key.
    other_host = get(f"/host/vpt-some-other-host{GATED_SUFFIX}", headers=cookie)
    assert other_host.status_code == 403, (
        f"a session minted for {device_host} was accepted on another host's path "
        f"({other_host.status_code}) — the cookie is not host-scoped"
    )


def test_minted_cookie_can_cross_sites(post, api_headers: dict, device_host: str):
    """`SameSite=None`, or the mobile app cannot hold this cookie at all.

    Asserted on the raw `Set-Cookie` header rather than the parsed jar: `requests` keeps a
    Strict cookie quite happily, so a jar-level check passes while a real WebView drops it.
    """
    minted = post(MINT_PATH, json={"host_name": device_host}, headers=api_headers)
    assert minted.status_code == 200, f"could not mint a session for {device_host}"

    set_cookie = minted.headers.get("Set-Cookie", "")
    assert COOKIE_NAME in set_cookie, f"{MINT_PATH} returned no {COOKIE_NAME} cookie"
    lowered = set_cookie.lower()
    assert "samesite=none" in lowered, (
        f"{COOKIE_NAME} is not SameSite=None ({set_cookie!r}) — the mobile app serves the "
        "frontend from its own https://localhost origin, so every call it makes is "
        "cross-site and a Strict/Lax cookie is silently dropped: no stream in the app"
    )
    # SameSite=None is only honoured on a Secure cookie; without it browsers reject the pair.
    assert "secure" in lowered, f"{COOKIE_NAME} is SameSite=None but not Secure ({set_cookie!r})"


def test_gated_stream_answers_a_cross_origin_caller_without_a_wildcard(
    gate_status, post, get, api_headers: dict, device_host: str, gated_url: str
):
    """A credentialed cross-origin fetch forbids `Access-Control-Allow-Origin: *`.

    The mobile app must send the cookie, which makes its stream requests credentialed, and
    the browser then discards any response whose allow-origin is the wildcard — including a
    perfectly good 200. So the stream path has to echo the caller's origin and allow
    credentials for an origin on the allowlist.
    """
    minted = post(MINT_PATH, json={"host_name": device_host}, headers=api_headers)
    token = minted.cookies.get(COOKIE_NAME)
    assert token, f"{MINT_PATH} returned no {COOKIE_NAME} cookie"

    app_origin = "https://localhost"  # the Capacitor shell's fixed origin
    response = get(
        gated_url,
        headers={"Cookie": f"{COOKIE_NAME}={token}", "Origin": app_origin},
    )
    assert response.status_code not in (401, 403), (
        f"a minted session was refused on its own host ({response.status_code})"
    )

    allow_origin = response.headers.get("Access-Control-Allow-Origin")
    assert allow_origin == app_origin, (
        f"gated stream answered Access-Control-Allow-Origin={allow_origin!r} to a caller from "
        f"{app_origin}; a credentialed request needs that origin echoed back, and a browser "
        "drops the response outright on '*'"
    )
    assert response.headers.get("Access-Control-Allow-Credentials") == "true", (
        "gated stream did not allow credentials — the browser will not attach the host-session "
        "cookie to the manifest or to any segment derived from it"
    )
