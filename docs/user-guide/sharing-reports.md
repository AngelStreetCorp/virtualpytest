# Sharing a test report

Send one test report to someone who has no VPT account. They open a link and see the report as it looks in VPT. The link stops working after the time you choose.

## Make a link

1. Open **Test → Test Reports**.
2. On the run's row, click the **Share** icon next to the report link.
3. Choose:
   - **Expires after**: 1 hour, 1 day, 7 days (default) or 30 days.
   - **Protect with a password** (off by default, at least 8 characters). Send the password some other way than the link.
   - **Include video** (on by default). Turn it off for a smaller link that loads faster.
4. Click **Create link** and copy it.

The dialog shows a **delete link** only once. Keep it if you want to revoke the link without logging in.

## What the person sees

- The report, with a banner that says it is a shared copy and when it expires.
- Steps, screenshots, reference images, the mosaic and the video.
- **Not included:** execution logs, the script, run details, live device views and links back into VPT. Each removed item shows *"not included in the snapshot"*.
- **Hidden values:** typed or secret-like values show as `•••`, and web addresses lose their query string. Check the report before you share it.

<div data-technical>

Masked action parameters: `text`, `password`, `pin`, `code`, `token`, `secret`, `value`, `api_key` show as `•••`. `url` and `href` parameters lose their query string. Remote key presses (`key='OK'`) stay visible. Text verifications (`text='Home'`) are masked too. Free text a script prints elsewhere is not rewritten.

Only files that belong to the report are copied into the snapshot: its own folder, step screenshots and verification reference images. A file a report merely names in its text, or that sits elsewhere in storage, is left out.

</div>

The link shows a **frozen copy**, so it still works after the original run is cleaned up.

## Revoke a link

- In the Share dialog, under **Active links for this report**, click **Revoke**. The creator, a manager or an admin can revoke it.
- Or open the delete link and confirm.

A revoked link shows *"This shared report has expired or was revoked"*. Its copy is deleted soon after. The row stays in the list as history.

<div data-technical>

A revoked copy is deleted from storage immediately, when the server that built the copy handles the revoke. Otherwise that server's cleanup removes it within 15 minutes. An expired link's copy is deleted by the same cleanup, within 15 minutes of expiry.

</div>

## See and revoke every shared link

Open **Test Reports > Shared links** (shown when sharing is on). It lists the links of your whole team, with their status, time left and how often each was opened. The footer shows how many links are active and how much of the team quota is used.

Admins, managers and the person who made a link can revoke it: click **Revoke**, then **Confirm revoke**. A link is shown only once, when you create it.

<div data-technical>

Filters: **Active** (default), **Expired**, **Revoked** or **All**, plus report name and creator. Each row shows the report, the device, when the link was made and who made it. The creator reads "Service" for a link made through the API. Rows that are already revoked or expired show a status chip instead of a Revoke button. Only a hash of the key is stored, which is why the list cannot show the link again.

</div>

## Who can share

| | Can create links | Can revoke |
|---|---|---|
| Admin, Manager | yes | every link of the team |
| Developer, Tester | yes | their own links |
| Viewer | no | no |

<div data-technical>

Creating a link needs the `reports.tests:share` permission, which these roles have by default. An admin can remove it from a role or a person on the Users page.

</div>

For the full picture, see [Who can do what](../agent/platform/ACCESS_MODEL.md).

## Turning the feature on

Sharing is off on a new installation. An admin turns it on with a server setting, then restarts the server. While it is off, the Share icon is hidden and existing links stop opening. Each server serves only the links it created.

<div data-technical>

Set this in the backend server's `.env`, then restart the server:

```
REPORT_SHARING_ENABLED=true
```

Each copy lives in that server's storage, which is why each server serves only its own links.

</div>

## Limits

- One link holds at most **150 MB**. A long run's video is the usual reason. Untick *Include video* to make it smaller.
- A team keeps at most **5 GB** of live links. Revoke old links to free up space.
- Test reports are kept for 14 days, so runs older than that can no longer be shared.
- Anyone who holds a link can open it until it expires. Use short expiries and a password for anything sensitive.

<div data-technical>

Search engines are told not to index shared links.

</div>
