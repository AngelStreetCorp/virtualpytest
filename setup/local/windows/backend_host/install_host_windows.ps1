#!/usr/bin/env pwsh
<#
.SYNOPSIS
    VirtualPyTest Windows Host Installation Script
    Equivalent to setup/local/install_host.sh + install_host_services.sh

.DESCRIPTION
    Installs VirtualPyTest backend_host on Windows with all services and dependencies.
    Creates Windows services equivalent to Linux systemd services.

.EXAMPLE
    .\install_host_windows.ps1
    # Full installation
#>

#Requires -Version 5.1
#Requires -RunAsAdministrator

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Global variables
$script:PROJECT_ROOT = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
$script:BACKEND_HOST_PATH = Join-Path $script:PROJECT_ROOT "backend_host"
$script:SCRIPTS_PATH = Join-Path $script:BACKEND_HOST_PATH "scripts"
$script:SHARED_PATH = Join-Path $script:PROJECT_ROOT "shared"
$script:INSTALL_PATH = "C:\virtualpytest"
$script:LOGS_PATH = Join-Path $script:INSTALL_PATH "logs"
$script:NOVNC_PATH = Join-Path $script:INSTALL_PATH "novnc"
$script:NOVNC_VERSION = "1.5.0"
$script:NOVNC_ZIP_URL = "https://github.com/novnc/noVNC/archive/refs/tags/v$($script:NOVNC_VERSION).zip"
# No shipped default: it used to be one literal shared by every install of a public repo.
# Get-HostVncPassword generates one and writes it to .env when none is configured.
$script:DEFAULT_HOST_VNC_PASSWORD = ""
$script:HOST_VNC_PORT = 5900
$script:VENV_PATH = Join-Path $script:PROJECT_ROOT "venv"
$script:PYTHON_EXE = Join-Path $script:VENV_PATH "Scripts\python.exe"
$script:PIP_EXE = Join-Path $script:VENV_PATH "Scripts\pip.exe"
$script:TEAMS_NETWORK_ASSESSMENT_EXE = "C:\Program Files (x86)\Microsoft Teams Network Assessment Tool\NetworkAssessmentTool.exe"

# Bootstrap: copy repo to C:\virtualpytest\virtualpytest and run installers from there
$bootstrap = Join-Path $PSScriptRoot "..\\shared\\bootstrap.ps1"
if (Test-Path $bootstrap) {
    . $bootstrap
    Ensure-VptRunningFromStandardRoot -CurrentProjectRoot $script:PROJECT_ROOT -CurrentScriptPath $MyInvocation.MyCommand.Path -BoundParams $PSBoundParameters -UnboundArgs $args
}

# Service names
# Keep naming coherent with Linux (vpt-*.service). On Windows we omit the ".service" suffix.
$script:SERVICES = @{
    "vpt-host" = "Host API service"
    # NOTE: On Windows, desktop capture (ffmpeg gdigrab) must run in an interactive session.
    # It cannot run reliably from Session 0 (services/SSH). We install stream as a Scheduled Task.
    "vpt-stream" = "FFmpeg video capture task"
    "vpt-monitor" = "Capture monitoring service"
    "vpt-archiver" = "Hot/cold storage archiver"
    "vpt-transcript" = "Audio transcription service"
    "vpt-kpi" = "KPI measurement executor"
    # Windows-only helpers
    "vpt-vnc" = "VNC server service"
    "vpt-websockify" = "WebSocket proxy service"
}

$script:STREAM_TASK_NAME = "vpt-stream"
$script:HOST_TASK_NAME = "vpt-host"

function Write-Log {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"

    Write-Host $logMessage

    # Also log to file if logs directory exists
    if (Test-Path $script:LOGS_PATH) {
        $logFile = Join-Path $script:LOGS_PATH "install.log"
        $logMessage | Out-File -FilePath $logFile -Append -Encoding UTF8
    }
}

function Setup-NoVNC {
    <#
    .SYNOPSIS
        Installs noVNC static files for websockify (--web) on Windows.

    .NOTES
        Linux uses a system package path (e.g., /usr/share/novnc). On Windows we
        download and extract a pinned release into C:\virtualpytest\novnc so the
        vpt-websockify service can serve /vnc_lite.html and supporting assets.
    #>
    Write-Log "Setting up noVNC static files..."

    # If already installed, keep it.
    $vncLite = Join-Path $script:NOVNC_PATH "vnc_lite.html"
    if (Test-Path $vncLite) {
        Write-Log "noVNC already present at $script:NOVNC_PATH"
        return
    }

    if (-not (Test-Path $script:NOVNC_PATH)) {
        New-Item -ItemType Directory -Path $script:NOVNC_PATH -Force | Out-Null
    }

    $zipPath = Join-Path $env:TEMP "novnc-$($script:NOVNC_VERSION).zip"
    $extractRoot = Join-Path $env:TEMP "novnc-extract"

    try {
        Write-Log "Downloading noVNC v$($script:NOVNC_VERSION)..."
        # PowerShell 5.1 compatibility: UseBasicParsing
        Invoke-WebRequest -Uri $script:NOVNC_ZIP_URL -OutFile $zipPath -UseBasicParsing

        if (Test-Path $extractRoot) {
            Remove-Item -Recurse -Force $extractRoot -ErrorAction SilentlyContinue
        }
        New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
        Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force

        $topDir = Get-ChildItem -Path $extractRoot -Directory | Select-Object -First 1
        if (-not $topDir) {
            throw "Failed to find extracted noVNC directory under $extractRoot"
        }

        # Clear destination then copy extracted content.
        Get-ChildItem -Path $script:NOVNC_PATH -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Copy-Item -Path (Join-Path $topDir.FullName "*") -Destination $script:NOVNC_PATH -Recurse -Force

        # Replace upstream vnc_lite.html with our template (same as Linux) so:
        # - default password behavior is consistent
        # - websockify path is auto-detected for nginx routing (/host/{name}/websockify)
        $template = Join-Path $script:BACKEND_HOST_PATH "config\\services\\linux\\vnc.lite.example"
        if (Test-Path $template) {
            try {
                $content = Get-Content -Path $template -Raw -ErrorAction Stop
                $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
                [System.IO.File]::WriteAllText($vncLite, $content, $utf8NoBom)
                Write-Log "Installed custom vnc_lite.html template to $vncLite"
            } catch {
                Write-Log "Failed to write custom vnc_lite.html template: $($_.Exception.Message)" "WARNING"
            }
        } else {
            Write-Log "Custom vnc_lite.html template not found at $template (using upstream noVNC vnc_lite.html)" "WARNING"
        }

        if (-not (Test-Path $vncLite)) {
            throw "noVNC install completed, but vnc_lite.html was not found at $vncLite"
        }

        $patchScript = Join-Path $script:BACKEND_HOST_PATH "scripts\patch_novnc_close_frame.sh"
        if (Test-Path $patchScript) {
            Write-Log "Patching noVNC VideoDecoder to close VideoFrames..."
            bash $patchScript $script:NOVNC_PATH 2>&1 | ForEach-Object { Write-Log $_ }
        } else {
            Write-Log "Missing patch script: $patchScript" "WARNING"
        }

        Write-Log "noVNC installed to $script:NOVNC_PATH"
    } catch {
        Write-Log "Failed to setup noVNC: $($_.Exception.Message)" "ERROR"
        throw
    } finally {
        try { Remove-Item -Force $zipPath -ErrorAction SilentlyContinue } catch { }
        try { Remove-Item -Recurse -Force $extractRoot -ErrorAction SilentlyContinue } catch { }
    }
}

