# run_audio_stereo_mix.ps1 - vpt-windows host_vnc audio capture + HLS segmenter.
#
# Owns ONE pipeline: capture_audio_stereo_mix.py | ffmpeg. The Python process
# reads the Stereo Mix / Mixage stereo device and writes raw PCM to stdout; the
# OS pipe feeds ffmpeg as `-f s16le -i -`. One wrapper, one process tree.
#
# Why a pipe and not a rolling raw.pcm file?
#   - A regular file is read from byte 0 by ffmpeg every time it (re)starts, so
#     after any restart ffmpeg replays the whole history (40 minutes of audio
#     after 40 minutes of uptime) instead of the live stream. On top of that
#     `-use_wallclock_as_timestamps 1` leaves `-re` with nothing to pace
#     against, so ffmpeg read the file back as fast as the disk served it,
#     reached EOF in ~65 s and was restarted in a loop while the playlist
#     churned. Measured on vpt-windows 2026-10-17: raw.pcm at 425 MB and frozen,
#     ffmpeg restarted every 65 s, audio HLS resetting with it.
#   - The file also never stops growing (~14 GB/day at 44.1 kHz stereo), and
#     truncating it under a live writer produces a sparse file.
#   - A pipe has no history: each read is the live samples, nothing to replay,
#     nothing on disk. The capture script already detects a dead parent through
#     a BrokenPipe on stdout, which is exactly the contract a pipe needs.
#
# Stalled-source recovery: PortAudio can stop calling the callback (device
# disappeared, "Mixage stereo" disabled, sound service restarted) while the
# Python process stays alive. A pipe then simply goes quiet, so liveness alone
# is not enough: the loop also watches the HLS playlist's LastWriteTime and
# restarts the pair when it has not advanced for VPT_AUDIO_STALL_SECONDS
# (default 20 s, i.e. ten 2 s segments).
#
# Contract with installer:
#   Sets up the Scheduled Task `vpt-windows-audio` that runs THIS script under
#   the console user's InteractiveToken (Session 1) at logon.
#
# Ref: BUG-0597 (original pipeline), BUG-0604 (this rewrite).

$ErrorActionPreference = 'Stop'

# ----- Config (env-driven with sane defaults) ---------------------------------

$ScriptDir       = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }

$ProjectRoot     = $env:VPT_PROJECT_ROOT
if (-not $ProjectRoot) {
    # Best-effort discovery: this script lives in backend_host/scripts/, parent
    # is the project root. Works on first install when $env is not yet loaded.
    $candidates = @(
        (Resolve-Path (Join-Path $ScriptDir '..\..')).Path,
        'C:\virtualpytest\virtualpytest',
        'C:\virtualpytest',
        'D:\virtualpytest\virtualpytest'
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path (Join-Path $c 'backend_host\src\.env'))) {
            $ProjectRoot = $c
            break
        }
    }
    if (-not $ProjectRoot) { $ProjectRoot = 'C:\virtualpytest\virtualpytest' }
}

$venvPython      = if ($env:VPT_VENV_PYTHON) { $env:VPT_VENV_PYTHON }
                   elseif ($ProjectRoot)   { Join-Path $ProjectRoot 'venv\Scripts\python.exe' }
                   else                    { 'C:\virtualpytest\virtualpytest\venv\Scripts\python.exe' }
$CaptureScript   = if ($env:VPT_AUDIO_CAPTURE_SCRIPT) { $env:VPT_AUDIO_CAPTURE_SCRIPT }
                   elseif ($ScriptDir -and (Test-Path (Join-Path $ScriptDir 'capture_audio_stereo_mix.py'))) {
                       Join-Path $ScriptDir 'capture_audio_stereo_mix.py'
                   }
                   elseif ($ProjectRoot) {
                       Join-Path $ProjectRoot 'backend_host\scripts\capture_audio_stereo_mix.py'
                   } else {
                       'C:\virtualpytest\capture_audio_stereo_mix.py'
                   }

$ffmpegExe       = if ($env:VPT_FFMPEG_PATH) { $env:VPT_FFMPEG_PATH } else { 'C:\ffmpeg\bin\ffmpeg.exe' }

