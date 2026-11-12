<#
.SYNOPSIS
  Installs the standalone peek-a-foxy.exe for the current user. No administrator rights needed.

.DESCRIPTION
  Downloads peek-a-foxy.exe and its .sha256 from a GitHub release of paodelonga/peek-a-foxy,
  checks the file against that hash, copies it to a per-user folder and adds the folder to your
  user PATH. It runs nothing else: after it finishes, open a new terminal and run
  `peek-a-foxy install` (that command asks for administrator permission only for the two loader
  files it copies into Firefox's folder).

  The hash is published next to the program, so it catches a damaged or truncated download; it does
  not protect against a release that was itself replaced. Read the script and the release first if
  that matters to you.

.PARAMETER Version
  Release to install, such as 0.3.0. Default: the latest release.

.PARAMETER InstallDir
  Where to put peek-a-foxy.exe. Default: %LOCALAPPDATA%\Programs\peek-a-foxy.

.PARAMETER NoPath
  Do not touch the user PATH.

.EXAMPLE
  irm https://github.com/paodelonga/peek-a-foxy/releases/latest/download/install.ps1 | iex
#>
[CmdletBinding()]
param(
    [string]$Version = "latest",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\peek-a-foxy"),
    [switch]$NoPath
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repository = "https://github.com/paodelonga/peek-a-foxy/releases"
if ($Version -eq "latest") {
    $base = "$repository/latest/download"
} elseif ($Version -match '^v?(\d+\.\d+\.\d+(?:rc\d+)?)$') {
    $base = "$repository/download/v$($Matches[1])"
} else {
    throw "Version must look like 1.2.3 or 1.2.3rc1 (or be 'latest'), not '$Version'."
}

# The hash file is saved and then read as text. Invoke-WebRequest's own .Content is a byte array,
# not a string, whenever the server does not say the file is text (GitHub serves release assets as
# application/octet-stream), and a byte array turns into numbers instead of the hash.
function Read-PublishedHash([string]$Path) {
    if ([IO.FileInfo]::new($Path).Length -gt 1024) {
        throw "The published hash file is too large to be a SHA-256 value."
    }
    $text = Get-Content -Raw -LiteralPath $Path -Encoding UTF8  # nothing at all for an empty file
    $word = ""
    if ($text) { $word = @($text.Trim() -split '\s+')[0] }
    if ($word -notmatch '^[0-9a-fA-F]{64}$') { throw "The published hash file is not a SHA-256 value." }
    return $word
}

# The user PATH is the registry value HKCU\Environment\Path. It is read as the raw text, with the
# %VARIABLES% still unexpanded, and written back with the kind it had (REG_EXPAND_SZ for almost
# everybody), so entries such as %USERPROFILE%\bin stay variables. [Environment]::Get/Set-
# EnvironmentVariable would expand them for good and save the result as a plain string.
function Split-PathList([string]$List) {
    # A semicolon inside double quotes belongs to the entry (Windows allows "C:\a;b" in a PATH).
    $entries = [Collections.Generic.List[string]]::new()
    $current = [Text.StringBuilder]::new()
    $quoted = $false
    foreach ($char in $List.ToCharArray()) {
        if ($char -eq '"') { $quoted = -not $quoted }
        if ($char -eq ';' -and -not $quoted) {
            $entries.Add($current.ToString())
            [void]$current.Clear()
        } else {
            [void]$current.Append($char)
        }
    }
    $entries.Add($current.ToString())
    return $entries.ToArray()
}

function Get-PathKey([string]$Entry) {
    # What an entry points at, for comparing: no quotes, variables expanded, no trailing slash.
    $text = [Environment]::ExpandEnvironmentVariables($Entry.Trim().Trim('"').Trim())
    return $text.TrimEnd('\', '/')
}

function Get-PathWithEntry([string]$Raw, [string]$Directory) {
    # The value with $Directory added at the end, or $null when it is already an entry. Everything
    # that was there stays as it was; only the separator at the join is made right.
    $wanted = Get-PathKey $Directory
    foreach ($entry in (Split-PathList $Raw)) {
        $key = Get-PathKey $entry
        if ($key -and [string]::Equals($key, $wanted, [StringComparison]::OrdinalIgnoreCase)) {
            return $null
        }
    }
    $kept = $Raw.TrimEnd(';')
    if (-not $kept.Trim()) { return $Directory }
    return "$kept;$Directory"
}

function Add-UserPathEntry([string]$Directory, [string]$SubKey = "Environment") {
    # True when the folder was added, false when it was already in the PATH.
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($SubKey)
    try {
        $none = [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
        $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
        $raw = ""
        if ($key.GetValueNames() -contains "Path") {
            $kind = $key.GetValueKind("Path")
            if ($kind -ne "String" -and $kind -ne "ExpandString") {
                throw "The user PATH is not a text value in the registry, so it was left alone."
            }
            $raw = [string]$key.GetValue("Path", "", $none)
        }
        $updated = Get-PathWithEntry $raw $Directory
        if ($null -eq $updated) { return $false }
        $key.SetValue("Path", $updated, $kind)
        return $true
    } finally {
        $key.Dispose()
    }
}

function Send-EnvironmentChange {
    # Deleting a variable that does not exist changes nothing, but .NET announces the change to the
    # running programs (WM_SETTINGCHANGE), so a new terminal started from Explorer sees the PATH.
    try { [Environment]::SetEnvironmentVariable("PEEK_A_FOXY_NOTIFY", $null, "User") } catch { }
}

if (-not $NoPath -and $InstallDir -match '[%;"]') {
    # A % would be read as a variable in the PATH, and a ; or " would split or quote the entry.
    throw "The folder '$InstallDir' has a %, a ; or a double quote in its name, which cannot go in the PATH safely. Pick another folder or use -NoPath."
}

Write-Host "This will:"
Write-Host "  1. download peek-a-foxy.exe and peek-a-foxy.exe.sha256 from $base"
Write-Host "  2. check the file against the hash"
Write-Host "  3. copy it to $InstallDir"
if (-not $NoPath) { Write-Host "  4. add that folder to your user PATH" }
Write-Host "Nothing else is run and no administrator rights are used."
Write-Host ""

$temporary = Join-Path ([IO.Path]::GetTempPath()) ("peek-a-foxy-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $exe = Join-Path $temporary "peek-a-foxy.exe"
    Invoke-WebRequest -UseBasicParsing -Uri "$base/peek-a-foxy.exe" -OutFile $exe
    $hashFile = Join-Path $temporary "peek-a-foxy.exe.sha256"
    Invoke-WebRequest -UseBasicParsing -Uri "$base/peek-a-foxy.exe.sha256" -OutFile $hashFile
    $expected = Read-PublishedHash $hashFile
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash
    if ($actual -ne $expected.ToUpperInvariant()) {
        throw "The download does not match its published SHA-256 (got $actual, expected $expected). Nothing was installed."
    }

    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    $target = Join-Path $InstallDir "peek-a-foxy.exe"
    Copy-Item -LiteralPath $exe -Destination $target -Force
    Write-Host "Installed $target"

    if (-not $NoPath) {
        if (Add-UserPathEntry $InstallDir) {
            Send-EnvironmentChange
            Write-Host "Added $InstallDir to your user PATH."
        }
    }
    Write-Host ""
    Write-Host "Open a new terminal and run:  peek-a-foxy install"
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
