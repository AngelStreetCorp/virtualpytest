# Prepare a Windows PC to be powered by a VirtualPyTest host's Wake-on-LAN power
# controller (DEVICE{i}_POWER_MAC): it stays awake 24/7 on AC, never locks, wakes
# from a magic packet, and accepts the host's SSH key for shutdown/restart.
#
# Run in an elevated PowerShell on the PC itself:
#   .\setup\local\windows\backend_host\prepare_wol_target.ps1 -HostPublicKey "ssh-ed25519 AAAA... vpt@host"
#
# Still manual (see docs/agent/devices/WAKE_ON_LAN.md): BIOS Wake-on-LAN + ErP off,
# auto sign-in (autologin.md), and the .env lines on the host.

param(
    # Public key of the VirtualPyTest host that sends the shutdown (~/.ssh/id_ed25519.pub there)
    [string]$HostPublicKey = ""
)

$ErrorActionPreference = "Stop"

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Run this script from an elevated (Administrator) PowerShell."
}

Write-Host "== Power: never sleep or hibernate on AC, monitor off after 10 min"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 10

Write-Host "== No password on wake, no lock screen, no secure screen saver"
powercfg /setacvalueindex SCHEME_CURRENT SUB_NONE CONSOLELOCK 0
powercfg /setactive SCHEME_CURRENT
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f | Out-Null
reg add "HKCU\Control Panel\Desktop" /v ScreenSaveActive /t REG_SZ /d 0 /f | Out-Null
reg add "HKCU\Control Panel\Desktop" /v ScreenSaverIsSecure /t REG_SZ /d 0 /f | Out-Null

Write-Host "== Fast Startup off (it blocks Wake-on-LAN from a full shutdown on many NICs)"
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power" /v HiberbootEnabled /t REG_DWORD /d 0 /f | Out-Null

Write-Host "== Wake-on-LAN on the wired adapters"
Get-NetAdapter -Physical | Where-Object { $_.MediaType -eq '802.3' } | ForEach-Object {
    $name = $_.Name
    foreach ($prop in 'Wake on Magic Packet', 'Shutdown Wake-On-Lan', 'Shutdown Wake Up') {
        if (Get-NetAdapterAdvancedProperty -Name $name -DisplayName $prop -ErrorAction SilentlyContinue) {
            Set-NetAdapterAdvancedProperty -Name $name -DisplayName $prop -DisplayValue 'Enabled' -ErrorAction SilentlyContinue
        }
    }
    powercfg /deviceenablewake "$($_.InterfaceDescription)" 2>$null
    Write-Host ("   {0}  MAC {1}  IP {2}" -f $name, $_.MacAddress,
        ((Get-NetIPAddress -InterfaceAlias $name -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress -join ','))
}

Write-Host "== OpenSSH Server (shutdown/restart channel and power status probe)"
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*'
if ($cap.State -ne 'Installed') { Add-WindowsCapability -Online -Name $cap.Name | Out-Null }
Set-Service sshd -StartupType Automatic
Start-Service sshd
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True `
        -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}

if ($HostPublicKey) {
    # The SSH user is this (admin) account; Windows OpenSSH authenticates members of
    # Administrators against administrators_authorized_keys, not ~\.ssh\authorized_keys.
    $keyFile = "$env:ProgramData\ssh\administrators_authorized_keys"
    if (-not (Test-Path $keyFile) -or -not (Select-String -Path $keyFile -SimpleMatch $HostPublicKey -Quiet)) {
        Add-Content -Path $keyFile -Value $HostPublicKey -Encoding ascii
    }
    icacls $keyFile /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null
    Write-Host "   host key added to $keyFile"
} else {
    Write-Host "   no -HostPublicKey given: add the host's public key later to enable power off"
}

Write-Host ""
Write-Host "Done. Remaining manual steps: BIOS Wake-on-LAN / ErP off, auto sign-in, host .env."
Write-Host "SSH user for DEVICE{i}_POWER_SSH_USER: $env:USERNAME"