$StreamBase      = if ($env:VPT_STREAM_BASE) { $env:VPT_STREAM_BASE } else { 'C:\virtualpytest\stream' }
$Device          = if ($env:VPT_AUDIO_DEVICE) { $env:VPT_AUDIO_DEVICE } else { 'device1' }
$AudioFolder     = Join-Path $StreamBase "${Device}_audio"
$SegmentsDir     = Join-Path $AudioFolder 'segments'
$Playlist        = Join-Path $SegmentsDir 'output.m3u8'
$LegacyRawPcm    = Join-Path $AudioFolder 'raw.pcm'
$PipelineCmd     = Join-Path $AudioFolder 'audio_pipeline.cmd'

# The wrapper runs as the console user (session 1) because WASAPI loopback has
# no meaning in session 0. ProgramData\virtualpytest\logs is owned by the
# SYSTEM install and the interactive token cannot write the pidfile there
# (UnauthorizedAccessException, seen 2026-10-17), so default to the host log
# root the other wrappers use. Logs are still tailed from the same place docs
# point at (%VIRTUALPYTEST_LOGS%).
$LogDir          = if ($env:VPT_LOG_DIR) { $env:VPT_LOG_DIR }
                   elseif ($env:VIRTUALPYTEST_LOGS) { $env:VIRTUALPYTEST_LOGS }
                   else { 'C:\virtualpytest\logs' }
if (-not (Test-Path $LogDir)) { New-Item -Path $LogDir -ItemType Directory -Force | Out-Null }

$LogFile         = Join-Path $LogDir "vpt-windows-audio.log"
$FfmpegStderr    = Join-Path $AudioFolder 'ffmpeg.err'
$CaptureStderr   = Join-Path $AudioFolder 'capture.err'

$SampleRate      = if ($env:VPT_AUDIO_SAMPLE_RATE) { $env:VPT_AUDIO_SAMPLE_RATE } else { 44100 }
$Channels        = if ($env:VPT_AUDIO_CHANNELS) { $env:VPT_AUDIO_CHANNELS } else { 2 }
$Bitrate         = if ($env:VPT_AUDIO_BITRATE) { $env:VPT_AUDIO_BITRATE } else { '64k' }
$SegmentSeconds  = if ($env:VPT_AUDIO_SEGMENT_SECONDS) { $env:VPT_AUDIO_SEGMENT_SECONDS } else { 2 }
$PlaylistSize    = if ($env:VPT_AUDIO_PLAYLIST_SIZE) { $env:VPT_AUDIO_PLAYLIST_SIZE } else { 10 }
$StallSeconds    = if ($env:VPT_AUDIO_STALL_SECONDS) { [int]$env:VPT_AUDIO_STALL_SECONDS } else { 20 }

$DeviceHint      = if ($env:VPT_AUDIO_DEVICE_HINT) { $env:VPT_AUDIO_DEVICE_HINT } else { 'Mixage_stereo' }

# ----- Helpers ---------------------------------------------------------------

function Write-AudioLog {
    param([string]$line)
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $final = "[$stamp] $line"
    try { Add-Content -Path $LogFile -Value $final -Encoding UTF8 } catch { }
    Write-Host $final
}

function Initialize-AudioDirs {
    foreach ($d in @($AudioFolder, $SegmentsDir)) {
        if (-not (Test-Path $d)) {
            New-Item -Path $d -ItemType Directory -Force | Out-Null
        }
    }
    # The old file-based pipeline left a 400+ MB raw.pcm behind. It is not read
    # or written any more (the samples travel through the pipe); drop it.
    if (Test-Path $LegacyRawPcm) {
        try {
            Remove-Item $LegacyRawPcm -Force -ErrorAction Stop
            Write-AudioLog "removed legacy raw.pcm (file-based pipeline no longer used)"
        } catch {
            Write-AudioLog "could not remove legacy raw.pcm: $($_.Exception.Message)"
        }
    }
    Reset-AudioDirs
}

function Reset-AudioDirs {
    # Clear stale segments between pipeline restarts so a half-written segment
    # from the previous instance is never served.
    foreach ($seg in (Get-ChildItem $SegmentsDir -ErrorAction SilentlyContinue)) {
        Remove-Item $seg.FullName -Force -ErrorAction SilentlyContinue
    }
}

