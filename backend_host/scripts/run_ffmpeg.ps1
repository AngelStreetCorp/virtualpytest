param(
    [string]$TargetDevice = "all",
    [string]$Quality = "sd"
)

$ErrorActionPreference = "Stop"

# Get script paths
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendHostDir = Split-Path -Parent $scriptDir
$envFile = Join-Path $backendHostDir "src\.env"

# Load environment variables
if (Test-Path $envFile) {
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

    foreach ($line in Get-Content $envFile) {
        if ($null -eq $line) { $line = "" }
        $l = ([string]$line).Trim()
        if (-not $l -or $l.StartsWith("#")) { continue }
        if ($l -notmatch '^\s*([^=]+?)\s*=\s*(.*)\s*$') { continue }

        $key = $matches[1].Trim()
        $value = Parse-DotEnvValue -RawValue $matches[2]
        if ($key) {
            Set-Item -Path "env:$key" -Value $value
        }
    }
}

# Build grabber configuration
$grabbers = @{}
$script:FFMPEG_PIDS = @()
$script:ACTIVE_CAPTURES_FILE = $null
$script:DEVICE_STATE = @{}

function Get-NowEpoch {
    return [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
}

function Get-EnvIntOrDefault {
    param(
        [string]$Name,
        [int]$DefaultValue
    )
    $raw = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($raw)) { return $DefaultValue }

    $parsed = 0
    if ([int]::TryParse($raw, [ref]$parsed)) { return $parsed }
    return $DefaultValue
}

$script:STALL_TIMEOUT_SECONDS = Get-EnvIntOrDefault -Name "FFMPEG_STALL_TIMEOUT_SECONDS" -DefaultValue 20
$script:STALL_RESTART_COOLDOWN_SECONDS = Get-EnvIntOrDefault -Name "FFMPEG_STALL_RESTART_COOLDOWN_SECONDS" -DefaultValue 30

# Host grabber (VNC display)
if ($env:HOST_VIDEO_SOURCE) {
    $grabbers["host"] = "$($env:HOST_VIDEO_SOURCE)|$($env:HOST_VIDEO_AUDIO)|$($env:HOST_VIDEO_CAPTURE_PATH)|$($env:HOST_VIDEO_FPS)"
}

# Device grabbers
for ($i = 1; $i -le 10; $i++) {
    $videoVar = "DEVICE${i}_VIDEO"
    $audioVar = "DEVICE${i}_VIDEO_AUDIO"
    $captureVar = "DEVICE${i}_VIDEO_CAPTURE_PATH"
    $fpsVar = "DEVICE${i}_VIDEO_FPS"

    $videoSource = Get-Item -Path "env:$videoVar" -ErrorAction SilentlyContinue
    if ($videoSource) {
        $audioDevice = Get-Item -Path "env:$audioVar" -ErrorAction SilentlyContinue
        $capturePath = Get-Item -Path "env:$captureVar" -ErrorAction SilentlyContinue
        $fps = Get-Item -Path "env:$fpsVar" -ErrorAction SilentlyContinue

        # An empty FPS reaches Start-Process -ArgumentList as an empty string and
        # PowerShell rejects it ("Cannot validate argument on parameter
        # 'ArgumentList'. The argument is null or empty.") before ffmpeg ever
        # starts, leaving the previous playlist on disk (frozen / ENDLIST) which
        # the dashboard renders as a black tile that keeps reloading. Default it
        # instead of dying. See BUG-0601.
        $fpsValue = if ($fps -and $fps.Value) { $fps.Value } else { "5" }
        if (-not ($fps -and $fps.Value)) {
            Write-Host "WARNING: $fpsVar is not set - defaulting to $fpsValue fps (add $fpsVar=5 to .env)"
        }

        $grabbers["device$i"] = "$($videoSource.Value)|$($audioDevice.Value)|$($capturePath.Value)|$fpsValue"
    }
}

if ($grabbers.Count -eq 0) {
    Write-Error "No devices configured in .env file"
    exit 1
}

Write-Host "Found $($grabbers.Count) device(s) configured"

