# Network Test Tool launcher for Windows (run without installing).
#
#   irm https://droltr.github.io/Network_Test_Tool/run.ps1 | iex
#
# What it does:
#   1. Finds the latest (or pinned) release of droltr/Network_Test_Tool on GitHub.
#   2. Downloads NetworkTestTool-<version>-windows-x86_64.exe into
#      %LOCALAPPDATA%\NetworkTestTool\bin\<tag>\ (reused on later runs).
#   3. Verifies its SHA-256 against the release's SHA256SUMS.txt.
#   4. Starts it. No admin rights, no registry writes, no PATH changes, no shortcuts.
#
# Optional environment variables:
#   NTT_VERSION=v0.8.1   Use this release tag instead of the latest release.
#   NTT_NO_LAUNCH=1      Download and verify only, do not start the app.
#   NTT_SKIP_HASH=1      Run even if the release has no SHA256SUMS.txt (not recommended).
#   NTT_SUMS_URL=<url>   Read checksums from this URL, file:// URI or local path (testing).
#
# Note: corporate endpoint protection (EDR, AppLocker, WDAC, Constrained Language Mode)
# may block "irm | iex" or the downloaded exe. In that case download the exe manually
# from https://github.com/droltr/Network_Test_Tool/releases/latest
#
# The whole script is one script block, so nothing it defines leaks into your session
# and an error never closes your PowerShell window. Keep this file ASCII-only.