function Test-AudioEnvironment {
    if (-not (Test-Path $venvPython)) {
        Write-AudioLog "python not found at $venvPython -- check venv path"
        return $false
    }
    if (-not (Test-Path $CaptureScript)) {
        Write-AudioLog "capture script not found at $CaptureScript"
        return $false
    }
    if (-not (Test-Path $ffmpegExe)) {
        Write-AudioLog "ffmpeg not found at $ffmpegExe -- install ffmpeg"
        return $false
    }
    return $true
}

function Write-PipelineCmd {
    # One cmd.exe process owns the OS pipe: python | ffmpeg. Writing a .cmd file
    # keeps the quoting readable (and debuggable by hand) instead of nesting
    # Start-Process -ArgumentList quoting around a pipeline. ASCII only: this
    # file is consumed by cmd.exe.
    $ffArgs = @(
        '-hide_banner', '-loglevel', 'error', '-y',
        '-fflags', '+nobuffer+genpts+flush_packets',
        '-use_wallclock_as_timestamps', '1',
        '-f', 's16le',
        '-ar', "$SampleRate",
        '-ac', "$Channels",
        '-i', '-',
        '-c:a', 'aac', '-b:a', $Bitrate,
        '-ar', '44100',
        '-f', 'hls',
        '-hls_time', "$SegmentSeconds",
        '-hls_list_size', "$PlaylistSize",
        '-hls_flags', '+delete_segments+omit_endlist',
        # `%%` because this line is written to a .cmd file: cmd expands `%0`
        # in a batch file (it became the script path in the first live run).
        '-hls_segment_filename', "`"$(Join-Path $SegmentsDir 'segment_%%09d.ts')`"",
        "`"$Playlist`""
    ) -join ' '

    $lines = @(
        '@echo off',
        ('"' + $venvPython + '" "' + $CaptureScript + '" --device-hint ' + $DeviceHint + ' 2>>"' + $CaptureStderr + '" | "' + $ffmpegExe + '" ' + $ffArgs + ' 2>>"' + $FfmpegStderr + '"')
    )
    Set-Content -Path $PipelineCmd -Value $lines -Encoding ASCII
}

function Start-Pipeline {
    Reset-AudioDirs
    Write-PipelineCmd
    Write-AudioLog "starting pipeline: python capture | ffmpeg (hint=$DeviceHint sr=$SampleRate ch=$Channels)"
    $proc = Start-Process -FilePath $env:ComSpec -ArgumentList @('/c', "`"$PipelineCmd`"") `
        -PassThru -NoNewWindow
    Write-AudioLog "pipeline pid=$($proc.Id)"
    return $proc
}

function Stop-Pipeline {
    param($Proc)
    if ($null -eq $Proc) { return }
    try {
        # /T kills the python + ffmpeg children too; without it the pair leaks
        # and the next start fights the old ffmpeg for the playlist.
        & taskkill /T /F /PID $Proc.Id 2>&1 | Out-Null
    } catch { }
}

function Get-PlaylistStamp {
    try {
        $f = Get-Item $Playlist -ErrorAction Stop
        return "$($f.LastWriteTimeUtc.Ticks)/$($f.Length)"
    } catch {
        return ''
    }
}

function Test-ProcAlive {
    param([int]$Id)
    if ($Id -le 0) { return $false }
    try {
        $p = Get-Process -Id $Id -ErrorAction Stop
        return -not $p.HasExited
    } catch {
        return $false
    }
}

# ----- Main loop -------------------------------------------------------------

if (-not (Test-AudioEnvironment)) {
    Write-AudioLog "environment not ready, exiting (Scheduled Task will not be re-armed)"
    exit 1
}

Initialize-AudioDirs
Write-AudioLog "vpt-windows audio pipeline starting (pipe mode, hint=$DeviceHint sr=$SampleRate ch=$Channels)"
Write-AudioLog "  stream dir = $AudioFolder"
Write-AudioLog "  segments   = $SegmentsDir"
Write-AudioLog "  log file   = $LogFile"
Write-AudioLog "  stall watchdog = $StallSeconds s"

# 5s cooldown mirrors run_ffmpeg.ps1 (BUG-0592) so a crashing loop doesn't
# hammer Scheduled Task's restart counter.
$CooldownSeconds = 5
$shouldRun = $true

$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    $script:shouldRun = $false
}