# Determine active_captures.conf location (stream base)
if ($env:STREAM_BASE_PATH) {
    $script:ACTIVE_CAPTURES_FILE = Join-Path $env:STREAM_BASE_PATH "active_captures.conf"
} elseif ($env:HOST_VIDEO_CAPTURE_PATH) {
    $script:ACTIVE_CAPTURES_FILE = Join-Path (Split-Path -Parent $env:HOST_VIDEO_CAPTURE_PATH) "active_captures.conf"
} else {
    # Fallback to first configured capture path
    $first = $grabbers.Values | Select-Object -First 1
    if ($first) {
        $firstCapture = ($first -split '\|')[2]
        if ($firstCapture) {
            $script:ACTIVE_CAPTURES_FILE = Join-Path (Split-Path -Parent $firstCapture) "active_captures.conf"
        }
    }
}

if (-not $script:ACTIVE_CAPTURES_FILE) {
    $script:ACTIVE_CAPTURES_FILE = "C:\\virtualpytest\\stream\\active_captures.conf"
}

# Ensure active_captures.conf directory exists
try {
    $activeDir = Split-Path -Parent $script:ACTIVE_CAPTURES_FILE
    if ($activeDir -and -not (Test-Path $activeDir)) {
        New-Item -ItemType Directory -Path $activeDir -Force | Out-Null
    }
} catch { }

# Linux parity: clean file only when starting all devices
if ($TargetDevice -eq "all") {
    try { if (Test-Path $script:ACTIVE_CAPTURES_FILE) { Remove-Item -Force $script:ACTIVE_CAPTURES_FILE -ErrorAction SilentlyContinue } } catch { }
    try {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($script:ACTIVE_CAPTURES_FILE, "", $utf8NoBom)
    } catch { }
}

