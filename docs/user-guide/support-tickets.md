# Support tickets

Report a problem or ask for help without leaving the app. Your ticket reaches the support team with the
version, server, team, page and logs already filled in.

If **Open a ticket** is missing from the Settings menu, support tickets are switched off on your server
(or not connected yet). Ask an administrator.

## Open a ticket

1. Open **Settings** in the top bar and choose **Open a ticket**.
2. Fill in the form, top to bottom:

| Field | What to pick |
|---|---|
| **Type** | Incident (something that worked is broken), Bug (a defect you can reproduce), Request (you want something added or changed), Question (you need an answer). |
| **Priority** | How soon you need it: P0 High, P1 Medium (the default), P2 Low. |
| **Severity** | How bad it is: Blocker, Major or Minor. Only shown for Incident and Bug. |
| **Frequency** | How often it happens: Always, Frequent, Random or Seen once. |
| **Family** | The part of the platform: Platform, Scripting, Monitoring, Dashboards or AI. |
| **Category** | The kind of thing inside that family (for example Device, Script, Heatmap, Grafana, Agent). |
| **Target** | The exact server, host, device, script or report the ticket is about. Optional. |
| **Title** | One line that says what it is. |
| **Description** | A short template is filled in for you (for example Steps / Expected / Actual for a Bug). Write your answers under it. |
| **More details** | Optional: "Since when", and up to 5 attached files of at most 5 MB each (screenshots, logs). |

3. Select **Send**. You can only send once the description holds more than the bare template.

Version, server, team, your email, the page you were on and your browser are added to the ticket
automatically. You do not need to type them.

### Priority or severity?

- **Priority** is your call on urgency: how soon you need an answer.
- **Severity** is the impact of the problem itself: **Blocker** stops your work, **Major** breaks an
  important function but you can work around it, **Minor** is small.

A blocker can still be low priority (a broken feature you do not need this month), and the reverse.

## Statuses you will see

The support team uses a finer workflow; you see five words.

| You see | Meaning |
|---|---|
| **Open** | Received; waiting to be picked up. |
| **In progress** | Someone is working on it, or a fix exists and is being prepared. |
| **Waiting for you** | Support asked you a question. |
| **Delivered, please check** | The fix is released. Please check it and tell support. |
| **Closed** | Done (fixed, duplicate of another ticket, or will not be fixed). |

## Follow your tickets

- **By email**, once your support team has set up the mailbox. Until then, replies are only in the
  helpdesk.
- **In the app**: open **Plugins -> Zammad** to see the team's recent tickets. Select a row to open
  that ticket in the support system.

Not available yet: opening a ticket from a button on a device, host, script or dashboard page (the
Settings menu is the only entry), and reading the ticket thread inside the app. A ticket can still
read **Open** after support has started on it. The support system always shows the current status.

<div data-technical>

The Zammad view shows Opened, Closed and Total counts for Today, 7 days, 30 days or All. Filter by
Team, User and Project. The arrow on a row opens the ticket in the support system.

When several servers are configured, targets show the server name, so same-named hosts are told apart.

Ticket statuses in the app do not update by themselves yet.

Operators: see [Zammad setup](../integrations/zammad-setup.md).

</div>
