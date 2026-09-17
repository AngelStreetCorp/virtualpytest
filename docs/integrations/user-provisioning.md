# User Provisioning — create users and reset passwords from an external system

**One HTTPS call creates a user, or resets their password, on both VirtualPyTest and Grafana at
once — so a person has the same password everywhere they log in.**

Use this when an external system (an identity manager, an onboarding portal, an intranet) owns
your user accounts and should push them into VirtualPyTest. It is plain HTTP and JSON — no SDK,
no shared framework, callable from any language.

> Looking for the UI instead? Users are managed in-app under **Settings → Users**. This page is
> for automating it from outside.

---

## Your base URL

Every example below starts with `https://your-server.example.com`. **Replace it with your own
installation's address** — there is no single global address for VirtualPyTest, because every
installation runs its own server.

Three ways to find yours:

| Situation | Base URL |
|-----------|----------|
| You have the web app open | The same origin it calls. Open your browser's network tab and look at any `/server/*` request. |
| You have the frontend config | `VITE_SERVER_URL` in `frontend/.env` |
| You are on the same network as the server | `http://<server-host>:5109` — the port is `SERVER_PORT` in the root `.env` (default `5109`) |

Behind a reverse proxy this is your own domain (`https://vpt.yourcompany.com`); on a local or
LAN install it is typically `http://192.168.x.x:5109`. The hosted reference deployment happens to
live at `https://virtualpytest.angelstreet.io`, but that is *one* installation — do not hard-code
it. Make it a configuration value on your side.

If your installation runs **several backend servers**, they share one user database, so any of
them can create the user. Pick the one whose `GRAFANA_URL` points at the Grafana you want users
mirrored into, and always call that one.

---

## Prerequisites

Provisioning needs three things configured in the server's root `.env`. Without them the calls
fail with a clear error rather than silently doing nothing.

| Variable | Why |
|----------|-----|
| `SUPABASE_SERVICE_ROLE_KEY` | Creating and deleting users goes through the Auth Admin API, which the anonymous key cannot do. Missing → `500`, "SUPABASE_SERVICE_ROLE_KEY not configured". |
| `GRAFANA_URL` | Where the server reaches Grafana's admin API, **including any sub-path** (e.g. `http://localhost:3000/grafana`). Only needed for `?grafana=true`. |
| `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` | A Grafana **server** admin. Used as basic auth against Grafana's admin API. |

Grafana must also still have its login form enabled (users log in with a password).

---

## Authentication

Every call carries the service API key as a header:

```
X-API-Key: <your API_KEY>
```

That is `API_KEY` from the server's `.env`. It authenticates as a service principal, which is
treated as admin-equivalent — so no user account or JWT is needed on the calling side.

> **This key is a secret.** It belongs in server-side configuration on the calling system, never
> in a browser, a mobile app, or anything shipped to a client. The same key also drives device
> control, so treat it as full access to the installation.

---

## Create a user

```bash
curl -X POST "https://your-server.example.com/server/users?grafana=true" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "email": "marie.dupont@example.com",
        "password": "a strong password",
        "full_name": "Marie Dupont",
        "group": "QA Team",
        "provider_type": "dmacp"
      }'
```

The `?grafana=true` flag is what also creates the Grafana account. Leave it off and only
VirtualPyTest is written. **Send it every time** unless you deliberately don't want the person to
reach the dashboards.

