# Supabase Authentication Setup Guide

Complete guide for setting up user authentication in VirtualPyTest with Supabase.

## Overview

VirtualPyTest supports **optional authentication** with multiple sign-in methods:

✅ **Email/Password** - Built-in Supabase authentication  
✅ **Google OAuth** - Sign in with Google account  
✅ **GitHub OAuth** - Sign in with GitHub account  
✅ **Role-Based Access Control** - Admin, Tester, Viewer roles  
✅ **Backend JWT Validation** - Secure API protection  

**Whether users must log in is decided by the server's auth posture** (`SERVER_OPEN_MODE`,
`SUPABASE_JWT_SECRET` — see [supabase.md](supabase.md#authentication-open-mode-or-login)).
Fresh installs start in open mode (no login). This page is the long version: OAuth
providers, roles, permissions, how the tokens flow.

## Prerequisites

- **Optional**: Supabase account ([supabase.com](https://supabase.com))
- **Optional**: Google Cloud Console account (for Google OAuth)
- **Optional**: GitHub account (for GitHub OAuth)

## 1. Create Supabase Project

1. Go to [app.supabase.com](https://app.supabase.com)
2. Click "New Project"
3. Fill in project details:
   - **Name**: VirtualPyTest (or your preferred name)
   - **Database Password**: Generate a strong password
   - **Region**: Choose closest to your users
4. Click "Create new project"
5. Wait for the project to be provisioned (~2 minutes)

## 2. Get Supabase Credentials

1. In your Supabase project dashboard, go to **Settings** → **API**
2. Copy the following values:
   - **Project URL** (e.g., `https://xxxxx.supabase.co`)
   - **anon/public key** (starts with `eyJ...`)
3. Add to `frontend/.env` file:

```env
# Add these to enable authentication:
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGc...your-anon-key
```

**Note:** If you don't add these variables, the app runs without authentication (all pages public).

## 3. Create Database Schema

If you already ran the full schema per [Supabase and authentication](./supabase.md) (recommended
— `./setup/db/apply_schema.sh`), this is done: it includes
`setup/db/schema/018_supabase_auth_schema.sql`, which creates `profiles`, the `handle_new_user()`
signup trigger, admin RLS policies, and `is_admin()`.

**Adding auth to an install that skipped it:** apply just that one file (it's self-contained —
safe to run on its own even before `019_team_members.sql`):

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f setup/db/schema/018_supabase_auth_schema.sql
```

Or copy its contents into the Supabase dashboard's **SQL Editor** and click **Run**. Don't
hand-copy an older snippet from elsewhere — always use the current file, since the RLS policies
and trigger functions in it have changed over time (most recently to add a nullable `team_id`).

**What this does:**
- Creates `profiles` table linked to `auth.users`, with a nullable `team_id`
- Auto-creates a profile (and default-team membership, once `team_members` exists) on signup
- Sets default role to `viewer`
- Enables Row Level Security, including admin-only policies via `is_admin()`

## 4. Enable Email/Password Authentication

Email/password authentication works automatically once you've created the database schema.

**To enable it in Supabase:**

1. Go to **Authentication** → **Providers**
2. Find **Email** provider
3. Ensure it's **enabled** (should be on by default)
4. Optional: Configure email templates for verification emails

**Users can now:**
- Sign up with email/password
- Sign in with email/password
- Reset forgotten passwords

## 5. Configure Google OAuth (Optional)

### 5.1 Create Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project or select an existing one
3. Go to **APIs & Services** → **Credentials**
4. Click **Create Credentials** → **OAuth client ID**
5. Configure consent screen if prompted:
   - User Type: **External**
   - App name: **VirtualPyTest**
   - User support email: Your email
   - Developer contact: Your email
6. Create OAuth client ID:
   - Application type: **Web application**
   - Name: **VirtualPyTest**
   - Authorized redirect URIs:
     ```
     https://your-project.supabase.co/auth/v1/callback
     ```
7. Copy the **Client ID** and **Client Secret**

### 5.2 Configure in Supabase

1. In Supabase dashboard, go to **Authentication** → **Providers**
2. Find **Google** and click to expand
3. Enable Google provider
4. Paste your **Client ID** and **Client Secret**
5. Click **Save**

**Note:** Google OAuth is optional. Email/password auth works without it.

## 6. Configure GitHub OAuth (Optional)

### 6.1 Create GitHub OAuth App

1. Go to [GitHub Settings](https://github.com/settings/developers)
2. Click **OAuth Apps** → **New OAuth App**
3. Fill in the details:
   - **Application name**: VirtualPyTest
   - **Homepage URL**: `http://localhost:5073` (development) or your production URL
   - **Authorization callback URL**:
     ```
     https://your-project.supabase.co/auth/v1/callback
     ```
4. Click **Register application**
5. Copy the **Client ID**
6. Click **Generate a new client secret** and copy it

### 6.2 Configure in Supabase

1. In Supabase dashboard, go to **Authentication** → **Providers**
2. Find **GitHub** and click to expand
3. Enable GitHub provider
4. Paste your **Client ID** and **Client Secret**
5. Click **Save**

**Note:** GitHub OAuth is optional. Email/password auth works without it.

## 7. Configure Redirect URLs (Required for OAuth only)

1. In Supabase dashboard, go to **Authentication** → **URL Configuration**
2. Add your redirect URLs:
   - **Site URL**: `http://localhost:5073` (for development)
   - **Redirect URLs**: Add:
     ```
     http://localhost:5073/auth/callback
     https://your-production-domain.com/auth/callback
     ```

## 8. Test Authentication

1. Start your frontend:
   ```bash
   cd frontend
   npm run dev
   ```

2. Navigate to `http://localhost:5073`
   - Should automatically redirect to `/login`

3. **Try all authentication methods:**

   **Email/Password:**
   - Click **SIGN UP** tab
   - Enter your name, email, password
   - Click "Create Account"
   - Check your email for verification (if enabled)
   - Switch to **LOGIN** tab and sign in

   **Google OAuth:**
   - Click the Google icon
   - Complete Google sign-in flow
   - Redirected back to dashboard

   **GitHub OAuth:**
   - Click the GitHub icon
   - Authorize the application
   - Redirected back to dashboard

4. After first login, you should see the dashboard

## 9. Create Your First Admin User

All new users get the default `viewer` role. To promote yourself to admin:

1. Sign in to your app (any method)
2. In Supabase dashboard, go to **Table Editor** → **profiles**
3. Find your user row
4. Edit the `role` column and change it to `admin`
5. Refresh your app - you now have admin access!

**Admin SQL shortcut:**
```sql
UPDATE public.profiles 
SET role = 'admin' 
WHERE email = 'your-email@example.com';
```

## 10. User Roles & Permissions

### Default Roles

Real default permission strings, from `backend_server/src/routes/server_permissions_routes.py`
(`namespace:action` format — this replaced an older flat naming scheme, so don't trust an example
elsewhere that doesn't look like this):

| Role | Description | Default Permissions |
|------|-------------|---------------------|
| **admin** | Full access to everything | `None` in the code = every permission, unconditionally |
| **tester** | Can build and run tests | `dashboard:view`, `device_control:view`/`execute`, `testcases:view`/`create`/`edit`/`hide`, `campaigns:view`/`create`/`edit`/`execute`, `builder.test:view`/`use`, `builder.campaign:view`/`use`, `execution.run:view`/`run_test`/`run_campaign`, `execution.monitor:view`, `reports.tests:view`, `reports.campaigns:view`, `reports.models:view`, `reports.dependency:view`, `monitoring.incidents:view`, `monitoring.heatmap:view`, `monitoring.ai_queue:view`, `interface:view`, `ai_agent:view`/`use`, `plugins.jira:view`/`manage`, `settings.status:view` |
| **viewer** | Read-only access | `dashboard:view`, `testcases:view`, `campaigns:view`, `reports.tests:view`, `reports.campaigns:view`, `reports.models:view`, `reports.dependency:view`, `monitoring.incidents:view`, `monitoring.heatmap:view`, `monitoring.ai_queue:view`, `settings.status:view` |

### Changing User Roles

**Recommended — the built-in Users page** (`frontend/src/pages/Users.tsx`, an admin can reach it
from the app): edit a user's role directly, or override individual permissions.

**Manually in Supabase** (works too, e.g. before you have any admin yet):
1. Go to **Table Editor** → **profiles**
2. Find the user
3. Edit the `role` field

### Custom Permissions

Individual permission overrides are **allow/deny**, not a simple additive list — a denied
permission blocks access even if the user's role would otherwise grant it. Manage these from the
**Users** page's Permissions tab (grouped by namespace: `dashboard`, `device_control`,
`testcases`, `campaigns`, `builder.*`, `execution.*`, `reports.*`, `monitoring.*`, `interface`,
`ai_agent`, `plugins.jira`, `settings.status`) rather than hand-editing the `profiles.permissions`
column directly.

## 11. Backend API Protection

Every `/server/*` route is gated by one global guard (`configure_global_frontend_auth_guard`
in `backend_server/src/app.py`): unless `SERVER_OPEN_MODE=true`, a request needs a valid
Supabase JWT (browser), an `X-API-Key` (hosts, scripts) or an auto-sign token; a short list
of routes such as `/server/health` stays public. On top of that, individual routes use
`backend_server/src/lib/auth_middleware.py`'s `@require_user_auth` / `@require_role` /
`@require_permission` decorators for role- and permission-level checks.
`/configuration/models` and `/configuration/settings` are **frontend page paths** (protected
client-side by `ProtectedRoute`/`PermissionGate`, a different mechanism), not backend routes.

**How it works, where it is enforced:**

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

## 12. How Authentication Works

### Frontend Flow

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

### Backend Flow

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

## 13. Troubleshooting

### "Invalid redirect URL" error
- Check that your redirect URLs are correctly configured in Supabase
- Ensure the callback URL matches exactly: `/auth/callback`

### User profile not created
- Check the SQL function `handle_new_user()` is created
- Check the trigger `on_auth_user_created` exists
- Look at Supabase logs for errors

### Can't access protected pages
- Check your role in the `profiles` table
- Verify permissions are correctly set
- Check browser console for auth errors

### Environment variables not loading
- Make sure `.env` file is in the `frontend` directory (NOT project root)
- Restart the Vite dev server after changing `.env`
- Variables must start with `VITE_` prefix
- Check browser console: Should see "🔒 Auth enabled" or "🔓 Auth disabled"

### Login page says "Authentication Disabled"
- Check `frontend/.env` has `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`
- Restart dev server after adding credentials
- Variables must NOT have quotes in .env file

### "supabaseUrl is required" error
- Ensure `VITE_SUPABASE_URL` is set in `frontend/.env` (not project root)
- Clear browser cache and restart dev server

### Email verification not working
- Check Supabase → Authentication → Email Templates
- For development, disable email confirmation in Supabase settings
- Or check your email spam folder

## Security Best Practices

1. **Never commit `.env` files** - They're in `.gitignore` by default
2. **Row Level Security (RLS)** - `profiles` and `team_members` have real per-user/admin
   policies (from the SQL above). All other tables have RLS enabled with an open policy;
   app-data authorization is enforced by the backend, not by Postgres — see
   [supabase.md — Row-level security](supabase.md#row-level-security)
3. **Validate roles on backend** - Always verify user permissions on your API
4. **Rotate secrets regularly** - Update OAuth credentials periodically
5. **Use different projects for dev/prod** - Keep environments separate

## 14. Architecture Summary

### Frontend Components

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

### Backend Components

```
backend_server/src/
├── lib/auth_middleware.py             # JWT validation decorators
└── routes/server_auth_routes.py       # Auth test endpoints
```

### Database Schema

```
Supabase:
├── auth.users                         # Managed by Supabase
└── public.profiles                    # Your custom user data
    ├── id → auth.users(id)
    ├── email, full_name, avatar_url
    ├── role (admin/tester/viewer)
    └── permissions (JSONB array)
```

## 15. Disabling Authentication

Two halves, both needed: `SERVER_OPEN_MODE=true` in the server's `.env` (otherwise the API
keeps answering 401), and empty `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` in
`frontend/.env` followed by a frontend rebuild (otherwise the login page stays). Recipes for
each install path: [supabase.md](supabase.md#enforce-login) (read it backwards).

## Next Steps

**Completed:**
- ✅ Email/password authentication
- ✅ Google & GitHub OAuth
- ✅ Backend JWT validation
- ✅ Role-based access control
- ✅ Protected routes
- ✅ Password reset flow
- ✅ Admin panel for user management (Users page: role changes + per-permission allow/deny overrides)

**Future Enhancements:**
- [ ] Custom email templates (branded emails)
- [ ] Multi-Factor Authentication (MFA)
- [ ] Session management UI
- [ ] Activity logs/audit trail

## Resources

- [Supabase Auth Documentation](https://supabase.com/docs/guides/auth)
- [Google OAuth Setup](https://supabase.com/docs/guides/auth/social-login/auth-google)
- [GitHub OAuth Setup](https://supabase.com/docs/guides/auth/social-login/auth-github)
- [Row Level Security Guide](https://supabase.com/docs/guides/auth/row-level-security)

