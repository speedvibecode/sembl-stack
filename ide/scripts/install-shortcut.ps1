# Creates the one-click entry points for Sembl Factory IDE:
#   - Desktop shortcut
#   - Start Menu shortcut
#   - optionally (-AutoStart) a Startup-folder shortcut that warms the backend at login
# Shortcuts target launch.vbs via wscript so no console window flashes.
param([switch]$AutoStart)
$ErrorActionPreference = 'Stop'

$scriptsDir = $PSScriptRoot
$ideRoot = Split-Path -Parent $scriptsDir
$vbs = Join-Path $scriptsDir 'launch.vbs'
$icon = Join-Path $ideRoot 'resources\sembl.ico'
if (-not (Test-Path $vbs)) { throw "launcher not found: $vbs" }

$shell = New-Object -ComObject WScript.Shell

function New-SemblShortcut([string]$lnkPath, [string]$args, [string]$desc) {
    $sc = $shell.CreateShortcut($lnkPath)
    $sc.TargetPath = "$env:WINDIR\System32\wscript.exe"
    $sc.Arguments = "`"$vbs`"$args"
    $sc.WorkingDirectory = $ideRoot
    if (Test-Path $icon) { $sc.IconLocation = "$icon,0" }
    $sc.Description = $desc
    $sc.Save()
    Write-Host "created $lnkPath"
}

$desktop = [Environment]::GetFolderPath('Desktop')
New-SemblShortcut (Join-Path $desktop 'Sembl Factory IDE.lnk') '' 'Open the Sembl Factory IDE'

$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Sembl Factory IDE.lnk'
New-SemblShortcut $startMenu '' 'Open the Sembl Factory IDE'

if ($AutoStart) {
    $startup = [Environment]::GetFolderPath('Startup')
    New-SemblShortcut (Join-Path $startup 'Sembl Factory IDE backend.lnk') ' -BackendOnly' 'Warm the Sembl Factory IDE backend at login'
}
