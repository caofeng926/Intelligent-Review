<#
.SYNOPSIS
  Upload local kp.db to a GitHub release as a binary asset so that the
  sync-db workflow can download and deploy it to the CVM.

.DESCRIPTION
  Why this exists:
    * webapp/data/kp.db is .gitignored (~373 MB), so the sync-db.yml
      workflow cannot read it from the runner working tree.
    * We sidestep this by uploading the DB to a GitHub release as a
      binary asset, and the workflow downloads it via curl.

  Flow:
    1. (Optionally) deletes any existing release with the same tag
    2. Creates a new release with the given tag
    3. Uploads kp.db as a release asset
    4. (If -Trigger is set) triggers the sync-db workflow
    5. Prints the workflow run URL for monitoring

  PAT scope required: public_repo (or full repo) plus workflow (if -Trigger).

.PARAMETER Pat
  GitHub Personal Access Token. If omitted, the script prompts for it
  (typed input is masked). The token is held in a local string variable
  and overwritten with spaces at end of script.

.PARAMETER Tag
  Release tag. Default: kp-db-latest. If a release with this tag already
  exists, it is deleted and recreated for a clean re-upload.

.PARAMETER DbPath
  Path to kp.db. Default: webapp/data/kp.db (relative to project root).

.PARAMETER Repo
  GitHub repo (owner/name). Default: caofeng926/Intelligent-Review.

.PARAMETER Trigger
  If set, also triggers the sync-db workflow after upload and prints
  the run URL. Requires workflow PAT scope.

.EXAMPLE
  # One-shot: prompts for PAT, uploads, then triggers sync-db
  .\scripts\upload_kp_db_to_release.ps1 -Trigger

.EXAMPLE
  # Pass PAT inline (less secure -- visible in shell history)
  .\scripts\upload_kp_db_to_release.ps1 -Pat ghp_xxxxxxx -Trigger
#>
[CmdletBinding()]
param(
    [string] $Pat,

    [string] $Tag = 'kp-db-latest',

    [string] $DbPath = 'webapp/data/kp.db',

    [string] $Repo = 'caofeng926/Intelligent-Review',

    [switch] $Trigger
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

# Prompt for PAT if not provided (use Marshal instead of ConvertFrom-SecureString -AsPlainText
# to stay compatible with Windows PowerShell 5.1)
if ([string]::IsNullOrWhiteSpace($Pat)) {
    $secure = Read-Host "GitHub PAT (public_repo + workflow scopes)" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $Pat = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}
if ([string]::IsNullOrWhiteSpace($Pat)) {
    throw "PAT is required"
}

# Resolve DB path
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dbFull = if ([System.IO.Path]::IsPathRooted($DbPath)) { $DbPath } else { Join-Path $projectRoot $DbPath }
if (-not (Test-Path $dbFull)) {
    throw "kp.db not found at: $dbFull"
}
$dbSize = (Get-Item $dbFull).Length
$dbSizeMb = [math]::Round($dbSize / 1MB, 1)
Write-Host "DB:      $dbFull ($dbSizeMb MB)"
Write-Host "Repo:    $Repo"
Write-Host "Tag:     $Tag"
Write-Host "Trigger: $Trigger"

$apiBase = "https://api.github.com/repos/$Repo"
$hdrJson = @{ Authorization = "Bearer $Pat"; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
$hdrBin  = @{ Authorization = "Bearer $Pat"; Accept = 'application/vnd.github+json'; 'Content-Type' = 'application/octet-stream' }

try {
    # 1. Check if release with this tag already exists
    Write-Host "`n[1/4] Checking if release '$Tag' exists..."
    $existing = $null
    try {
        $existing = Invoke-RestMethod -Uri "$apiBase/releases/tags/$Tag" -Headers $hdrJson -Method Get
    } catch {
        if ($_.Exception.Response.StatusCode -ne 404) { throw }
    }
    if ($existing) {
        Write-Host "  found existing release id=$($existing.id) -- deleting for clean re-upload"
        Invoke-RestMethod -Uri "$apiBase/releases/$($existing.id)" -Headers $hdrJson -Method Delete | Out-Null
    }

    # 2. Create new release
    Write-Host "[2/4] Creating release '$Tag'..."
    $body = @{
        tag_name               = $Tag
        target_commitish       = 'main'
        name                   = "kp.db snapshot $Tag"
        body                   = "Automated kp.db upload.`nSize: $dbSizeMb MB`nDate: $(Get-Date -Format 'u')"
        draft                  = $false
        prerelease             = $true
        generate_release_notes = $false
    } | ConvertTo-Json -Depth 5
    $release = Invoke-RestMethod -Uri "$apiBase/releases" -Headers $hdrJson -Method Post -Body $body -ContentType 'application/json'
    Write-Host "  created id=$($release.id) url=$($release.html_url)"

    # 3. Upload kp.db as asset (GitHub supports up to 2 GB)
    Write-Host "[3/4] Uploading kp.db ($dbSizeMb MB)... this can take a while on slow links"
    $uploadUrl = $release.upload_url -replace '\{.*\}$', ''
    # NB: use + for concatenation; "$uploadUrl?name" gets parsed as a nullable variable scope in PS
    $assetUrl = $uploadUrl + '?name=kp.db'
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        Invoke-RestMethod -Uri $assetUrl -Headers $hdrBin -Method Post -InFile $dbFull -ContentType 'application/octet-stream' | Out-Null
    } catch {
        Write-Error "Upload failed: $_"
        throw
    }
    $sw.Stop()
    $mbps = [math]::Round(($dbSize / 1MB) / [math]::Max($sw.Elapsed.TotalSeconds, 1), 2)
    Write-Host ("  upload done in {0:N1}s ({1} MB/s)" -f $sw.Elapsed.TotalSeconds, $mbps)

    # 4. Verify
    Write-Host "[4/4] Verifying..."
    $assets = Invoke-RestMethod -Uri "$apiBase/releases/$($release.id)/assets" -Headers $hdrJson -Method Get
    $kpAsset = $assets | Where-Object { $_.name -eq 'kp.db' } | Select-Object -First 1
    if (-not $kpAsset) {
        throw "kp.db asset not found on release"
    }
    Write-Host "  kp.db asset: $($kpAsset.browser_download_url) ($([math]::Round($kpAsset.size/1MB,1)) MB)"

    # 5. Optionally trigger sync-db workflow
    if ($Trigger) {
        Write-Host "`n[5/5] Triggering sync-db workflow..."
        $dispBody = @{ ref = 'main'; inputs = @{ release_tag = $Tag } } | ConvertTo-Json -Depth 5
        try {
            Invoke-RestMethod -Uri "$apiBase/actions/workflows/sync-db.yml/dispatches" -Headers $hdrJson -Method Post -Body $dispBody -ContentType 'application/json' | Out-Null
        } catch {
            Write-Warning "Trigger failed (you can still trigger manually): $_"
        }
        Write-Host "  trigger accepted. Monitor at:"
        Write-Host "    https://github.com/$Repo/actions/workflows/sync-db.yml"
    } else {
        Write-Host "`nDone. Now trigger the sync-db workflow manually:"
        Write-Host "  https://github.com/$Repo/actions/workflows/sync-db.yml"
        Write-Host "  Tag: $Tag (default)"
    }
} finally {
    # Best-effort PAT scrub
    $Pat = ' ' * $Pat.Length
}