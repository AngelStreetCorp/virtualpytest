Yes — Windows can auto-select a specific user even when multiple accounts exist. The `netplwiz` method normally handles both:

* selecting the account
* logging in automatically

If it still stops at the user selection screen, use the registry method because it forces a specific account.

### Reliable setup for multi-user Windows 11

Open Registry Editor:

```text
Win + R → regedit
```

Go to:

```text
HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon
```

Set these values exactly:

| Key               | Type   | Value                  |
| ----------------- | ------ | ---------------------- |
| `AutoAdminLogon`  | String | `1`                    |
| `DefaultUserName` | String | exact Windows username |
| `DefaultPassword` | String | your password          |
| `ForceAutoLogon`  | String | `1`                    |

If using a Microsoft account:

```text
DefaultUserName = your@email.com
```

If using a local account, also add:

| Key                 | Value         |
| ------------------- | ------------- |
| `DefaultDomainName` | computer name |

You can find the computer name with:

```text
Settings → System → About
```

or:

```cmd
hostname
```

Example:

```text
DefaultDomainName = DESKTOP-ABCD123
```

---

### Important

Windows may still interrupt auto-login if:

* another user is still signed in
* Fast User Switching is active
* Windows Update forced a restart
* a policy requires sign-in

To improve reliability:

#### Disable “Use my sign-in info…”

Settings → Accounts → Sign-in options

Disable:

> “Use my sign-in info to automatically finish setting up after an update”

#### Ensure other users are fully signed out

Not just “Switch user”.

---

### Most reliable enterprise-style solution

Microsoft provides an official tool:

**Sysinternals Autologon**

From [Microsoft Sysinternals](https://learn.microsoft.com/en-us/sysinternals/downloads/autologon?utm_source=chatgpt.com)

It securely configures:

* username
* domain
* encrypted password
* automatic login

This is generally more reliable than manual registry edits on Windows 11.
