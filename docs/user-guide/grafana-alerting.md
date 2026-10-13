# Grafana Alerting — Get Told When Something Breaks

VirtualPyTest writes everything it sees to the database: host health every minute, capture
status per device, every incident (blackscreen, freeze, audio loss, macroblocks), every script
result, the fleet-health check. Grafana dashboards show that data; **Grafana alerting** watches it
for you and sends an email (or a Slack / Teams / webhook message) when something goes wrong.

This page covers:

1. [What alerting can do](#1-what-alerting-can-do)
2. [Prerequisites — SMTP for email](#2-prerequisites)
3. [Apply the predefined alerts with one command](#3-apply-the-predefined-alerts-script)
4. [The predefined alerts](#4-the-predefined-alerts)
5. [Create or change an alert by hand in Grafana](#5-create-or-change-an-alert-by-hand)
6. [Write your own alert](#6-write-your-own-alert)
7. [Tuning: who gets what, how often, silences](#7-tuning)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. What alerting can do

An **alert rule** runs a SQL query against the VirtualPyTest database on a schedule (every 1, 5
or 15 minutes), compares each row's number to a threshold and, when it stays above it for a
while, **fires**. A firing alert is sent to a **contact point** — a list of email addresses, a
Slack channel, a Teams webhook... When the problem goes away, a **resolved** message follows.

Typical uses:

| You want to know when... | Data it reads |
|---|---|
| a host stops reporting (service down, machine off, network lost) | `system_metrics` |
| a platform service (server, Supabase, Redis, DB backup, MinIO...) or an infra VM is down, or an infra VM's disk / memory is high | `service_status`, `vm_metrics` (System Service Status) |
| a disk is almost full, memory or CPU temperature is too high | `system_metrics` |
| the video capture or the monitor of a device stopped | `system_device_metrics` |
| a device has an incident, or far too many incidents | `alerts` (the device incidents table) |
| a script keeps failing, or its pass rate suddenly dropped (a regression) | `script_results` |
| the fleet-health check marks a device DOWN | `fleet_health` |

One rule watches every host / device / script at once: each row the query returns is its own
alert (Grafana calls it an *instance*), with the host, device or script name in the message.

---

## 2. Prerequisites

| What | Why | Check |
|---|---|---|
| Grafana **11 or newer** | the alerting described here (unified alerting) is on by default | Grafana → **Help (?)** shows the version |
| The **Supabase PostgreSQL** data source, uid `supabase-postgres` | every predefined rule queries it; the installer creates it | Connections → Data sources |
| A Grafana **admin** login | to create rules and contact points | — |
| An **SMTP server** — for email only | Grafana sends email itself, through SMTP | see below |

Slack, Microsoft Teams, Telegram, Discord, PagerDuty, Opsgenie and plain webhooks do **not** need
SMTP — only a webhook URL or token, entered in the contact point.

### Configure SMTP

Grafana's email settings live in `/etc/grafana/grafana.ini`, section `[smtp]` (the template
shipped in `infra/monitoring/grafana/config/grafana.ini` has them all commented out — email is
off until you set them). Edit the file on the Grafana machine:

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

Then restart Grafana:

```bash
sudo systemctl restart grafana-server
```

Running Grafana in Docker? Use environment variables instead of editing the file —
`GF_SMTP_ENABLED=true`, `GF_SMTP_HOST`, `GF_SMTP_USER`, `GF_SMTP_PASSWORD`,
`GF_SMTP_FROM_ADDRESS`, `GF_SMTP_FROM_NAME` — and recreate the container.

Common providers:

| Provider | `host` | Notes |
|---|---|---|
| Gmail / Google Workspace | `smtp.gmail.com:587` | needs 2-step verification and an **app password**, not your normal password |
| Microsoft 365 | `smtp.office365.com:587` | SMTP AUTH must be enabled for the mailbox |
| Amazon SES | `email-smtp.<region>.amazonaws.com:587` | SMTP credentials from the SES console; verify the sender |
| Brevo, Mailgun, SendGrid... | see the provider | any SMTP relay works |
| Your company relay | `mail.yourcompany.local:25` | often no user/password; `startTLS_policy = NoStartTLS` if it has no TLS |

**Test it** — either in Grafana (**Alerting → Contact points → Edit → Test**) or with the script:

```bash
python3 scripts/grafana_alerts.py test-email --email you@example.com
```

`sent test email to you@example.com` means Grafana handed the mail to your SMTP server. A
`FAILED` line prints the SMTP error (wrong password, port blocked, sender not allowed...).

> **Set Grafana's default contact point to a real address too.** Out of the box it is
> `grafana-default-email` with the placeholder `<example@email.com>`. Any alert that is not
> routed anywhere else goes there. Edit it under **Alerting → Contact points**.

---

## 3. Apply the predefined alerts (script)

`scripts/grafana_alerts.py` creates everything in one go: a folder **VirtualPyTest Alerts**, an
email contact point **VirtualPyTest email** with a short digest email template, a notification
policy that groups the alerts and limits how often mail is sent ([§7](#7-tuning)), and the rules. Run it where it can reach Grafana —
normally on the server VM, from the repository, so it reads `GRAFANA_URL`,
`GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` and `TEAM_ID` from the `.env` like the server does.

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

# Take it all away again
python3 scripts/grafana_alerts.py remove
```

Options: `--grafana-url https://your-host/grafana` overrides `GRAFANA_URL` (include the sub-path
if Grafana is served under one); `--insecure` accepts a self-signed certificate; `--team-id`
says whose script results the *Test results* rules watch (defaults to `TEAM_ID` from `.env`).
Mail volume: `--group-by`, `--group-wait`, `--group-interval`, `--repeat-interval` — see
[§7](#7-tuning). `apply` takes up to about a minute: it waits until Grafana is actually using the
new notification policy before it creates the rules.

Things to know:

- **Safe to re-run.** Re-running updates the contact point's addresses, the mail timing and the
  template, and resets the rules to the catalog. It also **overwrites thresholds you changed in the UI** — so either tune in the catalog file (`infra/monitoring/grafana/alerting/vpt-alert-rules.json`)
  and re-run, or tune in the UI and stop re-running.
- **Keep your own rules out of the *VirtualPyTest Alerts* folder.** The script owns the rule
  groups in it; a rule you add to one of them is removed on the next run.
- The rules stay **editable in the Grafana UI** (they are not locked as "provisioned").

---

## 4. The predefined alerts

All thresholds are starting points — change them to fit your lab.

| Rule (uid) | Fires when | Threshold · wait | Severity | Default |
|---|---|---|---|---|
| **Host stopped reporting** (`vpt-host-offline`) | no metrics from a host for longer than the threshold | > 10 min · 5 min | critical | ✅ |
| **Host disk almost full** (`vpt-host-disk-high`) | root disk use | > 85 % · 10 min | warning | ✅ |
| **Host memory high** (`vpt-host-memory-high`) | memory use | > 90 % · 15 min | warning | ✅ |
| **Host CPU too hot** (`vpt-host-cpu-temp-high`) | CPU temperature (hosts that report one, e.g. Raspberry Pi) | > 80 °C · 10 min | warning | ✅ |
| **Capture or monitor not running** (`vpt-capture-not-running`) | a device's ffmpeg capture or monitor is not `active` | any · 10 min | critical | ✅ |
| **Too many incidents on a device** (`vpt-incident-storm`) | incidents started on one device in the last hour | > 20 | warning | ✅ |
| **Device incident ongoing** (`vpt-incident-active`) | a blackscreen / freeze / audio loss / macroblocks incident still open | > 10 min | warning | opt-in |
| **Script failing repeatedly** (`vpt-script-failure-streak`) | the last runs of a script on a device all failed (prod, not discarded) | ≥ 3 in a row | warning | ✅ |
| **Script pass rate dropped** (`vpt-script-regression`) | a script's pass rate over the last 24 h vs its previous 7 days | drop > 30 points | warning | ✅ |
| **Fleet health: device DOWN** (`vpt-fleet-device-down`) | the latest fleet-health check marks a device DOWN (set the threshold to 0 for DEGRADED too) | DOWN | critical | ✅ |
| **Platform service down** (`vpt-service-down`) | a component of the System Service Status page is `down`, or was not checked for 3 min (*stale*); component `agent` = the infra VM itself is off or unreachable | any · 3 min | critical | ✅ ¹ |
| **Platform service degraded** (`vpt-service-degraded`) | a component reports `degraded` | 15 min | warning | opt-in ¹ |
| **Infra VM disk almost full** (`vpt-infra-vm-disk-high`) | root disk of the database, storage, frontend, proxy... VM | > 85 % · 10 min | warning | ✅ ¹ |
| **Infra VM memory high** (`vpt-infra-vm-memory-high`) | memory of an infra VM | > 90 % · 15 min | warning | ✅ ¹ |

¹ *Platform services* rules read the tables of the System Service Status feature (`service_status`,
`vm_metrics`, migration `20261001e_infra_status.sql`, filled once a minute by the server's
infra-status collector and the VM agents). Until that migration is applied, `apply` skips these
rules and says so — re-run it afterwards. A component that is no longer collected (removed from
the install) shows as *stale* for up to a day.

**Why is *Device incident ongoing* opt-in?** A device that sits idle on a static menu reports a
*freeze* that can last for hours — that is expected, not a fault. Turn the rule on when your
devices play live content all day, or copy it and restrict the query to the incident types and
devices you care about (`AND incident_type IN ('blackscreen', 'audio_loss')`).

**How *Script pass rate dropped* decides.** It compares, per script and userinterface, the share
of passed runs over the last 24 hours with the 7 days before. It only judges scripts with at
least 3 runs today and 5 in the baseline, so a script that ran once does not trigger it. A drop
of more than 30 points (say 95 % → 60 %) usually means a new app build or device firmware.

**The email** is one digest per group: the subject counts the alerts, the body has one line per
alert — severity, rule, and what and where, with the measured value — and one link to all
VirtualPyTest alerts in Grafana:

```text
Subject: [VirtualPyTest] 3 firing, 1 resolved

FIRING (3)
- [warning] Too many incidents on a device: appletv (host-3): 31 incidents in the last hour
- [warning] Script failing repeatedly: dns_lookuptime failed 161 times in a row on host-1_Host
- [critical] Fleet health: device DOWN: Fleet health: host-4_Host on host-4 is DOWN

RESOLVED (1)
- Host disk almost full: host-2 disk at 84.9%

All VirtualPyTest alerts: https://your-host/grafana/alerting/list?search=label:source%3Dvirtualpytest
```

Grafana's default email lists each alert's raw query results (`Values: A=2 C=1` — *A* is the
measured value, *C* is 1 because the threshold is crossed). The VirtualPyTest template leaves that
block out; the value is already in each line. The full detail (description, labels, a silence
link) is one click away in Grafana.

---

## 5. Create or change an alert by hand

You can do everything in the Grafana UI, without the script. Example: the disk alert.

1. **Alerting → Contact points → + Add contact point.** Name it, choose **Email**, enter the
   addresses (separate with `;`), **Test**, **Save**.
2. **Alerting → Alert rules → + New alert rule.**
3. **Name:** `Host disk almost full`.
4. **Define query:** data source **Supabase PostgreSQL**, switch the editor to **Code**, set
   **Format** to **Table**, and paste:

   ```sql
   SELECT DISTINCT ON (server_name, host_name)
          coalesce(server_name, '') AS server_name, host_name, disk_percent::float AS value
   FROM system_metrics
   WHERE "timestamp" > now() - interval '15 minutes'
   ORDER BY server_name, host_name, "timestamp" DESC
   ```

   **Preview** shows one row per host.
5. **Expressions:** keep only a **Threshold** on query **A**: *IS ABOVE* `85`. (Grafana may add
   a *Reduce* step; it is not needed — this query already returns one number per host.)
6. **Folder & labels:** pick or create a folder; add the label `severity = warning`.
7. **Evaluation:** an evaluation group with interval **1m**; **Pending period** `10m`.
8. **Configure no data and error handling:** set **Alert state if no data** to **OK** (no rows
   means nothing is wrong).
9. **Notifications:** to have this rule in the same grouped VirtualPyTest mail, add the label
   `source = virtualpytest` in step 6 and choose **Use notification policy**. Selecting a contact
   point directly instead sends this rule's mails on their own, with Grafana's default timing.
10. **Annotations → Summary:** `{{ $labels.host_name }} disk at {{ printf "%.1f" $values.A.Value }}%`.
11. **Save rule and exit.**

The SQL of every predefined rule is in `infra/monitoring/grafana/alerting/vpt-alert-rules.json`
— copy any of them the same way.

To change a predefined rule after the script created it: **Alerting → Alert rules → VirtualPyTest
Alerts → the rule → Edit**. Change the threshold in the *Threshold* expression, the waiting time
in *Pending period*.

---

## 6. Write your own alert

Any question you can answer with SQL can become an alert. The rule of thumb for the query:

- **One row per thing to watch** (host, device, script...).
- **Text columns become labels** — they name the thing in the message (`host_name`, `device_name`...).
- **One numeric column** (call it `value`) is compared to the threshold.
- **No rows = healthy.** Set *Alert state if no data* to **OK**.
- Keep it fast: always limit by time (`WHERE started_at > now() - interval '...'`).
- Tables that belong to a team (`script_results`, campaign and deployment results...) must be
  filtered by your `team_id`.

Ideas built on data VirtualPyTest already records:

| Alert | Table · column |
|---|---|
| Internet download speed on a host below N Mbps | `system_metrics.download_mbps` |
| Host load average too high for 15 min | `system_metrics.load_average_15m` |
| A specific campaign or script did not run today | `script_results.started_at` (count = 0 → return a row with value 1) |
| A scheduled deployment keeps failing | `deployment_executions` |
| New incident type on a device that never had it | `alerts.incident_type` vs the last 7 days |
| A KPI (zap time, boot time...) went above its target | `script_results.metadata` |

Example — the same script is failing on **every** device (more likely the app than the device):

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

---

## 7. Tuning

**Who gets what.** One contact point per audience: e.g. *Ops* for host rules, *QA* for script
rules. Either pick the contact point in each rule (*Notifications* section), or use
**Notification policies** to route by label — `severity = critical` to an on-call channel,
everything else to email.

**How many mails — avoiding spam.** Grafana does not send one mail per alert: it collects alerts
into **groups** and sends one mail per group. Four settings decide the volume; the script sets
them on the *source = virtualpytest* notification policy:

| Option | Default (script) | Meaning |
|---|---|---|
| `--group-by` | `all` | What shares a mail. `all`: every VirtualPyTest alert in one digest. `rule`: one mail per rule (disk alerts together, script alerts together...). `host`: one mail per host. |
| `--group-wait` | `1m` | How long a **new** group waits before its first mail, to collect alerts that fire together. |
| `--group-interval` | `1h` | **At most one mail per group per this interval.** Alerts that start or resolve in between are added to the next mail. |
| `--repeat-interval` | `24h` | When nothing changed, the still-firing alerts are mailed again after this long (a reminder). Must be ≥ the group interval. |

With the defaults a recipient gets **at most one VirtualPyTest mail per hour**, plus one daily
reminder while something stays broken. The only mail that does not wait an hour is the first
one after a quiet period (a new group): it goes out after `--group-wait`. Examples:

```bash
# Quietest: one digest, at most every 4 hours, reminder once a day
python3 scripts/grafana_alerts.py apply --email ops@example.com --group-interval 4h --repeat-interval 24h
# Faster for critical labs: one mail per rule, at most every 15 minutes
python3 scripts/grafana_alerts.py apply --email ops@example.com --group-by rule --group-interval 15m --repeat-interval 4h
```

The same settings are in the UI: **Alerting → Notification policies →** the policy matching
`source = virtualpytest` **→ Edit → Override general timings / Group by**. A re-run of the script
puts back the values it is given.

**Quiet hours / maintenance.**

- **Silences** (*Alerting → Silences*) mute matching alerts for a set time — e.g. `host_name = host-3`
  for the 2 hours you rewire it. A firing alert also has a **Silence** link in its email.
- **Mute timings** (*Alerting → Notification policies → Mute timings*) mute on a schedule —
  nights, weekends — and are attached to a notification policy.

**Pending period** (the *for* / *wait* column above) is how long a condition must last before
firing. Raise it if an alert flaps; lower it if you need to know sooner.

---

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Test email works but no alert mail | The rule is *Normal* / *Pending* — open it and look at its state and history. Or the alert went to another contact point: check the rule's *Notifications* section and **Notification policies**. |
| `FAILED ... connection refused / timeout` on the test | Wrong host/port, or the Grafana machine cannot reach it (outbound 25/465/587 blocked). |
| `535 authentication failed` | Wrong user/password; Gmail needs an app password; Microsoft 365 needs SMTP AUTH enabled. |
| No email at all and nothing in the logs | `[smtp] enabled = true` missing, or Grafana not restarted. Logs: `/var/log/grafana/grafana.log` (search `smtp` / `notifier`). |
| Rule state **Error** | The SQL fails — open the rule, **Preview** shows the database error. An email "DatasourceError" is sent for it. |
| Rule always **Normal** | The query returns no row above the threshold — **Preview** shows the numbers. |
| Mail sent to `example@email.com` | Grafana's default contact point still has its placeholder address — set a real one (see §2). |
| `apply` prints `policy WARNING: not active yet` | Grafana had not loaded the new policy after 135 s. The first alerts may go to the default contact point; the next ones follow the policy. |
| Still too many mails | Raise `--group-interval` (at most one mail per group per interval) or use `--group-by all`; silence a known, accepted problem instead of letting it repeat. |
| Too many *Device incident ongoing* mails | Idle devices report long freezes — restrict the rule (see §4) or leave it off. |
| Thresholds changed in the UI came back | The script was re-run — it resets rules to the catalog (see §3). |

Related: [Running Tests](./running-tests.md) · [Who can do what](./permissions.md) (who can see
which devices on the dashboards — alert rules see all data, they are not limited per viewer).
