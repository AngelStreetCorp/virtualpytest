# setup/docker/installers/windows/install_docker.ps1
# Windows Docker Desktop installer

Write-Host "[DOCKER] Installing Docker Desktop for Windows"
Write-Host ""

# Check if Docker is already installed
if (Get-Command docker -ErrorAction SilentlyContinue) {
    try {
        $version = docker --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Docker is already installed"
            Write-Host $version
            exit 0
        }
    } catch {
         Write-Host "[ERROR] Docker command exists but failed, continue with installation"
         exit 1
    }
}

# Check if running as administrator
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "[ERROR] Please run as Administrator"
    Write-Host "   Right-click PowerShell and select 'Run as Administrator'"
    exit 1
}

# Install Chocolatey if not present
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
    Write-Host "[INSTALL] Installing Chocolatey package manager..."
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    try {
        Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))
        Write-Host "[OK] Chocolatey installed successfully"
    } catch {
        Write-Host "[ERROR] Failed to install Chocolatey: $($_.Exception.Message)"
        exit 1
    }
} else {
    Write-Host "[OK] Chocolatey is already installed"
}

# Install Docker Desktop
Write-Host "[INSTALL] Installing Docker Desktop..."
try {
    choco install docker-desktop -y
    Write-Host "[OK] Docker Desktop installed successfully"
} catch {
    Write-Host "[ERROR] Failed to install Docker Desktop: $($_.Exception.Message)"
    Write-Host "   You can install Docker Desktop manually from: https://www.docker.com/products/docker-desktop"
    exit 1
}

# Enable WSL2 for better Linux container support
Write-Host "[CONFIG] Enabling WSL2 support..."
try {
    dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
    dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
    Write-Host "[OK] WSL2 enabled"
} catch {
    Write-Host "[WARNING] WSL2 setup failed, but Docker Desktop should still work"
}

Write-Host ""
Write-Host "[SUCCESS] Docker Desktop installation completed!"
Write-Host ""
Write-Host "[NEXT] Next steps:"
Write-Host "   1. Restart your computer"
Write-Host "   2. Start Docker Desktop from the Start menu"
Write-Host "   3. Wait for Docker to finish initializing"
Write-Host "   4. Run: docker --version"
Write-Host ""
Write-Host "[INFO] Useful commands:"
Write-Host "   Start Docker:  docker --version"
Write-Host "   Launch app:   cd setup\docker\standalone_server_host"
Write-Host "                 .\launch.bat"
Write-Host ""

# Restart computer to complete installation
Write-Host "[RESTART] Docker installation completed! Please restart your computer to complete the installation."
