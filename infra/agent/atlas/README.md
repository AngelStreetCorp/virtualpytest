# Atlas FAQ nightly pass — systemd units

The Atlas Prepared FAQ has two jobs that must run on their own: the **review pass** (promote the
reviewed `proposed` rows to `live`) and the **alias top-up** (give the rows that have no aliases a
set of validated user wordings). Both live in `scripts/agent/faq_nightly.sh`.

The units below are installed by hand on node1, like the other `vpt-*` timers. They are kept here
as the source of truth — the integration lane treats a `*.service` / `*.timer` file as a sensitive
path (it changes infra), so the definitions live in this document and are copied to
`/etc/systemd/system`.

## Install (node1, once)

```bash
sudo install -m 644 -o root -g root /opt/virtualpytest/infra/agent/atlas/vpt-faq-review.service /etc/systemd/system/
sudo install -m 644 -o root -g root /opt/virtualpytest/infra/agent/atlas/vpt-faq-review.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vpt-faq-review.timer
```

Check it:

```bash
systemctl list-timers | grep vpt-faq-review
sudo systemctl start vpt-faq-review.service     # run it once, now
journalctl -u vpt-faq-review.service -n 40      # read what it did
```

## `vpt-faq-review.timer`

```ini
[Unit]
# Nightly at 04:05, after the Localize accuracy benchmark (03:40) and before the 07:00 fleet health report.
Description=VPT Atlas FAQ nightly review (TASK-152)

[Timer]
OnCalendar=*-*-* 04:05:00
Persistent=true
Unit=vpt-faq-review.service

[Install]
WantedBy=timers.target
```

## `vpt-faq-review.service`

```ini
[Unit]
# vpt-faq-review.service — the Atlas Prepared FAQ nightly pass (TASK-152).
#
# Runs scripts/agent/faq_nightly.sh, which promotes the reviewed proposed rows to live and then
# tops up the aliases of the rows that have none. The pass was written in phase 9b but never
# scheduled: no timer, no cron entry, no pm2 job, so the proposed rows stayed proposed and the
# self-promotion loop never advanced.
#
# Runs on node1 (the server): it needs the repo and the DB keys in /opt/virtualpytest/.env.
Description=VPT Atlas FAQ nightly review (TASK-152)

[Service]
Type=oneshot
User=vpt_user
WorkingDirectory=/opt/virtualpytest
ExecStart=/bin/bash /opt/virtualpytest/scripts/agent/faq_nightly.sh
Nice=15
CPUQuota=50%
Restart=no
StandardOutput=journal
StandardError=journal
```

## Why it is a timer and not a cron entry

The other `vpt-*` jobs on this box are systemd timers, and a timer that missed its slot (the
machine was down) runs on the next boot (`Persistent=true`). A crontab entry would silently skip
the night the box was off — and the review pass is exactly the kind of job whose delay is
invisible until the corpus goes stale.

The script is idempotent: the review flips only the rows that are eligible, and the alias top-up
only writes aliases on rows that have none (or whose alias set is broken and has been regenerated).
