# BUG-0603 — `install_host_windows.ps1` did not parse under Windows PowerShell 5.1 (encoder + a stray brace)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0603                                                     |
| Reported  | 2026-10-17                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | setup / Windows install                                      |
| Fixed in  | build 90145 |
| Commit    | `shortHash` (or "TBD")                                       |

---

## Symptom

`setup/local/windows/backend_host/install_host_windows.ps1`, the maintained
Windows-host installer, could not be executed by Windows PowerShell 5.1. The
parser reported a cascade of errors starting at the "VirtualPyTest VNC" firewall
rule and finishing with `missing closing '}'`, so the whole file was rejected
before any function ran. The only installers that worked were the two
hand-maintained ASCII snapshots at the repo root
(`install_host_windows_fixed.ps1`, `install_host_windows_ascii.ps1`).

## Root cause

Two independent defects, both invisible on Linux/macOS:

1. **UTF-8 without a BOM read as ANSI.** The file held 15 em dashes (`—`,
   U+2014) and two `é` (U+00E9) — in comments and in
   `Description = "… (LAN only — no VNC authentication)"`. PowerShell 5.1
   decodes a BOM-less `.ps1` with the ANSI code page; on this French Windows
   the em dash's bytes `E2 80 94` become `â€”`, and `0x94` is the cp1252 smart
   quote — PowerShell treats it as a closing string delimiter, so the string
   ends early and the object literal breaks.
2. **A stray `}` at line 530.** The BUG-0600 hardening added
   `Ensure-TaskEnabled -TaskName $script:HOST_TASK_NAME` at the end of
   `Install-HostScheduledTask` and left one extra closing brace after the
   function. Brace depth went `0 → -2` there, which no encoding fix can hide.

Neither defect appears when the file is parsed by PowerShell 7 (which assumes
UTF-8), which is how it slipped through review.

## Fix

`setup/local/windows/backend_host/install_host_windows.ps1`:

- Replaced every non-ASCII character with its ASCII equivalent
  (`—`/`–` → `-`, `é` → `e`, plus the smart quotes and ellipsis in the same
  map) so the file is pure ASCII, matching the two root snapshots.
- Removed the stray `}` after `Install-HostScheduledTask`.

No code path, comment meaning or string value (other than the dash in the
firewall-rule description) changes.

`setup/local/windows/README.md` now states the rule: keep `.ps1` files
ASCII-only, because Windows PowerShell 5.1 reads a BOM-less script as ANSI and
a multi-byte character can terminate a string.

## Verification

- Parsed on the live `vpt-windows` host with the Windows PowerShell 5.1
  parser (`[System.Management.Automation.Language.Parser]::ParseFile`):
  `0` errors. Before the fix the same parser reported 1 error (after the
  encoding-only fix) and 7 errors (before it).
- `LC_ALL=C grep -c '[^ -~]'` on the file: `0` non-ASCII lines.
- Diff is confined to the 17 replaced characters and the deleted brace line.
