# JIRA Integration

Quick integration for tracking JIRA tickets from VirtualPyTest.

## Features

- ✅ Multiple JIRA instances support
- ✅ Secure API token storage (backend proxy)
- ✅ Real-time ticket dashboard
- ✅ Filter by status
- ✅ Quick statistics (total, by status)
- ✅ One-click to open in JIRA

## Setup

### 1. Generate JIRA API Token

1. Go to https://id.atlassian.com/manage/api-tokens
2. Click "Create API token"
3. Name it (e.g., "VirtualPyTest Integration")
4. Copy the token (you won't see it again!)

### 2. Add JIRA Instance

1. Navigate to **Integrations → JIRA** in VirtualPyTest
2. Click **"Add JIRA Instance"**
3. Fill in the form:
   - **Instance Name**: Your custom name (e.g., "Company JIRA")
   - **JIRA Domain**: Your domain without https:// (e.g., `yourcompany.atlassian.net`)
   - **Email**: Your JIRA account email
   - **API Token**: Paste the token from step 1
   - **Project Key**: The project key (e.g., `PROJ` from ticket `PROJ-123`)
4. Click **"Test Connection"** to verify
5. Click **"Save"**

## Usage

### View Tickets

1. Select your JIRA instance from dropdown
2. See statistics cards (total, open, in progress, done, etc.)
3. Browse tickets in the table below

### Filter Tickets

Use the **Status Filter** dropdown to show only:
- All tickets
- Open
- In Progress
- To Do
- Done
- Closed

### Open in JIRA

Click the 🔗 icon on any ticket to open it in JIRA (new tab)

### Refresh Data

Click **"Refresh"** button to reload tickets and stats

### Edit/Delete Instance

1. Select the instance
2. Click **"Edit"** to update credentials
3. Click **"Delete"** to remove (with confirmation)

## Security

- ✅ API tokens stored on backend (never sent to frontend)
- ✅ All JIRA API calls go through backend proxy
- ✅ Frontend never sees or handles API tokens

## API Endpoints

Backend endpoints (for reference):

```
GET  /server/integrations/jira/instances
POST /server/integrations/jira/instances
DELETE /server/integrations/jira/instances/:id
GET  /server/integrations/jira/:id/tickets
GET  /server/integrations/jira/:id/stats
POST /server/integrations/jira/:id/test
```

## Troubleshooting

### Connection Failed

- Verify domain is correct (no `https://`, no trailing `/`)
- Check email matches your JIRA account
- Regenerate API token if expired
- Verify project key exists

### No Tickets Showing

- Check project key is correct
- Verify you have permission to view project
- Try different status filter
- Click "Refresh"

### Authentication Error

- API token may be expired or revoked
- Regenerate token at https://id.atlassian.com/manage/api-tokens
- Edit instance with new token

## Configuration File

Instances are stored in:
```
backend_server/config/integrations/jira_instances.json
```

**Warning**: Do not commit this file if it contains API tokens!

## Future Enhancements

Planned features:
- Create tickets from VirtualPyTest
- Link test cases to JIRA tickets
- Sync test results as JIRA comments
- Support for more filters (assignee, priority, labels)
- Ticket search
- Custom JQL queries

