# Branding and White-Labeling

Branding is embedded at build time via Vite environment variables. This ensures branding cannot be modified or corrupted after the production build.

---

## Quick Start

1. Set environment variables in `frontend/.env` before building.
2. Run `npm run build` to create a production build with embedded branding.

---

## Environment Variables

Configure branding in `frontend/.env`:

```bash
VITE_PROJECT_NAME=VirtualPyTest
VITE_PROJECT_TAGLINE=Automated Testing Platform
VITE_PROJECT_LOGO_URL=/brand/logo.svg
VITE_PROJECT_TITLE=VirtualPyTest Web Interface
VITE_SHOW_FOOTER=true
VITE_SHOW_PROJECT_NAME=true
```

### Fields

- `VITE_PROJECT_NAME`: Displayed in the header, login, and docs header.
- `VITE_PROJECT_LOGO_URL`: Optional. Path or URL for a logo image.
- `VITE_PROJECT_TAGLINE`: Shown in the footer (when enabled).
- `VITE_PROJECT_TITLE`: Browser tab title.
- `VITE_SHOW_FOOTER`: `true` or `false` to show/hide the footer.
- `VITE_SHOW_PROJECT_NAME`: `false` hides the project name text in the header, footer and mobile
  bar, and puts the logo in place of the name on the login page. Set it when the logo is a
  **wordmark** (it already spells the name out) — otherwise the name is written twice, once as
  the image and once as text. Leave it `true` (the default) for emblem-only logos.

---

## Logo Hosting

Place the logo file in `frontend/public/brand/` so it is served statically. Example:

- `frontend/public/brand/logo.svg`
- `VITE_PROJECT_LOGO_URL` set to `/brand/logo.svg`

Prepare the file for where it is drawn: the header renders it at 28 px height / 160 px max width
on a coloured app bar, so crop the margins off, strip a white background to transparency (a white
rectangle on the app bar is the usual mistake) and ship it at ~160 px tall rather than at
marketing resolution. A wordmark also wants `VITE_SHOW_PROJECT_NAME=false` (see above).

You can also use an absolute URL if the logo is hosted elsewhere.

---

## Per-customer branding with an overlay

When VirtualPyTest is deployed for a customer with a **customer overlay** (a small repo
layered over the platform at deploy time by `setup/proxmox/node/deploy_customer.sh`), the
branding does not live in `frontend/.env` on the machine but in the overlay:

- `frontend/.env.production` in the overlay — the `VITE_PROJECT_*` / `VITE_SHOW_FOOTER` /
  `VITE_NAV_*` values above. Vite layers it **over** the machine's own `frontend/.env`
  (environment URLs and tokens, never in git) at build time: a key set in
  `.env.production` wins, everything else keeps the machine's value. Only `VITE_*`
  values belong there — they are baked into the public bundle — never a token. An overlay
  must never contain a `frontend/.env`; the deploy script refuses it.
- `frontend/public/brand/` in the overlay — the logo and other brand assets, served
  statically; point `VITE_PROJECT_LOGO_URL` at `/brand/<file>` (or use an absolute URL and
  ship no file).

The reference overlay — the template to copy for a new customer, and the onboarding
guide in its `README.md` — is
[AngelStreetCorp/vpt-customer-demo](https://github.com/AngelStreetCorp/vpt-customer-demo).

---

## Notes

- Branding is baked into the JavaScript bundle at build time.
- To change branding, update the environment variables and rebuild.
- This approach prevents tampering with branding in production deployments.
