# Branding and White-Labeling

Set your name, logo and colours once, before the build. The look is then fixed in the app itself, so nobody can change it later by accident.

---

## Quick Start

1. Set your branding values before you build.
2. Build the app. The branding is saved into it.

<div data-technical>

1. Set the environment variables in `frontend/.env` before building.
2. Run `npm run build` to create a production build with embedded branding.

</div>

---

## Settings

Your branding is a short list of settings. The names and logo are shown in the header, on the login page, and in the footer.

<div data-technical>

Configure branding in `frontend/.env`:

```bash
VITE_PROJECT_NAME=VirtualPyTest
VITE_PROJECT_TAGLINE=Automated Testing Platform
VITE_PROJECT_LOGO_URL=/brand/logo.svg
VITE_PROJECT_TITLE=VirtualPyTest Web Interface
VITE_SHOW_FOOTER=true
VITE_SHOW_PROJECT_NAME=true
```

</div>

### What each setting does

- **Name:** shown in the header, on the login page and in the docs header.
- **Logo:** optional. A picture to show instead of, or next to, the name.
- **Tagline:** shown in the footer, when the footer is on.
- **Title:** the text on the browser tab.
- **Footer:** turn it on or off.
- **Show the name:** turn it off when your logo already spells out the name. Otherwise the name appears twice. Keep it on for a logo that is only a symbol.

<div data-technical>

- `VITE_PROJECT_NAME`: displayed in the header, login, and docs header.
- `VITE_PROJECT_LOGO_URL`: optional. Path or URL for a logo image.
- `VITE_PROJECT_TAGLINE`: shown in the footer (when enabled).
- `VITE_PROJECT_TITLE`: browser tab title.
- `VITE_SHOW_FOOTER`: `true` or `false` to show or hide the footer.
- `VITE_SHOW_PROJECT_NAME`: `false` hides the project name text in the header, footer and mobile bar, and puts the logo in place of the name on the login page. Set it when the logo is a **wordmark** (it already spells the name out), otherwise the name is written twice, once as the image and once as text. Leave it `true` (the default) for emblem-only logos.

</div>

---

## Logo

Put your logo file where the app can serve it, and point the setting at it. Use a logo that is cropped and sized for the header: the header area is small, and a logo with a white background looks wrong on the coloured bar.

- Crop the empty margins off the logo.
- Make any white background transparent.
- Use a file about 160 px tall. A bigger file does not look better here.
- A wordmark (a logo with the name in it) also needs the name switched off, as above.

You can also use a web address if the logo is hosted somewhere else.

<div data-technical>

Place the logo file in `frontend/public/brand/` so it is served statically. Example:

- `frontend/public/brand/logo.svg`
- `VITE_PROJECT_LOGO_URL` set to `/brand/logo.svg`

Prepare the file for where it is drawn: the header renders it at 28 px height / 160 px max width on a coloured app bar, so crop the margins off, strip a white background to transparency (a white rectangle on the app bar is the usual mistake) and ship it at ~160 px tall rather than at marketing resolution. A wordmark also wants `VITE_SHOW_PROJECT_NAME=false` (see above).

</div>

---

## Per-customer branding with an overlay

When VirtualPyTest is set up for a customer, the branding can come from a separate, small project called an **overlay**. It is added on top of the platform when it is deployed. The overlay keeps the customer's look apart from the main code.

<div data-technical>

When VirtualPyTest is deployed for a customer with a **customer overlay** (a small repo layered over the platform at deploy time by `setup/proxmox/node/deploy_customer.sh`), the branding does not live in `frontend/.env` on the machine but in the overlay:

- `frontend/.env.production` in the overlay: the `VITE_PROJECT_*` / `VITE_SHOW_FOOTER` / `VITE_NAV_*` values above. Vite layers it **over** the machine's own `frontend/.env` (environment URLs and tokens, never in git) at build time: a key set in `.env.production` wins, everything else keeps the machine's value. Only `VITE_*` values belong there, because they are baked into the public bundle, never a token. An overlay must never contain a `frontend/.env`; the deploy script refuses it.
- `frontend/public/brand/` in the overlay: the logo and other brand assets, served statically. Point `VITE_PROJECT_LOGO_URL` at `/brand/<file>` (or use an absolute URL and ship no file).

</div>

The overlay is built from a template. Copy the template for each new customer. Its README explains the onboarding steps.

<div data-technical>

The reference overlay, the template to copy for a new customer, is [AngelStreetCorp/vpt-customer-demo](https://github.com/AngelStreetCorp/vpt-customer-demo). Its `README.md` is the onboarding guide.

</div>

---

## Notes

- The branding is built into the app. Changing it means changing the settings and building again.
- Because it is built in, the branding cannot be edited in a running production app.
