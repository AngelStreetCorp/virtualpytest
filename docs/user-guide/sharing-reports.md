# Sharing a test report

Send one test report to someone who has no VPT account: a partner, a customer, a colleague
outside the team. They open a link and see the report as it looks in VPT, with its steps,
screenshots, verification images and video. The link works for the time you choose, and you can
protect it with a password.

## Make a link

1. Open **Test → Test Reports**.
2. On the run's row, click the **Share** icon next to the report link.
3. Choose:
   - **Expires after**: 1 hour, 1 day, 7 days (default) or 30 days.
   - **Protect with a password** (off by default, at least 8 characters). The person needs the
     password to open the link. Send it to them some other way than the link itself.
   - **Include video** (on by default). Without it the link is smaller and loads faster.
4. Click **Create link** and copy it.

The dialog also shows a **delete link**, only once. Keep it if you want to be able to revoke the
link without logging in.

## What the person sees

- The report page itself, with a banner saying it is a shared snapshot and when it expires.
- Steps, step screenshots, verification reference images, the mosaic and the video.
- **Not included:** execution logs, the script source, run metadata, live device views and links
  back into VPT. These can contain tokens, addresses or internal names. Each removed link stays
  visible with the note *"not included in the snapshot"*.
- **Masked:** the value of typed or secret-like action parameters (`text`, `password`, `pin`,
  `code`, `token`, `secret`, `value`, `api_key`) shows as `•••`, and `url` / `href`
  parameters lose their query string. Remote key presses (`key='OK'`) stay visible. Text
  verifications (`text='Home'`) are masked too. Check the report before sharing: free text a script prints
  elsewhere is not rewritten.
- Only files that belong to the report are copied into the snapshot: its own folder, step
  screenshots and verification reference images. A file a report merely names in its text, or
  that sits elsewhere in storage, is left out.

The link shows a **frozen copy** made when you clicked Create. It keeps working after the
original run is cleaned up (test reports are kept for 14 days) and until the link expires.

## Revoke a link

- In the Share dialog, under **Active links for this report**, click **Revoke**. The creator, a
  manager or an admin can revoke it.
- Or open the delete link and confirm.

A revoked link answers *"This shared report has expired or was revoked"* and its copy is deleted
from storage immediately (when the server that built the copy handles the revoke; otherwise that
server's cleanup removes it within 15 minutes). An expired link's copy is deleted by the same
cleanup, within 15 minutes of expiry. The row stays in the list as history.

## See and revoke every shared link

**Test Reports > Shared links** (shown when sharing is on) lists the links of your team, not only
those of one report. Filter by **Active** (default), **Expired**, **Revoked** or **All**, and by
report name or creator. Each row shows the report (click to open the original report while it
still exists), device, creation time, creator ("Service" for a link made through the API), time to
expiry, password, video, size, views and last view. The creator, a manager or an admin sees a
**Revoke** button on a row that is not revoked yet (click, then **Confirm revoke**); other rows show a status
chip. The footer shows the number of active links and the team quota used.

The list cannot reopen a link: only a hash of the key is stored, so the link is shown once, at
creation.

## Who can share

| | Can create links | Can revoke |
|---|---|---|
| Admin, Manager | yes | every link of the team |
| Developer, Tester | yes | their own links |
| Viewer | no | no |

Creating a link needs the `reports.tests:share` permission, which these roles have by default. An
admin can remove it from a role or a person on the Users page, see [Who can do what](./permissions.md).

## Turning the feature on

Sharing is off on a new installation. To turn it on, set the following in the backend server's
`.env` and restart the server:

```
REPORT_SHARING_ENABLED=true
```

While it is off, the Share icon is hidden and existing links stop opening. Each server serves only
the links it created, because the copy lives in that server's storage.

## Limits

- One link holds at most **150 MB** (a long run's video is the usual reason to go over; untick
  *Include video*).
- A team keeps at most **5 GB** of live links. Revoke old links to free space.
- Runs older than 14 days can no longer be shared: their files are already gone.
- Search engines are told not to index shared links. Still, anyone holding the link can open it
  until it expires, so prefer short expiries and a password for anything sensitive.