function Get-HostVncPassword {
    # TightVNC only uses the first 8 characters.
    $pwd = $script:DEFAULT_HOST_VNC_PASSWORD
    $envFile = Join-Path $script:BACKEND_HOST_PATH "src\\.env"
    try {
        if (Test-Path $envFile) {
            $line = (Get-Content -Path $envFile -ErrorAction SilentlyContinue) | Where-Object { $_ -match '^HOST_VNC_PASSWORD=' } | Select-Object -First 1
            if ($line) { $pwd = (($line -split '=', 2)[1]).Trim(" `"'") }
        }
    } catch { }
    if ((-not $pwd) -or ($pwd -eq "CHANGE_ME")) {
        # Generate one and persist it, so it survives a re-run instead of changing
        # every time. There is deliberately no literal to fall back on.
        $bytes = New-Object byte[] 16
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $pwd = (([System.Convert]::ToBase64String($bytes)) -replace '[^A-Za-z0-9]', '')
        if ($pwd.Length -gt 8) { $pwd = $pwd.Substring(0, 8) }
        try {
            if (Test-Path $envFile) {
                $content = Get-Content -Path $envFile
                if ($content | Where-Object { $_ -match '^HOST_VNC_PASSWORD=' }) {
                    ($content -replace '^HOST_VNC_PASSWORD=.*', "HOST_VNC_PASSWORD=$pwd") | Set-Content -Path $envFile
                } else {
                    Add-Content -Path $envFile -Value "HOST_VNC_PASSWORD=$pwd"
                }
                Write-Log "Generated a VNC password into $envFile (HOST_VNC_PASSWORD)"
            }
        } catch { Write-Log "Could not persist the generated VNC password to $envFile" "WARNING" }
    }
    if ($pwd.Length -gt 8) { $pwd = $pwd.Substring(0, 8) }
    return $pwd
}

function ConvertTo-TightVncPasswordBytes {
    param([Parameter(Mandatory = $true)][string]$Password)
    $p = $Password; if (-not $p) { $p = "" }; if ($p.Length -gt 8) { $p = $p.Substring(0, 8) }
    $plain = New-Object byte[] 8
    $b = [System.Text.Encoding]::ASCII.GetBytes($p)
    [Array]::Copy($b, 0, $plain, 0, [Math]::Min(8, $b.Length))
    $key = [byte[]](23, 82, 107, 6, 35, 78, 88, 7)
    $des = [System.Security.Cryptography.DES]::Create()
    try {
        $des.Mode = [System.Security.Cryptography.CipherMode]::ECB
        $des.Padding = [System.Security.Cryptography.PaddingMode]::None
        $des.Key = $key
        $des.IV = $key
        return ,($des.CreateEncryptor().TransformFinalBlock($plain, 0, 8))
    } finally { $des.Dispose() }
}

function Get-ConsoleUsername {
    # Best-effort: use "query user" to find the active console session user.
    try {
        $lines = & query user 2>$null
        foreach ($line in $lines) {
            if ($line -match '^\s*(\S+)\s+console\s+\d+\s+Active') {
                return $matches[1]
            }
        }
    } catch { }
    return $null
}

function Install-StreamScheduledTask {
    Write-Log "Installing vpt-stream scheduled task (interactive session required on Windows)..."

    $consoleUser = Get-ConsoleUsername
    if (-not $consoleUser) {
        Write-Log "No active console session detected (cannot create InteractiveToken task). Log in to the console once and re-run installer." "WARNING"
        return
    }

    $streamWrapper = Join-Path $script:SCRIPTS_PATH "stream_wrapper.ps1"
    if (-not (Test-Path $streamWrapper)) {
        Write-Log "Missing stream wrapper: $streamWrapper" "WARNING"
        return
    }

    try {
        # Remove any previous task.
        if (Get-ScheduledTask -TaskName $script:STREAM_TASK_NAME -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $script:STREAM_TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
        }
    } catch { }

    # Use explicit XML to avoid ScheduledTasks module edge-cases around ExecutionTimeLimit formatting.
    # Task scheduler expects ISO 8601 duration; unlimited is PT0S.
    $psExe = "$env:SystemRoot\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    $psArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$streamWrapper`""

    $taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>VirtualPyTest stream (ffmpeg) - must run in interactive session</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$consoleUser</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$psExe</Command>
      <Arguments>$psArgs</Arguments>
      <WorkingDirectory>$($script:SCRIPTS_PATH)</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

    try {
        Register-ScheduledTask -TaskName $script:STREAM_TASK_NAME -Xml $taskXml -Force | Out-Null
        Write-Log "Installed scheduled task: $($script:STREAM_TASK_NAME) (user: $consoleUser)"
    } catch {
        Write-Log "Could not register scheduled task $($script:STREAM_TASK_NAME): $($_.Exception.Message)" "WARNING"
        Write-Log "Stream capture will need manual task creation or interactive startup" "WARNING"
    }
}

function Install-HostScheduledTask {
    Write-Log "Installing vpt-host scheduled task (interactive session required for visible browser automation)..."

    $consoleUser = Get-ConsoleUsername
    if (-not $consoleUser) {
        Write-Log "No active console session detected (cannot create InteractiveToken task). Log in to the console once and re-run installer." "WARNING"
        return
    }

    $hostWrapper = Join-Path $script:SCRIPTS_PATH "host_wrapper.ps1"
    if (-not (Test-Path $hostWrapper)) {
        Write-Log "Missing host wrapper: $hostWrapper" "WARNING"
        return
    }

    try {
        if (Get-ScheduledTask -TaskName $script:HOST_TASK_NAME -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $script:HOST_TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
        }
    } catch { }

    $psExe = "$env:SystemRoot\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    $psArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$hostWrapper`""

    $taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>VirtualPyTest host API - run in interactive session for visible browser automation</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$consoleUser</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$psExe</Command>
      <Arguments>$psArgs</Arguments>
      <WorkingDirectory>$($script:SCRIPTS_PATH)</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

    try {
        Register-ScheduledTask -TaskName $script:HOST_TASK_NAME -Xml $taskXml -Force | Out-Null
        Write-Log "Installed scheduled task: $($script:HOST_TASK_NAME) (user: $consoleUser)"
    } catch {
        Write-Log "Could not register scheduled task $($script:HOST_TASK_NAME): $($_.Exception.Message)" "WARNING"
        Write-Log "Host API will need manual task creation or interactive startup" "WARNING"
    }
}

function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Install-Chocolatey {
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        Write-Log "Chocolatey already installed"
        return
    }

    Write-Log "Installing Chocolatey package manager..."
    try {
        Set-ExecutionPolicy Bypass -Scope Process -Force
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
        Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))

        # Refresh environment
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

        Write-Log "Chocolatey installed successfully" "SUCCESS"
    }
    catch {
        throw "Failed to install Chocolatey: $_"
    }
}

