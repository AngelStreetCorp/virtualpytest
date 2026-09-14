#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Sync VirtualPyTest code on Windows from a "source checkout" into the standard runtime path.

.DESCRIPTION
  Mirrors the Linux sync behavior (sync_code.sh), but for Windows hosts where services run from:
    C:\virtualpytest\virtualpytest

  Uses robocopy with /MIR and excludes heavy local artifacts and local env config.

.EXAMPLE
  pwsh -File .\setup\proxmox\vm\shared\sync_code.ps1

.EXAMPLE
  pwsh -File .\setup\proxmox\vm\shared\sync_code.ps1 -SourceRoot C:\Users\jndoye\virtualpytest -DestRoot C:\virtualpytest\virtualpytest
#>

#Requires -Version 5.1

param(
  [string]$SourceRoot = "C:\Users\jndoye\virtualpytest",
  [string]$DestRoot = "C:\virtualpytest\virtualpytest"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info([string]$Msg) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Write-Host "[$ts] [SYNC] $Msg"
}

if (-not (Test-Path $SourceRoot)) {
  throw "SourceRoot not found: $SourceRoot"
}

$null = New-Item -ItemType Directory -Path $DestRoot -Force

$excludeDirs = @(
  ".git",
  ".github",
  ".cursor",
  ".husky",
  "venv",
  "node_modules",
  ".next",
  "__pycache__",
  ".pytest_cache",
  ".mypy_cache",
  ".ruff_cache",
  "user_data",
  "webkit_user_data",
  "playwright-report",
  "playwright-viewport-report",
  "security_report",
  "dist"
)

$excludeFiles = @(
  ".env",
  "*.pyc",
  "*.pyo"
)

$cacheDirsToDelete = @(
  "__pycache__",
  ".pytest_cache",
  ".mypy_cache",
  ".ruff_cache"
)

Write-Info "Cleaning destination caches (best-effort)..."
foreach ($d in $cacheDirsToDelete) {
  Get-ChildItem -Path $DestRoot -Directory -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq $d } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
}
Get-ChildItem -Path $DestRoot -File -Recurse -Force -Include "*.pyc","*.pyo" -ErrorAction SilentlyContinue |
  ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }

$args = @(
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
  $args += "/XD"
  $args += $d
}

foreach ($f in $excludeFiles) {
  $args += "/XF"
  $args += $f
}

Write-Info "Syncing code..."
Write-Info "  Source: $SourceRoot"
Write-Info "  Dest:   $DestRoot"

$out = & robocopy @args 2>&1
$out | ForEach-Object { Write-Host $_ }

# Robocopy uses bitmask exit codes; 0-7 are success-ish.
if ($LASTEXITCODE -gt 7) {
  throw "robocopy failed with exit code $LASTEXITCODE"
}

Write-Info "Done (robocopy exit code: $LASTEXITCODE)"