function Update-ActiveCaptures {
    param(
        [string]$CaptureDir,
        [string]$ProcessId,
        [string]$Quality
    )

    $confFile = $script:ACTIVE_CAPTURES_FILE
    $tempFile = "${confFile}.tmp.$PID"
    $normalizedCaptureDir = $CaptureDir.TrimEnd('\','/')

    try {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        $writer = New-Object System.IO.StreamWriter($tempFile, $false, $utf8NoBom)

        # Copy over all lines except this capture dir
        if (Test-Path $confFile) {
            foreach ($line in Get-Content $confFile) {
                if ($line -and ($line -notmatch "^$([regex]::Escape($normalizedCaptureDir)),")) {
                    $writer.WriteLine($line)
                }
            }
        }

        # Add new entry (CSV)
        $writer.WriteLine("$normalizedCaptureDir,$ProcessId,$Quality")
        $writer.Close()

        # Atomic replace
        Move-Item -Force -Path $tempFile -Destination $confFile
    } catch {
        Write-Host "Failed to update active_captures.conf: $($_.Exception.Message)"
        try { if (Test-Path $tempFile) { Remove-Item -Force $tempFile -ErrorAction SilentlyContinue } } catch { }
    }
}

# Function to detect source type
function Get-SourceType {
    param([string]$source)

    if ($source -match '^/dev/video\d+$') {
        return "v4l2"
    } elseif ($source -match '^:\d+$' -or $source -match '^(desktop|gdigrab)$') {
        return "x11grab"
    } elseif ($source -match '\.(png|jpg|jpeg)$') {
        # Image file source (Android emulator PNG frames updated by vpt-emulator-fifo).
        # Mirrors the imagefile branch in run_ffmpeg.sh — the source file is rewritten
        # by another process (emulator_screencap.ps1) and ffmpeg reads it as a stream.
        return "imagefile"
    } else {
        return "unknown"
    }
}

function Wait-ImageDims {
    # Mirrors the identify-based wait loop in run_ffmpeg.sh:1701-1717. Reads the first 24
    # bytes (PNG IHDR is at byte 16 with width/height as 4-byte big-endian) to detect
    # orientation. Returns "<width> <height>" or null.
    param([string]$Path)
    $wait = 0
    while ($wait -le 60) {
        try {
            if (Test-Path $Path) {
                $bytes = [System.IO.File]::ReadAllBytes($Path)
                if ($bytes.Length -ge 24 -and $bytes[0] -eq 0x89 -and $bytes[1] -eq 0x50 -and $bytes[2] -eq 0x4E -and $bytes[3] -eq 0x47) {
                    $w = ($bytes[16] -shl 24) -bor ($bytes[17] -shl 16) -bor ($bytes[18] -shl 8) -bor $bytes[19]
                    $h = ($bytes[20] -shl 24) -bor ($bytes[21] -shl 16) -bor ($bytes[22] -shl 8) -bor $bytes[23]
                    if ($w -gt 0 -and $h -gt 0) { return "$w $h" }
                }
            }
        } catch { }
        Start-Sleep -Seconds 2
        $wait++
    }
    return "1920 1080"   # default landscape
}

function Reset-LogIfLarge {
    # Parity with run_ffmpeg.sh reset_log_if_large — prevents ffmpeg stderr log from growing unbounded.
    param(
        [string]$LogFile,
        [int]$MaxSizeMB = 30
    )
    if (-not (Test-Path $LogFile)) { return }
    try {
        $sizeMB = (Get-Item $LogFile -ErrorAction Stop).Length / 1MB
        if ($sizeMB -ge $MaxSizeMB) {
            Set-Content -Path $LogFile -Value $null -ErrorAction SilentlyContinue
        }
    } catch { }
}

function Clear-StaleFFmpeg {
    # Parity with the stale-ffmpeg sweep at run_ffmpeg.sh:701-721. Kills leftover ffmpeg.exe
    # processes whose command line references a capture dir we're about to claim.
    param([string[]]$CaptureDirs)
    if ($null -eq $CaptureDirs -or $CaptureDirs.Count -eq 0) { return }

    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='ffmpeg.exe'" -ErrorAction Stop
    } catch {
        return
    }

    foreach ($p in $procs) {
        $cmd = [string]$p.CommandLine
        if ([string]::IsNullOrEmpty($cmd)) { continue }
        foreach ($dir in $CaptureDirs) {
            if ([string]::IsNullOrWhiteSpace($dir)) { continue }
            if ($cmd -like "*$dir*") {
                Write-Host "Killing stale ffmpeg PID $($p.ProcessId) for $dir"
                try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch { }
                break
            }
        }
    }
}

function Get-DesktopResolution {
    # Try multiple methods; service sessions can be weird. Fall back to 1280x720.
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        if ($b.Width -gt 0 -and $b.Height -gt 0) {
            return "$($b.Width)x$($b.Height)"
        }
    } catch { }

    try {
        $vc = Get-CimInstance Win32_VideoController -ErrorAction Stop | Select-Object -First 1
        if ($vc.CurrentHorizontalResolution -and $vc.CurrentVerticalResolution) {
            return "$($vc.CurrentHorizontalResolution)x$($vc.CurrentVerticalResolution)"
        }
    } catch { }

    return "1280x720"
}

