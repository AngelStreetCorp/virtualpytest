# JIRA Integration

See your JIRA tickets in one place, filter them and open any ticket in JIRA with one click.

<div data-technical>

You can connect more than one JIRA site.

</div>

## Setup

### 1. Create a JIRA API token

Create a token in your Atlassian account. It works like a password for VirtualPyTest.

1. Go to https://id.atlassian.com/manage/api-tokens
2. Click "Create API token" and give it a name
3. Copy the token. You will not see it again.

<div data-technical>

Example name: "VirtualPyTest Integration". Keep the token somewhere safe.

</div>

### 2. Add your JIRA site

1. Open **Integrations → JIRA** in VirtualPyTest
2. Click **"Add JIRA Instance"**
3. Fill in the form:
   - **Instance Name**: a name you choose
   - **JIRA Domain**: your site address
   - **Email**: the email of your JIRA account
   - **API Token**: paste the token from step 1
   - **Project Key**: the short code of your project
4. Click **"Test Connection"**
5. Click **"Save"**

<div data-technical>

Examples: "Company JIRA" as the name; `yourcompany.atlassian.net` as the domain; `PROJ` as the project key, from the ticket `PROJ-123`.

Domain format: no `https://` and no trailing `/`.

</div>

## Usage

### View tickets

Pick your JIRA site. Counts show at the top.

### Filter tickets

Use the **Status Filter** to choose which tickets to show.

### Open a ticket in JIRA

Click the link icon on a ticket. It opens in a new tab.

### Refresh and edit

Click **"Refresh"** to reload. To change or remove a site, select it and click **"Edit"** or **"Delete"**.

<div data-technical>

Edit lets you change the details, for example a new token. You will be asked to confirm a delete.

</div>

## Security

Your API token stays on the server.

<div data-technical>

All JIRA requests go through the server, and the web page never handles the token.

</div>

## API Endpoints

<div data-technical>

Backend endpoints (for reference):

```
GET  /server/integrations/jira/instances
POST /server/integrations/jira/instances
DELETE /server/integrations/jira/instances/:id
GET  /server/integrations/jira/:id/tickets
GET  /server/integrations/jira/:id/stats
POST /server/integrations/jira/:id/test
```

</div>

## Troubleshooting

**Connection failed.** Check the domain, email, token and project key.

**No tickets showing.** Check the project key and try another filter.

**Authentication error.** The token may have expired. Create a new one.

<div data-technical>

- Connection failed: the domain must not start with `https://` or end with `/`. The email must match your JIRA account. If the token expired, create a new one. The project key must exist.
- No tickets showing: check the project key, try another status filter, and click "Refresh".
- Authentication error: the token may be expired or revoked. Create a new one at https://id.atlassian.com/manage/api-tokens, then edit the site and paste it.

</div>

## Configuration File

Your sites are saved on the server.

<div data-technical>

Sites are stored in `jira_instances.json` under `~/.config/virtualpytest/` of the user the server runs as (`vpt_user`), or in `$VPT_CONFIG_DIR`:

```
~/.config/virtualpytest/jira_instances.json
```

Your tokens stay private. The file lives outside the project folder, so a deploy (`rsync --delete`) cannot wipe it. It holds API tokens, so never copy it into the repository.

</div>

## Future Enhancements

More features are planned.

<div data-technical>

Planned features:
- Create tickets from VirtualPyTest
- Link test cases to JIRA tickets
- Sync test results as JIRA comments
- More filters (assignee, priority, labels)
- Ticket search
- Custom JQL queries

</div>
