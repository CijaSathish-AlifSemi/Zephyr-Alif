# Launcher for the Alif Zephyr installer (Windows).
#
# A first-time machine may have no usable Python, so this script only:
#   1. downloads the pinned portable Python (from the manifest) into a cache,
#   2. checks its sha256,
#   3. runs alif_setup.py with that Python.
# Everything else (git, cmake, ninja, compiler, SDK) is done by alif_setup.py.
#
# Usage: alif-setup install | verify | uninstall   [options]   (see --help)
# Start it through alif-setup.bat (from cmd.exe or PowerShell).

$ErrorActionPreference = 'Stop'
$here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$cache = Join-Path $env:LOCALAPPDATA 'alif-zephyr-setup'

function Fail($msg) {
    [Console]::Error.WriteLine("ERROR: $msg")
    exit 1
}

# --- platform -------------------------------------------------------------
if (-not [Environment]::Is64BitOperatingSystem) {
    Fail 'only 64-bit Windows is supported in this version.'
}

# --- which manifest -------------------------------------------------------
$manifest = $null
for ($i = 0; $i -lt $args.Count; $i++) {
    if ($args[$i] -eq '--manifest' -and ($i + 1) -lt $args.Count) { $manifest = $args[$i + 1] }
    elseif ($args[$i] -like '--manifest=*') { $manifest = $args[$i].Substring('--manifest='.Length) }
}
if (-not $manifest) {
    $found = Get-ChildItem -Path (Join-Path $here 'manifests') -Filter 'v*.json' -ErrorAction SilentlyContinue |
        Sort-Object { try { [version]($_.BaseName.TrimStart('v')) } catch { [version]'0.0' } } |
        Select-Object -Last 1
    if (-not $found) { Fail "no manifest found in $here\manifests" }
    $manifest = $found.FullName
}
if (-not (Test-Path $manifest)) { Fail "manifest not found: $manifest" }

$m = Get-Content -Raw -Encoding UTF8 $manifest | ConvertFrom-Json
$plat = $m.platforms.'windows-x86_64'
if (-not $plat) { Fail "$manifest has no 'windows-x86_64' section." }
$pyUrl = $plat.tools.python.url
$pySha = $plat.tools.python.sha256.ToLower()
if (-not $pyUrl -or -not $pySha) { Fail "could not read the python url/sha256 from $manifest" }

# --- bootstrap Python -----------------------------------------------------
$pyDir = Join-Path $cache ('bootstrap-python-' + $pySha.Substring(0, 12))
$pyExe = Join-Path $pyDir 'python.exe'
if (-not (Test-Path $pyExe)) {
    $dl = Join-Path $cache 'downloads'
    New-Item -ItemType Directory -Force -Path $dl | Out-Null
    $name = [System.Uri]::UnescapeDataString((Split-Path -Leaf ([Uri]$pyUrl).AbsolutePath))
    $file = Join-Path $dl $name

    $ok = (Test-Path $file) -and ((Get-FileHash -Algorithm SHA256 $file).Hash.ToLower() -eq $pySha)
    if (-not $ok) {
        Write-Host 'Downloading portable Python (one time, about 45 MB)...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $pyUrl -OutFile "$file.part"
        } catch {
            Fail "download failed: $pyUrl`n  $($_.Exception.Message)`n  Check your internet connection / proxy and try again."
        }
        Move-Item -Force "$file.part" $file
        if ((Get-FileHash -Algorithm SHA256 $file).Hash.ToLower() -ne $pySha) {
            Remove-Item -Force $file
            Fail "checksum mismatch for $file (deleted it; please run again)."
        }
    }

    # Use the tar.exe that ships with Windows 10 (1803 and newer), not one from PATH.
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (-not (Test-Path $tar)) {
        Fail "tar.exe not found. It is part of Windows 10 version 1803 and newer; please update Windows."
    }
    $tmp = "$pyDir.tmp"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    & $tar -xzf $file -C $tmp --strip-components=1
    if ($LASTEXITCODE -ne 0) { Fail "could not unpack $file" }
    if (Test-Path $pyDir) { Remove-Item -Recurse -Force $pyDir }
    Move-Item $tmp $pyDir
}

& $pyExe -I (Join-Path $here 'alif_setup.py') @args
exit $LASTEXITCODE
