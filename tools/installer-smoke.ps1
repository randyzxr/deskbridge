$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
$taskVersion = & $taskPython -c 'from deskbridge import __version__; print(__version__)'
$taskExisting = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{353672EC-5376-4B55-9B05-D7C52A06B6F2}_is1'
if (Test-Path -LiteralPath $taskExisting) { throw 'An installed DeskBridge already exists; do not replace it with a smoke test.' }
$taskDirectory = [IO.Path]::GetFullPath((Join-Path $taskRoot ('build\installer-smoke-' + [guid]::NewGuid().ToString('N'))))
$taskAllowed = [IO.Path]::GetFullPath((Join-Path $taskRoot 'build')) + [IO.Path]::DirectorySeparatorChar
if (-not $taskDirectory.StartsWith($taskAllowed, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected test installation directory' }
$taskInstaller = Join-Path $taskRoot "dist\DeskBridge-$taskVersion-windows-x64-setup.exe"
$taskInstalled = $false
try {
    $taskProcess = Start-Process -FilePath $taskInstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/SP-','/NORESTART','/NOCLOSEAPPLICATIONS','/NORESTARTAPPLICATIONS','/NOICONS','/TASKS=',('/DIR="' + $taskDirectory + '"')) -WindowStyle Hidden -Wait -PassThru
    if ($taskProcess.ExitCode -ne 0) { throw "Installation failed: $($taskProcess.ExitCode)" }
    $taskInstalled = $true
    $taskExe = Join-Path $taskDirectory 'DeskBridge.exe'
    & $taskPython (Join-Path $taskRoot 'tools\frozen_checks.py') $taskExe
    if ($LASTEXITCODE -ne 0) { throw 'Installed application failed its identity/core probe' }
    if (-not (Test-Path -LiteralPath (Join-Path $taskDirectory 'docs\quick-start.md'))) { throw 'Missing quick start' }
} finally {
    if ($taskInstalled) {
        $taskUninstaller = Join-Path $taskDirectory 'unins000.exe'
        if (-not ([IO.Path]::GetFullPath($taskUninstaller)).StartsWith($taskAllowed, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected uninstaller path' }
        $taskProcess = Start-Process -FilePath $taskUninstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -WindowStyle Hidden -Wait -PassThru
        if ($taskProcess.ExitCode -ne 0) { throw "Uninstall failed: $($taskProcess.ExitCode)" }
        if (Test-Path -LiteralPath (Join-Path $taskDirectory 'DeskBridge.exe')) { throw 'Installed executable remains after uninstall' }
        if (Test-Path -LiteralPath $taskExisting) { throw 'Test uninstall registration remains' }
    }
}
Write-Output 'PASS: per-user installer, installed executable identity/core probe, bundled quick start, and uninstall; no service installed'
