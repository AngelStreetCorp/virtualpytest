#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Windows installer bootstrap: copy repo to a standard install root and re-exec from there.

.DESCRIPTION
  Mirrors the Linux "/opt/virtualpytest" pattern on Windows:
    - A stable code location (default: C:\virtualpytest\virtualpytest)
    - Installers run from the stable location so Windows services point to stable paths

  This enables using a "source of truth" repo checkout anywhere (or on a share),
  while each machine installs/runs from its own local folder.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-VptStandardProjectRoot {
  return "C:\virtualpytest\virtualpytest"
}

function Copy-VptProjectToStandardRoot {
  param(
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [Parameter(Mandatory = $true)][string]$DestRoot
  )

  if (-not (Test-Path $SourceRoot)) {
    throw "SourceRoot not found: $SourceRoot"
  }

  $null = New-Item -ItemType Directory -Path $DestRoot -Force

  # Copy everything needed to run installers/services, but don't overwrite local env config.
  # Exclude heavy build artifacts that should be re-installed on the target machine anyway.
  #
  # Important: robocopy does not support glob-style "**" patterns in /XD.
  $excludeDirs = @(
    ".git",
    "venv",
    "setup\\local\\venv",
    "frontend\\node_modules"
  )

  # Preserve local configuration in the destination. If destination is empty, installers will
  # create these from *.example templates.
  $excludeFileNames = @(
    ".env"
  )

  $robocopyArgs = @(
    $SourceRoot,
    $DestRoot,
    "/MIR",
    "/R:2",
    "/W:1",
    "/NFL",
    "/NDL",
    "/NJH",
    "/NJS",
    "/NP"
  )

  foreach ($d in $excludeDirs) {
    $robocopyArgs += "/XD"
    # Use a full path to avoid ambiguity and quoting issues.
    $robocopyArgs += (Join-Path $SourceRoot $d)
  }

  foreach ($f in $excludeFileNames) {
    $robocopyArgs += "/XF"
    $robocopyArgs += $f
  }

  Write-Host "[BOOTSTRAP] Copying VirtualPyTest repo to: $DestRoot"
  Write-Host "[BOOTSTRAP] Source: $SourceRoot"

  # Capture output so a failure is actionable.
  $out = & robocopy @robocopyArgs 2>&1
  $out | ForEach-Object { Write-Host $_ }

  # Robocopy uses bitmask exit codes; 0-7 are success-ish.
  if ($LASTEXITCODE -gt 7) {
    throw "robocopy failed with exit code $LASTEXITCODE"
  }
}

function Ensure-VptRunningFromStandardRoot {
  param(
    [Parameter(Mandatory = $true)][string]$CurrentProjectRoot,
    [Parameter(Mandatory = $true)][string]$CurrentScriptPath,
    [hashtable]$BoundParams = @{},
    [object[]]$UnboundArgs = @()
  )

  $standardRoot = Get-VptStandardProjectRoot

  # Normalize for case-insensitive compare on Windows.
  $cur = (Resolve-Path $CurrentProjectRoot).Path.TrimEnd('\')
  $std = $standardRoot.TrimEnd('\')

  if ($cur.ToLowerInvariant() -eq $std.ToLowerInvariant()) {
    return
  }

  Copy-VptProjectToStandardRoot -SourceRoot $cur -DestRoot $std

  $scriptFull = (Resolve-Path $CurrentScriptPath).Path
  $rel = $scriptFull.Substring($cur.Length).TrimStart('\')
  $destScript = Join-Path $std $rel

  if (-not (Test-Path $destScript)) {
    throw "Re-exec target script not found after copy: $destScript"
  }

  $invokeArgs = @()
  foreach ($k in $BoundParams.Keys) {
    $v = $BoundParams[$k]
    if ($v -is [bool]) {
      if ($v) { $invokeArgs += "-$k" }
    } else {
      $invokeArgs += "-$k"
      $invokeArgs += "$v"
    }
  }
  $invokeArgs += $UnboundArgs

  Write-Host "[BOOTSTRAP] Re-executing from standard root: $destScript"
  & powershell.exe -ExecutionPolicy Bypass -File $destScript @invokeArgs
  exit $LASTEXITCODE
}
