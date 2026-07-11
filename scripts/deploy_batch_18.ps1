# scripts/deploy_batch_18.ps1
# Deploy 18th batch (药品限适应症-神经系统药物) to medical-audit CVM.
# Uploads: webapp/ingest_xlsx.py + webapp/data/kp.db, then restarts service.
#
# Run from project root:
#     $env:MA_SSH_PASS = "<password>"
#     .\scripts\deploy_batch_18.ps1
#
[CmdletBinding()]
param(
    [string] $SshHost   = "132.232.152.250",
    [int]    $SshPort   = 2222,
    [string] $SshUser   = "ubuntu",
    [string] $SshPass   = $env:MA_SSH_PASS,
    [string] $RemoteDir = "/opt/medical-audit/webapp",
    [string] $HealthcheckUrl = "http://127.0.0.1:5000/"
)

if (-not $SshPass) { Write-Error "MA_SSH_PASS env var required"; exit 1 }

$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$webappDir   = Join-Path $projectRoot "webapp"
$helper      = Join-Path $scriptDir "_ssh.py"

if (-not (Test-Path $helper)) { throw "_ssh.py not found at $helper" }

$env:MA_SSH_HOST = $SshHost
$env:MA_SSH_PORT = "$SshPort"
$env:MA_SSH_USER = $SshUser
$env:MA_SSH_PASS = $SshPass

function Invoke-SshHelper {
    param([Parameter(ValueFromRemainingArguments=$true)]$Args)
    Write-Host ">> python -X utf8 $helper $($Args -join ' ')"
    & python -X utf8 $helper @Args
    if ($LASTEXITCODE -ne 0) { throw "_ssh.py exited $LASTEXITCODE" }
}

Write-Host "============================================================"
Write-Host " Deploy batch 18 -> ${SshUser}@${SshHost}:${SshPort}"
Write-Host "   target:   $RemoteDir"
Write-Host "   healthck: $HealthcheckUrl"
Write-Host "============================================================"

# 1. Backup remote DB
Write-Host "`n[1/5] Backing up remote kp.db..."
Invoke-SshHelper backup "$RemoteDir/data/kp.db"

# 2. Upload ingest_xlsx.py
Write-Host "`n[2/5] Uploading webapp/ingest_xlsx.py..."
Invoke-SshHelper upload (Join-Path $webappDir "ingest_xlsx.py") "$RemoteDir/ingest_xlsx.py"

# 3. Upload kp.db
$localDb = Join-Path $webappDir "data\kp.db"
$dbSizeMB = [math]::Round((Get-Item $localDb).Length / 1MB, 1)
Write-Host "`n[3/5] Uploading kp.db ($dbSizeMB MB)..."
Invoke-SshHelper upload $localDb "$RemoteDir/data/kp.db"

# 4. Restart service (ubuntu user needs sudo; pipe password via echo + sudo -S)
Write-Host "`n[4/5] Restarting medical-audit.service (sudo)..."
$restartCmd = "echo `"$SshPass`" | sudo -S -p '' systemctl restart medical-audit.service && sleep 2 && systemctl is-active medical-audit.service"
Invoke-SshHelper exec $restartCmd

# 5. Healthcheck from inside CVM (catches gunicorn-boot failures)
Write-Host "`n[5/5] Healthcheck (from inside CVM)..."
Invoke-SshHelper healthcheck-remote $HealthcheckUrl

Write-Host "`n[done] Deploy batch 18 complete."
