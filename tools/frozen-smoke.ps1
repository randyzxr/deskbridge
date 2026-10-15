$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskVersion = & (Join-Path $taskRoot '.venv\Scripts\python.exe') -c 'from deskbridge import __version__; print(__version__)'
$taskExe = Join-Path $taskRoot "dist\$taskVersion\DeskBridge\DeskBridge.exe"
$taskProfile = Join-Path $taskRoot ('build\frozen-smoke-' + [guid]::NewGuid().ToString('N'))
$taskArgs = @('--profile', ('"' + $taskProfile + '"'))
$taskProcess = Start-Process -FilePath $taskExe -ArgumentList $taskArgs -WindowStyle Hidden -PassThru
try {
    if ($taskProcess.WaitForExit(2500)) { throw "Frozen GUI exited early: $($taskProcess.ExitCode)" }
    $taskIdentity = Join-Path $taskProfile 'tls\deskbridge.pem'
    if (-not (Test-Path -LiteralPath $taskIdentity)) { throw 'Frozen application did not initialize its isolated identity' }
    $taskProcess.Refresh()
    # A user's close button now hides to tray. End only this isolated smoke-test
    # process; normal tray cleanup is verified separately by tray_smoke.py.
    $taskProcess.Kill()
    if (-not $taskProcess.WaitForExit(5000)) { throw 'Frozen GUI did not terminate' }
    Write-Output 'PASS: Windows frozen GUI starts without project Python and initializes its isolated identity.'
} finally {
    if (-not $taskProcess.HasExited) { $taskProcess.Kill() }
    $taskProcess.Dispose()
}
