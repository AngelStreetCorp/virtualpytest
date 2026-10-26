# Supabase Authentication Setup Guide

This guide shows how to set up user sign-in for VirtualPyTest with Supabase.

## Overview

Sign-in is **optional**. Users can sign in with email and password, Google or GitHub. Each user gets a role (admin, tester or viewer) that decides what they can do.

Whether users must sign in is set on the server. A new install starts with no sign-in. See [supabase.md](supabase.md#authentication-open-mode-or-login) to switch.

<div data-technical>

The switch is `SERVER_OPEN_MODE` together with `SUPABASE_JWT_SECRET`. Fresh installs start in open mode (no login).

</div>

## Prerequisites

- **Optional**: a Supabase account ([supabase.com](https://supabase.com))
- **Optional**: a Google Cloud Console account (for Google sign-in)
- **Optional**: a GitHub account (for GitHub sign-in)

## 1. Create a Supabase project

Go to [app.supabase.com](https://app.supabase.com), click **"New Project"**, and fill in the details. Wait about two minutes.

<div data-technical>

Name: VirtualPyTest, or any name. Database password: a strong one. Region: the one closest to your users. Then click **"Create new project"**.

</div>

## 2. Get the Supabase credentials

1. In your Supabase project, go to **Settings**, then **API**
2. Copy the **Project URL** and the **anon / public key**
3. Add them to the frontend's settings file

<div data-technical>

Example values: the Project URL looks like `https://xxxxx.supabase.co`, and the anon key starts with `eyJ...`.

In `frontend/.env`:

```env
# Add these to enable authentication:
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGc...your-anon-key
```

</div>

**Note:** if you leave these out, the app runs without sign-in, and every page is public.

## 3. Create the database tables

If you already set up the full database as described in [Supabase and authentication](./supabase.md), this step is done. We recommend that route.

<div data-technical>

Run `./setup/db/apply_schema.sh`. It includes `setup/db/schema/018_supabase_auth_schema.sql`, which creates `profiles`, the `handle_new_user()` signup trigger, admin RLS policies, and `is_admin()`.

</div>

**Adding sign-in to an install that skipped it:** apply just that one file. It stands on its own, so it is safe to run before `019_team_members.sql`.

<div data-technical>

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f setup/db/schema/018_supabase_auth_schema.sql
```

You can also copy the file's contents into the Supabase dashboard's **SQL Editor** and click **Run**. Always use the current file, not an older copy from somewhere else. The security rules and trigger functions in it have changed over time (most recently to add a nullable `team_id`).

</div>

The file creates a `profiles` table linked to the sign-in accounts. It gives each new user the `viewer` role and limits admin-only rules to admins.

<div data-technical>

What this does:

- Creates a `profiles` table linked to `auth.users`, with a nullable `team_id`
- Creates a profile on signup, and adds the user to the default team once `team_members` exists
- Gives every new user the `viewer` role by default
- Turns on Row Level Security, with admin-only rules through `is_admin()`

</div>

## 4. Turn on email and password sign-in

Email sign-in is on by default in **Authentication**, then **Providers**. Users can then sign up, sign in and reset a forgotten password.

<div data-technical>

Make sure the **Email** provider is **enabled**. Optional: customise the emails for account verification.

</div>

## 5. Set up Google sign-in (optional)

### 5.1 Create Google credentials

1. In the [Google Cloud Console](https://console.cloud.google.com), create an OAuth client ID under **APIs & Services**, then **Credentials**
2. Copy the **Client ID** and the **Client Secret**

<div data-technical>

Steps: click **"Create Credentials"**, then **"OAuth client ID"**. If asked, set up the consent screen with your email and the app name **VirtualPyTest**. Create the client as a **Web application** named **VirtualPyTest**, and set the authorized redirect URI to the address below.

Consent screen: user type **External**, app name **VirtualPyTest**, user support email and developer contact both your email.

Authorized redirect URI:

```
https://your-project.supabase.co/auth/v1/callback
```

</div>

### 5.2 Add them to Supabase

Turn on **Google** under **Authentication**, then **Providers**. Paste the Client ID and Client Secret, and save. Google sign-in is optional.

## 6. Set up GitHub sign-in (optional)

### 6.1 Create a GitHub OAuth app

1. In [GitHub Settings](https://github.com/settings/developers), create a new OAuth app named **VirtualPyTest**
2. Copy the **Client ID**, and generate and copy a **client secret**

<div data-technical>

Steps: click **"OAuth Apps"**, then **"New OAuth App"**. Set the homepage URL to `http://localhost:5073` for development, or your production address. Set the authorization callback URL to the address below, then click **"Register application"**.

</div>

<div data-technical>

Authorization callback URL:

```
https://your-project.supabase.co/auth/v1/callback
```

</div>

### 6.2 Add them to Supabase

Turn on **GitHub** under **Authentication**, then **Providers**. Paste the Client ID and Client Secret, and save. GitHub sign-in is optional.

## 7. Set the redirect addresses (only needed for Google or GitHub)

Supabase must know where to send users after they sign in with Google or GitHub. Set these under **Authentication**, then **URL Configuration**.

<div data-technical>

Site URL: `http://localhost:5073` for development. Redirect URLs:

```
http://localhost:5073/auth/callback
https://your-production-domain.com/auth/callback
```

</div>

## 8. Test the sign-in

1. Open the app. You should be sent to the sign-in page.
2. Sign up with email and password, or use Google or GitHub. You are sent to the dashboard.

<div data-technical>

Start the frontend first (`http://localhost:5073`):

```bash
cd frontend
npm run dev
```

Sign-up tab: enter your name, email and password, then click **"Create Account"**. Check your email if verification is on, then switch to the **Log in** tab. GitHub: authorise the app.

</div>

## 9. Make your first admin

Every new user starts as `viewer`. To become admin, sign in once, change your `role` to `admin` in Supabase's **profiles** table, and refresh the app.

<div data-technical>

Shortcut with SQL:

```sql
UPDATE public.profiles
SET role = 'admin'
WHERE email = 'your-email@example.com';
```

</div>

## 10. User roles and permissions

### Default roles

There are three roles. **Admin** can do everything. **Tester** can build and run tests. **Viewer** can only look.

<div data-technical>

Real default permission strings, from `backend_server/src/routes/server_permissions_routes.py`
(`namespace:action` format — this replaced an older flat naming scheme, so don't trust an example
elsewhere that doesn't look like this):

| Role | Description | Default Permissions |
|------|-------------|---------------------|
| **admin** | Full access to everything | `None` in the code = every permission, unconditionally |
| **tester** | Can build and run tests | `dashboard:view`, `device_control:view`/`execute`, `testcases:view`/`create`/`edit`/`hide`, `campaigns:view`/`create`/`edit`/`execute`, `builder.test:view`/`use`, `builder.campaign:view`/`use`, `execution.run:view`/`run_test`/`run_campaign`, `execution.monitor:view`, `reports.tests:view`, `reports.campaigns:view`, `reports.models:view`, `reports.dependency:view`, `monitoring.incidents:view`, `monitoring.heatmap:view`, `monitoring.ai_queue:view`, `interface:view`, `ai_agent:view`/`use`, `plugins.jira:view`/`manage`, `settings.status:view` |
| **viewer** | Read-only access | `dashboard:view`, `testcases:view`, `campaigns:view`, `reports.tests:view`, `reports.campaigns:view`, `reports.models:view`, `reports.dependency:view`, `monitoring.incidents:view`, `monitoring.heatmap:view`, `monitoring.ai_queue:view`, `settings.status:view` |

</div>

### Changing a user's role

Admins change roles on the **Users** page in the app. Without an admin, edit the `role` field in Supabase's **profiles** table.

<div data-technical>

Recommended path: the built-in Users page (`frontend/src/pages/Users.tsx`, an admin can reach it from the app).

</div>

### Custom permissions

On the **Users** page, Permissions tab, you can allow or deny single permissions. A denied permission blocks access, even if the role allows it.

<div data-technical>

Individual permission overrides are **allow/deny**, not a simple additive list — a denied permission blocks access even if the user's role would otherwise grant it. Manage these from the **Users** page's Permissions tab (grouped by namespace: `dashboard`, `device_control`, `testcases`, `campaigns`, `builder.*`, `execution.*`, `reports.*`, `monitoring.*`, `interface`, `ai_agent`, `plugins.jira`, `settings.status`) rather than hand-editing the `profiles.permissions` column directly.

</div>

## 11. How the server protects its routes

The server checks every request for a valid sign-in, an API key or an auto-sign token. A few public routes, such as the health check, need nothing.

<div data-technical>

Every `/server/*` route is gated by one global guard (`configure_global_frontend_auth_guard`
in `backend_server/src/app.py`): unless `SERVER_OPEN_MODE=true`, a request needs a valid
Supabase JWT (browser), an `X-API-Key` (hosts, scripts) or an auto-sign token; a short list
of routes such as `/server/health` stays public. On top of that, individual routes use
`backend_server/src/lib/auth_middleware.py`'s `@require_user_auth` / `@require_role` /
`@require_permission` decorators for role- and permission-level checks.
`/configuration/models` and `/configuration/settings` are **frontend page paths** (protected
client-side by `ProtectedRoute`/`PermissionGate`, a different mechanism), not backend routes.

**How it works:**

1. Frontend sends JWT token in `Authorization: Bearer <token>` header
2. Backend validates token using `@require_user_auth` decorator
3. Backend checks role/permissions with `@require_role` or `@require_permission`
4. Request proceeds if authorized, returns 401/403 if not

**Real example** (`GET /server/auth/admin/test`, from `server_auth_routes.py`):

```python
from backend_server.src.lib.auth_middleware import require_user_auth, require_role

@server_auth_bp.route('/admin/test', methods=['GET'])
@require_user_auth
@require_role('admin')
def admin_only_endpoint():
    return jsonify({'success': True, 'message': 'Welcome, admin!', 'user': request.user_email})
```

</div>

Requests from users who are not allowed are refused.

<div data-technical>

Refused requests get "unauthorised" (401) or "forbidden" (403).

</div>

## 12. How sign-in works

If sign-in is set up, users sign in first. After that, every request carries proof of the sign-in, and the server checks it.

### Frontend flow

<div data-technical>

```
User visits app
   ↓
Check if VITE_SUPABASE_URL exists in frontend/.env
   ↓
YES → Redirect to /login         NO → Allow access (no auth)
   ↓
User signs in (email/Google/GitHub)
   ↓
Supabase returns JWT token
   ↓
Token stored in browser
   ↓
Every API call includes: Authorization: Bearer <JWT>
   ↓
Backend validates JWT → Allows/Denies
```

</div>

### Backend flow

<div data-technical>

```
API Request arrives
   ↓
@require_user_auth checks for JWT token
   ↓
Validates token with Supabase secret
   ↓
Extracts user_id, email, role
   ↓
@require_role checks if user has required role
   ↓
Proceeds if authorized ✅  OR  Returns 403 ❌
```

</div>

## 13. Troubleshooting

Find your problem below.

### "Invalid redirect URL" error

Check the redirect addresses in Supabase. The callback address must match exactly.

<div data-technical>

Ensure the callback URL matches exactly: `/auth/callback`

</div>

### The user profile was not created

Check the database function and trigger that create profiles, and the Supabase logs.

<div data-technical>

Check the SQL function `handle_new_user()` is created; check the trigger `on_auth_user_created` exists.

</div>

### The user cannot open some pages

Check the user's role and permissions.

<div data-technical>

Check your role in the `profiles` table; verify permissions are correctly set; check browser console for auth errors.

</div>

### Environment settings are not picked up

Put the `.env` file in the `frontend` folder and restart the dev server. The browser console shows whether sign-in is on.

<div data-technical>

Setting names must start with `VITE_`. Values must not have quotes.

</div>

<div data-technical>

- Make sure `.env` file is in the `frontend` directory (NOT project root)
- Restart the Vite dev server after changing `.env`
- Variables must start with `VITE_` prefix
- Check browser console: Should see "🔒 Auth enabled" or "🔓 Auth disabled"

</div>

### The login page says "Authentication Disabled"

Check that `frontend/.env` has both Supabase settings, then restart the dev server.

<div data-technical>

Do not put quotes around the values.

</div>

<div data-technical>

- Check `frontend/.env` has `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`
- Restart dev server after adding credentials
- Variables must NOT have quotes in .env file

</div>

### The error "supabaseUrl is required"

Put the URL setting in `frontend/.env`, then clear the browser cache and restart the dev server.

<div data-technical>

Ensure `VITE_SUPABASE_URL` is set in `frontend/.env` (not project root).

</div>

### Email verification does not work

Check your spam folder. For development, you can turn off email confirmation in Supabase.

<div data-technical>

In Supabase, check **Authentication**, then **Email Templates**.

</div>

## Security best practices

1. **Never commit `.env` files.**
2. **Row Level Security.** The backend enforces the access rules for app data. See [supabase.md, Row-level security](supabase.md#row-level-security).
3. **Check roles on the backend** on every API call.
4. **Rotate secrets** and OAuth credentials from time to time.
5. **Keep development and production in separate projects.**

<div data-technical>

Item 1: they are listed in `.gitignore`.

Item 2: the `profiles` and `team_members` tables have their own per-user and admin rules. All other tables have RLS turned on with an open rule.

</div>

## 14. Architecture summary

The files that make up sign-in, for code changes.

<div data-technical>

### Frontend components

```
frontend/src/
├── lib/supabase.ts                    # Supabase client + auth detection
├── contexts/auth/
│   ├── AuthContext.tsx                # Auth state management
│   └── PermissionContext.tsx          # Role/permission logic
├── components/auth/
│   ├── LoginPage.tsx                  # Email/OAuth login UI
│   ├── ProtectedRoute.tsx             # Route protection
│   ├── PermissionGate.tsx             # UI element protection
│   └── UserMenu.tsx                   # User avatar dropdown
├── hooks/auth/
│   ├── useAuth.ts                     # Login/logout
│   ├── usePermissions.ts              # Check permissions
│   └── useProfile.ts                  # User profile data
└── utils/apiClient.ts                 # Auto JWT injection
```

### Backend components

```
backend_server/src/
├── lib/auth_middleware.py             # JWT validation decorators
└── routes/server_auth_routes.py       # Auth test endpoints
```

### Database schema

```
Supabase:
├── auth.users                         # Managed by Supabase
└── public.profiles                    # Your custom user data
    ├── id → auth.users(id)
    ├── email, full_name, avatar_url
    ├── role (admin/tester/viewer)
    └── permissions (JSONB array)
```

</div>

## 15. Turning sign-in off

Turning sign-in off takes two changes, or the API or the login page keeps asking for a login:

1. On the server, turn on open mode.
2. In the frontend, clear the two Supabase settings, then build the frontend again.

<div data-technical>

Two halves, both needed: `SERVER_OPEN_MODE=true` in the server's `.env` (otherwise the API
keeps answering 401), and empty `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` in
`frontend/.env` followed by a frontend rebuild (otherwise the login page stays). Recipes for
each install path: [supabase.md](supabase.md#enforce-login) (read it backwards).

For the steps for each kind of install, see [Supabase and authentication](supabase.md#enforce-login), read from the end.

</div>

## 16. Login page options (for sites where admins create every account)

If an admin creates every account, you can show only email and password on the login page. Turn options off in the frontend's settings file, then build the frontend again.

<div data-technical>

| Flag | Hides |
|------|-------|
| `VITE_ENABLE_OAUTH` | Google / GitHub buttons |
| `VITE_ENABLE_SIGNUP` | **Sign Up** tab and the "Create Account" link |
| `VITE_ENABLE_RESET_PASSWORD` | **Reset Password** tab |

With both `VITE_ENABLE_SIGNUP` and `VITE_ENABLE_RESET_PASSWORD` off the tab bar disappears.

Hiding the tab is not enough to stop signups — the Supabase signup API stays open to anyone
holding the anon key (it is in the bundle). Close it on the Supabase side too:
`enable_signup = false` under **`[auth]` only** in `supabase/config.toml` (Supabase CLI
install, then `supabase stop && supabase start`). Leave `[auth.email] enable_signup = true`:
in the CLI that key switches the whole email provider, so setting it to `false` breaks
email/password **sign-in** too. `DISABLE_SIGNUP=true` for the
Docker stack, or *Authentication → Providers → Email → Allow new users to sign up* off on a
cloud project.

Admins keep creating users from the **Users** page or Supabase Studio, and reset passwords there.

</div>

Hiding buttons does not stop sign-ups. Close sign-up in Supabase too.

## Next steps

**Done:** email, Google and GitHub sign-in, role-based access, password reset and an admin Users page.

**Planned:**

- [ ] Custom email templates (branded emails)
- [ ] Multi-factor authentication (MFA)
- [ ] A session management screen
- [ ] An activity log and audit trail

## Resources

- [Supabase Auth Documentation](https://supabase.com/docs/guides/auth)
- [Google OAuth Setup](https://supabase.com/docs/guides/auth/social-login/auth-google)
- [GitHub OAuth Setup](https://supabase.com/docs/guides/auth/social-login/auth-github)
- [Row Level Security Guide](https://supabase.com/docs/guides/auth/row-level-security)
