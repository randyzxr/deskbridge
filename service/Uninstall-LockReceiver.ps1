#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$taskName = 'DeskBridgeLockReceiver'
$taskSc = Join-Path $env:SystemRoot 'System32\sc.exe'
$taskService = Get-Service -Name $taskName -ErrorAction SilentlyContinue
if ($taskService) {
    if ($taskService.Status -ne 'Stopped') { Stop-Service -Name $taskName; $taskService.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(10)) }
    & $taskSc 'delete' $taskName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Service removal failed ($LASTEXITCODE)." }
}
# No recursive deletion: private snapshot and binaries are retained for explicit
# review/cleanup, avoiding accidental loss of pairing keys or path traversal.
Write-Output 'Service removed. Original DeskBridge identity remains unchanged.'
Write-Output 'Protected DeskBridgeLockReceiver directories in Program Files and ProgramData are retained; review them before explicit cleanup/reinstall.'
