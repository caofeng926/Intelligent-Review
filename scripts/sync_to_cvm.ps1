# scripts/sync_to_cvm.ps1
# Sync webapp/ from local to the medical-audit CVM, then restart the service.
#
# Run from project root (or anywhere; uses $PSScriptRoot):
#     .\scripts\sync_to_cvm.ps1
#     .\scripts\sync_to_cvm.ps1 -SkipDb            # only small files
#     .\scripts\sync_to_cvm.ps1 -HealthcheckUrl http://127.0.0.1:5000/
#
# Requires: python on PATH with `paramiko` installed (pip install paramiko).
#
[CmdletBinding()]
param(
    [switch] $SkipDb = $false,
    [string] $HealthcheckUrl = "http://127.0.0.1:5000/",
    [string] $SshHost = "132.232.152.250",
    [int]    $SshPort = 22,
    [string] $SshUser = "root",
    [string] $SshPass = $env:MA_SSH_PASS
if (-not $SshPass) { Write-Error "MA_SSH_PASS env var required (set it before running)"; exit 1 }
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "Continue"

# Resolve paths relative to this script so it works from any cwd.
$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$webappDir   = Join-Path $projectRoot "webapp"

if (-not (Test-Path $webappDir)) {
    throw "webapp/ not found at $webappDir"
}

$remoteWebapp = "/opt/medical-audit/webapp"
$remoteDb     = "$remoteWebapp/data/kp.db"
$helper       = Join-Path $scriptDir "_ssh.py"

if (-not (Test-Path $helper)) {
    throw "Helper not found: $helper"
}

# Push SSH creds to the python helper via env vars (no shell history leak).
$env:MA_SSH_HOST = $SshHost
$env:MA_SSH_PORT = "$SshPort"
$env:MA_SSH_USER = $SshUser
$env:MA_SSH_PASS = $SshPass

function Invoke-SshHelper {
    param([Parameter(ValueFromRemainingArguments=$true)]$Args)
    Write-Host ">> python -X utf8 $helper $($Args -join ' ')"
    & python -X utf8 $helper @Args
    if ($LASTEXITCODE -ne 0) {
        throw "_ssh.py exited with code $LASTEXITCODE"
    }
}

function Push-Path {
    param([string]$Local, [string]$Remote)
    if (-not (Test-Path $Local)) {
        Write-Warning "[skip] missing local path: $Local"
        return
    }
    Invoke-SshHelper upload $Local $Remote
}

Write-Host "============================================================"
Write-Host " medical-audit sync to CVM"
Write-Host "   host:    $SshHost`:$SshPort"
Write-Host "   target:  $remoteWebapp"
Write-Host "   skip db: $SkipDb"
Write-Host "============================================================"

# 1. Back up the remote DB first so we always have a rollback target.
Write-Host "`n[1/5] Backing up remote DB (if present)..."
Invoke-SshHelper backup $remoteDb

# 2. Upload small source files first so a DB failure does not strand the app.
Write-Host "`n[2/5] Uploading small webapp files..."
$smallFiles = @(
    "app.py",
    "admin.py",
    "db.py",
    "search.py",
    "nhsa_api.py",
    "nhsa_browse.py",
    "qa.py",
    "yp2023.py",
    "ingest_yp_2023.py",
    "requirements.txt"
)
foreach ($name in $smallFiles) {
    $localPath = Join-Path $webappDir $name
    $remotePath = "$remoteWebapp/$name"
    Push-Path -Local $localPath -Remote $remotePath
}

# 3. Upload templates/ and static/ as directory trees.
Write-Host "`n[3/5] Uploading templates/ and static/..."
foreach ($dir in @("templates", "static")) {
    $localPath = Join-Path $webappDir $dir
    $remotePath = "$remoteWebapp/$dir"
    Push-Path -Local $localPath -Remote $remotePath
}

# 4. Upload kp.db (large) unless -SkipDb.
if (-not $SkipDb) {
    $localDb = Join-Path $webappDir "data\kp.db"
    if (Test-Path $localDb) {
        Write-Host "`n[4/5] Uploading kp.db (this can take 5-15 minutes)..."
        $sizeBytes = (Get-Item $localDb).Length
        Write-Host ("   local size: {0:N1} MB" -f ($sizeBytes / 1MB))
        Push-Path -Local $localDb -Remote $remoteDb
    } else {
        Write-Warning "[skip] local kp.db not found at $localDb"
    }
} else {
    Write-Host "`n[4/5] Skipping kp.db upload (-SkipDb)"
}

# 5. Restart service and healthcheck.
Write-Host "`n[5/5] Restarting medical-audit.service..."
Invoke-SshHelper exec "systemctl restart medical-audit.service && sleep 3 && systemctl is-active medical-audit.service"

Write-Host "`n[health:local] Waiting for $HealthcheckUrl to return 200 (local view)..."
Invoke-SshHelper healthcheck $HealthcheckUrl

Write-Host "`n[health:cvm] Re-checking $HealthcheckUrl from inside the CVM (catches gunicorn-boot failures that local view misses)..."
Invoke-SshHelper healthcheck-remote $HealthcheckUrl

Write-Host "`n[done] Sync complete."