| Field | Required | Notes |
|-------|----------|-------|
| `email` | yes | The identifier both systems recognise the person by |
| `password` | on create | At least 6 characters |
| `full_name` | no | Defaults to the part before the `@` — `marie.dupont@example.com` becomes `marie.dupont`. See [Names](#the-default-name) |
| `group` | no | Team name, created if it doesn't exist. Omit it and the person lands in the installation's default team. See [Teams](#teams-and-the-default-team) |
| `provider_type` | no | Your platform's name. Defaults to `virtualpytest`. See [Where an account comes from](#where-an-account-comes-from) |

### The default name

`full_name` is the name shown in the users list and on the Grafana account. Send it if you have a
real one. If you don't, you get the email's local part rather than a blank cell — for
`marie.dupont@example.com` that is `marie.dupont`.

A later call **never overwrites a name that is already set**: a reset that doesn't mention
`full_name` leaves whatever is there alone, and only fills it in if it is still blank. So a person
who renames themselves in VirtualPyTest keeps that name across every future reset you send.

Whatever name ends up being used is written to the account itself as well as to VirtualPyTest, so
it is what Supabase's own **Display name** column shows for that user — not a blank.

### Teams and the default team

Every installation has one default team, and a new account is put in it automatically. Send `group`
to place them somewhere else instead: the team is looked up by name and **created if it doesn't
exist**, then the person is added to it and it becomes their primary team.

An auto-created team is created empty — no team-level permission grants, exactly like every other
team including the default one. Team permissions are additive grants on top of a person's role, so
a new team grants nothing by itself and a provisioned account can never come out with more access
than its role allows. If a team is meant to grant something extra, an admin sets that on the team
in the Users page afterwards; provisioning never does it for you.

Note that `group` **adds** a team rather than moving the person out of the default one — they stay
a member of both, and permissions are the union across every team they belong to.

### Where an account comes from

`provider_type` records which platform administers the account. Anything created inside
VirtualPyTest — a UI signup, an admin, our own tooling — is `virtualpytest`. Send your own platform
name (`"provider_type": "dmacp"`) and the account is marked as yours, so it is obvious in the users
list and in the database which side owns a given person.

It is only written when you send it. A password reset that omits it leaves the existing value
alone, so one platform's reset can never quietly reassign another platform's user. Sending it on a
later call *does* reassign the account — that is how you take ownership of one deliberately.

---

## Reset a password

The same operation, addressed to an existing person by email:

```bash
curl -X PUT "https://your-server.example.com/server/users/marie.dupont@example.com?grafana=true" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"password": "the new password"}'
```

This sets the password on **both** systems. The person can log in immediately — there is no
confirmation email step.

**Keep the `-X PUT`.** Without it curl sends a `GET`, which only *reads* the person's status and
never touches the password. That address answers a `GET` with `405` and repeats the call you
meant, so a dropped `-X PUT` can't be mistaken for a successful reset:

```json
{
  "status": "error",
  "error": "method_not_allowed",
  "detail": "GET only reads this user's status and never changes a password. To set the password, use: PUT /server/users/marie.dupont@example.com?grafana=true with body {\"password\": \"...\"}."
}
```

Resetting a password **never changes the person's role or permissions.**

`PUT` also creates the user if they don't exist yet, so if your side treats "set password" as one
operation you can use it for both onboarding and reset and ignore `POST` entirely.

---

## Edit a user without touching their password

The same `PUT`, with no `password` field. Send only what you want to change:

```bash
curl -X PUT "https://your-server.example.com/server/users/marie.dupont@example.com?grafana=true" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "full_name": "Marie Dupont",
        "provider_type": "dmacp",
        "group": "QA Team"
      }'
```

All three fields are independent — send one, two or all of them. Their password is left exactly as
it was, and so is anything you don't mention.

`password` is only **required** when the person doesn't exist yet, because then the call has to
create them. Editing someone who isn't there yet returns:

```json
{ "status": "error", "error": "invalid_payload", "detail": "password is required to create a user" }
```

Two things this route deliberately will not do:

- **Change their role or permissions.** VirtualPyTest owns those; an admin sets them in the Users
  page. A provisioning call never changes them, on purpose.
- **Remove them from a team.** `group` adds a team and makes it their primary one. Taking someone
  out of a team is an admin action in the Users page, or `DELETE` the user entirely.

---

## What you get back

```json
{
  "status": "ok",
  "action": "updated",
  "email": "marie.dupont@example.com",
  "user_id": "7fdb81c8-b5de-46fd-aaa4-cd9cbc5a5a8d",
  "platform": {
    "role": "viewer",
    "team": "QA Team",
    "full_name": "marie.dupont",
    "provider_type": "dmacp"
  },
  "grafana":  { "user_id": 3, "org_role": "Viewer" }
}
```

| Field | Meaning |
|-------|---------|
| `action` | `created` for a new person, `updated` for an existing one. Useful for your own audit log. |
| `platform` | Their role, team, name and `provider_type` inside VirtualPyTest — the values as stored after the call, so you can confirm the defaults that were applied. |
| `grafana` | Confirms the Grafana account was written. **If this key is absent, the Grafana half did not run** — check that you sent `?grafana=true`. |

---

## Remove a user

```bash
curl -X DELETE "https://your-server.example.com/server/users/marie.dupont@example.com?grafana=true" \
  -H "X-API-Key: $API_KEY"
```

```json
{ "status": "ok", "action": "deleted", "email": "marie.dupont@example.com" }
```

`action` is `deleted` if the person existed, or `absent` if they were already gone — both return
`200`. Deleting someone twice is harmless, so a retry after a network failure is safe.

### What it removes

| Removed | Kept |
|---------|------|
| The VirtualPyTest login and profile — role, permissions, team membership | Test results, campaign runs, reports and any other history they produced |
| Their active sessions (they are signed out everywhere) | |
| The Grafana account, **only if you sent `?grafana=true`** | Dashboards they created in Grafana — those belong to the organisation, not the person |

History is kept on purpose: results belong to the team, not to the person who launched them, so
removing someone never erases the record of what was tested. Deleting a user is about **access**,
not about data.

### Order of operations, and what a failure means

VirtualPyTest is deleted first, Grafana second. If the Grafana step fails you get a `502` — and by
then the VirtualPyTest account is **already gone**. Retry the same call: the VirtualPyTest half
reports `absent` and the Grafana half completes.

Until that retry succeeds the person still has a working Grafana login, so treat a `502` on delete
as an **unfinished offboarding**, not a completed one.

### Confirm it worked

For anything access-sensitive — an employee leaving, a revoked contractor — verify rather than
trust the status code:

```bash
curl "https://your-server.example.com/server/users/marie.dupont@example.com" \
  -H "X-API-Key: $API_KEY"
# expect: {"status":"ok","exists":false,...}
```

### There is no "disable"

Delete is permanent and there is no suspend or deactivate. Lowering someone's role to `viewer`
restricts what they can do but still lets them log in, so it is not a substitute for removing
access. If you need reversible suspension, that belongs in the system that owns identity — stop
provisioning them and delete here.

### Deleting by internal ID

The in-app Users page deletes by internal user ID instead of email:

```
DELETE /server/users/{user_id}
```

External systems should use the email form — email is the identifier you already hold, and it is
stable across both systems.

---

## The rest of the operations

All four take the same `X-API-Key` header and the same `?grafana=true` flag.

| To do this | Call | Body |
|------------|------|------|
| Create a user | `POST /server/users` | `email`, `password`, `full_name`, `group`, `provider_type` |
| Reset a password | `PUT /server/users/{email}` | `password`, `provider_type` |
| Edit without touching the password | `PUT /server/users/{email}` | any of `full_name`, `provider_type`, `group` |
| Check whether someone exists | `GET /server/users/{email}` | — |
| Remove a user | `DELETE /server/users/{email}` | — |

`GET` returns `200 {"exists": false}` for an unknown person — **not** a `404`. You never need to
call it before creating or resetting (both handle either case); it exists for audit screens on
the calling side.

---

## Teams and permissions, by email

These three take an **email or an internal user ID** in the path, so an external system never has
to resolve a UUID first.

| To do this | Call |
|------------|------|
| Add someone to a team | `POST /server/users/{email}/assign-team` — body `{"team_id": "..."}` |
| Remove someone from a team | `POST /server/users/{email}/remove-team` — body `{"team_id": "..."}` |
| Read what someone can do | `GET /server/users/{email}/permissions` |

An unknown email returns `404`.

> **Joining a team by name is easier.** `assign-team` needs a team **id**, not a name. If all you
> have is the team's name, send `group` on the normal create/reset call instead — it creates the
> team if needed and joins the person in one step:
>
> ```bash
> curl -X PUT "https://your-server.example.com/server/users/marie.dupont@example.com" \
>   -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
>   -d '{"group": "QA Team"}'
> ```
>
> Use `assign-team` only when you already hold the id — `GET /server/teams` lists them.

The permissions call returns the effective breakdown, which is useful for showing someone's real
access in your own admin screen rather than guessing from the role:

```json
{
  "success": true,
  "user_id": "7fdb81c8-b5de-46fd-aaa4-cd9cbc5a5a8d",
  "role": "tester",
  "role_permissions": ["dashboard:view", "campaigns:execute", "..."],
  "team_permissions": [],
  "individual_grants": [],
  "denied_permissions": [],
  "effective": ["campaigns:execute", "dashboard:view", "..."]
}
```

`effective` is what actually applies — role defaults plus team and individual grants, minus
anything explicitly revoked.

---

## Who decides what

Ownership is split, and agreeing on it early avoids a lot of confusion about which team handles
which support request.

**The external system owns identity:**
- Email address — the permanent identifier that links the two systems
- Password, and every reset of it
- Full name
- Group

**VirtualPyTest owns access:**
- The person's **role**
- What they can see and do
- Any individually granted or revoked permissions

The practical consequence: **a newly provisioned person can log in everywhere immediately, but
starts as a `viewer` — read-only.** Somebody with admin rights inside VirtualPyTest raises them to
`tester` or `admin`. The external system never sends a role, and password resets leave the role
untouched.

---

## What a user can see, after the account exists

Access is decided by **role**, which is set in VirtualPyTest and mirrored automatically into
Grafana — so the two never drift apart.

| Role | In VirtualPyTest | In Grafana |
|------|------------------|------------|
| `viewer` *(default for new users)* | Read-only: dashboard, test cases, campaigns, reports, monitoring. Cannot run or change anything. | **Viewer** — reads dashboards |
| `tester` | Everything a viewer has, plus running tests and campaigns, building them, device control, the AI agent, Jira | **Editor** — can edit dashboards |
| `admin` | Everything, including user management and settings | **Admin** — manages the organisation |

The mapping is configurable in `backend_server/config/integrations/grafana_config.json`
(`grafana_role_by_role`, `default_role`, `grafana_org_id`).

On top of the role, an administrator can grant an individual extra permissions or explicitly
revoke one. The effective result is:

```
what a person can do  =  ( role  +  group grants  +  individual grants )  −  anything explicitly revoked
```

> ### ⚠️ `group` is a label, not a data boundary
>
> The `group` you send names a team and places the person in it, but **it does not partition what
> they can see.** Everyone on a given installation sees that installation's test results,
> regardless of group. If you need genuinely separated data per customer or per business unit,
> that is a separate installation — not a group. Worth stating up front so nobody designs around
> the wrong assumption.

---

## Rules to build against

- **Every call is safe to repeat.** Sending the same create or reset twice changes nothing the
  second time. Deleting someone already gone returns `200`. Retrying after a network failure is
  always safe.
- **Email is permanent.** It is how the two systems recognise the same person. Changing an email
  means delete + create, not an edit.
- **Passwords need at least 6 characters** — the minimum enforced by the login store.
- **Create the account before first login.** There is no cold-start path where someone logs in and
  gets provisioned on the way through.

---

## Errors

| Code | Meaning | What to do |
|------|---------|------------|
| `400` | Missing or invalid input — usually no email, a password under 6 characters, or a blank `provider_type` | Fix the payload; retrying as-is won't help |
| `401` | API key missing or wrong | Check your configuration |
| `403` | The key authenticated but isn't allowed here | Confirm you're sending `API_KEY`, not a user token |
| `405` | A `GET` on `/server/users/{email}` carried a password or `?grafana=`, i.e. a write addressed to the read-only status check | Send the same call as a `PUT` — usually a missing `-X PUT` in curl |
| `500` | Either `SUPABASE_SERVICE_ROLE_KEY` is not configured, or the `group` could not be created/joined | Read `detail`. For a config problem see [Prerequisites](#prerequisites); for a group problem **retry** — see the note below |
| `502` | VirtualPyTest was updated, but Grafana could not be reached | **Retry the same call.** The password is already live on VirtualPyTest; the retry finishes the Grafana half |

### A `500` on a call that sent `group`

The user and password are written **before** the group is applied, so a `500` naming the group
means the person exists with the new password but was not placed in the team. Retry the same call:
the user half is a no-op the second time and the group is applied.

This is reported rather than ignored on purpose. Previously a group that could not be created was
silently dropped and the call still returned `200` with `"team": null` — so the caller believed the
group had been applied when it never was.

A `502` means "half done", not "failed". Because every call is a safe repeat, queueing it and
sending the identical request again converges. It is the only error worth building retry logic
around.

---

## Mirroring into Grafana on its own

Normally you never call Grafana directly — the user routes above do it for you. For the rare case
where the two have drifted apart (for example a `502` you never retried), the mirror is also
exposed on its own:

| Call | Purpose |
|------|---------|
| `POST /server/integrations/grafana/users` | Create or update the Grafana account (`email`, `password`, `full_name`, `org_role`, `org_id`) |
| `PATCH /server/integrations/grafana/users/{email}/org-role` | Re-push only the role |
| `DELETE /server/integrations/grafana/users/{email}` | Remove the Grafana account |

These touch **only** Grafana — they do not create or change a VirtualPyTest user.

---

## Before going live

- **Get the API key** to the calling system over a secure channel, into server-side config.
- **Confirm network access.** Access to `/server/*` may be restricted to known IP addresses; if so,
  the calling system's outbound address has to be allowed or every call fails.
- **Decide who the first admin is**, so somebody can raise other people's roles from day one.

---

## Related

- [API Reference](../api/README.md) — full endpoint reference with interactive Swagger UI
- [Integrations overview](README.md)
- [Grafana dashboards](../features/analytics.md)
