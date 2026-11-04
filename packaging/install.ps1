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
} elseif ($Version -match '^v?(\d+\.\d+\.\d+)$') {
    $base = "$repository/download/v$($Matches[1])"
} else {
    throw "Version must look like 1.2.3 (or be 'latest'), not '$Version'."
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
    $line = (Invoke-WebRequest -UseBasicParsing -Uri "$base/peek-a-foxy.exe.sha256").Content
    $expected = ([Text.Encoding]::UTF8.GetString([Text.Encoding]::UTF8.GetBytes([string]$line))).Trim().Split()[0]
    if ($expected -notmatch '^[0-9a-fA-F]{64}$') { throw "The published hash file is not a SHA-256 value." }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash
    if ($actual -ne $expected.ToUpperInvariant()) {
        throw "The download does not match its published SHA-256 (got $actual, expected $expected). Nothing was installed."
    }

    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    $target = Join-Path $InstallDir "peek-a-foxy.exe"
    Copy-Item -LiteralPath $exe -Destination $target -Force
    Write-Host "Installed $target"

    if (-not $NoPath) {
        $current = [Environment]::GetEnvironmentVariable("Path", "User")
        $entries = @(); if ($current) { $entries = $current.Split(";") | Where-Object { $_ } }
        if ($entries -notcontains $InstallDir) {
            [Environment]::SetEnvironmentVariable("Path", (($entries + $InstallDir) -join ";"), "User")
            Write-Host "Added $InstallDir to your user PATH."
        }
    }
    Write-Host ""
    Write-Host "Open a new terminal and run:  peek-a-foxy install"
    Write-Host "(it needs Git for Windows: winget install Git.Git)"
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