# Install Python via Chocolatey
function Install-Python {
    Write-Log "Installing Python via Chocolatey..."
    
    # Ensure Chocolatey is installed
    Install-Chocolatey
    
    # Install Python
    # Pin to a stable version that has broad wheel support (numpy/scipy/etc).
    # Avoid bleeding-edge versions that trigger source builds requiring MSVC.
    Write-Log "Installing Python 3.12..."
    choco install python312 -y --no-progress
    
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Failed to install Python via Chocolatey" "ERROR"
        throw "Failed to install Python"
    }
    
    # Refresh environment to pick up new Python
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    
    Write-Log "Python installed successfully" "SUCCESS"
}

function Get-Python312Args {
    # Prefer py launcher, independent of PATH order.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $ver = & py -3.12 --version 2>&1
            if ($LASTEXITCODE -eq 0) {
                return @("py", "-3.12")
            }
        } catch { }
    }
    return $null
}

function Install-WindowsDependencies {
    Write-Log "Installing Windows dependencies..."

    # Install Chocolatey first
    Install-Chocolatey

    # Update Chocolatey
    choco upgrade chocolatey -y

    # Install core dependencies (Python is handled separately by Test-Python)
    $packages = @(
        "ffmpeg",           # Video processing
        "vcredist-all",     # Visual C++ redistributables
        "git",              # Version control
        "nssm",             # Non-Sucking Service Manager
        "vcxsrv",           # X11 server for Windows
        "speedtest",        # Ookla Speedtest CLI
        "rsync"             # File sync (used by deploy script)
    )

    # Always install VNC for Windows (unconditional)
    $packages += "tightvnc"  # VNC server

    foreach ($package in $packages) {
        Write-Log "Installing $package..."
        choco install $package -y --no-progress
    }

    Install-TeamsNetworkAssessmentTool

    Write-Log "Windows dependencies installed" "SUCCESS"
}

function Install-TeamsNetworkAssessmentTool {
    Write-Log "Checking Microsoft Teams Network Assessment Tool..."

    if (Test-Path $script:TEAMS_NETWORK_ASSESSMENT_EXE) {
        Write-Log "Teams Network Assessment Tool already installed at: $($script:TEAMS_NETWORK_ASSESSMENT_EXE)" "SUCCESS"
        return
    }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Log "winget is not available. Install Teams Network Assessment Tool manually." "WARNING"
        Write-Log "Expected executable path: $($script:TEAMS_NETWORK_ASSESSMENT_EXE)" "WARNING"
        return
    }

    $candidateIds = @(
        "Microsoft.TeamsNetworkAssessmentTool",
        "Microsoft.NetworkAssessmentToolForMicrosoftTeams",
        "Microsoft.TeamsNetworkAssessment"
    )

    $installed = $false
    foreach ($id in $candidateIds) {
        try {
            & winget show --id $id --exact --accept-source-agreements *> $null
            if ($LASTEXITCODE -ne 0) {
                continue
            }

            Write-Log "Installing Teams Network Assessment Tool via winget id: $id"
            & winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -eq 0) {
                $installed = $true
                break
            }
        } catch {
            Write-Log "winget install attempt failed for id '$id': $($_.Exception.Message)" "WARNING"
        }
    }

    if ((Test-Path $script:TEAMS_NETWORK_ASSESSMENT_EXE) -or $installed) {
        Write-Log "Teams Network Assessment Tool installed" "SUCCESS"
        return
    }

    Write-Log "Could not auto-install Teams Network Assessment Tool with winget." "WARNING"
    Write-Log "Install manually, then verify: $($script:TEAMS_NETWORK_ASSESSMENT_EXE)" "WARNING"
}

function Test-Python {
    Write-Log "Checking Python installation..."
    
    try {
        $pythonVersion = & python --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Found: $pythonVersion" "SUCCESS"
            return
        }
    } catch {
        # Python not found
    }
    
    # Python not found - install it
    Write-Log "Python is not installed - installing via Chocolatey..."
    Install-Python
    
    # Verify installation
    try {
        $pythonVersion = & python --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Python installation failed - please install manually from https://www.python.org/downloads/" "ERROR"
            Write-Log "Make sure to check 'Add Python to PATH' during installation" "ERROR"
            throw "Python installation failed"
        }
        Write-Log "Python installed: $pythonVersion" "SUCCESS"
    } catch {
        Write-Log "Python installation failed - please install manually from https://www.python.org/downloads/" "ERROR"
        throw "Python installation failed"
    }
}

function Setup-PythonEnvironment {
    Write-Log "Setting up Python virtual environment..."

    # First verify Python is available
    Test-Python

    # Create virtual environment if it doesn't exist
    if (-not (Test-Path $script:VENV_PATH)) {
        Write-Log "Creating Python virtual environment at $script:VENV_PATH..."
        $py312 = Get-Python312Args
        if ($py312) {
            & $py312[0] $py312[1] -m venv $script:VENV_PATH
        } else {
            & python -m venv $script:VENV_PATH
        }
        
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Failed to create virtual environment" "ERROR"
            throw "Failed to create virtual environment"
        }
        
        # Verify venv was actually created
        if (-not (Test-Path $script:VENV_PATH)) {
            Write-Log "Virtual environment directory was not created" "ERROR"
            throw "Virtual environment directory was not created"
        }
        
        # Verify python.exe exists in venv
        if (-not (Test-Path $script:PYTHON_EXE)) {
            Write-Log "Virtual environment is incomplete - python.exe not found" "ERROR"
            Write-Log "Expected: $script:PYTHON_EXE" "ERROR"
            throw "Virtual environment is incomplete"
        }
        
        Write-Log "Virtual environment created successfully"
    } else {
        # Verify existing venv is valid
        if (-not (Test-Path $script:PYTHON_EXE)) {
            Write-Log "Existing virtual environment is invalid - python.exe not found" "ERROR"
            Write-Log "Please delete $script:VENV_PATH and run installation again" "ERROR"
            throw "Existing virtual environment is invalid"
        }
        Write-Log "Virtual environment already exists and is valid"
    }

    # Activate virtual environment
    Write-Log "Activating virtual environment..."
    & $script:PYTHON_EXE -c "import sys; print(f'Python: {sys.version}')"
    $pyMajorMinor = & $script:PYTHON_EXE -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
    if ($pyMajorMinor -notmatch '^3\.(10|11|12)$') {
        Write-Log "Unsupported Python version in venv: $pyMajorMinor (expected 3.10-3.12 for Windows wheels). Delete venv and ensure Python 3.12 is installed." "ERROR"
        throw "Unsupported Python version in venv: $pyMajorMinor"
    }

    # Upgrade pip
    & $script:PIP_EXE install --upgrade pip

    # Install Python dependencies
    Write-Log "Installing Python dependencies..."
    $requirementsFile = Join-Path $script:BACKEND_HOST_PATH "requirements.txt"
    if (Test-Path $requirementsFile) {
        Write-Log "Installing from $requirementsFile..."
        & $script:PIP_EXE install -r $requirementsFile -v
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Failed to install Python dependencies" "ERROR"
            throw "Failed to install Python dependencies"
        }
        Write-Log "Python dependencies installed successfully (includes psutil, flask, etc.)"
    } else {
        Write-Log "requirements.txt not found at $requirementsFile" "WARNING"
    }

    # Install additional Windows-specific packages
    & $script:PIP_EXE install websockify
    Setup-NoVNC

    # Install Playwright browsers
    Write-Log "Installing Playwright browsers..."
    & $script:PYTHON_EXE -m playwright install chromium firefox webkit
    & $script:PYTHON_EXE -m playwright install-deps

    Write-Log "Python environment setup complete"
}