# Refuse to start TWO instances at once via a pidfile lock. The file stores
# "<pid>|<process-start-ticks>" so a recycled PID (a stale file whose number now
# belongs to this very process, which happened on 2026-10-17) is not mistaken
# for a live sibling.
$LockFile = Join-Path $LogDir 'vpt-windows-audio.pid'
$thisStart = (Get-Process -Id $PID).StartTime.Ticks
if (Test-Path $LockFile) {
    $raw = ''
    try { $raw = (Get-Content $LockFile -Raw).Trim() } catch { }
    $parts = $raw -split '\|'
    $existingPid = 0
    $existingStart = [int64]0
    [void][int]::TryParse($parts[0], [ref]$existingPid)
    if ($parts.Count -gt 1) { [void][int64]::TryParse($parts[1], [ref]$existingStart) }
    if ($existingPid -gt 0 -and $existingPid -ne $PID) {
        try {
            $p = Get-Process -Id $existingPid -ErrorAction Stop
            if ($existingStart -eq 0 -or $p.StartTime.Ticks -eq $existingStart) {
                Write-AudioLog "another audio pipeline already runs (pid=$existingPid started $($p.StartTime)) -- exiting clean"
                exit 0
            }
            Write-AudioLog "pidfile pid=$existingPid belongs to a different process now (start time mismatch), reclaiming"
        } catch {
            Write-AudioLog "stale pidfile detected (pid=$existingPid not running), reclaiming"
        }
    }
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
}
try {
    Set-Content -Path $LockFile -Value ("$PID|$thisStart") -NoNewline
} catch {
    # Never let a log-dir ACL decision stop the audio pipeline.
    Write-AudioLog "could not write pidfile ($($_.Exception.Message)) -- continuing without the single-instance lock"
}
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    param($Event)
    if (Test-Path $LockFile) {
        $current = ''
        try { $current = Get-Content $LockFile -Raw } catch { }
        if ($current -like "$PID|*") { Remove-Item $LockFile -Force }
    }
}

# Initial probe to make sure the device is visible before we commit
$probeOut = [System.IO.Path]::GetTempFileName()
$probe = Start-Process -FilePath $venvPython -ArgumentList @($CaptureScript, '--probe', '--device-hint', $DeviceHint) `
    -PassThru -NoNewWindow -Wait `
    -RedirectStandardOutput $probeOut `
    -RedirectStandardError $CaptureStderr
Remove-Item $probeOut -Force -ErrorAction SilentlyContinue
if ($probe.ExitCode -ne 0) {
    Write-AudioLog "probe failed: no usable capture source. Check the default speaker (WASAPI loopback) or, in stereo_mix mode, that 'Mixage stereo' is enabled in Sound Control Panel > Recording > right-click > Show Disabled Devices."
    exit 1
}
Write-AudioLog "probe ok, starting capture | ffmpeg pipeline"

$pipeline      = $null
$lastStamp     = ''
$lastAdvance   = Get-Date
$startedAt     = Get-Date

try {
    while ($shouldRun) {
        if (-not (Test-ProcAlive $pipeline.Id)) {
            if ($null -ne $pipeline) {
                Write-AudioLog "pipeline pid=$($pipeline.Id) exited -- restarting"
            }
            $pipeline    = Start-Pipeline
            $startedAt   = Get-Date
            $lastAdvance = Get-Date
            $lastStamp   = ''
            # Give the pair time to open the device and write the first segment.
            Start-Sleep -Seconds 6
            continue
        }

        $stamp = Get-PlaylistStamp
        if ($stamp -ne $lastStamp) {
            $lastStamp   = $stamp
            $lastAdvance = Get-Date
        } else {
            $silentFor = [int]((Get-Date) - $lastAdvance).TotalSeconds
            if ($silentFor -ge $StallSeconds) {
                Write-AudioLog "no HLS playlist update for ${silentFor}s (capture stalled or ffmpeg blocked) -- restarting pipeline"
                Stop-Pipeline $pipeline
                $pipeline = $null
                Start-Sleep -Seconds $CooldownSeconds
                continue
            }
        }

        Start-Sleep -Seconds 2
    }
}
finally {
    Write-AudioLog "shutting down audio pipeline"
    Stop-Pipeline $pipeline
    Reset-AudioDirs
    Write-AudioLog "stopped cleanly"
}