# Function to start FFmpeg grabber
function Start-Grabber {
    param(
        [string]$source,
        [string]$audioDevice,
        [string]$captureDir,
        [string]$index,
        [string]$inputFps,
        [string]$quality = "sd"
    )

    $sourceType = Get-SourceType $source

    if ($sourceType -eq "unknown") {
        Write-Error "Unknown source type for $source"
        return
    }

    # Storage paths (direct to capture directory â€” no hot/cold split on Windows)
    $outputSegments = Join-Path $captureDir "segments"
    $outputCaptures = Join-Path $captureDir "captures"
    $outputThumbnails = Join-Path $captureDir "thumbnails"

    # Ensure directories exist
    @($outputSegments, $outputCaptures, $outputThumbnails) | ForEach-Object {
        if (-not (Test-Path $_)) {
            New-Item -ItemType Directory -Path $_ -Force | Out-Null
        }
    }

    # Build FFmpeg argument list based on source type and quality.
    # IMPORTANT: Use an argument array (not a giant string) so PowerShell doesn't mis-parse
    # tokens like -map or filtergraph labels like [streamout].
    $ffmpegArgs = @()

    if ($sourceType -eq "x11grab") {
        # VNC display capture
        $resolution = Get-DesktopResolution

        if ($quality -eq "hd") {
            $streamScale = "1280:720"
            $streamBitrate = "1000k"
            $captureScale = "1280:720"
        } elseif ($quality -eq "sd") {
            $streamScale = "640:360"
            $streamBitrate = "350k"
            $captureScale = "1280:720"
        } else {
            $streamScale = "320:180"
            $streamBitrate = "120k"
            $captureScale = "1280:720"
        }

        $bufsizeK = [int](($streamBitrate -replace 'k','')) * 2
        $filter = "[0:v]fps=2[v2];[v2]split=3[str][cap][thm];" +
                  "[str]scale=${streamScale}:flags=neighbor[streamout];" +
                  "[cap]scale=${captureScale}:flags=neighbor,setpts=PTS-STARTPTS[captureout];" +
                  "[thm]scale=320:180:flags=neighbor[thumbout]"

        $ffmpegArgs = @(
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-f", "gdigrab",
            "-video_size", $resolution,
            "-framerate", $inputFps,
            "-i", "desktop",
            "-filter_complex", $filter,
                        "-g", "8",
                        "-keyint_min", "8",
                        "-sc_threshold", "0",
            "-map", "[streamout]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-b:v", $streamBitrate,
            "-maxrate", $streamBitrate,
            "-bufsize", "${bufsizeK}k",
            "-pix_fmt", "yuv420p",
            "-profile:v", "baseline",
            "-level", "3.0",
            "-f", "hls",
            "-hls_time", "4",
            "-hls_list_size", "40",
            "-hls_flags", "delete_segments+omit_endlist+split_by_time",
            "-hls_segment_filename", (Join-Path $outputSegments "segment_%09d.ts"),
            (Join-Path $outputSegments "output.m3u8"),
            "-map", "[captureout]",
            "-fps_mode", "passthrough",
            "-c:v", "mjpeg",
            "-q:v", "10",
            "-f", "image2",
            "-atomic_writing", "1",
            (Join-Path $outputCaptures "capture_%09d.jpg"),
            "-map", "[thumbout]",
            "-fps_mode", "passthrough",
            "-c:v", "mjpeg",
            "-q:v", "10",
            "-f", "image2",
            "-atomic_writing", "1",
            (Join-Path $outputThumbnails "capture_%09d_thumbnail.jpg")
        )
    } elseif ($sourceType -eq "v4l2") {
        # Camera capture (Windows DirectShow)
        if ($quality -eq "hd") {
            $streamScale = "1280:720"
            $streamBitrate = "1500k"
            $captureScale = "1280:720"
        } elseif ($quality -eq "sd") {
            $streamScale = "640:360"
            $streamBitrate = "350k"
            $captureScale = "1280:720"
        } else {
            $streamScale = "320:180"
            $streamBitrate = "150k"
            $captureScale = "1280:720"
        }

        $maxrateK = [int](($streamBitrate -replace 'k','') * 1.2)
        $bufsizeK = [int](($streamBitrate -replace 'k','')) * 2
        $filter = "[0:v]split=3[str][cap][thm];" +
                  "[str]scale=${streamScale}:flags=fast_bilinear[streamout];" +
                  "[cap]fps=5,scale=${captureScale}:flags=fast_bilinear,setpts=PTS-STARTPTS[captureout];" +
                  "[thm]fps=5,scale=320:180:flags=neighbor[thumbout]"

        $dshowInput = "video=$source"
        if ($audioDevice -and $audioDevice -ne "null") {
            $dshowInput = "${dshowInput}:audio=$audioDevice"
        }

        $ffmpegArgs = @(
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-fflags", "+nobuffer+genpts+flush_packets",
            "-use_wallclock_as_timestamps", "1",
            "-thread_queue_size", "512",
            "-f", "dshow",
            "-video_size", "1280x720",
            "-framerate", $inputFps,
            "-i", $dshowInput,
            "-filter_complex", $filter,
            "-map", "[streamout]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-b:v", $streamBitrate,
            "-maxrate", "${maxrateK}k",
            "-bufsize", "${bufsizeK}k",
            "-x264opts", "keyint=10:min-keyint=10:no-scenecut:bframes=0",
            "-pix_fmt", "yuv420p",
            "-profile:v", "baseline",
            "-level", "3.0",
            "-c:a", "aac",
            "-b:a", "32k",
            "-ar", "48000",
            "-ac", "2",
            "-f", "hls",
            "-hls_time", "1",
            "-hls_list_size", "150",
            "-hls_flags", "delete_segments+omit_endlist+split_by_time",
            "-lhls", "1",
            "-hls_segment_filename", (Join-Path $outputSegments "segment_%09d.ts"),
            (Join-Path $outputSegments "output.m3u8"),
            "-map", "[captureout]",
            "-fps_mode", "passthrough",
            "-c:v", "mjpeg",
            "-q:v", "8",
            "-f", "image2",
            "-atomic_writing", "1",
            (Join-Path $outputCaptures "capture_%09d.jpg"),
            "-map", "[thumbout]",
            "-fps_mode", "passthrough",
            "-c:v", "mjpeg",
            "-q:v", "8",
            "-f", "image2",
            "-atomic_writing", "1",
            (Join-Path $outputThumbnails "capture_%09d_thumbnail.jpg")
        )
    } elseif ($sourceType -eq "imagefile") {
        # Image file source (Android emulator PNG frames updated by vpt-emulator-fifo).
        # Port of run_ffmpeg.sh:1696-1829. The frames are stamped with the wall clock
        # so audio + video share a clock; the stream output is resampled to a constant
        # fps via `-r` because image2pipe delivers VFR by default.
        $dims = Wait-ImageDims $source
        $imgW, $imgH = $dims -split ' '
        $orientation = "landscape"
        if ([int]$imgH -gt [int]$imgW) { $orientation = "portrait" }

        if ($orientation -eq "portrait") {
            $thumbScale = "180:320"
            if ($quality -eq "hd")      { $streamScale = "720:1280"; $streamBitrate = "750k" }
            elseif ($quality -eq "sd")  { $streamScale = "360:640";  $streamBitrate = "175k" }
            else                         { $streamScale = "180:320";  $streamBitrate = "60k"  }
        } else {
            $thumbScale = "320:180"
            if ($quality -eq "hd")      { $streamScale = "1280:720"; $streamBitrate = "750k" }
            elseif ($quality -eq "sd")  { $streamScale = "640:360";  $streamBitrate = "175k" }
            else                         { $streamScale = "320:180";  $streamBitrate = "60k"  }
        }
        $streamGop = [int]([math]::Floor([int]$inputFps * 4 / 5))
        $bufsizeK  = [int](($streamBitrate -replace 'k','')) * 2

        # Wall-clock the video so audio can be interleaved cleanly (parity with BUG-0169).
        # Split into 3 outputs: stream, capture (mjpeg), thumbnail (mjpeg).
        $filter = "[0:v]settb=AVTB,setpts=RTCTIME-RTCSTART,split=3[str][cap][thm];" +
                  "[str]scale=${streamScale}[streamout];" +
                  "[cap]setpts=PTS-STARTPTS[captureout];" +
                  "[thm]scale=${thumbScale}[thumbout]"

        # Read the PNG file via image2 demuxer with -loop 1. ffmpeg reads the file
        # once and loops that frame, which is the right behaviour for a *static*
        # screenshot path. The emulator_screencap.ps1 loop is the live source —
        # ffmpeg just provides HLS packaging + capture/thumbnail fanout. Parity
        # with the labox-mobile imagefile path (run_ffmpeg.sh:1696-1829) where
        # the bash version pipes `cat | ffmpeg -f image2pipe`; on Windows the
        # cat-loop equivalent needs a background stdin writer, which is harder to
        # keep alive across Task Scheduler restarts. -loop 1 is the pragmatic
        # trade-off: stream runs continuously, content is the most recent frame
        # the screencap wrote (faster than the next-restart cycle of -i -).
        $ffmpegArgs = @(
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-fflags", "+flush_packets",
            "-threads", "1",
            "-f", "image2",
            "-loop", "1",
            "-framerate", $inputFps,
            "-i", $source,
            "-filter_complex", $filter,
            "-map", "[streamout]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-r", $inputFps,
            "-g", $streamGop,
            "-keyint_min", $streamGop,
            "-x264opts", "no-scenecut:bframes=0",
            "-b:v", $streamBitrate,
            "-maxrate", $streamBitrate,
            "-bufsize", "${bufsizeK}k",
            "-pix_fmt", "yuv420p",
            "-f", "hls",
            "-hls_time", "0.8",
            "-hls_list_size", "375",
            "-hls_delete_threshold", "375",
            "-hls_flags", "delete_segments+program_date_time",
            "-hls_segment_filename", (Join-Path $outputSegments "segment_%09d.ts"),
            (Join-Path $outputSegments "output.m3u8"),
            "-map", "[captureout]",
            "-fps_mode", "passthrough",
            "-enc_time_base", "1:1000",
            "-c:v", "mjpeg",
            "-q:v", "8",
            "-f", "image2",
            "-atomic_writing", "1",
            (Join-Path $outputCaptures "capture_%09d.jpg"),
            "-map", "[thumbout]",
            "-fps_mode", "passthrough",
            "-enc_time_base", "1:1000",
            "-c:v", "mjpeg",
            "-q:v", "8",
            "-f", "image2",
            "-atomic_writing", "1",
            (Join-Path $outputThumbnails "capture_%09d_thumbnail.jpg")
        )
    }

    if ($ffmpegArgs.Count -gt 0) {
        Write-Host "Starting $index with quality $quality"

        # Capture ffmpeg stderr to a per-device log (parity with /tmp/ffmpeg_output_<index>.log on Linux).
        # Rotation keeps it bounded; -loglevel error above already silences "failed to delete old segment".
        $logFile = Join-Path $env:TEMP "ffmpeg_output_$index.log"
        Reset-LogIfLarge -LogFile $logFile

        # Start FFmpeg process
        $process = Start-Process -FilePath "ffmpeg" -ArgumentList $ffmpegArgs -NoNewWindow -PassThru -RedirectStandardError $logFile
        $script:FFMPEG_PIDS += $process.Id

        # Update active captures file (CSV: path,PID,quality)
        Update-ActiveCaptures -CaptureDir $captureDir -ProcessId $process.Id -Quality $quality
        Write-Host "Wrote active_captures.conf entry: $captureDir,$($process.Id),$quality -> $script:ACTIVE_CAPTURES_FILE"

        $script:DEVICE_STATE[$index] = @{
            Source = $source
            AudioDevice = $audioDevice
            CaptureDir = $captureDir
            InputFps = $inputFps
            Quality = $quality
            PID = $process.Id
            LastRestartEpoch = Get-NowEpoch
        }

        Write-Host "Started $index (PID: $($process.Id))"
    }
}