function Setup-StorageDirectories {
    Write-Log "Setting up storage directories..."

    function Parse-DotEnvValue {
        param([string]$RawValue)

        # PowerShell 5.1 compatible (no null-coalescing operator).
        if ($null -eq $RawValue) { $RawValue = "" }
        $v = ([string]$RawValue).Trim()
        if ($v -match '^"([^"]*)"(?:\s+#.*)?$') { return $matches[1] }
        if ($v -match "^'([^']*)'(?:\s+#.*)?$") { return $matches[1] }
        # Unquoted value: strip inline comment after whitespace to avoid "value    # comment"
        return ($v -replace '\s+#.*$', '').Trim()
    }

    # Create main directories
    $script:STREAM_PATH = Join-Path $script:INSTALL_PATH "stream"
    $directories = @(
        $script:INSTALL_PATH,
        $script:LOGS_PATH,
        $script:STREAM_PATH
    )

    foreach ($dir in $directories) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    # Read devices from .env file
    $envFile = Join-Path $script:BACKEND_HOST_PATH "src\.env"
    $envContent = Get-Content $envFile -ErrorAction SilentlyContinue
    $devices = @()

    # Check for HOST device
    $hostCapturePath = $envContent | Where-Object { $_ -match '^HOST_VIDEO_CAPTURE_PATH=' } | ForEach-Object {
        Parse-DotEnvValue -RawValue (($_ -split '=', 2)[1])
    }
    if ($hostCapturePath) {
        $captureFolder = Split-Path $hostCapturePath -Leaf
        $devices += $captureFolder
        Write-Log "Found host device: $captureFolder"
    }

    # Check for DEVICE1-14
    for ($i = 1; $i -le 14; $i++) {
        $deviceCapturePath = $envContent | Where-Object { $_ -match "^DEVICE${i}_VIDEO_CAPTURE_PATH=" } | ForEach-Object {
            Parse-DotEnvValue -RawValue (($_ -split '=', 2)[1])
        }
        if ($deviceCapturePath) {
            $captureFolder = Split-Path $deviceCapturePath -Leaf
            $devices += $captureFolder
            Write-Log "Found device${i}: $captureFolder"
        }
    }

    if ($devices.Count -eq 0) {
        Write-Log "No devices found in .env file" "WARNING"
        return
    }

    Write-Log "Configuring storage for $($devices.Count) device(s): $($devices -join ', ')"

    # Create per-device storage structure (flat — no hot/cold split on Windows)
    # On Linux, RAM tmpfs provides hot storage; on Windows FFmpeg writes directly to disk.
    foreach ($device in $devices) {
        $devicePath = Join-Path $script:STREAM_PATH $device
        Write-Log "Setting up device: $device"

        # Create device base directory
        if (-not (Test-Path $devicePath)) {
            New-Item -ItemType Directory -Path $devicePath -Force | Out-Null
        }

        # Create storage directories
        # captures, thumbnails - flat (no hour folders)
        foreach ($subdir in @("captures", "thumbnails")) {
            $subdirPath = Join-Path $devicePath $subdir
            if (-not (Test-Path $subdirPath)) {
                New-Item -ItemType Directory -Path $subdirPath -Force | Out-Null
            }
        }

        # segments, metadata, audio - with hour folders 0-23
        foreach ($subdir in @("segments", "metadata", "audio")) {
            $subdirPath = Join-Path $devicePath $subdir
            if (-not (Test-Path $subdirPath)) {
                New-Item -ItemType Directory -Path $subdirPath -Force | Out-Null
            }

            # Create hour folders (0-23)
            for ($hour = 0; $hour -lt 24; $hour++) {
                $hourPath = Join-Path $subdirPath $hour.ToString()
                if (-not (Test-Path $hourPath)) {
                    New-Item -ItemType Directory -Path $hourPath -Force | Out-Null
                }
            }

            # Create temp folder for segments and metadata
            if ($subdir -in @("segments", "metadata")) {
                $tempPath = Join-Path $subdirPath "temp"
                if (-not (Test-Path $tempPath)) {
                    New-Item -ItemType Directory -Path $tempPath -Force | Out-Null
                }
            }
        }

        Write-Log "Device $device storage ready (with hour folders 0-23)"
    }

    Write-Log "Storage directories setup complete"
}

function Setup-EnvironmentConfiguration {
    Write-Log "Setting up environment configuration..."

    # Create .env file if it doesn't exist
    $envFile = Join-Path $script:BACKEND_HOST_PATH "src\.env"
    if (-not (Test-Path $envFile)) {
        $envExample = Join-Path $script:BACKEND_HOST_PATH "src\.env.example"
        if (Test-Path $envExample) {
            Copy-Item $envExample $envFile
            Write-Log "Created .env file from .env.example"
        } else {
            Write-Log "No .env found and backend_host/src/.env.example not found" "ERROR"
            Write-Log "Please create backend_host/src/.env or backend_host/src/.env.example manually" "ERROR"
            exit 1
        }
    } else {
        Write-Log ".env file already exists, preserving existing configuration"
    }

    # Set Windows environment variables
    Write-Log "Setting Windows environment variables..."

    $envVars = @{
        "VIRTUALPYTEST_ROOT" = $script:PROJECT_ROOT
        "VIRTUALPYTEST_HOST" = $script:BACKEND_HOST_PATH
        "VIRTUALPYTEST_LOGS" = $script:LOGS_PATH
        "PYTHONPATH" = "$($script:PROJECT_ROOT);$($script:SHARED_PATH);$($script:BACKEND_HOST_PATH)\src"
        "DISPLAY" = ":1"
    }

    foreach ($envVar in $envVars.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($envVar.Key, $envVar.Value, "Machine")
        Write-Log "Set environment variable: $($envVar.Key) = $($envVar.Value)"
    }

    Write-Log "Environment configuration complete"
}

