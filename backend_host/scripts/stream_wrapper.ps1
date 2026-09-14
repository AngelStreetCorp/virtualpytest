param(
    [string]$TargetDevice = "all",
    [string]$Quality = "sd"
)

$ErrorActionPreference = "Continue"

# Per-file size cap, parity with run_ffmpeg.ps1 Reset-LogIfLarge (MaxSizeMB=30).
# run_ffmpeg.ps1 already self-caps the ffmpeg stderr log; this only bounds the
# wrapper-owned stream_wrapper.log so it can't grow unbounded either.
$LogMaxBytes = 30MB

function Rotate-LogFile {
    # Size-capped rotation, keep one .1 backup. Safe to call only on files
    # this script owns the write handle for (no concurrent appender).
    param([string]$Path, [long]$MaxBytes)
    try {
        if ((Test-Path $Path) -and ((Get-Item $Path -ErrorAction Stop).Length -ge $MaxBytes)) {
            $bak = "$Path.1"
            Remove-Item -LiteralPath $bak -Force -ErrorAction SilentlyContinue
            Move-Item -LiteralPath $Path -Destination $bak -Force -ErrorAction SilentlyContinue
        }
    } catch { }
}

function Write-Log([string]$Msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [stream_wrapper] $Msg"
    try {
        $logRoot = $env:VIRTUALPYTEST_LOGS
        if (-not $logRoot) { $logRoot = "C:\\virtualpytest\\logs" }
        $null = New-Item -ItemType Directory -Path $logRoot -Force -ErrorAction SilentlyContinue
        $wrapperLog = Join-Path $logRoot "stream_wrapper.log"
        Rotate-LogFile -Path $wrapperLog -MaxBytes $LogMaxBytes
        $line | Out-File -FilePath $wrapperLog -Append -Encoding UTF8
    } catch { }
    Write-Host $line
}

try {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $backendHostDir = Split-Path -Parent $scriptDir
    $projectRoot = Split-Path -Parent $backendHostDir

    $env:VIRTUALPYTEST_ROOT = $projectRoot
    $env:VIRTUALPYTEST_HOST = $backendHostDir
    if (-not $env:VIRTUALPYTEST_LOGS) { $env:VIRTUALPYTEST_LOGS = "C:\\virtualpytest\\logs" }

    $runFfmpeg = Join-Path $scriptDir "run_ffmpeg.ps1"
    if (-not (Test-Path $runFfmpeg)) {
        Write-Log "run_ffmpeg.ps1 not found: $runFfmpeg"
        exit 2
    }

    Write-Log "Starting run_ffmpeg.ps1 (TargetDevice=$TargetDevice, Quality=$Quality) from $runFfmpeg"

    # If ffmpeg exits (e.g., locked screen / permissions), we want the task to be restartable.
    & $runFfmpeg -TargetDevice $TargetDevice -Quality $Quality
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Write-Log "run_ffmpeg.ps1 exited with code $code"
        exit $code
    }
} catch {
    Write-Log "Unhandled error: $_"
    exit 1
}