function Get-LatestCaptureAgeSeconds {
    param([string]$CaptureDir)

    $hotCaptures = Join-Path $CaptureDir "hot\captures"
    $coldCaptures = Join-Path $CaptureDir "captures"
    $capturesDir = $null

    if (Test-Path $hotCaptures) {
        $capturesDir = $hotCaptures
    } elseif (Test-Path $coldCaptures) {
        $capturesDir = $coldCaptures
    } else {
        return $null
    }

    $latest = Get-ChildItem -Path $capturesDir -Filter "capture_*.jpg" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1

    if ($null -eq $latest) { return $null }

    $age = ([DateTime]::UtcNow - $latest.LastWriteTimeUtc).TotalSeconds
    return [int][Math]::Floor($age)
}

function Restart-StalledGrabbers {
    $now = Get-NowEpoch

    foreach ($device in @($script:DEVICE_STATE.Keys)) {
        $state = $script:DEVICE_STATE[$device]
        if ($null -eq $state) { continue }

        $captureDir = [string]$state.CaptureDir
        $age = Get-LatestCaptureAgeSeconds -CaptureDir $captureDir
        if ($null -eq $age) { continue }
        if ($age -lt $script:STALL_TIMEOUT_SECONDS) { continue }

        $lastRestart = [int64]$state.LastRestartEpoch
        if (($now - $lastRestart) -lt $script:STALL_RESTART_COOLDOWN_SECONDS) { continue }

        # BUG-0593: `$pid` is PowerShell's read-only automatic variable (the
        # current process's PID). Reassigning it is a runtime error. Use
        # `$devicePid` (or any non-reserved name) instead.
        $devicePid = [int]$state.PID
        Write-Host "Stall detected: $device has no new frames for ${age}s (timeout=$($script:STALL_TIMEOUT_SECONDS)s). Restarting ffmpeg..."

        try {
            Stop-Process -Id $devicePid -Force -ErrorAction SilentlyContinue
        } catch { }

        $script:FFMPEG_PIDS = @($script:FFMPEG_PIDS | Where-Object { $_ -ne $devicePid })

        Start-Grabber -source ([string]$state.Source) `
            -audioDevice ([string]$state.AudioDevice) `
            -captureDir $captureDir `
            -index $device `
            -inputFps ([string]$state.InputFps) `
            -quality ([string]$state.Quality)
    }
}

function Check-QualityChanges {
    # Parity with run_ffmpeg.sh check_quality_changes(): watch active_captures.conf
    # for a quality field that differs from what a device is actually running, and
    # restart that device's ffmpeg with the new quality. This is what makes the
    # frontend "Restart streams" button take effect on Windows.
    $confFile = $script:ACTIVE_CAPTURES_FILE
    if (-not $confFile -or -not (Test-Path $confFile)) { return }

    $lines = @()
    try {
        $lines = Get-Content $confFile -ErrorAction Stop
    } catch {
        return
    }

    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $parts = $line -split ','
        if ($parts.Count -lt 3) { continue }

        $confCaptureDir = $parts[0].Trim()
        $configQuality = $parts[2].Trim()
        if ([string]::IsNullOrWhiteSpace($confCaptureDir) -or [string]::IsNullOrWhiteSpace($configQuality)) { continue }

        $normConf = $confCaptureDir.TrimEnd('\', '/')

        foreach ($device in @($script:DEVICE_STATE.Keys)) {
            $state = $script:DEVICE_STATE[$device]
            if ($null -eq $state) { continue }

            $normState = ([string]$state.CaptureDir).TrimEnd('\', '/')
            if ($normState -ne $normConf) { continue }

            $runningQuality = [string]$state.Quality
            if ($configQuality -eq $runningQuality) { break }

            Write-Host "Quality change detected: $device ($runningQuality -> $configQuality). Restarting ffmpeg..."

            $oldPid = [int]$state.PID
            try { Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue } catch { }
            $script:FFMPEG_PIDS = @($script:FFMPEG_PIDS | Where-Object { $_ -ne $oldPid })

            # Mirror run_ffmpeg.sh: clean up any leftover ffmpeg for this dir, then
            # pause before restart so the device handle is released.
            Clear-StaleFFmpeg -CaptureDirs @($normState)
            Start-Sleep -Seconds 2

            Start-Grabber -source ([string]$state.Source) `
                -audioDevice ([string]$state.AudioDevice) `
                -captureDir ([string]$state.CaptureDir) `
                -index $device `
                -inputFps ([string]$state.InputFps) `
                -quality $configQuality
            break
        }
    }
}