function Test-ServiceExists {
    param([string]$ServiceName)

    try {
        $service = Get-Service -Name $ServiceName -ErrorAction Stop
        return $true
    }
    catch {
        return $false
    }
}

# Cap every NSSM-managed service log at 30 MB with online rotation (NSSM
# renames to <name>-<timestamp>.log and reopens while running). Same 30 MB
# convention as the host_wrapper.ps1 / run_ffmpeg.ps1 caps — without this,
# AppStdout/AppStderr grow unbounded and can starve the host (see the
# take-control "Host communication timeout" incident).
function Set-NssmLogRotation {
    param([string]$NssmPath, [string]$ServiceName)
    $maxBytes = 31457280  # 30 MB
    try {
        & $NssmPath set $ServiceName AppRotateFiles 1 | Out-Null
        & $NssmPath set $ServiceName AppRotateOnline 1 | Out-Null
        & $NssmPath set $ServiceName AppRotateSeconds 0 | Out-Null   # size-based only
        & $NssmPath set $ServiceName AppRotateBytes $maxBytes | Out-Null
    } catch { }
}

function Install-WindowsServices {
    Write-Log "Installing Windows services..."

    # Get NSSM path
    $nssmPath = Join-Path $env:ChocolateyInstall "bin\nssm.exe"
    if (-not (Test-Path $nssmPath)) {
        $nssmPath = "nssm.exe"  # Hope it's in PATH
    }

    # Remove legacy/old service names to avoid stale configs (wrong paths) from older installs.
    $legacyServices = @(
        "VirtualPyTest-Flask",
        "VirtualPyTest-Monitor",
        "VirtualPyTest-Stream",
        "VirtualPyTest-Archiver",
        "VirtualPyTest-Transcript",
        "VirtualPyTest-VNC",
        "VirtualPyTest-WebSockify",
        "VPTFlaskAPI",
        "VPTMonitor",
        "VPTStream",
        "VPTArchiver",
        "VPTTranscript",
        "VPTVNC",
        "VPTWebSockify"
    )
    foreach ($svc in $legacyServices) {
        if (Test-ServiceExists $svc) {
            Write-Log "Removing legacy Windows service: $svc" "WARNING"
            try { Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue } catch { }
            try { & $nssmPath remove $svc confirm | Out-Null } catch { }
            try { sc.exe delete $svc 2>$null | Out-Null } catch { }
        }
    }

    # Install Host API as scheduled task (browser automation must run in interactive desktop session).
    if (Test-ServiceExists "vpt-host") {
        Write-Log "Removing vpt-host service (browser automation must run interactively on Windows)" "WARNING"
        try { Stop-Service -Name "vpt-host" -Force -ErrorAction SilentlyContinue } catch { }
        try { & $nssmPath remove "vpt-host" confirm | Out-Null } catch { }
        try { sc.exe delete "vpt-host" 2>$null | Out-Null } catch { }
    }
    Install-HostScheduledTask

    # Install Monitor service
    Write-Log "Installing Monitor service..."
    $monitorScript = Join-Path $script:SCRIPTS_PATH "capture_monitor.py"
    if (-not (Test-ServiceExists "vpt-monitor")) {
        & $nssmPath install vpt-monitor $script:PYTHON_EXE | Out-Null
    }
    & $nssmPath set vpt-monitor AppParameters "`"$monitorScript`"" | Out-Null
    & $nssmPath set vpt-monitor AppDirectory $script:SCRIPTS_PATH | Out-Null
    & $nssmPath set vpt-monitor AppEnvironmentExtra `
        "PYTHONUTF8=1" `
        "PYTHONIOENCODING=utf-8" `
        "PYTHONPATH=$($script:PROJECT_ROOT);$($script:SHARED_PATH);$($script:BACKEND_HOST_PATH)\src" | Out-Null
    & $nssmPath set vpt-monitor AppStdout (Join-Path $script:LOGS_PATH "monitor.log") | Out-Null
    & $nssmPath set vpt-monitor AppStderr (Join-Path $script:LOGS_PATH "monitor_error.log") | Out-Null

    # Install Stream as Scheduled Task (FFmpeg gdigrab must run in interactive session, not Session 0 services).
    if (Test-ServiceExists "vpt-stream") {
        Write-Log "Removing vpt-stream service (Windows desktop capture must run interactively)" "WARNING"
        try { Stop-Service -Name "vpt-stream" -Force -ErrorAction SilentlyContinue } catch { }
        try { & $nssmPath remove "vpt-stream" confirm | Out-Null } catch { }
        try { sc.exe delete "vpt-stream" 2>$null | Out-Null } catch { }
    }
    Install-StreamScheduledTask

    # Install Archiver service
    Write-Log "Installing Archiver service..."
    $archiverScript = Join-Path $script:SCRIPTS_PATH "hot_cold_archiver.py"
    if (-not (Test-ServiceExists "vpt-archiver")) {
        & $nssmPath install vpt-archiver $script:PYTHON_EXE | Out-Null
    }
    & $nssmPath set vpt-archiver AppParameters "`"$archiverScript`"" | Out-Null
    & $nssmPath set vpt-archiver AppDirectory $script:SCRIPTS_PATH | Out-Null
    & $nssmPath set vpt-archiver AppEnvironmentExtra `
        "PYTHONUTF8=1" `
        "PYTHONIOENCODING=utf-8" `
        "PYTHONPATH=$($script:PROJECT_ROOT);$($script:SHARED_PATH);$($script:BACKEND_HOST_PATH)\src" | Out-Null
    & $nssmPath set vpt-archiver AppStdout (Join-Path $script:LOGS_PATH "archiver.log") | Out-Null
    & $nssmPath set vpt-archiver AppStderr (Join-Path $script:LOGS_PATH "archiver_error.log") | Out-Null

    # Install Transcript service
    Write-Log "Installing Transcript service..."
    $transcriptScript = Join-Path $script:SCRIPTS_PATH "transcript_accumulator.py"
    if (-not (Test-ServiceExists "vpt-transcript")) {
        & $nssmPath install vpt-transcript $script:PYTHON_EXE | Out-Null
    }
    & $nssmPath set vpt-transcript AppParameters "`"$transcriptScript`"" | Out-Null
    & $nssmPath set vpt-transcript AppDirectory $script:SCRIPTS_PATH | Out-Null
    & $nssmPath set vpt-transcript AppEnvironmentExtra `
        "PYTHONUTF8=1" `
        "PYTHONIOENCODING=utf-8" `
        "PYTHONPATH=$($script:PROJECT_ROOT);$($script:SHARED_PATH);$($script:BACKEND_HOST_PATH)\src" | Out-Null
    & $nssmPath set vpt-transcript AppStdout (Join-Path $script:LOGS_PATH "transcript.log") | Out-Null
    & $nssmPath set vpt-transcript AppStderr (Join-Path $script:LOGS_PATH "transcript_error.log") | Out-Null

    # Install KPI Executor service
    Write-Log "Installing KPI Executor service..."
    $kpiScript = Join-Path $script:SCRIPTS_PATH "kpi_executor.py"
    if (-not (Test-ServiceExists "vpt-kpi")) {
        & $nssmPath install vpt-kpi $script:PYTHON_EXE | Out-Null
    }
    & $nssmPath set vpt-kpi AppParameters "`"$kpiScript`"" | Out-Null
    & $nssmPath set vpt-kpi AppDirectory $script:SCRIPTS_PATH | Out-Null
    & $nssmPath set vpt-kpi AppEnvironmentExtra `
        "PYTHONUTF8=1" `
        "PYTHONIOENCODING=utf-8" `
        "PYTHONPATH=$($script:PROJECT_ROOT);$($script:SHARED_PATH);$($script:BACKEND_HOST_PATH)\src" | Out-Null
    & $nssmPath set vpt-kpi AppStdout (Join-Path $script:LOGS_PATH "kpi.log") | Out-Null
    & $nssmPath set vpt-kpi AppStderr (Join-Path $script:LOGS_PATH "kpi_error.log") | Out-Null

    # Install VNC service (always on Windows)
    # TightVNC registers its own service ("tvnserver") during install. If it is
    # already present, skip vpt-vnc — running both binds port 5900 twice and
    # produces "Security negotiation failed on no security types" errors.
    # See docs/agent/TROUBLESHOOT.md ("Windows VNC duplicate services").
    Write-Log "Installing VNC service..."
    $vncPath = "C:\Program Files\TightVNC\tvnserver.exe"
    if (Test-Path $vncPath) {
        if (Get-Service tvnserver -ErrorAction SilentlyContinue) {
            Write-Log "TightVNC native service 'tvnserver' already installed — skipping vpt-vnc (port 5900 conflict)" "WARNING"
            if (Test-ServiceExists "vpt-vnc") {
                try { Stop-Service -Name "vpt-vnc" -Force -ErrorAction SilentlyContinue } catch { }
                try { & $nssmPath remove "vpt-vnc" confirm | Out-Null } catch { }
            }
        } else {
            if (-not (Test-ServiceExists "vpt-vnc")) {
                & $nssmPath install vpt-vnc $vncPath | Out-Null
            }
            & $nssmPath set vpt-vnc AppParameters "-run" | Out-Null
        }
    } else {
        Write-Log "TightVNC not found, skipping VNC service installation" "WARNING"
    }

    # Install WebSockify service (always on Windows)
    Write-Log "Installing WebSockify service..."
    if (-not (Test-ServiceExists "vpt-websockify")) {
        & $nssmPath install vpt-websockify $script:PYTHON_EXE | Out-Null
    }
    # Serve noVNC static files (vnc_lite.html, /app, /core, etc.) like Linux does.
    # Without --web, websockify returns 405 for normal HTTP GETs (only WS proxy works).
    & $nssmPath set vpt-websockify AppParameters ("-m websockify --web `"" + $script:NOVNC_PATH + "`" 0.0.0.0:6080 localhost:$($script:HOST_VNC_PORT)") | Out-Null
    & $nssmPath set vpt-websockify AppDirectory $script:PROJECT_ROOT | Out-Null
    & $nssmPath set vpt-websockify AppStdout (Join-Path $script:LOGS_PATH "websockify.log") | Out-Null
    & $nssmPath set vpt-websockify AppStderr (Join-Path $script:LOGS_PATH "websockify_error.log") | Out-Null

    # Ensure services are set to auto-start
    & $nssmPath set vpt-monitor Start SERVICE_AUTO_START | Out-Null
    & $nssmPath set vpt-archiver Start SERVICE_AUTO_START | Out-Null
    & $nssmPath set vpt-transcript Start SERVICE_AUTO_START | Out-Null
    & $nssmPath set vpt-kpi Start SERVICE_AUTO_START | Out-Null
    if (Test-ServiceExists "vpt-vnc") { & $nssmPath set vpt-vnc Start SERVICE_AUTO_START | Out-Null }
    & $nssmPath set vpt-websockify Start SERVICE_AUTO_START | Out-Null

    # Cap every NSSM service's stdout/stderr log at 30 MB (online rotation).
    # vpt-vnc is excluded: it runs tvnserver with no AppStdout/AppStderr.
    foreach ($svc in @("vpt-monitor", "vpt-archiver", "vpt-transcript", "vpt-kpi", "vpt-websockify")) {
        if (Test-ServiceExists $svc) { Set-NssmLogRotation -NssmPath $nssmPath -ServiceName $svc }
    }

    Write-Log "Windows services installed"
}

function Setup-VNC {
    Write-Log "Setting up VNC server..."

    # Configure TightVNC via registry (command-line options not supported).
    # Authentication is intentionally disabled: the host runs in a trusted
    # internal network and the password-sync path (HKLM vs per-service-SID hive)
    # is fragile across Session 0 / LocalSystem / NSSM combinations.
    # See docs/agent/TROUBLESHOOT.md ("Windows VNC duplicate services").
    $vncPath = "C:\Program Files\TightVNC\tvnserver.exe"
    if (Test-Path $vncPath) {
        Write-Log "Configuring TightVNC via registry (authentication disabled)..."

        foreach ($regPath in @("HKLM:\SOFTWARE\TightVNC\Server", "HKLM:\SOFTWARE\WOW6432Node\TightVNC\Server")) {
            if (-not (Test-Path $regPath)) {
                try { New-Item -Path $regPath -Force | Out-Null } catch { continue }
            }
            New-ItemProperty -Path $regPath -Name "UseVncAuthentication" -PropertyType DWord -Value 0 -Force | Out-Null
            Remove-ItemProperty -Path $regPath -Name "Password" -Force -ErrorAction SilentlyContinue
            New-ItemProperty -Path $regPath -Name "RfbPort" -PropertyType DWord -Value $script:HOST_VNC_PORT -Force | Out-Null
            New-ItemProperty -Path $regPath -Name "AcceptRfbConnections" -PropertyType DWord -Value 1 -Force | Out-Null
            New-ItemProperty -Path $regPath -Name "AllowLoopback" -PropertyType DWord -Value 1 -Force | Out-Null
        }

        # Restart whichever VNC service is actually registered so new settings take effect
        foreach ($svc in @("tvnserver", "vpt-vnc")) {
            if (Get-Service $svc -ErrorAction SilentlyContinue) {
                try { Restart-Service $svc -Force -ErrorAction SilentlyContinue } catch { }
            }
        }

        Write-Log "TightVNC configured on port $($script:HOST_VNC_PORT) (no authentication)"
        Write-Log "VNC has NO authentication on this host — the firewall rule is limited to the local subnet. Keep this machine off untrusted networks." "WARNING"
    } else {
        Write-Log "TightVNC not installed, skipping VNC configuration" "WARNING"
    }

    # Configure VcXsrv
    Write-Log "Configuring VcXsrv X11 server..."
    $vcxsrvConfigPath = "C:\ProgramData\VcXsrv\config.xlaunch"
    if (-not (Test-Path (Split-Path $vcxsrvConfigPath))) {
        New-Item -ItemType Directory -Path (Split-Path $vcxsrvConfigPath) -Force | Out-Null
    }

    $vcxsrvConfig = @"
-display :1
-screen 0 1280x720x24
-ac
+extension GLX
+render
-noreset
"@

    $vcxsrvConfig | Out-File -FilePath $vcxsrvConfigPath -Encoding ASCII
    Write-Log "VcXsrv configuration created"
}


function Setup-Firewall {
    Write-Log "Configuring Windows Firewall..."

    $firewallRules = @(
        @{
            Name = "VirtualPyTest Host API"
            Port = 6109
            Description = "VirtualPyTest Host API"
        },
        @{
            # TightVNC runs here without authentication (see Configure-TightVNC for why),
            # so this rule is scoped to the local subnet. Opening an unauthenticated
            # remote desktop to every routable address is not something a hardening
            # checklist can make safe after the fact.
            Name = "VirtualPyTest VNC"
            Port = $script:HOST_VNC_PORT
            Description = "VirtualPyTest VNC Server (LAN only — no VNC authentication)"
            RemoteAddress = "LocalSubnet"
        },
        @{
            Name = "VirtualPyTest noVNC"
            Port = 6080
            Description = "VirtualPyTest noVNC Web Interface"
        },
        @{
            Name = "VirtualPyTest Browser CDP 9222"
            Port = 9222
            Description = "VirtualPyTest browser remote debugging port 9222"
        },
        @{
            Name = "VirtualPyTest Browser CDP 9223"
            Port = 9223
            Description = "VirtualPyTest browser remote debugging port 9223"
        }
    )

    foreach ($rule in $firewallRules) {
        # Remove existing rule if it exists
        Remove-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue | Out-Null

        # Create new rule (suppress output)
        if ($rule.RemoteAddress) {
            New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Protocol TCP -LocalPort $rule.Port -Action Allow -Description $rule.Description -RemoteAddress $rule.RemoteAddress | Out-Null
            Write-Log "Created firewall rule: $($rule.Name) (Port $($rule.Port), $($rule.RemoteAddress) only)"
        } else {
            New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Protocol TCP -LocalPort $rule.Port -Action Allow -Description $rule.Description | Out-Null
            Write-Log "Created firewall rule: $($rule.Name) (Port $($rule.Port))"
        }
    }

    Write-Log "Windows Firewall configured"
}

function Create-StreamScript {
    # This repo includes a maintained PowerShell stream runner at backend_host/scripts/run_ffmpeg.ps1.
    # Do not generate/overwrite it at install time (older versions caused quoting/Session 0 issues).
    $streamScriptPath = Join-Path $script:SCRIPTS_PATH "run_ffmpeg.ps1"
    if (Test-Path $streamScriptPath) {
        Write-Log "Using repo stream script: $streamScriptPath"
        return
    }

    Write-Log "Missing stream script: $streamScriptPath" "ERROR"
    exit 1
}

function Start-Services {
    Write-Log "Starting VirtualPyTest services..."

    $servicesToStart = @(
        "vpt-monitor",
        "vpt-archiver",
        "vpt-transcript",
        "vpt-kpi",
        "vpt-vnc",
        "vpt-websockify"
    )

    foreach ($service in $servicesToStart) {
        try {
            Start-Service -Name $service -ErrorAction Stop
            Write-Log "Started service: $service"
        }
        catch {
            Write-Log "Failed to start service $service : $_" -Level "WARNING"
        }
    }

    try {
        Start-ScheduledTask -TaskName $script:HOST_TASK_NAME -ErrorAction Stop
        Write-Log "Started scheduled task: $($script:HOST_TASK_NAME)"
    } catch {
        Write-Log "Failed to start scheduled task $($script:HOST_TASK_NAME): $_" -Level "WARNING"
    }

    # Start stream task (interactive session)
    try {
        Start-ScheduledTask -TaskName $script:STREAM_TASK_NAME -ErrorAction Stop
        Write-Log "Started scheduled task: $($script:STREAM_TASK_NAME)"
    } catch {
        Write-Log "Failed to start scheduled task $($script:STREAM_TASK_NAME): $_" -Level "WARNING"
    }

    Write-Log "Services startup complete"
}

function Set-ServiceStartup {
    Write-Log "Configuring service startup types..."

    $services = @(
        "vpt-monitor",
        "vpt-archiver",
        "vpt-transcript",
        "vpt-kpi",
        "vpt-vnc",
        "vpt-websockify"
    )

    foreach ($service in $services) {
        try {
            Set-Service -Name $service -StartupType Automatic
            Write-Log "Set $service to start automatically"
        }
        catch {
            Write-Log "Failed to set startup type for $service : $_" -Level "WARNING"
        }
    }

    Write-Log "Service startup configuration complete"
}

function Test-Installation {
    Write-Log "Testing installation..."

    $tests = @()

    # Test Python environment
    try {
        $pythonVersion = & $script:PYTHON_EXE --version
        $tests += @{Name="Python Environment"; Status="PASS"; Details=$pythonVersion}
    }
    catch {
        $tests += @{Name="Python Environment"; Status="FAIL"; Details="Python not working"}
    }

    # Test services
    foreach ($service in $script:SERVICES.Keys) {
        if ($service -eq "vpt-host") {
            try {
                $task = Get-ScheduledTask -TaskName $script:HOST_TASK_NAME -ErrorAction Stop
                $info = Get-ScheduledTaskInfo -TaskName $script:HOST_TASK_NAME -ErrorAction Stop
                $state = $task.State
                $status = if ($state -eq "Running") { "PASS" } else { "WARNING" }
                $tests += @{Name="vpt-host"; Status=$status; Details="Task: $state (LastRun: $($info.LastRunTime))"}
            }
            catch {
                $tests += @{Name="vpt-host"; Status="WARNING"; Details="Task not found (log in to console + re-run installer)"}
            }
            continue
        }
        if ($service -eq "vpt-stream") {
            try {
                $task = Get-ScheduledTask -TaskName $script:STREAM_TASK_NAME -ErrorAction Stop
                $info = Get-ScheduledTaskInfo -TaskName $script:STREAM_TASK_NAME -ErrorAction Stop
                $state = $task.State
                $status = if ($state -eq "Running") { "PASS" } else { "WARNING" }
                $tests += @{Name="vpt-stream"; Status=$status; Details="Task: $state (LastRun: $($info.LastRunTime))"}
            }
            catch {
                $tests += @{Name="vpt-stream"; Status="WARNING"; Details="Task not found (log in to console + re-run installer)"}
            }
            continue
        }

        try {
            $svc = Get-Service -Name $service -ErrorAction Stop
            $status = if ($svc.Status -eq "Running") { "PASS" } else { "WARNING" }
            $tests += @{Name=$service; Status=$status; Details="Status: $($svc.Status)"}
        }
        catch {
            $tests += @{Name=$service; Status="FAIL"; Details="Service not found"}
        }
    }

    # Test directories
    $testDirs = @($script:INSTALL_PATH, $script:LOGS_PATH)
    foreach ($dir in $testDirs) {
        $status = if (Test-Path $dir) { "PASS" } else { "FAIL" }
        $tests += @{Name="Directory: $(Split-Path $dir -Leaf)"; Status=$status; Details=$dir}
    }

    # Display test results
    Write-Log "Installation Test Results:"
    Write-Log ("-" * 60)

    foreach ($test in $tests) {
        $statusIcon = switch ($test.Status) {
            "PASS" { "[PASS]" }
            "WARNING" { "[WARN]" }
            "FAIL" { "[FAIL]" }
        }
        Write-Log ("{0,-25} {1} {2}" -f $test.Name, $statusIcon, $test.Details)
    }

    Write-Log ("-" * 60)

    $failedTests = @($tests | Where-Object { $_.Status -eq "FAIL" }).Count
    if ($failedTests -eq 0) {
        Write-Log "Installation completed successfully!" -Level "SUCCESS"
    } else {
        Write-Log "$failedTests test(s) failed. Check the details above." -Level "WARNING"
    }
}

function Uninstall-VirtualPyTest {
    Write-Log "Uninstalling VirtualPyTest..."

    # Remove stream task (Windows)
    try {
        if (Get-ScheduledTask -TaskName $script:HOST_TASK_NAME -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $script:HOST_TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
            Write-Log "Removed scheduled task: $($script:HOST_TASK_NAME)"
        }
        if (Get-ScheduledTask -TaskName $script:STREAM_TASK_NAME -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $script:STREAM_TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
            Write-Log "Removed scheduled task: $($script:STREAM_TASK_NAME)"
        }
    } catch { }

    # Stop and remove services (new names + legacy)
    $allServices = @()
    $allServices += $script:SERVICES.Keys
    $allServices += @(
        "VirtualPyTest-Flask","VirtualPyTest-Monitor","VirtualPyTest-Stream","VirtualPyTest-Archiver","VirtualPyTest-Transcript","VirtualPyTest-VNC","VirtualPyTest-WebSockify",
        "VPTFlaskAPI","VPTMonitor","VPTStream","VPTArchiver","VPTTranscript","VPTVNC","VPTWebSockify"
    )
    foreach ($service in ($allServices | Select-Object -Unique)) {
        try {
            Stop-Service -Name $service -ErrorAction SilentlyContinue
            & nssm remove $service confirm
            Write-Log "Removed service: $service"
        }
        catch {
            Write-Log "Failed to remove service $service : $_" -Level "WARNING"
        }
    }

    # Remove directories
    $dirsToRemove = @($script:INSTALL_PATH)
    foreach ($dir in $dirsToRemove) {
        if (Test-Path $dir) {
            Remove-Item -Path $dir -Recurse -Force -ErrorAction SilentlyContinue
            Write-Log "Removed directory: $dir"
        }
    }

    # Remove firewall rules
    $firewallRules = @("VirtualPyTest Host API", "VirtualPyTest VNC", "VirtualPyTest noVNC")
    foreach ($rule in $firewallRules) {
        Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue
    }

    # Remove environment variables
    $envVars = @("VIRTUALPYTEST_ROOT", "VIRTUALPYTEST_HOST", "VIRTUALPYTEST_LOGS", "PYTHONPATH")
    foreach ($envVar in $envVars) {
        [Environment]::SetEnvironmentVariable($envVar, $null, "Machine")
    }

    Write-Log "VirtualPyTest uninstallation complete"
}

function Show-Usage {
    Write-Log "VirtualPyTest Windows Installation Complete!"
    Write-Log ""
    Write-Log "Configuration:"
    Write-Log "   Config File: $($script:BACKEND_HOST_PATH)\src\.env"
    Write-Log "   Logs: $($script:LOGS_PATH)"
    Write-Log "   Storage: $($script:INSTALL_PATH)"
    Write-Log ""
    Write-Log "Service Management:"
    Write-Log "   Start all:  Get-Service vpt-* | Start-Service"
    Write-Log "   Stop all:   Get-Service vpt-* | Stop-Service"
    Write-Log "   Status:     Get-Service vpt-*"
    Write-Log ""
    Write-Log "Access Points:"
    Write-Log "   API:        http://localhost:6109"
    Write-Log "   VNC:        localhost:$($script:HOST_VNC_PORT)"
    Write-Log "   noVNC Web:  http://localhost:6080"
    Write-Log ""
    Write-Log "Next Steps:"
    Write-Log "   1. Edit $($script:BACKEND_HOST_PATH)\src\.env to configure devices"
    Write-Log "   2. Configure camera devices in FFmpeg stream script"
    Write-Log "   3. Test services: Get-Service vpt-* | Select Name, Status"
    Write-Log ""
    Write-Log "Troubleshooting:"
    Write-Log "   Logs:       $($script:LOGS_PATH)\*.log"
    Write-Log "   Services:   eventvwr.msc (Windows Event Viewer)"
    Write-Log "   FFmpeg:     Check $($script:LOGS_PATH)\ffmpeg_*.log"
}

# Main installation logic
function Install-Main {
    try {
        Write-Log "Starting VirtualPyTest Windows Installation"
        Write-Log "Install Path: $($script:INSTALL_PATH)"

        # Check administrator privileges
        if (-not (Test-Administrator)) {
            throw "This script must be run as Administrator"
        }

        # Change to project root
        Set-Location $script:PROJECT_ROOT

        # Installation steps
        Install-WindowsDependencies
        Setup-PythonEnvironment
        Setup-EnvironmentConfiguration
        Setup-StorageDirectories
        Install-WindowsServices
        Setup-VNC
        Setup-Firewall
        Create-StreamScript
        Set-ServiceStartup
        Start-Services
        Test-Installation

        Show-Usage

    }
    catch {
        Write-Log "Installation failed: $_" -Level "ERROR"
        Write-Log "Check the log file at $($script:LOGS_PATH)\install.log for details"
        throw
    }
}

# Main script execution
Install-Main
