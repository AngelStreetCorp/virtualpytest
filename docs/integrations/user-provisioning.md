# User Provisioning — create users and reset passwords from an external system

**One call creates a user, or resets their password, on both VirtualPyTest and Grafana. The person then has the same password in both.**

Use this when another system (an identity manager, an intranet) owns your users. Any language that can send a web request works.

> You can also manage users in the app under **Settings → Users**. This page is for automating it from outside.

---

## Your base URL

Each call goes to your own VirtualPyTest server. The examples on this page use `https://your-server.example.com`. Replace it with your server's address.

<div data-technical>

Behind a reverse proxy this is your own domain (`https://vpt.yourcompany.com`); on a local or LAN install it is typically `http://192.168.x.x:5109`.

The hosted reference deployment lives at `https://virtualpytest.angelstreet.io`, but that is one installation. Do not hard-code it.

Three ways to find your address:

| Situation | Base URL |
|-----------|----------|
| You have the web app open | The same origin it calls. Open your browser's network tab and look at any `/server/*` request. |
| You have the frontend config | `VITE_SERVER_URL` in `frontend/.env` |
| You are on the same network as the server | `http://<server-host>:5109`. The port is `SERVER_PORT` in the root `.env` (default `5109`). |

</div>

If your installation runs several backend servers, they share one user database. Call the one whose Grafana you want users added to.

<div data-technical>

Pick the server whose `GRAFANA_URL` points at the Grafana you want users mirrored into, and always call that one.

</div>

---

## Prerequisites

Three settings must be on the server. If one is missing, the call fails with a clear error. Grafana's login form must also stay on, because people log in with a password.

<div data-technical>

Set these in the server's root `.env`:

| Variable | Why |
|----------|-----|
| `SUPABASE_SERVICE_ROLE_KEY` | Creating and deleting users goes through the Auth Admin API, which the anonymous key cannot do. Missing → `500`, "SUPABASE_SERVICE_ROLE_KEY not configured". |
| `GRAFANA_URL` | Where the server reaches Grafana's admin API, **including any sub-path** (e.g. `http://localhost:3000/grafana`). Only needed for `?grafana=true`. |
| `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` | A Grafana **server** admin. Used as basic auth against Grafana's admin API. |

Grafana must also still have its login form enabled (users log in with a password).

</div>

---

## Authentication

Every call sends a service key in a header. The key is a secret with full admin rights on the installation. Keep it on your server only, never in a browser, a mobile app or anything a client can see. You need no user login.

<div data-technical>

```
X-API-Key: <your API_KEY>
```

That is `API_KEY` from the server's `.env`. It authenticates as a service principal, which is treated as admin-equivalent, so no user account or JWT is needed on the calling side.

The key is a secret. It belongs in server-side configuration on the calling system, never in a browser, a mobile app or anything shipped to a client. The same key also drives device control, so treat it as full access to the installation.

</div>

---

## Create a user

Send the person's details to the users address with `?grafana=true`, which also creates their Grafana account. Always add it. Only the email is always required. A password is required for a new person.

<div data-technical>

```bash
curl -X POST "https://your-server.example.com/server/users?grafana=true" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "email": "marie.dupont@example.com",
        "password": "a strong password",
        "full_name": "Marie Dupont",
        "team": "QA Team",
        "role": "DevUser",
        "provider_type": "idp"
      }'
```

The `?grafana=true` flag is what also creates the Grafana account. Leave it off and only VirtualPyTest is written. **Send it every time** unless you deliberately don't want the person to reach the dashboards.

