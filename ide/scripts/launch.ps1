# Sembl Factory IDE launcher.
# Idempotent: starts the compiled backend only if nothing is serving on the port,
# then opens a standalone app-mode browser window on it. Safe to double-click twice.
#
#   launch.ps1                start backend if needed + open a window
#   launch.ps1 -BackendOnly   just warm the backend (used by the login auto-start)
param(
    [int]$Port = 3000,
    [switch]$BackendOnly
)
$ErrorActionPreference = 'Stop'

$ideRoot = Split-Path -Parent $PSScriptRoot
$appDir = Join-Path $ideRoot 'browser-app'
$url = "http://127.0.0.1:$Port"

function Test-Backend {
    try {
        $r = Invoke-WebRequest -Uri "$url/" -UseBasicParsing -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Fail($msg) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($msg, 'Sembl Factory IDE', 'OK', 'Error') | Out-Null
    exit 1
}

if (-not (Test-Backend)) {
    $main = Join-Path $appDir 'lib\backend\main.js'
    if (-not (Test-Path $main)) {
        Fail "Backend bundle not found:`n$main`n`nBuild it first: npm run build:prod --workspace=browser-app (from ide/)"
    }
    $node = $null
    try { $node = (Get-Command node -ErrorAction Stop).Source } catch {}
    if (-not $node) { Fail 'node was not found on PATH.' }

    $logDir = Join-Path $env:LOCALAPPDATA 'sembl-ide'
    New-Item -ItemType Directory -Force $logDir | Out-Null
    Start-Process -FilePath $node `
        -ArgumentList "`"$main`" --port $Port --hostname 127.0.0.1 --plugins=local-dir:plugins" `
        -WorkingDirectory $appDir -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir 'backend.log') `
        -RedirectStandardError (Join-Path $logDir 'backend.err.log')

    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Backend) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        Fail "The IDE backend did not become ready on port $Port within 30s.`nSee $logDir\backend.err.log"
    }
}

if ($BackendOnly) { exit 0 }

# Open as a standalone app window (own taskbar entry, no browser chrome).
$browsers = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$browser = $browsers | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($browser) {
    Start-Process -FilePath $browser -ArgumentList "--app=$url"
} else {
    Start-Process $url   # plain default-browser tab as last resort
}
