# Grafana Alerting — Get Told When Something Breaks

VirtualPyTest records host health, device capture, incidents, script results and fleet health. Grafana
dashboards show this data. **Grafana alerting** watches it for you and sends an email (or a Slack, Teams or
webhook message) when something goes wrong.

This page covers:

1. [What alerting can do](#1-what-alerting-can-do)
2. [Prerequisites — email setup](#2-prerequisites)
3. [Apply the predefined alerts with one command](#3-apply-the-predefined-alerts-script)
4. [The predefined alerts](#4-the-predefined-alerts)
5. [Create or change an alert by hand in Grafana](#5-create-or-change-an-alert-by-hand)
6. [Write your own alert](#6-write-your-own-alert)
7. [Tuning: who gets what, how often, silences](#7-tuning)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. What alerting can do

An alert checks the data on a schedule, every 1, 5 or 15 minutes. If a value stays over its threshold, the alert
**fires** and sends a message to a **contact point** (an email list, a Slack channel, a Teams webhook). When the
problem is gone, a **resolved** message follows.

| You want to know when... |
|---|
| a host stops reporting (service down, machine off, network lost) |
| a platform service or infrastructure machine is down, or its disk or memory is high |
| a disk is almost full, or memory or CPU temperature is too high |
| the video capture or the monitor of a device stopped |
| a device has an incident, or far too many incidents |
| a script keeps failing, or its pass rate suddenly drops |
| the fleet-health check marks a device DOWN |

<div data-technical>

Data read by each kind of alert: `system_metrics` (host down, disk, memory, CPU temperature), `service_status` and
`vm_metrics` (System Service Status), `system_device_metrics` (capture and monitor), `alerts` (device incidents),
`script_results` (scripts) and `fleet_health` (fleet check).

One rule watches every host, device or script at once. Each row the query returns becomes its own alert, which
Grafana calls an *instance*. The host, device or script name goes into the message.

</div>

---

## 2. Prerequisites

| What | Check |
|---|---|
| Grafana **11 or newer** | Grafana → **Help (?)** shows the version |
| The **Supabase PostgreSQL** data source | Connections → Data sources |
| A Grafana **admin** login | — |
| An **SMTP mail server**, for email only | see below |

Slack, Microsoft Teams, Telegram, Discord, PagerDuty, Opsgenie and webhooks do not need SMTP. They only need a
webhook address or a token, entered in the contact point.

<div data-technical>

Grafana 11 or newer is needed because unified alerting is on by default there. The data source uid is
`supabase-postgres`; the installer creates it.

</div>

### Configure SMTP

Set the mail server in Grafana's settings on the Grafana machine, then restart Grafana. Email stays off until you do.

<div data-technical>

Edit `/etc/grafana/grafana.ini`, section `[smtp]`. The template `infra/monitoring/grafana/config/grafana.ini` has
them all commented out.

```ini
[smtp]
enabled = true
host = smtp.example.com:587
user = alerts@example.com
# If the password contains # or ; wrap it in triple quotes: """my#pass"""
password = your-smtp-password
from_address = alerts@example.com
from_name = VirtualPyTest
# StartTLS on port 587: OpportunisticStartTLS (default) or MandatoryStartTLS
startTLS_policy = OpportunisticStartTLS
skip_verify = false
```

Restart Grafana:

```bash
sudo systemctl restart grafana-server
```

Running Grafana in Docker? Use environment variables instead of the file: `GF_SMTP_ENABLED=true`, `GF_SMTP_HOST`,
`GF_SMTP_USER`, `GF_SMTP_PASSWORD`, `GF_SMTP_FROM_ADDRESS`, `GF_SMTP_FROM_NAME`. Then recreate the container.

For a company relay without TLS, set `startTLS_policy = NoStartTLS`.

</div>

| Provider | Server address (`host`) | Notes |
|---|---|---|
| Gmail / Google Workspace | `smtp.gmail.com:587` | needs an **app password** |
| Microsoft 365 | `smtp.office365.com:587` | SMTP AUTH must be enabled |
| Amazon SES | `email-smtp.<region>.amazonaws.com:587` | verify the sender |
| Brevo, Mailgun, SendGrid... | see the provider | any SMTP relay works |
| Your company relay | `mail.yourcompany.local:25` | often no login needed |

**Test it** in Grafana (**Alerting → Contact points → Edit → Test**), or with the script. Success means Grafana
handed the mail to your mail server. A failure prints the error.

<div data-technical>

```bash
python3 scripts/grafana_alerts.py test-email --email you@example.com
```

Success prints `sent test email to you@example.com`. A failure starts with `FAILED`, for example
`FAILED ... connection refused / timeout`.

</div>

> **Set Grafana's default contact point to a real address too.** Alerts that are not routed elsewhere go there.
> Edit it under **Alerting → Contact points**.

<div data-technical>

The default contact point is `grafana-default-email`. Out of the box its address is the placeholder
`<example@email.com>`.

</div>

---

## 3. Apply the predefined alerts (script)

One script sets up the whole alerting: a folder, an email contact point, the mail timing and the rules. Run it on
the server VM, from the repository.

- Safe to re-run. It resets the rules to the catalog, and **overwrites thresholds you changed in the UI**. Tune in
  the catalog and re-run, or tune in the UI and stop re-running.
- Keep your own rules out of the *VirtualPyTest Alerts* folder. The script removes rules it does not know.
- The rules stay editable in the Grafana UI.

<div data-technical>

Script: `scripts/grafana_alerts.py`. It reads `GRAFANA_URL`, `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` and
`TEAM_ID` from `.env`, the same way the server does. Catalog: `infra/monitoring/grafana/alerting/vpt-alert-rules.json`.
The folder is **VirtualPyTest Alerts**, the contact point is **VirtualPyTest email** with a short digest template,
and the notification policy groups the alerts and limits mail (see §7).

```bash
# See what is available
python3 scripts/grafana_alerts.py list

# Apply the recommended rules, mail two people
python3 scripts/grafana_alerts.py apply --email ops@example.com,qa@example.com

# Pick exactly which rules
python3 scripts/grafana_alerts.py apply --email ops@example.com --rules vpt-host-offline,vpt-host-disk-high

# Everything, including the opt-in rules
python3 scripts/grafana_alerts.py apply --email ops@example.com --rules all

# Fewer, grouped mails: one mail per rule, at most every 30 minutes, repeated twice a day
python3 scripts/grafana_alerts.py apply --email ops@example.com --group-by rule --group-interval 30m --repeat-interval 12h

# What is firing right now
python3 scripts/grafana_alerts.py status

# One printable digest per recipient (start time, NEW since the previous digest, RESOLVED in the
# window with end time). Persists the firing set in .grafana_alert_digest_state.json so the next
# run can mark NEW alerts. `mail` also calls this helper before sending.
python3 scripts/grafana_alerts.py report --email ops@example.com,qa@example.com

# Take it all away again
python3 scripts/grafana_alerts.py remove
```

Options: `--grafana-url https://your-host/grafana` overrides `GRAFANA_URL`, and includes the sub-path if Grafana is
served under one. `--insecure` accepts a self-signed certificate. `--team-id` sets whose script results the *Test
results* rules watch (default `TEAM_ID`). Mail volume: `--group-by`, `--group-wait`, `--group-interval`,
`--repeat-interval`, see §7.

`apply` takes up to about a minute. It waits until Grafana uses the new notification policy, then creates the rules.
The `report` subcommand writes `.grafana_alert_digest_state.json` on every run.

</div>

---

## 4. The predefined alerts

Thresholds are starting points. Change them to fit your lab.

| Rule | Fires when | Threshold · wait | Severity | On by default |
|---|---|---|---|---|
| **All hosts stopped reporting (system down)** | every host has been silent for more than 10 min | any · 2 min | **critical** | yes |
| **All hosts of one site offline** | every host of one site has been silent for more than 10 min | any · 2 min | **major** | yes |
| **Host stopped reporting** | no metrics from a host for longer than the threshold | more than 10 min · 5 min | **minor** | yes |
| **Host disk almost full** | root disk use | above 85 % · 10 min | warning | yes |
| **Host memory high** | memory use | above 90 % · 15 min | warning | yes |
| **Host CPU too hot** | CPU temperature (hosts that report one, e.g. Raspberry Pi) | above 80 °C · 10 min | warning | yes |
| **Capture or monitor not running** | a device's capture or monitor is not running | any · 10 min | **minor** | yes |
| **Too many incidents on a device** | incidents started on one device in the last hour | more than 20 | warning | yes |
| **Device incident ongoing** | a blackscreen, freeze, audio loss or macroblocks incident is still open | more than 10 min | warning | opt-in |
| **Script failing repeatedly** | the last runs of a script on a device all failed | 3 or more in a row | warning | yes |
| **Script pass rate dropped** | pass rate over the last 24 h falls against the previous 7 days | drop of more than 30 points | warning | yes |
| **Fleet health: device DOWN** | the latest fleet-health check marks a device DOWN | DOWN | **minor** | yes |
| **Platform service down** | a platform service is down, or was not checked for 3 min | any · 3 min | **major** | yes ¹ |
| **Platform service degraded** | a platform service reports degraded | 15 min | warning | opt-in ¹ |
| **Infra VM disk almost full** | root disk of an infra VM | above 85 % · 10 min | warning | yes ¹ |
| **Infra VM memory high** | memory of an infra VM | above 90 % · 15 min | warning | yes ¹ |

¹ The platform service rules need the System Service Status tables. Until their migration is applied, `apply` skips
these rules and says so. Re-run it afterwards.

<div data-technical>

Rule identifiers (uid) and the data each rule reads:

| Rule | uid | Reads |
|---|---|---|
| All hosts stopped reporting | `vpt-system-down` | `system_metrics` |
| All hosts of one site offline | `vpt-fleet-all-hosts-offline` | `system_metrics`, grouped by `server_name` |
| Host stopped reporting | `vpt-host-offline` | `system_metrics` |
| Host disk almost full | `vpt-host-disk-high` | `system_metrics` |
| Host memory high | `vpt-host-memory-high` | `system_metrics` |
| Host CPU too hot | `vpt-host-cpu-temp-high` | `system_metrics` |
| Capture or monitor not running | `vpt-capture-not-running` | `system_device_metrics` |
| Too many incidents on a device | `vpt-incident-storm` | `alerts` |
| Device incident ongoing | `vpt-incident-active` | `alerts` |
| Script failing repeatedly | `vpt-script-failure-streak` | `script_results` |
| Script pass rate dropped | `vpt-script-regression` | `script_results` |
| Fleet health: device DOWN | `vpt-fleet-device-down` | `fleet_health` |
| Platform service down | `vpt-service-down` | `service_status` |
| Platform service degraded | `vpt-service-degraded` | `service_status` |
| Infra VM disk almost full | `vpt-infra-vm-disk-high` | `vm_metrics` |
| Infra VM memory high | `vpt-infra-vm-memory-high` | `vm_metrics` |

The platform service rules need the migration `20261001e_infra_status.sql`. It is filled once a minute by the server's
infra-status collector and the VM agents. A component no longer collected shows as *stale* for up to a day. The
*All hosts stopped reporting* rule also needs at least one host seen in the last day. The component `agent` means the
infra machine itself is off or unreachable. Set the degraded rule's threshold to 0 to include DEGRADED in the fleet rule.

**Why is *Device incident ongoing* opt-in?** An idle device on a static menu can report a freeze that lasts for hours.
That is expected. Turn the rule on for devices that play live content all day, or limit it with
`AND incident_type IN ('blackscreen', 'audio_loss')`.

**How *Script pass rate dropped* decides.** It compares, per script and user interface, the share of passed runs in
the last 24 hours with the 7 days before. It only judges a script with at least 3 runs today and 5 in the baseline.

**Severity bands, detail.** The only `[critical]` rule is `vpt-system-down`. `vpt-fleet-all-hosts-offline` and
`vpt-service-down` are `[major]`. `vpt-host-offline`, `vpt-capture-not-running` and `vpt-fleet-device-down` are
`[minor]`. Under the old two-band scheme, all serious alerts were `[critical]`. To route `[major]` quieter, add
`severity = major` to the on-call route that already matches `severity = critical`.

**Grafana's default email** shows raw query values (`Values: A=2 C=1`). The VirtualPyTest template leaves that out. The
full detail is one click away in Grafana.

</div>

**Severity bands.** Each rule fires at one of four bands, from most to least impact:

- **critical**: the whole system is down, every host silent. Only *All hosts stopped reporting* uses it.
- **major**: a whole site is offline, or a platform component is down long enough to block users.
- **minor**: one host, one device's capture, or one fleet-health verdict. Most of the fleet still works.
- **warning**: resource or quality thresholds, such as disk, memory, CPU temperature and regressions.

**The email** is one digest per group. The subject counts the alerts. Each alert has one line with its band, rule,
place and value. A `NEW` flag marks alerts that were not in the last digest. Read it like this:

```text
Subject: [VirtualPyTest] 4 firing, 2 resolved

FIRING (4)
- [critical · NEW] All hosts stopped reporting (system down): all hosts stopped reporting
     1 (1 known hosts across the platform, last seen any of them is older than 10 min)
     start=2026-10-16 07:18
- [major] Platform service down: storage / minio is down (seen by vpt-pi4)  start=2026-10-16 06:42
- [minor · NEW] Host stopped reporting: labox-dongle has not reported metrics for 8 min
     start=2026-10-16 07:24
- [minor] Host stopped reporting: labox-mobile has not reported metrics for 21 min
     start=2026-10-16 07:11

RESOLVED (2)
- [was warning] Host disk almost full: host-clone-1 disk at 85.1%
     start=2026-10-15 22:14  end=2026-10-16 06:55
- [was major] Platform service down: redis on vpt-pi3 returned to ok
     start=2026-10-16 07:01  end=2026-10-16 07:18

All VirtualPyTest alerts: https://your-host/grafana/alerting/list?search=label:source%3Dvirtualpytest
```

<div data-technical>

`NEW` compares each alert's identity (its `uid` plus its labels) with the saved set in
`.grafana_alert_digest_state.json`. Resolved alerts stay in that file for seven days, sliding. An alert's `start` is
when it left `pending` and became `alerting`. `end` is shown only for alerts that resolved in the digest window.

</div>

---

## 5. Create or change an alert by hand

You can build any alert in the Grafana UI. Example: the disk alert.

1. **Alerting → Contact points → + Add contact point.** Choose **Email**, enter the addresses separated by `;`,
   press **Test**, then **Save**.
2. **Alerting → Alert rules → + New alert rule.** Name it `Host disk almost full`.
3. **Define query.** Choose **Supabase PostgreSQL**, switch to **Code**, set **Format** to **Table**, and paste the SQL
   below. **Preview** shows one row per host.

   <div data-technical>

   ```sql
   SELECT DISTINCT ON (server_name, host_name)
          coalesce(server_name, '') AS server_name, host_name, disk_percent::float AS value
   FROM system_metrics
   WHERE "timestamp" > now() - interval '15 minutes'
   ORDER BY server_name, host_name, "timestamp" DESC
   ```

   </div>

4. **Expressions.** Keep only a **Threshold** on query **A**: *IS ABOVE* `85`. A *Reduce* step is not needed.
5. **Folder and labels.** Pick a folder, and add the label `severity = warning`.
6. **Evaluation.** Group interval **1m**, pending period `10m`.
7. **No data.** Set **Alert state if no data** to **OK**.
8. **Notifications.** Choose **Use notification policy** to join the grouped VirtualPyTest email.
9. **Annotations → Summary.** Enter a message with the host name and the value.

   <div data-technical>

   Add the label `source = virtualpytest` so the rule joins the grouped email. Summary template:
   `{{ $labels.host_name }} disk at {{ printf "%.1f" $values.A.Value }}%`. Choosing a contact point directly
   sends that rule's mails on their own, with Grafana's default timing.

   </div>

10. **Save rule and exit.**

To change a predefined rule later: **Alerting → Alert rules → VirtualPyTest Alerts → the rule → Edit**. The catalog
copy is `infra/monitoring/grafana/alerting/vpt-alert-rules.json`.

---

## 6. Write your own alert

Any question you can answer with a SQL query can become an alert.

- One row per thing to watch. Text columns name it in the message.
- One number, called `value`, is compared with the threshold.
- No rows means healthy. Set *Alert state if no data* to **OK**.

<div data-technical>

Rules of thumb: text columns become labels (`host_name`, `device_name`). Always limit the query by time, for example
`WHERE started_at > now() - interval '...'`. Tables that belong to a team (`script_results`, campaign and deployment
results) must be filtered by your `team_id`.

Ideas and the data they use:

| Alert | Table · column |
|---|---|
| Internet download speed below N Mbps | `system_metrics.download_mbps` |
| Host load average too high for 15 min | `system_metrics.load_average_15m` |
| Campaign or script did not run today | `script_results.started_at` (count = 0 → return a row with value 1) |
| Scheduled deployment keeps failing | `deployment_executions` |
| New incident type on a device | `alerts.incident_type` vs the last 7 days |
| KPI above its target | `script_results.metadata` |

Example: the same script fails on **every** device, which points to the app rather than the devices.

```sql
SELECT script_name,
       count(DISTINCT host_name || ':' || device_name) FILTER (WHERE NOT success)::float AS value
FROM script_results
WHERE team_id = '<your team id>' AND environment = 'prod' AND NOT coalesce(discard, false)
  AND started_at > now() - interval '2 hours'
GROUP BY script_name
HAVING bool_and(NOT success)
```

Threshold: *IS ABOVE* `1` (failing on at least two devices, and no run passed).

</div>

---

## 7. Tuning

**Who gets what.** Use one contact point per audience, for example *Ops* for host rules and *QA* for script rules.
Pick it in each rule, or route by label with **Notification policies**. A good split by band:

| Band | Suggested contact point |
|---|---|
| critical | on-call (PagerDuty, Opsgenie or an on-call email) |
| major | on-call or the platform lead |
| minor | the ops mailing list |
| warning | the product mailing list |

<div data-technical>

Matchers: `severity = critical`, `severity = major`, `severity = minor`, `severity = warning`. Your own per-band routes
go in **Alerting → Contact points** and **Notification policies**, as siblings of the policy `vpt-alerts`. `apply`
only rewrites the policy whose matcher is `source = virtualpytest`.

</div>

**How many mails.** Grafana sends one mail per group, not per alert. With the defaults you get at most one
VirtualPyTest mail per hour, and one daily reminder while something stays broken. The first mail after a quiet
period goes out after a short wait.

| Setting | Default | What it does |
|---|---|---|
| Group by | all | What shares a mail: all alerts, one rule, or one host |
| Group wait | 1 minute | How long a new group waits to collect alerts |
| Group interval | 1 hour | At most one mail per group in this time |
| Repeat interval | 24 hours | Reminder for alerts still firing. At least the group interval |

<div data-technical>

Options: `--group-by` (`all`, `rule`, `host`; default `--group-by all`), `--group-wait` (default `1m`),
`--group-interval` (default `1h`) and `--repeat-interval` (default `24h`). Examples:

```bash
# Quietest: one digest, at most every 4 hours, reminder once a day
python3 scripts/grafana_alerts.py apply --email ops@example.com --group-interval 4h --repeat-interval 24h
# Faster for critical labs: one mail per rule, at most every 15 minutes
python3 scripts/grafana_alerts.py apply --email ops@example.com --group-by rule --group-interval 15m --repeat-interval 4h
```

In the UI: **Alerting → Notification policies →** the policy matching `source = virtualpytest` **→ Edit → Override
general timings / Group by**. A re-run of the script puts back the values it is given.

</div>

**Silences and mute timings.**

- **Silences** (*Alerting → Silences*) mute matching alerts for a set time. Every alert email also has a **Silence** link.
- **Mute timings** (*Alerting → Notification policies → Mute timings*) mute on a schedule, such as nights and weekends.

<div data-technical>

Example silence matcher: `host_name = host-3`.

</div>

**Pending period** is how long a condition must last before the alert fires. Raise it if an alert flaps. Lower it if
you need to know sooner.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| The test works, but no alert mail comes | Open the rule and check its state and history. Check its *Notifications* section and **Notification policies**. |
| The test fails with connection refused or timeout | Check the host and port. The Grafana machine may be blocked from the mail server. |
| The test fails with an authentication error | Check the user and password. Gmail needs an app password. Microsoft 365 needs SMTP AUTH. |
| No email, and nothing in the logs | Check that email is switched on in the settings, and that Grafana was restarted. |
| Rule state is **Error** | Open the rule and press **Preview**. It shows the database error. |
| Rule is always **Normal** | The query returns no row above the threshold. **Preview** shows the numbers. |
| Mail goes to the placeholder address | Set a real address on the default contact point (see §2). |
| `apply` warns that the policy is not active yet | The first alerts may go to the default contact point. Later ones follow the policy. |
| Still too many mails | Raise the group interval, or silence a known problem. |
| Too many *Device incident ongoing* mails | Restrict the rule (see §4) or leave it off. |
| Thresholds changed in the UI came back | The script was re-run and reset the rules (see §3). |

<div data-technical>

Exact messages and places to look: `sent test email to ...` (success), `FAILED` (failure), `535 authentication failed`,
the placeholder `example@email.com`, and `policy WARNING: not active yet` (Grafana had not loaded the new policy after 135 s). Grafana's log is
`/var/log/grafana/grafana.log`; search it for `smtp` or `notifier`. The setting is `[smtp] enabled = true`.

</div>

Related: [Running Tests](./running-tests.md) · [Who can do what](../agent/platform/ACCESS_MODEL.md) (who can see
which devices on the dashboards — alert rules see all data, they are not limited per viewer).
