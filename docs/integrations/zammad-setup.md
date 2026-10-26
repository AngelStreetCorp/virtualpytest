# Zammad setup (support tickets)

This connects VirtualPyTest to a **Zammad** helpdesk. Users then send a support ticket from **Settings -> Open a ticket**.

Tickets arrive with the details filled in. For the user's view, see [Support tickets](../user-guide/support-tickets.md).

## 1. Choose a Zammad

- **Hosted by the platform operator:** ask for the address and an API token, then skip to step 3.
- **Your own Zammad:** install it first.

<div data-technical>

Install Zammad from <https://docs.zammad.org>, then create:
- the groups `Devices`, `Hosts & System`, `Scripts`, `Dashboards` and `Platform` (step 4 only checks them);
- an **admin** agent whose API token you will use (Zammad: Profile -> Token Access).

</div>

## 2. Prepare the Zammad instance (once)

Run the setup script once on each new Zammad. It is safe to run again.

<div data-technical>

```bash
set -a; . .env; set +a            # ZAMMAD_URL and an admin's ZAMMAD_API_TOKEN
python3 -m features.zammad.lib.setup_zammad
```

It creates the workflow ticket states (accepted, assigned, in progress, need info, fixed, delivered, reopened, duplicate, won't fix) and the ticket attributes `vpt_type`, `vpt_family`, `vpt_category`, `vpt_target`, `vpt_severity`, `vpt_frequency` and `vpt_fixed_in_build`. Then it runs Zammad's object manager migration. Zammad restarts its application server for a moment, and the script waits. Run it again after any change to `features/zammad/lib/model.py`.

</div>

## 3. Connect VirtualPyTest

- **As an admin, in the app:** go to **Plugins -> Zammad -> Setup**.
- **Without the screen:** set three environment variables on the backend server.

The connection is tested before anything is saved. The status dot shows Connected, Unreachable or Not configured.

<div data-technical>

Environment variables:

```
ZAMMAD_URL=https://support.example.com          # no trailing slash
ZAMMAD_API_TOKEN=...                            # the agent's API token
ZAMMAD_PUBLIC_URL=https://support.example.com   # optional: what a browser opens; defaults to ZAMMAD_URL
```

The connection is tested with `GET /api/v1/users/me` before anything is saved. The values are stored in `zammad_instances.json` in the server's state directory, outside the deploy folder, so a deploy does not overwrite them. A field left empty in that file falls back to the environment. The gear icon appears once you are connected. The token is never sent back to the browser.

</div>

## 4. Set up the database, once per database

The ticket list needs three database files, run in order on each database. Without them, tickets cannot be listed.

<div data-technical>

```
features/zammad/db/001_support_tickets.sql
features/zammad/db/002_ticket_model.sql      # refuses to run if the table already holds old-model rows
features/zammad/db/003_priority_severity.sql
```

Each file can be run again safely. A `*_rollback.sql` file undoes it. Every query filters by `team_id`.

</div>

## 5. Switch it on and off

- **Per server:** an admin turns it on or off in **Settings -> Features -> Feature Toggles -> Support tickets (Zammad)**. When off, "Open a ticket" is hidden.
- **Per deployment:** the feature can be left out entirely.

<div data-technical>

- Off: creating a ticket or replying answers `409 support tickets are disabled`. Existing tickets stay in the list. A server with no address or token acts as off.
- The ticket carries the version, server, team and user. The user is the sender, so Zammad's email replies reach them once email is set up in Zammad. The **Plugins -> Zammad** page lists and counts the tickets VirtualPyTest keeps.
- Per deployment: `DISABLED_FEATURES=zammad` (in `customer.conf`, or `--disabled-features` on `deploy_customer.sh`). The folder is not deployed and the routes are not registered.

</div>

## 6. Test it

Open **Settings -> Open a ticket**, send one, and check that it appears in Zammad and on the Plugins page.

**Use a throw-away Zammad for the live test.** The live test creates and closes real tickets.

<div data-technical>

```bash
python3 -m pytest tests/backend_server/test_zammad.py tests/backend_server/test_zammad_provider.py -q
# also runs the live create / reply / read / close test against a real instance:
ZAMMAD_URL=https://support.example.com ZAMMAD_API_TOKEN=... python3 -m pytest tests/backend_server/test_zammad_provider.py -q
```

</div>

## Known gaps

Ticket status in the list does not follow Zammad yet.

<div data-technical>

Not built yet:
- Context buttons on device, host, script and dashboard pages
- A "My tickets" thread page
- A webhook that copies status changes from Zammad back. Until it exists, the status stays at `new`.
- Jira and GitLab as other providers

</div>