| Field | Required | Notes |
|-------|----------|-------|
| `email` | yes | The identifier both systems recognise the person by |
| `password` | on create | At least 6 characters |
| `full_name` | no | Defaults to the part before the `@`. `marie.dupont@example.com` becomes `marie.dupont`. See [Names](#the-default-name) |
| `role` | no | The person's role: your own name for it (`"DevUser"`) or VirtualPyTest's (`"developer"`). Omit it and a new account gets the installation's default role. See [Roles](#roles) |
| `team` | no | Team name, created if it doesn't exist. Omit it and the person lands in the installation's default team. `group` is the same field under its older name. See [Teams](#teams-and-the-default-team) |
| `replace_teams` | no | `true` also takes the person out of every other team, so `team` *moves* them. Needs `team`. |
| `provider_type` | no | Your platform's name. Defaults to `virtualpytest`. See [Where an account comes from](#where-an-account-comes-from) |

</div>

### The default name

The name shown in the users list and on the Grafana account. If you send none, the name is the part of the email before the `@`, so `marie.dupont@example.com` shows as `marie.dupont`. A later call never overwrites a name that is already set.

<div data-technical>

A later call **never overwrites a name that is already set**: a reset that doesn't mention `full_name` leaves whatever is there alone, and only fills it in if it is still blank. So a person who renames themselves in VirtualPyTest keeps that name across every future reset you send.

Whatever name ends up being used is written to the account itself as well as to VirtualPyTest, so it is what Supabase's own **Display name** column shows for that user, not a blank.

</div>

### Roles

VirtualPyTest has five roles, from most to least powerful: `admin`, `manager`, `developer`, `tester` and `viewer`. An admin can give each role its own name on the **Roles** page. Send the name your platform uses.

Anyone with the server key can set any role, including `admin`. Guard that key carefully.

<div data-technical>

VirtualPyTest has five roles, from most to least privileged: `admin`, `manager`, `developer`, `tester`, `viewer`. Each has one **preferred name**, set by an admin on the **Roles** page. That is the name the app shows, and the name your platform sends. If your platform calls its top role `SuperAdmin`, the admin renames `admin` to `SuperAdmin` and you send:

```json
{ "role": "SuperAdmin" }
```

- Matching ignores case and surrounding spaces. The role id itself (`"admin"`) is always accepted too.
- Preferred names are unique, so a name always means one role. `provider_type` plays no part.
- An unknown name changes nothing and answers `400`, listing every name that would be accepted.
- A call made with the server API key may set **any** role, `admin` included. Treat the key accordingly.
- Changing the role also updates the person's Grafana org role when you send `?grafana=true`.

</div>

### Teams and the default team

New accounts join the default team. Send a team name to put the person elsewhere; the team is created if needed. A team never grants access on its own. To move them out of the default team, send `replace_teams`.

<div data-technical>

Every installation has one default team, and a new account is put in it automatically. Send `team` (or its older name `group`) to place them somewhere else instead: the team is looked up by name and **created if it doesn't exist**, then the person is added to it and it becomes their primary team.

An auto-created team has no limit. A team never grants anything: what a person can do comes from their role (and any individual grants an admin adds), and a team can only *cap* it. An admin may set a permission limit and a device limit on the team afterwards. So a provisioned account can never come out with more access than its role allows.

Note that `team` **adds** a team rather than moving the person out of the default one. They stay a member of both. Team limits add up across every team they belong to, the default team counting only when it is their only one. Send `"replace_teams": true` with it to *move* them instead: they are removed from every other team, the default one included.

</div>

### Where an account comes from

Send your platform's name as `provider_type` to mark the account as yours. Accounts created inside VirtualPyTest are marked `virtualpytest`. A password reset that leaves it out does not change the owner.

<div data-technical>

`provider_type` records which platform administers the account. Anything created inside VirtualPyTest (a UI signup, an admin, our own tooling) is `virtualpytest`. Send your own platform name (`"provider_type": "idp"`) and the account is marked as yours, so it is obvious in the users list and in the database which side owns a given person.

It is only written when you send it. A password reset that omits it leaves the existing value alone, so one platform's reset can never quietly reassign another platform's user. Sending it on a later call *does* reassign the account. That is how you take ownership of one deliberately.

</div>

---

## Reset a password

Use the same address, with the person's email in the path, and the `PUT` method. The new password is set on both systems at once, so the person can log in straight away. There is no confirmation email.

Always use `PUT`. A `GET` only reads the person's status and never changes the password.

<div data-technical>

```bash
curl -X PUT "https://your-server.example.com/server/users/marie.dupont@example.com?grafana=true" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"password": "the new password"}'
```

This sets the password on **both** systems. The person can log in immediately — there is no confirmation email step.

**Keep the `-X PUT`.** Without it curl sends a `GET`, which only *reads* the person's status and never touches the password. That address answers a `GET` with `405` and repeats the call you meant, so a dropped `-X PUT` can't be mistaken for a successful reset:

```json
{
  "status": "error",
  "error": "method_not_allowed",
  "detail": "GET only reads this user's status and never changes a password. To set the password, use: PUT /server/users/marie.dupont@example.com?grafana=true with body {\"password\": \"...\"}."
}
```

Resetting a password **never changes the person's role or permissions** unless you also send `role` in the same call.

`PUT` also creates the user if they don't exist yet, so if your side treats "set password" as one operation you can use it for both onboarding and reset and ignore `POST` entirely.

</div>

A reset does not change the role unless you send `role`. `PUT` also creates a missing user.

---

## Edit a user without touching their password

Use the same `PUT`, but leave out `password`. Send only the fields you want to change. Anything you leave out stays as it is.

Editing someone who does not exist yet fails, because the call would have to create them. It needs a password for that.

<div data-technical>

The same `PUT`, with no `password` field. Send only what you want to change:

```bash
curl -X PUT "https://your-server.example.com/server/users/marie.dupont@example.com?grafana=true" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "full_name": "Marie Dupont",
        "provider_type": "idp",
        "role": "SuperUser",
        "team": "QA Team",
        "replace_teams": true
      }'
```

Every field is independent — send only the ones you want to change. Their password is left exactly as it was, and so is anything you don't mention.

`password` is only **required** when the person doesn't exist yet, because then the call has to create them. Editing someone who isn't there yet returns:

```json
{ "status": "error", "error": "invalid_payload", "detail": "password is required to create a user" }
```

</div>

This route does not change individual permissions. An admin sets those on the Users page.

<div data-technical>

What this route deliberately will not do: **change individual permissions.** The role decides what someone can do; per-person extra grants and denials are set by an admin on the Users page.

</div>

---

## What you get back

A successful call returns the stored result. Use it for your audit log. If the `grafana` part is missing, the Grafana account was not written: check that you sent `?grafana=true`.

<div data-technical>

```json
{
  "status": "ok",
  "action": "updated",
  "email": "marie.dupont@example.com",
  "user_id": "7fdb81c8-b5de-46fd-aaa4-cd9cbc5a5a8d",
  "platform": {
    "role": "developer",
    "teams": ["Default Team", "QA Team"],
    "team": "QA Team",
    "full_name": "marie.dupont",
    "provider_type": "idp"
  },
  "grafana":  { "user_id": 3, "org_role": "Viewer" }
}
```

| Field | Meaning |
|-------|---------|
| `action` | `created` for a new person, `updated` for an existing one. Useful for your own audit log. |
| `platform` | Their role (VirtualPyTest's id), every team they are in, their primary `team`, name and `provider_type`. These are the values as stored after the call, so you can confirm the defaults that were applied. |
| `grafana` | Confirms the Grafana account was written. **If this key is absent, the Grafana half did not run.** Check that you sent `?grafana=true`. |

</div>

---

## Remove a user

Send a `DELETE` to the person's email. Their login is removed and they are signed out. Grafana is removed only if you sent `?grafana=true`. Their test results and reports are kept. Retrying is safe.

<div data-technical>

```bash
curl -X DELETE "https://your-server.example.com/server/users/marie.dupont@example.com?grafana=true" \
  -H "X-API-Key: $API_KEY"
```

```json
{ "status": "ok", "action": "deleted", "email": "marie.dupont@example.com" }
```

`action` is `deleted` if the person existed, or `absent` if they were already gone — both return `200`. Deleting someone twice is harmless, so a retry after a network failure is safe.

| Removed | Kept |
|---------|------|
| The VirtualPyTest login and profile — role, permissions, team membership | Test results, campaign runs, reports and any other history they produced |
| Their active sessions (they are signed out everywhere) | |
| The Grafana account, **only if you sent `?grafana=true`** | Dashboards they created in Grafana — those belong to the organisation, not the person |

History is kept on purpose: results belong to the team, not to the person who launched them, so removing someone never erases the record of what was tested. Deleting a user is about **access**, not about data.

</div>

### Order of operations, and what a failure means

VirtualPyTest is cleaned up first, then Grafana. A `502` means the Grafana part is unfinished: retry the same call.

<div data-technical>

VirtualPyTest is deleted first, Grafana second. If the Grafana step fails you get a `502` — and by then the VirtualPyTest account is **already gone**. Retry the same call: the VirtualPyTest half reports `absent` and the Grafana half completes.

Until that retry succeeds the person still has a working Grafana login, so treat a `502` on delete as an **unfinished offboarding**, not a completed one.

</div>

### Confirm it worked

For access that must end, ask the server whether the person still exists.

<div data-technical>

For anything access-sensitive — an employee leaving, a revoked contractor — verify rather than trust the status code:

```bash
curl "https://your-server.example.com/server/users/marie.dupont@example.com" \
  -H "X-API-Key: $API_KEY"
# expect: {"status":"ok","exists":false,...}
```

</div>

### There is no "disable"

Removing a user is permanent, and there is no suspend. A `viewer` role still lets them log in. For a reversible pause, stop provisioning them in the system that owns the identity.

<div data-technical>

Delete is permanent and there is no suspend or deactivate. Lowering someone's role to `viewer` restricts what they can do but still lets them log in, so it is not a substitute for removing access. If you need reversible suspension, that belongs in the system that owns identity — stop provisioning them and delete here.

</div>

### Deleting by internal ID

Use the email form. The Users page in the app deletes by internal user ID instead.

<div data-technical>

The in-app Users page deletes by internal user ID instead of email:

```
DELETE /server/users/{user_id}
```

External systems should use the email form — email is the identifier you already hold, and it is stable across both systems.

</div>

---

## The rest of the operations

All operations use the same `X-API-Key` header and `?grafana=true` flag. You never need to check if someone exists first.

<div data-technical>

| To do this | Call | Body |
|------------|------|------|
| Create a user | `POST /server/users` | `email`, `password`, `full_name`, `group`, `provider_type` |
| Reset a password | `PUT /server/users/{email}` | `password`, `provider_type` |
| Edit without touching the password | `PUT /server/users/{email}` | any of `full_name`, `provider_type`, `group` |
| Check whether someone exists | `GET /server/users/{email}` | — |
| Remove a user | `DELETE /server/users/{email}` | — |

`GET` returns `200 {"exists": false}` for an unknown person — **not** a `404`. You never need to call it before creating or resetting (both handle either case); it exists for audit screens on the calling side.

</div>

---

## Teams and permissions, by email

These calls take an **email or an internal user ID**. To join a team by name, send `group` on the create or reset call. To see what someone can really do, read their permissions.

<div data-technical>

These three take an **email or an internal user ID** in the path, so an external system never has to resolve a UUID first.

| To do this | Call |
|------------|------|
| Add someone to a team | `POST /server/users/{email}/assign-team` — body `{"team_id": "..."}` |
| Remove someone from a team | `POST /server/users/{email}/remove-team` — body `{"team_id": "..."}` |
| Read what someone can do | `GET /server/users/{email}/permissions` |

An unknown email returns `404`.

**Joining a team by name is easier.** `assign-team` needs a team **id**, not a name. If all you have is the team's name, send `group` on the normal create/reset call instead — it creates the team if needed and joins the person in one step:

> ```bash
> curl -X PUT "https://your-server.example.com/server/users/marie.dupont@example.com" \
>   -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
>   -d '{"group": "QA Team"}'
> ```

Use `assign-team` only when you already hold the id — `GET /server/teams` lists them.

The permissions call returns the effective breakdown, which is useful for showing someone's real access in your own admin screen rather than guessing from the role:

```json
{
  "success": true,
  "user_id": "7fdb81c8-b5de-46fd-aaa4-cd9cbc5a5a8d",
  "role": "tester",
  "role_permissions": ["dashboard:view", "campaigns:execute", "..."],
  "team_ceiling": null,
  "individual_grants": [],
  "denied_permissions": [],
  "effective": ["campaigns:execute", "dashboard:view", "..."]
}
```

`effective` is what actually applies — role defaults plus team and individual grants, minus anything explicitly revoked.

</div>

---

## Who decides what

**Your system owns identity:** the email, the password and resets, the full name, the team and the role if you send one. A new person without a role starts as `viewer`.

**VirtualPyTest owns the rest of access:** what each role can do, and extra permissions for one person.

---

## What a user can see, after the account exists

Access is decided by **role**. It is copied to Grafana automatically, so the two match.

| Role | In VirtualPyTest | In Grafana |
|------|------------------|------------|
| `viewer` *(default for new users)* | Read-only: dashboards, test cases, campaigns, reports and monitoring | Viewer |
| `tester` | Runs tests and campaigns, builds them, controls devices, uses the AI agent | Viewer |
| `developer` | Everything a tester can do, plus building and editing navigation trees | Viewer |
| `manager` | Everything a developer can do, plus managing people in their own teams | Viewer |
| `admin` | Everything, including user management and settings | Admin |

<div data-technical>

Full detail for each role:

| Role | In VirtualPyTest | In Grafana |
|------|------------------|------------|
| `viewer` *(default for new users)* | Read-only: dashboard, test cases, campaigns, reports, monitoring. Cannot run or change anything. | **Viewer** — reads dashboards |
| `tester` | Everything a viewer has, plus running tests and campaigns, building them, device control, the AI agent, Jira | **Viewer** — reads dashboards, only their own devices |
| `developer` | Everything a tester has, plus building and editing navigation trees | **Viewer** |
| `manager` | Everything a developer has, plus managing the people and team members **of their own teams**. Never roles, server settings, deployments or other teams | **Viewer** |
| `admin` | Everything, including user management and settings | **Admin** — manages the organisation |

These are the default permission sets. An installation can adjust each role on its Roles page, and shows the roles under its own names.

The mapping is configurable in `backend_server/config/integrations/grafana_config.json` (`grafana_role_by_role`, `default_role`, `grafana_org_id`).

On top of the role, an administrator can grant an individual extra permissions or explicitly revoke one. The effective result is:

```
what a person can do  =  ( role  +  group grants  +  individual grants )  −  anything explicitly revoked
```

</div>

An admin can also grant or revoke single permissions for one person.

> ### `group` is a label, not a data boundary
>
> The `group` you send places the person in a team, but it does not limit what they can see. Everyone on one installation sees that installation's test results. For data kept apart per customer, use a separate installation.

<div data-technical>

The `group` you send names a team and places the person in it, but it does not limit what they can see. Everyone on one installation sees that installation's test results, whatever their group. If you need data kept apart per customer or per business unit, use a separate installation, not a group. Decide this up front, so nobody designs around the wrong assumption.

</div>

---

## Rules to build against

- **Every call is safe to repeat.** Sending the same create or reset twice changes nothing the second time.
- **Email is permanent.** To change someone's email, delete and create them.
- **Passwords need at least 6 characters.**
- **Create the account before the first login.**

<div data-technical>

- **Every call is safe to repeat.** Sending the same create or reset twice changes nothing the second time. Deleting someone already gone returns `200`. Retrying after a network failure is always safe.
- **Email is permanent.** It is how the two systems recognise the same person. Changing an email means delete + create, not an edit.
- **Passwords need at least 6 characters** — the minimum enforced by the login store.
- **Create the account before first login.** There is no cold-start path where someone logs in and gets provisioned on the way through.

</div>

---

## Errors

Most errors are a fix on your side. Retry only the `502`, and the `500` that names a group.

| Code | What it means |
|------|---------------|
| `400` | Something in the request is missing or invalid. Fix the request. Retrying the same request will not help. |
| `401` | The key is missing or wrong. Check your configuration. |
| `403` | The key is valid but not allowed to do this. Check that you send the service key, not a user's login token. |
| `405` | A `GET` was sent where a write was meant. Send the call as a `PUT`. |
| `500` | A server setting is missing, or the team could not be created or joined. Read the message. |
| `502` | VirtualPyTest was updated, but Grafana could not be reached. Retry the same call. |

<div data-technical>

| Code | Meaning | What to do |
|------|---------|------------|
| `400` | Missing or invalid input — usually no email, a password under 6 characters, a blank `provider_type`, a `role` nobody recognises (`detail` lists the accepted names), or `replace_teams` without a `team` | Fix the payload; retrying as-is won't help |
| `401` | API key missing or wrong | Check your configuration |
| `403` | The key authenticated but isn't allowed here | Confirm you're sending `API_KEY`, not a user token |
| `405` | A `GET` on `/server/users/{email}` carried a password or `?grafana=`, i.e. a write addressed to the read-only status check | Send the same call as a `PUT` — usually a missing `-X PUT` in curl |
| `500` | Either `SUPABASE_SERVICE_ROLE_KEY` is not configured, or the `group` could not be created/joined | Read `detail`. For a config problem see [Prerequisites](#prerequisites); for a group problem **retry** — see the note below |
| `502` | VirtualPyTest was updated, but Grafana could not be reached | **Retry the same call.** The password is already live on VirtualPyTest; the retry finishes the Grafana half |

</div>

### A `500` on a call that sent `group`

The user and password are saved before the team is applied. A `500` that names the group means the person exists with the new password but is not in the team yet. Retry the same call. The user part does nothing the second time, and the team is applied.

A `502` means "half done", not "failed". Sending the same request again finishes the job.

<div data-technical>

The user and password are written **before** the group is applied, so a `500` naming the group means the person exists with the new password but was not placed in the team. Retry the same call: the user half is a no-op the second time and the group is applied.

This is reported rather than ignored on purpose. Previously a group that could not be created was silently dropped and the call still returned `200` with `"team": null` — so the caller believed the group had been applied when it never was.

A `502` means "half done", not "failed". Because every call is a safe repeat, queueing it and sending the identical request again converges. It is the only error worth building retry logic around.

</div>

---

## Mirroring into Grafana on its own

You normally never call Grafana directly. If the two drift apart, you can mirror only the Grafana side. These calls change only Grafana.

<div data-technical>

Normally you never call Grafana directly — the user routes above do it for you. For the rare case where the two have drifted apart (for example a `502` you never retried), the mirror is also exposed on its own:

| Call | Purpose |
|------|---------|
| `POST /server/integrations/grafana/users` | Create or update the Grafana account (`email`, `password`, `full_name`, `org_role`, `org_id`) |
| `PATCH /server/integrations/grafana/users/{email}/org-role` | Re-push only the role |
| `DELETE /server/integrations/grafana/users/{email}` | Remove the Grafana account |

These touch **only** Grafana — they do not create or change a VirtualPyTest user.

</div>

---

## Before going live

- Give the API key to the calling system over a secure channel.
- Check network access. If calls to `/server/*` are limited to known IP addresses, the calling system's address must be allowed.
- Decide who the first admin is.

<div data-technical>

- **Get the API key** to the calling system over a secure channel, into server-side config.
- **Confirm network access.** Access to `/server/*` may be restricted to known IP addresses; if so, the calling system's outbound address has to be allowed or every call fails.
- **Decide who the first admin is**, so somebody can raise other people's roles from day one.

</div>

---

## Related

- [API Reference](../api/README.md): full endpoint reference with interactive Swagger UI
- [Integrations overview](README.md)
- [Grafana dashboards](../features/analytics.md)