& {
    $Repo = 'droltr/Network_Test_Tool'
    $ReleasesPage = "https://github.com/$Repo/releases/latest"
    $AssetPattern = '^NetworkTestTool-.+-windows-x86_64\.exe$'
    $SumsName = 'SHA256SUMS.txt'
    $KeepVersions = 2

    function Write-Step([string]$Text) { Write-Host "  $Text" }
    function Write-Fail([string]$Text) {
        Write-Host ''
        Write-Host "  ERROR: $Text" -ForegroundColor Red
        Write-Host "  Manual download: $ReleasesPage" -ForegroundColor Yellow
        Write-Host ''
    }
    function Test-Flag([string]$Name) {
        $v = [Environment]::GetEnvironmentVariable($Name)
        return ($v -and $v -notin @('0', 'false', 'no'))
    }
    function Get-FileSha256([string]$Path) {
        # Get-FileHash is missing in some locked-down hosts; use .NET directly.
        $stream = [IO.File]::OpenRead($Path)
        try {
            $sha = [Security.Cryptography.SHA256]::Create()
            try { $bytes = $sha.ComputeHash($stream) } finally { $sha.Dispose() }
        } finally { $stream.Dispose() }
        return (-join ($bytes | ForEach-Object { $_.ToString('x2') }))
    }
    function Get-ReleaseFromApi([string]$Tag) {
        $url = if ($Tag) { "https://api.github.com/repos/$Repo/releases/tags/$Tag" } else { "https://api.github.com/repos/$Repo/releases/latest" }
        $headers = @{ 'Accept' = 'application/vnd.github+json'; 'User-Agent' = 'NetworkTestTool-launcher' }
        return Invoke-RestMethod -Uri $url -Headers $headers -UseBasicParsing -TimeoutSec 30 -ErrorAction Stop
    }
    function Get-LatestTagFromRedirect {
        # github.com/<repo>/releases/latest redirects to .../releases/tag/<tag>.
        $req = [Net.WebRequest]::Create($ReleasesPage)
        $req.Method = 'HEAD'
        $req.UserAgent = 'NetworkTestTool-launcher'
        $req.Timeout = 30000
        $resp = $req.GetResponse()
        try { $final = $resp.ResponseUri.AbsoluteUri } finally { $resp.Close() }
        if ($final -match '/releases/tag/([^/?#]+)$') { return [Uri]::UnescapeDataString($Matches[1]) }
        throw "Could not read the latest release tag from $final"
    }
    function Get-RemoteText([string]$Url) {
        if ($Url -match '^file:' -or (Test-Path -LiteralPath $Url -PathType Leaf -ErrorAction SilentlyContinue)) {
            $path = if ($Url -match '^file:') { ([Uri]$Url).LocalPath } else { $Url }
            return [IO.File]::ReadAllText($path)
        }
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 60 -ErrorAction Stop
        if ($r.Content -is [byte[]]) { return [Text.Encoding]::UTF8.GetString($r.Content) }
        return [string]$r.Content
    }
    function Get-HttpStatus($ErrorRecord) {
        $resp = $ErrorRecord.Exception.Response
        if ($resp -and $resp.StatusCode) { return [int]$resp.StatusCode }
        return 0
    }

    $savedProgress = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with the progress bar in 5.1
    try {
        if ($PSVersionTable.PSEdition -ne 'Core' -or $IsWindows) {
            if (-not [Environment]::Is64BitOperatingSystem) {
                Write-Fail 'Network Test Tool needs 64-bit Windows.'
                return
            }
        } else {
            Write-Fail 'This launcher is for Windows. On Linux/macOS run: curl -fsSL https://droltr.github.io/Network_Test_Tool/run.sh | sh'
            return
        }
        if ($PSVersionTable.PSEdition -ne 'Core') {
            # Windows PowerShell 5.1 may default to TLS 1.0/1.1, which GitHub rejects.
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        }

        Write-Host ''
        Write-Host '  Network Test Tool launcher' -ForegroundColor Cyan

        # ---- 1. Resolve the release -------------------------------------------------
        $pinned = $env:NTT_VERSION
        if ($pinned -and $pinned -notmatch '^v') { $pinned = "v$pinned" }
        $tag = $null; $exeName = $null; $exeUrl = $null; $sumsUrl = $null; $apiDigest = $null; $apiSize = $null
        $label = if ($pinned) { "release $pinned" } else { 'the latest release' }
        Write-Step "Looking up $label on GitHub..."
        try {
            $rel = Get-ReleaseFromApi $pinned
            $tag = $rel.tag_name
            $asset = @($rel.assets | Where-Object { $_.name -match $AssetPattern }) | Select-Object -First 1
            if (-not $asset) {
                Write-Fail "Release $tag has no Windows x86_64 build."
                return
            }
            $exeName = $asset.name
            $exeUrl = $asset.browser_download_url
            $apiSize = [long]$asset.size
            if ($asset.PSObject.Properties['digest'] -and $asset.digest -match '^sha256:([0-9a-fA-F]{64})$') { $apiDigest = $Matches[1].ToLower() }
            $sumsAsset = @($rel.assets | Where-Object { $_.name -eq $SumsName }) | Select-Object -First 1
            if ($sumsAsset) { $sumsUrl = $sumsAsset.browser_download_url }
        } catch {
            $status = Get-HttpStatus $_
            if ($status -eq 404) {
                Write-Fail "Release '$pinned' was not found."
                return
            }
            # API blocked or rate limited (403/429): fall back to plain github.com URLs.
            Write-Step "GitHub API unavailable ($($_.Exception.Message.Trim())); using direct release links."
            try {
                $tag = if ($pinned) { $pinned } else { Get-LatestTagFromRedirect }
            } catch {
                Write-Fail "Cannot reach GitHub. Check your internet connection, proxy or firewall. ($($_.Exception.Message.Trim()))"
                return
            }
            $exeName = "NetworkTestTool-$($tag -replace '^v', '')-windows-x86_64.exe"
            $exeUrl = "https://github.com/$Repo/releases/download/$tag/$exeName"
            $sumsUrl = "https://github.com/$Repo/releases/download/$tag/$SumsName"
        }
        if ($env:NTT_SUMS_URL) { $sumsUrl = $env:NTT_SUMS_URL }
        Write-Step "Release: $tag ($exeName)"

        # ---- 2. Expected checksum ------------------------------------------------------
        $expected = $null
        if ($sumsUrl) {
            try {
                $sumsText = Get-RemoteText $sumsUrl
                foreach ($line in ($sumsText -split "`r?`n")) {
                    if ($line -match '^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$' -and $Matches[2] -eq $exeName) {
                        $expected = $Matches[1].ToLower()
                        break
                    }
                }
                if (-not $expected) {
                    Write-Fail "$SumsName of $tag has no entry for $exeName. Refusing to run an unverified file."
                    return
                }
            } catch {
                if ((Get-HttpStatus $_) -ne 404) {
                    Write-Fail "Could not download $SumsName ($($_.Exception.Message.Trim()))."
                    return
                }
            }
        }
        if (-not $expected) {
            if (Test-Flag 'NTT_SKIP_HASH') {
                Write-Host "  WARNING: $tag has no $SumsName; NTT_SKIP_HASH=1 is set, continuing without it." -ForegroundColor Yellow
            } else {
                Write-Fail ("Release $tag has no $SumsName, so the download cannot be verified. " +
                    'Wait for a newer release, download it manually, or set $env:NTT_SKIP_HASH=1 to run it unverified at your own risk.')
                return
            }
        }

        # ---- 3. Download (or reuse the cache) ---------------------------------------
        $baseDir = $env:LOCALAPPDATA
        if (-not $baseDir) { $baseDir = Join-Path $env:USERPROFILE 'AppData\Local' }
        $binDir = Join-Path $baseDir 'NetworkTestTool\bin'
        $verDir = Join-Path $binDir ($tag -replace '[^\w.\-]', '_')
        $exePath = Join-Path $verDir $exeName
        $null = New-Item -ItemType Directory -Path $verDir -Force

        # Every checksum we have (SHA256SUMS.txt and GitHub's asset digest) must match.
        $wants = @(@($expected, $apiDigest) | Where-Object { $_ })
        $testFile = {
            param([string]$Path)
            if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
            if ($wants.Count -eq 0) { return ((-not $apiSize) -or ((Get-Item -LiteralPath $Path).Length -eq $apiSize)) }
            $h = Get-FileSha256 $Path
            foreach ($w in $wants) { if ($h -ne $w) { return $false } }
            return $true
        }

        # Remove partial downloads left behind by interrupted runs.
        Get-ChildItem -LiteralPath $verDir -Filter '*.part' -File -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-1) } |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }

        if (& $testFile $exePath) {
            Write-Step 'Using the cached copy.'
        } else {
            # A unique temp name per run, so parallel runs never write into the same file.
            $part = Join-Path $verDir ("$exeName.$PID.$([IO.Path]::GetRandomFileName()).part")
            Write-Step 'Downloading (about 40 MB)...'
            try {
                Invoke-WebRequest -Uri $exeUrl -OutFile $part -UseBasicParsing -TimeoutSec 600 -ErrorAction Stop
            } catch {
                Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
                Write-Fail "Download failed: $($_.Exception.Message.Trim())"
                return
            }
            if ($wants.Count -gt 0) {
                $actual = Get-FileSha256 $part
                foreach ($want in $wants) {
                    if ($actual -ne $want) {
                        Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
                        Write-Fail "Checksum mismatch for $exeName (expected $want, got $actual). The file was deleted."
                        return
                    }
                }
                if ($expected) { Write-Step "SHA-256 verified against $SumsName." }
                else { Write-Step 'SHA-256 verified against the GitHub asset digest only.' }
            }
            # Move into place. [IO.File]::Move is atomic on the same volume and fails if the
            # target exists: then keep another run's file if it verifies, else replace it.
            $placed = $false
            for ($try = 0; $try -lt 3 -and -not $placed; $try++) {
                try {
                    [IO.File]::Move($part, $exePath)
                    $placed = $true
                } catch {
                    if (& $testFile $exePath) {
                        Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
                        $placed = $true
                    } else {
                        Remove-Item -LiteralPath $exePath -Force -ErrorAction SilentlyContinue
                    }
                }
            }
            if (-not $placed) {
                Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
                Write-Fail "Could not write $exePath (is an old copy still running?)."
                return
            }
        }
        (Get-Item -LiteralPath $verDir).LastWriteTime = Get-Date

        # ---- 4. Keep only the newest versions ---------------------------------------
        Get-ChildItem -LiteralPath $binDir -Directory -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -Skip $KeepVersions |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }

        # ---- 5. Launch -------------------------------------------------------------------
        # Check the final file once more right before using it.
        if (-not (& $testFile $exePath)) {
            Write-Fail "$exePath changed or failed verification just before launch. Run the command again."
            return
        }
        if (Test-Flag 'NTT_NO_LAUNCH') {
            Write-Step "NTT_NO_LAUNCH is set; not starting. File: $exePath"
            return
        }
        Write-Step 'Starting Network Test Tool...'
        Start-Process -FilePath $exePath -WorkingDirectory $verDir
        Write-Host ''
    } catch {
        Write-Fail "Unexpected error: $($_.Exception.Message)"
    } finally {
        $ProgressPreference = $savedProgress
    }
}