# Kill any stale ffmpeg.exe processes from previous runs that still reference our capture dirs
# (mirrors the sweep at run_ffmpeg.sh:701-721 — prevents PID collisions and orphan writers).
$staleTargets = @()
foreach ($device in $grabbers.Keys) {
    if ($TargetDevice -eq "all" -or $TargetDevice -eq $device) {
        $dir = ($grabbers[$device] -split '\|')[2]
        if ($dir) { $staleTargets += $dir.TrimEnd('\','/') }
    }
}
Clear-StaleFFmpeg -CaptureDirs $staleTargets

# Process all devices
foreach ($device in $grabbers.Keys) {
    $config = $grabbers[$device] -split '\|'
    $source = $config[0]
    $audioDevice = $config[1]
    $captureDir = $config[2]
    $fps = $config[3]

    if ($TargetDevice -eq "all" -or $TargetDevice -eq $device) {
        Start-Grabber -source $source -audioDevice $audioDevice -captureDir $captureDir -index $device -inputFps $fps -quality $Quality
    }
}

Write-Host "All grabbers started"

# Keep script running and restart ffmpeg in-place if it dies.
# Old behaviour (BUG-0592) was `exit 1` on death, expecting Task Scheduler to
# restart the wrapper. Two problems with that: (a) Task Scheduler auto-disables
# a task after enough RestartOnFailure iterations, and the atomic-rename
# race between the emulator_screencap.ps1 loop and ffmpeg's image2 demuxer
# keeps killing ffmpeg, so the task ended up Disabled every time. (b) Even
# when the task survived, the cold-start re-running run_ffmpeg.ps1 has to
# re-import the env, re-allocate the ffmpeg log file, and re-create every
# HLS playlist — a 5-10 s gap with no segments. Restart in-place and the
# ffmpeg pipeline keeps rolling; a `RestartOnFailure` is reserved for the
# "wrapper itself died" case (host crash, OOM, etc.).
$script:DEATH_RESTART_COOLDOWN_SECONDS = 5
$lastDeathRestart = [int64]0
while ($true) {
    Restart-StalledGrabbers
    Check-QualityChanges

    $nowEpoch = Get-NowEpoch
    foreach ($device in @($script:DEVICE_STATE.Keys)) {
        $state = $script:DEVICE_STATE[$device]
        if ($null -eq $state) { continue }
        # BUG-0593: `$pid` is PowerShell's read-only automatic variable (the
        # current process's PID). Reassigning it errors out with
        # "Impossible de remplacer la variable PID, car elle est constante
        # ou en lecture seule", which crashes the wrapper at the first
        # iteration of this loop. Use `$devicePid` (or any non-reserved name)
        # instead. Same for the other loop below.
        $devicePid = [int]$state.PID
        if ($devicePid -le 0) { continue }

        $isAlive = $true
        try {
            $p = Get-Process -Id $devicePid -ErrorAction Stop
            if ($p.HasExited) { $isAlive = $false }
        } catch {
            $isAlive = $false
        }
        if ($isAlive) { continue }

        # ffmpeg for this device is gone. Restart in place, with a cooldown
        # so a flapping source (e.g. a half-written latest.png the screencap
        # loop is mid-rename on) doesn't hot-loop the restarter.
        if (($nowEpoch - $lastDeathRestart) -lt $script:DEATH_RESTART_COOLDOWN_SECONDS) { continue }
        $lastDeathRestart = $nowEpoch
        Write-Host "ffmpeg for $device (PID $devicePid) exited; restarting in-place."

        $script:FFMPEG_PIDS = @($script:FFMPEG_PIDS | Where-Object { $_ -ne $devicePid })

        # Clear any leftover ffmpeg for this capture dir (mirrors the stall
        # path), pause briefly so the device handle is released, then start.
        $captureDir = [string]$state.CaptureDir
        Clear-StaleFFmpeg -CaptureDirs @($captureDir.TrimEnd('\', '/'))
        Start-Sleep -Seconds 2

        try {
            Start-Grabber -source ([string]$state.Source) `
                -audioDevice ([string]$state.AudioDevice) `
                -captureDir $captureDir `
                -index $device `
                -inputFps ([string]$state.InputFps) `
                -quality ([string]$state.Quality)
        } catch {
            Write-Host "Restart of $device failed: $_"
        }
    }

    Start-Sleep -Seconds 1
}
