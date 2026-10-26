"""Why a `/server/...` request that reached the auto_proxy catch-all had no host.

The catch-all in `routes/auto_proxy.py` answers for every `/server/*` path that matched no
blueprint. It proxies the path to a device host, and the host helper refuses without a
`host_name` — so a caller whose PATH was wrong is told it forgot a device parameter. That
misdirection cost an afternoon on BUG-0507: a GitLab route whose project carried an encoded
slash matched nothing, fell into the catch-all, and answered a question about device hosts
while the page showed an empty repository.

This module holds the explanation on its own, with no Flask and no backend imports, so it can be
unit-tested anywhere. The catch-all calls it; it never decides whether to proxy — that stays in
auto_proxy, which knows what a device call looks like.
"""

#: Prefix of the host helper's refusal. Anything else from that helper is left untouched.
MISSING_HOST_PREFIX = 'host_name required'

#: Stable, greppable marker, so a caller can branch on it without parsing prose.
FALLBACK_FLAG = 'auto_proxy_fallback'


def explain_unmatched_endpoint(endpoint: str, payload, status_code: int):
    """Reword the catch-all's "no host_name" refusal into something a caller can act on.

    Returns `payload` unchanged unless the catch-all failed *for that exact reason*: the
    catch-all cannot tell "I am a device route and you forgot my host" from "no route matched
    me at all", so the answer names both and flags itself. Any other failure, and any success,
    comes back untouched.
    """
    if status_code != 400 or not isinstance(payload, dict):
        return payload
    reason = str(payload.get('error') or '')
    if not reason.startswith(MISSING_HOST_PREFIX):
        return payload

    out = dict(payload)
    out['error'] = (
        f"No /server route matched /server/{endpoint}, and it is not a device proxy route "
        f"either (those need a host_name). If VirtualPyTest should answer this path, its route "
        f"did not match; if a device should answer it, send host_name. ({reason})"
    )
    out['unmatched_endpoint'] = f'/server/{endpoint}'
    out[FALLBACK_FLAG] = True
    return out