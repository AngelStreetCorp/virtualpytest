param()

$ErrorActionPreference = "Continue"

# Per-file size cap for wrapper-owned logs. Parity with run_ffmpeg.ps1
# Reset-LogIfLarge (MaxSizeMB=30) — prevents host.log / host_error.log /
# host_wrapper.log from growing unbounded and starving the single
# gunicorn worker (1 worker / 1 thread / gevent) on disk I/O.
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
    $line = "[$ts] [host_wrapper] $Msg"
    try {
        $logRoot = $env:VIRTUALPYTEST_LOGS
        if (-not $logRoot) { $logRoot = "C:\\virtualpytest\\logs" }
        $null = New-Item -ItemType Directory -Path $logRoot -Force -ErrorAction SilentlyContinue
        $wrapperLog = Join-Path $logRoot "host_wrapper.log"
        Rotate-LogFile -Path $wrapperLog -MaxBytes $LogMaxBytes
        $line | Out-File -FilePath $wrapperLog -Append -Encoding UTF8
    } catch { }
    Write-Host $line
}

# Pump one redirected stream to a wrapper-owned log file, rotating in place
# when it crosses the cap. Runs in its own runspace/thread so stdout and
# stderr drain independently (no two-stream deadlock) and stay in separate
# files. Owns the write handle, so Move-Item rotation is clean.
$StreamPump = {
    param($Reader, $Path, [long]$MaxBytes)

    function RotateNow([string]$p, [long]$m) {
        try {
            if ((Test-Path $p) -and ((Get-Item $p -ErrorAction Stop).Length -ge $m)) {
                $b = "$p.1"
                Remove-Item -LiteralPath $b -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath $p -Destination $b -Force -ErrorAction SilentlyContinue
            }
        } catch { }
    }

    $enc = New-Object System.Text.UTF8Encoding($false)  # UTF-8, no BOM (matches python output)
    $sw = $null
    try {
        while ($true) {
            $linecontent = $Reader.ReadLine()
            if ($null -eq $linecontent) { break }   # stream closed: process exited
            if ($null -eq $sw) {
                RotateNow $Path $MaxBytes            # rotate carryover from a previous run
                $sw = New-Object System.IO.StreamWriter($Path, $true, $enc)
                $sw.AutoFlush = $true
            }
            $sw.WriteLine($linecontent)
            if ($sw.BaseStream.Length -ge $MaxBytes) {
                $sw.Flush(); $sw.Close(); $sw = $null
                RotateNow $Path $MaxBytes            # move the just-closed file to .1
            }
        }
    } finally {
        if ($null -ne $sw) { try { $sw.Flush(); $sw.Close() } catch { } }
    }
}

try {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $backendHostDir = Split-Path -Parent $scriptDir
    $projectRoot = Split-Path -Parent $backendHostDir

    $env:VIRTUALPYTEST_ROOT = $projectRoot
    $env:VIRTUALPYTEST_HOST = $backendHostDir
    if (-not $env:VIRTUALPYTEST_LOGS) { $env:VIRTUALPYTEST_LOGS = "C:\\virtualpytest\\logs" }

    $venvPython = Join-Path $projectRoot "venv\\Scripts\\python.exe"
    $appPath = Join-Path $backendHostDir "src\\app.py"
    $logRoot = $env:VIRTUALPYTEST_LOGS
    $null = New-Item -ItemType Directory -Path $logRoot -Force -ErrorAction SilentlyContinue
    $stdoutLog = Join-Path $logRoot "host.log"
    $stderrLog = Join-Path $logRoot "host_error.log"

    if (-not (Test-Path $venvPython)) {
        Write-Log "Python executable not found: $venvPython"
        exit 2
    }
    if (-not (Test-Path $appPath)) {
        Write-Log "Host app not found: $appPath"
        exit 2
    }

    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONPATH = "$projectRoot;$projectRoot\\shared;$backendHostDir\\src"

    # Rotate any oversized carryover before the long-lived process starts.
    Rotate-LogFile -Path $stdoutLog -MaxBytes $LogMaxBytes
    Rotate-LogFile -Path $stderrLog -MaxBytes $LogMaxBytes

    # Supervisor loop. The backend host MUST survive transient network/DB
    # outages: app.py treats Supabase unreachable at startup as fatal
    # (validate_core_environment -> sys.exit(1)), and the live gevent server
    # also dies if its bound LAN socket drops when the adapter goes down.
    # Recovery used to depend solely on Task Scheduler's RestartOnFailure,
    # which is bounded (Count=999, then it gives up permanently until next
    # logon) and unreliable — so a multi-hour network outage left the host
    # dead with no recovery. This loop relaunches Python ourselves, forever,
    # with capped backoff, independent of Task Scheduler. We never exit on a
    # child failure; the loop just waits and retries until the network (and
    # thus the startup DB probe) recovers.
    $minBackoff = 5      # seconds; delay after a fast/early crash
    $maxBackoff = 60     # seconds; cap so a hard crash-loop doesn't spin hot
    $stableRunSecs = 60  # ran at least this long => treat as healthy, reset backoff
    $backoff = $minBackoff

    while ($true) {
        Write-Log "Starting backend host app from $appPath (log cap ${LogMaxBytes}B/file, 1 backup)"
        $runStart = Get-Date

        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $venvPython
        $psi.Arguments = "`"$appPath`""
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        $psi.WorkingDirectory = $scriptDir

        $proc = New-Object System.Diagnostics.Process
        $proc.StartInfo = $psi
        [void]$proc.Start()

        # Two in-process runspaces share the live StreamReader objects by
        # reference (same AppDomain) and own their own write handles.
        # Recreated each iteration since the child (and its streams) is new.
        $pumpText = $StreamPump.ToString()
        $outPs = [powershell]::Create()
        $outPs.AddScript($pumpText).AddArgument($proc.StandardOutput).AddArgument($stdoutLog).AddArgument($LogMaxBytes) | Out-Null
        $errPs = [powershell]::Create()
        $errPs.AddScript($pumpText).AddArgument($proc.StandardError).AddArgument($stderrLog).AddArgument($LogMaxBytes) | Out-Null
        $outHandle = $outPs.BeginInvoke()
        $errHandle = $errPs.BeginInvoke()

        $proc.WaitForExit()
        $code = $proc.ExitCode

        # Let the pumps drain trailing output, then tear down.
        $outPs.EndInvoke($outHandle); $outPs.Dispose()
        $errPs.EndInvoke($errHandle); $errPs.Dispose()

        $ranSecs = [int]((Get-Date) - $runStart).TotalSeconds
        if ($ranSecs -ge $stableRunSecs) {
            # Process stayed up long enough to count as a real run (e.g. the
            # live server lost its socket on a network blip). Reset backoff so
            # recovery is fast.
            Write-Log "backend host app exited with code $code after ${ranSecs}s; restarting in ${minBackoff}s"
            $backoff = $minBackoff
        } else {
            Write-Log "backend host app exited with code $code after ${ranSecs}s (early exit, likely network/DB unreachable); restarting in ${backoff}s"
        }

        Start-Sleep -Seconds $backoff

        # Grow backoff only for fast/early crashes (network still down), capped.
        if ($ranSecs -lt $stableRunSecs) {
            $backoff = [Math]::Min($maxBackoff, $backoff * 2)
        }
    }
} catch {
    # The supervisor loop above never exits, so reaching here means a fatal
    # setup error (bad paths, runspace failure, etc). Exit non-zero so Task
    # Scheduler's RestartOnFailure picks it up as a backstop.
    Write-Log "Unhandled error: $_"
    exit 1
}
